"""科目与期间的版本、审计、迁移和并发边界。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.database import connection, migrate
from app.core.models import AccountingPeriodChange, LedgerAccountChange
from app.main import app


@pytest.fixture
def ledger(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "ledger.db"))
    with TestClient(
        app, client=("127.0.0.1", 12345), raise_server_exceptions=False
    ) as client:
        assert (
            client.post(
                "/api/v1/setup/admin",
                json={"username": "admin", "password": "secure-pass-123"},
            ).status_code
            == 201
        )
        client.headers["Authorization"] = (
            "Bearer "
            + client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "secure-pass-123"},
            ).json()["token"]
        )
        yield client


ACCOUNT = {
    "code": "1001",
    "name": "库存现金",
    "category": "asset",
    "normal_balance": "debit",
    "reason": "建立科目",
}
PERIOD = {
    "code": "2026-01",
    "name": "2026 年 1 月",
    "start_date": "2026-01-01",
    "end_date": "2026-01-31",
    "reason": "建立期间",
}
BASE = "/api/v1/finance"


def test_account_versions_audit_and_immutable_structure(ledger):
    record = ledger.post(
        f"{BASE}/ledger-accounts", json={**ACCOUNT, "code": " ab_01 "}
    ).json()
    assert (
        record["code"] == "AB_01"
        and record["version"] == 1
        and record["is_active"] is True
    )
    path = f'{BASE}/ledger-accounts/{record["id"]}'
    update = {
        "name": "现金科目",
        "is_active": False,
        "version": 1,
        "reason": "停用旧科目",
    }
    saved = ledger.put(path, json=update)
    assert saved.status_code == 200 and saved.json()["version"] == 2
    assert ledger.put(path, json={**update, "name": "过期名称"}).status_code == 409
    assert (
        ledger.put(path, json={**update, "version": 2, "code": "2001"}).status_code
        == 422
    )
    assert ledger.delete(path).status_code == 405
    history = ledger.get(path + "/changes").json()
    assert len(history) == 2 and history[0]["before"] is None
    assert history[1]["before"] == record and history[1]["after"] == saved.json()
    assert (
        history[1]["changed_by_name"] == "admin"
        and history[1]["reason"] == update["reason"]
    )
    assert (
        ledger.post(
            f"{BASE}/ledger-accounts", json={**ACCOUNT, "code": "ab_01"}
        ).status_code
        == 409
    )
    assert ledger.get(f"{BASE}/ledger-accounts").json() == [saved.json()]


def test_period_boundaries_and_immutable_dates(ledger):
    response = ledger.post(f"{BASE}/accounting-periods", json=PERIOD)
    assert response.status_code == 201
    record = response.json()
    assert record["status"] == "open"
    # 首尾日期属于期间；紧邻下一天允许，包含、跨越和同一天交叠都拒绝。
    for start, end in [
        ("2026-01-31", "2026-02-28"),
        ("2025-12-01", "2026-01-01"),
        ("2025-12-01", "2026-02-28"),
        ("2026-01-10", "2026-01-20"),
    ]:
        assert (
            ledger.post(
                f"{BASE}/accounting-periods",
                json={**PERIOD, "code": "OTHER", "start_date": start, "end_date": end},
            ).status_code
            == 409
        )
    assert (
        ledger.post(
            f"{BASE}/accounting-periods",
            json={
                **PERIOD,
                "code": "2026-02",
                "start_date": "2026-02-01",
                "end_date": "2026-02-28",
            },
        ).status_code
        == 201
    )
    path = f'{BASE}/accounting-periods/{record["id"]}'
    update = {"name": "首个期间", "version": 1, "reason": "修正名称"}
    result = ledger.put(path, json=update)
    assert result.status_code == 200 and result.json()["version"] == 2
    assert ledger.put(path, json=update).status_code == 409
    assert (
        ledger.put(
            path, json={**update, "version": 2, "end_date": "2026-02-28"}
        ).status_code
        == 422
    )
    assert (
        ledger.post(path + "/close", json={"reason": "缺少版本"}).status_code == 422
    )
    assert ledger.get(path + "/changes").json()[1]["before"] == record
    assert ledger.get(f"{BASE}/accounting-periods/999/changes").status_code == 404


@pytest.mark.parametrize(
    "path,payload",
    [
        ("ledger-accounts", {**ACCOUNT, "code": "/路径"}),
        ("ledger-accounts", {**ACCOUNT, "name": "   "}),
        ("ledger-accounts", {**ACCOUNT, "reason": "  "}),
        ("ledger-accounts", {**ACCOUNT, "category": "unknown"}),
        ("ledger-accounts", {**ACCOUNT, "normal_balance": "both"}),
        ("accounting-periods", {**PERIOD, "end_date": "2026-02-30"}),
        ("accounting-periods", {**PERIOD, "start_date": "20260101"}),
        ("accounting-periods", {**PERIOD, "start_date": "2026-02-01"}),
    ],
)
def test_invalid_metadata_is_rejected_without_writes(ledger, path, payload):
    assert ledger.post(f"{BASE}/{path}", json=payload).status_code == 422
    assert ledger.get(f"{BASE}/{path}").json() == []


def test_independent_permissions_and_default_finance_grant(ledger):
    for username, role in [("finance", "finance"), ("buyer", "buyer")]:
        assert (
            ledger.post(
                "/api/v1/users",
                json={
                    "username": username,
                    "password": "secure-pass-123",
                    "roles": [role],
                },
            ).status_code
            == 201
        )
        token = ledger.post(
            "/api/v1/auth/login",
            json={"username": username, "password": "secure-pass-123"},
        ).json()["token"]
        headers = {"Authorization": "Bearer " + token}
        for path, payload in [
            ("ledger-accounts", ACCOUNT),
            ("accounting-periods", PERIOD),
        ]:
            assert ledger.get(f"{BASE}/{path}", headers=headers).status_code == (
                200 if role == "finance" else 403
            )
            assert ledger.post(
                f"{BASE}/{path}", headers=headers, json=payload
            ).status_code == (201 if role == "finance" else 403)
            assert ledger.get(
                f"{BASE}/{path}/1/changes", headers=headers
            ).status_code == (200 if role == "finance" else 403)
    role = ledger.post(
        "/api/v1/roles",
        json={
            "code": "ledger_read",
            "label": "总账查看",
            "permissions": ["ledger_account.view"],
        },
    )
    assert role.status_code == 201
    assert (
        ledger.post(
            "/api/v1/users",
            json={
                "username": "reader",
                "password": "secure-pass-123",
                "roles": ["ledger_read"],
            },
        ).status_code
        == 201
    )
    token = ledger.post(
        "/api/v1/auth/login", json={"username": "reader", "password": "secure-pass-123"}
    ).json()["token"]
    headers = {"Authorization": "Bearer " + token}
    assert ledger.get(f"{BASE}/ledger-accounts", headers=headers).status_code == 200
    assert (
        ledger.post(
            f"{BASE}/ledger-accounts", headers=headers, json=ACCOUNT
        ).status_code
        == 403
    )
    assert ledger.get(f"{BASE}/accounting-periods", headers=headers).status_code == 403


@pytest.mark.parametrize(
    "path,payload,change_type",
    [
        ("ledger-accounts", ACCOUNT, LedgerAccountChange),
        ("accounting-periods", PERIOD, AccountingPeriodChange),
    ],
)
def test_audit_failure_rolls_back_creation_and_revision(
    ledger, path, payload, change_type
):
    def fail(session, *_):
        if any(isinstance(item, change_type) for item in session.new):
            raise RuntimeError("模拟审计写入失败")

    event.listen(Session, "before_flush", fail)
    try:
        assert ledger.post(f"{BASE}/{path}", json=payload).status_code == 500
    finally:
        event.remove(Session, "before_flush", fail)
    assert ledger.get(f"{BASE}/{path}").json() == []
    record = ledger.post(f"{BASE}/{path}", json=payload).json()
    update = {"name": "新名称", "reason": "调整", "version": 1}
    if path == "ledger-accounts":
        update["is_active"] = False
    event.listen(Session, "before_flush", fail)
    try:
        assert (
            ledger.put(f'{BASE}/{path}/{record["id"]}', json=update).status_code == 500
        )
    finally:
        event.remove(Session, "before_flush", fail)
    assert ledger.get(f"{BASE}/{path}").json() == [record]
    assert len(ledger.get(f'{BASE}/{path}/{record["id"]}/changes').json()) == 1
    assert ledger.put(f'{BASE}/{path}/{record["id"]}', json=update).status_code == 200


@pytest.mark.parametrize("kind", ["period_create", "account_update"])
def test_concurrent_writes_cannot_overlap_or_overwrite(ledger, kind):
    barrier = Barrier(2)
    if kind == "account_update":
        record = ledger.post(f"{BASE}/ledger-accounts", json=ACCOUNT).json()

    def write(index):
        barrier.wait(timeout=5)
        if kind == "period_create":
            return ledger.post(
                f"{BASE}/accounting-periods", json={**PERIOD, "code": f"P{index}"}
            ).status_code
        return ledger.put(
            f'{BASE}/ledger-accounts/{record["id"]}',
            json={
                "name": f"并发{index}",
                "is_active": True,
                "version": 1,
                "reason": "修改名称",
            },
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        expected = [200, 409] if kind == "account_update" else [201, 409]
        assert sorted(pool.map(write, range(2))) == expected
    if kind == "account_update":
        assert (
            len(ledger.get(f'{BASE}/ledger-accounts/{record["id"]}/changes').json())
            == 2
        )
    else:
        assert len(ledger.get(f"{BASE}/accounting-periods").json()) == 1


def test_v39_upgrade_preserves_data_and_is_repeatable(ledger, remove_journal_schema):
    with connection() as db:
        remove_journal_schema(db)
        db.execute("INSERT INTO suppliers(name) VALUES ('升级前供应商')")
        for table in (
            "ledger_account_changes",
            "accounting_period_changes",
            "ledger_accounts",
            "accounting_periods",
        ):
            db.execute(f"DROP TABLE {table}")
        for code in (
            "ledger_account.view",
            "ledger_account.manage",
            "accounting_period.view",
            "accounting_period.manage",
        ):
            db.execute("DELETE FROM role_permissions WHERE permission_code=?", (code,))
            db.execute("DELETE FROM permissions WHERE code=?", (code,))
        db.execute(
            "DELETE FROM permission_groups WHERE code IN ('finance.ledger_accounts','finance.accounting_periods')"
        )
        db.execute("PRAGMA user_version=39")
    migrate()
    migrate()
    with connection() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 95
        assert db.execute("SELECT name FROM suppliers").fetchone()[0] == "升级前供应商"
        assert (
            db.execute(
                "SELECT COUNT(*) FROM role_permissions WHERE permission_code='ledger_account.view'"
            ).fetchone()[0]
            == 2
        )
    assert ledger.get(f"{BASE}/ledger-accounts").json() == []
    assert ledger.get(f"{BASE}/accounting-periods").json() == []
