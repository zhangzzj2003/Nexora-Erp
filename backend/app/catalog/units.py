"""独立的物料单位目录、版本编辑与变更留存。"""

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.access.security import require
from app.core.models import Material, MaterialUnit, MaterialUnitChange, User
from app.core.orm import model_data, orm_session

router = APIRouter(prefix='/api/v1/material-units')


class UnitInput(BaseModel):
    # 名称长度与物料单位一致，空格不能绕过必填或名称唯一约束。
    name: str = Field(min_length=1, max_length=20)
    enabled: bool = Field(default=True, strict=True)
    notes: str = Field(default='', max_length=500)
    version: int | None = Field(default=None, ge=1, strict=True)
    reason: str = Field(default='', max_length=500)

    @field_validator('name', 'notes', 'reason')
    @classmethod
    def trim_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode='after')
    def validate_name(self):
        if not self.name:
            raise ValueError('单位名称不能为空')
        return self


def unit_data(db: Session, row: MaterialUnit) -> dict:
    # 引用数按实际物料名称计算，编辑单位表不会批量改写物料。
    return {**model_data(row), 'material_count': db.scalar(
        select(func.count()).select_from(Material).where(Material.unit == row.name))}


def record_unit_change(db: Session, row: MaterialUnit, before: dict | None,
                       actor: dict, reason: str) -> None:
    # 审计只保存单位本身的字段，引用数是查询结果而非单位属性。
    db.add(MaterialUnitChange(unit_id=row.id,
        before_json=json.dumps(before, ensure_ascii=False) if before else None,
        after_json=json.dumps(model_data(row), ensure_ascii=False),
        changed_by=actor['id'], reason=reason))


def flush_unit(db: Session) -> None:
    try:
        db.flush()
    except IntegrityError:
        raise HTTPException(409, '单位名称已存在') from None


@router.get('')
def list_units(_: dict = Depends(require('inventory.view'))) -> list[dict]:
    with orm_session() as db:
        return [unit_data(db, row) for row in db.scalars(select(MaterialUnit).order_by(MaterialUnit.id))]


@router.get('/{unit_id}')
def unit_detail(unit_id: int, _: dict = Depends(require('inventory.view'))) -> dict:
    with orm_session() as db:
        row = db.get(MaterialUnit, unit_id)
        if row is None:
            raise HTTPException(404, '单位不存在')
        return unit_data(db, row)


@router.post('', status_code=201)
def create_unit(payload: UnitInput, actor: dict = Depends(require('catalog.manage'))) -> dict:
    with orm_session(write=True) as db:
        row = MaterialUnit(name=payload.name, enabled=payload.enabled, notes=payload.notes, version=1)
        db.add(row)
        flush_unit(db)
        record_unit_change(db, row, None, actor, payload.reason or '新增单位')
        return unit_data(db, row)


@router.put('/{unit_id}')
def update_unit(unit_id: int, payload: UnitInput,
                actor: dict = Depends(require('catalog.manage'))) -> dict:
    with orm_session(write=True) as db:
        row = db.get(MaterialUnit, unit_id)
        if row is None:
            raise HTTPException(404, '单位不存在')
        if payload.version != row.version:
            raise HTTPException(409, '单位资料已更新，请重新打开编辑窗口')
        if not payload.reason:
            raise HTTPException(422, '请填写修改原因')
        if row.name != payload.name and db.scalar(select(Material.id).where(Material.unit == row.name).limit(1)):
            raise HTTPException(409, '已被物料使用的单位不能改名，可以停用后新增单位')
        before = model_data(row)
        row.name, row.enabled, row.notes = payload.name, payload.enabled, payload.notes
        row.version += 1
        flush_unit(db)
        record_unit_change(db, row, before, actor, payload.reason)
        return unit_data(db, row)


@router.get('/{unit_id}/changes')
def unit_changes(unit_id: int, _: dict = Depends(require('inventory.view'))) -> list[dict]:
    with orm_session() as db:
        if db.get(MaterialUnit, unit_id) is None:
            raise HTTPException(404, '单位不存在')
        rows = db.execute(select(MaterialUnitChange, User.username).join(User, User.id == MaterialUnitChange.changed_by)
            .where(MaterialUnitChange.unit_id == unit_id).order_by(MaterialUnitChange.id.desc()).limit(100))
        return [{'id': change.id, 'unit_id': unit_id,
                 'before': json.loads(change.before_json) if change.before_json else None,
                 'after': json.loads(change.after_json), 'reason': change.reason,
                 'changed_by_name': username, 'created_at': change.created_at} for change, username in rows]


def resolve_material_unit(db: Session, name: str, unit_id: int | None,
                          actor: dict, previous: str | None = None) -> None:
    # 新客户端提交所选编号；旧客户端仅传文字时收录目录，兼容既有导入接口。
    row = db.get(MaterialUnit, unit_id) if unit_id is not None else db.scalar(select(MaterialUnit).where(MaterialUnit.name == name))
    if unit_id is not None and (row is None or row.name != name):
        raise HTTPException(409, '所选单位已变更或不存在，请刷新单位列表后重选')
    if row is None:
        row = MaterialUnit(name=name, enabled=True, notes='', version=1)
        db.add(row)
        flush_unit(db)
        record_unit_change(db, row, None, actor, '兼容旧客户端物料单位')
    if not row.enabled and name != previous:
        raise HTTPException(409, '所选单位已停用，请选择启用的单位')
