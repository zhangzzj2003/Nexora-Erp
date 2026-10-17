"""工单与仓库四页共用的生产物料接口；页面位置不会扩大服务端权限。"""
from decimal import Decimal
from datetime import date, datetime, time, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, or_, and_
from app.access.security import require
from app.catalog.material_rules import material_choice_data
from app.core import document_approval as approval
from app.core.document_responses import NumberedRoute
from app.core.orm import orm_session
from app.core.models import (WorkOrder,WorkOrderLine,Bom,Material,Warehouse,User,
    MaterialFlowExecution,MaterialFlowExecutionLine,MaterialFlowExecutionLot,MaterialFlowLine,
    MaterialIssue,MaterialIssueLine,MaterialIssueReversal,MaterialReturn,MaterialReturnLine,MaterialReturnReversal,PhysicalLot,StockMovement)
from app.production.material_flow_rules import (MODELS,APPROVAL_NAMES,PERMISSIONS,ZERO,document,lines_for,
    executed_quantity,received_for_dispatch_line,exchange_progress,flow_quantities,source_available,legacy_source_remaining,replacement_committed)
from app.production.material_flow_inputs import FlowCreateInput,FlowUpdateInput,FlowExecuteInput,FlowActionInput
from app.production.material_flow_actions import (create_document,update_document,execute_document,
    close_document,reverse_document,create_exchange_dispatch,create_legacy_receipt)

router=APIRouter(prefix='/api/v1',route_class=NumberedRoute)
BASES={'dispatch':'material-dispatches','receipt':'material-receipts','exchange':'material-exchanges','return':'material-returns/flow'}


