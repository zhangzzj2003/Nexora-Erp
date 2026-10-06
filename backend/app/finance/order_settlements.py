"""同一往来对象的订单贷方余额核销，保留原收付款和追加式撤销。"""

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.access.security import require
from app.core.models import OrderSettlementTransfer
from app.core.orm import orm_session
from app.core.period_lock import ensure_date_unlocked
from app.finance.routes import account_data, money, transfer_data
from app.finance.subledger_rules import check_subledger

router = APIRouter(prefix='/api/v1/finance/order-settlements')


class TransferInput(BaseModel):
    kind: str
    from_order_id: int = Field(gt=0)
    to_order_id: int = Field(gt=0)
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
        # 写锁内复算双方余额，防止并行退款、收款或核销重复使用同一贷方。
        source = account_data(db, data.kind, data.from_order_id)
        target = account_data(db, data.kind, data.to_order_id)
        if source['party_id'] != target['party_id']:
            raise HTTPException(409, '只能核销同一客户或供应商的订单')
        if not source['source_keys'] or not target['source_keys']:
            raise HTTPException(409, '双方订单均须有已确认且已定价的业务单据')
        if Decimal(source['outstanding_amount']) >= 0:
            raise HTTPException(409, '来源订单没有可用贷方余额')
        if Decimal(target['outstanding_amount']) <= 0:
            raise HTTPException(409, '目标订单没有待结余额')
        if data.amount > -Decimal(source['outstanding_amount']) or data.amount > Decimal(target['outstanding_amount']):
            raise HTTPException(409, '核销金额超过可用贷方或目标未结余额')
        record = OrderSettlementTransfer(kind=data.kind, party_id=source['party_id'],
            from_order_id=data.from_order_id, to_order_id=data.to_order_id,
            amount=money(data.amount), reference=data.reference, reason=data.reason,
            created_by=user['id'])
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
        if original.reverses_id is not None:
            raise HTTPException(409, '撤销记录不能再次撤销')
        if db.scalar(select(OrderSettlementTransfer.id).where(
                OrderSettlementTransfer.reverses_id == transfer_id).limit(1)) is not None:
            raise HTTPException(409, '此订单核销已撤销')
        # 原记录和凭据不改写，反向记录恢复双方余额并保留操作人。
        record = OrderSettlementTransfer(kind=original.kind, party_id=original.party_id,
            from_order_id=original.from_order_id, to_order_id=original.to_order_id,
            amount=money(-Decimal(original.amount)), reference=f'撤销 #{transfer_id}',
            reason=data.reason, reverses_id=transfer_id, created_by=user['id'])
        db.add(record)
        db.flush()
        return transfer_data(db, record.id)
