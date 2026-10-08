"""销售售后退换修；客户物品保管与公司库存严格分开。"""

from app.core.document_responses import NumberedRoute
from app.core.document_approval import record_author
from app.core import document_approval as approval
from app.core.approval_documents import after_sales_snapshot
import json
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select

from app.access.security import require
from app.catalog.material_rules import material_choice_data
from app.core.models import (AfterSalesCase, AfterSalesCustody, Shipment, ShipmentLine, SalesReturn, SalesReturnLine,
    SalesReturnReversal, SalesOrder, SalesOrderLine, Material, Warehouse, WarehouseOutbound,
    WarehouseOutboundLine)
from app.core.orm import orm_session, add_model, model_data
from app.core.period_lock import ensure_date_unlocked
from app.inventory.warehouse import require_warehouse
from app.sales.after_sales_rules import (now, encoded, source, remaining_quantity, check_quantity,
    case_data, audit, authors, return_effective)
from app.sales.customer_scope import (visible_customer_ids, require_visible_shipment_line,
    require_visible_after_sales)

router = APIRouter(route_class=NumberedRoute, prefix='/api/v1/after-sales')


def quantity(value):
    if not value.is_finite() or value <= 0 or value > 1_000_000 or value.as_tuple().exponent < -3:
        raise ValueError('数量须大于零、最多三位小数且不超过一百万')
    return value


def price(value, digits):
    if value is not None and (not value.is_finite() or value < 0 or value > 1_000_000_000 or value.as_tuple().exponent < -digits):
        raise ValueError(f'金额须非负且最多 {digits} 位小数')
    return value


class RepairPart(BaseModel):
    model_config = ConfigDict(extra='forbid')
    material_id: int = Field(gt=0, strict=True)
    quantity: Decimal
    _quantity = field_validator('quantity')(quantity)


class CaseInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    shipment_line_id: int = Field(gt=0, strict=True)
    reference: str = Field(min_length=1, max_length=100)
    kind: Literal['return','exchange','repair']
    quantity: Decimal
    complaint: str = Field(min_length=1, max_length=400)
    solution: str = Field(min_length=1, max_length=400)
    charge_mode: Literal['none','free','charge']
    fee_amount: Decimal
    customer_acceptance: str = Field(min_length=1, max_length=400)
    warranty_days: int | None = Field(default=None, ge=1, le=36500, strict=True)
    warranty_basis: str = Field(default='', max_length=400)
    warehouse_id: int | None = Field(default=None, gt=0, strict=True)
    replacement_material_id: int | None = Field(default=None, gt=0, strict=True)
    replacement_quantity: Decimal | None = None
    replacement_unit_price: Decimal | None = None
    parts: list[RepairPart] = Field(default_factory=list, max_length=100)
    reason: str = Field(min_length=1, max_length=200)
    _quantity = field_validator('quantity')(quantity)

    @field_validator('replacement_quantity')
    @classmethod
    def replacement_qty(cls, value):
        return quantity(value) if value is not None else None

    @field_validator('fee_amount')
    @classmethod
    def fee(cls, value):
        return price(value, 2)

    @field_validator('replacement_unit_price')
    @classmethod
    def replacement_price(cls, value):
        return price(value, 4)

    @field_validator('reference','complaint','solution','customer_acceptance','reason')
    @classmethod
    def trim_text(cls, value):
        if not value.strip():
            raise ValueError('依据、诉求、方案、客户同意及原因不能为空')
        return value.strip()

    @field_validator('warranty_basis')
    @classmethod
    def trim_warranty_basis(cls, value):
        return value.strip()

    @model_validator(mode='after')
    def explicit_plan(self):
        if (self.warranty_days is None) != (self.warranty_basis == ''):
            raise ValueError('保修天数和合同依据须同时填写，未确认条款时两者均留空')
        if self.kind == 'repair':
            if self.charge_mode not in ('free','charge') or (self.charge_mode=='free' and self.fee_amount != 0) or (
                self.charge_mode=='charge' and self.fee_amount <= 0):
                raise ValueError('维修须明确免费或收费，免费金额为零，收费金额须大于零')
            if any(value is not None for value in (self.replacement_material_id,self.replacement_quantity,self.replacement_unit_price)):
                raise ValueError('维修不能填写换货物料或价格')
            if self.parts and self.warehouse_id is None:
                raise ValueError('维修耗材须指定公司出库仓')
        else:
            if self.charge_mode != 'none' or self.fee_amount != 0 or self.parts or self.warehouse_id is None:
                raise ValueError('退换货须选择退回仓，不填写维修费用或耗材')
            replacement = (self.replacement_material_id,self.replacement_quantity,self.replacement_unit_price)
            if self.kind == 'exchange' and any(value is None for value in replacement):
                raise ValueError('换货须明确替换物料、数量与销售价格，不自动抵销价差')
            if self.kind == 'return' and any(value is not None for value in replacement):
                raise ValueError('退货不能填写替换销售明细')
        if len({line.material_id for line in self.parts}) != len(self.parts):
            raise ValueError('维修耗材不能重复')
        return self


