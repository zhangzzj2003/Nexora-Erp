"""按已过账余额生成损益结转；金额与来源在服务端事务内固定。"""

from app.core.document_responses import NumberedRoute
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.access.security import require
from app.core.models import (AccountingPeriod, Journal, JournalLine, LedgerAccount,
    ProfitTransfer, ProfitTransferPolicy, ProfitTransferPolicyChange, User)
from app.core.orm import add_model, model_data, orm_session
from app.core.period_lock import ensure_date_unlocked
from app.finance.business_sources import encoded
from app.finance.business_journals import posted_reversal, pending_sources
from app.finance.journals import JournalInput, JournalLineInput, ReasonInput, audit, save_lines, view
from app.finance.ledger import PeriodInput, get_record, snapshot
from app.finance.ledger_reports import confirmed_opening_lines
from app.finance.opening_rules import check_journal_opening
from app.finance.auxiliary_rules import snapshot_values, combination

router = APIRouter(route_class=NumberedRoute, prefix='/api/v1/finance/profit-transfers')
ZERO = Decimal(0)


def utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


class PolicyInput(ReasonInput):
    version: int = Field(ge=0, strict=True)
    start_date: str
    target_account_id: int = Field(gt=0, strict=True)
    cost_account_ids: list[int] = Field(default_factory=list, max_length=1000)

    _date = field_validator('start_date')(PeriodInput.valid_date.__func__)

    @field_validator('cost_account_ids', mode='before')
    @classmethod
    def cost_ids(cls, value):
        if not isinstance(value, list) or any(type(item) is not int or item <= 0 for item in value):
            raise ValueError('成本科目须为正整数编号列表')
        if len(set(value)) != len(value):
            raise ValueError('成本科目不能重复')
        return sorted(value)


class GenerateInput(ReasonInput):
    period_id: int = Field(gt=0, strict=True)
    period_version: int = Field(gt=0, strict=True)
    policy_version: int = Field(gt=0, strict=True)
    fingerprint: str = Field(pattern=r'^[0-9a-f]{64}$')
    reference: str = Field(min_length=1, max_length=80)

    _reference = field_validator('reference')(JournalInput.nonblank_reference.__func__)


def policy_data(record: ProfitTransferPolicy | None) -> dict:
    if record is None:
        return dict(version=0, start_date='', target_account_id=None, cost_account_ids=[])
    return dict(version=record.version, start_date=record.start_date,
        target_account_id=record.target_account_id, cost_account_ids=json.loads(record.cost_account_ids_json),
        changed_by=record.changed_by, created_at=record.created_at)


