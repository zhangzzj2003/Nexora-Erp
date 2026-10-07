"""采购入库单及冲销接口。"""

from app.core.document_responses import NumberedRoute
# 审批核对与原业务写入共用一个事务，旧客户端也不能跳过批准直接执行。
from app.core import document_approval as approval
from app.core.approval_documents import receipt_snapshot, document_snapshot
from sqlalchemy import select, update, func, literal
from sqlalchemy.orm import Session, aliased
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.access.security import require
from app.core.orm import orm_session, add_model
from app.core.models import (
    Material,
    PhysicalLot,
    PhysicalLotAllocation,
    PurchaseGoodsReceipt,
    Receipt,
    ReceiptLine,
    ReceiptOrderLink,
    ReceiptReversal,
    ReceiptWarehouse,
    StockMovement,
    Supplier,
    User,
    Warehouse,
)
from app.inventory.warehouse import balance, require_warehouse
from app.inventory.physical_lots import LotPart, post_lot_movement
from app.inventory.lot_inputs import PhysicalLotPartInput
from app.purchase.orders import (
    linked_order_for_receipt,
    order_receipt_lines,
    update_order_receipt_status,
    validate_receipt_post,
)
from app.purchase.returns import returned_quantity as purchase_returned_quantity

UserRu = aliased(User)
UserU = aliased(User)

router = APIRouter(route_class=NumberedRoute, prefix="/api/v1")


class ReceiptLineInput(BaseModel):
    material_id: int = Field(gt=0)
    quantity: Decimal

    @field_validator("quantity")
    @classmethod
    def valid_quantity(cls, value: Decimal) -> Decimal:
        # 用十进制字符串保存数量，避免浮点数改变库存精度。
        if not value.is_finite() or value <= 0 or value > 1_000_000 or value.as_tuple().exponent < -3:
            raise ValueError("数量须大于零、最多三位小数且不超过一百万")
        return value


class ReceiptInput(BaseModel):
    supplier_id: int = Field(gt=0)
    # 老客户端省略仓库时继续入主仓库；新客户端必须让用户明确选择。
    warehouse_id: int = Field(default=1, gt=0)
    purchase_order_id: int | None = Field(default=None, gt=0)
    reference: str = Field(default="", max_length=100)
    lines: list[ReceiptLineInput] = Field(min_length=1, max_length=100)


class ReceiptReverseInput(BaseModel):
    reason: str = Field(min_length=1, max_length=200)

    @field_validator("reason")
    @classmethod
    def trim_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("冲销原因不能为空")
        return value.strip()


class ReceiptLotLineInput(BaseModel):
    receipt_line_id: int = Field(gt=0)
    lots: list[PhysicalLotPartInput] = Field(min_length=1, max_length=20)


class ReceiptPostInput(BaseModel):
    lines: list[ReceiptLotLineInput] = Field(min_length=1, max_length=100)


