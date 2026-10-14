"""生产物料办理服务；额度、库存、审批及审计共用同一写事务。"""

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy import select, delete, func
from app.core import document_approval as approval
from app.core.models import (
    MaterialFlowExecution, MaterialFlowExecutionLine, MaterialFlowLine, MaterialReceipt,
    MaterialDispatch, MaterialIssue, MaterialIssueLine, StockMovement,
    PhysicalLotAllocation, PhysicalLotMovementEvidence, WorkOrder, WorkOrderLine, ProductionCompletion, ProductionCompletionReversal,
)
from app.core.orm import add_model
from app.core.period_lock import ensure_date_unlocked, ensure_movement_unlocked
from app.inventory.warehouse import require_warehouse, balance
from app.inventory.physical_lots import LotPart, post_lot_movement, unassigned_stock_quantity
from app.production.cost_lock import ensure_unsettled
from app.production.material_flow_rules import (
    MODELS, APPROVAL_NAMES, PERMISSIONS, ZERO, document, lines_for, active_facts,
    executed_quantity, source_available, source_movement, exchange_progress, replacement_committed,
)
from app.production.material_flow_inputs import FlowCreateInput
from app.production.material_flow_lots import return_lots,record_execution_lots


def now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def reversal_lots(db, movement):
    # 执行后现场补证也属于库存批次事实；更正须反向处理完整依据，不能只恢复正式库存。
    allocations=list(db.scalars(select(PhysicalLotAllocation).where(PhysicalLotAllocation.movement_id==movement.id)))
    evidence=list(db.scalars(select(PhysicalLotMovementEvidence).where(PhysicalLotMovementEvidence.movement_id==movement.id)))
    quantity=Decimal(movement.quantity)
    if allocations and evidence:
        raise HTTPException(409,'原流水同时存在批次分配和现场补证，请先核对来源')
    if allocations:
        if sum((Decimal(part.quantity) for part in allocations),ZERO)!=quantity:
            raise HTTPException(409,'原流水批次分配不完整，无法更正')
        return [LotPart(part.lot_id,-Decimal(part.quantity),part.id) for part in allocations]
    if evidence:
        amounts={}
        for part in evidence:
            amounts[part.lot_id]=amounts.get(part.lot_id,ZERO)+Decimal(part.quantity)
        if sum(amounts.values(),ZERO)!=quantity or any(value*quantity<=0 for value in amounts.values()):
            raise HTTPException(409,'原流水现场补证未完整归批，无法更正')
        return [LotPart(lot_id,-amount) for lot_id,amount in amounts.items()]
    # 未归批退入库存不能在更正时扣走已明确批次的库存；同一事务逐笔扣减也保护合计余额。
    if quantity>0 and unassigned_stock_quantity(db,movement.warehouse_id,movement.material_id)<quantity:
        raise HTTPException(409,'原退回材料的未归批库存不足，无法更正')
    return []


