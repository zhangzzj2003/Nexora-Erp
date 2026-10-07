"""采购退货单：以原入库行为来源，确认后追加负向库存流水。"""

from app.core.document_responses import NumberedRoute
from sqlalchemy import select, update, func, literal, and_, or_
from sqlalchemy.orm import Session, aliased
from sqlalchemy.engine import RowMapping
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.core.orm import orm_session, add_model
from app.core.models import (
    Material,
    PurchaseOrderLine,
    PurchaseReturn,
    PurchaseReturnLine,
    PurchaseReturnReversal,
    Receipt,
    ReceiptLine,
    ReceiptOrderLink,
    ReceiptReversal,
    ReceiptWarehouse,
    StockMovement,
    Supplier,
    User,
    Warehouse,
    WarehouseOutbound,
    WarehouseOutboundLine,
    PhysicalLotAllocation,
)
from app.inventory.warehouse import balance
from app.inventory.physical_lots import LotPart, post_lot_movement
from app.access.security import require

UserRu = aliased(User)
UserU = aliased(User)

router = APIRouter(route_class=NumberedRoute, prefix="/api/v1")


class PurchaseReturnLineInput(BaseModel):
    receipt_line_id: int = Field(gt=0)
    quantity: Decimal

    @field_validator("quantity")
    @classmethod
    def valid_quantity(cls, value: Decimal) -> Decimal:
        # 与入库一致的三位精度，避免退货累计时出现不可核对的尾差。
        if not value.is_finite() or value <= 0 or value > 1_000_000 or value.as_tuple().exponent < -3:
            raise ValueError("退货数量须大于零、最多三位小数且不超过一百万")
        return value


class PurchaseReturnInput(BaseModel):
    receipt_id: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=200)
    lines: list[PurchaseReturnLineInput] = Field(min_length=1, max_length=100)

    @field_validator("reason")
    @classmethod
    def trim_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("退货原因不能为空")
        return value.strip()


class PurchaseReturnReverseInput(BaseModel):
    reason: str = Field(min_length=1, max_length=200)

    @field_validator("reason")
    @classmethod
    def trim_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("冲销原因不能为空")
        return value.strip()


def returned_quantity(
    db: Session, receipt_line_id: int, exclude_return_id: int | None = None, include_pending: bool = False
) -> Decimal:
    # 已冲销退货保留历史，但不再减少原入库的净收货数量。
    return sum(
        (
            Decimal(row)
            for row in db.scalars(
                select(PurchaseReturnLine.quantity)
                .select_from(PurchaseReturnLine)
                .join(PurchaseReturn, PurchaseReturn.id == PurchaseReturnLine.purchase_return_id)
                .outerjoin(
                    PurchaseReturnReversal, PurchaseReturnReversal.purchase_return_id == PurchaseReturn.id
                )
                .outerjoin(WarehouseOutbound, WarehouseOutbound.purchase_return_id == PurchaseReturn.id)
                .where(
                    PurchaseReturnLine.receipt_line_id == receipt_line_id,
                    PurchaseReturn.id != func.coalesce(exclude_return_id, -1),
                    or_(
                        PurchaseReturn.status == "posted",
                        and_(
                            and_(int(include_pending) == 1, PurchaseReturn.status == "draft"),
                            WarehouseOutbound.status == "draft",
                        ),
                    ),
                    PurchaseReturnReversal.id.is_(None),
                )
            )
        ),
        Decimal(0),
    )


