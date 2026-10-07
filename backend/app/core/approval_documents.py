"""审批领域适配器；明细快照和可执行状态必须由服务端业务模型生成。"""

from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import (
    DocumentApprovalCase, Material, PurchaseGoodsReceipt, PurchaseGoodsReceiptLine, PurchaseOrder, PurchaseOrderLine,
    PurchaseOrderRequestLink, Receipt, ReceiptLine, ReceiptOrderLink, ReceiptReversal,
    ReceiptWarehouse, Supplier, Warehouse, WarehouseInbound, WarehouseInboundLine,
    WarehouseInboundReversal, PurchaseReturn, PurchaseReturnLine, PurchaseReturnReversal,
    WarehouseOutbound, WarehouseOutboundLine, WarehouseOutboundReversal, MaintenanceJob, MaintenanceChange,
    AfterSalesCase, AfterSalesChange, Transfer, TransferLine, TransferReversal,
    Stocktake, StocktakeLine, StocktakeReversal, StockAdjustment, StockAdjustmentLine, StockAdjustmentReversal,
)
from app.core.approval_catalog import approval_type


def inbound_snapshot(db: Session, identifier: int) -> dict:
    source = db.get(WarehouseInbound, identifier)
    if source is None:
        raise HTTPException(404, '其他入库单不存在')
    # 不纳入流程时间、展示编号或基础资料名称；核对的是入库业务内容本身。
    return {'warehouse_id': source.warehouse_id, 'reason': source.reason,
            'note': source.note, 'reference': source.reference,
            'lines': [{'id': line.id, 'material_id': line.material_id, 'quantity': line.quantity}
                      for line in db.scalars(select(WarehouseInboundLine).where(
                          WarehouseInboundLine.inbound_id == identifier).order_by(WarehouseInboundLine.id))]}


def purchase_order_snapshot(db: Session, identifier: int) -> dict:
    source = document_source(db, 'PurchaseOrder', identifier)
    # 采购数量、价格和申请关联全部固定；收货进度属于执行结果，不纳入正文。
    lines = [dict(row) for row in db.execute(select(
        PurchaseOrderLine.id, PurchaseOrderLine.material_id, PurchaseOrderLine.quantity,
        PurchaseOrderLine.unit_price, PurchaseOrderRequestLink.purchase_request_line_id)
        .outerjoin(PurchaseOrderRequestLink,
            PurchaseOrderRequestLink.purchase_order_line_id == PurchaseOrderLine.id)
        .where(PurchaseOrderLine.purchase_order_id == identifier)
        .order_by(PurchaseOrderLine.id)).mappings()]
    return {'supplier_id': source.supplier_id, 'reference': source.reference, 'lines': lines}


def goods_receipt_snapshot(db: Session, identifier: int) -> dict:
    source = document_source(db, 'PurchaseGoodsReceipt', identifier)
    order = db.get(PurchaseOrder, source.purchase_order_id)
    # 合格、拒收数量与原因均需审批，批准收货不等于批准自动生成的入库单。
    lines = [dict(row) for row in db.execute(select(
        PurchaseGoodsReceiptLine.id, PurchaseGoodsReceiptLine.purchase_order_line_id,
        PurchaseOrderLine.material_id, PurchaseGoodsReceiptLine.accepted_quantity,
        PurchaseGoodsReceiptLine.rejected_quantity, PurchaseGoodsReceiptLine.rejection_reason)
        .join(PurchaseOrderLine, PurchaseOrderLine.id == PurchaseGoodsReceiptLine.purchase_order_line_id)
        .where(PurchaseGoodsReceiptLine.goods_receipt_id == identifier)
        .order_by(PurchaseGoodsReceiptLine.id)).mappings()]
    return {'purchase_order_id': source.purchase_order_id,
            'supplier_id': order.supplier_id, 'warehouse_id': source.warehouse_id,
            'reference': source.reference, 'lines': lines}


