"""从已过账来源凭证还原订单的控制科目和完整辅助组合，不套用当前通用映射。"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import JournalLine, OrderSettlementTransfer, PaymentRecord
from app.finance.auxiliary_rules import combination, snapshot_values
from app.finance.business_journals import bindings_at
from app.finance.business_sources import ROLE_LABELS, business_sources
from app.finance.routes import financial_entries, party_data
from app.finance.subledger_order_balances import active_records, order_id

ZERO = Decimal(0)


def scope_key(account_id: int, auxiliary: list) -> tuple:
    return account_id, combination(auxiliary)


@dataclass
class ScopeGroup:
    account_id: int
    auxiliary: list[dict]
    amount: Decimal = ZERO
    evidence: list[dict] = field(default_factory=list)


@dataclass
class OrderScope:
    kind: str
    order_id: int
    party_id: int
    party_name: str
    groups: dict[tuple, ScopeGroup] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)

    def block(self, message: str) -> None:
        if message not in self.blockers:
            self.blockers.append(message)


def control_proof(db: Session, source: dict, binding, kind: str, today: str) -> tuple[JournalLine, list[dict]]:
    """用途必须对应绑定时的科目、原金额和真实分录，不能从科目名称猜测。"""
    saved, journal = binding
    snapshot = json.loads(saved.source_json)
    if journal.status != 'posted' or journal.currency != 'CNY' or journal.journal_date > today:
        raise HTTPException(409, '来源凭证须已过账且日期不晚于核销当日')
    if snapshot.get('fingerprint') != source['fingerprint']:
        raise HTTPException(409, '来源与已过账凭证的经济依据已变化')
    account_id = json.loads(saved.mapping_json).get(kind)
    value = Decimal(source['roles'][kind])
    positions = snapshot.get('role_positions')
    lines = list(db.scalars(select(JournalLine).where(JournalLine.journal_id == journal.id)
        .order_by(JournalLine.position)))
    if positions is not None:
        candidates = [line for line in lines if line.position == positions.get(kind)]
    else:
        # 旧版服务端固定生成用途摘要；仅接受精确匹配的旧凭证，不回填或猜测归属。
        summary = f"{snapshot['label']} #{snapshot['source_id']} · {ROLE_LABELS[kind]}"
        candidates = [line for line in lines if line.summary == summary]
    candidates = [line for line in candidates if line.account_id == account_id
        and Decimal(line.debit) - Decimal(line.credit) == value]
    if len(candidates) != 1:
        raise HTTPException(409, '来源凭证缺少唯一可核对的往来用途分录')
    line = candidates[0]
    auxiliary = snapshot_values(db, line)
    pairs = combination(auxiliary)
    expected = {(item['kind'], item['party_id']) for item in source['business']}
    if source['source_type'] == 'payment_record':
        record = source['records'][0]
        expected.add((record['kind'], party_data(db, record['kind'], record['order_id'])['party_id']))
    if len(expected) != 1:
        raise HTTPException(409, '来源往来身份不明确，不能分配订单组合')
    expected_kind, identifier = next(iter(expected))
    partner_kind = 'customer' if expected_kind == 'receivable' else 'supplier'
    if (partner_kind, identifier) not in pairs or any(
            item_kind in ('customer', 'supplier') and (item_kind, item_id) != (partner_kind, identifier)
            for item_kind, item_id in pairs):
        raise HTTPException(409, '已过账分录的实际往来辅助与订单不一致')
    return line, auxiliary


def project_orders(db: Session, start_date: str, to_date: str | None = None,
                   *, include_control_transfers: bool = True, for_funds: bool = False) -> dict[tuple[str, int], OrderScope]:
    today = to_date or datetime.now(timezone.utc).date().isoformat()
    result: dict[tuple[str, int], OrderScope] = {}

    def owner(kind: str, identifier: int) -> OrderScope:
        key = kind, identifier
        if key not in result:
            party = party_data(db, kind, identifier)
            result[key] = OrderScope(kind, identifier, party['party_id'], party['party_name'])
        return result[key]

    for entry in financial_entries(db):
        if entry['order_id'] is not None and entry['posted_at'][:10] <= today:
            scope = owner(entry['kind'], entry['order_id'])
            if entry['amount'] is None:
                scope.block('订单有尚未定价的业务来源')
    for payment in db.scalars(select(PaymentRecord).where(PaymentRecord.status == 'executed')):
        if (payment.executed_at or payment.created_at)[:10] <= today:
            owner(payment.kind, payment.order_id)
    bindings = bindings_at(db, to_date)
    for source in business_sources(db).values():
        if source['source_date'] > today:
            continue
        allocations: dict[tuple[str, int], Decimal] = {}
        for entry in source['business']:
            if entry['order_id'] is not None and entry['amount'] is not None:
                key = entry['kind'], entry['order_id']
                allocations[key] = allocations.get(key, ZERO) + Decimal(entry['amount'])
        if source['source_type'] == 'payment_record':
            payment = source['records'][0]
            allocations[payment['kind'], payment['order_id']] = -Decimal(payment['amount'])
        for (kind, identifier), value in allocations.items():
            scope = owner(kind, identifier)
            if not value:
                continue
            problem = None
            if source['source_date'] < start_date:
                problem = '订单来源早于分户启用日，需核对期初归属'
            elif source['source_date'] > today:
                problem = '订单来源日期晚于核销当日'
            elif source['blockers']:
                problem = '订单来源尚有缺价或成本依据缺口'
            elif source['key'] not in bindings:
                problem = '订单来源尚无有效已过账凭证'
            elif bindings[source['key']][1].status != 'posted':
                problem = '订单来源凭证尚未过账'
            elif kind not in source['roles']:
                problem = '订单来源没有可分配的往来用途分录'
            if problem:
                pending_funds = (source['source_type'] == 'payment_record'
                    and source['records'][0].get('control_scope')
                    and source['source_date'] >= start_date and not source['blockers']
                    and (source['key'] not in bindings or bindings[source['key']][1].status != 'posted'))
                if not (for_funds and pending_funds):
                    scope.block(f"{source['label']} #{source['source_id']}：{problem}")
                if pending_funds:
                    # 已办理但待过账的组合资金先扣业务额度，同时保留总账缺口阻止新转账。
                    frozen = source['records'][0]['control_scope']
                    key = scope_key(frozen['account_id'], frozen['auxiliary'])
                    group = scope.groups.setdefault(key, ScopeGroup(frozen['account_id'], frozen['auxiliary']))
                    group.amount += value
                    group.evidence.append(dict(type='pending_payment', payment_id=source['source_id'],
                        date=source['source_date'], amount=f'{value:.2f}'))
                continue
            try:
                line, auxiliary = control_proof(db, source, bindings[source['key']], kind, today)
            except HTTPException as error:
                scope.block(f"{source['label']} #{source['source_id']}：{error.detail}")
                continue
            expected = sum((amount for (item_kind, _), amount in allocations.items() if item_kind == kind), ZERO)
            normalized = Decimal(source['roles'][kind]) * (1 if kind == 'receivable' else -1)
            if expected != normalized:
                scope.block('来源往来总额与逐订单分配不一致')
                continue
            key = scope_key(line.account_id, auxiliary)
            group = scope.groups.setdefault(key, ScopeGroup(line.account_id, auxiliary))
            group.amount += value
            group.evidence.append(dict(type='journal', source_key=source['key'], fingerprint=source['fingerprint'],
                journal_id=line.journal_id, journal_line_id=line.id, account_id=line.account_id, order_id=identifier,
                journal_date=bindings[source['key']][1].journal_date, auxiliary=auxiliary,
                amount=f'{value:.2f}'))

    # 已有订单间核销只保存订单身份。完整来源都属于唯一同组合时才可重放其归属。
    # 无法确定的旧事实明确阻止新抵销，不能把当前通用映射填进历史记录。
    transfers = [row for row in db.scalars(select(OrderSettlementTransfer).where(OrderSettlementTransfer.status == 'executed')
        .order_by(OrderSettlementTransfer.id)) if (row.executed_at or row.created_at)[:10] <= today]
    reversed_ids = {row.reverses_id for row in transfers if row.reverses_id is not None}
    for transfer in transfers:
        if transfer.reverses_id is not None or transfer.id in reversed_ids:
            continue
        source = owner(transfer.kind, transfer.from_order_id)
        target = owner(transfer.kind, transfer.to_order_id)
        if source.blockers or target.blockers or len(source.groups) != 1 or len(target.groups) != 1:
            for scope in (source, target):
                scope.block(f'订单核销 #{transfer.id} 缺少可核对的唯一组合归属')
            continue
        source_key, target_key = next(iter(source.groups)), next(iter(target.groups))
        if source_key != target_key or source.party_id != target.party_id:
            for scope in (source, target):
                scope.block(f'订单核销 #{transfer.id} 的双方组合不一致，须补证核对')
            continue
        source.groups[source_key].amount += Decimal(transfer.amount)
        target.groups[target_key].amount -= Decimal(transfer.amount)
        for scope, key, sign in ((source, source_key, 1), (target, target_key, -1)):
            group = scope.groups[key]
            group.evidence.append(dict(type='order_settlement', transfer_id=transfer.id, kind=transfer.kind, order_id=scope.order_id,
                from_order_id=transfer.from_order_id, to_order_id=transfer.to_order_id, party_id=transfer.party_id,
                amount=f'{Decimal(transfer.amount) * sign:.2f}', executed_at=transfer.executed_at or transfer.created_at,
                account_id=group.account_id, auxiliary=group.auxiliary))

    # 旧订单核销的归属依赖整条连接链；后发现的缺口须传到先处理的相邻订单。
    links: dict[tuple[str, int], set[tuple[str, int]]] = {}
    for transfer in transfers:
        if transfer.reverses_id is not None or transfer.id in reversed_ids:
            continue
        source_key, target_key = (transfer.kind, transfer.from_order_id), (transfer.kind, transfer.to_order_id)
        links.setdefault(source_key, set()).add(target_key)
        links.setdefault(target_key, set()).add(source_key)
    visited = set()
    for initial in links:
        if initial in visited:
            continue
        pending, component = [initial], set()
        while pending:
            key = pending.pop()
            if key in component:
                continue
            component.add(key); pending.extend(links[key] - component)
        visited.update(component)
        scopes = [result[key] for key in sorted(component)]
        if any(scope.blockers for scope in scopes):
            for scope in scopes:
                scope.block('关联订单的核销链存在归属缺口，请先撤销或核对相关抵扣')
            continue
        proofs = {}
        for scope in scopes:
            for group in scope.groups.values():
                for proof in group.evidence:
                    proofs[json.dumps(proof, ensure_ascii=False, sort_keys=True)] = proof
        # 金额只累计自身分配；链内其他订单的凭证作为额度来源依据一并固定和保护。
        for scope in scopes:
            for group in scope.groups.values():
                group.evidence = [proofs[key] for key in sorted(proofs)]

    for record in active_records(db, to_date):
        scope = owner(record.kind, order_id(record))
        auxiliary = json.loads(record.auxiliary_json)
        key = scope_key(record.account_id, auxiliary)
        group = scope.groups.setdefault(key, ScopeGroup(record.account_id, auxiliary))
        group.amount += Decimal(record.amount) * (1 if record.direction == 'order_credit' else -1)
    if include_control_transfers:
        from app.finance.control_balance_projection import apply_order_transfers
        apply_order_transfers(db, result, today)
    return result


def public_scope(scope: OrderScope) -> dict:
    return dict(kind=scope.kind, order_id=scope.order_id, party_id=scope.party_id, party_name=scope.party_name,
        blockers=scope.blockers, groups=[dict(account_id=group.account_id, auxiliary=group.auxiliary,
            outstanding_amount=f'{group.amount:.2f}', evidence=group.evidence)
            for _, group in sorted(scope.groups.items())])
