"""两级物料分类和分类规格模板的维护、版本及审计。"""

import json
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.access.security import require
from app.core.models import Material, MaterialCategory, MaterialSpecField, MaterialCategoryChange, User
from app.core.orm import orm_session, model_data

router = APIRouter(prefix='/api/v1/material-categories')


class RevisionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: int = Field(ge=1, strict=True)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator('reason')
    @classmethod
    def reason_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('请填写修改原因')
        return value.strip()


class CategoryInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    code: str = Field(pattern=r'^[A-Z]{2,4}(?:-[A-Z]{2,4})?$', max_length=10)
    parent_code: str | None = Field(default=None, pattern=r'^[A-Z]{2,4}$')
    name: str = Field(min_length=1, max_length=80)
    enabled: bool = Field(default=True, strict=True)
    sort_order: int = Field(default=0, ge=0, le=9999, strict=True)
    notes: str = Field(default='', max_length=500)
    version: int | None = Field(default=None, ge=1, strict=True)
    reason: str = Field(default='', max_length=500)

    @field_validator('name', 'notes', 'reason')
    @classmethod
    def trim_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode='after')
    def validate_path(self):
        if not self.name or ('-' in self.code) != bool(self.parent_code):
            raise ValueError('请填写名称并选择正确的大类或子类')
        if self.parent_code and not re.fullmatch(re.escape(self.parent_code) + r'-[A-Z]{2,4}', self.code):
            raise ValueError('子类短码必须以大类短码开头')
        return self


class SpecFieldInput(RevisionInput):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal['text', 'number', 'enum', 'boolean', 'date']
    unit: str = Field(default='', max_length=20)
    options: list[str] = Field(default_factory=list, max_length=50)
    allow_custom: bool = Field(default=False, strict=True)
    required: bool = Field(default=False, strict=True)
    enabled: bool = Field(default=True, strict=True)
    sort_order: int = Field(default=0, ge=0, le=9999, strict=True)

    @field_validator('name', 'unit')
    @classmethod
    def trim_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode='after')
    def validate_options(self):
        self.options = [value.strip() for value in self.options]
        if not self.name or any(not value or len(value) > 120 for value in self.options) or len(set(self.options)) != len(self.options):
            raise ValueError('字段名称及选项不能为空或重复')
        if self.kind != 'enum' and (self.options or self.allow_custom):
            raise ValueError('仅选项字段支持常用选项和自定义值')
        if self.kind != 'number' and self.unit:
            raise ValueError('仅数值字段设置单位')
        if self.kind == 'enum' and not self.options and not self.allow_custom:
            raise ValueError('选项字段至少设置一个选项，或允许自定义值')
        return self


def field_data(row: MaterialSpecField) -> dict:
    result = model_data(row)
    result['options'] = json.loads(result.pop('options_json'))
    return result


def category_directory(db: Session) -> dict[str, dict]:
    # 同一个读快照只加载一次目录，所有业务选料复用，避免逐物料查询。
    if 'material_category_directory' not in db.info:
        fields: dict[str, list] = {}
        for row in db.scalars(select(MaterialSpecField).where(MaterialSpecField.deleted == False)
                              .order_by(MaterialSpecField.sort_order, MaterialSpecField.id)):
            fields.setdefault(row.category_code, []).append(field_data(row))
        counts = dict(db.execute(select(Material.category_code, func.count()).group_by(Material.category_code)).all())
        db.info['material_category_directory'] = {row.code: {**model_data(row),
            'fields': fields.get(row.code, []), 'material_count': counts.get(row.code, 0)}
            for row in db.scalars(select(MaterialCategory).order_by(MaterialCategory.sort_order, MaterialCategory.code))}
    return db.info['material_category_directory']


def category_data(db: Session, row: MaterialCategory) -> dict:
    db.info.pop('material_category_directory', None)
    return category_directory(db)[row.code]


def category_tree(db: Session) -> list[dict]:
    directory = category_directory(db)
    return [{**group, 'children': [child for child in directory.values()
        if child['parent_code'] == group['code'] and not child['deleted']]}
        for group in directory.values() if group['parent_code'] is None and not group['deleted']]


