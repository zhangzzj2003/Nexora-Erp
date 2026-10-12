"""历史原单与现有订单的双向同组合核销、独立审批及追加式撤销。"""

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.access.security import current_user, require
from app.core import document_approval as approval
from app.core.document_responses import NumberedRoute
from app.core.models import (BusinessJournalSource, Journal, JournalLine, OrderSettlementTransfer, PurchaseOrder, SalesOrder,
    SubledgerOpening, SubledgerOpeningLine, SubledgerOrderSettlement)
from app.core.orm import add_model, orm_session
from app.core.period_lock import ensure_date_unlocked
from app.finance.auxiliary_rules import combination, snapshot_values
from app.finance.business_sources import business_sources
from app.finance.journals import VersionInput
from app.finance.order_ledger_scope import OrderScope, project_orders, public_scope, scope_key
from app.finance.order_settlements import ReverseInput, TransferInput
from app.finance.routes import account_data, money, party_data
from app.finance.subledger_order_balances import active_records, order_id, record_data
from app.finance.subledger_rules import check_subledger


class SettlementInput(ReverseInput):
    opening_line_id: int = Field(gt=0, strict=True)
    order_id: int = Field(gt=0, strict=True)
    direction: Literal['historical_credit', 'order_credit']
    amount: Decimal
    reference: str = Field(min_length=1, max_length=100)
    _amount = field_validator('amount')(TransferInput.valid_amount.__func__)
    _reference = field_validator('reference')(TransferInput.trim_required.__func__)


router = APIRouter(route_class=NumberedRoute, prefix='/api/v1/finance/subledger-order-settlements')
read_access = require('subledger_order_settlement.view')


def saved_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def evidence_key(item: dict) -> tuple:
    return ('order_settlement', item['transfer_id'], item['order_id']) if item['type'] == 'order_settlement' else (
        'journal', item['source_key'], item['journal_id'], item['journal_line_id'], item['order_id'])


def evidence_state(db: Session, evidence: list[dict]) -> list[dict]:
    sources = business_sources(db)
    result = []
    for item in evidence:
        if item['type'] == 'order_settlement':
            transfer = db.get(OrderSettlementTransfer, item['transfer_id'])
            result.append(dict(type='order_settlement', transfer_id=item['transfer_id'],
                record=None if transfer is None else {field: getattr(transfer, field) for field in (
                    'kind', 'party_id', 'from_order_id', 'to_order_id', 'amount', 'status', 'executed_at')},
                reversals=list(db.scalars(select(OrderSettlementTransfer.id).where(
                    OrderSettlementTransfer.reverses_id == item['transfer_id'],
                    OrderSettlementTransfer.status == 'executed').order_by(OrderSettlementTransfer.id)))))
            continue
        journal = db.get(Journal, item['journal_id'])
        line = db.get(JournalLine, item['journal_line_id'])
        binding = db.scalar(select(BusinessJournalSource).where(BusinessJournalSource.journal_id == item['journal_id']))
        source = sources.get(item['source_key'])
        result.append(dict(type='journal', source_key=item['source_key'], journal_id=item['journal_id'],
            journal_line_id=item['journal_line_id'],
            fingerprint=source['fingerprint'] if source else None,
            binding_key=binding.active_key if binding else None,
            status=journal.status if journal else None, date=journal.journal_date if journal else None,
            reversals=list(db.scalars(select(Journal.id).where(Journal.reversal_of_id == item['journal_id'],
                Journal.status == 'posted').order_by(Journal.id))),
            line=None if line is None else dict(account_id=line.account_id, debit=line.debit,
                credit=line.credit, auxiliary=snapshot_values(db, line))))
    return result


