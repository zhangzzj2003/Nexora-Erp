"""产品档案、迁移、联合冲突及 BOM 派生的真实接口闭环。"""
from approval_test_helpers import create_planned_work_order, seed_legacy_work_order
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from app.main import app
from app.core.database import connection, migrate
from app.core.models import Material, ProductProfile, ProductChange
from app.core.orm import orm_session


@pytest.fixture
def erp(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'products.db'))
    with TestClient(app, client=('127.0.0.1', 12000)) as client:
        base = '/api/v1'
        assert client.post(base + '/setup/admin', json={'username':'admin','password':'secure-pass-123'}).status_code == 201
        def login(name):
            token = client.post(base + '/auth/login', json={'username':name,'password':'secure-pass-123'}).json()['token']
            return {'Authorization': 'Bearer ' + token}
        admin = login('admin')
        client.post(base + '/roles', headers=admin, json={'code':'product_reader','label':'产品只读','permissions':['inventory.view']})
        client.post(base + '/users', headers=admin, json={'username':'warehouse','password':'secure-pass-123','roles':['product_reader']})
        client.post(base + '/users', headers=admin, json={'username':'planner','password':'secure-pass-123','roles':['planner']})
        def request(method, path, payload=None, actor=None):
            return client.request(method, base + path, headers=actor or admin, **({'json':payload} if payload is not None else {}))
        # 调用方显式选择计划建单或历史夹具，普通 request 不拦截或改写旧 HTTP 请求。
        request.plan_work_order = lambda payload, actor=None: create_planned_work_order(client,
            headers=actor or admin, account_headers=admin, json=payload)
        request.legacy_work_order = lambda payload: seed_legacy_work_order(client, headers=admin, json=payload)
        yield request, login('warehouse'), login('planner')


def material(code, name=None):
    return {'sku':'PRODUCT-' + code, 'name':name or code, 'unit':'件', 'specification':'流程测试规格'}


def test_product_identity_atomic_edit_and_audit(erp):
    req, warehouse, _ = erp
    model = req('POST','/product-models',{'code':'A100','name':'智能终端','notes':''}).json()
    new = req('POST','/products',{'kind':'finished','model_id':model['id'], 'configuration_name':'标准版','material':material('A')})
    assert new.status_code == 201, new.text
    row = new.json(); mid = row['material_id']
    assert row['material']['id'] == mid
    assert req('GET', f'/materials/{mid}').json()['sku'] == 'PRODUCT-A'
    assert req('POST','/products',{'material_id':mid,'kind':'component'}).status_code == 409
    assert req('POST','/products',{'material_id':mid,'material':material('B')}).status_code == 422
    assert req('POST','/products',{'material':material('B'),'model_id':9999}).status_code == 422
    assert len(req('GET','/materials').json()) == 1
    assert req('POST','/products',{'material_id':99999}).status_code == 422
    assert req('POST','/products',{'material_id':mid},warehouse).status_code == 403
    assert req('POST','/products/query',{},warehouse).json()['items'][0]['id'] == row['id']
    assert 'boms' not in req('GET',f"/products/{row['id']}",actor=warehouse).json()
    update = {'kind':'semi_finished','model_id':model['id'],'configuration_name':'扩展版','version':1,'reason':'修改配置',
              'material':{**material('A','终端组件'),'version':1}}
    saved = req('PUT', f"/products/{row['id']}", update)
    assert saved.status_code == 200, saved.text
    assert saved.json()['version'] == 2 and saved.json()['material']['version'] == 2
    # 另一入口修改物料后，联合编辑不能只更新产品归组。
    assert req('PUT',f'/materials/{mid}',{**material('A','材料端更新'),'version':2}).status_code == 200
    conflict = req('PUT',f"/products/{row['id']}",{**update,'version':2,'kind':'component','material':{**material('A'),'version':2}})
    assert conflict.status_code == 409
    current = req('GET',f"/products/{row['id']}").json()
    assert current['kind'] == 'semi_finished' and current['version'] == 2
    assert current['material']['name'] == '材料端更新'
    assert req('PUT',f"/products/{row['id']}",{**update,'reason':' '}).status_code == 422
    history = req('GET',f"/products/{row['id']}/changes").json()
    assert len(history) == 2
    assert history[0]['reason'] == '修改配置' and history[0]['before']['material']['name'] == 'A'
    assert history[0]['after']['kind'] == 'semi_finished'
    assert req('GET',f"/products/{row['id']}/changes",actor=warehouse).status_code == 200
    assert req('POST','/product-models',{'code':'A100','name':'重复','notes':''}).status_code == 409
    assert req('PUT',f"/product-models/{model['id']}",{'code':'A100','name':'更名','notes':'','version':1,'reason':'更正'}).status_code == 200
    assert req('PUT',f"/product-models/{model['id']}",{'code':'A100','name':'旧版本','notes':'','version':1,'reason':'冲突'}).status_code == 409
    assert len(req('GET',f"/product-models/{model['id']}/changes").json()) == 2
    assert req('GET',f"/products/{row['id']}").json()['model_name'] == '更名'


