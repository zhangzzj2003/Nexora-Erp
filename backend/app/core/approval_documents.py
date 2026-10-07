"""审批领域适配器；明细快照和可执行状态必须由服务端业务模型生成。"""

from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import (
    DocumentApprovalCase, DocumentApprovalAuthor, Material, PaymentRecord, PurchaseGoodsReceipt, PurchaseGoodsReceiptLine, PurchaseOrder, PurchaseOrderLine,
    PurchaseOrderRequestLink, Receipt, ReceiptLine, ReceiptOrderLink, ReceiptReversal,
    ReceiptWarehouse, Supplier, Warehouse, WarehouseInbound, WarehouseInboundLine,
    WarehouseInboundReversal, PurchaseReturn, PurchaseReturnLine, PurchaseReturnReversal,
    WarehouseOutbound, WarehouseOutboundLine, WarehouseOutboundReversal, MaintenanceJob, MaintenanceChange, EquipmentAttachment, EquipmentAttachmentReversal, User,
    AfterSalesCase, AfterSalesChange, AfterSalesAttachment, AfterSalesAttachmentReversal, Transfer, TransferLine, TransferReversal,
    Stocktake, StocktakeLine, StocktakeReversal, StockAdjustment, StockAdjustmentLine, StockAdjustmentReversal,
    CrmQuoteLine, CrmQuoteAttachment, CrmQuoteAttachmentReversal,
    SalesOrder, SalesOrderLine, Shipment, ShipmentLine, ShipmentReversal, SalesReturn, SalesReturnLine,
    SalesReturnReversal, Customer, CrmQuote, CrmChange, SalesOrderContractRevision,
    SalesOrderContractAttachment, SalesOrderContractAttachmentReversal,
    PurchaseRequest, PurchaseRequestLine, MaintenancePurchaseRequest,
    Bom, WorkOrder, WorkOrderLine, MaterialIssue, MaterialIssueLine, MaterialIssueReversal,
    MaterialReturn, MaterialReturnLine, MaterialReturnReversal, ProductionCompletion, ProductionCompletionReversal,
    QualityDisposition, QualityDispositionChange, MrpPlan, MrpPlanChange, MrpConversion,
    Journal, JournalChange, JournalAttachment, JournalAttachmentReversal, OpeningBalance, OpeningBalanceChange, SubledgerOpening, SubledgerOpeningChange,
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


def purchase_request_snapshot(db: Session, identifier: int) -> dict:
    source = document_source(db, 'PurchaseRequest', identifier)
    conversions = list(db.scalars(select(MrpConversion).where(
        MrpConversion.purchase_request_id == identifier).order_by(MrpConversion.id)))
    plans = list(db.scalars(select(MrpPlan).where(MrpPlan.id.in_([row.plan_id for row in conversions]))
                           .order_by(MrpPlan.id)))
    links = list(db.scalars(select(MaintenancePurchaseRequest).where(
        MaintenancePurchaseRequest.purchase_request_id == identifier).order_by(MaintenancePurchaseRequest.id)))
    jobs = list(db.scalars(select(MaintenanceJob).where(MaintenanceJob.id.in_([row.job_id for row in links]))
                          .order_by(MaintenanceJob.id)))
    # 原计划作者、维护方案作者及本单转换人都参与编制，不能通过自动建单后自审。
    authors = {row.created_by for row in [*conversions, *plans, *links, *jobs]}
    authors.update(row.submitted_by for row in plans if row.submitted_by is not None)
    authors.update(db.scalars(select(MrpPlanChange.changed_by).where(
        MrpPlanChange.plan_id.in_([row.id for row in plans]),
        MrpPlanChange.action.in_(('create', 'edit', 'submit')))))
    authors.update(db.scalars(select(MaintenanceChange.changed_by).where(
        MaintenanceChange.entity_type == 'job', MaintenanceChange.entity_id.in_([row.id for row in jobs]),
        MaintenanceChange.action.in_(('create', 'edit', 'submit')))))
    for job in jobs:
        authors.update(maintenance_snapshot(db, job.id)['source_author_ids'])
    # 转单进度不属于需求正文；其他建议的转换人员也不改变本单的批准摘要。
    return {'reference': source.reference, 'note': source.note, 'source_author_ids': sorted(authors),
            'mrp_conversion_ids': [row.id for row in conversions], 'maintenance_job_ids': [row.id for row in jobs],
            'lines': [dict(row) for row in db.execute(select(
                PurchaseRequestLine.id, PurchaseRequestLine.material_id, PurchaseRequestLine.quantity)
                .where(PurchaseRequestLine.purchase_request_id == identifier).order_by(PurchaseRequestLine.id)).mappings()]}


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
    # 采购订单批准不能由申请编制人完成；原申请的编制范围沿来源关系恢复。
    requests = list(db.scalars(select(PurchaseRequest).join(PurchaseRequestLine,
        PurchaseRequestLine.purchase_request_id == PurchaseRequest.id)
        .where(PurchaseRequestLine.id.in_([line['purchase_request_line_id'] for line in lines
                                          if line['purchase_request_line_id'] is not None])).distinct()))
    authors = {row.created_by for row in requests}
    authors.update(row.submitted_by for row in requests if row.submitted_by is not None)
    from app.core.models import DocumentApprovalAuthor
    authors.update(db.scalars(select(DocumentApprovalAuthor.user_id).where(
        DocumentApprovalAuthor.document_type == 'PurchaseRequest',
        DocumentApprovalAuthor.document_id.in_([row.id for row in requests]))))
    for request in requests:
        authors.update(purchase_request_snapshot(db, request.id)['source_author_ids'])
    return {'supplier_id': source.supplier_id, 'reference': source.reference,
            'source_author_ids': sorted(authors), 'lines': lines}


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
    for job in jobs:
        authors.update(maintenance_snapshot(db, job.id)['source_author_ids'])
    for case in cases:
        authors.update(after_sales_snapshot(db, case.id)['source_author_ids'])
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


def after_sales_snapshot(db: Session, identifier: int) -> dict:
    import json
    from app.core.models import DocumentApprovalAuthor
    source = document_source(db, 'AfterSalesCase', identifier)
    executed = db.scalar(select(DocumentApprovalCase).where(
        DocumentApprovalCase.document_type == 'AfterSalesCase',
        DocumentApprovalCase.document_id == identifier, DocumentApprovalCase.intent == 'execute',
        DocumentApprovalCase.status == 'executed'))
    fixed = json.loads(executed.snapshot_json) if executed else None
    attachments = list(db.scalars(select(AfterSalesAttachment).where(
        AfterSalesAttachment.case_id == identifier).order_by(AfterSalesAttachment.id)))
    # 已执行方案只保留原审批附件；后续维修照片属于作业证据，不改写方案批准依据。
    if fixed is not None:
        ids = {row['id'] for row in fixed['attachments']}
        attachments = [row for row in attachments if row.id in ids]
    reversals = list(db.scalars(select(AfterSalesAttachmentReversal).where(
        AfterSalesAttachmentReversal.attachment_id.in_([row.id for row in attachments]))))
    authors = {source.created_by}
    authors.update(db.scalars(select(AfterSalesChange.changed_by).where(
        AfterSalesChange.case_id == identifier, AfterSalesChange.action.in_(('create', 'edit', 'submit')))))
    authors.update(row.created_by for row in [*attachments, *reversals])
    authors.update(db.scalars(select(DocumentApprovalAuthor.user_id).where(
        DocumentApprovalAuthor.document_type == 'AfterSalesCase', DocumentApprovalAuthor.document_id == identifier)))
    return {**{field: getattr(source, field) for field in (
        'shipment_line_id', 'reference', 'kind', 'quantity', 'complaint', 'solution', 'charge_mode',
        'fee_amount', 'customer_acceptance', 'warranty_days', 'warranty_basis', 'warehouse_id',
        'replacement_material_id', 'replacement_quantity', 'replacement_unit_price', 'source_json', 'parts_json')},
        'source_author_ids': fixed['source_author_ids'] if fixed is not None else sorted(authors),
        'attachments': [{'id': row.id, 'file_name': row.file_name, 'sha256': row.sha256,
            'reversal_id': next((item.id for item in reversals if item.attachment_id == row.id), None)}
            for row in attachments]}


def quote_snapshot(db: Session, identifier: int) -> dict:
    source = document_source(db, 'CrmQuote', identifier)
    attachments = list(db.scalars(select(CrmQuoteAttachment).where(
        CrmQuoteAttachment.quote_id == identifier).order_by(CrmQuoteAttachment.id)))
    reversals = list(db.scalars(select(CrmQuoteAttachmentReversal).where(
        CrmQuoteAttachmentReversal.attachment_id.in_([row.id for row in attachments]))
        .order_by(CrmQuoteAttachmentReversal.id)))
    # 附件编制人员与历次正文编制人员都排除；旧库没有作者表也沿原审计恢复。
    authors = set(db.scalars(select(CrmChange.changed_by).where(
        CrmChange.entity_kind == 'quote', CrmChange.entity_id == identifier,
        CrmChange.action.in_(('create', 'edit', 'submit')))))
    authors.update(row.created_by for row in [*attachments, *reversals])
    from app.core.models import DocumentApprovalAuthor
    authors.update(db.scalars(select(DocumentApprovalAuthor.user_id).where(
        DocumentApprovalAuthor.document_type == 'CrmQuote', DocumentApprovalAuthor.document_id == identifier)))
    return {**{field: getattr(source, field) for field in (
                'opportunity_id', 'customer_id', 'contact_id', 'reference', 'valid_until', 'terms', 'party_json')},
            'source_author_ids': sorted(authors),
            'attachments': [{'id': row.id, 'file_name': row.file_name, 'sha256': row.sha256,
                'reversal_id': next((item.id for item in reversals if item.attachment_id == row.id), None)}
                for row in attachments],
            'lines': [dict(row) for row in db.execute(select(
                CrmQuoteLine.id, CrmQuoteLine.position, CrmQuoteLine.material_id, CrmQuoteLine.sku,
                CrmQuoteLine.material_name, CrmQuoteLine.unit, CrmQuoteLine.quantity, CrmQuoteLine.unit_price)
                .where(CrmQuoteLine.quote_id == identifier).order_by(CrmQuoteLine.position)).mappings()]}


def sales_source_authors(db: Session, order_id: int) -> list[int]:
    # 新旧派生草稿都从原审计恢复编制人员，转换人或原方案作者不能审核下游。
    quotes = list(db.scalars(select(CrmQuote).where(CrmQuote.sales_order_id == order_id)))
    cases = list(db.scalars(select(AfterSalesCase).where(AfterSalesCase.replacement_order_id == order_id)))
    authors = {row.created_by for row in [*quotes, *cases]}
    authors.update(row.submitted_by for row in [*quotes, *cases] if row.submitted_by is not None)
    authors.update(db.scalars(select(CrmChange.changed_by).where(
        CrmChange.entity_kind == 'quote', CrmChange.entity_id.in_([row.id for row in quotes]),
        CrmChange.action.in_(('create', 'edit', 'submit', 'convert')))))
    authors.update(db.scalars(select(AfterSalesChange.changed_by).where(
        AfterSalesChange.case_id.in_([row.id for row in cases]),
        AfterSalesChange.action.in_(('create', 'edit', 'submit', 'process')))))
    for quote in quotes:
        authors.update(quote_snapshot(db, quote.id)['source_author_ids'])
    for case in cases:
        authors.update(after_sales_snapshot(db, case.id)['source_author_ids'])
    return sorted(authors)


def sales_order_snapshot(db: Session, identifier: int) -> dict:
    source = document_source(db, 'SalesOrder', identifier)
    revisions = list(db.scalars(select(SalesOrderContractRevision).where(
        SalesOrderContractRevision.sales_order_id == identifier).order_by(SalesOrderContractRevision.version)))
    attachments = list(db.scalars(select(SalesOrderContractAttachment).where(
        SalesOrderContractAttachment.revision_id.in_([row.id for row in revisions]))
        .order_by(SalesOrderContractAttachment.id)))
    reversals = list(db.scalars(select(SalesOrderContractAttachmentReversal).where(
        SalesOrderContractAttachmentReversal.attachment_id.in_([row.id for row in attachments]))
        .order_by(SalesOrderContractAttachmentReversal.id)))
    authors = set(sales_source_authors(db, identifier))
    authors.update(row.created_by for row in [*revisions, *attachments, *reversals])
    # 合同正文和附件指纹一起固定，审批期间不得追加或撤销依据后直接确认。
    return {'customer_id': source.customer_id, 'reference': source.reference,
            'source_author_ids': sorted(authors),
            'contract': [{field: getattr(row, field) for field in (
                'id', 'version', 'body', 'acceptance_reference', 'reason')} for row in revisions],
            'contract_attachments': [{'id': row.id, 'revision_id': row.revision_id, 'sha256': row.sha256,
                'reversal_id': next((part.id for part in reversals if part.attachment_id == row.id), None)}
                for row in attachments],
            'lines': [dict(row) for row in db.execute(select(
                SalesOrderLine.id, SalesOrderLine.material_id, SalesOrderLine.quantity,
                SalesOrderLine.unit_price, SalesOrderLine.warranty_days, SalesOrderLine.warranty_basis)
                .where(SalesOrderLine.sales_order_id == identifier).order_by(SalesOrderLine.id)).mappings()]}


def shipment_snapshot(db: Session, identifier: int) -> dict:
    source = document_source(db, 'Shipment', identifier)
    order = db.get(SalesOrder, source.sales_order_id)
    # 出库审批只固定客户、来源和数量，不扩大为订单金额查看权限。
    return {'sales_order_id': source.sales_order_id, 'customer_id': order.customer_id,
            'warehouse_id': source.warehouse_id, 'reference': source.reference,
            'lines': [dict(row) for row in db.execute(select(
                ShipmentLine.id, ShipmentLine.sales_order_line_id, SalesOrderLine.material_id,
                ShipmentLine.quantity).join(SalesOrderLine, SalesOrderLine.id == ShipmentLine.sales_order_line_id)
                .where(ShipmentLine.shipment_id == identifier).order_by(ShipmentLine.id)).mappings()]}


def sales_return_snapshot(db: Session, identifier: int) -> dict:
    source = document_source(db, 'SalesReturn', identifier)
    shipment = db.get(Shipment, source.shipment_id)
    order = db.get(SalesOrder, shipment.sales_order_id)
    cases = list(db.scalars(select(AfterSalesCase).where(AfterSalesCase.sales_return_id == identifier)))
    authors = {row.created_by for row in cases}
    authors.update(row.submitted_by for row in cases if row.submitted_by is not None)
    authors.update(db.scalars(select(AfterSalesChange.changed_by).where(
        AfterSalesChange.case_id.in_([row.id for row in cases]),
        AfterSalesChange.action.in_(('create', 'edit', 'submit', 'process')))))
    for case in cases:
        authors.update(after_sales_snapshot(db, case.id)['source_author_ids'])
    return {'shipment_id': source.shipment_id, 'sales_order_id': order.id,
            'customer_id': order.customer_id, 'warehouse_id': source.warehouse_id,
            'reason': source.reason, 'source_author_ids': sorted(authors),
            'lines': [dict(row) for row in db.execute(select(
                SalesReturnLine.id, SalesReturnLine.shipment_line_id, ShipmentLine.sales_order_line_id,
                SalesOrderLine.material_id, SalesReturnLine.quantity)
                .join(ShipmentLine, ShipmentLine.id == SalesReturnLine.shipment_line_id)
                .join(SalesOrderLine, SalesOrderLine.id == ShipmentLine.sales_order_line_id)
                .where(SalesReturnLine.sales_return_id == identifier).order_by(SalesReturnLine.id)).mappings()]}


def maintenance_snapshot(db: Session, identifier: int) -> dict:
    import json
    source = document_source(db, 'MaintenanceJob', identifier)
    executed = db.scalar(select(DocumentApprovalCase).where(
        DocumentApprovalCase.document_type == 'MaintenanceJob',
        DocumentApprovalCase.document_id == identifier, DocumentApprovalCase.intent == 'execute',
        DocumentApprovalCase.status == 'executed'))
    fixed = json.loads(executed.snapshot_json) if executed else None
    attachments = list(db.scalars(select(EquipmentAttachment).where(
        EquipmentAttachment.job_id == identifier).order_by(EquipmentAttachment.id)))
    # 作业阶段可追加照片，但原批准方案的附件与作者范围保持固定。
    if fixed is not None:
        ids = {item['id'] for item in fixed['attachments']}
        attachments = [item for item in attachments if item.id in ids]
    reversals = list(db.scalars(select(EquipmentAttachmentReversal).where(
        EquipmentAttachmentReversal.attachment_id.in_([item.id for item in attachments]))))
    authors = {source.created_by, *[item.created_by for item in [*attachments, *reversals]]}
    authors.update(db.scalars(select(MaintenanceChange.changed_by).where(
        MaintenanceChange.entity_type == 'job', MaintenanceChange.entity_id == identifier,
        MaintenanceChange.action.in_(('create', 'edit', 'submit')))))
    authors.update(db.scalars(select(DocumentApprovalAuthor.user_id).where(
        DocumentApprovalAuthor.document_type == 'MaintenanceJob', DocumentApprovalAuthor.document_id == identifier)))
    return {field: getattr(source, field) for field in (
        'reference', 'equipment_id', 'kind', 'plan_id', 'plan_version', 'plan_due_date',
        'hour_plan_id', 'plan_due_hours', 'plan_meter_reading_id', 'work_order_id',
        'assigned_to', 'request_note', 'equipment_json', 'work_order_json', 'parts_json', 'warehouse_id')} | {
        'source_author_ids': fixed['source_author_ids'] if fixed is not None else sorted(authors),
        'attachments': [{'id': item.id, 'file_name': item.file_name, 'sha256': item.sha256,
            'reversal_id': next((part.id for part in reversals if part.attachment_id == item.id), None)}
            for item in attachments]}


def maintenance_execution_snapshot(db: Session, identifier: int) -> dict:
    source = document_source(db, 'MaintenanceJob', identifier)
    # 验收更正须核对实际结果、原计划推进与全量附件指纹，不能只批准最初的维护方案。
    return {field: getattr(source, field) for field in (
        'parts_outbound_id', 'solution', 'labor_hours', 'service_amount', 'reported_by', 'reported_at',
        'accepted_by', 'accepted_at', 'plan_roll_json')} | {
        'attachments': [{'id': item.id, 'sha256': item.sha256,
            'reversal_id': db.scalar(select(EquipmentAttachmentReversal.id).where(
                EquipmentAttachmentReversal.attachment_id == item.id))}
            for item in db.scalars(select(EquipmentAttachment).where(
                EquipmentAttachment.job_id == identifier).order_by(EquipmentAttachment.id))]}


def mrp_snapshot(db: Session, identifier: int) -> dict:
    source = document_source(db, 'MrpPlan', identifier)
    # 固定完整计划和全部计算依据；转单进度及其他建议的转换人不改变批准正文。
    authors = {source.created_by}
    authors.update(db.scalars(select(MrpPlanChange.changed_by).where(
        MrpPlanChange.plan_id == identifier, MrpPlanChange.action.in_(('create', 'submit')))))
    authors.update(db.scalars(select(DocumentApprovalAuthor.user_id).where(
        DocumentApprovalAuthor.document_type == 'MrpPlan', DocumentApprovalAuthor.document_id == identifier)))
    return {field: getattr(source, field) for field in ('reference', 'input_json', 'snapshot_json', 'fingerprint')} | {
        'source_author_ids': sorted(authors)}


def quality_snapshot(db: Session, identifier: int) -> dict:
    # 处置正文固定原质检与追加材料；成本分配是后续事实，不属于方案审批正文。
    source = document_source(db, 'QualityDisposition', identifier)
    executed = db.scalar(select(DocumentApprovalCase).where(
        DocumentApprovalCase.document_type == 'QualityDisposition',
        DocumentApprovalCase.document_id == identifier, DocumentApprovalCase.intent == 'execute',
        DocumentApprovalCase.status == 'executed'))
    authors = {source.created_by}
    authors.update(db.scalars(select(QualityDispositionChange.changed_by).where(
        QualityDispositionChange.disposition_id == identifier,
        QualityDispositionChange.action.in_(('create', 'edit', 'submit')))))
    authors.update(db.scalars(select(DocumentApprovalAuthor.user_id).where(
        DocumentApprovalAuthor.document_type == 'QualityDisposition',
        DocumentApprovalAuthor.document_id == identifier)))
    if executed:
        import json
        authors = set(json.loads(executed.snapshot_json)['source_author_ids'])
    return {**{field: getattr(source, field) for field in ('completion_id', 'reference', 'kind',
        'quantity', 'loss_treatment', 'defect', 'action_note', 'warehouse_id', 'materials_json', 'source_json')},
        'source_author_ids': sorted(authors)}


def work_order_snapshot(db: Session, identifier: int) -> dict:
    source = document_source(db, 'WorkOrder', identifier)
    bom = db.get(Bom, source.bom_id)
    conversions = list(db.scalars(select(MrpConversion).where(MrpConversion.work_order_id == identifier)
                                 .order_by(MrpConversion.id)))
    plans = list(db.scalars(select(MrpPlan).where(MrpPlan.id.in_([row.plan_id for row in conversions]))
                           .order_by(MrpPlan.id)))
    dispositions = list(db.scalars(select(QualityDisposition).where(QualityDisposition.rework_order_id == identifier)
                                  .order_by(QualityDisposition.id)))
    # 派生草稿恢复原编制审计；审批人不因批准上游而自动获得下游批准结果。
    authors = {row.created_by for row in [*plans, *dispositions, *conversions]}
    authors.update(row.submitted_by for row in [*plans, *dispositions] if row.submitted_by is not None)
    authors.update(db.scalars(select(MrpPlanChange.changed_by).where(
        MrpPlanChange.plan_id.in_([row.id for row in plans]),
        # 本工单的转换人来自上面的关联记录；同计划其他建议的转单不能改写本单批准正文。
        MrpPlanChange.action.in_(('create', 'edit', 'submit')))))
    authors.update(db.scalars(select(QualityDispositionChange.changed_by).where(
        QualityDispositionChange.disposition_id.in_([row.id for row in dispositions]),
        QualityDispositionChange.action.in_(('create', 'edit', 'submit', 'post')))))
    return {'bom_id': bom.id, 'bom_version': bom.version, 'bom_base_quantity': bom.base_quantity,
            'product_material_id': bom.product_material_id, 'warehouse_id': source.warehouse_id,
            'target_quantity': source.target_quantity, 'reference': source.reference, 'note': source.note,
            'source_author_ids': sorted(authors),
            'mrp_conversion_ids': [row.id for row in conversions],
            'rework_disposition_ids': [row.id for row in dispositions],
            'lines': [dict(row) for row in db.execute(select(WorkOrderLine.id,
                WorkOrderLine.component_material_id.label('material_id'),
                WorkOrderLine.required_quantity.label('quantity'))
                .where(WorkOrderLine.work_order_id == identifier).order_by(WorkOrderLine.id)).mappings()]}


def material_issue_snapshot(db: Session, identifier: int) -> dict:
    source = document_source(db, 'MaterialIssue', identifier)
    # 剩余需料和库存是执行时动态核对值，固定正文只包含本单的工单来源、仓库和数量。
    return {'work_order_id': source.work_order_id, 'warehouse_id': source.warehouse_id,
            'reference': source.reference,
            'lines': [dict(row) for row in db.execute(select(MaterialIssueLine.id,
                MaterialIssueLine.work_order_line_id, WorkOrderLine.component_material_id.label('material_id'),
                MaterialIssueLine.quantity).join(WorkOrderLine, WorkOrderLine.id == MaterialIssueLine.work_order_line_id)
                .where(MaterialIssueLine.material_issue_id == identifier).order_by(MaterialIssueLine.id)).mappings()]}


def material_return_snapshot(db: Session, identifier: int) -> dict:
    source = document_source(db, 'MaterialReturn', identifier)
    issue = db.get(MaterialIssue, source.material_issue_id)
    return {'material_issue_id': issue.id, 'work_order_id': issue.work_order_id,
            'warehouse_id': issue.warehouse_id, 'reason': source.reason,
            'lines': [dict(row) for row in db.execute(select(MaterialReturnLine.id,
                MaterialReturnLine.material_issue_line_id, MaterialIssueLine.work_order_line_id,
                WorkOrderLine.component_material_id.label('material_id'), MaterialReturnLine.quantity)
                .join(MaterialIssueLine, MaterialIssueLine.id == MaterialReturnLine.material_issue_line_id)
                .join(WorkOrderLine, WorkOrderLine.id == MaterialIssueLine.work_order_line_id)
                .where(MaterialReturnLine.material_return_id == identifier).order_by(MaterialReturnLine.id)).mappings()]}


def completion_snapshot(db: Session, identifier: int) -> dict:
    source = document_source(db, 'ProductionCompletion', identifier)
    order = db.get(WorkOrder, source.work_order_id)
    bom = db.get(Bom, order.bom_id)
    # 质检是独立业务前置，质检结果固定后才可送审；质检填写人属于本单编制人员。
    return {'work_order_id': order.id, 'warehouse_id': order.warehouse_id, 'bom_id': bom.id,
            'bom_version': bom.version, 'reported_quantity': source.reported_quantity,
            'accepted_quantity': source.accepted_quantity, 'rejected_quantity': source.rejected_quantity,
            'qc_note': source.qc_note, 'reference': source.reference,
            'source_author_ids': [source.inspected_by] if source.inspected_by is not None else [],
            'lines': [{'id': source.id, 'material_id': bom.product_material_id,
                       'quantity': source.reported_quantity}]}


def payment_snapshot(db: Session, identifier: int) -> dict:
    from app.finance.routes import party_data
    source = document_source(db, 'PaymentRecord', identifier)
    original = db.get(PaymentRecord, source.reverses_id) if source.reverses_id else None
    # 身份、金额与原资金执行事实固定；余额在审批及执行时重算，不固定易变化的余额。
    return {field: getattr(source, field) for field in ('kind', 'order_id', 'action', 'amount', 'reference', 'note', 'reverses_id')} | {
        'party_id': party_data(db, source.kind, source.order_id)['party_id'],
        'source_author_ids': sorted({source.created_by, *([original.created_by] if original else []),
            *([original.executed_by] if original and original.executed_by is not None else [])}),
        'original': None if original is None else {field: getattr(original, field) for field in
            ('id', 'document_no', 'kind', 'order_id', 'action', 'amount', 'reference', 'executed_at')}}


def subledger_snapshot(db: Session, identifier: int) -> dict:
    from app.finance.subledger_openings import snapshot
    import json
    source = document_source(db, 'SubledgerOpening', identifier)
    original = snapshot(db, source)
    basis = opening_snapshot(db, source.opening_balance_id)
    basis.pop('source_author_ids')
    authors = {source.created_by}
    authors.update(db.scalars(select(SubledgerOpeningChange.changed_by).where(
        SubledgerOpeningChange.opening_id == identifier,
        SubledgerOpeningChange.action.in_(('create', 'update', 'submit')))))
    authors.update(db.scalars(select(DocumentApprovalAuthor.user_id).where(
        DocumentApprovalAuthor.document_type == 'SubledgerOpening', DocumentApprovalAuthor.document_id == identifier)))
    executed = db.scalar(select(DocumentApprovalCase).where(
        DocumentApprovalCase.document_type == 'SubledgerOpening', DocumentApprovalCase.document_id == identifier,
        DocumentApprovalCase.intent == 'execute', DocumentApprovalCase.status == 'executed'))
    if executed:
        authors = set(json.loads(executed.snapshot_json)['source_author_ids'])
    # 完整五百行与总账依据全部参与摘要，确认结果与基础资料名称不覆盖批准正文。
    return {field: original[field] for field in ('reference', 'effective_date', 'opening_balance_id',
        'opening_version', 'control_accounts', 'note', 'currency')} | {
        'source_author_ids': sorted(authors), 'ledger_basis': basis,
        'lines': [{field: line[field] for field in ('id', 'kind', 'customer_id', 'supplier_id',
            'account_id', 'account_code', 'document_reference', 'document_date', 'debit', 'credit')} | {
            'auxiliary': [{'kind': item['kind'], 'id': item['id']} for item in line['auxiliary']]}
            for line in original['lines']]}


def opening_snapshot(db: Session, identifier: int) -> dict:
    from app.finance.opening_balances import snapshot
    import json
    source = document_source(db, 'OpeningBalance', identifier)
    original = snapshot(db, source)
    authors = {source.created_by}
    authors.update(db.scalars(select(OpeningBalanceChange.changed_by).where(
        OpeningBalanceChange.opening_balance_id == identifier,
        OpeningBalanceChange.action.in_(('create', 'update', 'submit')))))
    authors.update(db.scalars(select(DocumentApprovalAuthor.user_id).where(
        DocumentApprovalAuthor.document_type == 'OpeningBalance', DocumentApprovalAuthor.document_id == identifier)))
    executed = db.scalar(select(DocumentApprovalCase).where(
        DocumentApprovalCase.document_type == 'OpeningBalance', DocumentApprovalCase.document_id == identifier,
        DocumentApprovalCase.intent == 'execute', DocumentApprovalCase.status == 'executed'))
    if executed:
        # 撤销申请与确认人员不能改写原启用方案的作者快照。
        authors = set(json.loads(executed.snapshot_json)['source_author_ids'])
    return {field: original[field] for field in ('reference', 'effective_date', 'period_id', 'note', 'currency')} | {
        'source_author_ids': sorted(authors),
        'lines': [{field: line[field] for field in ('id', 'account_id', 'account_code', 'category',
            'normal_balance', 'summary', 'debit', 'credit')} | {
            'auxiliary': [{'kind': item['kind'], 'id': item['id']} for item in line['auxiliary']]}
            for line in original['lines']]}


def journal_snapshot(db: Session, identifier: int) -> dict:
    from app.finance.journals import snapshot
    import json
    source = document_source(db, 'Journal', identifier)
    original = snapshot(db, source)
    case = db.scalar(select(DocumentApprovalCase).where(
        DocumentApprovalCase.document_type == 'Journal', DocumentApprovalCase.document_id == identifier,
        DocumentApprovalCase.intent == 'execute', DocumentApprovalCase.status == 'executed'))
    authors = {source.created_by}
    authors.update(db.scalars(select(JournalChange.changed_by).where(
        JournalChange.journal_id == identifier, JournalChange.action.in_(('create', 'update', 'submit')))))
    attachments = list(db.scalars(select(JournalAttachment).where(
        JournalAttachment.journal_id == identifier).order_by(JournalAttachment.id)))
    authors.update(item.created_by for item in attachments)
    authors.update(db.scalars(select(JournalAttachmentReversal.created_by).where(
        JournalAttachmentReversal.attachment_id.in_([item.id for item in attachments]))))
    authors.update(db.scalars(select(DocumentApprovalAuthor.user_id).where(
        DocumentApprovalAuthor.document_type == 'Journal', DocumentApprovalAuthor.document_id == identifier)))
    if case:
        # 过账后可补录作业证据，但不能改写原审批附件和编制人员的固定范围。
        frozen = json.loads(case.snapshot_json)
        authors = set(frozen['source_author_ids'])
        attachments = [item for item in attachments if item.id in {row['id'] for row in frozen['attachments']}]
    return {field: original[field] for field in ('reference', 'journal_date', 'period_id', 'note',
        'currency', 'reversal_of_id', 'business_source', 'profit_transfer')} | {
        'source_author_ids': sorted(authors),
        # 基础资料更名不改变科目和辅助组合的身份；执行仍重核启用状态与辅助要求。
        'lines': [{field: line[field] for field in ('id', 'account_id', 'account_code', 'category',
            'normal_balance', 'summary', 'debit', 'credit')} | {
            'auxiliary': [{'kind': item['kind'], 'id': item['id']} for item in line['auxiliary']]}
            for line in original['lines']],
        'attachments': [{'id': item.id, 'file_name': item.file_name, 'sha256': item.sha256,
            'reversal_id': db.scalar(select(JournalAttachmentReversal.id).where(
                JournalAttachmentReversal.attachment_id == item.id))} for item in attachments]}


def native_review_evidence(db: Session, document_type: str, identifier: int) -> dict | None:
    # 首次接入前保存原流程信息，独立于新审批正文，不能冒充新模板中的批准。
    if document_type == 'MaintenanceJob':
        source = db.get(MaintenanceJob, identifier)
        submitted = db.scalar(select(MaintenanceChange).where(
            MaintenanceChange.entity_type == 'job', MaintenanceChange.entity_id == identifier,
            MaintenanceChange.action == 'submit').order_by(MaintenanceChange.id.desc()).limit(1))
        reviewed = db.scalar(select(MaintenanceChange).where(
            MaintenanceChange.entity_type == 'job', MaintenanceChange.entity_id == identifier,
            MaintenanceChange.action.in_(('approve', 'reject'))).order_by(MaintenanceChange.id.desc()).limit(1))
        if not submitted and not reviewed and not source.reviewed_by:
            return None
        return {'status': source.status, 'submitted_by': submitted.changed_by if submitted else None,
            'submitted_at': submitted.created_at if submitted else None, 'reviewed_by': source.reviewed_by,
            'reviewed_at': reviewed.created_at if reviewed else None,
            'review_reason': (reviewed.reason + '；现场依据：' + reviewed.evidence) if reviewed else ''}
    if document_type not in ('StockAdjustment', 'PurchaseRequest', 'CrmQuote', 'AfterSalesCase', 'QualityDisposition', 'MrpPlan', 'Journal', 'OpeningBalance', 'SubledgerOpening'):
        return None
    source = db.get(approval_type(document_type).model, identifier)
    if source.submitted_by is None and source.reviewed_by is None:
        return None
    result = {field: getattr(source, field) for field in (
        'status', 'submitted_by', 'submitted_at', 'reviewed_by', 'reviewed_at')}
    # 报价和售后意见保存在追加审计中，不存在主单 review_reason 字段。
    if document_type == 'SubledgerOpening':
        result['review_reason'] = db.scalar(select(SubledgerOpeningChange.reason).where(
            SubledgerOpeningChange.opening_id == identifier, SubledgerOpeningChange.action.in_(('approve', 'reject')))
            .order_by(SubledgerOpeningChange.id.desc()).limit(1)) or ''
    elif document_type == 'OpeningBalance':
        result['review_reason'] = db.scalar(select(OpeningBalanceChange.reason).where(
            OpeningBalanceChange.opening_balance_id == identifier, OpeningBalanceChange.action.in_(('approve', 'reject')))
            .order_by(OpeningBalanceChange.id.desc()).limit(1)) or ''
    elif document_type == 'Journal':
        result['review_reason'] = db.scalar(select(JournalChange.reason).where(
            JournalChange.journal_id == identifier, JournalChange.action.in_(('approve', 'reject')))
            .order_by(JournalChange.id.desc()).limit(1)) or ''
    elif document_type == 'CrmQuote':
        result['review_reason'] = db.scalar(select(CrmChange.reason).where(
            CrmChange.entity_kind == 'quote', CrmChange.entity_id == identifier,
            CrmChange.action.in_(('approve', 'reject'))).order_by(CrmChange.id.desc()).limit(1)) or ''
    elif document_type == 'AfterSalesCase':
        result['review_reason'] = db.scalar(select(AfterSalesChange.reason).where(
            AfterSalesChange.case_id == identifier, AfterSalesChange.action.in_(('approve', 'reject')))
            .order_by(AfterSalesChange.id.desc()).limit(1)) or ''
    elif document_type == 'QualityDisposition':
        result['review_reason'] = db.scalar(select(QualityDispositionChange.reason).where(
            QualityDispositionChange.disposition_id == identifier,
            QualityDispositionChange.action.in_(('approve', 'reject')))
            .order_by(QualityDispositionChange.id.desc()).limit(1)) or ''
    elif document_type == 'MrpPlan':
        result['review_reason'] = db.scalar(select(MrpPlanChange.reason).where(
            MrpPlanChange.plan_id == identifier, MrpPlanChange.action.in_(('approve', 'reject')))
            .order_by(MrpPlanChange.id.desc()).limit(1)) or ''
    else:
        result['review_reason'] = source.review_reason
    return result


def sync_native_review(db: Session, document_type: str, identifier: int, action: str,
                       state: dict, user_id: int, reason: str) -> None:
    if document_type not in ('StockAdjustment', 'PurchaseRequest'):
        return
    source = db.get(approval_type(document_type).model, identifier)
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
_SNAPSHOTS = {'PaymentRecord': payment_snapshot, 'SubledgerOpening': subledger_snapshot, 'OpeningBalance': opening_snapshot, 'Journal': journal_snapshot, 'MaintenanceJob': maintenance_snapshot, 'MrpPlan': mrp_snapshot, 'QualityDisposition': quality_snapshot, 'AfterSalesCase': after_sales_snapshot, 'CrmQuote': quote_snapshot, 'PurchaseRequest': purchase_request_snapshot, 'WarehouseInbound': inbound_snapshot, 'PurchaseOrder': purchase_order_snapshot,
              'PurchaseGoodsReceipt': goods_receipt_snapshot, 'Receipt': receipt_snapshot,
              'PurchaseReturn': purchase_return_snapshot, 'WarehouseOutbound': outbound_snapshot,
              'Transfer': transfer_snapshot, 'Stocktake': stocktake_snapshot, 'StockAdjustment': adjustment_snapshot,
              'SalesOrder': sales_order_snapshot, 'Shipment': shipment_snapshot, 'SalesReturn': sales_return_snapshot,
              'WorkOrder': work_order_snapshot, 'MaterialIssue': material_issue_snapshot,
              'MaterialReturn': material_return_snapshot, 'ProductionCompletion': completion_snapshot}
_REVERSE = {'MaterialIssue': (MaterialIssueReversal, 'material_issue_id', 'material_issue.reverse'),
            'MaterialReturn': (MaterialReturnReversal, 'material_return_id', 'material_return.reverse'),
            'ProductionCompletion': (ProductionCompletionReversal, 'production_completion_id', 'production_completion.reverse'),
            'Shipment': (ShipmentReversal, 'shipment_id', 'shipment.reverse'),
            'SalesReturn': (SalesReturnReversal, 'sales_return_id', 'sales_return.reverse'),
            'Transfer': (TransferReversal, 'transfer_id', 'transfer.reverse'),
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
        if document_type in ('OpeningBalance', 'SubledgerOpening'):
            if source.status != 'confirmed':
                raise HTTPException(409, '仅已确认期初可以另行申请撤销')
            return source
        if document_type == 'MaintenanceJob':
            if source.status != 'accepted':
                raise HTTPException(409, '仅已验收维护工单可以独立申请更正')
            return source
        if document_type == 'QualityDisposition':
            if source.status != 'posted':
                raise HTTPException(409, '仅已确认处置可以独立申请更正')
            return source
        if document_type == 'AfterSalesCase':
            if source.status != 'closed':
                raise HTTPException(409, '售后仅可对已结案单另行申请更正')
            return source
        if document_type == 'WarehouseOutbound' and source.source_kind != 'other':
            raise HTTPException(422, '采购退货出库请从原退货单另行申请冲销')
        reversal = _REVERSE.get(document_type)
        if reversal is None:
            raise HTTPException(422, '此类单据不支持独立冲销审批')
        model, field, _ = reversal
        if source.status != 'posted' or db.scalar(select(model.id).where(getattr(model, field) == identifier)):
            raise HTTPException(409, '此冲销动作已处理，不能继续审批')
    elif source.status not in (('draft', 'submitted', 'approved', 'rejected')
                               if document_type in ('StockAdjustment', 'PurchaseRequest', 'CrmQuote', 'AfterSalesCase', 'QualityDisposition', 'MrpPlan', 'MaintenanceJob', 'Journal', 'OpeningBalance', 'SubledgerOpening') else
                               ('inspected',) if document_type == 'ProductionCompletion' else ('draft',)):
        # 历史已执行记录不补造审批；只限制仍待执行的草稿。
        raise HTTPException(409, '此单据已处理，不能继续审批')
    elif document_type == 'PurchaseReturn' and db.scalar(select(DocumentApprovalCase.id).where(
            DocumentApprovalCase.document_type == document_type,
            DocumentApprovalCase.document_id == identifier, DocumentApprovalCase.intent == 'execute',
            DocumentApprovalCase.status == 'executed')):
        # 退货转出库是本单执行点；后续待出库不允许再次撤回或生成另一张出库单。
        raise HTTPException(409, '退货已转出库，请在仓库出库单继续独立审批')
    if intent == 'execute' and document_type == 'MaintenanceJob':
        from app.core.document_approval import find_case
        case = find_case(db, document_type, identifier)
        if case and case.status == 'executed':
            raise HTTPException(409, '维护方案已办理，不能再次送审或撤回')
    if intent == 'execute' and document_type == 'PurchaseRequest':
        from app.purchase.requests import ordered_quantity
        # 旧库已全部转完的申请只供查询；部分剩余需求可以重新取得独立批准，不改写旧订单。
        lines = list(db.scalars(select(PurchaseRequestLine).where(
            PurchaseRequestLine.purchase_request_id == identifier)))
        if not any(Decimal(line.quantity) > ordered_quantity(db, line.id) for line in lines):
            raise HTTPException(409, '申请已无待转数量，保留原转单记录')
    if intent == 'execute' and document_type == 'MrpPlan':
        import json
        converted = set(db.scalars(select(MrpConversion.suggestion_key).where(MrpConversion.plan_id == identifier)))
        suggestions = json.loads(source.snapshot_json)['suggestions']
        # 旧库全部转完的计划只供核对，不补造新批准；零建议计划仍可留存审核结论。
        if suggestions and all(row['key'] in converted for row in suggestions):
            raise HTTPException(409, '计划已无待转建议，保留原转单记录')
    return source


def document_snapshot(db: Session, document_type: str, identifier: int, intent: str,
                      reason: str = '', evidence: str = '') -> dict:
    document_pending(db, document_type, identifier, intent)
    content = current_snapshot(db, document_type, identifier)
    if intent == 'reverse':
        if not reason.strip() or len(reason.strip()) > 200:
            raise HTTPException(422, '冲销原因必填，最多二百字')
        result = {'document': content, 'reversal_reason': reason.strip()}
        if document_type in ('OpeningBalance', 'SubledgerOpening'):
            source = db.get(approval_type(document_type).model, identifier)
            result['confirmation'] = {'confirmed_by': source.confirmed_by, 'confirmed_at': source.confirmed_at}
        if document_type == 'MaintenanceJob':
            if not evidence.strip() or len(evidence.strip()) > 600:
                raise HTTPException(422, '验收更正现场依据必填，最多六百字')
            result.update(reversal_evidence=evidence.strip(), execution=maintenance_execution_snapshot(db, identifier))
        return result
    return content


def submit_permission(document_type: str, intent: str, source=None) -> str | None:
    # 反向资金草稿独立送审，建单权限不能代替冲销权限。
    if document_type == 'PaymentRecord' and source is not None and source.reverses_id is not None:
        return 'finance.reverse'
    # 冲销送审/撤回沿用冲销权限，不能因为有建单权限而获得冲销权限。
    if intent == 'reverse' and document_type == 'SubledgerOpening':
        return 'subledger_opening.reverse'
    if intent == 'reverse' and document_type == 'OpeningBalance':
        return 'opening_balance.reverse'
    if intent == 'reverse' and document_type == 'MaintenanceJob':
        return 'equipment.reverse'
    if intent == 'reverse' and document_type == 'QualityDisposition':
        return 'quality.reverse'
    if intent == 'reverse' and document_type == 'AfterSalesCase':
        return 'after_sales.reverse'
    if intent == 'reverse' and document_type in _REVERSE:
        return _REVERSE[document_type][2]
    return None


def document_summary(db: Session, document_type: str, content: dict) -> list[dict]:
    if document_type == 'PaymentRecord':
        return [{'label': label, 'value': str(content[field])} for label, field in (
            ('订单内部编号', 'order_id'), ('往来对象内部编号', 'party_id'),
            ('金额（元）', 'amount'), ('参考号', 'reference'), ('备注', 'note'))] + [
            {'label': '往来类别', 'value': '客户应收' if content['kind'] == 'receivable' else '供应商应付'},
            {'label': '资金动作', 'value': {'settlement': '收款 / 付款', 'refund': '退款 / 收退', 'reversal': '反向资金'}[content['action']]}] + (
            [{'label': '原资金单号', 'value': content['original']['document_no'] or f"#{content['original']['id']}"}]
            if content['original'] else [])
    if document_type == 'SubledgerOpening':
        from app.core.models import LedgerAccount
        from app.finance.auxiliary_rules import LABELS
        original = db.get(OpeningBalance, content['opening_balance_id'])
        result = [{'label': label, 'value': str(value)} for label, value in [
            ('分户依据', content['reference']), ('启用日', content['effective_date']),
            ('总账期初', original.document_no or f"#{original.id}"), ('总账版本', content['opening_version']),
            ('备注', content['note']), ('原单总数', len(content['lines']))]]
        for control in content['control_accounts']:
            account = db.get(LedgerAccount, control['account_id'])
            result.append({'label': '应收控制科目' if control['kind'] == 'receivable' else '应付控制科目',
                'value': account.code + ' · ' + account.name if account else str(control['account_id'])})
        for line in content['lines'][:100]:
            auxiliary = '、'.join(f"{LABELS[item['kind']]} #{item['id']}" for item in line['auxiliary'])
            result.append({'label': line['document_reference'], 'value': f"原单日期 {line['document_date']}；科目 {line['account_code']}；借 {line['debit']} / 贷 {line['credit']}；{auxiliary}"})
        result.append({'label': '完整核对', 'value': '请在本方案“核对与审计”中核对全部原单及逐组合勾稽；此处展示前一百行，全部原单及总账期初依据均参与摘要校验。'})
        return result
    if document_type == 'OpeningBalance':
        from app.core.models import LedgerAccount, AccountingPeriod
        from app.finance.auxiliary_rules import LABELS
        period = db.get(AccountingPeriod, content['period_id'])
        total = sum(Decimal(line['debit']) for line in content['lines'])
        result = [{'label': label, 'value': str(value)} for label, value in [
            ('启用日', content['effective_date']), ('会计期间', period.code if period else content['period_id']),
            ('依据编号', content['reference']), ('备注', content['note']), ('借贷各', f'人民币 {total:.2f} 元')]]
        for line in content['lines']:
            account = db.get(LedgerAccount, line['account_id'])
            auxiliary = '、'.join(f"{LABELS[item['kind']]} #{item['id']}" for item in line['auxiliary'])
            result.append({'label': line['account_code'] + ' · ' + (account.name if account else '科目快照'),
                'value': f"{line['summary']}；借 {line['debit']} / 贷 {line['credit']}；辅助 {auxiliary or '无'}"})
        return result
    if document_type == 'Journal':
        from app.core.models import LedgerAccount, AccountingPeriod
        from app.finance.auxiliary_rules import LABELS
        period = db.get(AccountingPeriod, content['period_id'])
        total = sum(Decimal(line['debit']) for line in content['lines'])
        result = [{'label': label, 'value': str(value)} for label, value in [
            ('凭证日期', content['journal_date']), ('会计期间', period.code if period else content['period_id']),
            ('依据编号', content['reference']), ('备注', content['note']), ('借贷各', f'人民币 {total:.2f} 元'),
            ('来源', '独立冲销凭证' if content['reversal_of_id'] else '损益结转' if content['profit_transfer']
                else '业务来源凭证' if content['business_source'] else '手工凭证')]]
        for line in content['lines']:
            account = db.get(LedgerAccount, line['account_id'])
            auxiliary = '、'.join(f"{LABELS[item['kind']]} #{item['id']}" for item in line['auxiliary'])
            result.append({'label': line['account_code'] + ' · ' + (account.name if account else '科目快照'),
                'value': f"{line['summary']}；借 {line['debit']} / 贷 {line['credit']}；辅助 {auxiliary or '无'}"})
        result.extend({'label': '固定附件', 'value': item['file_name'] + ' · SHA256 ' + item['sha256']
            + ('（已撤销）' if item['reversal_id'] else '')} for item in content['attachments'][:10])
        result.append({'label': '附件核对', 'value': f"共固定 {len(content['attachments'])} 份，完整指纹均参与校验；此处展示前十份。"})
        return result
    if document_type == 'MaintenanceJob':
        import json
        equipment = json.loads(content['equipment_json'])
        executor = db.get(User, content['assigned_to'])
        # 设备查看权限不能透过通用弹窗读取关联生产工单正文。
        summary = [{'label': label, 'value': str(value) if value is not None else '—'} for label, value in [
            ('设备', equipment['code'] + ' · ' + equipment['name']),
            ('设备位置', equipment['location']), ('维护依据', content['reference']),
            ('维护方式', '周期保养' if content['kind'] == 'preventive' else '故障维护'),
            ('计划日期或小时阈值', content['plan_due_date'] or content['plan_due_hours']),
            ('指定执行人', executor.username if executor else content['assigned_to']),
            ('维护方案', content['request_note']), ('生产关联', '有生产关联，仅说明影响' if content['work_order_id'] else '无')]]
        summary.extend({'label': '计划耗材', 'value': f"{db.get(Material, item['material_id']).name} × {item['quantity']}"}
            for item in json.loads(content['parts_json']))
        summary.extend({'label': '方案附件', 'value': item['file_name'] + ' · SHA256 ' + item['sha256']
            + ('（已撤销）' if item['reversal_id'] else '')} for item in content['attachments'][:10])
        summary.append({'label': '附件核对', 'value': f"固定附件共 {len(content['attachments'])} 份；此处最多展示前十份，完整指纹均参与审批校验。"})
        return summary
    if document_type == 'MrpPlan':
        import json
        inputs, snapshot = json.loads(content['input_json']), json.loads(content['snapshot_json'])
        summary = [{'label': label, 'value': str(value)} for label, value in [
            ('计划依据', content['reference']), ('计划起日', inputs['start_date']),
            ('编制依据', inputs['reason']), ('来源指纹', content['fingerprint']),
            ('固定建议数', len(snapshot['suggestions'])), ('固定警告数', len(snapshot['warnings']))]]
        # 完整正文参与摘要校验；通用弹窗限制展示量，明确引导核对原固定结果与 CSV。
        summary.extend({'label': '固定供给建议', 'value': f"{row['sku']} · {row['name']} × {row['quantity']} {row['unit']}；需求日 {row['due_date']}；{'采购' if row['supply_mode'] == 'buy' else '生产'}"}
            for row in snapshot['suggestions'][:100])
        summary.append({'label': '完整依据', 'value': '请核对本计划的结果与来源、警告及固定 CSV；此处最多展示前 100 条建议。'})
        return summary
    if document_type == 'QualityDisposition':
        import json
        original = json.loads(content['source_json'])
        summary = [{'label': label, 'value': str(value)} for label, value in [
            ('原完工单', db.get(ProductionCompletion, content['completion_id']).document_no or f"#{content['completion_id']}"),
            ('成品', f"{original['product_sku']} · {original['product_name']}"),
            ('检验依据', original['qc_note']), ('处置依据', content['reference']),
            ('处置方式及数量', f"{ {'scrap': '报废', 'rework': '返工'}[content['kind']] } · {content['quantity']} {original['product_unit']}"),
            ('成本处理', {'absorb': '由合格品承担', 'expense': '独立报废损失', 'carry': '携带来源成本返工'}[content['loss_treatment']]),
            ('缺陷记录', content['defect']), ('处置说明', content['action_note'])]]
        if content['warehouse_id'] is not None:
            warehouse = db.get(Warehouse, content['warehouse_id'])
            summary.append({'label': '返工仓库', 'value': warehouse.name if warehouse else str(content['warehouse_id'])})
        summary.extend({'label': '追加材料', 'value': f"{line['sku']} · {line['material_name']} × {line['quantity']} {line['unit']}"}
            for line in json.loads(content['materials_json']))
        return summary
    if document_type == 'AfterSalesCase':
        import json
        original = json.loads(content['source_json'])
        summary = [{'label': label, 'value': str(value) if value is not None else '—'} for label, value in [
            ('客户', original['customer_name']), ('原出库明细', content['shipment_line_id']),
            ('售后依据', content['reference']), ('处理方式', {'return': '退货', 'exchange': '换货', 'repair': '维修'}[content['kind']]),
            ('物品及数量', f"{original['sku']} · {original['material_name']} × {content['quantity']} {original['unit']}"),
            ('客户诉求', content['complaint']), ('办理方案', content['solution']),
            ('客户同意依据', content['customer_acceptance']),
            ('维修收费', f"{ {'none': '不涉及维修费', 'free': '免费维修', 'charge': '收费维修'}[content['charge_mode']] } · ¥{content['fee_amount']}"),
            ('保修依据', content['warranty_basis'] or '未确认保修条款')]]
        if 'replacement' in original:
            line = original['replacement']
            summary.append({'label': '换货计划', 'value': f"{line['sku']} · {line['material_name']} × {line['quantity']} {line['unit']}；单价 ¥{line['unit_price']}"})
        summary.extend({'label': '维修耗材', 'value': f"{line['sku']} · {line['material_name']} × {line['quantity']} {line['unit']}"}
            for line in json.loads(content['parts_json']))
        summary.extend({'label': '方案附件', 'value': row['file_name'] +
            ('（已撤销）' if row['reversal_id'] else '') + ' · SHA256 ' + row['sha256']}
            for row in content['attachments'])
        return summary
    # 报价使用固定的名称和联系方式；资料改名不能改写送审显示的依据。
    if document_type == 'CrmQuote':
        import json
        party = json.loads(content['party_json'])
        summary = [{'label': label, 'value': value or '—'} for label, value in [
            ('客户', party['customer_name']), ('联系人', party['contact_name']),
            ('电话', party['phone']), ('邮箱', party['email']), ('参考号', content['reference']),
            ('有效期', content['valid_until']), ('商务条款', content['terms'])]]
        summary.extend({'label': f"{line['sku']} · {line['material_name']}",
            'value': f"{line['quantity']} {line['unit']}；单价 ¥{line['unit_price']}"}
            for line in content['lines'])
        summary.extend({'label': '附件依据', 'value': row['file_name'] +
            ('（已撤销）' if row['reversal_id'] else '') + ' · SHA256 ' + row['sha256']}
            for row in content['attachments'])
        return summary
    # 其他单据只读取固定正文和当前资料名称，不调用其他领域详情。
    summary = []
    for field, model, label in [('supplier_id', Supplier, '供应商'), ('customer_id', Customer, '客户'), ('warehouse_id', Warehouse, '仓库'),
                                ('from_warehouse_id', Warehouse, '来源仓库'), ('to_warehouse_id', Warehouse, '目标仓库')]:
        if field in content:
            item = db.get(model, content[field])
            summary.append({'label': label, 'value': item.name if item else str(content[field])})
    if 'purchase_order_id' in content:
        order = db.get(PurchaseOrder, content['purchase_order_id'])
        summary.append({'label': '采购订单', 'value': order.document_no or f'#{order.id}'})
    if 'sales_order_id' in content:
        order = db.get(SalesOrder, content['sales_order_id'])
        summary.append({'label': '销售订单', 'value': order.document_no or f'#{order.id}'})
    if 'work_order_id' in content:
        order = db.get(WorkOrder, content['work_order_id'])
        summary.append({'label': '生产工单', 'value': order.document_no or f'#{order.id}'})
    if document_type == 'PurchaseRequest':
        summary.append({'label': '采购说明', 'value': content['note'] or '—'})
        for conversion_id in content['mrp_conversion_ids']:
            conversion = db.get(MrpConversion, conversion_id)
            plan = db.get(MrpPlan, conversion.plan_id)
            summary.append({'label': '物料需求计划', 'value': plan.document_no or f'#{plan.id}'})
        for identifier in content['maintenance_job_ids']:
            job = db.get(MaintenanceJob, identifier)
            summary.append({'label': '维护工单', 'value': job.document_no or f'#{job.id}'})
    if document_type == 'WorkOrder':
        product = db.get(Material, content['product_material_id'])
        summary.extend([{'label': '成品目标', 'value': f"{product.sku} · {product.name} × {content['target_quantity']} {product.unit}"},
                        {'label': 'BOM 版本', 'value': str(content['bom_version'])},
                        {'label': '工单说明', 'value': content['note']}])
        for conversion_id in content['mrp_conversion_ids']:
            conversion = db.get(MrpConversion, conversion_id)
            plan = db.get(MrpPlan, conversion.plan_id)
            summary.append({'label': '物料需求计划', 'value': plan.document_no or f'#{plan.id}'})
        for identifier in content['rework_disposition_ids']:
            row = db.get(QualityDisposition, identifier)
            summary.append({'label': '返工来源', 'value': row.document_no or f'#{row.id}'})
    if document_type == 'MaterialReturn':
        issue = db.get(MaterialIssue, content['material_issue_id'])
        summary.extend([{'label': '原领料单', 'value': issue.document_no or f'#{issue.id}'},
                        {'label': '退料原因', 'value': content['reason']}])
    if document_type == 'ProductionCompletion':
        summary.extend([{'label': '质检结果', 'value': f"报工 {content['reported_quantity']}；合格 {content['accepted_quantity']}；不合格 {content['rejected_quantity']}"},
                        {'label': '质检说明', 'value': content['qc_note'] or '—'}])
    if document_type == 'SalesReturn':
        source = db.get(Shipment, content['shipment_id'])
        summary.extend([{'label': '原出库单', 'value': source.document_no or f'#{source.id}'},
                        {'label': '退货原因', 'value': content['reason']}])
    if document_type == 'SalesOrder' and content['contract']:
        contract = content['contract'][-1]
        summary.extend([{'label': '合同正文（版本 ' + str(contract['version']) + '）', 'value': contract['body']},
                        {'label': '客户确认依据', 'value': contract['acceptance_reference']}])
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
        if document_type == 'SalesOrder' and line['warranty_days'] is not None:
            value += f"；保修 {line['warranty_days']} 天（{line['warranty_basis']}）"
        summary.append({'label': f'{material.sku} · {material.name}' if material else str(line['material_id']),
                        'value': value})
    return summary
