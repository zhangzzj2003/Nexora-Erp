"""生产计划固定正文、来源额度与执行进度；所有查询复用业务事务。"""

import json
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import document_approval as approval
from app.core.models import (Bom, BomLine, Material, ProductionPlan, ProductionPlanLine,
    ProductionPlanRelease, ProductionPlanChange, MrpConversion, MrpPlan, MrpPlanChange, SalesOrder, SalesOrderLine, WorkOrder, Warehouse)
from app.core.orm import model_data
from app.production.bom_dependencies import require_bom_ready
from app.catalog.product_rules import require_product_use
from app.production.work_orders import posted_completion_totals
from app.sales.orders import shipped_quantity


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def qty(value: Decimal) -> str:
    return format(value.quantize(Decimal('0.001')), 'f')


def get_plan(db: Session, identifier: int, version: int | None = None) -> ProductionPlan:
    plan = db.get(ProductionPlan, identifier)
    if plan is None:
        raise HTTPException(404, '生产计划不存在')
    if version is not None and version != plan.version:
        raise HTTPException(409, '生产计划版本已变化，请重新读取')
    return plan


def plan_lines(db: Session, identifier: int) -> list[ProductionPlanLine]:
    return list(db.scalars(select(ProductionPlanLine).where(
        ProductionPlanLine.plan_id == identifier).order_by(ProductionPlanLine.position)))


def bom_snapshot(db: Session, identifier: int) -> dict:
    bom = db.get(Bom, identifier)
    if bom is None or bom.status != 'active':
        raise HTTPException(409, '生产计划须选择启用中的 BOM')
    require_product_use(db, bom.product_material_id, 'can_produce')
    require_bom_ready(db, identifier)
    product = db.get(Material, bom.product_material_id)
    lines = list(db.scalars(select(BomLine).where(BomLine.bom_id == identifier).order_by(BomLine.id)))
    if not lines:
        raise HTTPException(409, 'BOM 没有组件，不能编制生产计划')
    return {'id': bom.id, 'version': bom.version, 'base_quantity': bom.base_quantity,
        'material_id': product.id, 'sku': product.sku, 'name': product.name, 'unit': product.unit,
        'components': [{'material_id': row.component_material_id, 'quantity': row.quantity,
                        'component_bom_id': row.component_bom_id} for row in lines]}


def same_bom(left: dict, right: dict) -> bool:
    # 改名不改变配方；版本、基数、产品身份及子版本约束必须仍与批准正文相同。
    return all(left[key] == right[key] for key in ('id', 'version', 'base_quantity', 'material_id', 'components'))


def component_quantity(snapshot: dict, quantity: Decimal, component: dict) -> Decimal:
    value = (quantity * Decimal(component['quantity']) / Decimal(snapshot['base_quantity'])).quantize(
        Decimal('0.001'), rounding=ROUND_CEILING)
    if value > 1_000_000:
        raise HTTPException(422, '计划组件数量超过一百万，请拆分生产计划')
    return value


def sales_allocations(db: Session, exclude_plan_id: int | None = None) -> dict[int, Decimal]:
    allocated: dict[int, Decimal] = defaultdict(Decimal)
    query = select(ProductionPlanLine, ProductionPlan.status).join(ProductionPlan, ProductionPlan.id == ProductionPlanLine.plan_id).where(
        ProductionPlanLine.sales_order_line_id.is_not(None))
    if exclude_plan_id is not None:
        query = query.where(ProductionPlan.id != exclude_plan_id)
    # 草稿也占用编排额度；终止计划仅释放未下达部分，仍有效的工单继续占用销售额度。
    for row, status in db.execute(query):
        quantity = Decimal(row.quantity)
        if status == 'cancelled':
            quantity = sum((Decimal(value) for value in db.scalars(select(ProductionPlanRelease.quantity)
                .join(WorkOrder, WorkOrder.id == ProductionPlanRelease.work_order_id).where(
                    ProductionPlanRelease.line_id == row.id, WorkOrder.status != 'cancelled'))), Decimal(0))
        allocated[row.sales_order_line_id] += quantity
    return allocated


