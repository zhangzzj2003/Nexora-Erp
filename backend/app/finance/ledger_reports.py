"""已过账总账查询；列表、合计与导出保持同一读取快照。"""

import csv
from datetime import datetime, timezone
from decimal import Decimal
from io import StringIO
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access.security import require
from app.core.models import AccountingPeriod, Journal, JournalLine, LedgerAccount, ProfitTransfer
from app.core.orm import orm_session
from app.finance.ledger import PeriodInput, snapshot
from app.reports.routes import csv_value
from app.finance.opening_rules import active_opening
from app.finance.opening_balances import (
    lines_for as opening_lines,
    view as opening_view,
    history as opening_history,
)

router = APIRouter(prefix="/api/v1/finance/ledger-reports")
ZERO = Decimal(0)
BALANCE_KEYS = (
    "opening_debit",
    "opening_credit",
    "debit",
    "credit",
    "closing_debit",
    "closing_credit",
)


class LedgerReportQuery(BaseModel):
    paged: bool = False
    model_config = ConfigDict(extra="forbid")
    kind: Literal["trial_balance", "account_ledger"]
    from_date: str
    to_date: str
    account_id: int | None = Field(default=None, strict=True, gt=0)

    @field_validator("from_date", "to_date")
    @classmethod
    def valid_date(cls, value: str) -> str:
        return PeriodInput.valid_date(value)

    @model_validator(mode="after")
    def valid_scope(self):
        if self.to_date < self.from_date:
            raise ValueError("结束日期不能早于开始日期")
        if self.kind == "account_ledger" and self.account_id is None:
            raise ValueError("科目明细须选择一个科目")
        if self.kind == "trial_balance" and self.account_id is not None:
            raise ValueError("试算平衡须查询全部科目")
        return self


COLUMNS = {
    "trial_balance": [
        ("code", "科目编码"),
        ("name", "科目名称"),
        ("opening_debit", "期初借方（元）"),
        ("opening_credit", "期初贷方（元）"),
        ("debit", "本期借方（元）"),
        ("credit", "本期贷方（元）"),
        ("closing_debit", "期末借方（元）"),
        ("closing_credit", "期末贷方（元）"),
    ],
    "account_ledger": [
        ("date", "凭证日期"),
        ("period_code", "会计期间"),
        ("journal_id", "凭证号"),
        ("position", "分录序号"),
        ("reference", "依据编号"),
        ("account", "科目快照"),
        ("summary", "摘要"),
        ("debit", "借方（元）"),
        ("credit", "贷方（元）"),
        ("balance_direction", "余额方向"),
        ("balance", "余额（元）"),
        ("source", "来源"),
    ],
}


def money(value: Decimal) -> str:
    return f"{value:.2f}"


def sides(net: Decimal) -> tuple[str, str]:
    return money(max(net, ZERO)), money(max(-net, ZERO))


def posted_lines(db: Session, filters: LedgerReportQuery):
    statement = (
        select(JournalLine, Journal, AccountingPeriod.code)
        .join(Journal, Journal.id == JournalLine.journal_id)
        .join(AccountingPeriod, AccountingPeriod.id == Journal.period_id)
        .where(Journal.status == "posted", Journal.journal_date <= filters.to_date)
        .order_by(Journal.journal_date, Journal.id, JournalLine.position)
    )
    if filters.account_id is not None:
        statement = statement.where(JournalLine.account_id == filters.account_id)
    return db.execute(statement)


def trial_balance(db: Session, filters: LedgerReportQuery) -> tuple[list[dict], dict]:
    # 不用 SQLite 对文本金额 SUM，避免它隐式转为二进制浮点。
    amounts: dict[int, list[Decimal]] = {
        line.account_id: [Decimal(line.debit) - Decimal(line.credit), ZERO, ZERO]
        for line in confirmed_opening_lines(db)
    }
    for line, journal, _ in posted_lines(db, filters):
        values = amounts.setdefault(line.account_id, [ZERO, ZERO, ZERO])
        debit, credit = Decimal(line.debit), Decimal(line.credit)
        if journal.journal_date < filters.from_date:
            values[0] += debit - credit
        else:
            values[1] += debit
            values[2] += credit
    rows, sums = [], {key: ZERO for key in BALANCE_KEYS}
    # 停用和零余额科目仍可核对；编码、类别与方向本来就不可修改。
    for account in db.scalars(select(LedgerAccount).order_by(LedgerAccount.code)):
        opening, debit, credit = amounts.get(account.id, [ZERO, ZERO, ZERO])
        opening_debit, opening_credit = sides(opening)
        closing_debit, closing_credit = sides(opening + debit - credit)
        row = dict(
            account_id=str(account.id),
            code=account.code,
            name=account.name,
            opening_debit=opening_debit,
            opening_credit=opening_credit,
            debit=money(debit),
            credit=money(credit),
            closing_debit=closing_debit,
            closing_credit=closing_credit,
        )
        rows.append(row)
        for key in BALANCE_KEYS:
            sums[key] += Decimal(row[key])
    totals = {key: money(value) for key, value in sums.items()}
    totals["balanced"] = all(
        sums[a] == sums[b]
        for a, b in (
            ("opening_debit", "opening_credit"),
            ("debit", "credit"),
            ("closing_debit", "closing_credit"),
        )
    )
    return rows, totals


