"""辅助档案、科目规则及同一快照的辅助余额和逐笔来源。"""

from app.core.document_responses import NumberedRoute
import csv
import json
from datetime import datetime, timezone
from decimal import Decimal
from io import StringIO
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.access.security import require
from app.core.models import (AuxiliaryItem, AuxiliaryItemChange, AuxiliaryPolicy,
    AuxiliaryPolicyChange, AccountingPeriod, LedgerAccount, Journal, JournalLine, User)
from app.core.orm import add_model, model_data, orm_session
from app.core.period_lock import ensure_date_unlocked
from app.finance.auxiliary_rules import (Kind, LABELS, policy_data, selection_options, snapshot_values)
from app.finance.journals import ReasonInput
from app.finance.ledger import PeriodInput
from app.finance.ledger_reports import confirmed_opening_lines, sides
from app.finance.opening_rules import active_opening
from app.reports.routes import csv_value

router = APIRouter(route_class=NumberedRoute, prefix='/api/v1/finance/auxiliary')
ZERO = Decimal(0)


class ItemInput(ReasonInput):
    kind: Literal['department', 'project']
    code: str = Field(min_length=1, max_length=40, pattern=r'^[A-Za-z0-9_-]+$')
    name: str = Field(min_length=1, max_length=80)

    @field_validator('name')
    @classmethod
    def name_nonblank(cls, value):
        if not value.strip():
            raise ValueError('辅助档案名称不能为空')
        return value.strip()


class ItemUpdate(ReasonInput):
    version: int = Field(gt=0, strict=True)
    name: str = Field(min_length=1, max_length=80)
    is_active: bool = Field(strict=True)

    _name = field_validator('name')(ItemInput.name_nonblank.__func__)


class PolicyInput(ReasonInput):
    version: int = Field(ge=0, strict=True)
    start_date: str
    required_kinds: list[Kind] = Field(max_length=4)

    _date = field_validator('start_date')(PeriodInput.valid_date.__func__)

    @field_validator('required_kinds')
    @classmethod
    def unique_kinds(cls, values):
        if len(set(values)) != len(values):
            raise ValueError('必填辅助类型不能重复')
        return sorted(values)


class ReportQuery(BaseModel):
    model_config = ConfigDict(extra='forbid')
    account_id: int = Field(gt=0, strict=True)
    kind: Kind
    from_date: str
    to_date: str
    entity_id: int | None = Field(default=None, ge=0, strict=True)

    _dates = field_validator('from_date', 'to_date')(PeriodInput.valid_date.__func__)

    @model_validator(mode='after')
    def date_order(self):
        if self.from_date > self.to_date:
            raise ValueError('结束日期不能早于开始日期')
        return self


def item_data(record):
    return {**model_data(record), 'is_active': bool(record.is_active)}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


@router.get('/options')
def options(_: dict = Depends(require('auxiliary.view'))) -> dict:
    with orm_session() as db:
        return dict(**selection_options(db, include_inactive=True), kinds=LABELS,
            accounts=[{**model_data(item), 'is_active': bool(item.is_active)}
                for item in db.scalars(select(LedgerAccount).order_by(LedgerAccount.code))],
            periods=[model_data(item) for item in db.scalars(select(AccountingPeriod).order_by(AccountingPeriod.start_date))])


@router.post('/items', status_code=201)
def create_item(data: ItemInput, user: dict = Depends(require('auxiliary.manage'))) -> dict:
    try:
        with orm_session(write=True) as db:
            record = add_model(db, AuxiliaryItem(kind=data.kind, code=data.code, name=data.name,
                is_active=1, version=1, created_by=user['id']))
            result = item_data(record)
            db.add(AuxiliaryItemChange(item_id=record.id, before_json=None, after_json=encoded(result),
                reason=data.reason, changed_by=user['id']))
            db.flush()
            return result
    except IntegrityError:
        raise HTTPException(409, '同类辅助档案编码已使用') from None


