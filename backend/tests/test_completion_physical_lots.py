"""合格完工批次、整批不合格与原分配冲销的接口验收。"""

from approval_test_helpers import approve_document

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.models import PhysicalLot, PhysicalLotAllocation, StockMovement
from app.core.orm import orm_session
from app.inventory.physical_lots import LotPart, post_lot_movement
from app.main import app


def test_completion_lots_follow_accepted_quantity_and_original_reversal(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'completion-lots.db'))
    with TestClient(app, client=('127.0.0.1', 12000)) as client:
        base = '/api/v1'
        assert client.post(f'{base}/setup/admin', json={
            'username': 'admin', 'password': 'secure-pass-123'}).status_code == 201
        token = client.post(f'{base}/auth/login', json={
            'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
        auth = {'Authorization': f'Bearer {token}'}
        supplier = client.post(f'{base}/suppliers', headers=auth, json={'name': '组件来源'}).json()['id']
        product = client.post(f'{base}/materials', headers=auth, json={
            'sku': 'FINISHED-LOT', 'name': '成品', 'unit': '件'}).json()['id']
        component = client.post(f'{base}/materials', headers=auth, json={
            'sku': 'COMPONENT-LOT', 'name': '组件', 'unit': '件'}).json()['id']
        receipt = client.post(f'{base}/receipts', headers=auth, json={
            'supplier_id': supplier, 'warehouse_id': 1,
            'lines': [{'material_id': component, 'quantity': '4'}]}).json()['id']
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, auth, 'Receipt', receipt)
        assert client.post(f'{base}/receipts/{receipt}/post', headers=auth).status_code == 200
        bom = client.post(f'{base}/boms', headers=auth, json={
            'product_material_id': product, 'base_quantity': '1',
            'lines': [{'component_material_id': component, 'quantity': '2'}]}).json()['id']
        assert client.post(f'{base}/boms/{bom}/activate', headers=auth).status_code == 200
        order = client.post(f'{base}/work-orders', headers=auth, json={
            'bom_id': bom, 'warehouse_id': 1, 'target_quantity': '2'}).json()
        assert client.post(f'{base}/work-orders/{order["id"]}/release', headers=auth).status_code == 200
        issue = client.post(f'{base}/material-issues', headers=auth, json={
            'work_order_id': order['id'], 'warehouse_id': 1,
            'lines': [{'work_order_line_id': order['lines'][0]['id'], 'quantity': '4'}]}).json()['id']
        assert client.post(f'{base}/material-issues/{issue}/post', headers=auth).status_code == 200

        first = client.post(f'{base}/production-completions', headers=auth, json={
            'work_order_id': order['id'], 'reported_quantity': '1'}).json()['id']
        assert client.post(f'{base}/production-completions/{first}/inspect', headers=auth, json={
            'accepted_quantity': '1', 'qc_note': '合格'}).status_code == 200
        post_url = f'{base}/production-completions/{first}/post'
        for invalid in [
            {'lots': []},
            {'lots': [{'quantity': '0.999'}]},
            {'lots': [{'quantity': '1', 'manufactured_on': '2026-10-02',
                       'expires_on': '2026-10-01'}]},
        ]:
            assert client.post(post_url, headers=auth, json=invalid).status_code == 422
        with orm_session() as db:
            assert list(db.scalars(select(PhysicalLot.id).where(PhysicalLot.material_id == product))) == []
            assert list(db.scalars(select(StockMovement.id).where(StockMovement.material_id == product))) == []
        posted = client.post(post_url, headers=auth, json={'lots': [
            {'quantity': '0.375', 'manufactured_on': '2026-10-01', 'expires_on': '2027-10-01'},
            {'quantity': '0.625'}]})
        assert posted.status_code == 200
        lots = posted.json()['physical_lots']
        assert [(row['code'], row['quantity']) for row in lots] == [
            (f'P{first}-P1', '0.375'), (f'P{first}-P2', '0.625')]
        assert lots[0]['manufactured_on'] == '2026-10-01'
        assert client.post(post_url, headers=auth, json={'lots': [{'quantity': '1'}]}).status_code == 409
        assert client.get(f'{base}/inventory/physical-lots/overview', headers=auth).json()['fully_allocated'] is True

        second = client.post(f'{base}/production-completions', headers=auth, json={
            'work_order_id': order['id'], 'reported_quantity': '1'}).json()['id']
        assert client.post(f'{base}/production-completions/{second}/inspect', headers=auth, json={
            'accepted_quantity': '0', 'qc_note': '整批不合格'}).status_code == 200
        second_url = f'{base}/production-completions/{second}/post'
        assert client.post(second_url, headers=auth, json={
            'lots': [{'quantity': '1'}]}).status_code == 422
        zero = client.post(second_url, headers=auth)
        assert zero.status_code == 200
        assert zero.json()['physical_lots'] == []

        with orm_session(write=True) as db:
            spent = post_lot_movement(db, StockMovement(
                warehouse_id=1, material_id=product, quantity='-0.125',
                source_type='lot_test_outbound', source_id=1, source_line_id=1,
                created_by=1), [LotPart(lots[0]['id'], Decimal('-0.125'))])
            spent_id = spent.id
        reverse_url = f'{base}/production-completions/{first}/reverse'
        assert client.post(reverse_url, headers=auth, json={'reason': '误报'}).status_code == 409
        assert client.get(f'{base}/production-completions', headers=auth).json()[1]['reversal_id'] is None
        with orm_session(write=True) as db:
            original = db.scalar(select(PhysicalLotAllocation).where(
                PhysicalLotAllocation.movement_id == spent_id))
            post_lot_movement(db, StockMovement(
                warehouse_id=1, material_id=product, quantity='0.125',
                source_type='lot_test_reversal', source_id=2, source_line_id=1,
                created_by=1), [LotPart(lots[0]['id'], Decimal('0.125'), original.id)])
        reversed_entry = client.post(reverse_url, headers=auth, json={'reason': '误报'})
        assert reversed_entry.status_code == 200
        assert reversed_entry.json()['status'] == 'reversed'
        assert client.post(reverse_url, headers=auth, json={'reason': '重复'}).status_code == 409
        history = client.get(f'{base}/inventory/physical-lots/{lots[0]["id"]}/history',
                             headers=auth).json()
        assert history['movements'][-1]['quantity'] == '-0.375'
        assert history['movements'][-1]['original_allocation_id'] == history['movements'][0]['id']
