"""总账科目和会计期间基础；资料修改保留版本和前后快照。"""

from app.core.document_responses import NumberedRoute
import json
import re
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.finance.opening_rules import check_period_opening
from app.core.period_lock import ensure_date_unlocked

from app.access.security import require
from app.core.models import (
    AccountingPeriod,
    AccountingPeriodChange,
    LedgerAccount,
    LedgerAccountChange,
    User,
)
from app.core.orm import add_model, model_data, orm_session

router = APIRouter(route_class=NumberedRoute, prefix="/api/v1/finance")


class MetadataInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=200)

    @field_validator("name", "reason")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("名称和依据不能为空")
        return value.strip()


class CreateMetadata(MetadataInput):
    code: str = Field(min_length=1, max_length=32)

    @field_validator("code")
    @classmethod
    def valid_code(cls, value: str) -> str:
        value = value.strip().upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9_.-]{0,31}", value):
            raise ValueError(
                "编码须为字母或数字开头，可包含点、下划线和横线，最多 32 位"
            )
        return value


class AccountInput(CreateMetadata):
    category: Literal["asset", "liability", "equity", "income", "expense", "cost"]
    normal_balance: Literal["debit", "credit"]


class AccountUpdate(MetadataInput):
    version: int = Field(gt=0, strict=True)
    is_active: bool = Field(strict=True)


class PeriodInput(CreateMetadata):
    start_date: str
    end_date: str

    @field_validator("start_date", "end_date")
    @classmethod
    def valid_date(cls, value: str) -> str:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("日期须使用 YYYY-MM-DD 格式")
        try:
            date.fromisoformat(value)
        except ValueError:
            raise ValueError("日期不是有效的日历日期") from None
        return value

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.start_date > self.end_date:
            raise ValueError("结束日期不能早于开始日期")
        return self


class PeriodUpdate(MetadataInput):
    version: int = Field(gt=0, strict=True)


def snapshot(record: LedgerAccount | AccountingPeriod) -> dict:
    result = model_data(record)
    if isinstance(record, LedgerAccount):
        result["is_active"] = bool(record.is_active)
    return result


def audit(
    db: Session,
    record: LedgerAccount | AccountingPeriod,
    before: dict | None,
    reason: str,
    user_id: int,
) -> None:
    fields = dict(
        before_json=(
            json.dumps(before, ensure_ascii=False) if before is not None else None
        ),
        after_json=json.dumps(snapshot(record), ensure_ascii=False),
        reason=reason,
        changed_by=user_id,
    )
    change = (
        LedgerAccountChange(account_id=record.id, **fields)
        if isinstance(record, LedgerAccount)
        else AccountingPeriodChange(period_id=record.id, **fields)
    )
    # 主记录与日志一起提交，不能出现已修改但没有审计记录的资料。
    db.add(change)
    db.flush()


def get_record(db: Session, model, record_id: int, version: int | None = None):
    record = db.get(model, record_id)
    if record is None:
        raise HTTPException(404, "资料不存在")
    if version is not None and record.version != version:
        raise HTTPException(409, "资料已被其他人修改，请刷新后核对再保存")
    return record


@router.get("/ledger-accounts")
def list_accounts(_: dict = Depends(require("ledger_account.view"))) -> list[dict]:
    with orm_session() as db:
        return [
            snapshot(record)
            for record in db.scalars(select(LedgerAccount).order_by(LedgerAccount.code))
        ]


@router.post("/ledger-accounts", status_code=201)
def create_account(
    data: AccountInput, user: dict = Depends(require("ledger_account.manage"))
) -> dict:
    try:
        with orm_session(write=True) as db:
            record = add_model(
                db,
                LedgerAccount(
                    code=data.code,
                    name=data.name,
                    category=data.category,
                    normal_balance=data.normal_balance,
                    is_active=1,
                    version=1,
                    created_by=user["id"],
                ),
            )
            audit(db, record, None, data.reason, user["id"])
            return snapshot(record)
    except IntegrityError:
        raise HTTPException(409, "科目编码已存在") from None


