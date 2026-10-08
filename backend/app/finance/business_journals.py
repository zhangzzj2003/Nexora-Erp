"""可配置科目、来源快照和去重约束的业务凭证草稿。"""

from app.core.document_responses import NumberedRoute
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.access.security import require
from app.core.models import (BusinessJournalPolicy, BusinessJournalPolicyChange,
    BusinessJournalSource, Journal, LedgerAccount, User)
from app.core.models import SalesOrder, PurchaseOrder
from app.core.orm import add_model, model_data, orm_session
from app.core.period_lock import ensure_date_unlocked
from app.finance.business_sources import ROLE_LABELS, business_sources, encoded
from app.finance.journals import (JournalInput, JournalLineInput, ReasonInput, audit,
    period_for, save_lines, view)
from app.finance.ledger import PeriodInput
from app.finance.auxiliary_rules import AuxiliaryReference, selection_options
from app.finance.subledger_rules import check_control_mapping

router = APIRouter(route_class=NumberedRoute, prefix='/api/v1/finance/business-journals')


class PolicyInput(ReasonInput):
    version: int = Field(ge=0, strict=True)
    start_date: str
    mapping: dict[str, int] = Field(min_length=1, max_length=len(ROLE_LABELS))

    _date = field_validator('start_date')(PeriodInput.valid_date.__func__)

    @field_validator('mapping', mode='before')
    @classmethod
    def valid_mapping(cls, value):
        if not isinstance(value, dict) or any(key not in ROLE_LABELS or type(identifier) is not int
                or identifier <= 0 for key, identifier in value.items()):
            raise ValueError('科目映射须使用已支持的业务用途和正整数科目编号')
        return value


class GenerateInput(ReasonInput):
    source_key: str = Field(pattern=r'^[a-z_]+:[1-9][0-9]*$', max_length=80)
    fingerprint: str = Field(pattern=r'^[0-9a-f]{64}$')
    policy_version: int = Field(gt=0, strict=True)
    reference: str = Field(min_length=1, max_length=80)
    journal_date: str
    auxiliary_by_role: dict[str, list[AuxiliaryReference]] = Field(default_factory=dict, max_length=len(ROLE_LABELS))

    @field_validator('auxiliary_by_role')
    @classmethod
    def auxiliary_roles(cls, values):
        if any(role not in ROLE_LABELS or len(items) > 4 or len({item.kind for item in items}) != len(items)
                for role, items in values.items()):
            raise ValueError('辅助配置须使用支持的业务用途，每类最多选择一个')
        return values

    _reference = field_validator('reference')(JournalInput.nonblank_reference.__func__)
    _date = field_validator('journal_date')(PeriodInput.valid_date.__func__)


def policy_data(record: BusinessJournalPolicy | None) -> dict:
    if record is None:
        return dict(version=0, start_date='', mapping={})
    return dict(version=record.version, start_date=record.start_date,
        mapping=json.loads(record.mapping_json), changed_by=record.changed_by, created_at=record.created_at)


def posted_reversal(db: Session, journal_id: int) -> Journal | None:
    return db.scalar(select(Journal).where(Journal.reversal_of_id == journal_id, Journal.status == 'posted'))


def active_bindings(db: Session) -> dict[str, tuple[BusinessJournalSource, Journal]]:
    return {source.source_key: (source, journal) for source, journal in db.execute(
        select(BusinessJournalSource, Journal).join(Journal, Journal.id == BusinessJournalSource.journal_id)
        .where(BusinessJournalSource.active_key.is_not(None))) if journal.status != 'cancelled'
        and posted_reversal(db, journal.id) is None}


def minimum_date(db: Session, source: dict) -> str:
    dates = [source['source_date']]
    for journal in db.scalars(select(Journal).join(BusinessJournalSource,
            BusinessJournalSource.journal_id == Journal.id)
            .where(BusinessJournalSource.source_key == source['key'])):
        reversal = posted_reversal(db, journal.id)
        if reversal:
            dates.append(reversal.journal_date)
    return max(dates)


def inferred_partners(db: Session, source: dict) -> list[AuxiliaryReference]:
    if source['source_type'] == 'subledger_payment':
        return [AuxiliaryReference(kind=item['kind'], id=item['id']) for item in source['records'][0]['auxiliary']]
    pairs = {(item['kind'], item['party_id']) for item in source['business']}
    if source['source_type'] == 'payment_record':
        record = source['records'][0]
        order = db.get(SalesOrder if record['kind'] == 'receivable' else PurchaseOrder, record['order_id'])
        if order:
            pairs.add((record['kind'], order.customer_id if record['kind'] == 'receivable' else order.supplier_id))
    if len(pairs) > 1:
        raise HTTPException(409, '业务来源包含不同往来对象，不能合并辅助分录')
    return [AuxiliaryReference(kind='customer' if kind == 'receivable' else 'supplier', id=identifier)
        for kind, identifier in pairs]


