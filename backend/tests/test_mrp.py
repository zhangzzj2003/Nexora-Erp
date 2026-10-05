"""验证共享组件、日期净需求、来源快照、职责分离和事务转单。"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal
import os
import sqlite3

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core.database import migrate
from app.core.models import Base, MrpConversion, MrpPlan, MrpPlanChange, PurchaseRequest, WorkOrder
from app.core.orm import orm_session
from app.main import app
from app.production import mrp
from app.production.mrp_engine import calculate

BASE = '/api/v1'
MRP = BASE + '/production/mrp'
START = '2030-01-01'


def engine_source():
    return {'materials': [{'id': identifier, 'sku': f'M{identifier}', 'name': f'物料{identifier}', 'unit': '件'}
            for identifier in (1,2,3)],
        'policies': [{'material_id': identifier, 'supply_mode': 'auto', 'lead_time_days': 0,
            'safety_stock': '0', 'minimum_quantity': '0', 'multiple_quantity': '0'} for identifier in (1,2,3)],
        'boms': [{'id': 1, 'version': 1, 'product_material_id': 1, 'base_quantity': '1',
                'lines': [{'id':1,'component_material_id':3,'quantity':'2'}]},
            {'id': 2, 'version': 1, 'product_material_id': 2, 'base_quantity': '1',
                'lines': [{'id':2,'component_material_id':3,'quantity':'3'}]}],
        'movements': [{'material_id':3,'quantity':'7'}], 'demands': [], 'supplies': [], 'reservations': []}


def test_shared_components_are_netted_once_and_stock_is_not_double_counted():
    result = calculate(engine_source(), START, {}, {}, [
        {'material_id':1,'quantity':'10','due_date':START,'reference':'成品甲'},
        {'material_id':2,'quantity':'10','due_date':START,'reference':'成品乙'}])
    component = next(row for row in result['rows'] if row['material_id'] == 3)
    assert component['gross_quantity'] == '50.000'
    assert component['planned_quantity'] == '43.000'
    assert len(component['demand_sources']) == 2
    assert component['level'] == 1
    assert len([row for row in result['suggestions'] if row['material_id'] == 3]) == 1


def test_dates_prevent_late_supply_from_satisfying_earlier_demand_and_lots_carry_forward():
    source = engine_source()
    source['boms'] = []
    source['movements'] = []
    source['supplies'] = [{'key':'po:1','material_id':3,'quantity':'2'}]
    source['policies'][2].update(safety_stock='1', minimum_quantity='4', multiple_quantity='3', lead_time_days=2)
    result = calculate(source, START, {}, {'po:1':'2030-01-05'}, [
        {'material_id':3,'quantity':'2','due_date':START,'reference':'紧急'},
        {'material_id':3,'quantity':'2','due_date':'2030-01-02','reference':'翌日'}])
    rows = [row for row in result['rows'] if row['material_id'] == 3]
    assert rows[0]['planned_quantity'] == '6.000'
    assert rows[1]['planned_quantity'] == '0.000'
    assert rows[2]['scheduled_quantity'] == '2.000'
    assert rows[2]['closing_quantity'] == '4.000'
    assert result['suggestions'][0]['late']
    assert result['suggestions'][0]['required_release_date'] == '2029-12-30'
    assert result['suggestions'][0]['release_date'] == START


def test_fractional_bom_rounding_and_parent_lead_time_drive_component_dates():
    source = engine_source()
    source['boms'] = source['boms'][:1]
    source['boms'][0]['base_quantity'] = '3'
    source['boms'][0]['lines'][0]['quantity'] = '1'
    source['movements'] = []
    source['policies'][0]['lead_time_days'] = 3
    result = calculate(source, START, {}, {}, [
        {'material_id':1,'quantity':'1','due_date':'2030-01-10','reference':'定制'}])
    child = next(row for row in result['rows'] if row['material_id'] == 3)
    assert child['date'] == '2030-01-07'
    assert child['gross_quantity'] == '0.334'


def test_cycles_missing_make_boms_and_large_component_orders_are_rejected():
    source = engine_source()
    source['boms'].append({'id':3,'version':1,'product_material_id':3,'base_quantity':'1',
        'lines':[{'id':3,'component_material_id':1,'quantity':'1'}]})
    with pytest.raises(HTTPException, match='循环'):
        calculate(source, START, {}, {}, [])
    source = engine_source()
    source['boms'] = []
    source['policies'][0]['supply_mode'] = 'make'
    with pytest.raises(HTTPException, match='没有启用 BOM'):
        calculate(source, START, {}, {}, [])
    source = engine_source()
    with pytest.raises(HTTPException, match='一百万'):
        calculate(source, START, {}, {}, [{'material_id':1,'quantity':'600000','due_date':START,'reference':'大单'}])


@pytest.fixture
def seeded(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'mrp.db'))
    monkeypatch.setattr(mrp, 'today', lambda: START)
    with TestClient(app, client=('127.0.0.1',12000), raise_server_exceptions=False) as client:
        assert client.post(BASE+'/setup/admin', json={'username':'admin','password':'secure-pass-123'}).status_code == 201
        def login(username):
            token = client.post(BASE+'/auth/login', json={'username':username,'password':'secure-pass-123'}).json()['token']
            return {'Authorization': f'Bearer {token}'}
        admin = login('admin')
        for username, role in (('reviewer','admin'),('planner','planner'),('viewer','viewer')):
            assert client.post(BASE+'/users', headers=admin, json={
                'username':username,'password':'secure-pass-123','roles':[role]}).status_code == 201
        material_ids = [client.post(BASE+'/materials', headers=admin, json={
            'sku':sku,'name':name,'unit':'件'}).json()['id'] for sku,name in (('A','成品'),('B','组件'),('R','=原料'))]
        a,b,r = material_ids
        for product, lines in ((a, [(b,'2'),(r,'1')]), (b, [(r,'3')])):
            bom = client.post(BASE+'/boms', headers=admin, json={'product_material_id':product,'base_quantity':'1',
                'lines':[{'component_material_id':material,'quantity':qty} for material,qty in lines]}).json()['id']
            assert client.post(BASE+f'/boms/{bom}/activate', headers=admin).status_code == 200
        supplier = client.post(BASE+'/suppliers', headers=admin, json={'name':'供应商'}).json()['id']
        receipt = client.post(BASE+'/receipts', headers=admin, json={'supplier_id':supplier,'warehouse_id':1,
            'lines':[{'material_id':r,'quantity':'5'}]}).json()['id']
        assert client.post(BASE+f'/receipts/{receipt}/post', headers=admin).status_code == 200
        yield client, admin, login('reviewer'), login('planner'), login('viewer'), material_ids, supplier


def payload(client, admin, materials, reference='PLAN-1'):
    options = client.get(MRP+'/options', headers=admin).json()
    return {'reference':reference,'start_date':START,'reason':'按订单与库存核对',
        'demand_dates':[{'key':row['key'],'due_date':'2030-01-10'} for row in options['demands']],
        'supply_dates':[{'key':row['key'],'due_date':'2030-01-05'} for row in options['supplies'] if not row.get('due_date')],
        'manual_demands':[{'material_id':materials[0],'quantity':'2','due_date':'2030-01-10','reference':'额外订单'}]}


def approved(client, admin, reviewer, data):
    response = client.post(MRP+'/plans', headers=admin, json=data)
    assert response.status_code == 201, response.text
    record = response.json()
    response = client.post(MRP+f'/plans/{record["id"]}/submit', headers=admin,
        json={'version':record['version'],'reason':'确认来源'})
    assert response.status_code == 200, response.text
    record = response.json()
    response = client.post(MRP+f'/plans/{record["id"]}/approve', headers=reviewer,
        json={'version':record['version'],'reason':'独立核对'})
    assert response.status_code == 200, response.text
    return response.json()


def test_full_plan_workflow_snapshot_and_conversion_do_not_change_stock(seeded):
    client, admin, reviewer, planner, viewer, materials, _ = seeded
    assert client.get(MRP+'/options', headers=viewer).status_code == 403
    assert client.get(MRP+'/options', headers=planner).status_code == 200
    stock = client.get(BASE+'/stock', headers=admin).json()
    data = payload(client, admin, materials)
    record = client.post(MRP+'/plans', headers=admin, json=data).json()
    assert client.post(MRP+f'/plans/{record["id"]}/convert', headers=admin,
        json={'version':1,'suggestion_key':'1:2030-01-10','reason':'未审核'}).status_code == 409
    assert client.post(MRP+f'/plans/{record["id"]}/submit', headers=admin,
        json={'version':1,'reason':'提交'}).status_code == 200
    assert client.post(MRP+f'/plans/{record["id"]}/approve', headers=admin,
        json={'version':2,'reason':'本人审核'}).status_code == 403
    assert client.post(MRP+f'/plans/{record["id"]}/approve', headers=reviewer,
        json={'version':2,'reason':'独立核对'}).status_code == 200
    detail = client.get(MRP+f'/plans/{record["id"]}', headers=planner).json()
    assert detail['snapshot']['sources']['movements']
    assert "'=原料" in detail['csv']
    assert detail['csv'].startswith('\ufeff')
    original = deepcopy(detail['snapshot'])
    suggestions = {row['material_id']:row for row in detail['snapshot']['suggestions']}
    assert suggestions[materials[2]]['quantity'] == '9.000'
    for material in materials:
        current = client.get(MRP+f'/plans/{record["id"]}', headers=admin).json()
        response = client.post(MRP+f'/plans/{record["id"]}/convert', headers=planner, json={
            'version':current['version'],'suggestion_key':suggestions[material]['key'],'warehouse_id':1,'reason':'按计划转单'})
        assert response.status_code == 201, response.text
        target = response.json()
        if target['purchase_request_id']:
            request = client.get(BASE+'/purchase-requests', headers=planner).json()[-1]
            assert request['id'] == target['purchase_request_id']
            assert request['lines'][0]['quantity'] == '9.000'
            assert client.put(BASE+f'/purchase-requests/{request["id"]}', headers=planner,
                json={'lines':[{'material_id':materials[2],'quantity':'1'}]}).status_code == 409
        assert client.get(MRP+f'/plans/{record["id"]}/check', headers=admin).json()['matched']
    assert client.get(BASE+'/stock', headers=admin).json() == stock
    current = client.get(MRP+f'/plans/{record["id"]}', headers=admin).json()
    assert current['snapshot'] == original
    assert len(current['conversions']) == 3
    assert client.post(MRP+f'/plans/{record["id"]}/convert', headers=admin, json={
        'version':current['version'],'suggestion_key':suggestions[materials[0]]['key'],'warehouse_id':1,'reason':'重复'}).status_code == 409
    assert client.post(MRP+f'/plans/{record["id"]}/cancel', headers=admin,
        json={'version':current['version'],'reason':'原单未取消'}).status_code == 409
    actions = [row['action'] for row in client.get(MRP+f'/plans/{record["id"]}/changes', headers=admin).json()]
    assert actions == ['create','submit','approve','convert','convert','convert']


def test_existing_sales_purchases_and_work_orders_have_complete_dated_sources(seeded):
    client, admin, reviewer, planner, viewer, materials, supplier = seeded
    a,b,r = materials
    customer = client.post(BASE+'/customers', headers=admin, json={'name':'客户'}).json()['id']
    sale = client.post(BASE+'/sales-orders', headers=admin, json={'customer_id':customer,
        'lines':[{'material_id':a,'quantity':'2','unit_price':'1'}]}).json()['id']
    assert client.post(BASE+f'/sales-orders/{sale}/confirm', headers=admin).status_code == 200
    purchase = client.post(BASE+'/purchase-orders', headers=admin, json={'supplier_id':supplier,
        'lines':[{'material_id':r,'quantity':'20','unit_price':'1'}]}).json()['id']
    assert client.post(BASE+f'/purchase-orders/{purchase}/confirm', headers=admin).status_code == 200
    bom = next(row for row in client.get(BASE+'/boms', headers=admin).json() if row['product_material_id'] == b)
    work = client.post(BASE+'/work-orders', headers=admin, json={'bom_id':bom['id'],'warehouse_id':1,'target_quantity':'1'}).json()
    options = client.get(MRP+'/options', headers=admin).json()
    assert len(options['demands']) == 1
    assert len(options['supplies']) == 2
    assert options['reservations'][0]['quantity'] == '3.000'
    data = payload(client, admin, materials)
    assert client.post(MRP+'/plans', headers=admin, json={**data,'demand_dates':[]}).status_code == 409
    assert client.post(MRP+'/plans', headers=admin, json={**data,'supply_dates':[]}).status_code == 409
    plan = approved(client, admin, reviewer, data)
    detail = client.get(MRP+f'/plans/{plan["id"]}', headers=admin).json()
    row = next(row for row in detail['snapshot']['rows'] if row['material_id'] == a)
    assert row['gross_quantity'] == '4.000'
    assert len(row['demand_sources']) == 2
    assert any('工单 #' in text and '状态为 草稿，尚待' in text for text in detail['snapshot']['warnings'])
    # 采购先到而工单预计成品后到；迟到成品不能覆盖更早的日期需求。
    assert any(item['source_id'] == work['id'] for item in detail['snapshot']['sources']['supplies'] if item['kind'] == 'work_order')


def test_policy_audit_version_checks_and_stale_plans_keep_original_evidence(seeded):
    client, admin, reviewer, planner, viewer, materials, _ = seeded
    record = approved(client, admin, reviewer, payload(client, admin, materials))
    original = client.get(MRP+f'/plans/{record["id"]}', headers=admin).json()
    policy = {'version':0,'supply_mode':'auto','lead_time_days':2,'safety_stock':'1',
        'minimum_quantity':'0','multiple_quantity':'0','reason':'更新交期'}
    assert client.put(MRP+f'/policies/{materials[0]}', headers=viewer, json=policy).status_code == 403
    assert client.put(MRP+f'/policies/{materials[0]}', headers=planner, json=policy).status_code == 200
    assert client.put(MRP+f'/policies/{materials[0]}', headers=planner, json=policy).status_code == 409
    check = client.get(MRP+f'/plans/{record["id"]}/check', headers=admin).json()
    assert not check['matched'] and check['fingerprint'] != check['current_fingerprint']
    assert client.post(MRP+f'/plans/{record["id"]}/convert', headers=admin, json={
        'version':record['version'],'suggestion_key':original['snapshot']['suggestions'][0]['key'],
        'warehouse_id':1,'reason':'旧计划'}).status_code == 409
    assert client.get(MRP+f'/plans/{record["id"]}', headers=admin).json()['snapshot'] == original['snapshot']
    history = client.get(MRP+f'/policies/{materials[0]}/changes', headers=admin).json()
    assert history[0]['before'] is None and history[0]['after']['version'] == 1
    for edit in ({'lead_time_days':True},{'minimum_quantity':'1e3'},{'safety_stock':'NaN'},
                 {'version':False},{'multiple_quantity':'0.0001'}):
        assert client.put(MRP+f'/policies/{materials[0]}', headers=planner, json={**policy,**edit}).status_code == 422


def test_concurrent_transfers_stale_competing_plan_and_cancelled_targets(seeded):
    client, admin, reviewer, planner, viewer, materials, _ = seeded
    first = approved(client, admin, reviewer, payload(client, admin, materials, 'FIRST'))
    second = approved(client, admin, reviewer, payload(client, admin, materials, 'SECOND'))
    detail = client.get(MRP+f'/plans/{first["id"]}', headers=admin).json()
    key = next(row['key'] for row in detail['snapshot']['suggestions'] if row['material_id'] == materials[0])
    request = {'version':first['version'],'suggestion_key':key,'warehouse_id':1,'reason':'并发转单'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post(MRP+f'/plans/{first["id"]}/convert', headers=admin, json=request), range(2)))
    assert sorted(row.status_code for row in responses) == [201,409]
    assert not client.get(MRP+f'/plans/{second["id"]}/check', headers=admin).json()['matched']
    target = next(row.json() for row in responses if row.status_code == 201)
    assert client.post(BASE+f'/work-orders/{target["work_order_id"]}/cancel', headers=admin).status_code == 200
    assert client.get(MRP+f'/plans/{first["id"]}/check', headers=admin).json()['cancelled_target']
    current = client.get(MRP+f'/plans/{first["id"]}', headers=admin).json()
    assert client.post(MRP+f'/plans/{first["id"]}/cancel', headers=admin,
        json={'version':current['version'],'reason':'原单已取消'}).status_code == 200


def test_transfer_failure_rolls_back_target_link_and_audit(seeded):
    client, admin, reviewer, planner, viewer, materials, _ = seeded
    record = approved(client, admin, reviewer, payload(client, admin, materials))
    detail = client.get(MRP+f'/plans/{record["id"]}', headers=admin).json()
    key = next(row['key'] for row in detail['snapshot']['suggestions'] if row['material_id'] == materials[2])
    def fail_audit(session, *_):
        if any(isinstance(row, MrpPlanChange) and row.action == 'convert' for row in session.new):
            raise RuntimeError('模拟审计写入故障')
    event.listen(Session, 'before_flush', fail_audit)
    try:
        response = client.post(MRP+f'/plans/{record["id"]}/convert', headers=admin, json={
            'version':record['version'],'suggestion_key':key,'reason':'按计划采购'})
        assert response.status_code == 500
    finally:
        event.remove(Session, 'before_flush', fail_audit)
    with orm_session() as db:
        assert not list(db.scalars(select(PurchaseRequest)))
        assert not list(db.scalars(select(MrpConversion)))
        assert db.get(MrpPlan, record['id']).version == record['version']
    assert len(client.get(MRP+f'/plans/{record["id"]}/changes', headers=admin).json()) == 3


def test_utc_start_expiry_input_tampering_and_duplicate_references(seeded, monkeypatch):
    client, admin, reviewer, planner, viewer, materials, _ = seeded
    data = payload(client, admin, materials)
    for edit in ({'start_date':'2029-12-31'},{'snapshot':{'suggestions':[]}},{'reason':'  '},
                 {'manual_demands':[{'material_id':True,'quantity':'1','due_date':START,'reference':'错误'}]}):
        assert client.post(MRP+'/plans', headers=admin, json={**data,**edit}).status_code == 422
    plan = approved(client, admin, reviewer, data)
    assert client.post(MRP+'/plans', headers=admin, json=data).status_code == 409
    monkeypatch.setattr(mrp, 'today', lambda:'2030-01-02')
    assert client.get(MRP+f'/plans/{plan["id"]}/check', headers=admin).json()['expired_start_date']


def test_v48_upgrade_preserves_stock_and_is_idempotent(seeded, remove_mrp_schema):
    client, admin, reviewer, planner, viewer, materials, _ = seeded
    with sqlite3.connect(os.environ['NEXORA_DB_PATH']) as db:
        before = db.execute('SELECT * FROM stock_movements ORDER BY id').fetchall()
        remove_mrp_schema(db)
        db.execute('PRAGMA user_version = 48')
    migrate()
    migrate()
    with sqlite3.connect(os.environ['NEXORA_DB_PATH']) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 81
        assert db.execute('SELECT * FROM stock_movements ORDER BY id').fetchall() == before
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        assert len(Base.metadata.tables) == 178
        assert db.execute("SELECT COUNT(*) FROM role_permissions WHERE role_code='planner' AND permission_code='purchase_request.create'").fetchone()[0] == 1


def test_upgrade_failure_rolls_back_new_tables(seeded, remove_mrp_schema, monkeypatch):
    from contextlib import contextmanager
    import app.core.database as database
    with database.connection() as db:
        remove_mrp_schema(db)
        db.execute('PRAGMA user_version = 48')
    original = database.connection
    @contextmanager
    def failing_connection():
        with original() as db:
            db.set_authorizer(lambda operation, name, *_: sqlite3.SQLITE_DENY
                if operation == sqlite3.SQLITE_CREATE_TABLE and name == 'mrp_conversions' else sqlite3.SQLITE_OK)
            yield db
    monkeypatch.setattr(database, 'connection', failing_connection)
    with pytest.raises(Exception):
        migrate()
    with original() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 48
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='mrp_policies'").fetchone()
        assert not db.execute("SELECT 1 FROM permissions WHERE code='mrp.view'").fetchone()


def test_previous_submitter_cannot_review_after_resubmission(seeded):
    client, admin, reviewer, planner, viewer, materials, _ = seeded
    record = client.post(MRP+'/plans', headers=admin, json=payload(client, admin, materials)).json()
    record = client.post(MRP+f'/plans/{record["id"]}/submit', headers=planner,
        json={'version':record['version'],'reason':'初次提交'}).json()
    record = client.post(MRP+f'/plans/{record["id"]}/reject', headers=reviewer,
        json={'version':record['version'],'reason':'退回核对'}).json()
    record = client.post(MRP+f'/plans/{record["id"]}/submit', headers=admin,
        json={'version':record['version'],'reason':'重新提交'}).json()
    assert len(record['author_ids']) == 2
    # 后续授予审核权限不能消除这个账号已经参与编制的事实。
    client.post(BASE+'/roles', headers=admin, json={'code':'mrp_review','label':'计划审核','permissions':['mrp.view','mrp.review']})
    planner_id = client.get(BASE+'/auth/me', headers=planner).json()['id']
    client.put(BASE+f'/users/{planner_id}/roles', headers=admin, json={'roles':['planner','mrp_review']})
    assert client.post(MRP+f'/plans/{record["id"]}/approve', headers=planner,
        json={'version':record['version'],'reason':'历史提交人审核'}).status_code == 403
