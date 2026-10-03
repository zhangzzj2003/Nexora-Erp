"""已确认退料冲销保留原单，并对库存、批次和后续领用执行原子校验。"""

import sqlite3
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import migrate
from app.core.models import MaterialReturnReversal, PhysicalLotAllocation, StockMovement
from app.core.orm import orm_session
from app.finance.business_sources import business_sources
from app.main import app


def scenario(client, *, legacy_return=False):
    base = '/api/v1'
    assert client.post(f'{base}/setup/admin', json={
        'username': 'admin', 'password': 'secure-pass-123'}).status_code == 201
    token = client.post(f'{base}/auth/login', json={
        'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
    auth = {'Authorization': f'Bearer {token}'}
    client.post(f'{base}/users', headers=auth, json={
        'username': 'planner', 'password': 'secure-pass-123', 'roles': ['planner']})
    token = client.post(f'{base}/auth/login', json={
        'username': 'planner', 'password': 'secure-pass-123'}).json()['token']
    planner = {'Authorization': f'Bearer {token}'}
    supplier = client.post(f'{base}/suppliers', headers=auth, json={'name': '退料冲销供货方'}).json()['id']
    product = client.post(f'{base}/materials', headers=auth, json={
        'sku': 'RETURN-REV-FIN', 'name': '成品', 'unit': '件'}).json()['id']
    material = client.post(f'{base}/materials', headers=auth, json={
        'sku': 'RETURN-REV-PART', 'name': '组件', 'unit': '件'}).json()['id']
    receipt = client.post(f'{base}/receipts', headers=auth, json={
        'supplier_id': supplier, 'lines': [{'material_id': material, 'quantity': '4'}]}).json()
    posted = client.post(f'{base}/receipts/{receipt["id"]}/post', headers=auth, json={
        'lines': [{'receipt_line_id': receipt['lines'][0]['id'],
                   'lots': [{'quantity': '4'}]}]}).json()
    lot_id = posted['lines'][0]['physical_lots'][0]['id']
    receipt_movement = client.get(f'{base}/movements', headers=auth).json()[0]['id']
    assert client.post(f'{base}/inventory/valuation/inputs', headers=auth, json={
        'movement_id': receipt_movement, 'unit_cost': '5.0000',
        'reference': 'RETURN-REV-COST', 'reason': '采购发票'}).status_code == 201
    bom = client.post(f'{base}/boms', headers=auth, json={
        'product_material_id': product, 'base_quantity': '1',
        'lines': [{'component_material_id': material, 'quantity': '2'}]}).json()['id']
    assert client.post(f'{base}/boms/{bom}/activate', headers=auth).status_code == 200
    order = client.post(f'{base}/work-orders', headers=auth, json={
        'bom_id': bom, 'warehouse_id': 1, 'target_quantity': '1'}).json()
    assert client.post(f'{base}/work-orders/{order["id"]}/release', headers=auth).status_code == 200
    issue = client.post(f'{base}/material-issues', headers=auth, json={
        'work_order_id': order['id'], 'warehouse_id': 1,
        'lines': [{'work_order_line_id': order['lines'][0]['id'], 'quantity': '2'}]}).json()
    assert client.post(f'{base}/material-issues/{issue["id"]}/post', headers=auth, json={
        'lines': [{'material_issue_line_id': issue['lines'][0]['id'],
                   'lots': [{'lot_id': lot_id, 'quantity': '2'}]}]}).status_code == 200
    returned = client.post(f'{base}/material-returns', headers=auth, json={
        'material_issue_id': issue['id'], 'reason': '未使用退回',
        'lines': [{'material_issue_line_id': issue['lines'][0]['id'], 'quantity': '1'}]}).json()
    post_body = None if legacy_return else {'lines': [{
        'return_line_id': returned['lines'][0]['id'],
        'lots': [{'lot_id': lot_id, 'quantity': '1'}]}]}
    assert client.post(f'{base}/material-returns/{returned["id"]}/post', headers=auth,
                       json=post_body).status_code == 200
    return auth, planner, material, lot_id, order, issue, returned


def test_return_reversal_restores_net_issue_and_pairs_cost(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'return-reversal.db'))
    with TestClient(app, client=('127.0.0.1', 12018)) as client:
        auth, planner, material, lot_id, order, issue, returned = scenario(client)
        base = '/api/v1'
        url = f'{base}/material-returns/{returned["id"]}/reverse'
        inbound = client.post(f'{base}/warehouse-inbounds', headers=auth, json={
            'warehouse_id': 1, 'reason': 'gift', 'note': '测试平均价变化',
            'lines': [{'material_id': material, 'quantity': '1'}]}).json()
        assert client.post(f'{base}/warehouse-inbounds/{inbound["id"]}/post', headers=auth,
            json={'lines': [{'inbound_line_id': inbound['lines'][0]['id'],
                             'lots': [{'quantity': '1'}]}]}).status_code == 200
        inbound_movement = client.get(f'{base}/movements', headers=auth).json()[0]['id']
        assert client.post(f'{base}/inventory/valuation/inputs', headers=auth, json={
            'movement_id': inbound_movement, 'unit_cost': '20.0000',
            'reference': 'DIFFERENT-COST', 'reason': '另一批次价格'}).status_code == 201
        before = client.get(f'{base}/movements', headers=auth).json()
        assert client.post(url, headers=planner, json={'reason': '退料录错'}).status_code == 403
        assert client.post(url, headers=auth, json={'reason': '  '}).status_code == 422
        response = client.post(url, headers=auth, json={'reason': '  退料录错  '})
        assert response.status_code == 201, response.text
        record = response.json()
        assert record['status'] == 'reversed' and record['reversal_reason'] == '退料录错'
        assert client.post(url, headers=auth, json={'reason': '再次冲销'}).status_code == 409
        assert Decimal(client.get(f'{base}/work-orders', headers=auth).json()[0]
                       ['lines'][0]['issued_quantity']) == 2
        assert Decimal(client.get(f'{base}/material-issues', headers=auth).json()[0]
                       ['lines'][0]['returnable_quantity']) == 2
        movements = client.get(f'{base}/movements', headers=auth).json()
        assert len(movements) == len(before) + 1
        reversal_movement = movements[0]
        assert reversal_movement['source_type'] == 'material_return_reversal'
        assert reversal_movement['material_return_reversal_id'] == record['reversal_id']
        assert Decimal(reversal_movement['quantity']) == -1
        assert Decimal(next(row for row in client.get(f'{base}/stock?warehouse_id=1',
                           headers=auth).json() if row['id'] == material)['quantity']) == 3
        costs = {row['id']: row for row in client.get(f'{base}/inventory/valuation',
                                                       headers=auth).json()['movements']}
        assert costs[reversal_movement['id']]['unit_cost'] == '5.0000'
        assert costs[reversal_movement['id']]['cost_source'] == 'linked_movement'
        assert costs[inbound_movement]['unit_cost'] == '20.0000'
        with orm_session() as db:
            sources = business_sources(db)
            assert sources[f'material_return:{returned["id"]}']['roles'] == {
                'inventory': '5.00', 'work_in_progress': '-5.00'}
            assert sources[f'material_return_reversal:{record["reversal_id"]}']['roles'] == {
                'inventory': '-5.00', 'work_in_progress': '5.00'}
            assert db.scalar(select(MaterialReturnReversal.id).where(
                MaterialReturnReversal.material_return_id == returned['id'])) is not None
            parts = list(db.scalars(select(PhysicalLotAllocation).where(
                PhysicalLotAllocation.movement_id == reversal_movement['id'])))
            assert len(parts) == 1 and parts[0].lot_id == lot_id
            assert Decimal(parts[0].quantity) == -1 and parts[0].original_allocation_id is not None
        for movement in (reversal_movement, next(row for row in movements
                if row['source_type'] == 'material_return')):
            assert client.post(f'{base}/inventory/physical-lots/movements/{movement["id"]}/evidence',
                headers=auth, json={'lot_id': lot_id, 'quantity': '1',
                                    'evidence': '冲销后禁止改写原批次证据'}).status_code == 409
        assert client.post(f'{base}/material-issues/{issue["id"]}/reverse',
            headers=auth, json={'reason': '原领料也录错'}).status_code == 201


def test_return_reversal_rejects_reissue_and_consumed_lot(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'return-reversal-gates.db'))
    with TestClient(app, client=('127.0.0.1', 12019)) as client:
        auth, _, material, lot_id, order, issue, returned = scenario(client)
        base = '/api/v1'
        url = f'{base}/material-returns/{returned["id"]}/reverse'
        reissue = client.post(f'{base}/material-issues', headers=auth, json={
            'work_order_id': order['id'], 'warehouse_id': 1,
            'lines': [{'work_order_line_id': order['lines'][0]['id'], 'quantity': '1'}]}).json()
        assert client.post(f'{base}/material-issues/{reissue["id"]}/post', headers=auth, json={
            'lines': [{'material_issue_line_id': reissue['lines'][0]['id'],
                       'lots': [{'lot_id': lot_id, 'quantity': '1'}]}]}).status_code == 200
        count = len(client.get(f'{base}/movements', headers=auth).json())
        assert client.post(url, headers=auth, json={'reason': '退料有误'}).status_code == 409
        assert len(client.get(f'{base}/movements', headers=auth).json()) == count
        assert client.post(f'{base}/material-issues/{reissue["id"]}/reverse',
            headers=auth, json={'reason': '取消补领'}).status_code == 201
        completion = client.post(f'{base}/production-completions', headers=auth, json={
            'work_order_id': order['id'], 'reported_quantity': '1'}).json()
        assert client.post(url, headers=auth, json={'reason': '报工未处理'}).status_code == 409
        assert client.post(f'{base}/production-completions/{completion["id"]}/cancel',
                           headers=auth).status_code == 200
        outbound = client.post(f'{base}/warehouse-outbounds', headers=auth, json={
            'warehouse_id': 1, 'reason': 'sample', 'note': '耗用退料批次',
            'lines': [{'material_id': material, 'quantity': '3'}]}).json()
        assert client.post(f'{base}/warehouse-outbounds/{outbound["id"]}/post', headers=auth,
            json={'lines': [{'outbound_line_id': outbound['lines'][0]['id'],
                             'lots': [{'lot_id': lot_id, 'quantity': '3'}]}]}).status_code == 200
        assert client.post(url, headers=auth, json={'reason': '批次已耗用'}).status_code == 409
        inbound = client.post(f'{base}/warehouse-inbounds', headers=auth, json={
            'warehouse_id': 1, 'reason': 'gift', 'note': '另一批次补入',
            'lines': [{'material_id': material, 'quantity': '1'}]}).json()
        assert client.post(f'{base}/warehouse-inbounds/{inbound["id"]}/post', headers=auth,
            json={'lines': [{'inbound_line_id': inbound['lines'][0]['id'],
                             'lots': [{'quantity': '1'}]}]}).status_code == 200
        # 总库存足够时仍必须核对原退料所归的批次。
        assert Decimal(next(row for row in client.get(f'{base}/stock?warehouse_id=1',
                            headers=auth).json() if row['id'] == material)['quantity']) == 1
        assert client.post(url, headers=auth, json={'reason': '原退料批次不足'}).status_code == 409
        with orm_session() as db:
            assert db.scalar(select(MaterialReturnReversal.id).where(
                MaterialReturnReversal.material_return_id == returned['id'])) is None
        assert client.get(f'{base}/material-returns', headers=auth).json()[0]['status'] == 'posted'


