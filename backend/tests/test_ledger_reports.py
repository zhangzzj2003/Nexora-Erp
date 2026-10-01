"""总账查询的日期口径、精确余额、冲销、授权与导出快照。"""

import csv
from io import StringIO

import pytest

from test_journals import journals, action, payload
from test_ledger_foundation import ledger, BASE

REPORT = BASE + "/ledger-reports"
JOURNALS = BASE + "/journals"
FILTERS = dict(
    kind="trial_balance", from_date="2026-01-10", to_date="2026-01-20", account_id=None
)


def query(client, **overrides):
    response = client.post(REPORT + "/query", json={**FILTERS, **overrides})
    assert response.status_code == 200, response.text
    return response.json()


def make(journals, reference, day, amount, *, posted=True, credit_first=False):
    client, reviewer = journals
    data = payload(reference)
    data["journal_date"] = day
    data["lines"][0]["debit"] = amount
    data["lines"][1]["credit"] = amount
    if credit_first:
        for line in data["lines"]:
            line["debit"], line["credit"] = line["credit"], line["debit"]
    response = client.post(JOURNALS, json=data)
    assert response.status_code == 201, response.text
    record = response.json()
    if posted:
        record = action(client, action(client, record, "submit"), "approve", reviewer)
        record = action(client, record, "post")
    return record


def test_empty_database(ledger):
    report = query(ledger)
    assert report["rows"] == [] and report["totals"]["balanced"] is True
    assert all(v == "0.00" for k, v in report["totals"].items() if k != "balanced")


def test_unused_accounts(journals):
    client, _ = journals
    assert len(query(client)["rows"]) == 2
    detail = query(client, kind="account_ledger", account_id=1)
    assert detail["rows"] == []
    # 无发生额的导出也要标明科目，不能让相同零余额报表失去查询范围。
    csv_rows = list(csv.reader(StringIO(detail["csv"].lstrip("\ufeff"))))
    assert csv_rows[0][-1] == "科目"
    assert csv_rows[1][-1] == "1001 · 库存现金"


def test_date_boundaries_sorting_opening_credit_and_exact_cents(journals):
    client, reviewer = journals
    # 建单顺序与凭证日期相反，余额应按凭证日期再按编号、行号排序。
    middle = make(journals, "MID", "2026-01-12", "0.20")
    opening = make(journals, "OLD", "2026-01-09", "0.10")
    first = make(journals, "START", "2026-01-10", "0.10")
    last = make(journals, "END", "2026-01-20", "0.05", credit_first=True)
    make(journals, "FUTURE", "2026-01-21", "100")
    make(journals, "DRAFT", "2026-01-11", "999", posted=False)
    approved = make(journals, "APPROVED", "2026-01-15", "777", posted=False)
    approved = action(client, action(client, approved, "submit"), "approve", reviewer)
    report = query(client)
    assert report["totals"] == dict(
        opening_debit="0.10",
        opening_credit="0.10",
        debit="0.35",
        credit="0.35",
        closing_debit="0.35",
        closing_credit="0.35",
        balanced=True,
    )
    assert report["rows"][0]["closing_debit"] == "0.35"
    detail = query(client, kind="account_ledger", account_id=1)
    assert [r["journal_id"] for r in detail["rows"]] == list(
        map(str, (first["id"], middle["id"], last["id"]))
    )
    assert [r["balance"] for r in detail["rows"]] == ["0.20", "0.40", "0.35"]
    credit = query(client, kind="account_ledger", account_id=2)
    assert all(r["balance_direction"] == "贷" for r in credit["rows"])
    assert credit["totals"]["opening_credit"] == "0.10"
    only_opening = query(
        client,
        kind="account_ledger",
        account_id=1,
        from_date="2026-01-22",
        to_date="2026-01-31",
    )
    assert (
        only_opening["rows"] == []
        and only_opening["totals"]["closing_debit"] == "100.35"
    )
    assert (
        query(
            client,
            kind="account_ledger",
            account_id=1,
            from_date="2026-01-01",
            to_date="2026-01-08",
        )["totals"]["closing_debit"]
        == "0.00"
    )
    assert client.get(f'{JOURNALS}/{opening["id"]}').json()["lines"] == opening["lines"]


def test_reversal_only_counts_after_post_and_keeps_source(journals):
    client, reviewer = journals
    original = make(journals, "ORIGINAL", "2026-01-10", "123.45")
    reversal = client.post(
        f'{JOURNALS}/{original["id"]}/reverse',
        json=dict(
            version=original["version"],
            reference="REV",
            journal_date="2026-01-20",
            reason="更正",
        ),
    ).json()
    assert query(client)["rows"][0]["closing_debit"] == "123.45"
    reversal = action(client, action(client, reversal, "submit"), "approve", reviewer)
    assert query(client)["rows"][0]["closing_debit"] == "123.45"
    action(client, reversal, "post")
    report = query(client)
    assert report["rows"][0]["closing_debit"] == "0.00"
    assert report["totals"]["debit"] == report["totals"]["credit"] == "246.90"
    detail = query(client, kind="account_ledger", account_id=1)
    assert detail["rows"][-1]["balance_direction"] == "平"
    assert detail["rows"][-1]["source"] == f'冲销记-{original["id"]}'
    assert detail["rows"][-1]["reversal_of_id"] == str(original["id"])
    assert query(client, to_date="2026-01-19")["rows"][0]["closing_debit"] == "123.45"
    assert (
        client.get(f'{JOURNALS}/{original["id"]}').json()["reversal_journal_id"]
        == reversal["id"]
    )


