"""用途在授权候选、新单据与历史履约中的真实接口回归。"""

from test_material_catalog import client, create
from approval_test_helpers import approve_document


def call(client, method, path, data=None, status=200):
    response = client.request(method, '/api/v1/' + path, json=data)
    assert response.status_code == status, response.text
    return response.json() if response.content else None


def test_authorized_choices_include_independent_uses_without_product_pagination(client):
    raw = create(client)
    material = create(client, {'sku': 'USES', 'name': '用途测试', 'unit': '件'})
    profile = call(client, 'POST', 'products', {'material_id': material['id'], 'kind': 'finished',
        'can_purchase': False, 'can_sell': True, 'can_produce': False}, 201)
    # 无须先读产品页；授权物料接口仍保留完整目录供库存和历史资料使用。
    for path in ['materials', 'crm/options', 'after-sales', 'production/mrp/options']:
        result = call(client, 'GET', path)
        rows = result if isinstance(result, list) else result['materials']
        current = next(row for row in rows if row['id'] == material['id'])
        assert current['can_purchase'] is False and current['can_sell'] is True and current['can_produce'] is False
        legacy = next(row for row in rows if row['id'] == raw['id'])
        assert all(legacy[key] is True for key in ('can_purchase', 'can_sell', 'can_produce'))
    call(client, 'PUT', f"products/{profile['id']}", {'kind': 'finished', 'version': 1,
        'can_purchase': True, 'can_sell': False, 'can_produce': True, 'reason': '切换独立用途'})
    changed = next(row for row in call(client, 'GET', 'materials') if row['id'] == material['id'])
    assert changed['can_purchase'] is True and changed['can_sell'] is False and changed['can_produce'] is True
    call(client, 'DELETE', f"products/{profile['id']}", {'version': 2, 'reason': '归档子机型'})
    retained = next(row for row in call(client, 'GET', 'materials') if row['id'] == material['id'])
    assert retained['can_purchase'] is True and retained['can_sell'] is False and retained['can_produce'] is False


def test_purchase_restriction_blocks_new_edit_conversion_and_free_receipts_but_keeps_order_fulfilment(client):
    material = create(client)
    supplier = call(client, 'POST', 'suppliers', {'name': '用途供应商'}, 201)['id']
    line = {'material_id': material['id'], 'quantity': '2', 'unit_price': '3'}
    request = call(client, 'POST', 'purchase-requests', {'lines': [line]}, 201)
    order = call(client, 'POST', 'purchase-orders', {'supplier_id': supplier, 'lines': [line]}, 201)
    approve_document(client, dict(client.headers), 'PurchaseOrder', order['id'])
    call(client, 'POST', f"purchase-orders/{order['id']}/confirm")
    call(client, 'POST', 'products', {'material_id': material['id'], 'kind': 'finished', 'can_purchase': False}, 201)
    for method, path, data in [
        ('POST', 'purchase-requests', {'lines': [line]}),
        ('PUT', f"purchase-requests/{request['id']}", {'lines': [line]}),
        ('POST', 'purchase-orders', {'supplier_id': supplier, 'lines': [line]}),
        ('POST', 'purchase-orders', {'supplier_id': supplier, 'purchase_request_id': request['id'],
            'lines': [{**line, 'purchase_request_line_id': request['lines'][0]['id']}]}),
        ('POST', 'receipts', {'supplier_id': supplier, 'lines': [{'material_id': material['id'], 'quantity': '1'}]})
    ]:
        assert '未允许采购' in call(client, method, path, data, 409)['detail']
    assert call(client, 'GET', 'purchase-requests')[0]['lines'] == request['lines']
    # 关联已确认旧订单的入库是履约，不能因当前用途关闭而失去接收货物的能力。
    receipt = call(client, 'POST', 'receipts', {'supplier_id': supplier, 'purchase_order_id': order['id'],
        'lines': [{'material_id': material['id'], 'quantity': '1'}]}, 201)
    approve_document(client, dict(client.headers), 'Receipt', receipt['id'])
    call(client, 'POST', f"receipts/{receipt['id']}/post")


def test_mrp_explicit_supply_modes_obey_independent_uses_and_auto_remains_available(client):
    material = create(client)
    call(client, 'POST', 'products', {'material_id': material['id'], 'kind': 'finished',
        'can_purchase': False, 'can_produce': False}, 201)
    policy = {'version': 0, 'supply_mode': 'auto', 'lead_time_days': 0, 'safety_stock': '0',
        'minimum_quantity': '0', 'multiple_quantity': '0', 'reason': '用途参数校验'}
    for mode, label in [('buy', '采购'), ('make', '生产')]:
        assert '未允许' + label in call(client, 'PUT', f"production/mrp/policies/{material['id']}",
            {**policy, 'supply_mode': mode}, 409)['detail']
    call(client, 'PUT', f"production/mrp/policies/{material['id']}", policy)