def test_existing_material_pagination_and_literal_filters(erp):
    req, _, _ = erp
    models = [req('POST','/product-models',{'code':f'M{i}','name':f'机型{i}','notes':''}).json() for i in range(2)]
    old = req('POST','/materials',material('EXISTING','保留旧物料')).json()
    before = req('GET','/stock').json()
    included = req('POST','/products',{'material_id':old['id'],'kind':'component'}).json()
    assert included['material']['version'] == old['version']
    assert req('GET','/stock').json() == before
    for index in range(25):
        response = req('POST','/products',{'material':material(str(index), f'产品{index}'), 'kind':'finished',
            'model_id':models[index % 2]['id'], 'configuration_name':'长续航版' if index % 2 else '标准版'})
        assert response.status_code == 201, response.text
    page = req('POST','/products/query',{'page':2,'page_size':20}).json()
    assert page['total'] == 26 and page['page'] == 2 and len(page['items']) == 6
    assert len({row['id'] for row in page['items']}) == 6
    filtered = req('POST','/products/query',{'query':'长续航版','model_id':models[1]['id'],'kind':'finished','page':999,'page_size':5}).json()
    assert filtered['total'] == 12 and filtered['page'] == 3 and len(filtered['items']) == 2
    assert req('POST','/products/query',{'query':'%'}).json()['total'] == 0
    assert req('POST','/products/query',{'query':'流程测试规格'}).json()['total'] == 26
    assert req('POST','/products/query',{'page_size':101}).status_code == 422


def test_bom_derivation_and_work_order_snapshot(erp):
    req, _, planner = erp
    mid = {key:req('POST','/materials',material(key)).json()['id'] for key in ('A','B','C','D')}
    def bom(product, component, source=None, quantity='2'):
        return {'product_material_id':mid[product], 'base_quantity':'1','lines':[{'component_material_id':mid[component],'quantity':quantity}],
                **({'source_bom_id':source} if source else {})}
    source = req('POST','/boms',bom('A','B'),planner).json()
    assert req('POST','/products/query',{}).json()['total'] == 1
    assert req('POST',f"/boms/{source['id']}/activate",actor=planner).status_code == 200
    order = req.plan_work_order({'bom_id':source['id'],'warehouse_id':1,'target_quantity':'5','reference':'产品闭环','note':''},planner).json()
    derived = req('POST','/boms',bom('C','D',source['id'],'3'),planner)
    assert derived.status_code == 201, derived.text
    derived = derived.json()
    assert derived['source_bom']['id'] == source['id'] and derived['source_bom']['product_name'] == 'A'
    assert req('GET',f"/boms?product_material_id={mid['C']}").json()[0]['id'] == derived['id']
    assert req('GET',f"/boms/{derived['id']}").json()['lines'][0]['component_material_id'] == mid['D']
    replacement = req('POST','/boms',bom('A','D',source['id']),planner).json()
    assert replacement['version'] == 2
    assert req('POST',f"/boms/{source['id']}/retire",actor=planner).status_code == 200
    assert req('POST',f"/boms/{replacement['id']}/activate",actor=planner).status_code == 200
    old_order = next(row for row in req('GET','/work-orders').json() if row['id'] == order['id'])
    assert old_order['bom_version'] == 1 and old_order['lines'][0]['component_material_id'] == mid['B']
    assert old_order['lines'][0]['required_quantity'] == '10.000'
    assert req('POST',f"/boms/{derived['id']}/cancel",actor=planner).status_code == 200
    assert req('POST','/boms',bom('A','B',derived['id']),planner).status_code == 422
    assert req('POST','/boms',bom('A','A',source['id']),planner).status_code == 422
    assert req('POST','/boms',bom('A','B',99999),planner).status_code == 422


