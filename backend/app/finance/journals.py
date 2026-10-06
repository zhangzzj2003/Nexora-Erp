"""总账凭证：版本审计、独立审核和追加式冲销。"""

from app.core.document_responses import NumberedRoute
import json
import re
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.access.security import require
from app.core.models import (
    AccountingPeriod,
    LedgerAccount,
    Journal,
    JournalLine,
    JournalChange,
    BusinessJournalSource,
    ProfitTransfer,
    User,
)
from app.core.orm import add_model, model_data, orm_session
from app.finance.ledger import PeriodInput
from app.finance.opening_rules import check_journal_opening
from app.finance.auxiliary_rules import (AuxiliaryReference, line_data, validate_references,
    validate_line, save_snapshots, snapshot_values, selection_options)

router = APIRouter(route_class=NumberedRoute, prefix="/api/v1/finance/journals")


class ReasonInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=200)

    @field_validator("reason")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("操作原因不能为空")
        return value.strip()


class VersionInput(ReasonInput):
    version: int = Field(gt=0, strict=True)


class JournalLineInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: int = Field(gt=0, strict=True)
    summary: str = Field(min_length=1, max_length=200)
    debit: str
    credit: str
    auxiliary: list[AuxiliaryReference] = Field(default_factory=list, max_length=4)

    @field_validator('auxiliary')
    @classmethod
    def unique_auxiliary(cls, values):
        if len({item.kind for item in values}) != len(values):
            raise ValueError('每类辅助信息最多选择一个')
        return sorted(values, key=lambda item: item.kind)

    @field_validator("summary")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("分录摘要不能为空")
        return value.strip()

    @field_validator("debit", "credit")
    @classmethod
    def valid_amount(cls, value: str) -> str:
        # 固定分位且有上限，拒绝浮点、科学计数、NaN 和静默舍入。
        if not re.fullmatch(r"\d{1,12}(?:\.\d{1,2})?", value):
            raise ValueError("金额须为非负数字，整数最多 12 位、小数最多 2 位")
        return f"{Decimal(value):.2f}"

    @model_validator(mode="after")
    def one_side(self):
        if (Decimal(self.debit) > 0) == (Decimal(self.credit) > 0):
            raise ValueError("每条分录须且只能填写一方正金额")
        return self


