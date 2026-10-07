"""生产单据只读关联；固定实物分配与同物料采购参考明确分开。"""

from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import select
from app.access.security import require
from app.core.orm import orm_session
from app.core.models import (Bom, Material, WorkOrder, WorkOrderLine, MaterialIssue, MaterialIssueLine,
    MaterialIssueReversal, MaterialReturn, MaterialReturnLine, MaterialReturnReversal,
    ProductionCompletion, ProductionCompletionReversal, StockMovement, PhysicalLot,
    PhysicalLotAllocation, PhysicalLotMovementEvidence, Receipt, ReceiptLine, ReceiptReversal, Supplier)
from app.production.work_orders import issued_quantity

router = APIRouter(prefix='/api/v1')


def document(row, reversal=None):
    # 仅投影生产查询需要的身份、状态及冲销依据，不返回成本、客户或财务信息。
    return dict(id=row.id, document_no=row.document_no, reference=row.reference if hasattr(row,'reference') else '',
        status='reversed' if reversal else row.status, created_at=row.created_at,
        posted_at=getattr(row,'posted_at',None), reversal_reason=reversal.reason if reversal else None)


def issue_sources(db, issue, line, material_id):
    movement = db.scalar(select(StockMovement).where(StockMovement.source_type=='material_issue',
        StockMovement.source_id==issue.id, StockMovement.source_line_id==line.id))
    if movement is None:return [],line.quantity
    quantities={}; kinds={}
    # 正式分配和追加补证均按原始流水、批次 ID 累计；补证冲销的正负数量相抵。
    for model,kind in ((PhysicalLotAllocation,'allocation'),(PhysicalLotMovementEvidence,'supplement')):
        for row in db.scalars(select(model).where(model.movement_id==movement.id)):
            quantities[row.lot_id]=quantities.get(row.lot_id,Decimal(0))-Decimal(row.quantity)
            kinds.setdefault(row.lot_id,set()).add(kind)
    result=[]
    for lot_id,quantity in sorted(quantities.items()):
        if quantity<=0:continue
        lot=db.get(PhysicalLot,lot_id)
        if lot is None or lot.material_id!=material_id:continue
        origin=db.get(StockMovement,lot.origin_movement_id) if lot.origin_movement_id else None
        source=dict(lot_id=lot.id,lot_code=lot.code,quantity=format(quantity,'f'),
            evidence_kind='supplement' if 'supplement' in kinds[lot_id] else 'allocation',
            origin_movement_id=origin.id if origin else None,source_type=origin.source_type if origin else None,
            source_id=origin.source_id if origin else None,source_document_no=None,
            supplier_id=None,supplier_name=None,receipt_reversed=False)
        # 必须沿真实批次原始入库流水及其明细核对；同名批号、FIFO 或成本均不是证据。
        if origin and origin.source_type=='receipt' and origin.material_id==material_id and Decimal(origin.quantity)>0:
            receipt=db.get(Receipt,origin.source_id);receipt_line=db.get(ReceiptLine,origin.source_line_id)
            # 原始入库也可能在事后补证，须累计有效证据；撤销的补证不能继续证明来源。
            original_quantity=sum((Decimal(part.quantity) for model in (PhysicalLotAllocation,PhysicalLotMovementEvidence)
                for part in db.scalars(select(model).where(model.lot_id==lot.id,model.movement_id==origin.id))),Decimal(0))
            if receipt and receipt_line and receipt_line.receipt_id==receipt.id and receipt_line.material_id==material_id and original_quantity>0:
                supplier=db.get(Supplier,receipt.supplier_id)
                source.update(source_document_no=receipt.document_no,supplier_id=receipt.supplier_id,
                    supplier_name=supplier.name if supplier else None,
                    receipt_reversed=db.scalar(select(ReceiptReversal.id).where(ReceiptReversal.receipt_id==receipt.id)) is not None)
        result.append(source)
    assigned=sum((Decimal(r['quantity']) for r in result),Decimal(0))
    return result,format(Decimal(line.quantity)-assigned,'f')


