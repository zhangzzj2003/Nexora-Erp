"""固定往来组合、双重独立审批与凭证过账事务内的余额转账。"""

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.access.security import current_user, require
from app.core import document_approval as approval
from app.core.document_responses import NumberedRoute
from app.core.models import (BusinessJournalPolicy, ControlBalanceTransfer, ControlBalanceTransferChange,
    Journal, LedgerAccount, PaymentRecord, SubledgerPayment, SubledgerOpening, User)
from app.core.orm import add_model, model_data, orm_session
from app.core.period_lock import ensure_date_unlocked
from app.finance.auxiliary_rules import AuxiliaryReference, combination, selection_options, snapshot_values, validate_references
from app.finance.control_balance_projection import (OriginScope, encode, executed_transfers, group_data,
    origin_key, project_origins, public_origin, public_origins, saved_origin)
from app.finance.journals import (JournalInput, JournalLineInput, ReasonInput, VersionInput,
    audit as audit_journal, lines_for, period_for, save_lines, view as journal_view)
from app.finance.order_ledger_scope import ScopeGroup, scope_key
from app.finance.subledger_rules import check_subledger

router = APIRouter(route_class=NumberedRoute, prefix='/api/v1/finance/control-transfers')


class ScopeChoice(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_type: Literal['historical', 'order']
    source_id: int = Field(gt=0, strict=True)
    account_id: int = Field(gt=0, strict=True)
    auxiliary: list[AuxiliaryReference] = Field(min_length=1, max_length=4)
    fingerprint: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')

    @field_validator('auxiliary')
    @classmethod
    def unique_kinds(cls, values):
        if len({item.kind for item in values}) != len(values):
            raise ValueError('每类辅助信息只能选择一个')
        return sorted(values, key=lambda item: item.kind)


class TransferInput(ReasonInput):
    kind: Literal['receivable', 'payable']
    operation: Literal['reclassify', 'allocate']
    business_date: str
    from_scope: ScopeChoice
    to_scope: ScopeChoice
    amount: str
    reference: str = Field(min_length=1, max_length=80)
    _date = field_validator('business_date')(JournalInput.valid_date.__func__)
    _amount = field_validator('amount')(JournalLineInput.valid_amount.__func__)
    _reference = field_validator('reference')(JournalInput.nonblank_reference.__func__)

    @field_validator('amount')
    @classmethod
    def positive(cls, value):
        if Decimal(value) <= 0:
            raise ValueError('转账金额须大于零')
        return value


class GenerateInput(VersionInput):
    reference: str = Field(min_length=1, max_length=80)
    _reference = field_validator('reference')(JournalInput.nonblank_reference.__func__)


class ReverseInput(VersionInput):
    business_date: str
    reference: str = Field(min_length=1, max_length=80)
    _date = field_validator('business_date')(JournalInput.valid_date.__func__)
    _reference = field_validator('reference')(JournalInput.nonblank_reference.__func__)


def permission(row: ControlBalanceTransfer) -> str:
    return 'control_transfer.reverse' if row.reverses_id is not None else 'control_transfer.post'


def get_record(db: Session, identifier: int, version: int | None = None) -> ControlBalanceTransfer:
    row = db.get(ControlBalanceTransfer, identifier)
    if row is None:
        raise HTTPException(404, '往来余额转账不存在')
    if version is not None and version != row.version:
        raise HTTPException(409, '转账已变化，请刷新核对后操作')
    return row


def content(row: ControlBalanceTransfer) -> dict:
    result = {name: getattr(row, name) for name in ('kind', 'party_id', 'operation', 'business_date',
        'amount', 'from_delta', 'reference', 'reason', 'reverses_id')}
    return dict(**result, from_scope=json.loads(row.from_scope_json), to_scope=json.loads(row.to_scope_json),
        evidence=json.loads(row.evidence_json), currency='CNY')


def approval_snapshot(db: Session, identifier: int) -> dict:
    row = get_record(db, identifier)
    authors = {row.created_by}
    if row.reverses_id is not None:
        original = get_record(db, row.reverses_id)
        authors.update({original.created_by, original.executed_by} - {None})
    return dict(**content(row), source_author_ids=sorted(authors))


def record_data(db: Session, row: ControlBalanceTransfer) -> dict:
    result = model_data(row)
    for key in ('from_scope_json', 'to_scope_json', 'evidence_json'):
        result.pop(key)
    journal = db.get(Journal, row.journal_id) if row.journal_id else None
    result.update(content(row), approval=approval.case_data(approval.find_case(db, 'ControlBalanceTransfer', row.id)),
        journal_status=journal.status if journal else None, created_by_name=db.get(User, row.created_by).username,
        reversal_id=db.scalar(select(ControlBalanceTransfer.id).where(ControlBalanceTransfer.reverses_id == row.id,
            ControlBalanceTransfer.status != 'cancelled')))
    return result


def audit(db: Session, row: ControlBalanceTransfer, action: str, reason: str, actor: int) -> None:
    db.add(ControlBalanceTransferChange(transfer_id=row.id, action=action,
        snapshot_json=encode(record_data(db, row)), reason=reason, changed_by=actor))
    db.flush()


def checked_date(db: Session, date: str) -> None:
    if date > datetime.now(timezone.utc).date().isoformat():
        raise HTTPException(409, '不能提前生效未来日期的余额转账')
    check_subledger(db, date)
    ensure_date_unlocked(db, date)
    period_for(db, date)


def freeze_choice(db: Session, origins: dict, kind: str, choice: ScopeChoice, date: str,
                  *, allow_new: bool = False, check_fingerprint: bool = True) -> tuple[dict, dict, Decimal]:
    origin: OriginScope | None = origins.get(origin_key(kind, choice.source_type, choice.source_id))
    if origin is None:
        raise HTTPException(409, '原单或订单没有可核对的已过账组合来源')
    if origin.blockers:
        raise HTTPException(409, '来源存在缺价、未过账或归属缺口：' + '；'.join(origin.blockers))
    partner = 'customer' if kind == 'receivable' else 'supplier'
    pairs = combination(choice.auxiliary)
    if (partner, origin.party_id) not in pairs or any(key in ('customer', 'supplier') and
            (key, identifier) != (partner, origin.party_id) for key, identifier in pairs):
        raise HTTPException(409, '完整辅助必须沿用原单实际往来对象')
    account = db.get(LedgerAccount, choice.account_id)
    if account is None or not account.is_active or account.category not in ('asset', 'liability'):
        raise HTTPException(409, '转账须使用启用的资产或负债控制科目')
    opposite = 'payable' if kind == 'receivable' else 'receivable'
    opening = db.scalar(select(SubledgerOpening).where(SubledgerOpening.active_key == 1))
    controls = json.loads(opening.control_accounts_json) if opening else []
    policy = db.get(BusinessJournalPolicy, 1)
    mapping = json.loads(policy.mapping_json) if policy else {}
    allowed = {item['account_id'] for item in controls if item['kind'] == kind} if opening else {
        group.account_id for scope in origins.values() if scope.kind == kind for group in scope.groups.values()}
    if not opening and kind in mapping:
        allowed.add(mapping[kind])
    if account.id not in allowed:
        raise HTTPException(409, '转账科目须属于对应往来类别已配置或有真实凭证证明的控制范围')
    if any(item['kind'] == opposite and item['account_id'] == account.id for item in controls) or mapping.get(opposite) == account.id:
        raise HTTPException(409, '应收与应付不能共用控制科目')
    if any(group.account_id == account.id for scope in origins.values() if scope.kind == opposite for group in scope.groups.values()):
        raise HTTPException(409, '此科目已有另一往来类别的真实控制余额，不能混用')
    group = origin.groups.get(scope_key(choice.account_id, choice.auxiliary))
    if group is None:
        if not allow_new:
            raise HTTPException(409, '所选组合没有实际余额来源')
        group = ScopeGroup(choice.account_id, validate_references(db, account.id, date, choice.auxiliary))
    else:
        validate_references(db, account.id, date, choice.auxiliary)
    public = group_data(origin, group)
    if check_fingerprint and (choice.fingerprint != public['fingerprint'] and not (
            allow_new and choice.fingerprint is None and not group.evidence and group.amount == 0)):
        raise HTTPException(409, '完整组合金额或来源已变化，请刷新后重新编制转账')
    for evidence in group.evidence:
        fact_date = evidence.get('date') or evidence.get('journal_date') or (evidence.get('executed_at') or '')[:10]
        if fact_date and fact_date > date:
            raise HTTPException(409, '转账日期不能早于所选组合已有来源或下游事实')
    saved = {key: public[key] for key in ('kind', 'source_type', 'source_id', 'party_id', 'account_id', 'auxiliary')}
    return saved, public, group.amount


def validate_limits(operation: str, source: dict, target: dict, source_amount: Decimal,
                    target_amount: Decimal, amount: Decimal) -> Decimal:
    if source['party_id'] != target['party_id']:
        raise HTTPException(409, '转账双方须为同一真实往来对象')
    if scope_key(source['account_id'], source['auxiliary']) == scope_key(target['account_id'], target['auxiliary']):
        raise HTTPException(409, '双方控制科目和完整辅助组合相同，请使用同组合核销')
    if operation == 'reclassify':
        if saved_origin(source) != saved_origin(target):
            raise HTTPException(409, '余额重分类须保留同一原单或订单身份')
        if not source_amount or amount > abs(source_amount):
            raise HTTPException(409, '重分类超过来源组合实际借方或贷方余额')
        return -amount if source_amount > 0 else amount
    if saved_origin(source) == saved_origin(target):
        raise HTTPException(409, '同一原单不同组合请使用余额重分类')
    if source_amount >= 0 or target_amount <= 0 or amount > min(-source_amount, target_amount):
        raise HTTPException(409, '贷方分配超过来源组合贷方或目标组合借方余额')
    return amount


def choice_from_saved(saved: dict) -> ScopeChoice:
    return ScopeChoice(source_type=saved['source_type'], source_id=saved['source_id'], account_id=saved['account_id'],
        auxiliary=[AuxiliaryReference(kind=item['kind'], id=item['id']) for item in saved['auxiliary']])


def active_transfers(db: Session) -> list[ControlBalanceTransfer]:
    rows = executed_transfers(db)
    reversed_ids = {row.reverses_id for row in rows if row.reverses_id is not None}
    return [row for row in rows if row.reverses_id is None and row.id not in reversed_ids]


def validate_reversal(db: Session, row: ControlBalanceTransfer) -> None:
    original = get_record(db, row.reverses_id)
    if original.status != 'executed' or original.reverses_id is not None:
        raise HTTPException(409, '只能更正已生效的原始转账')
    ensure_date_unlocked(db, original.business_date)
    if row.business_date < original.business_date or (row.from_scope_json, row.to_scope_json,
            row.from_delta, row.amount, row.kind, row.party_id, row.operation) != (
            original.from_scope_json, original.to_scope_json, f'{-Decimal(original.from_delta):.2f}',
            original.amount, original.kind, original.party_id, original.operation):
        raise HTTPException(409, '更正日期、身份、组合或反向金额与原转账不一致')
    if db.scalar(select(ControlBalanceTransfer.id).where(ControlBalanceTransfer.reverses_id == original.id,
            ControlBalanceTransfer.status != 'cancelled', ControlBalanceTransfer.id != row.id)):
        raise HTTPException(409, '原转账已有有效更正草稿或记录')
    for later in active_transfers(db):
        if later.id != original.id and original.id in dependencies(json.loads(later.evidence_json)):
            raise HTTPException(409, '原转账已有下游余额转账，请先倒序更正')
    for model in (PaymentRecord, SubledgerPayment):
        reversed_ids = set(db.scalars(select(model.reverses_id).where(model.status == 'executed', model.reverses_id.is_not(None))))
        for payment in db.scalars(select(model).where(model.status == 'executed', model.reverses_id.is_(None), model.control_scope_json.is_not(None))):
            if payment.id not in reversed_ids and original.id in dependencies(json.loads(payment.control_scope_json)):
                raise HTTPException(409, '原转账已有下游收付款，请先冲销资金及其凭证')
    origins = project_origins(db)
    for saved in (json.loads(original.from_scope_json), json.loads(original.to_scope_json)):
        origin = origins.get(saved_origin(saved))
        if origin is None or origin.blockers:
            raise HTTPException(409, '原转账组合存在未过账或无法核对的下游来源，须先完成凭证更正')


def dependencies(value) -> set[int]:
    if isinstance(value, dict):
        found = {value['transfer_id']} if value.get('type') == 'control_transfer' else set()
        for child in value.values():
            found.update(dependencies(child))
        return found
    if isinstance(value, list):
        return set().union(*(dependencies(child) for child in value)) if value else set()
    return set()


def validate_transfer(db: Session, row: ControlBalanceTransfer) -> None:
    checked_date(db, row.business_date)
    if row.status != 'draft':
        raise HTTPException(409, '只有未生效的转账草稿可继续办理')
    if row.reverses_id is not None:
        validate_reversal(db, row)
        return
    origins = project_origins(db)
    evidence = json.loads(row.evidence_json)
    values = []
    for name, saved in (('source', json.loads(row.from_scope_json)), ('target', json.loads(row.to_scope_json))):
        choice = choice_from_saved(saved)
        fixed, current, amount = freeze_choice(db, origins, row.kind, choice, row.business_date,
            allow_new=name == 'target' and row.operation == 'reclassify', check_fingerprint=False)
        if current['fingerprint'] != evidence[name]['fingerprint']:
            raise HTTPException(409, '转账依据或额度已变化，须取消草稿并重新编制、审批')
        if saved_origin(fixed) != saved_origin(saved) or fixed['party_id'] != row.party_id:
            raise HTTPException(409, '转账往来来源身份已变化')
        values.append(amount)
    delta = validate_limits(row.operation, json.loads(row.from_scope_json), json.loads(row.to_scope_json),
        values[0], values[1], Decimal(row.amount))
    if f'{delta:.2f}' != row.from_delta:
        raise HTTPException(409, '真实余额方向与固定转账不一致')


@router.get('')
def list_transfers(_: dict = Depends(require('control_transfer.view'))) -> list[dict]:
    with orm_session() as db:
        actor = approval.actor(db, _['id'], 'control_transfer.view')
        def visible(row):
            return all(('subledger_opening.view' if saved['source_type'] == 'historical' else 'finance.view')
                in actor['permissions'] for saved in (json.loads(row.from_scope_json), json.loads(row.to_scope_json)))
        return [record_data(db, row) for row in db.scalars(select(ControlBalanceTransfer).order_by(ControlBalanceTransfer.id.desc())) if visible(row)]


@router.get('/options')
def options(user: dict = Depends(require('control_transfer.view'))) -> dict:
    with orm_session() as db:
        actor = approval.actor(db, user['id'], 'control_transfer.view')
        # 独立页面查看权不能扩大历史原单或现有订单的查看范围。
        origins = public_origins(db)
        opening = db.scalar(select(SubledgerOpening).where(SubledgerOpening.active_key == 1))
        policy = db.get(BusinessJournalPolicy, 1)
        mapping = json.loads(policy.mapping_json) if policy else {}
        registered = json.loads(opening.control_accounts_json) if opening else []
        controls = registered if opening else [dict(kind=kind, account_id=identifier) for kind in ('receivable', 'payable')
            for identifier in sorted({group['account_id'] for origin in origins if origin['kind'] == kind for group in origin['groups']}
                | ({mapping[kind]} if kind in mapping else set()))]
        origins = [row for row in origins if ('subledger_opening.view' if row['source_type'] == 'historical'
            else 'finance.view') in actor['permissions']]
        partners = {('customer' if row['kind'] == 'receivable' else 'supplier', row['party_id']) for row in origins}
        auxiliary = selection_options(db)
        auxiliary['auxiliary_items'] = [item for item in auxiliary['auxiliary_items'] if
            item['kind'] not in ('customer', 'supplier') or (item['kind'], item['id']) in partners]
        return dict(currency='CNY', origins=origins, control_accounts=controls, **auxiliary, accounts=[model_data(row)
            for row in db.scalars(select(LedgerAccount).where(LedgerAccount.is_active == 1,
                LedgerAccount.category.in_(('asset', 'liability'))).order_by(LedgerAccount.code))])


@router.get('/funds-options')
def funds_options(kind: Literal['receivable', 'payable'], source_type: Literal['historical', 'order'],
                  source_id: int = Query(gt=0), user: dict = Depends(require('finance.record'))) -> dict:
    from app.finance.control_balance_funds import touched_origin
    with orm_session() as db:
        approval.actor(db, user['id'], 'finance.record')
        require_origin_view(db, user['id'], dict(source_type=source_type))
        key = origin_key(kind, source_type, source_id)
        required = touched_origin(db, key)
        try:
            origin = project_origins(db, for_funds=True).get(key)
        except HTTPException as error:
            if required or error.status_code != 409:
                raise
            # 未使用转账的旧业务保留原流程；不补造未配置的组合依据。
            return dict(required=False, origin=None, currency='CNY', accounts=[])
        identifiers = {part.account_id for part in origin.groups.values()} if origin else set()
        accounts = [dict(id=row.id, code=row.code, name=row.name) for row in db.scalars(
            select(LedgerAccount).where(LedgerAccount.id.in_(identifiers)).order_by(LedgerAccount.code))]
        return dict(required=required, origin=public_origin(origin) if origin else None, currency='CNY', accounts=accounts)


@router.get('/balances')
def balances(to_date: str = Query(pattern=r'^\d{4}-\d{2}-\d{2}$'),
             user: dict = Depends(require('control_transfer.view'))) -> dict:
    try:
        date = JournalInput.valid_date(to_date)
    except ValueError:
        raise HTTPException(422, '截止日须为有效日期') from None
    if date > datetime.now(timezone.utc).date().isoformat():
        raise HTTPException(422, '截止日不能晚于当日')
    with orm_session() as db:
        actor = approval.actor(db, user['id'], 'control_transfer.view')
        rows = [row for row in public_origins(db, date) if ('subledger_opening.view'
            if row['source_type'] == 'historical' else 'finance.view') in actor['permissions']]
        return dict(to_date=date, currency='CNY', time_basis='UTC', origins=rows)


@router.get('/{identifier}')
def detail(identifier: int = Path(gt=0), user: dict = Depends(require('control_transfer.view'))) -> dict:
    with orm_session() as db:
        approval.actor(db, user['id'], 'control_transfer.view')
        row = get_record(db, identifier)
        for saved in (json.loads(row.from_scope_json), json.loads(row.to_scope_json)):
            require_origin_view(db, user['id'], saved)
        return record_data(db, row)


def require_origin_view(db: Session, actor_id: int, saved: dict) -> None:
    approval.actor(db, actor_id, 'subledger_opening.view' if saved['source_type'] == 'historical' else 'finance.view')


@router.post('', status_code=201)
def create(data: TransferInput, user: dict = Depends(require('control_transfer.create'))) -> dict:
    try:
        with orm_session(write=True) as db:
            approval.actor(db, user['id'], 'control_transfer.create')
            for choice in (data.from_scope, data.to_scope):
                require_origin_view(db, user['id'], dict(source_type=choice.source_type))
            checked_date(db, data.business_date)
            origins = project_origins(db)
            source, source_proof, source_amount = freeze_choice(db, origins, data.kind, data.from_scope, data.business_date)
            target, target_proof, target_amount = freeze_choice(db, origins, data.kind, data.to_scope, data.business_date,
                allow_new=data.operation == 'reclassify')
            for saved in (source, target):
                require_origin_view(db, user['id'], saved)
            delta = validate_limits(data.operation, source, target, source_amount, target_amount, Decimal(data.amount))
            row = add_model(db, ControlBalanceTransfer(kind=data.kind, party_id=source['party_id'], operation=data.operation,
                business_date=data.business_date, from_scope_json=encode(source), to_scope_json=encode(target),
                evidence_json=encode(dict(source=source_proof, target=target_proof)), amount=data.amount,
                from_delta=f'{delta:.2f}', reference=data.reference, reason=data.reason, created_by=user['id'], status='draft'))
            audit(db, row, 'create', data.reason, user['id'])
            return record_data(db, row)
    except IntegrityError:
        raise HTTPException(409, '转账参考号已使用') from None


@router.post('/{identifier}/generate', status_code=201)
def generate(data: GenerateInput, identifier: int = Path(gt=0),
             user: dict = Depends(current_user)) -> dict:
    try:
        with orm_session(write=True) as db:
            row = get_record(db, identifier, data.version)
            actor_permission = permission(row)
            approval.actor(db, user['id'], actor_permission)
            approval.actor(db, user['id'], 'journal.create')
            for saved in (json.loads(row.from_scope_json), json.loads(row.to_scope_json)):
                require_origin_view(db, user['id'], saved)
            approval.require_approved(db, 'ControlBalanceTransfer', row.id, approval_snapshot(db, row.id),
                user['id'], permission=actor_permission)
            validate_transfer(db, row)
            previous = db.get(Journal, row.journal_id) if row.journal_id else None
            if previous and previous.status != 'cancelled':
                raise HTTPException(409, '转账已有有效凭证，请继续办理该凭证')
            period = period_for(db, row.business_date)
            original = get_record(db, row.reverses_id) if row.reverses_id else None
            journal = add_model(db, Journal(reference=data.reference, journal_date=row.business_date,
                period_id=period.id, note=data.reason, created_by=user['id'], status='draft', version=1,
                reversal_of_id=original.journal_id if original else None))
            specs, frozen = [], []
            delta = Decimal(row.from_delta) * (1 if row.kind == 'receivable' else -1)
            for saved, sign in ((json.loads(row.from_scope_json), 1), (json.loads(row.to_scope_json), -1)):
                value = delta * sign
                specs.append(JournalLineInput(account_id=saved['account_id'], summary=f'往来余额转账 #{row.id}',
                    debit=f'{max(value, Decimal(0)):.2f}', credit=f'{max(-value, Decimal(0)):.2f}',
                    auxiliary=[AuxiliaryReference(kind=item['kind'], id=item['id']) for item in saved['auxiliary']]))
                frozen.append(saved['auxiliary'])
            save_lines(db, journal, specs, frozen_auxiliary=frozen)
            row.journal_id, row.version = journal.id, row.version + 1
            db.flush()
            audit_journal(db, journal, None, 'create', data.reason, user['id'])
            audit(db, row, 'generate', data.reason, user['id'])
            return dict(transfer=record_data(db, row), journal=journal_view(db, journal))
    except IntegrityError:
        raise HTTPException(409, '凭证参考号或反向关联已使用') from None


@router.post('/{identifier}/reverse', status_code=201)
def reverse(data: ReverseInput, identifier: int = Path(gt=0),
            user: dict = Depends(require('control_transfer.reverse'))) -> dict:
    try:
        with orm_session(write=True) as db:
            approval.actor(db, user['id'], 'control_transfer.reverse')
            original = get_record(db, identifier, data.version)
            for saved in (json.loads(original.from_scope_json), json.loads(original.to_scope_json)):
                require_origin_view(db, user['id'], saved)
            checked_date(db, data.business_date)
            row = ControlBalanceTransfer(kind=original.kind, party_id=original.party_id, operation=original.operation,
                business_date=data.business_date, from_scope_json=original.from_scope_json, to_scope_json=original.to_scope_json,
                evidence_json=original.evidence_json, amount=original.amount, from_delta=f'{-Decimal(original.from_delta):.2f}',
                reference=data.reference, reason=data.reason, reverses_id=original.id, created_by=user['id'], status='draft')
            validate_transfer(db, row)
            add_model(db, row)
            audit(db, row, 'create', data.reason, user['id'])
            return record_data(db, row)
    except IntegrityError:
        raise HTTPException(409, '原转账已有更正记录或参考号已使用') from None


@router.post('/{identifier}/cancel')
def cancel(data: VersionInput, identifier: int = Path(gt=0),
           user: dict = Depends(current_user)) -> dict:
    with orm_session(write=True) as db:
        row = get_record(db, identifier, data.version)
        approval.actor(db, user['id'], 'control_transfer.reverse' if row.reverses_id else 'control_transfer.create')
        for saved in (json.loads(row.from_scope_json), json.loads(row.to_scope_json)):
            require_origin_view(db, user['id'], saved)
        case = approval.find_case(db, 'ControlBalanceTransfer', row.id)
        journal = db.get(Journal, row.journal_id) if row.journal_id else None
        if row.status != 'draft' or (case and case.status in ('submitted', 'approved')) or (journal and journal.status != 'cancelled'):
            raise HTTPException(409, '先撤回转账审批并取消关联凭证，才可取消未生效转账')
        row.status, row.version = 'cancelled', row.version + 1
        row.cancelled_by, row.cancelled_at, row.cancellation_reason = user['id'], approval.now(db), data.reason
        audit(db, row, 'cancel', data.reason, user['id'])
        return record_data(db, row)


@router.get('/{identifier}/changes')
def changes(identifier: int = Path(gt=0), _: dict = Depends(require('control_transfer.view'))) -> list[dict]:
    with orm_session() as db:
        row = get_record(db, identifier)
        for saved in (json.loads(row.from_scope_json), json.loads(row.to_scope_json)):
            require_origin_view(db, _['id'], saved)
        return [dict(id=row.id, action=row.action, snapshot=json.loads(row.snapshot_json), reason=row.reason,
            changed_by=row.changed_by, created_at=row.created_at) for row in db.scalars(
                select(ControlBalanceTransferChange).where(ControlBalanceTransferChange.transfer_id == identifier)
                    .order_by(ControlBalanceTransferChange.id))]


def validate_journal(db: Session, journal: Journal, *, actor_id: int | None = None) -> ControlBalanceTransfer | None:
    row = db.scalar(select(ControlBalanceTransfer).where(ControlBalanceTransfer.journal_id == journal.id))
    if row is None:
        if journal.reversal_of_id:
            protect_journal(db, journal.reversal_of_id)
        return None
    if actor_id is not None:
        approval.actor(db, actor_id, permission(row))
        for saved in (json.loads(row.from_scope_json), json.loads(row.to_scope_json)):
            require_origin_view(db, actor_id, saved)
    case = approval.find_case(db, 'ControlBalanceTransfer', row.id)
    if case is None or case.status != 'approved' or case.content_digest != approval.digest(approval_snapshot(db, row.id))[1]:
        raise HTTPException(409, '关联转账尚无当前有效批准')
    validate_transfer(db, row)
    expected_reverse = get_record(db, row.reverses_id).journal_id if row.reverses_id else None
    if journal.journal_date != row.business_date or journal.currency != 'CNY' or journal.reversal_of_id != expected_reverse:
        raise HTTPException(409, '凭证日期、币种或反向关联与固定转账不一致')
    lines = lines_for(db, journal.id)
    if len(lines) != 2:
        raise HTTPException(409, '转账凭证须有且仅有两条固定组合分录')
    delta = Decimal(row.from_delta) * (1 if row.kind == 'receivable' else -1)
    for line, saved, sign in zip(lines, (json.loads(row.from_scope_json), json.loads(row.to_scope_json)), (1, -1)):
        if line.account_id != saved['account_id'] or combination(snapshot_values(db, line)) != combination(saved['auxiliary']) or (
                Decimal(line.debit) - Decimal(line.credit) != delta * sign):
            raise HTTPException(409, '凭证分录与固定转账组合或金额不一致')
    return row


def authorize_journal_cancel(db: Session, journal: Journal, actor_id: int) -> None:
    row = db.scalar(select(ControlBalanceTransfer).where(ControlBalanceTransfer.journal_id == journal.id))
    if row is None:
        return
    approval.actor(db, actor_id, 'control_transfer.reverse' if row.reverses_id else 'control_transfer.create')
    for saved in (json.loads(row.from_scope_json), json.loads(row.to_scope_json)):
        require_origin_view(db, actor_id, saved)


def post_effect(db: Session, journal: Journal, row: ControlBalanceTransfer | None, actor_id: int, reason: str) -> None:
    if row is None:
        return
    case = approval.require_approved(db, 'ControlBalanceTransfer', row.id, approval_snapshot(db, row.id),
        actor_id, permission=permission(row))
    row.status, row.version = 'executed', row.version + 1
    row.executed_by, row.executed_at = actor_id, approval.now(db)
    db.flush()
    approval.mark_executed(db, case, actor_id, permission=permission(row), reason=reason)
    audit(db, row, 'post', reason, actor_id)


def protect_journal(db: Session, identifier: int) -> None:
    for row in active_transfers(db):
        if row.journal_id == identifier:
            raise HTTPException(409, '转账凭证须从原转账建立等额更正并分别审批')
        evidence = json.loads(row.evidence_json)
        if any(proof.get('journal_id') == identifier for side in ('source', 'target') for proof in evidence[side]['evidence']):
            raise HTTPException(409, '凭证已成为生效余额转账依据，请先倒序更正转账')
