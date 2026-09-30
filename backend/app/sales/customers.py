"""客户档案维护、独立转交及版本审计。"""

import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.access.security import require, current_user
from app.core.models import Customer, CustomerProfile, CustomerChange, SalesOrder, SalesOrderOwner, User
from app.core.orm import orm_session, model_data, add_model
from app.sales.customer_scope import require_customer, is_admin

router = APIRouter(prefix='/api/v1/customers')


class CustomerInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    contact_name: str = Field(default='', max_length=60)
    phone: str = Field(default='', max_length=40)
    address: str = Field(default='', max_length=300)
    note: str = Field(default='', max_length=500)
    owner_id: int | None = Field(default=None, gt=0)
    is_active: bool = True

    @field_validator('name','contact_name','phone','address','note')
    @classmethod
    def trim(cls, value):
        value = value.strip()
        return value


class CustomerUpdate(CustomerInput):
    version: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=200)


class OrderTransfer(BaseModel):
    owner_id: int = Field(gt=0)
    version: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=200)


def customer_access(user: dict = Depends(current_user)) -> dict:
    # 资料查看与共享订单查看分离，旧销售查看权限不再授予客户档案访问。
    if not is_admin(user) and 'customer.view' not in user['permissions'] and 'customer.manage' not in user['permissions']:
        raise HTTPException(403, '没有查看客户资料的权限')
    return user


def owner_check(db: Session, owner_id: int | None):
    if owner_id is not None:
        person = db.get(User, owner_id)
        if person is None or not person.is_active:
            raise HTTPException(422, '负责商务不存在或已停用')


def customer_data(db: Session, customer_id: int) -> dict:
    customer = db.get(Customer, customer_id)
    profile = db.get(CustomerProfile, customer_id)
    owner = db.get(User, profile.owner_id) if profile.owner_id else None
    return {'id': customer.id, 'name': customer.name, **model_data(profile),
            'owner_name': (owner.full_name or owner.username) if owner else '待分配'}


def audit(db: Session, customer_id: int, user: dict, action: str, before: dict | None, after: dict, reason: str, order_id=None):
    # 审计与修改同事务提交；失败时连档案或订单归属一起回滚。
    db.add(CustomerChange(customer_id=customer_id, order_id=order_id, action=action,
        before_json=json.dumps(before, ensure_ascii=False) if before else None,
        after_json=json.dumps(after, ensure_ascii=False), reason=reason.strip(), changed_by=user['id']))


@router.get('')
def list_customers(user: dict = Depends(customer_access)) -> list[dict]:
    with orm_session() as db:
        stmt = select(Customer.id).join(CustomerProfile, CustomerProfile.customer_id == Customer.id)
        if not is_admin(user):
            stmt = stmt.where(CustomerProfile.owner_id == user['id'])
        return [customer_data(db, cid) for cid in db.scalars(stmt.order_by(Customer.name, Customer.id))]


@router.get('/{customer_id}')
def get_customer(customer_id: int, user: dict = Depends(customer_access)) -> dict:
    with orm_session() as db:
        require_customer(db, customer_id, user)
        return customer_data(db, customer_id)


@router.get('/{customer_id}/history')
def customer_history(customer_id: int, user: dict = Depends(customer_access)) -> list[dict]:
    with orm_session() as db:
        require_customer(db, customer_id, user)
        # 非管理员不读取转交前的私有资料快照，历史金额归属记录仅管理员可查。
        rows = db.scalars(select(CustomerChange).where(CustomerChange.customer_id == customer_id).order_by(CustomerChange.id.desc()))
        return [model_data(row) if is_admin(user) else {key: getattr(row, key) for key in ('id','action','reason','changed_by','created_at')}
                for row in rows if is_admin(user) or row.order_id is None]


@router.post('', status_code=201)
def create_customer(payload: CustomerInput, user: dict = Depends(require('customer.manage'))) -> dict:
    if not payload.name:
        raise HTTPException(422, '客户名称不能为空')
    with orm_session(write=True) as db:
        owner_id = payload.owner_id if is_admin(user) else user['id']
        if not is_admin(user) and payload.owner_id not in (None, user['id']):
            raise HTTPException(403, '不能给其他商务创建客户')
        owner_check(db, owner_id)
        try:
            customer = add_model(db, Customer(name=payload.name))
            db.add(CustomerProfile(customer_id=customer.id, owner_id=owner_id,
                **payload.model_dump(exclude={'name','owner_id'})))
            db.flush()
        except IntegrityError:
            raise HTTPException(409, '客户名称不可使用，请联系管理员核查') from None
        after = customer_data(db, customer.id)
        audit(db, customer.id, user, 'create', None, after, '新增客户')
        return after


@router.put('/{customer_id}')
def update_customer(customer_id: int, payload: CustomerUpdate, user: dict = Depends(require('customer.manage'))) -> dict:
    if not payload.name or not payload.reason.strip():
        raise HTTPException(422, '客户名称和修改原因不能为空')
    with orm_session(write=True) as db:
        profile = require_customer(db, customer_id, user)
        if profile.version != payload.version:
            raise HTTPException(409, '客户已被修改，请刷新后重试')
        before = customer_data(db, customer_id)
        if not is_admin(user) and payload.owner_id not in (None, profile.owner_id):
            raise HTTPException(403, '只有管理员可以转交客户')
        owner_id = payload.owner_id if is_admin(user) else profile.owner_id
        owner_check(db, owner_id)
        profile.owner_id = owner_id
        for key, value in payload.model_dump(exclude={'name','owner_id','version','reason'}).items():
            setattr(profile, key, value)
        profile.version += 1
        db.get(Customer, customer_id).name = payload.name
        try:
            db.flush()
        except IntegrityError:
            raise HTTPException(409, '客户名称不可使用，请联系管理员核查') from None
        after = customer_data(db, customer_id)
        audit(db, customer_id, user, 'transfer' if before['owner_id'] != owner_id else 'update', before, after, payload.reason)
        return after


@router.put('/orders/{order_id}/owner')
def transfer_order(order_id: int, payload: OrderTransfer, user: dict = Depends(require('users.manage'))) -> dict:
    # 仅内置管理员可转交订单，客户转交不会触发此操作。
    if not is_admin(user):
        raise HTTPException(403, '只有管理员可以转交订单')
    if not payload.reason.strip():
        raise HTTPException(422, '转交原因不能为空')
    with orm_session(write=True) as db:
        order = db.get(SalesOrder, order_id)
        owner = db.get(SalesOrderOwner, order_id)
        if order is None or owner is None:
            raise HTTPException(404, '订单不存在')
        if owner.version != payload.version:
            raise HTTPException(409, '订单归属已变更，请刷新后重试')
        owner_check(db, payload.owner_id)
        before = model_data(owner)
        owner.owner_id = payload.owner_id
        owner.version += 1
        db.flush()
        audit(db, order.customer_id, user, 'order_transfer', before, model_data(owner), payload.reason, order_id)
        return model_data(owner)
