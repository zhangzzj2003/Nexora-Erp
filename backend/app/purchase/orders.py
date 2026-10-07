"""采购订单及入库关联；订单数量只由已确认入库单消耗。"""

from app.core.document_responses import NumberedRoute
# 审批核对与原业务写入共用一个事务，旧客户端也不能跳过批准直接执行。
from app.core import document_approval as approval
from app.core.approval_documents import purchase_order_snapshot
from sqlalchemy import select, update, func, literal
from sqlalchemy.orm import Session
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.core.orm import orm_session, add_model
from app.core.models import (
    Material,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderRequestLink,
    PurchaseRequest,
    PurchaseRequestLine,
    Receipt,
    ReceiptLine,
    ReceiptOrderLink,
    ReceiptReversal,
    Supplier,
    User,
)
from app.purchase.returns import returned_quantity as purchase_returned_quantity
from app.purchase.requests import ordered_quantity
from app.access.security import require

router = APIRouter(route_class=NumberedRoute, prefix="/api/v1")


class PurchaseOrderLineInput(BaseModel):
    material_id: int = Field(gt=0)
    purchase_request_line_id: int | None = Field(default=None, gt=0)
    quantity: Decimal
    unit_price: Decimal

    @field_validator("quantity")
    @classmethod
    def valid_quantity(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 0 or value > 1_000_000 or value.as_tuple().exponent < -3:
            raise ValueError("数量须大于零、最多三位小数且不超过一百万")
        return value

    @field_validator("unit_price")
    @classmethod
    def valid_unit_price(cls, value: Decimal) -> Decimal:
        # 单价保留四位小数，金额展示按人民币分四舍五入。
        if not value.is_finite() or value < 0 or value > 1_000_000_000 or value.as_tuple().exponent < -4:
            raise ValueError("单价须非负、最多四位小数且不超过十亿")
        return value


class PurchaseOrderInput(BaseModel):
    supplier_id: int = Field(gt=0)
    purchase_request_id: int | None = Field(default=None, gt=0)
    reference: str = Field(default="", max_length=100)
    lines: list[PurchaseOrderLineInput] = Field(min_length=1, max_length=100)


def received_quantity(db: Session, order_line_id: int) -> Decimal:
    # 只计算已确认入库，草稿不能预占订单数量；不用 SQLite SUM 避免浮点尾差。
    return sum(
        (
            Decimal(row)
            for row in db.scalars(
                select(ReceiptLine.quantity)
                .select_from(ReceiptOrderLink)
                .join(ReceiptLine, ReceiptLine.id == ReceiptOrderLink.receipt_line_id)
                .join(Receipt, Receipt.id == ReceiptLine.receipt_id)
                .outerjoin(ReceiptReversal, ReceiptReversal.receipt_id == Receipt.id)
                .where(
                    ReceiptOrderLink.purchase_order_line_id == order_line_id,
                    Receipt.status == "posted",
                    ReceiptReversal.id.is_(None),
                )
            )
        ),
        Decimal(0),
    )


def returned_quantity(db: Session, order_line_id: int) -> Decimal:
    # 原订单的已入库量保持毛额；退供应商数量另外展示，避免历史状态漂移。
    return sum(
        (
            purchase_returned_quantity(db, row)
            for row in db.scalars(
                select(ReceiptOrderLink.receipt_line_id)
                .select_from(ReceiptOrderLink)
                .where(ReceiptOrderLink.purchase_order_line_id == order_line_id)
            )
        ),
        Decimal(0),
    )


def order_data(db: Session, order_id: int) -> dict:
    row = (
        db.execute(
            select(
                PurchaseOrder.id,
                PurchaseOrder.supplier_id,
                PurchaseOrder.reference,
                PurchaseOrder.status,
                PurchaseOrder.created_by,
                PurchaseOrder.confirmed_by,
                PurchaseOrder.cancelled_by,
                PurchaseOrder.created_at,
                PurchaseOrder.confirmed_at,
                PurchaseOrder.cancelled_at,
                Supplier.name.label("supplier_name"),
                User.username.label("created_by_name"),
            )
            .select_from(PurchaseOrder)
            .join(Supplier, (Supplier.id == PurchaseOrder.supplier_id))
            .join(User, (User.id == PurchaseOrder.created_by))
            .where((PurchaseOrder.id == order_id))
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(404, "采购订单不存在")
    lines = []
    total = Decimal(0)
    for entry in db.execute(
        select(
            PurchaseOrderLine.id,
            PurchaseOrderLine.material_id,
            Material.sku,
            Material.name.label("material_name"),
            Material.unit,
            PurchaseOrderLine.quantity,
            PurchaseOrderLine.unit_price,
            PurchaseOrderRequestLink.purchase_request_line_id,
        )
        .select_from(PurchaseOrderLine)
        .join(Material, (Material.id == PurchaseOrderLine.material_id))
        .outerjoin(
            PurchaseOrderRequestLink,
            (PurchaseOrderRequestLink.purchase_order_line_id == PurchaseOrderLine.id),
        )
        .where((PurchaseOrderLine.purchase_order_id == order_id))
        .order_by(PurchaseOrderLine.id)
    ).mappings():
        quantity = Decimal(entry["quantity"])
        price = Decimal(entry["unit_price"])
        received = received_quantity(db, entry["id"])
        returned = returned_quantity(db, entry["id"])
        line_total = (quantity * price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total += line_total
        lines.append(
            {
                **dict(entry),
                "received_quantity": str(received),
                "returned_quantity": str(returned),
                "net_received_quantity": str(received - returned),
                "remaining_quantity": str(quantity - received),
                "line_total": str(line_total),
            }
        )
    request_ids = {
        entry["purchase_request_id"]
        for entry in db.execute(
            select(PurchaseRequestLine.purchase_request_id)
            .select_from(PurchaseOrderRequestLink)
            .join(
                PurchaseOrderLine, (PurchaseOrderLine.id == PurchaseOrderRequestLink.purchase_order_line_id)
            )
            .join(
                PurchaseRequestLine,
                (PurchaseRequestLine.id == PurchaseOrderRequestLink.purchase_request_line_id),
            )
            .where((PurchaseOrderLine.purchase_order_id == order_id))
            .distinct()
        ).mappings()
    }
    return {
        **dict(row),
        "purchase_request_id": next(iter(request_ids), None),
        "approval": approval.case_data(approval.find_case(db, "PurchaseOrder", order_id)),
        "lines": lines,
        "total_amount": str(total),
    }


def order_receipt_lines(
    db: Session, order_id: int, supplier_id: int, lines: list[tuple[int, Decimal]]
) -> dict[int, int]:
    order = (
        db.execute(
            select(PurchaseOrder.supplier_id, PurchaseOrder.status)
            .select_from(PurchaseOrder)
            .where((PurchaseOrder.id == order_id))
        )
        .mappings()
        .first()
    )
    if not order:
        raise HTTPException(422, "采购订单不存在")
    if order["supplier_id"] != supplier_id:
        raise HTTPException(422, "入库单供应商与采购订单不一致")
    if order["status"] not in ("confirmed", "partially_received"):
        raise HTTPException(409, "采购订单当前不可入库")
    known = {
        row["material_id"]: row
        for row in db.execute(
            select(PurchaseOrderLine.id, PurchaseOrderLine.material_id, PurchaseOrderLine.quantity)
            .select_from(PurchaseOrderLine)
            .where((PurchaseOrderLine.purchase_order_id == order_id))
        ).mappings()
    }
    result: dict[int, int] = {}
    for material_id, quantity in lines:
        item = known.get(material_id)
        if not item:
            raise HTTPException(422, "入库物料不属于此采购订单")
        if quantity > Decimal(item["quantity"]) - received_quantity(db, item["id"]):
            raise HTTPException(409, f"物料 #{material_id} 超出采购订单未入库数量")
        result[material_id] = item["id"]
    return result


def linked_order_for_receipt(db: Session, receipt_id: int) -> int | None:
    rows = (
        db.execute(
            select(PurchaseOrderLine.purchase_order_id, ReceiptLine.material_id, ReceiptLine.quantity)
            .select_from(ReceiptLine)
            .outerjoin(ReceiptOrderLink, (ReceiptOrderLink.receipt_line_id == ReceiptLine.id))
            .outerjoin(PurchaseOrderLine, (PurchaseOrderLine.id == ReceiptOrderLink.purchase_order_line_id))
            .where((ReceiptLine.receipt_id == receipt_id))
        )
        .mappings()
        .all()
    )
    order_ids = {row["purchase_order_id"] for row in rows}
    if order_ids == {None}:
        return None
    if len(order_ids) != 1 or None in order_ids:
        raise HTTPException(409, "入库单关联的采购订单不一致")
    return order_ids.pop()


def validate_receipt_post(db: Session, receipt_id: int, supplier_id: int) -> int | None:
    order_id = linked_order_for_receipt(db, receipt_id)
    if order_id is None:
        return None
    lines = [
        (row["material_id"], Decimal(row["quantity"]))
        for row in db.execute(
            select(ReceiptLine.material_id, ReceiptLine.quantity)
            .select_from(ReceiptLine)
            .where((ReceiptLine.receipt_id == receipt_id))
        ).mappings()
    ]
    order_receipt_lines(db, order_id, supplier_id, lines)
    return order_id


def update_order_receipt_status(db: Session, order_id: int) -> None:
    lines = (
        db.execute(
            select(PurchaseOrderLine.id, PurchaseOrderLine.quantity)
            .select_from(PurchaseOrderLine)
            .where((PurchaseOrderLine.purchase_order_id == order_id))
        )
        .mappings()
        .all()
    )
    received = [received_quantity(db, line["id"]) for line in lines]
    status = (
        "confirmed"
        if all(quantity == 0 for quantity in received)
        else (
            "received"
            if all(quantity == Decimal(line["quantity"]) for quantity, line in zip(received, lines))
            else "partially_received"
        )
    )
    db.execute(update(PurchaseOrder).where((PurchaseOrder.id == order_id)).values(status=status))


@router.get("/purchase-orders")
def list_purchase_orders(_: dict = Depends(require("inventory.view"))) -> list[dict]:
    with orm_session() as db:
        ids = [
            row
            for row in db.scalars(
                select(PurchaseOrder.id).select_from(PurchaseOrder).order_by(PurchaseOrder.id.desc())
            )
        ]
        return [order_data(db, order_id) for order_id in ids]


@router.post("/purchase-orders", status_code=201)
def create_purchase_order(
    payload: PurchaseOrderInput, user: dict = Depends(require("purchase_order.create"))
) -> dict:
    if len({line.material_id for line in payload.lines}) != len(payload.lines):
        raise HTTPException(422, "一张采购订单不能重复选择同一物料")
    if (
        payload.purchase_request_id is None
        and any(line.purchase_request_line_id is not None for line in payload.lines)
    ) or (
        payload.purchase_request_id is not None
        and any(line.purchase_request_line_id is None for line in payload.lines)
    ):
        raise HTTPException(422, "关联申请的订单须为每条明细选择申请明细")
    with orm_session(write=True) as db:
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
        if payload.purchase_request_id is not None:
            request = (
                db.execute(
                    select(PurchaseRequest.status)
                    .select_from(PurchaseRequest)
                    .where((PurchaseRequest.id == payload.purchase_request_id))
                )
                .mappings()
                .first()
            )
            if not request:
                raise HTTPException(422, "采购申请不存在")
            if request["status"] != "approved":
                raise HTTPException(409, "只有已批准的采购申请可转订单")
            for line in payload.lines:
                source = (
                    db.execute(
                        select(PurchaseRequestLine.material_id, PurchaseRequestLine.quantity)
                        .select_from(PurchaseRequestLine)
                        .where(
                            PurchaseRequestLine.id == line.purchase_request_line_id,
                            PurchaseRequestLine.purchase_request_id == payload.purchase_request_id,
                        )
                    )
                    .mappings()
                    .first()
                )
                if not source or source["material_id"] != line.material_id:
                    raise HTTPException(422, "采购订单明细与申请明细不一致")
                # 在同一写事务内检查未转数量，两个客户端不能同时占用同一申请余额。
                if line.quantity > Decimal(source["quantity"]) - ordered_quantity(
                    db, line.purchase_request_line_id
                ):
                    raise HTTPException(409, f"申请明细 #{line.purchase_request_line_id} 的未转数量不足")
        cursor = add_model(
            db,
            PurchaseOrder(
                supplier_id=payload.supplier_id, reference=payload.reference.strip(), created_by=user["id"]
            ),
        )
        for line in payload.lines:
            line_id = add_model(
                db,
                PurchaseOrderLine(
                    purchase_order_id=cursor.id,
                    material_id=line.material_id,
                    quantity=str(line.quantity),
                    unit_price=str(line.unit_price),
                ),
            ).id
            if line.purchase_request_line_id is not None:
                add_model(
                    db,
                    PurchaseOrderRequestLink(
                        purchase_order_line_id=line_id, purchase_request_line_id=line.purchase_request_line_id
                    ),
                )
        return order_data(db, cursor.id)


@router.post("/purchase-orders/{order_id}/confirm")
def confirm_purchase_order(order_id: int, user: dict = Depends(require("purchase_order.confirm"))) -> dict:
    with orm_session(write=True) as db:
        row = (
            db.execute(
                select(PurchaseOrder.status).select_from(PurchaseOrder).where((PurchaseOrder.id == order_id))
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "采购订单不存在")
        if row["status"] != "draft":
            raise HTTPException(409, "只能确认草稿采购订单")
        approved = approval.require_approved(db, 'PurchaseOrder', order_id,
            purchase_order_snapshot(db, order_id), user['id'])
        db.execute(
            update(PurchaseOrder)
            .where((PurchaseOrder.id == order_id))
            .values(status="confirmed", confirmed_by=user["id"], confirmed_at=func.current_timestamp())
        )
        approval.mark_executed(db, approved, user['id'])
        return order_data(db, order_id)


@router.post("/purchase-orders/{order_id}/cancel")
def cancel_purchase_order(order_id: int, user: dict = Depends(require("purchase_order.cancel"))) -> dict:
    with orm_session(write=True) as db:
        row = (
            db.execute(
                select(PurchaseOrder.status).select_from(PurchaseOrder).where((PurchaseOrder.id == order_id))
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "采购订单不存在")
        # 已有确认入库的数据不能通过取消订单抹去；后续退货应走独立单据。
        if row["status"] not in ("draft", "confirmed"):
            raise HTTPException(409, "已入库或已取消的采购订单不可取消")
        pending = approval.find_case(db, 'PurchaseOrder', order_id)
        if pending and pending.status in ('submitted', 'approved'):
            raise HTTPException(409, '请先撤回审批，再取消采购订单')
        db.execute(
            update(PurchaseOrder)
            .where((PurchaseOrder.id == order_id))
            .values(status="cancelled", cancelled_by=user["id"], cancelled_at=func.current_timestamp())
        )
        return order_data(db, order_id)
