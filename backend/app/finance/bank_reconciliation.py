"""以银行流水证据勾对人工收付款；匹配及撤销均追加记录。"""

from datetime import date
from decimal import Decimal
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.access.security import require
from app.core.models import (BankAccount, BankMatch, BankMatchReversal, BankStatementLine,
    PaymentRecord, SubledgerOpeningLine, SubledgerPayment, User)
from app.core.orm import add_model, model_data, orm_session

router = APIRouter(prefix='/api/v1/finance/bank-reconciliation')


def money(value: Decimal) -> str:
    return f'{value:.2f}'


def clean(value: str, label: str, *, required: bool = True) -> str:
    result = value.strip()
    if (required and not result) or any(ord(character) < 32 for character in result):
        raise ValueError(f'{label}无效')
    return result


class AccountInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    code: str = Field(pattern=r'^[A-Z0-9][A-Z0-9_-]{0,31}$')
    name: str = Field(min_length=1, max_length=80)

    @field_validator('name')
    @classmethod
    def valid_name(cls, value: str) -> str:
        return clean(value, '账户名称')


class LineInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    transaction_id: str = Field(min_length=1, max_length=100)
    occurred_on: str
    amount: Decimal
    counterparty: str = Field(default='', max_length=120)
    note: str = Field(default='', max_length=200)

    @field_validator('transaction_id')
    @classmethod
    def valid_transaction_id(cls, value: str) -> str:
        return clean(value, '银行交易号')

    @field_validator('occurred_on')
    @classmethod
    def valid_date(cls, value: str) -> str:
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            raise ValueError('银行交易日期无效') from None
        if parsed.isoformat() != value:
            raise ValueError('银行交易日期须为 YYYY-MM-DD')
        return value

    @field_validator('amount', mode='before')
    @classmethod
    def string_amount(cls, value: object) -> object:
        if not isinstance(value, str) or not re.fullmatch(r'-?(?:0|[1-9]\d*)(?:\.\d{1,2})?', value):
            raise ValueError('银行金额须使用十进制文本')
        return value

    @field_validator('amount')
    @classmethod
    def valid_amount(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value == 0 or abs(value) > 1_000_000_000_000 or value.as_tuple().exponent < -2:
            raise ValueError('银行金额须非零、最多两位小数且不超过一万亿元')
        return value

    @field_validator('counterparty', 'note')
    @classmethod
    def valid_text(cls, value: str) -> str:
        return clean(value, '银行流水文本', required=False)


class LineBatchInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    account_id: int = Field(gt=0, strict=True)
    lines: list[LineInput] = Field(min_length=1, max_length=500)


class MatchInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    statement_line_id: int = Field(gt=0, strict=True)
    source_type: Literal['order_payment', 'subledger_payment']
    source_id: int = Field(gt=0, strict=True)
    reason: str = Field(min_length=1, max_length=200)

    @field_validator('reason')
    @classmethod
    def valid_reason(cls, value: str) -> str:
        return clean(value, '勾对依据')


class ReasonInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reason: str = Field(min_length=1, max_length=200)

    @field_validator('reason')
    @classmethod
    def valid_reason(cls, value: str) -> str:
        return clean(value, '撤销原因')


def source(db: Session, source_type: str, source_id: int) -> dict:
    if source_type == 'order_payment':
        row = db.get(PaymentRecord, source_id)
        if row is None:
            raise HTTPException(404, '收付款记录不存在')
        kind = row.kind
        label = f'{"销售" if kind == "receivable" else "采购"}订单 #{row.order_id}'
    else:
        row = db.get(SubledgerPayment, source_id)
        if row is None:
            raise HTTPException(404, '历史分户收付款不存在')
        line = db.get(SubledgerOpeningLine, row.opening_line_id)
        kind = line.kind
        label = f'历史原单 {line.document_reference}'
    # 退款和冲销在来源表中已经带负号；应付方向相对银行入账反转。
    signed = Decimal(row.amount) * (1 if kind == 'receivable' else -1)
    return dict(source_type=source_type, source_id=row.id, label=label, kind=kind,
        action=row.action, bank_amount=money(signed), reference=row.reference,
        created_at=row.created_at)


def active_matches(db: Session) -> list[BankMatch]:
    reversed_ids = set(db.scalars(select(BankMatchReversal.match_id)))
    return [item for item in db.scalars(select(BankMatch).order_by(BankMatch.id))
        if item.id not in reversed_ids]


def overview_data(db: Session) -> dict:
    users = dict(db.execute(select(User.id, User.username)).all())
    matches = list(db.scalars(select(BankMatch).order_by(BankMatch.id.desc())))
    reversals = {item.match_id: item for item in db.scalars(select(BankMatchReversal))}
    active = [item for item in matches if item.id not in reversals]
    by_line = {item.statement_line_id: item.id for item in active}
    by_source = {(item.source_type, item.source_id): item.id for item in active}
    accounts = [dict(**model_data(item), created_by_name=users.get(item.created_by))
        for item in db.scalars(select(BankAccount).order_by(BankAccount.code))]
    lines = [dict(**model_data(item), account_code=db.get(BankAccount, item.account_id).code,
        match_id=by_line.get(item.id), created_by_name=users.get(item.created_by))
        for item in db.scalars(select(BankStatementLine).order_by(BankStatementLine.id.desc()))]
    sources = [dict(**source(db, kind, item.id), match_id=by_source.get((kind, item.id)))
        for kind, model in (('order_payment', PaymentRecord), ('subledger_payment', SubledgerPayment))
        for item in db.scalars(select(model).order_by(model.id.desc()))]
    evidence = [dict(**model_data(item), created_by_name=users.get(item.created_by),
        reversal=(dict(**model_data(reversals[item.id]),
            created_by_name=users.get(reversals[item.id].created_by)) if item.id in reversals else None))
        for item in matches]
    return dict(currency='CNY', accounts=accounts, lines=lines, sources=sources, matches=evidence)


@router.get('/overview')
def overview(_: dict = Depends(require('bank_reconciliation.view'))) -> dict:
    with orm_session() as db:
        return overview_data(db)


@router.post('/accounts', status_code=201)
def create_account(data: AccountInput, user: dict = Depends(require('bank_reconciliation.account'))) -> dict:
    try:
        with orm_session(write=True) as db:
            item = add_model(db, BankAccount(code=data.code, name=data.name, created_by=user['id']))
            return dict(**model_data(item), created_by_name=user['username'])
    except IntegrityError:
        raise HTTPException(409, '银行账户编码已使用') from None


@router.post('/lines/import', status_code=201)
def import_lines(data: LineBatchInput, user: dict = Depends(require('bank_reconciliation.record'))) -> dict:
    references = [item.transaction_id for item in data.lines]
    if len(references) != len(set(references)):
        raise HTTPException(422, '同批银行交易号不能重复')
    try:
        with orm_session(write=True) as db:
            account = db.get(BankAccount, data.account_id)
            if account is None:
                raise HTTPException(404, '银行账户不存在')
            ids = []
            for line in data.lines:
                item = add_model(db, BankStatementLine(account_id=account.id,
                    transaction_id=line.transaction_id, occurred_on=line.occurred_on,
                    amount=money(line.amount), counterparty=line.counterparty, note=line.note,
                    created_by=user['id']))
                ids.append(item.id)
            return dict(account_id=account.id, line_ids=ids, imported_count=len(ids))
    except IntegrityError:
        raise HTTPException(409, '此账户的银行交易号已登记，整批未写入') from None


@router.post('/matches', status_code=201)
def match(data: MatchInput, user: dict = Depends(require('bank_reconciliation.match'))) -> dict:
    with orm_session(write=True) as db:
        line = db.get(BankStatementLine, data.statement_line_id)
        if line is None:
            raise HTTPException(404, '银行流水不存在')
        payment = source(db, data.source_type, data.source_id)
        if Decimal(line.amount) != Decimal(payment['bank_amount']):
            raise HTTPException(409, '银行收支方向或金额与收付款记录不一致')
        for item in active_matches(db):
            if item.statement_line_id == line.id or (item.source_type, item.source_id) == (data.source_type, data.source_id):
                raise HTTPException(409, '银行流水或收付款记录已有有效勾对')
        item = add_model(db, BankMatch(statement_line_id=line.id, source_type=data.source_type,
            source_id=data.source_id, reason=data.reason, created_by=user['id']))
        return model_data(item)


@router.post('/matches/{match_id}/reverse', status_code=201)
def reverse_match(data: ReasonInput, match_id: int = Path(gt=0),
                  user: dict = Depends(require('bank_reconciliation.reverse'))) -> dict:
    try:
        with orm_session(write=True) as db:
            item = db.get(BankMatch, match_id)
            if item is None:
                raise HTTPException(404, '银行勾对不存在')
            if db.scalar(select(BankMatchReversal.id).where(BankMatchReversal.match_id == match_id)):
                raise HTTPException(409, '银行勾对已撤销')
            reversal = add_model(db, BankMatchReversal(match_id=match_id, reason=data.reason,
                created_by=user['id']))
            return model_data(reversal)
    except IntegrityError:
        raise HTTPException(409, '银行勾对已撤销') from None
