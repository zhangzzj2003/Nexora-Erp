"""自定义分类与规格的真实接口、权限、并发及旧档案保护。"""

from concurrent.futures import ThreadPoolExecutor
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core.database import connection, migrate
from app.core.models import Material, MaterialCategory, MaterialSpecField, MaterialCategoryChange, MaterialChange, MaterialCodeSequence
from app.core.orm import orm_session
from app.main import app


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'categories.db'))
    with TestClient(app, client=('127.0.0.1', 12000), raise_server_exceptions=False) as client:
        assert client.post('/api/v1/setup/admin', json={'username':'admin', 'password':'secure-pass-123'}).status_code == 201
        client.headers['Authorization'] = 'Bearer ' + client.post('/api/v1/auth/login', json={'username':'admin', 'password':'secure-pass-123'}).json()['token']
        yield client


def category(client, code='ZZ-MT'):
    return next(child for group in client.get('/api/v1/material-categories').json() for child in [group, *group['children']] if child['code'] == code)


def custom(client):
    for code, parent, name in [('ZZ', None, '自定义材料'), ('ZZ-MT', 'ZZ', '非标结构件')]:
        response = client.post('/api/v1/material-categories', json={'code':code,'parent_code':parent,'name':name})
        assert response.status_code == 201, response.text
    return category(client)


def field(client, name='尺寸', kind='number', unit='mm', **options):
    response = client.post('/api/v1/material-categories/ZZ-MT/fields', json={
        'version':category(client)['version'],'reason':'根据图纸定义字段',
        'name':name,'kind':kind,'unit':unit, **options})
    assert response.status_code == 201, response.text
    return response.json()['fields'][-1]


def material(client, values=None, **options):
    body = {'name':'非标物料', 'unit':'件', 'category_code':'ZZ-MT'}
    if values is not None:
        body.update(spec_values=values, spec_template_version=category(client)['template_version'])
    return client.post('/api/v1/materials', json={**body, **options})


def value(field, val=None, status='filled'):
    return {'field_id':field['id'], 'status':status, 'value':val, 'source':'图纸 A 第 2 版'}


def update_category(client, target_code, **changes):
    row = category(client, target_code)
    return client.put('/api/v1/material-categories/' + target_code, json={
        **{key:row[key] for key in ('code','parent_code','name','enabled','notes','sort_order','version')}, 'reason':'核对后调整类别', **changes})


def update_field(client, field, **changes):
    body = {key:field[key] for key in ('name','kind','unit','options','allow_custom','required','enabled','sort_order')}
    return client.put(f"/api/v1/material-categories/ZZ-MT/fields/{field['id']}", json={
        **body, 'version':category(client)['version'], 'reason':'修订字段', **changes})


def test_custom_categories_codes_rename_disable_and_nonreuse(client):
    custom(client)
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda _: material(client).json(), range(4)))
    assert sorted(row['sku'] for row in rows) == [f'ZZ-MT-{n:06d}' for n in range(1,5)]
    assert update_category(client, 'ZZ-MT', name='定制结构件').status_code == 200
    listing = client.get('/api/v1/materials').json()
    assert all(row['category_name'] == '自定义材料 / 定制结构件' for row in listing)
    assert {row['sku'] for row in listing} == {row['sku'] for row in rows}
    assert update_category(client, 'ZZ', enabled=False).status_code == 200
    assert material(client).status_code == 409
    old = rows[0]
    assert client.put(f"/api/v1/materials/{old['id']}",json={**old,'name':'旧档案补名称','reason':'补录'}).status_code == 200
    row = category(client)
    assert client.request('DELETE','/api/v1/material-categories/ZZ-MT', json={'version':row['version'],'reason':'移除'}).status_code == 409
    for row in rows:
        assert client.request('DELETE',f"/api/v1/materials/{row['id']}").status_code == 204
    assert client.request('DELETE','/api/v1/material-categories/ZZ-MT', json={'version':category(client)['version'],'reason':'移除'}).status_code == 409
    assert update_category(client, 'ZZ', enabled=True).status_code == 200
    assert material(client).json()['sku'] == 'ZZ-MT-000005'
    assert update_category(client, 'ZZ-MT', code='ZZ-XX').status_code == 409


def test_legacy_manual_code_also_reserves_category_identity(client):
    custom(client)
    row = client.post('/api/v1/materials', json={'sku':'ZZ-MT-000009','name':'旧客户端档案','unit':'件'}).json()
    assert category(client)['used'] is True
    assert client.delete(f"/api/v1/materials/{row['id']}").status_code == 204
    assert client.request('DELETE','/api/v1/material-categories/ZZ-MT',json={
        'version':category(client)['version'],'reason':'已无物料'}).status_code == 409
    assert material(client).json()['sku'] == 'ZZ-MT-000010'