def find_category(db: Session, code: str, *, child: bool = False) -> MaterialCategory:
    row = db.get(MaterialCategory, code)
    if row is None or row.deleted:
        raise HTTPException(404, '物料类别不存在')
    if child and not row.parent_code:
        raise HTTPException(422, '规格模板只能在子类中维护')
    return row


def validate_selection(db: Session, code: str, previous: str | None = None) -> None:
    if not code:
        return
    row = db.get(MaterialCategory, code)
    if row is None or row.deleted or not row.parent_code:
        raise HTTPException(422, '请选择有效的物料子类')
    parent = db.get(MaterialCategory, row.parent_code)
    if code != previous and (not row.enabled or not parent.enabled):
        raise HTTPException(409, '所选物料类别已停用，请重新选择')
    # 标记一经使用不再释放，删除物料后也不能复用前缀。
    row.used = True


def check_revision(row: MaterialCategory, payload: RevisionInput | CategoryInput) -> None:
    if payload.version != row.version:
        raise HTTPException(409, '分类或规格模板已更新，请刷新后核对；当前输入请先保留')
    if not payload.reason.strip():
        raise HTTPException(422, '请填写修改原因')


def record_change(db: Session, row: MaterialCategory, action: str, before: dict | None,
                  actor: dict, reason: str) -> dict:
    db.flush()
    result = category_data(db, row)
    db.add(MaterialCategoryChange(category_code=row.code, action=action,
        before_json=json.dumps(before, ensure_ascii=False) if before else None,
        after_json=json.dumps(result, ensure_ascii=False), changed_by=actor['id'], reason=reason))
    return result


def check_name(db: Session, parent: str | None, name: str, code: str) -> None:
    if db.scalar(select(MaterialCategory.code).where(MaterialCategory.parent_code == parent,
            MaterialCategory.name == name, MaterialCategory.deleted == False, MaterialCategory.code != code)):
        raise HTTPException(409, '同一层级已有此类别名称')


@router.get('')
def list_categories(_: dict = Depends(require('inventory.view'))) -> list[dict]:
    with orm_session() as db:
        return category_tree(db)


@router.post('', status_code=201)
def create_category(payload: CategoryInput, actor: dict = Depends(require('catalog.manage'))) -> dict:
    with orm_session(write=True) as db:
        if db.get(MaterialCategory, payload.code):
            raise HTTPException(409, '分类短码已占用，包括曾移除的类别')
        if payload.parent_code:
            parent = find_category(db, payload.parent_code)
            if parent.parent_code or not parent.enabled:
                raise HTTPException(409, '请选择启用的大类')
        check_name(db, payload.parent_code, payload.name, payload.code)
        row = MaterialCategory(**payload.model_dump(exclude={'version', 'reason'}), version=1, template_version=1)
        db.add(row)
        return record_change(db, row, 'create', None, actor, payload.reason or '新增物料类别')


@router.put('/{code}')
def update_category(code: str, payload: CategoryInput, actor: dict = Depends(require('catalog.manage'))) -> dict:
    with orm_session(write=True) as db:
        row = find_category(db, code)
        check_revision(row, payload)
        if payload.code != row.code or payload.parent_code != row.parent_code:
            raise HTTPException(409, '分类短码与父类建立后不可修改')
        check_name(db, row.parent_code, payload.name, row.code)
        before = category_data(db, row)
        row.name, row.notes, row.enabled, row.sort_order = payload.name, payload.notes, payload.enabled, payload.sort_order
        row.version += 1
        return record_change(db, row, 'update', before, actor, payload.reason)


@router.delete('/{code}')
def delete_category(code: str, payload: RevisionInput, actor: dict = Depends(require('catalog.manage'))) -> dict:
    with orm_session(write=True) as db:
        row = find_category(db, code)
        check_revision(row, payload)
        if row.used or db.scalar(select(Material.id).where(Material.category_code == code).limit(1)) or db.scalar(
                select(MaterialCategory.code).where(MaterialCategory.parent_code == code, MaterialCategory.deleted == False).limit(1)):
            raise HTTPException(409, '类别已使用或仍有子类，请停用以保留历史关联')
        before = category_data(db, row)
        row.deleted, row.enabled = True, False
        row.version += 1
        return record_change(db, row, 'delete', before, actor, payload.reason)


