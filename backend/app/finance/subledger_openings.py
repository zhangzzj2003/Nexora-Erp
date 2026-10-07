"""历史未结单据分户启用、逐组合勾稽及追加式收付款。"""

from app.core.document_responses import NumberedRoute
import csv
import json
from datetime import datetime, timezone
from decimal import Decimal
from io import StringIO
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.access.security import current_user, require
from app.core.models import (BusinessJournalPolicy, LedgerAccount, OpeningBalance,
    OpeningBalanceLine, PaymentRecord, SubledgerOpening, SubledgerOpeningChange,
    SubledgerOpeningLine, SubledgerPayment, User)
from app.core.orm import add_model, model_data, orm_session
from app.core.period_lock import ensure_date_unlocked
from app.finance.auxiliary_rules import (AuxiliaryReference, combination,
    selection_options, snapshot_values, validate_references)
from app.finance.journals import JournalInput, JournalLineInput, ReasonInput, VersionInput
from app.finance.opening_rules import active_opening, ensure_no_posted_journals
from app.finance.subledger_rules import active_subledger, check_control_mapping, check_subledger
from app.reports.routes import csv_value

router = APIRouter(route_class=NumberedRoute, prefix='/api/v1/finance/subledger-openings')
ZERO = Decimal(0)


class ControlInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['receivable', 'payable']
    account_id: int = Field(gt=0, strict=True)


class LineInput(JournalLineInput):
    kind: Literal['receivable', 'payable']
    party_id: int = Field(gt=0, strict=True)
    document_reference: str = Field(min_length=1, max_length=80)
    document_date: str
    summary: str = '历史未结单据'

    _reference = field_validator('document_reference')(JournalInput.nonblank_reference.__func__)
    _date = field_validator('document_date')(JournalInput.valid_date.__func__)

    @field_validator('auxiliary')
    @classmethod
    def optional_dimensions(cls, values):
        if any(value.kind not in ('department', 'project') for value in values):
            raise ValueError('客户或供应商由往来对象决定，附加辅助仅支持部门与项目')
        return values


class OpeningInput(ReasonInput):
    reference: str = Field(min_length=1, max_length=80)
    opening_balance_id: int = Field(gt=0, strict=True)
    opening_version: int = Field(gt=0, strict=True)
    control_accounts: list[ControlInput] = Field(min_length=1, max_length=2)
    lines: list[LineInput] = Field(max_length=500)
    note: str = Field(default='', max_length=500)
    _reference = field_validator('reference')(JournalInput.nonblank_reference.__func__)

    @model_validator(mode='after')
    def unique_sources(self):
        if len({item.kind for item in self.control_accounts}) != len(self.control_accounts) or len(
                {item.account_id for item in self.control_accounts}) != len(self.control_accounts):
            raise ValueError('每类往来只选一个控制科目，两个类别不能共用科目')
        # 同一原始单据不能通过换科目或辅助组合重复导入。
        keys = [(line.kind, line.party_id, line.document_reference) for line in self.lines]
        if len(set(keys)) != len(keys):
            raise ValueError('同一往来对象的原始单据编号不能重复')
        return self


class OpeningUpdate(OpeningInput):
    version: int = Field(gt=0, strict=True)


class PaymentInput(ReasonInput):
    action: Literal['settlement', 'refund']
    amount: str
    reference: str = Field(min_length=1, max_length=80)
    _amount = field_validator('amount')(JournalLineInput.valid_amount.__func__)
    _reference = field_validator('reference')(JournalInput.nonblank_reference.__func__)

    @field_validator('amount')
    @classmethod
    def positive(cls, value):
        if Decimal(value) <= 0:
            raise ValueError('收付款金额须大于零')
        return value


