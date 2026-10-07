"""联系人批量导入；预检与提交共享客户可见范围和重复提示。"""

from app.core.document_responses import NumberedRoute
from hashlib import sha256
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access.security import require
from app.core.models import CrmChange, CrmContact
from app.core.orm import add_model, orm_session
from app.sales.crm_rules import StrictInput, audit
from app.sales.customer_names import comparable_customer_name
from app.sales.customer_scope import require_visible_customer


router = APIRouter(route_class=NumberedRoute, prefix='/api/v1/crm/contacts')


class ContactImportRow(StrictInput):
    customer_id: int = Field(strict=True, gt=0)
    name: str = Field(min_length=1, max_length=120)
    job_title: str = Field(default='', max_length=120)
    phone: str = Field(default='', max_length=80)
    email: str = Field(default='', max_length=160)
    note: str = Field(default='', max_length=1000)

    @field_validator('name')
    @classmethod
    def valid_name(cls, name: str) -> str:
        if not comparable_customer_name(name) or any(ord(char) < 32 for char in name):
            raise ValueError('联系人姓名无效')
        return name

    @field_validator('job_title', 'phone', 'email', 'note')
    @classmethod
    def no_control_chars(cls, value: str) -> str:
        if any(ord(char) < 32 for char in value):
            raise ValueError('联系人资料不能包含控制字符')
        return value


class ContactImportPreviewInput(StrictInput):
    rows: list[ContactImportRow] = Field(min_length=1, max_length=100)


class ContactImportInput(ContactImportPreviewInput):
    reason: str = Field(min_length=1, max_length=200)
    allow_similar: bool = Field(default=False, strict=True)


def preview_rows(db: Session, rows: list[ContactImportRow], user: dict) -> list[dict]:
    customer_ids = {row.customer_id for row in rows}
    customers = {identifier: require_visible_customer(db, identifier, user) for identifier in customer_ids}
    existing = list(db.scalars(select(CrmContact).where(CrmContact.customer_id.in_(customer_ids))
                               .order_by(CrmContact.id)))
    result = []
    for index, row in enumerate(rows):
        key = comparable_customer_name(row.name)
        candidates = [contact.id for contact in existing if contact.customer_id == row.customer_id
                      and comparable_customer_name(contact.name) == key]
        batch_rows = [earlier + 1 for earlier in range(index)
                      if rows[earlier].customer_id == row.customer_id
                      and comparable_customer_name(rows[earlier].name) == key]
        result.append({'row': index + 1, 'customer_id': row.customer_id,
                       'customer_name': customers[row.customer_id].name, 'name': row.name,
                       'existing_contact_ids': candidates, 'batch_rows': batch_rows,
                       'requires_confirmation': bool(candidates or batch_rows)})
    return result


@router.post('/import-preview')
def preview_contact_import(payload: ContactImportPreviewInput,
                           user: dict = Depends(require('crm_contact.manage'))) -> dict:
    with orm_session() as db:
        rows = preview_rows(db, payload.rows, user)
    return {'rows': rows, 'requires_confirmation': any(row['requires_confirmation'] for row in rows)}


@router.post('/import', status_code=201)
def import_contacts(payload: ContactImportInput,
                    user: dict = Depends(require('crm_contact.manage'))) -> dict:
    batch_reference = sha256(json.dumps([row.model_dump() for row in payload.rows], ensure_ascii=False,
                                        sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()[:16]
    with orm_session(write=True) as db:
        # 网络响应丢失时，重试同一批名单不可再次建立联系人。
        if db.scalar(select(CrmChange.id).where(CrmChange.entity_kind == 'contact',
                CrmChange.action == 'create', CrmChange.changed_by == user['id'],
                CrmChange.reason.like(f'批量导入 {batch_reference} 第1条：%')).limit(1)):
            raise HTTPException(409, '该批联系人已导入，请刷新资料核对')
        checked = preview_rows(db, payload.rows, user)
        if any(row['requires_confirmation'] for row in checked) and not payload.allow_similar:
            raise HTTPException(409, '同一客户下有同名联系人，请核对并确认导入')
        created = []
        for index, row in enumerate(payload.rows, start=1):
            contact = add_model(db, CrmContact(**row.model_dump(), is_active=1, version=1,
                                               created_by=user['id']))
            audit(db, 'contact', contact, 'create', None,
                  f'批量导入 {batch_reference} 第{index}条：{payload.reason}', user['id'])
            created.append({'id': contact.id, 'customer_id': contact.customer_id,
                            'name': contact.name, 'version': contact.version})
        return {'batch_reference': batch_reference, 'created': created}
