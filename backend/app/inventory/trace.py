"""单据独立编号，按明细数量及库存批次双向追溯，输出不含商务金额或客户联系方式。"""
import json
from decimal import Decimal
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, delete
from app.access.security import require
from app.core.orm import orm_session, add_model
from app.core import models as m
from app.query.snapshots import snapshot_metadata
from app.inventory.lots import balance

router=APIRouter(prefix='/api/v1/trace')


class AllocationLine(BaseModel):
    model_config=ConfigDict(extra='forbid')
    sales_order_line_id:int=Field(gt=0,strict=True)
    quantity:Decimal=Field(gt=0,le=1000000,decimal_places=3)


class AllocationInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    work_order_id:int=Field(gt=0,strict=True)
    lines:list[AllocationLine]=Field(max_length=100)
    reason:str=Field(min_length=1,max_length=200)


@router.put('/allocations')
def allocate(payload:AllocationInput,user:dict=Depends(require('work_order.create'))):
    with orm_session(write=True) as db:
        order=db.get(m.WorkOrder,payload.work_order_id)
        if order is None:raise HTTPException(404,'生产工单不存在')
        if order.status not in ('draft','released'):raise HTTPException(409,'已完成或已取消工单不能修改销售需求分配')
        if not payload.reason.strip():raise HTTPException(422,'请填写分配原因')
        if len({line.sales_order_line_id for line in payload.lines})!=len(payload.lines):raise HTTPException(422,'不能重复分配同一销售明细')
        if sum((line.quantity for line in payload.lines),Decimal(0))>Decimal(order.target_quantity):raise HTTPException(409,'销售分配合计超过工单产量')
        product=db.get(m.Bom,order.bom_id).product_material_id
        for line in payload.lines:
            sales_line=db.get(m.SalesOrderLine,line.sales_order_line_id)
            sales=db.get(m.SalesOrder,sales_line.sales_order_id) if sales_line else None
            if sales_line is None or sales_line.material_id!=product or sales.status not in ('confirmed','partially_shipped','completed'):raise HTTPException(409,'请选择有效销售订单中相同成品的明细')
            occupied=sum((Decimal(q) for q in db.scalars(select(m.SalesWorkAllocation.quantity).join(m.WorkOrder,m.WorkOrder.id==m.SalesWorkAllocation.work_order_id)
                .where(m.SalesWorkAllocation.sales_order_line_id==line.sales_order_line_id,m.SalesWorkAllocation.work_order_id!=order.id,m.WorkOrder.status!='cancelled'))),Decimal(0))
            if occupied+line.quantity>Decimal(sales_line.quantity):raise HTTPException(409,'分配超过销售明细需求，已有其他工单占用')
        db.execute(delete(m.SalesWorkAllocation).where(m.SalesWorkAllocation.work_order_id==order.id))
        db.add_all([m.SalesWorkAllocation(work_order_id=order.id,sales_order_line_id=line.sales_order_line_id,quantity=str(line.quantity),created_by=user['id']) for line in payload.lines])
        db.add(m.TraceAudit(work_order_id=order.id,evidence_json=json.dumps([line.model_dump(mode='json') for line in payload.lines],ensure_ascii=False),reason=payload.reason.strip(),created_by=user['id']))
        return {'work_order_id':order.id,'allocated_quantity':str(sum((line.quantity for line in payload.lines),Decimal(0)))}


class TraceQuery(BaseModel):
    model_config=ConfigDict(extra='forbid')
    kind:Literal['sales_order','work_order','shipment','lot','receipt']
    id:int=Field(gt=0,strict=True)


MODELS={'sales_order':m.SalesOrder,'work_order':m.WorkOrder,'shipment':m.Shipment,'receipt':m.Receipt,
    'material_issue':m.MaterialIssue,'material_return':m.MaterialReturn,'production_completion':m.ProductionCompletion,
    'sales_return':m.SalesReturn,'purchase_return':m.PurchaseReturn,'transfer':m.Transfer,'stocktake':m.Stocktake,
    'adjustment':m.StockAdjustment,'other_inbound':m.WarehouseInbound,'other_outbound':m.WarehouseOutbound,'lot':m.InventoryLot}
LABELS={'sales_order':'销','work_order':'工','shipment':'出','receipt':'入','material_issue':'领','material_return':'退料',
    'production_completion':'完','sales_return':'销退','purchase_return':'采退','transfer':'调','stocktake':'盘','adjustment':'调账',
    'other_inbound':'其他入','other_outbound':'其他出','lot':'批次','movement':'流水'}


# 冲销单编号与原单编号是不同序列，必须通过冲销关系回到原单。
REVERSALS={
    'receipt':(m.ReceiptReversal,'receipt_id'), 'shipment':(m.ShipmentReversal,'shipment_id'),
    'sales_return':(m.SalesReturnReversal,'sales_return_id'), 'purchase_return':(m.PurchaseReturnReversal,'purchase_return_id'),
    'production_completion':(m.ProductionCompletionReversal,'production_completion_id'),
    'transfer':(m.TransferReversal,'transfer_id'), 'stocktake':(m.StocktakeReversal,'stocktake_id'),
    'adjustment':(m.StockAdjustmentReversal,'adjustment_id'), 'other_inbound':(m.WarehouseInboundReversal,'inbound_id'),
    'other_outbound':(m.WarehouseOutboundReversal,'outbound_id')}


def movement_document(db,row):
    kind='transfer' if row.source_type.startswith('transfer_') else row.source_type.removesuffix('_reversal')
    if kind not in MODELS:return None
    identifier=row.source_id
    if 'reversal' in row.source_type:
        model,field=REVERSALS[kind];reversal=db.get(model,row.source_id)
        if reversal is None:return None
        identifier=getattr(reversal,field)
    return kind,identifier