class BalanceQuery(BaseModel):
    model_config = ConfigDict(extra='forbid')
    to_date: str
    kind: Literal['receivable', 'payable'] | None = None
    party_id: int | None = Field(default=None, gt=0, strict=True)
    _date = field_validator('to_date')(JournalInput.valid_date.__func__)

    @model_validator(mode='after')
    def party_scope(self):
        if self.party_id is not None and self.kind is None:
            raise ValueError('指定往来对象时须同时指定往来类别')
        return self


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def get_record(db: Session, identifier: int, version: int | None = None) -> SubledgerOpening:
    record = db.get(SubledgerOpening, identifier)
    if record is None:
        raise HTTPException(404, '分户期初方案不存在')
    if version is not None and record.version != version:
        raise HTTPException(409, '分户方案已变化，请刷新核对后再操作')
    return record


def lines_for(db: Session, identifier: int) -> list[SubledgerOpeningLine]:
    return list(db.scalars(select(SubledgerOpeningLine).where(
        SubledgerOpeningLine.opening_id == identifier).order_by(SubledgerOpeningLine.position)))


def line_data(line: SubledgerOpeningLine) -> dict:
    result = model_data(line)
    result.pop('auxiliary_json')
    result['auxiliary'] = json.loads(line.auxiliary_json)
    result['party_id'] = line.customer_id if line.kind == 'receivable' else line.supplier_id
    result['party_name'] = next(item['name'] for item in result['auxiliary']
        if item['kind'] == ('customer' if line.kind == 'receivable' else 'supplier'))
    value = Decimal(line.debit) - Decimal(line.credit)
    result['opening_amount'] = f'{value if line.kind == "receivable" else -value:.2f}'
    return result


def snapshot(db: Session, record: SubledgerOpening) -> dict:
    result = model_data(record)
    result['control_accounts'] = json.loads(result.pop('control_accounts_json'))
    result['evidence'] = json.loads(result.pop('evidence_json')) if record.evidence_json else None
    result['lines'] = [line_data(line) for line in lines_for(db, record.id)]
    result['currency'] = 'CNY'
    return result


def view(db: Session, record: SubledgerOpening) -> dict:
    return dict(**snapshot(db, record), created_by_name=db.get(User, record.created_by).username,
        author_ids=list(db.scalars(select(SubledgerOpeningChange.changed_by).where(
            SubledgerOpeningChange.opening_id == record.id,
            SubledgerOpeningChange.action.in_(('create', 'update', 'submit'))).distinct())))


def audit(db: Session, record: SubledgerOpening, before: dict | None,
          action: str, reason: str, actor: int) -> None:
    db.add(SubledgerOpeningChange(opening_id=record.id, action=action,
        before_json=encode(before) if before else None, after_json=encode(snapshot(db, record)),
        reason=reason, changed_by=actor))
    db.flush()


def ensure_initial(db: Session) -> None:
    ensure_no_posted_journals(db)
    from app.finance.routes import financial_entries
    if financial_entries(db) or db.scalar(select(PaymentRecord.id).limit(1)) is not None:
        raise HTTPException(409, '已有业务往来或订单收付款，不能再导入首次分户期初，避免重复计入')


def bound_opening(db: Session, identifier: int, version: int) -> OpeningBalance:
    opening = active_opening(db)
    if opening is None or opening.id != identifier or opening.version != version or opening.status != 'confirmed':
        raise HTTPException(409, '须选择版本未变化的已确认总账期初')
    return opening


def controls(db: Session, values: list[dict]) -> dict:
    result = {}
    for item in values:
        account = db.get(LedgerAccount, item['account_id'])
        if account is None or not account.is_active or account.category not in ('asset', 'liability'):
            raise HTTPException(409, '往来控制科目须为已启用的资产或负债科目')
        result[item['kind']] = account
    policy = db.get(BusinessJournalPolicy, 1)
    mapping = json.loads(policy.mapping_json) if policy else {}
    if any(kind in mapping and mapping[kind] != account.id for kind, account in result.items()):
        raise HTTPException(409, '往来控制科目须与已有业务凭证科目配置一致')
    return result