@router.put('/items/{item_id}')
def update_item(data: ItemUpdate, item_id: int = Path(gt=0), user: dict = Depends(require('auxiliary.manage'))) -> dict:
    with orm_session(write=True) as db:
        record = db.get(AuxiliaryItem, item_id)
        if record is None:
            raise HTTPException(404, '辅助档案不存在')
        if record.version != data.version:
            raise HTTPException(409, '辅助档案已变化，请刷新核对')
        if record.name == data.name and bool(record.is_active) == data.is_active:
            raise HTTPException(409, '辅助档案没有变化')
        before = item_data(record)
        record.name, record.is_active, record.version = data.name, int(data.is_active), record.version + 1
        db.flush()
        after = item_data(record)
        db.add(AuxiliaryItemChange(item_id=record.id, before_json=encoded(before), after_json=encoded(after),
            reason=data.reason, changed_by=user['id']))
        db.flush()
        return after


@router.put('/policies/{account_id}')
def save_policy(data: PolicyInput, account_id: int = Path(gt=0), user: dict = Depends(require('auxiliary.configure'))) -> dict:
    with orm_session(write=True) as db:
        account = db.get(LedgerAccount, account_id)
        if account is None or not account.is_active:
            raise HTTPException(409, '辅助规则须选择已存在且启用的科目')
        record = db.scalar(select(AuxiliaryPolicy).where(AuxiliaryPolicy.account_id == account_id))
        before = policy_data(record, account_id)
        if before['version'] != data.version:
            raise HTTPException(409, '辅助规则已变化，请刷新核对')
        if record and record.start_date != data.start_date:
            raise HTTPException(409, '辅助规则启用日期保存后固定')
        if record and before['required_kinds'] == data.required_kinds:
            raise HTTPException(409, '辅助规则没有变化')
        if record is None:
            ensure_date_unlocked(db, data.start_date)
            record = add_model(db, AuxiliaryPolicy(account_id=account_id, start_date=data.start_date,
                required_kinds_json=encoded(data.required_kinds), version=1, changed_by=user['id']))
        else:
            record.required_kinds_json = encoded(data.required_kinds)
            record.version, record.changed_by = record.version + 1, user['id']
            db.flush()
        after = policy_data(record, account_id)
        db.add(AuxiliaryPolicyChange(account_id=account_id, before_json=encoded(before),
            after_json=encoded(after), reason=data.reason, changed_by=user['id']))
        db.flush()
        return after


@router.get('/changes')
def changes(_: dict = Depends(require('auxiliary.view'))) -> list[dict]:
    with orm_session() as db:
        results = []
        for category, model in (('item', AuxiliaryItemChange), ('policy', AuxiliaryPolicyChange)):
            for record, name in db.execute(select(model, User.username).join(User, User.id == model.changed_by)):
                results.append(dict(id=record.id, category=category,
                    target_id=record.item_id if category == 'item' else record.account_id,
                    before=json.loads(record.before_json) if record.before_json else None,
                    after=json.loads(record.after_json), reason=record.reason,
                    changed_by=record.changed_by, changed_by_name=name, created_at=record.created_at))
        return sorted(results, key=lambda item: (item['created_at'], item['category'], item['id']), reverse=True)


