"""生产领料单与库存流水；确认时核对工单剩余需料和源仓库存。"""

from app.core import document_approval as approval
from app.core.approval_documents import material_issue_snapshot
from app.core.document_responses import NumberedRoute
from sqlalchemy import select, update, func
from sqlalchemy.orm import Session
from sqlalchemy.engine import RowMapping
from decimal import Decimal
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.core.orm import orm_session, add_model
from app.core.models import (
    Material,
    MaterialIssue,
    MaterialIssueLine,
    MaterialIssueReversal,
    MaterialReturn,
    MaterialReturnReversal,
    ProductionCompletion,
    ProductionCompletionReversal,
    ProductionCostEntry,
    ProductionCostReversal,
    PhysicalLot,
    PhysicalLotAllocation,
    PhysicalLotMovementEvidence,
    StockMovement,
    User,
    Warehouse,
    WorkOrder,
    WorkOrderLine,
)
from app.inventory.warehouse import balance, require_warehouse
from app.inventory.physical_lots import LotPart, lot_balance, post_lot_movement
from app.access.security import require
from app.production.material_returns import returned_quantity
from app.production.work_orders import issued_quantity
from app.production.cost_lock import ensure_unsettled
from app.core.period_lock import ensure_date_unlocked, ensure_movement_unlocked

router = APIRouter(route_class=NumberedRoute, prefix="/api/v1")