def test_legacy_return_reversal_preserves_evidence_lot(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'return-reversal-legacy.db'))
    with TestClient(app, client=('127.0.0.1', 12021)) as client:
        auth, _, _, lot_id, _, _, returned = scenario(client, legacy_return=True)
        base = '/api/v1'
        original = next(row for row in client.get(f'{base}/movements', headers=auth).json()
                        if row['source_type'] == 'material_return')
        assert client.post(f'{base}/inventory/physical-lots/movements/{original["id"]}/evidence',
            headers=auth, json={'lot_id': lot_id, 'quantity': '1',
                                'evidence': '现场确认历史退料归属批次'}).status_code == 201
        response = client.post(f'{base}/material-returns/{returned["id"]}/reverse',
            headers=auth, json={'reason': '旧退料登记错误'})
        assert response.status_code == 201, response.text
        reverse_movement = client.get(f'{base}/movements', headers=auth).json()[0]
        with orm_session() as db:
            parts = list(db.scalars(select(PhysicalLotAllocation).where(
                PhysicalLotAllocation.movement_id == reverse_movement['id'])))
            assert len(parts) == 1 and parts[0].lot_id == lot_id
            assert Decimal(parts[0].quantity) == -1 and parts[0].original_allocation_id is None


def test_v66_upgrade_adds_return_reversal_without_user_changes(monkeypatch, tmp_path):
    path = tmp_path / 'v66-upgrade.db'
    monkeypatch.setenv('NEXORA_DB_PATH', str(path))
    with TestClient(app, client=('127.0.0.1', 12020)) as client:
        client.post('/api/v1/setup/admin', json={
            'username': 'admin', 'password': 'secure-pass-123'})
    with sqlite3.connect(path) as db:
        users = db.execute('SELECT id, username, password_hash FROM users').fetchall()
        db.execute('DROP TABLE inventory_warning_events')
        db.execute('DROP TABLE inventory_warning_observations')
        db.execute('DROP TABLE material_return_reversals')
        db.execute("DELETE FROM role_permissions WHERE permission_code='material_return.reverse'")
        db.execute("DELETE FROM permissions WHERE code='material_return.reverse'")
        db.execute('PRAGMA user_version = 66')
    migrate()
    migrate()
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 70
        assert db.execute('SELECT id, username, password_hash FROM users').fetchall() == users
        assert db.execute("SELECT role_code FROM role_permissions WHERE permission_code='material_return.reverse'").fetchall() == [('admin',)]
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='material_return_reversals'").fetchone() is not None
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
