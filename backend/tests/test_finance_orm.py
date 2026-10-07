"""财务 ORM 迁移：来源方向、并发余额与失败回滚。"""

from approval_test_helpers import approve_document, prepare_purchase_return

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.models import PaymentRecord
from app.core.orm import orm_session
from app.main import app


@pytest.fixture
def cycle(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'finance-orm.db'))
    with TestClient(app, client=('127.0.0.1', 12000), raise_server_exceptions=False) as client:
        def api(method, path, payload=None, expected=200):
            response = client.request(method, '/api/v1/' + path, json=payload)
            assert response.status_code == expected, response.text
            return response.json()

        api('POST', 'setup/admin', {'username': 'admin', 'password': 'secure-pass-123'}, 201)
        token = api('POST', 'auth/login', {'username': 'admin', 'password': 'secure-pass-123'})['token']
        client.headers['Authorization'] = f'Bearer {token}'
        supplier = api('POST', 'suppliers', {'name': '供应商'}, 201)['id']
        customer = api('POST', 'customers', {'name': '客户'}, 201)['id']
        material = api('POST', 'materials', {'sku': 'FIN', 'name': '测试物料', 'unit': '件'}, 201)['id']
        purchase = api('POST', 'purchase-orders', {'supplier_id': supplier,
            'lines': [{'material_id': material, 'quantity': '2', 'unit_price': '5'}]}, 201)['id']
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, dict(client.headers), 'PurchaseOrder', purchase)
        api('POST', f'purchase-orders/{purchase}/confirm')
        receipt = api('POST', 'receipts', {'supplier_id': supplier, 'purchase_order_id': purchase,
            'lines': [{'material_id': material, 'quantity': '2'}]}, 201)
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, dict(client.headers), 'Receipt', receipt['id'])
        api('POST', f'receipts/{receipt["id"]}/post')
        sale = api('POST', 'sales-orders', {'customer_id': customer,
            'lines': [{'material_id': material, 'quantity': '1', 'unit_price': '10'}]}, 201)['id']
        approve_document(client, dict(client.headers), 'SalesOrder', sale)
        api('POST', f'sales-orders/{sale}/confirm')
        shipment = api('POST', 'shipments', {'sales_order_id': sale, 'warehouse_id': 1,
            'lines': [{'material_id': material, 'quantity': '1'}]}, 201)
        approve_document(client, dict(client.headers), 'Shipment', shipment['id'])
        api('POST', f'shipments/{shipment["id"]}/post')
        yield client, api, purchase, sale, receipt, shipment


@pytest.mark.parametrize('kind', ['receivable', 'payable'])
def test_parallel_payments_cannot_overdraw_same_order(cycle, kind):
    client, api, purchase, sale, *_ = cycle
    order_id = sale if kind == 'receivable' else purchase
    payload = {'kind': kind, 'order_id': order_id, 'action': 'settlement', 'amount': '7'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda reference: client.post('/api/v1/finance/payment-records',
            json={**payload, 'reference': reference}), ('FIRST', 'SECOND')))
    assert sorted(row.status_code for row in responses) == [201, 409]
    account = next(item for item in api('GET', 'finance/accounts') if item['kind'] == kind)
    assert account['settled_amount'] == '7.00' and account['outstanding_amount'] == '3.00'
    # 同号重复写入的金额仍在余额以内，须真正触发唯一性保护并整体回滚。
    duplicate = {**payload, 'amount': '1', 'reference': 'DUPLICATE'}
    api('POST', 'finance/payment-records', duplicate, 201)
    api('POST', 'finance/payment-records', duplicate, 409)
    assert next(item for item in api('GET', 'finance/accounts') if item['kind'] == kind)['settled_amount'] == '8.00'


def test_reversal_failure_rolls_back_then_concurrent_retry_once(cycle, monkeypatch):
    client, api, _, sale, *_ = cycle
    record = api('POST', 'finance/payment-records', {'kind': 'receivable', 'order_id': sale,
        'action': 'settlement', 'amount': '5', 'reference': 'BANK'}, 201)
    from app.finance import routes
    original = routes.payment_data

    def failed_response(*_):
        raise RuntimeError('模拟冲销写入后响应失败')

    monkeypatch.setattr(routes, 'payment_data', failed_response)
    path = f'/api/v1/finance/payment-records/{record["id"]}/reverse'
    assert client.post(path, json={'reason': '错误登记'}).status_code == 500
    monkeypatch.setattr(routes, 'payment_data', original)
    with orm_session() as db:
        rows = list(db.scalars(select(PaymentRecord)))
        assert len(rows) == 1 and rows[0].amount == '5.00' and rows[0].action == 'settlement'
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post(path, json={'reason': '错误登记'}), range(2)))
    assert sorted(row.status_code for row in responses) == [201, 409]
    records = api('GET', 'finance/payment-records')
    assert len(records) == 2 and sum((Decimal(row['amount']) for row in records), Decimal(0)) == 0
    assert records[0]['reverses_id'] == record['id'] and records[0]['note'] == '错误登记'


def test_all_eight_sources_preserve_original_and_reversal_amounts(cycle):
    client, api, _, _, receipt, shipment = cycle
    sale_return = api('POST', 'sales-returns', {'shipment_id': shipment['id'], 'warehouse_id': 1,
        'reason': '退回', 'lines': [{'shipment_line_id': shipment['lines'][0]['id'], 'quantity': '0.5'}]}, 201)
    approve_document(client, dict(client.headers), 'SalesReturn', sale_return['id'])
    api('POST', f'sales-returns/{sale_return["id"]}/post')
    purchase_return = api('POST', 'purchase-returns', {'receipt_id': receipt['id'], 'reason': '退回',
        'lines': [{'receipt_line_id': receipt['lines'][0]['id'], 'quantity': '0.5'}]}, 201)
    prepare_purchase_return(client, dict(client.headers), purchase_return['id'])
    api('POST', f'purchase-returns/{purchase_return["id"]}/post')
    # 冲销前显式审批固定原因，保留原八类业务来源金额与依赖核对。
    approve_document(client, dict(client.headers), 'Receipt', receipt['id'], intent='reverse', reason='更正')
    approve_document(client, dict(client.headers), 'PurchaseReturn', purchase_return['id'], intent='reverse', reason='更正')
    approve_document(client, dict(client.headers), 'SalesReturn', sale_return['id'], intent='reverse', reason='更正')
    approve_document(client, dict(client.headers), 'Shipment', shipment['id'], intent='reverse', reason='更正')
    for path in (f'purchase-returns/{purchase_return["id"]}', f'sales-returns/{sale_return["id"]}',
                 f'shipments/{shipment["id"]}', f'receipts/{receipt["id"]}'):
        api('POST', path + '/reverse', {'reason': '更正'}, 201)
    report = api('GET', 'finance/receivables-payables')
    assert report['receivable_amount'] == report['payable_amount'] == '0.00'
    assert {row['source_type']: row['amount'] for row in report['entries']} == {
        'shipment': '10.00', 'shipment_reversal': '-10.00',
        'sales_return': '-5.00', 'sales_return_reversal': '5.00',
        'receipt': '10.00', 'receipt_reversal': '-10.00',
        'purchase_return': '-2.50', 'purchase_return_reversal': '2.50'}
    assert all(row['posted_by_name'] == 'admin' and row['posted_at'] for row in report['entries'])
    assert len({row['key'] for row in report['entries']}) == 8
    overview = api('GET', 'finance/overview')
    assert overview['report'] == report
    assert all(row['business_amount'] == row['outstanding_amount'] == '0.00' for row in overview['accounts'])
