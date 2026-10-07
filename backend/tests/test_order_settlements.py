"""订单间贷方核销的金额、归属、权限和追加式撤销。"""

from approval_test_helpers import approve_document, prepare_purchase_return, execute_payment

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.core.database import connection
from app.core.models import AccountingPeriod
from app.core.orm import orm_session
from app.main import app


def test_order_credit_settlement_and_reversal(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'order-settlements.db'))
    base = '/api/v1'
    with TestClient(app, client=('127.0.0.1', 12000)) as client:
        client.post(f'{base}/setup/admin', json={'username': 'admin', 'password': 'secure-pass-123'})

        def auth(name):
            token = client.post(f'{base}/auth/login', json={
                'username': name, 'password': 'secure-pass-123'}).json()['token']
            return {'Authorization': f'Bearer {token}'}

        admin = auth('admin')
        for name, role in (('accountant', 'finance'), ('buyer', 'buyer')):
            assert client.post(f'{base}/users', headers=admin, json={
                'username': name, 'password': 'secure-pass-123', 'roles': [role]}).status_code == 201
        finance, buyer = auth('accountant'), auth('buyer')
        customer = client.post(f'{base}/customers', headers=admin, json={'name': '核销客户'}).json()['id']
        other_customer = client.post(f'{base}/customers', headers=admin, json={'name': '其他客户'}).json()['id']
        supplier = client.post(f'{base}/suppliers', headers=admin, json={'name': '库存供应商'}).json()['id']
        material = client.post(f'{base}/materials', headers=admin, json={
            'sku': 'OFFSET', 'name': '核销物料', 'unit': '件'}).json()['id']
        purchase = client.post(f'{base}/purchase-orders', headers=admin, json={
            'supplier_id': supplier, 'lines': [{'material_id': material, 'quantity': '6',
                                                'unit_price': '4'}]}).json()['id']
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, admin, 'PurchaseOrder', purchase)
        client.post(f'{base}/purchase-orders/{purchase}/confirm', headers=admin)
        receipt_doc = client.post(f'{base}/receipts', headers=admin, json={
            'supplier_id': supplier, 'purchase_order_id': purchase,
            'lines': [{'material_id': material, 'quantity': '6'}]}).json()
        receipt = receipt_doc['id']
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, admin, 'Receipt', receipt)
        assert client.post(f'{base}/receipts/{receipt}/post', headers=admin).status_code == 200

        def sale(party):
            order = client.post(f'{base}/sales-orders', headers=admin, json={
                'customer_id': party, 'lines': [{'material_id': material, 'quantity': '2',
                                                  'unit_price': '10'}]}).json()['id']
            approve_document(client, admin, 'SalesOrder', order)
            client.post(f'{base}/sales-orders/{order}/confirm', headers=admin)
            shipment = client.post(f'{base}/shipments', headers=admin, json={
                'sales_order_id': order, 'warehouse_id': 1,
                'lines': [{'material_id': material, 'quantity': '2'}]}).json()
            approve_document(client, admin, 'Shipment', shipment['id'])
            assert client.post(f'{base}/shipments/{shipment["id"]}/post', headers=admin).status_code == 200
            return order, shipment

        source, shipment = sale(customer)
        target, _ = sale(customer)
        foreign, _ = sale(other_customer)
        payment_path = f'{base}/finance/payment-records'
        paid=client.post(payment_path, headers=finance, json={
            'kind': 'receivable', 'order_id': source, 'action': 'settlement',
            'amount': '20', 'reference': 'BANK-1'})
        assert paid.status_code == 201
        execute_payment(client,finance,paid.json(),account_headers=admin)
        returned = client.post(f'{base}/sales-returns', headers=admin, json={
            'shipment_id': shipment['id'], 'warehouse_id': 1, 'reason': '退回一件',
            'lines': [{'shipment_line_id': shipment['lines'][0]['id'], 'quantity': '1'}]}).json()['id']
        approve_document(client, admin, 'SalesReturn', returned)
        assert client.post(f'{base}/sales-returns/{returned}/post', headers=admin).status_code == 200
        path = f'{base}/finance/order-settlements'
        draft = {'kind': 'receivable', 'from_order_id': source, 'to_order_id': target,
                 'amount': '6.00', 'reference': 'OFFSET-1', 'reason': '同客户退货贷方抵扣新订单'}
        assert client.get(path, headers=buyer).status_code == 403
        assert client.post(path, headers=buyer, json=draft).status_code == 403
        assert client.post(path, headers=finance, json={**draft, 'amount': '6.001'}).status_code == 422
        assert client.post(path, headers=finance, json={**draft, 'from_order_id': target,
            'to_order_id': target}).status_code == 422
        assert client.post(path, headers=finance, json={**draft, 'to_order_id': foreign}).status_code == 409
        assert client.post(path, headers=finance, json={**draft, 'amount': '11'}).status_code == 409
        created = client.post(path, headers=finance, json=draft)
        assert created.status_code == 201
        transfer = created.json()
        assert transfer['party_id'] == customer and transfer['amount'] == '6.00'
        assert transfer['created_by_name'] == 'accountant'
        assert client.post(path, headers=finance, json=draft).status_code == 409

        def balances():
            return {item['order_id']: item for item in client.get(
                f'{base}/finance/accounts', headers=finance).json() if item['kind'] == 'receivable'}

        assert balances()[source]['outstanding_amount'] == '-4.00'
        assert balances()[target]['outstanding_amount'] == '14.00'
        assert balances()[source]['settled_amount'] == '20.00'
        assert balances()[source]['credit_used_amount'] == '6.00'
        assert balances()[target]['debt_covered_amount'] == '6.00'
        assert client.post(payment_path, headers=finance, json={
            'kind': 'receivable', 'order_id': source, 'action': 'refund',
            'amount': '5', 'reference': 'REF-OVER'}).status_code == 409
        assert client.post(path, headers=finance, json={**draft, 'amount': '4.01',
            'reference': 'OFFSET-2'}).status_code == 409
        assert [item['id'] for item in client.get(f'{base}/finance/overview', headers=finance).json()['transfers']] == [transfer['id']]
        reverse = f'{path}/{transfer["id"]}/reverse'
        assert client.post(reverse, headers=buyer, json={'reason': '更正'}).status_code == 403
        assert client.post(reverse, headers=finance, json={'reason': '   '}).status_code == 422
        undone = client.post(reverse, headers=finance, json={'reason': '关联单据填错'})
        assert undone.status_code == 201
        assert undone.json()['reverses_id'] == transfer['id']
        assert undone.json()['amount'] == '-6.00'
        assert client.post(reverse, headers=finance, json={'reason': '重复'}).status_code == 409
        assert client.post(f'{path}/{undone.json()["id"]}/reverse', headers=finance,
            json={'reason': '重复'}).status_code == 409
        assert balances()[source]['outstanding_amount'] == '-10.00'
        assert balances()[target]['outstanding_amount'] == '20.00'
        assert client.post(path, headers=finance, json={**draft,
            'reference': 'OFFSET-NEW'}).status_code == 201

        # 供应商应付沿用同一规则，订单编号相同也不能跨应收、应付类别抵扣。
        paid=client.post(payment_path, headers=finance, json={
            'kind': 'payable', 'order_id': purchase, 'action': 'settlement',
            'amount': '24', 'reference': 'PAY-SUP'})
        assert paid.status_code == 201
        execute_payment(client,finance,paid.json(),account_headers=admin)
        purchase_return = client.post(f'{base}/purchase-returns', headers=admin, json={
            'receipt_id': receipt, 'reason': '退一件',
            'lines': [{'receipt_line_id': receipt_doc['lines'][0]['id'], 'quantity': '1'}]}).json()['id']
        prepare_purchase_return(client, admin, purchase_return)
        assert client.post(f'{base}/purchase-returns/{purchase_return}/post', headers=admin).status_code == 200
        purchase_target = client.post(f'{base}/purchase-orders', headers=admin, json={
            'supplier_id': supplier, 'lines': [{'material_id': material, 'quantity': '2',
                                                'unit_price': '4'}]}).json()['id']
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, admin, 'PurchaseOrder', purchase_target)
        client.post(f'{base}/purchase-orders/{purchase_target}/confirm', headers=admin)
        next_receipt = client.post(f'{base}/receipts', headers=admin, json={
            'supplier_id': supplier, 'purchase_order_id': purchase_target,
            'lines': [{'material_id': material, 'quantity': '2'}]}).json()['id']
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, admin, 'Receipt', next_receipt)
        assert client.post(f'{base}/receipts/{next_receipt}/post', headers=admin).status_code == 200
        payable_transfer = client.post(path, headers=finance, json={
            'kind': 'payable', 'from_order_id': purchase, 'to_order_id': purchase_target,
            'amount': '4.00', 'reference': 'SUP-OFFSET', 'reason': '供应商退货抵扣新订单'})
        assert payable_transfer.status_code == 201
        payable_accounts = {item['order_id']: item for item in client.get(
            f'{base}/finance/accounts', headers=finance).json() if item['kind'] == 'payable'}
        assert payable_accounts[purchase]['outstanding_amount'] == '0.00'
        assert payable_accounts[purchase_target]['outstanding_amount'] == '4.00'

        # 已结期间禁止补写核销及撤销，防止期末固定证据与当前余额脱节。
        today = datetime.now(timezone.utc).date().isoformat()
        with orm_session(write=True) as db:
            db.add(AccountingPeriod(code='LOCKED', name='锁期模拟', start_date=today,
                end_date=today, status='closed', version=1, created_by=1))
        locked = client.post(path, headers=finance, json={**draft, 'reference': 'LOCKED'})
        assert locked.status_code == 409 and '锁定' in locked.json()['detail']
        locked_reverse = client.post(f'{path}/{payable_transfer.json()["id"]}/reverse',
            headers=finance, json={'reason': '锁期撤销'})
        assert locked_reverse.status_code == 409 and '锁定' in locked_reverse.json()['detail']
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 90
