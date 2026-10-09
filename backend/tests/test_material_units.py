"""单位管理、选择边界和旧库升级的真实事务验收。"""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.main import app
from app.core.database import connection, migrate
from app.core.models import MaterialUnitChange
from app.core.orm import orm_session


@pytest.fixture
def client(monkeypatch, tmp_path):
    # 所有单位及物料都写入临时库，不污染本机正式 ERP 服务。
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'units.db'))
    with TestClient(app, client=('127.0.0.1', 12300), raise_server_exceptions=False) as client:
        account = {'username': 'admin', 'password': 'secure-pass-123'}
        assert client.post('/api/v1/setup/admin', json=account).status_code == 201
        token = client.post('/api/v1/auth/login', json=account).json()['token']
        client.headers['Authorization'] = f'Bearer {token}'
        yield client


def units(client):
    return client.get('/api/v1/material-units').json()


def material(client, choice, **extra):
    return client.post('/api/v1/materials', json={'name':'测试物料', 'unit':choice['name'],
        'unit_id':choice['id'], 'category_code':'HW-FA', **extra})


def test_defaults_create_update_conflict_and_history(client):
    names = {unit['name'] for unit in units(client)}
    assert {'件','个','条','米','千克'} <= names
    new = client.post('/api/v1/material-units', json={'name':'  托盘  ', 'notes':'整托', 'enabled':True})
    assert new.status_code == 201
    row = new.json()
    assert row['name'] == '托盘' and row['material_count'] == 0
    assert client.post('/api/v1/material-units', json={'name':'托盘'}).status_code == 409
    path = f"/api/v1/material-units/{row['id']}"
    assert client.put(path, json={**row, 'reason':' '}).status_code == 422
    changed = client.put(path, json={**row, 'name':'小托盘', 'enabled':False, 'reason':'调整名称'}).json()
    assert changed['version'] == 2 and not changed['enabled']
    assert client.put(path, json={**row,'reason':'过期编辑'}).status_code == 409
    assert client.get(path).json() == changed
    history = client.get(f'{path}/changes').json()
    assert len(history) == 2
    assert history[0]['before']['name'] == '托盘' and history[0]['after']['name'] == '小托盘'
    assert history[0]['changed_by_name'] == 'admin'


def test_disabled_units_preserve_existing_but_reject_new_choices(client):
    unit = next(unit for unit in units(client) if unit['name'] == '条')
    row = material(client, unit).json()
    path = f"/api/v1/material-units/{unit['id']}"
    latest = client.get(path).json()
    assert latest['material_count'] == 1
    assert client.put(path, json={**latest, 'name':'改名', 'reason':'尝试改名'}).status_code == 409
    assert client.put(path, json={**latest,'enabled':False,'reason':'暂停使用'}).status_code == 200
    assert material(client, unit).status_code == 409
    # 编辑名称时可保留停用的原单位，旧客户端也不能在新物料上绕过停用。
    edited = client.put(f"/api/v1/materials/{row['id']}", json={**row,'unit_id':unit['id'], 'name':'改名称'})
    assert edited.status_code == 200 and edited.json()['unit'] == '条'
    assert client.post('/api/v1/materials', json={'name':'旧客户端', 'unit':'条', 'sku':'LEGACY'}).status_code == 409
    active = next(unit for unit in units(client) if unit['name'] == '件')
    assert material(client, active, unit='条').status_code == 409
    assert material(client, {'id':99999,'name':'不存在'}).status_code == 409


@pytest.mark.parametrize('payload', [{'name':' '}, {'name':'字'*21}, {'name':'新单位','enabled':1},
    {'name':'新单位','version':True}, {'name':'新单位','notes':'字'*501}])
def test_invalid_inputs_do_not_write(client, payload):
    before = units(client)
    assert client.post('/api/v1/material-units', json=payload).status_code == 422
    assert units(client) == before


def test_parallel_duplicate_units_and_atomic_failure(client):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.post('/api/v1/material-units', json={'name':'并发单位'}), range(2)))
    assert sorted(result.status_code for result in results) == [201,409]
    before = units(client)
    def fail_audit(db, *_):
        if any(isinstance(row, MaterialUnitChange) for row in db.new):
            raise RuntimeError('模拟审计写入失败')
    event.listen(Session,'before_flush',fail_audit)
    try:
        assert client.post('/api/v1/material-units', json={'name':'失败单位'}).status_code == 500
        # 兼容导入自动收录也必须和物料、编码一起回滚。
        assert client.post('/api/v1/materials', json={'name':'失败物料','unit':'失败旧单位','category_code':'HW-FA'}).status_code == 500
    finally:
        event.remove(Session,'before_flush',fail_audit)
    assert units(client) == before
    assert client.get('/api/v1/materials').json() == []
    good = client.post('/api/v1/materials', json={'name':'旧调用物料','unit':'自定义旧单位','category_code':'HW-FA'})
    assert good.status_code == 201 and good.json()['sku'] == 'HW-FA-000001'
    assert next(unit for unit in units(client) if unit['name']=='自定义旧单位')['material_count'] == 1


def test_permissions_and_missing_units(client):
    assert client.get('/api/v1/material-units/99999').status_code == 404
    assert client.put('/api/v1/material-units/99999',json={'name':'单位','version':1,'reason':'修改'}).status_code == 404
    assert client.get('/api/v1/material-units/99999/changes').status_code == 404
    client.post('/api/v1/users',json={'username':'viewer','password':'secure-pass-123','roles':['viewer']})
    token=client.post('/api/v1/auth/login',json={'username':'viewer','password':'secure-pass-123'}).json()['token']
    client.headers['Authorization']=f'Bearer {token}'
    assert client.get('/api/v1/material-units').status_code == 200
    assert client.post('/api/v1/material-units',json={'name':'越权单位'}).status_code == 403
    row=units(client)[0]
    assert client.put(f"/api/v1/material-units/{row['id']}",json={**row,'reason':'越权停用'}).status_code == 403
    client.headers.clear()
    assert client.get('/api/v1/material-units').status_code == 401


def test_v86_upgrade_preserves_legacy_units_and_is_idempotent(client):
    old=client.post('/api/v1/materials',json={'name':'历史物料','sku':'OLD','unit':'历史箱单位'}).json()
    # 模拟真实第 86 版：不存在单位目录，物料和供应商原数据仍在。
    with connection() as db:
        db.execute('DROP TABLE material_unit_changes')
        db.execute('DROP TABLE material_units')
        db.execute('PRAGMA user_version = 86')
    migrate()
    assert client.get(f"/api/v1/materials/{old['id']}").json() == old
    first=units(client)
    assert next(unit for unit in first if unit['name']=='历史箱单位')['material_count'] == 1
    migrate()
    assert units(client) == first
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 99
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    with orm_session() as db:
        assert list(db.scalars(select(MaterialUnitChange))) == []
