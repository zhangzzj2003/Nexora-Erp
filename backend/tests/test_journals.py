"""凭证金额、职责分离、冲销快照和并发审计回归。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core.models import JournalChange, AccountingPeriod
from app.core.orm import orm_session
from app.core.database import connection, migrate
from test_ledger_foundation import ledger, ACCOUNT, PERIOD, BASE

PATH = BASE + "/journals"


@pytest.fixture
def journals(ledger):
    for code in ("1001", "2001"):
        assert (
            ledger.post(
                BASE + "/ledger-accounts", json={**ACCOUNT, "code": code}
            ).status_code
            == 201
        )
    assert ledger.post(BASE + "/accounting-periods", json=PERIOD).status_code == 201
    assert (
        ledger.post(
            "/api/v1/users",
            json={
                "username": "reviewer",
                "password": "reviewer-pass-123",
                "roles": ["finance"],
            },
        ).status_code
        == 201
    )
    token = ledger.post(
        "/api/v1/auth/login",
        json={"username": "reviewer", "password": "reviewer-pass-123"},
    ).json()["token"]
    return ledger, {"Authorization": "Bearer " + token}


def payload(reference="J001"):
    return {
        "reference": reference,
        "journal_date": "2026-01-10",
        "note": "手工录入",
        "reason": "原始票据",
        "lines": [
            {"account_id": 1, "summary": "现金", "debit": "123.45", "credit": "0"},
            {"account_id": 2, "summary": "往来", "debit": "0", "credit": "123.45"},
        ],
    }


def create(client, reference="J001"):
    response = client.post(PATH, json=payload(reference))
    assert response.status_code == 201, response.text
    return response.json()


def action(client, record, name, reviewer=None):
    response = client.post(
        f'{PATH}/{record["id"]}/{name}',
        json={"version": record["version"], "reason": "核对依据"},
        headers=reviewer,
    )
    assert response.status_code == 200, response.text
    return response.json()


def posted(journals):
    client, reviewer = journals
    record = action(client, create(client), "submit")
    record = action(client, record, "approve", reviewer)
    return action(client, record, "post")


def test_full_lifecycle_snapshot_and_history(journals):
    client, reviewer = journals
    record = create(client)
    assert record["currency"] == "CNY" and record["total_debit"] == "123.45"
    assert record["lines"][0]["credit"] == "0.00"
    assert client.post(PATH, json=payload()).status_code == 409
    record = action(client, record, "submit")
    assert (
        client.post(
            f'{PATH}/{record["id"]}/approve',
            json={"version": record["version"], "reason": "自审"},
        ).status_code
        == 409
    )
    record = action(client, record, "approve", reviewer)
    record = action(client, record, "post")
    assert record["status"] == "posted" and record["version"] == 4
    for name in ("post", "cancel", "submit"):
        assert (
            client.post(
                f'{PATH}/{record["id"]}/{name}', json={"version": 4, "reason": "重复"}
            ).status_code
            == 409
        )
    assert (
        client.put(
            f'{PATH}/{record["id"]}', json={**payload(), "version": 4}
        ).status_code
        == 409
    )
    assert client.delete(f'{PATH}/{record["id"]}').status_code == 405
    history = client.get(f'{PATH}/{record["id"]}/changes').json()
    assert [h["action"] for h in history] == ["create", "submit", "approve", "post"]
    assert history[-1]["after"]["lines"] == record["lines"]
    assert history[2]["changed_by_name"] == "reviewer"
    assert client.get(PATH).json()[0] == record


@pytest.mark.parametrize(
    "field,value",
    [
        ("debit", "NaN"),
        ("debit", "1e2"),
        ("debit", "1.001"),
        ("debit", "-1"),
        ("debit", 123.45),
        ("debit", "1000000000000"),
        ("debit", "0"),
        ("credit", "1"),
        ("summary", " "),
    ],
)
def test_invalid_line_rejected(journals, field, value):
    client, _ = journals
    data = payload()
    data["lines"][0][field] = value
    assert client.post(PATH, json=data).status_code == 422
    assert client.get(PATH).json() == []


def test_unbalanced_unknown_period_and_account(journals):
    client, _ = journals
    data = payload()
    data["lines"][1]["credit"] = "123.44"
    assert client.post(PATH, json=data).status_code == 422
    assert (
        client.post(PATH, json={**payload(), "journal_date": "2026-02-01"}).status_code
        == 409
    )
    assert (
        client.post(PATH, json={**payload(), "journal_date": "2026-02-30"}).status_code
        == 422
    )
    data = payload()
    data["lines"][0]["account_id"] = 999
    assert client.post(PATH, json=data).status_code == 409
    assert client.post(PATH, json={**payload(), "currency": "USD"}).status_code == 422
    assert client.get(PATH).json() == []


def test_rejected_edit_versions_and_all_authors_cannot_review(journals):
    client, reviewer = journals
    record = action(client, create(client), "submit")
    record = action(client, record, "reject", reviewer)
    old_version = record["version"]
    record = client.put(
        f'{PATH}/{record["id"]}',
        json={**payload(), "version": old_version, "note": "补充"},
        headers=reviewer,
    ).json()
    assert record["status"] == "draft" and record["reviewed_by"] is None
    assert (
        client.put(
            f'{PATH}/{record["id"]}', json={**payload(), "version": old_version}
        ).status_code
        == 409
    )
    record = action(client, record, "submit")
    for headers in (None, reviewer):
        assert (
            client.post(
                f'{PATH}/{record["id"]}/approve',
                json={"version": record["version"], "reason": "审核"},
                headers=headers,
            ).status_code
            == 409
        )


def test_disabled_account_and_closed_period_checked_again(journals):
    client, reviewer = journals
    record = create(client)
    assert (
        client.put(
            BASE + "/ledger-accounts/1",
            json={
                "name": "现金停用",
                "is_active": False,
                "version": 1,
                "reason": "停用",
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            f'{PATH}/{record["id"]}/submit', json={"version": 1, "reason": "提交"}
        ).status_code
        == 409
    )
    assert (
        client.put(
            BASE + "/ledger-accounts/1",
            json={"name": "现金", "is_active": True, "version": 2, "reason": "恢复"},
        ).status_code
        == 200
    )
    record = action(client, record, "submit")
    record = action(client, record, "approve", reviewer)
    with orm_session(write=True) as db:
        db.get(AccountingPeriod, record["period_id"]).status = "closed"
    assert (
        client.post(
            f'{PATH}/{record["id"]}/post',
            json={"version": record["version"], "reason": "过账"},
        ).status_code
        == 409
    )
    assert client.get(PATH).json()[0]["status"] == "approved"


def test_reversal_is_draft_balanced_immutable_and_single_active(journals):
    client, reviewer = journals
    original = posted(journals)
    client.put(
        BASE + "/ledger-accounts/1",
        json={"name": "现金新名称", "is_active": False, "version": 1, "reason": "停用"},
    )
    reverse_input = {
        "version": original["version"],
        "reference": "REV001",
        "journal_date": "2026-01-20",
        "reason": "纠正误录",
    }
    response = client.post(f'{PATH}/{original["id"]}/reverse', json=reverse_input)
    assert response.status_code == 201, response.text
    reverse = response.json()
    assert reverse["status"] == "draft" and reverse["reversal_of_id"] == original["id"]
    assert reverse["lines"][0]["credit"] == original["lines"][0]["debit"]
    assert reverse["lines"][0]["account_name"] == original["lines"][0]["account_name"]
    assert (
        client.post(
            f'{PATH}/{original["id"]}/reverse',
            json={**reverse_input, "reference": "REV002"},
        ).status_code
        == 409
    )
    assert (
        client.put(
            f'{PATH}/{reverse["id"]}', json={**payload(), "version": 1}
        ).status_code
        == 409
    )
    reverse = action(client, reverse, "cancel")
    reverse = client.post(
        f'{PATH}/{original["id"]}/reverse',
        json={**reverse_input, "reference": "REV002"},
    ).json()
    reverse = action(client, reverse, "submit")
    reverse = action(client, reverse, "approve", reviewer)
    reverse = action(client, reverse, "post")
    assert reverse["status"] == "posted"
    originals = [row for row in client.get(PATH).json() if row["id"] == original["id"]]
    assert (
        originals[0]["lines"] == original["lines"]
        and originals[0]["reversal_journal_id"] == reverse["id"]
    )
    assert (
        client.post(
            f'{PATH}/{reverse["id"]}/reverse',
            json={**reverse_input, "reference": "CHAIN"},
        ).status_code
        == 409
    )


@pytest.mark.parametrize("kind", ["post", "update", "reverse"])
def test_concurrent_writes_do_not_duplicate(journals, kind):
    client, _ = journals
    record = posted(journals) if kind == "reverse" else create(client)
    if kind == "post":
        record = action(client, record, "submit")
        record = action(client, record, "approve", journals[1])
    gate = Barrier(2)

    def run(index):
        gate.wait()
        if kind == "update":
            return client.put(
                f'{PATH}/{record["id"]}',
                json={**payload(), "version": record["version"], "note": str(index)},
            ).status_code
        data = {"version": record["version"], "reason": "并发"}
        if kind == "reverse":
            data.update(reference=f"REV{index}", journal_date="2026-01-20")
        return client.post(f'{PATH}/{record["id"]}/{kind}', json=data).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        expected = [201, 409] if kind == "reverse" else [200, 409]
        assert sorted(pool.map(run, range(2))) == expected


@pytest.mark.parametrize("kind", ["create", "update", "post", "reverse"])
def test_audit_failure_rolls_back_entire_operation(journals, kind):
    client, reviewer = journals
    record = None if kind == "create" else create(client)
    if kind in ("post", "reverse"):
        record = action(client, record, "submit")
        record = action(client, record, "approve", reviewer)
        if kind == "reverse":
            record = action(client, record, "post")
    before = client.get(PATH).json()

    def fail(db, *_):
        if any(isinstance(item, JournalChange) for item in db.new):
            raise RuntimeError("模拟审计失败")

    event.listen(Session, "before_flush", fail)
    try:
        if kind == "create":
            response = client.post(PATH, json=payload())
        elif kind == "update":
            response = client.put(
                f'{PATH}/{record["id"]}',
                json={**payload(), "version": record["version"], "note": "失败修改"},
            )
        else:
            data = {"version": record["version"], "reason": "失败"}
            if kind == "reverse":
                data.update(reference="REV", journal_date="2026-01-20")
            response = client.post(f'{PATH}/{record["id"]}/{kind}', json=data)
        assert response.status_code == 500
    finally:
        event.remove(Session, "before_flush", fail)
    assert client.get(PATH).json() == before


def test_permissions_options_and_migration(journals, remove_journal_schema):
    client, reviewer = journals
    assert client.get(PATH + "/options", headers=reviewer).status_code == 200
    assert len(client.get(PATH + "/options").json()["accounts"]) == 2
    assert (
        client.post(
            "/api/v1/users",
            json={
                "username": "buyer",
                "password": "buyer-password-123",
                "roles": ["buyer"],
            },
        ).status_code
        == 201
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"username": "buyer", "password": "buyer-password-123"},
    ).json()["token"]
    headers = {"Authorization": "Bearer " + token}
    record = create(client)
    for name in ("submit", "approve", "reject", "post", "cancel", "reverse"):
        data = {"version": 1, "reason": "越权"}
        if name == "reverse":
            data.update(reference="REV", journal_date="2026-01-20")
        assert (
            client.post(
                f'{PATH}/{record["id"]}/{name}', json=data, headers=headers
            ).status_code
            == 403
        )
    assert client.get(PATH, headers=headers).status_code == 403
    assert client.get(PATH + "/options", headers=headers).status_code == 403
    with connection() as db:
        remove_journal_schema(db)
        db.execute("PRAGMA user_version=40")
    migrate()
    migrate()
    with connection() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 79
        assert db.execute("SELECT count(*) FROM ledger_accounts").fetchone()[0] == 2
        assert (
            db.execute(
                "SELECT count(*) FROM role_permissions WHERE permission_code='journal.post'"
            ).fetchone()[0]
            == 2
        )
    assert client.get(PATH).json() == []


def test_options_and_read_only_permissions_are_independent(journals):
    client, _ = journals
    record = create(client)
    for name, permissions in [
        ("creator", ["journal.create"]),
        ("observer", ["journal.view"]),
    ]:
        assert (
            client.post(
                "/api/v1/roles",
                json={"code": name, "label": name, "permissions": permissions},
            ).status_code
            == 201
        )
        assert (
            client.post(
                "/api/v1/users",
                json={
                    "username": name,
                    "password": "permission-pass-123",
                    "roles": [name],
                },
            ).status_code
            == 201
        )
        token = client.post(
            "/api/v1/auth/login",
            json={"username": name, "password": "permission-pass-123"},
        ).json()["token"]
        headers = {"Authorization": "Bearer " + token}
        assert client.get(PATH + "/options", headers=headers).status_code == (
            200 if name == "creator" else 403
        )
        assert client.get(PATH, headers=headers).status_code == (
            403 if name == "creator" else 200
        )
        assert client.get(
            f'{PATH}/{record["id"]}/changes', headers=headers
        ).status_code == (403 if name == "creator" else 200)
        assert (
            client.post(
                f'{PATH}/{record["id"]}/submit',
                json={"version": 1, "reason": "越权"},
                headers=headers,
            ).status_code
            == 403
        )
    assert (
        client.post(PATH, json=payload("READONLY"), headers=headers).status_code == 403
    )


def test_post_rechecks_account_and_freezes_snapshot(journals):
    client, reviewer = journals
    record = action(client, create(client), "submit")
    record = action(client, record, "approve", reviewer)
    update = {
        "name": "过账前名称",
        "is_active": False,
        "version": 1,
        "reason": "资料修订",
    }
    assert client.put(BASE + "/ledger-accounts/1", json=update).status_code == 200
    assert (
        client.post(
            f'{PATH}/{record["id"]}/post',
            json={"version": record["version"], "reason": "过账"},
        ).status_code
        == 409
    )
    assert (
        client.put(
            BASE + "/ledger-accounts/1",
            json={**update, "version": 2, "is_active": True},
        ).status_code
        == 200
    )
    record = action(client, record, "post")
    assert record["lines"][0]["account_name"] == "过账前名称"
    assert (
        client.put(
            BASE + "/ledger-accounts/1",
            json={**update, "version": 3, "name": "过账后名称"},
        ).status_code
        == 200
    )
    assert client.get(PATH).json()[0]["lines"] == record["lines"]
    assert (
        client.post(
            f'{PATH}/{record["id"]}/reverse',
            json={
                "version": record["version"],
                "reference": "EARLY",
                "journal_date": "2026-01-09",
                "reason": "提前",
            },
        ).status_code
        == 409
    )
