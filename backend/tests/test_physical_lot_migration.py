"""旧库存批次期初只承认逐仓余额，不伪造历史实物来源。"""

from approval_test_helpers import approve_document
import sqlite3
from contextlib import contextmanager
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import connection, migrate
from app.core.models import PhysicalLot, PhysicalLotAllocation, PhysicalLotOpening, StockMovement
from app.core.orm import add_model, orm_session
from app.main import app


def test_existing_movements_become_unidentified_lot_openings(monkeypatch, tmp_path, remove_physical_lot_schema):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'old-stock.db'))
    with TestClient(app, client=('127.0.0.1', 12345)) as client:
        assert client.post('/api/v1/setup/admin', json={
            'username': 'admin', 'password': 'secure-pass-123'}).status_code == 201
        token = client.post('/api/v1/auth/login', json={
            'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
        auth = {'Authorization': f'Bearer {token}'}
        material_id = client.post('/api/v1/materials', headers=auth, json={
            'sku': 'LOT-HISTORY', 'name': '旧库存物料', 'unit': '件'}).json()['id']
        warehouse_id = client.post('/api/v1/warehouses', headers=auth, json={
            'code': 'SECOND', 'name': '第二仓'}).json()['id']
        for target_warehouse, quantity in ((1, '2.125'), (warehouse_id, '3.375')):
            inbound_id = client.post('/api/v1/warehouse-inbounds', headers=auth, json={
                'warehouse_id': target_warehouse, 'reason': 'opening', 'note': '旧期初',
                'lines': [{'material_id': material_id, 'quantity': quantity}]}).json()['id']
            approve_document(client, auth, 'WarehouseInbound', inbound_id)
            assert client.post(f'/api/v1/warehouse-inbounds/{inbound_id}/post', headers=auth).status_code == 200
        outbound_id = client.post('/api/v1/warehouse-outbounds', headers=auth, json={
            'warehouse_id': 1, 'reason': 'sample', 'note': '旧出库',
            'lines': [{'material_id': material_id, 'quantity': '0.125'}]}).json()['id']
        approve_document(client, auth, 'WarehouseOutbound', outbound_id)
        assert client.post(f'/api/v1/warehouse-outbounds/{outbound_id}/post', headers=auth).status_code == 200

    with orm_session() as db:
        movement_ids = list(db.scalars(select(StockMovement.id).order_by(StockMovement.id)))
    with connection() as db:
        remove_physical_lot_schema(db)
        db.execute('PRAGMA user_version = 55')
    migrate()
    migrate()

    with orm_session() as db:
        lots = list(db.scalars(select(PhysicalLot).order_by(PhysicalLot.id)))
        openings = list(db.scalars(select(PhysicalLotOpening).order_by(PhysicalLotOpening.id)))
        assert [(lot.material_id, lot.code, lot.source_kind, lot.origin_movement_id)
                for lot in lots] == [
                    (material_id, f'LEGACY-W1-M{material_id}', 'legacy', None),
                    (material_id, f'LEGACY-W{warehouse_id}-M{material_id}', 'legacy', None)]
        assert [(row.warehouse_id, Decimal(row.quantity), row.checkpoint_movement_id)
                for row in openings] == [(1, Decimal('2.000'), movement_ids[-1]),
                                         (warehouse_id, Decimal('3.375'), movement_ids[-1])]
        assert all('无实物批次证据' in row.evidence for row in openings)
        assert db.scalar(select(PhysicalLotAllocation.id)) is None
        assert list(db.scalars(select(StockMovement.id).order_by(StockMovement.id))) == movement_ids

    with TestClient(app, client=('127.0.0.1', 12345)) as client:
        path = '/api/v1/inventory/physical-lots/overview'
        assert client.get(path).status_code == 401
        before = client.get(path, headers=auth).json()
        assert before['fully_allocated'] is True
        assert before['differences'] == []
        history = client.get(f'/api/v1/inventory/physical-lots/{lots[0].id}/history', headers=auth).json()
        assert history['lot']['source_kind'] == 'legacy'
        assert history['lot']['origin_movement_id'] is None
        assert history['movements'] == []
        assert history['openings'][0]['checkpoint_movement_id'] == movement_ids[-1]
        assert {(row['warehouse_id'], row['quantity'], row['source_kind']) for row in before['rows']} == {
            (1, '2.000', 'legacy'), (warehouse_id, '3.375', 'legacy')}
        new_inbound = client.post('/api/v1/warehouse-inbounds', headers=auth, json={
            'warehouse_id': 1, 'reason': 'gift', 'note': '升级后新入库',
            'lines': [{'material_id': material_id, 'quantity': '0.125'}]}).json()['id']
        approve_document(client, auth, 'WarehouseInbound', new_inbound)
        assert client.post(f'/api/v1/warehouse-inbounds/{new_inbound}/post', headers=auth).status_code == 200
        after = client.get(path, headers=auth, params={
            'warehouse_id': 1, 'material_id': material_id}).json()
        assert after['fully_allocated'] is False
        assert after['differences'] == [{
            'warehouse_id': 1, 'warehouse_name': '主仓库', 'material_id': material_id,
            'sku': 'LOT-HISTORY', 'stock_quantity': '2.125',
            'lot_quantity': '2.000', 'difference': '0.125'}]

        # 分配直接引用已确认流水；两边数量相等后，诊断差额随之消失。
        with orm_session(write=True) as db:
            movement_id = db.scalar(select(StockMovement.id).where(
                StockMovement.source_type == 'other_inbound',
                StockMovement.source_id == new_inbound))
            lot = add_model(db, PhysicalLot(material_id=material_id, code='GIFT-BATCH',
                                            source_kind='other_inbound', origin_movement_id=movement_id,
                                            created_by=1))
            db.add(PhysicalLotAllocation(lot_id=lot.id, movement_id=movement_id, quantity='0.125'))
        complete = client.get(path, headers=auth, params={'warehouse_id': 1}).json()
        assert complete['fully_allocated'] is True
        assert complete['differences'] == []
        assert any(row['lot_code'] == 'GIFT-BATCH' and row['quantity'] == '0.125'
                   for row in complete['rows'])


def test_failed_lot_upgrade_rolls_back_all_new_tables(monkeypatch, tmp_path, remove_physical_lot_schema):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'interrupted.db'))
    migrate()
    with connection() as db:
        remove_physical_lot_schema(db)
        db.execute('PRAGMA user_version = 55')

    from app.core import database
    original_connection = database.connection

    @contextmanager
    def fail_allocation_table():
        with original_connection() as db:
            db.set_authorizer(lambda action, name, *_: sqlite3.SQLITE_DENY
                              if action == sqlite3.SQLITE_CREATE_TABLE and name == 'physical_lot_allocations'
                              else sqlite3.SQLITE_OK)
            yield db

    with monkeypatch.context() as scoped:
        scoped.setattr(database, 'connection', fail_allocation_table)
        with pytest.raises(sqlite3.DatabaseError):
            migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 55
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name LIKE 'physical_lot_%'").fetchone()
    migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 91