def receipt_data(db: Session, receipt_id: int) -> dict:
    row = (
        db.execute(
            select(
                Receipt.id,
                Receipt.supplier_id,
                Receipt.reference,
                Receipt.status,
                Receipt.created_by,
                Receipt.posted_by,
                Receipt.created_at,
                Receipt.posted_at,
                Supplier.name.label("supplier_name"),
                UserU.username.label("created_by_name"),
                Warehouse.id.label("warehouse_id"),
                Warehouse.name.label("warehouse_name"),
                ReceiptReversal.id.label("reversal_id"),
                ReceiptReversal.reason.label("reversal_reason"),
                ReceiptReversal.created_by.label("reversed_by"),
                UserRu.username.label("reversed_by_name"),
                ReceiptReversal.created_at.label("reversed_at"),
            )
            .select_from(Receipt)
            .join(Supplier, (Supplier.id == Receipt.supplier_id))
            .join(UserU, (UserU.id == Receipt.created_by))
            .join(ReceiptWarehouse, (ReceiptWarehouse.receipt_id == Receipt.id))
            .join(Warehouse, (Warehouse.id == ReceiptWarehouse.warehouse_id))
            .outerjoin(ReceiptReversal, (ReceiptReversal.receipt_id == Receipt.id))
            .outerjoin(UserRu, (UserRu.id == ReceiptReversal.created_by))
            .where((Receipt.id == receipt_id))
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(404, "入库单不存在")
    lines = (
        db.execute(
            select(
                ReceiptLine.id,
                ReceiptLine.material_id,
                Material.sku,
                Material.name.label("material_name"),
                Material.unit,
                ReceiptLine.quantity,
            )
            .select_from(ReceiptLine)
            .join(Material, (Material.id == ReceiptLine.material_id))
            .where((ReceiptLine.receipt_id == receipt_id))
            .order_by(ReceiptLine.id)
        )
        .mappings()
        .all()
    )
    detailed_lines = []
    lots_by_line: dict[int, list[dict]] = {}
    for line_id, lot, allocation in db.execute(
        select(StockMovement.source_line_id, PhysicalLot, PhysicalLotAllocation)
        .join(PhysicalLotAllocation, PhysicalLotAllocation.movement_id == StockMovement.id)
        .join(PhysicalLot, PhysicalLot.id == PhysicalLotAllocation.lot_id)
        .where(StockMovement.source_type == 'receipt', StockMovement.source_id == receipt_id)
        .order_by(StockMovement.source_line_id, PhysicalLotAllocation.id)
    ):
        lots_by_line.setdefault(line_id, []).append({
            'id': lot.id, 'code': lot.code, 'quantity': allocation.quantity,
            'supplier_lot': lot.supplier_lot, 'manufactured_on': lot.manufactured_on,
            'expires_on': lot.expires_on,
        })
    for line in lines:
        # 同一次读取只汇总一次已退量，可退数量只由已确认单据推导。
        returned = purchase_returned_quantity(db, line["id"])
        detailed_lines.append(
            {
                **dict(line),
                "returned_quantity": str(returned),
                "returnable_quantity": str(
                    Decimal(0) if row["reversal_id"] else Decimal(line["quantity"]) - returned
                ),
                'physical_lots': lots_by_line.get(line['id'], []),
            }
        )
    goods_receipt = (
        db.execute(
            select(PurchaseGoodsReceipt.id)
            .select_from(PurchaseGoodsReceipt)
            .where((PurchaseGoodsReceipt.inbound_receipt_id == receipt_id))
        )
        .mappings()
        .first()
    )
    return {
        **dict(row),
        "purchase_order_id": linked_order_for_receipt(db, receipt_id),
        "approval": approval.case_data(approval.find_case(db, 'Receipt', receipt_id)),
        "reversal_approval": approval.case_data(approval.find_case(db, 'Receipt', receipt_id, 'reverse')),
        "goods_receipt_id": goods_receipt["id"] if goods_receipt else None,
        "lines": detailed_lines,
    }


@router.get("/receipts")
def list_receipts(_: dict = Depends(require("inventory.view"))) -> list[dict]:
    with orm_session() as db:
        ids = [row for row in db.scalars(select(Receipt.id).select_from(Receipt).order_by(Receipt.id.desc()))]
        return [receipt_data(db, receipt_id) for receipt_id in ids]


@router.post("/receipts", status_code=201)
def create_receipt(payload: ReceiptInput, user: dict = Depends(require("receipt.create"))) -> dict:
    if len({line.material_id for line in payload.lines}) != len(payload.lines):
        raise HTTPException(422, "一张入库单不能重复选择同一物料")
    with orm_session(write=True) as db:
        require_warehouse(db, payload.warehouse_id)
        if (
            not db.execute(
                select(literal(1)).select_from(Supplier).where((Supplier.id == payload.supplier_id))
            )
            .mappings()
            .first()
        ):
            raise HTTPException(422, "供应商不存在")
        for line in payload.lines:
            if (
                not db.execute(
                    select(literal(1)).select_from(Material).where((Material.id == line.material_id))
                )
                .mappings()
                .first()
            ):
                raise HTTPException(422, "物料不存在")
        order_line_ids = (
            order_receipt_lines(
                db,
                payload.purchase_order_id,
                payload.supplier_id,
                [(line.material_id, line.quantity) for line in payload.lines],
            )
            if payload.purchase_order_id is not None
            else {}
        )
        cursor = add_model(
            db,
            Receipt(
                supplier_id=payload.supplier_id, reference=payload.reference.strip(), created_by=user["id"]
            ),
        )
        add_model(db, ReceiptWarehouse(receipt_id=cursor.id, warehouse_id=payload.warehouse_id))
        for line in payload.lines:
            line_cursor = add_model(
                db,
                ReceiptLine(receipt_id=cursor.id, material_id=line.material_id, quantity=str(line.quantity)),
            )
            if payload.purchase_order_id is not None:
                add_model(
                    db,
                    ReceiptOrderLink(
                        receipt_line_id=line_cursor.id,
                        purchase_order_line_id=order_line_ids[line.material_id],
                    ),
                )
        return receipt_data(db, cursor.id)


@router.post("/receipts/{receipt_id}/post")
def post_receipt(receipt_id: int, payload: ReceiptPostInput | None = None,
                 user: dict = Depends(require("receipt.post"))) -> dict:
    with orm_session(write=True) as db:
        # 状态变更和库存流水写入使用同一个写事务，重复确认会返回冲突。
        row = (
            db.execute(
                select(Receipt.status, Receipt.supplier_id)
                .select_from(Receipt)
                .where((Receipt.id == receipt_id))
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "入库单不存在")
        if row["status"] != "draft":
            raise HTTPException(409, "此入库单已经确认")
        approved = approval.require_approved(db, 'Receipt', receipt_id,
            receipt_snapshot(db, receipt_id), user['id'])
        order_id = validate_receipt_post(db, receipt_id, row["supplier_id"])
        lines = list(db.execute(
            select(ReceiptLine.id, ReceiptLine.material_id, ReceiptLine.quantity,
                   ReceiptWarehouse.warehouse_id)
            .join(ReceiptWarehouse, ReceiptWarehouse.receipt_id == ReceiptLine.receipt_id)
            .where(ReceiptLine.receipt_id == receipt_id).order_by(ReceiptLine.id)
        ))
        lot_lines = {line.receipt_line_id: line for line in payload.lines} if payload else None
        if lot_lines is not None and (len(lot_lines) != len(payload.lines)
                                      or set(lot_lines) != {line.id for line in lines}):
            raise HTTPException(422, '批次明细必须与入库单明细逐行对应')
        for line in lines:
            movement = StockMovement(
                warehouse_id=line.warehouse_id, material_id=line.material_id,
                quantity=line.quantity, source_type='receipt', source_id=receipt_id,
                source_line_id=line.id, created_by=user['id'])
            if lot_lines is None:
                db.add(movement)
                continue
            parts = lot_lines[line.id].lots
            if sum((part.quantity for part in parts), Decimal(0)) != Decimal(line.quantity):
                raise HTTPException(422, f'入库明细 #{line.id} 的批次数量之和不匹配')
            if any(part.manufactured_on and part.expires_on
                   and part.expires_on < part.manufactured_on for part in parts):
                raise HTTPException(422, f'入库明细 #{line.id} 的失效日期早于生产日期')
            lots = [add_model(db, PhysicalLot(
                material_id=line.material_id, code=f'R{receipt_id}-L{line.id}-P{index}',
                source_kind='receipt', supplier_lot=part.supplier_lot,
                manufactured_on=part.manufactured_on.isoformat() if part.manufactured_on else None,
                expires_on=part.expires_on.isoformat() if part.expires_on else None,
                created_by=user['id'])) for index, part in enumerate(parts, 1)]
            post_lot_movement(db, movement, [
                LotPart(lot.id, part.quantity) for lot, part in zip(lots, parts)])
            for lot in lots:
                lot.origin_movement_id = movement.id
        db.execute(
            update(Receipt)
            .where((Receipt.id == receipt_id))
            .values(status="posted", posted_by=user["id"], posted_at=func.current_timestamp())
        )
        if order_id is not None:
            update_order_receipt_status(db, order_id)
        approval.mark_executed(db, approved, user['id'])
        return receipt_data(db, receipt_id)


@router.post("/receipts/{receipt_id}/reverse", status_code=201)
def reverse_receipt(
    receipt_id: int, payload: ReceiptReverseInput, user: dict = Depends(require("receipt.reverse"))
) -> dict:
    with orm_session(write=True) as db:
        # 写锁覆盖退货依赖、当前库存、冲销流水和订单进度，避免并发改变核对结果。
        row = (
            db.execute(
                select(Receipt.status, ReceiptWarehouse.warehouse_id)
                .select_from(Receipt)
                .join(ReceiptWarehouse, (ReceiptWarehouse.receipt_id == Receipt.id))
                .where((Receipt.id == receipt_id))
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "入库单不存在")
        if row["status"] != "posted":
            raise HTTPException(409, "只有已确认入库单可冲销")
        if (
            db.execute(
                select(literal(1))
                .select_from(ReceiptReversal)
                .where((ReceiptReversal.receipt_id == receipt_id))
            )
            .mappings()
            .first()
        ):
            raise HTTPException(409, "此入库单已冲销")
        # 冲销原因也是固定审批内容；失败时库存和审批状态整体回滚。
        approved = approval.require_approved(db, 'Receipt', receipt_id,
            document_snapshot(db, 'Receipt', receipt_id, 'reverse', payload.reason),
            user['id'], intent='reverse', permission='receipt.reverse')
        lines = (
            db.execute(
                select(ReceiptLine.id, ReceiptLine.material_id, ReceiptLine.quantity)
                .select_from(ReceiptLine)
                .where((ReceiptLine.receipt_id == receipt_id))
            )
            .mappings()
            .all()
        )
        for line in lines:
            if purchase_returned_quantity(db, line["id"]) > 0:
                raise HTTPException(409, "原入库单仍有已确认采购退货，请先冲销退货")
            if balance(db, row["warehouse_id"], line["material_id"]) < Decimal(line["quantity"]):
                raise HTTPException(409, f"原入库仓物料 #{line['material_id']} 库存不足，无法冲销")
        cursor = add_model(
            db, ReceiptReversal(receipt_id=receipt_id, reason=payload.reason, created_by=user["id"])
        )
        for line in lines:
            # 保留原正向入库流水，再用关联原明细的负向流水抵消误入库数量。
            movement = StockMovement(
                warehouse_id=row['warehouse_id'], material_id=line['material_id'],
                quantity=str(-Decimal(line['quantity'])), source_type='receipt_reversal',
                source_id=cursor.id, source_line_id=line['id'], created_by=user['id'])
            allocations = list(db.scalars(
                select(PhysicalLotAllocation)
                .join(StockMovement, StockMovement.id == PhysicalLotAllocation.movement_id)
                .where(StockMovement.source_type == 'receipt', StockMovement.source_id == receipt_id,
                       StockMovement.source_line_id == line['id'])
                .order_by(PhysicalLotAllocation.id)))
            if allocations:
                if sum((Decimal(part.quantity) for part in allocations), Decimal(0)) != Decimal(line['quantity']):
                    raise HTTPException(409, '原入库批次分配不完整，无法冲销')
                post_lot_movement(db, movement, [LotPart(
                    part.lot_id, -Decimal(part.quantity), part.id) for part in allocations])
            else:
                db.add(movement)
        order_id = linked_order_for_receipt(db, receipt_id)
        if order_id is not None:
            update_order_receipt_status(db, order_id)
        approval.mark_executed(db, approved, user['id'], permission='receipt.reverse')
        return receipt_data(db, receipt_id)
