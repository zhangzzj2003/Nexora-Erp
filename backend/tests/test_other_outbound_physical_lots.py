"""其他出库逐批扣减、输入拒绝和原分配冲销。"""

from approval_test_helpers import approve_document
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.models import PhysicalLotAllocation, StockMovement, WarehouseOutbound
from app.core.orm import add_model, orm_session
from app.main import app


def test_other_outbound_lots_are_selected_and_reversed_atomically(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'other-outbound-lots.db'))
    with TestClient(app, client=('127.0.0.1', 12001)) as client:
        base = '/api/v1'
        assert client.post(f'{base}/setup/admin', json={
            'username': 'admin', 'password': 'secure-pass-123'}).status_code == 201
        token = client.post(f'{base}/auth/login', json={
            'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
        auth = {'Authorization': f'Bearer {token}'}
        materials = [client.post(f'{base}/materials', headers=auth, json={
            'sku': f'OUT-LOT-{index}', 'name': f'样品{index}', 'unit': '件'}).json()['id']
            for index in range(2)]
        inbound = client.post(f'{base}/warehouse-inbounds', headers=auth, json={
            'warehouse_id': 1, 'reason': 'gift', 'note': '来源', 'lines': [
                {'material_id': materials[0], 'quantity': '3.125'},
                {'material_id': materials[1], 'quantity': '2.000'}]}).json()
        approve_document(client, auth, 'WarehouseInbound', inbound["id"])
        posted_inbound = client.post(f'{base}/warehouse-inbounds/{inbound["id"]}/post', headers=auth,
            json={'lines': [
                {'inbound_line_id': inbound['lines'][0]['id'], 'lots': [
                    {'quantity': '1.125'}, {'quantity': '2.000'}]},
                {'inbound_line_id': inbound['lines'][1]['id'], 'lots': [
                    {'quantity': '2.000'}]}]}).json()
        lot_a, lot_b = [part['id'] for part in posted_inbound['lines'][0]['physical_lots']]
        lot_c = posted_inbound['lines'][1]['physical_lots'][0]['id']
        draft = client.post(f'{base}/warehouse-outbounds', headers=auth, json={
            'warehouse_id': 1, 'reason': 'sample', 'note': '现场领用', 'lines': [
                {'material_id': materials[0], 'quantity': '2.125'},
                {'material_id': materials[1], 'quantity': '1.000'}]}).json()
        line_a, line_c = [row['id'] for row in draft['lines']]
        options_url = f'{base}/warehouse-outbounds/{draft["id"]}/available-lots'
        options = client.get(options_url, headers=auth)
        assert options.status_code == 200
        assert [(row['lot_id'], row['quantity']) for row in options.json()['lines'][0]['lots']] == [
            (lot_a, '1.125'), (lot_b, '2.000')]
        other_warehouse = client.post(f'{base}/warehouses', headers=auth, json={
            'code': 'OUT-LOT-2', 'name': '第二仓'}).json()['id']
        other_inbound = client.post(f'{base}/warehouse-inbounds', headers=auth, json={
            'warehouse_id': other_warehouse, 'reason': 'gift', 'note': '旧客户端入库',
            'lines': [{'material_id': materials[0], 'quantity': '1.000'}]}).json()['id']
        approve_document(client, auth, 'WarehouseInbound', other_inbound)
        assert client.post(f'{base}/warehouse-inbounds/{other_inbound}/post', headers=auth).status_code == 200
        other_draft = client.post(f'{base}/warehouse-outbounds', headers=auth, json={
            'warehouse_id': other_warehouse, 'reason': 'sample', 'note': '越仓批次',
            'lines': [{'material_id': materials[0], 'quantity': '1.000'}]}).json()
        assert client.get(f'{base}/warehouse-outbounds/{other_draft["id"]}/available-lots',
                          headers=auth).json()['lines'][0]['lots'] == []
        assert client.post(f'{base}/warehouse-outbounds/{other_draft["id"]}/post', headers=auth,
                           json={'lines': [{'outbound_line_id': other_draft['lines'][0]['id'],
                                            'lots': [{'lot_id': lot_a, 'quantity': '1.000'}]}]}).status_code == 409
        with orm_session(write=True) as db:
            purchase_return_gate = add_model(db, WarehouseOutbound(
                warehouse_id=1, source_kind='purchase_return', reason='purchase_return',
                note='共享确认闸口', reference='', created_by=1)).id
        assert client.get(f'{base}/warehouse-outbounds/{purchase_return_gate}/available-lots',
                          headers=auth).status_code == 409
        assert client.post(f'{base}/warehouse-outbounds/{purchase_return_gate}/post', headers=auth,
                           json={'lines': [{'outbound_line_id': line_a,
                                            'lots': [{'lot_id': lot_a, 'quantity': '1.000'}]}]}).status_code == 409
        post_url = f'{base}/warehouse-outbounds/{draft["id"]}/post'
        allocation = [
            {'outbound_line_id': line_a, 'lots': [
                {'lot_id': lot_a, 'quantity': '1.125'}, {'lot_id': lot_b, 'quantity': '1.000'}]},
            {'outbound_line_id': line_c, 'lots': [{'lot_id': lot_c, 'quantity': '1.000'}]},
        ]
        for invalid, status in [
            (allocation[:1], 422),
            ([allocation[0], allocation[0]], 422),
            ([{**allocation[0], 'lots': [{'lot_id': lot_a, 'quantity': '2.125'}]}, allocation[1]], 409),
            ([{**allocation[0], 'lots': [{'lot_id': lot_c, 'quantity': '2.125'}]}, allocation[1]], 422),
            ([{**allocation[0], 'lots': [{'lot_id': lot_b, 'quantity': '1.000'}]}, allocation[1]], 422),
        ]:
            assert client.post(post_url, headers=auth, json={'lines': invalid}).status_code == status
            assert next(item for item in client.get(f'{base}/warehouse-outbounds', headers=auth).json()
                        if item['id'] == draft['id'])['status'] == 'draft'
        with orm_session() as db:
            assert list(db.scalars(select(StockMovement.id).where(
                StockMovement.source_type == 'other_outbound',
                StockMovement.source_id == draft['id']))) == []
        posted = client.post(post_url, headers=auth, json={'lines': allocation})
        assert posted.status_code == 200
        assert [[(part['id'], part['quantity']) for part in line['physical_lots']]
                for line in posted.json()['lines']] == [
                    [(lot_a, '1.125'), (lot_b, '1.000')], [(lot_c, '1.000')]]
        assert client.get(options_url, headers=auth).status_code == 409
        assert client.post(post_url, headers=auth, json={'lines': allocation}).status_code == 409
        reverse = client.post(f'{base}/warehouse-outbounds/{draft["id"]}/reverse', headers=auth,
                              json={'reason': '未实际领用'})
        assert reverse.status_code == 201
        assert reverse.json()['lines'][0]['physical_lots'][0]['id'] == lot_a
        with orm_session() as db:
            originals = list(db.scalars(select(PhysicalLotAllocation).join(
                StockMovement, StockMovement.id == PhysicalLotAllocation.movement_id).where(
                    StockMovement.source_type == 'other_outbound',
                    StockMovement.source_id == draft['id'])))
            reversals = list(db.scalars(select(PhysicalLotAllocation).where(
                PhysicalLotAllocation.original_allocation_id.in_([part.id for part in originals]))))
            assert len(reversals) == len(originals) == 3
            assert sorted(Decimal(row.quantity) for row in reversals) == [
                Decimal('1.000'), Decimal('1.000'), Decimal('1.125')]
        assert client.get(f'{base}/inventory/physical-lots/overview?warehouse_id=1',
                          headers=auth).json()['fully_allocated']
