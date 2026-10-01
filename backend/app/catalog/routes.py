"""供应商与物料基础资料接口。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.access.security import require
from app.core.models import Material, Supplier, SupplierMaterial
from app.core.orm import orm_session, model_data
from app.catalog.material_rules import (CATEGORY_CODES, MATERIAL_CATEGORIES, DETAIL_FIELDS,
    allocate_material_code, reserve_legacy_code, material_data, record_material_change)

router = APIRouter(prefix="/api/v1")


class SupplierInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("供应商名称不能为空")
        return value.strip()


class MaterialInput(BaseModel):
    # 编码留空时由类别分配；无分类的旧客户端仍可提交原有手工编码。
    sku: str = Field(default="", max_length=40)
    name: str = Field(min_length=1, max_length=120)
    unit: str = Field(min_length=1, max_length=20)
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
        return [{'id': row.id, 'name': row.name} for row in db.scalars(select(Supplier).order_by(Supplier.name))]


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
        return {"items": [{'id': row.id, 'name': row.name} for row in rows], "total": total,
                "page": page, "page_size": payload.page_size}


@router.post("/suppliers", status_code=201)
def create_supplier(payload: SupplierInput, _: dict = Depends(require("catalog.manage"))) -> dict:
    with orm_session(write=True) as db:
        supplier = Supplier(name=payload.name)
        db.add(supplier)
        flush_catalog(db, "供应商已存在")
        return {"id": supplier.id, "name": supplier.name}


@router.get("/material-categories")
def material_categories(_: dict = Depends(require("inventory.view"))) -> list[dict]:
    # 分类与编码前缀以服务端目录为准，客户端只展示中文名称并提交固定子类代码。
    return MATERIAL_CATEGORIES


@router.get("/materials")
def list_materials(_: dict = Depends(require("inventory.view"))) -> list[dict]:
    with orm_session() as db:
        return [material_data(row) for row in db.scalars(select(Material).order_by(Material.sku))]


@router.get("/materials/{material_id}")
def material_detail(material_id: int, _: dict = Depends(require("inventory.view"))) -> dict:
    # 打开编辑器时重新读取当前版本，冲突后取消再打开不重复使用旧列表快照。
    with orm_session() as db:
        material = db.get(Material, material_id)
        if material is None:
            raise HTTPException(404, '物料不存在')
        return material_data(material)


@router.post("/materials", status_code=201)
def create_material(payload: MaterialInput, actor: dict = Depends(require("catalog.manage"))) -> dict:
    if not payload.category_code and not payload.sku:
        raise HTTPException(422, '请先选择物料子类，编码将在保存时自动生成')
    if payload.category_code and payload.sku:
        raise HTTPException(422, '分类物料的编码由系统自动生成，请勿手工填写')
    with orm_session(write=True) as db:
        sku = allocate_material_code(db, payload.category_code) if payload.category_code else payload.sku
        if not payload.category_code:
            reserve_legacy_code(db, sku)
        material = Material(sku=sku, name=payload.name, unit=payload.unit,
                            **{key: getattr(payload, key) for key in DETAIL_FIELDS}, version=1)
        db.add(material)
        flush_catalog(db, "物料编码已存在")
        record_material_change(db, material, 'create', None, actor, payload.reason or '新增物料')
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
        before = material_data(material)
        # 兼容仅改名称/单位的请求；未提交的详细字段保留，显式空字符串才清除。
        material.name, material.unit = payload.name, payload.unit
        for key in DETAIL_FIELDS:
            if key in payload.model_fields_set:
                setattr(material, key, getattr(payload, key))
        material.version += 1
        record_material_change(db, material, 'update', before, actor, payload.reason or '修改物料资料')
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
                    _: dict = Depends(require("catalog.manage"))) -> dict:
    with orm_session(write=True) as db:
        supplier = db.get(Supplier, supplier_id)
        if supplier is None:
            raise HTTPException(404, "供应商不存在")
        supplier.name = payload.name
        flush_catalog(db, "供应商已存在")
        return {"id": supplier_id, **payload.model_dump()}


@router.delete("/suppliers/{supplier_id}", status_code=204)
def delete_supplier(supplier_id: int, _: dict = Depends(require("catalog.manage"))) -> None:
    with orm_session(write=True) as db:
        supplier = db.get(Supplier, supplier_id)
        if supplier is None:
            raise HTTPException(404, "供应商不存在")
        db.delete(supplier)
        flush_catalog(db, "供应商已被业务单据引用，不能删除")


@router.get("/supplier-materials")
def list_supplier_materials(_: dict = Depends(require("inventory.view"))) -> list[dict]:
    with orm_session() as db:
        return [model_data(row) for row in db.scalars(select(SupplierMaterial)
            .order_by(SupplierMaterial.supplier_id, SupplierMaterial.material_id))]


@router.put("/suppliers/{supplier_id}/materials/{material_id}", status_code=204)
def bind_supplier_material(supplier_id: int, material_id: int,
                           _: dict = Depends(require("catalog.manage"))) -> None:
    with orm_session(write=True) as db:
        if db.get(Supplier, supplier_id) is None:
            raise HTTPException(404, "供应商不存在")
        if db.get(Material, material_id) is None:
            raise HTTPException(404, "物料不存在")
        if db.get(SupplierMaterial, (supplier_id, material_id)) is None:
            db.add(SupplierMaterial(supplier_id=supplier_id, material_id=material_id))


@router.delete("/suppliers/{supplier_id}/materials/{material_id}", status_code=204)
def unbind_supplier_material(supplier_id: int, material_id: int,
                             _: dict = Depends(require("catalog.manage"))) -> None:
    with orm_session(write=True) as db:
        link = db.get(SupplierMaterial, (supplier_id, material_id))
        if link is None:
            raise HTTPException(404, "供货关系不存在")
        db.delete(link)