def validate_settlement(db: Session, record: SubledgerOrderSettlement,
                        scopes: dict[tuple[str, int], OrderScope] | None = None) -> None:
    from app.finance.subledger_openings import balance
    today = datetime.now(timezone.utc).date().isoformat()
    check_subledger(db, today)
    ensure_date_unlocked(db, today)
    line = db.get(SubledgerOpeningLine, record.opening_line_id)
    if line is None:
        raise HTTPException(404, '历史分户原单不存在')
    opening = db.get(SubledgerOpening, line.opening_id)
    if opening.status != 'confirmed' or opening.active_key != 1:
        raise HTTPException(409, '历史原单须来自有效已确认分户方案')
    identifier = order_id(record)
    from app.finance.control_balance_funds import ensure_legacy_origin
    ensure_legacy_origin(db, line.kind, 'historical', line.id)
    ensure_legacy_origin(db, record.kind, 'order', identifier)
    party = party_data(db, record.kind, identifier)
    if record.kind != line.kind or party['party_id'] != (line.customer_id or line.supplier_id):
        raise HTTPException(409, '历史原单与订单须为同类同一实际往来对象')
    if record.account_id != line.account_id or combination(json.loads(record.auxiliary_json)) != combination(json.loads(line.auxiliary_json)):
        raise HTTPException(409, '核销须保留历史原单的控制科目及完整辅助组合')
    if record.reverses_id is not None:
        original = db.get(SubledgerOrderSettlement, record.reverses_id)
        if original is None or original.status != 'executed' or original.reverses_id is not None:
            raise HTTPException(409, '原核销未执行或本身为反向记录')
        fields = ('opening_line_id', 'sales_order_id', 'purchase_order_id', 'kind', 'direction',
                  'account_id', 'auxiliary_json', 'order_evidence_json')
        if any(getattr(record, field) != getattr(original, field) for field in fields) or Decimal(record.amount) != -Decimal(original.amount):
            raise HTTPException(409, '反向核销与原执行事实不一致')
        ensure_date_unlocked(db, original.executed_at)
        if db.scalar(select(SubledgerOrderSettlement.id).where(SubledgerOrderSettlement.reverses_id == original.id,
                SubledgerOrderSettlement.status != 'cancelled', SubledgerOrderSettlement.id != record.id).limit(1)):
            raise HTTPException(409, '原核销已有有效反向草稿或记录')
        return
    scopes = scopes if scopes is not None else project_orders(db, opening.effective_date)
    scope = scopes.get((record.kind, identifier))
    if scope is None or scope.blockers:
        raise HTTPException(409, '订单归属尚不可核对：' + ('；'.join(scope.blockers) if scope else '缺少业务来源'))
    group = scope.groups.get(scope_key(record.account_id, json.loads(record.auxiliary_json)))
    if group is None or not group.evidence:
        raise HTTPException(409, '订单没有与历史原单同控制科目及完整辅助组合的已过账来源')
    current = {evidence_key(item): item for item in group.evidence}
    stored = json.loads(record.order_evidence_json)
    if not stored or any(current.get(evidence_key(item)) != item for item in stored):
        raise HTTPException(409, '已核对的订单凭证依据已变化，请取消后重新编制')
    account = account_data(db, record.kind, identifier)
    if not account['source_keys']:
        raise HTTPException(409, '订单须有已确认且已定价业务来源')
    live = Decimal(account['outstanding_amount'])
    historical = Decimal(balance(db, line)['outstanding_amount'])
    amount = Decimal(record.amount)
    limits = (-historical, live, group.amount) if record.direction == 'historical_credit' else (historical, -live, -group.amount)
    if amount <= 0 or amount > min(limits):
        raise HTTPException(409, '核销超过历史原单、订单最新余额或匹配组合的可用额度')


@router.get('')
def list_settlements(_: dict = Depends(read_access)) -> list[dict]:
    with orm_session() as db:
        return [record_data(db, row) for row in db.scalars(select(SubledgerOrderSettlement)
            .order_by(SubledgerOrderSettlement.id.desc()))]


