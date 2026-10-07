"""仅在授权后的接口响应补充编号，不把展示字段写进历史快照或来源指纹。"""

import json
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy import select

from app.core import models
from app.core.document_types import DOCUMENT_TYPES
from app.core.orm import orm_session

# 主单接口与嵌套集合使用明确的类型白名单，不能把明细 ID 当作另一张主单。
PATH_TYPES = {
    'purchase-requests': 'PurchaseRequest', 'purchase-orders': 'PurchaseOrder',
    'purchase-goods-receipts': 'PurchaseGoodsReceipt', 'receipts': 'Receipt',
    'purchase-returns': 'PurchaseReturn', 'warehouse-inbounds': 'WarehouseInbound',
    'warehouse-outbounds': 'WarehouseOutbound', 'transfers': 'Transfer', 'stocktakes': 'Stocktake',
    'stock-adjustments': 'StockAdjustment', 'sales-orders': 'SalesOrder', 'shipments': 'Shipment',
    'sales-returns': 'SalesReturn', 'work-orders': 'WorkOrder', 'material-issues': 'MaterialIssue',
    'material-returns': 'MaterialReturn', 'production-completions': 'ProductionCompletion',
    'crm/quotes': 'CrmQuote', 'crm/records/quote': 'CrmQuote',
    'after-sales/cases': 'AfterSalesCase', 'production-quality/dispositions': 'QualityDisposition',
    'production/mrp/plans': 'MrpPlan', 'production-costs/settlements': 'ProductionCostSettlement',
    'equipment/jobs': 'MaintenanceJob', 'finance/journals': 'Journal',
    'finance/opening-balances': 'OpeningBalance', 'finance/subledger-openings': 'SubledgerOpening',
    'payment-records': 'PaymentRecord', 'finance/payment-records': 'PaymentRecord', 'finance/order-settlements': 'OrderSettlementTransfer',
}
COLLECTION_TYPES = {
    'quotes': 'CrmQuote', 'dispositions': 'QualityDisposition', 'jobs': 'MaintenanceJob',
    'payment_records': 'PaymentRecord', 'payments': 'PaymentRecord',
    'order_settlements': 'OrderSettlementTransfer', 'journal': 'Journal',
    'opening_balance': 'OpeningBalance', 'opening': 'SubledgerOpening',
    'requests': 'PurchaseRequest', 'orders': 'PurchaseOrder', 'goods_receipts': 'PurchaseGoodsReceipt', 'settlements': 'ProductionCostSettlement',
}
# 表名集合和单据类型同源；嵌套的自动建单结果也按各自主单编号展示。
COLLECTION_TYPES.update({table: name for name, table, _, _ in DOCUMENT_TYPES})
RELATION_TYPES = {
    'purchase_request': 'PurchaseRequest', 'purchase_order': 'PurchaseOrder',
    'goods_receipt': 'PurchaseGoodsReceipt', 'inbound_receipt': 'Receipt', 'receipt': 'Receipt',
    'purchase_return': 'PurchaseReturn', 'outbound': 'WarehouseOutbound',
    'sales_order': 'SalesOrder', 'replacement_order': 'SalesOrder', 'shipment': 'Shipment',
    'sales_return': 'SalesReturn', 'work_order': 'WorkOrder', 'rework_order': 'WorkOrder',
    'origin_work_order': 'WorkOrder', 'material_issue': 'MaterialIssue',
    'material_return': 'MaterialReturn', 'completion': 'ProductionCompletion',
    'production_completion': 'ProductionCompletion', 'disposition': 'QualityDisposition',
    'settlement': 'ProductionCostSettlement', 'origin_settlement': 'ProductionCostSettlement',
    'job': 'MaintenanceJob', 'maintenance_job': 'MaintenanceJob', 'case': 'AfterSalesCase', 'parts_outbound': 'WarehouseOutbound',
    'journal': 'Journal', 'reversal_journal': 'Journal', 'reversal_of': 'Journal',
    'opening_balance': 'OpeningBalance', 'subledger_opening': 'SubledgerOpening',
}
SOURCE_TYPES = {
    'receipt': 'Receipt', 'purchase_return': 'PurchaseReturn', 'other_inbound': 'WarehouseInbound',
    'other_outbound': 'WarehouseOutbound', 'shipment': 'Shipment', 'sales_return': 'SalesReturn',
    'transfer': 'Transfer', 'transfer_in': 'Transfer', 'transfer_out': 'Transfer',
    'order_payment': 'PaymentRecord', 'payment_record': 'PaymentRecord', 'subledger_payment': 'SubledgerPayment',
    'quality_loss': 'QualityDisposition', 'stocktake': 'Stocktake', 'stock_adjustment': 'StockAdjustment', 'adjustment': 'StockAdjustment',
    'material_issue': 'MaterialIssue', 'material_return': 'MaterialReturn',
    'production_completion': 'ProductionCompletion', 'work_order': 'WorkOrder',
    'after_sales_repair': 'AfterSalesCase', 'purchase_order': 'PurchaseOrder', 'sales_order': 'SalesOrder', 'purchase_request': 'PurchaseRequest',
}
REVERSAL_TYPES = {
    'receipt': ('ReceiptReversal', 'receipt_id'), 'purchase_return': ('PurchaseReturnReversal', 'purchase_return_id'),
    'other_inbound': ('WarehouseInboundReversal', 'inbound_id'),
    'other_outbound': ('WarehouseOutboundReversal', 'outbound_id'),
    'shipment': ('ShipmentReversal', 'shipment_id'), 'sales_return': ('SalesReturnReversal', 'sales_return_id'),
    'transfer': ('TransferReversal', 'transfer_id'), 'stocktake': ('StocktakeReversal', 'stocktake_id'),
    'adjustment': ('StockAdjustmentReversal', 'adjustment_id'),
    'stock_adjustment': ('StockAdjustmentReversal', 'adjustment_id'),
    'material_issue': ('MaterialIssueReversal', 'material_issue_id'),
    'material_return': ('MaterialReturnReversal', 'material_return_id'),
    'production_completion': ('ProductionCompletionReversal', 'production_completion_id'),
}


