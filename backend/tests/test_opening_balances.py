"""首次启用、独立审核、精确期初、并发及审计回滚。"""

from approval_test_helpers import approve_document
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import csv
from io import StringIO
import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session
from app.core.models import OpeningBalanceChange
from app.core.database import connection, migrate
from test_journals import journals, create as create_journal, action as journal_action
from test_ledger_reports import query
from test_ledger_foundation import ledger

BASE = "/api/v1/finance/opening-balances"


def payload(reference="OPEN-001", lines=None):
    return dict(
        reference=reference,
        effective_date="2026-01-01",
        note="启用试算表",
        reason="已核对上期余额",
        lines=(
            lines
            if lines is not None
            else [
                dict(account_id=1, summary="现金期初", debit="123.45", credit="0"),
                dict(account_id=2, summary="应付期初", debit="0", credit="123.45"),
            ]
        ),
    )


def create(journals, **changes):
    response = journals[0].post(BASE, json={**payload(), **changes})
    assert response.status_code == 201, response.text
    return response.json()


def action(journals, record, name, review=False):
    client, reviewer = journals
    if name in ('submit', 'approve', 'reject', 'withdraw'):
        # 原有回归明确调用真实统一入口，成功后重新读取业务版本；不会自动批准。
        response = client.post(f'/api/v1/system/document-approvals/OpeningBalance/{record["id"]}/{name}',
            json=dict(version=record['approval']['version'], reason='期初核对'), headers=reviewer if review else None)
        if response.status_code == 200:
            return next(row for row in client.get(BASE).json() if row['id'] == record['id'])
    else:
        response = client.post(f'{BASE}/{record["id"]}/{name}',
            json=dict(version=record['version'], reason='期初核对'), headers=reviewer if review else None)
    assert response.status_code == 200, response.text
    return response.json()


def confirmed(journals, **changes):
    record = action(journals, create(journals, **changes), "submit")
    return action(journals, action(journals, record, "approve", True), "confirm")


def test_lifecycle_report_basis_and_no_current_occurrence(journals):
    client, _ = journals
    record = create(journals)
    assert record["currency"] == "CNY" and record["total_debit"] == "123.45"
    assert query(client)["totals"]["opening_debit"] == "0.00"
    record = action(journals, record, "submit")
    assert (
        client.post(
            f'{BASE}/{record["id"]}/approve', json=dict(version=2, reason="自审")
        ).status_code
        == 409
    )
    record = action(journals, record, "approve", True)
    assert query(client)["opening_balance"] is None
    record = action(journals, record, "confirm")
    report = query(client, from_date="2026-01-01")
    assert report["totals"] == dict(
        opening_debit="123.45",
        opening_credit="123.45",
        debit="0.00",
        credit="0.00",
        closing_debit="123.45",
        closing_credit="123.45",
        balanced=True,
    )
    assert report["opening_balance"]["id"] == record["id"]
    assert [h["action"] for h in report["opening_balance"]["changes"]] == [
        "create",
        "submit",
        "approve",
        "confirm",
    ]
    detail = query(client, kind="account_ledger", account_id=1)
    assert detail["rows"] == [] and detail["totals"]["closing_debit"] == "123.45"
    assert "OPEN-001" in detail["csv"] and "2026-01-01" in detail["csv"]
    assert (
        client.post(
            "/api/v1/finance/ledger-reports/query",
            json=dict(
                kind="trial_balance", from_date="2025-12-31", to_date="2026-01-20"
            ),
        ).status_code
        == 409
    )
    assert (
        client.put(
            f'{BASE}/{record["id"]}', json={**payload(), "version": record["version"]}
        ).status_code
        == 409
    )
    assert client.delete(f'{BASE}/{record["id"]}').status_code == 405


def test_pending_blocks_post_then_post_locks_opening_and_precise_carry(journals):
    client, reviewer = journals
    opening = create(journals)
    record = journal_action(
        client,
        journal_action(client, create_journal(client), "submit"),
        "approve",
        reviewer,
    )
    assert (
        client.post(
            f'/api/v1/finance/journals/{record["id"]}/post',
            json=dict(version=record["version"], reason="尝试"),
        ).status_code
        == 409
    )
    opening = action(
        journals,
        action(journals, action(journals, opening, "submit"), "approve", True),
        "confirm",
    )
    journal_action(client, record, "post")
    report = query(client)
    assert report["totals"]["opening_debit"] == "123.45"
    assert (
        report["totals"]["debit"] == "123.45"
        and report["totals"]["closing_debit"] == "246.90"
    )
    assert (
        query(client, kind="account_ledger", account_id=1)["rows"][0]["balance"]
        == "246.90"
    )
    for request in (
        client.post(
            f'{BASE}/{opening["id"]}/reverse', json=dict(version=4, reason="重设")
        ),
        client.post(BASE, json=payload("SECOND")),
    ):
        assert request.status_code == 409
    assert client.get(BASE).json()[0]["status"] == "confirmed"


