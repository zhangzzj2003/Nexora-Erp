"""物料绑定、待完善供应商、资料审计和旧库升级的行为链验收。"""
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.main import app
from app.core.database import connection, migrate
from app.core.models import MaterialChange
from app.catalog.supplier_profiles import PROFILE_FIELDS


@pytest.fixture
def client(monkeypatch, tmp_path):
    # 每条测试使用临时库，绝不向本机 ERP 正式服务写测试供应商。
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'supplier-profile.db'))
    with TestClient(app, client=('127.0.0.1', 12000), raise_server_exceptions=False) as client:
        account = {'username': 'admin', 'password': 'secure-pass-123'}
        assert client.post('/api/v1/setup/admin', json=account).status_code == 201
        token = client.post('/api/v1/auth/login', json=account).json()['token']
        client.headers['Authorization'] = f'Bearer {token}'
        yield client


def material(client, choices=None):
    payload = {'name': '测试螺丝', 'unit': '个', 'category_code': 'HW-FA', 'brand': '原制造商'}
    if choices is not None:
        payload['suppliers'] = choices
    return client.post('/api/v1/materials', json=payload)


def detail(client, row):
    return client.get(f"/api/v1/materials/{row['id']}?include_suppliers=true").json()


def test_create_bind_complete_and_audit(client):
    old = client.post('/api/v1/suppliers', json={'name': '已有供应商'}).json()
    row = material(client, [{'supplier_id': old['id']}, {'name': ' 新供应商 '}]).json()
    suppliers = client.get('/api/v1/suppliers').json()
    new = next(item for item in suppliers if item['name'] == '新供应商')
    assert new['profile_status'] == 'pending'
    assert all(new[field] == '' for field in PROFILE_FIELDS)
    assert row['brand'] == '原制造商'
    assert detail(client, row)['supplier_ids'] == sorted([old['id'], new['id']])
    # 补齐资料只修改同一个档案，名称和供货关系保持不变。
    path = f"/api/v1/suppliers/{new['id']}"
    partial = client.put(path, json={**new, 'phone': ' 13800000000 ', 'reason': '补电话'}).json()
    assert partial['profile_status'] == 'pending' and partial['version'] == 2
    complete = client.put(path, json={'name': new['name'], 'contact_name': ' 张工 ',
        'address': ' 深圳市测试地址 ', 'version': 2, 'reason': '完善联系资料'}).json()
    assert complete['phone'] == '13800000000'
    assert complete['contact_name'] == '张工' and complete['profile_status'] == 'complete'
    listed = client.post('/api/v1/suppliers/query', json={'query': '新供'}).json()['items'][0]
    assert listed == complete
    changes = client.get(f'{path}/changes').json()
    assert changes[0]['before'] == partial and changes[0]['after'] == complete
    assert changes[-1]['reason'] == '物料绑定时创建待完善供应商'
    assert detail(client, row)['supplier_ids'] == sorted([old['id'], new['id']])
    # 清空必填资料后自然恢复待完善，不能靠传状态字段绕过完善条件。
    response = client.put(path, json={'name': new['name'], 'phone': '', 'version': 3,
                                    'reason': '电话待核实', 'profile_status': 'complete'})
    assert response.json()['profile_status'] == 'pending'


def test_name_reuse_and_concurrent_creation(client):
    existing = client.post('/api/v1/suppliers', json={'name': 'Acme', 'contact_name': '原联系人'}).json()
    first = material(client, [{'name': ' acme '}, {'name': 'Acme'}, {'supplier_id': existing['id']}]).json()
    assert detail(client, first)['supplier_ids'] == [existing['id']]
    assert client.get('/api/v1/suppliers').json() == [existing]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: material(client, [{'name': '并发新供应商'}]), range(2)))
    assert all(result.status_code == 201 for result in results)
    ids = [detail(client, result.json())['supplier_ids'][0] for result in results]
    assert ids[0] == ids[1]
    assert len(client.get('/api/v1/suppliers').json()) == 2
    assert len(client.get(f'/api/v1/suppliers/{ids[0]}/changes').json()) == 1


def test_ambiguous_legacy_names_require_explicit_selection(client):
    one = client.post('/api/v1/suppliers', json={'name': 'ACME'}).json()
    client.post('/api/v1/suppliers', json={'name': 'acme'})
    assert material(client, [{'name': 'Acme'}]).status_code == 409
    assert material(client, [{'name': 'ACME'}]).status_code == 201
    assert material(client, [{'supplier_id': one['id']}]).status_code == 201


