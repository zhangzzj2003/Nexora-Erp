"""物料计划参数、固定计算快照、独立审核与可追溯转单。"""

from app.core.document_responses import NumberedRoute
import csv
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from io import StringIO
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.access.security import require
from app.catalog.material_rules import material_choice_data
from app.core.models import (Material, MrpConversion, MrpPlan, MrpPlanChange, MrpPolicy,
    MrpPolicyChange, PurchaseRequest, User, Warehouse, WorkOrder)
from app.core.orm import model_data, orm_session
from app.core import document_approval as approval
from app.core.approval_documents import mrp_snapshot
from app.production.mrp_engine import calculate
from app.production.mrp_sources import collect, encode, fingerprint
from app.production.work_orders import WorkOrderInput, create_work_order_in_session
from app.purchase.requests import PurchaseRequestInput, create_purchase_request_in_session
from app.reports.routes import csv_value

router = APIRouter(route_class=NumberedRoute, prefix='/api/v1/production/mrp')


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def valid_date(value: str) -> str:
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('日期须为 YYYY-MM-DD')
    date.fromisoformat(value)
    return value


def valid_quantity(value: str) -> str:
    if not re.fullmatch(r'\d{1,7}(?:\.\d{1,3})?', value) or Decimal(value) > 1_000_000:
        raise ValueError('数量须非负，最多三位小数且不超过一百万')
    return format(Decimal(value).quantize(Decimal('0.001')), 'f')


class ReasonInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reason: str = Field(min_length=1, max_length=500)

    @field_validator('reason')
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('原因或依据不能为空')
        return value.strip()


class VersionInput(ReasonInput):
    version: int = Field(gt=0, strict=True)


class PolicyInput(ReasonInput):
    version: int = Field(ge=0, strict=True)
    supply_mode: Literal['auto', 'buy', 'make']
    lead_time_days: int = Field(ge=0, le=365, strict=True)
    safety_stock: str
    minimum_quantity: str
    multiple_quantity: str
    _quantity = field_validator('safety_stock', 'minimum_quantity', 'multiple_quantity')(valid_quantity)


class ScheduledDate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    key: str = Field(min_length=1, max_length=80)
    due_date: str
    _date = field_validator('due_date')(valid_date)


class ManualDemand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    material_id: int = Field(gt=0, strict=True)
    quantity: str
    due_date: str
    reference: str = Field(min_length=1, max_length=100)
    _quantity = field_validator('quantity')(valid_quantity)
    _date = field_validator('due_date')(valid_date)
    _reference = field_validator('reference')(ReasonInput.nonblank.__func__)

    @field_validator('quantity')
    @classmethod
    def positive(cls, value: str) -> str:
        if Decimal(value) <= 0:
            raise ValueError('需求数量须大于零')
        return value


class PlanInput(ReasonInput):
    reference: str = Field(min_length=1, max_length=80)
    start_date: str
    demand_dates: list[ScheduledDate] = Field(max_length=2000)
    supply_dates: list[ScheduledDate] = Field(max_length=2000)
    manual_demands: list[ManualDemand] = Field(max_length=500)
    _date = field_validator('start_date')(valid_date)
    _reference = field_validator('reference')(ReasonInput.nonblank.__func__)

    @model_validator(mode='after')
    def schedules(self):
        for rows in (self.demand_dates, self.supply_dates):
            if len({row.key for row in rows}) != len(rows):
                raise ValueError('同一来源不能重复安排日期')
        start = date.fromisoformat(self.start_date)
        for row in [*self.demand_dates, *self.supply_dates, *self.manual_demands]:
            days = (date.fromisoformat(row.due_date) - start).days
            if days < 0 or days > 730:
                raise ValueError('需求和供给日期须在计划起日起 730 天内')
        return self


class ConversionInput(VersionInput):
    suggestion_key: str = Field(min_length=1, max_length=80)
    warehouse_id: int | None = Field(default=None, gt=0, strict=True)
    reference: str = Field(default='', max_length=100)


