"""生产领料批次选择、原单证据及失败时整单回滚。"""

from approval_test_helpers import approve_document

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.models import PhysicalLotAllocation, StockMovement
from app.core.orm import orm_session
from app.main import app


def test_material_issue_uses_selected_lots_atomically(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'issue-lots.db'))
    with TestClient(app, client=('127.0.0.1', 12003)) as client:
        base = '/api/v1'
        assert client.post(f'{base}/setup/admin', json={
            'username': 'admin', 'password': 'secure-pass-123'}).status_code == 201
        token = client.post(f'{base}/auth/login', json={
            'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
        auth = {'Authorization': f'Bearer {token}'}
        supplier = client.post(f'{base}/suppliers', headers=auth,
                               json={'name': '领料批次供应商'}).json()['id']
        product = client.post(f'{base}/materials', headers=auth,
                              json={'sku': 'ISSUE-FIN', 'name': '成品', 'unit': '件'}).json()['id']
        material = client.post(f'{base}/materials', headers=auth,
                               json={'sku': 'ISSUE-PART', 'name': '组件', 'unit': '件'}).json()['id']
        receipt = client.post(f'{base}/receipts', headers=auth, json={
            'supplier_id': supplier, 'lines': [{'material_id': material, 'quantity': '3.000'}]}).json()
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, auth, 'Receipt', receipt['id'])
        posted_receipt = client.post(f'{base}/receipts/{receipt["id"]}/post', headers=auth,
            json={'lines': [{'receipt_line_id': receipt['lines'][0]['id'], 'lots': [
                {'quantity': '1.000'}, {'quantity': '2.000'}]}]}).json()
        lot_a, lot_b = [item['id'] for item in posted_receipt['lines'][0]['physical_lots']]
        bom = client.post(f'{base}/boms', headers=auth, json={
            'product_material_id': product, 'base_quantity': '1',
            'lines': [{'component_material_id': material, 'quantity': '2.000'}]}).json()['id']
        assert client.post(f'{base}/boms/{bom}/activate', headers=auth).status_code == 200
        order = client.post(f'{base}/work-orders', headers=auth, json={
            'bom_id': bom, 'warehouse_id': 1, 'target_quantity': '1'}).json()
        approve_document(client, auth, 'WorkOrder', order['id'])
        assert client.post(f'{base}/work-orders/{order["id"]}/release', headers=auth).status_code == 200
        issue = client.post(f'{base}/material-issues', headers=auth, json={
            'work_order_id': order['id'], 'warehouse_id': 1,
            'lines': [{'work_order_line_id': order['lines'][0]['id'],
                       'quantity': '1.500'}]}).json()
        issue_id, line_id = issue['id'], issue['lines'][0]['id']
        options_url = f'{base}/material-issues/{issue_id}/available-lots'
        options = client.get(options_url, headers=auth)
        assert options.status_code == 200
        assert [(lot['lot_id'], lot['quantity']) for lot in options.json()['lines'][0]['lots']] == [
            (lot_a, '1.000'), (lot_b, '2.000')]
        # 独立审批完成后，再验证原库存约束或失败回滚。
        approve_document(client, auth, 'MaterialIssue', issue_id)
        post_url = f'{base}/material-issues/{issue_id}/post'
        allocation = {'lines': [{'material_issue_line_id': line_id, 'lots': [
            {'lot_id': lot_a, 'quantity': '0.500'},
            {'lot_id': lot_b, 'quantity': '1.000'}]}]}
        for invalid, status in [
            ({'lines': []}, 422),
            ({'lines': [{**allocation['lines'][0], 'material_issue_line_id': line_id + 99}]}, 422),
            ({'lines': [{**allocation['lines'][0], 'lots': [
                {'lot_id': lot_a, 'quantity': '1.500'}]}]}, 409),
            ({'lines': [{**allocation['lines'][0], 'lots': [
                {'lot_id': lot_b, 'quantity': '1.000'}]}]}, 422),
        ]:
            assert client.post(post_url, headers=auth, json=invalid).status_code == status
            assert client.get(f'{base}/material-issues', headers=auth).json()[0]['status'] == 'draft'
        with orm_session() as db:
            assert list(db.scalars(select(StockMovement.id).where(
                StockMovement.source_type == 'material_issue',
                StockMovement.source_id == issue_id))) == []
        posted = client.post(post_url, headers=auth, json=allocation)
        assert posted.status_code == 200
        assert [(part['id'], part['quantity']) for part in posted.json()['lines'][0]['physical_lots']] == [
            (lot_a, '0.500'), (lot_b, '1.000')]
        assert client.get(options_url, headers=auth).status_code == 409
        assert client.post(post_url, headers=auth, json=allocation).status_code == 409
        with orm_session() as db:
            allocations = list(db.scalars(select(PhysicalLotAllocation).join(
                StockMovement, StockMovement.id == PhysicalLotAllocation.movement_id).where(
                    StockMovement.source_type == 'material_issue',
                    StockMovement.source_id == issue_id)))
            assert sorted(Decimal(part.quantity) for part in allocations) == [
                Decimal('-1.000'), Decimal('-0.500')]
        assert client.get(f'{base}/inventory/physical-lots/overview', headers=auth,
                          params={'material_id': material}).json()['fully_allocated']
