"""生产计划编制、独立审批与分批工单；不直接改变库存。"""

from datetime import date
from decimal import Decimal
import hashlib
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete, select

from app.access.security import require
from app.catalog.material_rules import material_choice_data
from app.core import document_approval as approval
from app.core.document_responses import NumberedRoute
from app.core.models import (Bom, Material, ProductionPlan, ProductionPlanLine, ProductionPlanRelease,
    ProductProfile, SalesOrder, SalesOrderLine, Warehouse)
from app.core.orm import add_model, orm_session, model_data
from app.production.plan_rules import (approval_snapshot, bom_snapshot, component_quantity, encode, get_plan,
    plan_data, qty, record_change, release_rows, sales_allocations, today, validate_plan, validate_sales)
from app.production.work_orders import WorkOrderInput, create_work_order_in_session
from app.sales.orders import shipped_quantity

router = APIRouter(route_class=NumberedRoute, prefix='/api/v1/production/plans')


class PlanLineInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    bom_id: int = Field(gt=0, strict=True)
    warehouse_id: int = Field(gt=0, strict=True)
    sales_order_line_id: int | None = Field(default=None, gt=0, strict=True)
    quantity: str = Field(pattern=r'^\d{1,7}(\.\d{1,3})?$')
    start_date: str
    end_date: str
    priority: Literal['normal', 'high', 'urgent'] = 'normal'

    @field_validator('quantity')
    @classmethod
    def positive(cls, value: str) -> str:
        if not 0 < Decimal(value) <= 1_000_000:
            raise ValueError('计划数量须大于零且不超过一百万')
        return qty(Decimal(value))

    @field_validator('start_date', 'end_date')
    @classmethod
    def valid_date(cls, value: str) -> str:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError('日期须为 YYYY-MM-DD')
        return value

    @model_validator(mode='after')
    def date_order(self):
        if not 0 <= (date.fromisoformat(self.end_date) - date.fromisoformat(self.start_date)).days <= 730:
            raise ValueError('完工日须在开工日起 730 天内')
        return self


class PlanInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reference: str = Field(min_length=1, max_length=100)
    note: str = Field(default='', max_length=500)
    reason: str = Field(min_length=1, max_length=500)
    lines: list[PlanLineInput] = Field(min_length=1, max_length=100)

    @field_validator('reference', 'reason')
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('计划名称和操作依据不能为空')
        return value.strip()


class EditInput(PlanInput):
    version: int = Field(gt=0, strict=True)


class CancelInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: int = Field(gt=0, strict=True)
    reason: str = Field(min_length=1, max_length=500)
    _reason = field_validator('reason')(PlanInput.nonblank.__func__)


class ReleaseInput(CancelInput):
    approval_version: int = Field(gt=0, strict=True)
    line_id: int = Field(gt=0, strict=True)
    request_id: str = Field(min_length=16, max_length=80, pattern=r'^[a-zA-Z0-9-]+$')
    quantity: str = Field(pattern=r'^\d{1,7}(\.\d{1,3})?$')
    _quantity = field_validator('quantity')(PlanLineInput.positive.__func__)


def save_lines(db, plan: ProductionPlan, payload: PlanInput) -> None:
    validate_sales(db, payload.lines, plan.id, check_unshipped=True)
    for position, line in enumerate(payload.lines):
        if not 0 <= (date.fromisoformat(line.start_date) - date.fromisoformat(today())).days <= 730:
            raise HTTPException(422, '新编计划开工日须在服务端今天起 730 天内')
        if db.get(Warehouse, line.warehouse_id) is None:
            raise HTTPException(422, '完工目标仓库不存在')
        snapshot = bom_snapshot(db, line.bom_id)
        for component in snapshot['components']:
            component_quantity(snapshot, Decimal(line.quantity), component)
        db.add(ProductionPlanLine(plan_id=plan.id, position=position,
            **line.model_dump(), bom_json=encode(snapshot)))
    db.flush()