def test_unused_delete_retains_prefix_and_all_changes(client):
    custom(client)
    row = category(client)
    assert client.request('DELETE','/api/v1/material-categories/ZZ-MT',json={'version':row['version'],'reason':'目录重复'}).status_code == 200
    assert client.post('/api/v1/material-categories',json={'code':'ZZ-MT','parent_code':'ZZ','name':'重新占用'}).status_code == 409
    history = client.get('/api/v1/material-categories/ZZ-MT/changes').json()
    assert [entry['action'] for entry in history] == ['delete','create']
    assert history[0]['before']['deleted'] is False and history[0]['after']['deleted'] is True
    assert client.request('DELETE','/api/v1/material-categories/ZZ',json={'version':category(client,'ZZ')['version'],'reason':'目录重复'}).status_code == 200


def test_all_types_precise_values_statuses_and_extra_attributes(client):
    custom(client)
    numeric = field(client)
    boolean = field(client, '屏蔽', 'boolean', '')
    enum = field(client, '材质', 'enum', '', options=['铜','铝'], allow_custom=True)
    date = field(client, '确认日期', 'date', '')
    text = field(client, '针脚定义', 'text', '')
    exact = '123456789012345678901234.000000000001'
    response = material(client, [value(numeric,exact),value(boolean,False),value(enum,'镀锡铜'),value(date,'2028-02-29'),value(text,None,'pending')],
                        extra_attributes=[{'name':'特殊工艺','value':'双层绝缘','unit':''}])
    assert response.status_code == 201, response.text
    row = response.json()
    assert row['spec_values'][0]['value'] == exact
    assert row['spec_values'][1]['value'] is False
    assert '尺寸：' + exact + 'mm' in row['spec_summary'] and '屏蔽：否' in row['spec_summary'] and '针脚定义：待确认' in row['spec_summary']
    assert row['extra_attributes'][0]['value'] == '双层绝缘'
    assert client.get(f"/api/v1/materials/{row['id']}").json() == row
    # 公共选料卡使用同一规范化值，分类改名实时生效。
    choices = client.get('/api/v1/production/mrp/options').json()['materials']
    assert choices[0]['spec_values'] == row['spec_values']
    with orm_session() as db:
        audit = db.scalar(select(MaterialChange).where(MaterialChange.material_id == row['id']))
        assert json.loads(audit.after_json)['spec_values'][0]['source'] == '图纸 A 第 2 版'


@pytest.mark.parametrize('kind,val', [('number','NaN'),('number','10mm'),('number','1e5'),('number','1.0000000000001'),('number',10),('boolean','false'),('date','2026-02-29'),('enum','金')])
def test_invalid_typed_values_do_not_consume_sequence(client, kind, val):
    custom(client)
    spec = field(client, kind=kind, unit='mm' if kind == 'number' else '', **({'options':['银']} if kind == 'enum' else {}))
    assert material(client,[value(spec,val)]).status_code == 422
    assert client.get('/api/v1/materials').json() == []
    with orm_session() as db:
        assert db.get(MaterialCodeSequence,'ZZ-MT') is None
        assert db.get(MaterialSpecField,spec['id']).used is False


def test_spec_storage_does_not_reinterpret_mrp_source_snapshot(client):
    from app.production.mrp_sources import collect
    custom(client)
    row = material(client).json()
    with orm_session() as db:
        before = collect(db)
    # 新增存储列和分类显示名称不改变旧计划来源；真正修改原有物料资料仍会变化。
    with orm_session(write=True) as db:
        item = db.get(Material, row['id'])
        item.spec_template_version = 3
        item.extra_attributes_json = '[{"name":"工艺","value":"喷砂","unit":""}]'
        db.get(MaterialCategory, 'ZZ-MT').name = '新版类别名称'
    with orm_session() as db:
        assert collect(db) == before
    with orm_session(write=True) as db:
        db.get(Material, row['id']).name = '变更后的物料'
    with orm_session() as db:
        assert collect(db) != before


def test_required_templates_and_legacy_unrelated_edit(client):
    custom(client)
    old = material(client).json()
    numeric = field(client, required=True)
    assert material(client).status_code == 422
    assert material(client,[value(numeric,None,'unknown')]).status_code == 422
    assert client.put(f"/api/v1/materials/{old['id']}",json={**old,'name':'仅改名称'}).status_code == 200
    current = client.get(f"/api/v1/materials/{old['id']}").json()
    response = client.put(f"/api/v1/materials/{old['id']}",json={'name':current['name'],'unit':current['unit'],'version':current['version'],
        'spec_template_version':category(client)['template_version'],'spec_values':[value(numeric,'0.0000')]})
    assert response.status_code == 200, response.text
    assert response.json()['spec_values'][0]['value'] == '0'