def save_lines(db: Session, record: SubledgerOpening, values: list[LineInput]) -> None:
    mapping = controls(db, json.loads(record.control_accounts_json))
    for position, value in enumerate(values, 1):
        account = mapping.get(value.kind)
        if account is None or account.id != value.account_id:
            raise HTTPException(409, '分户明细须使用所属类别的控制科目')
        if value.document_date >= record.effective_date:
            raise HTTPException(409, '历史未结单据日期须早于总账启用日')
        kind = 'customer' if value.kind == 'receivable' else 'supplier'
        references = [AuxiliaryReference(kind=kind, id=value.party_id), *value.auxiliary]
        auxiliary = validate_references(db, account.id, record.effective_date, references)
        db.add(SubledgerOpeningLine(opening_id=record.id, position=position, kind=value.kind,
            account_id=account.id, account_code=account.code, account_name=account.name,
            customer_id=value.party_id if kind == 'customer' else None,
            supplier_id=value.party_id if kind == 'supplier' else None,
            document_reference=value.document_reference, document_date=value.document_date,
            debit=value.debit, credit=value.credit, auxiliary_json=encode(auxiliary)))
    db.flush()


def reconcile(db: Session, record: SubledgerOpening) -> dict:
    bound_opening(db, record.opening_balance_id, record.opening_version)
    mapping = controls(db, json.loads(record.control_accounts_json))
    actual, expected, labels = {}, {}, {}
    identifiers = {account.id for account in mapping.values()}
    for line in db.scalars(select(OpeningBalanceLine).where(
            OpeningBalanceLine.opening_balance_id == record.opening_balance_id,
            OpeningBalanceLine.account_id.in_(identifiers))):
        values = snapshot_values(db, line)
        key = (line.account_id, combination(values))
        expected[key] = expected.get(key, ZERO) + Decimal(line.debit) - Decimal(line.credit)
        labels[key] = values
    for line in lines_for(db, record.id):
        values = json.loads(line.auxiliary_json)
        key = (line.account_id, combination(values))
        actual[key] = actual.get(key, ZERO) + Decimal(line.debit) - Decimal(line.credit)
        labels.setdefault(key, values)
    rows = [dict(account_id=key[0], auxiliary=labels[key], ledger_amount=f'{expected.get(key, ZERO):.2f}',
        subledger_amount=f'{actual.get(key, ZERO):.2f}',
        difference=f'{actual.get(key, ZERO) - expected.get(key, ZERO):.2f}')
        for key in sorted(set(actual) | set(expected))]
    return dict(opening_balance_id=record.opening_balance_id, opening_version=record.opening_version,
        effective_date=record.effective_date, currency='CNY', rows=rows,
        matched=all(Decimal(item['difference']) == 0 for item in rows))


def validate(db: Session, record: SubledgerOpening) -> dict:
    ensure_initial(db)
    ensure_date_unlocked(db, record.effective_date)
    mapping = controls(db, json.loads(record.control_accounts_json))
    for line in lines_for(db, record.id):
        values = json.loads(line.auxiliary_json)
        references = [AuxiliaryReference(kind=item['kind'], id=item['id']) for item in values]
        line.auxiliary_json = encode(validate_references(db, line.account_id, record.effective_date, references))
        line.account_name = mapping[line.kind].name
    db.flush()
    evidence = reconcile(db, record)
    if not evidence['matched']:
        raise HTTPException(409, '分户金额与总账期初的往来及完整辅助组合不一致，请逐行核对差额')
    return evidence


@router.get('')
def list_records(_: dict = Depends(require('subledger_opening.view'))) -> list[dict]:
    with orm_session() as db:
        return [view(db, row) for row in db.scalars(select(SubledgerOpening).order_by(SubledgerOpening.id.desc()))]


