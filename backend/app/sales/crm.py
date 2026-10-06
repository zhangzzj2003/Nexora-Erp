"""客户联系人、待办跟进与销售商机；变更保留前后版本。"""

from app.core.document_responses import NumberedRoute
import json
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, field_validator
from sqlalchemy import select, func

from app.access.security import require
from app.catalog.material_rules import material_choice_data
from app.core.models import CrmContact, CrmActivity, CrmOpportunity, CrmQuote, CrmChange, Customer, Material, User, SalesOrder
from app.core.orm import orm_session, add_model, model_data
from app.sales.crm_rules import StrictInput, VersionInput, valid_date, validate_amount, get_record, require_customer, require_contact, require_owner, record_data, raw_data, audit, copy_fields
from app.sales.customer_scope import visible_customers

router = APIRouter(route_class=NumberedRoute, prefix='/api/v1/crm')
CONTACT_FIELDS = ('name','job_title','phone','email','note','is_active')
OPPORTUNITY_FIELDS = ('contact_id','title','owner_id','stage','estimated_amount','expected_close_date','note')


class ContactInput(StrictInput):
    customer_id: int = Field(strict=True, gt=0)
    name: str = Field(min_length=1, max_length=120)
    job_title: str = Field(default='', max_length=120)
    phone: str = Field(default='', max_length=80)
    email: str = Field(default='', max_length=160)
    note: str = Field(default='', max_length=1000)
    is_active: bool = Field(default=True, strict=True)


class ContactEdit(ContactInput, VersionInput):
    pass


class OpportunityInput(StrictInput):
    customer_id: int = Field(strict=True, gt=0)
    contact_id: int | None = Field(default=None, strict=True, gt=0)
    title: str = Field(min_length=1, max_length=160)
    owner_id: int = Field(strict=True, gt=0)
    stage: Literal['prospect','qualified','proposal','negotiation','lost'] = 'prospect'
    estimated_amount: Decimal
    probability_percent: int | None = Field(default=None, strict=True, ge=0, le=100)
    expected_close_date: str
    note: str = Field(default='', max_length=1000)
    _date = field_validator('expected_close_date')(valid_date)
    _amount = field_validator('estimated_amount')(validate_amount)


class OpportunityEdit(OpportunityInput, VersionInput):
    pass


class ActivityInput(StrictInput):
    customer_id: int = Field(strict=True, gt=0)
    contact_id: int | None = Field(default=None, strict=True, gt=0)
    opportunity_id: int | None = Field(default=None, strict=True, gt=0)
    subject: str = Field(min_length=1, max_length=160)
    owner_id: int = Field(strict=True, gt=0)
    due_date: str
    note: str = Field(default='', max_length=1000)
    _date = field_validator('due_date')(valid_date)


@router.get('/options')
def options(user: dict = Depends(require('crm.view'))):
    with orm_session() as db:
        return {'customers': [dict(id=row.id,name=row.name,owner_id=row.owner_id,version=row.version)
            for row in db.scalars(visible_customers(select(Customer).order_by(Customer.name),user))],
            'materials': [material_choice_data(row) for row in db.scalars(select(Material).order_by(Material.sku))],
            'owners': [dict(id=row.id,name=row.full_name or row.username) for row in db.scalars(select(User)
                .where(User.is_active == 1).order_by(User.username))]}


@router.get('/overview')
def overview(user: dict = Depends(require('crm.view'))):
    with orm_session() as db:
        return {key: [record_data(db, kind, row) for row in db.scalars(visible_customers(
            select(model).join(Customer, Customer.id == model.customer_id).order_by(model.id.desc()), user))]
            for key,kind,model in (('contacts','contact',CrmContact),('activities','activity',CrmActivity),
                ('opportunities','opportunity',CrmOpportunity),('quotes','quote',CrmQuote))}


@router.get('/records/{kind}/{identifier}')
def detail(kind: Literal['contact','activity','opportunity','quote'], identifier: int,
           user: dict = Depends(require('crm.view'))):
    with orm_session() as db:
        return record_data(db, kind, get_record(db,kind,identifier,user=user))


@router.get('/records/{kind}/{identifier}/changes')
def changes(kind: Literal['contact','activity','opportunity','quote'], identifier: int,
            user: dict = Depends(require('crm.view'))):
    with orm_session() as db:
        get_record(db,kind,identifier,user=user)
        return [{**model_data(row), 'before': json.loads(row.before_json) if row.before_json else None,
            'after': json.loads(row.after_json), 'changed_by_name': name}
            for row,name in db.execute(select(CrmChange,User.username).join(User,User.id == CrmChange.changed_by)
                .where(CrmChange.entity_kind == kind,CrmChange.entity_id == identifier).order_by(CrmChange.id.desc()))]


@router.post('/contacts', status_code=201)
def create_contact(payload: ContactInput, user: dict = Depends(require('crm_contact.manage'))):
    with orm_session(write=True) as db:
        require_customer(db,payload.customer_id,user)
        row = add_model(db,CrmContact(**payload.model_dump(), version=1, created_by=user['id']))
        audit(db,'contact',row,'create',None,'建立联系人',user['id'])
        return record_data(db,'contact',row)


