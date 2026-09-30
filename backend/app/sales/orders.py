"""客户、销售订单和出库单；订单完成量只由已确认出库计算。"""

from sqlalchemy import select, update, func, literal
from sqlalchemy.orm import Session, aliased
from sqlalchemy.exc import IntegrityError
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.core.orm import orm_session, add_model
from app.core.models import (
    Customer,
    SalesOrderOwner,
    Material,
    SalesOrder,
    SalesOrderLine,
    Shipment,
    ShipmentLine,
    ShipmentReversal,
    StockMovement,
    User,
    Warehouse,
)
from app.inventory.warehouse import TransferLineInput, balance, require_warehouse
from app.purchase.orders import PurchaseOrderLineInput
from app.sales.returns import returned_quantity
from app.access.security import require
from app.sales.customer_scope import require_customer, protect_amount

UserRu = aliased(User)
UserU = aliased(User)

router = APIRouter(prefix="/api/v1")


class SalesOrderInput(BaseModel):
    customer_id: int = Field(gt=0)
    reference: str = Field(default="", max_length=100)
    # 销售和采购遵守同一物料数量、单价精度，避免两端金额算法漂移。
    lines: list[PurchaseOrderLineInput] = Field(min_length=1, max_length=100)


class ShipmentInput(BaseModel):
    sales_order_id: int = Field(gt=0)
    warehouse_id: int = Field(gt=0)
    reference: str = Field(default="", max_length=100)
    lines: list[TransferLineInput] = Field(min_length=1, max_length=100)


class ShipmentReverseInput(BaseModel):
    reason: str = Field(min_length=1, max_length=200)

    @field_validator("reason")
    @classmethod
    def trim_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("冲销原因不能为空")
        return value.strip()


def shipped_quantity(db: Session, order_line_id: int) -> Decimal:
    # 已冲销出库保留历史，但不再消耗订单的可出库数量。
    return sum(
        (
            Decimal(row)
            for row in db.scalars(
                select(ShipmentLine.quantity)
                .select_from(ShipmentLine)
                .join(Shipment, Shipment.id == ShipmentLine.shipment_id)
                .outerjoin(ShipmentReversal, ShipmentReversal.shipment_id == Shipment.id)
                .where(
                    ShipmentLine.sales_order_line_id == order_line_id,
                    Shipment.status == "posted",
                    ShipmentReversal.id.is_(None),
                )
            )
        ),
        Decimal(0),
    )


def returned_order_quantity(db: Session, order_line_id: int) -> Decimal:
    # 退货另记正向库存流水；订单显示已退量，但历史已出库量保持原值。
    line_ids = [
        row
        for row in db.scalars(
            select(ShipmentLine.id)
            .select_from(ShipmentLine)
            .join(Shipment, Shipment.id == ShipmentLine.shipment_id)
            .outerjoin(ShipmentReversal, ShipmentReversal.shipment_id == Shipment.id)
            .where(
                ShipmentLine.sales_order_line_id == order_line_id,
                Shipment.status == "posted",
                ShipmentReversal.id.is_(None),
            )
        )
    ]
    return sum((returned_quantity(db, line_id) for line_id in line_ids), Decimal(0))


