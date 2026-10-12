"""由原单、真实凭证和已生效转账投影完整组合；不调用通用来源再次枚举转账。"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import (BusinessJournalPolicy, ControlBalanceTransfer, Journal, SubledgerOpening,
    SubledgerOpeningLine, SubledgerPayment, SubledgerOrderSettlement, SalesOrder, PurchaseOrder)
from app.finance.auxiliary_rules import combination
from app.finance.order_ledger_scope import ScopeGroup, project_orders, scope_key

ZERO = Decimal(0)


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def fingerprint(value) -> str:
    return hashlib.sha256(encode(value).encode()).hexdigest()


def origin_key(kind: str, source_type: str, identifier: int) -> tuple:
    return kind, source_type, identifier


def saved_origin(scope: dict) -> tuple:
    return origin_key(scope['kind'], scope['source_type'], scope['source_id'])


@dataclass
class OriginScope:
    kind: str
    source_type: str
    source_id: int
    party_id: int
    party_name: str
    reference: str
    groups: dict[tuple, ScopeGroup] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)


def executed_transfers(db: Session, to_date: str | None = None) -> list[ControlBalanceTransfer]:
    date = to_date or datetime.now(timezone.utc).date().isoformat()
    return list(db.scalars(select(ControlBalanceTransfer).where(
        ControlBalanceTransfer.status == 'executed', ControlBalanceTransfer.business_date <= date)
        .order_by(ControlBalanceTransfer.business_date, ControlBalanceTransfer.id)))


def transfer_proof(row: ControlBalanceTransfer) -> dict:
    return dict(type='control_transfer', transfer_id=row.id, journal_id=row.journal_id,
        date=row.business_date, from_delta=row.from_delta, reverses_id=row.reverses_id)


def apply_delta(groups: dict, saved: dict, value: Decimal, proof: dict) -> None:
    key = scope_key(saved['account_id'], saved['auxiliary'])
    group = groups.setdefault(key, ScopeGroup(saved['account_id'], saved['auxiliary']))
    group.amount += value
    group.evidence.append(proof)


def checked_transfer(db: Session, row: ControlBalanceTransfer) -> None:
    journal = db.get(Journal, row.journal_id)
    if journal is None or journal.status != 'posted' or journal.journal_date != row.business_date:
        raise HTTPException(409, f'余额转账 #{row.id} 缺少有效已过账凭证，不能推定余额')


def apply_order_transfers(db: Session, orders: dict, to_date: str) -> None:
    for row in executed_transfers(db, to_date):
        checked_transfer(db, row)
        for saved, sign in ((json.loads(row.from_scope_json), 1), (json.loads(row.to_scope_json), -1)):
            if saved['source_type'] != 'order':
                continue
            origin = orders.get((row.kind, saved['source_id']))
            if origin is None or origin.party_id != row.party_id:
                raise HTTPException(409, '转账订单原来源已失效，不能静默重建组合')
            apply_delta(origin.groups, saved, Decimal(row.from_delta) * sign, transfer_proof(row))


def origin_delta(db: Session, kind: str, source_type: str, identifier: int,
                 to_date: str | None = None) -> Decimal:
    result = ZERO
    for row in executed_transfers(db, to_date):
        if row.kind != kind:
            continue
        for saved, sign in ((json.loads(row.from_scope_json), 1), (json.loads(row.to_scope_json), -1)):
            if (saved['source_type'], saved['source_id']) == (source_type, identifier):
                result += Decimal(row.from_delta) * sign
    return result


def project_origins(db: Session, to_date: str | None = None, *, for_funds: bool = False) -> dict[tuple, OriginScope]:
    from app.finance.subledger_openings import balance, line_data
    from app.finance.subledger_order_balances import executed
    from app.finance.business_sources import business_sources
    from app.finance.business_journals import bindings_at
    date = to_date or datetime.now(timezone.utc).date().isoformat()
    opening = db.scalar(select(SubledgerOpening).where(SubledgerOpening.active_key == 1,
        SubledgerOpening.status == 'confirmed'))
    policy = db.get(BusinessJournalPolicy, 1)
    start_date = opening.effective_date if opening else policy.start_date if policy else None
    if start_date is None or start_date > date:
        raise HTTPException(409, '先配置业务凭证启用日期或确认历史分户方案，再核对完整组合转账')
    result = {}
    sources, bindings = business_sources(db), bindings_at(db, to_date)
    historical_lines = list(db.scalars(select(SubledgerOpeningLine).where(SubledgerOpeningLine.opening_id == opening.id))) if opening else []
    for line in historical_lines:
        public = line_data(line)
        baseline = balance(db, line, to_date, include_control_transfers=False)
        auxiliary = json.loads(line.auxiliary_json)
        key = scope_key(line.account_id, auxiliary)
        origin = OriginScope(line.kind, 'historical', line.id, public['party_id'],
            public['party_name'], line.document_reference)
        group = ScopeGroup(line.account_id, auxiliary, Decimal(baseline['outstanding_amount']))
        group.evidence.append(dict(type='opening', line_id=line.id, opening_id=opening.id,
            opening_version=opening.version, date=opening.effective_date, kind=line.kind,
            party_id=public['party_id'], account_id=line.account_id, auxiliary=auxiliary,
            debit=line.debit, credit=line.credit, document_reference=line.document_reference))
        origin.groups[key] = group
        for payment in db.scalars(select(SubledgerPayment).where(SubledgerPayment.opening_line_id == line.id,
                SubledgerPayment.status == 'executed').order_by(SubledgerPayment.id)):
            payment_date = (payment.executed_at or payment.created_at)[:10]
            if payment_date > date:
                continue
            proof = dict(type='historical_payment', payment_id=payment.id, amount=payment.amount,
                date=payment_date, reverses_id=payment.reverses_id)
            binding = bindings.get(f'subledger_payment:{payment.id}')
            source = sources.get(f'subledger_payment:{payment.id}')
            if binding and source and binding[1].status == 'posted' and binding[1].journal_date <= date and (
                    json.loads(binding[0].source_json)['fingerprint'] == source['fingerprint']):
                proof.update(journal_id=binding[1].id, fingerprint=source['fingerprint'], journal_date=binding[1].journal_date)
            elif not for_funds:
                origin.blockers.append(f'历史资金 #{payment.id} 尚无截止日内可核对的已过账凭证')
            if payment.control_scope_json is not None:
                saved = json.loads(payment.control_scope_json)
                # 原单总额已经扣除这笔资金，再把该扣减从旧组合移到固定实际组合。
                group.amount += Decimal(payment.amount)
                apply_delta(origin.groups, saved, -Decimal(payment.amount), proof)
            else:
                group.evidence.append(proof)
        group.evidence.extend(dict(type='historical_settlement', settlement_id=item['id'],
            amount=item['amount'], date=(item.get('executed_at') or item['created_at'])[:10])
            for item in baseline['settlements'])
        for row in db.scalars(executed(db, to_date).where(
                SubledgerOrderSettlement.opening_line_id == line.id)):
            group.evidence.append(dict(type='historical_order_settlement', settlement_id=row.id,
                amount=row.amount, direction=row.direction, date=row.executed_at[:10]))
        result[origin_key(line.kind, 'historical', line.id)] = origin
    for (kind, identifier), scope in project_orders(db, start_date, to_date,
            include_control_transfers=False, for_funds=for_funds).items():
        order = db.get(SalesOrder if kind == 'receivable' else PurchaseOrder, identifier)
        result[origin_key(kind, 'order', identifier)] = OriginScope(kind, 'order', identifier,
            scope.party_id, scope.party_name, order.reference, scope.groups, scope.blockers)
    for row in executed_transfers(db, to_date):
        checked_transfer(db, row)
        for saved, sign in ((json.loads(row.from_scope_json), 1), (json.loads(row.to_scope_json), -1)):
            origin = result.get(saved_origin(saved))
            if origin is None or origin.party_id != row.party_id:
                raise HTTPException(409, '已生效转账的往来或原单归属已变化')
            apply_delta(origin.groups, saved, Decimal(row.from_delta) * sign, transfer_proof(row))
    return result


def group_data(origin: OriginScope, group: ScopeGroup) -> dict:
    saved = dict(kind=origin.kind, source_type=origin.source_type, source_id=origin.source_id,
        party_id=origin.party_id, account_id=group.account_id, auxiliary=group.auxiliary)
    # 显示名称可修订；固定经济归属、真实来源及组合额度用于发现并发和失效草稿。
    proof = dict(scope={**saved, 'auxiliary': [dict(kind=kind, id=identifier)
        for kind, identifier in combination(group.auxiliary)]},
        outstanding_amount=f'{group.amount:.2f}', evidence=group.evidence, blockers=origin.blockers)
    return dict(**saved, party_name=origin.party_name, reference=origin.reference,
        outstanding_amount=f'{group.amount:.2f}', blockers=origin.blockers,
        evidence=group.evidence, fingerprint=fingerprint(proof))


def public_origin(origin: OriginScope) -> dict:
    return dict(kind=origin.kind, source_type=origin.source_type, source_id=origin.source_id,
        party_id=origin.party_id, party_name=origin.party_name, reference=origin.reference,
        outstanding_amount=f'{sum((group.amount for group in origin.groups.values()), ZERO):.2f}',
        blockers=origin.blockers, groups=[group_data(origin, group) for _, group in sorted(origin.groups.items())])


def public_origins(db: Session, to_date: str | None = None) -> list[dict]:
    return [public_origin(origin) for _, origin in sorted(project_origins(db, to_date).items())]
