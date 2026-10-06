"""公司配置的资产负债与损益报表；查询、归档均使用同一 ORM 快照。"""

from app.core.document_responses import NumberedRoute
import csv
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.access.security import require
from app.core.models import (AccountingPeriod, BusinessJournalSource, FinancialStatement,
    FinancialStatementPolicy, FinancialStatementPolicyChange, Journal, JournalLine,
    LedgerAccount, ProfitTransfer, ProfitTransferPolicy, User)
from app.core.orm import add_model, model_data, orm_session
from app.finance.business_sources import encoded
from app.finance.journals import ReasonInput
from app.finance.ledger import PeriodInput, snapshot
from app.finance.ledger_reports import confirmed_opening_lines
from app.finance.opening_rules import active_opening
from app.reports.routes import csv_value
from app.finance.auxiliary_rules import snapshot_values

router = APIRouter(route_class=NumberedRoute, prefix='/api/v1/finance/statements')
ZERO = Decimal(0)
GROUPS = {'asset': '资产', 'liability': '负债', 'equity': '权益', 'revenue': '收入', 'expense': '费用及销售成本'}


def money(value: Decimal) -> str:
    # 零余额统一显示为正零；展示符号不改变 Decimal 的金额或来源。
    return f'{value if value else ZERO:.2f}'


class LineInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    code: str = Field(pattern=r'^[A-Z][A-Z0-9_]{0,31}$')
    name: str = Field(min_length=1, max_length=80)
    group: Literal['asset', 'liability', 'equity', 'revenue', 'expense']

    @field_validator('name')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('报表项目名称不能为空')
        return value.strip()


class AllocationInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    account_id: int = Field(gt=0, strict=True)
    line_code: str


class PolicyInput(ReasonInput):
    version: int = Field(ge=0, strict=True)
    lines: list[LineInput] = Field(min_length=1, max_length=1000)
    allocations: list[AllocationInput] = Field(max_length=10000)
    manual_transfer_ids: list[int] = Field(default_factory=list, max_length=10000)

    @field_validator('manual_transfer_ids', mode='before')
    @classmethod
    def ids(cls, value):
        if not isinstance(value, list) or any(type(item) is not int or item <= 0 for item in value):
            raise ValueError('手工结转凭证须为正整数编号')
        if len(set(value)) != len(value):
            raise ValueError('手工结转凭证不能重复')
        return sorted(value)

    @model_validator(mode='after')
    def unique(self):
        if len({item.code for item in self.lines}) != len(self.lines):
            raise ValueError('报表项目编码不能重复')
        if len({item.account_id for item in self.allocations}) != len(self.allocations):
            raise ValueError('同一科目只能归属一个报表项目')
        return self


class QueryInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    from_date: str
    to_date: str

    _dates = field_validator('from_date', 'to_date')(PeriodInput.valid_date.__func__)

    @model_validator(mode='after')
    def order(self):
        if self.to_date < self.from_date:
            raise ValueError('结束日期不能早于开始日期')
        return self


class ArchiveInput(QueryInput, ReasonInput):
    policy_version: int = Field(gt=0, strict=True)
    fingerprint: str = Field(pattern=r'^[0-9a-f]{64}$')


def policy_data(record: FinancialStatementPolicy | None) -> dict:
    return (dict(version=record.version, **json.loads(record.configuration_json)) if record
        else dict(version=0, lines=[], allocations=[], manual_transfer_ids=[]))


