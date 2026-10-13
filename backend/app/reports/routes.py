"""报表筛选与 CSV 使用同一份服务端计算结果。"""

from app.core.document_responses import NumberedRoute
import csv
from datetime import date
from sqlalchemy import select, func, true, tuple_
from sqlalchemy.orm import Session

from decimal import Decimal
from io import StringIO
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.access.security import current_user
from app.core.orm import orm_session
from app.core.models import (
    Material,
    PurchaseGoodsReceipt,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderRequestLink,
    PurchaseRequest,
    PurchaseReturn,
    Receipt,
    StockMovement,
    Supplier,
    Warehouse,
)
from app.inventory.ledger import LedgerQuery, query_ledger
from app.purchase.goods_receipts import goods_receipt_data
from app.purchase.orders import order_data
from app.purchase.receipts import receipt_data
from app.purchase.requests import request_data
from app.purchase.returns import purchase_return_data

router = APIRouter(route_class=NumberedRoute, prefix="/api/v1")

ReportKind = Literal[
    "purchase_requests", "purchase_orders", "receiving_returns", "inventory_balance", "stock_flow"
]


class ReportQuery(BaseModel):
    kind: ReportKind
    warehouse_id: int | None = Field(default=None, gt=0)
    material_id: int | None = Field(default=None, gt=0)
    supplier_id: int | None = Field(default=None, gt=0)
    from_date: date | None = None
    to_date: date | None = None


class InventoryReportQuery(ReportQuery):
    # 库存报表分页独立于采购报表，保持既有采购查询和完整 CSV 导出接口。
    kind: Literal['inventory_balance', 'stock_flow']
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


COLUMNS = {
    "purchase_requests": [
        ("document", "申请单"),
        ("status", "状态"),
        ("date", "创建时间"),
        ("reference", "参考号"),
        ("material", "物料"),
        ("quantity", "申请量"),
        ("ordered", "已转订单"),
        ("remaining", "未转数量"),
        ("suppliers", "关联供应商"),
    ],
    "purchase_orders": [
        ("document", "采购订单"),
        ("request", "申请单"),
        ("supplier", "供应商"),
        ("status", "状态"),
        ("date", "创建时间"),
        ("material", "物料"),
        ("ordered", "订购量"),
        ("received", "已入库"),
        ("returned", "已退货"),
        ("remaining", "未入库"),
        ("amount", "订单行金额"),
    ],
    "receiving_returns": [
        ("type", "单据类型"),
        ("document", "单号"),
        ("source", "来源单号"),
        ("supplier", "供应商"),
        ("warehouse", "仓库"),
        ("status", "状态"),
        ("date", "创建时间"),
        ("material", "物料"),
        ("quantity", "合格或入库量"),
        ("rejected", "拒收量"),
        ("reason", "拒收或退货原因"),
    ],
    "inventory_balance": [
        ("warehouse", "仓库"),
        ("material", "物料"),
        ("unit", "单位"),
        ("quantity", "余额"),
    ],
    "stock_flow": [
        ("warehouse", "仓库"),
        ("material", "物料"),
        ("unit", "单位"),
        ("opening", "期初"),
        ("inbound", "收入"),
        ("outbound", "发出"),
        ("closing", "期末"),
    ],
}


def within_period(value: str, filters: ReportQuery) -> bool:
    day = value[:10]
    return (not filters.from_date or day >= str(filters.from_date)) and (
        not filters.to_date or day <= str(filters.to_date)
    )


def purchase_request_rows(db: Session, filters: ReportQuery) -> list[dict[str, str]]:
    rows = []
    for item_id in db.scalars(
        select(PurchaseRequest.id).select_from(PurchaseRequest).order_by(PurchaseRequest.id)
    ):
        item = request_data(db, item_id)
        if not within_period(item["created_at"], filters):
            continue
        for line in item["lines"]:
            if filters.material_id and line["material_id"] != filters.material_id:
                continue
            suppliers = (
                db.execute(
                    select(Supplier.id, Supplier.name)
                    .select_from(PurchaseOrderRequestLink)
                    .join(
                        PurchaseOrderLine,
                        (PurchaseOrderLine.id == PurchaseOrderRequestLink.purchase_order_line_id),
                    )
                    .join(PurchaseOrder, (PurchaseOrder.id == PurchaseOrderLine.purchase_order_id))
                    .join(Supplier, (Supplier.id == PurchaseOrder.supplier_id))
                    .where(
                        PurchaseOrderRequestLink.purchase_request_line_id == line["id"],
                        PurchaseOrder.status != "cancelled",
                    )
                    .distinct()
                )
                .mappings()
                .all()
            )
            if filters.supplier_id and not any(row["id"] == filters.supplier_id for row in suppliers):
                continue
            rows.append(
                {
                    "document": db.get(PurchaseRequest, item_id).document_no or str(item_id),
                    "status": item["status"],
                    "date": item["created_at"],
                    "reference": item["reference"],
                    "material": f"{line['sku']} · {line['material_name']}",
                    "quantity": line["quantity"],
                    "ordered": line["ordered_quantity"],
                    "remaining": line["remaining_quantity"],
                    "suppliers": "、".join(row["name"] for row in suppliers),
                }
            )
    return rows