def balances(db: Session, period: AccountingPeriod, policy: dict, exclude_journal_id: int | None = None) -> dict:
    """沿用正式期初和全部已过账分录；成本类只结转公司明确选择的科目。"""
    accounts = {item.id: item for item in db.scalars(select(LedgerAccount).order_by(LedgerAccount.code))}
    selected = {identifier for identifier, item in accounts.items() if item.category in ('income', 'expense')}
    selected.update(policy['cost_account_ids'])
    nets = {identifier: ZERO for identifier in accounts}
    auxiliary_nets, auxiliary_snapshots = {}, {}

    def accumulate(line):
        values = snapshot_values(db, line)
        key = (line.account_id, combination(values))
        nets[line.account_id] += Decimal(line.debit) - Decimal(line.credit)
        auxiliary_nets[key] = auxiliary_nets.get(key, ZERO) + Decimal(line.debit) - Decimal(line.credit)
        auxiliary_snapshots.setdefault(key[1], values)
        # 没有辅助信息的旧来源保持原指纹，避免升级改写既有已过账结转。
        return {'auxiliary': values} if values else {}

    opening_sources, sources = [], []
    for line in confirmed_opening_lines(db):
        auxiliary = accumulate(line)
        if line.account_id in selected:
            opening_sources.append(dict(line_id=line.id, opening_balance_id=line.opening_balance_id,
                account_id=line.account_id, debit=line.debit, credit=line.credit, **auxiliary))
    for line, journal in db.execute(select(JournalLine, Journal)
            .join(Journal, Journal.id == JournalLine.journal_id)
            .where(Journal.status == 'posted', Journal.journal_date <= period.end_date)
            .order_by(Journal.journal_date, Journal.id, JournalLine.position)):
        if journal.id == exclude_journal_id:
            continue
        auxiliary = accumulate(line)
        if line.account_id in selected:
            sources.append(dict(journal_id=journal.id, line_id=line.id, account_id=line.account_id,
                journal_date=journal.journal_date, reference=journal.reference,
                reversal_of_id=journal.reversal_of_id, debit=line.debit, credit=line.credit, **auxiliary))
    rows, lines, frozen, blockers = [], [], [], []
    blockers.extend(f'科目 #{identifier} 不存在' for identifier in selected if identifier not in accounts)
    profit_by_auxiliary = {}
    for (identifier, key), net in sorted(auxiliary_nets.items(), key=lambda item: (accounts[item[0][0]].code, item[0][1])):
        if identifier not in selected:
            continue
        account = accounts[identifier]
        profit_by_auxiliary[key] = profit_by_auxiliary.get(key, ZERO) - net
        if not net:
            continue
        if not account.is_active:
            blockers.append(f'科目 {account.code} 已停用，须先启用并核对余额')
        if abs(net) >= Decimal('1000000000000'):
            blockers.append(f'科目 {account.code} 余额超出单条凭证金额范围')
        row = dict(account_id=identifier, code=account.code, name=account.name, category=account.category,
            balance=f'{net:.2f}', debit=f'{max(-net, ZERO):.2f}', credit=f'{max(net, ZERO):.2f}',
            auxiliary=auxiliary_snapshots[key])
        rows.append(row)
        lines.append({field: row[field] for field in ('account_id', 'debit', 'credit')})
        frozen.append(auxiliary_snapshots[key])
    # 转入科目以借方为正；盈利转贷方，亏损转借方；净额为零时仍清空各损益科目。
    net_profit = -sum((nets.get(identifier, ZERO) for identifier in selected), ZERO)
    target = accounts.get(policy['target_account_id'])
    if target is None or not target.is_active or target.category != 'equity' or target.normal_balance != 'credit':
        blockers.append('本年利润须配置启用、贷方方向的权益科目')
    if abs(net_profit) >= Decimal('1000000000000'):
        blockers.append('结转净额超出单条凭证金额范围')
    for key, profit in sorted(profit_by_auxiliary.items()):
        if abs(profit) >= Decimal('1000000000000'):
            blockers.append('辅助组合结转净额超出单条凭证金额范围')
        if profit and target:
            lines.append(dict(account_id=target.id, debit=f'{max(-profit, ZERO):.2f}', credit=f'{max(profit, ZERO):.2f}'))
            frozen.append(auxiliary_snapshots[key])
    if len(lines) > 100:
        blockers.append('辅助组合超过单张凭证 100 条分录上限，须先核对并减少组合范围')
    economic = dict(period_id=period.id, start_date=period.start_date, end_date=period.end_date,
        policy_version=policy['version'], target_account_id=policy['target_account_id'],
        cost_account_ids=policy['cost_account_ids'], opening_sources=opening_sources, sources=sources)
    fingerprint = hashlib.sha256(encoded(economic).encode()).hexdigest()
    excluded = [dict(account_id=item.id, code=item.code, name=item.name, balance=f'{nets[item.id]:.2f}')
        for item in accounts.values() if item.category == 'cost' and item.id not in selected and nets[item.id]]
    return dict(**economic, fingerprint=fingerprint, currency='CNY', time_basis='UTC', rows=rows,
        lines=lines, line_auxiliary=frozen, net_profit=f'{net_profit:.2f}', blockers=blockers, excluded_cost_accounts=excluded,
        target_account=({**model_data(target), 'is_active': bool(target.is_active)} if target else None))


def precheck(db: Session, period: AccountingPeriod) -> dict:
    policy = policy_data(db.get(ProfitTransferPolicy, 1))
    evidence = balances(db, period, policy)
    blockers = list(evidence['blockers'])
    if not policy['version']:
        blockers.append('先配置损益结转启用日期、本年利润和成本科目范围')
    elif period.start_date < policy['start_date']:
        blockers.append('期间早于结转启用日期，须人工核对历史损益')
    if period.status != 'open':
        blockers.append('期间已结账，须先重开才能结转或更正')
    if period.end_date >= utc_today():
        blockers.append('只能结转已结束期间；日期按服务端 UTC 归属')
    if db.scalar(select(AccountingPeriod.id).where(AccountingPeriod.end_date < period.start_date,
            AccountingPeriod.status != 'closed').limit(1)):
        blockers.append('须先结账更早的期间')
    if db.scalar(select(Journal.id).where(Journal.journal_date <= period.end_date,
            Journal.status.not_in(('posted', 'cancelled'))).limit(1)):
        blockers.append('须先过账或取消截至期末的其他未处理凭证')
    missing = pending_sources(db, period.end_date)
    if missing:
        blockers.append('须先核价并过账纳管业务来源：' + '、'.join(missing))
    try:
        check_journal_opening(db, period.end_date)
    except HTTPException as exc:
        blockers.append(str(exc.detail))
    active = db.scalar(select(ProfitTransfer).where(ProfitTransfer.active_period_id == period.id))
    if active:
        blockers.append('本期间已有有效结转；草稿须取消，已过账结转须在原期间末冲销后重建')
    if not evidence['rows']:
        blockers.append('纳管损益科目余额均为零，无需生成结转凭证')
    warnings = ['本预览是截至期末的累计待结余额，包含正式期初及历史余额；不等同于本期利润表。',
        '成本类仅纳入明确选择的科目；生产成本、在制品不得未经核对作为损益结转。',
        '生成后仍须提交、另一账号审核并过账；更正时须从较晚结转倒序冲销。']
    journal = db.get(Journal, active.journal_id) if active else None
    return dict(period=snapshot(period), policy_version=policy['version'], evidence=evidence,
        fingerprint=evidence['fingerprint'], can_generate=not blockers, blockers=blockers, warnings=warnings,
        journal_id=journal.id if journal else None, journal_status=journal.status if journal else None)


