"""完工成本结算：ORM 保存来源快照并按合格数量分摊，冲销保留历史。"""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access.security import require
from app.core.period_lock import ensure_movement_unlocked
from app.core.models import (User, Material, WorkOrder, WorkOrderLine, MaterialIssue,
    MaterialIssueLine, MaterialReturn, ProductionCompletion, ProductionCompletionReversal,
    StockMovement, ProductionCostEntry, ProductionCostSettlement, ProductionSettlementReversal,
    ProductionCostAllocation, ProductionSettlementSource, ProductionSettlementDependency,
    ProductionSettlementCharge)
from app.core.orm import orm_session, model_data
from app.inventory.valuation import calculate_valuation
from app.production.cost_lock import ensure_unsettled
from app.production.costs import CostReversalInput, cost_report, money

router = APIRouter(prefix='/api/v1/production-costs/settlements')


class SettlementInput(BaseModel):
    work_order_id: int = Field(gt=0)
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
    from app.core.models import ProductionQualityCost, QualityDisposition
    quality_costs=[{**model_data(row),'kind':item.kind,'quantity':item.quantity,'rework_order_id':item.rework_order_id} for row,item in session.execute(select(ProductionQualityCost,QualityDisposition).join(QualityDisposition,QualityDisposition.id==ProductionQualityCost.disposition_id).where(ProductionQualityCost.settlement_id==settlement_id))]
    return {'quality_costs':quality_costs, **model_data(settlement), 'created_by_name': session.get(User, settlement.created_by).username,
        'status': 'reversed' if reversal is not None else 'active',
        'reversal_id': reversal.id if reversal is not None else None,
        'reversal_reason': reversal.reason if reversal is not None else None,
        'reversed_at': reversal.created_at if reversal is not None else None,
        'reversed_by_name': session.get(User, reversal.created_by).username if reversal is not None else None,
        'allocations': [model_data(row) for row in allocations], 'material_sources': sources,
        'charges': [{key: getattr(row, key) for key in ('id', 'kind', 'amount', 'reference', 'created_by', 'created_at')}
                    for row in charges]}


@router.get('')
def list_settlements(_: dict = Depends(require('production_cost.view'))) -> list[dict]:
    with orm_session() as session:
        return [settlement_data(session, value) for value in session.scalars(
            select(ProductionCostSettlement.id).order_by(ProductionCostSettlement.id.desc()))]


@router.post('', status_code=201)
def settle_cost(payload: SettlementInput,
                user: dict = Depends(require('production_cost.settle'))) -> dict:
    with orm_session(write=True) as session:
        # 写事务覆盖状态、价格、费用与分摊，避免并发重复结算。
        order = session.get(WorkOrder, payload.work_order_id)
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
        report = cost_report(session)
        summary = next(item for item in report['orders'] if item['work_order_id'] == order.id)
        if summary['total_amount'] is None:
            raise HTTPException(409, '工单尚有未核价净领料，不能结算')
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
        from app.production.quality_costs import quality_allocations, carried_cost
        quality,inventory_amount=quality_allocations(session,order.id,Decimal(summary['total_amount']))
        # 全不合格仍可结算，成本必须有报废或返工去向，不能虚增成品库存。
        if session.scalar(select(ProductionCostSettlement.id).where(
            ProductionCostSettlement.work_order_id == order.id, ProductionCostSettlement.reference == payload.reference)) is not None:
            raise HTTPException(409, '同一工单不能重复使用结算依据编号')
        valuation = calculate_valuation(session)
        settlement = ProductionCostSettlement(work_order_id=order.id, reference=payload.reference,
            note=payload.note.strip(), material_amount=summary['known_material_amount'],
            labor_amount=summary['labor_amount'], overhead_amount=summary['overhead_amount'],
            total_amount=summary['total_amount'], accepted_quantity=str(accepted), created_by=user['id'])
        session.add(settlement)
        session.flush()
        cumulative_quantity = Decimal(0)
        allocated = Decimal(0)
        for completion, movement_id in completions:
            quantity = Decimal(completion.accepted_quantity)
            cumulative_quantity += quantity
            cumulative_amount = Decimal(money(inventory_amount * cumulative_quantity / accepted))
            # 累计分摊处理尾分，所有批次精确相加到结算总额。
            session.add(ProductionCostAllocation(settlement_id=settlement.id, completion_id=completion.id,
                movement_id=movement_id, quantity=str(quantity), amount=money(cumulative_amount - allocated)))
            allocated = cumulative_amount
        from app.core.models import ProductionQualityCost
        session.add_all([ProductionQualityCost(settlement_id=settlement.id,disposition_id=item.id,amount=money(value)) for item,value in quality])
        _,parents=carried_cost(session,order.id)
        dependencies: set[tuple[str, int]] = {('settlement',identifier) for identifier in parents}
        for source in report['material_sources']:
            if source['work_order_id'] != order.id:
                continue
            session.add(ProductionSettlementSource(settlement_id=settlement.id,
                **{key: source[key] for key in ('material_issue_line_id', 'movement_id', 'net_quantity',
                                               'unit_cost', 'amount', 'cost_source', 'cost_entry_id')}))
            dependencies.update(valuation.dependencies.get(source['movement_id'], set()))
        session.add_all([ProductionSettlementDependency(settlement_id=settlement.id, kind=kind, source_id=value)
                         for kind, value in sorted(dependencies)])
        session.add_all([ProductionSettlementCharge(settlement_id=settlement.id, entry_id=item['id'])
            for item in report['entries'] if item['work_order_id'] == order.id and item['status'] == 'active'
            and item['kind'] in ('labor', 'overhead')])
        session.flush()
        return settlement_data(session, settlement.id)


@router.post('/{settlement_id}/reverse')
def reverse_settlement(settlement_id: int, payload: CostReversalInput,
                       user: dict = Depends(require('production_cost.reopen'))) -> dict:
    with orm_session(write=True) as session:
        settlement = settlement_data(session, settlement_id)
        if settlement['status'] != 'active':
            raise HTTPException(409, '此成本结算已冲销')
        for allocation in settlement['allocations']:
            ensure_movement_unlocked(session, allocation['movement_id'])
        if session.scalar(select(ProductionSettlementDependency.settlement_id).where(
            ProductionSettlementDependency.kind == 'settlement', ProductionSettlementDependency.source_id == settlement_id,
            ~select(ProductionSettlementReversal.id).where(
                ProductionSettlementReversal.settlement_id == ProductionSettlementDependency.settlement_id).exists()).limit(1)) is not None:
            raise HTTPException(409, '此成品成本已用于后续工单结算，须先冲销后续结算')
        session.add(ProductionSettlementReversal(settlement_id=settlement_id, reason=payload.reason, created_by=user['id']))
        session.flush()
        return settlement_data(session, settlement_id)
