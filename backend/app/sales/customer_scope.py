"""客户数据范围与订单金额范围；所有边界校验在服务端执行。"""

from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.core.models import CustomerProfile, SalesOrderOwner


def is_admin(user: dict) -> bool:
    return 'admin' in user['roles']


def require_customer(db: Session, customer_id: int, user: dict, *, active: bool = False) -> CustomerProfile:
    profile = db.get(CustomerProfile, customer_id)
    # 越权与不存在统一返回 404，不暴露其他商务客户的存在性。
    if profile is None or (not is_admin(user) and profile.owner_id != user['id']):
        raise HTTPException(404, '客户不存在或无权访问')
    if active and not profile.is_active:
        raise HTTPException(409, '客户已停用，不能新建销售订单')
    return profile


def can_view_amount(db: Session, order_id: int, user: dict) -> bool:
    owner = db.get(SalesOrderOwner, order_id)
    return is_admin(user) or 'sales_amount.all' in user['permissions'] or (owner is not None and owner.owner_id == user['id'])


def protect_amount(db: Session, record: dict, user: dict, order_id: int) -> dict:
    # 使用显式金额可见标记，null 表示无权限，绝不能用零伪装实际金额。
    visible = can_view_amount(db, order_id, user)
    owner = db.get(SalesOrderOwner, order_id)
    result = dict(record, amount_visible=visible, owner_id=owner.owner_id if owner else None,
                  owner_version=owner.version if owner else 1)
    if not visible:
        result['total_amount'] = None
        result['lines'] = [dict(line, unit_price=None, line_total=None, quoted_price=None, tax_rate=None, discount_rate=None) for line in record.get('lines', [])]
    return result