def document_data(db,kind,identifier):
    header=document(db,kind,identifier)
    order=db.get(WorkOrder,header.work_order_id)
    bom=db.get(Bom,order.bom_id)
    product=db.get(Material,bom.product_material_id)
    warehouse=db.get(Warehouse,header.warehouse_id)
    author=db.get(User,header.created_by)
    source_kind=header.source_document_type
    source_model=MODELS.get(source_kind) if source_kind else None
    source=db.get(source_model,header.source_document_id) if source_model else db.get(MaterialIssue,header.source_document_id) if source_kind=='legacy_issue' else None
    items=[]
    for line in lines_for(db,kind,identifier):
        workline=db.get(WorkOrderLine,line.work_order_line_id)
        material=db.get(Material,workline.component_material_id)
        actual=executed_quantity(db,line.id)
        dispatched,signed=exchange_progress(db,line.id) if kind=='exchange' else (actual,received_for_dispatch_line(db,line.id)) if kind=='dispatch' else (ZERO,actual if kind=='receipt' else ZERO)
        handover=executed_quantity(db,line.id,'handover_return') if kind=='receipt' else ZERO
        line_source_kind='receipt' if line.source_receipt_line_id else 'legacy_issue' if line.legacy_issue_line_id else 'exchange' if line.exchange_line_id else None
        line_source=document(db,'receipt',db.get(MaterialFlowLine,line.source_receipt_line_id).document_id) if line.source_receipt_line_id else db.get(MaterialIssue,db.get(MaterialIssueLine,line.legacy_issue_line_id).material_issue_id) if line.legacy_issue_line_id else document(db,'exchange',db.get(MaterialFlowLine,line.exchange_line_id).document_id) if line.exchange_line_id else None
        remaining=max(ZERO,Decimal(line.quantity)-(signed if kind=='exchange' else actual)-handover)
        # 补发草稿编辑使用专用余额，关闭、冲销及交接退回沿用实际发料的同一额度规则。
        replacement_available = max(ZERO,actual-sum((replacement_committed(db,child)
            for child in db.scalars(select(MaterialFlowLine).where(MaterialFlowLine.document_type=='dispatch',
                MaterialFlowLine.exchange_line_id==line.id))),ZERO)) if kind=='exchange' else ZERO
        # 参数沿本行工单物料身份提供，复用已读取对象；不包含供应商绑定及价格。
        items.append({'id':line.id,'work_order_line_id':workline.id,'material_id':material.id,'sku':material.sku,
            'material':material_choice_data(material),
            'material_name':material.name,'unit':material.unit,'quantity':line.quantity,'executed_quantity':str(actual),
            'dispatched_quantity':str(dispatched),'received_quantity':str(signed),'handover_returned_quantity':str(handover),
            'replacement_available_quantity':str(replacement_available),
            'remaining_quantity':str(ZERO if header.status in ('closed','reversed') else remaining),'closed_quantity':str(remaining if header.status=='closed' else ZERO),
            'source_document_kind':line_source_kind,'source_document_id':line_source.id if line_source else None,'source_document_no':line_source.document_no if line_source else None,
            'source_receipt_line_id':line.source_receipt_line_id,'legacy_issue_line_id':line.legacy_issue_line_id,
            'exchange_line_id':line.exchange_line_id,'disposal':line.disposal,'evidence':line.evidence})
    executions=[]
    for event in db.scalars(select(MaterialFlowExecution).where(MaterialFlowExecution.document_type==kind,MaterialFlowExecution.document_id==identifier).order_by(MaterialFlowExecution.id)):
        user=db.get(User,event.created_by)
        executions.append({'id':event.id,'action':event.action,'reason':event.reason,'created_by':event.created_by,
            'created_by_name':user.username,'created_at':event.created_at,'lines':[{'id':fact.id,'line_id':fact.line_id,
                'quantity':fact.quantity,'movement_id':fact.movement_id,'source_movement_id':fact.source_movement_id,
                'reverses_line_id':fact.reverses_line_id,'lots':[{'lot_id':lot.lot_id,'quantity':lot.quantity,'code':db.get(PhysicalLot,lot.lot_id).code} for lot in db.scalars(select(MaterialFlowExecutionLot).where(MaterialFlowExecutionLot.execution_line_id==fact.id))]} for fact in db.scalars(select(MaterialFlowExecutionLine).where(MaterialFlowExecutionLine.execution_id==event.id))]})
    name=APPROVAL_NAMES.get(kind,'MaterialReceipt')
    return {'id':header.id,'document_no':header.document_no,'kind':kind,'work_order_id':order.id,
        'work_order_document_no':order.document_no,'product_name':product.name,'warehouse_id':warehouse.id,
        'warehouse_name':warehouse.name,'status':header.status,'version':header.version,'reference':header.reference,
        'reason':header.reason,'note':header.note,'created_by':header.created_by,'created_by_name':author.username,
        'created_at':header.created_at,'closed_by':header.closed_by,'closed_at':header.closed_at,'close_reason':header.close_reason,
        'source_document_kind':source_kind,'source_document_type':source_kind,'source_document_id':header.source_document_id,
        'source_document_no':source.document_no if source else None,'approval':approval.case_data(approval.find_case(db,name,identifier)) if kind!='receipt' else None,
        'reversal_approval':approval.case_data(approval.find_case(db,name,identifier,'reverse')),
        'planned_quantity':str(sum((Decimal(item['quantity']) for item in items),ZERO)),
        'executed_quantity':str(sum((Decimal(item['executed_quantity']) for item in items),ZERO)),
        'received_quantity':str(sum((Decimal(item['received_quantity']) for item in items),ZERO)),
        'dispatched_quantity':str(sum((Decimal(item['dispatched_quantity']) for item in items),ZERO)),
        'damaged_quantity':str(sum((Decimal(item['executed_quantity']) for item in items),ZERO) if kind=='exchange' else ZERO),
        'remaining_quantity':str(sum((Decimal(item['remaining_quantity']) for item in items),ZERO)),
        'lines':items,'executions':executions}


def work_order_choices(db):
    return [{'id':order.id,'document_no':order.document_no,'product_name':product.name,
        'warehouse_id':order.warehouse_id,'status':order.status}
        for order,product in db.execute(select(WorkOrder,Material).join(Bom,Bom.id==WorkOrder.bom_id)
            .join(Material,Material.id==Bom.product_material_id).where(WorkOrder.status.in_(('released','in_progress'))).order_by(WorkOrder.id.desc()))]