@router.get('/options')
def settlement_options(_: dict = Depends(read_access)) -> dict:
    from app.finance.subledger_openings import balance
    with orm_session() as db:
        opening = db.scalar(select(SubledgerOpening).where(SubledgerOpening.active_key == 1,
            SubledgerOpening.status == 'confirmed'))
        if opening is None:
            return dict(currency='CNY', active=False, lines=[], orders=[])
        originals = []
        fields = ('id', 'opening_id', 'kind', 'account_id', 'account_code', 'account_name', 'party_id', 'party_name',
                  'document_reference', 'document_date', 'auxiliary', 'opening_amount', 'outstanding_amount')
        for line in db.scalars(select(SubledgerOpeningLine).where(SubledgerOpeningLine.opening_id == opening.id)
                .order_by(SubledgerOpeningLine.position)):
            row = balance(db, line)
            originals.append({field: row[field] for field in fields})
        orders = []
        for scope in project_orders(db, opening.effective_date).values():
            order = db.get(SalesOrder if scope.kind == 'receivable' else PurchaseOrder, scope.order_id)
            orders.append(dict(**public_scope(scope), currency='CNY', order_document_no=order.document_no,
                outstanding_amount=account_data(db, scope.kind, scope.order_id)['outstanding_amount']))
        return dict(currency='CNY', active=True, lines=originals,
            orders=sorted(orders, key=lambda row: (row['kind'], row['order_id'])))


@router.post('', status_code=201)
def create_settlement(data: SettlementInput, user: dict = Depends(require('finance.record')),
                      _: dict = Depends(read_access)) -> dict:
    try:
        with orm_session(write=True) as db:
            approval.actor(db, user['id'], 'finance.record')
            approval.actor(db, user['id'], 'subledger_order_settlement.view')
            line = db.get(SubledgerOpeningLine, data.opening_line_id)
            if line is None:
                raise HTTPException(404, '历史分户原单不存在')
            opening = db.get(SubledgerOpening, line.opening_id)
            scopes = project_orders(db, opening.effective_date)
            scope = scopes.get((line.kind, data.order_id))
            group = scope.groups.get(scope_key(line.account_id, json.loads(line.auxiliary_json))) if scope else None
            record = SubledgerOrderSettlement(opening_line_id=line.id, kind=line.kind,
                sales_order_id=data.order_id if line.kind == 'receivable' else None,
                purchase_order_id=data.order_id if line.kind == 'payable' else None,
                direction=data.direction, account_id=line.account_id, auxiliary_json=line.auxiliary_json,
                order_evidence_json=saved_json(group.evidence if group else []), amount=money(data.amount),
                reference=data.reference, reason=data.reason, created_by=user['id'], status='draft', version=1)
            validate_settlement(db, record, scopes)
            add_model(db, record)
            return record_data(db, record)
    except IntegrityError:
        raise HTTPException(409, '此原单、订单与方向的核销参考号已使用') from None


@router.post('/{settlement_id}/reverse', status_code=201)
def reverse_settlement(data: ReverseInput, settlement_id: int = Path(gt=0),
                       user: dict = Depends(require('finance.reverse')), _: dict = Depends(read_access)) -> dict:
    try:
        with orm_session(write=True) as db:
            approval.actor(db, user['id'], 'finance.reverse')
            approval.actor(db, user['id'], 'subledger_order_settlement.view')
            original = db.get(SubledgerOrderSettlement, settlement_id)
            if original is None:
                raise HTTPException(404, '历史与订单核销不存在')
            fields = ('opening_line_id', 'sales_order_id', 'purchase_order_id', 'kind', 'direction',
                      'account_id', 'auxiliary_json', 'order_evidence_json')
            record = SubledgerOrderSettlement(**{field: getattr(original, field) for field in fields},
                amount=money(-Decimal(original.amount)), reference=f'冲销 #{original.id}', reason=data.reason,
                reverses_id=original.id, created_by=user['id'], status='draft', version=1)
            validate_settlement(db, record)
            add_model(db, record)
            return record_data(db, record)
    except IntegrityError:
        raise HTTPException(409, '原核销已有有效反向草稿或记录') from None