@router.post('/query')
def query_trace(payload:TraceQuery,user:dict=Depends(require('trace.view'))):
    with orm_session() as db:
        nodes={};edges=[];queue=[(payload.kind,payload.id)];seen=set();edge_keys=set()
        def link(parent,child,quantity,relation):
            key=(parent,child,str(quantity),relation)
            if key not in edge_keys:
                edge_keys.add(key);edges.append({'from':f'{parent[0]}:{parent[1]}','to':f'{child[0]}:{child[1]}','quantity':str(quantity),'relation':relation})
            if child not in seen:queue.append(child)
        while queue:
            kind,identifier=queue.pop(0)
            if (kind,identifier) in seen:continue
            seen.add((kind,identifier))
            if len(seen)>1000:raise HTTPException(422,'关联范围超过一千个节点，请从工单或批次缩小查询')
            model=m.StockMovement if kind=='movement' else MODELS.get(kind)
            row=db.get(model,identifier) if model else None
            if row is None:
                if len(seen)==1:raise HTTPException(404,'溯源起点不存在')
                continue
            node={'key':f'{kind}:{identifier}','number':row.code if kind=='lot' else f'{LABELS.get(kind,kind)}-{identifier}',
                'kind':kind,'status':getattr(row,'status',''),'reference':getattr(row,'reference',''),'created_at':row.created_at,'basis':getattr(row,'basis','单据原始关联')}
            nodes[node['key']]=node;parent=(kind,identifier)
            if kind=='sales_order':
                for alloc in db.scalars(select(m.SalesWorkAllocation).join(m.SalesOrderLine,m.SalesOrderLine.id==m.SalesWorkAllocation.sales_order_line_id).where(m.SalesOrderLine.sales_order_id==identifier)):
                    link(parent,('work_order',alloc.work_order_id),alloc.quantity,'销售需求分配')
                for child in db.scalars(select(m.Shipment).where(m.Shipment.sales_order_id==identifier)):link(parent,('shipment',child.id),'','销售出库')
            if kind=='work_order':
                for alloc in db.scalars(select(m.SalesWorkAllocation).where(m.SalesWorkAllocation.work_order_id==identifier)):
                    sales=db.get(m.SalesOrderLine,alloc.sales_order_line_id);link(parent,('sales_order',sales.sales_order_id),alloc.quantity,'对应销售需求')
                for child_kind,child_model in [('material_issue',m.MaterialIssue),('production_completion',m.ProductionCompletion)]:
                    for child in db.scalars(select(child_model).where(child_model.work_order_id==identifier)):link(parent,(child_kind,child.id),getattr(child,'accepted_quantity',''),'生产单据')
            if kind=='material_return':link(parent,('material_issue',row.material_issue_id),'','原领料单')
            if kind=='material_issue':
                for child in db.scalars(select(m.MaterialReturn).where(m.MaterialReturn.material_issue_id==identifier)):link(parent,('material_return',child.id),'','生产退料')
            if kind in ('material_issue','production_completion'):link(parent,('work_order',row.work_order_id),'','工单来源')
            if kind=='production_completion':
                for child in db.scalars(select(m.QualityDisposition).where(m.QualityDisposition.completion_id==identifier)):
                    if child.rework_order_id:link(parent,('work_order',child.rework_order_id),child.quantity,'不合格品返工')
            if kind=='shipment':
                link(parent,('sales_order',row.sales_order_id),'','订单来源')
                for returned in db.scalars(select(m.SalesReturn).where(m.SalesReturn.shipment_id==identifier)):link(parent,('sales_return',returned.id),'','出库退货')
            if kind=='sales_return':link(parent,('shipment',row.shipment_id),'','原出库')
            if kind=='lot':
                node['material_id']=row.material_id
                for alloc in db.scalars(select(m.MovementLot).where(m.MovementLot.lot_id==identifier)):link(parent,('movement',alloc.movement_id),alloc.quantity,'批次流转')
                node['warehouse_balances']='；'.join(f'{warehouse.name}: {balance(db,row,warehouse.id)}' for warehouse in db.scalars(select(m.Warehouse)) if balance(db,row,warehouse.id)!=0)
            elif kind=='movement':
                node.update(material_id=row.material_id,warehouse_id=row.warehouse_id,quantity=row.quantity)
                doc=movement_document(db,row)
                if doc:link(parent,doc,row.quantity,'库存单据来源')
                for alloc in db.scalars(select(m.MovementLot).where(m.MovementLot.movement_id==identifier)):link(parent,('lot',alloc.lot_id),alloc.quantity,'系统批次分配')
            else:
                source_kinds=['transfer_in','transfer_out'] if kind=='transfer' else [kind]
                for movement in db.scalars(select(m.StockMovement).where(m.StockMovement.source_type.in_(source_kinds),m.StockMovement.source_id==identifier)):
                    link(parent,('movement',movement.id),movement.quantity,'库存确认')
                if kind in REVERSALS:
                    model,field=REVERSALS[kind]
                    reversal_ids=select(model.id).where(getattr(model,field)==identifier)
                    types=['transfer_reversal_in','transfer_reversal_out'] if kind=='transfer' else [kind+'_reversal']
                    for movement in db.scalars(select(m.StockMovement).where(m.StockMovement.source_type.in_(types),m.StockMovement.source_id.in_(reversal_ids))):
                        link(parent,('movement',movement.id),movement.quantity,'库存冲销')
        # 列表只输出操作资料；金额隔离无需依赖前端隐藏列。
        return snapshot_metadata({'nodes':list(nodes.values()),'edges':edges,'rows':list(nodes.values()),'csv':'','totals':{'nodes':len(nodes),'edges':len(edges)}},user,('nodes','edges','rows'))
