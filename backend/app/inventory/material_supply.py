"""物料当前采购供需快照；只读汇总，不改变库存或历史计划。"""

import json
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator
from sqlalchemy import select

from app.access.security import current_user
from app.core.models import (Material, Warehouse, StockMovement, PurchaseOrder,
    PurchaseOrderLine, PurchaseOrderRequestLink, PurchaseRequest, PurchaseRequestLine,
    PurchaseGoodsReceipt, Receipt, ReceiptLine, ReceiptOrderLink,
    MrpPlan, MrpConversion, DocumentApprovalCase)
from app.core.orm import orm_session
from app.purchase.orders import received_quantity
from app.purchase.requests import ordered_quantity
from app.production.mrp import current_check

router = APIRouter(prefix='/api/v1/inventory/material-supply')
ZERO = Decimal(0)
PHASES = ('stock', 'planned', 'awaiting_delivery', 'awaiting_inbound')


class SupplyQuery(BaseModel):
    # 严格编号和批量上限同时在服务端校验，不能由客户端声明查看权限。
    model_config = ConfigDict(extra='forbid')
    material_ids: list[StrictInt] = Field(min_length=1, max_length=100)

    @field_validator('material_ids')
    @classmethod
    def valid_ids(cls, value: list[int]) -> list[int]:
        # 与桌面安全整数边界一致，避免超大整数进入 SQLite 查询后触发溢出。
        if any(not 0 < identifier <= 9_007_199_254_740_991 for identifier in value) or len(set(value)) != len(value):
            raise ValueError('物料编号须为不重复的正安全整数')
        return value


def quantity(value: Decimal) -> str:
    return format(value.quantize(Decimal('0.001')), 'f')