def get_plan(db: Session, identifier: int, version: int | None = None) -> MrpPlan:
    record = db.get(MrpPlan, identifier)
    if record is None:
        raise HTTPException(404, '物料计划不存在')
    if version is not None and record.version != version:
        raise HTTPException(409, '物料计划已变化，请刷新后再操作')
    return record


def conversion_data(db: Session, row: MrpConversion) -> dict:
    target = db.get(PurchaseRequest, row.purchase_request_id) if row.purchase_request_id else db.get(WorkOrder, row.work_order_id)
    return {**model_data(row), 'target_status': target.status, 'target_reference': target.reference,
        'created_by_name': db.get(User, row.created_by).username}


def metadata(db: Session, record: MrpPlan) -> dict:
    snapshot = json.loads(record.snapshot_json)
    conversions = [conversion_data(db, row) for row in db.scalars(select(MrpConversion)
        .where(MrpConversion.plan_id == record.id).order_by(MrpConversion.id))]
    return {key: getattr(record, key) for key in ('id', 'reference', 'fingerprint', 'status', 'version', 'created_by',
        'submitted_by', 'reviewed_by', 'cancelled_by', 'created_at', 'submitted_at', 'reviewed_at', 'cancelled_at')} | {
        'created_by_name': db.get(User, record.created_by).username,
        'author_ids': sorted({record.created_by, *db.scalars(select(MrpPlanChange.changed_by)
            .where(MrpPlanChange.plan_id == record.id, MrpPlanChange.action == 'submit'))}),
        'start_date': json.loads(record.input_json)['start_date'], 'suggestion_count': len(snapshot['suggestions']),
        'warning_count': len(snapshot['warnings']), 'conversions': conversions,
        'approval': approval.case_data(approval.find_case(db, 'MrpPlan', record.id))}


def report_csv(record: MrpPlan) -> str:
    stream = StringIO(newline='')
    writer = csv.writer(stream, lineterminator='\r\n')
    writer.writerow(['业务单号', '计划参考号', '指纹', '物料编码', '物料名称', '单位', '需求日', '低层码', '供给方式',
        '期初数量', '毛需求', '已安排供给', '安全库存', '净缺口', '建议供给', '期末预计数量', '建议编号'])
    for row in json.loads(record.snapshot_json)['rows']:
        writer.writerow([csv_value(record.document_no or str(record.id)), csv_value(record.reference), record.fingerprint, *[csv_value(str(row[key]) if row[key] is not None else '') for key in (
            'sku','name','unit','date','level','supply_mode','opening_quantity','gross_quantity','scheduled_quantity',
            'safety_stock','net_quantity','planned_quantity','closing_quantity','suggestion_key')]])
    return '\ufeff' + stream.getvalue()


def record_change(db: Session, record: MrpPlan, action: str, before: dict | None, reason: str, user: dict) -> None:
    db.add(MrpPlanChange(plan_id=record.id, action=action, before_json=encode(before) if before else None,
        after_json=encode(metadata(db, record)), reason=reason, changed_by=user['id']))
    db.flush()


def validate_schedule(snapshot: dict, payload: PlanInput) -> None:
    demand_keys = {row['key'] for row in snapshot['demands']}
    supply_keys = {row['key'] for row in snapshot['supplies'] if not row.get('due_date')}
    if demand_keys != {row.key for row in payload.demand_dates} or supply_keys != {row.key for row in payload.supply_dates}:
        raise HTTPException(409, '需求或供给来源已变化，须重新读取并逐项安排日期，不能遗漏现有承诺')
    known = {row['id'] for row in snapshot['materials']}
    if any(row.material_id not in known for row in payload.manual_demands):
        raise HTTPException(422, '手工需求物料不存在')


