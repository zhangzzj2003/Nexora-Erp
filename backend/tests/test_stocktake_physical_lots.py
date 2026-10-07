"""盘点差异逐批归属、冲销原分配及失败回滚。"""

from approval_test_helpers import approve_document
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.models import PhysicalLot, PhysicalLotAllocation, StockMovement
from app.core.orm import orm_session
from app.main import app


def _client(monkeypatch, tmp_path, filename):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / filename))
    return TestClient(app, client=('127.0.0.1', 12006))


def _auth(client):
    base = '/api/v1'
    assert client.post(f'{base}/setup/admin', json={
        'username': 'admin', 'password': 'secure-pass-123'}).status_code == 201
    token = client.post(f'{base}/auth/login', json={
        'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
    return {'Authorization': f'Bearer {token}'}


def test_stocktake_surplus_and_shortage_fix_actual_lots_and_reverse(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path, 'stocktake-lots.db') as client:
        base = '/api/v1'
        auth = _auth(client)
        material = client.post(f'{base}/materials', headers=auth, json={
            'sku': 'STOCKTAKE-LOT', 'name': '盘点批次物料', 'unit': '件'}).json()['id']
        inbound = client.post(f'{base}/warehouse-inbounds', headers=auth, json={
            'warehouse_id': 1, 'reason': 'gift', 'note': '来源',
            'lines': [{'material_id': material, 'quantity': '3.000'}]}).json()
        approve_document(client, auth, 'WarehouseInbound', inbound["id"])
        posted_inbound = client.post(f'{base}/warehouse-inbounds/{inbound["id"]}/post', headers=auth,
            json={'lines': [{'inbound_line_id': inbound['lines'][0]['id'], 'lots': [
                {'quantity': '1.000'}, {'quantity': '2.000'}]}]}).json()
        lot_a, lot_b = [part['id'] for part in posted_inbound['lines'][0]['physical_lots']]
        surplus = client.post(f'{base}/stocktakes', headers=auth, json={
            'warehouse_id': 1, 'lines': [{'material_id': material,
                                         'counted_quantity': '4.000'}]}).json()
        surplus_id, surplus_line = surplus['id'], surplus['lines'][0]['id']
        options_url = f'{base}/stocktakes/{surplus_id}/available-lots'
        assert client.get(options_url).status_code == 401
        options = client.get(options_url, headers=auth)
        assert options.status_code == 200
        assert options.json()['lines'][0]['difference'] == '1.000'
        assert [part['lot_id'] for part in options.json()['lines'][0]['lots']] == [lot_a, lot_b]
        approve_document(client, auth, 'Stocktake', surplus_id)
        post_url = f'{base}/stocktakes/{surplus_id}/post'
        surplus_parts = [{'lot_id': lot_a, 'quantity': '0.250'},
                         {'quantity': '0.750', 'supplier_lot': '现场找到',
                          'manufactured_on': '2026-09-01', 'expires_on': '2027-09-01'}]
        for invalid, status in [
            ({'lines': []}, 422),
            ({'lines': [{'stocktake_line_id': surplus_line + 99, 'lots': surplus_parts}]}, 422),
            ({'lines': [{'stocktake_line_id': surplus_line, 'lots': [surplus_parts[0]]}]}, 422),
            ({'lines': [{'stocktake_line_id': surplus_line, 'lots': [
                {'lot_id': lot_a, 'quantity': '1.000', 'supplier_lot': '伪造'}]}]}, 422),
        ]:
            assert client.post(post_url, headers=auth, json=invalid).status_code == status
        with orm_session() as db:
            assert list(db.scalars(select(PhysicalLot.id).where(
                PhysicalLot.source_kind == 'stocktake'))) == []
        posted = client.post(post_url, headers=auth, json={
            'lines': [{'stocktake_line_id': surplus_line, 'lots': surplus_parts}]})
        assert posted.status_code == 200
        evidence = posted.json()['lines'][0]['physical_lots']
        assert [part['quantity'] for part in evidence] == ['0.250', '0.750']
        new_lot = evidence[1]['id']
        with orm_session() as db:
            lot = db.get(PhysicalLot, new_lot)
            assert lot.source_kind == 'stocktake'
            assert lot.supplier_lot == '现场找到'
            assert lot.origin_movement_id is not None
        shortage = client.post(f'{base}/stocktakes', headers=auth, json={
            'warehouse_id': 1, 'lines': [{'material_id': material,
                                         'counted_quantity': '2.500'}]}).json()
        shortage_id, shortage_line = shortage['id'], shortage['lines'][0]['id']
        approve_document(client, auth, 'Stocktake', shortage_id)
        shortage_url = f'{base}/stocktakes/{shortage_id}/post'
        assert client.post(shortage_url, headers=auth, json={'lines': [{
            'stocktake_line_id': shortage_line, 'lots': [
                {'quantity': '1.500'}]}]}).status_code == 422
        assert client.post(shortage_url, headers=auth, json={'lines': [{
            'stocktake_line_id': shortage_line, 'lots': [
                {'lot_id': lot_a, 'quantity': '1.500'}]}]}).status_code == 409
        assert client.post(shortage_url, headers=auth, json={'lines': [{
            'stocktake_line_id': shortage_line, 'lots': [
                {'lot_id': lot_a, 'quantity': '0.500'},
                {'lot_id': lot_b, 'quantity': '1.000'}]}]}).status_code == 200
        overview = client.get(f'{base}/inventory/physical-lots/overview', headers=auth,
                              params={'material_id': material}).json()
        assert overview['fully_allocated']
        assert {(row['lot_id'], row['quantity']) for row in overview['rows']} == {
            (lot_a, '0.750'), (lot_b, '1.000'), (new_lot, '0.750')}
        for stocktake_id in (shortage_id, surplus_id):
            approve_document(client, auth, 'Stocktake', stocktake_id, intent='reverse', reason='复核更正')
            assert client.post(f'{base}/stocktakes/{stocktake_id}/reverse', headers=auth,
                               json={'reason': '复核更正'}).status_code == 200
        with orm_session() as db:
            originals = list(db.scalars(select(PhysicalLotAllocation).join(
                StockMovement, StockMovement.id == PhysicalLotAllocation.movement_id).where(
                    StockMovement.source_type == 'stocktake')))
            reversals = list(db.scalars(select(PhysicalLotAllocation).where(
                PhysicalLotAllocation.original_allocation_id.in_([part.id for part in originals]))))
            assert len(originals) == len(reversals) == 4
            assert sorted(Decimal(part.quantity) for part in reversals) == [
                Decimal('-0.750'), Decimal('-0.250'), Decimal('0.500'), Decimal('1.000')]
        assert client.get(f'{base}/inventory/physical-lots/overview', headers=auth,
                          params={'material_id': material}).json()['fully_allocated']


def test_stocktake_surplus_reverse_requires_original_lot_quantity(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path, 'stocktake-lot-consumed.db') as client:
        base = '/api/v1'
        auth = _auth(client)
        material = client.post(f'{base}/materials', headers=auth, json={
            'sku': 'STOCKTAKE-CONSUMED', 'name': '盘盈后已耗用', 'unit': '件'}).json()['id']
        stocktake = client.post(f'{base}/stocktakes', headers=auth, json={
            'warehouse_id': 1, 'lines': [{'material_id': material,
                                         'counted_quantity': '1.000'}]}).json()
        approve_document(client, auth, 'Stocktake', stocktake["id"])
        posted = client.post(f'{base}/stocktakes/{stocktake["id"]}/post', headers=auth,
            json={'lines': [{'stocktake_line_id': stocktake['lines'][0]['id'],
                             'lots': [{'quantity': '1.000'}]}]})
        assert posted.status_code == 200
        lot_id = posted.json()['lines'][0]['physical_lots'][0]['id']
        outbound = client.post(f'{base}/warehouse-outbounds', headers=auth, json={
            'warehouse_id': 1, 'reason': 'sample', 'note': '已领用',
            'lines': [{'material_id': material, 'quantity': '0.500'}]}).json()
        approve_document(client, auth, 'WarehouseOutbound', outbound['id'])
        assert client.post(f'{base}/warehouse-outbounds/{outbound["id"]}/post', headers=auth,
            json={'lines': [{'outbound_line_id': outbound['lines'][0]['id'],
                             'lots': [{'lot_id': lot_id, 'quantity': '0.500'}]}]}).status_code == 200
        approve_document(client, auth, 'Stocktake', stocktake['id'], intent='reverse', reason='误盘盈')
        assert client.post(f'{base}/stocktakes/{stocktake["id"]}/reverse', headers=auth,
                           json={'reason': '误盘盈'}).status_code == 409
        current = next(row for row in client.get(f'{base}/stocktakes', headers=auth).json()
                       if row['id'] == stocktake['id'])
        assert current['reversal_id'] is None
        with orm_session() as db:
            assert list(db.scalars(select(StockMovement.id).where(
                StockMovement.source_type == 'stocktake_reversal'))) == []