def checked_return_lines(
    db: Session, receipt_id: int, lines: list[tuple[int, Decimal]], exclude_return_id: int | None = None
) -> dict[int, RowMapping]:
    receipt = (
        db.execute(select(Receipt.status).select_from(Receipt).where((Receipt.id == receipt_id)))
        .mappings()
        .first()
    )
    if not receipt:
        raise HTTPException(422, "原入库单不存在")
    if receipt["status"] != "posted":
        raise HTTPException(409, "只有已确认入库单可退货")
    if (
        db.execute(
            select(literal(1)).select_from(ReceiptReversal).where((ReceiptReversal.receipt_id == receipt_id))
        )
        .mappings()
        .first()
    ):
        raise HTTPException(409, "原入库单已冲销，不能退货")
    known = {
        row["id"]: row
        for row in db.execute(
            select(ReceiptLine.id, ReceiptLine.material_id, ReceiptLine.quantity)
            .select_from(ReceiptLine)
            .where((ReceiptLine.receipt_id == receipt_id))
        ).mappings()
    }
    result: dict[int, RowMapping] = {}
    for line_id, quantity in lines:
        item = known.get(line_id)
        if not item:
            raise HTTPException(422, "退货明细不属于原入库单")
        if quantity > Decimal(item["quantity"]) - returned_quantity(
            db, line_id, exclude_return_id, include_pending=True
        ):
            raise HTTPException(409, f"入库明细 #{line_id} 超出可退数量")
        result[line_id] = item
    return result