class CaseEdit(CaseInput):
    version: int = Field(gt=0, strict=True)


class CaseAction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: int = Field(gt=0, strict=True)
    reason: str = Field(min_length=1, max_length=200)
    evidence: str = Field(default='', max_length=400)
    inspection_result: Literal['pass','fail'] | None = None
    _trim_reason = field_validator('reason')(CaseInput.trim_text.__func__)


def get_case(db, case_id, version=None):
    row = db.get(AfterSalesCase, case_id)
    if row is None:
        raise HTTPException(404, '售后单不存在')
    if version is not None and row.version != version:
        raise HTTPException(409, '售后版本已变化，请刷新后核对；本次输入未生效')
    return row


def apply_input(db, row, payload):
    if db.scalar(select(AfterSalesCase.id).where(AfterSalesCase.reference==payload.reference,
        AfterSalesCase.id != (row.id or 0))):
        raise HTTPException(409, '售后依据编号已使用，请使用新编号并保留历史')
    original = source(db, payload.shipment_line_id, writable=True)
    if original['warranty_days'] is not None:
        if (payload.warranty_days, payload.warranty_basis) not in (
            (None, ''), (original['warranty_days'], original['warranty_basis'])
        ):
            raise HTTPException(409, '售后保修条款与原销售订单不一致，请刷新来源证据')
    if payload.warehouse_id:
        require_warehouse(db, payload.warehouse_id)
    if payload.replacement_material_id:
        replacement=db.get(Material,payload.replacement_material_id)
        if replacement is None:
            raise HTTPException(422, '替换物料不存在')
        original['replacement']=dict(material_id=replacement.id,sku=replacement.sku,material_name=replacement.name,
            unit=replacement.unit,quantity=str(payload.replacement_quantity),unit_price=str(payload.replacement_unit_price))
    parts = []
    for part in payload.parts:
        material = db.get(Material, part.material_id)
        if material is None:
            raise HTTPException(422, '维修耗材不存在')
        parts.append(dict(material_id=material.id, sku=material.sku, material_name=material.name,
            unit=material.unit, quantity=str(part.quantity)))
    for key in ('shipment_line_id','reference','kind','complaint','solution','charge_mode',
        'customer_acceptance','warehouse_id','replacement_material_id','warranty_days','warranty_basis'):
        setattr(row, key, getattr(payload,key))
    if original['warranty_days'] is not None:
        # 合同条款来自原订单；旧客户端留空时也按服务端来源固定证据。
        row.warranty_days = original['warranty_days']
        row.warranty_basis = original['warranty_basis']
    for key in ('quantity','fee_amount','replacement_quantity','replacement_unit_price'):
        value = getattr(payload,key)
        setattr(row, key, str(value) if value is not None else None)
    row.fee_amount = str(payload.fee_amount.quantize(Decimal('0.01')))
    row.source_json, row.parts_json = encoded(original), encoded(parts)
    check_quantity(db, row)


