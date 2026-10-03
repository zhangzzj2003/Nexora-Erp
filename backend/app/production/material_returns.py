"""生产退料更正：沿原领料明细和仓库追加正向库存流水。"""

from sqlalchemy import select, update, func
from sqlalchemy.orm import Session
from sqlalchemy.engine import RowMapping
from decimal import Decimal
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.orm import orm_session, add_model
from app.core.models import (
    Material,
    MaterialIssue,
    MaterialIssueLine,
    MaterialIssueReversal,
    MaterialReturn,
    MaterialReturnLine,
    MaterialReturnReversal,
    PhysicalLot,
    PhysicalLotAllocation,
    PhysicalLotMovementEvidence,
    ProductionCompletion,
    ProductionCompletionReversal,
    StockMovement,
    User,
    Warehouse,
    WorkOrder,
    WorkOrderLine,
)
from app.access.security import require
from app.inventory.physical_lots import LotPart, post_lot_movement, unassigned_stock_quantity
from app.inventory.warehouse import balance
from app.inventory.lot_inputs import PhysicalLotPartInput
from app.production.work_orders import issued_quantity, posted_completion_totals, required_for_output
from app.production.cost_lock import ensure_unsettled
from app.core.period_lock import ensure_date_unlocked, ensure_movement_unlocked

router = APIRouter(prefix="/api/v1")


class MaterialReturnLineInput(BaseModel):
    material_issue_line_id: int = Field(gt=0)
    quantity: Decimal

    @field_validator("quantity")
    @classmethod
    def valid_quantity(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 0 or value > 1_000_000 or value.as_tuple().exponent < -3:
            raise ValueError("退料数量须大于零、最多三位小数且不超过一百万")
        return value


class MaterialReturnInput(BaseModel):
    material_issue_id: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=200)
    lines: list[MaterialReturnLineInput] = Field(min_length=1, max_length=100)

    @field_validator("reason")
    @classmethod
    def trim_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("退料原因不能为空")
        return value.strip()


class MaterialReturnLotPartInput(PhysicalLotPartInput):
    lot_id: int | None = Field(default=None, gt=0)

    @model_validator(mode='after')
    def existing_lot_has_no_new_origin(self):
        if self.lot_id is not None and any((
                self.supplier_lot, self.manufactured_on, self.expires_on)):
            raise ValueError('已有批次不能同时登记新批次来源字段')
        return self


class MaterialReturnLotLineInput(BaseModel):
    return_line_id: int = Field(gt=0)
    lots: list[MaterialReturnLotPartInput] = Field(min_length=1, max_length=20)


class MaterialReturnPostInput(BaseModel):
    lines: list[MaterialReturnLotLineInput] = Field(min_length=1, max_length=100)


class MaterialReturnReverseInput(BaseModel):
    reason: str = Field(min_length=1, max_length=200)

    @field_validator('reason')
    @classmethod
    def trim_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('冲销原因不能为空')
        return value.strip()


def source_lot_remaining(db: Session, issue_line_id: int) -> dict[int, Decimal]:
    """原领料批次减去已确认退回原批次的数量，新发现批次不冒充原批次。"""
    issued: dict[int, Decimal] = {}
    for lot_id, quantity in db.execute(select(PhysicalLotAllocation.lot_id,
            PhysicalLotAllocation.quantity).join(
                StockMovement, StockMovement.id == PhysicalLotAllocation.movement_id).where(
                    StockMovement.source_type == 'material_issue',
                    StockMovement.source_line_id == issue_line_id)):
        issued[lot_id] = issued.get(lot_id, Decimal(0)) - Decimal(quantity)
    returned: dict[int, Decimal] = {}
    for lot_id, quantity in db.execute(select(PhysicalLotAllocation.lot_id,
            PhysicalLotAllocation.quantity).join(
                StockMovement, StockMovement.id == PhysicalLotAllocation.movement_id).join(
                    MaterialReturnLine, MaterialReturnLine.id == StockMovement.source_line_id).join(
                        MaterialReturn,
                        MaterialReturn.id == MaterialReturnLine.material_return_id).where(
                            StockMovement.source_type == 'material_return',
                            MaterialReturnLine.material_issue_line_id == issue_line_id,
                            MaterialReturn.status == 'posted',
                            ~select(MaterialReturnReversal.id).where(
                                MaterialReturnReversal.material_return_id == MaterialReturn.id).exists())):
        returned[lot_id] = returned.get(lot_id, Decimal(0)) + Decimal(quantity)
    return {lot_id: quantity - returned.get(lot_id, Decimal(0))
            for lot_id, quantity in issued.items()}