class JournalInput(ReasonInput):
    reference: str = Field(min_length=1, max_length=80)
    journal_date: str
    note: str = Field(default="", max_length=500)
    lines: list[JournalLineInput] = Field(min_length=2, max_length=100)

    @field_validator("reference")
    @classmethod
    def nonblank_reference(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("凭证依据编号不能为空")
        return value.strip()

    @field_validator("journal_date")
    @classmethod
    def valid_date(cls, value: str) -> str:
        return PeriodInput.valid_date(value)

    @model_validator(mode="after")
    def balanced(self):
        if sum(Decimal(line.debit) for line in self.lines) != sum(
            Decimal(line.credit) for line in self.lines
        ):
            raise ValueError("凭证借贷金额必须相等")
        return self


class JournalUpdate(JournalInput):
    version: int = Field(gt=0, strict=True)


class ReversalInput(VersionInput):
    reference: str = Field(min_length=1, max_length=80)
    journal_date: str

    _reference = field_validator("reference")(JournalInput.nonblank_reference.__func__)
    _date = field_validator("journal_date")(JournalInput.valid_date.__func__)


def period_for(db: Session, journal_date: str) -> AccountingPeriod:
    period = db.scalar(
        select(AccountingPeriod).where(
            AccountingPeriod.start_date <= journal_date,
            AccountingPeriod.end_date >= journal_date,
        )
    )
    if period is None or period.status != "open":
        raise HTTPException(409, "凭证日期须属于一个开放的会计期间")
    return period


def get_journal(db: Session, journal_id: int, version: int | None = None) -> Journal:
    record = db.get(Journal, journal_id)
    if record is None:
        raise HTTPException(404, "凭证不存在")
    if version is not None and record.version != version:
        raise HTTPException(409, "凭证已变化，请刷新核对后再操作")
    return record


def lines_for(db: Session, journal_id: int) -> list[JournalLine]:
    return list(
        db.scalars(
            select(JournalLine)
            .where(JournalLine.journal_id == journal_id)
            .order_by(JournalLine.position)
        )
    )


def snapshot(db: Session, record: Journal) -> dict:
    result = model_data(record)
    result["lines"] = [line_data(db, line) for line in lines_for(db, record.id)]
    result["total_debit"] = (
        f'{sum(Decimal(line["debit"]) for line in result["lines"]):.2f}'
    )
    result["total_credit"] = (
        f'{sum(Decimal(line["credit"]) for line in result["lines"]):.2f}'
    )
    source = db.scalar(select(BusinessJournalSource).where(BusinessJournalSource.journal_id == record.id))
    result['business_source'] = (dict(key=source.source_key, evidence=json.loads(source.source_json),
        mapping=json.loads(source.mapping_json), policy_version=source.policy_version) if source else None)
    transfer = db.scalar(select(ProfitTransfer).where(ProfitTransfer.journal_id == record.id))
    result['profit_transfer'] = (dict(period_id=transfer.period_id,
        evidence=json.loads(transfer.evidence_json), policy=json.loads(transfer.policy_json)) if transfer else None)
    return result


def view(db: Session, record: Journal) -> dict:
    result = snapshot(db, record)
    result["created_by_name"] = db.scalar(
        select(User.username).where(User.id == record.created_by)
    )
    result["period_code"] = db.scalar(
        select(AccountingPeriod.code).where(AccountingPeriod.id == record.period_id)
    )
    result["reversal_journal_id"] = db.scalar(
        select(Journal.id)
        .where(Journal.reversal_of_id == record.id, Journal.status != "cancelled")
        .limit(1)
    )
    result["author_ids"] = list(
        db.scalars(
            select(JournalChange.changed_by)
            .where(
                JournalChange.journal_id == record.id,
                JournalChange.action.in_(("create", "update", "submit")),
            )
            .distinct()
        )
    )
    return result


def audit(
    db: Session,
    record: Journal,
    before: dict | None,
    action: str,
    reason: str,
    actor: int,
) -> None:
    db.add(
        JournalChange(
            journal_id=record.id,
            action=action,
            before_json=(
                json.dumps(before, ensure_ascii=False) if before is not None else None
            ),
            after_json=json.dumps(snapshot(db, record), ensure_ascii=False),
            reason=reason,
            changed_by=actor,
        )
    )
    db.flush()


def save_lines(db: Session, record: Journal, inputs: list[JournalLineInput], *, frozen_auxiliary: list[list[dict]] | None = None) -> None:
    accounts = {
        account.id: account
        for account in db.scalars(
            select(LedgerAccount).where(
                LedgerAccount.id.in_([line.account_id for line in inputs])
            )
        )
    }
    if any(
        line.account_id not in accounts or not accounts[line.account_id].is_active
        for line in inputs
    ):
        raise HTTPException(409, "分录须使用已存在且启用的科目")
    for position, line in enumerate(inputs, 1):
        account = accounts[line.account_id]
        values = (frozen_auxiliary[position - 1] if frozen_auxiliary is not None
            else validate_references(db, account.id, record.journal_date, line.auxiliary))
        saved = add_model(
            db,
            JournalLine(
                journal_id=record.id,
                position=position,
                account_id=account.id,
                account_code=account.code,
                account_name=account.name,
                category=account.category,
                normal_balance=account.normal_balance,
                summary=line.summary,
                debit=line.debit,
                credit=line.credit,
            )
        )
        save_snapshots(db, saved, values)
    db.flush()


def validate_for_post(db: Session, record: Journal) -> None:
    if period_for(db, record.journal_date).id != record.period_id:
        raise HTTPException(409, "凭证期间不匹配")
    lines = lines_for(db, record.id)
    # 冲销沿用已过账的科目快照，允许纠正停用科目的旧凭证。
    frozen = record.reversal_of_id is not None or db.scalar(select(ProfitTransfer.id).where(ProfitTransfer.journal_id == record.id)) is not None
    if record.reversal_of_id is None:
        for line in lines:
            account = db.get(LedgerAccount, line.account_id)
            if account is None or not account.is_active:
                raise HTTPException(409, "凭证科目已停用，请更正后重新提交")
            line.account_name = account.name
            if not frozen:
                validate_line(db, line, record.journal_date)
    if len(lines) < 2 or sum(Decimal(line.debit) for line in lines) != sum(
        Decimal(line.credit) for line in lines
    ):
        raise HTTPException(409, "凭证分录不平衡")
    db.flush()


@router.get("")
def list_journals(_: dict = Depends(require("journal.view"))) -> list[dict]:
    with orm_session() as db:
        return [
            view(db, record)
            for record in db.scalars(select(Journal).order_by(Journal.id.desc()))
        ]


@router.get("/options")
def journal_options(_: dict = Depends(require("journal.create"))) -> dict:
    # 建单选项由建单权限提供，不要求额外获得维护基础资料的权限。
    with orm_session() as db:
        return {
            **selection_options(db),
            "accounts": [
                {**model_data(a), "is_active": bool(a.is_active)}
                for a in db.scalars(
                    select(LedgerAccount)
                    .where(LedgerAccount.is_active == 1)
                    .order_by(LedgerAccount.code)
                )
            ],
            "periods": [
                model_data(p)
                for p in db.scalars(
                    select(AccountingPeriod)
                    .where(AccountingPeriod.status == "open")
                    .order_by(AccountingPeriod.start_date)
                )
            ],
        }


@router.post("", status_code=201)
def create_journal(
    data: JournalInput, user: dict = Depends(require("journal.create"))
) -> dict:
    try:
        with orm_session(write=True) as db:
            period = period_for(db, data.journal_date)
            record = add_model(
                db,
                Journal(
                    reference=data.reference,
                    journal_date=data.journal_date,
                    period_id=period.id,
                    note=data.note,
                    status="draft",
                    version=1,
                    created_by=user["id"],
                ),
            )
            save_lines(db, record, data.lines)
            audit(db, record, None, "create", data.reason, user["id"])
            return view(db, record)
    except IntegrityError:
        raise HTTPException(409, "凭证依据编号已使用") from None


@router.put("/{journal_id}")
def update_journal(
    data: JournalUpdate,
    journal_id: int = Path(gt=0),
    user: dict = Depends(require("journal.create")),
) -> dict:
    try:
        with orm_session(write=True) as db:
            record = get_journal(db, journal_id, data.version)
            if (
                record.status not in ("draft", "rejected")
                or record.reversal_of_id is not None
                or db.scalar(select(BusinessJournalSource.id).where(BusinessJournalSource.journal_id == record.id)) is not None
                or db.scalar(select(ProfitTransfer.id).where(ProfitTransfer.journal_id == record.id)) is not None
            ):
                raise HTTPException(
                    409, "仅手工草稿或驳回凭证可编辑；业务、结转或冲销草稿需取消后重建"
                )
            before = snapshot(db, record)
            record.reference, record.journal_date, record.note = (
                data.reference,
                data.journal_date,
                data.note,
            )
            record.period_id = period_for(db, data.journal_date).id
            record.status, record.reviewed_by, record.reviewed_at = "draft", None, None
            record.submitted_by, record.submitted_at = None, None
            record.version += 1
            db.execute(delete(JournalLine).where(JournalLine.journal_id == record.id))
            save_lines(db, record, data.lines)
            audit(db, record, before, "update", data.reason, user["id"])
            return view(db, record)
    except IntegrityError:
        raise HTTPException(409, "凭证依据编号已使用") from None


def transition(journal_id: int, data: VersionInput, user: dict, action: str) -> dict:
    allowed = {
        "submit": ("draft", "rejected"),
        "approve": ("submitted",),
        "reject": ("submitted",),
        "post": ("approved",),
        "cancel": ("draft", "rejected", "submitted", "approved"),
    }
    target = {
        "submit": "submitted",
        "approve": "approved",
        "reject": "rejected",
        "post": "posted",
        "cancel": "cancelled",
    }
    with orm_session(write=True) as db:
        record = get_journal(db, journal_id, data.version)
        if record.status not in allowed[action]:
            raise HTTPException(409, "凭证状态不允许此操作")
        if action in ("approve", "reject"):
            authors = db.scalars(
                select(JournalChange.changed_by).where(
                    JournalChange.journal_id == record.id,
                    JournalChange.action.in_(("create", "update", "submit")),
                )
            ).all()
            if user["id"] in authors:
                raise HTTPException(
                    409, "建单、编辑或提交过此凭证的人不能审核，请由另一账号处理"
                )
        before = snapshot(db, record)
        if action == "post":
            check_journal_opening(db, record.journal_date)
        if action in ("submit", "approve", "post"):
            from app.finance.business_journals import validate_source
            validate_source(db, record)
            from app.finance.profit_transfers import validate_source as validate_transfer
            validate_transfer(db, record)
            validate_for_post(db, record)
        record.status, record.version = target[action], record.version + 1
        prefix = {
            "submit": "submitted",
            "approve": "reviewed",
            "reject": "reviewed",
            "post": "posted",
            "cancel": "cancelled",
        }[action]
        setattr(record, prefix + "_by", user["id"])
        setattr(
            record,
            prefix + "_at",
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        )
        db.flush()
        from app.finance.business_journals import release_source
        release_source(db, record)
        from app.finance.profit_transfers import release_source as release_transfer
        release_transfer(db, record)
        audit(db, record, before, action, data.reason, user["id"])
        return view(db, record)


@router.post("/{journal_id}/submit")
def submit(
    data: VersionInput,
    journal_id: int = Path(gt=0),
    user: dict = Depends(require("journal.submit")),
) -> dict:
    return transition(journal_id, data, user, "submit")


@router.post("/{journal_id}/approve")
def approve(
    data: VersionInput,
    journal_id: int = Path(gt=0),
    user: dict = Depends(require("journal.review")),
) -> dict:
    return transition(journal_id, data, user, "approve")


@router.post("/{journal_id}/reject")
def reject(
    data: VersionInput,
    journal_id: int = Path(gt=0),
    user: dict = Depends(require("journal.review")),
) -> dict:
    return transition(journal_id, data, user, "reject")


@router.post("/{journal_id}/post")
def post(
    data: VersionInput,
    journal_id: int = Path(gt=0),
    user: dict = Depends(require("journal.post")),
) -> dict:
    return transition(journal_id, data, user, "post")


@router.post("/{journal_id}/cancel")
def cancel(
    data: VersionInput,
    journal_id: int = Path(gt=0),
    user: dict = Depends(require("journal.cancel")),
) -> dict:
    return transition(journal_id, data, user, "cancel")


@router.post("/{journal_id}/reverse", status_code=201)
def reverse(
    data: ReversalInput,
    journal_id: int = Path(gt=0),
    user: dict = Depends(require("journal.reverse")),
) -> dict:
    try:
        with orm_session(write=True) as db:
            original = get_journal(db, journal_id, data.version)
            if original.status != "posted" or original.reversal_of_id is not None:
                raise HTTPException(409, "仅已过账的原始凭证可建立冲销")
            if data.journal_date < original.journal_date:
                raise HTTPException(409, "冲销日期不能早于原凭证日期")
            transfer = db.scalar(select(ProfitTransfer).where(ProfitTransfer.journal_id == original.id))
            if transfer and data.journal_date != original.journal_date:
                raise HTTPException(409, '结转冲销必须记入原期间末；已结期间须先倒序重开')
            existing = db.scalar(
                select(Journal.id)
                .where(
                    Journal.reversal_of_id == journal_id, Journal.status != "cancelled"
                )
                .limit(1)
            )
            if existing is not None:
                raise HTTPException(409, "此凭证已有未取消的冲销凭证")
            period = period_for(db, data.journal_date)
            record = add_model(
                db,
                Journal(
                    reference=data.reference,
                    journal_date=data.journal_date,
                    period_id=period.id,
                    note=data.reason,
                    status="draft",
                    version=1,
                    created_by=user["id"],
                    reversal_of_id=original.id,
                ),
            )
            for source in lines_for(db, original.id):
                fields = model_data(source)
                fields.pop("id")
                fields.update(
                    journal_id=record.id, debit=source.credit, credit=source.debit
                )
                saved = add_model(db, JournalLine(**fields))
                save_snapshots(db, saved, snapshot_values(db, source))
            db.flush()
            audit(db, record, None, "create", data.reason, user["id"])
            # 原凭证不改金额或状态；只有冲销凭证经过独立审核并过账后才抵销。
            return view(db, record)
    except IntegrityError:
        raise HTTPException(409, "凭证依据编号已使用") from None


@router.get("/{journal_id}")
def journal_detail(
    journal_id: int = Path(gt=0), _: dict = Depends(require("journal.view"))
) -> dict:
    with orm_session() as db:
        return view(db, get_journal(db, journal_id))


@router.get("/{journal_id}/changes")
def journal_changes(
    journal_id: int = Path(gt=0), _: dict = Depends(require("journal.view"))
) -> list[dict]:
    with orm_session() as db:
        get_journal(db, journal_id)
        return [
            {
                "id": change.id,
                "action": change.action,
                "reason": change.reason,
                "before": (
                    json.loads(change.before_json) if change.before_json else None
                ),
                "after": json.loads(change.after_json),
                "changed_by": change.changed_by,
                "changed_by_name": username,
                "created_at": change.created_at,
            }
            for change, username in db.execute(
                select(JournalChange, User.username)
                .join(User, JournalChange.changed_by == User.id)
                .where(JournalChange.journal_id == journal_id)
                .order_by(JournalChange.id)
            )
        ]
