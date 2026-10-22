"""待生产汇总来源与定制要求：审批固定、余额守恒以及旧库兼容。"""
from app.core.database import connection, migrate
from app.core.models import ProductionPlanLine
from app.core.orm import orm_session
from approval_test_helpers import approve_document
from test_production_plans import seeded, context, draft, create, approved, release_input, BASE


def test_pending_demands_only_approved_balance_and_cancelled_order_returns(context):
    client, admin, *_ = context
    create(context)  # 未送审计划不能提醒主管开工。
    first = approved(context)
    second = approved(context)
    assert {row['id'] for row in client.get(BASE + '/pending-demands', headers=admin).json()} == {first['id'], second['id']}
    released = client.post(BASE + f'/{first["id"]}/release', headers=admin, json=release_input(first, '10'))
    assert released.status_code == 201, released.text
    assert [row['id'] for row in client.get(BASE + '/pending-demands', headers=admin).json()] == [second['id']]
    order_id = released.json()['releases'][0]['work_order_id']
    cancelled = client.post(f'/api/v1/work-orders/{order_id}/cancel', headers=admin)
    assert cancelled.status_code == 200, cancelled.text
    restored = client.get(BASE + '/pending-demands', headers=admin).json()
    assert {row['id'] for row in restored} == {first['id'], second['id']}
    assert restored[0]['lines'][0]['unreleased_quantity'] == '10.000'
    partial = client.post(BASE + f'/{second["id"]}/release', headers=admin, json=release_input(second, '4'))
    assert partial.status_code == 201, partial.text
    assert next(row for row in client.get(BASE + '/pending-demands', headers=admin).json() if row['id'] == second['id'])['lines'][0]['unreleased_quantity'] == '6.000'


def test_requirements_fixed_in_plan_and_work_order_approval(context):
    client, admin, *_ = context
    payload = draft(context)
    payload['lines'][0]['production_requirements'] = '  甲公司 Logo；白色；礼盒包装  '
    row = approved(context, payload)
    requirement = '甲公司 Logo；白色；礼盒包装'
    assert row['lines'][0]['production_requirements'] == requirement
    evidence = client.get(f'/api/v1/system/document-approvals/ProductionPlan/{row["id"]}', headers=admin).json()
    summary = next(item for item in evidence['summary'] if item['label'] == '计划产品')
    assert summary['production_plan_line']['production_requirements'] == requirement
    result = client.post(BASE + f'/{row["id"]}/release', headers=admin, json=release_input(row))
    assert result.status_code == 201, result.text
    work_id = result.json()['releases'][0]['work_order_id']
    order = next(item for item in client.get('/api/v1/work-orders', headers=admin).json() if item['id'] == work_id)
    assert order['production_schedule']['production_requirements'] == requirement
    work = client.get(f'/api/v1/system/document-approvals/WorkOrder/{work_id}', headers=admin).json()
    assert {'label': '生产要求', 'value': requirement} in work['summary']
    # 即使绕过正常只读界面篡改要求，批准指纹仍会阻止按旧批准继续生成。
    with orm_session(write=True) as db:
        db.get(ProductionPlanLine, row['lines'][0]['id']).production_requirements = '乙公司 Logo；黑色'
    current = client.get(BASE + f'/{row["id"]}', headers=admin).json()
    assert client.post(BASE + f'/{row["id"]}/release', headers=admin, json=release_input(current)).status_code == 409


def test_requirements_validation_and_demand_permissions(context):
    client, admin, _, _, viewer, _ = context
    payload = draft(context)
    for invalid in (None, 42, '色' * 501):
        payload['lines'][0]['production_requirements'] = invalid
        assert client.post(BASE, headers=admin, json=payload).status_code == 422
    assert client.get(BASE + '/pending-demands', headers=viewer).status_code == 403
    assert client.get(BASE + '/pending-demands').status_code == 401


def test_v108_migration_preserves_approved_plan_fingerprint(context):
    client, admin, *_ = context
    row = approved(context)
    # 隔离库退回 v108 的列布局；迁移不能给旧计划伪造生产要求或撤销原批准。
    with connection() as db:
        db.execute('ALTER TABLE production_plan_lines DROP COLUMN production_requirements')
        db.execute('PRAGMA user_version=108')
    migrate(); migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 112
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    current = client.get(BASE + f'/{row["id"]}', headers=admin).json()
    assert current['lines'][0]['production_requirements'] == ''
    assert client.post(BASE + f'/{row["id"]}/release', headers=admin, json=release_input(current)).status_code == 201


def test_v109_failure_rolls_back_added_column_and_version(context, monkeypatch):
    from contextlib import contextmanager
    import sqlite3
    import pytest
    from app.core import database
    with connection() as db:
        db.execute('ALTER TABLE production_plan_lines DROP COLUMN production_requirements')
        db.execute('PRAGMA user_version=108')
    original = database.connection

    @contextmanager
    def failing_connection():
        with original() as db:
            # 在加列之后拒绝版本更新，证明 DDL 与版本号一起回滚。
            db.set_authorizer(lambda operation, name, value, *_: sqlite3.SQLITE_DENY
                if operation == sqlite3.SQLITE_PRAGMA and name == 'user_version' and value == '109' else sqlite3.SQLITE_OK)
            yield db
    monkeypatch.setattr(database, 'connection', failing_connection)
    with pytest.raises(sqlite3.DatabaseError):
        migrate()
    with original() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 108
        assert 'production_requirements' not in {row[1] for row in db.execute('PRAGMA table_info(production_plan_lines)')}
