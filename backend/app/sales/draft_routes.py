"""销售单据草稿修订入口；已执行单据、售后派生正文及审批锁保持原边界。"""

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.access.security import require
from app.core.document_responses import NumberedRoute
from app.core.models import CrmQuote, SalesDraftChange, SalesOrderLine, SalesReturnLine, ShipmentLine, User
from app.core.orm import orm_session
from app.inventory.warehouse import require_warehouse
from app.sales.customer_scope import require_visible_customer, require_visible_order, require_visible_return, require_visible_shipment
from app.sales.drafts import DraftRevisionInput, begin_revision, finish_revision
from app.sales.orders import (SalesOrderInput, ShipmentInput, checked_order_lines, sales_order_data,
                              shipment_data, validate_sales_order_input)
from app.sales.returns import SalesReturnInput, checked_return_lines, sales_return_data
from app.sales.after_sales_rules import ensure_return_available

router = APIRouter(route_class=NumberedRoute, prefix='/api/v1')


class SalesOrderRevisionInput(SalesOrderInput, DraftRevisionInput):
    pass


class ShipmentRevisionInput(ShipmentInput, DraftRevisionInput):
    pass


class SalesReturnRevisionInput(SalesReturnInput, DraftRevisionInput):
    pass


def replace_lines(db, model, foreign_key: str, identifier: int, identity_key: str, values: list[dict]) -> None:
    # 同一来源保留明细 ID；新增行先刷新再删除旧行，避免 SQLite 重用刚删除的最大 ID。
    remaining = {getattr(row, identity_key): row for row in db.scalars(
        select(model).where(getattr(model, foreign_key) == identifier))}
    for fields in values:
        row = remaining.pop(fields[identity_key], None)
        if row is None:
            db.add(model(**{foreign_key: identifier}, **fields))
        else:
            for key, value in fields.items():
                setattr(row, key, value)
    db.flush()
    for row in remaining.values():
        db.delete(row)
    db.flush()


@router.put('/sales-orders/{order_id}')
def revise_sales_order(order_id: int, payload: SalesOrderRevisionInput,
                       user: dict = Depends(require('sales_order.create'))) -> dict:
    with orm_session(write=True) as db:
        order = require_visible_order(db, order_id, user)
        version = begin_revision(db, 'SalesOrder', order, payload, user['id'])
        require_visible_customer(db, payload.customer_id, user)
        if order.customer_id != payload.customer_id and db.scalar(select(CrmQuote.id).where(
                CrmQuote.sales_order_id == order_id)):
            raise HTTPException(409, '报价转单须保留原客户，可在此补充保修条款及修订订单明细')
        validate_sales_order_input(db, payload)
        before = sales_order_data(db, order_id)
        order.customer_id, order.reference = payload.customer_id, payload.reference.strip()
        replace_lines(db, SalesOrderLine, 'sales_order_id', order_id, 'material_id', [
            {'material_id': line.material_id, 'quantity': str(line.quantity), 'unit_price': str(line.unit_price),
             'warranty_days': line.warranty_days, 'warranty_basis': line.warranty_basis} for line in payload.lines])
        finish_revision(db, 'SalesOrder', order_id, version, before, sales_order_data(db, order_id),
                        payload.revision_reason, user['id'])
        return sales_order_data(db, order_id)


@router.put('/shipments/{shipment_id}')
def revise_shipment(shipment_id: int, payload: ShipmentRevisionInput,
                     user: dict = Depends(require('shipment.create'))) -> dict:
    with orm_session(write=True) as db:
        shipment = require_visible_shipment(db, shipment_id, user)
        version = begin_revision(db, 'Shipment', shipment, payload, user['id'])
        require_visible_order(db, payload.sales_order_id, user)
        require_warehouse(db, payload.warehouse_id)
        if len({line.material_id for line in payload.lines}) != len(payload.lines):
            raise HTTPException(422, '一张出库单不能重复选择同一物料')
        sources = checked_order_lines(db, payload.sales_order_id,
                                     [(line.material_id, line.quantity) for line in payload.lines])
        before = shipment_data(db, shipment_id)
        shipment.sales_order_id, shipment.warehouse_id = payload.sales_order_id, payload.warehouse_id
        shipment.reference = payload.reference.strip()
        replace_lines(db, ShipmentLine, 'shipment_id', shipment_id, 'sales_order_line_id', [
            {'sales_order_line_id': sources[line.material_id], 'quantity': str(line.quantity)} for line in payload.lines])
        finish_revision(db, 'Shipment', shipment_id, version, before, shipment_data(db, shipment_id),
                        payload.revision_reason, user['id'])
        return shipment_data(db, shipment_id)


@router.put('/sales-returns/{return_id}')
def revise_sales_return(return_id: int, payload: SalesReturnRevisionInput,
                        user: dict = Depends(require('sales_return.create'))) -> dict:
    with orm_session(write=True) as db:
        document = require_visible_return(db, return_id, user)
        version = begin_revision(db, 'SalesReturn', document, payload, user['id'])
        require_visible_shipment(db, payload.shipment_id, user)
        require_warehouse(db, payload.warehouse_id)
        if len({line.shipment_line_id for line in payload.lines}) != len(payload.lines):
            raise HTTPException(422, '一张退货单不能重复选择同一出库明细')
        checked_return_lines(db, payload.shipment_id,
                             [(line.shipment_line_id, line.quantity) for line in payload.lines])
        values = [{'shipment_line_id': line.shipment_line_id, 'quantity': str(line.quantity)} for line in payload.lines]
        ensure_return_available(db, return_id, values)
        before = sales_return_data(db, return_id)
        document.shipment_id, document.warehouse_id, document.reason = payload.shipment_id, payload.warehouse_id, payload.reason
        replace_lines(db, SalesReturnLine, 'sales_return_id', return_id, 'shipment_line_id', values)
        finish_revision(db, 'SalesReturn', return_id, version, before, sales_return_data(db, return_id),
                        payload.revision_reason, user['id'])
        return sales_return_data(db, return_id)


@router.get('/sales-drafts/{document_type}/{document_id}/changes')
def draft_changes(document_type: Literal['SalesOrder', 'Shipment', 'SalesReturn'], document_id: int,
                  user: dict = Depends(require('sales.view'))) -> list[dict]:
    with orm_session() as db:
        # 历史与正文沿用同一客户可见范围，不能用历史入口绕过客户隔离。
        check = {'SalesOrder': require_visible_order, 'Shipment': require_visible_shipment,
                 'SalesReturn': require_visible_return}[document_type]
        check(db, document_id, user)
        return [{'id': row.id, 'version': row.version, 'reason': row.reason,
                 'changed_by_name': username, 'created_at': row.created_at,
                 'before': json.loads(row.before_json), 'after': json.loads(row.after_json)}
                for row, username in db.execute(select(SalesDraftChange, User.username)
                    .join(User, User.id == SalesDraftChange.changed_by).where(
                        SalesDraftChange.document_type == document_type,
                        SalesDraftChange.document_id == document_id).order_by(SalesDraftChange.version.desc()))]