@router.post('/{settlement_id}/{action}')
def execute_settlement(action: Literal['post', 'cancel'], data: VersionInput, settlement_id: int = Path(gt=0),
                       user: dict = Depends(current_user), _: dict = Depends(read_access)) -> dict:
    from app.core.approval_documents import subledger_order_settlement_snapshot
    with orm_session(write=True) as db:
        approval.actor(db, user['id'], 'subledger_order_settlement.view')
        record = db.get(SubledgerOrderSettlement, settlement_id)
        if record is None:
            raise HTTPException(404, '历史与订单核销不存在')
        permission = 'finance.reverse' if record.reverses_id is not None else 'finance.record'
        approval.actor(db, user['id'], permission)
        if record.status != 'draft' or record.version != data.version:
            raise HTTPException(409, '核销已变化或已处理，请重新读取')
        if not data.reason.strip() or len(data.reason.strip()) > 200:
            raise HTTPException(422, '执行或取消依据必填，最多二百字')
        case = approval.find_case(db, 'SubledgerOrderSettlement', record.id)
        if action == 'cancel':
            if case and case.status in ('submitted', 'approved'):
                raise HTTPException(409, '请先撤回核销审批，再取消草稿')
            record.status, record.cancelled_by, record.cancelled_at = 'cancelled', user['id'], approval.now(db)
            record.cancellation_reason = data.reason.strip()
        else:
            case = approval.require_approved(db, 'SubledgerOrderSettlement', record.id,
                subledger_order_settlement_snapshot(db, record.id), user['id'], permission=permission)
            validate_settlement(db, record)
            record.status, record.executed_by, record.executed_at = 'executed', user['id'], approval.now(db)
            ensure_date_unlocked(db, record.executed_at)
            check_subledger(db, record.executed_at)
            approval.mark_executed(db, case, user['id'], permission=permission, reason=data.reason.strip())
        record.version += 1
        db.flush()
        return record_data(db, record)


def protect_journal(db: Session, journal_id: int) -> None:
    for record in active_records(db):
        if any(item.get('journal_id') == journal_id for item in json.loads(record.order_evidence_json)):
            raise HTTPException(409, '此凭证是已执行历史与订单核销的组合依据，请先独立撤销该核销')
    protected = protected_orders(db)
    if not protected:
        return
    opening = db.scalar(select(SubledgerOpening).where(SubledgerOpening.active_key == 1))
    scopes = project_orders(db, opening.effective_date, include_control_transfers=False)
    if any((scope.kind, scope.order_id) in protected and any(proof.get('journal_id') == journal_id
            for group in scope.groups.values() for proof in group.evidence) for scope in scopes.values()):
        raise HTTPException(409, '此凭证属于已执行历史核销的关联订单依据，请先独立撤销该核销')


def protected_orders(db: Session) -> set[tuple[str, int]]:
    protected = {(record.kind, order_id(record)) for record in active_records(db)}
    if not protected:
        return protected
    transfers = list(db.scalars(select(OrderSettlementTransfer).where(OrderSettlementTransfer.status == 'executed')))
    reversed_ids = {row.reverses_id for row in transfers if row.reverses_id is not None}
    links: dict[tuple[str, int], set[tuple[str, int]]] = {}
    for row in transfers:
        if row.reverses_id is not None or row.id in reversed_ids:
            continue
        source, target = (row.kind, row.from_order_id), (row.kind, row.to_order_id)
        links.setdefault(source, set()).add(target); links.setdefault(target, set()).add(source)
    pending = list(protected)
    while pending:
        key = pending.pop()
        for related in links.get(key, set()) - protected:
            protected.add(related); pending.append(related)
    return protected


def protect_order_transfer(db: Session, kind: str, source_id: int, target_id: int) -> None:
    if not {(kind, source_id), (kind, target_id)} & protected_orders(db):
        return
    opening = db.scalar(select(SubledgerOpening).where(SubledgerOpening.active_key == 1))
    scopes = project_orders(db, opening.effective_date)
    source, target = scopes.get((kind, source_id)), scopes.get((kind, target_id))
    if source is None or target is None or source.blockers or target.blockers or len(source.groups) != 1 or len(target.groups) != 1:
        raise HTTPException(409, '关联历史核销的订单间抵扣须有唯一完整组合，不能混合归属')
    if next(iter(source.groups)) != next(iter(target.groups)):
        raise HTTPException(409, '关联历史核销的订单间抵扣不能跨控制科目或辅助组合')
