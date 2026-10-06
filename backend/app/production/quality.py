"""报废与返工处置：严格载荷、独立审核、数量占用及原子转工单。"""

import json
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select

from app.access.security import require
from app.catalog.material_rules import material_choice_data
from app.core.models import (Material, MaterialIssue, MaterialReturn, ProductionCostEntry, ProductionCostReversal,
    ProductionCompletion, ProductionCompletionReversal, QualityDisposition, Warehouse, WorkOrder, WorkOrderLine)
from app.core.orm import orm_session, model_data, add_model
from app.core.period_lock import ensure_date_unlocked
from app.inventory.warehouse import require_warehouse
from app.production.cost_lock import active_settlement, ensure_unsettled
from app.production.work_orders import issued_quantity
from app.production.quality_rules import (source, reserved_quantity, check_quantity, record_for,
    audit, independent_reviewer, disposition_data, now, encoded, settlement_dispositions)

router = APIRouter(prefix='/api/v1/production-quality')


def quantity(value: Decimal) -> Decimal:
    if not value.is_finite() or value <= 0 or value > 1_000_000 or value.as_tuple().exponent < -3:
        raise ValueError('数量须大于零、最多三位小数且不超过一百万')
    return value


class ReworkMaterial(BaseModel):
    model_config = ConfigDict(extra='forbid')
    material_id: int = Field(gt=0, strict=True)
    quantity: Decimal
    _quantity = field_validator('quantity')(quantity)