@router.get('')
def overview(user: dict=Depends(require('after_sales.view'))):
    with orm_session() as db:
        sources = []
        for identifier in db.scalars(select(ShipmentLine.id).join(Shipment,
                Shipment.id == ShipmentLine.shipment_id).join(SalesOrder,
                SalesOrder.id == Shipment.sales_order_id).where(
                SalesOrder.customer_id.in_(visible_customer_ids(user))).order_by(ShipmentLine.id.desc())):
            item = source(db,identifier)
            if item['valid']:
                sources.append({**item,'remaining_quantity':str(remaining_quantity(db,identifier))})
        return dict(sources=sources, cases=[case_data(db,row) for row in db.scalars(
            select(AfterSalesCase).join(ShipmentLine,
                ShipmentLine.id == AfterSalesCase.shipment_line_id).join(Shipment,
                Shipment.id == ShipmentLine.shipment_id).join(SalesOrder,
                SalesOrder.id == Shipment.sales_order_id).where(
                SalesOrder.customer_id.in_(visible_customer_ids(user))).order_by(AfterSalesCase.id.desc()))],
            materials=[material_choice_data(row) for row in db.scalars(select(Material))],
            warehouses=[dict(id=row.id,name=row.name) for row in db.scalars(select(Warehouse))])


@router.get('/cases/{case_id}')
def detail(case_id: int, user: dict=Depends(require('after_sales.view'))):
    with orm_session() as db:
        return case_data(db,require_visible_after_sales(db,get_case(db,case_id),user))


@router.post('/cases',status_code=201)
def create(payload: CaseInput, user: dict=Depends(require('after_sales.create'))):
    with orm_session(write=True) as db:
        require_visible_shipment_line(db, payload.shipment_line_id, user)
        row=AfterSalesCase(status='draft',version=1,created_by=user['id'])
        apply_input(db,row,payload)
        add_model(db,row)
        audit(db,row,'create',None,user['id'],payload.reason)
        return case_data(db,row)


@router.put('/cases/{case_id}')
def edit(case_id: int,payload: CaseEdit,user: dict=Depends(require('after_sales.create'))):
    with orm_session(write=True) as db:
        row=require_visible_after_sales(db,get_case(db,case_id),user)
        if row.version != payload.version:
            raise HTTPException(409,'售后版本已变化，请刷新后核对；本次输入未生效')
        require_visible_shipment_line(db, payload.shipment_line_id, user)
        if row.status not in ('draft','rejected'):
            raise HTTPException(409,'只有草稿或驳回申请可修订')
        before=model_data(row)
        record_author(db, 'AfterSalesCase', row.id, user['id'])
        apply_input(db,row,payload)
        row.status='draft'; row.version+=1
        audit(db,row,'edit',before,user['id'],payload.reason)
        return case_data(db,row)


def prepare_approval_action(db, row, action, user, reason):
    # 统一审批使用原领域约束和同一事务；售后原操作依据仍限定二百字。
    if action in ('submit', 'approve', 'reject') and (not reason.strip() or len(reason.strip()) > 200):
        raise HTTPException(422, '售后送审与审核依据必填，最多二百字')
    before = model_data(row)
    if action in ('submit', 'approve'):
        check_quantity(db, row)
    if action == 'submit':
        original = source(db, row.shipment_line_id, writable=True)
        if row.kind == 'exchange':
            replacement = db.get(Material, row.replacement_material_id)
            if replacement is None:
                raise HTTPException(409, '换货物料已失效，请撤回后核对')
            original['replacement'] = dict(material_id=replacement.id, sku=replacement.sku,
                material_name=replacement.name, unit=replacement.unit,
                quantity=row.replacement_quantity, unit_price=row.replacement_unit_price)
        row.source_json = encoded(original)
        db.flush()
    return before


def sync_approval_action(db, row, action, state, user_id, reason, before):
    # 中间审核步骤仍占用数量；撤回释放预约量，原人员与每步意见留在追加审计。
    row.status = 'draft' if action == 'withdraw' else state['status']
    if action == 'submit':
        row.submitted_by, row.submitted_at = state['submitted_by'], state['submitted_at']
        row.reviewed_by = row.reviewed_at = None
    elif action in ('approve', 'reject'):
        row.reviewed_by, row.reviewed_at = user_id, now()
    row.version += 1
    audit(db, row, action, before, user_id, reason.strip() or '撤回售后方案审批')


