"""销售退货单：逐项关联已出库明细，确认后追加正向库存流水。"""

from app.core.document_responses import NumberedRoute
from sqlalchemy import select, update, func, literal
from sqlalchemy.orm import Session, aliased
from sqlalchemy.engine import RowMapping
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.orm import orm_session, add_model
from app.core.models import (
    Customer,
    Material,
    PhysicalLot,
    PhysicalLotAllocation,
    SalesOrder,
    SalesOrderLine,
    SalesReturn,
    SalesReturnLine,
    SalesReturnReversal,
    Shipment,
    ShipmentLine,
    ShipmentReversal,
    StockMovement,
    User,
    Warehouse,
)
from app.inventory.warehouse import balance, require_warehouse
from app.inventory.physical_lots import LotPart, post_lot_movement
from app.inventory.lot_inputs import PhysicalLotPartInput
from app.access.security import require
from app.sales.customer_scope import (visible_customer_ids, require_visible_shipment,
    require_visible_return)

UserRu = aliased(User)
UserU = aliased(User)

router = APIRouter(route_class=NumberedRoute, prefix="/api/v1")


class SalesReturnLineInput(BaseModel):
    shipment_line_id: int = Field(gt=0)
    quantity: Decimal

    @field_validator("quantity")
    @classmethod
    def valid_quantity(cls, value: Decimal) -> Decimal:
        # 退货沿用库存三位小数精度，不允许用超小数量绕过累计限制。
        if not value.is_finite() or value <= 0 or value > 1_000_000 or value.as_tuple().exponent < -3:
            raise ValueError("退货数量须大于零、最多三位小数且不超过一百万")
        return value


class SalesReturnInput(BaseModel):
    shipment_id: int = Field(gt=0)
    warehouse_id: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=200)
    lines: list[SalesReturnLineInput] = Field(min_length=1, max_length=100)

    @field_validator("reason")
    @classmethod
    def trim_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("退货原因不能为空")
        return value.strip()


class SalesReturnReverseInput(BaseModel):
    reason: str = Field(min_length=1, max_length=200)

    @field_validator("reason")
    @classmethod
    def trim_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("冲销原因不能为空")
        return value.strip()


class SalesReturnLotPartInput(PhysicalLotPartInput):
    lot_id: int | None = Field(default=None, gt=0)

    @model_validator(mode='after')
    def existing_lot_has_no_new_origin(self):
        if self.lot_id is not None and any((
                self.supplier_lot, self.manufactured_on, self.expires_on)):
            raise ValueError('已有批次不能同时登记新批次来源字段')
        return self


class SalesReturnLotLineInput(BaseModel):
    return_line_id: int = Field(gt=0)
    lots: list[SalesReturnLotPartInput] = Field(min_length=1, max_length=20)


class SalesReturnPostInput(BaseModel):
    lines: list[SalesReturnLotLineInput] = Field(min_length=1, max_length=100)


def source_lot_remaining(db: Session, shipment_line_id: int) -> dict[int, Decimal]:
    """只允许回仓到原出库已确认的实物批次，并扣除未冲销的既往退货。"""
    shipped: dict[int, Decimal] = {}
    for lot_id, quantity in db.execute(select(PhysicalLotAllocation.lot_id,
            PhysicalLotAllocation.quantity).join(
                StockMovement, StockMovement.id == PhysicalLotAllocation.movement_id).where(
                    StockMovement.source_type == 'shipment',
                    StockMovement.source_line_id == shipment_line_id)):
        shipped[lot_id] = shipped.get(lot_id, Decimal(0)) - Decimal(quantity)
    returned: dict[int, Decimal] = {}
    for lot_id, quantity in db.execute(select(PhysicalLotAllocation.lot_id,
            PhysicalLotAllocation.quantity).join(
                StockMovement, StockMovement.id == PhysicalLotAllocation.movement_id).join(
                    SalesReturnLine, SalesReturnLine.id == StockMovement.source_line_id).join(
                        SalesReturn, SalesReturn.id == SalesReturnLine.sales_return_id).outerjoin(
                            SalesReturnReversal,
                            SalesReturnReversal.sales_return_id == SalesReturn.id).where(
                                StockMovement.source_type == 'sales_return',
                                SalesReturnLine.shipment_line_id == shipment_line_id,
                                SalesReturn.status == 'posted',
                                SalesReturnReversal.id.is_(None))):
        returned[lot_id] = returned.get(lot_id, Decimal(0)) + Decimal(quantity)
    return {lot_id: quantity - returned.get(lot_id, Decimal(0))
            for lot_id, quantity in shipped.items()}


