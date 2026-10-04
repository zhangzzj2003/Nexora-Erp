"""物料分类、编号、资料回读、版本冲突和旧库升级的真实接口验收。"""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.main import app
from app.core.database import connection, migrate
from app.core.orm import orm_session
from app.core.models import MaterialChange, MaterialCodeSequence
from app.catalog.material_rules import DETAIL_FIELDS, MATERIAL_CATEGORIES


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'material.db'))
    with TestClient(app, client=('127.0.0.1', 12000), raise_server_exceptions=False) as client:
        account = {'username': 'admin', 'password': 'secure-pass-123'}
        assert client.post('/api/v1/setup/admin', json=account).status_code == 201
        token = client.post('/api/v1/auth/login', json=account).json()['token']
        client.headers['Authorization'] = f'Bearer {token}'
        yield client


def input_data(category='EL-SR'):
    return dict(name='贴片电阻', unit='个', category_code=category, specification='10kΩ ±1% 0.1W',
        package='0603', brand='测试品牌', manufacturer_part_number='RC0603-10K',
        electrical_value='10kΩ', tolerance='±1%', rated_voltage='50V', rated_power='0.1W',
        temperature_range='-40℃～85℃', compliance='RoHS', notes='无铅、卷带包装')


def create(client, payload=None):
    response = client.post('/api/v1/materials', json=payload or input_data())
    assert response.status_code == 201, response.text
    return response.json()


def test_full_details_roundtrip_and_independent_category_codes(client):
    assert client.get('/api/v1/material-categories').json() == MATERIAL_CATEGORIES
    first = create(client, {key: f' {value} ' for key, value in input_data().items()})
    assert first == dict(id=first['id'], sku='EL-SR-000001', version=1, **input_data())
    assert create(client)['sku'] == 'EL-SR-000002'
    for code in ('EL-SC', 'EL-TR', 'EL-TC', 'EL-IC', 'PL-OT', 'HW-OT'):
        assert create(client, input_data(code))['sku'] == f'{code}-000001'
    assert first in client.get('/api/v1/materials').json()
    assert client.get(f"/api/v1/materials/{first['id']}").json() == first
    assert client.get('/api/v1/materials/999999').status_code == 404


def test_concurrent_allocation_delete_nonreuse_and_legacy_collision(client):
    # 多个请求并发写同一子类，不能获得相同编码。
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda _: create(client), range(4)))
    assert sorted(row['sku'] for row in rows) == [f'EL-SR-{number:06d}' for number in range(1, 5)]
    for row in rows:
        assert client.delete(f"/api/v1/materials/{row['id']}").status_code == 204
    assert create(client)['sku'] == 'EL-SR-000005'
    legacy = create(client, dict(sku='EL-SR-000099', name='旧接口物料', unit='件'))
    assert client.delete(f"/api/v1/materials/{legacy['id']}").status_code == 204
    assert create(client)['sku'] == 'EL-SR-000100'
    with orm_session() as db:
        assert len(list(db.scalars(select(MaterialChange).where(MaterialChange.action == 'delete')))) == 5


def test_edit_versions_fixed_code_and_partial_preservation(client):
    row = create(client)
    path = f"/api/v1/materials/{row['id']}"
    payload = dict(name='改名', unit='个', version=1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(lambda _: client.put(path, json=payload).status_code, range(2)))
    assert sorted(codes) == [200, 409]
    current = client.get('/api/v1/materials').json()[0]
    assert current['specification'] == row['specification'] and current['version'] == 2
    assert client.put(path, json=dict(payload, version=2, sku='NEW')).status_code == 409
    assert client.put(path, json=dict(name='改名', unit='个')).status_code == 409
    updated = client.put(path, json=dict(payload, version=2, category_code='EL-SC', notes='', reason='修正分类')).json()
    assert updated['sku'] == row['sku'] and updated['category_code'] == 'EL-SC' and updated['notes'] == ''
    with orm_session() as db:
        changes = list(db.scalars(select(MaterialChange).order_by(MaterialChange.id)))
        assert [change.action for change in changes] == ['create', 'update', 'update']
        assert changes[-1].reason == '修正分类' and changes[-1].changed_by == 1
        assert json.loads(changes[-1].before_json)['category_code'] == 'EL-SR'
        assert json.loads(changes[-1].after_json)['version'] == 3


@pytest.mark.parametrize('bad', [dict(category_code='EL'), dict(category_code='EL-UNKNOWN'),
    dict(category_code=''), dict(sku='CUSTOM'), dict(name='  '), dict(unit='  '),
    dict(package='字' * 81), dict(notes='字' * 1001), dict(version=True)])
def test_invalid_input_does_not_consume_number(client, bad):
    assert client.post('/api/v1/materials', json={**input_data(), **bad}).status_code == 422
    assert create(client)['sku'] == 'EL-SR-000001'


def test_audit_failure_rolls_back_code_and_material(client):
    def fail_audit(db, *_):
        if any(isinstance(row, MaterialChange) for row in db.new):
            raise RuntimeError('模拟审计保存失败')
    event.listen(Session, 'before_flush', fail_audit)
    try:
        assert client.post('/api/v1/materials', json=input_data()).status_code == 500
    finally:
        event.remove(Session, 'before_flush', fail_audit)
    assert client.get('/api/v1/materials').json() == []
    with orm_session() as db:
        assert list(db.scalars(select(MaterialCodeSequence))) == []
        assert list(db.scalars(select(MaterialChange))) == []
    assert create(client)['sku'] == 'EL-SR-000001'


def test_exhausted_counter_returns_conflict_without_writing(client):
    with orm_session(write=True) as db:
        db.add(MaterialCodeSequence(prefix='EL-SR', last_number=999999))
    assert client.post('/api/v1/materials', json=input_data()).status_code == 409
    assert client.get('/api/v1/materials').json() == []


def test_old_database_upgrade_preserves_references_and_initializes_sequence(client, remove_material_schema):
    row = create(client, dict(sku='EL-SR-000015', name='旧物料', unit='件'))
    supplier = client.post('/api/v1/suppliers', json={'name': '旧供应商'}).json()['id']
    assert client.put(f"/api/v1/suppliers/{supplier}/materials/{row['id']}").status_code == 204
    with connection() as db:
        remove_material_schema(db)
        db.execute('PRAGMA user_version=53')
    migrate()
    migrate()
    upgraded = client.get('/api/v1/materials').json()[0]
    assert (upgraded['id'], upgraded['sku'], upgraded['name'], upgraded['version']) == (row['id'], row['sku'], '旧物料', 1)
    assert all(upgraded[field] == '' for field in DETAIL_FIELDS)
    assert client.get('/api/v1/supplier-materials').json() == [{'supplier_id': supplier, 'material_id': row['id']}]
    assert client.delete(f"/api/v1/materials/{row['id']}").status_code == 204
    assert create(client)['sku'] == 'EL-SR-000016'
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 73
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_categories_and_material_writes_require_permission(client):
    assert client.post('/api/v1/users', json=dict(username='viewer', password='secure-pass-123', roles=['viewer'])).status_code == 201
    token = client.post('/api/v1/auth/login', json=dict(username='viewer', password='secure-pass-123')).json()['token']
    client.headers['Authorization'] = f'Bearer {token}'
    assert client.get('/api/v1/material-categories').status_code == 200
    assert client.post('/api/v1/materials', json=input_data()).status_code == 403
    client.headers.pop('Authorization')
    assert client.get('/api/v1/material-categories').status_code == 401
