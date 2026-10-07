"""维修实际工时的追加记录与反向更正。"""

from app.core.document_responses import NumberedRoute
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from app.access.security import require
from app.core.models import AfterSalesLabor
from app.core.orm import add_model, model_data, orm_session
from app.core.period_lock import ensure_date_unlocked
from app.sales.after_sales import get_case, permission
from app.sales.after_sales_rules import audit, case_data, now
from app.sales.customer_scope import require_visible_after_sales

router = APIRouter(route_class=NumberedRoute, prefix='/api/v1/after-sales')


class LaborRecord(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: int = Field(gt=0, strict=True)
    hours: Decimal
    reason: str = Field(min_length=1, max_length=200)
    evidence: str = Field(min_length=1, max_length=400)

    @field_validator('hours', mode='before')
    @classmethod
    def text_hours(cls, value):
        if not isinstance(value, str):
            raise ValueError('工时须以十进制文本填写')
        return value

    @field_validator('hours')
    @classmethod
    def valid_hours(cls, value):
        if not value.is_finite() or value <= 0 or value > 100_000 or value.as_tuple().exponent < -2:
            raise ValueError('工时须大于零、最多两位小数且不超过十万小时')
        return value

    @field_validator('reason', 'evidence')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('工时原因与实际依据不能为空')
        return value.strip()


class LaborReverse(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: int = Field(gt=0, strict=True)
    reason: str = Field(min_length=1, max_length=200)
    evidence: str = Field(min_length=1, max_length=400)
    _nonblank = field_validator('reason', 'evidence')(LaborRecord.nonblank.__func__)


def writable_case(db, case_id, version, user):
    permission(user, 'after_sales.view')
    row = require_visible_after_sales(db, get_case(db, case_id), user)
    if row.version != version:
        raise HTTPException(409, '售后版本已变化，请刷新后核对；本次输入未生效')
    if row.kind != 'repair' or row.status not in ('received', 'repaired'):
        raise HTTPException(409, '只有已收件或检验合格的维修单可登记或更正实际工时')
    ensure_date_unlocked(db, now())
    return row


@router.post('/cases/{case_id}/labor', status_code=201)
def record_labor(case_id: int, payload: LaborRecord,
                 user: dict = Depends(require('after_sales.labor'))):
    with orm_session(write=True) as db:
        row = writable_case(db, case_id, payload.version, user)
        before = model_data(row)
        entry = add_model(db, AfterSalesLabor(case_id=row.id, action='record',
            hours=str(payload.hours.quantize(Decimal('0.01'))), original_id=None,
            reason=payload.reason, evidence=payload.evidence, created_by=user['id']))
        row.version += 1
        audit(db, row, 'labor_record', before, user['id'], payload.reason,
              f'工时记录 #{entry.id}：{payload.evidence}')
        return case_data(db, row)


@router.post('/cases/{case_id}/labor/{entry_id}/reverse')
def reverse_labor(case_id: int, entry_id: int, payload: LaborReverse,
                  user: dict = Depends(require('after_sales.labor'))):
    with orm_session(write=True) as db:
        row = writable_case(db, case_id, payload.version, user)
        original = db.get(AfterSalesLabor, entry_id)
        if original is None or original.case_id != row.id or original.action != 'record':
            raise HTTPException(404, '原维修工时记录不存在')
        if db.scalar(select(AfterSalesLabor.id).where(AfterSalesLabor.original_id == entry_id)) is not None:
            raise HTTPException(409, '原维修工时已更正，不可重复更正')
        before = model_data(row)
        add_model(db, AfterSalesLabor(case_id=row.id, action='reverse', hours=original.hours,
            original_id=entry_id, reason=payload.reason, evidence=payload.evidence,
            created_by=user['id']))
        row.version += 1
        audit(db, row, 'labor_reverse', before, user['id'], payload.reason,
              f'更正工时记录 #{entry_id}：{payload.evidence}')
        return case_data(db, row)
