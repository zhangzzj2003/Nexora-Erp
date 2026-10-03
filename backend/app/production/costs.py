"""生产成本 ORM 归集：库存平均成本优先，人工和制造费用独立留痕。"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access.security import require
from app.core.period_lock import ensure_date_unlocked, ensure_movement_unlocked
from app.core.orm import orm_session, model_data
from app.core.models import (User, Material, Bom, WorkOrder, WorkOrderLine, MaterialIssue,
    MaterialIssueReversal,
    MaterialIssueLine, MaterialReturn, MaterialReturnLine, StockMovement, ProductionCostEntry,
    ProductionCostReversal, ProductionSettlementSource)
from app.inventory.valuation import calculate_valuation
from app.production.cost_lock import active_settlement, ensure_unsettled
from app.production.quality_rules import rework_source

router = APIRouter(prefix='/api/v1')


def money(value: Decimal) -> str:
    return str(value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


class MaterialValuationInput(BaseModel):
    material_issue_line_id: int = Field(gt=0)
    unit_cost: Decimal
    reference: str = Field(min_length=1, max_length=100)
    note: str = Field(default='', max_length=200)

    @field_validator('unit_cost')
    @classmethod
    def valid_unit_cost(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value < 0 or value > 1_000_000_000 or value.as_tuple().exponent < -4:
            raise ValueError('材料核定单价须非负、最多四位小数且不超过十亿')
        return value

    @field_validator('reference')
    @classmethod
    def trim_reference(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('成本依据编号不能为空')
        return value.strip()


class ChargeInput(BaseModel):
    work_order_id: int = Field(gt=0)
    kind: Literal['labor', 'overhead']
    amount: Decimal
    reference: str = Field(min_length=1, max_length=100)
    note: str = Field(default='', max_length=200)

    @field_validator('amount')
    @classmethod
    def valid_amount(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 0 or value > 1_000_000_000_000 or value.as_tuple().exponent < -2:
            raise ValueError('费用金额须大于零、最多两位小数且不超过一万亿元')
        return value

    @field_validator('reference')
    @classmethod
    def trim_reference(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('成本依据编号不能为空')
        return value.strip()


class CostReversalInput(BaseModel):
    reason: str = Field(min_length=1, max_length=200)

    @field_validator('reason')
    @classmethod
    def trim_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('冲销原因不能为空')
        return value.strip()


def returned_quantity(session: Session, issue_line_id: int) -> Decimal:
    return sum((Decimal(value) for value in session.scalars(select(MaterialReturnLine.quantity)
        .join(MaterialReturn, MaterialReturn.id == MaterialReturnLine.material_return_id)
        .where(MaterialReturnLine.material_issue_line_id == issue_line_id, MaterialReturn.status == 'posted'))), Decimal(0))


def entry_data(session: Session, entry_id: int) -> dict:
    entry = session.get(ProductionCostEntry, entry_id)
    if entry is None:
        raise HTTPException(404, '生产成本记录不存在')
    reversal = session.scalar(select(ProductionCostReversal).where(ProductionCostReversal.entry_id == entry_id))
    issue_line = session.get(MaterialIssueLine, entry.material_issue_line_id) if entry.material_issue_line_id else None
    material = session.get(Material, session.get(WorkOrderLine, issue_line.work_order_line_id).component_material_id) if issue_line else None
    net = Decimal(issue_line.quantity) - returned_quantity(session, issue_line.id) if issue_line else None
    current = (money(net * Decimal(entry.unit_cost)) if issue_line else entry.amount) if reversal is None else None
    return {**model_data(entry), 'created_by_name': session.get(User, entry.created_by).username,
        'status': 'reversed' if reversal else 'active', 'reversal_id': reversal.id if reversal else None,
        'reversal_reason': reversal.reason if reversal else None,
        'reversed_by': reversal.created_by if reversal else None,
        'reversed_at': reversal.created_at if reversal else None,
        'reversed_by_name': session.get(User, reversal.created_by).username if reversal else None,
        'issue_quantity': issue_line.quantity if issue_line else None,
        'material_sku': material.sku if material else None, 'material_name': material.name if material else None,
        'net_quantity': str(net) if net is not None else None, 'current_amount': current}


def cost_report(session: Session) -> dict:
    entries = [entry_data(session, value) for value in session.scalars(
        select(ProductionCostEntry.id).order_by(ProductionCostEntry.id.desc()))]
    manual_rates = {item['material_issue_line_id']: item for item in entries
                    if item['status'] == 'active' and item['kind'] == 'material'}
    valuation = calculate_valuation(session)
    issue_movements = {item['source_line_id']: item['id'] for item in valuation.report['movements']
                       if item['source_type'] == 'material_issue'}
    orders, unpriced_lines, material_sources = [], [], []
    for order, product_name in session.execute(select(WorkOrder, Material.name)
        .join(Bom, Bom.id == WorkOrder.bom_id).join(Material, Material.id == Bom.product_material_id)
        .order_by(WorkOrder.id.desc())):
        known, unpriced = Decimal(0), 0
        for line, material in session.execute(select(MaterialIssueLine, Material)
            .join(MaterialIssue, MaterialIssue.id == MaterialIssueLine.material_issue_id)
            .join(WorkOrderLine, WorkOrderLine.id == MaterialIssueLine.work_order_line_id)
            .join(Material, Material.id == WorkOrderLine.component_material_id)
            .where(MaterialIssue.work_order_id == order.id, MaterialIssue.status == 'posted',
                ~select(MaterialIssueReversal.id).where(
                    MaterialIssueReversal.material_issue_id == MaterialIssue.id).exists())):
            net = Decimal(line.quantity) - returned_quantity(session, line.id)
            if net <= 0:
                continue
            movement_id = issue_movements.get(line.id)
            inventory_cost = valuation.movement_costs.get(movement_id)
            manual = manual_rates.get(line.id)
            rate = inventory_cost if inventory_cost is not None else Decimal(manual['unit_cost']) if manual else None
            if rate is None:
                unpriced += 1
                unpriced_lines.append({'material_issue_line_id': line.id, 'material_issue_id': line.material_issue_id,
                    'work_order_id': order.id, 'sku': material.sku, 'material_name': material.name,
                    'unit': material.unit, 'net_quantity': str(net)})
            else:
                amount = money(net * rate)
                known += Decimal(amount)
                material_sources.append({'work_order_id': order.id, 'material_issue_line_id': line.id,
                    'material_issue_id': line.material_issue_id, 'movement_id': movement_id,
                    'sku': material.sku, 'material_name': material.name, 'net_quantity': str(net),
                    'unit_cost': str(rate), 'amount': amount, 'cost_source': 'inventory' if inventory_cost is not None else 'manual',
                    'cost_entry_id': None if inventory_cost is not None else manual['id']})
        fees = {kind: sum((Decimal(item['amount']) for item in entries
            if item['work_order_id'] == order.id and item['status'] == 'active' and item['kind'] == kind), Decimal(0))
            for kind in ('labor', 'overhead')}
        settlement = active_settlement(session, order.id)
        rework = rework_source(session, order.id)
        carried = Decimal(rework['amount']) if rework and rework['amount'] is not None else Decimal(0)
        unresolved_rework = rework is not None and rework['amount'] is None
        summary = {'work_order_id': order.id, 'product_name': product_name, 'work_order_status': order.status,
            'known_material_amount': money(known), 'labor_amount': money(fees['labor']),
            'overhead_amount': money(fees['overhead']),
            'rework_amount': None if unresolved_rework else money(carried), 'rework_source': rework,
            'unpriced_rework': unresolved_rework,
            'total_amount': None if unpriced or unresolved_rework else money(known + fees['labor'] + fees['overhead'] + carried),
            'unpriced_issue_count': unpriced, 'settlement_id': settlement['id'] if settlement else None}
        if settlement:
            # 结算后的汇总和来源均使用当时快照，后补价格不会悄然替换历史依据。
            summary.update(known_material_amount=settlement['material_amount'], labor_amount=settlement['labor_amount'],
                overhead_amount=settlement['overhead_amount'], rework_amount=settlement['rework_amount'],
                total_amount=settlement['total_amount'], unpriced_issue_count=0, unpriced_rework=False)
            material_sources = [item for item in material_sources if item['work_order_id'] != order.id]
            unpriced_lines = [item for item in unpriced_lines if item['work_order_id'] != order.id]
            for source, issue_id, sku, name in session.execute(select(ProductionSettlementSource,
                MaterialIssueLine.material_issue_id, Material.sku, Material.name)
                .join(MaterialIssueLine, MaterialIssueLine.id == ProductionSettlementSource.material_issue_line_id)
                .join(WorkOrderLine, WorkOrderLine.id == MaterialIssueLine.work_order_line_id)
                .join(Material, Material.id == WorkOrderLine.component_material_id)
                .where(ProductionSettlementSource.settlement_id == settlement['id'])):
                material_sources.append({**model_data(source), 'work_order_id': order.id,
                    'material_issue_id': issue_id, 'sku': sku, 'material_name': name})
        orders.append(summary)
    applied = {item['cost_entry_id'] for item in material_sources if item['cost_entry_id'] is not None}
    for entry in entries:
        entry['included_in_current_cost'] = entry['status'] == 'active' and (entry['kind'] != 'material' or entry['id'] in applied)
    return {'currency': 'CNY', 'orders': orders, 'entries': entries,
            'unpriced_lines': unpriced_lines, 'material_sources': material_sources}


@router.get('/production-costs')
def list_production_costs(_: dict = Depends(require('production_cost.view'))) -> dict:
    with orm_session() as session:
        return cost_report(session)


@router.post('/production-costs/material-valuations', status_code=201)
def record_material_valuation(payload: MaterialValuationInput,
                              user: dict = Depends(require('production_cost.record'))) -> dict:
    with orm_session(write=True) as session:
        line = session.get(MaterialIssueLine, payload.material_issue_line_id)
        if line is None:
            raise HTTPException(422, '领料明细不存在')
        issue = session.get(MaterialIssue, line.material_issue_id)
        if issue.status != 'posted' or session.scalar(select(MaterialIssueReversal.id).where(
                MaterialIssueReversal.material_issue_id == issue.id)) is not None:
            raise HTTPException(409, '只有已确认领料明细可以核价')
        ensure_unsettled(session, issue.work_order_id)
        movement_id = session.scalar(select(StockMovement.id).where(
            StockMovement.source_type == 'material_issue', StockMovement.source_line_id == line.id))
        if movement_id is not None:
            ensure_movement_unlocked(session, movement_id)
        if movement_id is not None and calculate_valuation(session).movement_costs.get(movement_id) is not None:
            raise HTTPException(409, '领料已有库存平均成本，无需另行人工核价；请更正库存成本来源')
        if session.scalar(select(ProductionCostEntry.id).where(ProductionCostEntry.material_issue_line_id == line.id,
            ~select(ProductionCostReversal.id).where(ProductionCostReversal.entry_id == ProductionCostEntry.id).exists()).limit(1)) is not None:
            raise HTTPException(409, '此领料明细已有有效核价记录，须先冲销原记录')
        entry = ProductionCostEntry(work_order_id=issue.work_order_id, kind='material', material_issue_line_id=line.id,
            unit_cost=str(payload.unit_cost), reference=payload.reference, note=payload.note.strip(), created_by=user['id'])
        session.add(entry)
        session.flush()
        return entry_data(session, entry.id)


@router.post('/production-costs/charges', status_code=201)
def record_charge(payload: ChargeInput, user: dict = Depends(require('production_cost.record'))) -> dict:
    with orm_session(write=True) as session:
        order = session.get(WorkOrder, payload.work_order_id)
        if order is None:
            raise HTTPException(422, '生产工单不存在')
        if order.status not in ('released', 'in_progress', 'completed'):
            raise HTTPException(409, '只有已下达、生产中或已完工的工单可以归集费用')
        ensure_unsettled(session, order.id)
        entry = ProductionCostEntry(work_order_id=order.id, kind=payload.kind, amount=money(payload.amount),
            reference=payload.reference, note=payload.note.strip(), created_by=user['id'])
        session.add(entry)
        session.flush()
        return entry_data(session, entry.id)


@router.post('/production-costs/{entry_id}/reverse')
def reverse_cost_entry(entry_id: int, payload: CostReversalInput,
                       user: dict = Depends(require('production_cost.reverse'))) -> dict:
    with orm_session(write=True) as session:
        entry = session.get(ProductionCostEntry, entry_id)
        if entry is None:
            raise HTTPException(404, '生产成本记录不存在')
        ensure_date_unlocked(session, entry.created_at)
        ensure_unsettled(session, entry.work_order_id)
        if session.scalar(select(ProductionCostReversal.id).where(ProductionCostReversal.entry_id == entry_id)) is not None:
            raise HTTPException(409, '此生产成本记录已冲销')
        session.add(ProductionCostReversal(entry_id=entry_id, reason=payload.reason, created_by=user['id']))
        session.flush()
        return entry_data(session, entry.id)