def associations(db,work,kind,identifier,inventory_visible,include_references):
    bom=db.get(Bom,work.bom_id);product=db.get(Material,bom.product_material_id)
    components=[];cutoff=work.created_at
    for line in db.scalars(select(WorkOrderLine).where(WorkOrderLine.work_order_id==work.id).order_by(WorkOrderLine.id)):
        material=db.get(Material,line.component_material_id);issues=[]
        for issue_line,issue in db.execute(select(MaterialIssueLine,MaterialIssue).join(MaterialIssue,
            MaterialIssue.id==MaterialIssueLine.material_issue_id).where(MaterialIssueLine.work_order_line_id==line.id).order_by(MaterialIssue.id)):
            reverse=db.scalar(select(MaterialIssueReversal).where(MaterialIssueReversal.material_issue_id==issue.id))
            effective=issue.status=='posted' and reverse is None
            if effective:cutoff=max(cutoff,issue.posted_at or issue.created_at)
            returns=[];returned=Decimal(0)
            for return_line,record in db.execute(select(MaterialReturnLine,MaterialReturn).join(MaterialReturn,
                MaterialReturn.id==MaterialReturnLine.material_return_id).where(MaterialReturnLine.material_issue_line_id==issue_line.id).order_by(MaterialReturn.id)):
                reversed_return=db.scalar(select(MaterialReturnReversal).where(MaterialReturnReversal.material_return_id==record.id))
                active=record.status=='posted' and reversed_return is None
                if active:returned+=Decimal(return_line.quantity)
                returns.append(dict(**document(record,reversed_return),line_id=return_line.id,quantity=return_line.quantity,effective=active))
            sources,gap=issue_sources(db,issue,issue_line,material.id) if inventory_visible and issue.status=='posted' else ([],None)
            issues.append(dict(**document(issue,reverse),line_id=issue_line.id,quantity=issue_line.quantity,
                effective=effective,returned_quantity=format(returned,'f'),returns=returns,sources=sources,unassigned_quantity=gap))
        components.append(dict(id=line.id,material_id=material.id,sku=material.sku,name=material.name,unit=material.unit,
            required_quantity=line.required_quantity,net_issued_quantity=format(issued_quantity(db,line.id),'f'),issues=issues,purchase_references=[]))
    completions=[]
    for row in db.scalars(select(ProductionCompletion).where(ProductionCompletion.work_order_id==work.id).order_by(ProductionCompletion.id)):
        reverse=db.scalar(select(ProductionCompletionReversal).where(ProductionCompletionReversal.production_completion_id==row.id))
        completions.append(dict(**document(row,reverse),reported_quantity=row.reported_quantity,
            accepted_quantity=row.accepted_quantity,rejected_quantity=row.rejected_quantity,effective=row.status=='posted' and reverse is None))
    if inventory_visible and include_references:
        for component in components:
            # 限定截至最后有效领料时的最近五十条入库；参考不代表本仓结存或实际使用。
            for line,receipt,supplier in db.execute(select(ReceiptLine,Receipt,Supplier).join(Receipt,
                Receipt.id==ReceiptLine.receipt_id).join(Supplier,Supplier.id==Receipt.supplier_id).where(
                ReceiptLine.material_id==component['material_id'],Receipt.status=='posted',Receipt.posted_at<=cutoff,
                ~select(ReceiptReversal.id).where(ReceiptReversal.receipt_id==Receipt.id).exists())
                .order_by(Receipt.posted_at.desc(),Receipt.id.desc(),ReceiptLine.id.desc()).limit(50)):
                component['purchase_references'].append(dict(receipt_id=receipt.id,document_no=receipt.document_no,
                    line_id=line.id,quantity=line.quantity,posted_at=receipt.posted_at,
                    supplier_id=supplier.id,supplier_name=supplier.name))
    return dict(target=dict(kind=kind,id=identifier),scope='work_order',inventory_visible=inventory_visible,
        references_included=inventory_visible and include_references,reference_cutoff=cutoff,reference_limit=50,
        work_order=dict(**document(work),target_quantity=work.target_quantity,product_name=product.name,product_sku=product.sku),
        bom=dict(id=bom.id,version=bom.version,base_quantity=bom.base_quantity),components=components,completions=completions)


@router.get('/work-orders/{identifier}/associations')
def work_order_associations(identifier:int=Path(gt=0),include_references:bool=Query(False),
                            user:dict=Depends(require('production.view'))):
    with orm_session() as db:
        work=db.get(WorkOrder,identifier)
        if work is None:raise HTTPException(404,'生产工单不存在')
        return associations(db,work,'work_order',identifier,'inventory.view' in user['permissions'],include_references)


@router.get('/production-completions/{identifier}/associations')
def completion_associations(identifier:int=Path(gt=0),include_references:bool=Query(False),
                            user:dict=Depends(require('production.view'))):
    with orm_session() as db:
        completion=db.get(ProductionCompletion,identifier)
        if completion is None:raise HTTPException(404,'完工单不存在')
        return associations(db,db.get(WorkOrder,completion.work_order_id),'completion',identifier,
            'inventory.view' in user['permissions'],include_references)
