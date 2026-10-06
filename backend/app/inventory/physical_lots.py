"""实物批次结存快照；未分配的库存必须显式显示为差额。"""

from app.core.document_responses import NumberedRoute
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access.security import require
from app.core.models import Material, PhysicalLot, PhysicalLotAllocation, PhysicalLotEvidenceGroup, PhysicalLotEvidenceGroupPair, PhysicalLotEvidencePair, PhysicalLotMovementEvidence, PhysicalLotOpening, PhysicalLotReclassification, StockMovement, User, Warehouse
from app.core.orm import add_model, orm_session
from app.inventory.lot_inputs import PhysicalLotPartInput


router = APIRouter(route_class=NumberedRoute, prefix='/api/v1/inventory/physical-lots')


@dataclass(frozen=True)
class LotPart:
    lot_id: int
    quantity: Decimal
    original_allocation_id: int | None = None


class LegacyEvidenceInput(PhysicalLotPartInput):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    legacy_lot_id: int = Field(gt=0, strict=True)
    warehouse_id: int = Field(gt=0, strict=True)
    evidence: str = Field(min_length=10, max_length=500)

    @field_validator('quantity', mode='before')
    @classmethod
    def exact_quantity_text(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError('补证数量须使用精确十进制文本')
        return value

    @field_validator('evidence')
    @classmethod
    def nonblank_evidence(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('须提供现场核对依据')
        return value.strip()


class ReverseEvidenceInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    reason: str = Field(min_length=10, max_length=500)


def reclassification_data(db: Session, record: PhysicalLotReclassification, username: str) -> dict:
    verified = db.get(PhysicalLot, record.verified_lot_id)
    return {'id': record.id, 'legacy_lot_id': record.legacy_lot_id,
            'verified_lot_id': record.verified_lot_id, 'warehouse_id': record.warehouse_id,
            'quantity': record.quantity, 'evidence': record.evidence,
            'original_reclassification_id': record.original_reclassification_id,
            'created_by_name': username, 'created_at': record.created_at,
            'verified_lot_code': verified.code}


def lot_balance(db: Session, warehouse_id: int, lot_id: int) -> Decimal:
    """在同一写事务中按原始文本累计数量，避免 SQLite 对小数的浮点求和。"""
    opening = db.scalars(select(PhysicalLotOpening.quantity).where(
        PhysicalLotOpening.warehouse_id == warehouse_id,
        PhysicalLotOpening.lot_id == lot_id))
    movement = db.scalars(select(PhysicalLotAllocation.quantity).join(
        StockMovement, StockMovement.id == PhysicalLotAllocation.movement_id).where(
            StockMovement.warehouse_id == warehouse_id,
            PhysicalLotAllocation.lot_id == lot_id))
    outgoing = db.scalars(select(PhysicalLotReclassification.quantity).where(
        PhysicalLotReclassification.warehouse_id == warehouse_id,
        PhysicalLotReclassification.legacy_lot_id == lot_id))
    incoming = db.scalars(select(PhysicalLotReclassification.quantity).where(
        PhysicalLotReclassification.warehouse_id == warehouse_id,
        PhysicalLotReclassification.verified_lot_id == lot_id))
    evidence = db.scalars(select(PhysicalLotMovementEvidence.quantity).join(
        StockMovement, StockMovement.id == PhysicalLotMovementEvidence.movement_id).where(
            StockMovement.warehouse_id == warehouse_id,
            PhysicalLotMovementEvidence.lot_id == lot_id))
    return (sum((Decimal(value) for value in (*opening, *movement, *evidence, *incoming)), Decimal(0))
            - sum((Decimal(value) for value in outgoing), Decimal(0)))


def unassigned_stock_quantity(db: Session, warehouse_id: int, material_id: int) -> Decimal:
    """正值表示正式库存尚有未归批次数量；补证只允许缩小当前差额。"""
    stock = db.scalars(select(StockMovement.quantity).where(
        StockMovement.warehouse_id == warehouse_id, StockMovement.material_id == material_id))
    opening = db.scalars(select(PhysicalLotOpening.quantity).join(
        PhysicalLot, PhysicalLot.id == PhysicalLotOpening.lot_id).where(
            PhysicalLotOpening.warehouse_id == warehouse_id,
            PhysicalLot.material_id == material_id))
    allocated = db.scalars(select(PhysicalLotAllocation.quantity).join(
        StockMovement, StockMovement.id == PhysicalLotAllocation.movement_id).where(
            StockMovement.warehouse_id == warehouse_id,
            StockMovement.material_id == material_id))
    evidence = db.scalars(select(PhysicalLotMovementEvidence.quantity).join(
        StockMovement, StockMovement.id == PhysicalLotMovementEvidence.movement_id).where(
            StockMovement.warehouse_id == warehouse_id,
            StockMovement.material_id == material_id))
    return (sum((Decimal(value) for value in stock), Decimal(0))
            - sum((Decimal(value) for value in (*opening, *allocated, *evidence)), Decimal(0)))


@router.post('/reclassifications', status_code=201)
def reclassify_legacy_lot(data: LegacyEvidenceInput,
                          user: dict = Depends(require('physical_lot.reclassify'))) -> dict:
    with orm_session(write=True) as db:
        if db.get(Warehouse, data.warehouse_id) is None:
            raise HTTPException(404, '仓库不存在')
        legacy = db.get(PhysicalLot, data.legacy_lot_id)
        if legacy is None or legacy.source_kind != 'legacy':
            raise HTTPException(422, '须选择历史未识别批次')
        if lot_balance(db, data.warehouse_id, legacy.id) < data.quantity:
            raise HTTPException(409, '历史未识别批次现存量不足，请重新读取')
        # 同仓同物料的补证一出一入相抵，逐笔补证也须纳入正式库存差额。
        if unassigned_stock_quantity(db, data.warehouse_id, legacy.material_id) < 0:
            raise HTTPException(409, '正式库存少于批次结存，请先核对未分配出库差额')
        # 补证只在实物批次之间转移数量，不建立正式库存流水，也不改移动平均成本。
        verified = add_model(db, PhysicalLot(
            material_id=legacy.material_id, code=f'VERIFIED-{uuid4().hex.upper()}',
            source_kind='legacy_evidence', supplier_lot=data.supplier_lot,
            manufactured_on=data.manufactured_on.isoformat() if data.manufactured_on else None,
            expires_on=data.expires_on.isoformat() if data.expires_on else None,
            created_by=user['id']))
        record = add_model(db, PhysicalLotReclassification(
            legacy_lot_id=legacy.id, verified_lot_id=verified.id,
            warehouse_id=data.warehouse_id, quantity=format(data.quantity, 'f'),
            evidence=data.evidence, created_by=user['id']))
        return reclassification_data(db, record, user['username'])


@router.post('/reclassifications/{record_id}/reverse', status_code=201)
def reverse_reclassification(data: ReverseEvidenceInput, record_id: int = Path(gt=0),
                             user: dict = Depends(require('physical_lot.reclassify'))) -> dict:
    with orm_session(write=True) as db:
        original = db.get(PhysicalLotReclassification, record_id)
        if original is None:
            raise HTTPException(404, '补证记录不存在')
        if original.original_reclassification_id is not None:
            raise HTTPException(422, '只能冲销原补证记录')
        if db.scalar(select(PhysicalLotReclassification.id).where(
                PhysicalLotReclassification.original_reclassification_id == record_id)) is not None:
            raise HTTPException(409, '原补证记录已冲销')
        quantity = Decimal(original.quantity)
        if lot_balance(db, original.warehouse_id, original.verified_lot_id) < quantity:
            raise HTTPException(409, '补证批次已被后续单据使用，不能冲销')
        reversal = add_model(db, PhysicalLotReclassification(
            legacy_lot_id=original.legacy_lot_id, verified_lot_id=original.verified_lot_id,
            warehouse_id=original.warehouse_id, quantity=format(-quantity, 'f'),
            evidence=data.reason, original_reclassification_id=original.id,
            created_by=user['id']))
        return reclassification_data(db, reversal, user['username'])


def post_lot_movement(db: Session, movement: StockMovement, parts: list[LotPart]) -> StockMovement:
    """将库存流水与完整的实物批次分配一起写入当前 ORM 事务。"""
    quantity = Decimal(movement.quantity)
    if not quantity.is_finite() or quantity == 0 or quantity.as_tuple().exponent < -3:
        raise HTTPException(422, '库存流水数量无效')
    if not parts or len({part.lot_id for part in parts}) != len(parts):
        raise HTTPException(422, '须为库存流水指定不重复的实物批次')
    checked: list[tuple[LotPart, Decimal]] = []
    for part in parts:
        value = part.quantity
        if (not value.is_finite() or value == 0 or value.as_tuple().exponent < -3
                or (value > 0) != (quantity > 0)):
            raise HTTPException(422, '批次分配数量方向或精度无效')
        lot = db.get(PhysicalLot, part.lot_id)
        if lot is None or lot.material_id != movement.material_id:
            raise HTTPException(422, f'物料 #{movement.material_id} 的实物批次无效')
        if value < 0 and lot_balance(db, movement.warehouse_id, part.lot_id) < -value:
            raise HTTPException(409, f'实物批次 {lot.code} 在仓库 #{movement.warehouse_id} 的数量不足')
        if part.original_allocation_id is not None:
            original = db.get(PhysicalLotAllocation, part.original_allocation_id)
            if original is None or original.lot_id != part.lot_id or Decimal(original.quantity) != -value:
                raise HTTPException(422, '冲销批次分配与原流水不一致')
            if db.scalar(select(PhysicalLotAllocation.id).where(
                    PhysicalLotAllocation.original_allocation_id == part.original_allocation_id)) is not None:
                raise HTTPException(409, '原批次分配已经冲销')
        checked.append((part, value))
    if sum((value for _, value in checked), Decimal(0)) != quantity:
        raise HTTPException(422, '批次分配数量之和与库存流水不一致')
    db.add(movement)
    db.flush()
    db.add_all(PhysicalLotAllocation(
        lot_id=part.lot_id, movement_id=movement.id, quantity=str(value),
        original_allocation_id=part.original_allocation_id)
        for part, value in checked)
    db.flush()
    return movement


def _add(balances: dict[tuple[int, int], Decimal], key: tuple[int, int], quantity: str) -> None:
    balances[key] = balances.get(key, Decimal(0)) + Decimal(quantity)


@router.get('/overview')
def overview(warehouse_id: int | None = Query(default=None, gt=0),
             material_id: int | None = Query(default=None, gt=0),
             _: dict = Depends(require('inventory.view'))) -> dict:
    with orm_session() as db:
        warehouses = {row.id: row for row in db.scalars(select(Warehouse))}
        materials = {row.id: row for row in db.scalars(select(Material))}
        if warehouse_id is not None and warehouse_id not in warehouses:
            raise HTTPException(404, '仓库不存在')
        if material_id is not None and material_id not in materials:
            raise HTTPException(404, '物料不存在')
        lots = {row.id: row for row in db.scalars(select(PhysicalLot))}
        stock: dict[tuple[int, int], Decimal] = {}
        lot_balances: dict[tuple[int, int], Decimal] = {}

        movement_query = select(StockMovement.warehouse_id, StockMovement.material_id, StockMovement.quantity)
        if warehouse_id is not None:
            movement_query = movement_query.where(StockMovement.warehouse_id == warehouse_id)
        if material_id is not None:
            movement_query = movement_query.where(StockMovement.material_id == material_id)
        for warehouse, material, quantity in db.execute(movement_query):
            _add(stock, (warehouse, material), quantity)

        opening_query = select(PhysicalLotOpening.warehouse_id, PhysicalLotOpening.lot_id,
                               PhysicalLotOpening.quantity).join(
                                   PhysicalLot, PhysicalLot.id == PhysicalLotOpening.lot_id)
        if warehouse_id is not None:
            opening_query = opening_query.where(PhysicalLotOpening.warehouse_id == warehouse_id)
        if material_id is not None:
            opening_query = opening_query.where(PhysicalLot.material_id == material_id)
        for warehouse, lot, quantity in db.execute(opening_query):
            _add(lot_balances, (warehouse, lot), quantity)

        allocation_query = select(StockMovement.warehouse_id, PhysicalLotAllocation.lot_id,
                                  PhysicalLotAllocation.quantity).join(
                                      StockMovement, StockMovement.id == PhysicalLotAllocation.movement_id).join(
                                          PhysicalLot, PhysicalLot.id == PhysicalLotAllocation.lot_id)
        if warehouse_id is not None:
            allocation_query = allocation_query.where(StockMovement.warehouse_id == warehouse_id)
        if material_id is not None:
            allocation_query = allocation_query.where(PhysicalLot.material_id == material_id)
        for warehouse, lot, quantity in db.execute(allocation_query):
            _add(lot_balances, (warehouse, lot), quantity)

        evidence_query = select(StockMovement.warehouse_id, PhysicalLotMovementEvidence.lot_id,
                                PhysicalLotMovementEvidence.quantity).join(
                                    StockMovement, StockMovement.id == PhysicalLotMovementEvidence.movement_id).join(
                                        PhysicalLot, PhysicalLot.id == PhysicalLotMovementEvidence.lot_id)
        if warehouse_id is not None:
            evidence_query = evidence_query.where(StockMovement.warehouse_id == warehouse_id)
        if material_id is not None:
            evidence_query = evidence_query.where(PhysicalLot.material_id == material_id)
        for warehouse, lot, quantity in db.execute(evidence_query):
            _add(lot_balances, (warehouse, lot), quantity)

        reclassification_query = select(PhysicalLotReclassification)
        if warehouse_id is not None:
            reclassification_query = reclassification_query.where(PhysicalLotReclassification.warehouse_id == warehouse_id)
        for record in db.scalars(reclassification_query):
            if material_id is not None and lots[record.legacy_lot_id].material_id != material_id:
                continue
            _add(lot_balances, (record.warehouse_id, record.legacy_lot_id),
                 format(-Decimal(record.quantity), 'f'))
            _add(lot_balances, (record.warehouse_id, record.verified_lot_id), record.quantity)

        assigned: dict[tuple[int, int], Decimal] = {}
        rows = []
        for (warehouse, lot_id), quantity in sorted(lot_balances.items()):
            lot = lots[lot_id]
            material = materials[lot.material_id]
            key = (warehouse, lot.material_id)
            assigned[key] = assigned.get(key, Decimal(0)) + quantity
            rows.append({
                'warehouse_id': warehouse, 'warehouse_name': warehouses[warehouse].name,
                'material_id': lot.material_id, 'sku': material.sku,
                'material_name': material.name, 'unit': material.unit,
                'lot_id': lot_id, 'lot_code': lot.code, 'source_kind': lot.source_kind,
                'supplier_lot': lot.supplier_lot, 'manufactured_on': lot.manufactured_on,
                'expires_on': lot.expires_on, 'quantity': format(quantity, 'f')})

        differences = []
        for key in sorted(stock.keys() | assigned.keys()):
            expected = stock.get(key, Decimal(0))
            actual = assigned.get(key, Decimal(0))
            if expected == actual:
                continue
            warehouse, material_id = key
            differences.append({
                'warehouse_id': warehouse, 'warehouse_name': warehouses[warehouse].name,
                'material_id': material_id, 'sku': materials[material_id].sku,
                'stock_quantity': format(expected, 'f'), 'lot_quantity': format(actual, 'f'),
                'difference': format(expected - actual, 'f')})
        return {'as_of': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
                'warehouse_id': warehouse_id, 'material_id': material_id,
                'rows': rows, 'differences': differences, 'fully_allocated': not differences}


@router.get('/{lot_id}/history')
def history(lot_id: int = Path(gt=0), _: dict = Depends(require('inventory.view'))) -> dict:
    with orm_session() as db:
        lot = db.get(PhysicalLot, lot_id)
        if lot is None:
            raise HTTPException(404, '实物批次不存在')
        material = db.get(Material, lot.material_id)
        openings = []
        balances: dict[int, Decimal] = {}
        for opening, warehouse in db.execute(select(PhysicalLotOpening, Warehouse).join(
                Warehouse, Warehouse.id == PhysicalLotOpening.warehouse_id).where(
                    PhysicalLotOpening.lot_id == lot_id).order_by(PhysicalLotOpening.id)):
            balances[opening.warehouse_id] = balances.get(opening.warehouse_id, Decimal(0)) + Decimal(opening.quantity)
            openings.append({'id': opening.id, 'warehouse_id': opening.warehouse_id,
                             'warehouse_name': warehouse.name, 'quantity': opening.quantity,
                             'checkpoint_movement_id': opening.checkpoint_movement_id,
                             'evidence': opening.evidence, 'created_at': opening.created_at})
        movements = []
        for allocation, movement, warehouse, username in db.execute(
                select(PhysicalLotAllocation, StockMovement, Warehouse, User.username)
                .join(StockMovement, StockMovement.id == PhysicalLotAllocation.movement_id)
                .join(Warehouse, Warehouse.id == StockMovement.warehouse_id)
                .outerjoin(User, User.id == StockMovement.created_by)
                .where(PhysicalLotAllocation.lot_id == lot_id)
                .order_by(PhysicalLotAllocation.movement_id, PhysicalLotAllocation.id)):
            balances[movement.warehouse_id] = balances.get(movement.warehouse_id, Decimal(0)) + Decimal(allocation.quantity)
            movements.append({'id': allocation.id, 'movement_id': movement.id,
                              'warehouse_id': movement.warehouse_id, 'warehouse_name': warehouse.name,
                              'quantity': allocation.quantity, 'source_type': movement.source_type,
                              'source_id': movement.source_id, 'source_line_id': movement.source_line_id,
                              'created_by_name': username, 'created_at': movement.created_at,
                              'original_allocation_id': allocation.original_allocation_id})
        reclassifications = []
        records = db.execute(select(PhysicalLotReclassification, User.username)
            .join(User, User.id == PhysicalLotReclassification.created_by)
            .where((PhysicalLotReclassification.legacy_lot_id == lot_id)
                   | (PhysicalLotReclassification.verified_lot_id == lot_id))
            .order_by(PhysicalLotReclassification.id))
        for record, username in records:
            direction = -1 if record.legacy_lot_id == lot_id else 1
            balances[record.warehouse_id] = balances.get(record.warehouse_id, Decimal(0)) + direction * Decimal(record.quantity)
            counterpart_id = record.verified_lot_id if direction < 0 else record.legacy_lot_id
            counterpart = db.get(PhysicalLot, counterpart_id)
            reclassifications.append({'id': record.id, 'warehouse_id': record.warehouse_id,
                                      'warehouse_name': db.get(Warehouse, record.warehouse_id).name,
                                      'quantity': format(direction * Decimal(record.quantity), 'f'),
                                      'counterpart_lot_id': counterpart_id,
                                      'counterpart_lot_code': counterpart.code,
                                      'evidence': record.evidence, 'created_by_name': username,
                                      'original_reclassification_id': record.original_reclassification_id,
                                      'created_at': record.created_at})
        movement_evidence = []
        evidence_rows = db.execute(select(PhysicalLotMovementEvidence, StockMovement, User.username)
            .join(StockMovement, StockMovement.id == PhysicalLotMovementEvidence.movement_id)
            .join(User, User.id == PhysicalLotMovementEvidence.created_by)
            .where(PhysicalLotMovementEvidence.lot_id == lot_id)
            .order_by(PhysicalLotMovementEvidence.id))
        for record, movement, username in evidence_rows:
            balances[movement.warehouse_id] = balances.get(movement.warehouse_id, Decimal(0)) + Decimal(record.quantity)
            movement_evidence.append({'id': record.id, 'movement_id': movement.id,
                                      'warehouse_id': movement.warehouse_id,
                                      'warehouse_name': db.get(Warehouse, movement.warehouse_id).name,
                                      'quantity': record.quantity, 'source_type': movement.source_type,
                                      'source_id': movement.source_id, 'source_line_id': movement.source_line_id,
                                      'evidence': record.evidence, 'created_by_name': username,
                                      'original_evidence_id': record.original_evidence_id,
                                      'created_at': record.created_at})
        evidence_pairs = []
        for pair, username in db.execute(select(PhysicalLotEvidencePair, User.username)
                .join(User, User.id == PhysicalLotEvidencePair.created_by)
                .where(PhysicalLotEvidencePair.lot_id == lot_id)
                .order_by(PhysicalLotEvidencePair.id)):
            evidence_pairs.append({'id': pair.id,
                                   'inbound_movement_id': pair.inbound_movement_id,
                                   'outbound_movement_id': pair.outbound_movement_id,
                                   'inbound_evidence_id': pair.inbound_evidence_id,
                                   'outbound_evidence_id': pair.outbound_evidence_id,
                                   'quantity': pair.quantity, 'evidence': pair.evidence,
                                   'original_pair_id': pair.original_pair_id,
                                   'created_by_name': username, 'created_at': pair.created_at})
        evidence_groups = []
        for group, username in db.execute(select(PhysicalLotEvidenceGroup, User.username)
                .join(User, User.id == PhysicalLotEvidenceGroup.created_by)
                .where(PhysicalLotEvidenceGroup.lot_id == lot_id)
                .order_by(PhysicalLotEvidenceGroup.id)):
            links = db.scalars(select(PhysicalLotEvidenceGroupPair).where(
                PhysicalLotEvidenceGroupPair.group_id == group.id).order_by(
                    PhysicalLotEvidenceGroupPair.position))
            pairs = []
            for link in links:
                pair = db.get(PhysicalLotEvidencePair, link.pair_id)
                pairs.append({'id': pair.id, 'inbound_movement_id': pair.inbound_movement_id,
                              'outbound_movement_id': pair.outbound_movement_id,
                              'quantity': pair.quantity})
            evidence_groups.append({'id': group.id, 'evidence': group.evidence,
                                    'original_group_id': group.original_group_id,
                                    'created_by_name': username, 'created_at': group.created_at,
                                    'pairs': pairs})
        return {'as_of': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
                'lot': {'id': lot.id, 'material_id': lot.material_id, 'code': lot.code,
                        'source_kind': lot.source_kind, 'supplier_lot': lot.supplier_lot,
                        'manufactured_on': lot.manufactured_on, 'expires_on': lot.expires_on,
                        'origin_movement_id': lot.origin_movement_id,
                        'sku': material.sku, 'material_name': material.name, 'unit': material.unit},
                'openings': openings, 'movements': movements,
                'reclassifications': reclassifications, 'movement_evidence': movement_evidence,
                'evidence_pairs': evidence_pairs, 'evidence_groups': evidence_groups,
                'balances': [{'warehouse_id': warehouse_id,
                              'warehouse_name': db.get(Warehouse, warehouse_id).name,
                              'quantity': format(quantity, 'f')}
                             for warehouse_id, quantity in sorted(balances.items())]}