@router.get('/options')
def options(_: dict = Depends(require('subledger_opening.create'))) -> dict:
    with orm_session() as db:
        opening = active_opening(db)
        from app.finance.opening_balances import view as opening_view
        return dict(**selection_options(db), opening_balance=opening_view(db, opening) if opening else None,
            accounts=[{**model_data(account), 'is_active': bool(account.is_active)} for account in db.scalars(select(LedgerAccount).where(
                LedgerAccount.is_active == 1, LedgerAccount.category.in_(('asset', 'liability'))).order_by(LedgerAccount.code))])


@router.post('', status_code=201)
def create(data: OpeningInput, user: dict = Depends(require('subledger_opening.create'))) -> dict:
    try:
        with orm_session(write=True) as db:
            ensure_initial(db)
            if active_subledger(db):
                raise HTTPException(409, '已有有效分户期初方案，请先完成或取消原方案')
            opening = bound_opening(db, data.opening_balance_id, data.opening_version)
            ensure_date_unlocked(db, opening.effective_date)
            record = add_model(db, SubledgerOpening(reference=data.reference,
                opening_balance_id=opening.id, opening_version=opening.version, effective_date=opening.effective_date,
                control_accounts_json=encode([item.model_dump() for item in data.control_accounts]),
                note=data.note, status='draft', version=1, active_key=1, created_by=user['id']))
            save_lines(db, record, data.lines)
            audit(db, record, None, 'create', data.reason, user['id'])
            return view(db, record)
    except IntegrityError:
        raise HTTPException(409, '依据编号已使用或已有有效分户方案') from None


@router.put('/{record_id}')
def update(data: OpeningUpdate, record_id: int = Path(gt=0),
           user: dict = Depends(require('subledger_opening.create'))) -> dict:
    try:
        with orm_session(write=True) as db:
            record = get_record(db, record_id, data.version)
            if record.status not in ('draft', 'rejected'):
                raise HTTPException(409, '仅草稿或驳回方案可编辑')
            ensure_initial(db)
            opening = bound_opening(db, data.opening_balance_id, data.opening_version)
            ensure_date_unlocked(db, opening.effective_date)
            before = snapshot(db, record)
            record.reference, record.note = data.reference, data.note
            record.opening_balance_id, record.opening_version, record.effective_date = opening.id, opening.version, opening.effective_date
            record.control_accounts_json = encode([item.model_dump() for item in data.control_accounts])
            record.status, record.version = 'draft', record.version + 1
            record.submitted_by = record.submitted_at = record.reviewed_by = record.reviewed_at = None
            db.execute(delete(SubledgerOpeningLine).where(SubledgerOpeningLine.opening_id == record.id))
            save_lines(db, record, data.lines)
            audit(db, record, before, 'update', data.reason, user['id'])
            return view(db, record)
    except IntegrityError:
        raise HTTPException(409, '分户依据编号已使用') from None


@router.get('/{record_id}/check')
def check(record_id: int = Path(gt=0), _: dict = Depends(require('subledger_opening.view'))) -> dict:
    with orm_session() as db:
        return reconcile(db, get_record(db, record_id))


@router.get('/{record_id}/changes')
def changes(record_id: int = Path(gt=0), _: dict = Depends(require('subledger_opening.view'))) -> list[dict]:
    with orm_session() as db:
        get_record(db, record_id)
        return [dict(id=change.id, action=change.action, before=json.loads(change.before_json) if change.before_json else None,
            after=json.loads(change.after_json), reason=change.reason, changed_by=change.changed_by,
            changed_by_name=name, created_at=change.created_at) for change, name in db.execute(
                select(SubledgerOpeningChange, User.username).join(User, User.id == SubledgerOpeningChange.changed_by)
                .where(SubledgerOpeningChange.opening_id == record_id).order_by(SubledgerOpeningChange.id))]


