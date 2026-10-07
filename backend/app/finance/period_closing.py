"""期间结账、倒序重开及不可覆盖的结账证据快照。"""

from app.core.document_responses import NumberedRoute
import json
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.access.security import require
from app.core.models import ProductionCostSettlement
from app.core.models import AccountingPeriod, Journal, JournalLine, PaymentRecord, OrderSettlementTransfer, PeriodClosing, User
from app.core.orm import add_model, model_data, orm_session
from app.finance.journals import VersionInput
from app.finance.ledger import audit, get_record, snapshot
from app.finance.ledger_reports import LedgerReportQuery, trial_balance, confirmed_opening_lines
from app.finance.auxiliary_rules import snapshot_values, selection_options
from app.finance.opening_rules import active_opening, check_journal_opening
from app.finance.routes import financial_entries, report_data
from app.inventory.valuation import calculate_valuation
from app.sales.after_sales_rules import archive_cases

router = APIRouter(route_class=NumberedRoute, prefix='/api/v1/finance/accounting-periods')


def utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def precheck(db: Session, period: AccountingPeriod) -> dict:
    blockers, warnings = [], []

    def block(code: str, message: str, ids: list[int] | None = None):
        blockers.append(dict(code=code, message=message, ids=ids or []))

    if period.status != 'open':
        block('already_closed', '期间已结账，不能重复结账')
    if period.end_date >= utc_today():
        block('not_ended', '只能结已结束的期间；业务时间按服务端 UTC 日期归属')
    earlier = list(db.scalars(select(AccountingPeriod.id).where(
        AccountingPeriod.end_date < period.start_date, AccountingPeriod.status != 'closed')))
    if earlier:
        block('earlier_open', '须先按时间顺序结账更早的期间', earlier)
    pending = list(db.scalars(select(Journal.id).where(Journal.journal_date <= period.end_date,
        Journal.status.not_in(('posted', 'cancelled'))).order_by(Journal.id)))
    if pending:
        block('pending_journals', '须先过账或取消截至期末的全部未处理凭证', pending)
    from app.finance.business_journals import pending_sources
    missing = pending_sources(db, period.end_date)
    if missing:
        block('pending_business_sources', '业务凭证纳管范围内尚有未过账来源：' + '、'.join(missing))
    from app.finance.profit_transfers import closing_evidence
    transfer = closing_evidence(db, period)
    if transfer['required'] and transfer['residuals']:
        block('profit_transfer_pending', '损益科目尚有期末余额，须先核对并过账损益结转',
            [item['account_id'] for item in transfer['residuals']])
    try:
        check_journal_opening(db, period.end_date)
    except HTTPException as exc:
        block('opening_pending', str(exc.detail))
    opening = active_opening(db)
    if opening is None:
        warnings.append('没有正式期初来源，凭证累计以零为起点；结账不证明业务期初已核对')
    rows, totals = trial_balance(db, LedgerReportQuery(kind='trial_balance',
        from_date=period.start_date, to_date=period.end_date))
    if not totals['balanced']:
        block('unbalanced', '期初、本期或期末借贷不平衡，请核对凭证与期初')
    valuation = calculate_valuation(db, through_date=period.end_date).report
    unknown = [item['id'] for item in valuation['movements'] if item['amount'] is None]
    if unknown:
        block('unpriced_inventory', '截至期末存在未知库存金额，须先核价并核对成本来源', unknown)
    negative = [item['id'] for item in valuation['materials'] if Decimal(item['quantity']) < 0]
    if negative:
        block('negative_inventory', '截至期末库存数量为负，请核对库存流水', negative)
    entries = [item for item in financial_entries(db) if item['posted_at'][:10] <= period.end_date]
    business = report_data(entries)
    from app.core.models import QualityDisposition, QualityCostAllocation, ProductionSettlementReversal
    quality_records = list(db.scalars(select(QualityDisposition).where(QualityDisposition.status == 'posted',
        QualityDisposition.posted_at < period.end_date + ' 24:00:00').order_by(QualityDisposition.id)))
    unallocated_quality = [record.id for record in quality_records if db.scalar(select(QualityCostAllocation.settlement_id).join(ProductionCostSettlement,ProductionCostSettlement.id==QualityCostAllocation.settlement_id).where(ProductionCostSettlement.status=='active',
        QualityCostAllocation.disposition_id == record.id, ~select(ProductionSettlementReversal.id).where(
            ProductionSettlementReversal.settlement_id == QualityCostAllocation.settlement_id).exists())) is None]
    if unallocated_quality:
        block('unsettled_quality', '已确认不合格品处置尚未固定原工单成本，须先核对并结算', unallocated_quality)
    if business['unpriced_count']:
        warnings.append('应收应付有历史无价来源；库存核价不能替代往来单价或业务对账')
    warnings.append('结账固定现有总账和业务证据；业务及损益结转草稿须单独生成、审核和过账，不自动生成法定财务报表')
    auxiliary_lines, unassigned_count = [], 0
    for line, journal in db.execute(select(JournalLine, Journal).join(Journal, Journal.id == JournalLine.journal_id)
            .where(Journal.status == 'posted', Journal.journal_date <= period.end_date)
            .order_by(Journal.id, JournalLine.position)):
        values = snapshot_values(db, line)
        unassigned_count += int(not values)
        auxiliary_lines.append(dict(journal_id=journal.id, line_id=line.id, account_id=line.account_id,
            auxiliary=values, debit=line.debit, credit=line.credit))
    auxiliary_opening = []
    for line in confirmed_opening_lines(db):
        values = snapshot_values(db, line)
        unassigned_count += int(not values)
        auxiliary_opening.append(dict(opening_balance_id=line.opening_balance_id, line_id=line.id,
            account_id=line.account_id, auxiliary=values, debit=line.debit, credit=line.credit))
    from app.finance.subledger_rules import active_subledger
    from app.finance.subledger_openings import snapshot as subledger_snapshot, balance as subledger_balance, lines_for as subledger_lines
    subledger = active_subledger(db)
    subledger_evidence = None if subledger is None else dict(opening=subledger_snapshot(db, subledger),
        rows=[subledger_balance(db, line, period.end_date) for line in subledger_lines(db, subledger.id)])
    evidence = dict(period=snapshot(period), currency='CNY', time_basis='UTC',
        subledger=subledger_evidence,
        after_sales=archive_cases(db, period.end_date, valuation),
        quality=[dict(disposition=model_data(record), allocations=[model_data(value) for value in db.scalars(
            select(QualityCostAllocation).join(ProductionCostSettlement, ProductionCostSettlement.id == QualityCostAllocation.settlement_id).where(ProductionCostSettlement.status == 'active',QualityCostAllocation.disposition_id == record.id))]) for record in quality_records],
        auxiliary=dict(lines=auxiliary_lines, opening=auxiliary_opening, unassigned_count=unassigned_count,
            policies=selection_options(db)['auxiliary_policies']),
        opening_balance_id=opening.id if opening and opening.status == 'confirmed' else None,
        profit_transfer=transfer,
        ledger=dict(rows=rows, totals=totals), inventory=valuation, business_sources=business,
        payments=[model_data(item) for item in db.scalars(select(PaymentRecord).where(
            PaymentRecord.status == 'executed', func.coalesce(PaymentRecord.executed_at, PaymentRecord.created_at) < period.end_date + ' 24:00:00').order_by(PaymentRecord.id))],
        order_settlements=[model_data(item) for item in db.scalars(select(OrderSettlementTransfer).where(
            OrderSettlementTransfer.status == 'executed', func.coalesce(OrderSettlementTransfer.executed_at, OrderSettlementTransfer.created_at) < period.end_date + ' 24:00:00').order_by(OrderSettlementTransfer.id))],
        posted_journal_ids=list(db.scalars(select(Journal.id).where(
            Journal.journal_date <= period.end_date, Journal.status == 'posted').order_by(Journal.id))))
    return dict(period=snapshot(period), can_close=not blockers, blockers=blockers,
        warnings=warnings, ledger_totals=totals, inventory_total=valuation['total_amount'],
        movement_count=len(valuation['movements']), business_unpriced_count=business['unpriced_count'],
        evidence=evidence)


