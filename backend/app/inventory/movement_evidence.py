"""旧客户端未分配流水的逐笔补证；正式库存流水保持原样。"""

from app.core.document_responses import NumberedRoute
from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.access.security import require
from app.core.models import (Material, PhysicalLot, PhysicalLotAllocation, PhysicalLotEvidenceGroup,
                             PhysicalLotEvidenceGroupPair, PhysicalLotEvidencePair,
                             PhysicalLotMovementCheckpoint, PhysicalLotMovementEvidence, StockMovement, Warehouse,
                             MaterialIssueReversal, MaterialReturnReversal)
from app.core.orm import add_model, orm_session
from app.inventory.lot_inputs import PhysicalLotPartInput
from app.inventory.physical_lots import lot_balance, unassigned_stock_quantity


router = APIRouter(route_class=NumberedRoute, prefix='/api/v1/inventory/physical-lots')


class MovementEvidenceInput(PhysicalLotPartInput):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    lot_id: int | None = Field(default=None, gt=0, strict=True)
    evidence: str = Field(min_length=10, max_length=500)

    @field_validator('quantity', mode='before')
    @classmethod
    def exact_quantity_text(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError('补证数量须使用精确十进制文本')
        return value


class ReverseMovementEvidenceInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    reason: str = Field(min_length=10, max_length=500)


class EvidencePairInput(MovementEvidenceInput):
    inbound_movement_id: int = Field(gt=0, strict=True)
    outbound_movement_id: int = Field(gt=0, strict=True)


class EvidenceGroupPairInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    inbound_movement_id: int = Field(gt=0, strict=True)
    outbound_movement_id: int = Field(gt=0, strict=True)
    quantity: Decimal

    @field_validator('quantity', mode='before')
    @classmethod
    def exact_quantity_text(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError('成组补证数量须使用精确十进制文本')
        return value

    @field_validator('quantity')
    @classmethod
    def valid_quantity(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 0 or value > 1_000_000 or value.as_tuple().exponent < -3:
            raise ValueError('成组补证数量须为正数、最多三位小数且不超过一百万')
        return value


class EvidenceGroupInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    pairs: list[EvidenceGroupPairInput] = Field(min_length=2, max_length=50)
    lot_id: int | None = Field(default=None, gt=0, strict=True)
    evidence: str = Field(min_length=10, max_length=500)
    supplier_lot: str | None = Field(default=None, max_length=100)
    manufactured_on: date | None = None
    expires_on: date | None = None


def _checkpoint(db: Session) -> PhysicalLotMovementCheckpoint:
    checkpoint = db.get(PhysicalLotMovementCheckpoint, 1)
    if checkpoint is None:
        raise HTTPException(503, '实物批次升级检查点缺失，请先完成数据库迁移')
    return checkpoint


def _assigned_to_movement(db: Session, movement_id: int) -> Decimal:
    allocations = db.scalars(select(PhysicalLotAllocation.quantity).where(
        PhysicalLotAllocation.movement_id == movement_id))
    evidence = db.scalars(select(PhysicalLotMovementEvidence.quantity).where(
        PhysicalLotMovementEvidence.movement_id == movement_id))
    return sum((Decimal(value) for value in (*allocations, *evidence)), Decimal(0))


def _ensure_movement_evidence_mutable(db: Session, movement: StockMovement) -> None:
    # 原领料冲销已固定当时的批次归属，后补证不得再改变原反向配对。
    if movement.source_type == 'material_issue_reversal' or (
            movement.source_type == 'material_issue' and db.scalar(
                select(MaterialIssueReversal.id).where(
                    MaterialIssueReversal.material_issue_id == movement.source_id)) is not None):
        raise HTTPException(409, '领料已冲销，不能再修改原单或冲销流水的批次补证')
    if movement.source_type == 'material_return_reversal' or (
            movement.source_type == 'material_return' and db.scalar(
                select(MaterialReturnReversal.id).where(
                    MaterialReturnReversal.material_return_id == movement.source_id)) is not None):
        raise HTTPException(409, '退料已冲销，不能再修改原单或冲销流水的批次补证')


def _result(db: Session, record: PhysicalLotMovementEvidence, username: str) -> dict:
    movement = db.get(StockMovement, record.movement_id)
    lot = db.get(PhysicalLot, record.lot_id)
    return {'id': record.id, 'movement_id': record.movement_id, 'lot_id': record.lot_id,
            'lot_code': lot.code, 'warehouse_id': movement.warehouse_id,
            'material_id': movement.material_id, 'quantity': record.quantity,
            'evidence': record.evidence, 'original_evidence_id': record.original_evidence_id,
            'created_by_name': username, 'created_at': record.created_at}


def _pair_result(db: Session, pair: PhysicalLotEvidencePair, username: str) -> dict:
    lot = db.get(PhysicalLot, pair.lot_id)
    inbound = db.get(StockMovement, pair.inbound_movement_id)
    return {'id': pair.id, 'inbound_movement_id': pair.inbound_movement_id,
            'outbound_movement_id': pair.outbound_movement_id,
            'inbound_evidence_id': pair.inbound_evidence_id,
            'outbound_evidence_id': pair.outbound_evidence_id,
            'lot_id': pair.lot_id, 'lot_code': lot.code,
            'warehouse_id': inbound.warehouse_id, 'material_id': inbound.material_id,
            'quantity': pair.quantity, 'evidence': pair.evidence,
            'original_pair_id': pair.original_pair_id,
            'created_by_name': username, 'created_at': pair.created_at}


def _group_result(db: Session, group: PhysicalLotEvidenceGroup, username: str) -> dict:
    lot = db.get(PhysicalLot, group.lot_id)
    links = db.scalars(select(PhysicalLotEvidenceGroupPair).where(
        PhysicalLotEvidenceGroupPair.group_id == group.id).order_by(
            PhysicalLotEvidenceGroupPair.position))
    return {'id': group.id, 'lot_id': group.lot_id, 'lot_code': lot.code,
            'warehouse_id': group.warehouse_id, 'material_id': group.material_id,
            'evidence': group.evidence, 'original_group_id': group.original_group_id,
            'created_by_name': username, 'created_at': group.created_at,
            'pairs': [_pair_result(db, db.get(PhysicalLotEvidencePair, link.pair_id), username)
                      for link in links]}


@router.get('/unallocated-movements')
def unallocated_movements(warehouse_id: int | None = Query(default=None, gt=0),
                          material_id: int | None = Query(default=None, gt=0),
                          _: dict = Depends(require('inventory.view'))) -> dict:
    with orm_session() as db:
        if warehouse_id is not None and db.get(Warehouse, warehouse_id) is None:
            raise HTTPException(404, '仓库不存在')
        if material_id is not None and db.get(Material, material_id) is None:
            raise HTTPException(404, '物料不存在')
        checkpoint = _checkpoint(db)
        conditions = [StockMovement.id > checkpoint.movement_id]
        if warehouse_id is not None:
            conditions.append(StockMovement.warehouse_id == warehouse_id)
        if material_id is not None:
            conditions.append(StockMovement.material_id == material_id)
        assigned: dict[int, Decimal] = {}
        for model in (PhysicalLotAllocation, PhysicalLotMovementEvidence):
            parts = select(model.movement_id, model.quantity).join(
                StockMovement, StockMovement.id == model.movement_id).where(*conditions)
            for movement_key, quantity in db.execute(parts):
                assigned[movement_key] = assigned.get(movement_key, Decimal(0)) + Decimal(quantity)
        rows = []
        for movement in db.scalars(select(StockMovement).where(*conditions).order_by(StockMovement.id.desc())):
            remaining = Decimal(movement.quantity) - assigned.get(movement.id, Decimal(0))
            if remaining == 0:
                continue
            rows.append({'movement_id': movement.id, 'warehouse_id': movement.warehouse_id,
                         'material_id': movement.material_id, 'quantity': movement.quantity,
                         'unallocated_quantity': format(remaining, 'f'),
                         'source_type': movement.source_type, 'source_id': movement.source_id,
                         'source_line_id': movement.source_line_id, 'created_at': movement.created_at})
            if len(rows) > 100:
                break
        return {'checkpoint_movement_id': checkpoint.movement_id,
                'checkpoint_basis': checkpoint.basis,
                'warehouse_id': warehouse_id, 'material_id': material_id,
                'rows': rows[:100], 'has_more': len(rows) > 100}


@router.post('/movements/{movement_id}/evidence', status_code=201)
def add_movement_evidence(data: MovementEvidenceInput, movement_id: int = Path(gt=0),
                          user: dict = Depends(require('physical_lot.movement_evidence'))) -> dict:
    with orm_session(write=True) as db:
        movement = db.get(StockMovement, movement_id)
        if movement is None:
            raise HTTPException(404, '库存流水不存在')
        _ensure_movement_evidence_mutable(db, movement)
        if movement.id <= _checkpoint(db).movement_id:
            raise HTTPException(422, '该流水已纳入历史未识别期初，不能重复分配')
        remaining = Decimal(movement.quantity) - _assigned_to_movement(db, movement.id)
        if remaining != 0 and ((remaining > 0) != (Decimal(movement.quantity) > 0)
                               or abs(remaining) > abs(Decimal(movement.quantity))):
            raise HTTPException(409, '原流水批次分配已超量，请先核对历史记录')
        quantity = data.quantity if remaining > 0 else -data.quantity
        if remaining == 0 or abs(quantity) > abs(remaining) or (quantity > 0) != (remaining > 0):
            raise HTTPException(409, '流水未分配数量不足，请重新读取')
        difference = unassigned_stock_quantity(db, movement.warehouse_id, movement.material_id)
        if (quantity > 0 and difference < quantity) or (quantity < 0 and difference > quantity):
            raise HTTPException(409, '本仓正式库存与批次差额不足，请先核对其他流水')
        if data.lot_id is None:
            if quantity < 0:
                raise HTTPException(422, '出库补证须选择现有实物批次')
            lot = add_model(db, PhysicalLot(
                material_id=movement.material_id, code=f'EVIDENCE-{uuid4().hex.upper()}',
                source_kind='movement_evidence', supplier_lot=data.supplier_lot,
                manufactured_on=data.manufactured_on.isoformat() if data.manufactured_on else None,
                expires_on=data.expires_on.isoformat() if data.expires_on else None,
                origin_movement_id=movement.id, created_by=user['id']))
        else:
            lot = db.get(PhysicalLot, data.lot_id)
            if lot is None or lot.material_id != movement.material_id:
                raise HTTPException(422, '所选批次与流水物料不一致')
            if data.supplier_lot or data.manufactured_on or data.expires_on:
                raise HTTPException(422, '已有批次的来源属性不能在逐笔补证时修改')
        if quantity < 0 and lot_balance(db, movement.warehouse_id, lot.id) < -quantity:
            raise HTTPException(409, '所选批次现存量不足')
        record = add_model(db, PhysicalLotMovementEvidence(
            movement_id=movement.id, lot_id=lot.id, quantity=format(quantity, 'f'),
            evidence=data.evidence, created_by=user['id']))
        return _result(db, record, user['username'])


@router.post('/movement-evidence/{record_id}/reverse', status_code=201)
def reverse_movement_evidence(data: ReverseMovementEvidenceInput, record_id: int = Path(gt=0),
                              user: dict = Depends(require('physical_lot.movement_evidence'))) -> dict:
    with orm_session(write=True) as db:
        original = db.get(PhysicalLotMovementEvidence, record_id)
        if original is None:
            raise HTTPException(404, '逐笔补证记录不存在')
        if original.original_evidence_id is not None:
            raise HTTPException(422, '只能冲销原始逐笔补证')
        if db.scalar(select(PhysicalLotEvidencePair.id).where(
                (PhysicalLotEvidencePair.inbound_evidence_id == record_id)
                | (PhysicalLotEvidencePair.outbound_evidence_id == record_id))) is not None:
            raise HTTPException(422, '成对补证须作为整体冲销')
        if db.scalar(select(PhysicalLotMovementEvidence.id).where(
                PhysicalLotMovementEvidence.original_evidence_id == record_id)) is not None:
            raise HTTPException(409, '逐笔补证已冲销')
        movement = db.get(StockMovement, original.movement_id)
        _ensure_movement_evidence_mutable(db, movement)
        quantity = Decimal(original.quantity)
        if quantity > 0 and lot_balance(db, movement.warehouse_id, original.lot_id) < quantity:
            raise HTTPException(409, '补证批次已被后续单据使用，不能冲销')
        reversal = add_model(db, PhysicalLotMovementEvidence(
            movement_id=original.movement_id, lot_id=original.lot_id,
            quantity=format(-quantity, 'f'), evidence=data.reason,
            original_evidence_id=original.id, created_by=user['id']))
        return _result(db, reversal, user['username'])


def _create_pair(db: Session, data: EvidencePairInput, user: dict) -> dict:
    checkpoint = _checkpoint(db).movement_id
    inbound = db.get(StockMovement, data.inbound_movement_id)
    outbound = db.get(StockMovement, data.outbound_movement_id)
    if inbound is None or outbound is None:
        raise HTTPException(404, '待补证库存流水不存在')
    _ensure_movement_evidence_mutable(db, inbound)
    _ensure_movement_evidence_mutable(db, outbound)
    if (inbound.id <= checkpoint or outbound.id <= checkpoint
            or inbound.id >= outbound.id
            or inbound.warehouse_id != outbound.warehouse_id
            or inbound.material_id != outbound.material_id
            or Decimal(inbound.quantity) <= 0 or Decimal(outbound.quantity) >= 0):
        raise HTTPException(422, '须选择升级后同仓同物料、先入后出的两笔流水')
    inbound_remaining = Decimal(inbound.quantity) - _assigned_to_movement(db, inbound.id)
    outbound_remaining = Decimal(outbound.quantity) - _assigned_to_movement(db, outbound.id)
    if inbound_remaining < data.quantity or outbound_remaining > -data.quantity:
        raise HTTPException(409, '两笔流水的未分配数量不足，请重新读取')
    if data.lot_id is None:
        lot = add_model(db, PhysicalLot(
            material_id=inbound.material_id, code=f'EVIDENCE-{uuid4().hex.upper()}',
            source_kind='movement_evidence', supplier_lot=data.supplier_lot,
            manufactured_on=data.manufactured_on.isoformat() if data.manufactured_on else None,
            expires_on=data.expires_on.isoformat() if data.expires_on else None,
            origin_movement_id=inbound.id, created_by=user['id']))
    else:
        lot = db.get(PhysicalLot, data.lot_id)
        if lot is None or lot.material_id != inbound.material_id:
            raise HTTPException(422, '所选批次与两笔流水的物料不一致')
        if lot.origin_movement_id is not None and lot.origin_movement_id > inbound.id:
            raise HTTPException(422, '不能把较早入库归入后来才建立的批次')
        if data.supplier_lot or data.manufactured_on or data.expires_on:
            raise HTTPException(422, '已有批次的来源属性不能在成对补证时修改')
        if lot_balance(db, inbound.warehouse_id, lot.id) < 0:
            raise HTTPException(409, '所选批次当前余额异常，请先核对')
    inbound_evidence = add_model(db, PhysicalLotMovementEvidence(
        movement_id=inbound.id, lot_id=lot.id, quantity=format(data.quantity, 'f'),
        evidence=data.evidence, created_by=user['id']))
    outbound_evidence = add_model(db, PhysicalLotMovementEvidence(
        movement_id=outbound.id, lot_id=lot.id, quantity=format(-data.quantity, 'f'),
        evidence=data.evidence, created_by=user['id']))
    pair = add_model(db, PhysicalLotEvidencePair(
        inbound_movement_id=inbound.id, outbound_movement_id=outbound.id,
        inbound_evidence_id=inbound_evidence.id, outbound_evidence_id=outbound_evidence.id,
        lot_id=lot.id, quantity=format(data.quantity, 'f'), evidence=data.evidence,
        created_by=user['id']))
    return _pair_result(db, pair, user['username'])


@router.post('/evidence-pairs', status_code=201)
def create_evidence_pair(data: EvidencePairInput,
                         user: dict = Depends(require('physical_lot.movement_evidence'))) -> dict:
    with orm_session(write=True) as db:
        return _create_pair(db, data, user)


def _reverse_pair(db: Session, pair_id: int, data: ReverseMovementEvidenceInput,
                  user: dict, *, within_group: bool = False) -> dict:
    original = db.get(PhysicalLotEvidencePair, pair_id)
    if original is None:
        raise HTTPException(404, '成对补证记录不存在')
    if original.original_pair_id is not None:
        raise HTTPException(422, '只能冲销原始成对补证')
    if not within_group and db.scalar(select(PhysicalLotEvidenceGroupPair.group_id).where(
            PhysicalLotEvidenceGroupPair.pair_id == pair_id)) is not None:
        raise HTTPException(422, '成组补证须作为整体冲销')
    if db.scalar(select(PhysicalLotEvidencePair.id).where(
            PhysicalLotEvidencePair.original_pair_id == pair_id)) is not None:
        raise HTTPException(409, '成对补证已冲销')
    _ensure_movement_evidence_mutable(db, db.get(StockMovement, original.inbound_movement_id))
    _ensure_movement_evidence_mutable(db, db.get(StockMovement, original.outbound_movement_id))
    lot = db.get(PhysicalLot, original.lot_id)
    # 新建批次的首次来源若已被其他证据引用，撤销来源会留下无法解释的追溯链。
    first_evidence_id = db.scalar(select(func.min(PhysicalLotMovementEvidence.id)).where(
        PhysicalLotMovementEvidence.lot_id == original.lot_id))
    if (lot.source_kind == 'movement_evidence'
            and lot.origin_movement_id == original.inbound_movement_id
            and original.inbound_evidence_id == first_evidence_id):
        evidence = list(db.scalars(select(PhysicalLotMovementEvidence).where(
            PhysicalLotMovementEvidence.lot_id == original.lot_id)))
        evidence_reversals = {row.original_evidence_id for row in evidence
                              if row.original_evidence_id is not None}
        active_evidence = any(row.original_evidence_id is None
                              and row.id not in (original.inbound_evidence_id,
                                                 original.outbound_evidence_id)
                              and row.id not in evidence_reversals for row in evidence)
        allocations = list(db.scalars(select(PhysicalLotAllocation).where(
            PhysicalLotAllocation.lot_id == original.lot_id)))
        allocation_reversals = {row.original_allocation_id for row in allocations
                                if row.original_allocation_id is not None}
        active_allocation = any(row.original_allocation_id is None
                                and row.id not in allocation_reversals for row in allocations)
        if active_evidence or active_allocation:
            raise HTTPException(409, '批次已被其他有效流水使用，不能冲销首次成对补证')
    quantity = Decimal(original.quantity)
    inbound_reverse = add_model(db, PhysicalLotMovementEvidence(
        movement_id=original.inbound_movement_id, lot_id=original.lot_id,
        quantity=format(-quantity, 'f'), evidence=data.reason,
        original_evidence_id=original.inbound_evidence_id, created_by=user['id']))
    outbound_reverse = add_model(db, PhysicalLotMovementEvidence(
        movement_id=original.outbound_movement_id, lot_id=original.lot_id,
        quantity=format(quantity, 'f'), evidence=data.reason,
        original_evidence_id=original.outbound_evidence_id, created_by=user['id']))
    reversal = add_model(db, PhysicalLotEvidencePair(
        inbound_movement_id=original.inbound_movement_id,
        outbound_movement_id=original.outbound_movement_id,
        inbound_evidence_id=inbound_reverse.id, outbound_evidence_id=outbound_reverse.id,
        lot_id=original.lot_id, quantity=format(-quantity, 'f'), evidence=data.reason,
        original_pair_id=original.id, created_by=user['id']))
    return _pair_result(db, reversal, user['username'])


@router.post('/evidence-pairs/{pair_id}/reverse', status_code=201)
def reverse_evidence_pair(data: ReverseMovementEvidenceInput, pair_id: int = Path(gt=0),
                          user: dict = Depends(require('physical_lot.movement_evidence'))) -> dict:
    with orm_session(write=True) as db:
        return _reverse_pair(db, pair_id, data, user)


@router.post('/evidence-groups', status_code=201)
def create_evidence_group(data: EvidenceGroupInput,
                          user: dict = Depends(require('physical_lot.movement_evidence'))) -> dict:
    if data.manufactured_on and data.expires_on and data.expires_on < data.manufactured_on:
        raise HTTPException(422, '失效日期早于生产日期')
    keys = [(part.inbound_movement_id, part.outbound_movement_id) for part in data.pairs]
    if len(set(keys)) != len(keys) or len({id for pair in keys for id in pair}) < 3:
        raise HTTPException(422, '成组补证须包含至少三笔流水且不得重复配对')
    with orm_session(write=True) as db:
        results = []
        lot_id = data.lot_id
        warehouse_id = material_id = None
        for part in sorted(data.pairs, key=lambda row: (row.inbound_movement_id,
                                                       row.outbound_movement_id)):
            pair_input = EvidencePairInput(
                inbound_movement_id=part.inbound_movement_id,
                outbound_movement_id=part.outbound_movement_id,
                quantity=format(part.quantity, 'f'), lot_id=lot_id,
                evidence=data.evidence,
                supplier_lot=data.supplier_lot if lot_id is None else None,
                manufactured_on=data.manufactured_on if lot_id is None else None,
                expires_on=data.expires_on if lot_id is None else None)
            result = _create_pair(db, pair_input, user)
            if warehouse_id is None:
                warehouse_id, material_id = result['warehouse_id'], result['material_id']
                lot_id = result['lot_id']
            elif result['warehouse_id'] != warehouse_id or result['material_id'] != material_id:
                raise HTTPException(422, '成组补证的全部流水须属于同仓同物料')
            results.append(result)
        group = add_model(db, PhysicalLotEvidenceGroup(
            lot_id=lot_id, warehouse_id=warehouse_id, material_id=material_id,
            evidence=data.evidence, created_by=user['id']))
        for position, result in enumerate(results):
            db.add(PhysicalLotEvidenceGroupPair(group_id=group.id,
                pair_id=result['id'], position=position))
        db.flush()
        return _group_result(db, group, user['username'])


@router.post('/evidence-groups/{group_id}/reverse', status_code=201)
def reverse_evidence_group(data: ReverseMovementEvidenceInput,
                           group_id: int = Path(gt=0),
                           user: dict = Depends(require('physical_lot.movement_evidence'))) -> dict:
    with orm_session(write=True) as db:
        original = db.get(PhysicalLotEvidenceGroup, group_id)
        if original is None:
            raise HTTPException(404, '成组补证记录不存在')
        if original.original_group_id is not None:
            raise HTTPException(422, '只能冲销原始成组补证')
        if db.scalar(select(PhysicalLotEvidenceGroup.id).where(
                PhysicalLotEvidenceGroup.original_group_id == group_id)) is not None:
            raise HTTPException(409, '成组补证已冲销')
        links = list(db.scalars(select(PhysicalLotEvidenceGroupPair).where(
            PhysicalLotEvidenceGroupPair.group_id == group_id).order_by(
                PhysicalLotEvidenceGroupPair.position.desc())))
        reversals = [_reverse_pair(db, link.pair_id, data, user, within_group=True)
                     for link in links]
        group = add_model(db, PhysicalLotEvidenceGroup(
            lot_id=original.lot_id, warehouse_id=original.warehouse_id,
            material_id=original.material_id, evidence=data.reason,
            original_group_id=original.id, created_by=user['id']))
        for position, result in enumerate(reversals):
            db.add(PhysicalLotEvidenceGroupPair(group_id=group.id,
                pair_id=result['id'], position=position))
        db.flush()
        return _group_result(db, group, user['username'])