def test_used_field_identity_and_historical_values_survive(client):
    custom(client)
    numeric = field(client)
    old = material(client,[value(numeric,'1.2500')]).json()
    assert update_field(client,numeric,kind='text',unit='').status_code == 409
    assert update_field(client,numeric,unit='cm').status_code == 409
    assert client.request('DELETE',f"/api/v1/material-categories/ZZ-MT/fields/{numeric['id']}",json={'version':category(client)['version'],'reason':'移除字段'}).status_code == 409
    assert update_field(client,numeric,name='图纸尺寸',enabled=False).status_code == 200
    read = client.get(f"/api/v1/materials/{old['id']}").json()
    assert read['spec_values'][0]['value'] == '1.25' and read['spec_values'][0]['name'] == '图纸尺寸' and read['spec_values'][0]['historical']
    response = client.put(f"/api/v1/materials/{old['id']}",json={'name':'重新分类','unit':'件','version':old['version'],'category_code':'WR-HS',
        'spec_values':[],'spec_template_version':category(client,'WR-HS')['template_version']})
    assert response.status_code == 200, response.text
    assert response.json()['sku'] == old['sku']
    assert response.json()['spec_values'][0]['value'] == '1.25'
    assert material(client,[value(numeric,'2')]).status_code == 422


def test_revision_conflicts_duplicate_fields_and_cross_category_rejection(client):
    custom(client)
    numeric = field(client)
    old_version = category(client)['template_version']
    field(client,'颜色','text','')
    assert material(client,[value(numeric,'2')],spec_template_version=old_version).status_code == 409
    assert material(client,[value(numeric,'2'),value(numeric,'3')]).status_code == 422
    foreign = category(client,'WR-WI')['fields'][0]
    assert material(client,[value(foreign,'铜')]).status_code == 422
    row = category(client)
    body = {'version':row['version'],'reason':'新增字段','name':'并发字段','kind':'text'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: client.post('/api/v1/material-categories/ZZ-MT/fields',json=body).status_code,range(2)))
    assert sorted(statuses) == [201,409]
    assert update_category(client,'ZZ-MT',version=True).status_code == 422
    assert update_category(client,'ZZ-MT',version=row['version']).status_code == 409


def test_duplicate_hierarchy_invalid_inputs_and_permissions(client):
    custom(client)
    for body, status in [({'code':'ZZ-AA','parent_code':'ZZ','name':'非标结构件'},409),
                         ({'code':'AA-BB','parent_code':'ZZ','name':'错误前缀'},422),
                         ({'code':'AA-BB','parent_code':'ZZ-MT','name':'第三层'},422),
                         ({'code':'XX','name':'自定义材料'},409), ({'code':'XX','name':' '},422)]:
        assert client.post('/api/v1/material-categories',json=body).status_code == status
    assert client.post('/api/v1/users',json={'username':'viewer','password':'secure-pass-123','roles':['viewer']}).status_code == 201
    client.headers['Authorization'] = 'Bearer ' + client.post('/api/v1/auth/login',json={'username':'viewer','password':'secure-pass-123'}).json()['token']
    assert client.get('/api/v1/material-categories').status_code == 200
    assert client.post('/api/v1/material-categories',json={'code':'XX','name':'无权限类别'}).status_code == 403
    assert client.post('/api/v1/material-categories/ZZ-MT/fields',json={'version':1,'reason':'x','name':'x','kind':'text'}).status_code == 403
    client.headers.pop('Authorization')
    assert client.get('/api/v1/material-categories').status_code == 401


def test_category_audit_failure_rolls_back_all_template_state(client):
    custom(client)
    before = category(client)
    def fail(db, _context, _instances):
        if any(isinstance(row,MaterialCategoryChange) for row in db.new):
            raise RuntimeError('模拟审计失败')
    event.listen(Session,'before_flush',fail)
    try:
        assert client.post('/api/v1/material-categories/ZZ-MT/fields',json={'version':before['version'],'reason':'新增','name':'新字段','kind':'text'}).status_code == 500
        assert client.post('/api/v1/material-categories',json={'code':'XX','name':'失败类别'}).status_code == 500
    finally:
        event.remove(Session,'before_flush',fail)
    assert category(client) == before
    with orm_session() as db:
        assert db.get(MaterialCategory,'XX') is None


def test_v93_upgrade_preserves_legacy_ids_text_and_counter(client):
    old = client.post('/api/v1/materials',json={'sku':'EL-WR-000032','name':'旧线束','unit':'件','specification':'非标准自由描述'}).json()
    with connection() as db:
        for table in ('material_category_changes','material_spec_fields','material_categories'):
            db.execute(f'DROP TABLE {table}')
        for col in ('spec_values_json','extra_attributes_json','spec_template_version'):
            db.execute(f'ALTER TABLE materials DROP COLUMN {col}')
        db.execute('PRAGMA user_version=93')
    migrate()
    migrate()
    read = client.get(f"/api/v1/materials/{old['id']}").json()
    assert read == old and read['specification'] == '非标准自由描述'
    assert category(client,'EL-WR')['used'] is True
    assert category(client,'PL-RM')['fields'] and category(client,'WR-HS')['fields']
    assert client.post('/api/v1/materials',json={'category_code':'EL-WR','name':'兼容旧前缀','unit':'件'}).json()['sku'] == 'EL-WR-000033'
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 95
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
