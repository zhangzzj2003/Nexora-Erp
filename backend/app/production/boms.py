"""生产 BOM 版本与启停用；工单将引用固定版本的成品和组件。"""

from app.core.document_responses import NumberedRoute
from sqlalchemy import select, update, func, literal
from sqlalchemy.orm import Session
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.core.orm import orm_session, add_model
from app.core.models import Bom, BomLine, Material, User
from app.access.security import require

router = APIRouter(route_class=NumberedRoute, prefix="/api/v1")


class BomLineInput(BaseModel):
    component_material_id: int = Field(gt=0)
    quantity: Decimal

    @field_validator("quantity")
    @classmethod
    def valid_quantity(cls, value: Decimal) -> Decimal:
        # 用料与库存采用相同的三位小数精度，后续领料可逐项核对。
        if not value.is_finite() or value <= 0 or value > 1_000_000 or value.as_tuple().exponent < -3:
            raise ValueError("用料数量须大于零、最多三位小数且不超过一百万")
        return value


class BomInput(BaseModel):
    product_material_id: int = Field(gt=0)
    base_quantity: Decimal = Decimal(1)
    note: str = Field(default="", max_length=200)
    lines: list[BomLineInput] = Field(min_length=1, max_length=100)

    @field_validator("base_quantity")
    @classmethod
    def valid_base_quantity(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 0 or value > 1_000_000 or value.as_tuple().exponent < -3:
            raise ValueError("成品基准数量须大于零、最多三位小数且不超过一百万")
        return value


def bom_data(db: Session, bom_id: int) -> dict:
    row = (
        db.execute(
            select(
                Bom.id,
                Bom.product_material_id,
                Bom.version,
                Bom.base_quantity,
                Bom.note,
                Bom.status,
                Bom.created_by,
                Bom.activated_by,
                Bom.retired_by,
                Bom.cancelled_by,
                Bom.created_at,
                Bom.activated_at,
                Bom.retired_at,
                Bom.cancelled_at,
                Material.sku.label("product_sku"),
                Material.name.label("product_name"),
                Material.unit.label("product_unit"),
                User.username.label("created_by_name"),
            )
            .select_from(Bom)
            .join(Material, (Material.id == Bom.product_material_id))
            .join(User, (User.id == Bom.created_by))
            .where((Bom.id == bom_id))
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(404, "BOM 不存在")
    lines = (
        db.execute(
            select(
                BomLine.id,
                BomLine.component_material_id,
                Material.sku,
                Material.name.label("material_name"),
                Material.unit,
                BomLine.quantity,
            )
            .select_from(BomLine)
            .join(Material, (Material.id == BomLine.component_material_id))
            .where((BomLine.bom_id == bom_id))
            .order_by(BomLine.id)
        )
        .mappings()
        .all()
    )
    return {**dict(row), "lines": [dict(line) for line in lines]}


def has_cycle_after_activation(db: Session, product_id: int, components: list[int]) -> bool:
    # 只看启用版本；草稿互相引用尚未生效，启用时必须阻止组件回指成品。
    graph: dict[int, set[int]] = {}
    for row in db.execute(
        select(Bom.product_material_id, BomLine.component_material_id)
        .select_from(Bom)
        .join(BomLine, (BomLine.bom_id == Bom.id))
        .where((Bom.status == "active"))
    ).mappings():
        graph.setdefault(row["product_material_id"], set()).add(row["component_material_id"])
    pending = list(components)
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if current == product_id:
            return True
        if current not in seen:
            seen.add(current)
            pending.extend(graph.get(current, ()))
    return False


@router.get("/boms")
def list_boms(_: dict = Depends(require("production.view"))) -> list[dict]:
    with orm_session() as db:
        ids = [row for row in db.scalars(select(Bom.id).select_from(Bom).order_by(Bom.id.desc()))]
        return [bom_data(db, bom_id) for bom_id in ids]


@router.post("/boms", status_code=201)
def create_bom(payload: BomInput, user: dict = Depends(require("bom.create"))) -> dict:
    component_ids = [line.component_material_id for line in payload.lines]
    if len(set(component_ids)) != len(component_ids):
        raise HTTPException(422, "一份 BOM 不能重复选择同一组件")
    if payload.product_material_id in component_ids:
        raise HTTPException(422, "成品不能直接作为自身组件")
    with orm_session(write=True) as db:
        known = set(db.scalars(select(Material.id)))
        if payload.product_material_id not in known or not set(component_ids) <= known:
            raise HTTPException(422, "成品或组件物料不存在")
        # 版本号在写事务中分配，两个计划员并行建单也不会拿到同一版本。
        version = db.scalar(
            select(func.coalesce(func.max(Bom.version), 0) + 1)
            .select_from(Bom)
            .where(Bom.product_material_id == payload.product_material_id)
        )
        cursor = add_model(
            db,
            Bom(
                product_material_id=payload.product_material_id,
                version=version,
                base_quantity=str(payload.base_quantity),
                note=payload.note.strip(),
                created_by=user["id"],
            ),
        )
        db.add_all(
            [
                BomLine(
                    bom_id=cursor.id,
                    component_material_id=line.component_material_id,
                    quantity=str(line.quantity),
                )
                for line in payload.lines
            ]
        )
        return bom_data(db, cursor.id)


@router.post("/boms/{bom_id}/activate")
def activate_bom(bom_id: int, user: dict = Depends(require("bom.activate"))) -> dict:
    with orm_session(write=True) as db:
        bom = (
            db.execute(select(Bom.product_material_id, Bom.status).select_from(Bom).where((Bom.id == bom_id)))
            .mappings()
            .first()
        )
        if not bom:
            raise HTTPException(404, "BOM 不存在")
        if bom["status"] != "draft":
            raise HTTPException(409, "只有 BOM 草稿可以启用")
        if (
            db.execute(
                select(literal(1))
                .select_from(Bom)
                .where(Bom.product_material_id == bom["product_material_id"], Bom.status == "active")
            )
            .mappings()
            .first()
        ):
            raise HTTPException(409, "此成品已有启用版本，请先停用旧版本")
        components = [
            row
            for row in db.scalars(
                select(BomLine.component_material_id).select_from(BomLine).where(BomLine.bom_id == bom_id)
            )
        ]
        if has_cycle_after_activation(db, bom["product_material_id"], components):
            raise HTTPException(409, "启用后会形成 BOM 循环引用")
        db.execute(
            update(Bom)
            .where((Bom.id == bom_id))
            .values(status="active", activated_by=user["id"], activated_at=func.current_timestamp())
        )
        return bom_data(db, bom_id)


@router.post("/boms/{bom_id}/retire")
def retire_bom(bom_id: int, user: dict = Depends(require("bom.retire"))) -> dict:
    with orm_session(write=True) as db:
        row = db.execute(select(Bom.status).select_from(Bom).where((Bom.id == bom_id))).mappings().first()
        if not row:
            raise HTTPException(404, "BOM 不存在")
        if row["status"] != "active":
            raise HTTPException(409, "只有启用中的 BOM 可以停用")
        db.execute(
            update(Bom)
            .where((Bom.id == bom_id))
            .values(status="retired", retired_by=user["id"], retired_at=func.current_timestamp())
        )
        return bom_data(db, bom_id)


@router.post("/boms/{bom_id}/cancel")
def cancel_bom(bom_id: int, user: dict = Depends(require("bom.cancel"))) -> dict:
    with orm_session(write=True) as db:
        row = db.execute(select(Bom.status).select_from(Bom).where((Bom.id == bom_id))).mappings().first()
        if not row:
            raise HTTPException(404, "BOM 不存在")
        if row["status"] != "draft":
            raise HTTPException(409, "只有 BOM 草稿可以取消")
        db.execute(
            update(Bom)
            .where((Bom.id == bom_id))
            .values(status="cancelled", cancelled_by=user["id"], cancelled_at=func.current_timestamp())
        )
        return bom_data(db, bom_id)
