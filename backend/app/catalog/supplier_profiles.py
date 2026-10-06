"""供应商资料、完善状态及物料保存时的供货关系。"""

import json

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.models import Material, Supplier, SupplierChange, SupplierMaterial

PROFILE_FIELDS = ('contact_name', 'phone', 'email', 'address', 'tax_number',
                  'bank_name', 'bank_account', 'notes')


class SupplierInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    contact_name: str = Field(default='', max_length=80)
    phone: str = Field(default='', max_length=40)
    email: str = Field(default='', max_length=150)
    address: str = Field(default='', max_length=300)
    tax_number: str = Field(default='', max_length=80)
    bank_name: str = Field(default='', max_length=120)
    bank_account: str = Field(default='', max_length=80)
    notes: str = Field(default='', max_length=1000)
    version: int | None = Field(default=None, ge=1, strict=True)
    reason: str = Field(default='', max_length=500)

    @field_validator('*')
    @classmethod
    def trim_fields(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode='after')
    def required_name(self):
        if not self.name:
            raise ValueError('供应商名称不能为空')
        return self


class SupplierBindingInput(BaseModel):
    model_config = {'extra': 'forbid'}
    supplier_id: int | None = Field(default=None, gt=0, strict=True)
    name: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator('name')
    @classmethod
    def trim_name(cls, value):
        if value is not None and not value.strip():
            raise ValueError('供应商名称不能为空')
        return value.strip() if value is not None else None

    @model_validator(mode='after')
    def exclusive_reference(self):
        # 已有供应商按编号绑定；新名称不能同时冒充一个已有编号。
        if (self.supplier_id is None) == (self.name is None):
            raise ValueError('请选择已有供应商或输入新名称')
        return self


def supplier_data(row: Supplier) -> dict:
    # 状态由真实必填资料推导，客户端不能把一个空档案标成已完善。
    complete = all(getattr(row, key).strip() for key in ('contact_name', 'phone', 'address'))
    return dict(id=row.id, name=row.name, version=row.version,
                profile_status='complete' if complete else 'pending',
                **{key: getattr(row, key) for key in PROFILE_FIELDS})


def record_supplier_change(db: Session, row: Supplier, action: str,
                           before: dict | None, actor: dict, reason: str) -> None:
    # 审计不依赖供应商外键，删除未引用的档案后仍保留前后快照。
    db.add(SupplierChange(supplier_id=row.id, action=action,
        before_json=json.dumps(before, ensure_ascii=False) if before is not None else None,
        after_json=json.dumps(supplier_data(row), ensure_ascii=False) if action != 'delete' else None,
        reason=reason, changed_by=actor['id']))


def material_supplier_ids(db: Session, material_id: int) -> list[int]:
    return list(db.scalars(select(SupplierMaterial.supplier_id)
        .where(SupplierMaterial.material_id == material_id).order_by(SupplierMaterial.supplier_id)))


def save_material_suppliers(db: Session, material: Material,
                            choices: list[SupplierBindingInput], actor: dict) -> list[int]:
    # 与物料和编码共用写锁与事务，取消表单不写库，保存失败不遗留空供应商。
    ids = set()
    for choice in choices:
        if choice.supplier_id is not None:
            supplier = db.get(Supplier, choice.supplier_id)
            if supplier is None:
                raise HTTPException(404, '所选供应商已不存在，请重新选择')
        else:
            candidates = list(db.scalars(select(Supplier).where(
                func.lower(Supplier.name) == choice.name.lower()).order_by(Supplier.id)))
            supplier = next((row for row in candidates if row.name == choice.name), None)
            if supplier is None and len(candidates) > 1:
                raise HTTPException(409, '存在多个同名供应商，请从已有档案中选择')
            if supplier is None and candidates:
                supplier = candidates[0]
            if supplier is None:
                supplier = Supplier(name=choice.name, version=1,
                                    **{key: '' for key in PROFILE_FIELDS})
                db.add(supplier)
                db.flush()
                record_supplier_change(db, supplier, 'create', None, actor, '物料绑定时创建待完善供应商')
        ids.add(supplier.id)
    for link in db.scalars(select(SupplierMaterial).where(SupplierMaterial.material_id == material.id)):
        if link.supplier_id not in ids:
            db.delete(link)
    for supplier_id in ids:
        if db.get(SupplierMaterial, (supplier_id, material.id)) is None:
            db.add(SupplierMaterial(supplier_id=supplier_id, material_id=material.id))
    return sorted(ids)
