"""采购入库的真实批次分配、精确守恒与原批次冲销。"""

from approval_test_helpers import approve_document

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.models import PhysicalLot, PhysicalLotAllocation, StockMovement
from app.core.orm import orm_session
from app.inventory.physical_lots import LotPart, post_lot_movement
from app.main import app


def test_receipt_lots_post_and_reverse_are_atomic(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'receipt-lots.db'))
    with TestClient(app, client=('127.0.0.1', 12000)) as client:
        base = '/api/v1'
        assert client.post(f'{base}/setup/admin', json={
            'username': 'admin', 'password': 'secure-pass-123'}).status_code == 201
        token = client.post(f'{base}/auth/login', json={
            'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
        auth = {'Authorization': f'Bearer {token}'}
        supplier = client.post(f'{base}/suppliers', headers=auth, json={'name': '批次供应商'}).json()['id']
        material = client.post(f'{base}/materials', headers=auth, json={
            'sku': 'RECEIPT-LOT', 'name': '可追溯物料', 'unit': '件'}).json()['id']
        receipt = client.post(f'{base}/receipts', headers=auth, json={
            'supplier_id': supplier, 'lines': [{'material_id': material, 'quantity': '2.125'}]}).json()
        receipt_id, line_id = receipt['id'], receipt['lines'][0]['id']
        # 先完成真实独立审批，保留原业务失败和并发断言。
        approve_document(client, auth, 'Receipt', receipt_id)
        post_url = f'{base}/receipts/{receipt_id}/post'
        assert receipt['lines'][0]['physical_lots'] == []
        assert client.post(post_url, json={'lines': [{
            'receipt_line_id': line_id + 99,
            'lots': [{'quantity': '2.125'}]}]}, headers=auth).status_code == 422
        assert client.post(post_url, json={'lines': [{
            'receipt_line_id': line_id,
            'lots': [{'quantity': '2.124'}]}]}, headers=auth).status_code == 422
        assert client.post(post_url, json={'lines': [{
            'receipt_line_id': line_id,
            'lots': [{'quantity': '2.125', 'manufactured_on': '2026-10-02',
                      'expires_on': '2026-10-01'}]}]}, headers=auth).status_code == 422
        with orm_session() as db:
            assert list(db.scalars(select(PhysicalLot.id).where(PhysicalLot.material_id == material))) == []
            assert list(db.scalars(select(StockMovement.id).where(StockMovement.material_id == material))) == []

        posted = client.post(post_url, json={'lines': [{
            'receipt_line_id': line_id,
            'lots': [
                {'quantity': '1.125', 'supplier_lot': '  SUP-01  ',
                 'manufactured_on': '2026-10-01', 'expires_on': '2027-10-01'},
                {'quantity': '1.000', 'supplier_lot': '  '},
            ]}]}, headers=auth)
        assert posted.status_code == 200
        parts = posted.json()['lines'][0]['physical_lots']
        assert [(row['code'], row['quantity'], row['supplier_lot']) for row in parts] == [
            (f'R{receipt_id}-L{line_id}-P1', '1.125', 'SUP-01'),
            (f'R{receipt_id}-L{line_id}-P2', '1.000', None)]
        assert client.post(post_url, json={'lines': [{
            'receipt_line_id': line_id, 'lots': [{'quantity': '2.125'}]}]}, headers=auth).status_code == 409
        overview = client.get(f'{base}/inventory/physical-lots/overview', headers=auth,
                              params={'material_id': material}).json()
        assert overview['fully_allocated'] is True
        assert [row['quantity'] for row in overview['rows']] == ['1.125', '1.000']
        first_history = client.get(f'{base}/inventory/physical-lots/{parts[0]["id"]}/history',
                                   headers=auth).json()
        assert first_history['lot']['origin_movement_id'] == first_history['movements'][0]['movement_id']
        assert first_history['lot']['supplier_lot'] == 'SUP-01'

        # 已实际耗用的原批次不能被入库冲销悄悄改到另一批次。
        with orm_session(write=True) as db:
            spent = post_lot_movement(db, StockMovement(
                warehouse_id=1, material_id=material, quantity='-0.125',
                source_type='lot_test_outbound', source_id=1, source_line_id=1, created_by=1),
                [LotPart(parts[0]['id'], Decimal('-0.125'))])
            spent_id = spent.id
        # 先完成真实独立审批，保留原业务失败和并发断言。
        approve_document(client, auth, 'Receipt', receipt_id, intent='reverse', reason='误入库')
        reverse_url = f'{base}/receipts/{receipt_id}/reverse'
        assert client.post(reverse_url, json={'reason': '误入库'}, headers=auth).status_code == 409
        assert client.get(f'{base}/receipts', headers=auth).json()[0]['reversal_id'] is None
        with orm_session(write=True) as db:
            original = db.scalar(select(PhysicalLotAllocation).where(
                PhysicalLotAllocation.movement_id == spent_id))
            post_lot_movement(db, StockMovement(
                warehouse_id=1, material_id=material, quantity='0.125',
                source_type='lot_test_reversal', source_id=2, source_line_id=1, created_by=1),
                [LotPart(parts[0]['id'], Decimal('0.125'), original.id)])

        reversed_result = client.post(reverse_url, json={'reason': '误入库'}, headers=auth)
        assert reversed_result.status_code == 201
        assert reversed_result.json()['reversal_reason'] == '误入库'
        assert client.post(reverse_url, json={'reason': '重复'}, headers=auth).status_code == 409
        overview = client.get(f'{base}/inventory/physical-lots/overview', headers=auth,
                              params={'material_id': material}).json()
        assert overview['fully_allocated'] is True
        assert all(Decimal(row['quantity']) == 0 for row in overview['rows'])
        history = client.get(f'{base}/inventory/physical-lots/{parts[0]["id"]}/history',
                             headers=auth).json()
        assert history['movements'][-1]['quantity'] == '-1.125'
        assert history['movements'][-1]['original_allocation_id'] == history['movements'][0]['id']