def register_routes(kind,base):
    # 固定闭包生成四类相同的边界；客户端不能提供任意 ORM 模型或动态表名。
    def query(page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=200),q:str='',status:str='',
              warehouse_id:int|None=None,created_by:int|None=None,date_from:str='',date_to:str='',work_order_id:int|None=None,
              timezone_offset_minutes:int=Query(0,ge=-840,le=840),
              user:dict=Depends(require('material_flow.view'))):
        for value in (date_from,date_to):
            if value:
                try: date.fromisoformat(value)
                except ValueError: raise HTTPException(422,'日期格式无效')
        if date_from and date_to and date_from>date_to:
            raise HTTPException(422,'开始日期不能晚于结束日期')
        try:
            offset=timedelta(minutes=timezone_offset_minutes)
            start=datetime.combine(date.fromisoformat(date_from),time())+offset if date_from else None
            end=datetime.combine(date.fromisoformat(date_to),time())+timedelta(days=1)+offset if date_to else None
        except (OverflowError,ValueError):
            raise HTTPException(422,'日期超出支持范围')
        with orm_session() as db:
            model=MODELS[kind]
            conditions=[]
            if warehouse_id:
                conditions.append(model.warehouse_id==warehouse_id)
            if work_order_id:
                conditions.append(model.work_order_id==work_order_id)
            if created_by:
                conditions.append(or_(model.created_by==created_by,model.id.in_(select(MaterialFlowExecution.document_id).where(
                    MaterialFlowExecution.document_type==kind,MaterialFlowExecution.created_by==created_by))))
            if date_from:
                # 与界面本地日期保持一致；客户端偏移采用 Date.getTimezoneOffset 的 UTC 减本地口径。
                conditions.append(model.created_at>=start.strftime('%Y-%m-%d %H:%M:%S'))
            if date_to:
                conditions.append(model.created_at<end.strftime('%Y-%m-%d %H:%M:%S'))
            if q.strip():
                term=q.strip().lower()
                def matches(column):
                    return func.lower(column).contains(term,autoescape=True)
                material_ids=select(Material.id).where(or_(matches(Material.sku),matches(Material.name)))
                workline_ids=select(WorkOrderLine.id).where(WorkOrderLine.component_material_id.in_(material_ids))
                detail_ids=select(MaterialFlowLine.document_id).where(MaterialFlowLine.document_type==kind,
                    MaterialFlowLine.work_order_line_id.in_(workline_ids))
                order_ids=select(WorkOrder.id).join(Bom,Bom.id==WorkOrder.bom_id).join(Material,Material.id==Bom.product_material_id).where(
                    or_(matches(WorkOrder.document_no),matches(Material.name)))
                source_matches=[and_(model.source_document_type==source_kind,model.source_document_id.in_(
                    select(source_model.id).where(matches(source_model.document_no)))) for source_kind,source_model in {**MODELS,'legacy_issue':MaterialIssue}.items()]
                conditions.append(or_(matches(model.document_no),matches(model.reference),model.id.in_(detail_ids),model.work_order_id.in_(order_ids),*source_matches))
            # 先在数据库按完整筛选集统计，再只读取当前页的详情；页数不会改变总数口径。
            counts=dict(db.execute(select(model.status,func.count(model.id)).where(*conditions).group_by(model.status)).all())
            summary={key:counts.get(key,0) for key in ('draft','partial','completed','closed','reversed')}
            if status:
                conditions.append(model.status==status)
            total=db.scalar(select(func.count(model.id)).where(*conditions)) or 0
            ids=db.scalars(select(model.id).where(*conditions).order_by(model.id.desc()).offset((page-1)*page_size).limit(page_size))
            actors={row.id:row.username for row in db.scalars(select(User).where(User.id.in_(select(model.created_by))))}
            actors.update({row.id:row.username for row in db.scalars(select(User).where(User.id.in_(select(MaterialFlowExecution.created_by).where(MaterialFlowExecution.document_type==kind))))})
            return {'items':[document_data(db,kind,identifier) for identifier in ids],'total':total,'page':page,'page_size':page_size,
                'summary':summary,'actors':[{'id':key,'name':value} for key,value in actors.items()],
                'work_orders':work_order_choices(db),'warehouses':[{'id':w.id,'name':w.name} for w in db.scalars(select(Warehouse).order_by(Warehouse.id))]}

    def detail(identifier:int,user:dict=Depends(require('material_flow.view'))):
        with orm_session() as db:
            return document_data(db,kind,identifier)

    def create(payload:FlowCreateInput,user:dict=Depends(require(PERMISSIONS[kind]+'.create'))):
        with orm_session(write=True) as db:
            header=create_document(db,kind,payload,user['id']);return document_data(db,kind,header.id)

    def update(identifier:int,payload:FlowUpdateInput,user:dict=Depends(require(PERMISSIONS[kind]+'.create'))):
        with orm_session(write=True) as db:
            header=update_document(db,kind,identifier,payload,user['id']);db.flush();return document_data(db,kind,header.id)

    def execute(identifier:int,payload:FlowExecuteInput,user:dict=Depends(require('material_receipt.sign' if kind=='receipt' else PERMISSIONS[kind]+'.post'))):
        with orm_session(write=True) as db:
            header=execute_document(db,kind,identifier,payload,user['id']);db.flush();return document_data(db,kind,header.id)

    def close(identifier:int,payload:FlowActionInput,user:dict=Depends(require(PERMISSIONS[kind]+'.close'))):
        with orm_session(write=True) as db:
            header=close_document(db,kind,identifier,payload,user['id']);db.flush();return document_data(db,kind,header.id)

    def reverse(identifier:int,payload:FlowActionInput,user:dict=Depends(require(PERMISSIONS[kind]+'.reverse'))):
        with orm_session(write=True) as db:
            header=reverse_document(db,kind,identifier,payload,user['id']);db.flush();return document_data(db,kind,header.id)

    def lots(identifier:int,user:dict=Depends(require('material_flow.view'))):
        from app.inventory.physical_lots import lot_balance
        from app.production.material_flow_lots import available_source_lots
        with orm_session() as db:
            header=document(db,kind,identifier);results=[]
            for line in lines_for(db,kind,identifier):
                workline=db.get(WorkOrderLine,line.work_order_line_id)
                values=[{'lot_id':lot.id,'code':lot.code,'quantity':str(lot_balance(db,header.warehouse_id,lot.id))}
                    for lot in db.scalars(select(PhysicalLot).where(PhysicalLot.material_id==workline.component_material_id))
                    if lot_balance(db,header.warehouse_id,lot.id)>0]
                if kind!='dispatch':
                    values=available_source_lots(db,line)
                results.append({'line_id':line.id,'lots':values})
            return {'lines':results}

    router.add_api_route('/'+base,query,methods=['GET'],name=kind+'_query')
    router.add_api_route('/'+base+'/{identifier}',detail,methods=['GET'],name=kind+'_detail')
    if kind!='receipt':
        router.add_api_route('/'+base,create,methods=['POST'],status_code=201,name=kind+'_create')
        router.add_api_route('/'+base+'/{identifier}',update,methods=['PUT'],name=kind+'_update')
        router.add_api_route('/'+base+'/{identifier}/close',close,methods=['POST'],name=kind+'_close')
    router.add_api_route('/'+base+'/{identifier}/execute',execute,methods=['POST'],name=kind+'_execute')
    router.add_api_route('/'+base+'/{identifier}/reverse',reverse,methods=['POST'],name=kind+'_reverse')
    router.add_api_route('/'+base+'/{identifier}/available-lots',lots,methods=['GET'],name=kind+'_lots')