def purchase_order_rows(db: Session, filters: ReportQuery) -> list[dict[str, str]]:
    rows = []
    for item_id in db.scalars(select(PurchaseOrder.id).select_from(PurchaseOrder).order_by(PurchaseOrder.id)):
        item = order_data(db, item_id)
        if not within_period(item["created_at"], filters) or (
            filters.supplier_id and item["supplier_id"] != filters.supplier_id
        ):
            continue
        for line in item["lines"]:
            if filters.material_id and line["material_id"] != filters.material_id:
                continue
            rows.append(
                {
                    "document": db.get(PurchaseOrder, item_id).document_no or str(item_id),
                    "request": (db.get(PurchaseRequest, item["purchase_request_id"]).document_no or str(item["purchase_request_id"])) if item["purchase_request_id"] else "",
                    "supplier": item["supplier_name"],
                    "status": item["status"],
                    "date": item["created_at"],
                    "material": f"{line['sku']} · {line['material_name']}",
                    "ordered": line["quantity"],
                    "received": line["received_quantity"],
                    "returned": line["returned_quantity"],
                    "remaining": line["remaining_quantity"],
                    "amount": line["line_total"],
                }
            )
    return rows


def receiving_return_rows(db: Session, filters: ReportQuery) -> list[dict[str, str]]:
    rows = []
    for item_id in db.scalars(
        select(PurchaseGoodsReceipt.id).select_from(PurchaseGoodsReceipt).order_by(PurchaseGoodsReceipt.id)
    ):
        item = goods_receipt_data(db, item_id)
        if (
            not within_period(item["created_at"], filters)
            or (filters.supplier_id and item["supplier_id"] != filters.supplier_id)
            or (filters.warehouse_id and item["warehouse_id"] != filters.warehouse_id)
        ):
            continue
        for line in item["lines"]:
            if filters.material_id and line["material_id"] != filters.material_id:
                continue
            rows.append(
                {
                    "type": "采购收货",
                    "document": db.get(PurchaseGoodsReceipt, item_id).document_no or str(item_id),
                    "source": db.get(PurchaseOrder, item["purchase_order_id"]).document_no or str(item["purchase_order_id"]),
                    "supplier": item["supplier_name"],
                    "warehouse": item["warehouse_name"],
                    "status": item["status"],
                    "date": item["created_at"],
                    "material": f"{line['sku']} · {line['material_name']}",
                    "quantity": line["accepted_quantity"],
                    "rejected": line["rejected_quantity"],
                    "reason": line["rejection_reason"],
                }
            )
    for item_id in db.scalars(select(Receipt.id).select_from(Receipt).order_by(Receipt.id)):
        item = receipt_data(db, item_id)
        if (
            not within_period(item["created_at"], filters)
            or (filters.supplier_id and item["supplier_id"] != filters.supplier_id)
            or (filters.warehouse_id and item["warehouse_id"] != filters.warehouse_id)
        ):
            continue
        for line in item["lines"]:
            if filters.material_id and line["material_id"] != filters.material_id:
                continue
            rows.append(
                {
                    "type": "采购入库",
                    "document": db.get(Receipt, item_id).document_no or str(item_id),
                    "source": (db.get(PurchaseGoodsReceipt, item["goods_receipt_id"]).document_no or str(item["goods_receipt_id"])) if item.get("goods_receipt_id") else "",
                    "supplier": item["supplier_name"],
                    "warehouse": item["warehouse_name"],
                    "status": "已冲销" if item["reversal_id"] else item["status"],
                    "date": item["created_at"],
                    "material": f"{line['sku']} · {line['material_name']}",
                    "quantity": line["quantity"],
                    "rejected": "0",
                    "reason": "",
                }
            )
    for item_id in db.scalars(
        select(PurchaseReturn.id).select_from(PurchaseReturn).order_by(PurchaseReturn.id)
    ):
        item = purchase_return_data(db, item_id)
        if (
            not within_period(item["created_at"], filters)
            or (filters.supplier_id and item["supplier_id"] != filters.supplier_id)
            or (filters.warehouse_id and item["warehouse_id"] != filters.warehouse_id)
        ):
            continue
        for line in item["lines"]:
            if filters.material_id and line["material_id"] != filters.material_id:
                continue
            rows.append(
                {
                    "type": "采购退货",
                    "document": db.get(PurchaseReturn, item_id).document_no or str(item_id),
                    "source": db.get(Receipt, item["receipt_id"]).document_no or str(item["receipt_id"]),
                    "supplier": item["supplier_name"],
                    "warehouse": item["warehouse_name"],
                    "status": "已冲销" if item["reversal_id"] else item["status"],
                    "date": item["created_at"],
                    "material": f"{line['sku']} · {line['material_name']}",
                    "quantity": line["quantity"],
                    "rejected": "0",
                    "reason": item["reason"],
                }
            )
    return rows