def save_field(db: Session, category: MaterialCategory, payload: SpecFieldInput,
               actor: dict, field_id: int | None = None) -> dict:
    check_revision(category, payload)
    before = category_data(db, category)
    row = db.get(MaterialSpecField, field_id) if field_id else None
    if field_id and (row is None or row.category_code != category.code or row.deleted):
        raise HTTPException(404, '规格字段不存在')
    if row and row.used and (row.kind != payload.kind or row.unit != payload.unit):
        raise HTTPException(409, '已使用字段不能改类型或单位，请停用后另建字段')
    if db.scalar(select(MaterialSpecField.id).where(MaterialSpecField.category_code == category.code,
            MaterialSpecField.name == payload.name, MaterialSpecField.deleted == False,
            MaterialSpecField.id != (field_id or 0))):
        raise HTTPException(409, '该子类已有同名字段')
    if row is None:
        if db.scalar(select(func.count()).select_from(MaterialSpecField).where(
                MaterialSpecField.category_code == category.code, MaterialSpecField.deleted == False)) >= 50:
            raise HTTPException(422, '每个子类最多维护 50 个规格字段')
        row = MaterialSpecField(category_code=category.code)
        db.add(row)
    for key in ('name', 'kind', 'unit', 'allow_custom', 'required', 'enabled', 'sort_order'):
        setattr(row, key, getattr(payload, key))
    row.options_json = json.dumps(payload.options, ensure_ascii=False)
    category.version += 1
    category.template_version += 1
    return record_change(db, category, 'field_update' if field_id else 'field_create', before, actor, payload.reason)


@router.post('/{code}/fields', status_code=201)
def create_field(code: str, payload: SpecFieldInput, actor: dict = Depends(require('catalog.manage'))) -> dict:
    with orm_session(write=True) as db:
        return save_field(db, find_category(db, code, child=True), payload, actor)


@router.put('/{code}/fields/{field_id}')
def update_field(code: str, field_id: int, payload: SpecFieldInput, actor: dict = Depends(require('catalog.manage'))) -> dict:
    with orm_session(write=True) as db:
        return save_field(db, find_category(db, code, child=True), payload, actor, field_id)


@router.delete('/{code}/fields/{field_id}')
def delete_field(code: str, field_id: int, payload: RevisionInput, actor: dict = Depends(require('catalog.manage'))) -> dict:
    with orm_session(write=True) as db:
        category = find_category(db, code, child=True)
        check_revision(category, payload)
        row = db.get(MaterialSpecField, field_id)
        if row is None or row.category_code != code or row.deleted:
            raise HTTPException(404, '规格字段不存在')
        if row.used:
            raise HTTPException(409, '字段已被物料使用，请停用以保留历史值')
        before = category_data(db, category)
        row.deleted, row.enabled = True, False
        category.version += 1
        category.template_version += 1
        return record_change(db, category, 'field_delete', before, actor, payload.reason)


@router.get('/{code}/changes')
def category_changes(code: str, _: dict = Depends(require('inventory.view'))) -> list[dict]:
    with orm_session() as db:
        if db.get(MaterialCategory, code) is None:
            raise HTTPException(404, '物料类别不存在')
        return [{'id': row.id, 'category_code': code, 'action': row.action,
            'before': json.loads(row.before_json) if row.before_json else None,
            'after': json.loads(row.after_json), 'reason': row.reason, 'changed_by_name': name, 'created_at': row.created_at}
            for row, name in db.execute(select(MaterialCategoryChange, User.username)
                .join(User, User.id == MaterialCategoryChange.changed_by)
                .where(MaterialCategoryChange.category_code == code).order_by(MaterialCategoryChange.id.desc()).limit(100))]
