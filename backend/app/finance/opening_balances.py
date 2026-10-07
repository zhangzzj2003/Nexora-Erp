"""期初余额：唯一启用方案、独立审核、确认及启用前可审计撤销。"""

from app.core.document_responses import NumberedRoute
import json
from datetime import datetime, timezone
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import Field, field_validator, model_validator
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.access.security import require, current_user
from app.core.models import (
    OpeningBalance,
    OpeningBalanceLine,
    OpeningBalanceChange,
    LedgerAccount,
    AccountingPeriod,
    User,
)
from app.core.orm import orm_session, model_data, add_model
from app.core import document_approval as approval
from app.core.approval_documents import opening_snapshot, document_snapshot
from app.finance.journals import (
    ReasonInput,
    VersionInput,
    JournalLineInput,
    JournalInput,
)
from app.finance.opening_rules import active_opening, ensure_no_posted_journals
from app.finance.auxiliary_rules import (combination, line_data, validate_references,
    validate_line, save_snapshots, selection_options)

router = APIRouter(route_class=NumberedRoute, prefix="/api/v1/finance/opening-balances")


class OpeningInput(ReasonInput):
    reference: str = Field(min_length=1, max_length=80)
    effective_date: str
    note: str = Field(default="", max_length=500)
    lines: list[JournalLineInput] = Field(max_length=100)

    _reference = field_validator("reference")(JournalInput.nonblank_reference.__func__)
    _date = field_validator("effective_date")(JournalInput.valid_date.__func__)

    @model_validator(mode="after")
    def balanced(self):
        if len({(line.account_id, combination(line.auxiliary)) for line in self.lines}) != len(self.lines):
            raise ValueError("相同科目及辅助组合只能填写一条期初余额")
        if sum(Decimal(line.debit) for line in self.lines) != sum(
            Decimal(line.credit) for line in self.lines
        ):
            raise ValueError("期初借贷金额必须相等；全部为零时提交空明细")
        return self


class OpeningUpdate(OpeningInput):
    version: int = Field(strict=True, gt=0)


def first_period(db: Session, effective_date: str) -> AccountingPeriod:
    period = db.scalar(
        select(AccountingPeriod).order_by(AccountingPeriod.start_date).limit(1)
    )
    if period is None or period.status != "open" or period.start_date != effective_date:
        raise HTTPException(409, "启用日须为最早开放会计期间的开始日期")
    return period


def get_opening(
    db: Session, record_id: int, version: int | None = None
) -> OpeningBalance:
    record = db.get(OpeningBalance, record_id)
    if record is None:
        raise HTTPException(404, "期初余额不存在")
    if version is not None and record.version != version:
        raise HTTPException(409, "期初余额已变化，请刷新核对后再操作")
    return record


def lines_for(db: Session, record_id: int) -> list[OpeningBalanceLine]:
    return list(
        db.scalars(
            select(OpeningBalanceLine)
            .where(OpeningBalanceLine.opening_balance_id == record_id)
            .order_by(OpeningBalanceLine.position)
        )
    )


def snapshot(db: Session, record: OpeningBalance) -> dict:
    result = model_data(record)
    result["lines"] = [line_data(db, line) for line in lines_for(db, record.id)]
    for side in ("debit", "credit"):
        result["total_" + side] = (
            f'{sum(Decimal(line[side]) for line in result["lines"]):.2f}'
        )
    return result


def view(db: Session, record: OpeningBalance) -> dict:
    result = snapshot(db, record)
    result["created_by_name"] = db.scalar(
        select(User.username).where(User.id == record.created_by)
    )
    result["period_code"] = db.scalar(
        select(AccountingPeriod.code).where(AccountingPeriod.id == record.period_id)
    )
    result["author_ids"] = list(
        db.scalars(
            select(OpeningBalanceChange.changed_by)
            .where(
                OpeningBalanceChange.opening_balance_id == record.id,
                OpeningBalanceChange.action.in_(("create", "update", "submit")),
            )
            .distinct()
        )
    )
    result['approval'] = approval.case_data(approval.find_case(db, 'OpeningBalance', record.id))
    result['reversal_approval'] = approval.case_data(approval.find_case(db, 'OpeningBalance', record.id, 'reverse'))
    reverse = approval.find_case(db, 'OpeningBalance', record.id, 'reverse')
    result['reversal_reason'] = json.loads(reverse.snapshot_json).get('reversal_reason', '') if reverse else ''
    return result


