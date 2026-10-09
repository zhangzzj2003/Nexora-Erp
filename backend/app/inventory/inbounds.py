"""其他入库单：不产生采购应付的正向库存来源。"""

from app.core.document_responses import NumberedRoute
from sqlalchemy import select, update, func, literal
from sqlalchemy.orm import Session, aliased

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.access.security import require
from app.core.orm import orm_session, add_model
from app.core import document_approval as approval
from app.core.approval_documents import inbound_snapshot, document_snapshot
from app.core.models import (
    Material,
    PhysicalLot,
    PhysicalLotAllocation,
    StockMovement,
    User,
    Warehouse,
    WarehouseInbound,
    WarehouseInboundLine,
    WarehouseInboundReversal,
)
from app.inventory.warehouse import balance, require_warehouse
from app.inventory.lot_inputs import PhysicalLotPartInput
from app.inventory.physical_lots import LotPart, post_lot_movement

UserCreator = aliased(User)
UserPoster = aliased(User)
UserRu = aliased(User)

router = APIRouter(route_class=NumberedRoute, prefix="/api/v1")


class InboundLineInput(BaseModel):
    material_id: int = Field(gt=0)
    quantity: Decimal

    @field_validator("quantity")
    @classmethod
    def valid_quantity(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 0 or value > 1_000_000 or value.as_tuple().exponent < -3:
            raise ValueError("数量须大于零、最多三位小数且不超过一百万")
        return value


class InboundInput(BaseModel):
    warehouse_id: int = Field(gt=0)
    reason: str
    note: str = Field(min_length=1, max_length=200)
    reference: str = Field(default="", max_length=100)
    lines: list[InboundLineInput] = Field(min_length=1, max_length=100)

    @field_validator("reason")
    @classmethod
    def valid_reason(cls, value: str) -> str:
        if value not in ("opening", "gift", "other"):
            raise ValueError("入库用途无效")
        return value

    @field_validator("note")
    @classmethod
    def valid_note(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("入库说明不能为空")
        return value.strip()


class ReverseInput(BaseModel):
    reason: str = Field(min_length=1, max_length=200)

    @field_validator("reason")
    @classmethod
    def valid_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("冲销原因不能为空")
        return value.strip()


class InboundLotLineInput(BaseModel):
    inbound_line_id: int = Field(gt=0)
    lots: list[PhysicalLotPartInput] = Field(min_length=1, max_length=20)
    # 新客户端携带已入库检查点；重复点击和旧快照不能再次占用剩余额度。
    expected_received_quantity: Decimal | None = Field(default=None, ge=0, le=1_000_000)

    @field_validator('expected_received_quantity')
    @classmethod
    def valid_checkpoint(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and (not value.is_finite() or value.as_tuple().exponent < -3):
            raise ValueError('已入库检查点须为非负数且最多三位小数')
        return value


class InboundPostInput(BaseModel):
    lines: list[InboundLotLineInput] = Field(min_length=1, max_length=100)


def received_by_line(db: Session, inbound_id: int) -> dict[int, Decimal]:
    # 从不可改写的正向库存流水累计，旧单无需回填，也不受后续领料消耗影响。
    result: dict[int, Decimal] = {}
    for line_id, value in db.execute(select(StockMovement.source_line_id, StockMovement.quantity)
            .where(StockMovement.source_type == 'other_inbound', StockMovement.source_id == inbound_id)):
        result[line_id] = result.get(line_id, Decimal(0)) + Decimal(value)
    return result


def inbound_data(db: Session, inbound_id: int) -> dict:
    row = (
        db.execute(
            select(
                WarehouseInbound.id,
                WarehouseInbound.warehouse_id,
                WarehouseInbound.reason,
                WarehouseInbound.note,
                WarehouseInbound.reference,
                WarehouseInbound.status,
                WarehouseInbound.created_by,
                WarehouseInbound.posted_by,
                WarehouseInbound.cancelled_by,
                WarehouseInbound.created_at,
                WarehouseInbound.posted_at,
                WarehouseInbound.cancelled_at,
                Warehouse.name.label("warehouse_name"),
                UserCreator.username.label("created_by_name"),
                UserPoster.username.label("posted_by_name"),
                WarehouseInboundReversal.id.label("reversal_id"),
                WarehouseInboundReversal.reason.label("reversal_reason"),
                WarehouseInboundReversal.created_by.label("reversed_by"),
                UserRu.username.label("reversed_by_name"),
                WarehouseInboundReversal.created_at.label("reversed_at"),
            )
            .select_from(WarehouseInbound)
            .join(Warehouse, (Warehouse.id == WarehouseInbound.warehouse_id))
            .join(UserCreator, (UserCreator.id == WarehouseInbound.created_by))
            .outerjoin(UserPoster, (UserPoster.id == WarehouseInbound.posted_by))
            .outerjoin(WarehouseInboundReversal, (WarehouseInboundReversal.inbound_id == WarehouseInbound.id))
            .outerjoin(UserRu, (UserRu.id == WarehouseInboundReversal.created_by))
            .where((WarehouseInbound.id == inbound_id))
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(404, "其他入库单不存在")
    lines = (
        db.execute(
            select(
                WarehouseInboundLine.id,
                WarehouseInboundLine.material_id,
                Material.sku,
                Material.name.label("material_name"),
                Material.unit,
                WarehouseInboundLine.quantity,
            )
            .select_from(WarehouseInboundLine)
            .join(Material, (Material.id == WarehouseInboundLine.material_id))
            .where((WarehouseInboundLine.inbound_id == inbound_id))
            .order_by(WarehouseInboundLine.id)
        )
        .mappings()
        .all()
    )
    lots_by_line: dict[int, list[dict]] = {}
    for line_id, lot, allocation in db.execute(
        select(StockMovement.source_line_id, PhysicalLot, PhysicalLotAllocation)
        .join(PhysicalLotAllocation, PhysicalLotAllocation.movement_id == StockMovement.id)
        .join(PhysicalLot, PhysicalLot.id == PhysicalLotAllocation.lot_id)
        .where(StockMovement.source_type == 'other_inbound', StockMovement.source_id == inbound_id)
        .order_by(StockMovement.source_line_id, PhysicalLotAllocation.id)
    ):
        lots_by_line.setdefault(line_id, []).append({
            'id': lot.id, 'code': lot.code, 'quantity': allocation.quantity,
            'supplier_lot': lot.supplier_lot, 'manufactured_on': lot.manufactured_on,
            'expires_on': lot.expires_on,
        })
    received = received_by_line(db, inbound_id)
    # 部分入库是流水推导出的展示状态，保留旧库状态约束与原始单据，不重建历史表。
    status = 'partially_posted' if row['status'] == 'draft' and any(received.values()) else row['status']
    return {**dict(row), 'status': status, 'approval': approval.case_data(approval.find_case(db, 'WarehouseInbound', inbound_id)),
            'reversal_approval': approval.case_data(approval.find_case(db, 'WarehouseInbound', inbound_id, 'reverse')),
            'lines': [
        {**dict(line), 'received_quantity': str(received.get(line['id'], Decimal(0))),
         'remaining_quantity': str(Decimal(line['quantity']) - received.get(line['id'], Decimal(0))),
         'physical_lots': lots_by_line.get(line['id'], [])} for line in lines]}


@router.get("/warehouse-inbounds")
def list_inbounds(_: dict = Depends(require("other_inbound.view"))) -> list[dict]:
    with orm_session() as db:
        ids = [
            row
            for row in db.scalars(
                select(WarehouseInbound.id).select_from(WarehouseInbound).order_by(WarehouseInbound.id.desc())
            )
        ]
        return [inbound_data(db, item_id) for item_id in ids]


@router.post("/warehouse-inbounds", status_code=201)
def create_inbound(payload: InboundInput, user: dict = Depends(require("other_inbound.create"))) -> dict:
    if len({line.material_id for line in payload.lines}) != len(payload.lines):
        raise HTTPException(422, "一张入库单不能重复选择同一物料")
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
        inbound_id = add_model(
            db,
            WarehouseInbound(
                warehouse_id=payload.warehouse_id,
                reason=payload.reason,
                note=payload.note,
                reference=payload.reference.strip(),
                created_by=user["id"],
            ),
        ).id
        db.add_all(
            [
                WarehouseInboundLine(
                    inbound_id=inbound_id, material_id=line.material_id, quantity=str(line.quantity)
                )
                for line in payload.lines
            ]
        )
        return inbound_data(db, inbound_id)


@router.post("/warehouse-inbounds/{inbound_id}/post")
def post_inbound(inbound_id: int, payload: InboundPostInput | None = None,
                 user: dict = Depends(require("other_inbound.post"))) -> dict:
    with orm_session(write=True) as db:
        # 状态与所有正向流水同事务提交，失败时整单不改变库存。
        source = (
            db.execute(
                select(WarehouseInbound.status, WarehouseInbound.warehouse_id)
                .select_from(WarehouseInbound)
                .where((WarehouseInbound.id == inbound_id))
            )
            .mappings()
            .first()
        )
        if not source:
            raise HTTPException(404, "其他入库单不存在")
        if source["status"] not in ("draft", "partially_posted"):
            raise HTTPException(409, "此入库单已处理")
        if db.scalar(select(WarehouseInboundReversal.id).where(WarehouseInboundReversal.inbound_id == inbound_id)):
            raise HTTPException(409, '此入库单已冲销，不能继续入库')
        # 无论普通入库还是登记实物批次，都必须核对同一份已批准明细后才能增加库存。
        approved = approval.require_approved(db, 'WarehouseInbound', inbound_id,
                                              inbound_snapshot(db, inbound_id), user['id'])
        lines = list(db.execute(select(WarehouseInboundLine.id, WarehouseInboundLine.material_id,
                                       WarehouseInboundLine.quantity)
                                .where(WarehouseInboundLine.inbound_id == inbound_id)
                                .order_by(WarehouseInboundLine.id)))
        lot_lines = {line.inbound_line_id: line for line in payload.lines} if payload else None
        line_ids = {line.id for line in lines}
        partial = payload is not None and all(line.expected_received_quantity is not None for line in payload.lines)
        if payload and any(line.expected_received_quantity is not None for line in payload.lines) and not partial:
            raise HTTPException(422, '分批入库须为本次所有明细提供已入库检查点')
        if lot_lines is not None and (len(lot_lines) != len(payload.lines)
                or not set(lot_lines) <= line_ids or not partial and set(lot_lines) != line_ids):
            raise HTTPException(422, '批次明细必须与其他入库明细逐行对应')
        received = received_by_line(db, inbound_id)
        for line in lines:
            remaining = Decimal(line.quantity) - received.get(line.id, Decimal(0))
            if (lot_lines is not None and line.id not in lot_lines) or remaining == 0:
                if lot_lines is not None and line.id in lot_lines:
                    raise HTTPException(409, '此明细已全部入库，请刷新后操作')
                continue
            parts = lot_lines[line.id].lots if lot_lines is not None else None
            quantity = sum((part.quantity for part in parts), Decimal(0)) if parts else remaining
            if partial and lot_lines[line.id].expected_received_quantity != received.get(line.id, Decimal(0)):
                raise HTTPException(409, '已入库数量已变化，请刷新后操作，避免重复入库')
            if quantity > remaining or quantity <= 0 or not partial and quantity != remaining:
                raise HTTPException(422, f'其他入库明细 #{line.id} 的批次数量须不超过剩余待入库量 {remaining}')
            movement = StockMovement(
                warehouse_id=source['warehouse_id'], material_id=line.material_id,
                quantity=str(quantity), source_type='other_inbound', source_id=inbound_id,
                source_line_id=line.id, created_by=user['id'])
            received[line.id] = received.get(line.id, Decimal(0)) + quantity
            if lot_lines is None:
                db.add(movement)
                continue
            # 每次续收追加新的批次序号，不覆盖前次批次或复用来源编号。
            offset = db.scalar(select(func.count()).select_from(PhysicalLotAllocation)
                .join(StockMovement, StockMovement.id == PhysicalLotAllocation.movement_id)
                .where(StockMovement.source_type == 'other_inbound', StockMovement.source_id == inbound_id,
                       StockMovement.source_line_id == line.id)) or 0
            lots = [add_model(db, PhysicalLot(
                material_id=line.material_id, code=f'O{inbound_id}-L{line.id}-P{offset + index}',
                source_kind='other_inbound', supplier_lot=part.supplier_lot,
                manufactured_on=part.manufactured_on.isoformat() if part.manufactured_on else None,
                expires_on=part.expires_on.isoformat() if part.expires_on else None,
                created_by=user['id'])) for index, part in enumerate(parts, 1)]
            post_lot_movement(db, movement, [
                LotPart(lot.id, part.quantity) for lot, part in zip(lots, parts)])
            for lot in lots:
                lot.origin_movement_id = movement.id
        complete = all(received.get(line.id, Decimal(0)) == Decimal(line.quantity) for line in lines)
        db.execute(
            update(WarehouseInbound)
            .where((WarehouseInbound.id == inbound_id))
            .values(status="posted" if complete else "draft", posted_by=user["id"], posted_at=func.current_timestamp())
        )
        if complete:
            approval.mark_executed(db, approved, user['id'])
        else:
            # 原批准总量不变，部分执行留下追加事件；收齐前仍按同一批准正文核对剩余额度。
            approved.version += 1
            approval.append_event(db, approved, 'execute', user['id'],
                                  f'部分入库：本次登记 {len(lot_lines)} 条明细；剩余数量待后续到货', approved.current_step)
        return inbound_data(db, inbound_id)


@router.post("/warehouse-inbounds/{inbound_id}/cancel")
def cancel_inbound(inbound_id: int, user: dict = Depends(require("other_inbound.cancel"))) -> dict:
    with orm_session(write=True) as db:
        # 已送审内容先撤回再取消，避免留下可执行的批准记录。
        if any(received_by_line(db, inbound_id).values()):
            raise HTTPException(409, '已部分入库不能取消原单，请按已入库数量申请冲销')
        pending = approval.find_case(db, 'WarehouseInbound', inbound_id)
        if pending and pending.status in ('submitted', 'approved'):
            raise HTTPException(409, '请先撤回审批，再取消入库单')
        cursor = db.execute(
            update(WarehouseInbound)
            .where(WarehouseInbound.id == inbound_id, WarehouseInbound.status == "draft")
            .values(status="cancelled", cancelled_by=user["id"], cancelled_at=func.current_timestamp())
        )
        if not cursor.rowcount:
            if (
                not db.execute(
                    select(literal(1))
                    .select_from(WarehouseInbound)
                    .where((WarehouseInbound.id == inbound_id))
                )
                .mappings()
                .first()
            ):
                raise HTTPException(404, "其他入库单不存在")
            raise HTTPException(409, "只能取消其他入库草稿")
        return inbound_data(db, inbound_id)


@router.post("/warehouse-inbounds/{inbound_id}/reverse", status_code=201)
def reverse_inbound(
    inbound_id: int, payload: ReverseInput, user: dict = Depends(require("other_inbound.reverse"))
) -> dict:
    with orm_session(write=True) as db:
        source = (
            db.execute(
                select(WarehouseInbound.status, WarehouseInbound.warehouse_id)
                .select_from(WarehouseInbound)
                .where((WarehouseInbound.id == inbound_id))
            )
            .mappings()
            .first()
        )
        if not source:
            raise HTTPException(404, "其他入库单不存在")
        if (
            (source["status"] != "posted" and not any(received_by_line(db, inbound_id).values()))
            or db.execute(
                select(literal(1))
                .select_from(WarehouseInboundReversal)
                .where((WarehouseInboundReversal.inbound_id == inbound_id))
            )
            .mappings()
            .first()
        ):
            raise HTTPException(409, "只能冲销尚未冲销的已确认其他入库")
        # 冲销是独立审批意图，批准的原因必须与实际冲销一致，原入库审批不能复用。
        approved = approval.require_approved(db, 'WarehouseInbound', inbound_id,
            document_snapshot(db, 'WarehouseInbound', inbound_id, 'reverse', payload.reason),
            user['id'], intent='reverse', permission='other_inbound.reverse')
        lines = (
            db.execute(
                select(
                    WarehouseInboundLine.id, WarehouseInboundLine.material_id, WarehouseInboundLine.quantity
                )
                .select_from(WarehouseInboundLine)
                .where((WarehouseInboundLine.inbound_id == inbound_id))
            )
            .mappings()
            .all()
        )
        received = received_by_line(db, inbound_id)
        for line in lines:
            if balance(db, source["warehouse_id"], line["material_id"]) < received.get(line['id'], Decimal(0)):
                raise HTTPException(409, f"物料 #{line['material_id']} 当前库存不足，不能冲销原入库")
        reversal_id = add_model(
            db, WarehouseInboundReversal(inbound_id=inbound_id, reason=payload.reason, created_by=user["id"])
        ).id
        # 逐次正向流水冲销；混合普通入库和批次入库时也只扣回实际收到的数量。
        originals = list(db.scalars(select(StockMovement).where(
            StockMovement.source_type == 'other_inbound', StockMovement.source_id == inbound_id)
            .order_by(StockMovement.id)))
        for original in originals:
            movement = StockMovement(
                warehouse_id=source['warehouse_id'], material_id=original.material_id,
                quantity=str(-Decimal(original.quantity)), source_type='other_inbound_reversal',
                source_id=reversal_id, source_line_id=original.source_line_id, created_by=user['id'])
            allocations = list(db.scalars(
                select(PhysicalLotAllocation)
                .where(PhysicalLotAllocation.movement_id == original.id)
                .order_by(PhysicalLotAllocation.id)))
            if allocations:
                if sum((Decimal(part.quantity) for part in allocations), Decimal(0)) != Decimal(original.quantity):
                    raise HTTPException(409, '原其他入库批次分配不完整，无法冲销')
                post_lot_movement(db, movement, [LotPart(
                    part.lot_id, -Decimal(part.quantity), part.id) for part in allocations])
            else:
                db.add(movement)
        approval.mark_executed(db, approved, user['id'], permission='other_inbound.reverse')
        return inbound_data(db, inbound_id)