def returned_quantity(db: Session, shipment_line_id: int) -> Decimal:
    # 已冲销退货仍留在历史中，但不再占用原出库的可退数量。
    return sum(
        (
            Decimal(row)
            for row in db.scalars(
                select(SalesReturnLine.quantity)
                .select_from(SalesReturnLine)
                .join(SalesReturn, SalesReturn.id == SalesReturnLine.sales_return_id)
                .outerjoin(SalesReturnReversal, SalesReturnReversal.sales_return_id == SalesReturn.id)
                .where(
                    SalesReturnLine.shipment_line_id == shipment_line_id,
                    SalesReturn.status == "posted",
                    SalesReturnReversal.id.is_(None),
                )
            )
        ),
        Decimal(0),
    )


def checked_return_lines(
    db: Session, shipment_id: int, lines: list[tuple[int, Decimal]]
) -> dict[int, RowMapping]:
    shipment = (
        db.execute(select(Shipment.status).select_from(Shipment).where((Shipment.id == shipment_id)))
        .mappings()
        .first()
    )
    if not shipment:
        raise HTTPException(422, "原出库单不存在")
    if shipment["status"] != "posted":
        raise HTTPException(409, "只有已确认出库单可退货")
    if (
        db.execute(
            select(literal(1))
            .select_from(ShipmentReversal)
            .where((ShipmentReversal.shipment_id == shipment_id))
        )
        .mappings()
        .first()
    ):
        raise HTTPException(409, "原出库单已冲销，不能退货")
    known = {
        row["id"]: row
        for row in db.execute(
            select(ShipmentLine.id, ShipmentLine.quantity, SalesOrderLine.material_id)
            .select_from(ShipmentLine)
            .join(SalesOrderLine, (SalesOrderLine.id == ShipmentLine.sales_order_line_id))
            .where((ShipmentLine.shipment_id == shipment_id))
        ).mappings()
    }
    result: dict[int, RowMapping] = {}
    for line_id, quantity in lines:
        item = known.get(line_id)
        if not item:
            raise HTTPException(422, "退货明细不属于原出库单")
        if quantity > Decimal(item["quantity"]) - returned_quantity(db, line_id):
            raise HTTPException(409, f"出库明细 #{line_id} 超出可退数量")
        result[line_id] = item
    return result


