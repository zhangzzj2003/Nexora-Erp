"""销售出库逐批扣减、确认回滚与原分配冲销。"""

from approval_test_helpers import approve_document

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.models import PhysicalLotAllocation, StockMovement
from app.core.orm import orm_session
from app.main import app


def test_shipment_lots_are_selected_and_reversed_atomically(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'shipment-lots.db'))
    with TestClient(app, client=('127.0.0.1', 12003)) as client:
        base = '/api/v1'
        assert client.post(f'{base}/setup/admin', json={
            'username': 'admin', 'password': 'secure-pass-123'}).status_code == 201
        token = client.post(f'{base}/auth/login', json={
            'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
        auth = {'Authorization': f'Bearer {token}'}
        supplier = client.post(f'{base}/suppliers', headers=auth,
                               json={'name': '销售批次供应商'}).json()['id']
        material = client.post(f'{base}/materials', headers=auth, json={
            'sku': 'SHIP-LOT', 'name': '销售批次物料', 'unit': '件'}).json()['id']
        receipt = client.post(f'{base}/receipts', headers=auth, json={
            'supplier_id': supplier, 'lines': [{'material_id': material, 'quantity': '3.000'}]}).json()
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, auth, 'Receipt', receipt['id'])
        posted_receipt = client.post(f'{base}/receipts/{receipt["id"]}/post', headers=auth,
            json={'lines': [{'receipt_line_id': receipt['lines'][0]['id'], 'lots': [
                {'quantity': '1.000'}, {'quantity': '2.000'}]}]}).json()
        lot_a, lot_b = [item['id'] for item in posted_receipt['lines'][0]['physical_lots']]
        customer = client.post(f'{base}/customers', headers=auth,
                               json={'name': '批次客户'}).json()['id']
        order = client.post(f'{base}/sales-orders', headers=auth, json={
            'customer_id': customer, 'lines': [
                {'material_id': material, 'quantity': '2.000', 'unit_price': '5.00'}]}).json()
        assert client.post(f'{base}/sales-orders/{order["id"]}/confirm', headers=auth).status_code == 200
        shipment = client.post(f'{base}/shipments', headers=auth, json={
            'sales_order_id': order['id'], 'warehouse_id': 1,
            'lines': [{'material_id': material, 'quantity': '1.500'}]}).json()
        shipment_id, line_id = shipment['id'], shipment['lines'][0]['id']
        options_url = f'{base}/shipments/{shipment_id}/available-lots'
        options = client.get(options_url, headers=auth)
        assert options.status_code == 200
        assert [(item['lot_id'], item['quantity']) for item in options.json()['lines'][0]['lots']] == [
            (lot_a, '1.000'), (lot_b, '2.000')]
        post_url = f'{base}/shipments/{shipment_id}/post'
        allocation = {'lines': [{'shipment_line_id': line_id, 'lots': [
            {'lot_id': lot_a, 'quantity': '0.500'}, {'lot_id': lot_b, 'quantity': '1.000'}]}]}
        for invalid, status in [
            ({'lines': []}, 422),
            ({'lines': [{**allocation['lines'][0], 'shipment_line_id': line_id + 99}]}, 422),
            ({'lines': [{**allocation['lines'][0], 'lots': [
                {'lot_id': lot_a, 'quantity': '1.500'}]}]}, 409),
            ({'lines': [{**allocation['lines'][0], 'lots': [
                {'lot_id': lot_b, 'quantity': '1.000'}]}]}, 422),
        ]:
            assert client.post(post_url, headers=auth, json=invalid).status_code == status
            assert next(item for item in client.get(f'{base}/shipments', headers=auth).json()
                        if item['id'] == shipment_id)['status'] == 'draft'
        with orm_session() as db:
            assert list(db.scalars(select(StockMovement.id).where(
                StockMovement.source_type == 'shipment',
                StockMovement.source_id == shipment_id))) == []
        posted = client.post(post_url, headers=auth, json=allocation)
        assert posted.status_code == 200
        assert [(part['id'], part['quantity']) for part in posted.json()['lines'][0]['physical_lots']] == [
            (lot_a, '0.500'), (lot_b, '1.000')]
        assert client.get(options_url, headers=auth).status_code == 409
        assert client.post(post_url, headers=auth, json=allocation).status_code == 409
        overview = client.get(f'{base}/inventory/physical-lots/overview', headers=auth,
                              params={'material_id': material}).json()
        assert overview['fully_allocated']
        assert [item['quantity'] for item in overview['rows']] == ['0.500', '1.000']
        reversed_result = client.post(f'{base}/shipments/{shipment_id}/reverse', headers=auth,
                                      json={'reason': '误出库'})
        assert reversed_result.status_code == 201
        assert reversed_result.json()['lines'][0]['physical_lots'][0]['id'] == lot_a
        with orm_session() as db:
            originals = list(db.scalars(select(PhysicalLotAllocation).join(
                StockMovement, StockMovement.id == PhysicalLotAllocation.movement_id).where(
                    StockMovement.source_type == 'shipment',
                    StockMovement.source_id == shipment_id)))
            reversals = list(db.scalars(select(PhysicalLotAllocation).where(
                PhysicalLotAllocation.original_allocation_id.in_([part.id for part in originals]))))
            assert len(originals) == len(reversals) == 2
            assert sorted(Decimal(part.quantity) for part in reversals) == [
                Decimal('0.500'), Decimal('1.000')]
        assert client.get(f'{base}/inventory/physical-lots/overview', headers=auth,
                          params={'material_id': material}).json()['fully_allocated']
