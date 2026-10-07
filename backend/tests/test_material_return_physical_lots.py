"""生产退料核对原领料批次、累计可退量与新发现批次来源。"""

from approval_test_helpers import approve_document

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.models import PhysicalLot, PhysicalLotAllocation, StockMovement
from app.core.orm import orm_session
from app.main import app


def test_material_return_lots_follow_original_issue(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'return-lots.db'))
    with TestClient(app, client=('127.0.0.1', 12003)) as client:
        base = '/api/v1'
        assert client.post(f'{base}/setup/admin', json={
            'username': 'admin', 'password': 'secure-pass-123'}).status_code == 201
        token = client.post(f'{base}/auth/login', json={
            'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
        auth = {'Authorization': f'Bearer {token}'}
        supplier = client.post(f'{base}/suppliers', headers=auth,
                               json={'name': '退料批次供应商'}).json()['id']
        product = client.post(f'{base}/materials', headers=auth,
                              json={'sku': 'RETURN-FIN', 'name': '成品', 'unit': '件'}).json()['id']
        material = client.post(f'{base}/materials', headers=auth,
                               json={'sku': 'RETURN-PART', 'name': '组件', 'unit': '件'}).json()['id']
        receipt = client.post(f'{base}/receipts', headers=auth, json={
            'supplier_id': supplier, 'lines': [{'material_id': material, 'quantity': '2.000'}]}).json()
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, auth, 'Receipt', receipt['id'])
        received = client.post(f'{base}/receipts/{receipt["id"]}/post', headers=auth,
            json={'lines': [{'receipt_line_id': receipt['lines'][0]['id'], 'lots': [
                {'quantity': '1.000'}, {'quantity': '1.000'}]}]}).json()
        lot_a, lot_b = [part['id'] for part in received['lines'][0]['physical_lots']]
        bom = client.post(f'{base}/boms', headers=auth, json={
            'product_material_id': product, 'base_quantity': '1',
            'lines': [{'component_material_id': material, 'quantity': '2.000'}]}).json()['id']
        client.post(f'{base}/boms/{bom}/activate', headers=auth)
        order = client.post(f'{base}/work-orders', headers=auth, json={
            'bom_id': bom, 'warehouse_id': 1, 'target_quantity': '1'}).json()
        client.post(f'{base}/work-orders/{order["id"]}/release', headers=auth)
        issue = client.post(f'{base}/material-issues', headers=auth, json={
            'work_order_id': order['id'], 'warehouse_id': 1,
            'lines': [{'work_order_line_id': order['lines'][0]['id'],
                       'quantity': '2.000'}]}).json()
        issue_line = issue['lines'][0]['id']
        assert client.post(f'{base}/material-issues/{issue["id"]}/post', headers=auth,
            json={'lines': [{'material_issue_line_id': issue_line, 'lots': [
                {'lot_id': lot_a, 'quantity': '1.000'},
                {'lot_id': lot_b, 'quantity': '1.000'}]}]}).status_code == 200
        def make_return(quantity):
            return client.post(f'{base}/material-returns', headers=auth, json={
                'material_issue_id': issue['id'], 'reason': '未使用退回',
                'lines': [{'material_issue_line_id': issue_line, 'quantity': quantity}]}).json()

        first = make_return('0.750')
        first_id, first_line = first['id'], first['lines'][0]['id']
        options_url = f'{base}/material-returns/{first_id}/available-lots'
        assert [(lot['lot_id'], lot['quantity']) for lot in client.get(
            options_url, headers=auth).json()['lines'][0]['lots']] == [
                (lot_a, '1.000'), (lot_b, '1.000')]
        post_url = f'{base}/material-returns/{first_id}/post'
        for invalid, status in [
            ({'lines': []}, 422),
            ({'lines': [{'return_line_id': first_line + 99,
                        'lots': [{'lot_id': lot_a, 'quantity': '0.750'}]}]}, 422),
            ({'lines': [{'return_line_id': first_line,
                        'lots': [{'lot_id': lot_b, 'quantity': '0.500'}]}]}, 422),
            ({'lines': [{'return_line_id': first_line,
                        'lots': [{'lot_id': 99999, 'quantity': '0.750'}]}]}, 422),
            ({'lines': [{'return_line_id': first_line,
                        'lots': [{'lot_id': lot_a, 'quantity': '0.750',
                                  'supplier_lot': '伪造'}]}]}, 422),
        ]:
            assert client.post(post_url, headers=auth, json=invalid).status_code == status
            assert client.get(f'{base}/material-returns', headers=auth).json()[0]['status'] == 'draft'
        posted = client.post(post_url, headers=auth, json={'lines': [
            {'return_line_id': first_line, 'lots': [{'lot_id': lot_a, 'quantity': '0.750'}]}]})
        assert posted.status_code == 200
        assert posted.json()['lines'][0]['physical_lots'][0]['id'] == lot_a
        assert client.get(options_url, headers=auth).status_code == 409
        second = make_return('0.500')
        second_id, second_line = second['id'], second['lines'][0]['id']
        options = client.get(f'{base}/material-returns/{second_id}/available-lots',
                             headers=auth).json()['lines'][0]['lots']
        assert [(lot['lot_id'], lot['quantity']) for lot in options] == [
            (lot_a, '0.250'), (lot_b, '1.000')]
        assert client.post(f'{base}/material-returns/{second_id}/post', headers=auth,
            json={'lines': [{'return_line_id': second_line, 'lots': [
                {'lot_id': lot_a, 'quantity': '0.500'}]}]}).status_code == 409
        new_return = client.post(f'{base}/material-returns/{second_id}/post', headers=auth,
            json={'lines': [{'return_line_id': second_line, 'lots': [
                {'lot_id': None, 'quantity': '0.500', 'supplier_lot': '隔离退料'}]}]})
        assert new_return.status_code == 200
        new_lot = new_return.json()['lines'][0]['physical_lots'][0]
        assert new_lot['source_kind'] == 'material_return'
        assert new_lot['code'].startswith(f'MR{second_id}-L{second_line}-P')
        with orm_session() as db:
            lot = db.get(PhysicalLot, new_lot['id'])
            assert lot.origin_movement_id is not None
            allocations = list(db.scalars(select(PhysicalLotAllocation).join(
                StockMovement, StockMovement.id == PhysicalLotAllocation.movement_id).where(
                    StockMovement.source_type == 'material_return')))
            assert sorted(Decimal(part.quantity) for part in allocations) == [
                Decimal('0.500'), Decimal('0.750')]
        assert client.get(f'{base}/inventory/physical-lots/overview', headers=auth,
                          params={'material_id': material}).json()['fully_allocated']
