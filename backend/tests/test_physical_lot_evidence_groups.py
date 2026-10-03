"""多笔相抵流水须整组提交和冲销，不能留下半组来源。"""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import connection, migrate
from app.core.models import (Material, PhysicalLotEvidenceGroup, PhysicalLotEvidenceGroupPair,
                             PhysicalLotEvidencePair, PhysicalLotMovementEvidence, StockMovement)
from app.core.orm import add_model, orm_session
from app.main import app


def test_grouped_movement_evidence_is_atomic_and_reversible(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'evidence-group.db'))
    with TestClient(app, client=('127.0.0.1', 12345)) as client:
        client.post('/api/v1/setup/admin', json={'username': 'admin', 'password': 'secure-pass-123'})
        token = client.post('/api/v1/auth/login', json={
            'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
        auth = {'Authorization': f'Bearer {token}'}
        material_id = client.post('/api/v1/materials', headers=auth, json={
            'sku': 'GROUP-1', 'name': '成组核对试件', 'unit': '件'}).json()['id']
        with orm_session(write=True) as db:
            inbound = add_model(db, StockMovement(warehouse_id=1, material_id=material_id,
                quantity='2.000', source_type='legacy_test', source_id=1, source_line_id=1))
            outbound_one = add_model(db, StockMovement(warehouse_id=1, material_id=material_id,
                quantity='-1.000', source_type='legacy_test', source_id=2, source_line_id=2))
            outbound_two = add_model(db, StockMovement(warehouse_id=1, material_id=material_id,
                quantity='-1.000', source_type='legacy_test', source_id=3, source_line_id=3))
            movement_ids = inbound.id, outbound_one.id, outbound_two.id
        path = '/api/v1/inventory/physical-lots/evidence-groups'
        body = {'pairs': [
            {'inbound_movement_id': movement_ids[0], 'outbound_movement_id': movement_ids[2],
             'quantity': '1.000'},
            {'inbound_movement_id': movement_ids[0], 'outbound_movement_id': movement_ids[1],
             'quantity': '1.000'}],
            'evidence': '入库两件的箱码分别与两次出库交接记录逐件核对'}
        assert client.post(path, json=body).status_code == 401
        assert client.post(path, headers=auth, json={**body, 'pairs': body['pairs'][:1]}).status_code == 422
        assert client.post(path, headers=auth, json={**body, 'pairs':
            [body['pairs'][0], body['pairs'][0]]}).status_code == 422
        assert client.post(path, headers=auth, json={**body, 'pairs':
            [{**body['pairs'][0], 'quantity': 1}, body['pairs'][1]]}).status_code == 422
        assert client.post(path, headers=auth, json={**body, 'pairs':
            [{**body['pairs'][0], 'quantity': '1.001'}, body['pairs'][1]]}).status_code == 409
        with orm_session() as db:
            assert db.scalar(select(PhysicalLotEvidenceGroup.id)) is None
            assert db.scalar(select(PhysicalLotEvidencePair.id)) is None
        created = client.post(path, headers=auth, json=body)
        assert created.status_code == 201, created.text
        record = created.json()
        assert len(record['pairs']) == 2
        assert [part['outbound_movement_id'] for part in record['pairs']] == list(movement_ids[1:])
        assert len({part['lot_id'] for part in record['pairs']}) == 1
        assert client.get('/api/v1/inventory/physical-lots/unallocated-movements',
            headers=auth).json()['rows'] == []
        history = client.get(f"/api/v1/inventory/physical-lots/{record['lot_id']}/history",
            headers=auth).json()
        assert history['evidence_groups'][0]['id'] == record['id']
        assert len(history['evidence_groups'][0]['pairs']) == 2
        assert history['balances'][0]['quantity'] == '0.000'
        for part in record['pairs']:
            assert client.post(f"/api/v1/inventory/physical-lots/evidence-pairs/{part['id']}/reverse",
                headers=auth, json={'reason': '成组补证不能单独冲销其中一对'}).status_code == 422
        reverse_path = f"{path}/{record['id']}/reverse"
        reversed_group = client.post(reverse_path, headers=auth,
            json={'reason': '复核发现交接记录不对应，整组撤销'})
        assert reversed_group.status_code == 201, reversed_group.text
        assert reversed_group.json()['original_group_id'] == record['id']
        assert len(reversed_group.json()['pairs']) == 2
        assert client.post(reverse_path, headers=auth,
            json={'reason': '同一成组记录不可重复冲销'}).status_code == 409
        with orm_session() as db:
            assert len(list(db.scalars(select(PhysicalLotEvidenceGroup.id)))) == 2
            assert len(list(db.scalars(select(PhysicalLotEvidenceGroupPair)))) == 4
            assert len(list(db.scalars(select(PhysicalLotEvidencePair.id)))) == 4
            assert len(list(db.scalars(select(PhysicalLotMovementEvidence.id)))) == 8
            assert [row.quantity for row in db.scalars(select(StockMovement).order_by(StockMovement.id))] == [
                '2.000', '-1.000', '-1.000']


def test_group_mismatch_rolls_back_all_pairs_and_v59_upgrade(monkeypatch, tmp_path, remove_equipment_hour_schema):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'evidence-group-upgrade.db'))
    migrate()
    with connection() as db:
        remove_equipment_hour_schema(db)
        db.execute('DROP TABLE physical_lot_evidence_group_pairs')
        db.execute('DROP TABLE physical_lot_evidence_groups')
        db.execute('PRAGMA user_version = 59')
    migrate()
    migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 70
    with TestClient(app, client=('127.0.0.1', 12345)) as client:
        client.post('/api/v1/setup/admin', json={'username': 'admin', 'password': 'secure-pass-123'})
        token = client.post('/api/v1/auth/login', json={
            'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
        auth = {'Authorization': f'Bearer {token}'}
        first = client.post('/api/v1/materials', headers=auth, json={
            'sku': 'GROUP-2', 'name': '第一物料', 'unit': '件'}).json()['id']
        second = client.post('/api/v1/materials', headers=auth, json={
            'sku': 'GROUP-3', 'name': '第二物料', 'unit': '件'}).json()['id']
        with orm_session(write=True) as db:
            rows = [add_model(db, StockMovement(warehouse_id=1, material_id=material,
                quantity=quantity, source_type='legacy_test', source_id=index, source_line_id=index))
                for index, (material, quantity) in enumerate(
                    ((first, '1.000'), (first, '-1.000'),
                     (second, '1.000'), (second, '-1.000')), start=1)]
            ids = [row.id for row in rows]
        response = client.post('/api/v1/inventory/physical-lots/evidence-groups', headers=auth,
            json={'pairs': [
                {'inbound_movement_id': ids[0], 'outbound_movement_id': ids[1],
                 'quantity': '1.000'},
                {'inbound_movement_id': ids[2], 'outbound_movement_id': ids[3],
                 'quantity': '1.000'}],
                'evidence': '两类不同物料不得强行归为同一批次'})
        assert response.status_code == 422
        with orm_session() as db:
            assert db.scalar(select(PhysicalLotEvidenceGroup.id)) is None
            assert db.scalar(select(PhysicalLotEvidencePair.id)) is None
            assert db.scalar(select(PhysicalLotMovementEvidence.id)) is None