def returned_quantity(db: Session, issue_line_id: int) -> Decimal:
    # 草稿不改变工单净领料；只有确认退料才能恢复可领数量。
    return sum(
        (
            Decimal(row)
            for row in db.scalars(
                select(MaterialReturnLine.quantity)
                .select_from(MaterialReturnLine)
                .join(MaterialReturn, MaterialReturn.id == MaterialReturnLine.material_return_id)
                .where(
                    MaterialReturnLine.material_issue_line_id == issue_line_id,
                    MaterialReturn.status == "posted",
                    ~select(MaterialReturnReversal.id).where(
                        MaterialReturnReversal.material_return_id == MaterialReturn.id).exists(),
                )
            )
        ),
        Decimal(0),
    )


def checked_lines(db: Session, issue_id: int, lines: list[tuple[int, Decimal]]) -> dict[int, RowMapping]:
    issue = (
        db.execute(
            select(
                MaterialIssue.status,
                WorkOrder.status.label("work_order_status"),
                WorkOrder.id.label("work_order_id"),
                WorkOrder.target_quantity,
            )
            .select_from(MaterialIssue)
            .join(WorkOrder, (WorkOrder.id == MaterialIssue.work_order_id))
            .where((MaterialIssue.id == issue_id))
        )
        .mappings()
        .first()
    )
    if not issue:
        raise HTTPException(422, "原领料单不存在")
    if issue["status"] != "posted":
        raise HTTPException(409, "只有已确认领料单可退料")
    if db.scalar(select(MaterialIssueReversal.id).where(
            MaterialIssueReversal.material_issue_id == issue_id)) is not None:
        raise HTTPException(409, "原领料已冲销，不能再退料")
    if issue["work_order_status"] != "in_progress":
        raise HTTPException(409, "只有生产中的工单可退料")
    known = {
        row["id"]: row
        for row in db.execute(
            select(
                MaterialIssueLine.id,
                MaterialIssueLine.work_order_line_id,
                WorkOrderLine.component_material_id,
                WorkOrderLine.required_quantity,
                MaterialIssueLine.quantity,
            )
            .select_from(MaterialIssueLine)
            .join(WorkOrderLine, (WorkOrderLine.id == MaterialIssueLine.work_order_line_id))
            .where((MaterialIssueLine.material_issue_id == issue_id))
        ).mappings()
    }
    result = {}
    posted_output, _, _ = posted_completion_totals(db, issue["work_order_id"])
    for line_id, quantity in lines:
        source = known.get(line_id)
        if not source:
            raise HTTPException(422, "退料明细不属于原领料单")
        if quantity > Decimal(source["quantity"]) - returned_quantity(db, line_id):
            raise HTTPException(409, f"领料明细 #{line_id} 超出可退数量")
        # 已报工消耗的最低需料不能再退回，否则成品入库会失去物料来源。
        minimum = required_for_output(
            Decimal(source["required_quantity"]), Decimal(issue["target_quantity"]), posted_output
        )
        if issued_quantity(db, source["work_order_line_id"]) - quantity < minimum:
            raise HTTPException(409, f"组件 #{source['component_material_id']} 已用于完工报工，不可退料")
        result[line_id] = source
    return result