def receipt_snapshot(db: Session, identifier: int) -> dict:
    source = document_source(db, 'Receipt', identifier)
    warehouse_id = db.scalar(select(ReceiptWarehouse.warehouse_id).where(
        ReceiptWarehouse.receipt_id == identifier))
    if warehouse_id is None:
        raise HTTPException(409, '采购入库单缺少仓库，无法审批')
    # 固定来源关联，不能将已批准入库单换到另一订单或另一供应商。
    lines = [dict(row) for row in db.execute(select(
        ReceiptLine.id, ReceiptLine.material_id, ReceiptLine.quantity,
        ReceiptOrderLink.purchase_order_line_id, PurchaseOrderLine.purchase_order_id)
        .outerjoin(ReceiptOrderLink, ReceiptOrderLink.receipt_line_id == ReceiptLine.id)
        .outerjoin(PurchaseOrderLine, PurchaseOrderLine.id == ReceiptOrderLink.purchase_order_line_id)
        .where(ReceiptLine.receipt_id == identifier).order_by(ReceiptLine.id)).mappings()]
    return {'supplier_id': source.supplier_id, 'warehouse_id': warehouse_id,
            'reference': source.reference, 'lines': lines,
            'goods_receipt_id': db.scalar(select(PurchaseGoodsReceipt.id).where(
                PurchaseGoodsReceipt.inbound_receipt_id == identifier))}


def purchase_return_snapshot(db: Session, identifier: int) -> dict:
    source = document_source(db, 'PurchaseReturn', identifier)
    receipt = db.get(Receipt, source.receipt_id)
    # 退货批准固定原入库、供应商、仓库和逐行数量，不包含动态可退余额。
    return {'receipt_id': source.receipt_id, 'supplier_id': receipt.supplier_id,
            'warehouse_id': db.scalar(select(ReceiptWarehouse.warehouse_id).where(
                ReceiptWarehouse.receipt_id == source.receipt_id)),
            'reason': source.reason,
            'lines': [dict(row) for row in db.execute(select(
                PurchaseReturnLine.id, PurchaseReturnLine.receipt_line_id,
                ReceiptLine.material_id, ReceiptLine.receipt_id.label('source_receipt_id'),
                PurchaseReturnLine.quantity, ReceiptOrderLink.purchase_order_line_id,
                PurchaseOrderLine.purchase_order_id, PurchaseOrderLine.unit_price)
                .join(ReceiptLine, ReceiptLine.id == PurchaseReturnLine.receipt_line_id)
                .outerjoin(ReceiptOrderLink, ReceiptOrderLink.receipt_line_id == ReceiptLine.id)
                .outerjoin(PurchaseOrderLine, PurchaseOrderLine.id == ReceiptOrderLink.purchase_order_line_id)
                .where(PurchaseReturnLine.purchase_return_id == identifier)
                .order_by(PurchaseReturnLine.id)).mappings()]}


def outbound_snapshot(db: Session, identifier: int) -> dict:
    source = document_source(db, 'WarehouseOutbound', identifier)
    jobs = list(db.scalars(select(MaintenanceJob).where(MaintenanceJob.parts_outbound_id == identifier)
                          .order_by(MaintenanceJob.id)))
    cases = list(db.scalars(select(AfterSalesCase).where(AfterSalesCase.parts_outbound_id == identifier)
                           .order_by(AfterSalesCase.id)))
    # 旧服务派生的待执行草稿可能没有新作者表记录，须从原方案编制审计恢复排除范围。
    authors = {row.created_by for row in [*jobs, *cases]}
    authors.update(row.submitted_by for row in cases if row.submitted_by is not None)
    authors.update(db.scalars(select(MaintenanceChange.changed_by).where(
        MaintenanceChange.entity_type == 'job', MaintenanceChange.entity_id.in_([row.id for row in jobs]),
        MaintenanceChange.action.in_(('create', 'edit', 'submit')))))
    authors.update(db.scalars(select(AfterSalesChange.changed_by).where(
        AfterSalesChange.case_id.in_([row.id for row in cases]),
        AfterSalesChange.action.in_(('create', 'edit', 'submit')))))
    # 仓库查看权限不扩大为采购金额权限，固定来源 ID 及出库正文即可。
    return {'warehouse_id': source.warehouse_id, 'source_kind': source.source_kind,
            'purchase_return_id': source.purchase_return_id, 'reason': source.reason,
            'note': source.note, 'reference': source.reference,
            'maintenance_job_ids': [row.id for row in jobs],
            'after_sales_case_ids': [row.id for row in cases], 'source_author_ids': sorted(authors),
            'lines': [{'id': line.id, 'material_id': line.material_id, 'quantity': line.quantity}
                      for line in db.scalars(select(WarehouseOutboundLine).where(
                          WarehouseOutboundLine.outbound_id == identifier).order_by(WarehouseOutboundLine.id))]}