def balance_rows(db: Session, filters: ReportQuery) -> list[dict[str, str]]:
    totals: dict[tuple[int, int], Decimal] = {}
    movements = select(StockMovement.warehouse_id, StockMovement.material_id, StockMovement.quantity)
    if filters.to_date is not None:
        movements = movements.where(func.date(StockMovement.created_at) <= str(filters.to_date))
    for item in db.execute(movements).mappings():
        key = (item["warehouse_id"], item["material_id"])
        totals[key] = totals.get(key, Decimal(0)) + Decimal(item["quantity"])
    rows = []
    for warehouse in (
        db.execute(select(Warehouse.id, Warehouse.name).select_from(Warehouse).order_by(Warehouse.id))
        .mappings()
        .all()
    ):
        if filters.warehouse_id and warehouse["id"] != filters.warehouse_id:
            continue
        for material in (
            db.execute(
                select(Material.id, Material.sku, Material.name, Material.unit)
                .select_from(Material)
                .order_by(Material.sku)
            )
            .mappings()
            .all()
        ):
            if filters.material_id and material["id"] != filters.material_id:
                continue
            rows.append(
                {
                    "warehouse": warehouse["name"],
                    "material": f"{material['sku']} · {material['name']}",
                    "unit": material["unit"],
                    "quantity": str(totals.get((warehouse["id"], material["id"]), Decimal(0))),
                }
            )
    return rows


def flow_rows(filters: ReportQuery, user: dict) -> list[dict[str, str]]:
    ledger = query_ledger(
        LedgerQuery(
            warehouse_id=filters.warehouse_id,
            material_id=filters.material_id,
            from_date=filters.from_date,
            to_date=filters.to_date,
        ),
        user,
    )
    result = []
    for group in ledger["groups"]:
        # 台账明细已分页，收发存必须读取完整期间汇总，避免漏算其他页的流水。
        result.append(
            {
                "warehouse": group["warehouse_name"],
                "material": f"{group['sku']} · {group['material_name']}",
                "unit": group["unit"],
                "opening": group["opening_quantity"],
                "inbound": group['inbound_quantity'],
                "outbound": group['outbound_quantity'],
                "closing": group["closing_quantity"],
            }
        )
    return result


def csv_value(value: str) -> str:
    # 避免供应商名等文本被电子表格解释为公式；合法数字仍保留数字格式。
    stripped = value.lstrip()
    if stripped.startswith(("=", "@", "+")) or (
        stripped.startswith("-") and not stripped[1:].replace(".", "", 1).isdigit()
    ):
        return "'" + value
    return value