class MaterialIssueLineInput(BaseModel):
    work_order_line_id: int = Field(gt=0)
    quantity: Decimal

    @field_validator("quantity")
    @classmethod
    def valid_quantity(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 0 or value > 1_000_000 or value.as_tuple().exponent < -3:
            raise ValueError("领料数量须大于零、最多三位小数且不超过一百万")
        return value


class MaterialIssueInput(BaseModel):
    work_order_id: int = Field(gt=0)
    warehouse_id: int = Field(gt=0)
    reference: str = Field(default="", max_length=100)
    lines: list[MaterialIssueLineInput] = Field(min_length=1, max_length=100)


class MaterialIssueLotPartInput(BaseModel):
    lot_id: int = Field(gt=0)
    quantity: Decimal

    @field_validator('quantity')
    @classmethod
    def valid_quantity(cls, value: Decimal) -> Decimal:
        return MaterialIssueLineInput.valid_quantity(value)


class MaterialIssueLotLineInput(BaseModel):
    material_issue_line_id: int = Field(gt=0)
    lots: list[MaterialIssueLotPartInput] = Field(min_length=1, max_length=20)


class MaterialIssuePostInput(BaseModel):
    lines: list[MaterialIssueLotLineInput] = Field(min_length=1, max_length=100)


class MaterialIssueReversalInput(BaseModel):
    reason: str = Field(min_length=1, max_length=200)

    @field_validator('reason')
    @classmethod
    def trim_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('冲销原因不能为空')
        return value.strip()


def material_issue_data(db: Session, issue_id: int) -> dict:
    row = (
        db.execute(
            select(
                MaterialIssue.id,
                MaterialIssue.work_order_id,
                MaterialIssue.warehouse_id,
                MaterialIssue.reference,
                MaterialIssue.status,
                MaterialIssue.created_by,
                MaterialIssue.posted_by,
                MaterialIssue.cancelled_by,
                MaterialIssue.created_at,
                MaterialIssue.posted_at,
                MaterialIssue.cancelled_at,
                Warehouse.name.label("warehouse_name"),
                User.username.label("created_by_name"),
            )
            .select_from(MaterialIssue)
            .join(Warehouse, (Warehouse.id == MaterialIssue.warehouse_id))
            .join(User, (User.id == MaterialIssue.created_by))
            .where((MaterialIssue.id == issue_id))
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(404, "生产领料单不存在")
    reversal = db.scalar(select(MaterialIssueReversal).where(
        MaterialIssueReversal.material_issue_id == issue_id))
    lines = (
        db.execute(
            select(
                MaterialIssueLine.id,
                MaterialIssueLine.work_order_line_id,
                WorkOrderLine.component_material_id,
                Material.sku,
                Material.name.label("material_name"),
                Material.unit,
                MaterialIssueLine.quantity,
            )
            .select_from(MaterialIssueLine)
            .join(WorkOrderLine, (WorkOrderLine.id == MaterialIssueLine.work_order_line_id))
            .join(Material, (Material.id == WorkOrderLine.component_material_id))
            .where((MaterialIssueLine.material_issue_id == issue_id))
            .order_by(MaterialIssueLine.id)
        )
        .mappings()
        .all()
    )
    lots_by_line: dict[int, list[dict]] = {}
    for line_id, lot, allocation in db.execute(
        select(StockMovement.source_line_id, PhysicalLot, PhysicalLotAllocation)
        .join(PhysicalLotAllocation, PhysicalLotAllocation.movement_id == StockMovement.id)
        .join(PhysicalLot, PhysicalLot.id == PhysicalLotAllocation.lot_id)
        .where(StockMovement.source_type == 'material_issue', StockMovement.source_id == issue_id)
        .order_by(StockMovement.source_line_id, PhysicalLotAllocation.id)
    ):
        lots_by_line.setdefault(line_id, []).append({
            'id': lot.id, 'code': lot.code, 'quantity': format(-Decimal(allocation.quantity), 'f'),
            'source_kind': lot.source_kind, 'supplier_lot': lot.supplier_lot,
            'manufactured_on': lot.manufactured_on, 'expires_on': lot.expires_on,
        })
    details = []
    for line in lines:
        returned = returned_quantity(db, line["id"])
        details.append(
            {
                **dict(line),
                "returned_quantity": str(returned),
                "returnable_quantity": str(Decimal(0) if reversal else Decimal(line["quantity"]) - returned),
                "physical_lots": lots_by_line.get(line['id'], []),
            }
        )
    return {**dict(row), 'approval': approval.case_data(approval.find_case(db, 'MaterialIssue', issue_id)), 'reversal_approval': approval.case_data(approval.find_case(db, 'MaterialIssue', issue_id, 'reverse')), "status": "reversed" if reversal else row["status"],
            "reversal_id": reversal.id if reversal else None,
            "reversal_reason": reversal.reason if reversal else None,
            "reversed_by": reversal.created_by if reversal else None,
            "reversed_at": reversal.created_at if reversal else None,
            "lines": details}


def checked_lines(db: Session, order_id: int, lines: list[tuple[int, Decimal]]) -> list[RowMapping]:
    known = {
        row["id"]: row
        for row in db.execute(
            select(WorkOrderLine.id, WorkOrderLine.component_material_id, WorkOrderLine.required_quantity)
            .select_from(WorkOrderLine)
            .where((WorkOrderLine.work_order_id == order_id))
        ).mappings()
    }
    result = []
    for line_id, quantity in lines:
        row = known.get(line_id)
        if not row:
            raise HTTPException(422, "领料明细不属于此生产工单")
        if quantity > Decimal(row["required_quantity"]) - issued_quantity(db, line_id):
            raise HTTPException(409, f"组件 #{row['component_material_id']} 超出工单剩余需料")
        result.append(row)
    return result


@router.get("/material-issues")
def list_material_issues(_: dict = Depends(require("production.view"))) -> list[dict]:
    with orm_session() as db:
        ids = [
            row
            for row in db.scalars(
                select(MaterialIssue.id).select_from(MaterialIssue).order_by(MaterialIssue.id.desc())
            )
        ]
        return [material_issue_data(db, issue_id) for issue_id in ids]


@router.post("/material-issues", status_code=201)
def create_material_issue(
    payload: MaterialIssueInput, user: dict = Depends(require("material_issue.create"))
) -> dict:
    line_ids = [line.work_order_line_id for line in payload.lines]
    if len(set(line_ids)) != len(line_ids):
        raise HTTPException(422, "一张领料单不能重复选择同一组件")
    with orm_session(write=True) as db:
        order = (
            db.execute(
                select(WorkOrder.status).select_from(WorkOrder).where((WorkOrder.id == payload.work_order_id))
            )
            .mappings()
            .first()
        )
        if not order:
            raise HTTPException(422, "生产工单不存在")
        if order["status"] not in ("released", "in_progress"):
            raise HTTPException(409, "只有已下达或生产中的工单可以领料")
        require_warehouse(db, payload.warehouse_id)
        checked_lines(
            db, payload.work_order_id, [(line.work_order_line_id, line.quantity) for line in payload.lines]
        )
        cursor = add_model(
            db,
            MaterialIssue(
                work_order_id=payload.work_order_id,
                warehouse_id=payload.warehouse_id,
                reference=payload.reference.strip(),
                created_by=user["id"],
            ),
        )
        db.add_all(
            [
                MaterialIssueLine(
                    material_issue_id=cursor.id,
                    work_order_line_id=line.work_order_line_id,
                    quantity=str(line.quantity),
                )
                for line in payload.lines
            ]
        )
        return material_issue_data(db, cursor.id)


@router.get('/material-issues/{issue_id}/available-lots')
def available_material_issue_lots(issue_id: int,
                                  _: dict = Depends(require('material_issue.post'))) -> dict:
    with orm_session() as db:
        issue = db.get(MaterialIssue, issue_id)
        if issue is None:
            raise HTTPException(404, '生产领料单不存在')
        if issue.status != 'draft':
            raise HTTPException(409, '只能查询生产领料草稿的可用批次')
        lines = list(db.execute(
            select(MaterialIssueLine.id, MaterialIssueLine.quantity,
                   WorkOrderLine.component_material_id)
            .join(WorkOrderLine, WorkOrderLine.id == MaterialIssueLine.work_order_line_id)
            .where(MaterialIssueLine.material_issue_id == issue_id)
            .order_by(MaterialIssueLine.id)).mappings())
        materials = {line['component_material_id'] for line in lines}
        lots = list(db.scalars(select(PhysicalLot).where(
            PhysicalLot.material_id.in_(materials)).order_by(PhysicalLot.id)))
        available = {material_id: [] for material_id in materials}
        for lot in lots:
            quantity = lot_balance(db, issue.warehouse_id, lot.id)
            if quantity > 0:
                available[lot.material_id].append({
                    'lot_id': lot.id, 'code': lot.code, 'source_kind': lot.source_kind,
                    'quantity': format(quantity, 'f'), 'supplier_lot': lot.supplier_lot,
                    'manufactured_on': lot.manufactured_on, 'expires_on': lot.expires_on,
                })
        return {'material_issue_id': issue_id, 'warehouse_id': issue.warehouse_id,
                'lines': [{'material_issue_line_id': line['id'],
                           'material_id': line['component_material_id'],
                           'quantity': line['quantity'],
                           'lots': available[line['component_material_id']]}
                          for line in lines]}


@router.post("/material-issues/{issue_id}/post")
def post_material_issue(issue_id: int, payload: MaterialIssuePostInput | None = None,
                        user: dict = Depends(require("material_issue.post"))) -> dict:
    with orm_session(write=True) as db:
        # 同一写锁保护剩余需料、库存余额、负向流水和工单状态。
        issue = (
            db.execute(
                select(
                    MaterialIssue.id,
                    MaterialIssue.work_order_id,
                    MaterialIssue.warehouse_id,
                    MaterialIssue.reference,
                    MaterialIssue.status,
                    MaterialIssue.created_by,
                    MaterialIssue.posted_by,
                    MaterialIssue.cancelled_by,
                    MaterialIssue.created_at,
                    MaterialIssue.posted_at,
                    MaterialIssue.cancelled_at,
                )
                .select_from(MaterialIssue)
                .where((MaterialIssue.id == issue_id))
            )
            .mappings()
            .first()
        )
        if not issue:
            raise HTTPException(404, "生产领料单不存在")
        if issue["status"] != "draft":
            raise HTTPException(409, "此生产领料单已处理")
        order = (
            db.execute(
                select(WorkOrder.status)
                .select_from(WorkOrder)
                .where((WorkOrder.id == issue["work_order_id"]))
            )
            .mappings()
            .first()
        )
        if order["status"] not in ("released", "in_progress"):
            raise HTTPException(409, "生产工单当前不可领料")
        lines = (
            db.execute(
                select(MaterialIssueLine.id, MaterialIssueLine.work_order_line_id, MaterialIssueLine.quantity)
                .select_from(MaterialIssueLine)
                .where((MaterialIssueLine.material_issue_id == issue_id))
            )
            .mappings()
            .all()
        )
        checked = checked_lines(
            db,
            issue["work_order_id"],
            [(line["work_order_line_id"], Decimal(line["quantity"])) for line in lines],
        )
        lot_lines = {line.material_issue_line_id: line for line in payload.lines} if payload else None
        if lot_lines is not None and (len(lot_lines) != len(payload.lines)
                                      or set(lot_lines) != {line['id'] for line in lines}):
            raise HTTPException(422, '领料批次明细须与单据明细一致且不重复')
        for line, order_line in zip(lines, checked):
            if balance(db, issue["warehouse_id"], order_line["component_material_id"]) < Decimal(
                line["quantity"]
            ):
                raise HTTPException(409, f"组件 #{order_line['component_material_id']} 在源仓库的库存不足")
        # 独立批准不替代原数量/质检校验，执行记录与业务流水必须共同提交或回滚。
        approved = approval.require_approved(db, 'MaterialIssue', issue_id, material_issue_snapshot(db, issue_id), user['id'])
        for line, order_line in zip(lines, checked):
            movement = StockMovement(
                    warehouse_id=issue["warehouse_id"],
                    material_id=order_line["component_material_id"],
                    quantity=str(-Decimal(line["quantity"])),
                    source_type="material_issue",
                    source_id=issue_id,
                    source_line_id=line["id"],
                    created_by=user["id"],
                )
            if lot_lines is None:
                db.add(movement)
                continue
            parts = lot_lines[line['id']].lots
            if len({part.lot_id for part in parts}) != len(parts):
                raise HTTPException(422, '一行领料不能重复选择同一实物批次')
            if sum((part.quantity for part in parts), Decimal(0)) != Decimal(line['quantity']):
                raise HTTPException(422, f'领料明细 #{line["id"]} 的批次数量之和不匹配')
            post_lot_movement(db, movement, [LotPart(part.lot_id, -part.quantity) for part in parts])
        db.execute(
            update(MaterialIssue)
            .where((MaterialIssue.id == issue_id))
            .values(status="posted", posted_by=user["id"], posted_at=func.current_timestamp())
        )
        db.execute(
            update(WorkOrder)
            .where(WorkOrder.id == issue["work_order_id"], WorkOrder.status == "released")
            .values(status="in_progress")
        )
        approval.mark_executed(db, approved, user['id'])
        return material_issue_data(db, issue_id)


@router.post("/material-issues/{issue_id}/cancel")
def cancel_material_issue(issue_id: int, user: dict = Depends(require("material_issue.cancel"))) -> dict:
    with orm_session(write=True) as db:
        pending = approval.find_case(db, 'MaterialIssue', issue_id)
        if pending and pending.status in ('submitted', 'approved'):
            raise HTTPException(409, '请先撤回审批再取消单据')
        row = (
            db.execute(
                select(MaterialIssue.status).select_from(MaterialIssue).where((MaterialIssue.id == issue_id))
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "生产领料单不存在")
        if row["status"] != "draft":
            raise HTTPException(409, "已确认领料不可取消，须另行办理退料更正")
        db.execute(
            update(MaterialIssue)
            .where((MaterialIssue.id == issue_id))
            .values(status="cancelled", cancelled_by=user["id"], cancelled_at=func.current_timestamp())
        )
        return material_issue_data(db, issue_id)


@router.post('/material-issues/{issue_id}/reverse', status_code=201)
def reverse_material_issue(issue_id: int, payload: MaterialIssueReversalInput,
                           user: dict = Depends(require('material_issue.reverse'))) -> dict:
    with orm_session(write=True) as db:
        issue = db.get(MaterialIssue, issue_id)
        if issue is None:
            raise HTTPException(404, '生产领料单不存在')
        if issue.status != 'posted':
            raise HTTPException(409, '只有已确认的生产领料单可冲销')
        if db.scalar(select(MaterialIssueReversal.id).where(
                MaterialIssueReversal.material_issue_id == issue_id)) is not None:
            raise HTTPException(409, '此生产领料单已冲销')
        order = db.get(WorkOrder, issue.work_order_id)
        if order.status != 'in_progress':
            raise HTTPException(409, '工单当前状态不允许冲销领料')
        ensure_unsettled(db, order.id)
        if db.scalar(select(MaterialReturn.id).where(
                MaterialReturn.material_issue_id == issue_id,
                MaterialReturn.status != 'cancelled',
                ~select(MaterialReturnReversal.id).where(
                    MaterialReturnReversal.material_return_id == MaterialReturn.id).exists())) is not None:
            raise HTTPException(409, '原领料仍有退料单，须先取消草稿；已确认退料不可直接冲销领料')
        if db.scalar(select(ProductionCompletion.id).where(
                ProductionCompletion.work_order_id == order.id,
                (ProductionCompletion.status.in_(('draft', 'inspected')) | (
                    (ProductionCompletion.status == 'posted') & ~select(ProductionCompletionReversal.id)
                    .where(ProductionCompletionReversal.production_completion_id == ProductionCompletion.id)
                    .exists())))) is not None:
            raise HTTPException(409, '工单仍有有效报工，须先取消或冲销报工')
        lines = list(db.scalars(select(MaterialIssueLine).where(
            MaterialIssueLine.material_issue_id == issue_id).order_by(MaterialIssueLine.id)))
        line_ids = [line.id for line in lines]
        if db.scalar(select(ProductionCostEntry.id).where(
                ProductionCostEntry.material_issue_line_id.in_(line_ids),
                ~select(ProductionCostReversal.id).where(
                    ProductionCostReversal.entry_id == ProductionCostEntry.id).exists())) is not None:
            raise HTTPException(409, '原领料仍有有效人工核价，须先冲销核价记录')
        ensure_date_unlocked(db, datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'))
        originals = list(db.scalars(select(StockMovement).where(
            StockMovement.source_type == 'material_issue',
            StockMovement.source_id == issue_id)))
        movement_by_line = {movement.source_line_id: movement for movement in originals}
        if len(originals) != len(lines) or len(movement_by_line) != len(lines):
            raise HTTPException(409, '原领料库存流水不完整，无法安全冲销')
        for movement in originals:
            ensure_movement_unlocked(db, movement.id)
        # 冲销另行审批固定原因，不复用本单原批准。
        approved = approval.require_approved(db, 'MaterialIssue', issue_id,
            {'document': material_issue_snapshot(db, issue_id), 'reversal_reason': payload.reason.strip()},
            user['id'], intent='reverse', permission='material_issue.reverse')
        reversal = add_model(db, MaterialIssueReversal(
            material_issue_id=issue_id, reason=payload.reason, created_by=user['id']))
        for line in lines:
            original = movement_by_line[line.id]
            if original.warehouse_id != issue.warehouse_id or Decimal(original.quantity) != -Decimal(line.quantity):
                raise HTTPException(409, '原领料库存流水与单据不一致，无法安全冲销')
            movement = StockMovement(
                warehouse_id=original.warehouse_id, material_id=original.material_id,
                quantity=line.quantity, source_type='material_issue_reversal',
                source_id=reversal.id, source_line_id=line.id, created_by=user['id'])
            allocations = list(db.scalars(select(PhysicalLotAllocation).where(
                PhysicalLotAllocation.movement_id == original.id).order_by(PhysicalLotAllocation.id)))
            evidence = list(db.scalars(select(PhysicalLotMovementEvidence).where(
                PhysicalLotMovementEvidence.movement_id == original.id)))
            if allocations and evidence:
                raise HTTPException(409, '原领料同时存在批次分配和现场补证，须先核对来源')
            if allocations:
                if sum((Decimal(part.quantity) for part in allocations), Decimal(0)) != -Decimal(line.quantity):
                    raise HTTPException(409, '原领料批次分配不完整，无法冲销')
                post_lot_movement(db, movement, [LotPart(
                    part.lot_id, -Decimal(part.quantity), part.id) for part in allocations])
            elif evidence:
                amounts: dict[int, Decimal] = {}
                for part in evidence:
                    amounts[part.lot_id] = amounts.get(part.lot_id, Decimal(0)) + Decimal(part.quantity)
                if sum(amounts.values(), Decimal(0)) != -Decimal(line.quantity) or any(
                        value >= 0 for value in amounts.values()):
                    raise HTTPException(409, '原领料现场补证未完整归批，无法冲销')
                post_lot_movement(db, movement, [LotPart(lot_id, -amount)
                    for lot_id, amount in amounts.items()])
            else:
                db.add(movement)
        # 全部有效领料归零后回到已下达状态，工单原历史及冲销证据仍保留。
        if not any(issued_quantity(db, line.id) > 0 for line in db.scalars(
                select(WorkOrderLine).where(WorkOrderLine.work_order_id == order.id))):
            order.status = 'released'
        approval.mark_executed(db, approved, user['id'])
        return material_issue_data(db, issue_id)
