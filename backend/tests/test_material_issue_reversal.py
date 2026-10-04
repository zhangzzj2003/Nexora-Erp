"""已确认生产领料冲销保留原流水，并阻止有下游依赖时更正。"""

import sqlite3
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.models import MaterialIssueReversal, PhysicalLotAllocation, StockMovement
from app.core.database import migrate
from app.core.orm import orm_session
from app.finance.business_sources import business_sources
from app.main import app


def test_material_issue_reversal_restores_stock_lots_cost_and_work_order(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'issue-reversal.db'))
    with TestClient(app, client=('127.0.0.1', 12015)) as client:
        base = '/api/v1'
        assert client.post(f'{base}/setup/admin', json={
            'username': 'admin', 'password': 'secure-pass-123'}).status_code == 201
        token = client.post(f'{base}/auth/login', json={
            'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
        admin = {'Authorization': f'Bearer {token}'}
        assert client.post(f'{base}/users', headers=admin, json={
            'username': 'planner', 'password': 'secure-pass-123', 'roles': ['planner']}).status_code == 201
        planner_token = client.post(f'{base}/auth/login', json={
            'username': 'planner', 'password': 'secure-pass-123'}).json()['token']
        planner = {'Authorization': f'Bearer {planner_token}'}

        supplier = client.post(f'{base}/suppliers', headers=admin,
            json={'name': '领料冲销供应商'}).json()['id']
        product = client.post(f'{base}/materials', headers=admin,
            json={'sku': 'REV-FIN', 'name': '冲销成品', 'unit': '件'}).json()['id']
        material = client.post(f'{base}/materials', headers=admin,
            json={'sku': 'REV-PART', 'name': '冲销组件', 'unit': '件'}).json()['id']
        receipt = client.post(f'{base}/receipts', headers=admin, json={
            'supplier_id': supplier, 'lines': [{'material_id': material, 'quantity': '2'}]}).json()
        posted_receipt = client.post(f'{base}/receipts/{receipt["id"]}/post', headers=admin,
            json={'lines': [{'receipt_line_id': receipt['lines'][0]['id'],
                             'lots': [{'quantity': '2'}]}]}).json()
        lot_id = posted_receipt['lines'][0]['physical_lots'][0]['id']
        receipt_movement = client.get(f'{base}/movements', headers=admin).json()[0]['id']
        assert client.post(f'{base}/inventory/valuation/inputs', headers=admin, json={
            'movement_id': receipt_movement, 'unit_cost': '5.0000',
            'reference': 'REV-COST', 'reason': '发票核价'}).status_code == 201
        bom = client.post(f'{base}/boms', headers=admin, json={
            'product_material_id': product, 'base_quantity': '1',
            'lines': [{'component_material_id': material, 'quantity': '2'}]}).json()['id']
        assert client.post(f'{base}/boms/{bom}/activate', headers=admin).status_code == 200
        order = client.post(f'{base}/work-orders', headers=admin, json={
            'bom_id': bom, 'warehouse_id': 1, 'target_quantity': '1'}).json()
        order_id, order_line_id = order['id'], order['lines'][0]['id']
        assert client.post(f'{base}/work-orders/{order_id}/release', headers=admin).status_code == 200
        issue = client.post(f'{base}/material-issues', headers=admin, json={
            'work_order_id': order_id, 'warehouse_id': 1,
            'lines': [{'work_order_line_id': order_line_id, 'quantity': '1'}]}).json()
        issue_id, line_id = issue['id'], issue['lines'][0]['id']
        assert client.post(f'{base}/material-issues/{issue_id}/post', headers=admin,
            json={'lines': [{'material_issue_line_id': line_id,
                             'lots': [{'lot_id': lot_id, 'quantity': '1'}]}]}).status_code == 200
        reverse_url = f'{base}/material-issues/{issue_id}/reverse'
        assert client.post(reverse_url, headers=planner, json={'reason': '录错领料'}).status_code == 403
        assert client.post(reverse_url, headers=admin, json={'reason': '  '}).status_code == 422
        assert client.post(reverse_url, headers=admin, json={'reason': '录错领料'}).status_code == 201
        assert client.post(reverse_url, headers=admin, json={'reason': '重复冲销'}).status_code == 409
        record = client.get(f'{base}/material-issues', headers=admin).json()[0]
        assert record['status'] == 'reversed' and record['reversal_reason'] == '录错领料'
        assert record['lines'][0]['returnable_quantity'] == '0'
        stock = client.get(f'{base}/stock?warehouse_id=1', headers=admin).json()
        assert next(item for item in stock if item['id'] == material)['quantity'] == '2'
        work_order = client.get(f'{base}/work-orders', headers=admin).json()[0]
        assert work_order['status'] == 'released'
        assert Decimal(work_order['lines'][0]['issued_quantity']) == 0
        assert client.post(f'{base}/material-returns', headers=admin, json={
            'material_issue_id': issue_id, 'reason': '不可重复退料',
            'lines': [{'material_issue_line_id': line_id, 'quantity': '1'}]}).status_code == 409
        movements = client.get(f'{base}/movements', headers=admin).json()
        reversal_movement, original_movement = movements[:2]
        assert reversal_movement['source_type'] == 'material_issue_reversal'
        assert reversal_movement['source_line_id'] == line_id
        assert reversal_movement['quantity'] == '1'
        assert original_movement['source_type'] == 'material_issue'
        assert original_movement['quantity'] == '-1'
        valuation = client.get(f'{base}/inventory/valuation', headers=admin).json()
        movement_costs = {item['id']: item for item in valuation['movements']}
        assert movement_costs[reversal_movement['id']]['unit_cost'] == '5.0000'
        assert movement_costs[reversal_movement['id']]['cost_source'] == 'linked_movement'
        with orm_session() as db:
            sources = business_sources(db)
            assert sources[f'material_issue:{issue_id}']['roles'] == {
                'inventory': '-5.00', 'work_in_progress': '5.00'}
            assert sources[f'material_issue_reversal:{record["reversal_id"]}']['roles'] == {
                'inventory': '5.00', 'work_in_progress': '-5.00'}
            assert db.scalar(select(MaterialIssueReversal.id).where(
                MaterialIssueReversal.material_issue_id == issue_id)) is not None
            parts = list(db.scalars(select(PhysicalLotAllocation).where(
                PhysicalLotAllocation.movement_id == reversal_movement['id'])))
            assert len(parts) == 1 and parts[0].lot_id == lot_id
            assert Decimal(parts[0].quantity) == 1 and parts[0].original_allocation_id is not None

        # 旧客户端未选批次的领料先完成现场补证，再冲销时也应归还同一批次。
        legacy_issue = client.post(f'{base}/material-issues', headers=admin, json={
            'work_order_id': order_id, 'warehouse_id': 1,
            'lines': [{'work_order_line_id': order_line_id, 'quantity': '1'}]}).json()
        assert client.post(f'{base}/material-issues/{legacy_issue["id"]}/post',
            headers=admin).status_code == 200
        legacy_movement = client.get(f'{base}/movements', headers=admin).json()[0]['id']
        assert client.post(f'{base}/inventory/physical-lots/movements/{legacy_movement}/evidence',
            headers=admin, json={'quantity': '1', 'lot_id': lot_id,
                                 'evidence': '现场核对旧领料批次后补证'}).status_code == 201
        assert client.post(f'{base}/material-issues/{legacy_issue["id"]}/reverse',
            headers=admin, json={'reason': '旧领料确认有误'}).status_code == 201
        legacy_reversal_movement = client.get(f'{base}/movements', headers=admin).json()[0]['id']
        with orm_session() as db:
            parts = list(db.scalars(select(PhysicalLotAllocation).where(
                PhysicalLotAllocation.movement_id == legacy_reversal_movement)))
            assert len(parts) == 1 and parts[0].lot_id == lot_id
            assert Decimal(parts[0].quantity) == 1 and parts[0].original_allocation_id is None


def test_material_issue_reversal_blocks_return_and_completion(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'issue-dependencies.db'))
    with TestClient(app, client=('127.0.0.1', 12016)) as client:
        base = '/api/v1'
        client.post(f'{base}/setup/admin', json={'username': 'admin', 'password': 'secure-pass-123'})
        token = client.post(f'{base}/auth/login', json={
            'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
        auth = {'Authorization': f'Bearer {token}'}
        supplier = client.post(f'{base}/suppliers', headers=auth,
            json={'name': '依赖供应商'}).json()['id']
        product = client.post(f'{base}/materials', headers=auth,
            json={'sku': 'DEP-FIN', 'name': '依赖成品', 'unit': '件'}).json()['id']
        material = client.post(f'{base}/materials', headers=auth,
            json={'sku': 'DEP-PART', 'name': '依赖组件', 'unit': '件'}).json()['id']
        receipt = client.post(f'{base}/receipts', headers=auth, json={
            'supplier_id': supplier, 'lines': [{'material_id': material, 'quantity': '2'}]}).json()['id']
        client.post(f'{base}/receipts/{receipt}/post', headers=auth)
        bom = client.post(f'{base}/boms', headers=auth, json={
            'product_material_id': product, 'base_quantity': '1',
            'lines': [{'component_material_id': material, 'quantity': '1'}]}).json()['id']
        client.post(f'{base}/boms/{bom}/activate', headers=auth)
        order = client.post(f'{base}/work-orders', headers=auth, json={
            'bom_id': bom, 'warehouse_id': 1, 'target_quantity': '1'}).json()
        order_id, order_line_id = order['id'], order['lines'][0]['id']
        client.post(f'{base}/work-orders/{order_id}/release', headers=auth)
        issue = client.post(f'{base}/material-issues', headers=auth, json={
            'work_order_id': order_id, 'warehouse_id': 1,
            'lines': [{'work_order_line_id': order_line_id, 'quantity': '1'}]}).json()
        issue_id, line_id = issue['id'], issue['lines'][0]['id']
        client.post(f'{base}/material-issues/{issue_id}/post', headers=auth)
        reverse_url = f'{base}/material-issues/{issue_id}/reverse'
        return_id = client.post(f'{base}/material-returns', headers=auth, json={
            'material_issue_id': issue_id, 'reason': '待退料',
            'lines': [{'material_issue_line_id': line_id, 'quantity': '0.5'}]}).json()['id']
        before = len(client.get(f'{base}/movements', headers=auth).json())
        assert client.post(reverse_url, headers=auth, json={'reason': '错误确认'}).status_code == 409
        assert len(client.get(f'{base}/movements', headers=auth).json()) == before
        client.post(f'{base}/material-returns/{return_id}/cancel', headers=auth)
        completion_id = client.post(f'{base}/production-completions', headers=auth, json={
            'work_order_id': order_id, 'reported_quantity': '1'}).json()['id']
        assert client.post(reverse_url, headers=auth, json={'reason': '错误确认'}).status_code == 409
        client.post(f'{base}/production-completions/{completion_id}/cancel', headers=auth)
        valuation = client.post(f'{base}/production-costs/material-valuations', headers=auth, json={
            'material_issue_line_id': line_id, 'unit_cost': '3.0000',
            'reference': '手工核价依据', 'note': ''})
        assert valuation.status_code == 201
        assert client.post(reverse_url, headers=auth, json={'reason': '错误确认'}).status_code == 409
        assert client.post(f'{base}/production-costs/{valuation.json()["id"]}/reverse',
            headers=auth, json={'reason': '原领料错误确认'}).status_code == 200
        assert client.post(reverse_url, headers=auth, json={'reason': '错误确认'}).status_code == 201
        movements = client.get(f'{base}/movements', headers=auth).json()
        for movement in movements[:2]:
            assert client.post(f'{base}/inventory/physical-lots/movements/{movement["id"]}/evidence',
                headers=auth, json={'quantity': '1', 'evidence': '现场核对冲销后不可再次补证',
                                    'lot_id': 1}).status_code == 409


def test_v65_upgrade_adds_reversal_permission_without_touching_users(monkeypatch, tmp_path):
    path = tmp_path / 'v65-upgrade.db'
    monkeypatch.setenv('NEXORA_DB_PATH', str(path))
    with TestClient(app, client=('127.0.0.1', 12017)) as client:
        assert client.post('/api/v1/setup/admin', json={
            'username': 'admin', 'password': 'secure-pass-123'}).status_code == 201
    # 从已初始化的数据库构造第 65 版结构，单独检验新增迁移的幂等性。
    with sqlite3.connect(path) as db:
        before = db.execute('SELECT id, username, password_hash FROM users').fetchall()
        db.execute('DROP TABLE inventory_warning_events')
        db.execute('DROP TABLE inventory_warning_observations')
        db.execute('DROP TABLE material_return_reversals')
        db.execute("DELETE FROM role_permissions WHERE permission_code='material_return.reverse'")
        db.execute("DELETE FROM permissions WHERE code='material_return.reverse'")
        db.execute('DROP TABLE material_issue_reversals')
        db.execute("DELETE FROM role_permissions WHERE permission_code='material_issue.reverse'")
        db.execute("DELETE FROM permissions WHERE code='material_issue.reverse'")
        db.execute('PRAGMA user_version = 65')
    migrate()
    migrate()
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 72
        assert db.execute('SELECT id, username, password_hash FROM users').fetchall() == before
        assert db.execute("SELECT role_code FROM role_permissions WHERE permission_code='material_issue.reverse'").fetchall() == [('admin',)]
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='material_issue_reversals'").fetchone() is not None
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