def path_type(path: str) -> str | None:
    path = path.removeprefix('/api/v1/').strip('/')
    if any(segment in path.split('/') for segment in ('changes', 'attachments', 'options', 'available-lots', 'check')):
        return None
    if path in ('finance/business-journals/generate', 'finance/profit-transfers/generate'):
        return 'Journal'
    if path.startswith('finance/subledger-openings/') and '/payments' in path:
        return 'SubledgerPayment'
    for prefix in sorted(PATH_TYPES, key=len, reverse=True):
        if path == prefix or path.startswith(prefix + '/'):
            return PATH_TYPES[prefix]
    return None


def enrich_numbers(db, value, primary: str | None, path: str):
    requests = []
    def add(target, key, model, identifier):
        if isinstance(identifier, int) and not isinstance(identifier, bool) and identifier > 0:
            requests.append((target, key, model, identifier))

    def visit(node, kind=None):
        if isinstance(node, list):
            for part in node:
                visit(part, kind)
        elif isinstance(node, dict):
            if kind and not any(part in path.split('/') for part in ('changes', 'attachments')):
                add(node, 'document_no', kind, node.get('id'))
            for field, model in RELATION_TYPES.items():
                # 主单分录的父单 ID 已由外层展示，明细与审计快照保持逐项可比较。
                if 'position' in node and field in ('journal', 'opening_balance'):
                    continue
                add(node, field + '_document_no', model, node.get(field + '_id'))
            frozen = node.get('frozen_source')
            if isinstance(frozen, dict):
                # 冻结依据保留原样；仅在外层补充其来源主单号供页面展示。
                for field, model in RELATION_TYPES.items():
                    add(node, field + '_document_no', model, frozen.get(field + '_id'))
            if path.startswith('/api/v1/production/mrp'):
                add(node, 'plan_document_no', 'MrpPlan', node.get('plan_id'))
            order_type = 'SalesOrder' if node.get('kind') == 'receivable' else 'PurchaseOrder' if node.get('kind') == 'payable' else None
            if order_type:
                for field in ('order', 'from_order', 'to_order'):
                    add(node, field + '_document_no', order_type, node.get(field + '_id'))
            if kind in ('PaymentRecord', 'SubledgerPayment', 'OrderSettlementTransfer'):
                add(node, 'reverses_document_no', kind, node.get('reverses_id'))
            source = node.get('source_type') or node.get('kind')
            if isinstance(source, str):
                base = 'transfer' if source.startswith('transfer_reversal_') else source.removesuffix('_reversal')
                if base in SOURCE_TYPES:
                    identifier = node.get('source_id')
                    if ('_reversal' in source) and base in REVERSAL_TYPES and isinstance(identifier, int):
                        reverse_model, field = REVERSAL_TYPES[base]
                        reverse = db.get(getattr(models, reverse_model), identifier)
                        identifier = getattr(reverse, field, None)
                    add(node, 'source_document_no', SOURCE_TYPES[base], identifier)
            for key, part in list(node.items()):
                # 固定证据原样返回，补号不能改变快照内容或其哈希语义。
                if key not in ('snapshot', 'before', 'after', 'evidence', 'frozen_source'):
                    child = COLLECTION_TYPES.get(key)
                    # 财务 overview 的 transfers 是订单核销，不能按同名仓库调拨覆盖主单号。
                    if key == 'transfers' and path == '/api/v1/finance/overview':
                        child = 'OrderSettlementTransfer'
                    if key == 'payments' and path.startswith('/api/v1/finance/subledger-openings'):
                        child = 'SubledgerPayment'
                    if key == 'cases' and path.startswith('/api/v1/production-quality'):
                        child = 'ProductionCompletion'
                    if key == 'cases' and path.startswith('/api/v1/after-sales'):
                        child = 'AfterSalesCase'
                    if key == 'records' and source in ('payment_record', 'subledger_payment'):
                        child = SOURCE_TYPES[source]
                    if key in ('items', 'row', 'record'):
                        child = kind
                    visit(part, child)
    visit(value, primary)
    grouped = {}
    for _, _, name, identifier in requests:
        grouped.setdefault(name, set()).add(identifier)
    numbers = {}
    # 每种类型批量读取，明细多或分页数量大时也不逐行请求数据库。
    for name, identifiers in grouped.items():
        model = getattr(models, name)
        ids = sorted(identifiers)
        for start in range(0, len(ids), 500):
            for identifier, number in db.execute(select(model.id, model.document_no).where(model.id.in_(ids[start:start+500]))):
                numbers[name, identifier] = number
    for target, key, name, identifier in requests:
        target[key] = numbers.get((name, identifier))
    return value


class NumberedRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        async def handler(request):
            response = await original(request)
            if response.status_code == 204 or not response.body or request.url.path.endswith('/check'):
                return response
            if response.status_code >= 400 or 'application/json' not in response.headers.get('content-type', ''):
                return response
            value = json.loads(response.body)
            with orm_session() as db:
                enrich_numbers(db, value, path_type(request.url.path), request.url.path)
            headers = {key: value for key, value in response.headers.items() if key.lower() != 'content-length'}
            return JSONResponse(value, status_code=response.status_code, headers=headers, background=response.background)
        return handler