for kind,base in BASES.items():
    register_routes(kind,base)


@router.post('/material-receipts/{identifier}/handover-return')
def handover_return(identifier:int,payload:FlowExecuteInput,user:dict=Depends(require('material_receipt.handover_return'))):
    with orm_session(write=True) as db:
        header=execute_document(db,'receipt',identifier,payload,user['id'],'handover_return');db.flush()
        return document_data(db,'receipt',header.id)


@router.post('/material-exchanges/{identifier}/create-dispatch',status_code=201)
def replacement_dispatch(identifier:int,payload:FlowActionInput,user:dict=Depends(require('material_dispatch.create'))):
    with orm_session(write=True) as db:
        header=create_exchange_dispatch(db,identifier,payload,user['id']);db.flush()
        return document_data(db,'dispatch',header.id)


@router.get('/work-orders/{identifier}/material-flow')
def work_order_material_flow(identifier:int,user:dict=Depends(require('material_flow.view'))):
    from app.production.work_orders import issued_quantity,committed_quantity
    with orm_session() as db:
        order=db.get(WorkOrder,identifier)
        if order is None: raise HTTPException(404,'生产工单不存在')
        lines=[];sources=[]
        for line in db.scalars(select(WorkOrderLine).where(WorkOrderLine.work_order_id==identifier)):
            material=db.get(Material,line.component_material_id);facts=flow_quantities(db,line.id)
            historical=sum((Decimal(value) for value in db.scalars(select(MaterialIssueLine.quantity).join(MaterialIssue,MaterialIssue.id==MaterialIssueLine.material_issue_id).where(MaterialIssueLine.work_order_line_id==line.id,MaterialIssue.status=='posted',MaterialIssue.historical_direct.is_(True),MaterialIssue.id.not_in(select(MaterialIssueReversal.material_issue_id))))),ZERO)
            old_returned=sum((Decimal(value) for value in db.scalars(select(MaterialReturnLine.quantity).join(MaterialReturn,MaterialReturn.id==MaterialReturnLine.material_return_id).join(MaterialIssueLine,MaterialIssueLine.id==MaterialReturnLine.material_issue_line_id).where(MaterialIssueLine.work_order_line_id==line.id,MaterialReturn.status=='posted',MaterialReturn.id.not_in(select(MaterialReturnReversal.material_return_id))))),ZERO)
            # 有效量只减已执行事实；可用量另扣待退、待换及旧退料草稿预留，避免展示混淆。
            effective=facts['signed']+historical-facts['returned']-old_returned-facts['damaged']
            available=issued_quantity(db,line.id)
            # 工单汇总复用已查询物料的当前参数，不额外逐行读取资料。
            lines.append({'work_order_line_id':line.id,'material_id':material.id,'sku':material.sku,'material_name':material.name,'unit':material.unit,
                'material':material_choice_data(material),
                'required_quantity':line.required_quantity,'signed_quantity':str(facts['signed']+historical),'historical_direct_quantity':str(historical),'returned_quantity':str(facts['returned']+old_returned),
                'damaged_quantity':str(facts['damaged']),'reserved_quantity':str(effective-available),'effective_quantity':str(effective),'available_quantity':str(available),
                'in_transit_quantity':str(facts['in_transit']),'dispatchable_quantity':str(max(ZERO,Decimal(line.required_quantity)-committed_quantity(db,line.id)))})
            for receipt in db.scalars(select(MaterialFlowLine).where(MaterialFlowLine.document_type=='receipt',MaterialFlowLine.work_order_line_id==line.id,MaterialFlowLine.legacy_issue_line_id.is_(None))):
                available=source_available(db,MaterialFlowLine(work_order_line_id=line.id,source_receipt_line_id=receipt.id))
                source=document(db,'receipt',receipt.document_id)
                if available>0:
                    sources.append({'source_receipt_line_id':receipt.id,'legacy_issue_line_id':None,'work_order_line_id':line.id,
                        'material_id':material.id,'sku':material.sku,'material_name':material.name,'unit':material.unit,
                        'source_document_no':source.document_no,'source_document_kind':'receipt','source_document_id':source.id,
                        'quantity':str(executed_quantity(db,receipt.id)),'available_quantity':str(available),'warehouse_id':source.warehouse_id})
            for legacy in db.scalars(select(MaterialIssueLine).where(MaterialIssueLine.work_order_line_id==line.id)):
                available=legacy_source_remaining(db,legacy.id)
                source=db.get(MaterialIssue,legacy.material_issue_id)
                if available>0:
                    sources.append({'source_receipt_line_id':None,'legacy_issue_line_id':legacy.id,'work_order_line_id':line.id,
                        'material_id':material.id,'sku':material.sku,'material_name':material.name,'unit':material.unit,
                        'source_document_no':source.document_no,'source_document_kind':'legacy_issue','source_document_id':source.id,
                        'quantity':legacy.quantity,'available_quantity':str(available),'warehouse_id':source.warehouse_id})
        return {'work_order_id':identifier,'lines':lines,'sources':sources,
            **{key:[document_data(db,kind,row.id) for row in db.scalars(select(MODELS[kind]).where(MODELS[kind].work_order_id==identifier).order_by(MODELS[kind].id.desc()))]
                for kind,key in (('dispatch','dispatches'),('receipt','receipts'),('exchange','exchanges'),('return','returns'))}}