def current_check(db: Session, record: MrpPlan) -> dict:
    current = fingerprint(collect(db, record.id))
    targets = [conversion_data(db, row) for row in db.scalars(select(MrpConversion).where(MrpConversion.plan_id == record.id))]
    cancelled = any(row['target_status'] == 'cancelled' for row in targets)
    old_date = json.loads(record.input_json)['start_date'] < today()
    return {'matched': current == record.fingerprint and not cancelled and not old_date,
        'fingerprint': record.fingerprint, 'current_fingerprint': current,
        'cancelled_target': cancelled, 'expired_start_date': old_date}


def ensure_current(db: Session, record: MrpPlan) -> None:
    if not current_check(db, record)['matched']:
        raise HTTPException(409, '库存、来源、BOM、参数或计划日期已变化，须新建计划重算；旧快照仍保留')


def prepare_approval_action(db: Session, record: MrpPlan, action: str, user: dict, reason: str) -> dict:
    # 不重算或改写旧计划；每次提交及批准都核对原固定来源是否仍有效。
    if action in ('submit', 'approve', 'reject') and (not reason.strip() or len(reason.strip()) > 500):
        raise HTTPException(422, '计划送审与审核依据必填，最多五百字')
    if action in ('submit', 'approve'):
        ensure_current(db, record)
    return metadata(db, record)


def sync_approval_action(db: Session, record: MrpPlan, action: str, state: dict,
                         user_id: int, reason: str, before: dict) -> None:
    # 审批版本与业务版本分别推进；中间步骤仍待审批，全部通过才可转单。
    record.status = 'draft' if action == 'withdraw' else state['status']
    if action == 'submit':
        record.submitted_by, record.submitted_at = state['submitted_by'], state['submitted_at']
        record.reviewed_by = record.reviewed_at = None
    elif action in ('approve', 'reject'):
        record.reviewed_by, record.reviewed_at = user_id, approval.now(db)
    record.version += 1
    record_change(db, record, action, before, reason.strip() or '撤回计划审批', {'id': user_id})


@router.get('/options')
def options(_: dict = Depends(require('mrp.view'))) -> dict:
    with orm_session() as db:
        source = collect(db)
        # 分类名称只丰富选料响应，不写入计算来源或改变历史快照指纹。
        choices = {row.id: material_choice_data(row) for row in db.scalars(select(Material))}
        return {key: source[key] for key in ('materials','policies','boms','demands','supplies','reservations')} | {
            'materials': [{**row, **choices[row['id']]} for row in source['materials']],
            'fingerprint': fingerprint(source), 'today': today(),
            'warehouses': [model_data(row) for row in db.scalars(select(Warehouse).order_by(Warehouse.id))]}


@router.put('/policies/{material_id}')
def save_policy(payload: PolicyInput, material_id: int = Path(gt=0), user: dict = Depends(require('mrp.configure'))) -> dict:
    with orm_session(write=True) as db:
        if db.get(Material, material_id) is None:
            raise HTTPException(422, '物料不存在')
        record = db.get(MrpPolicy, material_id)
        if payload.version != (record.version if record else 0):
            raise HTTPException(409, '计划参数已变化，请刷新后再保存')
        before = model_data(record) if record else None
        values = payload.model_dump(exclude={'reason', 'version'})
        if record is None:
            record = MrpPolicy(material_id=material_id, **values, version=1, changed_by=user['id'])
            db.add(record)
        else:
            for key, value in values.items():
                setattr(record, key, value)
            record.version += 1
            record.changed_by = user['id']
        db.flush()
        db.add(MrpPolicyChange(material_id=material_id, before_json=encode(before) if before else None,
            after_json=encode(model_data(record)), reason=payload.reason, changed_by=user['id']))
        return model_data(record)


@router.get('/policies/{material_id}/changes')
def policy_changes(material_id: int = Path(gt=0), _: dict = Depends(require('mrp.view'))) -> list[dict]:
    with orm_session() as db:
        return [{**model_data(row), 'before': json.loads(row.before_json) if row.before_json else None,
            'after': json.loads(row.after_json), 'changed_by_name': name} for row, name in db.execute(
                select(MrpPolicyChange, User.username).join(User, User.id == MrpPolicyChange.changed_by)
                .where(MrpPolicyChange.material_id == material_id).order_by(MrpPolicyChange.id))]