def validate_sales(db: Session, lines: list, exclude_plan_id: int | None = None, *, check_unshipped: bool = False) -> None:
    allocated = sales_allocations(db, exclude_plan_id)
    requested: dict[int, Decimal] = defaultdict(Decimal)
    for line in lines:
        if line.sales_order_line_id is None:
            continue
        sale = db.get(SalesOrderLine, line.sales_order_line_id)
        order = db.get(SalesOrder, sale.sales_order_id) if sale else None
        if not sale or not order or order.status not in ('confirmed', 'partially_shipped'):
            raise HTTPException(409, '销售来源须为尚未交付完成的已确认订单')
        bom = db.get(Bom, line.bom_id)
        if not bom or bom.product_material_id != sale.material_id:
            raise HTTPException(422, '销售来源产品与计划 BOM 不一致')
        requested[sale.id] += Decimal(line.quantity)
        # 已发货和已安排可能对应同一批产品，因此分别校验，而不是把两者相加扣两遍。
        if requested[sale.id] + allocated[sale.id] > Decimal(sale.quantity):
            raise HTTPException(409, '累计生产计划数量超过销售订单数量')
        if (exclude_plan_id is None or check_unshipped) and requested[sale.id] > Decimal(sale.quantity) - shipped_quantity(db, sale.id):
            raise HTTPException(409, '计划数量超过销售订单未交付数量')


def validate_plan(db: Session, plan: ProductionPlan, *, line_id: int | None = None) -> None:
    if plan.status == 'cancelled':
        raise HTTPException(409, '生产计划已取消')
    lines = plan_lines(db, plan.id)
    if not lines:
        raise HTTPException(409, '生产计划没有明细')
    # 分批下达只重核本批来源；先前已经完成的另一行不因销售结清或 BOM 停用阻断剩余产品。
    if line_id is not None:
        lines = [line for line in lines if line.id == line_id]
        if not lines:
            raise HTTPException(422, '下达明细不属于此生产计划')
    validate_sales(db, lines, plan.id)
    for line in lines:
        if not same_bom(json.loads(line.bom_json), bom_snapshot(db, line.bom_id)):
            raise HTTPException(409, '生产计划 BOM 已变化，请撤回并重新编制')
        if db.get(Warehouse, line.warehouse_id) is None:
            raise HTTPException(409, '计划目标仓库已不存在')


def approval_snapshot(db: Session, identifier: int) -> dict:
    plan = get_plan(db, identifier)
    # 已下达数量与完工进度不属于批准正文，拆单不使剩余计划的批准失效。
    authors = {plan.created_by, *db.scalars(select(ProductionPlanChange.changed_by).where(
        ProductionPlanChange.plan_id == plan.id, ProductionPlanChange.action.in_(('create', 'edit'))))}
    conversions = list(db.scalars(select(MrpConversion).where(MrpConversion.production_plan_id == identifier)))
    # 编制与转换人员沿来源传递到计划、工单；只为新转单追加字段，旧批准正文保持不变。
    for conversion in conversions:
        source = db.get(MrpPlan, conversion.plan_id)
        authors.update((source.created_by, conversion.created_by))
        authors.update(db.scalars(select(MrpPlanChange.changed_by).where(
            MrpPlanChange.plan_id == source.id, MrpPlanChange.action.in_(('create', 'edit', 'submit')))))
    return {'reference': plan.reference, 'note': plan.note, 'reason': plan.reason,
        'source_author_ids': sorted(authors),
        **({'mrp_conversion_ids': [row.id for row in conversions]} if conversions else {}),
        # 空要求不进入快照，保证升级前已批准的计划仍能核对原指纹。
        'lines': [{key: value for key, value in model_data(line).items()
                   if key != 'production_requirements' or value}
                  for line in plan_lines(db, identifier)]}


