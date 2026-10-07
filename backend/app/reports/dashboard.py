"""首页只读经营快照：业务发生额与当前待办使用明确且独立的口径。"""

from app.core.document_responses import NumberedRoute
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.access.security import current_user, user_details
from app.core.orm import orm_session
from app.core.models import (
    SalesOrder, SalesOrderLine, Shipment, ShipmentLine, ShipmentReversal,
    PurchaseOrder, PurchaseOrderLine, Receipt, ReceiptLine, ReceiptOrderLink, ReceiptReversal,
    ProductionCompletion, ProductionCompletionReversal, WorkOrder, Transfer, TransferReversal,
    StockMovement, Material,
)
from app.finance.routes import financial_entries

router = APIRouter(route_class=NumberedRoute, prefix="/api/v1/dashboard")


class DashboardQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period: Literal["7d", "30d"] = "7d"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def money_summary(entries: list[dict]) -> dict:
    known = sum((Decimal(item['amount']) for item in entries if item['amount'] is not None), Decimal(0))
    missing = sum(item['amount'] is None for item in entries)
    return dict(amount=None if missing else f'{known:.2f}', known_amount=f'{known:.2f}',
                unpriced_count=missing, source_line_count=len(entries))


def pending_orders(db: Session, *, sales: bool) -> dict:
    order, line = (SalesOrder, SalesOrderLine) if sales else (PurchaseOrder, PurchaseOrderLine)
    parent = line.sales_order_id if sales else line.purchase_order_id
    partial = 'partially_shipped' if sales else 'partially_received'
    orders = dict(db.execute(select(order.id, order.status).where(order.status.in_(['draft', 'confirmed', partial]))).all())
    delivered: dict[int, Decimal] = {}
    if sales:
        rows = db.execute(select(ShipmentLine.sales_order_line_id, ShipmentLine.quantity)
            .join(Shipment, Shipment.id == ShipmentLine.shipment_id)
            .where(Shipment.status == 'posted', ~select(ShipmentReversal.id)
                   .where(ShipmentReversal.shipment_id == Shipment.id).exists()))
    else:
        rows = db.execute(select(ReceiptOrderLink.purchase_order_line_id, ReceiptLine.quantity)
            .join(ReceiptLine, ReceiptLine.id == ReceiptOrderLink.receipt_line_id)
            .join(Receipt, Receipt.id == ReceiptLine.receipt_id)
            .where(Receipt.status == 'posted', ~select(ReceiptReversal.id)
                   .where(ReceiptReversal.receipt_id == Receipt.id).exists()))
    for identifier, quantity in rows:
        delivered[identifier] = delivered.get(identifier, Decimal(0)) + Decimal(quantity)
    waiting = set()
    for identifier, order_id, quantity in db.execute(select(line.id, parent, line.quantity).where(parent.in_(list(orders)))):
        if orders[order_id] != 'draft' and delivered.get(identifier, Decimal(0)) < Decimal(quantity):
            waiting.add(order_id)
    return dict(draft=sum(status == 'draft' for status in orders.values()), waiting=len(waiting))


def effective_count(db: Session, model, reversal, key, start: str, cutoff: str) -> int:
    return db.scalar(select(func.count()).select_from(model).where(
        model.status == 'posted', model.posted_at >= start, model.posted_at <= cutoff,
        ~select(reversal.id).where(key == model.id).exists())) or 0