def audit(
    db: Session,
    record: OpeningBalance,
    before: dict | None,
    action: str,
    reason: str,
    actor: int,
) -> None:
    db.add(
        OpeningBalanceChange(
            opening_balance_id=record.id,
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


def save_lines(
    db: Session, record: OpeningBalance, inputs: list[JournalLineInput]
) -> None:
    accounts = {
        a.id: a
        for a in db.scalars(
            select(LedgerAccount).where(
                LedgerAccount.id.in_([line.account_id for line in inputs])
            )
        )
    }
    if any(
        line.account_id not in accounts or not accounts[line.account_id].is_active
        for line in inputs
    ):
        raise HTTPException(409, "期初余额须使用已存在且启用的科目")
    for position, line in enumerate(inputs, 1):
        account = accounts[line.account_id]
        values = validate_references(db, account.id, record.effective_date, line.auxiliary)
        saved = add_model(
            db,
            OpeningBalanceLine(
                opening_balance_id=record.id,
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


def validate(db: Session, record: OpeningBalance) -> None:
    ensure_no_posted_journals(db)
    if first_period(db, record.effective_date).id != record.period_id:
        raise HTTPException(409, "期初余额期间已不匹配")
    lines = lines_for(db, record.id)
    for line in lines:
        account = db.get(LedgerAccount, line.account_id)
        if account is None or not account.is_active:
            raise HTTPException(409, "期初科目已停用，请更正后重新提交")
        line.account_name = account.name
        validate_line(db, line, record.effective_date)
    if sum(Decimal(line.debit) for line in lines) != sum(
        Decimal(line.credit) for line in lines
    ):
        raise HTTPException(409, "期初余额不平衡")
    db.flush()


def history(db: Session, record_id: int) -> list[dict]:
    get_opening(db, record_id)
    return [
        dict(
            id=change.id,
            action=change.action,
            reason=change.reason,
            before=json.loads(change.before_json) if change.before_json else None,
            after=json.loads(change.after_json),
            changed_by=change.changed_by,
            changed_by_name=username,
            created_at=change.created_at,
        )
        for change, username in db.execute(
            select(OpeningBalanceChange, User.username)
            .join(User, OpeningBalanceChange.changed_by == User.id)
            .where(OpeningBalanceChange.opening_balance_id == record_id)
            .order_by(OpeningBalanceChange.id)
        )
    ]


@router.get("")
def list_openings(_: dict = Depends(require("opening_balance.view"))) -> list[dict]:
    with orm_session() as db:
        return [
            view(db, record)
            for record in db.scalars(
                select(OpeningBalance).order_by(OpeningBalance.id.desc())
            )
        ]


@router.get("/options")
def options(_: dict = Depends(require("opening_balance.create"))) -> dict:
    with orm_session() as db:
        period = db.scalar(
            select(AccountingPeriod).order_by(AccountingPeriod.start_date).limit(1)
        )
        return dict(
            **selection_options(db),
            accounts=[
                {**model_data(a), "is_active": bool(a.is_active)}
                for a in db.scalars(
                    select(LedgerAccount)
                    .where(LedgerAccount.is_active == 1)
                    .order_by(LedgerAccount.code)
                )
            ],
            period=model_data(period) if period is not None else None,
        )


@router.post("", status_code=201)
def create(
    data: OpeningInput, user: dict = Depends(require("opening_balance.create"))
) -> dict:
    try:
        with orm_session(write=True) as db:
            ensure_no_posted_journals(db)
            if active_opening(db) is not None:
                raise HTTPException(
                    409, "已有未结束的期初方案，请完成、取消或撤销原方案"
                )
            period = first_period(db, data.effective_date)
            record = add_model(
                db,
                OpeningBalance(
                    reference=data.reference,
                    effective_date=data.effective_date,
                    period_id=period.id,
                    note=data.note,
                    status="draft",
                    version=1,
                    active_key=1,
                    created_by=user["id"],
                ),
            )
            save_lines(db, record, data.lines)
            audit(db, record, None, "create", data.reason, user["id"])
            return view(db, record)
    except IntegrityError:
        raise HTTPException(409, "期初依据编号已使用，或已有有效期初方案") from None


@router.put("/{record_id}")
def update(
    data: OpeningUpdate,
    record_id: int = Path(gt=0),
    user: dict = Depends(require("opening_balance.create")),
) -> dict:
    try:
        with orm_session(write=True) as db:
            record = get_opening(db, record_id, data.version)
            if record.status not in ("draft", "rejected"):
                raise HTTPException(409, "仅草稿或驳回期初余额可编辑")
            ensure_no_posted_journals(db)
            before = snapshot(db, record)
            record.reference, record.effective_date, record.note = (
                data.reference,
                data.effective_date,
                data.note,
            )
            record.period_id = first_period(db, data.effective_date).id
            record.status = "draft"
            record.version += 1
            record.submitted_by = record.submitted_at = record.reviewed_by = (
                record.reviewed_at
            ) = None
            db.execute(
                delete(OpeningBalanceLine).where(
                    OpeningBalanceLine.opening_balance_id == record.id
                )
            )
            save_lines(db, record, data.lines)
            audit(db, record, before, "update", data.reason, user["id"])
            return view(db, record)
    except IntegrityError:
        raise HTTPException(409, "期初依据编号已使用") from None


def validate_reversal(db: Session, record: OpeningBalance) -> None:
    # 撤销只在未过账、期间开放且无有效分户引用时允许，审批不能替代执行时复核。
    from app.finance.subledger_rules import protect_opening
    from app.core.period_lock import ensure_date_unlocked
    protect_opening(db, record.id)
    ensure_no_posted_journals(db)
    ensure_date_unlocked(db, record.effective_date)


def prepare_approval_action(db: Session, record: OpeningBalance, action: str,
                            user: dict, reason: str, intent: str = 'execute') -> dict:
    if action != 'withdraw' and (not reason.strip() or len(reason.strip()) > 200):
        raise HTTPException(422, '期初审批依据必填，最多二百字')
    before = snapshot(db, record)
    if action in ('submit', 'approve'):
        if intent == 'reverse':
            validate_reversal(db, record)
        else:
            validate(db, record)
    return before


def sync_approval_action(db: Session, record: OpeningBalance, action: str, state: dict,
                         user_id: int, reason: str, before: dict) -> None:
    # 原业务版本和审计随每一步一起递增，中间核准不能提前启用期初。
    record.status = 'draft' if action == 'withdraw' else state['status']
    record.version += 1
    if action == 'submit':
        record.submitted_by, record.submitted_at = state['submitted_by'], state['submitted_at']
        record.reviewed_by = record.reviewed_at = None
    elif action in ('approve', 'reject'):
        record.reviewed_by, record.reviewed_at = user_id, approval.now(db)
    elif action == 'withdraw':
        record.submitted_by = record.submitted_at = record.reviewed_by = record.reviewed_at = None
    audit(db, record, before, action, reason, user_id)


def transition(
    db: Session, record: OpeningBalance, data: VersionInput, user: dict, action: str
) -> dict:
    if action in ('submit', 'approve', 'reject'):
        raise HTTPException(409, '请从带审批版本的统一单据入口送审或审核期初')
    states = {'confirm': ('approved',), 'cancel': ('draft', 'rejected', 'submitted', 'approved'),
              'reverse': ('confirmed',)}
    targets = {'confirm': 'confirmed', 'cancel': 'cancelled', 'reverse': 'reversed'}
    if record.status not in states[action]:
        raise HTTPException(409, '期初余额状态不允许此操作')
    case = approval.find_case(db, 'OpeningBalance', record.id)
    if action == 'cancel' and case and case.status in ('submitted', 'approved'):
        raise HTTPException(409, '请先撤回期初审批，再取消草稿')
    before = snapshot(db, record)
    if action == 'confirm':
        case = approval.require_approved(db, 'OpeningBalance', record.id,
            opening_snapshot(db, record.id), user['id'])
        validate(db, record)
    elif action == 'reverse':
        case = approval.require_approved(db, 'OpeningBalance', record.id,
            document_snapshot(db, 'OpeningBalance', record.id, 'reverse', data.reason), user['id'],
            intent='reverse', permission='opening_balance.reverse')
        validate_reversal(db, record)
    record.status = targets[action]
    record.version += 1
    if action in ("cancel", "reverse"):
        record.active_key = None
    prefix = {
        "confirm": "confirmed",
        "cancel": "cancelled",
        "reverse": "reversed",
    }[action]
    setattr(record, prefix + "_by", user["id"])
    setattr(
        record, prefix + "_at", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    )
    db.flush()
    audit(db, record, before, action, data.reason, user["id"])
    if action in ('confirm', 'reverse'):
        approval.mark_executed(db, case, user['id'],
            permission='opening_balance.reverse' if action == 'reverse' else None)
    return view(db, record)


@router.post("/{record_id}/{action}")
def change(
    action: str,
    data: VersionInput,
    record_id: int = Path(gt=0),
    user: dict = Depends(current_user),
) -> dict:
    permission = {
        "submit": "submit",
        "approve": "review",
        "reject": "review",
        "confirm": "confirm",
        "cancel": "cancel",
        "reverse": "reverse",
    }.get(action)
    if permission is None:
        raise HTTPException(404, "期初操作不存在")
    if "opening_balance." + permission not in user["permissions"]:
        raise HTTPException(403, "没有执行此操作的权限")
    with orm_session(write=True) as db:
        return transition(
            db, get_opening(db, record_id, data.version), data, user, action
        )


@router.get("/{record_id}/changes")
def changes(
    record_id: int = Path(gt=0), _: dict = Depends(require("opening_balance.view"))
) -> list[dict]:
    with orm_session() as db:
        return history(db, record_id)