def release_rows(db: Session, identifier: int) -> list[dict]:
    rows = []
    for release, order in db.execute(select(ProductionPlanRelease, WorkOrder).join(
            WorkOrder, WorkOrder.id == ProductionPlanRelease.work_order_id).where(
            ProductionPlanRelease.plan_id == identifier).order_by(ProductionPlanRelease.id)):
        reported, accepted, rejected = posted_completion_totals(db, order.id)
        rows.append({**model_data(release), 'work_order_document_no': order.document_no,
            'work_order_status': order.status, 'reported_quantity': qty(reported),
            'accepted_quantity': qty(accepted), 'rejected_quantity': qty(rejected)})
    return rows


def plan_data(db: Session, plan: ProductionPlan, *, detail: bool = False) -> dict:
    releases = release_rows(db, plan.id)
    case = approval.case_data(approval.find_case(db, 'ProductionPlan', plan.id))
    lines = []
    for line in plan_lines(db, plan.id):
        snapshot = json.loads(line.bom_json)
        active = [row for row in releases if row['line_id'] == line.id and row['work_order_status'] != 'cancelled']
        released = sum((Decimal(row['quantity']) for row in active), Decimal(0))
        reported = sum((Decimal(row['reported_quantity']) for row in active), Decimal(0))
        accepted = sum((Decimal(row['accepted_quantity']) for row in active), Decimal(0))
        rejected = sum((Decimal(row['rejected_quantity']) for row in active), Decimal(0))
        sale = db.get(SalesOrderLine, line.sales_order_line_id) if line.sales_order_line_id else None
        order = db.get(SalesOrder, sale.sales_order_id) if sale else None
        # 不同产品单位不合计数量；每条计划分别核对下达、报工、合格及剩余。
        lines.append({**{key: value for key, value in model_data(line).items() if key != 'bom_json'},
            'material_id': snapshot['material_id'], 'sku': snapshot['sku'], 'name': snapshot['name'],
            'unit': snapshot['unit'], 'bom_version': snapshot['version'],
            'warehouse_name': db.get(Warehouse, line.warehouse_id).name,
            'sales_order_id': order.id if order else None, 'sales_order_document_no': order.document_no if order else None,
            'sales_reference': order.reference if order else '',
            'released_quantity': qty(released), 'unreleased_quantity': qty(Decimal(line.quantity) - released),
            'reported_quantity': qty(reported), 'accepted_quantity': qty(accepted), 'rejected_quantity': qty(rejected),
            'remaining_quantity': qty(max(Decimal(0), Decimal(line.quantity) - reported)),
            'overdue': plan.status != 'cancelled' and case['status'] in ('approved', 'executed')
                and line.end_date < today() and reported < Decimal(line.quantity)})
    stage = 'completed' if lines and all(Decimal(row['remaining_quantity']) == 0 for row in lines) else (
        'in_progress' if any(Decimal(row['reported_quantity']) > 0 for row in lines) else (
        'released' if releases and any(row['work_order_status'] != 'cancelled' for row in releases) else 'unreleased'))
    result = {**model_data(plan), 'document_no': plan.document_no, 'approval': case, 'progress': stage,
        'line_count': len(lines), 'overdue_count': sum(row['overdue'] for row in lines),
        'start_date': min((row['start_date'] for row in lines), default=''),
        'end_date': max((row['end_date'] for row in lines), default=''),
        'products': '、'.join(dict.fromkeys(row['name'] for row in lines)),
        'can_edit': plan.status == 'draft' and not releases and case['status'] in ('draft', 'withdrawn', 'rejected')}
    if detail:
        result.update(lines=lines, releases=releases, changes=[{**{key: value for key, value in model_data(row).items()
                if key not in ('before_json', 'after_json')},
            'before': json.loads(row.before_json) if row.before_json else None, 'after': json.loads(row.after_json)}
            for row in db.scalars(select(ProductionPlanChange).where(
                ProductionPlanChange.plan_id == plan.id).order_by(ProductionPlanChange.id))])
    return result


def record_change(db: Session, plan: ProductionPlan, action: str, before: dict | None, reason: str, user_id: int) -> None:
    db.add(ProductionPlanChange(plan_id=plan.id, action=action,
        before_json=encode(before) if before is not None else None,
        after_json=encode({'version': plan.version, 'status': plan.status, **approval_snapshot(db, plan.id)}),
        reason=reason, changed_by=user_id))
