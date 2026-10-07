"""按仓库的现存量预警，规则与修订证据统一使用 ORM。"""

from app.core.document_responses import NumberedRoute
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from app.access.security import require
from app.catalog.material_rules import material_choice_data
from app.core.models import InventoryWarningRule, InventoryWarningChange, Material, Warehouse, StockMovement, User
from app.core.orm import orm_session, add_model, model_data

router = APIRouter(route_class=NumberedRoute, prefix='/api/v1/inventory/warnings')
PositiveId = Annotated[int, Path(gt=0)]


class RuleInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    version: int = Field(ge=0, strict=True)
    threshold: Decimal
    enabled: bool = Field(strict=True)
    reason: str = Field(min_length=1, max_length=200)

    @field_validator('threshold', mode='before')
    @classmethod
    def exact_quantity(cls, value):
        if isinstance(value, (float, bool)):
            raise ValueError('预警阈值请使用十进制文本')
        return value

    @field_validator('threshold')
    @classmethod
    def precision(cls, value):
        if not value.is_finite() or value < 0 or value > 1_000_000 or value.as_tuple().exponent < -3:
            raise ValueError('阈值须非负、最多三位小数且不超过一百万')
        return abs(value) if value.is_zero() else value


def source(db, model, identifier, label):
    row = db.get(model, identifier)
    if row is None:
        raise HTTPException(404, f'{label}不存在')
    return row


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def snapshot(db, row):
    warehouse = source(db, Warehouse, row.warehouse_id, '仓库')
    material = source(db, Material, row.material_id, '物料')
    return {**model_data(row), 'enabled': bool(row.enabled), 'warehouse_code': warehouse.code,
            'warehouse_name': warehouse.name, 'sku': material.sku, 'material_name': material.name, 'unit': material.unit}


def current_row(db, row, quantity):
    threshold = Decimal(row.threshold)
    state = 'disabled' if not row.enabled else 'out_of_stock' if quantity <= 0 else 'low' if quantity < threshold else 'normal'
    return {**snapshot(db, row), 'quantity': format(quantity, 'f'), 'status': state,
            'shortage': format(max(Decimal(0), threshold - quantity), 'f') if row.enabled else None}


def balances(db, warehouse_id=None):
    statement = select(StockMovement.warehouse_id, StockMovement.material_id, StockMovement.quantity)
    if warehouse_id is not None:
        statement = statement.where(StockMovement.warehouse_id == warehouse_id)
    values = {}
    # 不在 SQLite 中 SUM 文本，保留逐笔 Decimal 的精度，也不抵消不同仓库。
    for warehouse, material, quantity in db.execute(statement):
        key = (warehouse, material)
        values[key] = values.get(key, Decimal(0)) + Decimal(quantity)
    return values


def history(db, row):
    return [{'id': change.id, 'reason': change.reason, 'changed_by': change.changed_by,
             'changed_by_name': username, 'created_at': change.created_at,
             'before': json.loads(change.before_json) if change.before_json is not None else None,
             'after': json.loads(change.after_json)}
            for change, username in db.execute(select(InventoryWarningChange, User.username)
                .join(User, User.id == InventoryWarningChange.changed_by)
                .where(InventoryWarningChange.rule_id == row.id).order_by(InventoryWarningChange.id))]


@router.get('')
def overview(warehouse_id: Annotated[int | None, Query(gt=0)] = None,
             _: dict = Depends(require('inventory.view'))):
    with orm_session() as db:
        if warehouse_id is not None:
            source(db, Warehouse, warehouse_id, '仓库')
        values = balances(db, warehouse_id)
        statement = select(InventoryWarningRule).order_by(InventoryWarningRule.warehouse_id, InventoryWarningRule.material_id)
        if warehouse_id is not None:
            statement = statement.where(InventoryWarningRule.warehouse_id == warehouse_id)
        rows = [current_row(db, rule, values.get((rule.warehouse_id, rule.material_id), Decimal(0)))
                for rule in db.scalars(statement)]
        warehouses = [{'id': row.id, 'code': row.code, 'name': row.name} for row in db.scalars(select(Warehouse).order_by(Warehouse.code))]
        materials = [material_choice_data(row) for row in db.scalars(select(Material).order_by(Material.sku))]
        count = len(materials) * (1 if warehouse_id is not None else len(warehouses))
        return {'as_of': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
                'warehouse_id': warehouse_id, 'rows': rows, 'warehouses': warehouses, 'materials': materials,
                'summary': {**{state: sum(row['status'] == state for row in rows)
                              for state in ('normal','low','out_of_stock','disabled')},
                            'configured': len(rows), 'unconfigured': count - len(rows)}}


@router.get('/rules/{warehouse_id}/{material_id}')
def detail(warehouse_id: PositiveId, material_id: PositiveId, _: dict = Depends(require('inventory.view'))):
    with orm_session() as db:
        source(db, Warehouse, warehouse_id, '仓库')
        source(db, Material, material_id, '物料')
        row = db.scalar(select(InventoryWarningRule).where(InventoryWarningRule.warehouse_id == warehouse_id,
                                                          InventoryWarningRule.material_id == material_id))
        if row is None:
            raise HTTPException(404, '此仓库与物料尚未配置预警规则')
        quantity = balances(db, warehouse_id).get((warehouse_id, material_id), Decimal(0))
        return {'row': current_row(db, row, quantity), 'changes': history(db, row)}


@router.put('/rules/{warehouse_id}/{material_id}')
def save(warehouse_id: PositiveId, material_id: PositiveId, payload: RuleInput,
         user: dict = Depends(require('inventory_warning.manage'))):
    if 'inventory.view' not in user['permissions']:
        raise HTTPException(403, '没有库存查看权限')
    with orm_session(write=True) as db:
        source(db, Warehouse, warehouse_id, '仓库')
        source(db, Material, material_id, '物料')
        row = db.scalar(select(InventoryWarningRule).where(InventoryWarningRule.warehouse_id == warehouse_id,
                                                          InventoryWarningRule.material_id == material_id))
        if payload.version != (row.version if row else 0):
            raise HTTPException(409, '预警规则已被修改，请读取最新证据后重新修订，不能覆盖他人的更正')
        before = snapshot(db, row) if row else None
        if row is None:
            row = add_model(db, InventoryWarningRule(warehouse_id=warehouse_id, material_id=material_id,
                threshold=format(payload.threshold.quantize(Decimal('0.001')), 'f'), enabled=int(payload.enabled),
                version=1, created_by=user['id']))
        else:
            row.threshold = format(payload.threshold.quantize(Decimal('0.001')), 'f')
            row.enabled = int(payload.enabled)
            row.version += 1
        db.flush()
        db.add(InventoryWarningChange(rule_id=row.id, before_json=encoded(before) if before else None,
            after_json=encoded(snapshot(db, row)), reason=payload.reason, changed_by=user['id']))
        db.flush()
        quantity = balances(db, warehouse_id).get((warehouse_id, material_id), Decimal(0))
        return {'row': current_row(db, row, quantity), 'changes': history(db, row)}