def public_check(result: dict) -> dict:
    # 检查面板只读摘要；完整快照须有查看期间权限，不经客户端回传作为结账依据。
    return {key: value for key, value in result.items() if key != 'evidence'}


@router.get('/{period_id}/closing-check')
def closing_check(period_id: int = Path(gt=0),
                  _: dict = Depends(require('accounting_period.closing_view'))) -> dict:
    with orm_session() as db:
        return public_check(precheck(db, get_record(db, AccountingPeriod, period_id)))


@router.get('/{period_id}/closings')
def closing_history(period_id: int = Path(gt=0),
                    user: dict = Depends(require('accounting_period.closing_view'))) -> list[dict]:
    with orm_session() as db:
        get_record(db, AccountingPeriod, period_id)
        result = []
        for item, username in db.execute(select(PeriodClosing, User.username)
                .join(User, User.id == PeriodClosing.created_by)
                .where(PeriodClosing.period_id == period_id).order_by(PeriodClosing.id.desc())):
            evidence = json.loads(item.snapshot_json)
            if 'after_sales.cost' not in user['permissions']:
                # 结账查看权限可独立分配，不能借固定归档绕过售后内部成本授权。
                for case in evidence.get('after_sales', []):
                    case.pop('labor_cost', None)
                    case.pop('repair_margin', None)
            result.append(dict(id=item.id, period_id=item.period_id, period_version=item.period_version,
                action=item.action, evidence=evidence, reason=item.reason,
                created_by=item.created_by, created_by_name=username, created_at=item.created_at))
        return result


