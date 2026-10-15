"""生产物料事实与额度：签收、库存和正常 BOM 额度分别核算。"""

from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.models import (
    MaterialDispatch, MaterialReceipt, MaterialExchange, ProductionMaterialReturn,
    MaterialFlowLine, MaterialFlowExecution, MaterialFlowExecutionLine,
    MaterialIssue, MaterialIssueLine, MaterialIssueReversal, MaterialReturn,
    MaterialReturnLine, MaterialReturnReversal, WorkOrderLine, StockMovement,
)

MODELS = {'dispatch': MaterialDispatch, 'receipt': MaterialReceipt,
          'exchange': MaterialExchange, 'return': ProductionMaterialReturn}
APPROVAL_NAMES = {'dispatch': 'MaterialDispatch', 'exchange': 'MaterialExchange',
                  'return': 'ProductionMaterialReturn'}
PERMISSIONS = {'dispatch': 'material_dispatch', 'exchange': 'material_exchange',
               'return': 'material_flow_return', 'receipt': 'material_receipt'}
ZERO = Decimal(0)


def document(db, kind, identifier):
    if kind not in MODELS:
        raise HTTPException(422, '物料业务类型无效')
    row = db.get(MODELS[kind], identifier)
    if row is None:
        raise HTTPException(404, '生产物料单据不存在')
    return row


def lines_for(db, kind, identifier):
    return list(db.scalars(select(MaterialFlowLine).where(
        MaterialFlowLine.document_type == kind, MaterialFlowLine.document_id == identifier)
        .order_by(MaterialFlowLine.id)))


def active_facts(db: Session, line_id: int, actions: tuple[str, ...] | None = None):
    # 更正追加反向记录；原事实仍存在，但数量口径排除已经被更正的原记录。
    reversed_ids = select(MaterialFlowExecutionLine.reverses_line_id).where(
        MaterialFlowExecutionLine.reverses_line_id.is_not(None))
    query = select(MaterialFlowExecutionLine, MaterialFlowExecution).join(
        MaterialFlowExecution, MaterialFlowExecution.id == MaterialFlowExecutionLine.execution_id).where(
        MaterialFlowExecutionLine.line_id == line_id,
        MaterialFlowExecutionLine.reverses_line_id.is_(None),
        MaterialFlowExecutionLine.id.not_in(reversed_ids))
    if actions:
        query = query.where(MaterialFlowExecution.action.in_(actions))
    return list(db.execute(query.order_by(MaterialFlowExecutionLine.id)))


def executed_quantity(db, line_id, action='execute') -> Decimal:
    return sum((Decimal(fact.quantity) for fact, _ in active_facts(db, line_id, (action,))), ZERO)


def received_for_dispatch_line(db, line_id) -> Decimal:
    execution_ids = select(MaterialFlowExecutionLine.id).where(MaterialFlowExecutionLine.line_id == line_id)
    receipt_ids = db.scalars(select(MaterialFlowLine.id).where(MaterialFlowLine.document_type == 'receipt',
        MaterialFlowLine.source_execution_line_id.in_(execution_ids)))
    return sum((executed_quantity(db, identifier) for identifier in receipt_ids), ZERO)



def handover_for_dispatch_line(db, line_id) -> Decimal:
    execution_ids=select(MaterialFlowExecutionLine.id).where(MaterialFlowExecutionLine.line_id==line_id)
    receipt_ids=db.scalars(select(MaterialFlowLine.id).where(MaterialFlowLine.document_type=='receipt',MaterialFlowLine.source_execution_line_id.in_(execution_ids)))
    return sum((executed_quantity(db,identifier,'handover_return') for identifier in receipt_ids),ZERO)


def replacement_committed(db, line):
    header=document(db,'dispatch',line.document_id)
    if header.status=='reversed':
        return ZERO
    return (executed_quantity(db,line.id) if header.status=='closed' else Decimal(line.quantity))-handover_for_dispatch_line(db,line.id)

def exchange_progress(db, line_id) -> tuple[Decimal, Decimal]:
    dispatched = signed = ZERO
    for line in db.scalars(select(MaterialFlowLine).where(MaterialFlowLine.document_type == 'dispatch',
            MaterialFlowLine.exchange_line_id == line_id)):
        dispatched += executed_quantity(db, line.id)
        signed += received_for_dispatch_line(db, line.id)
    return dispatched, signed