def validate_mapping(db: Session, data: dict) -> None:
    groups = {item['code']: item['group'] for item in data['lines']}
    allowed = dict(asset={'asset'}, liability={'liability'}, equity={'equity'},
        income={'revenue'}, expense={'expense'}, cost={'asset', 'expense'})
    for item in data['allocations']:
        account = db.get(LedgerAccount, item['account_id'])
        if account is None or item['line_code'] not in groups:
            raise HTTPException(409, '科目或报表项目不存在，请刷新配置')
        if groups[item['line_code']] not in allowed[account.category]:
            raise HTTPException(409, f'科目 {account.code} 类别与报表项目不一致；成本须明确归入在制资产或损益费用')
    for identifier in data['manual_transfer_ids']:
        record = db.get(Journal, identifier)
        if record is None or record.status != 'posted' or record.reversal_of_id is not None:
            raise HTTPException(409, '手工结转须选择已过账原始凭证')
        if db.scalar(select(BusinessJournalSource.id).where(BusinessJournalSource.journal_id == identifier)):
            raise HTTPException(409, '业务来源凭证不能标为手工结转')
        if db.scalar(select(ProfitTransfer.id).where(ProfitTransfer.journal_id == identifier)):
            raise HTTPException(409, '系统损益结转自动识别，不需手工登记')
        accounts = list(db.scalars(select(LedgerAccount).join(JournalLine, JournalLine.account_id == LedgerAccount.id)
            .where(JournalLine.journal_id == identifier)))
        if not any(a.category in ('income', 'expense', 'cost') for a in accounts) or not any(a.category == 'equity' for a in accounts):
            raise HTTPException(409, '手工结转须包含损益及权益科目')
        if any(a.category not in ('income', 'expense', 'cost', 'equity') for a in accounts):
            raise HTTPException(409, '混合资产或负债业务不能标为手工结转')
        if any(a.category == 'cost' and groups.get(next((item['line_code'] for item in data['allocations']
                if item['account_id'] == a.id), '')) != 'expense' for a in accounts):
            raise HTTPException(409, '手工结转的成本科目须归入报表损益费用，不能排除在制资产发生额')


@router.get('/options')
def options(_: dict = Depends(require('financial_statement.view'))) -> dict:
    with orm_session() as db:
        return dict(policy=policy_data(db.get(FinancialStatementPolicy, 1)),
            accounts=[{**model_data(item), 'is_active': bool(item.is_active)} for item in db.scalars(select(LedgerAccount).order_by(LedgerAccount.code))],
            periods=[snapshot(item) for item in db.scalars(select(AccountingPeriod).order_by(AccountingPeriod.start_date))],
            groups=GROUPS)


@router.put('/policy')
def save_policy(data: PolicyInput, user: dict = Depends(require('financial_statement.configure'))) -> dict:
    with orm_session(write=True) as db:
        record = db.get(FinancialStatementPolicy, 1)
        before = policy_data(record)
        if data.version != before['version']:
            raise HTTPException(409, '报表配置已变化，请刷新核对')
        configuration = data.model_dump(exclude={'version', 'reason'})
        configuration['allocations'].sort(key=lambda item: item['account_id'])
        validate_mapping(db, configuration)
        if record and configuration == json.loads(record.configuration_json):
            raise HTTPException(409, '报表配置没有变化')
        if record:
            record.version += 1
            record.configuration_json = encoded(configuration)
            record.changed_by = user['id']
        else:
            record = add_model(db, FinancialStatementPolicy(id=1, configuration_json=encoded(configuration),
                version=1, changed_by=user['id']))
        db.flush()
        add_model(db, FinancialStatementPolicyChange(before_json=encoded(before),
            after_json=encoded(policy_data(record)), reason=data.reason, changed_by=user['id']))
        return policy_data(record)


@router.get('/policy/changes')
def history(_: dict = Depends(require('financial_statement.view'))) -> list[dict]:
    with orm_session() as db:
        return [dict(**model_data(item), before=json.loads(item.before_json), after=json.loads(item.after_json),
            changed_by_name=username) for item, username in db.execute(select(FinancialStatementPolicyChange, User.username)
            .join(User, User.id == FinancialStatementPolicyChange.changed_by).order_by(FinancialStatementPolicyChange.id.desc()))]