@router.post('/{period_id}/close')
def close_period(data: VersionInput, period_id: int = Path(gt=0),
                 user: dict = Depends(require('accounting_period.close'))) -> dict:
    with orm_session(write=True) as db:
        record = get_record(db, AccountingPeriod, period_id, data.version)
        result = precheck(db, record)
        if not result['can_close']:
            raise HTTPException(409, '；'.join(item['message'] for item in result['blockers']))
        before = snapshot(record)
        record.status, record.version = 'closed', record.version + 1
        db.flush()
        closing = add_model(db, PeriodClosing(period_id=record.id, period_version=record.version,
            action='close', snapshot_json=json.dumps(result['evidence'], ensure_ascii=False),
            reason=data.reason, created_by=user['id']))
        audit(db, record, before, data.reason, user['id'])
        return dict(period=snapshot(record), closing_id=closing.id)


@router.post('/{period_id}/reopen')
def reopen_period(data: VersionInput, period_id: int = Path(gt=0),
                  user: dict = Depends(require('accounting_period.reopen'))) -> dict:
    with orm_session(write=True) as db:
        record = get_record(db, AccountingPeriod, period_id, data.version)
        if record.status != 'closed':
            raise HTTPException(409, '仅已结期间可以重开')
        later = db.scalar(select(AccountingPeriod.id).where(AccountingPeriod.status == 'closed',
            AccountingPeriod.start_date > record.end_date).limit(1))
        if later is not None:
            raise HTTPException(409, '须先按倒序重开更晚的已结期间')
        before = snapshot(record)
        last_close = db.scalar(select(PeriodClosing).where(PeriodClosing.period_id == record.id,
            PeriodClosing.action == 'close').order_by(PeriodClosing.id.desc()).limit(1))
        if last_close is None:
            raise HTTPException(409, '期间缺少结账证据，不能重开；请检查数据库完整性')
        record.status, record.version = 'open', record.version + 1
        db.flush()
        closing = add_model(db, PeriodClosing(period_id=record.id, period_version=record.version,
            action='reopen', snapshot_json=json.dumps(dict(previous_closing_id=last_close.id,
                period=before), ensure_ascii=False), reason=data.reason, created_by=user['id']))
        audit(db, record, before, data.reason, user['id'])
        return dict(period=snapshot(record), closing_id=closing.id)