def test_cancel_reverse_replacement_and_zero_initialization(journals):
    client, _ = journals
    cancelled = action(journals, create(journals), "cancel")
    assert cancelled["active_key"] is None
    original = confirmed(journals, reference="SECOND")
    approve_document(client, None, 'OpeningBalance', original['id'], intent='reverse', reason='期初核对')
    original = next(row for row in client.get(BASE).json() if row['id'] == original['id'])
    reversed_record = action(journals, original, "reverse")
    assert (
        reversed_record["status"] == "reversed"
        and reversed_record["lines"] == original["lines"]
    )
    assert query(client)["opening_balance"] is None
    # 撤销后的空档不能偷跑过账，否则原期初会消失且无法再确认替代方案。
    journal = journal_action(
        client,
        journal_action(client, create_journal(client), "submit"),
        "approve",
        journals[1],
    )
    assert (
        client.post(
            f'/api/v1/finance/journals/{journal["id"]}/post',
            json=dict(version=journal["version"], reason="空档过账"),
        ).status_code
        == 409
    )
    zero = confirmed(journals, reference="ZERO", lines=[])
    assert zero["total_debit"] == "0.00" and zero["lines"] == []
    assert query(client)["opening_balance"]["reference"] == "ZERO"
    assert query(client)["totals"]["balanced"] is True
    assert len(client.get(BASE).json()) == 3


@pytest.mark.parametrize(
    "changes",
    [
        dict(reference=" "),
        dict(effective_date="2026-01-02"),
        dict(effective_date="2026-02-30"),
        dict(lines=[dict(account_id=1, summary="A", debit="1", credit="0")]),
        dict(
            lines=[
                dict(account_id=1, summary="A", debit="1", credit="0"),
                dict(account_id=1, summary="B", debit="0", credit="1"),
            ]
        ),
        dict(extra="拒绝"),
        dict(lines=[dict(account_id=True, summary="A", debit="1", credit="0")]),
        dict(lines=[dict(account_id=1, summary="A", debit="0.001", credit="0")]),
    ],
)
def test_input_failures(journals, changes):
    response = journals[0].post(BASE, json={**payload(), **changes})
    assert response.status_code in (409, 422)
    assert journals[0].get(BASE).json() == []


def test_versions_authors_inactive_accounts_and_earlier_period(journals):
    client, reviewer = journals
    record = create(journals)
    assert client.post(BASE, json=payload("SECOND")).status_code == 409
    assert (
        client.post(
            "/api/v1/finance/accounting-periods",
            json=dict(
                code="OLD",
                name="旧期",
                start_date="2025-12-01",
                end_date="2025-12-31",
                reason="旧期",
            ),
        ).status_code
        == 409
    )
    record = action(journals, record, "submit")
    record = action(journals, record, "reject", True)
    response = client.put(
        f'{BASE}/{record["id"]}',
        json={**payload(), "version": record["version"], "reason": "修正"},
        headers=reviewer,
    )
    assert response.status_code == 200, response.text
    record = response.json()
    assert set(record["author_ids"]) == {1, 2}
    record = action(journals, record, "submit")
    assert (
        client.post(
            f'{BASE}/{record["id"]}/approve',
            json=dict(version=record["version"], reason="编辑人自审"),
            headers=reviewer,
        ).status_code
        == 409
    )
    assert (
        client.post(
            f'{BASE}/{record["id"]}/cancel', json=dict(version=1, reason="旧版本")
        ).status_code
        == 409
    )
    record = action(journals, record, "withdraw")
    record = action(journals, record, "cancel")
    assert (
        client.put(
            "/api/v1/finance/ledger-accounts/1",
            json=dict(version=1, name="停用现金", is_active=False, reason="停用"),
        ).status_code
        == 200
    )
    assert client.post(BASE, json=payload("NEW")).status_code == 409


def test_audit_failure_rolls_back_and_concurrent_creation_confirmation(journals):
    client, reviewer = journals

    def fail(session, _):
        if any(isinstance(item, OpeningBalanceChange) for item in session.new):
            raise RuntimeError("模拟审计失败")

    event.listen(Session, "before_flush", fail)
    try:
        assert client.post(BASE, json=payload()).status_code == 500
    finally:
        event.remove(Session, "before_flush", fail)
    assert client.get(BASE).json() == []
    gate = Barrier(2)

    def create_at_once(index):
        gate.wait()
        return client.post(BASE, json=payload(f"C{index}")).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(create_at_once, range(2))) == [201, 409]
    record = client.get(BASE).json()[0]
    record = action(journals, action(journals, record, "submit"), "approve", True)
    gate = Barrier(2)

    def confirm_at_once(_):
        gate.wait()
        return client.post(
            f'{BASE}/{record["id"]}/confirm',
            json=dict(version=record["version"], reason="并发确认"),
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(confirm_at_once, range(2))) == [200, 409]
    assert len(client.get(f'{BASE}/{record["id"]}/changes').json()) == 4