def account_ledger(db: Session, filters: LedgerReportQuery) -> tuple[list[dict], dict]:
    account = db.get(LedgerAccount, filters.account_id)
    if account is None:
        raise HTTPException(404, "科目不存在")
    opening = sum(
        (
            Decimal(line.debit) - Decimal(line.credit)
            for line in confirmed_opening_lines(db)
            if line.account_id == account.id
        ),
        ZERO,
    )
    debit_sum, credit_sum, net = ZERO, ZERO, opening
    rows = []
    transfers = set(db.scalars(select(ProfitTransfer.journal_id)))
    for line, journal, period_code in posted_lines(db, filters):
        debit, credit = Decimal(line.debit), Decimal(line.credit)
        net += debit - credit
        if journal.journal_date < filters.from_date:
            opening = net
            continue
        debit_sum += debit
        credit_sum += credit
        rows.append(
            dict(
                date=journal.journal_date,
                period_code=period_code,
                journal_id=str(journal.id),
                position=str(line.position),
                reference=journal.reference,
                account=f"{line.account_code} · {line.account_name}",
                summary=line.summary,
                debit=money(debit),
                credit=money(credit),
                balance_direction="借" if net > ZERO else "贷" if net < ZERO else "平",
                balance=money(abs(net)),
                reversal_of_id=str(journal.reversal_of_id or ""),
                source=(
                    f"冲销记-{journal.reversal_of_id}"
                    if journal.reversal_of_id
                    else "损益结转" if journal.id in transfers else "手工录入"
                ),
            )
        )
    opening_debit, opening_credit = sides(opening)
    closing_debit, closing_credit = sides(net)
    return rows, dict(
        account_id=str(account.id),
        code=account.code,
        name=account.name,
        opening_debit=opening_debit,
        opening_credit=opening_credit,
        debit=money(debit_sum),
        credit=money(credit_sum),
        closing_debit=closing_debit,
        closing_credit=closing_credit,
    )


@router.get("/options")
def options(user: dict = Depends(require("journal.view"))) -> list[dict]:
    with orm_session() as db:
        return [
            snapshot(account)
            for account in db.scalars(
                select(LedgerAccount).order_by(LedgerAccount.code).limit(100)
            )
        ]


def confirmed_opening_lines(db: Session):
    record = active_opening(db)
    return (
        opening_lines(db, record.id)
        if record is not None and record.status == "confirmed"
        else []
    )


@router.post("/query")
def query_report(
    filters: LedgerReportQuery, user: dict = Depends(require("journal.view"))
) -> dict:
    with orm_session() as db:
        record = active_opening(db)
        opening = None
        if record is not None and record.status == "confirmed":
            if filters.from_date < record.effective_date:
                raise HTTPException(409, "查询开始日期不能早于总账启用日")
            opening = {
                **opening_view(db, record),
                "changes": opening_history(db, record.id),
            }
        rows, totals = (
            trial_balance(db, filters)
            if filters.kind == "trial_balance"
            else account_ledger(db, filters)
        )
        periods = [
            snapshot(period)
            for period in db.scalars(
                select(AccountingPeriod)
                .where(
                    AccountingPeriod.start_date <= filters.to_date,
                    AccountingPeriod.end_date >= filters.from_date,
                )
                .order_by(AccountingPeriod.start_date)
            )
        ]
        generated_at = datetime.now(timezone.utc).isoformat()
    columns = [{"key": key, "title": title} for key, title in COLUMNS[filters.kind]]
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["报表", "开始日期", "结束日期", "生成时间（UTC）", "口径", "期初来源", "科目"]
    )
    writer.writerow(
        [
            "试算平衡" if filters.kind == "trial_balance" else "科目明细",
            filters.from_date,
            filters.to_date,
            generated_at,
            (
                "已确认期初及已过账凭证；未结账数据可变化"
                if opening
                else "仅已过账凭证；未结账数据可变化"
            ),
            (
                csv_value(
                    f'期初-{opening["id"]} · {opening["reference"]} · {opening["effective_date"]}'
                )
                if opening
                else "未录入正式期初"
            ),
            (
                csv_value(f'{totals["code"]} · {totals["name"]}')
                if filters.kind == "account_ledger"
                else "全部科目"
            ),
        ]
    )
    writer.writerow([column["title"] for column in columns])
    for row in rows:
        writer.writerow([csv_value(row[column["key"]]) for column in columns])
    writer.writerow([])
    writer.writerow(
        ["合计", "期初借方", "期初贷方", "本期借方", "本期贷方", "期末借方", "期末贷方"]
    )
    writer.writerow(["人民币", *(totals[key] for key in BALANCE_KEYS)])
    result = dict(
        kind=filters.kind,
        filters=filters.model_dump(),
        columns=columns,
        rows=rows,
        totals=totals,
        periods=periods,
        generated_at=generated_at,
        opening_balance=opening,
        csv="\ufeff" + output.getvalue(),
    )

    if filters.paged:
        from app.query.snapshots import snapshot_metadata
        return snapshot_metadata(result,user,('rows','opening_balance.lines','opening_balance.changes'))
    return result