def source_auxiliary(db: Session, source: dict, role: str, selections: dict) -> list[AuxiliaryReference]:
    defaults = {item.kind: item for item in inferred_partners(db, source)}
    for item in selections.get(role, []):
        if source['source_type'] == 'subledger_payment' and (item.kind not in defaults or defaults[item.kind].id != item.id):
            raise HTTPException(409, '分户收付款须沿用原始未结单据的完整辅助归属')
        if item.kind in ('customer', 'supplier') and (item.kind not in defaults or defaults[item.kind].id != item.id):
            raise HTTPException(409, '辅助往来对象须与真实业务来源一致')
        defaults[item.kind] = item
    return list(defaults.values())


def source_mapping(source: dict, configured: dict) -> dict:
    mapping = dict(configured)
    if source['source_type'] == 'subledger_payment':
        # 历史资金始终结清原单科目；通用映射变化不能搬走其期初余额。
        record = source['records'][0]
        mapping[record['kind']] = record['account_id']
    return mapping


def source_rows(db: Session) -> list[dict]:
    policy = policy_data(db.get(BusinessJournalPolicy, 1))
    bindings = active_bindings(db)
    accounts = {item.id: item for item in db.scalars(select(LedgerAccount))}
    rows = []
    for item in business_sources(db).values():
        row = dict(item)
        mapping = source_mapping(item, policy['mapping'])
        blockers = list(item['blockers'])
        if not policy['version']:
            blockers.append('先配置启用日期和业务科目')
        elif item['source_date'] < policy['start_date']:
            blockers.append('来源早于业务凭证启用日期，需人工核对既有账务')
        for role in item['roles']:
            account = accounts.get(mapping.get(role))
            if account is None or not account.is_active:
                blockers.append(f'{ROLE_LABELS[role]}未配置启用科目')
        binding = bindings.get(item['key'])
        row.update(policy_version=policy['version'], blockers=blockers,
            auxiliary_defaults=[item.model_dump() for item in inferred_partners(db, item)],
            journal_id=binding[1].id if binding else None,
            journal_status=binding[1].status if binding else None,
            minimum_date=minimum_date(db, item),
            can_generate=not blockers and not binding and bool(item['roles']),
            no_amount=not item['roles'] and not item['blockers'])
        rows.append(row)
    return sorted(rows, key=lambda row: (row['source_date'], row['key']), reverse=True)


@router.get('')
def list_sources(_: dict = Depends(require('business_journal.view'))) -> list[dict]:
    with orm_session() as db:
        return source_rows(db)


@router.get('/policy')
def get_policy(_: dict = Depends(require('business_journal.view'))) -> dict:
    with orm_session() as db:
        return dict(**selection_options(db), policy=policy_data(db.get(BusinessJournalPolicy, 1)), roles=ROLE_LABELS,
            accounts=[{**model_data(item), 'is_active': bool(item.is_active)}
                for item in db.scalars(select(LedgerAccount).order_by(LedgerAccount.code))])


@router.put('/policy')
def save_policy(data: PolicyInput, user: dict = Depends(require('business_journal.configure'))) -> dict:
    with orm_session(write=True) as db:
        check_control_mapping(db, data.mapping)
        record = db.get(BusinessJournalPolicy, 1)
        before = policy_data(record)
        if data.version != before['version']:
            raise HTTPException(409, '科目配置已变化，请刷新核对后再保存')
        if record and data.start_date != record.start_date:
            raise HTTPException(409, '启用日期保存后固定，不能改写业务纳管范围')
        if record is None:
            ensure_date_unlocked(db, data.start_date)
        for identifier in data.mapping.values():
            account = db.get(LedgerAccount, identifier)
            if account is None or not account.is_active:
                raise HTTPException(409, '映射须选择已存在且启用的科目')
        if record and data.mapping == before['mapping']:
            raise HTTPException(409, '科目配置没有变化')
        if record is None:
            record = BusinessJournalPolicy(id=1, start_date=data.start_date,
                mapping_json=encoded(data.mapping), version=1, changed_by=user['id'])
            db.add(record)
        else:
            record.mapping_json, record.version, record.changed_by = encoded(data.mapping), record.version + 1, user['id']
        db.flush()
        db.add(BusinessJournalPolicyChange(before_json=encoded(before),
            after_json=encoded(policy_data(record)), reason=data.reason, changed_by=user['id']))
        db.flush()
        return policy_data(record)


@router.get('/policy/changes')
def policy_changes(_: dict = Depends(require('business_journal.view'))) -> list[dict]:
    with orm_session() as db:
        return [dict(id=record.id, before=json.loads(record.before_json) if record.before_json else None,
            after=json.loads(record.after_json), reason=record.reason, changed_by=record.changed_by,
            changed_by_name=username, created_at=record.created_at)
            for record, username in db.execute(select(BusinessJournalPolicyChange, User.username)
                .join(User, User.id == BusinessJournalPolicyChange.changed_by)
                .order_by(BusinessJournalPolicyChange.id.desc()))]