def test_failed_save_rolls_back_supplier_binding_audits_and_code(client):
    assert material(client, [{'name': '失败新供应商'}, {'supplier_id': 99999}]).status_code == 404
    assert client.get('/api/v1/suppliers').json() == []
    assert client.get('/api/v1/materials').json() == []
    assert client.get('/api/v1/supplier-changes').json() == []
    def fail_audit(db, *_):
        if any(isinstance(row, MaterialChange) for row in db.new):
            raise RuntimeError('模拟物料审计失败')
    event.listen(Session, 'before_flush', fail_audit)
    try:
        assert material(client, [{'name': '审计失败供应商'}]).status_code == 500
    finally:
        event.remove(Session, 'before_flush', fail_audit)
    assert client.get('/api/v1/suppliers').json() == []
    row = material(client, [{'name': '成功供应商'}]).json()
    assert row['sku'] == 'HW-FA-000001'


def test_edit_unbind_legacy_compatibility_and_stale_version(client):
    row = material(client, [{'name': '甲厂'}]).json()
    path = f"/api/v1/materials/{row['id']}"
    supplier = client.post('/api/v1/suppliers', json={'name': '乙厂'}).json()
    bind_path = f"/api/v1/suppliers/{supplier['id']}/materials/{row['id']}"
    assert client.put(bind_path).status_code == 204
    latest = detail(client, row)
    assert latest['version'] == 2
    assert client.put(bind_path).status_code == 204
    assert detail(client, row)['version'] == 2  # 幂等绑定不产生虚假版本与审计。
    stale = client.put(path, json={**row, 'suppliers': [{'name': '过期新供应商'}]})
    assert stale.status_code == 409
    assert len(client.get('/api/v1/suppliers').json()) == 2
    # 旧调用未传 suppliers 时仍保留全部绑定。
    updated = client.put(path, json={'name': row['name'], 'unit': '件', 'version': 2}).json()
    assert detail(client, updated)['supplier_ids'] == latest['supplier_ids']
    assert client.delete(bind_path).status_code == 204
    assert detail(client, row)['version'] == 4
    cleared = client.put(path, json={'name': row['name'], 'unit': '件', 'version': 4, 'suppliers': []})
    assert cleared.status_code == 200 and detail(client, row)['supplier_ids'] == []
    # 解绑只改关系，供应商档案仍可在管理页完善。
    assert len(client.get('/api/v1/suppliers').json()) == 2
    with connection() as db:
        import json
        changes = db.execute('SELECT before_json,after_json FROM material_changes ORDER BY id DESC').fetchall()
        assert json.loads(changes[0]['before_json'])['supplier_ids']
        assert json.loads(changes[0]['after_json'])['supplier_ids'] == []


@pytest.mark.parametrize('choices', [[{}], [{'supplier_id': True}], [{'supplier_id': -1}],
    [{'name': ' '}], [{'name': '字' * 121}], [{'name': '甲', 'supplier_id': 1}],
    [{'name': '甲', 'profile_status': 'complete'}], [{'name': '甲'}] * 21])
def test_invalid_binding_rejected_before_writes(client, choices):
    assert material(client, choices).status_code == 422
    assert client.get('/api/v1/suppliers').json() == []


def test_viewer_cannot_create_pending_supplier_through_material(client):
    client.post('/api/v1/users', json={'username': 'viewer', 'password': 'secure-pass-123', 'roles': ['viewer']})
    token = client.post('/api/v1/auth/login', json={'username': 'viewer', 'password': 'secure-pass-123'}).json()['token']
    client.headers['Authorization'] = f'Bearer {token}'
    assert material(client, [{'name': '越权新供应商'}]).status_code == 403
    assert client.get('/api/v1/suppliers').json() == []


def test_v85_migration_preserves_supplier_ids_bindings_and_history(client):
    row = material(client, [{'name': '历史供应商'}]).json()
    ids = detail(client, row)['supplier_ids']
    with connection() as db:
        old_changes = [tuple(item) for item in db.execute('SELECT * FROM supplier_changes')]
        for key in PROFILE_FIELDS:
            db.execute(f'ALTER TABLE suppliers DROP COLUMN {key}')
        db.execute('PRAGMA user_version = 85')
    migrate()
    migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 89
        assert [tuple(item) for item in db.execute('SELECT * FROM supplier_changes')] == old_changes
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    assert detail(client, row)['supplier_ids'] == ids
    supplier = client.get(f'/api/v1/suppliers/{ids[0]}').json()
    assert supplier['name'] == '历史供应商' and supplier['version'] == 1
    assert all(supplier[field] == '' for field in PROFILE_FIELDS)
    assert supplier['profile_status'] == 'pending'
