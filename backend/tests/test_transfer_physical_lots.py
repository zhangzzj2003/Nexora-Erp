"""调拨批次跨仓移动、异常回滚及沿原分配冲销。"""

from approval_test_helpers import approve_document
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.models import PhysicalLotAllocation, StockMovement
from app.core.orm import orm_session
from app.main import app


def test_transfer_moves_lots_between_warehouses_and_reverses_original_allocations(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'transfer-lots.db'))
    with TestClient(app, client=('127.0.0.1', 12004)) as client:
        base = '/api/v1'
        assert client.post(f'{base}/setup/admin', json={
            'username': 'admin', 'password': 'secure-pass-123'}).status_code == 201
        token = client.post(f'{base}/auth/login', json={
            'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
        auth = {'Authorization': f'Bearer {token}'}
        supplier = client.post(f'{base}/suppliers', headers=auth,
                               json={'name': '调拨批次供应商'}).json()['id']
        material = client.post(f'{base}/materials', headers=auth, json={
            'sku': 'TRANSFER-LOT', 'name': '调拨批次物料', 'unit': '件'}).json()['id']
        target = client.post(f'{base}/warehouses', headers=auth, json={
            'code': 'TRANSFER-LOT-2', 'name': '调拨目标仓'}).json()['id']
        receipt = client.post(f'{base}/receipts', headers=auth, json={
            'supplier_id': supplier, 'lines': [{'material_id': material, 'quantity': '3.000'}]}).json()
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, auth, 'Receipt', receipt['id'])
        posted_receipt = client.post(f'{base}/receipts/{receipt["id"]}/post', headers=auth,
            json={'lines': [{'receipt_line_id': receipt['lines'][0]['id'], 'lots': [
                {'quantity': '1.000'}, {'quantity': '2.000'}]}]}).json()
        lot_a, lot_b = [item['id'] for item in posted_receipt['lines'][0]['physical_lots']]
        transfer = client.post(f'{base}/transfers', headers=auth, json={
            'from_warehouse_id': 1, 'to_warehouse_id': target,
            'lines': [{'material_id': material, 'quantity': '1.500'}]}).json()
        transfer_id, line_id = transfer['id'], transfer['lines'][0]['id']
        options_url = f'{base}/transfers/{transfer_id}/available-lots'
        assert client.get(options_url).status_code == 401
        options = client.get(options_url, headers=auth)
        assert options.status_code == 200
        assert [(lot['lot_id'], lot['quantity']) for lot in options.json()['lines'][0]['lots']] == [
            (lot_a, '1.000'), (lot_b, '2.000')]
        approve_document(client, auth, 'Transfer', transfer_id)
        post_url = f'{base}/transfers/{transfer_id}/post'
        allocation = {'lines': [{'transfer_line_id': line_id, 'lots': [
            {'lot_id': lot_a, 'quantity': '0.500'}, {'lot_id': lot_b, 'quantity': '1.000'}]}]}
        for invalid, status in [
            ({'lines': []}, 422),
            ({'lines': [{**allocation['lines'][0], 'transfer_line_id': line_id + 99}]}, 422),
            ({'lines': [{**allocation['lines'][0], 'lots': [
                {'lot_id': lot_a, 'quantity': '1.500'}]}]}, 409),
            ({'lines': [{**allocation['lines'][0], 'lots': [
                {'lot_id': lot_b, 'quantity': '1.000'}]}]}, 422),
        ]:
            assert client.post(post_url, headers=auth, json=invalid).status_code == status
            assert next(row for row in client.get(f'{base}/transfers', headers=auth).json()
                        if row['id'] == transfer_id)['status'] == 'draft'
        with orm_session() as db:
            assert list(db.scalars(select(StockMovement.id).where(
                StockMovement.source_type == 'transfer_out',
                StockMovement.source_id == transfer_id))) == []
        posted = client.post(post_url, headers=auth, json=allocation)
        assert posted.status_code == 200
        assert [(part['id'], part['quantity']) for part in posted.json()['lines'][0]['physical_lots']] == [
            (lot_a, '0.500'), (lot_b, '1.000')]
        assert client.get(options_url, headers=auth).status_code == 409
        assert client.post(post_url, headers=auth, json=allocation).status_code == 409
        overview = client.get(f'{base}/inventory/physical-lots/overview', headers=auth,
                              params={'material_id': material}).json()
        assert overview['fully_allocated']
        quantities = {(row['warehouse_id'], row['lot_id']): row['quantity'] for row in overview['rows']}
        assert quantities == {(1, lot_a): '0.500', (1, lot_b): '1.000',
                              (target, lot_a): '0.500', (target, lot_b): '1.000'}
        approve_document(client, auth, 'Transfer', transfer_id, intent='reverse', reason='目标仓选择错误')
        reversed_result = client.post(f'{base}/transfers/{transfer_id}/reverse', headers=auth,
                                      json={'reason': '目标仓选择错误'})
        assert reversed_result.status_code == 200
        assert reversed_result.json()['lines'][0]['physical_lots'][0]['id'] == lot_a
        with orm_session() as db:
            originals = list(db.scalars(select(PhysicalLotAllocation).join(
                StockMovement, StockMovement.id == PhysicalLotAllocation.movement_id).where(
                    StockMovement.source_id == transfer_id,
                    StockMovement.source_type.in_(['transfer_out', 'transfer_in']))))
            reversals = list(db.scalars(select(PhysicalLotAllocation).where(
                PhysicalLotAllocation.original_allocation_id.in_([part.id for part in originals]))))
            assert len(originals) == len(reversals) == 4
            assert sorted(Decimal(part.quantity) for part in reversals) == [
                Decimal('-1.000'), Decimal('-0.500'), Decimal('0.500'), Decimal('1.000')]
        assert client.get(f'{base}/inventory/physical-lots/overview', headers=auth,
                          params={'material_id': material}).json()['fully_allocated']


def test_transfer_reverse_rejects_consumed_target_lot_without_partial_stock(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'transfer-consumed.db'))
    with TestClient(app, client=('127.0.0.1', 12005)) as client:
        base = '/api/v1'
        client.post(f'{base}/setup/admin', json={'username': 'admin', 'password': 'secure-pass-123'})
        token = client.post(f'{base}/auth/login', json={
            'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
        auth = {'Authorization': f'Bearer {token}'}
        material = client.post(f'{base}/materials', headers=auth, json={
            'sku': 'TRANSFER-CONSUMED', 'name': '已耗用批次', 'unit': '件'}).json()['id']
        target = client.post(f'{base}/warehouses', headers=auth, json={
            'code': 'TRANSFER-CONSUMED-2', 'name': '第二仓'}).json()['id']
        inbound = client.post(f'{base}/warehouse-inbounds', headers=auth, json={
            'warehouse_id': 1, 'reason': 'gift', 'note': '来源',
            'lines': [{'material_id': material, 'quantity': '2.000'}]}).json()
        approve_document(client, auth, 'WarehouseInbound', inbound["id"])
        posted_inbound = client.post(f'{base}/warehouse-inbounds/{inbound["id"]}/post', headers=auth,
            json={'lines': [{'inbound_line_id': inbound['lines'][0]['id'],
                             'lots': [{'quantity': '2.000'}]}]}).json()
        lot_id = posted_inbound['lines'][0]['physical_lots'][0]['id']
        transfer = client.post(f'{base}/transfers', headers=auth, json={
            'from_warehouse_id': 1, 'to_warehouse_id': target,
            'lines': [{'material_id': material, 'quantity': '1.000'}]}).json()
        approve_document(client, auth, 'Transfer', transfer["id"])
        posted = client.post(f'{base}/transfers/{transfer["id"]}/post', headers=auth,
            json={'lines': [{'transfer_line_id': transfer['lines'][0]['id'],
                             'lots': [{'lot_id': lot_id, 'quantity': '1.000'}]}]})
        assert posted.status_code == 200
        outbound = client.post(f'{base}/warehouse-outbounds', headers=auth, json={
            'warehouse_id': target, 'reason': 'sample', 'note': '已领用',
            'lines': [{'material_id': material, 'quantity': '0.500'}]}).json()
        approve_document(client, auth, 'WarehouseOutbound', outbound['id'])
        assert client.post(f'{base}/warehouse-outbounds/{outbound["id"]}/post', headers=auth,
            json={'lines': [{'outbound_line_id': outbound['lines'][0]['id'],
                             'lots': [{'lot_id': lot_id, 'quantity': '0.500'}]}]}).status_code == 200
        approve_document(client, auth, 'Transfer', transfer['id'], intent='reverse', reason='误调拨')
        reverse_url = f'{base}/transfers/{transfer["id"]}/reverse'
        assert client.post(reverse_url, headers=auth, json={'reason': '误调拨'}).status_code == 409
        current = next(row for row in client.get(f'{base}/transfers', headers=auth).json()
                       if row['id'] == transfer['id'])
        assert current['reversal_id'] is None
        assert current['status'] == 'posted'
        with orm_session() as db:
            assert list(db.scalars(select(StockMovement.id).where(
                StockMovement.source_type == 'transfer_reversal_out'))) == []
