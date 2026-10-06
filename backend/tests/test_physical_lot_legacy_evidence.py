"""历史未识别批次补证只改变实物归属，保留库存与操作者证据。"""

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.models import Material, PhysicalLot, PhysicalLotAllocation, PhysicalLotOpening, PhysicalLotReclassification, StockMovement
from app.core.database import connection, migrate
from app.core.orm import add_model, orm_session
from app.main import app


def test_legacy_evidence_reclassification_is_audited_and_keeps_stock(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'legacy-evidence.db'))
    with TestClient(app, client=('127.0.0.1', 12345)) as client:
        client.post('/api/v1/setup/admin', json={'username': 'admin', 'password': 'secure-pass-123'})
        token = client.post('/api/v1/auth/login', json={
            'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
        auth = {'Authorization': f'Bearer {token}'}
        assert client.post('/api/v1/users', headers=auth, json={
            'username': 'observer', 'password': 'observer-pass-123',
            'roles': ['viewer']}).status_code == 201
        observer_token = client.post('/api/v1/auth/login', json={
            'username': 'observer', 'password': 'observer-pass-123'}).json()['token']
        observer_auth = {'Authorization': f'Bearer {observer_token}'}
        material_id = client.post('/api/v1/materials', headers=auth, json={
            'sku': 'LEGACY-1', 'name': '待补证物料', 'unit': '件'}).json()['id']
        with orm_session(write=True) as db:
            movement = add_model(db, StockMovement(
                warehouse_id=1, material_id=material_id, quantity='5.000',
                source_type='legacy_test', source_id=1, source_line_id=1, created_by=1))
            lot = add_model(db, PhysicalLot(material_id=material_id,
                code=f'LEGACY-W1-M{material_id}', source_kind='legacy'))
            db.add(PhysicalLotOpening(lot_id=lot.id, warehouse_id=1, quantity='5.000',
                checkpoint_movement_id=movement.id, evidence='旧库存无实物批次证据'))
            legacy_id = lot.id
            movement_id = movement.id
        path = '/api/v1/inventory/physical-lots/reclassifications'
        body = {'legacy_lot_id': legacy_id, 'warehouse_id': 1, 'quantity': '2.125',
                'supplier_lot': '现场-001', 'evidence': '2026-10-03 现场逐箱核对并签字确认'}
        assert client.post(path, json=body).status_code == 401
        assert client.post(path, headers=observer_auth, json=body).status_code == 403
        created = client.post(path, headers=auth, json=body)
        assert created.status_code == 201, created.text
        result = created.json()
        assert result['quantity'] == '2.125'
        assert result['created_by_name'] == 'admin'
        assert result['verified_lot_code'].startswith('VERIFIED-')
        overview = client.get('/api/v1/inventory/physical-lots/overview', headers=auth,
                              params={'warehouse_id': 1, 'material_id': material_id}).json()
        assert overview['fully_allocated'] is True
        assert {(row['lot_id'], row['quantity']) for row in overview['rows']} == {
            (legacy_id, '2.875'), (result['verified_lot_id'], '2.125')}
        old_history = client.get(f'/api/v1/inventory/physical-lots/{legacy_id}/history', headers=auth).json()
        new_history = client.get(f"/api/v1/inventory/physical-lots/{result['verified_lot_id']}/history", headers=auth).json()
        assert old_history['reclassifications'][0]['quantity'] == '-2.125'
        assert new_history['reclassifications'][0]['quantity'] == '2.125'
        assert new_history['reclassifications'][0]['evidence'] == body['evidence']
        assert new_history['lot']['supplier_lot'] == '现场-001'
        with orm_session() as db:
            assert list(db.scalars(select(StockMovement.id))) == [movement_id]
            assert db.scalar(select(PhysicalLotReclassification.id)) == result['id']

        reverse_path = f"{path}/{result['id']}/reverse"
        assert client.post(reverse_path, headers=observer_auth,
                           json={'reason': '现场复核发现原标签错误'}).status_code == 403
        with orm_session(write=True) as db:
            outgoing = add_model(db, StockMovement(warehouse_id=1, material_id=material_id,
                quantity='-1.000', source_type='legacy_test', source_id=3, source_line_id=3, created_by=1))
            db.add(PhysicalLotAllocation(lot_id=result['verified_lot_id'],
                                         movement_id=outgoing.id, quantity='-1.000'))
        assert client.post(reverse_path, headers=auth,
                           json={'reason': '现场复核发现原标签错误'}).status_code == 409
        with orm_session(write=True) as db:
            incoming = add_model(db, StockMovement(warehouse_id=1, material_id=material_id,
                quantity='1.000', source_type='legacy_test', source_id=4, source_line_id=4, created_by=1))
            db.add(PhysicalLotAllocation(lot_id=result['verified_lot_id'],
                                         movement_id=incoming.id, quantity='1.000'))

        invalid = {**body, 'quantity': '3.000'}
        assert client.post(path, headers=auth, json=invalid).status_code == 409
        assert client.post(path, headers=auth, json={**body, 'quantity': '0.000'}).status_code == 422
        assert client.post(path, headers=auth, json={**body, 'quantity': 0.125}).status_code == 422
        assert client.post(path, headers=auth, json={**body, 'evidence': '无'}).status_code == 422
        assert client.post(path, headers=auth, json={**body, 'legacy_lot_id': result['verified_lot_id']}).status_code == 422
        with orm_session() as db:
            assert db.scalar(select(PhysicalLotReclassification.id).order_by(
                PhysicalLotReclassification.id.desc())) == result['id']
            assert sum((Decimal(row.quantity) for row in db.scalars(select(StockMovement))), Decimal(0)) == Decimal('5.000')
        with orm_session(write=True) as db:
            db.add(StockMovement(warehouse_id=1, material_id=material_id, quantity='-1.000',
                source_type='legacy_test', source_id=2, source_line_id=2, created_by=1))
        assert client.post(path, headers=auth, json={**body, 'quantity': '0.125'}).status_code == 409
        reversed_result = client.post(reverse_path, headers=auth,
                                      json={'reason': '现场复核发现原标签错误'})
        assert reversed_result.status_code == 201, reversed_result.text
        assert reversed_result.json()['quantity'] == '-2.125'
        assert reversed_result.json()['original_reclassification_id'] == result['id']
        assert client.post(reverse_path, headers=auth,
                           json={'reason': '重复冲销必须被服务端拒绝'}).status_code == 409
        history = client.get(f'/api/v1/inventory/physical-lots/{legacy_id}/history', headers=auth).json()
        assert [item['quantity'] for item in history['reclassifications']] == ['-2.125', '2.125']
        assert history['reclassifications'][1]['original_reclassification_id'] == result['id']
        overview = client.get('/api/v1/inventory/physical-lots/overview', headers=auth,
                              params={'warehouse_id': 1, 'material_id': material_id}).json()
        assert overview['differences'][0]['difference'] == '-1.000'
        assert {(row['lot_id'], row['quantity']) for row in overview['rows']} == {
            (legacy_id, '5.000'), (result['verified_lot_id'], '0.000')}


def test_v56_upgrade_preserves_openings_and_adds_permission_once(monkeypatch, tmp_path, remove_equipment_hour_schema):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'v56-reclass.db'))
    migrate()
    with orm_session(write=True) as db:
        material = add_model(db, Material(sku='UPGRADE-1', name='迁移试件', unit='件'))
        lot = add_model(db, PhysicalLot(material_id=material.id, code='LEGACY-UPGRADE', source_kind='legacy'))
        db.add(PhysicalLotOpening(lot_id=lot.id, warehouse_id=1, quantity='1.250',
                                  checkpoint_movement_id=0, evidence='旧库存未识别'))
    with connection() as db:
        before = db.execute('SELECT * FROM physical_lot_openings').fetchall()
        remove_equipment_hour_schema(db)
        db.execute('DROP TABLE physical_lot_evidence_group_pairs')
        db.execute('DROP TABLE physical_lot_evidence_groups')
        db.execute('DROP TABLE physical_lot_evidence_pairs')
        db.execute('DROP TABLE physical_lot_movement_evidence')
        db.execute('DROP TABLE physical_lot_movement_checkpoints')
        db.execute("DELETE FROM role_permissions WHERE permission_code='physical_lot.movement_evidence'")
        db.execute("DELETE FROM permissions WHERE code='physical_lot.movement_evidence'")
        db.execute('DROP TABLE physical_lot_reclassifications')
        db.execute("DELETE FROM role_permissions WHERE permission_code='physical_lot.reclassify'")
        db.execute("DELETE FROM permissions WHERE code='physical_lot.reclassify'")
        db.execute("DELETE FROM permission_groups WHERE code='warehouse.physical_lots'")
        db.execute('PRAGMA user_version = 56')
    migrate()
    migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 85
        assert db.execute('SELECT * FROM physical_lot_openings').fetchall() == before
        assert db.execute("SELECT COUNT(*) FROM role_permissions WHERE permission_code='physical_lot.reclassify'").fetchone()[0] == 2
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
