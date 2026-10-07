"""验证服务端预警事件的状态基线、来源快照与事务回滚。"""

from approval_test_helpers import approve_document
import os
import sqlite3
from threading import Event

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core.database import migrate
from app.core.models import InventoryWarningEvent, InventoryWarningObservation
from app.core.orm import orm_session
from app.inventory.warning_events import scan_warning_events
from app.main import app


@pytest.fixture
def erp(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'warning-events.db'))
    with TestClient(app, client=('127.0.0.1', 12000), raise_server_exceptions=False) as client:
        root = '/api/v1'
        client.post(root + '/setup/admin', json={'username': 'admin', 'password': 'secure-pass-123'})
        token = client.post(root + '/auth/login', json={
            'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
        admin = {'Authorization': 'Bearer ' + token}

        def api(method, path, data=None, status=200, headers=admin):
            result = client.request(method, root + path, json=data, headers=headers)
            assert result.status_code == status, result.text
            return result.json()

        material = api('POST', '/materials', {'sku': 'EVENT', 'name': '事件物料', 'unit': '件'}, 201)['id']
        yield client, api, material, admin


def rule(erp, *, version=0, threshold='2', enabled=True):
    return erp[1]('PUT', f'/inventory/warnings/rules/1/{erp[2]}', {
        'version': version, 'threshold': threshold, 'enabled': enabled, 'reason': '库存事件测试'})


def inbound(erp, quantity):
    row = erp[1]('POST', '/warehouse-inbounds', {'warehouse_id': 1, 'reason': 'other',
        'note': '库存事件来源', 'lines': [{'material_id': erp[2], 'quantity': quantity}]}, 201)
    approve_document(erp[0], erp[3], 'WarehouseInbound', row['id'])
    erp[1]('POST', f'/warehouse-inbounds/{row["id"]}/post')
    return row


def events(erp, suffix=''):
    return erp[1]('GET', '/inventory/warnings/events' + suffix)


def test_state_transitions_are_deduplicated_and_history_keeps_original_source(erp):
    _, api, material, _ = erp
    assert events(erp)['events'] == []
    rule(erp)
    assert scan_warning_events() == 1
    first = events(erp)['events'][0]
    assert (first['previous_status'], first['status'], first['quantity']) == (None, 'out_of_stock', '0')
    assert first['sku'] == 'EVENT' and first['rule_version'] == 1
    assert first['observed_at'] and first['created_at']
    assert scan_warning_events() == 0

    inbound(erp, '1')
    assert scan_warning_events() == 0  # 缺货恢复为低库存不会重复报警。
    assert events(erp)['events'][0]['id'] == first['id']
    inbound(erp, '1')
    assert scan_warning_events() == 0
    rule(erp, version=1, threshold='3')
    assert scan_warning_events() == 1
    low = events(erp)['events'][0]
    assert (low['previous_status'], low['status'], low['shortage']) == ('normal', 'low', '1.000')
    assert low['rule_version'] == 2
    rule(erp, version=2, threshold='3', enabled=False)
    assert scan_warning_events() == 0
    rule(erp, version=3, threshold='3')
    assert scan_warning_events() == 1
    assert events(erp)['events'][0]['previous_status'] == 'disabled'

    api('PUT', f'/materials/{material}', {'sku': 'EVENT', 'name': '改名后的物料',
        'unit': '件', 'version': 1, 'reason': '核对历史名称'})
    latest = events(erp)['events'][0]
    assert latest['material_name'] == '事件物料'  # 历史来源快照不随基础资料改名。
    page = events(erp, '?limit=1')
    assert len(page['events']) == 1 and page['next_before_id'] == latest['id']
    assert events(erp, f'?limit=1&before_id={latest["id"]}')['events'][0]['id'] == low['id']


def test_escalation_permission_scope_and_failed_write_roll_back(erp):
    _, api, _, _ = erp
    first = inbound(erp, '1')
    rule(erp)
    assert scan_warning_events() == 1
    opening = events(erp)['events'][0]
    api('GET', '/inventory/warnings/events', status=401, headers={})
    api('GET', '/inventory/warnings/events?warehouse_id=999', status=404)
    api('GET', '/inventory/warnings/events?limit=0', status=422)
    assert events(erp, '?warehouse_id=1')['events'][0]['id'] == opening['id']

    def fail(session, _):
        if any(isinstance(row, InventoryWarningEvent) for row in session.new):
            raise RuntimeError('模拟预警事件写后失败')

    second = inbound(erp, '1')
    assert scan_warning_events() == 0
    approve_document(erp[0], erp[3], 'WarehouseInbound', second['id'], intent='reverse', reason='退回误收')
    api('POST', f'/warehouse-inbounds/{second["id"]}/reverse', {'reason': '退回误收'}, 201)
    event.listen(Session, 'after_flush', fail)
    try:
        with pytest.raises(RuntimeError, match='模拟预警事件写后失败'):
            scan_warning_events()
    finally:
        event.remove(Session, 'after_flush', fail)
    with orm_session() as db:
        assert db.get(InventoryWarningObservation, opening['rule_id']).status == 'normal'
        assert len(db.scalars(select(InventoryWarningEvent)).all()) == 1
    assert scan_warning_events() == 1
    assert events(erp)['events'][0]['previous_status'] == 'normal'
    approve_document(erp[0], erp[3], 'WarehouseInbound', first['id'], intent='reverse', reason='退回误收')
    api('POST', f'/warehouse-inbounds/{first["id"]}/reverse', {'reason': '退回误收'}, 201)
    assert scan_warning_events() == 1
    assert events(erp)['events'][0]['previous_status'] == 'low'
    assert events(erp)['events'][0]['status'] == 'out_of_stock'


def test_v67_upgrade_adds_event_tables_without_changing_warning_rules(erp):
    rule(erp)
    with sqlite3.connect(os.environ['NEXORA_DB_PATH']) as db:
        previous = db.execute('SELECT * FROM inventory_warning_rules').fetchall()
        db.execute('DROP TABLE inventory_warning_events')
        db.execute('DROP TABLE inventory_warning_observations')
        db.execute('PRAGMA user_version = 67')
    migrate()
    migrate()
    with sqlite3.connect(os.environ['NEXORA_DB_PATH']) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 93
        assert db.execute('SELECT * FROM inventory_warning_rules').fetchall() == previous
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    assert scan_warning_events() == 1


def test_event_history_is_warehouse_scoped_and_requires_inventory_view(erp):
    _, api, material, _ = erp
    other = api('POST', '/warehouses', {'code': 'EVENT-2', 'name': '第二事件仓'}, 201)['id']
    rule(erp)
    api('PUT', f'/inventory/warnings/rules/{other}/{material}', {
        'version': 0, 'threshold': '2', 'enabled': True, 'reason': '第二仓库库存事件'})
    assert scan_warning_events() == 2
    assert {row['warehouse_id'] for row in events(erp)['events']} == {1, other}
    assert [row['warehouse_id'] for row in events(erp, f'?warehouse_id={other}')['events']] == [other]
    api('POST', '/users', {'username': 'accountant', 'password': 'secure-pass-123', 'roles': ['finance']}, 201)
    token = api('POST', '/auth/login', {'username': 'accountant', 'password': 'secure-pass-123'})['token']
    api('GET', '/inventory/warnings/events', status=403, headers={'Authorization': 'Bearer ' + token})


def test_server_startup_scans_existing_abnormal_rules_without_a_desktop(erp, monkeypatch):
    rule(erp)
    scanned = Event()
    from app.inventory import warning_events
    original = warning_events.scan_warning_events

    def observed_scan():
        result = original()
        scanned.set()
        return result

    monkeypatch.setattr(warning_events, 'scan_warning_events', observed_scan)
    with TestClient(app, client=('127.0.0.1', 12001)):
        assert scanned.wait(3)
    assert len(events(erp)['events']) == 1
