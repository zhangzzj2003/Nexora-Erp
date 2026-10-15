"""产品身份、同事务纳入与可审计变更。"""

import json
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.catalog.material_rules import material_data
from app.catalog.supplier_profiles import material_supplier_ids
from app.core.models import Material, ProductProfile, ProductModel, ProductChange
from app.core.orm import model_data


def product_data(db: Session, row: ProductProfile) -> dict:
    material = db.get(Material, row.material_id)
    model = db.get(ProductModel, row.model_id) if row.model_id else None
    return {**model_data(row), 'material': {**material_data(material),
        'supplier_ids': material_supplier_ids(db, material.id)},
        'model_code': model.code if model else '', 'model_name': model.name if model else ''}


def product_change(db: Session, kind: str, row, before: dict | None, actor: dict, reason: str) -> None:
    after = product_data(db, row) if kind == 'product' else model_data(row)
    db.add(ProductChange(entity_kind=kind, entity_id=row.id,
        before_json=json.dumps(before, ensure_ascii=False) if before is not None else None,
        after_json=json.dumps(after, ensure_ascii=False), reason=reason, changed_by=actor['id']))


def ensure_product(db: Session, material_id: int, actor: dict) -> ProductProfile:
    # 旧 BOM 入口与派生入口也补充同一档案；唯一约束避免重复纳入。
    row = db.scalar(select(ProductProfile).where(ProductProfile.material_id == material_id))
    if row is None:
        row = ProductProfile(material_id=material_id, kind='unclassified', configuration_name='', version=1,
                             created_by=actor['id'])
        db.add(row)
        db.flush()
        product_change(db, 'product', row, None, actor, '由 BOM 建单纳入产品，待分类')
    return row


def validate_model(db: Session, model_id: int | None) -> None:
    if model_id is not None and db.get(ProductModel, model_id) is None:
        raise HTTPException(422, '所选机型不存在，请重新选择')


def require_product_use(db: Session, material_id: int, capability: str) -> None:
    # 未纳入产品的历史物料沿用原流程；产品类型不能代替独立的业务用途开关。
    labels = {'can_sell': '销售', 'can_purchase': '采购', 'can_produce': '生产'}
    if capability not in labels:
        raise ValueError('未知产品用途')
    row = db.scalar(select(ProductProfile).where(ProductProfile.material_id == material_id))
    if row is not None and not getattr(row, capability):
        material = db.get(Material, material_id)
        raise HTTPException(409, f'物料 {material.sku} 未允许{labels[capability]}，请先维护产品资料')