def test_product_migration_is_additive_and_repeatable(erp):
    req, _, _ = erp
    a = req('POST','/materials',material('A')).json()['id']
    b = req('POST','/materials',material('B')).json()['id']
    for _ in range(2):
        assert req('POST','/boms',{'product_material_id':a,'lines':[{'component_material_id':b,'quantity':'1'}]}).status_code == 201
    before_boms = req('GET','/boms').json()
    before_stock = req('GET','/stock').json()
    # 结构迁移模拟旧库；业务夹具仍经真实接口建立，已有物料和 BOM 内容不重写。
    with orm_session(write=True) as db:
        db.execute(delete(ProductChange)); db.execute(delete(ProductProfile))
    with connection() as db:
        db.execute('PRAGMA user_version = 103')
    migrate(); migrate()
    rows = req('POST','/products/query',{}).json()
    assert rows['total'] == 1 and rows['items'][0]['material_id'] == a
    assert rows['items'][0]['kind'] == 'unclassified' and rows['items'][0]['created_by'] is None
    assert req('GET','/boms').json() == before_boms
    assert req('GET','/stock').json() == before_stock


def test_model_variants_create_derived_boms_and_independent_orders(erp):
    """标准版与长续航版共用机型，各自固定编码、BOM 版本及工单需求。"""
    req, _, _ = erp
    model = req('POST','/product-models',{'code':'A100','name':'A100 系列','notes':''}).json()
    products = []
    for configuration in ('标准版','长续航版'):
        created = req('POST','/products',{'kind':'finished','model_id':model['id'],'configuration_name':configuration,
            'material':{'name':'A100 ' + configuration,'unit':'件','category_code':'EL-PC'}})
        assert created.status_code == 201, created.text
        products.append(created.json())
    assert products[0]['material']['sku'] != products[1]['material']['sku']
    assert all(row['material']['sku'].startswith('EL-PC-') for row in products)
    component = req('POST','/materials',material('COMPONENT')).json()['id']
    source = req('POST','/boms',{'product_material_id':products[0]['material_id'],'base_quantity':'1',
        'lines':[{'component_material_id':component,'quantity':'2'}]}).json()
    derived = req('POST','/boms',{'product_material_id':products[1]['material_id'],'source_bom_id':source['id'],
        'base_quantity':'1','lines':[{'component_material_id':component,'quantity':'3'}]}).json()
    for bom in (source,derived):
        assert req('POST',f"/boms/{bom['id']}/activate").status_code == 200
    for bom, quantity, required in ((source,'10','20.000'),(derived,'5','15.000')):
        response = req.plan_work_order({'bom_id':bom['id'],'warehouse_id':1,'target_quantity':quantity})
        assert response.status_code == 201, response.text
        assert response.json()['lines'][0]['required_quantity'] == required
        assert response.json()['product_material_id'] == bom['product_material_id']
    filtered = req('POST','/products/query',{'model_id':model['id']}).json()
    assert filtered['total'] == 2
    assert {row['configuration_name'] for row in filtered['items']} == {'标准版','长续航版'}
    assert all(row['quantity'] == '0' for row in req('GET','/stock').json())