def report(db: Session, filters: QueryInput) -> dict:
    policy = policy_data(db.get(FinancialStatementPolicy, 1))
    if not policy['version']:
        raise HTTPException(409, '须先配置公司报表项目和科目对应关系')
    validate_mapping(db, policy)
    opening = active_opening(db)
    if opening and opening.status != 'confirmed':
        raise HTTPException(409, '正式期初尚未确认，不能生成财务报表')
    if opening and filters.from_date < opening.effective_date:
        raise HTTPException(409, '开始日期不能早于总账启用日')
    accounts = {a.id: a for a in db.scalars(select(LedgerAccount).order_by(LedgerAccount.code))}
    allocations = {a['account_id']: a['line_code'] for a in policy['allocations']}
    groups = {a['code']: a['group'] for a in policy['lines']}
    # 系统结转及其冲销不代表营业收入/费用；手工结转由公司显式分类并审计。
    transfers = set(db.scalars(select(ProfitTransfer.journal_id))) | set(policy['manual_transfer_ids'])
    sums = {identifier: [ZERO, ZERO, ZERO] for identifier in accounts}
    sources, opening_sources = [], []
    journal_categories, journal_reversals = {}, {}
    for line in confirmed_opening_lines(db):
        amount = Decimal(line.debit) - Decimal(line.credit)
        sums[line.account_id][0] += amount
        sums[line.account_id][1] += amount
        auxiliary = snapshot_values(db, line)
        opening_sources.append(dict(**model_data(line), line_code=allocations.get(line.account_id),
            **({'auxiliary': auxiliary} if auxiliary else {})))
    pending = [dict(id=j.id, date=j.journal_date, status=j.status) for j in db.scalars(select(Journal)
        .where(Journal.journal_date <= filters.to_date, Journal.status.not_in(('posted', 'cancelled'))).order_by(Journal.id))]
    for line, journal in db.execute(select(JournalLine, Journal).join(Journal, Journal.id == JournalLine.journal_id)
            .where(Journal.status == 'posted', Journal.journal_date <= filters.to_date)
            .order_by(Journal.journal_date, Journal.id, JournalLine.position)):
        values = sums[line.account_id]
        journal_categories.setdefault(journal.id, set()).add(accounts[line.account_id].category)
        journal_reversals[journal.id] = journal.reversal_of_id
        amount = Decimal(line.debit) - Decimal(line.credit)
        values[1] += amount
        if journal.journal_date < filters.from_date:
            values[0] += amount
        excluded = journal.id in transfers or journal.reversal_of_id in transfers
        if journal.journal_date >= filters.from_date and not excluded:
            values[2] += amount
        auxiliary = snapshot_values(db, line)
        sources.append(dict(line_id=line.id, journal_id=journal.id, journal_date=journal.journal_date,
            reference=journal.reference, reversal_of_id=journal.reversal_of_id, account_id=line.account_id,
            debit=line.debit, credit=line.credit, summary=line.summary, line_code=allocations.get(line.account_id),
            excluded_from_income=excluded,
            **({'auxiliary': auxiliary} if auxiliary else {})))
    unmapped = [dict(account_id=a.id, code=a.code, name=a.name, opening=f'{sums[a.id][0]:.2f}',
        closing=f'{sums[a.id][1]:.2f}', movement=f'{sums[a.id][2]:.2f}') for a in accounts.values()
        if a.id not in allocations and any(sums[a.id])]
    balance_rows, income_rows, contributions = [], [], []
    totals = {group: [ZERO, ZERO] for group in GROUPS}
    for definition in policy['lines']:
        group, code = definition['group'], definition['code']
        members = [identifier for identifier, target in allocations.items() if target == code]
        sign = Decimal(-1) if group in ('liability', 'equity', 'revenue') else Decimal(1)
        before = sum((sums[a][0] * sign for a in members), ZERO)
        end = sum((sums[a][1 if group in ('asset', 'liability', 'equity') else 2] * sign for a in members), ZERO)
        totals[group][0] += before
        totals[group][1] += end
        row = dict(**definition, opening=f'{before:.2f}', amount=f'{end:.2f}', account_ids=members)
        (balance_rows if group in ('asset', 'liability', 'equity') else income_rows).append(row)
        for identifier in members:
            a, values = accounts[identifier], sums[identifier]
            contributions.append(dict(account_id=a.id, code=a.code, name=a.name, line_code=code, group=group,
                opening=money(values[0] * sign), closing=money(values[1] * sign), movement=money(values[2] * sign)))
    profit_accounts = {a.id for a in accounts.values() if a.category in ('income', 'expense')}
    profit_accounts.update(identifier for identifier, code in allocations.items() if accounts[identifier].category == 'cost' and groups[code] == 'expense')
    retained = [-sum((sums[a][phase] for a in profit_accounts), ZERO) for phase in (0, 1)]
    balance_rows.append(dict(code='_UNCLOSED_PROFIT', name='未结转损益', group='equity',
        opening=f'{retained[0]:.2f}', amount=f'{retained[1]:.2f}', account_ids=sorted(profit_accounts)))
    assets, liabilities, equity = totals['asset'], totals['liability'], totals['equity']
    differences = [assets[p] - liabilities[p] - equity[p] - retained[p] for p in (0, 1)]
    net_profit = totals['revenue'][1] - totals['expense'][1]
    periods = list(db.scalars(select(AccountingPeriod).where(AccountingPeriod.start_date <= filters.to_date,
        AccountingPeriod.end_date >= filters.from_date).order_by(AccountingPeriod.start_date)))
    complete_periods = bool(periods) and periods[0].start_date == filters.from_date and periods[-1].end_date == filters.to_date
    complete_periods = complete_periods and all(date.fromisoformat(b.start_date) == date.fromisoformat(a.end_date) + timedelta(days=1)
        for a, b in zip(periods, periods[1:]))
    blockers = []
    if unmapped:
        blockers.append('有未映射且非零的科目，须先补齐报表项目')
    if any(differences):
        blockers.append('资产与负债权益核对不平，请核对期初、科目范围及损益')
    if pending:
        blockers.append('截至期末有未处理凭证，须过账或取消后归档')
    unclassified = [identifier for identifier, categories in journal_categories.items()
        if identifier not in transfers and journal_reversals[identifier] is None
        and 'equity' in categories and categories & {'income', 'expense', 'cost'}
        and categories <= {'income', 'expense', 'cost', 'equity'}]
    if unclassified:
        blockers.append('有仅含损益及权益的未分类凭证，须核对并明确手工结转范围')
    if not complete_periods or any(p.status != 'closed' for p in periods):
        blockers.append('归档范围须为连续、完整且均已结账的会计期间')
    transfer_policy = db.get(ProfitTransferPolicy, 1)
    if transfer_policy and filters.to_date >= transfer_policy.start_date:
        scoped_costs = {a for a in profit_accounts if accounts[a].category == 'cost'}
        if scoped_costs != set(json.loads(transfer_policy.cost_account_ids_json)):
            blockers.append('损益报表与结转的成本范围不一致，须核对公司科目配置')
    economic = dict(filters=filters.model_dump(), policy=policy, sources=sources, opening_sources=opening_sources,
        account_snapshots=[snapshot(a) for a in accounts.values() if a.id in allocations or any(sums[a.id])],
        periods=[snapshot(p) for p in periods], pending=pending, transfer_policy_version=transfer_policy.version if transfer_policy else 0)
    fingerprint = hashlib.sha256(encoded(economic).encode()).hexdigest()
    summary = dict(assets=f'{assets[1]:.2f}', liabilities=f'{liabilities[1]:.2f}', equity=f'{equity[1]+retained[1]:.2f}',
        unclosed_profit=f'{retained[1]:.2f}', opening_difference=f'{differences[0]:.2f}', closing_difference=f'{differences[1]:.2f}',
        revenue=f'{totals["revenue"][1]:.2f}', expense=f'{totals["expense"][1]:.2f}', net_profit=f'{net_profit:.2f}')
    result = dict(**economic, fingerprint=fingerprint, policy_version=policy['version'], balance_rows=balance_rows,
        income_rows=income_rows, contributions=contributions, unmapped=unmapped, totals=summary,
        can_archive=not blockers, blockers=blockers, unclassified_transfers=unclassified, currency='CNY', time_basis='UTC',
        opening_balance_id=opening.id if opening else None, generated_at=datetime.now(timezone.utc).isoformat(),
        warnings=['按公司项目映射编制，不代表某套法定报表格式；不提供税额或利润分配。',
            '利润表只计本期已过账发生额，排除系统及显式分类的手工损益结转和关联冲销。',
            '资产负债表包括正式期初及截至期末已过账余额，未结转损益单列权益；负数如实保留。'])
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['公司财务报表', filters.from_date, filters.to_date, '人民币', f'配置版本 {policy["version"]}'])
    writer.writerow(['状态', '可归档' if result['can_archive'] else '核对中', csv_value('；'.join(blockers))])
    for title, rows in [('资产负债表', balance_rows), ('利润表', income_rows)]:
        writer.writerow([title, '项目编码', '项目名称', '期初余额（元）' if title == '资产负债表' else '', '金额（元）'])
        for row in rows:
            writer.writerow([GROUPS[row['group']], row['code'], csv_value(row['name']), row['opening'] if title == '资产负债表' else '', row['amount']])
    writer.writerow(['本期净利润', summary['net_profit']])
    result['csv'] = '\ufeff' + output.getvalue()
    return result


