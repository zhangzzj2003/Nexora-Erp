"""把批准生产计划的未下达部分接入 MRP，工单部分沿用原供需口径。"""

import json
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select

from app.core import document_approval as approval
from app.core.models import ProductionPlan, ProductionPlanRelease, ProductionPlanLine, WorkOrder
from app.production.plan_rules import plan_lines, component_quantity, qty, validate_plan


def append_plan_sources(db, supplies: list, reservations: list, excluded_plans: set[int] | None = None) -> list[dict]:
    evidence = []
    for plan in db.scalars(select(ProductionPlan).where(ProductionPlan.status != 'cancelled').order_by(ProductionPlan.id)):
        # 原 MRP 的转单不改变其来源指纹；其他 MRP 仍完整计入批准计划。
        if excluded_plans and plan.id in excluded_plans:
            continue
        case = approval.find_case(db, 'ProductionPlan', plan.id)
        if case is None or case.status not in ('approved', 'executed'):
            continue
        # 销售原需求仍只收集一次；生产计划是确定数量的预计产出及组件需求，不再添加一份成品需求。
        for line in plan_lines(db, plan.id):
            bom = json.loads(line.bom_json)
            allocated = sum((Decimal(quantity) for quantity in db.scalars(select(ProductionPlanRelease.quantity)
                .join(WorkOrder, WorkOrder.id == ProductionPlanRelease.work_order_id).where(
                    ProductionPlanRelease.line_id == line.id, WorkOrder.status != 'cancelled'))), Decimal(0))
            remaining = max(Decimal(0), Decimal(line.quantity) - allocated)
            if remaining == 0:
                continue
            # 不把已经无法下达的旧安排当成可靠供给；用户可终止未下达余额，已有工单仍保留。
            try:
                validate_plan(db, plan, line_id=line.id)
            except HTTPException as cause:
                raise HTTPException(409, f'生产计划 {plan.document_no or plan.id} 的未下达来源已失效：{cause.detail}。请先核对或取消未下达安排') from cause
            evidence.append({'plan_id': plan.id, 'line_id': line.id, 'bom': bom, 'quantity': qty(remaining),
                'start_date': line.start_date, 'end_date': line.end_date, 'warehouse_id': line.warehouse_id})
            supplies.append({'key': f'production_plan:{line.id}', 'kind': 'production_plan',
                'source_id': plan.id, 'source_line_id': line.id, 'reference': plan.reference,
                'material_id': bom['material_id'], 'quantity': qty(remaining), 'status': 'approved',
                'warehouse_id': line.warehouse_id, 'bom_id': line.bom_id, 'due_date': line.end_date})
            for index, component in enumerate(bom['components']):
                reservations.append({'key': f'production_plan_component:{line.id}:{index}',
                    'kind': 'production_plan_requirement', 'source_id': plan.id, 'source_line_id': line.id,
                    'reference': plan.reference, 'status': 'approved', 'material_id': component['material_id'],
                    'quantity': qty(component_quantity(bom, remaining, component)), 'due_date': line.start_date})
    return evidence


def work_order_schedule(db, identifier: int) -> dict | None:
    row = db.execute(select(ProductionPlanLine, ProductionPlan).join(ProductionPlan,
        ProductionPlan.id == ProductionPlanLine.plan_id).join(ProductionPlanRelease,
        ProductionPlanRelease.line_id == ProductionPlanLine.id).where(
        ProductionPlanRelease.work_order_id == identifier)).first()
    if row is None:
        return None
    line, plan = row
    return {'production_plan_id': plan.id, 'production_plan_document_no': plan.document_no,
        # 只有明确记录的要求进入工单来源快照，旧工单的审批指纹保持不变。
        **({'production_requirements': line.production_requirements} if line.production_requirements else {}),
        'plan_line_id': line.id, 'start_date': line.start_date, 'end_date': line.end_date, 'priority': line.priority}
