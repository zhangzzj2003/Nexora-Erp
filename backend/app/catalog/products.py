"""产品与机型管理：沿用统一物料身份，联合写入在同一 ORM 事务提交。"""

import json
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, or_, select
from app.access.security import require, current_user
from app.catalog.routes import MaterialInput, create_material_in_session, update_material_in_session, flush_catalog
from app.catalog.product_rules import product_data, product_change, validate_model
from app.core.models import Material, ProductProfile, ProductModel, ProductChange, User, Bom, BomLine
from app.core.orm import orm_session, model_data

router = APIRouter(prefix='/api/v1')
ProductKind = Literal['finished', 'semi_finished', 'component', 'unclassified']


class ProductFields(BaseModel):
    kind: ProductKind = 'unclassified'
    model_id: int | None = Field(default=None, ge=1, strict=True)
    configuration_name: str = Field(default='', max_length=120)
    # 省略时创建保持旧行为，编辑时保留原值，避免旧客户端误开启已禁用用途。
    can_sell: bool | None = Field(default=None, strict=True)
    can_purchase: bool | None = Field(default=None, strict=True)
    can_produce: bool | None = Field(default=None, strict=True)
    reason: str = Field(default='', max_length=500)

    @field_validator('configuration_name', 'reason')
    @classmethod
    def trim_text(cls, value):
        return value.strip()

    @model_validator(mode='after')
    def validate_uses(self):
        # 只有省略字段才兼容旧客户端，显式 null 不能被误当成恢复或保留用途。
        for name in ('can_sell', 'can_purchase', 'can_produce'):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError('产品用途须为明确的布尔值')
        return self


class ProductInput(ProductFields):
    material_id: int | None = Field(default=None, ge=1, strict=True)
    material: MaterialInput | None = None

    @model_validator(mode='after')
    def validate_identity(self):
        if (self.material_id is None) == (self.material is None):
            raise ValueError('请选择纳入已有物料或新建物料资料，两者不能同时提供')
        return self


class ProductUpdate(ProductFields):
    version: int = Field(ge=1, strict=True)
    material: MaterialInput | None = None

    @model_validator(mode='after')
    def require_reason(self):
        if not self.reason:
            raise ValueError('请填写修改原因')
        return self


class ProductQuery(BaseModel):
    query: str = Field(default='', max_length=120)
    kind: ProductKind | None = None
    model_id: int | None = Field(default=None, ge=1, strict=True)
    page: int = Field(default=1, ge=1, le=2147483647)
    page_size: int = Field(default=20, ge=1, le=100)


class ModelInput(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=120)
    notes: str = Field(default='', max_length=500)
    version: int | None = Field(default=None, ge=1, strict=True)
    reason: str = Field(default='', max_length=500)

    @field_validator('code', 'name', 'notes', 'reason')
    @classmethod
    def trim_text(cls, value):
        return value.strip()

    @model_validator(mode='after')
    def validate_text(self):
        if not self.code or not self.name:
            raise ValueError('机型编码与名称不能为空')
        return self


@router.get('/product-bom-features')
def product_bom_features(_: dict = Depends(current_user)) -> dict:
    # 仅声明协议能力，供新客户端在写入前拒绝会忽略新字段的旧服务。
    return {'independent_uses': True, 'component_bom_versions': True}


def changes(db, kind, entity_id):
    return [{'id': row.id, 'before': json.loads(row.before_json) if row.before_json else None,
             'after': json.loads(row.after_json), 'reason': row.reason, 'changed_by_name': name,
             'created_at': row.created_at} for row, name in db.execute(select(ProductChange, User.username)
        .join(User, User.id == ProductChange.changed_by)
        .where(ProductChange.entity_kind == kind, ProductChange.entity_id == entity_id)
        .order_by(ProductChange.id.desc()))]