def source_movement(db, line: MaterialFlowLine):
    if line.source_execution_line_id:
        fact = db.get(MaterialFlowExecutionLine, line.source_execution_line_id)
        return db.get(StockMovement, fact.movement_id) if fact and fact.movement_id else None
    if line.source_receipt_line_id:
        return source_movement(db, db.get(MaterialFlowLine, line.source_receipt_line_id))
    if line.legacy_issue_line_id:
        return db.scalar(select(StockMovement).where(StockMovement.source_type == 'material_issue',
            StockMovement.source_line_id == line.legacy_issue_line_id))
    return None


def claimed_quantity(db, source_receipt_line_id=None, legacy_issue_line_id=None, exclude_document=None):
    query = select(MaterialFlowLine).where(MaterialFlowLine.document_type.in_(('return','exchange')))
    query = query.where(MaterialFlowLine.source_receipt_line_id == source_receipt_line_id) if source_receipt_line_id else query.where(
        MaterialFlowLine.legacy_issue_line_id == legacy_issue_line_id)
    total = ZERO
    for line in db.scalars(query):
        if exclude_document == (line.document_type, line.document_id):
            continue
        header = document(db, line.document_type, line.document_id)
        if header.status == 'reversed':
            continue
        total += executed_quantity(db, line.id) if header.status == 'closed' else Decimal(line.quantity)
    return total


def legacy_source_remaining(db, legacy_issue_line_id, exclude_document_id=None, exclude_legacy_return_id=None) -> Decimal:
    line = db.get(MaterialIssueLine, legacy_issue_line_id)
    issue = db.get(MaterialIssue, line.material_issue_id) if line else None
    if not issue or issue.status != 'posted' or db.scalar(select(MaterialIssueReversal.id).where(
            MaterialIssueReversal.material_issue_id == issue.id)):
        return ZERO
    if issue.historical_direct:
        quantity = Decimal(line.quantity)
    else:
        receipts = db.scalars(select(MaterialFlowLine).where(MaterialFlowLine.document_type == 'receipt',
            MaterialFlowLine.legacy_issue_line_id == line.id))
        quantity = sum((executed_quantity(db, receipt.id) for receipt in receipts), ZERO)
    returned = db.scalars(select(MaterialReturnLine.quantity).join(MaterialReturn,
        MaterialReturn.id == MaterialReturnLine.material_return_id).where(
        MaterialReturnLine.material_issue_line_id == line.id, MaterialReturn.status != 'cancelled',
        MaterialReturn.id != (exclude_legacy_return_id or -1),
        MaterialReturn.id.not_in(select(MaterialReturnReversal.material_return_id))))
    # 旧草稿退料同样占用来源，避免新旧入口同时办理同一份实物。
    return quantity - sum((Decimal(value) for value in returned), ZERO) - claimed_quantity(
        db, legacy_issue_line_id=line.id, exclude_document=exclude_document_id)


def source_available(db, line: MaterialFlowLine, exclude_document=None) -> Decimal:
    if line.source_receipt_line_id:
        receipt = db.get(MaterialFlowLine, line.source_receipt_line_id)
        if receipt is None or receipt.document_type != 'receipt' or receipt.work_order_line_id != line.work_order_line_id:
            raise HTTPException(422, '签收来源不属于本工单材料')
        # 旧接口发料的签收统一用旧行来源，避免两个来源键各自重复取得额度。
        if receipt.legacy_issue_line_id:
            raise HTTPException(422, '历史接口签收请使用原领料明细作为来源')
        return executed_quantity(db, receipt.id) - claimed_quantity(db,
            source_receipt_line_id=receipt.id, exclude_document=exclude_document)
    if line.legacy_issue_line_id:
        original = db.get(MaterialIssueLine, line.legacy_issue_line_id)
        if original is None or original.work_order_line_id != line.work_order_line_id:
            raise HTTPException(422, '历史领料来源不属于本工单材料')
        return legacy_source_remaining(db, original.id, exclude_document)
    raise HTTPException(422, '退换料必须选择已签收来源')


