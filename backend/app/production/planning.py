"""按确认需求展开多级 BOM，扣除库存与在途，并保留在制成本的截止日口径。"""
from datetime import date, timedelta
from decimal import Decimal, ROUND_CEILING
from sqlalchemy import select
from fastapi import HTTPException
from app.core import models as m
from app.production.work_orders import issued_quantity
from app.purchase.orders import received_quantity
from app.inventory.valuation import calculate_valuation


def mrp(db,warehouse_id,through_date):
    needed={};sources={};boms={};covered={};stock={}
    for material,quantity in db.execute(select(m.StockMovement.material_id,m.StockMovement.quantity).where(m.StockMovement.warehouse_id==warehouse_id)):
        stock[material]=stock.get(material,Decimal(0))+Decimal(quantity)
    for bom in db.scalars(select(m.Bom).where(m.Bom.status=='active').order_by(m.Bom.version)):
        boms[bom.product_material_id]=bom
    def add(material,quantity,source):
        needed[material]=needed.get(material,Decimal(0))+quantity
        sources.setdefault(material,set()).add(source)
    def explode(material,quantity,path,source):
        if material in path:raise HTTPException(409,'BOM 存在循环引用，须先更正再运行物料计划')
        if len(path)>20:raise HTTPException(422,'BOM 层级过深，请核对结构')
        bom=boms.get(material)
        if bom is None:add(material,quantity,source);return
        available=max(stock.get(material,Decimal(0))-covered.get(material,Decimal(0)),Decimal(0))
        used=min(available,quantity);covered[material]=covered.get(material,Decimal(0))+used;quantity-=used
        if quantity<=0:return
        for line in db.scalars(select(m.BomLine).where(m.BomLine.bom_id==bom.id)):
            requirement=(quantity*Decimal(line.quantity)/Decimal(bom.base_quantity)).quantize(Decimal('0.001'),rounding=ROUND_CEILING)
            explode(line.component_material_id,requirement,(*path,material),source)
    # 已建工单使用固定需料快照；销售未分配需求才重新展开 BOM，防止双重需求。
    for line,order in db.execute(select(m.WorkOrderLine,m.WorkOrder).join(m.WorkOrder,m.WorkOrder.id==m.WorkOrderLine.work_order_id)
        .where(m.WorkOrder.warehouse_id==warehouse_id,m.WorkOrder.status.in_(('draft','released','in_progress')))):
        remaining=Decimal(line.required_quantity)-issued_quantity(db,line.id)
        if remaining>0:add(line.component_material_id,remaining,f'工-{order.id}')
    for line,order in db.execute(select(m.SalesOrderLine,m.SalesOrder).join(m.SalesOrder,m.SalesOrder.id==m.SalesOrderLine.sales_order_id)
        .where(m.SalesOrder.status.in_(('confirmed','partially_shipped')))):
        allocated=sum((Decimal(value) for value in db.scalars(select(m.SalesWorkAllocation.quantity).join(m.WorkOrder,m.WorkOrder.id==m.SalesWorkAllocation.work_order_id)
            .where(m.SalesWorkAllocation.sales_order_line_id==line.id,m.WorkOrder.status!='cancelled'))),Decimal(0))
        from app.sales.orders import shipped_quantity
        remaining=max(Decimal(line.quantity)-max(allocated,shipped_quantity(db,line.id)),Decimal(0))
        if remaining:explode(line.material_id,remaining,(),f'销-{order.id}')
    incoming={};requested={}
    for material,quantity in db.execute(select(m.StockMovement.material_id,m.StockMovement.quantity).where(m.StockMovement.warehouse_id==warehouse_id)):
        stock[material]=stock.get(material,Decimal(0))+Decimal(quantity)
    for line in db.scalars(select(m.PurchaseOrderLine).join(m.PurchaseOrder,m.PurchaseOrder.id==m.PurchaseOrderLine.purchase_order_id)
        .where(m.PurchaseOrder.status.in_(('confirmed','partially_received')))):
        incoming[line.material_id]=incoming.get(line.material_id,Decimal(0))+max(Decimal(line.quantity)-received_quantity(db,line.id),Decimal(0))
    from app.purchase.requests import ordered_quantity
    for line in db.scalars(select(m.PurchaseRequestLine).join(m.PurchaseRequest,m.PurchaseRequest.id==m.PurchaseRequestLine.purchase_request_id).where(m.PurchaseRequest.status.not_in(('cancelled','rejected')))):
        requested[line.material_id]=requested.get(line.material_id,Decimal(0))+max(Decimal(line.quantity)-ordered_quantity(db,line.id),Decimal(0))
    policies={row.material_id:row for row in db.scalars(select(m.MaterialPlanningPolicy).where(m.MaterialPlanningPolicy.warehouse_id==warehouse_id))}
    rows=[]
    for identifier in sorted(set(needed)|set(policies)):
        material=db.get(m.Material,identifier);policy=policies.get(identifier)
        safety=Decimal(policy.safety_quantity) if policy else Decimal(0)
        shortage=max(needed.get(identifier,Decimal(0))+safety-stock.get(identifier,Decimal(0))-incoming.get(identifier,Decimal(0))-requested.get(identifier,Decimal(0)),Decimal(0))
        rows.append({'material_id':identifier,'sku':material.sku,'name':material.name,'unit':material.unit,'gross_quantity':str(needed.get(identifier,Decimal(0))),
            'stock_quantity':str(stock.get(identifier,Decimal(0))),'incoming_quantity':str(incoming.get(identifier,Decimal(0))),
            'requested_quantity':str(requested.get(identifier,Decimal(0))), 'safety_quantity':str(safety),'shortage_quantity':str(shortage),'need_date':through_date,
            'suggested_release_date':(date.fromisoformat(through_date)-timedelta(days=policy.lead_days if policy else 0)).isoformat(),
            'sources':'、'.join(sorted(sources.get(identifier,set())))})
    return rows