def transfer_snapshot(db: Session, identifier: int) -> dict:
    source = document_source(db, 'Transfer', identifier)
    # 双仓及逐行数量一起固定，执行仍须重新核对来源库存。
    return {'from_warehouse_id': source.from_warehouse_id, 'to_warehouse_id': source.to_warehouse_id,
            'reference': source.reference,
            'lines': [dict(row) for row in db.execute(select(
                TransferLine.id, TransferLine.material_id, TransferLine.quantity)
                .where(TransferLine.transfer_id == identifier).order_by(TransferLine.id)).mappings()]}


def stocktake_snapshot(db: Session, identifier: int) -> dict:
    source = document_source(db, 'Stocktake', identifier)
    # 原账面量和流水检查点属于盘点依据；批准不能覆盖盘点期间的新库存流水。
    return {'warehouse_id': source.warehouse_id, 'reference': source.reference,
            'lines': [dict(row) for row in db.execute(select(
                StocktakeLine.id, StocktakeLine.material_id, StocktakeLine.book_quantity,
                StocktakeLine.counted_quantity, StocktakeLine.movement_id)
                .where(StocktakeLine.stocktake_id == identifier).order_by(StocktakeLine.id)).mappings()]}


def adjustment_snapshot(db: Session, identifier: int) -> dict:
    source = document_source(db, 'StockAdjustment', identifier)
    return {'warehouse_id': source.warehouse_id, 'reference': source.reference, 'reason': source.reason,
            'lines': [dict(row) for row in db.execute(select(
                StockAdjustmentLine.id, StockAdjustmentLine.material_id, StockAdjustmentLine.quantity)
                .where(StockAdjustmentLine.adjustment_id == identifier).order_by(StockAdjustmentLine.id)).mappings()]}


def native_review_evidence(db: Session, document_type: str, identifier: int) -> dict | None:
    # 首次接入前保存原流程信息，独立于新审批正文，不能冒充新模板中的批准。
    if document_type != 'StockAdjustment':
        return None
    source = db.get(StockAdjustment, identifier)
    if source.submitted_by is None and source.reviewed_by is None:
        return None
    return {field: getattr(source, field) for field in (
        'status', 'submitted_by', 'submitted_at', 'reviewed_by', 'reviewed_at', 'review_reason')}


def sync_native_review(db: Session, document_type: str, identifier: int, action: str,
                       state: dict, user_id: int, reason: str) -> None:
    if document_type != 'StockAdjustment':
        return
    source = db.get(StockAdjustment, identifier)
    # 原单据状态投影统一审批结果，中间步骤仍为 submitted；撤回恢复草稿。
    source.status = 'draft' if action == 'withdraw' else state['status']
    if action == 'submit':
        source.submitted_by, source.submitted_at = state['submitted_by'], state['submitted_at']
        source.reviewed_by, source.reviewed_at, source.review_reason = None, None, ''
    elif action in ('approve', 'reject'):
        from app.core.document_approval import now
        source.reviewed_by, source.reviewed_at, source.review_reason = user_id, now(db), reason.strip()
    db.flush()


