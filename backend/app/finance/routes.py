"""从已确认业务单据推导应收应付，保留每笔金额的原始单据来源。"""

from app.core.document_responses import NumberedRoute
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.orm import orm_session, model_data
from app.core.models import (User, Material, Customer, Supplier, SalesOrder, SalesOrderLine,
    Shipment, ShipmentLine, ShipmentReversal, SalesReturn, SalesReturnLine, SalesReturnReversal,
    PurchaseOrder, PurchaseOrderLine, Receipt, ReceiptLine, ReceiptOrderLink, ReceiptReversal,
    PurchaseReturn, PurchaseReturnLine, PurchaseReturnReversal, PaymentRecord, OrderSettlementTransfer)
from app.access.security import require
from app.finance.subledger_rules import check_subledger
from app.core import document_approval as approval
from app.core.approval_documents import payment_snapshot
from app.core.period_lock import ensure_date_unlocked
from datetime import datetime, timezone
from pydantic import ConfigDict
from app.access.security import current_user

router = APIRouter(route_class=NumberedRoute, prefix="/api/v1")


def money(value: Decimal) -> str:
    # 对外金额始终保留人民币分位，避免零余额和整数付款显示不同精度。
    return str(value.quantize(Decimal("0.01")))


class PaymentInput(BaseModel):
    kind: str
    order_id: int = Field(gt=0)
    action: str
    amount: Decimal
    reference: str = Field(min_length=1, max_length=100)
    note: str = Field(default="", max_length=200)

    @field_validator("kind")
    @classmethod
    def valid_kind(cls, value: str) -> str:
        if value not in ("receivable", "payable"):
            raise ValueError("往来类别无效")
        return value

    @field_validator("action")
    @classmethod
    def valid_action(cls, value: str) -> str:
        if value not in ("settlement", "refund"):
            raise ValueError("收付款类型无效")
        return value

    @field_validator("amount")
    @classmethod
    def valid_amount(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 0 or value > 1_000_000_000_000 or value.as_tuple().exponent < -2:
            raise ValueError("金额须大于零、最多两位小数且不超过一万亿元")
        return value

    @field_validator("reference")
    @classmethod
    def trim_reference(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("收付款参考号不能为空")
        return value.strip()


class ReversalInput(BaseModel):
    reason: str = Field(min_length=1, max_length=200)

    @field_validator("reason")
    @classmethod
    def trim_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("冲销原因不能为空")
        return value.strip()


def amount(quantity: str, unit_price: str | None, sign: int) -> str | None:
    if unit_price is None:
        # 未关联采购订单的历史入库没有单价，不能把应付金额猜成零。
        return None
    value = (Decimal(quantity) * Decimal(unit_price)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return str(value * sign if value else value)


def entry(row: dict, kind: str, source_type: str, sign: int) -> dict:
    return {
        "key": f"{source_type}:{row['source_line_id']}",
        "kind": kind,
        "party_id": row["party_id"],
        "party_name": row["party_name"],
        "source_type": source_type,
        "source_id": row["source_id"],
        "source_line_id": row["source_line_id"],
        "order_id": row["order_id"],
        "material_id": row["material_id"],
        "sku": row["sku"],
        "quantity": row["quantity"],
        "unit_price": row["unit_price"],
        "amount": amount(row["quantity"], row["unit_price"], sign),
        "currency": "CNY",
        "posted_by": row["posted_by"],
        "posted_at": row["posted_at"],
    }


def sales_sources(db: Session, *, returned: bool, reversed: bool) -> list[dict]:
    line = SalesReturnLine if returned else ShipmentLine
    document = SalesReturn if returned else Shipment
    reversal = SalesReturnReversal if returned else ShipmentReversal
    source = reversal if reversed else document
    stmt = select(line.id.label('source_line_id'), source.id.label('source_id'),
        SalesOrder.id.label('order_id'), Customer.id.label('party_id'), Customer.name.label('party_name'),
        SalesOrderLine.material_id, Material.sku, line.quantity, SalesOrderLine.unit_price,
        (source.created_by if reversed else source.posted_by).label('posted_by'),
        (source.created_at if reversed else source.posted_at).label('posted_at')).select_from(line)
    if returned:
        stmt = stmt.join(SalesReturn, SalesReturn.id == SalesReturnLine.sales_return_id)
        stmt = stmt.join(ShipmentLine, ShipmentLine.id == SalesReturnLine.shipment_line_id)
    else:
        stmt = stmt.join(Shipment, Shipment.id == ShipmentLine.shipment_id)
    stmt = stmt.join(SalesOrderLine, SalesOrderLine.id == ShipmentLine.sales_order_line_id)
    stmt = stmt.join(SalesOrder, SalesOrder.id == SalesOrderLine.sales_order_id)
    stmt = stmt.join(Customer, Customer.id == SalesOrder.customer_id)
    stmt = stmt.join(Material, Material.id == SalesOrderLine.material_id)
    if reversed:
        key = SalesReturnReversal.sales_return_id if returned else ShipmentReversal.shipment_id
        stmt = stmt.join(reversal, key == document.id)
    else:
        stmt = stmt.where(document.status == 'posted')
    return [dict(row) for row in db.execute(stmt).mappings()]


def purchase_sources(db: Session, *, returned: bool, reversed: bool) -> list[dict]:
    line = PurchaseReturnLine if returned else ReceiptLine
    document = PurchaseReturn if returned else Receipt
    reversal = PurchaseReturnReversal if returned else ReceiptReversal
    source = reversal if reversed else document
    stmt = select(line.id.label('source_line_id'), source.id.label('source_id'),
        PurchaseOrderLine.purchase_order_id.label('order_id'), Supplier.id.label('party_id'),
        Supplier.name.label('party_name'), ReceiptLine.material_id, Material.sku, line.quantity,
        PurchaseOrderLine.unit_price, (source.created_by if reversed else source.posted_by).label('posted_by'),
        (source.created_at if reversed else source.posted_at).label('posted_at')).select_from(line)
    if returned:
        stmt = stmt.join(PurchaseReturn, PurchaseReturn.id == PurchaseReturnLine.purchase_return_id)
        stmt = stmt.join(ReceiptLine, ReceiptLine.id == PurchaseReturnLine.receipt_line_id)
    stmt = stmt.join(Receipt, Receipt.id == ReceiptLine.receipt_id)
    stmt = stmt.join(Supplier, Supplier.id == Receipt.supplier_id)
    stmt = stmt.join(Material, Material.id == ReceiptLine.material_id)
    # 历史自由入库没有采购价格，保留左连接让金额明确显示未知。
    stmt = stmt.outerjoin(ReceiptOrderLink, ReceiptOrderLink.receipt_line_id == ReceiptLine.id)
    stmt = stmt.outerjoin(PurchaseOrderLine, PurchaseOrderLine.id == ReceiptOrderLink.purchase_order_line_id)
    if reversed:
        key = PurchaseReturnReversal.purchase_return_id if returned else ReceiptReversal.receipt_id
        stmt = stmt.join(reversal, key == document.id)
    else:
        stmt = stmt.where(document.status == 'posted')
    return [dict(row) for row in db.execute(stmt).mappings()]


def financial_entries(db: Session) -> list[dict]:
    # 原单据和冲销分别保留；旧数据与缺价来源也通过模型关联追溯。
    result = []
    for returned in (False, True):
        for reversed in (False, True):
            sign = (-1 if returned else 1) * (-1 if reversed else 1)
            sales_type = 'sales_return' if returned else 'shipment'
            purchase_type = 'purchase_return' if returned else 'receipt'
            if reversed:
                sales_type += '_reversal'
                purchase_type += '_reversal'
            result.extend(entry(row, 'receivable', sales_type, sign)
                for row in sales_sources(db, returned=returned, reversed=reversed))
            result.extend(entry(row, 'payable', purchase_type, sign)
                for row in purchase_sources(db, returned=returned, reversed=reversed))
    from app.sales.after_sales_rules import repair_financial_entries
    result.extend(repair_financial_entries(db))
    users = dict(db.execute(select(User.id, User.username)).all())
    for item in result:
        item['posted_by_name'] = users.get(item['posted_by'])
    return sorted(result, key=lambda item: (item['posted_at'], item['source_type'], item['source_line_id']), reverse=True)


def report_data(entries: list[dict]) -> dict:
    totals = {"receivable": Decimal(0), "payable": Decimal(0)}
    unpriced = 0
    for item in entries:
        if item["amount"] is None:
            unpriced += 1
        else:
            totals[item["kind"]] += Decimal(item["amount"])
    # 此清单只汇总业务净额；收付款与未结金额由订单核对接口单独展示。
    return {"currency": "CNY", "receivable_amount": money(totals["receivable"]),
            "payable_amount": money(totals["payable"]), "unpriced_count": unpriced,
            "entries": entries}


@router.get("/finance/receivables-payables")
def list_receivables_payables(_: dict = Depends(require("finance.view"))) -> dict:
    with orm_session() as db:
        return report_data(financial_entries(db))


def party_data(db: Session, kind: str, order_id: int) -> dict:
    if kind == 'receivable':
        stmt = select(Customer.id.label('party_id'), Customer.name.label('party_name'))
        stmt = stmt.join(SalesOrder, SalesOrder.customer_id == Customer.id).where(SalesOrder.id == order_id)
    else:
        stmt = select(Supplier.id.label('party_id'), Supplier.name.label('party_name'))
        stmt = stmt.join(PurchaseOrder, PurchaseOrder.supplier_id == Supplier.id).where(PurchaseOrder.id == order_id)
    row = db.execute(stmt).mappings().first()
    if row is None:
        raise HTTPException(422, '往来订单不存在')
    return dict(row)


def account_data(db: Session, kind: str, order_id: int,
                 entries: list[dict] | None = None) -> dict:
    row = party_data(db, kind, order_id)
    source = [item for item in (entries if entries is not None else financial_entries(db))
              if item["kind"] == kind and item["order_id"] == order_id and item["amount"] is not None]
    billed = sum((Decimal(item["amount"]) for item in source), Decimal(0))
    settled = sum((Decimal(value) for value in db.scalars(select(PaymentRecord.amount)
        .where(PaymentRecord.kind == kind, PaymentRecord.order_id == order_id, PaymentRecord.status == 'executed'))), Decimal(0))
    credit_used = sum((Decimal(value) for value in db.scalars(select(OrderSettlementTransfer.amount)
        .where(OrderSettlementTransfer.kind == kind, OrderSettlementTransfer.from_order_id == order_id))), Decimal(0))
    debt_covered = sum((Decimal(value) for value in db.scalars(select(OrderSettlementTransfer.amount)
        .where(OrderSettlementTransfer.kind == kind, OrderSettlementTransfer.to_order_id == order_id))), Decimal(0))
    return {"kind": kind, "order_id": order_id, **dict(row), "currency": "CNY",
            "business_amount": money(billed), "settled_amount": money(settled),
            "credit_used_amount": money(credit_used), "debt_covered_amount": money(debt_covered),
            "outstanding_amount": money(billed - settled + credit_used - debt_covered),
            "source_keys": [item["key"] for item in source]}


@router.get("/finance/accounts")
def list_finance_accounts(_: dict = Depends(require("finance.view"))) -> list[dict]:
    with orm_session() as db:
        entries = financial_entries(db)
        keys = {(item["kind"], item["order_id"]) for item in entries if item["order_id"] is not None}
        return [account_data(db, kind, order_id, entries) for kind, order_id in sorted(keys)]


def payment_data(db: Session, payment_id: int) -> dict:
    record = db.get(PaymentRecord, payment_id)
    if record is None:
        raise HTTPException(404, '收付款记录不存在')
    return {**model_data(record), 'created_by_name': db.get(User, record.created_by).username,
            'approval': approval.case_data(approval.find_case(db, 'PaymentRecord', record.id)),
            **party_data(db, record.kind, record.order_id), 'currency': 'CNY'}


def transfer_data(db: Session, transfer_id: int) -> dict:
    record = db.get(OrderSettlementTransfer, transfer_id)
    if record is None:
        raise HTTPException(404, '订单核销记录不存在')
    party = party_data(db, record.kind, record.from_order_id)
    return {**model_data(record), 'created_by_name': db.get(User, record.created_by).username,
            'party_name': party['party_name'], 'currency': 'CNY'}


@router.get("/finance/payment-records")
def list_payment_records(_: dict = Depends(require("finance.view"))) -> list[dict]:
    with orm_session() as db:
        ids = list(db.scalars(select(PaymentRecord.id).order_by(PaymentRecord.id.desc())))
        return [payment_data(db, payment_id) for payment_id in ids]


@router.get("/finance/overview")
def finance_overview(_: dict = Depends(require("finance.view"))) -> dict:
    with orm_session() as db:
        # 一个读取事务提供同一时刻的单据、订单余额和收付款快照。
        entries = financial_entries(db)
        keys = {(item["kind"], item["order_id"]) for item in entries if item["order_id"] is not None}
        accounts = [account_data(db, kind, order_id, entries) for kind, order_id in sorted(keys)]
        ids = list(db.scalars(select(PaymentRecord.id).order_by(PaymentRecord.id.desc())))
        transfer_ids = list(db.scalars(select(OrderSettlementTransfer.id).order_by(OrderSettlementTransfer.id.desc())))
        return {"report": report_data(entries), "accounts": accounts,
                "payments": [payment_data(db, payment_id) for payment_id in ids],
                "transfers": [transfer_data(db, transfer_id) for transfer_id in transfer_ids]}


@router.post("/finance/payment-records", status_code=201)
def create_payment_record(payload: PaymentInput, user: dict = Depends(require("finance.record"))) -> dict:
    with orm_session(write=True) as db:
        check_subledger(db)
        # 写锁覆盖余额核对和新增记录，防止并行收付款超额。
        account = account_data(db, payload.kind, payload.order_id)
        if not account['source_keys']:
            raise HTTPException(409, '订单尚无已确认且已定价的业务单据')
        outstanding = Decimal(account['outstanding_amount'])
        if payload.action == 'settlement' and payload.amount > outstanding:
            raise HTTPException(409, '收付款金额超过订单未结金额')
        if payload.action == 'refund' and payload.amount > -outstanding:
            raise HTTPException(409, '退款金额超过订单贷方余额')
        signed = payload.amount if payload.action == 'settlement' else -payload.amount
        record = PaymentRecord(status='draft', kind=payload.kind, order_id=payload.order_id, action=payload.action,
            amount=money(signed), reference=payload.reference, note=payload.note.strip(), created_by=user['id'])
        validate_payment(db, record)
        try:
            db.add(record)
            db.flush()
        except IntegrityError:
            raise HTTPException(409, '此订单的收付款参考号已使用') from None
        return payment_data(db, record.id)


@router.post("/finance/payment-records/{payment_id}/reverse", status_code=201)
def reverse_payment_record(payment_id: int, payload: ReversalInput,
                           user: dict = Depends(require("finance.reverse"))) -> dict:
    with orm_session(write=True) as db:
        check_subledger(db)
        original = db.get(PaymentRecord, payment_id)
        if original is None:
            raise HTTPException(404, '收付款记录不存在')
        if original.action == 'reversal' or original.status != 'executed':
            raise HTTPException(409, '冲销记录不能再次冲销')
        if db.scalar(select(PaymentRecord.id).where(PaymentRecord.reverses_id == payment_id,
                PaymentRecord.status != 'cancelled').limit(1)) is not None:
            raise HTTPException(409, '此收付款记录已冲销')
        # 反向记录保留原编号、操作者与原因，不改写或删除历史金额。
        record = PaymentRecord(status='draft', kind=original.kind, order_id=original.order_id, action='reversal',
            amount=money(-Decimal(original.amount)), reference=f'冲销 #{payment_id}',
            note=payload.reason, reverses_id=payment_id, created_by=user['id'])
        validate_payment(db, record)
        db.add(record)
        db.flush()
        return payment_data(db, record.id)


def validate_payment(db: Session, record: PaymentRecord) -> None:
    """审批不预占余额，真正执行在原写锁内重新核对方向、限额及原资金。"""
    today = datetime.now(timezone.utc).date().isoformat()
    check_subledger(db, today)
    ensure_date_unlocked(db, today)
    account = account_data(db, record.kind, record.order_id)
    if not account['source_keys']:
        raise HTTPException(409, '订单尚无已确认且已定价的业务单据')
    amount = Decimal(record.amount)
    if record.reverses_id is not None:
        original = db.get(PaymentRecord, record.reverses_id)
        if original is None or original.status != 'executed' or original.action == 'reversal':
            raise HTTPException(409, '原资金尚未执行或本身是冲销')
        if (original.kind, original.order_id, -Decimal(original.amount)) != (record.kind, record.order_id, amount):
            raise HTTPException(409, '反向资金与原记录不一致')
        ensure_date_unlocked(db, original.executed_at or original.created_at)
        if db.scalar(select(PaymentRecord.id).where(PaymentRecord.reverses_id == original.id,
                PaymentRecord.status != 'cancelled', PaymentRecord.id != record.id).limit(1)) is not None:
            raise HTTPException(409, '原资金已有有效冲销草稿或记录')
    else:
        outstanding = Decimal(account['outstanding_amount'])
        limit = outstanding if record.action == 'settlement' else -outstanding
        if abs(amount) > limit:
            raise HTTPException(409, '收付款金额超过订单最新未结金额或贷方余额')


class PaymentExecutionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: int = Field(gt=0, strict=True)
    reason: str = Field(min_length=1, max_length=200)

    @field_validator('reason')
    @classmethod
    def required_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('资金执行或取消依据不能为空')
        return value.strip()


@router.post('/finance/payment-records/{payment_id}/{action}')
def execute_payment_record(payment_id: int, action: str, payload: PaymentExecutionInput,
                           user: dict = Depends(current_user)) -> dict:
    if action not in ('post', 'cancel'):
        raise HTTPException(404, '资金操作不存在')
    with orm_session(write=True) as db:
        record = db.get(PaymentRecord, payment_id)
        if record is None:
            raise HTTPException(404, '收付款记录不存在')
        permission = 'finance.reverse' if record.reverses_id is not None else 'finance.record'
        approval.actor(db, user['id'], permission)
        if record.version != payload.version or record.status != 'draft':
            raise HTTPException(409, '资金记录已变化或已处理，请重新读取')
        case = approval.find_case(db, 'PaymentRecord', payment_id)
        if action == 'cancel':
            if case and case.status in ('submitted', 'approved'):
                raise HTTPException(409, '请先撤回资金审批，再取消草稿')
            record.status = 'cancelled'
            record.cancelled_by, record.cancelled_at = user['id'], approval.now(db)
            record.cancellation_reason = payload.reason
        else:
            case = approval.require_approved(db, 'PaymentRecord', payment_id,
                payment_snapshot(db, payment_id), user['id'], permission=permission)
            validate_payment(db, record)
            record.status = 'executed'
            record.executed_by, record.executed_at = user['id'], approval.now(db)
            ensure_date_unlocked(db, record.executed_at)
            approval.mark_executed(db, case, user['id'], permission=permission, reason=payload.reason)
        record.version += 1
        db.flush()
        return payment_data(db, payment_id)