def wip(db,through_date):
    boundary=through_date+' 24:00:00';valuation=calculate_valuation(db,through_date=through_date)
    movements={row['source_line_id']:row['id'] for row in valuation.report['movements'] if row['source_type']=='material_issue'}
    rates={row.material_issue_line_id:Decimal(row.unit_cost) for row in db.scalars(select(m.ProductionCostEntry).where(m.ProductionCostEntry.kind=='material',m.ProductionCostEntry.created_at<boundary,
        ~select(m.ProductionCostReversal.id).where(m.ProductionCostReversal.entry_id==m.ProductionCostEntry.id,m.ProductionCostReversal.created_at<boundary).exists()))}
    rows=[]
    for order in db.scalars(select(m.WorkOrder).where(m.WorkOrder.created_at<boundary)):
        total=Decimal(0);unknown=0
        for line in db.scalars(select(m.MaterialIssueLine).join(m.MaterialIssue,m.MaterialIssue.id==m.MaterialIssueLine.material_issue_id).where(
            m.MaterialIssue.work_order_id==order.id,m.MaterialIssue.status=='posted',m.MaterialIssue.posted_at<boundary)):
            returned=sum((Decimal(q) for q in db.scalars(select(m.MaterialReturnLine.quantity).join(m.MaterialReturn,m.MaterialReturn.id==m.MaterialReturnLine.material_return_id)
                .where(m.MaterialReturnLine.material_issue_line_id==line.id,m.MaterialReturn.status=='posted',m.MaterialReturn.posted_at<boundary))),Decimal(0))
            quantity=Decimal(line.quantity)-returned
            rate=valuation.movement_costs.get(movements.get(line.id))
            if rate is None:rate=rates.get(line.id)
            if rate is None and quantity>0:unknown+=1
            elif rate is not None:total+=(quantity*rate).quantize(Decimal('0.01'))
        for entry in db.scalars(select(m.ProductionCostEntry).where(m.ProductionCostEntry.work_order_id==order.id,m.ProductionCostEntry.kind.in_(('labor','overhead')),
            m.ProductionCostEntry.created_at<boundary,~select(m.ProductionCostReversal.id).where(m.ProductionCostReversal.entry_id==m.ProductionCostEntry.id,m.ProductionCostReversal.created_at<boundary).exists())):total+=Decimal(entry.amount)
        valid_settlements=select(m.ProductionCostSettlement.id).where(m.ProductionCostSettlement.created_at<boundary,
            ~select(m.ProductionSettlementReversal.id).where(m.ProductionSettlementReversal.settlement_id==m.ProductionCostSettlement.id,m.ProductionSettlementReversal.created_at<boundary).exists())
        carry=sum((Decimal(q) for q in db.scalars(select(m.ProductionQualityCost.amount).join(m.QualityDisposition,m.QualityDisposition.id==m.ProductionQualityCost.disposition_id)
            .where(m.QualityDisposition.rework_order_id==order.id,m.ProductionQualityCost.settlement_id.in_(valid_settlements)))),Decimal(0));total+=carry
        settlement_ids=valid_settlements.where(m.ProductionCostSettlement.work_order_id==order.id)
        finished=sum((Decimal(q) for q in db.scalars(select(m.ProductionCostAllocation.amount).where(m.ProductionCostAllocation.settlement_id.in_(settlement_ids)))),Decimal(0))
        quality=sum((Decimal(q) for q in db.scalars(select(m.ProductionQualityCost.amount).where(m.ProductionQualityCost.settlement_id.in_(settlement_ids)))),Decimal(0))
        rows.append({'work_order_id':order.id,'through_date':through_date,'accumulated_amount':None if unknown else f'{total:.2f}',
            'finished_amount':f'{finished:.2f}','quality_amount':f'{quality:.2f}','carried_amount':f'{carry:.2f}',
            'wip_amount':None if unknown else f'{total-finished-quality:.2f}','unpriced_count':unknown})
    return {'rows':rows,'totals':{'wip_amount':f"{sum((Decimal(row['wip_amount']) for row in rows if row['wip_amount'] is not None),Decimal(0)):.2f}",
        'unpriced_orders':str(sum(row['unpriced_count']>0 for row in rows))}}
