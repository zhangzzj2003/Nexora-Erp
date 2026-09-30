"""生产计划与质量处置入口，写锁覆盖排程冲突及不合格数量占用。"""
from datetime import datetime, timezone
from decimal import Decimal
import json
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,Field,field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.access.security import require
from app.core.orm import orm_session,add_model,model_data
from app.core import models as m
from app.core.period_lock import ensure_date_unlocked
from app.finance.tools import parse,snapshot,Reason,Identity
from app.finance.ledger import PeriodInput
from app.production.planning import mrp,wip
from app.production.cost_lock import ensure_unsettled

router=APIRouter(prefix='/api/v1/production/tools')


class Command(BaseModel):
    model_config=ConfigDict(extra='forbid')
    action:Literal['mrp','create_request','policy','create_center','schedule','cancel_schedule','quality','wip']
    payload:dict=Field(default_factory=dict)


class PlanScope(BaseModel):
    model_config=ConfigDict(extra='forbid')
    warehouse_id:int=Field(gt=0,strict=True)
    through_date:str
    @field_validator('through_date')
    @classmethod
    def date(cls,value):return PeriodInput.valid_date(value)


class PolicyInput(Reason):
    material_id:int=Field(gt=0,strict=True)
    warehouse_id:int=Field(gt=0,strict=True)
    safety_quantity:Decimal=Field(ge=0,le=1000000,decimal_places=3)
    lead_days:int=Field(ge=0,le=3650,strict=True)
    version:int=Field(ge=0,strict=True)


class CenterInput(Reason):
    name:str=Field(min_length=1,max_length=80)


class ScheduleInput(Reason):
    id:int|None=Field(default=None,gt=0,strict=True)
    version:int=Field(default=0,ge=0,strict=True)
    work_order_id:int=Field(gt=0,strict=True)
    center_id:int=Field(gt=0,strict=True)
    operation:str=Field(min_length=1,max_length=80)
    starts_at:datetime
    ends_at:datetime
    @field_validator('starts_at','ends_at')
    @classmethod
    def timezone(cls,value):
        if value.tzinfo is None:raise ValueError('排程时间须包含时区')
        return value.astimezone(timezone.utc)


class QualityInput(Reason):
    completion_id:int=Field(gt=0,strict=True)
    kind:Literal['scrap','rework']
    quantity:Decimal=Field(gt=0,le=1000000,decimal_places=3)
    replacements:list[dict]=Field(default_factory=list,max_length=100)


def audit(db,user,kind,identifier,reason,row):
    db.add(m.ProductionPlanAudit(kind=kind,record_id=identifier,evidence_json=json.dumps(row,ensure_ascii=False),reason=reason,created_by=user['id']))


