"""审批领域适配器；明细快照和可执行状态必须由服务端业务模型生成。"""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import (
    Material, PurchaseGoodsReceipt, PurchaseGoodsReceiptLine, PurchaseOrder, PurchaseOrderLine,
    PurchaseOrderRequestLink, Receipt, ReceiptLine, ReceiptOrderLink, ReceiptReversal,
    ReceiptWarehouse, Supplier, Warehouse, WarehouseInbound, WarehouseInboundLine,
    WarehouseInboundReversal,
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


# 仅登记已在原领域执行事务中接入校验的类型，避免生成无法保障执行边界的批准记录。
_SNAPSHOTS = {'WarehouseInbound': inbound_snapshot, 'PurchaseOrder': purchase_order_snapshot,
              'PurchaseGoodsReceipt': goods_receipt_snapshot, 'Receipt': receipt_snapshot}
_REVERSE = {'WarehouseInbound': (WarehouseInboundReversal, 'inbound_id', 'other_inbound.reverse'),
            'Receipt': (ReceiptReversal, 'receipt_id', 'receipt.reverse')}


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
    if intent == 'reverse':
        reversal = _REVERSE.get(document_type)
        if reversal is None:
            raise HTTPException(422, '此类单据不支持独立冲销审批')
        model, field, _ = reversal
        if source.status != 'posted' or db.scalar(select(model.id).where(getattr(model, field) == identifier)):
            raise HTTPException(409, '此冲销动作已处理，不能继续审批')
    elif source.status != 'draft':
        # 历史已执行记录不补造审批；只限制仍待执行的草稿。
        raise HTTPException(409, '此单据已处理，不能继续审批')
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
    for field, model, label in [('supplier_id', Supplier, '供应商'), ('warehouse_id', Warehouse, '仓库')]:
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
    summary.append({'label': '参考号', 'value': content['reference'] or '—'})
    for line in content['lines']:
        material = db.get(Material, line['material_id'])
        unit = f' {material.unit}' if material else ''
        value = (f"合格 {line['accepted_quantity']}{unit}；拒收 {line['rejected_quantity']}{unit}；原因 {line['rejection_reason'] or '—'}"
                 if document_type == 'PurchaseGoodsReceipt' else line['quantity'] + unit)
        if 'unit_price' in line:
            value += f"；单价 ¥{line['unit_price']}"
        summary.append({'label': f'{material.sku} · {material.name}' if material else str(line['material_id']),
                        'value': value})
    return summary
