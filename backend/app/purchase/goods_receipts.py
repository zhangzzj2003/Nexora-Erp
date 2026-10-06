"""采购收货事实与待入库单的单向生成。"""

from app.core.document_responses import NumberedRoute
from sqlalchemy import select, update, func, literal
from sqlalchemy.orm import Session, aliased
from sqlalchemy.engine import RowMapping
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from app.access.security import require
from app.core.orm import orm_session, add_model
from app.core.models import (
    Material,
    PurchaseGoodsReceipt,
    PurchaseGoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    Receipt,
    ReceiptLine,
    ReceiptOrderLink,
    ReceiptReversal,
    ReceiptWarehouse,
    Supplier,
    User,
    Warehouse,
)
from app.inventory.warehouse import require_warehouse
from app.purchase.orders import received_quantity

UserConfirmer = aliased(User)
UserCreator = aliased(User)

router = APIRouter(route_class=NumberedRoute, prefix="/api/v1")


class GoodsReceiptLineInput(BaseModel):
    purchase_order_line_id: int = Field(gt=0)
    accepted_quantity: Decimal = Decimal(0)
    rejected_quantity: Decimal = Decimal(0)
    rejection_reason: str = Field(default="", max_length=200)

    @field_validator("accepted_quantity", "rejected_quantity")
    @classmethod
    def valid_quantity(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value < 0 or value > 1_000_000 or value.as_tuple().exponent < -3:
            raise ValueError("收货数量须非负、最多三位小数且不超过一百万")
        return value

    @model_validator(mode="after")
    def valid_result(self):
        if self.accepted_quantity + self.rejected_quantity <= 0:
            raise ValueError("每条收货明细须有合格或拒收数量")
        if self.rejected_quantity > 0 and not self.rejection_reason.strip():
            raise ValueError("拒收数量大于零时须填写原因")
        self.rejection_reason = self.rejection_reason.strip()
        return self


class GoodsReceiptInput(BaseModel):
    purchase_order_id: int = Field(gt=0)
    warehouse_id: int = Field(gt=0)
    reference: str = Field(default="", max_length=100)
    lines: list[GoodsReceiptLineInput] = Field(min_length=1, max_length=100)


def pending_accepted_quantity(db: Session, order_line_id: int) -> Decimal:
    # 已确认收货生成的待入库单先占用收货额度，避免两个仓库员同时生成超量入库草稿。
    return sum(
        (
            Decimal(row)
            for row in db.scalars(
                select(PurchaseGoodsReceiptLine.accepted_quantity)
                .select_from(PurchaseGoodsReceiptLine)
                .join(
                    PurchaseGoodsReceipt, PurchaseGoodsReceipt.id == PurchaseGoodsReceiptLine.goods_receipt_id
                )
                .join(Receipt, Receipt.id == PurchaseGoodsReceipt.inbound_receipt_id)
                .where(
                    PurchaseGoodsReceiptLine.purchase_order_line_id == order_line_id,
                    PurchaseGoodsReceipt.status == "confirmed",
                    Receipt.status == "draft",
                )
            )
        ),
        Decimal(0),
    )


def checked_lines(db: Session, payload: GoodsReceiptInput) -> tuple[RowMapping, dict[int, RowMapping]]:
    if len({line.purchase_order_line_id for line in payload.lines}) != len(payload.lines):
        raise HTTPException(422, "一张收货单不能重复选择同一订单明细")
    order = (
        db.execute(
            select(PurchaseOrder.supplier_id, PurchaseOrder.status)
            .select_from(PurchaseOrder)
            .where((PurchaseOrder.id == payload.purchase_order_id))
        )
        .mappings()
        .first()
    )
    if not order:
        raise HTTPException(422, "采购订单不存在")
    if order["status"] not in ("confirmed", "partially_received"):
        raise HTTPException(409, "采购订单当前不可收货")
    known = {
        row["id"]: row
        for row in db.execute(
            select(PurchaseOrderLine.id, PurchaseOrderLine.material_id, PurchaseOrderLine.quantity)
            .select_from(PurchaseOrderLine)
            .where((PurchaseOrderLine.purchase_order_id == payload.purchase_order_id))
        ).mappings()
    }
    for line in payload.lines:
        source = known.get(line.purchase_order_line_id)
        if not source:
            raise HTTPException(422, "收货明细不属于此采购订单")
        remaining = (
            Decimal(source["quantity"])
            - received_quantity(db, source["id"])
            - pending_accepted_quantity(db, source["id"])
        )
        if line.accepted_quantity + line.rejected_quantity > remaining:
            raise HTTPException(409, f"订单明细 #{source['id']} 超过待收数量")
    return order, known


def goods_receipt_data(db: Session, goods_receipt_id: int) -> dict:
    row = (
        db.execute(
            select(
                PurchaseGoodsReceipt.id,
                PurchaseGoodsReceipt.purchase_order_id,
                PurchaseGoodsReceipt.warehouse_id,
                PurchaseGoodsReceipt.inbound_receipt_id,
                PurchaseGoodsReceipt.reference,
                PurchaseGoodsReceipt.status,
                PurchaseGoodsReceipt.created_by,
                PurchaseGoodsReceipt.confirmed_by,
                PurchaseGoodsReceipt.cancelled_by,
                PurchaseGoodsReceipt.created_at,
                PurchaseGoodsReceipt.confirmed_at,
                PurchaseGoodsReceipt.cancelled_at,
                PurchaseOrder.supplier_id,
                Supplier.name.label("supplier_name"),
                Warehouse.name.label("warehouse_name"),
                UserCreator.username.label("created_by_name"),
                UserConfirmer.username.label("confirmed_by_name"),
                Receipt.status.label("inbound_status"),
                ReceiptReversal.id.label("inbound_reversal_id"),
            )
            .select_from(PurchaseGoodsReceipt)
            .join(PurchaseOrder, (PurchaseOrder.id == PurchaseGoodsReceipt.purchase_order_id))
            .join(Supplier, (Supplier.id == PurchaseOrder.supplier_id))
            .join(Warehouse, (Warehouse.id == PurchaseGoodsReceipt.warehouse_id))
            .join(UserCreator, (UserCreator.id == PurchaseGoodsReceipt.created_by))
            .outerjoin(UserConfirmer, (UserConfirmer.id == PurchaseGoodsReceipt.confirmed_by))
            .outerjoin(Receipt, (Receipt.id == PurchaseGoodsReceipt.inbound_receipt_id))
            .outerjoin(ReceiptReversal, (ReceiptReversal.receipt_id == Receipt.id))
            .where((PurchaseGoodsReceipt.id == goods_receipt_id))
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(404, "采购收货单不存在")
    lines = (
        db.execute(
            select(
                PurchaseGoodsReceiptLine.id,
                PurchaseGoodsReceiptLine.goods_receipt_id,
                PurchaseGoodsReceiptLine.purchase_order_line_id,
                PurchaseGoodsReceiptLine.accepted_quantity,
                PurchaseGoodsReceiptLine.rejected_quantity,
                PurchaseGoodsReceiptLine.rejection_reason,
                PurchaseOrderLine.material_id,
                Material.sku,
                Material.name.label("material_name"),
                Material.unit,
            )
            .select_from(PurchaseGoodsReceiptLine)
            .join(
                PurchaseOrderLine, (PurchaseOrderLine.id == PurchaseGoodsReceiptLine.purchase_order_line_id)
            )
            .join(Material, (Material.id == PurchaseOrderLine.material_id))
            .where((PurchaseGoodsReceiptLine.goods_receipt_id == goods_receipt_id))
            .order_by(PurchaseGoodsReceiptLine.id)
        )
        .mappings()
        .all()
    )
    return {**dict(row), "lines": [dict(line) for line in lines]}


@router.get("/purchase-goods-receipts")
def list_goods_receipts(_: dict = Depends(require("purchase_receiving.view"))) -> list[dict]:
    with orm_session() as db:
        ids = [
            row
            for row in db.scalars(
                select(PurchaseGoodsReceipt.id)
                .select_from(PurchaseGoodsReceipt)
                .order_by(PurchaseGoodsReceipt.id.desc())
            )
        ]
        return [goods_receipt_data(db, item_id) for item_id in ids]


@router.post("/purchase-goods-receipts", status_code=201)
def create_goods_receipt(
    payload: GoodsReceiptInput, user: dict = Depends(require("purchase_receiving.create"))
) -> dict:
    with orm_session(write=True) as db:
        require_warehouse(db, payload.warehouse_id)
        checked_lines(db, payload)
        cursor = add_model(
            db,
            PurchaseGoodsReceipt(
                purchase_order_id=payload.purchase_order_id,
                warehouse_id=payload.warehouse_id,
                reference=payload.reference.strip(),
                created_by=user["id"],
            ),
        )
        db.add_all(
            [
                PurchaseGoodsReceiptLine(
                    goods_receipt_id=cursor.id,
                    purchase_order_line_id=line.purchase_order_line_id,
                    accepted_quantity=str(line.accepted_quantity),
                    rejected_quantity=str(line.rejected_quantity),
                    rejection_reason=line.rejection_reason,
                )
                for line in payload.lines
            ]
        )
        return goods_receipt_data(db, cursor.id)


@router.post("/purchase-goods-receipts/{goods_receipt_id}/confirm")
def confirm_goods_receipt(
    goods_receipt_id: int, user: dict = Depends(require("purchase_receiving.confirm"))
) -> dict:
    with orm_session(write=True) as db:
        # 收货校验、待入库单生成和状态转换在同一写事务内完成，重试不能产生第二张入库单。
        source = (
            db.execute(
                select(
                    PurchaseGoodsReceipt.id,
                    PurchaseGoodsReceipt.purchase_order_id,
                    PurchaseGoodsReceipt.warehouse_id,
                    PurchaseGoodsReceipt.inbound_receipt_id,
                    PurchaseGoodsReceipt.reference,
                    PurchaseGoodsReceipt.status,
                    PurchaseGoodsReceipt.created_by,
                    PurchaseGoodsReceipt.confirmed_by,
                    PurchaseGoodsReceipt.cancelled_by,
                    PurchaseGoodsReceipt.created_at,
                    PurchaseGoodsReceipt.confirmed_at,
                    PurchaseGoodsReceipt.cancelled_at,
                )
                .select_from(PurchaseGoodsReceipt)
                .where((PurchaseGoodsReceipt.id == goods_receipt_id))
            )
            .mappings()
            .first()
        )
        if not source:
            raise HTTPException(404, "采购收货单不存在")
        if source["status"] != "draft":
            raise HTTPException(409, "此采购收货单已处理")
        lines = (
            db.execute(
                select(
                    PurchaseGoodsReceiptLine.id,
                    PurchaseGoodsReceiptLine.goods_receipt_id,
                    PurchaseGoodsReceiptLine.purchase_order_line_id,
                    PurchaseGoodsReceiptLine.accepted_quantity,
                    PurchaseGoodsReceiptLine.rejected_quantity,
                    PurchaseGoodsReceiptLine.rejection_reason,
                )
                .select_from(PurchaseGoodsReceiptLine)
                .where((PurchaseGoodsReceiptLine.goods_receipt_id == goods_receipt_id))
            )
            .mappings()
            .all()
        )
        payload = GoodsReceiptInput(
            purchase_order_id=source["purchase_order_id"],
            warehouse_id=source["warehouse_id"],
            reference=source["reference"],
            lines=[GoodsReceiptLineInput(**dict(line)) for line in lines],
        )
        order, known = checked_lines(db, payload)
        accepted = [line for line in lines if Decimal(line["accepted_quantity"]) > 0]
        inbound_id = None
        if accepted:
            inbound_id = add_model(
                db,
                Receipt(
                    supplier_id=order["supplier_id"], reference=source["reference"], created_by=user["id"]
                ),
            ).id
            add_model(db, ReceiptWarehouse(receipt_id=inbound_id, warehouse_id=source["warehouse_id"]))
            for line in accepted:
                receipt_line_id = add_model(
                    db,
                    ReceiptLine(
                        receipt_id=inbound_id,
                        material_id=known[line["purchase_order_line_id"]]["material_id"],
                        quantity=line["accepted_quantity"],
                    ),
                ).id
                add_model(
                    db,
                    ReceiptOrderLink(
                        receipt_line_id=receipt_line_id, purchase_order_line_id=line["purchase_order_line_id"]
                    ),
                )
        db.execute(
            update(PurchaseGoodsReceipt)
            .where((PurchaseGoodsReceipt.id == goods_receipt_id))
            .values(
                status="confirmed",
                confirmed_by=user["id"],
                confirmed_at=func.current_timestamp(),
                inbound_receipt_id=inbound_id,
            )
        )
        return goods_receipt_data(db, goods_receipt_id)


@router.post("/purchase-goods-receipts/{goods_receipt_id}/cancel")
def cancel_goods_receipt(
    goods_receipt_id: int, user: dict = Depends(require("purchase_receiving.cancel"))
) -> dict:
    with orm_session(write=True) as db:
        cursor = db.execute(
            update(PurchaseGoodsReceipt)
            .where(PurchaseGoodsReceipt.id == goods_receipt_id, PurchaseGoodsReceipt.status == "draft")
            .values(status="cancelled", cancelled_by=user["id"], cancelled_at=func.current_timestamp())
        )
        if not cursor.rowcount:
            if (
                not db.execute(
                    select(literal(1))
                    .select_from(PurchaseGoodsReceipt)
                    .where((PurchaseGoodsReceipt.id == goods_receipt_id))
                )
                .mappings()
                .first()
            ):
                raise HTTPException(404, "采购收货单不存在")
            raise HTTPException(409, "只能取消采购收货草稿")
        return goods_receipt_data(db, goods_receipt_id)
