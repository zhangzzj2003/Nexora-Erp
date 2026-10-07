"""完工成本结算：ORM 保存合格、损失及返工来源快照，冲销保留历史。"""

from app.core.document_responses import NumberedRoute
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal
from app.core import document_approval as approval
from app.core.approval_documents import settlement_snapshot, document_snapshot
from app.finance.routes import PaymentExecutionInput
from app.access.security import current_user
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access.security import require
from app.core.period_lock import ensure_movement_unlocked, ensure_date_unlocked
from app.core.models import (User, Material, WorkOrder, WorkOrderLine, MaterialIssue,
    MaterialIssueLine, MaterialReturn, ProductionCompletion, ProductionCompletionReversal,
    StockMovement, ProductionCostEntry, ProductionCostSettlement, ProductionSettlementReversal,
    ProductionCostAllocation, ProductionSettlementSource, ProductionSettlementDependency,
    ProductionSettlementCharge, QualityCostAllocation, ProductionReworkSource, QualityDisposition)
from app.core.orm import orm_session, model_data
from app.inventory.valuation import calculate_valuation
from app.production.cost_lock import ensure_unsettled
from app.production.costs import CostReversalInput, cost_report, money
from app.production.quality_rules import settlement_dispositions

router = APIRouter(route_class=NumberedRoute, prefix='/api/v1/production-costs/settlements')


class SettlementInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    work_order_id: int = Field(gt=0, strict=True)
    reference: str = Field(min_length=1, max_length=100)
    note: str = Field(default='', max_length=200)

    @field_validator('reference')
    @classmethod
    def trim_reference(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('结算依据编号不能为空')
        return value.strip()


def settlement_data(session: Session, settlement_id: int) -> dict:
    settlement = session.get(ProductionCostSettlement, settlement_id)
    if settlement is None:
        raise HTTPException(404, '成本结算不存在')
    reversal = session.scalar(select(ProductionSettlementReversal).where(
        ProductionSettlementReversal.settlement_id == settlement_id))
    sources = []
    for source, sku, name in session.execute(select(ProductionSettlementSource, Material.sku, Material.name)
        .join(MaterialIssueLine, MaterialIssueLine.id == ProductionSettlementSource.material_issue_line_id)
        .join(WorkOrderLine, WorkOrderLine.id == MaterialIssueLine.work_order_line_id)
        .join(Material, Material.id == WorkOrderLine.component_material_id)
        .where(ProductionSettlementSource.settlement_id == settlement_id)
        .order_by(ProductionSettlementSource.material_issue_line_id)):
        sources.append({**model_data(source), 'sku': sku, 'material_name': name})
    allocations = session.scalars(select(ProductionCostAllocation).where(
        ProductionCostAllocation.settlement_id == settlement_id).order_by(ProductionCostAllocation.completion_id))
    charges = session.scalars(select(ProductionCostEntry).join(ProductionSettlementCharge,
        ProductionSettlementCharge.entry_id == ProductionCostEntry.id).where(
            ProductionSettlementCharge.settlement_id == settlement_id).order_by(ProductionCostEntry.id))
    return {**model_data(settlement), 'created_by_name': session.get(User, settlement.created_by).username,
        'status': 'reversed' if reversal is not None else settlement.status,
        'approval': approval.case_data(approval.find_case(session, 'ProductionCostSettlement', settlement_id)),
        'reversal_approval': approval.case_data(approval.find_case(session, 'ProductionCostSettlement', settlement_id, 'reverse')),
        'reversal_id': reversal.id if reversal is not None else None,
        'reversal_reason': reversal.reason if reversal is not None else None,
        'reversed_at': reversal.created_at if reversal is not None else None,
        'reversed_by_name': session.get(User, reversal.created_by).username if reversal is not None else None,
        'allocations': [model_data(row) for row in allocations], 'material_sources': sources,
        'quality_allocations': [dict(**model_data(row), reference=reference, completion_id=completion_id,
            rework_order_id=order_id) for row, reference, completion_id, order_id in session.execute(
                select(QualityCostAllocation, QualityDisposition.reference, QualityDisposition.completion_id,
                    QualityDisposition.rework_order_id).join(QualityDisposition,
                    QualityDisposition.id == QualityCostAllocation.disposition_id)
                .where(QualityCostAllocation.settlement_id == settlement_id).order_by(QualityDisposition.id))],
        'rework_sources': [model_data(row) for row in session.scalars(select(ProductionReworkSource)
            .where(ProductionReworkSource.settlement_id == settlement_id))],
        'charges': [{key: getattr(row, key) for key in ('id', 'kind', 'amount', 'reference', 'created_by', 'created_at')}
                    for row in charges]}


@router.get('')
def list_settlements(_: dict = Depends(require('production_cost.view'))) -> list[dict]:
    with orm_session() as session:
        return [settlement_data(session, value) for value in session.scalars(
            select(ProductionCostSettlement.id).order_by(ProductionCostSettlement.id.desc()))]


def build_settlement_plan(session: Session, work_order_id: int) -> dict:
    """复算原业务成本与分摊；草稿不影响计价，也不锁定来源。"""
    # 写事务覆盖状态、价格、费用与分摊，避免并发重复结算。
    order = session.get(WorkOrder, work_order_id)
    if order is None:
        raise HTTPException(404, '生产工单不存在')
    if order.status != 'completed':
        raise HTTPException(409, '须完成工单全部报工后才能结算完工成本')
    ensure_unsettled(session, order.id)
    pending = session.scalar(select(ProductionCompletion.id).where(
        ProductionCompletion.work_order_id == order.id, ProductionCompletion.status.in_(('draft', 'inspected'))).limit(1))
    pending_issue = session.scalar(select(MaterialIssue.id).where(
        MaterialIssue.work_order_id == order.id, MaterialIssue.status == 'draft').limit(1))
    pending_return = session.scalar(select(MaterialReturn.id).join(MaterialIssue,
        MaterialIssue.id == MaterialReturn.material_issue_id).where(
            MaterialIssue.work_order_id == order.id, MaterialReturn.status == 'draft').limit(1))
    if any(value is not None for value in (pending, pending_issue, pending_return)):
        raise HTTPException(409, '须先取消或处理工单未确认的领料、退料和报工草稿')
    dispositions = settlement_dispositions(session, order.id)
    report = cost_report(session)
    summary = next(item for item in report['orders'] if item['work_order_id'] == order.id)
    if summary['total_amount'] is None:
        raise HTTPException(409, '工单尚有未核价净领料或原返工来源尚未结算，不能结算')
    completions = session.execute(select(ProductionCompletion, StockMovement.id)
        .join(StockMovement, (StockMovement.source_type == 'production_completion') &
            (StockMovement.source_id == ProductionCompletion.id) & (StockMovement.source_line_id == ProductionCompletion.id))
        .where(ProductionCompletion.work_order_id == order.id, ProductionCompletion.status == 'posted',
            ~select(ProductionCompletionReversal.id).where(
                ProductionCompletionReversal.production_completion_id == ProductionCompletion.id).exists())
        .order_by(ProductionCompletion.id)).all()
    accepted = sum((Decimal(row.accepted_quantity) for row, _ in completions), Decimal(0))
    for _, movement_id in completions:
        ensure_movement_unlocked(session, movement_id)
    absorbed = sum((Decimal(row.quantity) for row in dispositions if row.loss_treatment == 'absorb'), Decimal(0))
    external = [row for row in dispositions if row.loss_treatment != 'absorb']
    external_quantity = sum((Decimal(row.quantity) for row in external), Decimal(0))
    reported = accepted + absorbed + external_quantity
    if reported <= 0 or (accepted <= 0 and absorbed > 0):
        raise HTTPException(409, '没有合格成品可以承担正常报废成本，须按审批依据更正为独立损失或返工')
    valuation = calculate_valuation(session)
    header = dict(material_amount=summary['known_material_amount'], labor_amount=summary['labor_amount'],
        overhead_amount=summary['overhead_amount'], rework_amount=summary['rework_amount'],
        total_amount=summary['total_amount'], accepted_quantity=str(accepted))
    allocations, quality, sources, rework = [], [], [], []
    cumulative_quantity = allocated = Decimal(0)
    accepted_pool = Decimal(money(Decimal(header['total_amount']) * (accepted + absorbed) / reported))
    for completion, movement_id in completions:
        quantity = Decimal(completion.accepted_quantity)
        cumulative_quantity += quantity
        cumulative_amount = Decimal(money(accepted_pool * cumulative_quantity / accepted))
        # 累计比例承担尾分，预计与正式执行复用同一规则。
        allocations.append(dict(completion_id=completion.id, movement_id=movement_id,
            quantity=str(quantity), amount=money(cumulative_amount - allocated)))
        allocated = cumulative_amount
    external_pool = Decimal(header['total_amount']) - accepted_pool
    cumulative_quantity = allocated = Decimal(0)
    for disposition in dispositions:
        amount = Decimal(0)
        if disposition.loss_treatment != 'absorb':
            cumulative_quantity += Decimal(disposition.quantity)
            cumulative_amount = Decimal(money(external_pool * cumulative_quantity / external_quantity))
            amount, allocated = cumulative_amount - allocated, cumulative_amount
        quality.append(dict(disposition_id=disposition.id, quantity=disposition.quantity,
            amount=money(amount), kind=disposition.kind, loss_treatment=disposition.loss_treatment))
    dependencies = set()
    if summary['rework_source'] is not None:
        origin = summary['rework_source']
        dependencies.add(('settlement', origin['origin_settlement_id']))
        rework.append(dict(disposition_id=origin['disposition_id'], origin_settlement_id=origin['origin_settlement_id'], amount=origin['amount']))
    for source in report['material_sources']:
        if source['work_order_id'] != order.id:
            continue
        sources.append({key: source[key] for key in ('material_issue_line_id', 'movement_id', 'net_quantity',
            'unit_cost', 'amount', 'cost_source', 'cost_entry_id')})
        dependencies.update(valuation.dependencies.get(source['movement_id'], set()))
    return dict(header=header, allocations=allocations, quality_allocations=quality, material_sources=sources,
        rework_sources=rework, dependencies=[dict(kind=kind, source_id=value) for kind,value in sorted(dependencies)],
        charges=[dict(entry_id=item['id']) for item in sorted(report['entries'], key=lambda r:r['id'])
            if item['work_order_id']==order.id and item['status']=='active' and item['kind'] in ('labor','overhead')])


PLAN_MODELS = {'allocations': ProductionCostAllocation, 'quality_allocations': QualityCostAllocation,
    'material_sources': ProductionSettlementSource, 'rework_sources': ProductionReworkSource,
    'dependencies': ProductionSettlementDependency, 'charges': ProductionSettlementCharge}


def saved_settlement_plan(session: Session, record: ProductionCostSettlement) -> dict:
    result = {'header': {key:getattr(record,key) for key in
        ('material_amount','labor_amount','overhead_amount','rework_amount','total_amount','accepted_quantity')}}
    for key, model in PLAN_MODELS.items():
        # 比较经济正文，不把保存时生成的审计时间混入复算结果；消费者另按原生状态过滤。
        rows = [{name:value for name,value in model_data(row).items() if name not in ('settlement_id','created_at')}
            for row in session.scalars(select(model).where(model.settlement_id==record.id))]
        import json
        result[key] = sorted(rows,key=lambda row:json.dumps(row,sort_keys=True))
    return result


def normalized_plan(value: dict) -> dict:
    import json
    # 来源读序不代表经济内容；排序后比较全部实际数量、金额与依赖。
    return {key: sorted(rows,key=lambda row:json.dumps(row,sort_keys=True)) if isinstance(rows,list) else rows
        for key,rows in value.items()}


def validate_settlement(session: Session, record: ProductionCostSettlement) -> None:
    current = normalized_plan(build_settlement_plan(session,record.work_order_id))
    if current != saved_settlement_plan(session,record):
        raise HTTPException(409,'成本、数量或来源已变化，须取消原草稿并按新依据重新建立结算草稿')


@router.post('', status_code=201)
def settle_cost(payload: SettlementInput, user: dict = Depends(require('production_cost.settle'))) -> dict:
    with orm_session(write=True) as session:
        plan = build_settlement_plan(session,payload.work_order_id)
        if session.scalar(select(ProductionCostSettlement.id).where(
                ProductionCostSettlement.work_order_id==payload.work_order_id,
                ProductionCostSettlement.reference==payload.reference)) is not None:
            raise HTTPException(409,'同一工单不能重复使用结算依据编号')
        record = ProductionCostSettlement(work_order_id=payload.work_order_id,reference=payload.reference,
            note=payload.note.strip(),created_by=user['id'],status='draft',version=1,**plan['header'])
        session.add(record);session.flush()
        for key,model in PLAN_MODELS.items():
            session.add_all(model(settlement_id=record.id,**body) for body in plan[key])
        session.flush()
        return settlement_data(session,record.id)


@router.post('/{settlement_id}/reverse')
def reverse_settlement(settlement_id: int, payload: CostReversalInput,
                       user: dict = Depends(require('production_cost.reopen'))) -> dict:
    with orm_session(write=True) as session:
        settlement = settlement_data(session, settlement_id)
        if settlement['status'] != 'active':
            raise HTTPException(409, '此成本结算已冲销')
        record=session.get(ProductionCostSettlement,settlement_id)
        # 原生结算日期与当前冲销日期都遵守已关闭期间；不能只检查完工流水日期。
        ensure_date_unlocked(session,record.executed_at or record.created_at)
        ensure_date_unlocked(session,approval.now(session))
        case=approval.require_approved(session,'ProductionCostSettlement',settlement_id,
            document_snapshot(session,'ProductionCostSettlement',settlement_id,'reverse',payload.reason),
            user['id'],intent='reverse',permission='production_cost.reopen')
        for allocation in settlement['allocations']:
            ensure_movement_unlocked(session, allocation['movement_id'])
        for allocation in settlement['quality_allocations']:
            ensure_date_unlocked(session, session.get(QualityDisposition, allocation['disposition_id']).posted_at)
        if session.scalar(select(ProductionSettlementDependency.settlement_id).join(ProductionCostSettlement,ProductionCostSettlement.id==ProductionSettlementDependency.settlement_id).where(
            ProductionCostSettlement.status=='active',
            ProductionSettlementDependency.kind == 'settlement', ProductionSettlementDependency.source_id == settlement_id,
            ~select(ProductionSettlementReversal.id).where(
                ProductionSettlementReversal.settlement_id == ProductionSettlementDependency.settlement_id).exists()).limit(1)) is not None:
            raise HTTPException(409, '此成品成本已用于后续工单结算，须先冲销后续结算')
        session.add(ProductionSettlementReversal(settlement_id=settlement_id, reason=payload.reason, created_by=user['id']))
        record.version+=1
        approval.mark_executed(session,case,user['id'],permission='production_cost.reopen',reason=payload.reason)
        session.flush()
        return settlement_data(session, settlement_id)


@router.post('/{settlement_id}/{action}')
def execute_settlement(action: Literal['post','cancel'], data: PaymentExecutionInput,
                       settlement_id: int = Path(gt=0), user: dict = Depends(current_user)) -> dict:
    with orm_session(write=True) as session:
        record=session.get(ProductionCostSettlement,settlement_id)
        if record is None:raise HTTPException(404,'成本结算不存在')
        approval.actor(session,user['id'],'production_cost.settle')
        if record.status!='draft' or record.version!=data.version:
            raise HTTPException(409,'结算版本或状态已变化，请重新读取')
        case=approval.find_case(session,'ProductionCostSettlement',settlement_id)
        if action=='cancel':
            if case and case.status in ('submitted','approved'):raise HTTPException(409,'请先撤回结算审批，再取消草稿')
            record.status='cancelled';record.cancelled_by=user['id'];record.cancelled_at=approval.now(session);record.cancellation_reason=data.reason
        else:
            case=approval.require_approved(session,'ProductionCostSettlement',settlement_id,
                settlement_snapshot(session,settlement_id),user['id'])
            validate_settlement(session,record)
            record.status='active';record.executed_by=user['id'];record.executed_at=approval.now(session)
            ensure_date_unlocked(session,record.executed_at)
            approval.mark_executed(session,case,user['id'],reason=data.reason)
        record.version+=1;session.flush()
        return settlement_data(session,settlement_id)