def test_permissions_and_v41_migration(journals, remove_closing_schema):
    client, _ = journals
    client.post(
        "/api/v1/users",
        json=dict(username="buyer", password="secure-pass-123", roles=["buyer"]),
    )
    token = client.post(
        "/api/v1/auth/login", json=dict(username="buyer", password="secure-pass-123")
    ).json()["token"]
    headers = {"Authorization": "Bearer " + token}
    record = create(journals)
    for path in (BASE, BASE + "/options", f'{BASE}/{record["id"]}/changes'):
        assert client.get(path, headers=headers).status_code == 403
    for name in ("submit", "approve", "reject", "confirm", "cancel", "reverse"):
        assert (
            client.post(
                f'{BASE}/{record["id"]}/{name}',
                json=dict(version=1, reason="越权"),
                headers=headers,
            ).status_code
            == 403
        )
    assert client.post(BASE, json=payload("DENIED"), headers=headers).status_code == 403
    with connection() as db:
        remove_closing_schema(db)
        for table in (
            "opening_balance_changes",
            "opening_balance_lines",
            "opening_balances",
        ):
            db.execute(f"DROP TABLE {table}")
        db.execute(
            "DELETE FROM role_permissions WHERE permission_code LIKE 'opening_balance.%'"
        )
        db.execute("DELETE FROM permissions WHERE code LIKE 'opening_balance.%'")
        db.execute(
            "DELETE FROM permission_groups WHERE code='finance.opening_balances'"
        )
        db.execute("PRAGMA user_version=41")
    migrate()
    migrate()
    with connection() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 96
        assert db.execute("SELECT COUNT(*) FROM ledger_accounts").fetchone()[0] == 2
        assert (
            db.execute(
                "SELECT COUNT(*) FROM role_permissions WHERE permission_code='opening_balance.confirm'"
            ).fetchone()[0]
            == 2
        )
    assert client.get(BASE).json() == []


def test_legacy_posted_journal_prevents_new_opening(journals):
    client, reviewer = journals
    record = journal_action(
        client,
        journal_action(client, create_journal(client), "submit"),
        "approve",
        reviewer,
    )
    journal_action(client, record, "post")
    assert client.post(BASE, json=payload()).status_code == 409
    assert query(client)["opening_balance"] is None
    assert query(client)["totals"]["debit"] == "123.45"


def test_confirmation_audit_failure_preserves_approved_basis(journals):
    client, _ = journals
    record = action(
        journals, action(journals, create(journals), "submit"), "approve", True
    )

    def fail(session, _):
        if any(isinstance(item, OpeningBalanceChange) for item in session.new):
            raise RuntimeError("模拟确认审计失败")

    event.listen(Session, "before_flush", fail)
    try:
        assert (
            client.post(
                f'{BASE}/{record["id"]}/confirm',
                json=dict(version=record["version"], reason="确认"),
            ).status_code
            == 500
        )
    finally:
        event.remove(Session, "before_flush", fail)
    assert client.get(BASE).json()[0] == record
    assert query(client)["opening_balance"] is None
    assert len(client.get(f'{BASE}/{record["id"]}/changes').json()) == 3
    assert action(journals, record, "confirm")["version"] == 4


def test_report_only_permission_reads_confirmed_source_and_large_exact_amount(journals):
    client, _ = journals
    amount = "999999999999.99"
    opening = confirmed(
        journals,
        lines=[
            dict(account_id=1, summary="启用试算表", debit=amount, credit="0"),
            dict(account_id=2, summary="启用试算表", debit="0", credit=amount),
        ],
    )
    client.post(
        "/api/v1/roles",
        json=dict(code="report_reader", label="报表查看", permissions=["journal.view"]),
    )
    client.post(
        "/api/v1/users",
        json=dict(
            username="report_reader",
            password="secure-pass-123",
            roles=["report_reader"],
        ),
    )
    token = client.post(
        "/api/v1/auth/login",
        json=dict(username="report_reader", password="secure-pass-123"),
    ).json()["token"]
    headers = {"Authorization": "Bearer " + token}
    assert client.get(BASE, headers=headers).status_code == 403
    assert (
        client.get(f'{BASE}/{opening["id"]}/changes', headers=headers).status_code
        == 403
    )
    report = client.post(
        "/api/v1/finance/ledger-reports/query",
        json=dict(kind="trial_balance", from_date="2026-01-01", to_date="2026-01-31"),
        headers=headers,
    ).json()
    assert report["opening_balance"]["id"] == opening["id"]
    assert len(report["opening_balance"]["changes"]) == 4
    assert report["totals"]["opening_debit"] == amount
    assert report["totals"]["debit"] == "0.00"
    assert report["totals"]["closing_credit"] == amount