@router.post('/products/query')
def query_products(payload: ProductQuery, _: dict = Depends(require('inventory.view'))) -> dict:
    with orm_session() as db:
        terms = [ProductProfile.deleted_at.is_(None)]
        if payload.kind:
            terms.append(ProductProfile.kind == payload.kind)
        if payload.model_id is not None:
            terms.append(ProductProfile.model_id == payload.model_id)
        keyword = payload.query.strip()
        if keyword:
            # 字面子串搜索，不把用户输入当 LIKE 通配符；规格直接引用当前物料字段。
            fields = [Material.sku, Material.name, Material.specification, Material.package,
                      Material.manufacturer_part_number, Material.spec_values_json, Material.extra_attributes_json,
                      ProductProfile.configuration_name, ProductModel.code, ProductModel.name]
            terms.append(or_(*(func.instr(func.lower(field), keyword.lower()) > 0 for field in fields)))
        base = select(ProductProfile).join(Material, Material.id == ProductProfile.material_id)
        base = base.outerjoin(ProductModel, ProductModel.id == ProductProfile.model_id).where(*terms)
        total = db.scalar(select(func.count()).select_from(base.subquery()))
        page = min(payload.page, max(1, (total + payload.page_size - 1) // payload.page_size))
        rows = db.scalars(base.order_by(Material.sku, ProductProfile.id)
                          .limit(payload.page_size).offset((page - 1) * payload.page_size))
        return {'items': [product_data(db, row) for row in rows], 'total': total,
                'page': page, 'page_size': payload.page_size}


@router.get('/products/{product_id}')
def product_detail(product_id: int, _: dict = Depends(require('inventory.view'))) -> dict:
    with orm_session() as db:
        row = db.get(ProductProfile, product_id)
        if row is None or row.deleted_at is not None:
            raise HTTPException(404, '子机型不存在或已删除')
        return product_data(db, row)


@router.get('/products/{product_id}/changes')
def product_changes(product_id: int, _: dict = Depends(require('inventory.view'))) -> list[dict]:
    with orm_session() as db:
        if db.get(ProductProfile, product_id) is None:
            raise HTTPException(404, '产品不存在')
        return changes(db, 'product', product_id)


@router.post('/products', status_code=201)
def create_product(payload: ProductInput, actor: dict = Depends(require('catalog.manage'))) -> dict:
    with orm_session(write=True) as db:
        validate_model(db, payload.model_id)
        material_id = payload.material_id
        if payload.material is not None:
            material_id = create_material_in_session(db, payload.material, actor)['id']
        elif db.get(Material, material_id) is None:
            raise HTTPException(422, '所选物料不存在')
        row = ProductProfile(material_id=material_id, kind=payload.kind, model_id=payload.model_id,
            configuration_name=payload.configuration_name, version=1, created_by=actor['id'])
        for field in ('can_sell', 'can_purchase', 'can_produce'):
            setattr(row, field, getattr(payload, field) if getattr(payload, field) is not None else True)
        db.add(row)
        flush_catalog(db, '该物料已纳入产品管理，请直接查看或编辑')
        product_change(db, 'product', row, None, actor, payload.reason or '新增产品档案')
        return product_data(db, row)


@router.put('/products/{product_id}')
def update_product(product_id: int, payload: ProductUpdate, actor: dict = Depends(require('catalog.manage'))) -> dict:
    with orm_session(write=True) as db:
        row = db.get(ProductProfile, product_id)
        if row is None or row.deleted_at is not None:
            raise HTTPException(404, '子机型不存在或已删除')
        if row.version != payload.version:
            raise HTTPException(409, '产品资料已更新，请重新加载后编辑')
        validate_model(db, payload.model_id)
        before = product_data(db, row)
        if payload.material is not None:
            update_material_in_session(db, row.material_id, payload.material, actor)
        row.kind, row.model_id = payload.kind, payload.model_id
        for field in ('can_sell', 'can_purchase', 'can_produce'):
            if getattr(payload, field) is not None:
                setattr(row, field, getattr(payload, field))
        row.configuration_name, row.version = payload.configuration_name, row.version + 1
        db.flush()
        product_change(db, 'product', row, before, actor, payload.reason)
        return product_data(db, row)


@router.get('/product-models')
def list_models(_: dict = Depends(require('inventory.view'))) -> list[dict]:
    with orm_session() as db:
        # 数量覆盖整个系列，不能用前端搜索结果或当前分页判断能否删除。
        counts = dict(db.execute(select(ProductProfile.model_id, func.count(ProductProfile.id))
                                 .where(ProductProfile.deleted_at.is_(None)).group_by(ProductProfile.model_id)).all())
        return [{**model_data(row), 'child_count': counts.get(row.id, 0)} for row in db.scalars(
            select(ProductModel).where(ProductModel.deleted_at.is_(None)).order_by(ProductModel.code, ProductModel.id))]


@router.get('/product-models/{model_id}')
def model_detail(model_id: int, _: dict = Depends(require('inventory.view'))) -> dict:
    with orm_session() as db:
        row = db.get(ProductModel, model_id)
        if row is None:
            raise HTTPException(404, '机型不存在')
        return {**model_data(row), 'child_count': db.scalar(select(func.count(ProductProfile.id)).where(ProductProfile.model_id == model_id, ProductProfile.deleted_at.is_(None)))}


@router.get('/product-models/{model_id}/changes')
def model_changes(model_id: int, _: dict = Depends(require('inventory.view'))) -> list[dict]:
    with orm_session() as db:
        if db.get(ProductModel, model_id) is None:
            raise HTTPException(404, '机型不存在')
        return changes(db, 'model', model_id)


@router.post('/product-models', status_code=201)
def create_model(payload: ModelInput, actor: dict = Depends(require('catalog.manage'))) -> dict:
    with orm_session(write=True) as db:
        row = ProductModel(code=payload.code, name=payload.name, notes=payload.notes,
                           version=1, created_by=actor['id'])
        db.add(row)
        flush_catalog(db, '机型编码已存在')
        product_change(db, 'model', row, None, actor, payload.reason or '新增机型')
        return model_data(row)


@router.put('/product-models/{model_id}')
def update_model(model_id: int, payload: ModelInput, actor: dict = Depends(require('catalog.manage'))) -> dict:
    with orm_session(write=True) as db:
        row = db.get(ProductModel, model_id)
        if row is None or row.deleted_at is not None:
            raise HTTPException(404, '产品系列不存在或已删除')
        if row.version != payload.version:
            raise HTTPException(409, '机型资料已更新，请重新加载后编辑')
        if not payload.reason:
            raise HTTPException(422, '请填写修改原因')
        before = model_data(row)
        row.code, row.name, row.notes, row.version = payload.code, payload.name, payload.notes, row.version + 1
        flush_catalog(db, '机型编码已存在')
        product_change(db, 'model', row, before, actor, payload.reason)
        return model_data(row)


class ModelDeleteInput(BaseModel):
    version: int = Field(ge=1, strict=True)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator('reason')
    @classmethod
    def require_reason(cls, value):
        if not value.strip():
            raise ValueError('请填写删除原因')
        return value.strip()


@router.delete('/product-models/{model_id}')
def delete_model(model_id: int, payload: ModelDeleteInput, actor: dict = Depends(require('catalog.manage'))) -> dict:
    # BEGIN IMMEDIATE 串行化删除与子机型建档/归组；完整关联校验和软删除、审计必须同事务提交。
    with orm_session(write=True) as db:
        row = db.get(ProductModel, model_id)
        if row is None or row.deleted_at is not None:
            raise HTTPException(404, '产品系列不存在或已删除')
        if row.version != payload.version:
            raise HTTPException(409, '产品系列已更新，请刷新后再删除')
        count = db.scalar(select(func.count(ProductProfile.id)).where(ProductProfile.model_id == model_id, ProductProfile.deleted_at.is_(None)))
        if count:
            raise HTTPException(409, f'此系列仍有 {count} 个子机型，请先删除子机型后再删除系列')
        before = model_data(row)
        row.deleted_at = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        row.deleted_by, row.deletion_reason = actor['id'], payload.reason
        row.version += 1
        db.flush()
        product_change(db, 'model', row, before, actor, payload.reason)
        return {**model_data(row), 'child_count': 0}


@router.delete('/products/{product_id}')
def delete_product(product_id: int, payload: ModelDeleteInput, actor: dict = Depends(require('catalog.manage'))) -> dict:
    with orm_session(write=True) as db:
        row = db.get(ProductProfile, product_id)
        if row is None or row.deleted_at is not None:
            raise HTTPException(404, '子机型不存在或已删除')
        if row.version != payload.version:
            raise HTTPException(409, '子机型已更新，请刷新后再删除')
        # 未删除上层的启用配方仍受保护；已删除上层只剩历史，不得永久卡住后续目录清理。
        parents = db.scalar(select(func.count(BomLine.id)).join(Bom, Bom.id == BomLine.bom_id).where(
            Bom.status == 'active', BomLine.component_material_id == row.material_id,
            BomLine.component_bom_id.is_not(None), Bom.product_material_id.not_in(
                select(ProductProfile.material_id).where(ProductProfile.deleted_at.is_not(None)))))
        if parents:
            raise HTTPException(409, '子机型仍被启用的上层 BOM 固定引用，请先修订或停用上层 BOM')
        before = product_data(db, row)
        row.deleted_at = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        row.deleted_by, row.deletion_reason, row.can_produce = actor['id'], payload.reason, False
        row.version += 1
        db.flush()
        product_change(db, 'product', row, before, actor, payload.reason)
        return product_data(db, row)
