"""供应商和仓库档案的版本、审计与旧库升级。"""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core.database import connection, migrate
from app.core.models import SupplierChange, WarehouseChange
from app.core.orm import orm_session
from app.main import app


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'master-audit.db'))
    with TestClient(app, client=('127.0.0.1', 12000), raise_server_exceptions=False) as client:
        account = {'username': 'admin', 'password': 'secure-pass-123'}
        assert client.post('/api/v1/setup/admin', json=account).status_code == 201
        token = client.post('/api/v1/auth/login', json=account).json()['token']
        client.headers['Authorization'] = f'Bearer {token}'
        yield client


@pytest.mark.parametrize('resource,first,second', [
    ('suppliers', {'name': '甲供应商'}, {'name': '乙供应商'}),
    ('warehouses', {'code': 'EAST', 'name': '东仓'}, {'code': 'WEST', 'name': '西仓'}),
])
def test_master_data_change_versions_and_deleted_history(client, resource, first, second):
    created = client.post(f'/api/v1/{resource}', json=first).json()
    record_id = created['id']
    assert created['version'] == 1
    path = f'/api/v1/{resource}/{record_id}'
    assert client.get(path).json() == created
    edit = {**second, 'version': 1, 'reason': '核对纸质档案后修正'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: client.put(path, json=edit).status_code, range(2)))
    assert sorted(statuses) == [200, 409]
    assert client.put(path, json={**second, 'version': 2, 'reason': ''}).status_code == 422
    assert client.delete(f'{path}?version=1').status_code == 409
    assert client.delete(f'{path}?version=2').status_code == 204
    assert client.get(path).status_code == 404
    changes = client.get(f'{path}/changes').json()
    assert [row['action'] for row in changes] == ['delete', 'update', 'create']
    assert changes[0]['before']['version'] == 2 and changes[0]['after'] is None
    assert changes[1]['before'] == created
    assert changes[1]['after']['version'] == 2
    assert changes[1]['reason'] == '核对纸质档案后修正'
    assert all(row['changed_by_name'] == 'admin' for row in changes)
    change_path = '/api/v1/supplier-changes' if resource == 'suppliers' else '/api/v1/warehouse-changes'
    assert [row['id'] for row in client.get(change_path, params={'limit': 2}).json()] == [changes[0]['id'], changes[1]['id']]
    assert [row['id'] for row in client.get(change_path,
        params={'limit': 2, 'before_id': changes[1]['id']}).json()] == [changes[2]['id']]


@pytest.mark.parametrize('resource,payload,changed,model', [
    ('suppliers', {'name': '原供应商'}, {'name': '改名供应商'}, SupplierChange),
    ('warehouses', {'code': 'A', 'name': '原仓'}, {'code': 'B', 'name': '改名仓'}, WarehouseChange),
])
def test_audit_failure_rolls_back_master_data(client, resource, payload, changed, model):
    path = f'/api/v1/{resource}'
    def fail_audit(db, *_):
        if any(isinstance(row, model) for row in db.new):
            raise RuntimeError('模拟审计写入失败')
    event.listen(Session, 'before_flush', fail_audit)
    try:
        assert client.post(path, json=payload).status_code == 500
    finally:
        event.remove(Session, 'before_flush', fail_audit)
    assert not any(all(row.get(key) == value for key, value in payload.items())
                   for row in client.get(path).json())
    created = client.post(path, json=payload).json()
    edit = {**changed, 'version': 1, 'reason': '更正资料'}
    event.listen(Session, 'before_flush', fail_audit)
    try:
        assert client.put(f"{path}/{created['id']}", json=edit).status_code == 500
    finally:
        event.remove(Session, 'before_flush', fail_audit)
    assert client.get(f"{path}/{created['id']}").json() == created
    with orm_session() as db:
        assert len(list(db.scalars(select(model)))) == 1


def test_v61_upgrade_preserves_master_data_without_inventing_history(client, remove_equipment_hour_schema):
    supplier = client.post('/api/v1/suppliers', json={'name': '历史供应商'}).json()['id']
    warehouse = client.post('/api/v1/warehouses', json={'code': 'OLD', 'name': '历史仓'}).json()['id']
    with connection() as db:
        remove_equipment_hour_schema(db)
        db.execute('DROP TABLE supplier_changes')
        db.execute('DROP TABLE warehouse_changes')
        db.execute('ALTER TABLE suppliers DROP COLUMN version')
        db.execute('ALTER TABLE warehouses DROP COLUMN version')
        db.execute('PRAGMA user_version = 61')
    migrate()
    migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 66
        assert db.execute('SELECT version FROM suppliers WHERE id=?', (supplier,)).fetchone()[0] == 1
        assert db.execute('SELECT version FROM warehouses WHERE id=?', (warehouse,)).fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM supplier_changes').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM warehouse_changes').fetchone()[0] == 0


def test_viewer_sees_history_but_cannot_change_master_data(client):
    row = client.post('/api/v1/suppliers', json={'name': '可查看供应商'}).json()
    client.post('/api/v1/users', json={'username': 'viewer', 'password': 'secure-pass-123', 'roles': ['viewer']})
    token = client.post('/api/v1/auth/login', json={'username': 'viewer', 'password': 'secure-pass-123'}).json()['token']
    client.headers['Authorization'] = f'Bearer {token}'
    assert client.get(f"/api/v1/suppliers/{row['id']}/changes").status_code == 200
    assert client.get('/api/v1/supplier-changes').status_code == 200
    assert client.get('/api/v1/warehouse-changes').status_code == 200
    assert client.put(f"/api/v1/suppliers/{row['id']}",
                      json={'name': '越权', 'version': 1, 'reason': '测试'}).status_code == 403
    assert client.delete(f"/api/v1/suppliers/{row['id']}?version=1").status_code == 403
