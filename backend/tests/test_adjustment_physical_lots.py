"""库存调整逐批归属、异人审批、冲销及失败回滚。"""

from approval_test_helpers import approve_document
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.models import PhysicalLot, PhysicalLotAllocation, StockAdjustmentReversal, StockMovement
from app.core.orm import orm_session
from app.main import app


def test_adjustment_lots_follow_approval_and_original_allocations(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'adjustment-lots.db'))
    with TestClient(app, client=('127.0.0.1', 12007)) as client:
        base = '/api/v1'
        assert client.post(f'{base}/setup/admin', json={
            'username': 'admin', 'password': 'secure-pass-123'}).status_code == 201

        def auth(username):
            token = client.post(f'{base}/auth/login', json={
                'username': username, 'password': 'secure-pass-123'}).json()['token']
            return {'Authorization': f'Bearer {token}'}

        admin = auth('admin')
        assert client.post(f'{base}/users', headers=admin, json={
            'username': 'checker', 'password': 'secure-pass-123',
            'roles': ['warehouse']}).status_code == 201
        checker = auth('checker')
        material = client.post(f'{base}/materials', headers=admin, json={
            'sku': 'ADJ-LOT', 'name': '调整批次物料', 'unit': '件'}).json()['id']
        inbound = client.post(f'{base}/warehouse-inbounds', headers=admin, json={
            'warehouse_id': 1, 'reason': 'gift', 'note': '来源',
            'lines': [{'material_id': material, 'quantity': '2.000'}]}).json()
        approve_document(client, admin, 'WarehouseInbound', inbound["id"])
        posted_inbound = client.post(f'{base}/warehouse-inbounds/{inbound["id"]}/post', headers=admin,
            json={'lines': [{'inbound_line_id': inbound['lines'][0]['id'], 'lots': [
                {'quantity': '2.000'}]}]}).json()
        lot_id = posted_inbound['lines'][0]['physical_lots'][0]['id']

        def approved(quantity):
            item = client.post(f'{base}/stock-adjustments', headers=admin, json={
                'warehouse_id': 1, 'reason': '实物差异',
                'lines': [{'material_id': material, 'quantity': quantity}]}).json()
            item_id = item['id']
            assert client.post(f'{base}/stock-adjustments/{item_id}/submit', headers=admin).status_code == 200
            assert client.post(f'{base}/stock-adjustments/{item_id}/approve', headers=checker).status_code == 200
            return item_id, item['lines'][0]['id']

        surplus_id, surplus_line = approved('1.000')
        options_url = f'{base}/stock-adjustments/{surplus_id}/available-lots'
        assert client.get(options_url).status_code == 401
        options = client.get(options_url, headers=checker)
        assert options.status_code == 200
        assert options.json()['lines'][0]['lots'][0]['lot_id'] == lot_id
        surplus_url = f'{base}/stock-adjustments/{surplus_id}/post'
        parts = [{'lot_id': lot_id, 'quantity': '0.250'},
                 {'quantity': '0.750', 'supplier_lot': '调整盘出',
                  'manufactured_on': '2026-09-01', 'expires_on': '2027-09-01'}]
        for invalid in [
            {'lines': []},
            {'lines': [{'adjustment_line_id': surplus_line + 9, 'lots': parts}]},
            {'lines': [{'adjustment_line_id': surplus_line, 'lots': [parts[0]]}]},
            {'lines': [{'adjustment_line_id': surplus_line, 'lots': [
                {'lot_id': lot_id, 'quantity': '1.000', 'supplier_lot': '伪造'}]}]},
        ]:
            assert client.post(surplus_url, headers=checker, json=invalid).status_code == 422
        with orm_session() as db:
            assert list(db.scalars(select(PhysicalLot.id).where(
                PhysicalLot.source_kind == 'adjustment'))) == []
        posted = client.post(surplus_url, headers=checker, json={
            'lines': [{'adjustment_line_id': surplus_line, 'lots': parts}]})
        assert posted.status_code == 200
        evidence = posted.json()['lines'][0]['physical_lots']
        assert [part['quantity'] for part in evidence] == ['0.250', '0.750']
        new_id = evidence[1]['id']
        with orm_session() as db:
            lot = db.get(PhysicalLot, new_id)
            assert lot.source_kind == 'adjustment'
            assert lot.origin_movement_id is not None

        shortage_id, shortage_line = approved('-1.500')
        shortage_url = f'{base}/stock-adjustments/{shortage_id}/post'
        assert client.post(shortage_url, headers=checker, json={'lines': [{
            'adjustment_line_id': shortage_line, 'lots': [{'quantity': '1.500'}]}]}).status_code == 422
        assert client.post(shortage_url, headers=checker, json={'lines': [{
            'adjustment_line_id': shortage_line,
            'lots': [{'lot_id': new_id, 'quantity': '1.500'}]}]}).status_code == 409
        assert client.post(shortage_url, headers=checker, json={'lines': [{
            'adjustment_line_id': shortage_line,
            'lots': [{'lot_id': lot_id, 'quantity': '1.000'},
                     {'lot_id': new_id, 'quantity': '0.500'}]}]}).status_code == 200
        assert client.get(f'{base}/inventory/physical-lots/overview', headers=admin,
                          params={'material_id': material}).json()['fully_allocated']
        for adjustment_id in (shortage_id, surplus_id):
            assert client.post(f'{base}/stock-adjustments/{adjustment_id}/reverse',
                headers=admin, json={'reason': '核对更正'}).status_code == 201
        with orm_session() as db:
            originals = list(db.scalars(select(PhysicalLotAllocation).join(
                StockMovement, StockMovement.id == PhysicalLotAllocation.movement_id).where(
                    StockMovement.source_type == 'adjustment')))
            reversals = list(db.scalars(select(PhysicalLotAllocation).where(
                PhysicalLotAllocation.original_allocation_id.in_([part.id for part in originals]))))
            assert len(originals) == len(reversals) == 4
            assert sum((Decimal(part.quantity) for part in reversals), Decimal(0)) == Decimal('0.500')
        assert client.get(f'{base}/inventory/physical-lots/overview', headers=admin,
                          params={'material_id': material}).json()['fully_allocated']