def flow_quantities(db: Session, work_order_line_id: int) -> dict[str, Decimal]:
    result = {key: ZERO for key in ('dispatched','signed','returned','damaged','reserved','in_transit','committed','effective','pending_dispatch')}
    for line in db.scalars(select(MaterialFlowLine).where(MaterialFlowLine.work_order_line_id == work_order_line_id)):
        header = document(db, line.document_type, line.document_id)
        if header.status == 'reversed':
            continue
        actual = executed_quantity(db, line.id)
        if line.document_type == 'dispatch':
            result['dispatched'] += actual
            # 未执行的发料计划单独展示；已关闭余额不再待发，换料补发仍须计入待办。
            if header.status != 'closed':
                result['pending_dispatch'] += max(ZERO, Decimal(line.quantity) - actual)
            if not line.exchange_line_id:
                result['committed'] += actual if header.status == 'closed' else Decimal(line.quantity)
        elif line.document_type == 'receipt':
            result['signed'] += actual
            handover = executed_quantity(db, line.id, 'handover_return')
            result['in_transit'] += Decimal(line.quantity) - actual - handover
            if header.source_document_type == 'legacy_issue':
                # 历史接口的新发料同样待签；升级前旧单由调用方独立保留原口径。
                result['dispatched'] += Decimal(line.quantity)
                result['committed'] += Decimal(line.quantity)
            original=db.get(MaterialFlowExecutionLine,line.source_execution_line_id) if line.source_execution_line_id else None
            dispatch_line=db.get(MaterialFlowLine,original.line_id) if original else None
            if dispatch_line is None or not dispatch_line.exchange_line_id:
                result['committed'] -= handover
        elif line.document_type in ('return', 'exchange'):
            result['returned' if line.document_type == 'return' else 'damaged'] += actual
            if header.status != 'closed':
                result['reserved'] += Decimal(line.quantity) - actual
            if line.document_type == 'return':
                result['committed'] -= actual
    result['effective'] = result['signed'] - result['returned'] - result['damaged'] - result['reserved']
    return result


def pending_material_flow(db, work_order_id) -> bool:
    if db.scalar(select(MaterialIssue.id).where(MaterialIssue.work_order_id == work_order_id, MaterialIssue.status == 'draft').limit(1)):
        return True
    if db.scalar(select(MaterialReturn.id).join(MaterialIssue, MaterialIssue.id == MaterialReturn.material_issue_id).where(MaterialIssue.work_order_id == work_order_id,MaterialReturn.status == 'draft').limit(1)):
        return True
    return any(db.scalar(select(model.id).where(model.work_order_id == work_order_id,
        model.status.not_in(('completed', 'closed', 'reversed'))).limit(1)) for model in MODELS.values())


def flow_returned_for_movement(db, movement_id) -> Decimal:
    reversed_ids = select(MaterialFlowExecutionLine.reverses_line_id).where(MaterialFlowExecutionLine.reverses_line_id.is_not(None))
    rows = db.execute(select(MaterialFlowExecutionLine, MaterialFlowExecution).join(MaterialFlowExecution,
        MaterialFlowExecution.id == MaterialFlowExecutionLine.execution_id).where(
        MaterialFlowExecutionLine.source_movement_id == movement_id,
        MaterialFlowExecutionLine.movement_id.is_not(None), MaterialFlowExecutionLine.reverses_line_id.is_(None),
        MaterialFlowExecutionLine.id.not_in(reversed_ids), MaterialFlowExecution.action.in_(('execute','handover_return'))))
    return sum((Decimal(row.quantity) for row, event in rows if event.document_type == 'return' or event.action == 'handover_return'), ZERO)


def flow_cost_sources(db, work_order_id) -> list[dict]:
    results = []
    for header in db.scalars(select(MaterialDispatch).where(MaterialDispatch.work_order_id == work_order_id)):
        for line in lines_for(db,'dispatch',header.id):
            for fact, _ in active_facts(db,line.id,('execute',)):
                movement = db.get(StockMovement,fact.movement_id)
                returned = flow_returned_for_movement(db,movement.id)
                results.append({'execution_line_id':fact.id,'movement_id':movement.id,
                    'work_order_line_id':line.work_order_line_id,'material_id':movement.material_id,
                    'quantity':Decimal(fact.quantity),'returned_quantity':returned,
                    'net_quantity':Decimal(fact.quantity)-returned,'dispatch_id':header.id,'document_no':header.document_no})
    return results


def ensure_legacy_receipt_reversible(db, issue_id):
    source_ids=select(MaterialIssueLine.id).where(MaterialIssueLine.material_issue_id==issue_id)
    for child in db.scalars(select(MaterialFlowLine).where(MaterialFlowLine.document_type.in_(('return','exchange')),MaterialFlowLine.legacy_issue_line_id.in_(source_ids))):
        header=document(db,child.document_type,child.document_id)
        if header.status not in ('reversed','closed') or active_facts(db,child.id):
            raise HTTPException(409,'原领料已有退换料依赖，请先按依赖顺序更正')
    for header in db.scalars(select(MaterialReceipt).where(MaterialReceipt.source_document_type=='legacy_issue',
            MaterialReceipt.source_document_id==issue_id)):
        if any(active_facts(db,line.id) for line in lines_for(db,'receipt',header.id)):
            raise HTTPException(409,'领料已有签收或交接退回，请先按依赖顺序更正')
        header.status='reversed'
        header.version+=1
