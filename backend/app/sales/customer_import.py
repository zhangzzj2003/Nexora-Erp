"""客户名称批量导入；预检与提交共用同一套 ORM 可见范围规则。"""

from hashlib import sha256
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.access.security import require
from app.core.models import Customer, CustomerOwnerChange
from app.core.orm import add_model, orm_session
from app.sales.customer_names import (comparable_customer_name, duplicate_candidates,
                                      name_match, visible_name_rows)

router = APIRouter(prefix='/api/v1/customers')


class CustomerImportPreviewInput(BaseModel):
    model_config = {'extra': 'forbid'}
    names: list[str] = Field(min_length=1, max_length=100)

    @field_validator('names')
    @classmethod
    def valid_names(cls, names: list[str]) -> list[str]:
        cleaned = []
        seen = set()
        for name in names:
            value = name.strip()
            key = comparable_customer_name(value)
            if not value or len(value) > 120 or not key or any(ord(char) < 32 for char in value):
                raise ValueError('客户名称须为 1 至 120 字且不能包含控制字符')
            if key in seen:
                raise ValueError('导入名单中有重复的客户名称')
            seen.add(key)
            cleaned.append(value)
        return cleaned


class CustomerImportInput(CustomerImportPreviewInput):
    reason: str = Field(min_length=1, max_length=200)
    allow_similar: bool = Field(default=False, strict=True)

    @field_validator('reason')
    @classmethod
    def valid_reason(cls, reason: str) -> str:
        if not reason.strip():
            raise ValueError('请填写导入依据')
        return reason.strip()


def preview_rows(names: list[str], existing: list[tuple[int, str]]) -> list[dict]:
    rows = []
    for index, name in enumerate(names):
        candidates = duplicate_candidates(name, existing)
        batch_candidates = [earlier + 1 for earlier in range(index)
                            if name_match(name, names[earlier])]
        rows.append({'row': index + 1, 'name': name, 'candidates': candidates,
                     'batch_candidates': batch_candidates,
                     'can_import': not any(row['match'] == 'same_name' for row in candidates),
                     'requires_confirmation': any(row['match'] == 'similar_name' for row in candidates)
                     or bool(batch_candidates)})
    return rows


@router.post('/import-preview')
def preview_customer_import(payload: CustomerImportPreviewInput,
                            user: dict = Depends(require('customer.manage'))) -> dict:
    with orm_session() as db:
        rows = preview_rows(payload.names, visible_name_rows(db, user))
    return {'rows': rows, 'can_import': all(row['can_import'] for row in rows),
            'requires_confirmation': any(row['requires_confirmation'] for row in rows)}


@router.post('/import', status_code=201)
def import_customers(payload: CustomerImportInput,
                     user: dict = Depends(require('customer.manage'))) -> dict:
    batch_reference = sha256(json.dumps(payload.names, ensure_ascii=False,
                                        separators=(',', ':')).encode('utf-8')).hexdigest()[:16]
    try:
        with orm_session(write=True) as db:
            rows = preview_rows(payload.names, visible_name_rows(db, user))
            if not all(row['can_import'] for row in rows):
                raise HTTPException(409, '已有相同名称的可见客户，请修改导入名单')
            # 不披露其他负责人资料，但也不让空白和标点变体绕过全局同名保护。
            all_names = list(db.scalars(select(Customer.name)))
            if any(name_match(name, existing) == 'same_name'
                   for name in payload.names for existing in all_names):
                raise HTTPException(409, '客户名称冲突，导入未写入任何客户')
            if any(row['requires_confirmation'] for row in rows) and not payload.allow_similar:
                raise HTTPException(409, '存在相似客户，请核对并确认导入')
            created = []
            for index, name in enumerate(payload.names, start=1):
                customer = add_model(db, Customer(name=name, owner_id=user['id'], version=1))
                db.add(CustomerOwnerChange(customer_id=customer.id, before_owner_id=None,
                    after_owner_id=user['id'], version=1,
                    reason=f'批量导入 {batch_reference} 第{index}条：{payload.reason}',
                    changed_by=user['id']))
                created.append({'id': customer.id, 'name': name,
                                'owner_id': user['id'], 'version': 1})
            return {'batch_reference': batch_reference, 'created': created}
    except IntegrityError:
        # 其他负责人名下的精确重名不经预检披露，由数据库唯一约束整体回滚。
        raise HTTPException(409, '客户名称冲突，导入未写入任何客户') from None
