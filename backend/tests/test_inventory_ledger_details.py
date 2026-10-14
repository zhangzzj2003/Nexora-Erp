"""从真实流水追溯原单，覆盖冲销编号差异和领域查看权限。"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from approval_test_helpers import approve_document
from test_document_approval import context
from test_sales_document_approval import create_order
from app.inventory.ledger import ledger_document_target


def ledger_rows(client, auth):
    response = client.post('/api/v1/inventory-ledger/query', headers=auth, json={'page_size': 100})
    assert response.status_code == 200, response.text
    return response.json()['rows']


def detail(client, auth, movement_id):
    return client.get(f'/api/v1/inventory-ledger/{movement_id}/document', headers=auth)


def test_inbound_and_reversal_keep_original_document_and_are_read_only(context):
    client, auth, first = context
    # 特意让原单 ID 为 2、冲销 ID 为 1，避免相同编号掩盖误查另一张原单。
    second = client.post('/api/v1/warehouse-inbounds', headers=auth, json={
        'warehouse_id': 1, 'reason': 'gift', 'note': '应展示的原单',
        'lines': [{'material_id': first['lines'][0]['material_id'], 'quantity': '7'}]}).json()
    approve_document(client, auth, 'WarehouseInbound', second['id'])
    assert client.post(f"/api/v1/warehouse-inbounds/{second['id']}/post", headers=auth).status_code == 200
    approve_document(client, auth, 'WarehouseInbound', second['id'], intent='reverse', reason='核对更正')
    assert client.post(f"/api/v1/warehouse-inbounds/{second['id']}/reverse", headers=auth,
                       json={'reason': '核对更正'}).status_code == 201
    rows = ledger_rows(client, auth)
    assert len(rows) == 2
    for row in rows:
        response = detail(client, auth, row['id'])
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['movement_id'] == row['id']
        document = result['document']
        assert document['document_type'] == 'WarehouseInbound'
        assert document['document_id'] == second['id']
        assert document['document_no'] == second['document_no']
        assert document['status'] == 'executed'
        assert not any(document[key] for key in ('can_submit', 'can_review', 'can_withdraw'))
        assert {'label': '入库说明', 'value': '应展示的原单'} in document['summary']
        if row['source_type'].endswith('_reversal'):
            assert row['source_id'] != second['id']
            assert document['intent'] == 'reverse' and document['reversal_reason'] == '核对更正'
        else:
            assert document['intent'] == 'execute'
    assert ledger_rows(client, auth) == rows
    assert detail(client, auth, 999999).status_code == 404
    assert detail(client, auth, 0).status_code == 422


def make_viewer(client, auth, permissions):
    assert client.post('/api/v1/roles', headers=auth, json={
        'code': 'ledger_viewer', 'label': '台账查看', 'permissions': permissions}).status_code == 201
    assert client.post('/api/v1/users', headers=auth, json={
        'username': 'ledger_viewer', 'password': 'secure-pass-123', 'roles': ['ledger_viewer']}).status_code == 201
    token = client.post('/api/v1/auth/login', json={'username': 'ledger_viewer', 'password': 'secure-pass-123'}).json()['token']
    return {'Authorization': 'Bearer ' + token}


@pytest.mark.parametrize('permissions', [['inventory.view'], ['other_inbound.view']])
def test_document_requires_both_inventory_and_original_domain_permission(context, permissions):
    client, auth, inbound = context
    approve_document(client, auth, 'WarehouseInbound', inbound['id'])
    assert client.post(f"/api/v1/warehouse-inbounds/{inbound['id']}/post", headers=auth).status_code == 200
    movement = ledger_rows(client, auth)[0]
    viewer = make_viewer(client, auth, permissions)
    assert detail(client, viewer, movement['id']).status_code == 403
    assert detail(client, {}, movement['id']).status_code == 401


def test_sales_source_preserves_customer_visibility(context):
    client, auth, inbound = context
    approve_document(client, auth, 'WarehouseInbound', inbound['id'])
    client.post(f"/api/v1/warehouse-inbounds/{inbound['id']}/post", headers=auth)
    material = inbound['lines'][0]['material_id']
    order = create_order(client, auth, material)
    approve_document(client, auth, 'SalesOrder', order['id'])
    client.post(f"/api/v1/sales-orders/{order['id']}/confirm", headers=auth)
    shipment = client.post('/api/v1/shipments', headers=auth, json={'sales_order_id': order['id'], 'warehouse_id': 1,
        'lines': [{'material_id': material, 'quantity': '1'}]}).json()
    approve_document(client, auth, 'Shipment', shipment['id'])
    assert client.post(f"/api/v1/shipments/{shipment['id']}/post", headers=auth).status_code == 200
    row = next(row for row in ledger_rows(client, auth) if row['source_type'] == 'shipment')
    assert detail(client, auth, row['id']).json()['document']['document_id'] == shipment['id']
    viewer = make_viewer(client, auth, ['inventory.view', 'sales.view'])
    # 能查看台账和销售模块，仍不能读取不属于自己的客户单据。
    assert detail(client, viewer, row['id']).status_code == 404


@pytest.mark.parametrize('source, expected, field', [
    ('receipt', 'Receipt', 'receipt_id'), ('other_inbound', 'WarehouseInbound', 'inbound_id'),
    ('other_outbound', 'WarehouseOutbound', 'outbound_id'), ('shipment', 'Shipment', 'shipment_id'),
    ('purchase_return', 'PurchaseReturn', 'purchase_return_id'), ('sales_return', 'SalesReturn', 'sales_return_id'),
    ('stocktake', 'Stocktake', 'stocktake_id'), ('adjustment', 'StockAdjustment', 'adjustment_id'),
    ('material_issue', 'MaterialIssue', 'material_issue_id'), ('material_return', 'MaterialReturn', 'material_return_id'),
    ('production_completion', 'ProductionCompletion', 'production_completion_id'),
    ('transfer_in', 'Transfer', 'transfer_id'), ('transfer_out', 'Transfer', 'transfer_id')
])
def test_all_movement_sources_resolve_normal_and_reversal(source, expected, field):
    class Lookup:
        def get(self, model, identifier):
            assert identifier == 97 and model.__name__.endswith('Reversal')
            return SimpleNamespace(**{field: 12})
    db = Lookup()
    assert ledger_document_target(db, SimpleNamespace(source_type=source, source_id=12)) == (expected, 12, 'execute')
    reverse = source.replace('transfer_', 'transfer_reversal_') if source.startswith('transfer_') else source + '_reversal'
    assert ledger_document_target(db, SimpleNamespace(source_type=reverse, source_id=97)) == (expected, 12, 'reverse')


def test_missing_reversal_and_unknown_source_fail_without_guessing():
    db = SimpleNamespace(get=lambda *_: None)
    with pytest.raises(HTTPException) as missing:
        ledger_document_target(db, SimpleNamespace(source_type='receipt_reversal', source_id=97))
    assert missing.value.status_code == 404
    with pytest.raises(HTTPException) as unknown:
        ledger_document_target(db, SimpleNamespace(source_type='unknown_source', source_id=97))
    assert unknown.value.status_code == 422


@pytest.mark.parametrize('kind', ['inventory_balance', 'stock_flow'])
def test_report_material_columns_ids_and_complete_csv_match(context, kind):
    client, auth, inbound = context
    approve_document(client, auth, 'WarehouseInbound', inbound['id'])
    client.post(f"/api/v1/warehouse-inbounds/{inbound['id']}/post", headers=auth)
    filters = {'kind': kind, 'warehouse_id': 1, 'material_id': inbound['lines'][0]['material_id']}
    page = client.post('/api/v1/reports/inventory/query', headers=auth, json={**filters, 'page_size': 1}).json()
    export = client.post('/api/v1/reports/query', headers=auth, json=filters).json()
    assert [col['key'] for col in page['columns']][:3] == ['sku', 'material_name', 'warehouse']
    assert page['rows'] == export['rows']
    row = page['rows'][0]
    assert row['material_id'] == str(filters['material_id']) and row['warehouse_id'] == '1'
    assert row['material_name'] == '审批测试物料' and row['sku']
    assert export['csv'].startswith('\ufeff物料编号,物料名称,仓库,单位,')
