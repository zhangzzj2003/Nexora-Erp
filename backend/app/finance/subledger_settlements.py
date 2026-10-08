"""历史原单之间的贷方核销，按完整归属抵销且不新增资金或总账金额。"""

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.access.security import current_user, require
from app.core import document_approval as approval
from app.core.approval_documents import subledger_settlement_snapshot
from app.core.document_responses import NumberedRoute
from app.core.models import SubledgerOpening, SubledgerOpeningLine, SubledgerSettlement, User
from app.core.orm import add_model, model_data, orm_session
from app.core.period_lock import ensure_date_unlocked
from app.finance.auxiliary_rules import combination
from app.finance.journals import VersionInput
from app.finance.order_settlements import ReverseInput, TransferInput
from app.finance.subledger_rules import check_subledger


# 金额与必填文字沿用已交付订单核销的校验；明细 ID 只接受严格正整数。
class SettlementInput(ReverseInput):
    from_line_id: int = Field(gt=0, strict=True)
    to_line_id: int = Field(gt=0, strict=True)
    amount: Decimal
    reference: str = Field(min_length=1, max_length=100)
    _amount = field_validator('amount')(TransferInput.valid_amount.__func__)
    _reference = field_validator('reference')(TransferInput.trim_required.__func__)


router = APIRouter(route_class=NumberedRoute, prefix='/api/v1/finance/subledger-settlements')


def settlement_data(db: Session, record: SubledgerSettlement) -> dict:
    from app.finance.subledger_openings import line_data
    source, target = (db.get(SubledgerOpeningLine, identifier) for identifier in (record.from_line_id, record.to_line_id))
    details = line_data(source)
    return dict(**model_data(record), currency='CNY', kind=source.kind,
        opening_id=source.opening_id, account_id=source.account_id, account_code=source.account_code,
        party_id=details['party_id'], party_name=details['party_name'], auxiliary=json.loads(source.auxiliary_json),
        from_document_reference=source.document_reference, to_document_reference=target.document_reference,
        created_by_name=db.get(User, record.created_by).username,
        approval=approval.case_data(approval.find_case(db, 'SubledgerSettlement', record.id)))


def settlements_for(db: Session, line_id: int, to_date: str | None = None) -> list[dict]:
    statement = select(SubledgerSettlement).where(SubledgerSettlement.status == 'executed',
        or_(SubledgerSettlement.from_line_id == line_id, SubledgerSettlement.to_line_id == line_id))
    if to_date:
        statement = statement.where(SubledgerSettlement.executed_at < to_date + ' 24:00:00')
    return [settlement_data(db, item) for item in db.scalars(statement.order_by(SubledgerSettlement.id))]


def validate_settlement(db: Session, record: SubledgerSettlement) -> None:
    from app.finance.subledger_openings import balance
    today = datetime.now(timezone.utc).date().isoformat()
    check_subledger(db, today)
    ensure_date_unlocked(db, today)
    source, target = (db.get(SubledgerOpeningLine, identifier) for identifier in (record.from_line_id, record.to_line_id))
    if source is None or target is None:
        raise HTTPException(404, '历史分户原单不存在')
    opening = db.get(SubledgerOpening, source.opening_id)
    if opening.status != 'confirmed' or opening.active_key != 1 or source.opening_id != target.opening_id:
        raise HTTPException(409, '双方原单须来自同一有效已确认分户方案')
    if source.id == target.id:
        raise HTTPException(422, '来源与目标原单不能相同')
    if (source.kind, source.account_id, source.customer_id, source.supplier_id,
        combination(json.loads(source.auxiliary_json))) != (target.kind, target.account_id,
        target.customer_id, target.supplier_id, combination(json.loads(target.auxiliary_json))):
        raise HTTPException(409, '核销须为同类同对象、同控制科目及完整辅助组合')
    if record.reverses_id is not None:
        original = db.get(SubledgerSettlement, record.reverses_id)
        if original is None or original.status != 'executed' or original.reverses_id is not None:
            raise HTTPException(409, '原核销未执行或本身为反向记录')
        if (record.from_line_id, record.to_line_id, Decimal(record.amount)) != (
                original.from_line_id, original.to_line_id, -Decimal(original.amount)):
            raise HTTPException(409, '反向核销与原记录不一致')
        ensure_date_unlocked(db, original.executed_at)
        if db.scalar(select(SubledgerSettlement.id).where(SubledgerSettlement.reverses_id == original.id,
                SubledgerSettlement.status != 'cancelled', SubledgerSettlement.id != record.id).limit(1)):
            raise HTTPException(409, '原核销已有有效反向草稿或记录')
    else:
        amount = Decimal(record.amount)
        source_credit = -Decimal(balance(db, source)['outstanding_amount'])
        target_debt = Decimal(balance(db, target)['outstanding_amount'])
        if amount <= 0 or amount > source_credit or amount > target_debt:
            raise HTTPException(409, '核销超过来源最新贷方余额或目标最新待结金额')