@router.post('/query')
def query(filters: QueryInput, _: dict = Depends(require('financial_statement.view'))) -> dict:
    with orm_session() as db:
        return report(db, filters)


@router.post('/archive', status_code=201)
def archive(data: ArchiveInput, user: dict = Depends(require('financial_statement.archive'))) -> dict:
    try:
        with orm_session(write=True) as db:
            result = report(db, QueryInput(from_date=data.from_date, to_date=data.to_date))
            if data.policy_version != result['policy_version'] or data.fingerprint != result['fingerprint']:
                raise HTTPException(409, '报表来源或配置已变化，请重新查询核对')
            if not result['can_archive']:
                raise HTTPException(409, '；'.join(result['blockers']))
            record = add_model(db, FinancialStatement(from_date=data.from_date, to_date=data.to_date,
                policy_version=data.policy_version, fingerprint=result['fingerprint'], snapshot_json=encoded(result),
                reason=data.reason, created_by=user['id']))
            return dict(id=record.id, snapshot=result, reason=record.reason, created_by=record.created_by, created_at=record.created_at)
    except IntegrityError:
        raise HTTPException(409, '此快照已归档，请查看归档历史') from None


@router.get('/archives')
def archives(_: dict = Depends(require('financial_statement.view'))) -> list[dict]:
    with orm_session() as db:
        return [dict(id=r.id, from_date=r.from_date, to_date=r.to_date, policy_version=r.policy_version,
            reason=r.reason, created_by=r.created_by, created_by_name=name, created_at=r.created_at)
            for r, name in db.execute(select(FinancialStatement, User.username).join(User, User.id == FinancialStatement.created_by)
                .order_by(FinancialStatement.id.desc()))]


@router.get('/archives/{identifier}')
def archive_detail(identifier: int = Path(gt=0), _: dict = Depends(require('financial_statement.view'))) -> dict:
    with orm_session() as db:
        record = db.get(FinancialStatement, identifier)
        if record is None:
            raise HTTPException(404, '财务报表归档不存在')
        return dict(id=record.id, snapshot=json.loads(record.snapshot_json), reason=record.reason,
            created_by=record.created_by, created_at=record.created_at)
