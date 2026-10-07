"""客户关系的输入约束、版本边界和完整变更证据。"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import json

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import CrmContact, CrmOpportunity, CrmActivity, CrmQuote, CrmQuoteLine, CrmChange, Customer, SalesOrder, User
from app.core.orm import model_data
from app.sales.customer_scope import require_visible_customer, require_visible_record

ENTITIES = {'contact': CrmContact, 'activity': CrmActivity, 'opportunity': CrmOpportunity, 'quote': CrmQuote}
OPEN_STAGES = ('prospect', 'qualified', 'proposal', 'negotiation')


def today() -> str:
    # 目前公司币种及业务日固定为人民币、北京时间；不按客户端时钟判断报价过期。
    return datetime.now(timezone(timedelta(hours=8))).date().isoformat()


def json_text(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def valid_date(value: str) -> str:
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value or not 1900 <= parsed.year <= 2199:
        raise ValueError('日期须为 1900 至 2199 年的 YYYY-MM-DD')
    return value


class StrictInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class VersionInput(StrictInput):
    version: int = Field(strict=True, gt=0, le=2_147_483_647)
    reason: str = Field(min_length=1, max_length=500)


def get_record(db: Session, kind: str, identifier: int, version: int | None = None,
               user: dict | None = None):
    record = db.get(ENTITIES[kind], identifier)
    if record is None:
        raise HTTPException(404, '客户关系记录不存在')
    if user is not None:
        require_visible_record(db, record, user)
    if version is not None and record.version != version:
        raise HTTPException(409, '记录已被其他操作更新，请刷新后重试')
    return record


def require_customer(db: Session, identifier: int, user: dict | None = None) -> Customer:
    row = require_visible_customer(db, identifier, user) if user is not None else db.get(Customer, identifier)
    if row is None:
        raise HTTPException(422, '客户不存在')
    return row


def require_owner(db: Session, identifier: int):
    row = db.get(User, identifier)
    if row is None or not row.is_active:
        raise HTTPException(422, '负责人须为启用的账号')


def require_contact(db: Session, customer_id: int, identifier: int | None):
    if identifier is None:
        return None
    row = db.get(CrmContact, identifier)
    if row is None or row.customer_id != customer_id or not row.is_active:
        raise HTTPException(422, '联系人须属于该客户且处于启用状态')
    return row


def require_open_opportunity(db: Session, identifier: int, user: dict | None = None):
    row = get_record(db, 'opportunity', identifier, user=user)
    if row.stage not in OPEN_STAGES:
        raise HTTPException(409, '已转单或已丢单的商机不可新增、提交或转换报价')
    return row


def raw_data(db: Session, kind: str, record) -> dict:
    result = model_data(record)
    if kind == 'quote':
        result['party'] = json.loads(result.pop('party_json'))
        lines = [model_data(line) for line in db.scalars(select(CrmQuoteLine)
            .where(CrmQuoteLine.quote_id == record.id).order_by(CrmQuoteLine.position))]
        for line in lines:
            line['line_total'] = str((Decimal(line['quantity']) * Decimal(line['unit_price']))
                .quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
        result['lines'] = lines
        result['total_amount'] = str(sum((Decimal(line['line_total']) for line in lines), Decimal('0.00')))
        result['currency'] = 'CNY'
    return result


def record_data(db: Session, kind: str, record) -> dict:
    result = raw_data(db, kind, record)
    result['customer_name'] = require_customer(db, record.customer_id).name
    result['created_by_name'] = db.get(User, record.created_by).username
    contact_id = getattr(record, 'contact_id', None)
    result['contact_name'] = db.get(CrmContact, contact_id).name if contact_id else ''
    if kind in ('opportunity', 'activity'):
        result['owner_name'] = db.get(User, record.owner_id).username
    if kind == 'activity':
        result['overdue'] = record.status == 'planned' and record.due_date < today()
    if kind == 'opportunity':
        result['orders'] = [{'quote_id': quote.id, 'sales_order_id': order.id, 'status': order.status}
            for quote, order in db.execute(select(CrmQuote, SalesOrder)
                .join(SalesOrder, SalesOrder.id == CrmQuote.sales_order_id)
                .where(CrmQuote.opportunity_id == record.id).order_by(CrmQuote.id))]
    if kind == 'quote':
        # 报价正文始终来自冻结快照，实时信息只用于动作提示。
        result['customer_name'] = result['party']['customer_name']
        result['contact_name'] = result['party']['contact_name']
        result['opportunity_title'] = db.get(CrmOpportunity, record.opportunity_id).title
        result['opportunity_version'] = db.get(CrmOpportunity, record.opportunity_id).version
        result['opportunity_stage'] = db.get(CrmOpportunity, record.opportunity_id).stage
        result['contact_active'] = not contact_id or bool(db.get(CrmContact, contact_id).is_active)
        result['expired'] = record.valid_until < today()
        result['sales_order_status'] = db.get(SalesOrder, record.sales_order_id).status if record.sales_order_id else None
        from app.core.document_approval import case_data, find_case
        result['approval'] = case_data(find_case(db, 'CrmQuote', record.id))
        result['review_blocked'] = list(db.scalars(select(CrmChange.changed_by).where(
            CrmChange.entity_kind == 'quote', CrmChange.entity_id == record.id,
            CrmChange.action.in_(('create','edit','submit'))).distinct()))
    return result


def audit(db: Session, kind: str, record, action: str, before: dict | None, reason: str, user_id: int):
    db.flush()
    db.add(CrmChange(entity_kind=kind, entity_id=record.id, action=action,
        before_json=json_text(before) if before is not None else None,
        after_json=json_text(raw_data(db, kind, record)), reason=reason, changed_by=user_id))


def copy_fields(record, payload, names: tuple[str, ...]):
    for name in names:
        value = getattr(payload, name)
        setattr(record, name, str(value) if isinstance(value, Decimal) else value)


def validate_amount(value: Decimal) -> Decimal:
    if not value.is_finite() or value < 0 or value > 100_000_000_000 or value.as_tuple().exponent < -2:
        raise ValueError('预估金额须非负、最多两位小数且不超过一千亿元')
    return value