@router.get('')
def list_settlements(_: dict = Depends(require('subledger_opening.view'))) -> list[dict]:
    with orm_session() as db:
        return [settlement_data(db, row) for row in db.scalars(select(SubledgerSettlement).order_by(SubledgerSettlement.id.desc()))]


@router.post('', status_code=201)
def create_settlement(data: SettlementInput, user: dict = Depends(require('finance.record'))) -> dict:
    try:
        with orm_session(write=True) as db:
            record = SubledgerSettlement(**data.model_dump(exclude={'amount'}), amount=f'{data.amount:.2f}',
                created_by=user['id'], status='draft', version=1)
            validate_settlement(db, record)
            add_model(db, record)
            return settlement_data(db, record)
    except IntegrityError:
        raise HTTPException(409, '此原单组合的核销参考号已使用') from None


@router.post('/{settlement_id}/reverse', status_code=201)
def reverse_settlement(data: ReverseInput, settlement_id: int = Path(gt=0),
                       user: dict = Depends(require('finance.reverse'))) -> dict:
    try:
        with orm_session(write=True) as db:
            original = db.get(SubledgerSettlement, settlement_id)
            if original is None:
                raise HTTPException(404, '历史分户核销不存在')
            record = SubledgerSettlement(from_line_id=original.from_line_id, to_line_id=original.to_line_id,
                amount=f'{-Decimal(original.amount):.2f}', reference=f'冲销 #{original.id}', reason=data.reason,
                reverses_id=original.id, created_by=user['id'], status='draft', version=1)
            validate_settlement(db, record)
            add_model(db, record)
            return settlement_data(db, record)
    except IntegrityError:
        raise HTTPException(409, '原核销已有有效反向草稿或记录') from None


@router.post('/{settlement_id}/{action}')
def execute_settlement(action: Literal['post', 'cancel'], data: VersionInput, settlement_id: int = Path(gt=0),
                       user: dict = Depends(current_user)) -> dict:
    with orm_session(write=True) as db:
        record = db.get(SubledgerSettlement, settlement_id)
        if record is None:
            raise HTTPException(404, '历史分户核销不存在')
        permission = 'finance.reverse' if record.reverses_id is not None else 'finance.record'
        approval.actor(db, user['id'], permission)
        if record.version != data.version or record.status != 'draft':
            raise HTTPException(409, '核销已变化或已处理，请重新读取')
        if not data.reason.strip() or len(data.reason.strip()) > 200:
            raise HTTPException(422, '执行或取消依据必填，最多二百字')
        case = approval.find_case(db, 'SubledgerSettlement', record.id)
        if action == 'cancel':
            if case and case.status in ('submitted', 'approved'):
                raise HTTPException(409, '请先撤回审批，再取消草稿')
            record.status = 'cancelled'
            record.cancelled_by, record.cancelled_at = user['id'], approval.now(db)
            record.cancellation_reason = data.reason.strip()
        else:
            case = approval.require_approved(db, 'SubledgerSettlement', record.id,
                subledger_settlement_snapshot(db, record.id), user['id'], permission=permission)
            validate_settlement(db, record)
            record.status = 'executed'
            record.executed_by, record.executed_at = user['id'], approval.now(db)
            ensure_date_unlocked(db, record.executed_at)
            check_subledger(db, record.executed_at)
            approval.mark_executed(db, case, user['id'], permission=permission, reason=data.reason.strip())
        record.version += 1
        db.flush()
        return settlement_data(db, record)
