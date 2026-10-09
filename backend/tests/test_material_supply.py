"""采购计划、分批到货与入库的供需数量必须守恒且遵循真实权限。"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from approval_test_helpers import approve_document

ROOT = '/api/v1'
QUERY = ROOT + '/inventory/material-supply/query'


@pytest.fixture
def erp(monkeypatch, tmp_path):
    # 使用隔离数据库和真实审批，不碰正在运行的服务或用户业务数据。
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'material-supply.db'))
    with TestClient(app, client=('127.0.0.1', 13000)) as client:
        assert client.post(ROOT + '/setup/admin', json={'username': 'admin', 'password': 'secure-pass-123'}).status_code == 201
        token = client.post(ROOT + '/auth/login', json={'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
        admin = {'Authorization': 'Bearer ' + token}

        def api(method, path, payload=None, expected=200):
            response = client.request(method, ROOT + path, headers=admin, json=payload)
            assert response.status_code == expected, response.text
            return response.json()

        material = api('POST', '/materials', {'sku': 'SUPPLY', 'name': '供需物料', 'unit': '件'}, 201)['id']
        supplier = api('POST', '/suppliers', {'name': '供需供应商'}, 201)['id']
        yield client, admin, api, material, supplier


def snapshot(erp):
    row = erp[2]('POST', '/inventory/material-supply/query', {'material_ids': [erp[3]]})
    assert row['scope'] == 'all_warehouses'
    return row['rows'][0]


def counts(erp):
    row = snapshot(erp)
    return tuple(row[name + '_quantity'] for name in ('stock', 'planned', 'awaiting_delivery', 'awaiting_inbound'))


def test_partial_receiving_post_reversal_and_cancellation_do_not_double_count(erp):
    client, admin, api, material, supplier = erp
    order = api('POST', '/purchase-orders', {'supplier_id': supplier, 'lines': [
        {'material_id': material, 'quantity': '1000', 'unit_price': '1'}]}, 201)
    # 未批准订单不等于已采购；批准但尚未正式确认时仍属于计划阶段。
    assert counts(erp) == ('0.000', '0.000', '0.000', '0.000')
    approve_document(client, admin, 'PurchaseOrder', order['id'])
    assert counts(erp) == ('0.000', '1000.000', '0.000', '0.000')
    api('POST', f'/purchase-orders/{order["id"]}/confirm')
    assert counts(erp) == ('0.000', '0.000', '1000.000', '0.000')

    goods = api('POST', '/purchase-goods-receipts', {'purchase_order_id': order['id'], 'warehouse_id': 1,
        'lines': [{'purchase_order_line_id': order['lines'][0]['id'], 'accepted_quantity': '300',
                   'rejected_quantity': '10', 'rejection_reason': '检验不合格'}]}, 201)
    assert counts(erp) == ('0.000', '0.000', '1000.000', '0.000')
    approve_document(client, admin, 'PurchaseGoodsReceipt', goods['id'])
    goods = api('POST', f'/purchase-goods-receipts/{goods["id"]}/confirm')
    assert counts(erp) == ('0.000', '0.000', '700.000', '300.000')
    approve_document(client, admin, 'Receipt', goods['inbound_receipt_id'])
    # 同一入库单同时有收货依据和批准记录，也只能统计一次。
    assert counts(erp) == ('0.000', '0.000', '700.000', '300.000')
    api('POST', f'/receipts/{goods["inbound_receipt_id"]}/post')
    assert counts(erp) == ('300.000', '0.000', '700.000', '0.000')

    approve_document(client, admin, 'Receipt', goods['inbound_receipt_id'], intent='reverse', reason='收货数量登记错误')
    api('POST', f'/receipts/{goods["inbound_receipt_id"]}/reverse', {'reason': '收货数量登记错误'}, 201)
    assert counts(erp) == ('0.000', '0.000', '1000.000', '0.000')
    api('POST', f'/purchase-orders/{order["id"]}/cancel')
    assert counts(erp) == ('0.000', '0.000', '0.000', '0.000')


def test_approved_request_split_orders_remain_planned_until_confirmed(erp):
    client, admin, api, material, supplier = erp
    request = api('POST', '/purchase-requests', {'reference': '拆分计划', 'lines': [
        {'material_id': material, 'quantity': '10.125'}]}, 201)
    assert counts(erp)[1] == '0.000'
    approve_document(client, admin, 'PurchaseRequest', request['id'])
    assert counts(erp)[1] == '10.125'
    orders = []
    for value in ('3.025', '2.100'):
        orders.append(api('POST', '/purchase-orders', {'supplier_id': supplier, 'purchase_request_id': request['id'],
            'lines': [{'material_id': material, 'purchase_request_line_id': request['lines'][0]['id'],
                       'quantity': value, 'unit_price': '1'}]}, 201))
    assert counts(erp) == ('0.000', '10.125', '0.000', '0.000')
    approve_document(client, admin, 'PurchaseOrder', orders[0]['id'])
    api('POST', f'/purchase-orders/{orders[0]["id"]}/confirm')
    assert counts(erp) == ('0.000', '7.100', '3.025', '0.000')
    api('POST', f'/purchase-orders/{orders[1]["id"]}/cancel')
    assert counts(erp) == ('0.000', '7.100', '3.025', '0.000')


def test_mrp_conversion_counts_downstream_once_and_stale_plan_is_excluded(erp):
    client, admin, api, material, _ = erp
    def plan(reference):
        options = api('GET', '/production/mrp/options')
        record = api('POST', '/production/mrp/plans', {'reference': reference, 'start_date': options['today'],
            'reason': '核对采购计划', 'demand_dates': [], 'supply_dates': [
                {'key': row['key'], 'due_date': options['today']} for row in options['supplies'] if not row.get('due_date')],
            'manual_demands': [{'material_id': material, 'quantity': '10', 'due_date': options['today'], 'reference': reference}]}, 201)
        approve_document(client, admin, 'MrpPlan', record['id'], reason='核对采购计划')
        return api('GET', f'/production/mrp/plans/{record["id"]}')

    first = plan('计划一')
    assert counts(erp)[1] == '10.000'
    converted = api('POST', f'/production/mrp/plans/{first["id"]}/convert', {
        'version': first['version'], 'suggestion_key': first['snapshot']['suggestions'][0]['key'], 'reason': '转入采购申请'}, 201)
    assert counts(erp)[1] == '10.000'
    api('POST', f'/purchase-requests/{converted["purchase_request_id"]}/cancel')
    assert counts(erp)[1] == '0.000'
    plan('计划二')
    second = plan('计划三')
    # 两份相同来源的有效计算方案不能叠加；采用最近批准方案。
    assert counts(erp)[1] == '10.000'
    warehouse = api('POST', '/warehouse-inbounds', {'warehouse_id': 1, 'reason': 'other', 'note': '库存变化核对', 'lines': [
        {'material_id': material, 'quantity': '0.125'}]}, 201)
    approve_document(client, admin, 'WarehouseInbound', warehouse['id'])
    api('POST', f'/warehouse-inbounds/{warehouse["id"]}/post')
    assert counts(erp) == ('0.125', '0.000', '0.000', '0.000')
    # 当前展示不改写旧计划的计算结果。
    assert api('GET', f'/production/mrp/plans/{second["id"]}')['snapshot'] == second['snapshot']


def test_multiwarehouse_exact_decimals_and_manual_inbound_require_approval(erp):
    client, admin, api, material, supplier = erp
    warehouse = api('POST', '/warehouses', {'code': 'SUPPLY-2', 'name': '第二仓库'}, 201)['id']
    for warehouse_id, value in ((1, '0.100'), (1, '0.200'), (warehouse, '0.125')):
        receipt = api('POST', '/receipts', {'supplier_id': supplier, 'warehouse_id': warehouse_id,
            'lines': [{'material_id': material, 'quantity': value}]}, 201)
        assert counts(erp)[3] == '0.000'
        approve_document(client, admin, 'Receipt', receipt['id'])
        assert counts(erp)[3] == value
        api('POST', f'/receipts/{receipt["id"]}/post')
    assert counts(erp)[0] == '0.425'
    assert sorted(row['quantity'] for row in snapshot(erp)['sources'] if row['phase'] == 'stock') == ['0.125', '0.300']


def test_permissions_and_revocation_hide_unavailable_quantities_and_sources(erp):
    client, admin, api, material, _ = erp
    request = api('POST', '/purchase-requests', {'lines': [{'material_id': material, 'quantity': '8'}]}, 201)
    approve_document(client, admin, 'PurchaseRequest', request['id'])
    assert counts(erp)[1] == '8.000'
    api('POST', '/roles', {'code': 'supply_limited', 'label': '仅看库存', 'permissions': ['inventory.view']}, 201)
    api('POST', '/users', {'username': 'limited', 'password': 'secure-pass-123', 'roles': ['supply_limited']}, 201)
    token = client.post(ROOT + '/auth/login', json={'username': 'limited', 'password': 'secure-pass-123'}).json()['token']
    limited = {'Authorization': 'Bearer ' + token}
    result = client.post(QUERY, headers=limited, json={'material_ids': [material]}).json()['rows'][0]
    assert result['planned_quantity'] is None and result['stock_quantity'] == '0.000'
    assert not any(row['phase'] == 'planned' for row in result['sources'])
    api('PUT', '/roles/supply_limited', {'label': '已撤权', 'permissions': []})
    assert client.post(QUERY, headers=limited, json={'material_ids': [material]}).status_code == 403
    assert client.post(QUERY, json={'material_ids': [material]}).status_code == 401


@pytest.mark.parametrize('payload', [None, {}, {'material_ids': []}, {'material_ids': [True]},
    {'material_ids': ['1']}, {'material_ids': [-1]}, {'material_ids': [1, 1]},
    {'material_ids': list(range(1, 102))}, {'material_ids': [1], 'permissions': ['admin']},
    {'material_ids': [999999]}, {'material_ids': [10**30]}])
def test_bad_queries_are_rejected(erp, payload):
    assert erp[0].post(QUERY, headers=erp[1], json=payload).status_code == 422