# 仅登记已在原领域执行事务中接入校验的类型，避免生成无法保障执行边界的批准记录。
_SNAPSHOTS = {'WarehouseInbound': inbound_snapshot, 'PurchaseOrder': purchase_order_snapshot,
              'PurchaseGoodsReceipt': goods_receipt_snapshot, 'Receipt': receipt_snapshot,
              'PurchaseReturn': purchase_return_snapshot, 'WarehouseOutbound': outbound_snapshot,
              'Transfer': transfer_snapshot, 'Stocktake': stocktake_snapshot, 'StockAdjustment': adjustment_snapshot}
_REVERSE = {'Transfer': (TransferReversal, 'transfer_id', 'transfer.reverse'),
            'Stocktake': (StocktakeReversal, 'stocktake_id', 'stocktake.reverse'),
            'StockAdjustment': (StockAdjustmentReversal, 'adjustment_id', 'adjustment.reverse'),
            'WarehouseInbound': (WarehouseInboundReversal, 'inbound_id', 'other_inbound.reverse'),
            'Receipt': (ReceiptReversal, 'receipt_id', 'receipt.reverse'),
            'PurchaseReturn': (PurchaseReturnReversal, 'purchase_return_id', 'purchase_return.reverse'),
            'WarehouseOutbound': (WarehouseOutboundReversal, 'outbound_id', 'other_outbound.reverse')}


def document_source(db: Session, document_type: str, identifier: int):
    if document_type not in _SNAPSHOTS:
        raise HTTPException(409, '此类单据的统一审批入口尚未接入')
    source = db.get(approval_type(document_type).model, identifier)
    if source is None:
        raise HTTPException(404, '单据不存在')
    return source


def current_snapshot(db: Session, document_type: str, identifier: int) -> dict:
    document_source(db, document_type, identifier)
    return _SNAPSHOTS[document_type](db, identifier)


def document_pending(db: Session, document_type: str, identifier: int, intent: str):
    source = document_source(db, document_type, identifier)
    if document_type == 'WarehouseOutbound' and (source.source_kind not in ('other', 'purchase_return')
            or source.source_kind == 'purchase_return' and source.purchase_return_id is None):
        raise HTTPException(409, '出库单缺少有效业务来源，不能审批')
    if intent == 'reverse':
        if document_type == 'WarehouseOutbound' and source.source_kind != 'other':
            raise HTTPException(422, '采购退货出库请从原退货单另行申请冲销')
        reversal = _REVERSE.get(document_type)
        if reversal is None:
            raise HTTPException(422, '此类单据不支持独立冲销审批')
        model, field, _ = reversal
        if source.status != 'posted' or db.scalar(select(model.id).where(getattr(model, field) == identifier)):
            raise HTTPException(409, '此冲销动作已处理，不能继续审批')
    elif source.status not in (('draft', 'submitted', 'approved', 'rejected')
                               if document_type == 'StockAdjustment' else ('draft',)):
        # 历史已执行记录不补造审批；只限制仍待执行的草稿。
        raise HTTPException(409, '此单据已处理，不能继续审批')
    elif document_type == 'PurchaseReturn' and db.scalar(select(DocumentApprovalCase.id).where(
            DocumentApprovalCase.document_type == document_type,
            DocumentApprovalCase.document_id == identifier, DocumentApprovalCase.intent == 'execute',
            DocumentApprovalCase.status == 'executed')):
        # 退货转出库是本单执行点；后续待出库不允许再次撤回或生成另一张出库单。
        raise HTTPException(409, '退货已转出库，请在仓库出库单继续独立审批')
    return source


def document_snapshot(db: Session, document_type: str, identifier: int, intent: str,
                      reason: str = '') -> dict:
    document_pending(db, document_type, identifier, intent)
    content = current_snapshot(db, document_type, identifier)
    if intent == 'reverse':
        if not reason.strip() or len(reason.strip()) > 200:
            raise HTTPException(422, '冲销原因必填，最多二百字')
        return {'document': content, 'reversal_reason': reason.strip()}
    return content