@router.get('/policy')
def options(_: dict = Depends(require('profit_transfer.view'))) -> dict:
    with orm_session() as db:
        return dict(policy=policy_data(db.get(ProfitTransferPolicy, 1)),
            accounts=[{**model_data(item), 'is_active': bool(item.is_active)}
                for item in db.scalars(select(LedgerAccount).order_by(LedgerAccount.code))],
            periods=[snapshot(item) for item in db.scalars(select(AccountingPeriod).order_by(AccountingPeriod.start_date.desc()))])


@router.put('/policy')
def save_policy(data: PolicyInput, user: dict = Depends(require('profit_transfer.configure'))) -> dict:
    with orm_session(write=True) as db:
        record = db.get(ProfitTransferPolicy, 1)
        before = policy_data(record)
        if data.version != before['version']:
            raise HTTPException(409, '结转配置已变化，请刷新核对后再保存')
        if record and record.start_date != data.start_date:
            raise HTTPException(409, '启用日期保存后固定，不能改写结转纳管范围')
        if record is None:
            ensure_date_unlocked(db, data.start_date)
            period = db.scalar(select(AccountingPeriod).where(AccountingPeriod.start_date == data.start_date))
            if period is None or period.status != 'open':
                raise HTTPException(409, '启用日期须为开放会计期间的开始日期')
        target = db.get(LedgerAccount, data.target_account_id)
        if target is None or not target.is_active or target.category != 'equity' or target.normal_balance != 'credit':
            raise HTTPException(409, '本年利润须选择启用、贷方方向的权益科目')
        for identifier in data.cost_account_ids:
            item = db.get(LedgerAccount, identifier)
            if item is None or not item.is_active or item.category != 'cost':
                raise HTTPException(409, '成本纳管范围须选择已存在且启用的成本类科目')
        if record and record.target_account_id == data.target_account_id and json.loads(record.cost_account_ids_json) == data.cost_account_ids:
            raise HTTPException(409, '结转配置没有变化')
        if record is None:
            record = ProfitTransferPolicy(id=1, start_date=data.start_date, target_account_id=data.target_account_id,
                cost_account_ids_json=encoded(data.cost_account_ids), version=1, changed_by=user['id'])
            db.add(record)
        else:
            record.target_account_id = data.target_account_id
            record.cost_account_ids_json = encoded(data.cost_account_ids)
            record.version += 1
            record.changed_by = user['id']
        db.flush()
        db.add(ProfitTransferPolicyChange(before_json=encoded(before), after_json=encoded(policy_data(record)),
            reason=data.reason, changed_by=user['id']))
        db.flush()
        return policy_data(record)


@router.get('/policy/changes')
def policy_changes(_: dict = Depends(require('profit_transfer.view'))) -> list[dict]:
    with orm_session() as db:
        return [dict(id=item.id, before=json.loads(item.before_json) if item.before_json else None,
            after=json.loads(item.after_json), reason=item.reason, changed_by=item.changed_by,
            changed_by_name=username, created_at=item.created_at)
            for item, username in db.execute(select(ProfitTransferPolicyChange, User.username)
                .join(User, User.id == ProfitTransferPolicyChange.changed_by).order_by(ProfitTransferPolicyChange.id.desc()))]


@router.get('/periods/{period_id}')
def preview(period_id: int = Path(gt=0), _: dict = Depends(require('profit_transfer.view'))) -> dict:
    with orm_session() as db:
        return precheck(db, get_record(db, AccountingPeriod, period_id))