def sales_order_data(db: Session, order_id: int) -> dict:
    row = (
        db.execute(
            select(
                SalesOrder.id,
                SalesOrder.customer_id,
                SalesOrder.reference,
                SalesOrder.status,
                SalesOrder.created_by,
                SalesOrder.confirmed_by,
                SalesOrder.cancelled_by,
                SalesOrder.created_at,
                SalesOrder.confirmed_at,
                SalesOrder.cancelled_at,
                Customer.name.label("customer_name"),
                User.username.label("created_by_name"),
            )
            .select_from(SalesOrder)
            .join(Customer, (Customer.id == SalesOrder.customer_id))
            .join(User, (User.id == SalesOrder.created_by))
            .where((SalesOrder.id == order_id))
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(404, "销售订单不存在")
    lines = []
    total = Decimal(0)
    for item in db.execute(
        select(
            SalesOrderLine.id,
            SalesOrderLine.material_id,
            Material.sku,
            Material.name.label("material_name"),
            Material.unit,
            SalesOrderLine.quantity,
            SalesOrderLine.unit_price,
        )
        .select_from(SalesOrderLine)
        .join(Material, (Material.id == SalesOrderLine.material_id))
        .where((SalesOrderLine.sales_order_id == order_id))
        .order_by(SalesOrderLine.id)
    ).mappings():
        quantity = Decimal(item["quantity"])
        price = Decimal(item["unit_price"])
        shipped = shipped_quantity(db, item["id"])
        returned = returned_order_quantity(db, item["id"])
        line_total = (quantity * price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total += line_total
        lines.append(
            {
                **dict(item),
                "shipped_quantity": str(shipped),
                "returned_quantity": str(returned),
                "net_delivered_quantity": str(shipped - returned),
                "remaining_quantity": str(quantity - shipped),
                "line_total": str(line_total),
            }
        )
    return {**dict(row), "lines": lines, "total_amount": str(total)}


def shipment_data(db: Session, shipment_id: int) -> dict:
    row = (
        db.execute(
            select(
                Shipment.id,
                Shipment.sales_order_id,
                Shipment.warehouse_id,
                Shipment.reference,
                Shipment.status,
                Shipment.created_by,
                Shipment.posted_by,
                Shipment.cancelled_by,
                Shipment.created_at,
                Shipment.posted_at,
                Shipment.cancelled_at,
                Warehouse.name.label("warehouse_name"),
                Customer.name.label("customer_name"),
                UserU.username.label("created_by_name"),
                ShipmentReversal.id.label("reversal_id"),
                ShipmentReversal.reason.label("reversal_reason"),
                ShipmentReversal.created_by.label("reversed_by"),
                UserRu.username.label("reversed_by_name"),
                ShipmentReversal.created_at.label("reversed_at"),
            )
            .select_from(Shipment)
            .join(Warehouse, (Warehouse.id == Shipment.warehouse_id))
            .join(SalesOrder, (SalesOrder.id == Shipment.sales_order_id))
            .join(Customer, (Customer.id == SalesOrder.customer_id))
            .join(UserU, (UserU.id == Shipment.created_by))
            .outerjoin(ShipmentReversal, (ShipmentReversal.shipment_id == Shipment.id))
            .outerjoin(UserRu, (UserRu.id == ShipmentReversal.created_by))
            .where((Shipment.id == shipment_id))
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(404, "出库单不存在")
    lines = (
        db.execute(
            select(
                ShipmentLine.id,
                SalesOrderLine.material_id,
                Material.sku,
                Material.name.label("material_name"),
                Material.unit,
                ShipmentLine.quantity,
            )
            .select_from(ShipmentLine)
            .join(SalesOrderLine, (SalesOrderLine.id == ShipmentLine.sales_order_line_id))
            .join(Material, (Material.id == SalesOrderLine.material_id))
            .where((ShipmentLine.shipment_id == shipment_id))
            .order_by(ShipmentLine.id)
        )
        .mappings()
        .all()
    )
    result_lines = []
    for item in lines:
        returned = returned_quantity(db, item["id"])
        result_lines.append(
            {
                **dict(item),
                "returned_quantity": str(returned),
                "returnable_quantity": str(
                    Decimal(0) if row["reversal_id"] else Decimal(item["quantity"]) - returned
                ),
            }
        )
    return {**dict(row), "lines": result_lines}


def checked_order_lines(db: Session, order_id: int, lines: list[tuple[int, Decimal]]) -> dict[int, int]:
    order = (
        db.execute(select(SalesOrder.status).select_from(SalesOrder).where((SalesOrder.id == order_id)))
        .mappings()
        .first()
    )
    if not order:
        raise HTTPException(422, "销售订单不存在")
    if order["status"] not in ("confirmed", "partially_shipped"):
        raise HTTPException(409, "销售订单当前不可出库")
    known = {
        row["material_id"]: row
        for row in db.execute(
            select(SalesOrderLine.id, SalesOrderLine.material_id, SalesOrderLine.quantity)
            .select_from(SalesOrderLine)
            .where((SalesOrderLine.sales_order_id == order_id))
        ).mappings()
    }
    result: dict[int, int] = {}
    for material_id, quantity in lines:
        item = known.get(material_id)
        if not item:
            raise HTTPException(422, "出库物料不属于此销售订单")
        if quantity > Decimal(item["quantity"]) - shipped_quantity(db, item["id"]):
            raise HTTPException(409, f"物料 #{material_id} 超出销售订单未出库数量")
        result[material_id] = item["id"]
    return result


def update_order_shipment_status(db: Session, order_id: int) -> None:
    lines = (
        db.execute(
            select(SalesOrderLine.id, SalesOrderLine.quantity)
            .select_from(SalesOrderLine)
            .where((SalesOrderLine.sales_order_id == order_id))
        )
        .mappings()
        .all()
    )
    shipped = [shipped_quantity(db, line["id"]) for line in lines]
    status = (
        "confirmed"
        if all(quantity == 0 for quantity in shipped)
        else (
            "shipped"
            if all(quantity == Decimal(line["quantity"]) for quantity, line in zip(shipped, lines))
            else "partially_shipped"
        )
    )
    db.execute(update(SalesOrder).where((SalesOrder.id == order_id)).values(status=status))


@router.get("/sales-orders")
def list_sales_orders(user: dict = Depends(require("sales.view"))) -> list[dict]:
    with orm_session() as db:
        ids = [
            row
            for row in db.scalars(
                select(SalesOrder.id).select_from(SalesOrder).order_by(SalesOrder.id.desc())
            )
        ]
        return [protect_amount(db, sales_order_data(db, order_id), user, order_id) for order_id in ids]


@router.post("/sales-orders", status_code=201)
def create_sales_order(payload: SalesOrderInput, user: dict = Depends(require("sales_order.create"))) -> dict:
    if len({line.material_id for line in payload.lines}) != len(payload.lines):
        raise HTTPException(422, "一张销售订单不能重复选择同一物料")
    with orm_session(write=True) as db:
        # 客户资料仍私有；公司同事通过已存在订单办理后续，不借新建单访问他人客户。
        profile = require_customer(db, payload.customer_id, user, active=True)
        for line in payload.lines:
            if (
                not db.execute(
                    select(literal(1)).select_from(Material).where((Material.id == line.material_id))
                )
                .mappings()
                .first()
            ):
                raise HTTPException(422, "物料不存在")
        cursor = add_model(
            db,
            SalesOrder(
                customer_id=payload.customer_id, reference=payload.reference.strip(), created_by=user["id"]
            ),
        )
        db.add(SalesOrderOwner(order_id=cursor.id, owner_id=profile.owner_id or user['id']))
        db.add_all(
            [
                SalesOrderLine(
                    sales_order_id=cursor.id,
                    material_id=line.material_id,
                    quantity=str(line.quantity),
                    unit_price=str(line.unit_price),
                )
                for line in payload.lines
            ]
        )
        return protect_amount(db, sales_order_data(db, cursor.id), user, cursor.id)


@router.post("/sales-orders/{order_id}/confirm")
def confirm_sales_order(order_id: int, user: dict = Depends(require("sales_order.confirm"))) -> dict:
    with orm_session(write=True) as db:
        row = (
            db.execute(select(SalesOrder.status).select_from(SalesOrder).where((SalesOrder.id == order_id)))
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "销售订单不存在")
        if row["status"] != "draft":
            raise HTTPException(409, "只能确认草稿销售订单")
        db.execute(
            update(SalesOrder)
            .where((SalesOrder.id == order_id))
            .values(status="confirmed", confirmed_by=user["id"], confirmed_at=func.current_timestamp())
        )
        return protect_amount(db, sales_order_data(db, order_id), user, order_id)


@router.post("/sales-orders/{order_id}/cancel")
def cancel_sales_order(order_id: int, user: dict = Depends(require("sales_order.cancel"))) -> dict:
    with orm_session(write=True) as db:
        row = (
            db.execute(select(SalesOrder.status).select_from(SalesOrder).where((SalesOrder.id == order_id)))
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "销售订单不存在")
        # 已确认出库不能通过取消订单抹去，须走独立销售退货单。
        if row["status"] not in ("draft", "confirmed"):
            raise HTTPException(409, "已出库或已取消的销售订单不可取消")
        db.execute(
            update(SalesOrder)
            .where((SalesOrder.id == order_id))
            .values(status="cancelled", cancelled_by=user["id"], cancelled_at=func.current_timestamp())
        )
        return protect_amount(db, sales_order_data(db, order_id), user, order_id)


@router.get("/shipments")
def list_shipments(_: dict = Depends(require("sales.view"))) -> list[dict]:
    with orm_session() as db:
        ids = [
            row for row in db.scalars(select(Shipment.id).select_from(Shipment).order_by(Shipment.id.desc()))
        ]
        return [shipment_data(db, shipment_id) for shipment_id in ids]


@router.post("/shipments", status_code=201)
def create_shipment(payload: ShipmentInput, user: dict = Depends(require("shipment.create"))) -> dict:
    if len({line.material_id for line in payload.lines}) != len(payload.lines):
        raise HTTPException(422, "一张出库单不能重复选择同一物料")
    with orm_session(write=True) as db:
        require_warehouse(db, payload.warehouse_id)
        order_line_ids = checked_order_lines(
            db, payload.sales_order_id, [(line.material_id, line.quantity) for line in payload.lines]
        )
        cursor = add_model(
            db,
            Shipment(
                sales_order_id=payload.sales_order_id,
                warehouse_id=payload.warehouse_id,
                reference=payload.reference.strip(),
                created_by=user["id"],
            ),
        )
        db.add_all(
            [
                ShipmentLine(
                    shipment_id=cursor.id,
                    sales_order_line_id=order_line_ids[line.material_id],
                    quantity=str(line.quantity),
                )
                for line in payload.lines
            ]
        )
        return shipment_data(db, cursor.id)


@router.post("/shipments/{shipment_id}/post")
def post_shipment(shipment_id: int, user: dict = Depends(require("shipment.post"))) -> dict:
    with orm_session(write=True) as db:
        # 写锁覆盖订单剩余量、仓库余额和库存流水，阻止并发出库超量或负库存。
        shipment = (
            db.execute(
                select(
                    Shipment.id,
                    Shipment.sales_order_id,
                    Shipment.warehouse_id,
                    Shipment.reference,
                    Shipment.status,
                    Shipment.created_by,
                    Shipment.posted_by,
                    Shipment.cancelled_by,
                    Shipment.created_at,
                    Shipment.posted_at,
                    Shipment.cancelled_at,
                )
                .select_from(Shipment)
                .where((Shipment.id == shipment_id))
            )
            .mappings()
            .first()
        )
        if not shipment:
            raise HTTPException(404, "出库单不存在")
        if shipment["status"] != "draft":
            raise HTTPException(409, "此出库单已处理")
        lines = (
            db.execute(
                select(ShipmentLine.id, ShipmentLine.quantity, SalesOrderLine.material_id)
                .select_from(ShipmentLine)
                .join(SalesOrderLine, (SalesOrderLine.id == ShipmentLine.sales_order_line_id))
                .where((ShipmentLine.shipment_id == shipment_id))
            )
            .mappings()
            .all()
        )
        checked_order_lines(
            db,
            shipment["sales_order_id"],
            [(line["material_id"], Decimal(line["quantity"])) for line in lines],
        )
        for line in lines:
            if balance(db, shipment["warehouse_id"], line["material_id"]) < Decimal(line["quantity"]):
                raise HTTPException(409, f"物料 #{line['material_id']} 在出库仓库的库存不足")
        for line in lines:
            add_model(
                db,
                StockMovement(
                    warehouse_id=shipment["warehouse_id"],
                    material_id=line["material_id"],
                    quantity=str(-Decimal(line["quantity"])),
                    source_type="shipment",
                    source_id=shipment_id,
                    source_line_id=line["id"],
                    created_by=user["id"],
                ),
            )
        db.execute(
            update(Shipment)
            .where((Shipment.id == shipment_id))
            .values(status="posted", posted_by=user["id"], posted_at=func.current_timestamp())
        )
        update_order_shipment_status(db, shipment["sales_order_id"])
        return shipment_data(db, shipment_id)


@router.post("/shipments/{shipment_id}/reverse", status_code=201)
def reverse_shipment(
    shipment_id: int, payload: ShipmentReverseInput, user: dict = Depends(require("shipment.reverse"))
) -> dict:
    with orm_session(write=True) as db:
        # 有效销售退货依赖原出库，先处理退货再冲销出库，防止重复入库。
        shipment = (
            db.execute(
                select(Shipment.status, Shipment.warehouse_id, Shipment.sales_order_id)
                .select_from(Shipment)
                .where((Shipment.id == shipment_id))
            )
            .mappings()
            .first()
        )
        if not shipment:
            raise HTTPException(404, "出库单不存在")
        if shipment["status"] != "posted":
            raise HTTPException(409, "只有已确认出库单可冲销")
        if (
            db.execute(
                select(literal(1))
                .select_from(ShipmentReversal)
                .where((ShipmentReversal.shipment_id == shipment_id))
            )
            .mappings()
            .first()
        ):
            raise HTTPException(409, "此出库单已冲销")
        lines = (
            db.execute(
                select(ShipmentLine.id, ShipmentLine.quantity, SalesOrderLine.material_id)
                .select_from(ShipmentLine)
                .join(SalesOrderLine, (SalesOrderLine.id == ShipmentLine.sales_order_line_id))
                .where((ShipmentLine.shipment_id == shipment_id))
            )
            .mappings()
            .all()
        )
        for line in lines:
            if returned_quantity(db, line["id"]) > 0:
                raise HTTPException(409, "原出库单仍有已确认销售退货，请先冲销退货")
        cursor = add_model(
            db, ShipmentReversal(shipment_id=shipment_id, reason=payload.reason, created_by=user["id"])
        )
        for line in lines:
            # 在原出库仓追加正向库存，不改写已确认的负向出库流水。
            add_model(
                db,
                StockMovement(
                    warehouse_id=shipment["warehouse_id"],
                    material_id=line["material_id"],
                    quantity=line["quantity"],
                    source_type="shipment_reversal",
                    source_id=cursor.id,
                    source_line_id=line["id"],
                    created_by=user["id"],
                ),
            )
        update_order_shipment_status(db, shipment["sales_order_id"])
        return shipment_data(db, shipment_id)


@router.post("/shipments/{shipment_id}/cancel")
def cancel_shipment(shipment_id: int, user: dict = Depends(require("shipment.cancel"))) -> dict:
    with orm_session(write=True) as db:
        row = (
            db.execute(select(Shipment.status).select_from(Shipment).where((Shipment.id == shipment_id)))
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "出库单不存在")
        if row["status"] != "draft":
            raise HTTPException(409, "只有出库草稿可取消；已出库须走销售退货单")
        db.execute(
            update(Shipment)
            .where((Shipment.id == shipment_id))
            .values(status="cancelled", cancelled_by=user["id"], cancelled_at=func.current_timestamp())
        )
        return shipment_data(db, shipment_id)
