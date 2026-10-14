"""批次分配在写事务内保持精确守恒，失败时整笔流水回滚。"""

from decimal import Decimal

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.models import Material, PhysicalLot, PhysicalLotAllocation, StockMovement
from app.core.orm import add_model, orm_session
from app.inventory.physical_lots import LotPart, lot_balance, post_lot_movement
from app.main import app


def _movement(material_id: int, warehouse_id: int, quantity: str, source_id: int) -> StockMovement:
    return StockMovement(
        warehouse_id=warehouse_id, material_id=material_id, quantity=quantity,
        source_type='lot_test', source_id=source_id, source_line_id=source_id, created_by=1)


def test_lot_posting_conserves_multi_lot_stock_and_reversal_lineage(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'lot-transactions.db'))
    with TestClient(app, client=('127.0.0.1', 12345)) as client:
        assert client.post('/api/v1/setup/admin', json={
            'username': 'admin', 'password': 'secure-pass-123'}).status_code == 201
        token = client.post('/api/v1/auth/login', json={
            'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
        auth = {'Authorization': f'Bearer {token}'}
        assert client.post('/api/v1/roles', headers=auth, json={
            'code': 'sales_only_lot_test', 'label': '仅销售查看', 'permissions': ['sales.view']}).status_code == 201
        assert client.post('/api/v1/users', headers=auth, json={
            'username': 'lot_sales', 'password': 'secure-pass-123', 'roles': ['sales_only_lot_test']}).status_code == 201
        sales_token = client.post('/api/v1/auth/login', json={
            'username': 'lot_sales', 'password': 'secure-pass-123'}).json()['token']
        sales_auth = {'Authorization': f'Bearer {sales_token}'}
        material_id = client.post('/api/v1/materials', headers=auth, json={
            'sku': 'LOT-TXN', 'name': '批次事务物料', 'unit': '件'}).json()['id']
        other_material_id = client.post('/api/v1/materials', headers=auth, json={
            'sku': 'LOT-OTHER', 'name': '其他物料', 'unit': '件'}).json()['id']

    with orm_session(write=True) as db:
        first = add_model(db, PhysicalLot(material_id=material_id, code='A',
                                          source_kind='lot_test', created_by=1))
        second = add_model(db, PhysicalLot(material_id=material_id, code='B',
                                           source_kind='lot_test', created_by=1))
        inbound_a = post_lot_movement(db, _movement(material_id, 1, '2.000', 1), [
            LotPart(first.id, Decimal('2.000'))])
        inbound_b = post_lot_movement(db, _movement(material_id, 1, '3.000', 2), [
            LotPart(second.id, Decimal('3.000'))])
        first.origin_movement_id = inbound_a.id
        second.origin_movement_id = inbound_b.id
        first_id, second_id = first.id, second.id

    with pytest.raises(HTTPException) as shortage:
        with orm_session(write=True) as db:
            post_lot_movement(db, _movement(material_id, 1, '-3.000', 3), [
                LotPart(first_id, Decimal('-2.001')),
                LotPart(second_id, Decimal('-0.999'))])
    assert shortage.value.status_code == 409

    with pytest.raises(HTTPException) as mismatch:
        with orm_session(write=True) as db:
            post_lot_movement(db, _movement(material_id, 1, '-3.000', 4), [
                LotPart(first_id, Decimal('-1.000'))])
    assert mismatch.value.status_code == 422

    with pytest.raises(HTTPException) as wrong_material:
        with orm_session(write=True) as db:
            post_lot_movement(db, _movement(other_material_id, 1, '1.000', 5), [
                LotPart(first_id, Decimal('1.000'))])
    assert wrong_material.value.status_code == 422

    with pytest.raises(HTTPException) as wrong_warehouse:
        with orm_session(write=True) as db:
            post_lot_movement(db, _movement(material_id, 2, '-1.000', 6), [
                LotPart(first_id, Decimal('-1.000'))])
    assert wrong_warehouse.value.status_code == 409

    with orm_session(write=True) as db:
        outbound = post_lot_movement(db, _movement(material_id, 1, '-3.000', 7), [
            LotPart(first_id, Decimal('-1.125')),
            LotPart(second_id, Decimal('-1.875'))])
        outbound_id = outbound.id

    with pytest.raises(HTTPException) as consumed:
        with orm_session(write=True) as db:
            post_lot_movement(db, _movement(material_id, 1, '-2.000', 8), [
                LotPart(first_id, Decimal('-2.000'))])
    assert consumed.value.status_code == 409

    with orm_session(write=True) as db:
        allocations = list(db.scalars(select(PhysicalLotAllocation).where(
            PhysicalLotAllocation.movement_id == outbound_id).order_by(PhysicalLotAllocation.lot_id)))
        assert [Decimal(row.quantity) for row in allocations] == [Decimal('-1.125'), Decimal('-1.875')]
        reversal = post_lot_movement(db, _movement(material_id, 1, '3.000', 9), [
            LotPart(first_id, Decimal('1.125'), allocations[0].id),
            LotPart(second_id, Decimal('1.875'), allocations[1].id)])
        reversal_id = reversal.id
        assert lot_balance(db, 1, first_id) == Decimal('2.000')
        assert lot_balance(db, 1, second_id) == Decimal('3.000')

    with pytest.raises(HTTPException) as duplicate_reversal:
        with orm_session(write=True) as db:
            post_lot_movement(db, _movement(material_id, 1, '1.125', 10), [
                LotPart(first_id, Decimal('1.125'), allocations[0].id)])
    assert duplicate_reversal.value.status_code == 409

    with orm_session() as db:
        assert len(list(db.scalars(select(StockMovement.id)))) == 4
        assert len(list(db.scalars(select(PhysicalLotAllocation.id)))) == 6
        assert db.get(Material, material_id).sku == 'LOT-TXN'

    with TestClient(app, client=('127.0.0.1', 12345)) as client:
        path = f'/api/v1/inventory/physical-lots/{first_id}/history'
        assert client.get(path).status_code == 401
        assert client.get(path, headers=sales_auth).status_code == 403
        assert client.get('/api/v1/inventory/physical-lots/999/history', headers=auth).status_code == 404
        assert client.get('/api/v1/inventory/physical-lots/overview', headers=auth,
                          params={'warehouse_id': 999}).status_code == 404
        assert client.get('/api/v1/inventory/physical-lots/overview', headers=auth,
                          params={'material_id': 999}).status_code == 404
        history = client.get(path, headers=auth).json()
        assert history['lot']['code'] == 'A'
        assert history['lot']['origin_movement_id'] == inbound_a.id
        assert history['openings'] == []
        assert [(row['warehouse_id'], row['quantity']) for row in history['balances']] == [(1, '2.000')]
        assert [(row['movement_id'], row['quantity'], row['source_id']) for row in history['movements']] == [
            (inbound_a.id, '2.000', 1), (outbound_id, '-1.125', 7), (reversal_id, '1.125', 9)]
        assert history['movements'][-1]['original_allocation_id'] == allocations[0].id
        second_history = client.get(f'/api/v1/inventory/physical-lots/{second_id}/history', headers=auth).json()
        assert len(second_history['movements']) == 3
        overview = client.get('/api/v1/inventory/physical-lots/overview', headers=auth, params={
            'warehouse_id': 1, 'material_id': material_id}).json()
        assert overview['warehouse_id'] == 1 and overview['material_id'] == material_id
        assert overview['fully_allocated'] is True


def test_overview_keeps_requested_scope_when_unallocated_differences_exist(monkeypatch, tmp_path):
    """差额遍历不能把最后一行的物料编号写回查询范围，否则全部物料页面拒收。"""
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'lot-overview-scope.db'))
    with TestClient(app, client=('127.0.0.1', 12345)) as client:
        assert client.post('/api/v1/setup/admin', json={
            'username': 'admin', 'password': 'secure-pass-123'}).status_code == 201
        token = client.post('/api/v1/auth/login', json={
            'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
        auth = {'Authorization': f'Bearer {token}'}
        materials = [client.post('/api/v1/materials', headers=auth, json={
            'sku': f'SCOPE-{index}', 'name': f'范围物料 {index}', 'unit': '件'}).json()['id']
            for index in range(2)]
        second_warehouse = client.post('/api/v1/warehouses', headers=auth, json={
            'code': 'SCOPE-W2', 'name': '范围副仓'}).json()['id']
        # 用 ORM 模拟旧版未分配流水，两仓两物料确保最后一个差额不会掩盖缺陷。
        with orm_session(write=True) as db:
            for index, (warehouse, material) in enumerate([(1, materials[0]), (1, materials[1]), (second_warehouse, materials[0])]):
                db.add(_movement(material, warehouse, '2.000', 900 + index))
        path = '/api/v1/inventory/physical-lots/overview'
        for params in ({}, {'warehouse_id': 1}, {'material_id': materials[0]},
                       {'warehouse_id': second_warehouse, 'material_id': materials[0]}):
            response = client.get(path, headers=auth, params=params)
            assert response.status_code == 200
            result = response.json()
            assert result['warehouse_id'] == params.get('warehouse_id')
            assert result['material_id'] == params.get('material_id')
            assert result['fully_allocated'] is False
            assert len(result['differences']) == (3 if not params else 1 if len(params) == 2 else 2)
            for row in result['differences']:
                assert row['difference'] == '2.000'
                assert all(row[key] == value for key, value in params.items())
        # 无差额及非法范围继续遵循原接口约定。
        empty = client.get(path, headers=auth, params={'warehouse_id': second_warehouse, 'material_id': materials[1]}).json()
        assert empty['differences'] == []
        assert empty['material_id'] == materials[1]
        assert client.get(path, headers=auth, params={'material_id': 99999}).status_code == 404
        assert client.get(path).status_code == 401