def submit_permission(document_type: str, intent: str) -> str | None:
    # 冲销送审/撤回沿用冲销权限，不能因为有建单权限而获得冲销权限。
    if intent == 'reverse' and document_type in _REVERSE:
        return _REVERSE[document_type][2]
    return None


def document_summary(db: Session, document_type: str, content: dict) -> list[dict]:
    # 只读取固定正文和当前资料名称，不调用包含金额、客户或动态库存的其他领域详情。
    summary = []
    for field, model, label in [('supplier_id', Supplier, '供应商'), ('warehouse_id', Warehouse, '仓库'),
                                ('from_warehouse_id', Warehouse, '来源仓库'), ('to_warehouse_id', Warehouse, '目标仓库')]:
        if field in content:
            item = db.get(model, content[field])
            summary.append({'label': label, 'value': item.name if item else str(content[field])})
    if 'purchase_order_id' in content:
        order = db.get(PurchaseOrder, content['purchase_order_id'])
        summary.append({'label': '采购订单', 'value': order.document_no or f'#{order.id}'})
    if document_type == 'Receipt':
        # 来源单号只用于识别；来源订单 ID 本身已经固定在逐行正文中。
        for order_id in sorted({line['purchase_order_id'] for line in content['lines']
                                if line['purchase_order_id'] is not None}):
            order = db.get(PurchaseOrder, order_id)
            summary.append({'label': '采购订单', 'value': order.document_no or f'#{order.id}'})
        if content['goods_receipt_id'] is not None:
            source = db.get(PurchaseGoodsReceipt, content['goods_receipt_id'])
            summary.append({'label': '采购收货', 'value': source.document_no or f'#{source.id}'})
    if document_type == 'WarehouseInbound':
        summary.extend([{'label': '用途', 'value': {'opening': '期初补录', 'gift': '赠品', 'other': '其他'}[content['reason']]},
                        {'label': '入库说明', 'value': content['note']}])
    if document_type == 'PurchaseReturn':
        receipt = db.get(Receipt, content['receipt_id'])
        summary.extend([{'label': '原入库单', 'value': receipt.document_no or f'#{receipt.id}'},
                        {'label': '退货原因', 'value': content['reason']}])
    if document_type == 'WarehouseOutbound':
        summary.extend([{'label': '出库用途', 'value': {
            'scrap': '报废', 'sample': '样品', 'other': '其他', 'purchase_return': '采购退货'}[content['reason']]},
                        {'label': '出库说明', 'value': content['note']}])
        if content['purchase_return_id'] is not None:
            source = db.get(PurchaseReturn, content['purchase_return_id'])
            summary.append({'label': '采购退货单', 'value': source.document_no or f'#{source.id}'})
    if document_type == 'StockAdjustment':
        summary.append({'label': '调整原因', 'value': content['reason']})
    if 'reference' in content:
        summary.append({'label': '参考号', 'value': content['reference'] or '—'})
    for line in content['lines']:
        material = db.get(Material, line['material_id'])
        unit = f' {material.unit}' if material else ''
        value = (f"合格 {line['accepted_quantity']}{unit}；拒收 {line['rejected_quantity']}{unit}；原因 {line['rejection_reason'] or '—'}"
                 if document_type == 'PurchaseGoodsReceipt' else (f"账面 {line['book_quantity']}{unit}；实盘 {line['counted_quantity']}{unit}；差异 {Decimal(line['counted_quantity']) - Decimal(line['book_quantity'])}{unit}"
                       if document_type == 'Stocktake' else line['quantity'] + unit))
        if 'unit_price' in line:
            value += f"；单价 ¥{line['unit_price']}" if line['unit_price'] is not None else '；原价待核对'
        summary.append({'label': f'{material.sku} · {material.name}' if material else str(line['material_id']),
                        'value': value})
    return summary
