"""库存 ORM 查询保留跨仓精度、日期边界和无操作人的历史流水。"""

import pytest
from decimal import Decimal
from sqlalchemy import event
from fastapi.testclient import TestClient

from app.core.models import StockMovement
from app.core.orm import orm_session, engine_for
from app.core.database import database_path
from app.main import app


@pytest.fixture
def inventory(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'inventory-query.db'))
    with TestClient(app, client=('127.0.0.1', 12000)) as client:
        base = '/api/v1'
        assert client.post(base + '/setup/admin', json={
            'username': 'admin', 'password': 'secure-pass-123'}).status_code == 201
        token = client.post(base + '/auth/login', json={
            'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
        client.headers['Authorization'] = f'Bearer {token}'
        material = client.post(base + '/materials', json={
            'sku': 'FLOW', 'name': '流水物料', 'unit': '件'}).json()['id']
        empty = client.post(base + '/materials', json={
            'sku': 'EMPTY', 'name': '无库存物料', 'unit': '件'}).json()['id']
        warehouse = client.post(base + '/warehouses', json={'code': 'SECOND', 'name': '外仓'}).json()['id']
        with orm_session(write=True) as db:
            for line_id, source_type, quantity, timestamp in (
                (1, 'receipt', '0.300', '2026-01-30 23:59:59'),
                (2, 'shipment', '-0.100', '2026-01-31 00:00:00'),
                (3, 'other_inbound', '0.200', '2026-02-01 00:00:00')):
                db.add(StockMovement(warehouse_id=1, material_id=material, quantity=quantity,
                    source_type=source_type, source_id=line_id, source_line_id=line_id,
                    created_by=None, created_at=timestamp))
            db.add(StockMovement(warehouse_id=warehouse, material_id=material, quantity='0.600',
                source_type='other_inbound', source_id=4, source_line_id=4, created_by=1,
                created_at='2026-01-31 23:59:59'))
        yield client, material, empty, warehouse


def test_multi_warehouse_quantities_and_empty_material(inventory):
    client, material, empty, warehouse = inventory
    quantities = lambda rows: {row['id']: row['quantity'] for row in rows}
    assert quantities(client.get('/api/v1/stock').json()) == {material: '1.000', empty: '0'}
    assert quantities(client.get('/api/v1/stock', params={'warehouse_id': 1}).json())[material] == '0.400'
    assert quantities(client.get('/api/v1/stock', params={'warehouse_id': warehouse}).json())[material] == '0.600'
    assert client.get('/api/v1/stock', params={'warehouse_id': 999999}).status_code == 422
    movements = client.get('/api/v1/movements').json()
    assert len(movements) == 4 and movements[0]['source_id'] == 4
    assert movements[-1]['receipt_id'] == 1 and movements[-1]['shipment_id'] is None
    assert movements[2]['shipment_id'] == 2 and movements[2]['receipt_id'] is None
    assert movements[-1]['created_by'] is None and movements[-1]['material_name'] == '流水物料'


def test_ledger_date_limits_and_source_scope(inventory):
    client, material, _, warehouse = inventory
    path = '/api/v1/inventory-ledger/query'
    filters = {'warehouse_id': 1, 'material_id': material, 'from_date': '2026-01-31', 'to_date': '2026-01-31'}
    ledger = client.post(path, json=filters).json()
    assert ledger['groups'][0]['opening_quantity'] == '0.300'
    assert ledger['groups'][0]['closing_quantity'] == '0.200'
    assert len(ledger['rows']) == 1 and ledger['rows'][0]['balance_quantity'] == '0.200'
    assert ledger['rows'][0]['created_by_name'] is None
    other = client.post(path, json={**filters, 'warehouse_id': warehouse}).json()
    assert len(other['rows']) == 1 and other['groups'][0]['closing_quantity'] == '0.600'
    source = client.post(path, json={**filters, 'source_type': 'shipment'}).json()
    assert source['groups'][0]['opening_quantity'] == '0'
    assert source['groups'][0]['closing_quantity'] == '-0.100'
    assert client.post(path, json={**filters, 'material_id': 999999}).status_code == 422
    assert client.post(path, json={**filters, 'warehouse_id': 999999}).status_code == 422
    assert client.post(path, json={**filters, 'source_type': "receipt' OR 1=1"}).status_code == 422


def test_inventory_queries_require_login(inventory):
    client, *_ = inventory
    client.headers.pop('Authorization')
    assert client.get('/api/v1/stock').status_code == 401
    assert client.get('/api/v1/movements').status_code == 401
    assert client.post('/api/v1/inventory-ledger/query', json={}).status_code == 401


def test_ledger_pagination_preserves_exact_balances_and_full_summary(inventory):
    client, material, _, _ = inventory
    # 同时覆盖超大精确小数、同秒多条流水、页边界与期初；不依赖浮点近似。
    with orm_session(write=True) as db:
        for index in range(25):
            db.add(StockMovement(warehouse_id=1, material_id=material,
                quantity='100000000000000000.001' if index == 0 else '0.001',
                source_type='adjustment', source_id=index + 1, source_line_id=index + 1,
                created_by=None, created_at='2026-02-02 12:00:00'))
    path = '/api/v1/inventory-ledger/query'
    filters = {'warehouse_id': 1, 'material_id': material, 'from_date': '2026-02-02', 'page_size': 10}
    statements = []
    engine = engine_for(database_path().resolve())
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        first = client.post(path, json=filters).json()
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    # 真正的数据库分页必须带 LIMIT/OFFSET，而不是在全量响应上切片。
    assert any('LIMIT' in sql and 'OFFSET' in sql and 'created_by_name' in sql for sql in statements)
    second = client.post(path, json={**filters, 'page': 2}).json()
    last = client.post(path, json={**filters, 'page': 999}).json()
    assert (first['total'], first['page'], first['page_size']) == (25, 1, 10)
    assert [len(page['rows']) for page in (first, second, last)] == [10, 10, 5]
    assert last['page'] == 3
    combined = first['rows'] + second['rows'] + last['rows']
    assert len({row['id'] for row in combined}) == 25
    assert [row['id'] for row in combined] == sorted((row['id'] for row in combined), reverse=True)
    assert first['groups'] == second['groups'] == last['groups']
    assert first['groups'][0]['opening_quantity'] == '0.400'
    assert first['groups'][0]['closing_quantity'] == '100000000000000000.425'
    assert [Decimal(row['balance_quantity']) for row in combined] == [
        Decimal('100000000000000000.425') - Decimal('0.001') * index for index in range(25)]
    # 来源筛选改变的是累计范围，分页不能混入其他来源的期初。
    only_source = client.post(path, json={**filters, 'source_type': 'adjustment', 'page': 2}).json()
    assert only_source['total'] == 25
    assert only_source['groups'][0]['opening_quantity'] == '0'
    assert only_source['rows'][0]['balance_quantity'] == '100000000000000000.015'
    # 报表曾从台账 rows 累计，分页后必须仍覆盖超过 20 条的期间流水和导出。
    with orm_session(write=True) as db:
        db.add(StockMovement(warehouse_id=1, material_id=material, quantity='-0.005',
            source_type='shipment', source_id=999, source_line_id=999, created_by=None,
            created_at='2026-02-03 12:00:00'))
    flow = client.post('/api/v1/reports/query', json={
        'kind': 'stock_flow', 'warehouse_id': 1, 'material_id': material,
        'from_date': '2026-02-02', 'to_date': '2026-02-03'}).json()
    assert flow['rows'][0]['opening'] == '0.400'
    assert flow['rows'][0]['inbound'] == '100000000000000000.025'
    assert flow['rows'][0]['outbound'] == '0.005'
    assert flow['rows'][0]['closing'] == '100000000000000000.420'
    assert '100000000000000000.025' in flow['csv']


def test_ledger_default_order_empty_pages_and_invalid_pagination(inventory):
    client, _, empty, _ = inventory
    path = '/api/v1/inventory-ledger/query'
    result = client.post(path, json={}).json()
    # 外仓流水后写入但时间较早，必须按时间排序，不能单纯按 ID 倒序。
    assert [row['source_id'] for row in result['rows']] == [3, 4, 2, 1]
    assert (result['page'], result['page_size'], result['total']) == (1, 20, 4)
    blank = client.post(path, json={'material_id': empty, 'page': 4}).json()
    assert blank == {'rows': [], 'groups': [], 'total': 0, 'page': 1, 'page_size': 20}
    for invalid in ({'page': 0}, {'page': -1}, {'page': 1.5},
                    {'page_size': 0}, {'page_size': 101}, {'page_size': 'wrong'}):
        assert client.post(path, json=invalid).status_code == 422
