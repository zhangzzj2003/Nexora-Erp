"""销售订单合同正文的追加式版本证据。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.access.security import require
from app.core.models import SalesOrderContractRevision, User
from app.core.orm import add_model, model_data, orm_session
from app.sales.customer_scope import require_visible_order

router = APIRouter(prefix='/api/v1/sales-orders')


class ContractRevisionInput(BaseModel):
    model_config = {'extra': 'forbid'}
    expected_version: int = Field(strict=True, ge=0)
    body: str = Field(min_length=1, max_length=20000)
    acceptance_reference: str = Field(min_length=1, max_length=400)
    reason: str = Field(min_length=1, max_length=200)

    @field_validator('body', 'acceptance_reference', 'reason')
    @classmethod
    def trim_required(cls, value: str) -> str:
        result = value.strip()
        if not result:
            raise ValueError('合同正文、客户确认依据和登记原因均不能为空')
        return result


def contract_data(db, order_id: int, status: str) -> dict:
    history = [
        {**model_data(revision), 'created_by_name': username}
        for revision, username in db.execute(
            select(SalesOrderContractRevision, User.username)
            .join(User, User.id == SalesOrderContractRevision.created_by)
            .where(SalesOrderContractRevision.sales_order_id == order_id)
            .order_by(SalesOrderContractRevision.version.desc())
        )
    ]
    return {'sales_order_id': order_id, 'status': status,
            'version': history[0]['version'] if history else 0,
            'current': history[0] if history else None, 'history': history}


@router.get('/{order_id}/contract')
def get_contract(order_id: int, user: dict = Depends(require('sales.view'))) -> dict:
    with orm_session() as db:
        order = require_visible_order(db, order_id, user)
        return contract_data(db, order_id, order.status)


@router.post('/{order_id}/contract')
def record_contract(order_id: int, payload: ContractRevisionInput,
                    user: dict = Depends(require('sales_order.confirm'))) -> dict:
    if 'sales.view' not in user['permissions']:
        raise HTTPException(403, '没有查看销售订单的权限')
    with orm_session(write=True) as db:
        order = require_visible_order(db, order_id, user)
        if order.status == 'cancelled':
            raise HTTPException(409, '已取消销售订单不能登记合同')
        current = db.scalar(select(SalesOrderContractRevision)
            .where(SalesOrderContractRevision.sales_order_id == order_id)
            .order_by(SalesOrderContractRevision.version.desc()).limit(1))
        version = current.version if current else 0
        if payload.expected_version != version:
            raise HTTPException(409, '合同版本已变化，请重新核对')
        if current and current.body == payload.body and current.acceptance_reference == payload.acceptance_reference:
            raise HTTPException(409, '相同合同正文与客户确认依据已经登记')
        # 仅追加证据；订单明细、保修条款及既有售后来源快照不随正文修订重写。
        add_model(db, SalesOrderContractRevision(
            sales_order_id=order_id, version=version + 1, body=payload.body,
            acceptance_reference=payload.acceptance_reference, reason=payload.reason,
            created_by=user['id']))
        return contract_data(db, order_id, order.status)
