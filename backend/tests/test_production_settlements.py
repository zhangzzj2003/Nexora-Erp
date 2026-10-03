"""验证库存成本传入生产、完工分摊精度、来源锁定和多级结算冲销。"""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.database import connection, migrate
from app.main import app


@pytest.fixture
def erp(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'settlements.db'))
    with TestClient(app, client=('127.0.0.1', 12000)) as client:
        client.post('/api/v1/setup/admin', json={'username': 'admin', 'password': 'secure-pass-123'})
        token = client.post('/api/v1/auth/login', json={
            'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
        headers = {'Authorization': f'Bearer {token}'}

        def request(method, path, payload=None, status=200):
            response = client.request(method, f'/api/v1/{path}', json=payload, headers=headers)
            assert response.status_code == status, response.text
            return response.json()

        supplier = request('POST', 'suppliers', {'name': '供应商'}, 201)['id']

        def material(sku):
            return request('POST', 'materials', {'sku': sku, 'name': sku, 'unit': '件'}, 201)['id']

        def receipt(material_id, quantity, price=None):
            row = request('POST', 'receipts', {'supplier_id': supplier, 'warehouse_id': 1,
                'lines': [{'material_id': material_id, 'quantity': quantity}]}, 201)
            request('POST', f'receipts/{row["id"]}/post')
            movement = next(item for item in request('GET', 'inventory/valuation')['movements']
                            if item['source_type'] == 'receipt' and item['source_id'] == row['id'])
            if price is not None:
                request('POST', 'inventory/valuation/inputs', {'movement_id': movement['id'],
                    'unit_cost': price, 'reference': f'PRICE-{row["id"]}', 'reason': '原材料核价'}, 201)
            return movement['id']

        def work_order(component, product, quantity='1'):
            bom = request('POST', 'boms', {'product_material_id': product, 'base_quantity': '1',
                'lines': [{'component_material_id': component, 'quantity': '1'}]}, 201)
            request('POST', f'boms/{bom["id"]}/activate')
            order = request('POST', 'work-orders', {'bom_id': bom['id'], 'warehouse_id': 1,
                'target_quantity': quantity}, 201)
            request('POST', f'work-orders/{order["id"]}/release')
            issue = request('POST', 'material-issues', {'work_order_id': order['id'], 'warehouse_id': 1,
                'lines': [{'work_order_line_id': order['lines'][0]['id'], 'quantity': quantity}]}, 201)
            request('POST', f'material-issues/{issue["id"]}/post')
            return order, issue

        def complete(order, reported='1', accepted='1'):
            row = request('POST', 'production-completions', {
                'work_order_id': order['id'], 'reported_quantity': reported}, 201)
            request('POST', f'production-completions/{row["id"]}/inspect', {
                'accepted_quantity': accepted, 'qc_note': '检验记录'})
            request('POST', f'production-completions/{row["id"]}/post')
            return row['id']

        yield client, headers, request, material, receipt, work_order, complete


def test_inventory_costs_returns_allocations_and_sales_cost(erp):
    _, _, api, material, receipt, work_order, complete = erp
    raw, product = material('RAW'), material('PRODUCT')
    receipt(raw, '10', '2.5555')
    order, issue = work_order(raw, product, '3')
    report = api('GET', 'production-costs')
    assert report['orders'][0]['total_amount'] == '7.67'
    assert report['unpriced_lines'] == []
    assert report['material_sources'][0]['cost_source'] == 'inventory'
    api('POST', 'production-costs/material-valuations', {'material_issue_line_id': issue['lines'][0]['id'],
        'unit_cost': '99', 'reference': 'OVERRIDE'}, 409)
    returned = api('POST', 'material-returns', {'material_issue_id': issue['id'], 'reason': '退回多领',
        'lines': [{'material_issue_line_id': issue['lines'][0]['id'], 'quantity': '1'}]}, 201)
    api('POST', f'material-returns/{returned["id"]}/post')
    assert api('GET', 'production-costs')['orders'][0]['total_amount'] == '5.11'
    second_issue = api('POST', 'material-issues', {'work_order_id': order['id'], 'warehouse_id': 1,
        'lines': [{'work_order_line_id': order['lines'][0]['id'], 'quantity': '1'}]}, 201)
    api('POST', f'material-issues/{second_issue["id"]}/post')
    for kind, amount in (('labor', '0.01'), ('overhead', '0.02')):
        api('POST', 'production-costs/charges', {'work_order_id': order['id'], 'kind': kind,
            'amount': amount, 'reference': kind}, 201)
    completed = [complete(order) for _ in range(3)]
    settlement = api('POST', 'production-costs/settlements', {
        'work_order_id': order['id'], 'reference': 'SETTLE-1'}, 201)
    assert settlement['total_amount'] == '7.70'
    assert [row['amount'] for row in settlement['allocations']] == ['2.57', '2.56', '2.57']
    assert sum(Decimal(row['amount']) for row in settlement['allocations']) == Decimal('7.70')
    assert len(settlement['material_sources']) == 2
    assert len(settlement['charges']) == 2
    report = api('GET', 'inventory/valuation')
    assert next(row for row in report['materials'] if row['id'] == product)['amount'] == '7.70'
    assert all(row['settlement_id'] == settlement['id'] for row in report['movements']
               if row['source_type'] == 'production_completion')
    customer = api('POST', 'customers', {'name': '客户'}, 201)['id']
    sale = api('POST', 'sales-orders', {'customer_id': customer,
        'lines': [{'material_id': product, 'quantity': '1', 'unit_price': '10'}]}, 201)
    api('POST', f'sales-orders/{sale["id"]}/confirm')
    shipment = api('POST', 'shipments', {'sales_order_id': sale['id'], 'warehouse_id': 1,
        'lines': [{'material_id': product, 'quantity': '1'}]}, 201)
    api('POST', f'shipments/{shipment["id"]}/post')
    report = api('GET', 'inventory/valuation')
    assert next(row for row in report['movements'] if row['source_type'] == 'shipment')['amount'] == '-2.57'
    assert next(row for row in report['materials'] if row['id'] == product)['amount'] == '5.13'
    # 已结算后，不得直接改费用或冲销完工来破坏金额与来源关系。
    api('POST', f'production-completions/{completed[0]}/reverse', {'reason': '更正'}, 409)
    api('POST', 'production-costs/charges', {'work_order_id': order['id'], 'kind': 'labor',
        'amount': '1', 'reference': 'LATE'}, 409)
    api('POST', f'production-costs/{settlement["charges"][0]["id"]}/reverse', {'reason': '更正'}, 409)


def test_settlement_reverse_history_reprice_and_dependencies(erp):
    _, _, api, material, receipt, work_order, complete = erp
    raw, semi, final = material('RAW'), material('SEMI'), material('FINAL')
    movement_id = receipt(raw, '2', '10')
    first, _ = work_order(raw, semi)
    complete(first)
    first_settlement = api('POST', 'production-costs/settlements', {
        'work_order_id': first['id'], 'reference': 'FIRST'}, 201)
    second, _ = work_order(semi, final)
    complete(second)
    second_settlement = api('POST', 'production-costs/settlements', {
        'work_order_id': second['id'], 'reference': 'SECOND'}, 201)
    assert second_settlement['material_amount'] == '10.00'
    api('POST', f'production-costs/settlements/{first_settlement["id"]}/reverse', {'reason': '更正'}, 409)
    api('POST', 'inventory/valuation/inputs', {'movement_id': movement_id, 'unit_cost': '12',
        'reference': 'REPRICE', 'reason': '更正'}, 409)
    api('POST', f'production-costs/settlements/{second_settlement["id"]}/reverse', {'reason': ' '}, 422)
    api('POST', f'production-costs/settlements/{second_settlement["id"]}/reverse', {'reason': '成本复核'})
    api('POST', f'production-costs/settlements/{first_settlement["id"]}/reverse', {'reason': '价格变更'})
    api('POST', f'production-costs/settlements/{first_settlement["id"]}/reverse', {'reason': '重复'}, 409)
    api('POST', 'inventory/valuation/inputs', {'movement_id': movement_id, 'unit_cost': '12',
        'reference': 'REPRICE', 'reason': '更正'}, 201)
    api('POST', 'production-costs/settlements', {'work_order_id': first['id'], 'reference': 'FIRST'}, 409)
    updated = api('POST', 'production-costs/settlements', {
        'work_order_id': first['id'], 'reference': 'FIRST-NEW'}, 201)
    assert updated['total_amount'] == '12.00'
    history = api('GET', 'production-costs/settlements')
    original = next(row for row in history if row['id'] == first_settlement['id'])
    assert original['status'] == 'reversed'
    assert original['total_amount'] == '10.00'
    assert original['material_sources'][0]['unit_cost'] == '10'
    assert original['reversal_reason'] == '价格变更'
    assert api('GET', 'production-costs')['orders'][-1]['settlement_id'] == updated['id']


def test_manual_fallback_and_settlement_preconditions(erp):
    _, _, api, material, receipt, work_order, complete = erp
    raw, product = material('RAW'), material('PRODUCT')
    raw_movement = receipt(raw, '2')
    order, issue = work_order(raw, product)
    api('POST', 'production-costs/settlements', {'work_order_id': order['id'], 'reference': 'EARLY'}, 409)
    completion_id = complete(order)
    api('POST', 'production-costs/settlements', {'work_order_id': order['id'], 'reference': 'UNKNOWN'}, 409)
    api('POST', 'production-costs/material-valuations', {'material_issue_line_id': issue['lines'][0]['id'],
        'unit_cost': '1.5', 'reference': 'FALLBACK'}, 201)
    api('POST', 'production-costs/settlements', {'work_order_id': 999, 'reference': 'MISSING'}, 404)
    api('POST', 'production-costs/settlements', {'work_order_id': order['id'], 'reference': ' '}, 422)
    settled = api('POST', 'production-costs/settlements', {
        'work_order_id': order['id'], 'reference': 'MANUAL'}, 201)
    assert settled['material_sources'][0]['cost_source'] == 'manual'
    assert settled['allocations'][0]['amount'] == '1.50'
    api('POST', 'inventory/valuation/inputs', {'movement_id': raw_movement,
        'unit_cost': '5', 'reference': 'LATE-PRICE', 'reason': '补原料价格'}, 409)
    api('POST', 'inventory/valuation/inputs', {'movement_id': settled['allocations'][0]['movement_id'],
        'unit_cost': '99', 'reference': 'OVERRIDE', 'reason': '修改'}, 409)
    api('POST', f'production-costs/settlements/{settled["id"]}/reverse', {'reason': '完工重报'})
    api('POST', f'production-completions/{completion_id}/reverse', {'reason': '完工重报'})
    assert api('GET', 'production-costs/settlements')[0]['allocations'][0]['amount'] == '1.50'


def test_orm_settlement_rolls_back_all_flushed_records_on_failure(erp, monkeypatch):
    _, _, api, material, receipt, work_order, complete = erp
    raw, product = material('RAW'), material('PRODUCT')
    receipt(raw, '1', '1')
    order, _ = work_order(raw, product)
    complete(order)
    from app.production import settlements
    from fastapi import HTTPException
    original = settlements.settlement_data

    def failed_response(*_):
        raise HTTPException(409, '模拟分摊后异常')

    monkeypatch.setattr(settlements, 'settlement_data', failed_response)
    api('POST', 'production-costs/settlements', {'work_order_id': order['id'], 'reference': 'ROLLBACK'}, 409)
    monkeypatch.setattr(settlements, 'settlement_data', original)
    assert api('GET', 'production-costs/settlements') == []
    # 回滚必须释放写锁，重试同一个依据编号可以完整成功。
    result = api('POST', 'production-costs/settlements', {'work_order_id': order['id'], 'reference': 'ROLLBACK'}, 201)
    assert len(result['allocations']) == 1 and len(result['material_sources']) == 1


def test_settlement_rejects_all_rejected_output_and_pending_drafts(erp):
    _, _, api, material, receipt, work_order, complete = erp
    raw, product = material('RAW'), material('PRODUCT')
    receipt(raw, '2', '1')
    order, _ = work_order(raw, product)
    draft = api('POST', 'production-completions', {
        'work_order_id': order['id'], 'reported_quantity': '1'}, 201)
    complete(order, accepted='0')
    api('POST', 'production-costs/settlements', {'work_order_id': order['id'], 'reference': 'DRAFT'}, 409)
    api('POST', f'production-completions/{draft["id"]}/cancel')
    api('POST', 'production-costs/settlements', {'work_order_id': order['id'], 'reference': 'REJECTED'}, 409)
    assert api('GET', 'production-costs/settlements') == []


def test_settlement_permissions_and_concurrent_duplicate(erp):
    client, headers, api, material, receipt, work_order, complete = erp
    raw, product = material('RAW'), material('PRODUCT')
    receipt(raw, '1', '1')
    order, _ = work_order(raw, product)
    complete(order)
    api('POST', 'users', {'username': 'planner', 'password': 'secure-pass-123', 'roles': ['planner']}, 201)
    token = client.post('/api/v1/auth/login', json={
        'username': 'planner', 'password': 'secure-pass-123'}).json()['token']
    planner = {'Authorization': f'Bearer {token}'}
    assert client.get('/api/v1/production-costs/settlements', headers=planner).status_code == 200
    payload = {'work_order_id': order['id'], 'reference': 'CONCURRENT'}
    assert client.post('/api/v1/production-costs/settlements', headers=planner, json=payload).status_code == 403
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post('/api/v1/production-costs/settlements',
            headers=headers, json=payload), range(2)))
    assert sorted(row.status_code for row in responses) == [201, 409]
    settlement = api('GET', 'production-costs/settlements')[0]
    assert client.post(f'/api/v1/production-costs/settlements/{settlement["id"]}/reverse',
        headers=planner, json={'reason': '越权'}).status_code == 403
    assert len(api('GET', 'production-costs/settlements')) == 1


def test_v38_upgrade_preserves_data_and_grants_settlement_permissions(monkeypatch, tmp_path, remove_v39_schema):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'upgrade.db'))
    migrate()
    with connection() as db:
        db.execute("INSERT INTO materials(sku, name, unit) VALUES ('OLD', '旧物料', '件')")
        remove_v39_schema(db)
        db.execute('PRAGMA user_version = 38')
    migrate()
    migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 65
        assert db.execute("SELECT name FROM materials WHERE sku = 'OLD'").fetchone()[0] == '旧物料'
        assert {row[0] for row in db.execute("SELECT role_code FROM role_permissions WHERE permission_code = 'production_cost.settle'")} == {'admin', 'finance'}
        assert db.execute('SELECT COUNT(*) FROM production_cost_settlements').fetchone()[0] == 0
