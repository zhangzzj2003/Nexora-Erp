"""商机批量导入；金额只作为预估，不产生销售单或财务凭证。"""

from app.core.document_responses import NumberedRoute
from decimal import Decimal
from hashlib import sha256
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access.security import require
from app.core.models import CrmChange, CrmOpportunity, User
from app.core.orm import add_model, orm_session
from app.sales.crm_rules import (StrictInput, audit, require_contact, require_customer,
                                 require_owner, valid_date, validate_amount)
from app.sales.customer_names import comparable_customer_name


router = APIRouter(route_class=NumberedRoute, prefix='/api/v1/crm/opportunities')


class OpportunityImportRow(StrictInput):
    customer_id: int = Field(strict=True, gt=0)
    title: str = Field(min_length=1, max_length=160)
    owner_id: int = Field(strict=True, gt=0)
    estimated_amount: Decimal
    expected_close_date: str
    contact_id: int | None = Field(default=None, strict=True, gt=0)
    note: str = Field(default='', max_length=1000)
    _date = field_validator('expected_close_date')(valid_date)
    _amount = field_validator('estimated_amount')(validate_amount)

    @field_validator('title', 'note')
    @classmethod
    def valid_text(cls, value: str) -> str:
        if any(ord(char) < 32 for char in value):
            raise ValueError('商机资料不能包含控制字符')
        return value

    @field_validator('title')
    @classmethod
    def valid_title(cls, title: str) -> str:
        if not comparable_customer_name(title):
            raise ValueError('商机名称无效')
        return title


class OpportunityImportPreviewInput(StrictInput):
    rows: list[OpportunityImportRow] = Field(min_length=1, max_length=100)


class OpportunityImportInput(OpportunityImportPreviewInput):
    reason: str = Field(min_length=1, max_length=200)
    allow_similar: bool = Field(default=False, strict=True)


def preview_rows(db: Session, rows: list[OpportunityImportRow], user: dict) -> list[dict]:
    customers = {row.customer_id: require_customer(db, row.customer_id, user) for row in rows}
    existing = list(db.scalars(select(CrmOpportunity).where(
        CrmOpportunity.customer_id.in_(customers)).order_by(CrmOpportunity.id)))
    result = []
    for index, row in enumerate(rows):
        require_owner(db, row.owner_id)
        owner = db.get(User, row.owner_id)
        contact = require_contact(db, row.customer_id, row.contact_id)
        key = comparable_customer_name(row.title)
        candidates = [opportunity.id for opportunity in existing
                      if opportunity.customer_id == row.customer_id
                      and comparable_customer_name(opportunity.title) == key]
        batch_rows = [earlier + 1 for earlier in range(index)
                      if rows[earlier].customer_id == row.customer_id
                      and comparable_customer_name(rows[earlier].title) == key]
        result.append({'row': index + 1, 'customer_id': row.customer_id,
                       'customer_name': customers[row.customer_id].name, 'title': row.title,
                       'owner_id': row.owner_id,
                       'owner_name': owner.full_name or owner.username,
                       'contact_name': contact.name if contact else '',
                       'existing_opportunity_ids': candidates, 'batch_rows': batch_rows,
                       'requires_confirmation': bool(candidates or batch_rows)})
    return result


@router.post('/import-preview')
def preview_opportunity_import(payload: OpportunityImportPreviewInput,
                               user: dict = Depends(require('crm_opportunity.manage'))) -> dict:
    with orm_session() as db:
        rows = preview_rows(db, payload.rows, user)
    return {'rows': rows, 'requires_confirmation': any(row['requires_confirmation'] for row in rows)}


@router.post('/import', status_code=201)
def import_opportunities(payload: OpportunityImportInput,
                         user: dict = Depends(require('crm_opportunity.manage'))) -> dict:
    batch_reference = sha256(json.dumps([row.model_dump(mode='json') for row in payload.rows],
                                        ensure_ascii=False, sort_keys=True,
                                        separators=(',', ':')).encode('utf-8')).hexdigest()[:16]
    with orm_session(write=True) as db:
        if db.scalar(select(CrmChange.id).where(CrmChange.entity_kind == 'opportunity',
                CrmChange.action == 'create', CrmChange.changed_by == user['id'],
                CrmChange.reason.like(f'批量导入 {batch_reference} 第1条：%')).limit(1)):
            raise HTTPException(409, '该批商机已导入，请刷新资料核对')
        checked = preview_rows(db, payload.rows, user)
        if any(row['requires_confirmation'] for row in checked) and not payload.allow_similar:
            raise HTTPException(409, '同一客户下有同名商机，请核对并确认导入')
        created = []
        for index, row in enumerate(payload.rows, start=1):
            opportunity = add_model(db, CrmOpportunity(**{
                **row.model_dump(exclude={'estimated_amount'}),
                'estimated_amount': str(row.estimated_amount),
                'stage': 'prospect', 'version': 1, 'created_by': user['id']}))
            audit(db, 'opportunity', opportunity, 'create', None,
                  f'批量导入 {batch_reference} 第{index}条：{payload.reason}', user['id'])
            created.append({'id': opportunity.id, 'customer_id': opportunity.customer_id,
                            'title': opportunity.title, 'version': opportunity.version})
        return {'batch_reference': batch_reference, 'created': created}