def permission(user, *codes):
    if any(code not in user['permissions'] for code in codes):
        raise HTTPException(403,'缺少关联单据办理权限：'+ '、'.join(codes))


def evidence(payload):
    if not payload.evidence.strip():
        raise HTTPException(422,'请填写实际交接、检验或客户确认依据')
    return payload.evidence.strip()


@router.post('/cases/{case_id}/{action}')
def change(case_id: int, action: Literal['submit','approve','reject','process','receive','inspect','close','cancel','reverse'],
    payload: CaseAction, user: dict=Depends(require('after_sales.view'))):
    permission(user,'after_sales.review' if action in ('approve','reject') else 'after_sales.'+action)
    if action!='inspect' and payload.inspection_result is not None:
        raise HTTPException(422,'只有维修检验操作可填写检验结果')
    with orm_session(write=True) as db:
        row=require_visible_after_sales(db,get_case(db,case_id),user)
        if row.version != payload.version:
            raise HTTPException(409,'售后版本已变化，请刷新后核对；本次输入未生效')
        before=model_data(row)
        # 旧客户端保留原领域权限及业务版本，但不得跳过当前实例的审批步骤。
        if action in ('submit', 'approve', 'reject'):
            raise HTTPException(409, '请从单据审批入口按当前审批版本操作')
        approved = None
        if action in ('process', 'receive') and row.status == 'approved':
            approved = approval.require_approved(db, 'AfterSalesCase', row.id,
                after_sales_snapshot(db, row.id), user['id'], permission='after_sales.' + action)
        if action == 'reverse' and row.status == 'closed':
            approved = approval.require_approved(db, 'AfterSalesCase', row.id,
                {'document': after_sales_snapshot(db, row.id), 'reversal_reason': payload.reason.strip()},
                user['id'], intent='reverse', permission='after_sales.reverse')
        if action == 'cancel' and approval.find_case(db, 'AfterSalesCase', row.id) is not None:
            pending = approval.find_case(db, 'AfterSalesCase', row.id)
            if pending.status in ('submitted', 'approved'):
                raise HTTPException(409, '请先撤回售后审批再取消方案')
        if action=='process' and row.status=='approved' and row.kind in ('return','exchange'):
            permission(user,'sales_return.create')
            if row.kind=='exchange':
                permission(user,'sales_order.create')
            check_quantity(db,row); original=source(db,row.shipment_line_id,writable=True)
            returned=add_model(db,SalesReturn(shipment_id=original['shipment_id'],warehouse_id=row.warehouse_id,
                reason=f'售后 {row.reference}：{row.complaint}'[:200],created_by=user['id']))
            db.add(SalesReturnLine(sales_return_id=returned.id,shipment_line_id=row.shipment_line_id,quantity=row.quantity))
            row.sales_return_id=returned.id
            if row.kind=='exchange':
                order=add_model(db,SalesOrder(customer_id=original['customer_id'],reference=f'售后换货 {row.reference}',created_by=user['id']))
                db.add(SalesOrderLine(sales_order_id=order.id,material_id=row.replacement_material_id,
                    quantity=row.replacement_quantity,unit_price=row.replacement_unit_price))
                row.replacement_order_id=order.id
            row.status='processing'
        elif action=='receive' and row.status=='approved' and row.kind=='repair':
            proof=evidence(payload); check_quantity(db,row)
            parts=json.loads(row.parts_json)
            if parts:
                permission(user,'other_outbound.create')
                outbound=add_model(db,WarehouseOutbound(warehouse_id=row.warehouse_id,source_kind='other',
                    reason='other',note=f'售后维修耗材 {row.reference}'[:200],reference=row.reference,created_by=user['id']))
                db.add_all([WarehouseOutboundLine(outbound_id=outbound.id,material_id=part['material_id'],quantity=part['quantity']) for part in parts])
                row.parts_outbound_id=outbound.id
                # 耗材子单独立送审，原售后方案作者继续存证，审批按子单当前步骤按钮权限办理。
                for author_id in after_sales_snapshot(db, row.id)['source_author_ids']:
                    if author_id is not None:
                        record_author(db, 'WarehouseOutbound', outbound.id, author_id)
            db.add(AfterSalesCustody(case_id=row.id,action='receive',quantity=row.quantity,evidence=proof,created_by=user['id']))
            row.status='received'
        elif action=='inspect' and row.status=='received' and row.kind=='repair':
            evidence(payload)
            if payload.inspection_result is None:
                raise HTTPException(422,'维修检验须明确合格或不合格')
            if payload.inspection_result=='pass' and row.parts_outbound_id and case_data(db,row)['parts_status']!='posted':
                raise HTTPException(409,'批准维修方案的耗材须有效确认出库后才能检验合格')
            if payload.inspection_result=='pass':
                row.status='repaired'
        elif action=='close' and row.status in ('processing','repaired'):
            proof=evidence(payload)
            if row.kind=='repair':
                if row.parts_outbound_id and case_data(db,row)['parts_status']!='posted':
                    raise HTTPException(409,'维修耗材来源已更正，请核对后再交付')
                db.add(AfterSalesCustody(case_id=row.id,action='return',quantity=row.quantity,evidence=proof,created_by=user['id']))
            else:
                if not return_effective(db,row):
                    raise HTTPException(409,'关联退货须有效确认入库后才能结案')
                if row.kind=='exchange':
                    from app.sales.orders import sales_order_data
                    order=sales_order_data(db,row.replacement_order_id)
                    if sum((Decimal(line['net_delivered_quantity']) for line in order['lines']),Decimal(0)) < Decimal(row.replacement_quantity):
                        raise HTTPException(409,'换货销售订单尚未足量有效交付')
            row.status='closed'; row.closed_by=user['id']; row.closed_at=now()
        elif action=='cancel' and row.status in ('draft','submitted','approved','rejected','processing','received','repaired'):
            if row.sales_return_id:
                returned=db.get(SalesReturn,row.sales_return_id)
                reversed_return=db.scalar(select(SalesReturnReversal.id).where(SalesReturnReversal.sales_return_id==returned.id))
                if returned.status!='cancelled' and not reversed_return:
                    raise HTTPException(409,'须先取消关联退货草稿或按原流程冲销已确认退货')
            if row.replacement_order_id and db.get(SalesOrder,row.replacement_order_id).status!='cancelled':
                raise HTTPException(409,'须先取消关联换货订单')
            if row.parts_outbound_id and db.get(WarehouseOutbound,row.parts_outbound_id).status=='draft':
                raise HTTPException(409,'须先取消耗材出库草稿，避免遗留可确认单据')
            if row.status in ('received','repaired'):
                permission(user,'after_sales.close')
                db.add(AfterSalesCustody(case_id=row.id,action='return',quantity=row.quantity,
                    evidence=evidence(payload),created_by=user['id']))
            row.status='cancelled'
        elif action=='reverse' and row.status=='closed':
            ensure_date_unlocked(db,row.closed_at)
            if row.kind!='repair':
                if return_effective(db,row) or not db.scalar(select(SalesReturnReversal.id)
                    .where(SalesReturnReversal.sales_return_id==row.sales_return_id)):
                    raise HTTPException(409,'须先按原销售退货流程完成冲销')
                if row.replacement_order_id and db.get(SalesOrder,row.replacement_order_id).status!='cancelled':
                    raise HTTPException(409,'须先更正换货出库并取消换货订单')
            row.status='reversed'; row.reversed_by=user['id']; row.reversed_at=now()
        else:
            raise HTTPException(409,'当前阶段不能执行该售后操作')
        if approved is not None:
            # 实际办理、关联草稿和审批执行事件一起提交，任何异常都整体回滚。
            approval.mark_executed(db, approved, user['id'], permission='after_sales.' + action)
        row.version+=1
        audit(db,row,'inspect_'+payload.inspection_result if action=='inspect' else action,
            before,user['id'],payload.reason,payload.evidence.strip())
        return case_data(db,row)