def report(db, filters: ReportQuery) -> dict:
    account = db.get(LedgerAccount, filters.account_id)
    if account is None:
        raise HTTPException(404, '科目不存在')
    opening = active_opening(db)
    if opening and opening.status != 'confirmed':
        raise HTTPException(409, '期初方案尚未确认，请先处理后再核对辅助余额')
    if opening and filters.from_date < opening.effective_date:
        raise HTTPException(409, '查询开始日期不能早于正式启用日期')
    buckets = {}

    def add(line, date, source, *, is_opening=False):
        if line.account_id != account.id:
            return
        values = snapshot_values(db, line)
        value = next((item for item in values if item['kind'] == filters.kind), None)
        identifier = value['id'] if value else 0
        if filters.entity_id is not None and filters.entity_id != identifier:
            return
        row = buckets.setdefault(identifier, dict(entity_id=identifier,
            code=value['code'] if value else '', name=value['name'] if value else '未分配',
            opening=ZERO, debit=ZERO, credit=ZERO, entries=[]))
        debit, credit = Decimal(line.debit), Decimal(line.credit)
        before = is_opening or date < filters.from_date
        if before:
            row['opening'] += debit - credit
        else:
            row['debit'], row['credit'] = row['debit'] + debit, row['credit'] + credit
        row['entries'].append(dict(**source, date=date, position=line.position, line_id=line.id,
            summary=line.summary, debit=line.debit, credit=line.credit, auxiliary=values,
            opening_contribution=before))

    for line in confirmed_opening_lines(db):
        add(line, opening.effective_date, dict(opening_balance_id=line.opening_balance_id,
            journal_id=None, reference=opening.reference, source='正式期初'), is_opening=True)
    for line, journal in db.execute(select(JournalLine, Journal).join(Journal, Journal.id == JournalLine.journal_id)
            .where(Journal.status == 'posted', Journal.journal_date <= filters.to_date,
                JournalLine.account_id == filters.account_id).order_by(Journal.journal_date, Journal.id, JournalLine.position)):
        add(line, journal.journal_date, dict(journal_id=journal.id, opening_balance_id=None,
            reference=journal.reference, reversal_of_id=journal.reversal_of_id,
            source='冲销' if journal.reversal_of_id else '已过账凭证'))
    rows = []
    totals = dict(opening_net=ZERO, debit=ZERO, credit=ZERO, closing_net=ZERO)
    for row in sorted(buckets.values(), key=lambda item: (item['entity_id'] == 0, item['code'], item['entity_id'])):
        closing = row['opening'] + row['debit'] - row['credit']
        od, oc = sides(row['opening'])
        cd, cc = sides(closing)
        rows.append(dict(entity_id=row['entity_id'], code=row['code'], name=row['name'],
            opening_debit=od, opening_credit=oc, debit=f"{row['debit']:.2f}", credit=f"{row['credit']:.2f}",
            closing_debit=cd, closing_credit=cc, entries=row['entries']))
        totals['opening_net'] += row['opening']
        totals['debit'] += row['debit']
        totals['credit'] += row['credit']
        totals['closing_net'] += closing
    columns = [('code', '辅助编码'), ('name', '辅助名称'), ('opening_debit', '期初借方'),
        ('opening_credit', '期初贷方'), ('debit', '本期借方'), ('credit', '本期贷方'),
        ('closing_debit', '期末借方'), ('closing_credit', '期末贷方')]
    generated_at = datetime.now(timezone.utc).isoformat()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['辅助余额', csv_value(account.code), csv_value(account.name), LABELS[filters.kind],
        filters.from_date, filters.to_date, generated_at, '人民币；已确认期初及已过账；未分配不推断历史归属'])
    writer.writerow([label for _, label in columns])
    for row in rows:
        writer.writerow([csv_value(row[key]) for key, _ in columns])
    writer.writerow(['合计净额（借方为正）', '期初', f"{totals['opening_net']:.2f}",
        '本期借方', f"{totals['debit']:.2f}", '本期贷方', f"{totals['credit']:.2f}", '期末', f"{totals['closing_net']:.2f}"])
    return dict(filters=filters.model_dump(), account={**model_data(account), 'is_active': bool(account.is_active)},
        currency='CNY', generated_at=generated_at, rows=rows, totals={key: f'{value:.2f}' for key, value in totals.items()},
        columns=[dict(key=key, title=title) for key, title in columns], csv='\ufeff' + output.getvalue(),
        warnings=['未分配记录保留历史归属缺口；当前辅助余额不自动生成应收应付业务子账期初。',
            '辅助分组借贷余额可同时存在；与科目核对须比较带方向的净额。'])


@router.post('/query')
def query(filters: ReportQuery, _: dict = Depends(require('auxiliary.view'))) -> dict:
    with orm_session() as db:
        return report(db, filters)
