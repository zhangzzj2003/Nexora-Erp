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
    CustomerOwnerChange,
    Material,
    SalesOrder,
    SalesOrderLine,
    Shipment,
    ShipmentLine,
    ShipmentReversal,
    StockMovement,
    User,
    Warehouse,
    PhysicalLot,
    PhysicalLotAllocation,
)
from app.inventory.warehouse import TransferLineInput, balance, require_warehouse
from app.inventory.physical_lots import LotPart, lot_balance, post_lot_movement
from app.purchase.orders import PurchaseOrderLineInput
from app.sales.returns import returned_quantity
from app.access.security import require
from app.sales.customer_scope import (visible_customers, visible_customer_ids,
    require_visible_customer, require_visible_order, require_visible_shipment)
from app.sales.customer_names import duplicate_candidates, visible_name_rows

UserRu = aliased(User)
UserU = aliased(User)

router = APIRouter(prefix="/api/v1")


class CustomerInput(BaseModel):
    model_config = {'extra': 'forbid'}
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("客户名称不能为空")
        return value.strip()


class CustomerOwnerInput(BaseModel):
    model_config = {'extra': 'forbid'}
    owner_id: int = Field(strict=True, gt=0)
    version: int = Field(strict=True, gt=0)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator('reason')
    @classmethod
    def trim_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('请填写归属变更原因')
        return value.strip()


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


class ShipmentLotPartInput(BaseModel):
    lot_id: int = Field(gt=0)
    quantity: Decimal

    @field_validator('quantity')
    @classmethod
    def valid_quantity(cls, value: Decimal) -> Decimal:
        return TransferLineInput.valid_quantity(value)


class ShipmentLotLineInput(BaseModel):
    shipment_line_id: int = Field(gt=0)
    lots: list[ShipmentLotPartInput] = Field(min_length=1, max_length=20)


class ShipmentPostInput(BaseModel):
    lines: list[ShipmentLotLineInput] = Field(min_length=1, max_length=100)


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
    lots_by_line: dict[int, list[dict]] = {}
    for line_id, lot, allocation in db.execute(
        select(StockMovement.source_line_id, PhysicalLot, PhysicalLotAllocation)
        .join(PhysicalLotAllocation, PhysicalLotAllocation.movement_id == StockMovement.id)
        .join(PhysicalLot, PhysicalLot.id == PhysicalLotAllocation.lot_id)
        .where(StockMovement.source_type == 'shipment', StockMovement.source_id == shipment_id)
        .order_by(StockMovement.source_line_id, PhysicalLotAllocation.id)
    ):
        lots_by_line.setdefault(line_id, []).append({
            'id': lot.id, 'code': lot.code, 'quantity': format(-Decimal(allocation.quantity), 'f'),
            'source_kind': lot.source_kind, 'supplier_lot': lot.supplier_lot,
            'manufactured_on': lot.manufactured_on, 'expires_on': lot.expires_on,
        })
    result_lines = []
    for item in lines:
        returned = returned_quantity(db, item["id"])
        result_lines.append(
            {
                **dict(item),
                'physical_lots': lots_by_line.get(item['id'], []),
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


@router.get("/customers")
def list_customers(user: dict = Depends(require("sales.view"))) -> list[dict]:
    with orm_session() as db:
        return [
            dict(row)
            for row in db.execute(
                visible_customers(select(Customer.id, Customer.name, Customer.owner_id, Customer.version)
                    .select_from(Customer).order_by(Customer.name), user)
            ).mappings()
        ]


@router.post('/customers/duplicate-candidates')
def customer_duplicate_candidates(payload: CustomerInput,
                                  user: dict = Depends(require('customer.manage'))) -> list[dict]:
    with orm_session() as db:
        return duplicate_candidates(payload.name, visible_name_rows(db, user))


@router.post("/customers", status_code=201)
def create_customer(payload: CustomerInput, user: dict = Depends(require("customer.manage"))) -> dict:
    with orm_session(write=True) as db:
        try:
            cursor = add_model(db, Customer(name=payload.name, owner_id=user['id'], version=1))
            db.add(CustomerOwnerChange(customer_id=cursor.id, before_owner_id=None,
                after_owner_id=user['id'], version=1, reason='建立客户', changed_by=user['id']))
        except IntegrityError:
            raise HTTPException(409, "客户名称已存在") from None
        return {"id": cursor.id, "name": payload.name, "owner_id": user['id'], "version": 1}


@router.put('/customers/{customer_id}/owner')
def assign_customer_owner(customer_id: int, payload: CustomerOwnerInput,
                          user: dict = Depends(require('customer.assign'))) -> dict:
    with orm_session(write=True) as db:
        customer = db.get(Customer, customer_id)
        if customer is None:
            raise HTTPException(404, '客户不存在')
        if customer.version != payload.version:
            raise HTTPException(409, '客户归属版本已变化，请刷新后重试')
        owner = db.get(User, payload.owner_id)
        if owner is None or not owner.is_active:
            raise HTTPException(422, '负责人须为启用的账号')
        if customer.owner_id == owner.id:
            raise HTTPException(409, '客户已归属该负责人')
        previous = customer.owner_id
        customer.owner_id = owner.id
        customer.version += 1
        db.add(CustomerOwnerChange(customer_id=customer.id, before_owner_id=previous,
            after_owner_id=owner.id, version=customer.version, reason=payload.reason,
            changed_by=user['id']))
        return {'id': customer.id, 'name': customer.name,
                'owner_id': customer.owner_id, 'version': customer.version}


@router.get('/customers/{customer_id}/owner-changes')
def customer_owner_changes(customer_id: int,
                           user: dict = Depends(require('customer.assign'))) -> list[dict]:
    with orm_session() as db:
        require_visible_customer(db, customer_id, user)
        return [{'id': row.id, 'customer_id': row.customer_id,
                 'before_owner_id': row.before_owner_id, 'after_owner_id': row.after_owner_id,
                 'version': row.version, 'reason': row.reason, 'changed_by': row.changed_by,
                 'created_at': row.created_at}
                for row in db.scalars(select(CustomerOwnerChange)
                    .where(CustomerOwnerChange.customer_id == customer_id)
                    .order_by(CustomerOwnerChange.id.desc()))]


@router.get("/sales-orders")
def list_sales_orders(user: dict = Depends(require("sales.view"))) -> list[dict]:
    with orm_session() as db:
        ids = [
            row
            for row in db.scalars(
                select(SalesOrder.id).where(SalesOrder.customer_id.in_(visible_customer_ids(user)))
                    .order_by(SalesOrder.id.desc())
            )
        ]
        return [sales_order_data(db, order_id) for order_id in ids]


def create_sales_order_in_session(db: Session, payload: SalesOrderInput, user_id: int) -> dict:
    if len({line.material_id for line in payload.lines}) != len(payload.lines):
        raise HTTPException(422, "一张销售订单不能重复选择同一物料")
    if (
        not db.execute(
            select(literal(1)).select_from(Customer).where((Customer.id == payload.customer_id))
        )
        .mappings()
        .first()
    ):
        raise HTTPException(422, "客户不存在")
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
            customer_id=payload.customer_id, reference=payload.reference.strip(), created_by=user_id
        ),
    )
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
    return sales_order_data(db, cursor.id)


