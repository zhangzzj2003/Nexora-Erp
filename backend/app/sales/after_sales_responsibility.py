"""售后人工责任核定；每次更正追加记录，不根据保修期自动归责。"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.access.security import require
from app.core.models import AfterSalesResponsibility
from app.core.orm import orm_session, model_data
from app.core.period_lock import ensure_date_unlocked
from app.sales.after_sales import get_case, permission
from app.sales.after_sales_rules import authors, audit, case_data, now, responsibility_data
from app.sales.customer_scope import require_visible_after_sales

router = APIRouter(prefix='/api/v1/after-sales')


class ResponsibilityAssessment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: int = Field(gt=0, strict=True)
    outcome: Literal['company', 'customer', 'third_party', 'undetermined']
    basis: str = Field(min_length=1, max_length=400)
    reason: str = Field(min_length=1, max_length=200)

    @field_validator('basis', 'reason')
    @classmethod
    def nonempty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('责任依据与核定原因不能为空')
        return value.strip()


@router.post('/cases/{case_id}/responsibility', status_code=201)
def assess_responsibility(case_id: int, payload: ResponsibilityAssessment,
                          user: dict = Depends(require('after_sales.review'))):
    permission(user, 'after_sales.view')
    with orm_session(write=True) as db:
        row = require_visible_after_sales(db, get_case(db, case_id), user)
        if row.version != payload.version:
            raise HTTPException(409, '售后版本已变化，请刷新后核对；本次输入未生效')
        if row.status not in ('submitted', 'approved', 'processing', 'received', 'repaired', 'closed'):
            raise HTTPException(409, '只有已提交且未取消或冲销的售后单可核定责任')
        if user['id'] in authors(db, row):
            raise HTTPException(403, '编制、修订或提交过此申请的账号不能核定责任')
        ensure_date_unlocked(db, now())
        if row.closed_at:
            ensure_date_unlocked(db, row.closed_at)
        history = responsibility_data(db, row)
        if history and (history[-1]['outcome'], history[-1]['basis']) == (payload.outcome, payload.basis):
            raise HTTPException(409, '责任结果及依据未变化，无须重复登记')
        before = model_data(row)
        db.add(AfterSalesResponsibility(case_id=row.id, outcome=payload.outcome,
            basis=payload.basis, reason=payload.reason, assessed_by=user['id']))
        row.version += 1
        audit(db, row, 'assess_responsibility', before, user['id'], payload.reason, payload.basis)
        return case_data(db, row)
