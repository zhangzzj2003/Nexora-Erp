"""终止部分交付订单的剩余承诺；只读核对上下游，不替其他模块取消单据。"""

import json
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access.security import require
from app.core import document_approval as approval
from app.core.document_responses import NumberedRoute
from app.core.models import (SalesOrder, Shipment, ProductionPlan, ProductionPlanLine,
    ProductionPlanRelease, WorkOrder, MrpPlan, MrpConversion, PurchaseRequest,
    PurchaseRequestLine, PurchaseOrderRequestLink, PurchaseOrderLine, PurchaseOrder, AfterSalesCase)
from app.core.orm import orm_session
from app.sales.customer_scope import require_visible_order
from app.sales.orders import sales_order_data

router = APIRouter(route_class=NumberedRoute, prefix='/api/v1/sales-orders')


class ExpectedDelivery(BaseModel):
    model_config = {'extra': 'forbid'}
    line_id: int = Field(gt=0, strict=True)
    shipped_quantity: str = Field(pattern=r'^\d{1,7}(?:\.\d{1,3})?$')


class CloseInput(BaseModel):
    model_config = {'extra': 'forbid'}
    reason: str = Field(min_length=1, max_length=500)
    expected_lines: list[ExpectedDelivery] = Field(min_length=1, max_length=100)

    @field_validator('reason')
    @classmethod
    def trim_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('请填写终止剩余交付的原因')
        return value.strip()


def pending_plan(db: Session, plan: ProductionPlan, line_ids: set[int] | None = None) -> bool:
    for line in db.scalars(select(ProductionPlanLine).where(ProductionPlanLine.plan_id == plan.id)):
        if line_ids is not None and line.sales_order_line_id not in line_ids:
            continue
        released = Decimal(0)
        for release, work in db.execute(select(ProductionPlanRelease, WorkOrder).join(
                WorkOrder, WorkOrder.id == ProductionPlanRelease.work_order_id).where(
                ProductionPlanRelease.line_id == line.id)):
            if work.status not in ('cancelled', 'completed'):
                return True
            if work.status != 'cancelled':
                released += Decimal(release.quantity)
        if plan.status != 'cancelled' and released < Decimal(line.quantity):
            return True
    return False


def pending_request(db: Session, request: PurchaseRequest) -> bool:
    from app.purchase.requests import ordered_quantity
    from app.purchase.orders import received_quantity
    for line in db.scalars(select(PurchaseRequestLine).where(PurchaseRequestLine.purchase_request_id == request.id)):
        if request.status != 'cancelled' and ordered_quantity(db, line.id) < Decimal(line.quantity):
            return True
        for order_line, order in db.execute(select(PurchaseOrderLine, PurchaseOrder)
                .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
                .join(PurchaseOrderRequestLink, PurchaseOrderRequestLink.purchase_order_line_id == PurchaseOrderLine.id)
                .where(PurchaseOrderRequestLink.purchase_request_line_id == line.id)):
            if order.status != 'cancelled' and received_quantity(db, order_line.id) < Decimal(order_line.quantity):
                return True
    return False


def require_resolved_commitments(db: Session, order_id: int, line_ids: set[int]) -> None:
    shipment = db.scalar(select(Shipment).where(Shipment.sales_order_id == order_id, Shipment.status == 'draft'))
    if shipment:
        raise HTTPException(409, f'请先处理出库草稿 {shipment.document_no or "#" + str(shipment.id)}，再终止剩余交付')
    plans = db.scalars(select(ProductionPlan).join(ProductionPlanLine,
        ProductionPlanLine.plan_id == ProductionPlan.id).where(
        ProductionPlanLine.sales_order_line_id.in_(line_ids)).distinct())
    for plan in plans:
        if pending_plan(db, plan, line_ids):
            raise HTTPException(409, f'生产计划 {plan.document_no or "#" + str(plan.id)} 尚有未下达安排或未完工工单，请先由生产端处理')
    keys = {f'sales_order_line:{identifier}' for identifier in line_ids}
    # MRP 汇总多张需求，无法安全把某张订单的采购占用按比例拆走；必须先核对关联计划。
    for source in db.scalars(select(MrpPlan).join(MrpConversion, MrpConversion.plan_id == MrpPlan.id).distinct()):
        if not keys.intersection(row['key'] for row in json.loads(source.input_json)['demand_dates']):
            continue
        for conversion in db.scalars(select(MrpConversion).where(MrpConversion.plan_id == source.id)):
            pending = False
            if conversion.production_plan_id:
                pending = pending_plan(db, db.get(ProductionPlan, conversion.production_plan_id))
            elif conversion.work_order_id:
                pending = db.get(WorkOrder, conversion.work_order_id).status not in ('cancelled', 'completed')
            elif conversion.purchase_request_id:
                pending = pending_request(db, db.get(PurchaseRequest, conversion.purchase_request_id))
            if pending:
                raise HTTPException(409, f'关联物料计划 {source.document_no or "#" + str(source.id)} 尚有生产或采购待办，请先核对并处理原单')


@router.post('/{order_id}/close')
def close_order(payload: CloseInput, order_id: int, user: dict = Depends(require('sales_order.cancel'))) -> dict:
    with orm_session(write=True) as db:
        require_visible_order(db, order_id, user)
        order = db.get(SalesOrder, order_id)
        if order.status != 'partially_shipped' or order.closure_json:
            raise HTTPException(409, '仅部分出库且未终止的订单可终止剩余交付')
        if db.scalar(select(AfterSalesCase.id).where(AfterSalesCase.replacement_order_id == order_id)):
            raise HTTPException(409, '售后换货订单须由原售后方案处理，不能独立终止交付')
        current = sales_order_data(db, order_id)
        expected = {line.line_id: Decimal(line.shipped_quantity) for line in payload.expected_lines}
        actual = {line['id']: Decimal(line['shipped_quantity']) for line in current['lines']}
        # 事务中重核逐行实绩，防止弹窗打开后其他仓库已发货，却按过期数量关闭。
        if len(expected) != len(payload.expected_lines) or expected != actual:
            raise HTTPException(409, '订单出库数量已变化，请刷新并重新核对终止数量')
        require_resolved_commitments(db, order_id, set(actual))
        event = {'reason': payload.reason, 'created_by': user['id'], 'created_by_name': user['username'],
            'created_at': approval.now(db), 'lines': [{key: line[key] for key in
                ('id', 'material_id', 'sku', 'material_name', 'unit', 'quantity', 'shipped_quantity')} |
                {'closed_quantity': line['remaining_quantity']} for line in current['lines']]}
        order.status = 'closed'
        order.closure_json = json.dumps(event, ensure_ascii=False, separators=(',', ':'))
        db.flush()
        return sales_order_data(db, order_id)