def digest(payload, action=''):
    value = payload.model_dump(mode='json') if hasattr(payload,'model_dump') else payload
    return hashlib.sha256(json.dumps({'action':action,'payload':value},sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def order_for_write(db, order_id):
    order = db.get(WorkOrder,order_id)
    if order is None or order.status not in ('released','in_progress'):
        raise HTTPException(409,'只能办理已下达或生产中的工单')
    ensure_unsettled(db,order_id)
    ensure_date_unlocked(db,now())
    return order


def snapshot(db, kind, identifier):
    row=document(db,kind,identifier)
    return {'work_order_id':row.work_order_id,'warehouse_id':row.warehouse_id,
        'reference':row.reference,'reason':row.reason,'note':row.note,
        'source_document_type':row.source_document_type,'source_document_id':row.source_document_id,
        'lines':[{'id':line.id,'work_order_line_id':line.work_order_line_id,'quantity':line.quantity,
            'source_receipt_line_id':line.source_receipt_line_id,'legacy_issue_line_id':line.legacy_issue_line_id,
            'exchange_line_id':line.exchange_line_id,'source_execution_line_id':line.source_execution_line_id,
            'disposal':line.disposal,'evidence':line.evidence} for line in lines_for(db,kind,identifier)]}


def execution_snapshot(db, kind, identifier):
    return [{'id':fact.id,'line_id':fact.line_id,'quantity':fact.quantity,'movement_id':fact.movement_id,
             'source_movement_id':fact.source_movement_id,'action':event.action}
            for line in lines_for(db,kind,identifier) for fact,event in active_facts(db,line.id)]


def check_version(header, payload):
    if header.version != payload.version:
        raise HTTPException(409,'单据已更新，请刷新后重试')


def replay(db, kind, header, payload, action):
    # 先校验新鲜权限，再识别完全相同的网络重试；同一标识不能换一份正文。
    previous=db.scalar(select(MaterialFlowExecution).where(MaterialFlowExecution.document_type==kind,
        MaterialFlowExecution.document_id==header.id,MaterialFlowExecution.request_id==payload.request_id))
    if previous:
        if previous.request_digest != digest(payload,action):
            raise HTTPException(409,'重复请求标识对应的办理内容不同')
        return True
    check_version(header,payload)
    return False


def event_for(db,kind,header,payload,action,user_id):
    return add_model(db,MaterialFlowExecution(document_type=kind,document_id=header.id,action=action,
        request_id=payload.request_id,request_digest=digest(payload,action),reason=payload.reason,created_by=user_id))


def require_execution_approval(db,kind,header,user_id):
    name=APPROVAL_NAMES[kind]
    row=approval.find_case(db,name,header.id)
    if row is None or row.status not in ('approved','executed'):
        raise HTTPException(409,'请先提交单据并完成审批')
    if row.content_digest != approval.digest(snapshot(db,kind,header.id))[1]:
        raise HTTPException(409,'执行内容与批准内容不一致，请重新送审')
    approval.actor(db,user_id,PERMISSIONS[kind]+'.post')
    return row


def validate_lines(db,kind,payload,exclude=None):
    from app.production.work_orders import committed_quantity, issued_quantity, required_for_output, posted_completion_totals
    order=order_for_write(db,payload.work_order_id)
    require_warehouse(db,payload.warehouse_id)
    if kind in ('return','exchange') and not payload.reason:
        raise HTTPException(422,'退换料原因不能为空')
    if kind=='dispatch' and any(line.exchange_line_id for line in payload.lines):
        if any(not line.exchange_line_id for line in payload.lines):
            raise HTTPException(422,'普通发料和换料补发须分别建单')
        if len({db.get(MaterialFlowLine,line.exchange_line_id).document_id for line in payload.lines if db.get(MaterialFlowLine,line.exchange_line_id)})>1:
            raise HTTPException(422,'一次补发只能对应同一张换料单')
    keys=set()
    totals={}
    for source in payload.lines:
        workline=db.get(WorkOrderLine,source.work_order_line_id)
        if workline is None or workline.work_order_id!=order.id:
            raise HTTPException(422,'材料明细不属于本工单')
        key=(workline.id,source.source_receipt_line_id,source.legacy_issue_line_id,source.exchange_line_id)
        if key in keys:
            raise HTTPException(422,'同一来源材料不能重复填写')
        keys.add(key)
        line=MaterialFlowLine(document_type=kind,document_id=0,**source.model_dump(exclude={'quantity'}),quantity=str(source.quantity))
        if kind=='dispatch':
            if source.disposal!='physical' or source.evidence:
                raise HTTPException(422,'发料单不能直接登记损坏或损耗')
            if source.source_receipt_line_id or source.legacy_issue_line_id:
                raise HTTPException(422,'发料来源只能是工单需求或已收旧的换料额度')
            if source.exchange_line_id:
                exchange=db.get(MaterialFlowLine,source.exchange_line_id)
                if not exchange or exchange.document_type!='exchange' or exchange.work_order_line_id!=workline.id:
                    raise HTTPException(422,'换料补发来源无效')
                parent=document(db,'exchange',exchange.document_id)
                if parent.warehouse_id!=payload.warehouse_id:
                    raise HTTPException(422,'补发仓库必须与换料单一致')
                allowance=executed_quantity(db,exchange.id)
                used=ZERO
                for other in db.scalars(select(MaterialFlowLine).where(MaterialFlowLine.document_type=='dispatch',MaterialFlowLine.exchange_line_id==exchange.id)):
                    if exclude==('dispatch',other.document_id):
                        continue
                    other_header=document(db,'dispatch',other.document_id)
                    if other_header.status!='reversed':
                        used+=replacement_committed(db,other)
                if source.quantity>allowance-used:
                    raise HTTPException(409,'补发数量超过已收旧或已批准无实物损耗额度')
            else:
                reserved=committed_quantity(db,workline.id)
                if exclude:
                    reserved-=sum((Decimal(v.quantity) for v in lines_for(db,*exclude) if v.work_order_line_id==workline.id and not v.exchange_line_id),ZERO)
                totals[workline.id]=totals.get(workline.id,ZERO)+source.quantity
                if totals[workline.id] > Decimal(workline.required_quantity)-reserved:
                    raise HTTPException(409,'普通发料超过工单剩余需求，损坏补发须走换料单')
        else:
            if bool(source.source_receipt_line_id)==bool(source.legacy_issue_line_id) or source.exchange_line_id:
                raise HTTPException(422,'退换料必须选择且只能选择一个已签收来源')
            if source.quantity > source_available(db,line,exclude):
                raise HTTPException(409,'退换料数量超过来源可用余额或已被其他单据占用')
            movement=source_movement(db,line)
            if movement is None or movement.warehouse_id!=payload.warehouse_id:
                raise HTTPException(422,'退换料仓库必须与实际发料仓库一致')
            if kind=='return' and (source.disposal!='physical' or source.evidence):
                raise HTTPException(422,'正常退料只接收可重新使用的材料')
            if kind=='exchange' and source.disposal=='loss' and not source.evidence.strip():
                raise HTTPException(422,'无实物损耗必须填写依据并送审')
            totals[workline.id]=totals.get(workline.id,ZERO)+source.quantity
    if kind in ('return','exchange'):
        completed=posted_completion_totals(db,order.id)[0]
        for identifier,quantity in totals.items():
            workline=db.get(WorkOrderLine,identifier)
            available=issued_quantity(db,identifier)
            if exclude:
                available+=sum((Decimal(v.quantity) for v in lines_for(db,*exclude) if v.work_order_line_id==identifier),ZERO)
            if available-quantity < required_for_output(Decimal(workline.required_quantity),Decimal(order.target_quantity),completed):
                raise HTTPException(409,'退换料后材料不足以支撑已报工数量')


def create_document(db,kind,payload,user_id,source=None):
    if kind=='receipt':
        raise HTTPException(422,'领料签收单由实际发料自动产生')
    approval.actor(db,user_id,PERMISSIONS[kind]+'.create')
    previous=db.scalar(select(MODELS[kind]).where(MODELS[kind].request_id==payload.request_id))
    if previous:
        if previous.request_digest!=digest(payload,'create'):
            raise HTTPException(409,'重复请求标识对应的建单内容不同')
        return previous
    if kind in ('return','exchange') and not payload.reason:
        raise HTTPException(422,'退换料原因不能为空')
    validate_lines(db,kind,payload)
    if source is None and kind in ('return','exchange'):
        origins=set()
        for line in payload.lines:
            if line.source_receipt_line_id:
                origins.add(('receipt',db.get(MaterialFlowLine,line.source_receipt_line_id).document_id))
            else:
                origins.add(('legacy_issue',db.get(MaterialIssueLine,line.legacy_issue_line_id).material_issue_id))
        if len(origins)==1:
            source=origins.pop()
    if source is None and kind=='dispatch' and any(line.exchange_line_id for line in payload.lines):
        if any(not line.exchange_line_id for line in payload.lines):
            raise HTTPException(422,'普通发料和换料补发须分别建单')
        origins={db.get(MaterialFlowLine,line.exchange_line_id).document_id for line in payload.lines}
        if len(origins)!=1:
            raise HTTPException(422,'一次补发只能对应同一张换料单')
        source=('exchange',origins.pop())
    header=add_model(db,MODELS[kind](work_order_id=payload.work_order_id,warehouse_id=payload.warehouse_id,
        reference=payload.reference,reason=payload.reason,note=payload.note,created_by=user_id,
        request_id=payload.request_id,request_digest=digest(payload,'create'),
        source_document_type=source[0] if source else None,source_document_id=source[1] if source else None))
    db.add_all(MaterialFlowLine(document_type=kind,document_id=header.id,
        **line.model_dump(exclude={'quantity'}),quantity=str(line.quantity)) for line in payload.lines)
    db.flush()
    approval.record_author(db,APPROVAL_NAMES[kind],header.id,user_id)
    return header


def update_document(db,kind,identifier,payload,user_id):
    approval.actor(db,user_id,PERMISSIONS[kind]+'.create')
    header=document(db,kind,identifier)
    if replay(db,kind,header,payload,'edit'):
        return header
    if header.status!='draft' or any(active_facts(db,line.id) for line in lines_for(db,kind,identifier)):
        raise HTTPException(409,'已执行单据不能改写，须办理更正')
    approval.record_author(db,APPROVAL_NAMES[kind],header.id,user_id)
    if payload.work_order_id!=header.work_order_id:
        raise HTTPException(422,'不能更换来源工单')
    validate_lines(db,kind,payload,(kind,identifier))
    db.execute(delete(MaterialFlowLine).where(MaterialFlowLine.document_type==kind,MaterialFlowLine.document_id==identifier))
    header.warehouse_id,header.reference,header.reason,header.note=payload.warehouse_id,payload.reference,payload.reason,payload.note
    origins=set()
    for line in payload.lines:
        if line.source_receipt_line_id:
            origins.add(('receipt',db.get(MaterialFlowLine,line.source_receipt_line_id).document_id))
        elif line.legacy_issue_line_id:
            origins.add(('legacy_issue',db.get(MaterialIssueLine,line.legacy_issue_line_id).material_issue_id))
        elif line.exchange_line_id:
            origins.add(('exchange',db.get(MaterialFlowLine,line.exchange_line_id).document_id))
    origin=origins.pop() if len(origins)==1 else (None,None)
    header.source_document_type,header.source_document_id=origin
    db.add_all(MaterialFlowLine(document_type=kind,document_id=header.id,
        **line.model_dump(exclude={'quantity'}),quantity=str(line.quantity)) for line in payload.lines)
    event_for(db,kind,header,payload,'edit',user_id)
    header.version+=1
    return header


def refresh_status(db,kind,header):
    lines=lines_for(db,kind,header.id)
    actual=sum((executed_quantity(db,line.id) for line in lines),ZERO)
    complete=all(executed_quantity(db,line.id)+(executed_quantity(db,line.id,'handover_return') if kind=='receipt' else ZERO)>=Decimal(line.quantity) for line in lines)
    if kind=='exchange':
        complete=all(exchange_progress(db,line.id)[1]>=Decimal(line.quantity) for line in lines)
    header.status='completed' if complete else 'partial' if actual or any(active_facts(db,line.id) for line in lines) else 'draft'


def create_receipt(db,dispatch,execution,facts,user_id):
    receipt=add_model(db,MaterialReceipt(work_order_id=dispatch.work_order_id,warehouse_id=dispatch.warehouse_id,
        created_by=user_id,reference=dispatch.reference,source_document_type='dispatch',source_document_id=dispatch.id,
        request_id='dispatch-execution-'+str(execution.id),request_digest=str(execution.id)))
    for line,fact in facts:
        db.add(MaterialFlowLine(document_type='receipt',document_id=receipt.id,work_order_line_id=line.work_order_line_id,
            quantity=fact.quantity,source_execution_line_id=fact.id))
    db.flush()
    return receipt


def create_legacy_receipt(db,issue_id,user_id):
    issue=db.get(MaterialIssue,issue_id)
    if issue is None or issue.historical_direct:
        return None
    previous=db.scalar(select(MaterialReceipt).where(MaterialReceipt.source_document_type=='legacy_issue',MaterialReceipt.source_document_id==issue_id))
    if previous:
        return previous
    receipt=add_model(db,MaterialReceipt(work_order_id=issue.work_order_id,warehouse_id=issue.warehouse_id,
        created_by=user_id,reference=issue.reference,source_document_type='legacy_issue',source_document_id=issue.id,
        request_id='legacy-issue-'+str(issue.id),request_digest=str(issue.id)))
    for line in db.scalars(select(MaterialIssueLine).where(MaterialIssueLine.material_issue_id==issue.id)):
        db.add(MaterialFlowLine(document_type='receipt',document_id=receipt.id,work_order_line_id=line.work_order_line_id,
            quantity=line.quantity,legacy_issue_line_id=line.id))
    db.flush()
    return receipt


def execute_document(db,kind,identifier,payload,user_id,action='execute'):
    permission='material_receipt.handover_return' if action=='handover_return' else 'material_receipt.sign' if kind=='receipt' else PERMISSIONS[kind]+'.post'
    approval.actor(db,user_id,permission)
    header=document(db,kind,identifier)
    if replay(db,kind,header,payload,action):
        return header
    order=order_for_write(db,header.work_order_id)
    if header.status in ('completed','closed','reversed'):
        raise HTTPException(409,'单据已完成或关闭')
    if action=='handover_return' and (kind!='receipt' or not payload.reason):
        raise HTTPException(422,'交接退回必须填写实际退回原因')
    approved=require_execution_approval(db,kind,header,user_id) if kind!='receipt' else None
    known={line.id:line for line in lines_for(db,kind,identifier)}
    if len({line.line_id for line in payload.lines})!=len(payload.lines):
        raise HTTPException(422,'办理明细不能重复')
    event=event_for(db,kind,header,payload,action,user_id)
    outgoing=[]
    for item in payload.lines:
        line=known.get(item.line_id)
        if line is None:
            raise HTTPException(422,'办理明细不属于本单')
        actual=executed_quantity(db,line.id)
        remaining=Decimal(line.quantity)-actual-(executed_quantity(db,line.id,'handover_return') if kind=='receipt' else ZERO)
        if item.quantity>remaining:
            raise HTTPException(409,'办理数量超过剩余数量')
        workline=db.get(WorkOrderLine,line.work_order_line_id)
        original=source_movement(db,line) if kind in ('receipt','return','exchange') else None
        movement=None
        # 有实物旧料仅隔离接收留痕，完全损耗按批准依据确认，均不加回良品库存。
        if kind=='dispatch':
            if balance(db,header.warehouse_id,workline.component_material_id)<item.quantity:
                raise HTTPException(409,'仓库可用库存不足')
            parts=[LotPart(part.lot_id,-part.quantity) for part in item.lots] if item.lots else []
            direction=-item.quantity;source_type='material_dispatch'
        elif kind=='return' or action=='handover_return':
            parts=return_lots(db,line,item.quantity,item.lots,action)
            direction=item.quantity;source_type='production_material_return' if kind=='return' else 'material_handover_return'
        else:
            parts=[]
        # BEGIN IMMEDIATE 内分配执行行主键，先写流水再一次性插入完整事实，避免更新不可变记录。
        fact_id=(db.scalar(select(func.max(MaterialFlowExecutionLine.id))) or 0)+1
        if kind in ('dispatch','return') or action=='handover_return':
            movement=StockMovement(warehouse_id=header.warehouse_id,material_id=workline.component_material_id,
                quantity=str(direction),source_type=source_type,source_id=header.id,source_line_id=fact_id,created_by=user_id)
            if parts:
                post_lot_movement(db,movement,parts)
            else:
                db.add(movement);db.flush()
        fact=add_model(db,MaterialFlowExecutionLine(id=fact_id,execution_id=event.id,line_id=line.id,
            quantity=str(item.quantity),source_movement_id=original.id if original else None,
            movement_id=movement.id if movement else None))
        record_execution_lots(db,line,fact,action,item.lots,movement)
        outgoing.append((line,fact,movement))
    db.flush()
    if kind=='dispatch':
        create_receipt(db,header,event,[(line,fact) for line,fact,_ in outgoing],user_id)
        if order.status=='released':
            order.status='in_progress'
    refresh_status(db,kind,header)
    header.version+=1
    if kind=='receipt':
        # 新料实收后更新关联换料进度，单纯仓库发出不能把换料标为完成。
        for line in known.values():
            if line.source_execution_line_id:
                fact=db.get(MaterialFlowExecutionLine,line.source_execution_line_id)
                dispatch_line=db.get(MaterialFlowLine,fact.line_id)
                if dispatch_line.exchange_line_id:
                    exchange_line=db.get(MaterialFlowLine,dispatch_line.exchange_line_id)
                    exchange=document(db,'exchange',exchange_line.document_id)
                    refresh_status(db,'exchange',exchange);exchange.version+=1
    if approved and approved.status=='approved':
        approval.mark_executed(db,approved,user_id)
    return header


def close_document(db,kind,identifier,payload,user_id):
    if kind=='receipt':
        raise HTTPException(409,'待签差额只能继续签收或实物交接退回，不能直接关闭')
    approval.actor(db,user_id,PERMISSIONS[kind]+'.close')
    header=document(db,kind,identifier)
    if replay(db,kind,header,payload,'close'):
        return header
    order_for_write(db,header.work_order_id)
    if not payload.reason or header.status in ('closed','reversed','completed'):
        raise HTTPException(409,'只有未完成单据可以填写原因关闭余额')
    if kind=='exchange' and any(executed_quantity(db,line.id)!=exchange_progress(db,line.id)[1]
            for line in lines_for(db,kind,identifier)):
        raise HTTPException(409,'已收旧部分仍有待补发或待签收，不能关闭')
    event_for(db,kind,header,payload,'close',user_id)
    header.status='closed';header.version+=1
    header.closed_by=user_id;header.closed_at=now();header.close_reason=payload.reason
    return header


def exchange_request_key(identifier,request_id):
    # 自动子单的幂等键长度固定，客户端最大长度不会被前缀拼接放大。
    return 'exchange-'+str(identifier)+'-'+hashlib.sha256(request_id.encode()).hexdigest()


def create_exchange_dispatch(db,identifier,payload,user_id):
    approval.actor(db,user_id,'material_dispatch.create')
    header=document(db,'exchange',identifier)
    if replay(db,'exchange',header,payload,'create_dispatch'):
        return db.scalar(select(MaterialDispatch).where(MaterialDispatch.request_id==exchange_request_key(identifier,payload.request_id)))
    order_for_write(db,header.work_order_id)
    if header.status in ('closed','reversed','completed'):
        raise HTTPException(409,'换料单已关闭或完成')
    require_execution_approval(db,'exchange',header,user_id)
    candidates=[]
    for line in lines_for(db,'exchange',identifier):
        used=ZERO
        for child in db.scalars(select(MaterialFlowLine).where(MaterialFlowLine.document_type=='dispatch',MaterialFlowLine.exchange_line_id==line.id)):
            document_row=document(db,'dispatch',child.document_id)
            if document_row.status!='reversed':
                used+=replacement_committed(db,child)
        quantity=executed_quantity(db,line.id)-used
        if quantity>0:
            candidates.append({'work_order_line_id':line.work_order_line_id,'quantity':str(quantity),'exchange_line_id':line.id})
    if not candidates:
        raise HTTPException(409,'尚无未占用的收旧补发额度')
    new=FlowCreateInput(request_id=exchange_request_key(identifier,payload.request_id),
        work_order_id=header.work_order_id,warehouse_id=header.warehouse_id,reference=header.reference,
        reason=header.reason,note='换料补发，沿用原单等量同物料约束',lines=candidates)
    dispatch=create_document(db,'dispatch',new,user_id,('exchange',identifier))
    event_for(db,'exchange',header,payload,'create_dispatch',user_id)
    header.version+=1
    return dispatch


def reverse_document(db,kind,identifier,payload,user_id):
    from app.core.approval_documents import document_snapshot
    permission=PERMISSIONS[kind]+'.reverse'
    approval.actor(db,user_id,permission)
    header=document(db,kind,identifier)
    if replay(db,kind,header,payload,'reverse'):
        return header
    ensure_unsettled(db,header.work_order_id)
    ensure_date_unlocked(db,now())
    name='MaterialReceipt' if kind=='receipt' else APPROVAL_NAMES[kind]
    approved=approval.require_approved(db,name,identifier,
        document_snapshot(db,name,identifier,'reverse',payload.reason),user_id,intent='reverse',permission=permission)
    lines=lines_for(db,kind,identifier)
    # 先处理下游来源，再追加反向事实；任何已报工记录都要求按依赖顺序退回。
    if db.scalar(select(ProductionCompletion.id).where(ProductionCompletion.work_order_id==header.work_order_id,
            ProductionCompletion.status=='posted',ProductionCompletion.id.not_in(select(ProductionCompletionReversal.production_completion_id))).limit(1)):
        raise HTTPException(409,'工单已有有效报工，请先按依赖顺序更正报工')
    if kind=='dispatch':
        receipts=list(db.scalars(select(MaterialReceipt).where(MaterialReceipt.source_document_type=='dispatch',MaterialReceipt.source_document_id==identifier)))
        if any(active_facts(db,line.id) for receipt in receipts for line in lines_for(db,'receipt',receipt.id)):
            raise HTTPException(409,'发料已有签收或交接退回，请先更正关联签收单')
    elif kind=='receipt':
        from app.core.models import MaterialReturn, MaterialReturnLine, MaterialReturnReversal
        legacy_ids=[line.legacy_issue_line_id for line in lines if line.legacy_issue_line_id]
        if legacy_ids and db.scalar(select(MaterialReturn.id).join(MaterialReturnLine,MaterialReturnLine.material_return_id==MaterialReturn.id).where(MaterialReturnLine.material_issue_line_id.in_(legacy_ids),MaterialReturn.status!='cancelled',MaterialReturn.id.not_in(select(MaterialReturnReversal.material_return_id))).limit(1)):
            raise HTTPException(409,'签收来源已有历史退料，请先更正下游退料')
        for line in lines:
            for child in db.scalars(select(MaterialFlowLine).where(MaterialFlowLine.document_type.in_(('return','exchange')),
                    (MaterialFlowLine.source_receipt_line_id==line.id) | ((MaterialFlowLine.legacy_issue_line_id==line.legacy_issue_line_id) if line.legacy_issue_line_id else False))):
                child_header=document(db,child.document_type,child.document_id)
                if child_header.status not in ('closed','reversed') or active_facts(db,child.id):
                    raise HTTPException(409,'签收来源已有退换料，请先更正下游单据')
    elif kind=='exchange':
        for line in lines:
            for child in db.scalars(select(MaterialFlowLine).where(MaterialFlowLine.document_type=='dispatch',MaterialFlowLine.exchange_line_id==line.id)):
                child_header=document(db,'dispatch',child.document_id)
                if child_header.status not in ('closed','reversed') or active_facts(db,child.id):
                    raise HTTPException(409,'换料已有补发单，请先更正补发与签收')
    if kind=='receipt':
        from app.production.work_orders import committed_quantity
        restored_normal={};restored_exchange={}
        for line in lines:
            restored=executed_quantity(db,line.id,'handover_return')
            origin=db.get(MaterialFlowExecutionLine,line.source_execution_line_id) if line.source_execution_line_id else None
            dispatch_line=db.get(MaterialFlowLine,origin.line_id) if origin else None
            if dispatch_line and dispatch_line.exchange_line_id:
                key=dispatch_line.exchange_line_id
                restored_exchange[key]=restored_exchange.get(key,ZERO)+restored
            else:
                key=line.work_order_line_id
                restored_normal[key]=restored_normal.get(key,ZERO)+restored
        for workline_id,restored in restored_normal.items():
            workline=db.get(WorkOrderLine,workline_id)
            if committed_quantity(db,workline_id)+restored>Decimal(workline.required_quantity):
                raise HTTPException(409,'交接退回释放的额度已被后续发料占用，请先更正后续发料')
        for exchange_line_id,restored in restored_exchange.items():
            committed=sum((replacement_committed(db,child) for child in db.scalars(select(MaterialFlowLine).where(MaterialFlowLine.document_type=='dispatch',MaterialFlowLine.exchange_line_id==exchange_line_id))),ZERO)
            if committed+restored>executed_quantity(db,exchange_line_id):
                raise HTTPException(409,'交接退回释放的补发额度已被后续补发占用，请先更正后续补发')
    if kind=='return':
        from app.production.work_orders import committed_quantity
        restored_by_workline={}
        for line in lines:
            # 同一工单材料可从多次签收退回，整单更正必须合计恢复量后再核对普通发料额度。
            key=line.work_order_line_id
            restored_by_workline[key]=restored_by_workline.get(key,ZERO)+executed_quantity(db,line.id)
        for workline_id,restored in restored_by_workline.items():
            workline=db.get(WorkOrderLine,workline_id)
            if committed_quantity(db,workline_id)+restored>Decimal(workline.required_quantity):
                raise HTTPException(409,'退料释放的额度已被后续发料占用，请先更正后续发料')
    event=event_for(db,kind,header,payload,'reverse',user_id)
    facts=[(line,fact,event) for line in lines for fact,event in active_facts(db,line.id,('execute','handover_return'))]
    if not facts:
        raise HTTPException(409,'本单没有可更正的实际办理记录')
    for line,fact,original_event in facts:
        # 签收和旧料隔离虽不动良品库存，仍不能从当前日期绕过原事实的锁期。
        ensure_date_unlocked(db,original_event.created_at)
        if fact.source_movement_id:
            ensure_movement_unlocked(db,fact.source_movement_id)
        movement=db.get(StockMovement,fact.movement_id) if fact.movement_id else None
        reverse_movement=None
        next_id=(db.scalar(select(func.max(MaterialFlowExecutionLine.id))) or 0)+1
        if movement:
            ensure_movement_unlocked(db,movement.id)
            if Decimal(movement.quantity)>0 and balance(db,movement.warehouse_id,movement.material_id)<Decimal(movement.quantity):
                raise HTTPException(409,'已退回库存被后续使用，不能更正')
            reverse_movement=StockMovement(warehouse_id=movement.warehouse_id,material_id=movement.material_id,
                quantity=str(-Decimal(movement.quantity)),source_type=movement.source_type+'_reversal',source_id=identifier,
                source_line_id=next_id,created_by=user_id)
            parts=reversal_lots(db,movement)
            if parts:
                post_lot_movement(db,reverse_movement,parts)
            else:
                db.add(reverse_movement);db.flush()
        add_model(db,MaterialFlowExecutionLine(id=next_id,execution_id=event.id,line_id=line.id,
            quantity=str(-Decimal(fact.quantity)),movement_id=reverse_movement.id if reverse_movement else None,
            source_movement_id=movement.id if movement else fact.source_movement_id,reverses_line_id=fact.id))
    header.status='reversed';header.version+=1
    if kind=='dispatch':
        for receipt in receipts:
            receipt.status='reversed';receipt.version+=1
    elif kind=='receipt' and header.source_document_type=='dispatch':
        # 冲销签收后原发料仍待重新交接，原签收单保留更正事实并可重新签收。
        header.status='draft'
        for line in lines:
            if line.source_execution_line_id:
                origin=db.get(MaterialFlowExecutionLine,line.source_execution_line_id)
                dispatchline=db.get(MaterialFlowLine,origin.line_id)
                if dispatchline.exchange_line_id:
                    exchangeline=db.get(MaterialFlowLine,dispatchline.exchange_line_id)
                    exchange=document(db,'exchange',exchangeline.document_id)
                    refresh_status(db,'exchange',exchange);exchange.version+=1
    elif kind=='receipt':
        header.status='draft'
    approval.mark_executed(db,approved,user_id,permission=permission)
    return header