def dashboard_data(db: Session, permissions: list[str], period: str, now: datetime) -> dict:
    days = 7 if period == '7d' else 30
    today = now.date()
    first = today - timedelta(days=days-1)
    previous = first - timedelta(days=days)
    cutoff = now.strftime('%Y-%m-%d %H:%M:%S')
    first_stamp = f'{first} 00:00:00'
    result = dict(period=period, from_date=str(first), to_date=str(today),
                  previous_from_date=str(previous), previous_to_date=str(first-timedelta(days=1)),
                  generated_at=now.isoformat(), currency='CNY', time_basis='UTC',
                  finance=None, sales=None, purchase=None, production=None, inventory=None, composition=[])

    if 'finance.view' in permissions:
        # 复用往来来源的逐行分位金额；冲销按其发生日保留负向变化，不能回删原日。
        entries = [row for row in financial_entries(db) if row['posted_at'] <= cutoff
                   and row['posted_at'][:10] >= str(previous)]
        current = [row for row in entries if row['posted_at'][:10] >= str(first)]
        preceding = [row for row in entries if row['posted_at'][:10] < str(first)]
        finance = dict(trend=[], evidence=[], evidence_total=len(current))
        for name, kind in (('sales', 'receivable'), ('purchase', 'payable')):
            finance[name] = dict(current=money_summary([row for row in current if row['kind'] == kind]),
                                 previous=money_summary([row for row in preceding if row['kind'] == kind]))
        for offset in range(days):
            day = str(first + timedelta(days=offset))
            rows = [row for row in current if row['posted_at'][:10] == day]
            finance['trend'].append(dict(date=day,
                sales=money_summary([row for row in rows if row['kind'] == 'receivable']),
                purchase=money_summary([row for row in rows if row['kind'] == 'payable'])))
        finance['evidence'] = [{key: row[key] for key in (
            'key', 'kind', 'source_type', 'source_id', 'source_line_id', 'order_id', 'amount', 'posted_at')}
            for row in sorted(current, key=lambda row: (row['posted_at'], row['key']), reverse=True)[:100]]
        result['finance'] = finance

    specs = []
    if 'sales.view' in permissions:
        result['sales'] = pending_orders(db, sales=True)
        specs.append(('shipment', '销售出库', Shipment, ShipmentReversal, ShipmentReversal.shipment_id))
    if 'inventory.view' in permissions:
        result['purchase'] = pending_orders(db, sales=False)
        balances: dict[tuple[int, int], Decimal] = {}
        for warehouse, material, quantity in db.execute(select(
            StockMovement.warehouse_id, StockMovement.material_id, StockMovement.quantity)):
            key = (warehouse, material)
            balances[key] = balances.get(key, Decimal(0)) + Decimal(quantity)
        positive = {key for key, value in balances.items() if value > 0}
        result['inventory'] = dict(positive_positions=len(positive),
            stocked_materials=len({key[1] for key in positive}),
            registered_materials=db.scalar(select(func.count()).select_from(Material)) or 0,
            negative_positions=sum(value < 0 for value in balances.values()))
        specs.extend((('receipt', '采购入库', Receipt, ReceiptReversal, ReceiptReversal.receipt_id),
                      ('transfer', '仓库调拨', Transfer, TransferReversal, TransferReversal.transfer_id)))
    if 'production.view' in permissions:
        result['production'] = dict(draft=db.scalar(select(func.count()).select_from(WorkOrder)
            .where(WorkOrder.status == 'draft')) or 0,
            released=db.scalar(select(func.count()).select_from(WorkOrder)
            .where(WorkOrder.status.in_(('released', 'in_progress')))) or 0,
            awaiting_inspection=db.scalar(select(func.count()).select_from(ProductionCompletion)
            .where(ProductionCompletion.status == 'draft')) or 0,
            awaiting_post=db.scalar(select(func.count()).select_from(ProductionCompletion)
            .where(ProductionCompletion.status == 'inspected')) or 0)
        specs.append(('production_completion', '生产完工', ProductionCompletion,
                      ProductionCompletionReversal, ProductionCompletionReversal.production_completion_id))
    result['composition'] = [dict(key=key, label=label, count=effective_count(db, model, reversal, foreign, first_stamp, cutoff))
                            for key, label, model, reversal, foreign in specs]
    return result


@router.post('/query')
def query_dashboard(payload: DashboardQuery, user: dict = Depends(current_user)) -> dict:
    # 首页允许所有已登录账号访问；每个领域沿用原接口权限，不借首页扩大授权。
    with orm_session() as db:
        return dashboard_data(db, user_details(db, user['id'])['permissions'], payload.period, utc_now())
