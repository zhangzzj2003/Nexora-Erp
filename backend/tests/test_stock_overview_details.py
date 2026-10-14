"""库存总览按真实分类检索，跨仓分布与统计保持精确且不受分页影响。"""
from decimal import Decimal
import pytest
from sqlalchemy import select, event
from app.core.models import Material, MaterialCategory, StockMovement
from app.core.orm import orm_session, engine_for
from app.core.database import database_path
from test_inventory_query_orm import inventory, add_paged_materials


def query(client, **filters):
    response = client.post('/api/v1/stock/query', json=filters)
    assert response.status_code == 200, response.text
    return response.json()


def test_real_category_and_literal_search_with_database_pagination(inventory):
    client, material, empty, _ = inventory
    add_paged_materials()
    with orm_session(write=True) as db:
        row = db.get(Material, material)
        row.category_code = 'HW-FA'; row.name = '精密 100%_ 紧固件'
        # SKU 与分类前缀不一致也必须按档案分类，支持目录改名及停用后的查询。
        group = db.get(MaterialCategory, 'HW'); group.name = '五金配件'; group.enabled = False
    result = query(client, keyword='FLOW 精密 100%_', category_group='HW')
    row = result['items'][0]
    assert result['total'] == 1 and row['id'] == material
    assert row['category_group_name'] == '五金配件'
    assert row['category_name'].startswith('五金配件 / ')
    assert query(client, keyword='%_')['total'] == 1
    assert query(client, keyword="' OR 1=1")['total'] == 0
    assert query(client, category_group='EL')['items'] == []
    assert query(client, category_group='')['total'] == 26
    statements = []
    engine = engine_for(database_path().resolve())
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        page = query(client, keyword='分页', page=2, page_size=10)
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    assert page['total'] == 25 and len(page['items']) == 10
    assert any('LIMIT' in text and 'OFFSET' in text for text in statements)


def test_all_warehouse_distribution_scoped_totals_and_zero_history(inventory):
    client, material, empty, warehouse = inventory
    with orm_session(write=True) as db:
        for warehouse_id, material_id, quantity in [(1, material, '-0.4'), (warehouse, empty, '-2')]:
            db.add(StockMovement(warehouse_id=warehouse_id, material_id=material_id, quantity=quantity,
                source_type='adjustment', source_id=80, source_line_id=material_id, created_by=1, created_at='2026-02-03 01:00:00'))
    result = query(client, warehouse_id=1, material_id=material, page_size=1)
    row = result['items'][0]
    assert row['quantity'] == '0.000' and row['total_quantity'] == '0.600'
    assert {item['warehouse_id']: item['quantity'] for item in row['warehouses']} == {1: '0.000', warehouse: '0.600'}
    assert all(item['warehouse_code'] and item['warehouse_name'] for item in row['warehouses'])
    scoped = query(client, warehouse_id=1, page_size=1)['summary']
    assert (scoped['positive_material_count'], scoped['zero_material_count'], scoped['negative_material_count']) == (0, 2, 0)
    full = query(client, page_size=1)['summary']
    assert (full['positive_material_count'], full['zero_material_count'], full['negative_material_count']) == (1, 0, 1)
    assert full == query(client, page=2, page_size=1)['summary']
    # 单一物料详情的全仓数量与流水完整汇总一致，不能用第一页一条流水代替。
    ledger = client.post('/api/v1/inventory-ledger/query', json={'material_id': material, 'page_size': 1}).json()
    assert Decimal(row['total_quantity']) == sum(Decimal(item['closing_quantity']) for item in ledger['groups'])
    assert ledger['total'] > len(ledger['rows'])


def test_warehouse_quantities_keep_large_decimal_precision(inventory):
    client, material, _, warehouse = inventory
    with orm_session(write=True) as db:
        db.add(StockMovement(warehouse_id=warehouse, material_id=material, quantity='100000000000000000.001',
            source_type='adjustment', source_id=90, source_line_id=1, created_by=1, created_at='2026-02-04 01:00:00'))
    row = query(client, material_id=material)['items'][0]
    assert row['total_quantity'] == row['quantity'] == '100000000000000001.001'
    assert next(item['quantity'] for item in row['warehouses'] if item['warehouse_id'] == warehouse) == '100000000000000000.601'


@pytest.mark.parametrize('payload,code', [({'material_id': 999999}, 404), ({'material_id': 0}, 422),
    ({'category_group': 'MISSING'}, 422), ({'category_group': 'HW-FA'}, 422), ({'keyword': 'a' * 121}, 422)])
def test_invalid_stock_detail_query_is_rejected(inventory, payload, code):
    client, *_ = inventory
    assert client.post('/api/v1/stock/query', json=payload).status_code == code


def test_stock_query_requires_inventory_permission(inventory):
    client, material, *_ = inventory
    # 登录账号不等同于库存查看权限；与已有分页端点保持同一权限边界。
    role = client.post('/api/v1/roles', json={'code': 'no_stock', 'label': '无库存权限', 'permissions': []})
    assert role.status_code == 201, role.text
    created = client.post('/api/v1/users', json={'username': 'no_stock', 'password': 'secure-pass-123', 'roles': ['no_stock']})
    assert created.status_code == 201, created.text
    token = client.post('/api/v1/auth/login', json={'username': 'no_stock', 'password': 'secure-pass-123'}).json()['token']
    response = client.post('/api/v1/stock/query', headers={'Authorization': f'Bearer {token}'}, json={'material_id': material})
    assert response.status_code == 403