def purchase_return_data(db: Session, return_id: int) -> dict:
    row = (
        db.execute(
            select(
                PurchaseReturn.id,
                PurchaseReturn.receipt_id,
                PurchaseReturn.reason,
                PurchaseReturn.status,
                PurchaseReturn.created_by,
                PurchaseReturn.posted_by,
                PurchaseReturn.cancelled_by,
                PurchaseReturn.created_at,
                PurchaseReturn.posted_at,
                PurchaseReturn.cancelled_at,
                Receipt.supplier_id,
                Supplier.name.label("supplier_name"),
                ReceiptWarehouse.warehouse_id,
                Warehouse.name.label("warehouse_name"),
                UserU.username.label("created_by_name"),
                PurchaseReturnReversal.id.label("reversal_id"),
                PurchaseReturnReversal.reason.label("reversal_reason"),
                PurchaseReturnReversal.created_by.label("reversed_by"),
                UserRu.username.label("reversed_by_name"),
                PurchaseReturnReversal.created_at.label("reversed_at"),
                WarehouseOutbound.id.label("outbound_id"),
                WarehouseOutbound.status.label("outbound_status"),
            )
            .select_from(PurchaseReturn)
            .join(Receipt, (Receipt.id == PurchaseReturn.receipt_id))
            .join(Supplier, (Supplier.id == Receipt.supplier_id))
            .join(ReceiptWarehouse, (ReceiptWarehouse.receipt_id == Receipt.id))
            .join(Warehouse, (Warehouse.id == ReceiptWarehouse.warehouse_id))
            .join(UserU, (UserU.id == PurchaseReturn.created_by))
            .outerjoin(
                PurchaseReturnReversal, (PurchaseReturnReversal.purchase_return_id == PurchaseReturn.id)
            )
            .outerjoin(WarehouseOutbound, (WarehouseOutbound.purchase_return_id == PurchaseReturn.id))
            .outerjoin(UserRu, (UserRu.id == PurchaseReturnReversal.created_by))
            .where((PurchaseReturn.id == return_id))
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(404, "采购退货单不存在")
    lines = []
    total = Decimal(0)
    priced = True
    for item in db.execute(
        select(
            PurchaseReturnLine.id,
            PurchaseReturnLine.receipt_line_id,
            ReceiptLine.material_id,
            Material.sku,
            Material.name.label("material_name"),
            Material.unit,
            PurchaseReturnLine.quantity,
            PurchaseOrderLine.unit_price,
        )
        .select_from(PurchaseReturnLine)
        .join(ReceiptLine, (ReceiptLine.id == PurchaseReturnLine.receipt_line_id))
        .join(Material, (Material.id == ReceiptLine.material_id))
        .outerjoin(ReceiptOrderLink, (ReceiptOrderLink.receipt_line_id == ReceiptLine.id))
        .outerjoin(PurchaseOrderLine, (PurchaseOrderLine.id == ReceiptOrderLink.purchase_order_line_id))
        .where((PurchaseReturnLine.purchase_return_id == return_id))
        .order_by(PurchaseReturnLine.id)
    ).mappings():
        price = item["unit_price"]
        line_total = None
        if price is not None:
            line_total = (Decimal(item["quantity"]) * Decimal(price)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            total += line_total
        else:
            # 历史自由入库无采购单价，金额保持未知，不能伪造为零元。
            priced = False
        lines.append({**dict(item), "line_total": str(line_total) if line_total is not None else None})
    return {**dict(row), "lines": lines, "total_amount": str(total) if priced else None}


@router.get("/purchase-returns")
def list_purchase_returns(_: dict = Depends(require("inventory.view"))) -> list[dict]:
    with orm_session() as db:
        ids = [
            row
            for row in db.scalars(
                select(PurchaseReturn.id).select_from(PurchaseReturn).order_by(PurchaseReturn.id.desc())
            )
        ]
        return [purchase_return_data(db, return_id) for return_id in ids]


@router.post("/purchase-returns", status_code=201)
def create_purchase_return(
    payload: PurchaseReturnInput, user: dict = Depends(require("purchase_return.create"))
) -> dict:
    if len({line.receipt_line_id for line in payload.lines}) != len(payload.lines):
        raise HTTPException(422, "一张退货单不能重复选择同一入库明细")
    with orm_session(write=True) as db:
        checked_return_lines(
            db, payload.receipt_id, [(line.receipt_line_id, line.quantity) for line in payload.lines]
        )
        cursor = add_model(
            db, PurchaseReturn(receipt_id=payload.receipt_id, reason=payload.reason, created_by=user["id"])
        )
        db.add_all(
            [
                PurchaseReturnLine(
                    purchase_return_id=cursor.id,
                    receipt_line_id=line.receipt_line_id,
                    quantity=str(line.quantity),
                )
                for line in payload.lines
            ]
        )
        return purchase_return_data(db, cursor.id)


def submit_return_in_transaction(db: Session, return_id: int) -> int:
    # 同一退货只对应一张待出库单；提交时预留可退量，确认时再次检查。
    row = (
        db.execute(
            select(
                PurchaseReturn.id,
                PurchaseReturn.receipt_id,
                PurchaseReturn.reason,
                PurchaseReturn.status,
                PurchaseReturn.created_by,
                PurchaseReturn.posted_by,
                PurchaseReturn.cancelled_by,
                PurchaseReturn.created_at,
                PurchaseReturn.posted_at,
                PurchaseReturn.cancelled_at,
            )
            .select_from(PurchaseReturn)
            .where((PurchaseReturn.id == return_id))
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(404, "采购退货单不存在")
    if row["status"] != "draft":
        raise HTTPException(409, "此采购退货单已处理")
    if (
        db.execute(
            select(literal(1))
            .select_from(WarehouseOutbound)
            .where((WarehouseOutbound.purchase_return_id == return_id))
        )
        .mappings()
        .first()
    ):
        raise HTTPException(409, "退货已提交，不能重复生成出库单")
    lines = (
        db.execute(
            select(PurchaseReturnLine.receipt_line_id, PurchaseReturnLine.quantity, ReceiptLine.material_id)
            .select_from(PurchaseReturnLine)
            .join(ReceiptLine, (ReceiptLine.id == PurchaseReturnLine.receipt_line_id))
            .where((PurchaseReturnLine.purchase_return_id == return_id))
        )
        .mappings()
        .all()
    )
    checked_return_lines(
        db, row["receipt_id"], [(line["receipt_line_id"], Decimal(line["quantity"])) for line in lines]
    )
    warehouse_id = db.scalar(
        select(ReceiptWarehouse.warehouse_id)
        .select_from(ReceiptWarehouse)
        .where(ReceiptWarehouse.receipt_id == row["receipt_id"])
    )
    outbound_id = add_model(
        db,
        WarehouseOutbound(
            warehouse_id=warehouse_id,
            source_kind="purchase_return",
            reason="purchase_return",
            note=row["reason"],
            reference=f"采购退货 #{return_id}",
            created_by=row["created_by"],
            purchase_return_id=return_id,
        ),
    ).id
    db.add_all(
        [
            WarehouseOutboundLine(
                outbound_id=outbound_id, material_id=line["material_id"], quantity=line["quantity"]
            )
            for line in lines
        ]
    )
    return outbound_id


def post_return_in_transaction(db: Session, return_id: int, actor_id: int,
                               lot_lines: dict[int, list[LotPart]] | None = None) -> dict:
    # 必须持有 BEGIN IMMEDIATE 写锁；重查原入库可退量和原仓库余额。
    row = (
        db.execute(
            select(
                PurchaseReturn.id,
                PurchaseReturn.receipt_id,
                PurchaseReturn.reason,
                PurchaseReturn.status,
                PurchaseReturn.created_by,
                PurchaseReturn.posted_by,
                PurchaseReturn.cancelled_by,
                PurchaseReturn.created_at,
                PurchaseReturn.posted_at,
                PurchaseReturn.cancelled_at,
            )
            .select_from(PurchaseReturn)
            .where((PurchaseReturn.id == return_id))
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(404, "采购退货单不存在")
    if row["status"] != "draft":
        raise HTTPException(409, "此采购退货单已处理")
    outbound = (
        db.execute(
            select(WarehouseOutbound.id, WarehouseOutbound.status, WarehouseOutbound.warehouse_id)
            .select_from(WarehouseOutbound)
            .where((WarehouseOutbound.purchase_return_id == return_id))
        )
        .mappings()
        .first()
    )
    if not outbound:
        outbound_id = submit_return_in_transaction(db, return_id)
        outbound = (
            db.execute(
                select(WarehouseOutbound.id, WarehouseOutbound.status, WarehouseOutbound.warehouse_id)
                .select_from(WarehouseOutbound)
                .where((WarehouseOutbound.id == outbound_id))
            )
            .mappings()
            .first()
        )
    if outbound["status"] != "draft":
        raise HTTPException(409, "关联出库单已处理")
    lines = (
        db.execute(
            select(PurchaseReturnLine.id, PurchaseReturnLine.receipt_line_id, PurchaseReturnLine.quantity)
            .select_from(PurchaseReturnLine)
            .where((PurchaseReturnLine.purchase_return_id == return_id))
        )
        .mappings()
        .all()
    )
    source = checked_return_lines(
        db,
        row["receipt_id"],
        [(line["receipt_line_id"], Decimal(line["quantity"])) for line in lines],
        exclude_return_id=return_id,
    )
    if lot_lines is not None and set(lot_lines) != {
            source[line['receipt_line_id']]['material_id'] for line in lines}:
        raise HTTPException(422, '批次明细必须与采购退货明细逐行对应')
    for line in lines:
        material_id = source[line["receipt_line_id"]]["material_id"]
        quantity = Decimal(line["quantity"])
        if balance(db, outbound["warehouse_id"], material_id) < quantity:
            raise HTTPException(409, f"物料 #{material_id} 在原入库仓库库存不足；请先调回原仓库")
        movement = StockMovement(
                warehouse_id=outbound["warehouse_id"],
                material_id=material_id,
                quantity=str(-quantity),
                source_type="purchase_return",
                source_id=return_id,
                source_line_id=line["id"],
                created_by=actor_id,
            )
        if lot_lines is None:
            db.add(movement)
        else:
            post_lot_movement(db, movement, lot_lines[material_id])
    db.execute(
        update(PurchaseReturn)
        .where((PurchaseReturn.id == return_id))
        .values(status="posted", posted_by=actor_id, posted_at=func.current_timestamp())
    )
    db.execute(
        update(WarehouseOutbound)
        .where((WarehouseOutbound.id == outbound["id"]))
        .values(status="posted", posted_by=actor_id, posted_at=func.current_timestamp())
    )
    return purchase_return_data(db, return_id)


@router.post("/purchase-returns/{return_id}/submit")
def submit_purchase_return(return_id: int, user: dict = Depends(require("purchase_return.submit"))) -> dict:
    with orm_session(write=True) as db:
        submit_return_in_transaction(db, return_id)
        return purchase_return_data(db, return_id)


@router.post("/purchase-returns/{return_id}/post")
def post_purchase_return(return_id: int, user: dict = Depends(require("purchase_return.post"))) -> dict:
    # 兼容旧客户端：直接确认会在同一事务补建并确认关联出库单。
    with orm_session(write=True) as db:
        return post_return_in_transaction(db, return_id, user["id"])


@router.post("/purchase-returns/{return_id}/cancel")
def cancel_purchase_return(return_id: int, user: dict = Depends(require("purchase_return.cancel"))) -> dict:
    with orm_session(write=True) as db:
        row = (
            db.execute(
                select(PurchaseReturn.status)
                .select_from(PurchaseReturn)
                .where((PurchaseReturn.id == return_id))
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "采购退货单不存在")
        if row["status"] != "draft":
            raise HTTPException(409, "只有退货草稿可取消；已确认退货须另建更正单")
        db.execute(
            update(WarehouseOutbound)
            .where(WarehouseOutbound.purchase_return_id == return_id, WarehouseOutbound.status == "draft")
            .values(status="cancelled", cancelled_by=user["id"], cancelled_at=func.current_timestamp())
        )
        db.execute(
            update(PurchaseReturn)
            .where((PurchaseReturn.id == return_id))
            .values(status="cancelled", cancelled_by=user["id"], cancelled_at=func.current_timestamp())
        )
        return purchase_return_data(db, return_id)


@router.post("/purchase-returns/{return_id}/reverse", status_code=201)
def reverse_purchase_return(
    return_id: int,
    payload: PurchaseReturnReverseInput,
    user: dict = Depends(require("purchase_return.reverse")),
) -> dict:
    with orm_session(write=True) as db:
        # 一张已确认退货仅允许一次全量冲销；正向流水与冲销记录同事务提交。
        row = (
            db.execute(
                select(PurchaseReturn.status, ReceiptWarehouse.warehouse_id)
                .select_from(PurchaseReturn)
                .join(ReceiptWarehouse, (ReceiptWarehouse.receipt_id == PurchaseReturn.receipt_id))
                .where((PurchaseReturn.id == return_id))
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "采购退货单不存在")
        if row["status"] != "posted":
            raise HTTPException(409, "只有已确认采购退货可冲销")
        if (
            db.execute(
                select(literal(1))
                .select_from(PurchaseReturnReversal)
                .where((PurchaseReturnReversal.purchase_return_id == return_id))
            )
            .mappings()
            .first()
        ):
            raise HTTPException(409, "此采购退货单已冲销")
        lines = (
            db.execute(
                select(PurchaseReturnLine.id, PurchaseReturnLine.quantity, ReceiptLine.material_id)
                .select_from(PurchaseReturnLine)
                .join(ReceiptLine, (ReceiptLine.id == PurchaseReturnLine.receipt_line_id))
                .where((PurchaseReturnLine.purchase_return_id == return_id))
            )
            .mappings()
            .all()
        )
        cursor = add_model(
            db,
            PurchaseReturnReversal(
                purchase_return_id=return_id, reason=payload.reason, created_by=user["id"]
            ),
        )
        for line in lines:
            # 采购退货的反向实物回到原入库仓库，来源行仍指向原退货明细。
            movement = StockMovement(
                    warehouse_id=row["warehouse_id"],
                    material_id=line["material_id"],
                    quantity=line["quantity"],
                    source_type="purchase_return_reversal",
                    source_id=cursor.id,
                    source_line_id=line["id"],
                    created_by=user["id"],
                )
            allocations = list(db.scalars(
                select(PhysicalLotAllocation)
                .join(StockMovement, StockMovement.id == PhysicalLotAllocation.movement_id)
                .where(StockMovement.source_type == 'purchase_return',
                       StockMovement.source_id == return_id,
                       StockMovement.source_line_id == line['id'])
                .order_by(PhysicalLotAllocation.id)))
            if allocations:
                if sum((Decimal(part.quantity) for part in allocations), Decimal(0)) != -Decimal(line['quantity']):
                    raise HTTPException(409, '原采购退货批次分配不完整，无法冲销')
                post_lot_movement(db, movement, [LotPart(
                    part.lot_id, -Decimal(part.quantity), part.id) for part in allocations])
            else:
                db.add(movement)
        return purchase_return_data(db, return_id)
