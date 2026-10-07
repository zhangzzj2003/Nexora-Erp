"""MRP 来源快照；全部查询复用调用方 ORM 会话。"""

import hashlib
import json
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import (Bom, BomLine, Customer, Material, MrpConversion, MrpPolicy,
    PurchaseOrder, PurchaseOrderLine, PurchaseRequest, PurchaseRequestLine, SalesOrder, SalesOrderLine,
    StockMovement, Supplier, WorkOrder, WorkOrderLine)
from app.core.orm import model_data
from app.production.mrp_engine import quantity
from app.production.work_orders import issued_quantity, posted_completion_totals
from app.purchase.orders import received_quantity
from app.purchase.requests import ordered_quantity
from app.sales.orders import shipped_quantity


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def fingerprint(value: dict) -> str:
    return hashlib.sha256(encode(value).encode()).hexdigest()


def collect(db: Session, exclude_plan_id: int | None = None) -> dict:
    conversions = list(db.scalars(select(MrpConversion).order_by(MrpConversion.id)))
    own_requests = {row.purchase_request_id for row in conversions if row.plan_id == exclude_plan_id}
    own_orders = {row.work_order_id for row in conversions if row.plan_id == exclude_plan_id}
    request_dates = {row.purchase_request_id: row.due_date for row in conversions if row.purchase_request_id}
    work_dates = {row.work_order_id: row.due_date for row in conversions if row.work_order_id}
    # 规格存储列不参与旧计划的计算指纹；选项接口另行丰富当前资料，迁移不能使原批准计划失效。
    materials = [{key: value for key, value in model_data(row).items()
                  if key not in ('spec_values_json', 'extra_attributes_json', 'spec_template_version')}
                 for row in db.scalars(select(Material).order_by(Material.id))]
    if len(materials) > 2000:
        raise HTTPException(422, '当前计划支持最多 2000 个物料，请先调整计划范围设计')
    stored = {row.material_id: row for row in db.scalars(select(MrpPolicy))}
    policies = [model_data(stored[row['id']]) if row['id'] in stored else {
        'material_id': row['id'], 'supply_mode': 'auto', 'lead_time_days': 0,
        'safety_stock': '0.000', 'minimum_quantity': '0.000', 'multiple_quantity': '0.000',
        'version': 0, 'changed_by': None, 'created_at': None} for row in materials]
    boms = []
    seen = set()
    for bom in db.scalars(select(Bom).where(Bom.status == 'active').order_by(Bom.id)):
        if bom.product_material_id in seen:
            raise HTTPException(409, '同一产品存在多个启用 BOM，须先修正后计算')
        seen.add(bom.product_material_id)
        lines = [model_data(row) for row in db.scalars(select(BomLine).where(BomLine.bom_id == bom.id).order_by(BomLine.id))]
        if not lines:
            raise HTTPException(409, '启用 BOM 没有组件')
        boms.append({**model_data(bom), 'lines': lines})
    movements = [model_data(row) for row in db.scalars(select(StockMovement).order_by(StockMovement.id))]
    demands, supplies, reservations = [], [], []
    for line, order, customer in db.execute(select(SalesOrderLine, SalesOrder, Customer)
            .join(SalesOrder, SalesOrder.id == SalesOrderLine.sales_order_id)
            .join(Customer, Customer.id == SalesOrder.customer_id)
            .where(SalesOrder.status.in_(('confirmed', 'partially_shipped'))).order_by(SalesOrderLine.id)):
        remaining = Decimal(line.quantity) - shipped_quantity(db, line.id)
        if remaining > 0:
            demands.append({'key': f'sales_order_line:{line.id}', 'kind': 'sales_order', 'source_id': order.id,
                'source_line_id': line.id, 'reference': order.reference, 'party_name': customer.name,
                'status': order.status, 'material_id': line.material_id, 'quantity': quantity(remaining)})
    for line, order, supplier in db.execute(select(PurchaseOrderLine, PurchaseOrder, Supplier)
            .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
            .join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
            .where(PurchaseOrder.status != 'cancelled').order_by(PurchaseOrderLine.id)):
        remaining = Decimal(line.quantity) - received_quantity(db, line.id)
        if remaining > 0:
            supplies.append({'key': f'purchase_order_line:{line.id}', 'kind': 'purchase_order', 'source_id': order.id,
                'source_line_id': line.id, 'reference': order.reference, 'party_name': supplier.name,
                'status': order.status, 'material_id': line.material_id, 'quantity': quantity(remaining)})
    for line, request in db.execute(select(PurchaseRequestLine, PurchaseRequest)
            .join(PurchaseRequest, PurchaseRequest.id == PurchaseRequestLine.purchase_request_id)
            .where(PurchaseRequest.status != 'cancelled').order_by(PurchaseRequestLine.id)):
        if request.id in own_requests:
            continue
        remaining = Decimal(line.quantity) - ordered_quantity(db, line.id)
        if remaining > 0:
            supplies.append({'key': f'purchase_request_line:{line.id}', 'kind': 'purchase_request', 'source_id': request.id,
                'source_line_id': line.id, 'reference': request.reference, 'status': request.status,
                'material_id': line.material_id, 'quantity': quantity(remaining), 'due_date': request_dates.get(request.id)})
    for order, bom in db.execute(select(WorkOrder, Bom).join(Bom, Bom.id == WorkOrder.bom_id)
            .where(WorkOrder.status.in_(('draft', 'released', 'in_progress'))).order_by(WorkOrder.id)):
        if order.id in own_orders:
            continue
        reported, _, _ = posted_completion_totals(db, order.id)
        remaining = Decimal(order.target_quantity) - reported
        if remaining > 0:
            supplies.append({'key': f'work_order:{order.id}', 'kind': 'work_order', 'source_id': order.id,
                'reference': order.reference, 'status': order.status, 'material_id': bom.product_material_id,
                'quantity': quantity(remaining), 'warehouse_id': order.warehouse_id, 'bom_id': order.bom_id,
                'due_date': work_dates.get(order.id)})
            for line in db.scalars(select(WorkOrderLine).where(WorkOrderLine.work_order_id == order.id).order_by(WorkOrderLine.id)):
                needed = max(Decimal(0), Decimal(line.required_quantity) - issued_quantity(db, line.id))
                if needed > 0:
                    reservations.append({'key': f'work_order_line:{line.id}', 'kind': 'work_order_requirement',
                        'source_id': order.id, 'source_line_id': line.id, 'reference': order.reference,
                        'status': order.status, 'material_id': line.component_material_id, 'quantity': quantity(needed)})
    if len(demands) > 2000 or len(supplies) > 2000 or len(reservations) > 5000:
        raise HTTPException(422, '未执行需求或供给超过当前计划容量，请先整理单据')
    return {'materials': materials, 'policies': policies, 'boms': boms, 'movements': movements,
        'demands': demands, 'supplies': supplies, 'reservations': reservations}
