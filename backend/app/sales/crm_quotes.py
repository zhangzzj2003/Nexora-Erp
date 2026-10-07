"""报价冻结、独立审批及同事务转销售草稿，原报价保留。"""

from app.core.document_responses import NumberedRoute
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, field_validator
from sqlalchemy import delete, select, func
from sqlalchemy.exc import IntegrityError

from app.core import document_approval as approval
from app.core.approval_documents import current_snapshot
from app.access.security import require
from app.core.models import CrmQuote, CrmQuoteLine, CrmChange, Material
from app.core.orm import orm_session, add_model
from app.purchase.orders import PurchaseOrderLineInput
from app.sales.orders import SalesOrderInput, create_sales_order_in_session
from app.sales.crm_rules import StrictInput, VersionInput, valid_date, today, json_text, get_record, require_customer, require_contact, require_open_opportunity, raw_data, record_data, audit

router = APIRouter(route_class=NumberedRoute, prefix='/api/v1/crm/quotes')


class QuoteLineInput(StrictInput):
    material_id: int = Field(strict=True, gt=0)
    quantity: Decimal
    unit_price: Decimal

    @field_validator('quantity')
    @classmethod
    def quantity_rule(cls, value: Decimal):
        return PurchaseOrderLineInput.valid_quantity(value)

    @field_validator('unit_price')
    @classmethod
    def price_rule(cls, value: Decimal):
        return PurchaseOrderLineInput.valid_unit_price(value)


class QuoteInput(StrictInput):
    opportunity_id: int = Field(strict=True, gt=0)
    contact_id: int | None = Field(default=None, strict=True, gt=0)
    reference: str = Field(min_length=1, max_length=100)
    valid_until: str
    terms: str = Field(default='', max_length=1000)
    lines: list[QuoteLineInput] = Field(min_length=1, max_length=100)
    _date = field_validator('valid_until')(valid_date)


class QuoteEdit(QuoteInput, VersionInput):
    pass


class QuoteConversion(VersionInput):
    opportunity_version: int = Field(strict=True, gt=0, le=2_147_483_647)
    acceptance_reference: str = Field(min_length=1, max_length=120)


def freeze_party(db, record):
    customer = require_customer(db,record.customer_id)
    contact = require_contact(db,record.customer_id,record.contact_id)
    record.party_json = json_text({'customer_name':customer.name,
        'contact_name':contact.name if contact else '', 'phone':contact.phone if contact else '',
        'email':contact.email if contact else ''})


def write_quote(db, record, payload, user):
    require_open_opportunity(db,record.opportunity_id,user)
    if payload.valid_until < today():
        raise HTTPException(422,'报价有效期不可早于当前业务日')
    if len({line.material_id for line in payload.lines}) != len(payload.lines):
        raise HTTPException(422,'报价不可重复选择同一物料')
    record.contact_id = payload.contact_id
    record.reference = payload.reference
    record.valid_until = payload.valid_until
    record.terms = payload.terms
    freeze_party(db,record)
    materials = []
    for line in payload.lines:
        material = db.get(Material,line.material_id)
        if material is None:
            raise HTTPException(422,'报价物料不存在')
        materials.append(material)
    if record.id is None:
        add_model(db,record)
    else:
        db.execute(delete(CrmQuoteLine).where(CrmQuoteLine.quote_id == record.id))
    db.add_all([CrmQuoteLine(quote_id=record.id,position=position,material_id=line.material_id,
        sku=material.sku,material_name=material.name,unit=material.unit,
        quantity=str(line.quantity),unit_price=str(line.unit_price))
        for position,(line,material) in enumerate(zip(payload.lines,materials),1)])
    db.flush()


@router.post('', status_code=201)
def create_quote(payload: QuoteInput, user: dict = Depends(require('crm_quote.create'))):
    with orm_session(write=True) as db:
        opportunity = require_open_opportunity(db,payload.opportunity_id,user)
        record = CrmQuote(opportunity_id=opportunity.id,customer_id=opportunity.customer_id,
            status='draft',version=1,created_by=user['id'])
        try:
            write_quote(db,record,payload,user)
        except IntegrityError:
            raise HTTPException(409,'报价编号已存在') from None
        audit(db,'quote',record,'create',None,'建立报价',user['id'])
        return record_data(db,'quote',record)


@router.put('/{identifier}')
def edit_quote(identifier: int, payload: QuoteEdit, user: dict = Depends(require('crm_quote.create'))):
    with orm_session(write=True) as db:
        record = get_record(db,'quote',identifier,payload.version,user)
        if record.status not in ('draft','rejected'):
            raise HTTPException(409,'只有草稿或驳回的报价可以修订')
        if record.opportunity_id != payload.opportunity_id:
            raise HTTPException(409,'报价的所属商机不可修改')
        approval.record_author(db, 'CrmQuote', identifier, user['id'])
        before = raw_data(db,'quote',record)
        try:
            write_quote(db,record,payload,user)
        except IntegrityError:
            raise HTTPException(409,'报价编号已存在') from None
        record.status = 'draft'
        record.submitted_by = record.reviewed_by = None
        record.submitted_at = record.reviewed_at = None
        record.version += 1
        audit(db,'quote',record,'edit',before,payload.reason,user['id'])
        return record_data(db,'quote',record)