@router.post("/sales-orders", status_code=201)
def create_sales_order(payload: SalesOrderInput, user: dict = Depends(require("sales_order.create"))) -> dict:
    with orm_session(write=True) as db:
        require_visible_customer(db, payload.customer_id, user)
        return create_sales_order_in_session(db, payload, user["id"])

@router.post("/sales-orders/{order_id}/confirm")
def confirm_sales_order(order_id: int, user: dict = Depends(require("sales_order.confirm"))) -> dict:
    with orm_session(write=True) as db:
        require_visible_order(db, order_id, user)
        from app.sales.after_sales_rules import ensure_replacement_available
        ensure_replacement_available(db, order_id)
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
        return sales_order_data(db, order_id)


@router.post("/sales-orders/{order_id}/cancel")
def cancel_sales_order(order_id: int, user: dict = Depends(require("sales_order.cancel"))) -> dict:
    with orm_session(write=True) as db:
        require_visible_order(db, order_id, user)
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
        return sales_order_data(db, order_id)


@router.get("/shipments")
def list_shipments(user: dict = Depends(require("sales.view"))) -> list[dict]:
    with orm_session() as db:
        ids = [
            row for row in db.scalars(select(Shipment.id).join(SalesOrder,
                SalesOrder.id == Shipment.sales_order_id).where(
                    SalesOrder.customer_id.in_(visible_customer_ids(user))).order_by(Shipment.id.desc()))
        ]
        return [shipment_data(db, shipment_id) for shipment_id in ids]


@router.post("/shipments", status_code=201)
def create_shipment(payload: ShipmentInput, user: dict = Depends(require("shipment.create"))) -> dict:
    if len({line.material_id for line in payload.lines}) != len(payload.lines):
        raise HTTPException(422, "一张出库单不能重复选择同一物料")
    with orm_session(write=True) as db:
        require_visible_order(db, payload.sales_order_id, user)
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