def material_return_data(db: Session, return_id: int) -> dict:
    row = (
        db.execute(
            select(
                MaterialReturn.id,
                MaterialReturn.material_issue_id,
                MaterialReturn.reason,
                MaterialReturn.status,
                MaterialReturn.created_by,
                MaterialReturn.posted_by,
                MaterialReturn.cancelled_by,
                MaterialReturn.created_at,
                MaterialReturn.posted_at,
                MaterialReturn.cancelled_at,
                MaterialIssue.work_order_id,
                MaterialIssue.warehouse_id,
                Warehouse.name.label("warehouse_name"),
                User.username.label("created_by_name"),
            )
            .select_from(MaterialReturn)
            .join(MaterialIssue, (MaterialIssue.id == MaterialReturn.material_issue_id))
            .join(Warehouse, (Warehouse.id == MaterialIssue.warehouse_id))
            .join(User, (User.id == MaterialReturn.created_by))
            .where((MaterialReturn.id == return_id))
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(404, "生产退料单不存在")
    reversal = db.scalar(select(MaterialReturnReversal).where(
        MaterialReturnReversal.material_return_id == return_id))
    lines = (
        db.execute(
            select(
                MaterialReturnLine.id,
                MaterialReturnLine.material_issue_line_id,
                MaterialIssueLine.work_order_line_id,
                WorkOrderLine.component_material_id,
                Material.sku,
                Material.name.label("material_name"),
                Material.unit,
                MaterialReturnLine.quantity,
            )
            .select_from(MaterialReturnLine)
            .join(MaterialIssueLine, (MaterialIssueLine.id == MaterialReturnLine.material_issue_line_id))
            .join(WorkOrderLine, (WorkOrderLine.id == MaterialIssueLine.work_order_line_id))
            .join(Material, (Material.id == WorkOrderLine.component_material_id))
            .where((MaterialReturnLine.material_return_id == return_id))
            .order_by(MaterialReturnLine.id)
        )
        .mappings()
        .all()
    )
    result_lines = []
    for line in lines:
        lots = [{'id': lot.id, 'code': lot.code, 'source_kind': lot.source_kind,
                 'quantity': format(Decimal(allocation.quantity), 'f'),
                 'supplier_lot': lot.supplier_lot, 'manufactured_on': lot.manufactured_on,
                 'expires_on': lot.expires_on}
                for lot, allocation in db.execute(select(PhysicalLot, PhysicalLotAllocation).join(
                    PhysicalLotAllocation, PhysicalLotAllocation.lot_id == PhysicalLot.id).join(
                        StockMovement, StockMovement.id == PhysicalLotAllocation.movement_id).where(
                            StockMovement.source_type == 'material_return',
                            StockMovement.source_id == return_id,
                            StockMovement.source_line_id == line['id']).order_by(
                                PhysicalLotAllocation.id))]
        result_lines.append({**dict(line), 'physical_lots': lots})
    return {**dict(row), 'status': 'reversed' if reversal else row['status'],
            'reversal_id': reversal.id if reversal else None,
            'reversal_reason': reversal.reason if reversal else None,
            'reversed_by': reversal.created_by if reversal else None,
            'reversed_at': reversal.created_at if reversal else None,
            'lines': result_lines}


@router.get("/material-returns")
def list_material_returns(_: dict = Depends(require("production.view"))) -> list[dict]:
    with orm_session() as db:
        ids = [
            row
            for row in db.scalars(
                select(MaterialReturn.id).select_from(MaterialReturn).order_by(MaterialReturn.id.desc())
            )
        ]
        return [material_return_data(db, return_id) for return_id in ids]


@router.post("/material-returns", status_code=201)
def create_material_return(
    payload: MaterialReturnInput, user: dict = Depends(require("material_return.create"))
) -> dict:
    line_ids = [line.material_issue_line_id for line in payload.lines]
    if len(set(line_ids)) != len(line_ids):
        raise HTTPException(422, "一张退料单不能重复选择同一领料明细")
    with orm_session(write=True) as db:
        checked_lines(
            db,
            payload.material_issue_id,
            [(line.material_issue_line_id, line.quantity) for line in payload.lines],
        )
        cursor = add_model(
            db,
            MaterialReturn(
                material_issue_id=payload.material_issue_id, reason=payload.reason, created_by=user["id"]
            ),
        )
        db.add_all(
            [
                MaterialReturnLine(
                    material_return_id=cursor.id,
                    material_issue_line_id=line.material_issue_line_id,
                    quantity=str(line.quantity),
                )
                for line in payload.lines
            ]
        )
        return material_return_data(db, cursor.id)


@router.get('/material-returns/{return_id}/available-lots')
def available_material_return_lots(return_id: int,
                                   _: dict = Depends(require('material_return.post'))) -> dict:
    with orm_session() as db:
        material_return = db.get(MaterialReturn, return_id)
        if material_return is None:
            raise HTTPException(404, '生产退料单不存在')
        if material_return.status != 'draft':
            raise HTTPException(409, '只能查询生产退料草稿的原领料批次')
        warehouse_id = db.scalar(select(MaterialIssue.warehouse_id).where(
            MaterialIssue.id == material_return.material_issue_id))
        lines = list(db.execute(select(MaterialReturnLine.id,
                MaterialReturnLine.material_issue_line_id, MaterialReturnLine.quantity,
                WorkOrderLine.component_material_id).join(
                    MaterialIssueLine,
                    MaterialIssueLine.id == MaterialReturnLine.material_issue_line_id).join(
                        WorkOrderLine,
                        WorkOrderLine.id == MaterialIssueLine.work_order_line_id).where(
                            MaterialReturnLine.material_return_id == return_id).order_by(
                                MaterialReturnLine.id)).mappings())
        result = []
        for line in lines:
            remaining = source_lot_remaining(db, line['material_issue_line_id'])
            lots = []
            for lot_id, quantity in sorted(remaining.items()):
                if quantity <= 0:
                    continue
                lot = db.get(PhysicalLot, lot_id)
                lots.append({'lot_id': lot.id, 'code': lot.code,
                             'source_kind': lot.source_kind, 'quantity': format(quantity, 'f'),
                             'supplier_lot': lot.supplier_lot,
                             'manufactured_on': lot.manufactured_on,
                             'expires_on': lot.expires_on})
            result.append({'return_line_id': line['id'],
                           'material_issue_line_id': line['material_issue_line_id'],
                           'material_id': line['component_material_id'],
                           'quantity': line['quantity'], 'lots': lots})
        return {'return_id': return_id, 'material_issue_id': material_return.material_issue_id,
                'warehouse_id': warehouse_id, 'lines': result}


@router.post("/material-returns/{return_id}/post")
def post_material_return(return_id: int, payload: MaterialReturnPostInput | None = None,
                         user: dict = Depends(require("material_return.post"))) -> dict:
    with orm_session(write=True) as db:
        # 写锁覆盖累计退料量与正向流水，防止两份草稿同时确认导致超退。
        material_return = (
            db.execute(
                select(
                    MaterialReturn.id,
                    MaterialReturn.material_issue_id,
                    MaterialReturn.reason,
                    MaterialReturn.status,
                    MaterialReturn.created_by,
                    MaterialReturn.posted_by,
                    MaterialReturn.cancelled_by,
                    MaterialReturn.created_at,
                    MaterialReturn.posted_at,
                    MaterialReturn.cancelled_at,
                )
                .select_from(MaterialReturn)
                .where((MaterialReturn.id == return_id))
            )
            .mappings()
            .first()
        )
        if not material_return:
            raise HTTPException(404, "生产退料单不存在")
        if material_return["status"] != "draft":
            raise HTTPException(409, "此生产退料单已处理")
        lines = (
            db.execute(
                select(
                    MaterialReturnLine.id,
                    MaterialReturnLine.material_issue_line_id,
                    MaterialReturnLine.quantity,
                )
                .select_from(MaterialReturnLine)
                .where((MaterialReturnLine.material_return_id == return_id))
            )
            .mappings()
            .all()
        )
        source = checked_lines(
            db,
            material_return["material_issue_id"],
            [(line["material_issue_line_id"], Decimal(line["quantity"])) for line in lines],
        )
        warehouse_id = db.scalar(
            select(MaterialIssue.warehouse_id)
            .select_from(MaterialIssue)
            .where(MaterialIssue.id == material_return["material_issue_id"])
        )
        lot_lines = {line.return_line_id: line for line in payload.lines} if payload else None
        if lot_lines is not None and (len(lot_lines) != len(payload.lines)
                                      or set(lot_lines) != {line['id'] for line in lines}):
            raise HTTPException(422, '批次明细必须与生产退料明细逐行对应')
        for line in lines:
            movement = StockMovement(
                    warehouse_id=warehouse_id,
                    material_id=source[line["material_issue_line_id"]]["component_material_id"],
                    quantity=line["quantity"],
                    source_type="material_return",
                    source_id=return_id,
                    source_line_id=line["id"],
                    created_by=user["id"],
                )
            if lot_lines is None:
                db.add(movement)
                continue
            parts = lot_lines[line['id']].lots
            if sum((part.quantity for part in parts), Decimal(0)) != Decimal(line['quantity']):
                raise HTTPException(422, f'生产退料明细 #{line["id"]} 的批次数量之和不匹配')
            existing_ids = [part.lot_id for part in parts if part.lot_id is not None]
            if len(set(existing_ids)) != len(existing_ids):
                raise HTTPException(422, '一行生产退料不能重复选择同一原领料批次')
            remaining = source_lot_remaining(db, line['material_issue_line_id'])
            selected = []
            new_lots = []
            for index, part in enumerate(parts, 1):
                if part.lot_id is not None:
                    if part.lot_id not in remaining:
                        raise HTTPException(422, '退回批次不属于原领料明细')
                    if remaining[part.lot_id] < part.quantity:
                        raise HTTPException(409, '原领料批次剩余可退数量不足')
                    selected.append(LotPart(part.lot_id, part.quantity))
                    continue
                lot = add_model(db, PhysicalLot(
                    material_id=movement.material_id,
                    code=f'MR{return_id}-L{line["id"]}-P{index}', source_kind='material_return',
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
            update(MaterialReturn)
            .where((MaterialReturn.id == return_id))
            .values(status="posted", posted_by=user["id"], posted_at=func.current_timestamp())
        )
        return material_return_data(db, return_id)


@router.post("/material-returns/{return_id}/cancel")
def cancel_material_return(return_id: int, user: dict = Depends(require("material_return.cancel"))) -> dict:
    with orm_session(write=True) as db:
        row = (
            db.execute(
                select(MaterialReturn.status)
                .select_from(MaterialReturn)
                .where((MaterialReturn.id == return_id))
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "生产退料单不存在")
        if row["status"] != "draft":
            raise HTTPException(409, "已确认退料不可取消，须另行更正")
        db.execute(
            update(MaterialReturn)
            .where((MaterialReturn.id == return_id))
            .values(status="cancelled", cancelled_by=user["id"], cancelled_at=func.current_timestamp())
        )
        return material_return_data(db, return_id)


@router.post('/material-returns/{return_id}/reverse', status_code=201)
def reverse_material_return(return_id: int, payload: MaterialReturnReverseInput,
                            user: dict = Depends(require('material_return.reverse'))) -> dict:
    with orm_session(write=True) as db:
        material_return = db.get(MaterialReturn, return_id)
        if material_return is None:
            raise HTTPException(404, '生产退料单不存在')
        if material_return.status != 'posted':
            raise HTTPException(409, '只有已确认的生产退料单可冲销')
        if db.scalar(select(MaterialReturnReversal.id).where(
                MaterialReturnReversal.material_return_id == return_id)) is not None:
            raise HTTPException(409, '此生产退料单已冲销')
        issue = db.get(MaterialIssue, material_return.material_issue_id)
        order = db.get(WorkOrder, issue.work_order_id)
        if order.status != 'in_progress':
            raise HTTPException(409, '工单当前状态不允许冲销退料')
        ensure_unsettled(db, order.id)
        if db.scalar(select(ProductionCompletion.id).where(
                ProductionCompletion.work_order_id == order.id,
                (ProductionCompletion.status.in_(('draft', 'inspected')) | (
                    (ProductionCompletion.status == 'posted') & ~select(ProductionCompletionReversal.id)
                    .where(ProductionCompletionReversal.production_completion_id == ProductionCompletion.id)
                    .exists())))) is not None:
            raise HTTPException(409, '工单仍有有效报工，须先取消或冲销报工')
        ensure_date_unlocked(db, datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'))
        lines = list(db.execute(select(MaterialReturnLine, WorkOrderLine).join(
            MaterialIssueLine, MaterialIssueLine.id == MaterialReturnLine.material_issue_line_id).join(
                WorkOrderLine, WorkOrderLine.id == MaterialIssueLine.work_order_line_id).where(
                    MaterialReturnLine.material_return_id == return_id).order_by(
                        MaterialReturnLine.id)))
        originals = list(db.scalars(select(StockMovement).where(
            StockMovement.source_type == 'material_return', StockMovement.source_id == return_id)))
        movement_by_line = {movement.source_line_id: movement for movement in originals}
        if len(originals) != len(lines) or len(movement_by_line) != len(lines):
            raise HTTPException(409, '原退料库存流水不完整，无法安全冲销')
        stock_needed: dict[int, Decimal] = {}
        unassigned_needed: dict[int, Decimal] = {}
        movement_parts = []
        for line, order_line in lines:
            quantity = Decimal(line.quantity)
            original = movement_by_line.get(line.id)
            if (original is None or original.warehouse_id != issue.warehouse_id
                    or original.material_id != order_line.component_material_id
                    or Decimal(original.quantity) != quantity):
                raise HTTPException(409, '原退料库存流水与单据不一致，无法安全冲销')
            if issued_quantity(db, order_line.id) + quantity > Decimal(order_line.required_quantity):
                raise HTTPException(409, '退料冲销后工单将超出组件需料，须先更正后续补领')
            ensure_movement_unlocked(db, original.id)
            stock_needed[original.material_id] = stock_needed.get(original.material_id, Decimal(0)) + quantity
            allocations = list(db.scalars(select(PhysicalLotAllocation).where(
                PhysicalLotAllocation.movement_id == original.id).order_by(PhysicalLotAllocation.id)))
            evidence = list(db.scalars(select(PhysicalLotMovementEvidence).where(
                PhysicalLotMovementEvidence.movement_id == original.id)))
            if allocations and evidence:
                raise HTTPException(409, '原退料同时存在批次分配和现场补证，须先核对来源')
            if allocations:
                if sum((Decimal(part.quantity) for part in allocations), Decimal(0)) != quantity:
                    raise HTTPException(409, '原退料批次分配不完整，无法冲销')
                parts = [LotPart(part.lot_id, -Decimal(part.quantity), part.id) for part in allocations]
            elif evidence:
                amounts: dict[int, Decimal] = {}
                for part in evidence:
                    amounts[part.lot_id] = amounts.get(part.lot_id, Decimal(0)) + Decimal(part.quantity)
                if sum(amounts.values(), Decimal(0)) != quantity or any(
                        value <= 0 for value in amounts.values()):
                    raise HTTPException(409, '原退料现场补证未完整归批，无法冲销')
                parts = [LotPart(lot_id, -amount) for lot_id, amount in amounts.items()]
            else:
                parts = []
                unassigned_needed[original.material_id] = (
                    unassigned_needed.get(original.material_id, Decimal(0)) + quantity)
            movement_parts.append((line, original, parts))
        for material_id, quantity in stock_needed.items():
            if balance(db, issue.warehouse_id, material_id) < quantity:
                raise HTTPException(409, f'原退料仓物料 #{material_id} 库存不足，无法冲销')
        for material_id, quantity in unassigned_needed.items():
            if unassigned_stock_quantity(db, issue.warehouse_id, material_id) < quantity:
                raise HTTPException(409, f'原退料未分配物料 #{material_id} 的批次差额不足，无法冲销')
        reversal = add_model(db, MaterialReturnReversal(
            material_return_id=return_id, reason=payload.reason, created_by=user['id']))
        for line, original, parts in movement_parts:
            movement = StockMovement(
                warehouse_id=original.warehouse_id, material_id=original.material_id,
                quantity=str(-Decimal(line.quantity)), source_type='material_return_reversal',
                source_id=reversal.id, source_line_id=line.id, created_by=user['id'])
            if parts:
                post_lot_movement(db, movement, parts)
            else:
                db.add(movement)
        return material_return_data(db, return_id)
