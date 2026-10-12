"""跨历史与订单核销的已执行事实、双边余额及读取快照。"""

import json
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import document_approval as approval
from app.core.models import (Customer, PurchaseOrder, SalesOrder, SubledgerOpeningLine,
    SubledgerOrderSettlement, Supplier, User)
from app.core.orm import model_data

ZERO = Decimal(0)


def order_id(record: SubledgerOrderSettlement) -> int:
    identifier = record.sales_order_id if record.kind == 'receivable' else record.purchase_order_id
    if identifier is None:
        raise HTTPException(409, '核销订单归属不完整')
    return identifier


def executed(db: Session, to_date: str | None = None):
    statement = select(SubledgerOrderSettlement).where(SubledgerOrderSettlement.status == 'executed')
    if to_date:
        statement = statement.where(SubledgerOrderSettlement.executed_at < to_date + ' 24:00:00')
    return statement


def record_data(db: Session, record: SubledgerOrderSettlement) -> dict:
    line = db.get(SubledgerOpeningLine, record.opening_line_id)
    identifier = line.customer_id or line.supplier_id
    party = db.get(Customer if record.kind == 'receivable' else Supplier, identifier)
    order = db.get(SalesOrder if record.kind == 'receivable' else PurchaseOrder, order_id(record))
    return dict(**model_data(record), order_id=order_id(record), currency='CNY',
        opening_id=line.opening_id, party_id=identifier, party_name=party.name,
        document_reference=line.document_reference, account_code=line.account_code, account_name=line.account_name,
        auxiliary=json.loads(record.auxiliary_json), order_evidence=json.loads(record.order_evidence_json),
        order_document_no=order.document_no, created_by_name=db.get(User, record.created_by).username,
        approval=approval.case_data(approval.find_case(db, 'SubledgerOrderSettlement', record.id)))


def line_offset(db: Session, line_id: int, to_date: str | None = None) -> Decimal:
    return sum((Decimal(row.amount) * (-1 if row.direction == 'historical_credit' else 1)
        for row in db.scalars(executed(db, to_date).where(SubledgerOrderSettlement.opening_line_id == line_id))), ZERO)


def order_offsets(db: Session, kind: str, identifier: int, to_date: str | None = None) -> tuple[Decimal, Decimal]:
    column = SubledgerOrderSettlement.sales_order_id if kind == 'receivable' else SubledgerOrderSettlement.purchase_order_id
    rows = list(db.scalars(executed(db, to_date).where(SubledgerOrderSettlement.kind == kind, column == identifier)))
    return (sum((Decimal(row.amount) for row in rows if row.direction == 'order_credit'), ZERO),
            sum((Decimal(row.amount) for row in rows if row.direction == 'historical_credit'), ZERO))


def active_records(db: Session, to_date: str | None = None) -> list[SubledgerOrderSettlement]:
    reversals = set(db.scalars(executed(db, to_date).with_only_columns(SubledgerOrderSettlement.reverses_id)
        .where(SubledgerOrderSettlement.reverses_id.is_not(None))))
    return [row for row in db.scalars(executed(db, to_date).where(SubledgerOrderSettlement.reverses_id.is_(None)))
        if row.id not in reversals]