class VersionReason(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: int = Field(gt=0, strict=True)
    reason: str = Field(min_length=1, max_length=200)

    @field_validator('reason')
    @classmethod
    def trim_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('操作原因不能为空')
        return value.strip()


class DispositionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    completion_id: int = Field(gt=0, strict=True)
    reference: str = Field(min_length=1, max_length=100)
    kind: Literal['scrap','rework']
    quantity: Decimal
    loss_treatment: Literal['absorb','expense','carry']
    defect: str = Field(min_length=1, max_length=400)
    action_note: str = Field(min_length=1, max_length=400)
    warehouse_id: int | None = Field(default=None, gt=0, strict=True)
    materials: list[ReworkMaterial] = Field(default_factory=list, max_length=100)
    reason: str = Field(min_length=1, max_length=200)
    _quantity = field_validator('quantity')(quantity)

    @field_validator('reference','defect','action_note','reason')
    @classmethod
    def trim_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('依据、缺陷、处置说明及原因不能为空')
        return value.strip()

    @model_validator(mode='after')
    def valid_kind(self):
        if self.kind == 'scrap' and (self.loss_treatment == 'carry' or self.warehouse_id is not None or self.materials):
            raise ValueError('报废须明确成本处理，不填写返工仓库或材料')
        if self.kind == 'rework' and (self.loss_treatment != 'carry' or self.warehouse_id is None):
            raise ValueError('返工须携带来源成本并选择目标仓库')
        if len({line.material_id for line in self.materials}) != len(self.materials):
            raise ValueError('追加材料不能重复')
        return self


class DispositionEdit(DispositionInput):
    version: int = Field(gt=0, strict=True)


def can_read_cost(user: dict) -> bool:
    return 'production_cost.view' in user['permissions']


def apply_input(db, record, data):
    current = source(db, data.completion_id, writable=True)
    if db.scalar(select(QualityDisposition.id).where(QualityDisposition.reference == data.reference,
        QualityDisposition.id != (record.id or 0))) is not None:
        raise HTTPException(409, '处置依据编号已被使用，旧单据保留，请使用新的编号')
    if data.kind == 'rework':
        require_warehouse(db, data.warehouse_id)
    materials = []
    for line in data.materials:
        material = db.get(Material, line.material_id)
        if material is None or material.id == current['product_material_id']:
            raise HTTPException(422, '追加材料须存在且不能把本次不合格成品再次作为组件领料')
        materials.append(dict(material_id=material.id, sku=material.sku, material_name=material.name,
            unit=material.unit, quantity=str(line.quantity)))
    for key in ('completion_id','reference','kind','loss_treatment','defect','action_note','warehouse_id'):
        setattr(record, key, getattr(data, key))
    record.quantity, record.materials_json = str(data.quantity), encoded(materials)
    record.source_json = encoded(current)
    check_quantity(db, record)


@router.get('')
def overview(user: dict = Depends(require('quality.view'))) -> dict:
    with orm_session() as db:
        cases = []
        for completion in db.scalars(select(ProductionCompletion).where(
            ProductionCompletion.status == 'posted').order_by(ProductionCompletion.id.desc())):
            current = source(db, completion.id)
            if not current['valid']:
                continue
            used = reserved_quantity(db, completion.id)
            settled = active_settlement(db, completion.work_order_id)
            cases.append(dict(**current, reserved_quantity=str(used), remaining_quantity=str(Decimal(current['rejected_quantity']) - used),
                settled=settled is not None, settlement_id=settled['id'] if settled else None))
        records = db.scalars(select(QualityDisposition).order_by(QualityDisposition.id.desc()))
        return dict(cases=cases, dispositions=[disposition_data(db, row, include_cost=can_read_cost(user)) for row in records],
            materials=[material_choice_data(row) for row in db.scalars(select(Material).order_by(Material.sku))],
            warehouses=[dict(id=row.id,name=row.name) for row in db.scalars(select(Warehouse).order_by(Warehouse.id))])


@router.get('/dispositions/{identifier}')
def detail(identifier: int = Path(gt=0), user: dict = Depends(require('quality.view'))) -> dict:
    with orm_session() as db:
        return disposition_data(db, record_for(db, identifier), include_cost=can_read_cost(user))


@router.post('/dispositions', status_code=201)
def create(data: DispositionInput, user: dict = Depends(require('quality.create'))) -> dict:
    with orm_session(write=True) as db:
        record = QualityDisposition(status='draft', version=1, created_by=user['id'])
        apply_input(db, record, data)
        db.add(record)
        audit(db, record, None, 'create', data.reason, user['id'])
        return disposition_data(db, record, include_cost=can_read_cost(user))


@router.put('/dispositions/{identifier}')
def edit(data: DispositionEdit, identifier: int = Path(gt=0), user: dict = Depends(require('quality.create'))) -> dict:
    with orm_session(write=True) as db:
        record = record_for(db, identifier, data.version)
        if record.status not in ('draft','rejected'):
            raise HTTPException(409, '只有草稿或驳回处置单可以修订')
        if data.completion_id != record.completion_id:
            raise HTTPException(422, '原质检来源不能更换，请取消旧单后重新建立')
        before = model_data(record)
        apply_input(db, record, data)
        record.status, record.version = 'draft', record.version + 1
        audit(db, record, before, 'edit', data.reason, user['id'])
        return disposition_data(db, record, include_cost=can_read_cost(user))


def act(db, record, data, user, action):
    before = model_data(record)
    if action == 'submit':
        if record.status not in ('draft','rejected'):
            raise HTTPException(409, '只有草稿或驳回处置单可以提交')
        current = check_quantity(db, record)
        record.source_json = encoded(current)
        if record.kind == 'rework':
            require_warehouse(db, record.warehouse_id)
        record.status, record.submitted_by, record.submitted_at = 'submitted', user['id'], now(db)
    elif action in ('approve','reject'):
        if record.status != 'submitted':
            raise HTTPException(409, '只有提交后的处置单可以审核')
        independent_reviewer(db, record, user['id'])
        if action == 'approve':
            check_quantity(db, record)
        record.status = 'approved' if action == 'approve' else 'rejected'
        record.reviewed_by, record.reviewed_at = user['id'], now(db)
    elif action == 'cancel':
        if record.status not in ('draft','submitted','approved','rejected'):
            raise HTTPException(409, '已确认处置不能取消，须按原因更正')
        record.status = 'cancelled'
    elif action == 'post':
        if record.status != 'approved':
            raise HTTPException(409, '处置单须独立批准，且只能确认一次')
        current = check_quantity(db, record)
        if record.kind == 'rework':
            require_warehouse(db, record.warehouse_id)
            # 原不合格品仍在隔离来源内；这里只创建追加材料快照，不制造可用库存。
            order = add_model(db, WorkOrder(bom_id=current['bom_id'], warehouse_id=record.warehouse_id,
                target_quantity=record.quantity, reference=record.reference, note=record.action_note[:200], created_by=user['id']))
            db.add_all([WorkOrderLine(work_order_id=order.id, component_material_id=line['material_id'],
                required_quantity=line['quantity']) for line in json.loads(record.materials_json)])
            record.rework_order_id = order.id
        record.status, record.posted_by, record.posted_at = 'posted', user['id'], now(db)
    elif action == 'reverse':
        if record.status != 'posted':
            raise HTTPException(409, '只有已确认处置可以更正一次')
        current = source(db, record.completion_id)
        ensure_unsettled(db, current['work_order_id'])
        ensure_date_unlocked(db, record.posted_at)
        if record.rework_order_id is not None:
            order = db.get(WorkOrder, record.rework_order_id)
            ensure_unsettled(db, order.id)
            if db.scalar(select(ProductionCompletion.id).where(ProductionCompletion.work_order_id == order.id,
                ProductionCompletion.status != 'cancelled', ~select(ProductionCompletionReversal.id).where(
                    ProductionCompletionReversal.production_completion_id == ProductionCompletion.id).exists()).limit(1)) is not None:
                raise HTTPException(409, '须先取消或冲销返工工单的全部报工及后续处置')
            if db.scalar(select(MaterialIssue.id).where(MaterialIssue.work_order_id == order.id, MaterialIssue.status == 'draft')) is not None:
                raise HTTPException(409, '须先取消返工工单领料草稿')
            if db.scalar(select(MaterialReturn.id).join(MaterialIssue, MaterialIssue.id == MaterialReturn.material_issue_id).where(
                MaterialIssue.work_order_id == order.id, MaterialReturn.status == 'draft')) is not None:
                raise HTTPException(409, '须先取消返工工单退料草稿')
            for line in db.scalars(select(WorkOrderLine).where(WorkOrderLine.work_order_id == order.id)):
                if issued_quantity(db, line.id) != 0:
                    raise HTTPException(409, '须先将返工追加领料全部退回后更正处置')
            if db.scalar(select(ProductionCostEntry.id).where(ProductionCostEntry.work_order_id == order.id,
                ProductionCostEntry.kind.in_(('labor','overhead')), ~select(ProductionCostReversal.id).where(
                    ProductionCostReversal.entry_id == ProductionCostEntry.id).exists()).limit(1)) is not None:
                raise HTTPException(409, '须先冲销返工工单的人工及制造费用')
            order.status, order.cancelled_by, order.cancelled_at = 'cancelled', user['id'], now(db)
        record.status, record.reversed_by, record.reversed_at = 'reversed', user['id'], now(db)
    record.version += 1
    audit(db, record, before, action, data.reason, user['id'])
    return disposition_data(db, record, include_cost=can_read_cost(user))


def register_action(action: str, permission: str):
    def endpoint(data: VersionReason, identifier: int = Path(gt=0), user: dict = Depends(require(permission))):
        with orm_session(write=True) as db:
            return act(db, record_for(db, identifier, data.version), data, user, action)
    endpoint.__name__ = 'quality_' + action
    router.add_api_route('/dispositions/{identifier}/' + action, endpoint, methods=['POST'])


for action, permission in (('submit','quality.submit'), ('approve','quality.review'), ('reject','quality.review'),
    ('post','quality.post'), ('cancel','quality.cancel'), ('reverse','quality.reverse')):
    register_action(action, permission)
