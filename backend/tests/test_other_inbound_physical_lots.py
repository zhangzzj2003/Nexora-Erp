"""其他入库多批次登记、原批次冲销及事务回滚。"""

from approval_test_helpers import approve_document
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.models import PhysicalLot, PhysicalLotAllocation, StockMovement
from app.core.orm import orm_session
from app.inventory.physical_lots import LotPart, post_lot_movement
from app.main import app


def test_other_inbound_lots_are_fixed_and_reversed_atomically(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'other-inbound-lots.db'))
    with TestClient(app, client=('127.0.0.1', 12000)) as client:
        base = '/api/v1'
        assert client.post(f'{base}/setup/admin', json={
            'username': 'admin', 'password': 'secure-pass-123'}).status_code == 201
        token = client.post(f'{base}/auth/login', json={
            'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
        auth = {'Authorization': f'Bearer {token}'}
        first = client.post(f'{base}/materials', headers=auth, json={
            'sku': 'OTHER-LOT-A', 'name': '赠品甲', 'unit': '件'}).json()['id']
        second = client.post(f'{base}/materials', headers=auth, json={
            'sku': 'OTHER-LOT-B', 'name': '赠品乙', 'unit': '件'}).json()['id']
        created = client.post(f'{base}/warehouse-inbounds', headers=auth, json={
            'warehouse_id': 1, 'reason': 'gift', 'note': '实际赠品来源',
            'lines': [{'material_id': first, 'quantity': '2.125'},
                      {'material_id': second, 'quantity': '1.000'}]})
        assert created.status_code == 201
        inbound_id = created.json()['id']
        first_line, second_line = [line['id'] for line in created.json()['lines']]
        approve_document(client, auth, 'WarehouseInbound', inbound_id)
        post_url = f'{base}/warehouse-inbounds/{inbound_id}/post'
        assert created.json()['lines'][0]['physical_lots'] == []
        first_parts = [{'quantity': '1.125', 'supplier_lot': '  GIFT-01  ',
                        'manufactured_on': '2026-10-01', 'expires_on': '2027-10-01'},
                       {'quantity': '1.000'}]
        complete = [{'inbound_line_id': first_line, 'lots': first_parts},
                    {'inbound_line_id': second_line, 'lots': [{'quantity': '1.000'}]}]
        for invalid in [
            complete[:1],
            [{**complete[0], 'lots': [{'quantity': '2.124'}]}, complete[1]],
            [{**complete[0], 'lots': [{'quantity': '2.125',
                                      'manufactured_on': '2026-10-02',
                                      'expires_on': '2026-10-01'}]}, complete[1]],
        ]:
            assert client.post(post_url, headers=auth, json={'lines': invalid}).status_code == 422
        with orm_session() as db:
            assert list(db.scalars(select(PhysicalLot.id).where(PhysicalLot.material_id == first))) == []
            assert list(db.scalars(select(StockMovement.id).where(StockMovement.material_id == first))) == []

        posted = client.post(post_url, headers=auth, json={'lines': complete})
        assert posted.status_code == 200
        lines = posted.json()['lines']
        parts = lines[0]['physical_lots']
        assert [(row['code'], row['quantity'], row['supplier_lot']) for row in parts] == [
            (f'O{inbound_id}-L{first_line}-P1', '1.125', 'GIFT-01'),
            (f'O{inbound_id}-L{first_line}-P2', '1.000', None)]
        assert lines[1]['physical_lots'][0]['code'] == f'O{inbound_id}-L{second_line}-P1'
        assert client.post(post_url, headers=auth, json={'lines': complete}).status_code == 409
        overview = client.get(f'{base}/inventory/physical-lots/overview', headers=auth).json()
        assert overview['fully_allocated'] is True
        assert len(overview['rows']) == 3
        assert client.get(f'{base}/finance/receivables-payables', headers=auth).json()['entries'] == []

        with orm_session(write=True) as db:
            spent = post_lot_movement(db, StockMovement(
                warehouse_id=1, material_id=first, quantity='-0.125',
                source_type='lot_test_outbound', source_id=1, source_line_id=1,
                created_by=1), [LotPart(parts[0]['id'], Decimal('-0.125'))])
            spent_id = spent.id
        approve_document(client, auth, 'WarehouseInbound', inbound_id, intent='reverse', reason='误录')
        reverse_url = f'{base}/warehouse-inbounds/{inbound_id}/reverse'
        assert client.post(reverse_url, headers=auth, json={'reason': '误录'}).status_code == 409
        assert client.get(f'{base}/warehouse-inbounds', headers=auth).json()[0]['reversal_id'] is None
        with orm_session(write=True) as db:
            original = db.scalar(select(PhysicalLotAllocation).where(
                PhysicalLotAllocation.movement_id == spent_id))
            post_lot_movement(db, StockMovement(
                warehouse_id=1, material_id=first, quantity='0.125',
                source_type='lot_test_reversal', source_id=2, source_line_id=1,
                created_by=1), [LotPart(parts[0]['id'], Decimal('0.125'), original.id)])

        reversed_entry = client.post(reverse_url, headers=auth, json={'reason': '误录'})
        assert reversed_entry.status_code == 201
        assert reversed_entry.json()['reversal_reason'] == '误录'
        assert client.post(reverse_url, headers=auth, json={'reason': '重复'}).status_code == 409
        overview = client.get(f'{base}/inventory/physical-lots/overview', headers=auth).json()
        assert overview['fully_allocated'] is True
        assert all(Decimal(row['quantity']) == 0 for row in overview['rows'])
        history = client.get(f'{base}/inventory/physical-lots/{parts[0]["id"]}/history',
                             headers=auth).json()
        assert history['movements'][-1]['quantity'] == '-1.125'
        assert history['movements'][-1]['original_allocation_id'] == history['movements'][0]['id']