@router.put("/ledger-accounts/{account_id}")
def update_account(
    data: AccountUpdate,
    account_id: int = Path(gt=0),
    user: dict = Depends(require("ledger_account.manage")),
) -> dict:
    with orm_session(write=True) as db:
        record = get_record(db, LedgerAccount, account_id, data.version)
        before = snapshot(record)
        if record.name == data.name and bool(record.is_active) == data.is_active:
            raise HTTPException(409, "科目资料没有变化")
        record.name, record.is_active = data.name, int(data.is_active)
        record.version += 1
        db.flush()
        audit(db, record, before, data.reason, user["id"])
        return snapshot(record)


@router.get("/accounting-periods")
def list_periods(_: dict = Depends(require("accounting_period.view"))) -> list[dict]:
    with orm_session() as db:
        return [
            snapshot(record)
            for record in db.scalars(
                select(AccountingPeriod).order_by(AccountingPeriod.start_date)
            )
        ]


@router.post("/accounting-periods", status_code=201)
def create_period(
    data: PeriodInput, user: dict = Depends(require("accounting_period.manage"))
) -> dict:
    try:
        with orm_session(write=True) as db:
            # 日期范围含首尾；写锁使并发建立的重叠期间只能有一张成功。
            check_period_opening(db, data.start_date)
            ensure_date_unlocked(db, data.start_date)
            overlap = db.scalar(
                select(AccountingPeriod.id)
                .where(
                    AccountingPeriod.start_date <= data.end_date,
                    AccountingPeriod.end_date >= data.start_date,
                )
                .limit(1)
            )
            if overlap is not None:
                raise HTTPException(409, "日期与已有会计期间重叠，请核对开始和结束日期")
            record = add_model(
                db,
                AccountingPeriod(
                    code=data.code,
                    name=data.name,
                    start_date=data.start_date,
                    end_date=data.end_date,
                    status="open",
                    version=1,
                    created_by=user["id"],
                ),
            )
            audit(db, record, None, data.reason, user["id"])
            return snapshot(record)
    except IntegrityError:
        raise HTTPException(409, "期间编码已存在") from None


@router.put("/accounting-periods/{period_id}")
def update_period(
    data: PeriodUpdate,
    period_id: int = Path(gt=0),
    user: dict = Depends(require("accounting_period.manage")),
) -> dict:
    with orm_session(write=True) as db:
        record = get_record(db, AccountingPeriod, period_id, data.version)
        if record.status != "open":
            raise HTTPException(409, "已关闭期间不能修改")
        before = snapshot(record)
        if record.name == data.name:
            raise HTTPException(409, "期间名称没有变化")
        record.name = data.name
        record.version += 1
        db.flush()
        audit(db, record, before, data.reason, user["id"])
        return snapshot(record)


def changes(db: Session, model, source_column, record_id: int) -> list[dict]:
    results = []
    for change, username in db.execute(
        select(model, User.username)
        .join(User, model.changed_by == User.id)
        .where(source_column == record_id)
        .order_by(model.id)
    ):
        results.append(
            {
                "id": change.id,
                "before": (
                    json.loads(change.before_json) if change.before_json else None
                ),
                "after": json.loads(change.after_json),
                "reason": change.reason,
                "changed_by": change.changed_by,
                "changed_by_name": username,
                "created_at": change.created_at,
            }
        )
    return results


@router.get("/ledger-accounts/{account_id}/changes")
def account_changes(
    account_id: int = Path(gt=0), _: dict = Depends(require("ledger_account.view"))
) -> list[dict]:
    with orm_session() as db:
        get_record(db, LedgerAccount, account_id)
        return changes(
            db, LedgerAccountChange, LedgerAccountChange.account_id, account_id
        )


@router.get("/accounting-periods/{period_id}/changes")
def period_changes(
    period_id: int = Path(gt=0), _: dict = Depends(require("accounting_period.view"))
) -> list[dict]:
    with orm_session() as db:
        get_record(db, AccountingPeriod, period_id)
        return changes(
            db, AccountingPeriodChange, AccountingPeriodChange.period_id, period_id
        )
