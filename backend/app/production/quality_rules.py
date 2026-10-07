"""不合格数量占用、冻结证据与返工依赖，共用调用方 ORM 事务。"""

import json
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import (Bom, Material, ProductionCompletion, ProductionCompletionReversal,
    QualityDisposition, QualityDispositionChange, QualityCostAllocation, ProductionSettlementReversal,
    User, Warehouse, WorkOrder)
from app.core.orm import model_data
from app.core.period_lock import ensure_date_unlocked
from app.production.cost_lock import ensure_unsettled

RESERVED = ('submitted', 'approved', 'posted')


def encoded(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def now(db: Session) -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def source(db: Session, completion_id: int, *, writable: bool = False) -> dict:
    completion = db.get(ProductionCompletion, completion_id)
    if completion is None:
        raise HTTPException(404, '原生产完工单不存在')
    order = db.get(WorkOrder, completion.work_order_id)
    bom = db.get(Bom, order.bom_id)
    material = db.get(Material, bom.product_material_id)
    reversed_id = db.scalar(select(ProductionCompletionReversal.id).where(
        ProductionCompletionReversal.production_completion_id == completion.id))
    valid = completion.status == 'posted' and reversed_id is None and Decimal(completion.rejected_quantity or '0') > 0
    if writable:
        if not valid or order.status not in ('in_progress', 'completed'):
            raise HTTPException(409, '仅未冲销的已确认不合格报工可以处置')
        ensure_unsettled(db, order.id)
        ensure_date_unlocked(db, completion.posted_at)
    return dict(**model_data(completion), work_order_status=order.status, bom_id=order.bom_id,
        product_material_id=material.id, product_sku=material.sku, product_name=material.name,
        product_unit=material.unit, warehouse_id=order.warehouse_id,
        warehouse_name=db.get(Warehouse, order.warehouse_id).name, valid=valid)


def reserved_quantity(db: Session, completion_id: int, *, exclude: int | None = None) -> Decimal:
    return sum((Decimal(row.quantity) for row in db.scalars(select(QualityDisposition).where(
        QualityDisposition.completion_id == completion_id, QualityDisposition.status.in_(RESERVED)))
        if row.id != exclude), Decimal(0))


def check_quantity(db: Session, record: QualityDisposition) -> dict:
    current = source(db, record.completion_id, writable=True)
    if Decimal(record.quantity) > Decimal(current['rejected_quantity']) - reserved_quantity(db, record.completion_id, exclude=record.id):
        raise HTTPException(409, '处置数量超过尚未占用的不合格数量，请重新加载原质检来源')
    return current


def record_for(db: Session, identifier: int, version: int | None = None) -> QualityDisposition:
    record = db.get(QualityDisposition, identifier)
    if record is None:
        raise HTTPException(404, '不合格品处置单不存在')
    if version is not None and record.version != version:
        raise HTTPException(409, '处置单已被其他操作更新，请重新加载后复核；本次输入未保存')
    return record


def audit(db: Session, record: QualityDisposition, before: dict | None, action: str, reason: str, user_id: int):
    db.flush()
    db.add(QualityDispositionChange(disposition_id=record.id, action=action,
        before_json=encoded(before) if before is not None else None, after_json=encoded(model_data(record)),
        reason=reason, changed_by=user_id))
    db.flush()


def independent_reviewer(db: Session, record: QualityDisposition, user_id: int):
    actors = set(db.scalars(select(QualityDispositionChange.changed_by).where(
        QualityDispositionChange.disposition_id == record.id,
        QualityDispositionChange.action.in_(('create', 'edit', 'submit')))))
    if user_id in actors or user_id in (record.created_by, record.submitted_by):
        raise HTTPException(403, '编制、修订或提交过此处置单的账号不得审核，包括管理员')


def active_quality_allocations(db: Session, *, disposition_id: int | None = None):
    statement = select(QualityCostAllocation).where(~select(ProductionSettlementReversal.id).where(
        ProductionSettlementReversal.settlement_id == QualityCostAllocation.settlement_id).exists())
    if disposition_id is not None:
        statement = statement.where(QualityCostAllocation.disposition_id == disposition_id)
    return list(db.scalars(statement))


def rework_source(db: Session, order_id: int) -> dict | None:
    record = db.scalar(select(QualityDisposition).where(QualityDisposition.rework_order_id == order_id))
    if record is None or record.status != 'posted':
        return None
    allocations = active_quality_allocations(db, disposition_id=record.id)
    allocation = allocations[0] if allocations else None
    parent = db.get(ProductionCompletion, record.completion_id)
    return dict(disposition_id=record.id, reference=record.reference, completion_id=record.completion_id,
        origin_work_order_id=parent.work_order_id, quantity=record.quantity,
        origin_settlement_id=allocation.settlement_id if allocation else None,
        amount=allocation.amount if allocation else None)


def disposition_data(db: Session, record: QualityDisposition, *, include_cost: bool = False) -> dict:
    changes = [dict(**model_data(change), changed_by_name=username,
        before=json.loads(change.before_json) if change.before_json else None,
        after=json.loads(change.after_json)) for change, username in db.execute(
            select(QualityDispositionChange, User.username).join(User, User.id == QualityDispositionChange.changed_by)
            .where(QualityDispositionChange.disposition_id == record.id).order_by(QualityDispositionChange.id))]
    allocations = active_quality_allocations(db, disposition_id=record.id)
    current = source(db, record.completion_id)
    from app.core.document_approval import find_case, case_data
    result = dict(**model_data(record),
        approval=case_data(find_case(db, 'QualityDisposition', record.id)),
        reversal_approval=case_data(find_case(db, 'QualityDisposition', record.id, 'reverse')), materials=json.loads(record.materials_json),
        frozen_source=json.loads(record.source_json), current_source_valid=current['valid'],
        source_work_order_id=current['work_order_id'], source_work_order_status=current['work_order_status'],
        created_by_name=db.get(User, record.created_by).username,
        author_ids=sorted({record.created_by} | {change['changed_by'] for change in changes
            if change['action'] in ('create','edit','submit')}), changes=changes,
        cost_visible=include_cost, cost_allocation=None if not allocations else dict(
            settlement_id=allocations[0].settlement_id, amount=allocations[0].amount if include_cost else None,
            loss_treatment=allocations[0].loss_treatment))
    for key in ('materials_json', 'source_json'):
        result.pop(key)
    return result


def ensure_completion_unallocated(db: Session, completion_id: int):
    if db.scalar(select(QualityDisposition.id).where(QualityDisposition.completion_id == completion_id,
        QualityDisposition.status.in_(RESERVED)).limit(1)) is not None:
        raise HTTPException(409, '原质检数量已有提交或确认的处置，请先取消或更正处置及返工来源')


def settlement_dispositions(db: Session, order_id: int) -> list[QualityDisposition]:
    completions = list(db.scalars(select(ProductionCompletion).where(ProductionCompletion.work_order_id == order_id,
        ProductionCompletion.status == 'posted', ~select(ProductionCompletionReversal.id).where(
            ProductionCompletionReversal.production_completion_id == ProductionCompletion.id).exists())))
    records = list(db.scalars(select(QualityDisposition).join(ProductionCompletion,
        ProductionCompletion.id == QualityDisposition.completion_id).where(ProductionCompletion.work_order_id == order_id)))
    if any(record.status in ('draft','submitted','approved','rejected') for record in records):
        raise HTTPException(409, '须先确认或取消工单未处理的不合格品处置单')
    posted = [record for record in records if record.status == 'posted']
    for completion in completions:
        quantity = sum((Decimal(record.quantity) for record in posted if record.completion_id == completion.id), Decimal(0))
        if quantity != Decimal(completion.rejected_quantity or '0'):
            raise HTTPException(409, f'完工单 #{completion.id} 的不合格数量尚未全部确认处置，不能结算')
    for record in posted:
        ensure_date_unlocked(db, record.posted_at)
        ensure_date_unlocked(db, db.get(ProductionCompletion, record.completion_id).posted_at)
    return sorted(posted, key=lambda row: row.id)
