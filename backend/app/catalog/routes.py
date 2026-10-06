"""供应商与物料基础资料接口。"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.access.security import require
from app.core.models import Material, Supplier, SupplierChange, SupplierMaterial, User
from app.core.orm import orm_session, model_data
from app.catalog.material_rules import (CATEGORY_CODES, MATERIAL_CATEGORIES, DETAIL_FIELDS,
    allocate_material_code, reserve_legacy_code, material_data, record_material_change)

from app.catalog.supplier_profiles import (PROFILE_FIELDS, SupplierInput, SupplierBindingInput,
    supplier_data, record_supplier_change, material_supplier_ids, save_material_suppliers)
from app.catalog.units import resolve_material_unit

router = APIRouter(prefix="/api/v1")


def supplier_change_data(change: SupplierChange, username: str) -> dict:
    return {'id': change.id, 'supplier_id': change.supplier_id, 'action': change.action,
            'before': json.loads(change.before_json) if change.before_json else None,
            'after': json.loads(change.after_json) if change.after_json else None,
            'reason': change.reason, 'changed_by': change.changed_by,
            'changed_by_name': username, 'created_at': change.created_at}


class MaterialInput(BaseModel):
    # 未传供货关系时兼容旧客户端；显式空列表表示解除所有绑定。
    suppliers: list[SupplierBindingInput] | None = Field(default=None, max_length=20)
    # 编码留空时由类别分配；无分类的旧客户端仍可提交原有手工编码。
    sku: str = Field(default="", max_length=40)
    name: str = Field(min_length=1, max_length=120)
    unit: str = Field(min_length=1, max_length=20)
    # 可选编号兼容旧调用；新桌面必须提交从单位目录选择的编号和名称。
    unit_id: int | None = Field(default=None, ge=1, strict=True)
    category_code: str = Field(default="", max_length=10)
    specification: str = Field(default="", max_length=200)
    package: str = Field(default="", max_length=80)
    brand: str = Field(default="", max_length=120)
    manufacturer_part_number: str = Field(default="", max_length=120)
    electrical_value: str = Field(default="", max_length=80)
    tolerance: str = Field(default="", max_length=80)
    rated_voltage: str = Field(default="", max_length=80)
    rated_power: str = Field(default="", max_length=80)
    temperature_range: str = Field(default="", max_length=80)
    compliance: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=1000)
    version: int | None = Field(default=None, ge=1, strict=True)
    reason: str = Field(default="", max_length=500)

    @field_validator("*")
    @classmethod
    def trim_fields(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode='after')
    def validate_material(self):
        if not self.name or not self.unit:
            raise ValueError('名称和单位不能为空')
        if self.category_code and self.category_code not in CATEGORY_CODES:
            raise ValueError('请选择有效的物料子类')
        return self


def flush_catalog(db: Session, message: str) -> None:
    # 在接口的事务内触发约束，冲突映射为原有 409 语义，外层统一回滚。
    try:
        db.flush()
    except IntegrityError:
        raise HTTPException(409, message) from None


@router.get("/suppliers")
def list_suppliers(_: dict = Depends(require("inventory.view"))) -> list[dict]:
    with orm_session() as db:
        return [supplier_data(row) for row in db.scalars(select(Supplier).order_by(Supplier.name))]


class SupplierPageQuery(BaseModel):
    # 限制页大小和搜索长度，避免客户端提交无界查询。
    query: str = Field(default="", max_length=120)
    page: int = Field(default=1, ge=1, le=2147483647)
    page_size: int = Field(default=20, ge=1, le=100)


@router.post("/suppliers/query")
def query_suppliers(payload: SupplierPageQuery,
                    _: dict = Depends(require("inventory.view"))) -> dict:
    with orm_session() as db:
        # 总数与当前页使用同一快照，搜索按字面子串匹配，不把通配符当查询语法。
        match = func.instr(func.lower(Supplier.name), func.lower(payload.query.strip())) > 0
        total = db.scalar(select(func.count()).select_from(Supplier).where(match))
        page = min(payload.page, max(1, (total + payload.page_size - 1) // payload.page_size))
        rows = db.scalars(select(Supplier).where(match).order_by(Supplier.name, Supplier.id)
            .limit(payload.page_size).offset((page - 1) * payload.page_size))
        return {"items": [supplier_data(row) for row in rows], "total": total,
                "page": page, "page_size": payload.page_size}


@router.get("/suppliers/{supplier_id}")
def supplier_detail(supplier_id: int, _: dict = Depends(require("inventory.view"))) -> dict:
    with orm_session() as db:
        row = db.get(Supplier, supplier_id)
        if row is None:
            raise HTTPException(404, '供应商不存在')
        return supplier_data(row)


@router.get("/supplier-changes")
def recent_supplier_changes(before_id: int | None = Query(default=None, gt=0),
                            limit: int = Query(default=100, ge=1, le=500),
                            _: dict = Depends(require("inventory.view"))) -> list[dict]:
    with orm_session() as db:
        statement = select(SupplierChange, User.username).join(User, User.id == SupplierChange.changed_by)
        if before_id is not None:
            statement = statement.where(SupplierChange.id < before_id)
        return [supplier_change_data(change, username) for change, username in
                db.execute(statement.order_by(SupplierChange.id.desc()).limit(limit))]


@router.get("/suppliers/{supplier_id}/changes")
def supplier_changes(supplier_id: int, _: dict = Depends(require("inventory.view"))) -> list[dict]:
    with orm_session() as db:
        rows = db.execute(select(SupplierChange, User.username).join(User, User.id == SupplierChange.changed_by)
            .where(SupplierChange.supplier_id == supplier_id).order_by(SupplierChange.id.desc())).all()
        if not rows and db.get(Supplier, supplier_id) is None:
            raise HTTPException(404, '供应商不存在')
        return [supplier_change_data(change, username) for change, username in rows]


@router.post("/suppliers", status_code=201)
def create_supplier(payload: SupplierInput, actor: dict = Depends(require("catalog.manage"))) -> dict:
    with orm_session(write=True) as db:
        supplier = Supplier(name=payload.name, version=1,
                            **{key: getattr(payload, key) for key in PROFILE_FIELDS})
        db.add(supplier)
        flush_catalog(db, "供应商已存在")
        record_supplier_change(db, supplier, 'create', None, actor, payload.reason or '新增供应商')
        return supplier_data(supplier)


@router.get("/material-categories")
def material_categories(_: dict = Depends(require("inventory.view"))) -> list[dict]:
    # 分类与编码前缀以服务端目录为准，客户端只展示中文名称并提交固定子类代码。
    return MATERIAL_CATEGORIES


@router.get("/materials")
def list_materials(_: dict = Depends(require("inventory.view"))) -> list[dict]:
    with orm_session() as db:
        return [material_data(row) for row in db.scalars(select(Material).order_by(Material.sku))]


@router.get("/materials/{material_id}")
def material_detail(material_id: int, include_suppliers: bool = False, _: dict = Depends(require("inventory.view"))) -> dict:
    # 打开编辑器时重新读取当前版本，冲突后取消再打开不重复使用旧列表快照。
    with orm_session() as db:
        material = db.get(Material, material_id)
        if material is None:
            raise HTTPException(404, '物料不存在')
        result = material_data(material)
        if include_suppliers:
            result['supplier_ids'] = material_supplier_ids(db, material.id)
        return result


@router.post("/materials", status_code=201)
def create_material(payload: MaterialInput, actor: dict = Depends(require("catalog.manage"))) -> dict:
    if not payload.category_code and not payload.sku:
        raise HTTPException(422, '请先选择物料子类，编码将在保存时自动生成')
    if payload.category_code and payload.sku:
        raise HTTPException(422, '分类物料的编码由系统自动生成，请勿手工填写')
    with orm_session(write=True) as db:
        resolve_material_unit(db, payload.unit, payload.unit_id, actor)
        sku = allocate_material_code(db, payload.category_code) if payload.category_code else payload.sku
        if not payload.category_code:
            reserve_legacy_code(db, sku)
        material = Material(sku=sku, name=payload.name, unit=payload.unit,
                            **{key: getattr(payload, key) for key in DETAIL_FIELDS}, version=1)
        db.add(material)
        flush_catalog(db, "物料编码已存在")
        ids = save_material_suppliers(db, material, payload.suppliers, actor) if payload.suppliers is not None else None
        record_material_change(db, material, 'create', None, actor, payload.reason or '新增物料', supplier_ids=ids)
        return material_data(material)


@router.put("/materials/{material_id}")
def update_material(material_id: int, payload: MaterialInput,
                    actor: dict = Depends(require("catalog.manage"))) -> dict:
    with orm_session(write=True) as db:
        material = db.get(Material, material_id)
        if material is None:
            raise HTTPException(404, "物料不存在")
        if payload.version != material.version:
            raise HTTPException(409, '物料资料已更新或未提供版本，请重新加载后编辑')
        if payload.sku and payload.sku != material.sku:
            raise HTTPException(409, '物料编码建立后不可修改')
        resolve_material_unit(db, payload.unit, payload.unit_id, actor, material.unit)
        before = material_data(material)
        if payload.suppliers is not None:
            before['supplier_ids'] = material_supplier_ids(db, material.id)
        # 兼容仅改名称/单位的请求；未提交的详细字段保留，显式空字符串才清除。
        material.name, material.unit = payload.name, payload.unit
        for key in DETAIL_FIELDS:
            if key in payload.model_fields_set:
                setattr(material, key, getattr(payload, key))
        material.version += 1
        ids = save_material_suppliers(db, material, payload.suppliers, actor) if payload.suppliers is not None else None
        record_material_change(db, material, 'update', before, actor, payload.reason or '修改物料资料', supplier_ids=ids)
        return material_data(material)


@router.delete("/materials/{material_id}", status_code=204)
def delete_material(material_id: int, actor: dict = Depends(require("catalog.manage"))) -> None:
    with orm_session(write=True) as db:
        material = db.get(Material, material_id)
        if material is None:
            raise HTTPException(404, "物料不存在")
        record_material_change(db, material, 'delete', material_data(material), actor, '删除未被引用的物料')
        db.delete(material)
        flush_catalog(db, "物料已被业务单据或库存记录引用，不能删除")


@router.put("/suppliers/{supplier_id}")
def update_supplier(supplier_id: int, payload: SupplierInput,
                    actor: dict = Depends(require("catalog.manage"))) -> dict:
    with orm_session(write=True) as db:
        supplier = db.get(Supplier, supplier_id)
        if supplier is None:
            raise HTTPException(404, "供应商不存在")
        if payload.version != supplier.version:
            raise HTTPException(409, '供应商资料已更新或未提供版本，请重新加载后编辑')
        if not payload.reason:
            raise HTTPException(422, '请填写供应商资料修改原因')
        # 只修改调用方明确传入的字段；同名供应商也可以补充联系资料。
        changed = {key: getattr(payload, key) for key in ('name', *PROFILE_FIELDS)
                   if key in payload.model_fields_set}
        if all(getattr(supplier, key) == value for key, value in changed.items()):
            raise HTTPException(409, '供应商资料没有变化')
        before = supplier_data(supplier)
        for key, value in changed.items():
            setattr(supplier, key, value)
        supplier.version += 1
        flush_catalog(db, "供应商已存在")
        record_supplier_change(db, supplier, 'update', before, actor, payload.reason)
        return supplier_data(supplier)


@router.delete("/suppliers/{supplier_id}", status_code=204)
def delete_supplier(supplier_id: int, version: int = Query(ge=1),
                    actor: dict = Depends(require("catalog.manage"))) -> None:
    with orm_session(write=True) as db:
        supplier = db.get(Supplier, supplier_id)
        if supplier is None:
            raise HTTPException(404, "供应商不存在")
        if version != supplier.version:
            raise HTTPException(409, '供应商资料已更新，请重新加载后删除')
        before = supplier_data(supplier)
        db.delete(supplier)
        flush_catalog(db, "供应商已被业务单据引用，不能删除")
        record_supplier_change(db, supplier, 'delete', before, actor, '删除未被引用的供应商')


@router.get("/supplier-materials")
def list_supplier_materials(_: dict = Depends(require("inventory.view"))) -> list[dict]:
    with orm_session() as db:
        return [model_data(row) for row in db.scalars(select(SupplierMaterial)
            .order_by(SupplierMaterial.supplier_id, SupplierMaterial.material_id))]


@router.put("/suppliers/{supplier_id}/materials/{material_id}", status_code=204)
def bind_supplier_material(supplier_id: int, material_id: int,
                           actor: dict = Depends(require("catalog.manage"))) -> None:
    with orm_session(write=True) as db:
        if db.get(Supplier, supplier_id) is None:
            raise HTTPException(404, "供应商不存在")
        material = db.get(Material, material_id)
        if material is None:
            raise HTTPException(404, "物料不存在")
        if db.get(SupplierMaterial, (supplier_id, material_id)) is None:
            before = dict(material_data(material), supplier_ids=material_supplier_ids(db, material_id))
            db.add(SupplierMaterial(supplier_id=supplier_id, material_id=material_id))
            # 其他页面绑定同样推进版本，防止已打开的物料草稿覆盖新的供货关系。
            material.version += 1
            record_material_change(db, material, 'update', before, actor, '绑定供应商',
                                   supplier_ids=sorted([*before['supplier_ids'], supplier_id]))


@router.delete("/suppliers/{supplier_id}/materials/{material_id}", status_code=204)
def unbind_supplier_material(supplier_id: int, material_id: int,
                             actor: dict = Depends(require("catalog.manage"))) -> None:
    with orm_session(write=True) as db:
        link = db.get(SupplierMaterial, (supplier_id, material_id))
        if link is None:
            raise HTTPException(404, "供货关系不存在")
        material = db.get(Material, material_id)
        before = dict(material_data(material), supplier_ids=material_supplier_ids(db, material_id))
        db.delete(link)
        material.version += 1
        record_material_change(db, material, 'update', before, actor, '解除供应商绑定',
                               supplier_ids=[key for key in before['supplier_ids'] if key != supplier_id])