def prepare_approval_action(db, record, action, user, reason):
    # 沿用领域前置检查；先冻结报价资料再计算送审摘要，避免审批正文与原报价不同。
    if action in ('submit', 'approve', 'reject') and not reason.strip():
        raise HTTPException(422, '报价送审与审核须填写操作依据')
    before = raw_data(db, 'quote', record)
    if action in ('submit', 'approve'):
        require_open_opportunity(db, record.opportunity_id, user)
        require_contact(db, record.customer_id, record.contact_id)
        if record.valid_until < today():
            raise HTTPException(409, '报价已过期，请撤回并修订有效期')
    if action == 'submit':
        freeze_party(db, record)
        for line in db.scalars(select(CrmQuoteLine).where(CrmQuoteLine.quote_id == record.id)):
            material = db.get(Material, line.material_id)
            line.sku, line.material_name, line.unit = material.sku, material.name, material.unit
        db.flush()
    return before


def sync_approval_action(db, record, action, state, user_id, reason, before):
    # 原业务版本与审批版本各自递增；多步批准期间原状态仍为待审，原审计继续追加保存。
    record.status = 'draft' if action == 'withdraw' else state['status']
    if action == 'submit':
        record.submitted_by, record.submitted_at = state['submitted_by'], state['submitted_at']
        record.reviewed_by = record.reviewed_at = None
    elif action in ('approve', 'reject'):
        record.reviewed_by, record.reviewed_at = user_id, approval.now(db)
    record.version += 1
    audit(db, 'quote', record, action, before, reason.strip() or '撤回报价审批', user_id)


def legacy_review_blocked(db, identifier, payload, user):
    # 旧客户端保留原范围、权限与业务版本检查，但不能绕过统一审批步骤。
    get_record(db, 'quote', identifier, payload.version, user)
    raise HTTPException(409, '请从单据审批入口按当前审批版本操作')


@router.post('/{identifier}/submit')
def submit(identifier: int, payload: VersionInput, user: dict = Depends(require('crm_quote.submit'))):
    with orm_session(write=True) as db:
        legacy_review_blocked(db, identifier, payload, user)


@router.post('/{identifier}/approve')
def approve(identifier: int, payload: VersionInput, user: dict = Depends(require('crm_quote.review'))):
    with orm_session(write=True) as db:
        legacy_review_blocked(db, identifier, payload, user)


@router.post('/{identifier}/reject')
def reject(identifier: int, payload: VersionInput, user: dict = Depends(require('crm_quote.review'))):
    with orm_session(write=True) as db:
        legacy_review_blocked(db, identifier, payload, user)


@router.post('/{identifier}/cancel')
def cancel(identifier: int, payload: VersionInput, user: dict = Depends(require('crm_quote.cancel'))):
    with orm_session(write=True) as db:
        record = get_record(db,'quote',identifier,payload.version,user)
        if record.status in ('cancelled','converted'):
            raise HTTPException(409,'报价已取消或已转单，不可取消')
        approval.record_author(db, 'CrmQuote', identifier, user['id'])
        before = raw_data(db,'quote',record)
        record.status = 'cancelled'
        record.version += 1
        audit(db,'quote',record,'cancel',before,payload.reason,user['id'])
        return record_data(db,'quote',record)


@router.post('/{identifier}/convert')
def convert(identifier: int, payload: QuoteConversion, user: dict = Depends(require('crm_quote.convert')),
            _: dict = Depends(require('sales_order.create'))):
    with orm_session(write=True) as db:
        record = get_record(db,'quote',identifier,payload.version,user)
        if record.status != 'approved':
            raise HTTPException(409,'只有已批准且未转单的报价可以转单')
        approval_case = approval.require_approved(db, 'CrmQuote', identifier,
            current_snapshot(db, 'CrmQuote', identifier), user['id'])
        opportunity = get_record(db,'opportunity',record.opportunity_id,payload.opportunity_version,user)
        require_open_opportunity(db,opportunity.id,user)
        require_contact(db,record.customer_id,record.contact_id)
        if record.valid_until < today():
            raise HTTPException(409,'报价已过期，请建立新报价并重新审核')
        before = raw_data(db,'quote',record)
        opportunity_before = raw_data(db,'opportunity',opportunity)
        order = create_sales_order_in_session(db,SalesOrderInput(customer_id=record.customer_id,
            reference=record.reference, lines=[dict(material_id=line['material_id'],
                quantity=line['quantity'], unit_price=line['unit_price']) for line in before['lines']]),user['id'])
        record.status = 'converted'
        record.sales_order_id = order['id']
        record.acceptance_reference = payload.acceptance_reference
        record.converted_by = user['id']
        record.converted_at = func.current_timestamp()
        record.version += 1
        opportunity.stage = 'won'
        opportunity.version += 1
        audit(db,'quote',record,'convert',before,payload.reason,user['id'])
        audit(db,'opportunity',opportunity,'convert',opportunity_before,payload.reason,user['id'])
        approval.mark_executed(db, approval_case, user['id'])
        return record_data(db,'quote',record)
