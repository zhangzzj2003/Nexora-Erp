"""仓库其他出库单；库存减少只发生在确认事务中。"""

from app.core.document_responses import NumberedRoute
from sqlalchemy import select, update, func, literal
from sqlalchemy.orm import Session, aliased

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.access.security import require
from app.core.orm import orm_session, add_model
from app.core.models import (
    Material,
    StockMovement,
    User,
    Warehouse,
    WarehouseOutbound,
    WarehouseOutboundLine,
    WarehouseOutboundReversal,
    MaintenanceJob,
    PhysicalLot,
    PhysicalLotAllocation,
    PurchaseReturnLine,
    ReceiptLine,
)
from app.inventory.warehouse import balance, require_warehouse
from app.inventory.physical_lots import LotPart, lot_balance, post_lot_movement

UserCreator = aliased(User)
UserPoster = aliased(User)
UserRu = aliased(User)

router = APIRouter(route_class=NumberedRoute, prefix="/api/v1")


class OutboundLineInput(BaseModel):
    material_id: int = Field(gt=0)
    quantity: Decimal

    @field_validator("quantity")
    @classmethod
    def valid_quantity(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 0 or value > 1_000_000 or value.as_tuple().exponent < -3:
            raise ValueError("数量须大于零、最多三位小数且不超过一百万")
        return value


class OutboundInput(BaseModel):
    warehouse_id: int = Field(gt=0)
    reason: str
    note: str = Field(min_length=1, max_length=200)
    reference: str = Field(default="", max_length=100)
    lines: list[OutboundLineInput] = Field(min_length=1, max_length=100)

    @field_validator("reason")
    @classmethod
    def valid_reason(cls, value: str) -> str:
        if value not in ("scrap", "sample", "other"):
            raise ValueError("出库用途无效")
        return value

    @field_validator("note")
    @classmethod
    def valid_note(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("出库说明不能为空")
        return value.strip()


class ReverseInput(BaseModel):
    reason: str = Field(min_length=1, max_length=200)

    @field_validator("reason")
    @classmethod
    def valid_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("冲销原因不能为空")
        return value.strip()


class OutboundLotPartInput(BaseModel):
    lot_id: int = Field(gt=0)
    quantity: Decimal

    @field_validator('quantity')
    @classmethod
    def valid_quantity(cls, value: Decimal) -> Decimal:
        return OutboundLineInput.valid_quantity(value)


class OutboundLotLineInput(BaseModel):
    outbound_line_id: int = Field(gt=0)
    lots: list[OutboundLotPartInput] = Field(min_length=1, max_length=20)


class OutboundPostInput(BaseModel):
    lines: list[OutboundLotLineInput] = Field(min_length=1, max_length=100)


def outbound_data(db: Session, outbound_id: int) -> dict:
    row = (
        db.execute(
            select(
                WarehouseOutbound.id,
                WarehouseOutbound.warehouse_id,
                WarehouseOutbound.source_kind,
                WarehouseOutbound.reason,
                WarehouseOutbound.note,
                WarehouseOutbound.reference,
                WarehouseOutbound.status,
                WarehouseOutbound.created_by,
                WarehouseOutbound.posted_by,
                WarehouseOutbound.cancelled_by,
                WarehouseOutbound.created_at,
                WarehouseOutbound.posted_at,
                WarehouseOutbound.cancelled_at,
                WarehouseOutbound.purchase_return_id,
                Warehouse.name.label("warehouse_name"),
                UserCreator.username.label("created_by_name"),
                UserPoster.username.label("posted_by_name"),
                WarehouseOutboundReversal.id.label("reversal_id"),
                WarehouseOutboundReversal.reason.label("reversal_reason"),
                WarehouseOutboundReversal.created_by.label("reversed_by"),
                UserRu.username.label("reversed_by_name"),
                WarehouseOutboundReversal.created_at.label("reversed_at"),
            )
            .select_from(WarehouseOutbound)
            .join(Warehouse, (Warehouse.id == WarehouseOutbound.warehouse_id))
            .join(UserCreator, (UserCreator.id == WarehouseOutbound.created_by))
            .outerjoin(UserPoster, (UserPoster.id == WarehouseOutbound.posted_by))
            .outerjoin(
                WarehouseOutboundReversal, (WarehouseOutboundReversal.outbound_id == WarehouseOutbound.id)
            )
            .outerjoin(UserRu, (UserRu.id == WarehouseOutboundReversal.created_by))
            .where((WarehouseOutbound.id == outbound_id))
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(404, "仓库出库单不存在")
    lines = (
        db.execute(
            select(
                WarehouseOutboundLine.id,
                WarehouseOutboundLine.material_id,
                Material.sku,
                Material.name.label("material_name"),
                Material.unit,
                WarehouseOutboundLine.quantity,
            )
            .select_from(WarehouseOutboundLine)
            .join(Material, (Material.id == WarehouseOutboundLine.material_id))
            .where((WarehouseOutboundLine.outbound_id == outbound_id))
            .order_by(WarehouseOutboundLine.id)
        )
        .mappings()
        .all()
    )
    return_line_ids: dict[int, int] = {}
    movement_source = 'other_outbound'
    movement_source_id = outbound_id
    if row['source_kind'] == 'purchase_return' and row['purchase_return_id'] is not None:
        movement_source = 'purchase_return'
        movement_source_id = row['purchase_return_id']
        outbound_by_material = {line['material_id']: line['id'] for line in lines}
        return_line_ids = {return_line.id: outbound_by_material[material_id]
                           for return_line, material_id in db.execute(
                               select(PurchaseReturnLine, ReceiptLine.material_id)
                               .join(ReceiptLine, ReceiptLine.id == PurchaseReturnLine.receipt_line_id)
                               .where(PurchaseReturnLine.purchase_return_id == movement_source_id))}
    lots_by_line: dict[int, list[dict]] = {}
    for line_id, lot, allocation in db.execute(
        select(StockMovement.source_line_id, PhysicalLot, PhysicalLotAllocation)
        .join(PhysicalLotAllocation, PhysicalLotAllocation.movement_id == StockMovement.id)
        .join(PhysicalLot, PhysicalLot.id == PhysicalLotAllocation.lot_id)
        .where(StockMovement.source_type == movement_source,
               StockMovement.source_id == movement_source_id)
        .order_by(StockMovement.source_line_id, PhysicalLotAllocation.id)
    ):
        outbound_line_id = return_line_ids.get(line_id, line_id)
        lots_by_line.setdefault(outbound_line_id, []).append({
            'id': lot.id, 'code': lot.code, 'quantity': format(-Decimal(allocation.quantity), 'f'),
            'source_kind': lot.source_kind, 'supplier_lot': lot.supplier_lot,
            'manufactured_on': lot.manufactured_on, 'expires_on': lot.expires_on,
        })
    return {**dict(row), 'lines': [
        {**dict(line), 'physical_lots': lots_by_line.get(line['id'], [])} for line in lines]}


@router.get("/warehouse-outbounds")
def list_outbounds(_: dict = Depends(require("other_outbound.view"))) -> list[dict]:
    with orm_session() as db:
        ids = [
            row
            for row in db.scalars(
                select(WarehouseOutbound.id)
                .select_from(WarehouseOutbound)
                .order_by(WarehouseOutbound.id.desc())
            )
        ]
        return [outbound_data(db, item_id) for item_id in ids]


@router.post("/warehouse-outbounds", status_code=201)
def create_outbound(payload: OutboundInput, user: dict = Depends(require("other_outbound.create"))) -> dict:
    if len({line.material_id for line in payload.lines}) != len(payload.lines):
        raise HTTPException(422, "一张出库单不能重复选择同一物料")
    with orm_session(write=True) as db:
        require_warehouse(db, payload.warehouse_id)
        for line in payload.lines:
            if (
                not db.execute(
                    select(literal(1)).select_from(Material).where((Material.id == line.material_id))
                )
                .mappings()
                .first()
            ):
                raise HTTPException(422, f"物料 #{line.material_id} 不存在")
        outbound_id = add_model(
            db,
            WarehouseOutbound(
                warehouse_id=payload.warehouse_id,
                reason=payload.reason,
                note=payload.note,
                reference=payload.reference.strip(),
                created_by=user["id"],
            ),
        ).id
        db.add_all(
            [
                WarehouseOutboundLine(
                    outbound_id=outbound_id, material_id=line.material_id, quantity=str(line.quantity)
                )
                for line in payload.lines
            ]
        )
        return outbound_data(db, outbound_id)


@router.get('/warehouse-outbounds/{outbound_id}/available-lots')
def available_outbound_lots(outbound_id: int, _: dict = Depends(require('other_outbound.post'))) -> dict:
    with orm_session() as db:
        outbound = db.get(WarehouseOutbound, outbound_id)
        if outbound is None:
            raise HTTPException(404, '仓库出库单不存在')
        if (outbound.status != 'draft' or outbound.source_kind not in ('other', 'purchase_return')
                or (outbound.source_kind == 'purchase_return' and outbound.purchase_return_id is None)):
            raise HTTPException(409, '只能查询待确认仓库出库单的可用批次')
        lines = list(db.scalars(select(WarehouseOutboundLine).where(
            WarehouseOutboundLine.outbound_id == outbound_id).order_by(WarehouseOutboundLine.id)))
        materials = {line.material_id for line in lines}
        lots = list(db.scalars(select(PhysicalLot).where(
            PhysicalLot.material_id.in_(materials)).order_by(PhysicalLot.id)))
        available = {material_id: [] for material_id in materials}
        for lot in lots:
            quantity = lot_balance(db, outbound.warehouse_id, lot.id)
            if quantity > 0:
                available[lot.material_id].append({
                    'lot_id': lot.id, 'code': lot.code, 'source_kind': lot.source_kind,
                    'quantity': format(quantity, 'f'), 'supplier_lot': lot.supplier_lot,
                    'manufactured_on': lot.manufactured_on, 'expires_on': lot.expires_on,
                })
        return {'outbound_id': outbound_id, 'warehouse_id': outbound.warehouse_id,
                'lines': [{'outbound_line_id': line.id, 'material_id': line.material_id,
                           'quantity': line.quantity, 'lots': available[line.material_id]}
                          for line in lines]}


@router.post("/warehouse-outbounds/{outbound_id}/post")
def post_outbound(outbound_id: int, payload: OutboundPostInput | None = None,
                  user: dict = Depends(require("other_outbound.post"))) -> dict:
    with orm_session(write=True) as db:
        # 写锁覆盖各行库存检查与扣减，整单要么确认要么完全不动库存。
        source = (
            db.execute(
                select(
                    WarehouseOutbound.status, WarehouseOutbound.warehouse_id, WarehouseOutbound.source_kind
                )
                .select_from(WarehouseOutbound)
                .where((WarehouseOutbound.id == outbound_id))
            )
            .mappings()
            .first()
        )
        if not source:
            raise HTTPException(404, "仓库出库单不存在")
        if source["source_kind"] == "purchase_return":
            # 退货流水仍由退货单生成；仓库闸口将选定批次传入同一写事务。
            from app.purchase.returns import post_return_in_transaction

            row = (
                db.execute(
                    select(WarehouseOutbound.purchase_return_id)
                    .select_from(WarehouseOutbound)
                    .where((WarehouseOutbound.id == outbound_id))
                )
                .mappings()
                .first()
            )
            if row['purchase_return_id'] is None:
                raise HTTPException(409, '采购退货出库单缺少关联退货单')
            lot_lines = None
            if payload is not None:
                outbound_lines = list(db.scalars(select(WarehouseOutboundLine).where(
                    WarehouseOutboundLine.outbound_id == outbound_id)))
                requested = {line.outbound_line_id: line for line in payload.lines}
                if len(requested) != len(payload.lines) or set(requested) != {
                        line.id for line in outbound_lines}:
                    raise HTTPException(422, '批次明细必须与采购退货出库明细逐行对应')
                lot_lines = {}
                for line in outbound_lines:
                    parts = requested[line.id].lots
                    if len({part.lot_id for part in parts}) != len(parts):
                        raise HTTPException(422, '一行退货不能重复选择同一实物批次')
                    if sum((part.quantity for part in parts), Decimal(0)) != Decimal(line.quantity):
                        raise HTTPException(422, f'采购退货出库明细 #{line.id} 的批次数量之和不匹配')
                    lot_lines[line.material_id] = [LotPart(part.lot_id, -part.quantity) for part in parts]
            post_return_in_transaction(db, row["purchase_return_id"], user["id"], lot_lines)
            return outbound_data(db, outbound_id)
        if source["status"] != "draft" or source["source_kind"] != "other":
            raise HTTPException(409, "此出库单不能按其他出库确认")
        lines = (
            db.execute(
                select(
                    WarehouseOutboundLine.id,
                    WarehouseOutboundLine.material_id,
                    WarehouseOutboundLine.quantity,
                )
                .select_from(WarehouseOutboundLine)
                .where((WarehouseOutboundLine.outbound_id == outbound_id))
            )
            .mappings()
            .all()
        )
        lot_lines = {line.outbound_line_id: line for line in payload.lines} if payload else None
        if lot_lines is not None and (len(lot_lines) != len(payload.lines)
                                      or set(lot_lines) != {line['id'] for line in lines}):
            raise HTTPException(422, '批次明细必须与其他出库明细逐行对应')
        for line in lines:
            if balance(db, source["warehouse_id"], line["material_id"]) < Decimal(line["quantity"]):
                raise HTTPException(409, f"物料 #{line['material_id']} 在来源仓库库存不足")
        for line in lines:
            movement = StockMovement(
                    warehouse_id=source["warehouse_id"],
                    material_id=line["material_id"],
                    quantity=str(-Decimal(line["quantity"])),
                    source_type="other_outbound",
                    source_id=outbound_id,
                    source_line_id=line["id"],
                    created_by=user["id"],
                )
            if lot_lines is None:
                db.add(movement)
                continue
            parts = lot_lines[line['id']].lots
            if len({part.lot_id for part in parts}) != len(parts):
                raise HTTPException(422, '一行出库不能重复选择同一实物批次')
            if sum((part.quantity for part in parts), Decimal(0)) != Decimal(line['quantity']):
                raise HTTPException(422, f"其他出库明细 #{line['id']} 的批次数量之和不匹配")
            post_lot_movement(db, movement, [LotPart(part.lot_id, -part.quantity) for part in parts])
        db.execute(
            update(WarehouseOutbound)
            .where((WarehouseOutbound.id == outbound_id))
            .values(status="posted", posted_by=user["id"], posted_at=func.current_timestamp())
        )
        return outbound_data(db, outbound_id)


@router.post("/warehouse-outbounds/{outbound_id}/cancel")
def cancel_outbound(outbound_id: int, user: dict = Depends(require("other_outbound.cancel"))) -> dict:
    with orm_session(write=True) as db:
        cursor = db.execute(
            update(WarehouseOutbound)
            .where(
                WarehouseOutbound.id == outbound_id,
                WarehouseOutbound.status == "draft",
                WarehouseOutbound.source_kind == "other",
            )
            .values(status="cancelled", cancelled_by=user["id"], cancelled_at=func.current_timestamp())
        )
        if not cursor.rowcount:
            if (
                not db.execute(
                    select(literal(1))
                    .select_from(WarehouseOutbound)
                    .where((WarehouseOutbound.id == outbound_id))
                )
                .mappings()
                .first()
            ):
                raise HTTPException(404, "仓库出库单不存在")
            raise HTTPException(409, "只能取消其他出库草稿")
        return outbound_data(db, outbound_id)


@router.post("/warehouse-outbounds/{outbound_id}/reverse", status_code=201)
def reverse_outbound(
    outbound_id: int, payload: ReverseInput, user: dict = Depends(require("other_outbound.reverse"))
) -> dict:
    with orm_session(write=True) as db:
        source = (
            db.execute(
                select(
                    WarehouseOutbound.status, WarehouseOutbound.warehouse_id, WarehouseOutbound.source_kind
                )
                .select_from(WarehouseOutbound)
                .where((WarehouseOutbound.id == outbound_id))
            )
            .mappings()
            .first()
        )
        if not source:
            raise HTTPException(404, "仓库出库单不存在")
        if (
            source["status"] != "posted"
            or source["source_kind"] != "other"
            or db.execute(
                select(literal(1))
                .select_from(WarehouseOutboundReversal)
                .where((WarehouseOutboundReversal.outbound_id == outbound_id))
            )
            .mappings()
            .first()
        ):
            raise HTTPException(409, "只能冲销尚未冲销的已确认其他出库")
        if db.scalar(select(MaintenanceJob.id).where(MaintenanceJob.parts_outbound_id == outbound_id,
                MaintenanceJob.status == 'accepted')):
            raise HTTPException(409, '耗材已被有效设备维护验收使用，先更正验收再冲销出库')
        reversal_id = add_model(
            db,
            WarehouseOutboundReversal(outbound_id=outbound_id, reason=payload.reason, created_by=user["id"]),
        ).id
        for line in db.execute(
            select(
                WarehouseOutboundLine.id, WarehouseOutboundLine.material_id, WarehouseOutboundLine.quantity
            )
            .select_from(WarehouseOutboundLine)
            .where((WarehouseOutboundLine.outbound_id == outbound_id))
        ).mappings():
            movement = StockMovement(
                    warehouse_id=source["warehouse_id"],
                    material_id=line["material_id"],
                    quantity=line["quantity"],
                    source_type="other_outbound_reversal",
                    source_id=reversal_id,
                    source_line_id=line["id"],
                    created_by=user["id"],
                )
            allocations = list(db.scalars(
                select(PhysicalLotAllocation)
                .join(StockMovement, StockMovement.id == PhysicalLotAllocation.movement_id)
                .where(StockMovement.source_type == 'other_outbound',
                       StockMovement.source_id == outbound_id,
                       StockMovement.source_line_id == line['id'])
                .order_by(PhysicalLotAllocation.id)))
            if allocations:
                if sum((Decimal(part.quantity) for part in allocations), Decimal(0)) != -Decimal(line['quantity']):
                    raise HTTPException(409, '原其他出库批次分配不完整，无法冲销')
                post_lot_movement(db, movement, [LotPart(
                    part.lot_id, -Decimal(part.quantity), part.id) for part in allocations])
            else:
                db.add(movement)
        return outbound_data(db, outbound_id)