def test_large_precision_and_same_account_multiple_lines(journals):
    client, reviewer = journals
    make(journals, "LARGE1", "2026-01-10", "999999999999.99")
    make(journals, "LARGE2", "2026-01-10", "999999999999.99")
    record = payload("SAME")
    record["lines"] = [
        dict(account_id=1, summary="同科目借方", debit="0.1", credit="0"),
        dict(account_id=1, summary="同科目贷方", debit="0", credit="0.1"),
    ]
    record = client.post(JOURNALS, json=record).json()
    action(
        client,
        action(client, action(client, record, "submit"), "approve", reviewer),
        "post",
    )
    report = query(client)
    assert report["rows"][0]["debit"] == "2000000000000.08"
    assert report["rows"][0]["closing_debit"] == "1999999999999.98"
    rows = query(client, kind="account_ledger", account_id=1)["rows"]
    assert rows[-2]["position"] == "1" and rows[-1]["position"] == "2"
    assert rows[-1]["balance"] == "1999999999999.98"


def test_inactive_account_frozen_line_names_and_csv_formula_protection(journals):
    client, _ = journals
    make(journals, "=HYPERLINK(1)", "2026-01-10", "0.30")
    assert (
        client.put(
            BASE + "/ledger-accounts/1",
            json=dict(version=1, name="=SUM(1)", is_active=False, reason="停用"),
        ).status_code
        == 200
    )
    options = client.get(REPORT + "/options").json()
    assert options[0]["is_active"] is False
    assert query(client)["rows"][0]["name"] == "=SUM(1)"
    detail = query(client, kind="account_ledger", account_id=1)
    assert detail["rows"][0]["account"] == "1001 · 库存现金"
    csv_rows = list(csv.reader(StringIO(detail["csv"].lstrip("\ufeff"))))
    assert csv_rows[3][4] == "'=HYPERLINK(1)"
    assert "'=SUM(1)" in query(client)["csv"]
    assert csv_rows[3][7:9] == ["0.30", "0.00"]


def test_csv_uses_captured_rows_even_if_next_post_changes_database(
    journals, monkeypatch
):
    client, _ = journals
    make(journals, "BEFORE", "2026-01-10", "0.30")
    import app.finance.ledger_reports as module

    original = module.csv_value
    changed = False

    def during_export(value):
        nonlocal changed
        if not changed:
            changed = True
            make(journals, "AFTER", "2026-01-11", "10")
        return original(value)

    monkeypatch.setattr(module, "csv_value", during_export)
    report = query(client)
    assert report["rows"][0]["debit"] == report["totals"]["debit"] == "0.30"
    assert "10.30" not in report["csv"] and "0.30" in report["csv"]
    assert query(client)["totals"]["debit"] == "10.30"


@pytest.mark.parametrize(
    "changes",
    [
        dict(kind="unknown"),
        dict(from_date="2026-02-30"),
        dict(to_date="2026-01-09"),
        dict(from_date="2026-1-1"),
        dict(kind="account_ledger"),
        dict(account_id=1),
        dict(kind="account_ledger", account_id=True),
        dict(kind="account_ledger", account_id=0),
        dict(kind="account_ledger", account_id="1"),
        dict(extra="ignored"),
        dict(to_date="2026-01-20T00:00:00"),
    ],
)
def test_invalid_filters_are_rejected(journals, changes):
    assert (
        journals[0].post(REPORT + "/query", json={**FILTERS, **changes}).status_code
        == 422
    )


def test_permissions_and_missing_details(journals):
    client, _ = journals
    record = make(journals, "VIEW", "2026-01-10", "123.45")
    assert (
        client.post(
            REPORT + "/query",
            json={**FILTERS, "kind": "account_ledger", "account_id": 999},
        ).status_code
        == 404
    )
    assert client.get(JOURNALS + "/999").status_code == 404
    assert client.get(JOURNALS + "/0").status_code == 422
    client.post(
        "/api/v1/roles",
        json=dict(code="report_reader", label="总账查看", permissions=["journal.view", "sales_amount.all"]),
    )
    for username, roles in (("reader", ["report_reader"]), ("buyer", ["buyer"])):
        assert (
            client.post(
                "/api/v1/users",
                json=dict(username=username, password="secure-pass-123", roles=roles),
            ).status_code
            == 201
        )
        token = client.post(
            "/api/v1/auth/login",
            json=dict(username=username, password="secure-pass-123"),
        ).json()["token"]
        headers = {"Authorization": "Bearer " + token}
        expected = 200 if username == "reader" else 403
        assert (
            client.post(REPORT + "/query", headers=headers, json=FILTERS).status_code
            == expected
        )
        assert client.get(REPORT + "/options", headers=headers).status_code == expected
        assert (
            client.get(f'{JOURNALS}/{record["id"]}', headers=headers).status_code
            == expected
        )
        if username == "reader":
            assert (
                client.get(BASE + "/ledger-accounts", headers=headers).status_code
                == 403
            )
            assert (
                client.post(
                    JOURNALS, headers=headers, json=payload("DENIED")
                ).status_code
                == 403
            )
    client.headers.clear()
    assert client.post(REPORT + "/query", json=FILTERS).status_code == 401