@router.get('/options')
def options(_: dict = Depends(require('production_plan.view'))) -> dict:
    with orm_session() as db:
        boms, unavailable = [], []
        candidates = db.scalars(select(Bom).where(Bom.status == 'active',
            Bom.product_material_id.not_in(select(ProductProfile.material_id).where(
                (ProductProfile.deleted_at.is_not(None)) | (ProductProfile.can_produce.is_(False))))).order_by(Bom.id))
        # 某个下层配方失效只关闭它的新建候选，历史计划仍须能读取、取消及追溯。
        for bom in candidates:
            try:
                boms.append(bom_snapshot(db, bom.id))
            except HTTPException as cause:
                if cause.status_code not in (409, 422):
                    raise
                unavailable.append({'id': bom.id, 'reason': str(cause.detail)})
        product_ids = {row['material_id'] for row in boms}
        allocated = sales_allocations(db)
        sales = []
        # 计划查看权仅提供全公司生产所需的数量来源，不返回销售价格、金额或客户资料。
        for line, order in db.execute(select(SalesOrderLine, SalesOrder).join(SalesOrder,
                SalesOrder.id == SalesOrderLine.sales_order_id).where(
                SalesOrder.status.in_(('confirmed', 'partially_shipped')),
                SalesOrderLine.material_id.in_(product_ids)).order_by(SalesOrderLine.id)):
            remaining = max(Decimal(0), Decimal(line.quantity) - shipped_quantity(db, line.id))
            available = max(Decimal(0), min(remaining, Decimal(line.quantity) - allocated[line.id]))
            sales.append({'id': line.id, 'sales_order_id': order.id, 'sales_order_document_no': order.document_no,
                'reference': order.reference, 'material_id': line.material_id, 'quantity': line.quantity,
                'remaining_quantity': qty(remaining), 'available_quantity': qty(available)})
        return {'today': today(), 'boms': boms, 'sales_lines': sales, 'unavailable_boms': unavailable,
            'materials': [material_choice_data(row) for row in db.scalars(select(Material).where(Material.id.in_(product_ids)))],
            'warehouses': [model_data(row) for row in db.scalars(select(Warehouse).order_by(Warehouse.id))]}


@router.get('')
def list_plans(_: dict = Depends(require('production_plan.view'))) -> list[dict]:
    with orm_session() as db:
        return [plan_data(db, row) for row in db.scalars(select(ProductionPlan).order_by(ProductionPlan.id.desc()))]


@router.get('/{identifier}')
def detail(identifier: int = Path(gt=0), _: dict = Depends(require('production_plan.view'))) -> dict:
    with orm_session() as db:
        return plan_data(db, get_plan(db, identifier), detail=True)


@router.post('', status_code=201)
def create(payload: PlanInput, user: dict = Depends(require('production_plan.create'))) -> dict:
    with orm_session(write=True) as db:
        validate_sales(db, payload.lines)
        plan = add_model(db, ProductionPlan(reference=payload.reference, note=payload.note,
            reason=payload.reason, created_by=user['id']))
        save_lines(db, plan, payload)
        record_change(db, plan, 'create', None, payload.reason, user['id'])
        return plan_data(db, plan, detail=True)


@router.put('/{identifier}')
def edit(payload: EditInput, identifier: int = Path(gt=0), user: dict = Depends(require('production_plan.create'))) -> dict:
    with orm_session(write=True) as db:
        plan = get_plan(db, identifier, payload.version)
        if not plan_data(db, plan)['can_edit']:
            raise HTTPException(409, '仅未下达且未处于审批中的计划可编辑，请先撤回审批')
        before = approval_snapshot(db, plan.id)
        # 编辑仅发生在无执行事实的草稿；原正文仍进入追加审计，不改动历史工单。
        db.execute(delete(ProductionPlanLine).where(ProductionPlanLine.plan_id == plan.id))
        save_lines(db, plan, payload)
        plan.reference, plan.note, plan.reason = payload.reference, payload.note, payload.reason
        plan.version += 1
        record_change(db, plan, 'edit', before, payload.reason, user['id'])
        return plan_data(db, plan, detail=True)