def test_adjustment_surplus_reverse_refuses_consumed_lot(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'adjustment-consumed.db'))
    with TestClient(app, client=('127.0.0.1', 12008)) as client:
        base = '/api/v1'
        client.post(f'{base}/setup/admin', json={
            'username': 'admin', 'password': 'secure-pass-123'})
        token = client.post(f'{base}/auth/login', json={
            'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
        admin = {'Authorization': f'Bearer {token}'}
        client.post(f'{base}/users', headers=admin, json={
            'username': 'checker', 'password': 'secure-pass-123', 'roles': ['warehouse']})
        checker_token = client.post(f'{base}/auth/login', json={
            'username': 'checker', 'password': 'secure-pass-123'}).json()['token']
        checker = {'Authorization': f'Bearer {checker_token}'}
        material = client.post(f'{base}/materials', headers=admin, json={
            'sku': 'ADJ-CONSUMED', 'name': '已耗用调整批次', 'unit': '件'}).json()['id']
        item = client.post(f'{base}/stock-adjustments', headers=admin, json={
            'warehouse_id': 1, 'reason': '实物发现',
            'lines': [{'material_id': material, 'quantity': '1.000'}]}).json()
        item_id = item['id']
        client.post(f'{base}/stock-adjustments/{item_id}/submit', headers=admin)
        client.post(f'{base}/stock-adjustments/{item_id}/approve', headers=checker)
        posted = client.post(f'{base}/stock-adjustments/{item_id}/post', headers=checker,
            json={'lines': [{'adjustment_line_id': item['lines'][0]['id'],
                             'lots': [{'quantity': '1.000'}]}]}).json()
        lot_id = posted['lines'][0]['physical_lots'][0]['id']
        outbound = client.post(f'{base}/warehouse-outbounds', headers=admin, json={
            'warehouse_id': 1, 'reason': 'sample', 'note': '已领用',
            'lines': [{'material_id': material, 'quantity': '0.500'}]}).json()
        approve_document(client, admin, 'WarehouseOutbound', outbound['id'])
        assert client.post(f'{base}/warehouse-outbounds/{outbound["id"]}/post', headers=admin,
            json={'lines': [{'outbound_line_id': outbound['lines'][0]['id'],
                             'lots': [{'lot_id': lot_id, 'quantity': '0.500'}]}]}).status_code == 200
        assert client.post(f'{base}/stock-adjustments/{item_id}/reverse', headers=admin,
                           json={'reason': '误调整'}).status_code == 409
        with orm_session() as db:
            assert list(db.scalars(select(StockAdjustmentReversal.id))) == []