@router.put('/contacts/{identifier}')
def edit_contact(identifier: int, payload: ContactEdit, user: dict = Depends(require('crm_contact.manage'))):
    with orm_session(write=True) as db:
        row = get_record(db,'contact',identifier,payload.version,user)
        if row.customer_id != payload.customer_id:
            raise HTTPException(409,'联系人的所属客户不可修改，请停用后另建')
        before = raw_data(db,'contact',row)
        copy_fields(row,payload,CONTACT_FIELDS)
        row.version += 1
        audit(db,'contact',row,'edit',before,payload.reason,user['id'])
        return record_data(db,'contact',row)


@router.post('/opportunities', status_code=201)
def create_opportunity(payload: OpportunityInput, user: dict = Depends(require('crm_opportunity.manage'))):
    with orm_session(write=True) as db:
        if payload.stage == 'lost':
            raise HTTPException(422,'新商机须从开放阶段建立，丢单请在后续变更时填写原因')
        require_customer(db,payload.customer_id,user)
        require_contact(db,payload.customer_id,payload.contact_id)
        require_owner(db,payload.owner_id)
        row = CrmOpportunity(customer_id=payload.customer_id,version=1,created_by=user['id'])
        copy_fields(row,payload,OPPORTUNITY_FIELDS)
        row.probability_percent = payload.probability_percent
        add_model(db,row)
        audit(db,'opportunity',row,'create',None,'建立商机',user['id'])
        return record_data(db,'opportunity',row)


@router.put('/opportunities/{identifier}')
def edit_opportunity(identifier: int, payload: OpportunityEdit, user: dict = Depends(require('crm_opportunity.manage'))):
    with orm_session(write=True) as db:
        row = get_record(db,'opportunity',identifier,payload.version,user)
        if row.customer_id != payload.customer_id:
            raise HTTPException(409,'商机的所属客户不可修改')
        if row.stage == 'won':
            raise HTTPException(409,'已转单商机只能在所有来源订单取消后重开')
        if row.stage == 'lost' and payload.stage != 'lost':
            raise HTTPException(409,'已丢单商机须先填写原因重开，再修改阶段')
        if payload.stage == 'lost' and db.scalar(select(CrmQuote.id).where(CrmQuote.opportunity_id == identifier,
                CrmQuote.status.in_(('submitted','approved'))).limit(1)):
            raise HTTPException(409,'请先取消待审核或已批准的报价，再登记丢单')
        require_contact(db,row.customer_id,payload.contact_id)
        require_owner(db,payload.owner_id)
        before = raw_data(db,'opportunity',row)
        copy_fields(row,payload,OPPORTUNITY_FIELDS)
        # 旧版客户端未提交概率时保留原评估；明确提交 null 才清空。
        if 'probability_percent' in payload.model_fields_set:
            row.probability_percent = payload.probability_percent
        row.version += 1
        audit(db,'opportunity',row,'edit',before,payload.reason,user['id'])
        return record_data(db,'opportunity',row)


@router.post('/opportunities/{identifier}/reopen')
def reopen(identifier: int, payload: VersionInput, user: dict = Depends(require('crm_opportunity.manage'))):
    with orm_session(write=True) as db:
        row = get_record(db,'opportunity',identifier,payload.version,user)
        if row.stage not in ('won','lost'):
            raise HTTPException(409,'只可重开已转单或已丢单的商机')
        if db.scalar(select(CrmQuote.id).join(SalesOrder,SalesOrder.id == CrmQuote.sales_order_id)
                .where(CrmQuote.opportunity_id == identifier,SalesOrder.status != 'cancelled').limit(1)):
            raise HTTPException(409,'关联销售订单尚未取消，不可重开')
        before = raw_data(db,'opportunity',row)
        row.stage = 'prospect'
        row.probability_percent = None
        row.version += 1
        audit(db,'opportunity',row,'reopen',before,payload.reason,user['id'])
        return record_data(db,'opportunity',row)


@router.post('/activities', status_code=201)
def create_activity(payload: ActivityInput, user: dict = Depends(require('crm_activity.manage'))):
    with orm_session(write=True) as db:
        require_customer(db,payload.customer_id,user)
        require_contact(db,payload.customer_id,payload.contact_id)
        require_owner(db,payload.owner_id)
        if payload.opportunity_id:
            opportunity = get_record(db,'opportunity',payload.opportunity_id,user=user)
            if opportunity.customer_id != payload.customer_id:
                raise HTTPException(422,'跟进商机须属于该客户')
        row = add_model(db,CrmActivity(**payload.model_dump(),status='planned',result='',version=1,created_by=user['id']))
        audit(db,'activity',row,'create',None,'安排跟进',user['id'])
        return record_data(db,'activity',row)


@router.post('/activities/{identifier}/{action}')
def close_activity(identifier: int, action: Literal['complete','cancel'], payload: VersionInput,
                   user: dict = Depends(require('crm_activity.manage'))):
    with orm_session(write=True) as db:
        row = get_record(db,'activity',identifier,payload.version,user)
        if row.status != 'planned':
            raise HTTPException(409,'跟进已结束，不可重复处理；更正请另建跟进')
        before = raw_data(db,'activity',row)
        row.status = 'completed' if action == 'complete' else 'cancelled'
        row.result = payload.reason
        row.closed_by = user['id']
        row.closed_at = func.current_timestamp()
        row.version += 1
        audit(db,'activity',row,action,before,payload.reason,user['id'])
        return record_data(db,'activity',row)