@router.post('/{identifier}/cancel')
def cancel(payload: CancelInput, identifier: int = Path(gt=0), user: dict = Depends(require('production_plan.cancel'))) -> dict:
    with orm_session(write=True) as db:
        plan = get_plan(db, identifier, payload.version)
        case = approval.case_data(approval.find_case(db, 'ProductionPlan', plan.id))
        if plan.status == 'cancelled' or case['status'] in ('submitted', 'approved'):
            raise HTTPException(409, '计划已取消或仍处于审批中，请先撤回审批')
        # 取消终止尚未下达的安排；已生成工单继续独立执行，不能借此改写或取消执行事实。
        before = approval_snapshot(db, plan.id)
        plan.status, plan.cancelled_by, plan.cancelled_at = 'cancelled', user['id'], approval.now(db)
        plan.version += 1
        record_change(db, plan, 'cancel', before, payload.reason, user['id'])
        return plan_data(db, plan, detail=True)


@router.post('/{identifier}/release', status_code=201)
def release(payload: ReleaseInput, identifier: int = Path(gt=0), user: dict = Depends(require('production_plan.release'))) -> dict:
    with orm_session(write=True) as db:
        approval.actor(db, user['id'], 'work_order.create')
        digest = hashlib.sha256(encode(payload.model_dump(exclude={'version', 'approval_version'})).encode()).hexdigest()
        previous = db.scalar(select(ProductionPlanRelease).where(
            ProductionPlanRelease.plan_id == identifier, ProductionPlanRelease.request_id == payload.request_id))
        if previous:
            if previous.request_digest != digest:
                raise HTTPException(409, '此下达请求已用于其他数量或明细')
            # 网络重试返回同一次执行，不再建单，也不会复活已取消的工单。
            return plan_data(db, get_plan(db, identifier), detail=True)
        plan = get_plan(db, identifier, payload.version)
        validate_plan(db, plan, line_id=payload.line_id)
        case = approval.require_conversion_approved(db, 'ProductionPlan', plan.id, approval_snapshot(db, plan.id), user['id'])
        approval.check_version(case.version, payload.approval_version)
        line = db.get(ProductionPlanLine, payload.line_id)
        if line is None or line.plan_id != plan.id:
            raise HTTPException(422, '下达明细不属于此生产计划')
        used = sum((Decimal(row['quantity']) for row in release_rows(db, plan.id)
            if row['line_id'] == line.id and row['work_order_status'] != 'cancelled'), Decimal(0))
        if used + Decimal(payload.quantity) > Decimal(line.quantity):
            raise HTTPException(409, '累计下达数量超过生产计划数量')
        if line.sales_order_line_id is not None:
            sale = db.get(SalesOrderLine, line.sales_order_line_id)
            if Decimal(payload.quantity) > Decimal(sale.quantity) - shipped_quantity(db, sale.id):
                raise HTTPException(409, '本批下达数量超过销售订单当前未交付数量')
        before = approval_snapshot(db, plan.id)
        order = create_work_order_in_session(db, WorkOrderInput(bom_id=line.bom_id,
            warehouse_id=line.warehouse_id, target_quantity=Decimal(payload.quantity), reference=plan.reference,
            note=f'生产计划 {plan.document_no or plan.id}；计划开工 {line.start_date}；计划完工 {line.end_date}'), user)
        db.add(ProductionPlanRelease(plan_id=plan.id, line_id=line.id, work_order_id=order['id'],
            request_id=payload.request_id, request_digest=digest, quantity=payload.quantity,
            reason=payload.reason, created_by=user['id']))
        plan.version += 1
        db.flush()
        if case.status == 'approved':
            approval.mark_executed(db, case, user['id'], reason=payload.reason)
        record_change(db, plan, 'release', before, payload.reason, user['id'])
        return plan_data(db, plan, detail=True)