@router.get('/plans')
def plans(_: dict = Depends(require('mrp.view'))) -> list[dict]:
    with orm_session() as db:
        return [metadata(db, row) for row in db.scalars(select(MrpPlan).order_by(MrpPlan.id.desc()))]


@router.post('/plans', status_code=201)
def create_plan(payload: PlanInput, user: dict = Depends(require('mrp.create'))) -> dict:
    with orm_session(write=True) as db:
        if payload.start_date < today() or (date.fromisoformat(payload.start_date) - date.fromisoformat(today())).days > 730:
            raise HTTPException(422, '计划起日不能早于今天或晚于今天 730 天')
        source = collect(db)
        validate_schedule(source, payload)
        result = calculate(source, payload.start_date, {row.key: row.due_date for row in payload.demand_dates},
            {row.key: row.due_date for row in payload.supply_dates}, [row.model_dump() for row in payload.manual_demands])
        result['sources'] = source
        result['captured_at'] = datetime.now(timezone.utc).isoformat()
        source_names = {'purchase_order': '采购订单', 'purchase_request': '采购申请', 'work_order': '工单'}
        status_names = {'draft': '草稿', 'submitted': '待审批', 'rejected': '已驳回'}
        result['warnings'] += [f"供给 {source_names[row['kind']]} #{row['source_id']} 状态为 {status_names[row['status']]}，尚待原单批准、确认或下达"
            for row in source['supplies'] if row['status'] in ('draft','submitted','rejected')]
        record = MrpPlan(reference=payload.reference, input_json=encode(payload.model_dump()), snapshot_json=encode(result),
            fingerprint=fingerprint(source), status='draft', version=1, created_by=user['id'])
        db.add(record)
        try:
            db.flush()
        except IntegrityError:
            raise HTTPException(409, '计划依据编号已使用，请使用新编号重算') from None
        record_change(db, record, 'create', None, payload.reason, user)
        return metadata(db, record)


@router.get('/plans/{plan_id}')
def detail(plan_id: int = Path(gt=0), _: dict = Depends(require('mrp.view'))) -> dict:
    with orm_session() as db:
        record = get_plan(db, plan_id)
        return {**metadata(db, record), 'input': json.loads(record.input_json),
            'snapshot': json.loads(record.snapshot_json), 'csv': report_csv(record)}


@router.get('/plans/{plan_id}/check')
def check(plan_id: int = Path(gt=0), _: dict = Depends(require('mrp.view'))) -> dict:
    with orm_session() as db:
        return current_check(db, get_plan(db, plan_id))


@router.get('/plans/{plan_id}/changes')
def changes(plan_id: int = Path(gt=0), _: dict = Depends(require('mrp.view'))) -> list[dict]:
    with orm_session() as db:
        get_plan(db, plan_id)
        return [{**model_data(row), 'before': json.loads(row.before_json) if row.before_json else None,
            'after': json.loads(row.after_json), 'changed_by_name': name} for row, name in db.execute(
                select(MrpPlanChange, User.username).join(User, User.id == MrpPlanChange.changed_by)
                .where(MrpPlanChange.plan_id == plan_id).order_by(MrpPlanChange.id))]