@router.post('/query')
def query(payload: SupplyQuery, user: dict = Depends(current_user)) -> dict:
    permissions = set(user['permissions'])
    if not permissions.intersection({'inventory.view', 'mrp.view', 'purchase_request.view'}):
        raise HTTPException(403, '没有查看物料供需的权限')
    stock_allowed = 'inventory.view' in permissions
    # 计划由 MRP、申请和未确认订单共同组成，缺任何来源权限就返回未授权，不能冒充完整零值。
    plan_allowed = {'inventory.view', 'mrp.view', 'purchase_request.view'} <= permissions
    with orm_session() as db:
        materials = {row.id: row for row in db.scalars(select(Material).where(Material.id.in_(payload.material_ids)))}
        if len(materials) != len(payload.material_ids):
            raise HTTPException(422, '查询包含不存在的物料')
        totals = {identifier: {phase: ZERO for phase in PHASES} for identifier in materials}
        sources = {identifier: [] for identifier in materials}

        def add(identifier, phase, value, kind, record, *, warehouse_name=None):
            if value <= 0 and phase != 'stock':
                return
            totals[identifier][phase] += value
            sources[identifier].append({'phase': phase, 'kind': kind, 'document_id': record.id,
                'document_no': getattr(record, 'document_no', None),
                'reference': getattr(record, 'reference', ''), 'quantity': quantity(value),
                'warehouse_name': warehouse_name})

        if stock_allowed:
            balances = defaultdict(lambda: ZERO)
            warehouses = {row.id: row for row in db.scalars(select(Warehouse))}
            for identifier, warehouse_id, value in db.execute(select(StockMovement.material_id,
                    StockMovement.warehouse_id, StockMovement.quantity).where(StockMovement.material_id.in_(materials))):
                balances[(identifier, warehouse_id)] += Decimal(value)
            for (identifier, warehouse_id), value in balances.items():
                add(identifier, 'stock', value, 'warehouse', warehouses[warehouse_id],
                    warehouse_name=warehouses[warehouse_id].name)

            # 已确认收货产生的入库草稿即使尚未批准，也有真实到货依据；手工入库仅在批准后计入。
            confirmed_receipts = set(db.scalars(select(PurchaseGoodsReceipt.inbound_receipt_id)
                .where(PurchaseGoodsReceipt.status == 'confirmed')))
            approved_receipts = set(db.scalars(select(DocumentApprovalCase.document_id).where(
                DocumentApprovalCase.document_type == 'Receipt', DocumentApprovalCase.intent == 'execute',
                DocumentApprovalCase.status == 'approved')))
            pending_by_order = defaultdict(lambda: ZERO)
            for line, receipt, order_line_id in db.execute(select(ReceiptLine, Receipt,
                    ReceiptOrderLink.purchase_order_line_id).join(Receipt, Receipt.id == ReceiptLine.receipt_id)
                    .outerjoin(ReceiptOrderLink, ReceiptOrderLink.receipt_line_id == ReceiptLine.id)
                    .where(Receipt.status == 'draft', ReceiptLine.material_id.in_(materials))):
                if receipt.id not in confirmed_receipts and receipt.id not in approved_receipts:
                    continue
                value = Decimal(line.quantity)
                add(line.material_id, 'awaiting_inbound', value, 'receipt', receipt)
                if order_line_id is not None:
                    pending_by_order[order_line_id] += value
            for line, order in db.execute(select(PurchaseOrderLine, PurchaseOrder)
                    .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
                    .where(PurchaseOrder.status.in_(('confirmed', 'partially_received')),
                        PurchaseOrderLine.material_id.in_(materials))):
                # 已入库与已到未入库分别扣除；拒收、取消和冲销不消除供应商剩余交付义务。
                remaining = max(ZERO, Decimal(line.quantity) - received_quantity(db, line.id) - pending_by_order[line.id])
                add(line.material_id, 'awaiting_delivery', remaining, 'purchase_order', order)

        if plan_allowed:
            conversions = list(db.scalars(select(MrpConversion)))
            converted = {(row.plan_id, row.suggestion_key) for row in conversions}
            derived_requests = {row.purchase_request_id for row in conversions if row.purchase_request_id}
            approved_requests = set(db.scalars(select(DocumentApprovalCase.document_id).where(
                DocumentApprovalCase.document_type == 'PurchaseRequest', DocumentApprovalCase.intent == 'execute',
                DocumentApprovalCase.status.in_(('approved', 'executed')))))
            planned_request_lines = set()
            for line, request in db.execute(select(PurchaseRequestLine, PurchaseRequest)
                    .join(PurchaseRequest, PurchaseRequest.id == PurchaseRequestLine.purchase_request_id)
                    .where(PurchaseRequest.status != 'cancelled', PurchaseRequestLine.material_id.in_(materials))):
                if request.id not in approved_requests and request.id not in derived_requests:
                    continue
                planned_request_lines.add(line.id)
                add(line.material_id, 'planned', max(ZERO, Decimal(line.quantity) - ordered_quantity(db, line.id)),
                    'purchase_request', request)
            approved_orders = set(db.scalars(select(DocumentApprovalCase.document_id).where(
                DocumentApprovalCase.document_type == 'PurchaseOrder', DocumentApprovalCase.intent == 'execute',
                DocumentApprovalCase.status == 'approved')))
            for line, order, request_line_id in db.execute(select(PurchaseOrderLine, PurchaseOrder,
                    PurchaseOrderRequestLink.purchase_request_line_id)
                    .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
                    .outerjoin(PurchaseOrderRequestLink, PurchaseOrderRequestLink.purchase_order_line_id == PurchaseOrderLine.id)
                    .where(PurchaseOrder.status == 'draft', PurchaseOrderLine.material_id.in_(materials))):
                if order.id in approved_orders or request_line_id in planned_request_lines:
                    add(line.material_id, 'planned', Decimal(line.quantity), 'purchase_order', order)
            planned_materials = set()
            for plan in db.scalars(select(MrpPlan).where(MrpPlan.status == 'approved').order_by(MrpPlan.id.desc())):
                # 已过期或来源变化的固定计划不能再转单，不能当作当前有效采购计划。
                if not current_check(db, plan)['matched']:
                    continue
                # 已转申请的建议只沿下游原单统计；取消下游不能让旧计划再次凭空生效。
                included = set()
                for suggestion in json.loads(plan.snapshot_json)['suggestions']:
                    identifier = suggestion['material_id']
                    if identifier in materials and identifier not in planned_materials and suggestion['supply_mode'] == 'buy' and (plan.id, suggestion['key']) not in converted:
                        add(identifier, 'planned', Decimal(suggestion['quantity']), 'mrp_plan', plan)
                        included.add(identifier)
                # 固定 MRP 结果是同一批来源的计算方案，同物料仅采用最近有效批准计划，不能叠加旧方案。
                planned_materials.update(included)

        return {'scope': 'all_warehouses', 'generated_at': datetime.now(timezone.utc).isoformat(),
            'rows': [{'material_id': identifier, 'sku': materials[identifier].sku,
                'name': materials[identifier].name, 'unit': materials[identifier].unit,
                **{phase + '_quantity': quantity(totals[identifier][phase]) if (
                    plan_allowed if phase == 'planned' else stock_allowed) else None for phase in PHASES},
                'sources': sources[identifier]} for identifier in payload.material_ids]}
