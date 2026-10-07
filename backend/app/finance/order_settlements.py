"""同一往来对象的订单贷方余额核销，保留原收付款和追加式撤销。"""

from app.core.document_responses import NumberedRoute
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal
from sqlalchemy.orm import Session
from app.access.security import current_user
from app.core import document_approval as approval
from app.core.approval_documents import order_settlement_snapshot
from app.finance.routes import PaymentExecutionInput
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.access.security import require
from app.core.models import OrderSettlementTransfer
from app.core.orm import orm_session
from app.core.period_lock import ensure_date_unlocked
from app.finance.routes import account_data, money, transfer_data
from app.finance.subledger_rules import check_subledger

router = APIRouter(route_class=NumberedRoute, prefix='/api/v1/finance/order-settlements')


class TransferInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: str
    from_order_id: int = Field(gt=0, strict=True)
    to_order_id: int = Field(gt=0, strict=True)
    amount: Decimal
    reference: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=200)

    @field_validator('kind')
    @classmethod
    def valid_kind(cls, value: str) -> str:
        if value not in ('receivable', 'payable'):
            raise ValueError('往来类别无效')
        return value

    @field_validator('amount')
    @classmethod
    def valid_amount(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 0 or value > 1_000_000_000_000 or value.as_tuple().exponent < -2:
            raise ValueError('金额须大于零、最多两位小数且不超过一万亿元')
        return value

    @field_validator('reference', 'reason')
    @classmethod
    def trim_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('参考号和核销依据不能为空')
        return value.strip()


class ReverseInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reason: str = Field(min_length=1, max_length=200)

    @field_validator('reason')
    @classmethod
    def trim_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('撤销原因不能为空')
        return value.strip()


@router.get('')
def list_transfers(_: dict = Depends(require('finance.view'))) -> list[dict]:
    with orm_session() as db:
        ids = db.scalars(select(OrderSettlementTransfer.id).order_by(OrderSettlementTransfer.id.desc()))
        return [transfer_data(db, identifier) for identifier in ids]


@router.post('', status_code=201)
def create_transfer(data: TransferInput, user: dict = Depends(require('finance.record'))) -> dict:
    if data.from_order_id == data.to_order_id:
        raise HTTPException(422, '来源与目标订单不能相同')
    with orm_session(write=True) as db:
        today = datetime.now(timezone.utc).date().isoformat()
        check_subledger(db, today)
        ensure_date_unlocked(db, today)
        source = account_data(db, data.kind, data.from_order_id)
        record = OrderSettlementTransfer(kind=data.kind, party_id=source['party_id'],
            from_order_id=data.from_order_id, to_order_id=data.to_order_id,
            amount=money(data.amount), reference=data.reference, reason=data.reason,
            created_by=user['id'], status='draft', version=1)
        validate_transfer(db, record)
        try:
            db.add(record)
            db.flush()
        except IntegrityError:
            raise HTTPException(409, '此订单组合的核销参考号已使用') from None
        return transfer_data(db, record.id)


@router.post('/{transfer_id}/reverse', status_code=201)
def reverse_transfer(data: ReverseInput, transfer_id: int = Path(gt=0),
                     user: dict = Depends(require('finance.reverse'))) -> dict:
    with orm_session(write=True) as db:
        today = datetime.now(timezone.utc).date().isoformat()
        check_subledger(db, today)
        ensure_date_unlocked(db, today)
        original = db.get(OrderSettlementTransfer, transfer_id)
        if original is None:
            raise HTTPException(404, '订单核销记录不存在')
        if original.status != 'executed':
            raise HTTPException(409, '原核销未执行，不能建立撤销草稿')
        if original.reverses_id is not None:
            raise HTTPException(409, '撤销记录不能再次撤销')
        if db.scalar(select(OrderSettlementTransfer.id).where(
                OrderSettlementTransfer.reverses_id == transfer_id, OrderSettlementTransfer.status != 'cancelled').limit(1)) is not None:
            raise HTTPException(409, '此订单核销已撤销')
        # 原记录不改写；另建反向草稿，独立批准执行后才恢复双方余额。
        record = OrderSettlementTransfer(kind=original.kind, party_id=original.party_id,
            from_order_id=original.from_order_id, to_order_id=original.to_order_id,
            amount=money(-Decimal(original.amount)), reference=f'撤销 #{transfer_id}',
            reason=data.reason, reverses_id=transfer_id, created_by=user['id'], status='draft', version=1)
        validate_transfer(db, record)
        db.add(record)
        db.flush()
        return transfer_data(db, record.id)


def validate_transfer(db: Session, record: OrderSettlementTransfer) -> None:
    """同一写锁内复核最新业务和余额；草稿与批准不预占贷方。"""
    today = datetime.now(timezone.utc).date().isoformat()
    check_subledger(db, today)
    ensure_date_unlocked(db, today)
    source = account_data(db, record.kind, record.from_order_id)
    target = account_data(db, record.kind, record.to_order_id)
    if record.from_order_id == record.to_order_id:
        raise HTTPException(422, '来源与目标订单不能相同')
    if source['party_id'] != target['party_id'] or source['party_id'] != record.party_id:
        raise HTTPException(409, '只能核销同一客户或供应商的订单')
    if not source['source_keys'] or not target['source_keys']:
        raise HTTPException(409, '双方订单均须有已确认且已定价的业务单据')
    if record.reverses_id is not None:
        original = db.get(OrderSettlementTransfer, record.reverses_id)
        if original is None or original.status != 'executed' or original.reverses_id is not None:
            raise HTTPException(409, '原核销未执行或本身是撤销记录')
        fields = ('kind', 'party_id', 'from_order_id', 'to_order_id')
        if any(getattr(original, key) != getattr(record, key) for key in fields) or Decimal(record.amount) != -Decimal(original.amount):
            raise HTTPException(409, '撤销草稿与原核销不一致')
        ensure_date_unlocked(db, original.executed_at or original.created_at)
        if db.scalar(select(OrderSettlementTransfer.id).where(
                OrderSettlementTransfer.reverses_id == original.id, OrderSettlementTransfer.status != 'cancelled',
                OrderSettlementTransfer.id != record.id).limit(1)) is not None:
            raise HTTPException(409, '原核销已有有效撤销草稿或记录')
        # 撤销恢复原经济事实，可能形成需退款的贷方；不能按普通核销方向限制反向记录。
        return
    amount = Decimal(record.amount)
    if Decimal(source['outstanding_amount']) >= 0:
        raise HTTPException(409, '来源订单没有可用贷方余额')
    if Decimal(target['outstanding_amount']) <= 0:
        raise HTTPException(409, '目标订单没有待结余额')
    if amount <= 0 or amount > -Decimal(source['outstanding_amount']) or amount > Decimal(target['outstanding_amount']):
        raise HTTPException(409, '核销金额超过可用贷方或目标未结余额')


@router.post('/{transfer_id}/{action}')
def execute_transfer(action: Literal['post', 'cancel'], data: PaymentExecutionInput,
                     transfer_id: int = Path(gt=0), user: dict = Depends(current_user)) -> dict:
    with orm_session(write=True) as db:
        record = db.get(OrderSettlementTransfer, transfer_id)
        if record is None:
            raise HTTPException(404, '订单核销记录不存在')
        permission = 'finance.reverse' if record.reverses_id is not None else 'finance.record'
        approval.actor(db, user['id'], permission)
        if record.version != data.version or record.status != 'draft':
            raise HTTPException(409, '核销记录已变化或已处理，请重新读取')
        case = approval.find_case(db, 'OrderSettlementTransfer', transfer_id)
        if action == 'cancel':
            if case and case.status in ('submitted', 'approved'):
                raise HTTPException(409, '请先撤回核销审批，再取消草稿')
            record.status = 'cancelled'
            record.cancelled_by, record.cancelled_at = user['id'], approval.now(db)
            record.cancellation_reason = data.reason
        else:
            case = approval.require_approved(db, 'OrderSettlementTransfer', transfer_id,
                order_settlement_snapshot(db, transfer_id), user['id'], permission=permission)
            validate_transfer(db, record)
            record.status = 'executed'
            record.executed_by, record.executed_at = user['id'], approval.now(db)
            ensure_date_unlocked(db, record.executed_at)
            check_subledger(db, record.executed_at)
            approval.mark_executed(db, case, user['id'], permission=permission, reason=data.reason)
        record.version += 1
        db.flush()
        return transfer_data(db, transfer_id)