@router.post('/plans/{plan_id}/convert', status_code=201)
def convert(payload: ConversionInput, plan_id: int = Path(gt=0), user: dict = Depends(require('mrp.convert'))) -> dict:
    with orm_session(write=True) as db:
        record = get_plan(db, plan_id, payload.version)
        if record.status != 'approved':
            raise HTTPException(409, '须先完成独立审核批准物料计划')
        approved = approval.require_conversion_approved(db, 'MrpPlan', record.id, mrp_snapshot(db, record.id), user['id'])
        ensure_current(db, record)
        suggestion = next((row for row in json.loads(record.snapshot_json)['suggestions'] if row['key'] == payload.suggestion_key), None)
        if suggestion is None:
            raise HTTPException(422, '建议编号不存在于该固定计划')
        if db.scalar(select(MrpConversion.id).where(MrpConversion.plan_id == record.id,
                MrpConversion.suggestion_key == payload.suggestion_key)) is not None:
            raise HTTPException(409, '此建议已转入原单；取消原单后须重算新计划')
        needed_permission = 'purchase_request.create' if suggestion['supply_mode'] == 'buy' else 'work_order.create'
        if needed_permission not in user['permissions']:
            raise HTTPException(403, '还须拥有目标采购申请或工单的建单权限')
        before = metadata(db, record)
        reference = payload.reference.strip() or f'MRP-{record.id}-{suggestion["key"]}'
        if suggestion['supply_mode'] == 'buy':
            target = create_purchase_request_in_session(db, PurchaseRequestInput(reference=reference,
                note=f'物料计划 #{record.id}；需求日 {suggestion["due_date"]}',
                lines=[{'material_id': suggestion['material_id'], 'quantity': suggestion['quantity']}]), user)
            conversion = MrpConversion(plan_id=record.id, suggestion_key=suggestion['key'], purchase_request_id=target['id'],
                due_date=suggestion['due_date'], reason=payload.reason, created_by=user['id'])
        else:
            if payload.warehouse_id is None:
                raise HTTPException(422, '生产建议须选择工单目标仓库')
            target = create_work_order_in_session(db, WorkOrderInput(reference=reference,
                note=f'物料计划 #{record.id}；需求日 {suggestion["due_date"]}', bom_id=suggestion['bom_id'],
                warehouse_id=payload.warehouse_id, target_quantity=suggestion['quantity']), user)
            conversion = MrpConversion(plan_id=record.id, suggestion_key=suggestion['key'], work_order_id=target['id'],
                due_date=suggestion['due_date'], reason=payload.reason, created_by=user['id'])
        db.add(conversion)
        record.version += 1
        db.flush()
        if approved.status == 'approved':
            # 首次转单记录执行事件，后续只转换剩余建议，不重复审批或制造执行历史。
            approval.mark_executed(db, approved, user['id'])
        record_change(db, record, 'convert', before, payload.reason, user)
        return conversion_data(db, conversion)


@router.post('/plans/{plan_id}/{action}')
def change_status(payload: VersionInput, plan_id: int = Path(gt=0), action: str = '',
                  user: dict = Depends(require('mrp.view'))) -> dict:
    operation = {'submit': 'submit', 'approve': 'review', 'reject': 'review', 'cancel': 'cancel'}.get(action)
    if operation is None:
        raise HTTPException(404, '不支持此物料计划动作')
    if 'mrp.' + operation not in user['permissions']:
        raise HTTPException(403, '没有此物料计划动作权限')
    with orm_session(write=True) as db:
        record = get_plan(db, plan_id, payload.version)
        # 旧客户端不可绕过统一分步审批；仍保留原领域权限和业务版本检查。
        if action in ('submit', 'approve', 'reject'):
            raise HTTPException(409, '请从单据审批入口按当前审批版本操作')
        pending = approval.find_case(db, 'MrpPlan', record.id)
        if pending and pending.status in ('submitted', 'approved'):
            raise HTTPException(409, '请先撤回计划审批再取消')
        if record.status == 'cancelled':
            raise HTTPException(409, '物料计划当前阶段不允许此动作')
        if any(row['target_status'] != 'cancelled' for row in metadata(db, record)['conversions']):
            raise HTTPException(409, '计划已有有效转入原单，须先通过原单流程取消；历史计划保留')
        before = metadata(db, record)
        record.status, record.cancelled_by, record.cancelled_at = 'cancelled', user['id'], approval.now(db)
        record.version += 1
        db.flush()
        record_change(db, record, 'cancel', before, payload.reason, user)
        return metadata(db, record)
