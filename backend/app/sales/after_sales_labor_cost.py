"""维修工时的内部标准成本核价；不生成工资、应付或总账凭证。"""

import re
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from app.access.security import require
from app.core.models import AfterSalesLabor, AfterSalesLaborCost
from app.core.orm import add_model, model_data, orm_session
from app.core.period_lock import ensure_date_unlocked
from app.sales.after_sales import get_case, permission
from app.sales.after_sales_rules import audit, labor_cost_data, now
from app.sales.customer_scope import require_visible_after_sales

router = APIRouter(prefix='/api/v1/after-sales')


class LaborCostInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: int = Field(gt=0, strict=True)
    hourly_rate: Decimal | None
    reason: str = Field(min_length=1, max_length=200)
    evidence: str = Field(min_length=1, max_length=400)

    @field_validator('hourly_rate', mode='before')
    @classmethod
    def text_rate(cls, value):
        if value is not None and (not isinstance(value, str) or
                                  re.fullmatch(r'(?:0|[1-9]\d*)(?:\.\d{1,2})?', value) is None):
            raise ValueError('内部小时成本须以十进制文本填写')
        return value

    @field_validator('hourly_rate')
    @classmethod
    def valid_rate(cls, value):
        if value is not None and (not value.is_finite() or value <= 0 or
                                  value > 100_000 or value.as_tuple().exponent < -2):
            raise ValueError('内部小时成本须大于零、最多两位小数且不超过十万元')
        return value

    @field_validator('reason', 'evidence')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('核价原因与依据不能为空')
        return value.strip()


@router.get('/cases/{case_id}/labor-cost')
def get_labor_cost(case_id: int, user: dict = Depends(require('after_sales.cost'))):
    permission(user, 'after_sales.view')
    with orm_session() as db:
        row = require_visible_after_sales(db, get_case(db, case_id), user)
        return labor_cost_data(db, row)


@router.post('/cases/{case_id}/labor-cost/{entry_id}', status_code=201)
def value_labor_cost(case_id: int, entry_id: int, payload: LaborCostInput,
                     user: dict = Depends(require('after_sales.cost'))):
    permission(user, 'after_sales.view')
    with orm_session(write=True) as db:
        row = require_visible_after_sales(db, get_case(db, case_id), user)
        if row.version != payload.version:
            raise HTTPException(409, '售后版本已变化，请刷新后核对；本次输入未生效')
        if row.kind != 'repair' or row.status not in ('received', 'repaired', 'closed'):
            raise HTTPException(409, '只有已收件、已检验或已结案的有效维修单可核价')
        original = db.get(AfterSalesLabor, entry_id)
        if original is None or original.case_id != row.id or original.action != 'record':
            raise HTTPException(404, '原维修工时记录不存在')
        if db.scalar(select(AfterSalesLabor.id).where(AfterSalesLabor.original_id == entry_id)) is not None:
            raise HTTPException(409, '原维修工时已更正，不可继续核价')
        if original.created_by == user['id']:
            raise HTTPException(403, '实际工时登记人不能核定自身记录的内部成本')
        ensure_date_unlocked(db, original.created_at)
        ensure_date_unlocked(db, now())
        latest = db.scalar(select(AfterSalesLaborCost).where(AfterSalesLaborCost.labor_id == entry_id)
                           .order_by(AfterSalesLaborCost.id.desc()).limit(1))
        rate = str(payload.hourly_rate.quantize(Decimal('0.01'))) if payload.hourly_rate is not None else None
        if rate is None and latest is None:
            raise HTTPException(409, '尚未核价的工时无须撤销')
        if latest is not None and latest.hourly_rate == rate:
            raise HTTPException(409, '内部小时成本未变化，无须重复核价')
        amount = str((Decimal(original.hours) * Decimal(rate)).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP)) if rate is not None else None
        before = model_data(row)
        entry = add_model(db, AfterSalesLaborCost(labor_id=entry_id,
            action='set' if rate is not None else 'void', hourly_rate=rate, amount=amount,
            reason=payload.reason, evidence=payload.evidence, created_by=user['id']))
        row.version += 1
        audit(db, row, 'labor_cost_set' if rate is not None else 'labor_cost_void', before,
              user['id'], payload.reason, f'内部核价记录 #{entry.id}，原工时 #{entry_id}；依据单独受限保存')
        return labor_cost_data(db, row)