@router.post('')
def command(value:Command,user:dict=Depends(require('production.view'))):
    writing=value.action not in ('mrp','wip')
    permission='production_cost.view' if value.action=='wip' else 'production_completion.inspect' if value.action=='quality' else 'work_order.create'
    if writing or value.action=='wip':require(permission)(user)
    try:
        with orm_session(write=writing) as db:
            if value.action in ('mrp','create_request','wip'):
                data=parse(PlanScope,value.payload)
                if db.get(m.Warehouse,data.warehouse_id) is None:raise HTTPException(422,'仓库不存在')
                if value.action=='wip':
                    result=wip(db,data.through_date);return snapshot(result['rows'],user,result['totals'])
                rows=mrp(db,data.warehouse_id,data.through_date)
                if value.action=='create_request':
                    require('purchase_request.create')(user)
                    shortages=[row for row in rows if Decimal(row['shortage_quantity'])>0]
                    if not shortages:raise HTTPException(409,'当前没有采购缺口')
                    if len(shortages)>100:raise HTTPException(422,'缺料超过一百种，请按仓库或物料拆分申请')
                    request=add_model(db,m.PurchaseRequest(reference=f'MRP {data.through_date}',note='物料计划生成，请按公司审批流程核对',created_by=user['id']))
                    for row in shortages:db.add(m.PurchaseRequestLine(purchase_request_id=request.id,material_id=row['material_id'],quantity=row['shortage_quantity']))
                    audit(db,user,'mrp_request',request.id,'物料计划转采购申请',{'warehouse_id':data.warehouse_id,'rows':shortages})
                    return snapshot([{'request_id':request.id,'status':'草稿','material_count':len(shortages)}],user)
                return snapshot(rows,user,{'shortage_materials':str(sum(Decimal(row['shortage_quantity'])>0 for row in rows))})
            if value.action=='policy':
                data=parse(PolicyInput,value.payload)
                if db.get(m.Material,data.material_id) is None or db.get(m.Warehouse,data.warehouse_id) is None:raise HTTPException(422,'物料或仓库不存在')
                row=db.get(m.MaterialPlanningPolicy,(data.material_id,data.warehouse_id))
                if data.version!=(row.version if row else 0):raise HTTPException(409,'计划参数已变化，请刷新后保存')
                if row is None:row=add_model(db,m.MaterialPlanningPolicy(material_id=data.material_id,warehouse_id=data.warehouse_id,safety_quantity=str(data.safety_quantity),lead_days=data.lead_days,version=1))
                else:row.safety_quantity=str(data.safety_quantity);row.lead_days=data.lead_days;row.version+=1
                audit(db,user,'planning_policy',row.material_id,data.reason,model_data(row));return snapshot([model_data(row)],user)
            if value.action=='create_center':
                data=parse(CenterInput,value.payload)
                if not data.name.strip():raise HTTPException(422,'工作中心名称不能为空')
                row=add_model(db,m.WorkCenter(name=data.name.strip(),is_active=1));audit(db,user,'center',row.id,data.reason,model_data(row));return snapshot([model_data(row)],user)
            if value.action in ('schedule','cancel_schedule'):
                data=parse(Identity if value.action=='cancel_schedule' else ScheduleInput,value.payload)
                if value.action=='cancel_schedule':
                    row=db.get(m.ProductionSchedule,data.id)
                    if row is None or row.status!='planned':raise HTTPException(409,'排程不存在或已取消')
                    ensure_date_unlocked(db,row.starts_at);row.status='cancelled';row.version+=1
                else:
                    order=db.get(m.WorkOrder,data.work_order_id);center=db.get(m.WorkCenter,data.center_id)
                    if order is None or order.status in ('cancelled','completed') or center is None or not center.is_active:raise HTTPException(409,'请选择有效未完成工单和启用工作中心')
                    if data.ends_at<=data.starts_at:raise HTTPException(422,'结束时间须晚于开始时间')
                    start,end=data.starts_at.isoformat(),data.ends_at.isoformat();ensure_date_unlocked(db,start)
                    conflicts=select(m.ProductionSchedule.id).where(m.ProductionSchedule.status=='planned',m.ProductionSchedule.center_id==data.center_id,m.ProductionSchedule.starts_at<end,m.ProductionSchedule.ends_at>start)
                    if data.id:conflicts=conflicts.where(m.ProductionSchedule.id!=data.id)
                    if db.scalar(conflicts.limit(1)):raise HTTPException(409,'此工作中心在选定时间已有排程，请调整时间')
                    row=db.get(m.ProductionSchedule,data.id) if data.id else None
                    if data.id and (row is None or row.version!=data.version or row.status!='planned'):raise HTTPException(409,'排程已变化，请刷新后保存')
                    fields={'work_order_id':data.work_order_id,'center_id':data.center_id,'operation':data.operation.strip(),'starts_at':start,'ends_at':end}
                    if row:
                        for key,item in fields.items():setattr(row,key,item)
                        row.version+=1
                    else:row=add_model(db,m.ProductionSchedule(**fields,status='planned',version=1,created_by=user['id']))
                audit(db,user,'schedule',row.id,data.reason,model_data(row));return snapshot([model_data(row)],user)
            data=parse(QualityInput,value.payload);completion=db.get(m.ProductionCompletion,data.completion_id)
            if completion is None or completion.status!='posted' or db.scalar(select(m.ProductionCompletionReversal.id).where(m.ProductionCompletionReversal.production_completion_id==completion.id)):raise HTTPException(409,'须选择有效已确认质检完工单')
            ensure_unsettled(db,completion.work_order_id);ensure_date_unlocked(db,completion.posted_at)
            occupied=sum((Decimal(q) for q in db.scalars(select(m.QualityDisposition.quantity).where(m.QualityDisposition.completion_id==completion.id))),Decimal(0))
            if occupied+data.quantity>Decimal(completion.rejected_quantity):raise HTTPException(409,'处置数量超过尚未处理的不合格数量')
            child=None
            if data.kind=='rework':
                original=db.get(m.WorkOrder,completion.work_order_id)
                child=add_model(db,m.WorkOrder(bom_id=original.bom_id,warehouse_id=original.warehouse_id,target_quantity=str(data.quantity),reference=f'返工 完-{completion.id}',note=data.reason,status='in_progress',created_by=user['id'],released_by=user['id']))
                from app.production.boms import BomLineInput
                for replacement in data.replacements:
                    item=parse(BomLineInput,replacement)
                    if db.get(m.Material,item.component_material_id) is None:raise HTTPException(422,'替换物料不存在')
                    db.add(m.WorkOrderLine(work_order_id=child.id,component_material_id=item.component_material_id,required_quantity=str(item.quantity)))
            elif data.replacements:raise HTTPException(422,'报废处置不能指定返工替换料')
            row=add_model(db,m.QualityDisposition(completion_id=completion.id,kind=data.kind,quantity=str(data.quantity),rework_order_id=child.id if child else None,reason=data.reason,created_by=user['id']))
            audit(db,user,'quality',row.id,data.reason,model_data(row));return snapshot([model_data(row)],user)
    except IntegrityError:raise HTTPException(409,'名称或业务记录已存在，操作已回滚') from None