@router.post('/reports/inventory/query')
def query_inventory_report(filters: InventoryReportQuery, user: dict = Depends(current_user)) -> dict:
    if 'inventory_report.view' not in user['permissions']:
        raise HTTPException(403, '没有查看此报表的权限')
    if filters.from_date and filters.to_date and filters.to_date < filters.from_date:
        raise HTTPException(422, '结束日期不能早于开始日期')
    with orm_session() as db:
        # 余额报表保留全部仓库/物料组合（含零余额），收发存只列出有历史流水的组合。
        pairs = select(Warehouse.id.label('warehouse_id'), Warehouse.name.label('warehouse'),
            Material.id.label('material_id'), Material.sku, Material.name, Material.unit)
        if filters.kind == 'inventory_balance':
            pairs = pairs.select_from(Warehouse).join(Material, true())
        else:
            keys = select(StockMovement.warehouse_id, StockMovement.material_id)
            if filters.to_date is not None:
                keys = keys.where(func.date(StockMovement.created_at) <= str(filters.to_date))
            keys = keys.distinct().subquery()
            pairs = pairs.select_from(keys).join(Warehouse, Warehouse.id == keys.c.warehouse_id)
            pairs = pairs.join(Material, Material.id == keys.c.material_id)
        if filters.warehouse_id is not None:
            pairs = pairs.where(Warehouse.id == filters.warehouse_id)
        if filters.material_id is not None:
            pairs = pairs.where(Material.id == filters.material_id)
        total = db.scalar(select(func.count()).select_from(pairs.subquery())) or 0
        page = min(filters.page, max(1, (total + filters.page_size - 1) // filters.page_size))
        selected = db.execute(pairs.order_by(Warehouse.id, Material.sku, Material.id)
            .offset((page - 1) * filters.page_size).limit(filters.page_size)).mappings().all()
        totals = {(item['warehouse_id'], item['material_id']):
            {'opening': Decimal(0), 'inbound': Decimal(0), 'outbound': Decimal(0), 'closing': Decimal(0)}
            for item in selected}
        if totals:
            # 仅为当前页组合读取流水，仍按完整日期范围计算期初与期间收发，不能截断流水。
            movements = select(StockMovement.warehouse_id, StockMovement.material_id,
                StockMovement.quantity, StockMovement.created_at).where(
                    tuple_(StockMovement.warehouse_id, StockMovement.material_id).in_(list(totals)))
            if filters.to_date is not None:
                movements = movements.where(func.date(StockMovement.created_at) <= str(filters.to_date))
            for warehouse_id, material_id, quantity_text, created_at in db.execute(
                    movements.execution_options(yield_per=1000)):
                quantity = Decimal(quantity_text)
                values = totals[warehouse_id, material_id]
                values['closing'] += quantity
                if filters.from_date and created_at[:10] < str(filters.from_date):
                    values['opening'] += quantity
                else:
                    values['inbound'] += max(quantity, Decimal(0))
                    values['outbound'] += max(-quantity, Decimal(0))
        rows = []
        for item in selected:
            values = totals[item['warehouse_id'], item['material_id']]
            row = {'warehouse': item['warehouse'], 'material': f"{item['sku']} · {item['name']}", 'unit': item['unit']}
            if filters.kind == 'inventory_balance':
                row['quantity'] = str(values['closing'])
            else:
                row.update({key: str(value) for key, value in values.items()})
            rows.append(row)
        # 分页响应不携带全量 CSV；用户点击导出时再按同一筛选调用完整报表接口。
        return {'kind': filters.kind, 'columns': [{'key': key, 'title': title} for key, title in COLUMNS[filters.kind]],
                'rows': rows, 'total': total, 'page': page, 'page_size': filters.page_size}


@router.post("/reports/query")
def query_report(filters: ReportQuery, user: dict = Depends(current_user)) -> dict:
    if filters.from_date and filters.to_date and filters.to_date < filters.from_date:
        raise HTTPException(422, "结束日期不能早于开始日期")
    permission = (
        "inventory_report.view"
        if filters.kind in ("inventory_balance", "stock_flow")
        else "purchase_report.view"
    )
    if permission not in user["permissions"]:
        raise HTTPException(403, "没有查看此报表的权限")
    with orm_session() as db:
        if filters.kind == "purchase_requests":
            rows = purchase_request_rows(db, filters)
        elif filters.kind == "purchase_orders":
            rows = purchase_order_rows(db, filters)
        elif filters.kind == "receiving_returns":
            rows = receiving_return_rows(db, filters)
        elif filters.kind == "inventory_balance":
            rows = balance_rows(db, filters)
        else:
            rows = flow_rows(filters, user)
    columns = [{"key": key, "title": title} for key, title in COLUMNS[filters.kind]]
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([column["title"] for column in columns])
    for row in rows:
        writer.writerow([csv_value(row.get(column["key"], "")) for column in columns])
    # 列表和导出来自同一快照，前端保存当前响应中的 CSV 即可。
    return {"kind": filters.kind, "columns": columns, "rows": rows, "csv": "\ufeff" + output.getvalue()}