@router.get('/shipments/{shipment_id}/available-lots')
def available_shipment_lots(shipment_id: int, user: dict = Depends(require('shipment.post'))) -> dict:
    with orm_session() as db:
        shipment = require_visible_shipment(db, shipment_id, user)
        if shipment.status != 'draft':
            raise HTTPException(409, '只能查询销售出库草稿的可用批次')
        lines = list(db.execute(
            select(ShipmentLine.id, ShipmentLine.quantity, SalesOrderLine.material_id)
            .join(SalesOrderLine, SalesOrderLine.id == ShipmentLine.sales_order_line_id)
            .where(ShipmentLine.shipment_id == shipment_id).order_by(ShipmentLine.id)).mappings())
        materials = {line['material_id'] for line in lines}
        lots = list(db.scalars(select(PhysicalLot).where(
            PhysicalLot.material_id.in_(materials)).order_by(PhysicalLot.id)))
        available = {material_id: [] for material_id in materials}
        for lot in lots:
            quantity = lot_balance(db, shipment.warehouse_id, lot.id)
            if quantity > 0:
                available[lot.material_id].append({
                    'lot_id': lot.id, 'code': lot.code, 'source_kind': lot.source_kind,
                    'quantity': format(quantity, 'f'), 'supplier_lot': lot.supplier_lot,
                    'manufactured_on': lot.manufactured_on, 'expires_on': lot.expires_on,
                })
        return {'shipment_id': shipment_id, 'warehouse_id': shipment.warehouse_id,
                'lines': [{'shipment_line_id': line['id'], 'material_id': line['material_id'],
                           'quantity': line['quantity'], 'lots': available[line['material_id']]}
                          for line in lines]}


@router.post("/shipments/{shipment_id}/post")
def post_shipment(shipment_id: int, payload: ShipmentPostInput | None = None,
                  user: dict = Depends(require("shipment.post"))) -> dict:
    with orm_session(write=True) as db:
        require_visible_shipment(db, shipment_id, user)
        from app.sales.after_sales_rules import ensure_replacement_available
        linked_shipment = db.get(Shipment, shipment_id)
        if linked_shipment:
            ensure_replacement_available(db, linked_shipment.sales_order_id)
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
        lot_lines = {line.shipment_line_id: line for line in payload.lines} if payload else None
        if lot_lines is not None and (len(lot_lines) != len(payload.lines)
                                      or set(lot_lines) != {line['id'] for line in lines}):
            raise HTTPException(422, '批次明细必须与销售出库明细逐行对应')
        for line in lines:
            if balance(db, shipment["warehouse_id"], line["material_id"]) < Decimal(line["quantity"]):
                raise HTTPException(409, f"物料 #{line['material_id']} 在出库仓库的库存不足")
        for line in lines:
            movement = StockMovement(
                    warehouse_id=shipment["warehouse_id"],
                    material_id=line["material_id"],
                    quantity=str(-Decimal(line["quantity"])),
                    source_type="shipment",
                    source_id=shipment_id,
                    source_line_id=line["id"],
                    created_by=user["id"],
                )
            if lot_lines is None:
                db.add(movement)
                continue
            parts = lot_lines[line['id']].lots
            if len({part.lot_id for part in parts}) != len(parts):
                raise HTTPException(422, '一行销售出库不能重复选择同一实物批次')
            if sum((part.quantity for part in parts), Decimal(0)) != Decimal(line['quantity']):
                raise HTTPException(422, f'销售出库明细 #{line["id"]} 的批次数量之和不匹配')
            post_lot_movement(db, movement, [LotPart(part.lot_id, -part.quantity) for part in parts])
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
        require_visible_shipment(db, shipment_id, user)
        from app.sales.after_sales_rules import ensure_shipment_reversible
        ensure_shipment_reversible(db, shipment_id)
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
            movement = StockMovement(
                    warehouse_id=shipment["warehouse_id"],
                    material_id=line["material_id"],
                    quantity=line["quantity"],
                    source_type="shipment_reversal",
                    source_id=cursor.id,
                    source_line_id=line["id"],
                    created_by=user["id"],
                )
            allocations = list(db.scalars(
                select(PhysicalLotAllocation)
                .join(StockMovement, StockMovement.id == PhysicalLotAllocation.movement_id)
                .where(StockMovement.source_type == 'shipment',
                       StockMovement.source_id == shipment_id,
                       StockMovement.source_line_id == line['id'])
                .order_by(PhysicalLotAllocation.id)))
            if allocations:
                if sum((Decimal(part.quantity) for part in allocations), Decimal(0)) != -Decimal(line['quantity']):
                    raise HTTPException(409, '原销售出库批次分配不完整，无法冲销')
                post_lot_movement(db, movement, [LotPart(
                    part.lot_id, -Decimal(part.quantity), part.id) for part in allocations])
            else:
                db.add(movement)
        update_order_shipment_status(db, shipment["sales_order_id"])
        return shipment_data(db, shipment_id)


@router.post("/shipments/{shipment_id}/cancel")
def cancel_shipment(shipment_id: int, user: dict = Depends(require("shipment.cancel"))) -> dict:
    with orm_session(write=True) as db:
        require_visible_shipment(db, shipment_id, user)
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