@router.post('/{record_id}/{action}')
def transition(data: VersionInput, action: str, record_id: int = Path(gt=0), user: dict = Depends(current_user)) -> dict:
    permission = {'submit':'submit', 'approve':'review', 'reject':'review', 'confirm':'confirm',
        'cancel':'cancel', 'reverse':'reverse'}.get(action)
    if permission is None:
        raise HTTPException(404, '分户操作不存在')
    if 'subledger_opening.' + permission not in user['permissions']:
        raise HTTPException(403, '没有执行此操作的权限')
    states = {'submit':('draft','rejected'), 'approve':('submitted',), 'reject':('submitted',),
        'confirm':('approved',), 'cancel':('draft','rejected','submitted','approved'), 'reverse':('confirmed',)}
    with orm_session(write=True) as db:
        record = get_record(db, record_id, data.version)
        if record.status not in states[action]:
            raise HTTPException(409, '分户方案状态不允许此操作')
        if action in ('approve','reject') and user['id'] in view(db, record)['author_ids']:
            raise HTTPException(409, '建单、编辑或提交过方案的人不能审核，请由另一账号处理')
        before = snapshot(db, record)
        if action in ('submit','approve','confirm'):
            evidence = validate(db, record)
            if action == 'confirm':
                record.evidence_json = encode(evidence)
        if action == 'reverse':
            ensure_no_posted_journals(db)
            ensure_date_unlocked(db, record.effective_date)
            if db.scalar(select(SubledgerPayment.id).join(SubledgerOpeningLine,
                    SubledgerOpeningLine.id == SubledgerPayment.opening_line_id)
                    .where(SubledgerOpeningLine.opening_id == record.id).limit(1)) is not None:
                raise HTTPException(409, '期初已有收付款记录，即使已冲销也不能重设历史期初')
        record.status = {'submit':'submitted', 'approve':'approved', 'reject':'rejected',
            'confirm':'confirmed', 'cancel':'cancelled', 'reverse':'reversed'}[action]
        record.version += 1
        if action in ('cancel','reverse'):
            record.active_key = None
        prefix = {'submit':'submitted', 'approve':'reviewed', 'reject':'reviewed',
            'confirm':'confirmed', 'cancel':'cancelled', 'reverse':'reversed'}[action]
        setattr(record, prefix + '_by', user['id'])
        setattr(record, prefix + '_at', datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'))
        db.flush()
        audit(db, record, before, action, data.reason, user['id'])
        return view(db, record)


def payment_data(db: Session, record: SubledgerPayment) -> dict:
    line = db.get(SubledgerOpeningLine, record.opening_line_id)
    return dict(**model_data(record), kind=line.kind, account_id=line.account_id,
        party_id=line.customer_id or line.supplier_id, party_name=line_data(line)['party_name'],
        document_reference=line.document_reference, auxiliary=json.loads(line.auxiliary_json),
        currency='CNY', created_by_name=db.get(User, record.created_by).username)


def balance(db: Session, line: SubledgerOpeningLine, to_date: str | None = None) -> dict:
    statement = select(SubledgerPayment).where(SubledgerPayment.opening_line_id == line.id).order_by(SubledgerPayment.id)
    if to_date:
        statement = statement.where(SubledgerPayment.created_at < to_date + ' 24:00:00')
    payments = [payment_data(db, row) for row in db.scalars(statement)]
    settled = sum((Decimal(row['amount']) for row in payments), ZERO)
    result = line_data(line)
    return dict(**result, settled_amount=f'{settled:.2f}',
        outstanding_amount=f'{Decimal(result["opening_amount"]) - settled:.2f}', payments=payments)


@router.get('/payments')
def list_payments(_: dict = Depends(require('subledger_opening.view'))) -> list[dict]:
    with orm_session() as db:
        return [payment_data(db, row) for row in db.scalars(select(SubledgerPayment).order_by(SubledgerPayment.id.desc()))]


@router.post('/lines/{line_id}/payments', status_code=201)
def create_payment(data: PaymentInput, line_id: int = Path(gt=0),
                   user: dict = Depends(require('finance.record'))) -> dict:
    try:
        with orm_session(write=True) as db:
            check_subledger(db)
            line = db.get(SubledgerOpeningLine, line_id)
            if line is None:
                raise HTTPException(404, '分户期初明细不存在')
            if db.get(SubledgerOpening, line.opening_id).status != 'confirmed':
                raise HTTPException(409, '仅已确认方案的未结单据可以收付款')
            amount = Decimal(data.amount)
            outstanding = Decimal(balance(db, line)['outstanding_amount'])
            limit = outstanding if data.action == 'settlement' else -outstanding
            if amount > limit:
                raise HTTPException(409, '收付款超过未结金额或贷方可退余额')
            record = add_model(db, SubledgerPayment(opening_line_id=line.id, action=data.action,
                amount=f'{amount if data.action == "settlement" else -amount:.2f}',
                reference=data.reference, note=data.reason, created_by=user['id']))
            check_subledger(db, record.created_at)
            return payment_data(db, record)
    except IntegrityError:
        raise HTTPException(409, '此历史单据的收付款参考号已使用') from None


@router.post('/payments/{payment_id}/reverse', status_code=201)
def reverse_payment(data: ReasonInput, payment_id: int = Path(gt=0),
                    user: dict = Depends(require('finance.reverse'))) -> dict:
    with orm_session(write=True) as db:
        check_subledger(db)
        original = db.get(SubledgerPayment, payment_id)
        if original is None:
            raise HTTPException(404, '分户收付款不存在')
        if original.action == 'reversal' or db.scalar(select(SubledgerPayment.id).where(
                SubledgerPayment.reverses_id == original.id).limit(1)) is not None:
            raise HTTPException(409, '此登记已冲销或本身为冲销记录')
        record = add_model(db, SubledgerPayment(opening_line_id=original.opening_line_id, action='reversal',
            amount=f'{-Decimal(original.amount):.2f}', reference=f'冲销 #{original.id}', note=data.reason,
            reverses_id=original.id, created_by=user['id']))
        check_subledger(db, record.created_at)
        return payment_data(db, record)


@router.post('/query')
def query(data: BalanceQuery, _: dict = Depends(require('subledger_opening.view'))) -> dict:
    with orm_session() as db:
        record = active_subledger(db)
        check_subledger(db, data.to_date)
        rows = [] if record is None else [balance(db, line, data.to_date) for line in lines_for(db, record.id)
            if (data.kind is None or line.kind == data.kind)
            and (data.party_id is None or data.party_id == (line.customer_id or line.supplier_id))]
        totals = {kind: dict(opening_amount=f'{sum((Decimal(row["opening_amount"]) for row in rows if row["kind"] == kind), ZERO):.2f}',
            settled_amount=f'{sum((Decimal(row["settled_amount"]) for row in rows if row["kind"] == kind), ZERO):.2f}',
            outstanding_amount=f'{sum((Decimal(row["outstanding_amount"]) for row in rows if row["kind"] == kind), ZERO):.2f}')
            for kind in ('receivable','payable')}
        output = StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow(['类别','往来对象','原始单据','原单日期','科目','辅助归属','期初未结','已结净额','当前未结'])
        for row in rows:
            writer.writerow([csv_value(value) for value in (row['kind'], row['party_name'], row['document_reference'],
                row['document_date'], row['account_code'], ' / '.join(item['name'] for item in row['auxiliary']),
                row['opening_amount'], row['settled_amount'], row['outstanding_amount'])])
        return dict(currency='CNY', time_basis='UTC', to_date=data.to_date, rows=rows, totals=totals,
            opening=view(db, record) if record else None, csv=output.getvalue(),
            generated_at=datetime.now(timezone.utc).isoformat())