def sales_return_data(db: Session, return_id: int) -> dict:
    row = (
        db.execute(
            select(
                SalesReturn.id,
                SalesReturn.shipment_id,
                SalesReturn.warehouse_id,
                SalesReturn.reason,
                SalesReturn.status,
                SalesReturn.created_by,
                SalesReturn.posted_by,
                SalesReturn.cancelled_by,
                SalesReturn.created_at,
                SalesReturn.posted_at,
                SalesReturn.cancelled_at,
                Shipment.sales_order_id,
                Customer.name.label("customer_name"),
                Warehouse.name.label("warehouse_name"),
                UserU.username.label("created_by_name"),
                SalesReturnReversal.id.label("reversal_id"),
                SalesReturnReversal.reason.label("reversal_reason"),
                SalesReturnReversal.created_by.label("reversed_by"),
                UserRu.username.label("reversed_by_name"),
                SalesReturnReversal.created_at.label("reversed_at"),
            )
            .select_from(SalesReturn)
            .join(Shipment, (Shipment.id == SalesReturn.shipment_id))
            .join(SalesOrder, (SalesOrder.id == Shipment.sales_order_id))
            .join(Customer, (Customer.id == SalesOrder.customer_id))
            .join(Warehouse, (Warehouse.id == SalesReturn.warehouse_id))
            .join(UserU, (UserU.id == SalesReturn.created_by))
            .outerjoin(SalesReturnReversal, (SalesReturnReversal.sales_return_id == SalesReturn.id))
            .outerjoin(UserRu, (UserRu.id == SalesReturnReversal.created_by))
            .where((SalesReturn.id == return_id))
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(404, "销售退货单不存在")
    lines = []
    total = Decimal(0)
    for item in db.execute(
        select(
            SalesReturnLine.id,
            SalesReturnLine.shipment_line_id,
            SalesOrderLine.material_id,
            Material.sku,
            Material.name.label("material_name"),
            Material.unit,
            SalesReturnLine.quantity,
            SalesOrderLine.unit_price,
        )
        .select_from(SalesReturnLine)
        .join(ShipmentLine, (ShipmentLine.id == SalesReturnLine.shipment_line_id))
        .join(SalesOrderLine, (SalesOrderLine.id == ShipmentLine.sales_order_line_id))
        .join(Material, (Material.id == SalesOrderLine.material_id))
        .where((SalesReturnLine.sales_return_id == return_id))
        .order_by(SalesReturnLine.id)
    ).mappings():
        line_total = (Decimal(item["quantity"]) * Decimal(item["unit_price"])).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        total += line_total
        lots = [{"id": lot.id, "code": lot.code, "source_kind": lot.source_kind,
                 "quantity": format(Decimal(allocation.quantity), 'f'),
                 "supplier_lot": lot.supplier_lot, "manufactured_on": lot.manufactured_on,
                 "expires_on": lot.expires_on}
                for lot, allocation in db.execute(select(PhysicalLot, PhysicalLotAllocation).join(
                    PhysicalLotAllocation, PhysicalLotAllocation.lot_id == PhysicalLot.id).join(
                        StockMovement, StockMovement.id == PhysicalLotAllocation.movement_id).where(
                            StockMovement.source_type == 'sales_return',
                            StockMovement.source_id == return_id,
                            StockMovement.source_line_id == item['id']).order_by(PhysicalLotAllocation.id))]
        lines.append({**dict(item), "line_total": str(line_total), "physical_lots": lots})
    return {**dict(row), "lines": lines, "total_amount": str(total)}


@router.get("/sales-returns")
def list_sales_returns(user: dict = Depends(require("sales.view"))) -> list[dict]:
    with orm_session() as db:
        ids = [
            row
            for row in db.scalars(
                select(SalesReturn.id).join(Shipment, Shipment.id == SalesReturn.shipment_id)
                    .join(SalesOrder, SalesOrder.id == Shipment.sales_order_id)
                    .where(SalesOrder.customer_id.in_(visible_customer_ids(user)))
                    .order_by(SalesReturn.id.desc())
            )
        ]
        return [sales_return_data(db, return_id) for return_id in ids]


@router.post("/sales-returns", status_code=201)
def create_sales_return(
    payload: SalesReturnInput, user: dict = Depends(require("sales_return.create"))
) -> dict:
    if len({line.shipment_line_id for line in payload.lines}) != len(payload.lines):
        raise HTTPException(422, "一张退货单不能重复选择同一出库明细")
    with orm_session(write=True) as db:
        require_visible_shipment(db, payload.shipment_id, user)
        require_warehouse(db, payload.warehouse_id)
        checked_return_lines(
            db, payload.shipment_id, [(line.shipment_line_id, line.quantity) for line in payload.lines]
        )
        cursor = add_model(
            db,
            SalesReturn(
                shipment_id=payload.shipment_id,
                warehouse_id=payload.warehouse_id,
                reason=payload.reason,
                created_by=user["id"],
            ),
        )
        db.add_all(
            [
                SalesReturnLine(
                    sales_return_id=cursor.id,
                    shipment_line_id=line.shipment_line_id,
                    quantity=str(line.quantity),
                )
                for line in payload.lines
            ]
        )
        return sales_return_data(db, cursor.id)


@router.get('/sales-returns/{return_id}/available-lots')
def available_sales_return_lots(return_id: int,
                                user: dict = Depends(require('sales_return.post'))) -> dict:
    with orm_session() as db:
        sale_return = require_visible_return(db, return_id, user)
        if sale_return.status != 'draft':
            raise HTTPException(409, '只能查询退货草稿的原出库批次')
        lines = list(db.execute(select(SalesReturnLine.id, SalesReturnLine.shipment_line_id,
                SalesReturnLine.quantity, SalesOrderLine.material_id).join(
                    ShipmentLine, ShipmentLine.id == SalesReturnLine.shipment_line_id).join(
                        SalesOrderLine, SalesOrderLine.id == ShipmentLine.sales_order_line_id).where(
                            SalesReturnLine.sales_return_id == return_id).order_by(
                                SalesReturnLine.id)).mappings())
        result = []
        for line in lines:
            remaining = source_lot_remaining(db, line['shipment_line_id'])
            lots = []
            for lot_id, quantity in sorted(remaining.items()):
                if quantity <= 0:
                    continue
                lot = db.get(PhysicalLot, lot_id)
                lots.append({'lot_id': lot.id, 'code': lot.code,
                             'source_kind': lot.source_kind, 'quantity': format(quantity, 'f'),
                             'supplier_lot': lot.supplier_lot,
                             'manufactured_on': lot.manufactured_on, 'expires_on': lot.expires_on})
            result.append({'return_line_id': line['id'],
                           'shipment_line_id': line['shipment_line_id'],
                           'material_id': line['material_id'],
                           'quantity': line['quantity'], 'lots': lots})
        return {'return_id': return_id, 'shipment_id': sale_return.shipment_id,
                'warehouse_id': sale_return.warehouse_id, 'lines': result}


@router.post("/sales-returns/{return_id}/post")
def post_sales_return(return_id: int, payload: SalesReturnPostInput | None = None,
                      user: dict = Depends(require("sales_return.post"))) -> dict:
    with orm_session(write=True) as db:
        require_visible_return(db, return_id, user)
        # 同一写事务重新核对累计已退量；两张草稿无法并发退超原出库量。
        sale_return = (
            db.execute(
                select(
                    SalesReturn.id,
                    SalesReturn.shipment_id,
                    SalesReturn.warehouse_id,
                    SalesReturn.reason,
                    SalesReturn.status,
                    SalesReturn.created_by,
                    SalesReturn.posted_by,
                    SalesReturn.cancelled_by,
                    SalesReturn.created_at,
                    SalesReturn.posted_at,
                    SalesReturn.cancelled_at,
                )
                .select_from(SalesReturn)
                .where((SalesReturn.id == return_id))
            )
            .mappings()
            .first()
        )
        if not sale_return:
            raise HTTPException(404, "销售退货单不存在")
        if sale_return["status"] != "draft":
            raise HTTPException(409, "此销售退货单已处理")
        lines = (
            db.execute(
                select(SalesReturnLine.id, SalesReturnLine.shipment_line_id, SalesReturnLine.quantity)
                .select_from(SalesReturnLine)
                .where((SalesReturnLine.sales_return_id == return_id))
            )
            .mappings()
            .all()
        )
        source = checked_return_lines(
            db,
            sale_return["shipment_id"],
            [(line["shipment_line_id"], Decimal(line["quantity"])) for line in lines],
        )
        from app.sales.after_sales_rules import ensure_return_available
        ensure_return_available(db, return_id, lines)
        lot_lines = {line.return_line_id: line for line in payload.lines} if payload else None
        if lot_lines is not None and (len(lot_lines) != len(payload.lines)
                                      or set(lot_lines) != {line['id'] for line in lines}):
            raise HTTPException(422, '批次明细必须与销售退货明细逐行对应')
        for line in lines:
            # 原出库保留负向流水；退回的实物作为新来源入所选仓库。
            movement = StockMovement(
                warehouse_id=sale_return['warehouse_id'],
                material_id=source[line['shipment_line_id']]['material_id'],
                quantity=line['quantity'], source_type='sales_return',
                source_id=return_id, source_line_id=line['id'], created_by=user['id'],
            )
            if lot_lines is None:
                db.add(movement)
                continue
            parts = lot_lines[line['id']].lots
            if sum((part.quantity for part in parts), Decimal(0)) != Decimal(line['quantity']):
                raise HTTPException(422, f'销售退货明细 #{line["id"]} 的批次数量之和不匹配')
            existing_ids = [part.lot_id for part in parts if part.lot_id is not None]
            if len(set(existing_ids)) != len(existing_ids):
                raise HTTPException(422, '一行销售退货不能重复选择同一原出库批次')
            remaining = source_lot_remaining(db, line['shipment_line_id'])
            selected = []
            new_lots = []
            for index, part in enumerate(parts, 1):
                if part.lot_id is not None:
                    if part.lot_id not in remaining:
                        raise HTTPException(422, '退回批次不属于原出库明细')
                    if remaining[part.lot_id] < part.quantity:
                        raise HTTPException(409, '原出库批次剩余可退数量不足')
                    selected.append(LotPart(part.lot_id, part.quantity))
                    continue
                lot = add_model(db, PhysicalLot(
                    material_id=movement.material_id,
                    code=f'SR{return_id}-L{line["id"]}-P{index}', source_kind='sales_return',
                    supplier_lot=part.supplier_lot,
                    manufactured_on=part.manufactured_on.isoformat()
                    if part.manufactured_on else None,
                    expires_on=part.expires_on.isoformat() if part.expires_on else None,
                    created_by=user['id']))
                selected.append(LotPart(lot.id, part.quantity))
                new_lots.append(lot)
            post_lot_movement(db, movement, selected)
            for lot in new_lots:
                lot.origin_movement_id = movement.id
        db.execute(
            update(SalesReturn)
            .where((SalesReturn.id == return_id))
            .values(status="posted", posted_by=user["id"], posted_at=func.current_timestamp())
        )
        return sales_return_data(db, return_id)


@router.post("/sales-returns/{return_id}/cancel")
def cancel_sales_return(return_id: int, user: dict = Depends(require("sales_return.cancel"))) -> dict:
    with orm_session(write=True) as db:
        require_visible_return(db, return_id, user)
        row = (
            db.execute(
                select(SalesReturn.status).select_from(SalesReturn).where((SalesReturn.id == return_id))
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "销售退货单不存在")
        if row["status"] != "draft":
            raise HTTPException(409, "只有退货草稿可取消；已确认退货须另建更正单")
        db.execute(
            update(SalesReturn)
            .where((SalesReturn.id == return_id))
            .values(status="cancelled", cancelled_by=user["id"], cancelled_at=func.current_timestamp())
        )
        return sales_return_data(db, return_id)


@router.post("/sales-returns/{return_id}/reverse", status_code=201)
def reverse_sales_return(
    return_id: int, payload: SalesReturnReverseInput, user: dict = Depends(require("sales_return.reverse"))
) -> dict:
    with orm_session(write=True) as db:
        require_visible_return(db, return_id, user)
        from app.sales.after_sales_rules import ensure_return_reversible
        ensure_return_reversible(db, return_id)
        # 写锁内一次性核对退回仓的当前库存；不足时不能生成半套冲销流水。
        row = (
            db.execute(
                select(SalesReturn.status, SalesReturn.warehouse_id)
                .select_from(SalesReturn)
                .where((SalesReturn.id == return_id))
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "销售退货单不存在")
        if row["status"] != "posted":
            raise HTTPException(409, "只有已确认销售退货可冲销")
        if (
            db.execute(
                select(literal(1))
                .select_from(SalesReturnReversal)
                .where((SalesReturnReversal.sales_return_id == return_id))
            )
            .mappings()
            .first()
        ):
            raise HTTPException(409, "此销售退货单已冲销")
        lines = (
            db.execute(
                select(SalesReturnLine.id, SalesReturnLine.quantity, SalesOrderLine.material_id)
                .select_from(SalesReturnLine)
                .join(ShipmentLine, (ShipmentLine.id == SalesReturnLine.shipment_line_id))
                .join(SalesOrderLine, (SalesOrderLine.id == ShipmentLine.sales_order_line_id))
                .where((SalesReturnLine.sales_return_id == return_id))
            )
            .mappings()
            .all()
        )
        for line in lines:
            if balance(db, row["warehouse_id"], line["material_id"]) < Decimal(line["quantity"]):
                raise HTTPException(409, f"退回仓物料 #{line['material_id']} 库存不足，无法冲销")
        cursor = add_model(
            db, SalesReturnReversal(sales_return_id=return_id, reason=payload.reason, created_by=user["id"])
        )
        for line in lines:
            # 负向流水以原退货明细为来源行，财务则显示同额正向更正。
            movement = StockMovement(
                warehouse_id=row['warehouse_id'], material_id=line['material_id'],
                quantity=str(-Decimal(line['quantity'])),
                source_type='sales_return_reversal', source_id=cursor.id,
                source_line_id=line['id'], created_by=user['id'],
            )
            allocations = list(db.scalars(select(PhysicalLotAllocation).join(
                StockMovement, StockMovement.id == PhysicalLotAllocation.movement_id).where(
                    StockMovement.source_type == 'sales_return',
                    StockMovement.source_id == return_id,
                    StockMovement.source_line_id == line['id']).order_by(
                        PhysicalLotAllocation.id)))
            if allocations:
                if sum((Decimal(part.quantity) for part in allocations), Decimal(0)) != Decimal(line['quantity']):
                    raise HTTPException(409, '原销售退货批次分配不完整，无法冲销')
                post_lot_movement(db, movement, [LotPart(
                    part.lot_id, -Decimal(part.quantity), part.id) for part in allocations])
            else:
                db.add(movement)
        return sales_return_data(db, return_id)