@router.post('/generate', status_code=201)
def generate(data: GenerateInput, user: dict = Depends(require('business_journal.generate'))) -> dict:
    try:
        with orm_session(write=True) as db:
            policy = db.get(BusinessJournalPolicy, 1)
            if policy is None or policy.version != data.policy_version:
                raise HTTPException(409, '科目配置已变化，请刷新来源后再生成')
            source = business_sources(db).get(data.source_key)
            if source is None:
                raise HTTPException(404, '业务来源不存在')
            if source['fingerprint'] != data.fingerprint:
                raise HTTPException(409, '来源金额或成本依据已变化，请刷新核对后再生成')
            if source['blockers'] or not source['roles'] or source['source_date'] < policy.start_date:
                raise HTTPException(409, '来源缺价、没有入账金额或早于启用日期，不能生成')
            existing = db.scalar(select(BusinessJournalSource).where(BusinessJournalSource.active_key == data.source_key))
            if existing:
                previous = db.get(Journal, existing.journal_id)
                if previous.status != 'cancelled' and posted_reversal(db, previous.id) is None:
                    raise HTTPException(409, '此来源已有未取消且未完全冲销的凭证')
                existing.active_key = None
                db.flush()
            rebuilding = any(posted_reversal(db, identifier) is not None for identifier in db.scalars(
                select(BusinessJournalSource.journal_id).where(BusinessJournalSource.source_key == data.source_key)))
            earliest = minimum_date(db, source)
            if data.journal_date < earliest or (not rebuilding and data.journal_date != source['source_date']):
                raise HTTPException(409, '首次生成按业务发生日期入账；重建不得早于已过账冲销日期')
            period = period_for(db, data.journal_date)
            mapping = source_mapping(source, json.loads(policy.mapping_json))
            if set(data.auxiliary_by_role) - set(source['roles']):
                raise HTTPException(409, '不能为当前来源未生成的业务用途填写辅助信息')
            lines = []
            for role, amount in source['roles'].items():
                account_id = mapping.get(role)
                if account_id is None:
                    raise HTTPException(409, f'{ROLE_LABELS[role]}尚未配置科目')
                positive = not amount.startswith('-')
                lines.append(JournalLineInput(account_id=account_id,
                    auxiliary=source_auxiliary(db, source, role, data.auxiliary_by_role),
                    summary=f"{source['label']} #{source['source_id']} · {ROLE_LABELS[role]}",
                    debit=amount if positive else '0', credit=amount[1:] if not positive else '0'))
            record = add_model(db, Journal(reference=data.reference, journal_date=data.journal_date,
                period_id=period.id, note=data.reason, status='draft', version=1, created_by=user['id']))
            save_lines(db, record, lines)
            add_model(db, BusinessJournalSource(journal_id=record.id, source_key=data.source_key,
                active_key=data.source_key, source_json=encoded(source), mapping_json=encoded(mapping),
                policy_version=policy.version))
            audit(db, record, None, 'create', data.reason, user['id'])
            return view(db, record)
    except IntegrityError:
        raise HTTPException(409, '来源或凭证依据已使用，请刷新核对') from None


def validate_source(db: Session, journal: Journal) -> None:
    binding = db.scalar(select(BusinessJournalSource).where(BusinessJournalSource.journal_id == journal.id))
    if binding is None:
        return
    current = business_sources(db).get(binding.source_key)
    original = json.loads(binding.source_json)
    if current is None or current['blockers'] or current['fingerprint'] != original['fingerprint']:
        raise HTTPException(409, '业务来源已变化，请取消此草稿并重新生成，不能继续审核或过账')


def release_source(db: Session, journal: Journal) -> None:
    identifier = journal.reversal_of_id if journal.status == 'posted' else journal.id
    if journal.status not in ('posted', 'cancelled') or identifier is None:
        return
    binding = db.scalar(select(BusinessJournalSource).where(BusinessJournalSource.journal_id == identifier))
    if binding and (journal.status == 'cancelled' or journal.reversal_of_id is not None):
        binding.active_key = None


def validate_posted_sources(db: Session) -> None:
    protected = [(source, journal) for source, journal in db.execute(select(BusinessJournalSource, Journal)
        .join(Journal, Journal.id == BusinessJournalSource.journal_id).where(Journal.status == 'posted'))
        if posted_reversal(db, journal.id) is None]
    if not protected:
        return
    current = business_sources(db)
    for source, journal in protected:
        previous = json.loads(source.source_json)
        actual = current.get(source.source_key)
        if actual is None or actual['fingerprint'] != previous['fingerprint']:
            raise HTTPException(409, f'变更会改写已过账业务凭证 #{journal.id} 的来源，请先独立审核过账关联冲销')


def pending_sources(db: Session, end_date: str) -> list[str]:
    policy = db.get(BusinessJournalPolicy, 1)
    if policy is None:
        return []
    bindings = active_bindings(db)
    return [source['key'] for source in business_sources(db).values()
        if policy.start_date <= source['source_date'] <= end_date
        and (source['roles'] or source['blockers'])
        and (source['key'] not in bindings or bindings[source['key']][1].status != 'posted'
             or bindings[source['key']][1].journal_date > end_date)]
