"""采购退货的实物批次选择、失败回滚及原分配冲销。"""

from approval_test_helpers import approve_document

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.models import PhysicalLotAllocation, StockMovement
from app.core.orm import orm_session
from app.main import app


def test_purchase_return_lots_follow_warehouse_gate_and_reverse(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'return-lots.db'))
    with TestClient(app, client=('127.0.0.1', 12002)) as client:
        base = '/api/v1'
        assert client.post(f'{base}/setup/admin', json={
            'username': 'admin', 'password': 'secure-pass-123'}).status_code == 201
        token = client.post(f'{base}/auth/login', json={
            'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
        auth = {'Authorization': f'Bearer {token}'}
        supplier = client.post(f'{base}/suppliers', headers=auth,
                               json={'name': '退货批次供应商'}).json()['id']
        material = client.post(f'{base}/materials', headers=auth, json={
            'sku': 'RETURN-LOT', 'name': '批次退货物料', 'unit': '件'}).json()['id']
        receipt = client.post(f'{base}/receipts', headers=auth, json={
            'supplier_id': supplier, 'lines': [{'material_id': material, 'quantity': '3.000'}]}).json()
        receipt_line = receipt['lines'][0]['id']
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, auth, 'Receipt', receipt['id'])
        posted_receipt = client.post(f'{base}/receipts/{receipt["id"]}/post', headers=auth,
            json={'lines': [{'receipt_line_id': receipt_line, 'lots': [
                {'quantity': '1.000', 'supplier_lot': 'A'},
                {'quantity': '2.000', 'supplier_lot': 'B'}]}]}).json()
        lot_a, lot_b = [part['id'] for part in posted_receipt['lines'][0]['physical_lots']]
        returned = client.post(f'{base}/purchase-returns', headers=auth, json={
            'receipt_id': receipt['id'], 'reason': '来料退回', 'lines': [
                {'receipt_line_id': receipt_line, 'quantity': '1.500'}]}).json()
        return_id = returned['id']
        approve_document(client, auth, 'PurchaseReturn', return_id)
        submitted = client.post(f'{base}/purchase-returns/{return_id}/submit', headers=auth).json()
        outbound_id = submitted['outbound_id']
        outbound_line_id = next(item for item in client.get(f'{base}/warehouse-outbounds',
                                    headers=auth).json() if item['id'] == outbound_id)['lines'][0]['id']
        options_url = f'{base}/warehouse-outbounds/{outbound_id}/available-lots'
        options = client.get(options_url, headers=auth)
        assert options.status_code == 200
        assert [(item['lot_id'], item['quantity']) for item in options.json()['lines'][0]['lots']] == [
            (lot_a, '1.000'), (lot_b, '2.000')]
        # 出库另行批准后仍核对原批次数量与可用量。
        approve_document(client, auth, 'WarehouseOutbound', outbound_id)
        post_url = f'{base}/warehouse-outbounds/{outbound_id}/post'
        body = {'lines': [{'outbound_line_id': outbound_line_id, 'lots': [
            {'lot_id': lot_a, 'quantity': '0.500'}, {'lot_id': lot_b, 'quantity': '1.000'}]}]}
        for invalid, status in [
            ({'lines': []}, 422),
            ({'lines': [{**body['lines'][0], 'outbound_line_id': outbound_line_id + 99}]}, 422),
            ({'lines': [{**body['lines'][0], 'lots': [
                {'lot_id': lot_a, 'quantity': '1.500'}]}]}, 409),
            ({'lines': [{**body['lines'][0], 'lots': [
                {'lot_id': lot_b, 'quantity': '1.000'}]}]}, 422),
        ]:
            assert client.post(post_url, headers=auth, json=invalid).status_code == status
            assert next(item for item in client.get(f'{base}/purchase-returns', headers=auth).json()
                        if item['id'] == return_id)['status'] == 'draft'
        with orm_session() as db:
            assert list(db.scalars(select(StockMovement.id).where(
                StockMovement.source_type == 'purchase_return',
                StockMovement.source_id == return_id))) == []

        posted = client.post(post_url, headers=auth, json=body)
        assert posted.status_code == 200
        assert [(part['id'], part['quantity']) for part in posted.json()['lines'][0]['physical_lots']] == [
            (lot_a, '0.500'), (lot_b, '1.000')]
        assert client.get(options_url, headers=auth).status_code == 409
        assert client.post(post_url, headers=auth, json=body).status_code == 409
        overview = client.get(f'{base}/inventory/physical-lots/overview', headers=auth,
                              params={'material_id': material}).json()
        assert overview['fully_allocated']
        assert [item['quantity'] for item in overview['rows']] == ['0.500', '1.000']

        approve_document(client, auth, 'PurchaseReturn', return_id, intent='reverse', reason='误退货')
        reversed_result = client.post(f'{base}/purchase-returns/{return_id}/reverse',
                                      headers=auth, json={'reason': '误退货'})
        assert reversed_result.status_code == 201
        assert client.post(f'{base}/purchase-returns/{return_id}/reverse',
                           headers=auth, json={'reason': '重复'}).status_code == 409
        with orm_session() as db:
            originals = list(db.scalars(select(PhysicalLotAllocation).join(
                StockMovement, StockMovement.id == PhysicalLotAllocation.movement_id).where(
                    StockMovement.source_type == 'purchase_return',
                    StockMovement.source_id == return_id)))
            reversals = list(db.scalars(select(PhysicalLotAllocation).where(
                PhysicalLotAllocation.original_allocation_id.in_([part.id for part in originals]))))
            assert len(originals) == len(reversals) == 2
            assert sorted(Decimal(part.quantity) for part in reversals) == [
                Decimal('0.500'), Decimal('1.000')]
        assert client.get(f'{base}/inventory/physical-lots/overview', headers=auth,
                          params={'material_id': material}).json()['fully_allocated']