@router.post('/generate', status_code=201)
def generate(data: GenerateInput, user: dict = Depends(require('profit_transfer.generate'))) -> dict:
    try:
        with orm_session(write=True) as db:
            period = get_record(db, AccountingPeriod, data.period_id, data.period_version)
            policy = policy_data(db.get(ProfitTransferPolicy, 1))
            if policy['version'] != data.policy_version:
                raise HTTPException(409, '结转配置已变化，请刷新预览后再生成')
            result = precheck(db, period)
            if data.fingerprint != result['fingerprint']:
                raise HTTPException(409, '已过账来源已变化，请刷新预览并核对')
            if not result['can_generate']:
                raise HTTPException(409, '；'.join(result['blockers']))
            evidence = result['evidence']
            record = add_model(db, Journal(reference=data.reference, journal_date=period.end_date,
                period_id=period.id, note=data.reason, status='draft', version=1, created_by=user['id']))
            save_lines(db, record, [JournalLineInput(**line, summary=f'{period.code} · 损益结转') for line in evidence['lines']],
                frozen_auxiliary=evidence['line_auxiliary'])
            add_model(db, ProfitTransfer(journal_id=record.id, period_id=period.id, active_period_id=period.id,
                evidence_json=encoded(evidence), policy_json=encoded(policy)))
            audit(db, record, None, 'create', data.reason, user['id'])
            return view(db, record)
    except IntegrityError:
        raise HTTPException(409, '本期间已有结转或凭证依据编号已使用，请刷新核对') from None


def validate_source(db: Session, journal: Journal) -> None:
    binding = db.scalar(select(ProfitTransfer).where(ProfitTransfer.journal_id == journal.id))
    if binding:
        policy = json.loads(binding.policy_json)
        current_policy = policy_data(db.get(ProfitTransferPolicy, 1))
        period = db.get(AccountingPeriod, binding.period_id)
        evidence = balances(db, period, policy, journal.id)
        if policy['version'] != current_policy['version'] or evidence['fingerprint'] != json.loads(binding.evidence_json)['fingerprint']:
            raise HTTPException(409, '损益结转来源或配置已变化，请取消草稿并重新生成')
        if journal.journal_date != period.end_date or journal.period_id != period.id:
            raise HTTPException(409, '损益结转必须记入原期间末')
        if evidence['blockers']:
            raise HTTPException(409, '；'.join(evidence['blockers']))
        if db.scalar(select(Journal.id).where(Journal.id != journal.id,
                Journal.journal_date <= period.end_date, Journal.status.not_in(('posted', 'cancelled'))).limit(1)):
            raise HTTPException(409, '须先过账或取消截至期末的其他未处理凭证')
        if pending_sources(db, period.end_date):
            raise HTTPException(409, '须先处理纳管范围内未过账的业务来源')
        if db.scalar(select(AccountingPeriod.id).where(AccountingPeriod.end_date < period.start_date,
                AccountingPeriod.status != 'closed').limit(1)):
            raise HTTPException(409, '须先结账更早的期间')
    if journal.reversal_of_id:
        original = db.scalar(select(ProfitTransfer).where(ProfitTransfer.journal_id == journal.reversal_of_id))
        if original:
            period = db.get(AccountingPeriod, original.period_id)
            if journal.journal_date != period.end_date or journal.period_id != period.id:
                raise HTTPException(409, '结转冲销必须记入原期间末；已结期间须先倒序重开')


def release_source(db: Session, journal: Journal) -> None:
    identifier = journal.reversal_of_id if journal.status == 'posted' else journal.id
    if journal.status not in ('posted', 'cancelled') or identifier is None:
        return
    binding = db.scalar(select(ProfitTransfer).where(ProfitTransfer.journal_id == identifier))
    if binding and (journal.status == 'cancelled' or journal.reversal_of_id is not None):
        binding.active_period_id = None


def validate_posted_sources(db: Session) -> None:
    for binding, journal in db.execute(select(ProfitTransfer, Journal)
            .join(Journal, Journal.id == ProfitTransfer.journal_id).where(Journal.status == 'posted')):
        if posted_reversal(db, journal.id):
            continue
        period = db.get(AccountingPeriod, binding.period_id)
        current = balances(db, period, json.loads(binding.policy_json), journal.id)
        if current['fingerprint'] != json.loads(binding.evidence_json)['fingerprint']:
            raise HTTPException(409, f'变更会改写已过账损益结转 #{journal.id} 的来源，须先从较晚期间倒序冲销结转')


def closing_evidence(db: Session, period: AccountingPeriod) -> dict:
    policy = policy_data(db.get(ProfitTransferPolicy, 1))
    # 旧期间沿用历史结账口径；启用后的期间必须逐个损益科目清零，不能只核对净额。
    if not policy['version']:
        rows = balances(db, period, policy)['rows']
        return dict(required=bool(rows), residuals=rows, policy=policy, journal_id=None)
    if period.start_date < policy['start_date']:
        return dict(required=False, residuals=[], policy=policy, journal_id=None)
    result = balances(db, period, policy)
    binding = db.scalar(select(ProfitTransfer).where(ProfitTransfer.active_period_id == period.id))
    return dict(required=True, residuals=result['rows'], policy=policy,
        journal_id=binding.journal_id if binding else None, excluded_cost_accounts=result['excluded_cost_accounts'])
