"""实到先入库、续收检查点与部分冲销的业务回归。"""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.models import PhysicalLot, StockMovement, WarehouseInbound
from app.core.orm import orm_session
from app.inventory.warehouse import balance
from app.main import app
from approval_test_helpers import approve_document


@pytest.fixture
def inbound_client(monkeypatch, tmp_path):
    # 使用独立临时实例，测试只通过真实接口完成建单、审批与记账。
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'partial-inbound.db'))
    with TestClient(app, client=('127.0.0.1', 12010)) as client:
        assert client.post('/api/v1/setup/admin', json={
            'username': 'admin', 'password': 'secure-pass-123'}).status_code == 201
        token = client.post('/api/v1/auth/login', json={
            'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
        auth = {'Authorization': 'Bearer ' + token}
        materials = [client.post('/api/v1/materials', headers=auth, json={
            'sku': f'PARTIAL-{i}', 'name': f'分批物料{i}', 'unit': '件'}).json()['id'] for i in range(2)]
        yield client, auth, materials


def create_inbound(client, auth, materials):
    created = client.post('/api/v1/warehouse-inbounds', headers=auth, json={
        'warehouse_id': 1, 'reason': 'other', 'note': '分次实际到货',
        'lines': [{'material_id': identifier, 'quantity': '1000'} for identifier in materials]})
    assert created.status_code == 201, created.text
    return created.json()


def lot_line(line, quantity, checkpoint):
    # 检查点代表客户端读到的累计实收，不能在重试时自动改成最新值。
    return {'inbound_line_id': line['id'], 'expected_received_quantity': checkpoint,
            'lots': [{'quantity': quantity, 'supplier_lot': 'ACTUAL-LOT'}]}


def post(client, auth, record, lines):
    return client.post(f'/api/v1/warehouse-inbounds/{record["id"]}/post', headers=auth, json={'lines': lines})


def test_partial_800_is_usable_for_production_then_remaining_200(inbound_client):
    client, auth, materials = inbound_client
    record = create_inbound(client, auth, materials[:1])
    line = record['lines'][0]
    request = [lot_line(line, '800', '0')]
    assert post(client, auth, record, request).status_code == 409
    approve_document(client, auth, 'WarehouseInbound', record['id'])
    received = post(client, auth, record, request)
    assert received.status_code == 200, received.text
    partial = received.json()
    assert partial['status'] == 'partially_posted' and partial['approval']['status'] == 'approved'
    assert (partial['lines'][0]['quantity'], partial['lines'][0]['received_quantity'],
            partial['lines'][0]['remaining_quantity']) == ('1000', '800', '200')
    assert post(client, auth, record, request).status_code == 409
    path = f'/api/v1/system/document-approvals/WarehouseInbound/{record["id"]}'
    state = client.get(path, headers=auth).json()
    assert state['business_status'] == 'partially_posted' and state['content_matches']
    assert not state['can_withdraw'] and not state['can_submit']
    assert state['events'][-1]['action'] == 'execute' and '部分入库' in state['events'][-1]['reason']
    assert client.post(path + '/withdraw', headers=auth, json={'version': state['version']}).status_code == 409
    assert client.post(f'/api/v1/warehouse-inbounds/{record["id"]}/cancel', headers=auth).status_code == 409
    with orm_session() as db:
        assert db.get(WarehouseInbound, record['id']).status == 'draft'
        assert balance(db, 1, materials[0]) == Decimal('800')

    # 直接证明已到的800可用于真实工单领料，不必等待剩余200。
    bom = client.post('/api/v1/boms', headers=auth, json={
        'product_material_id': materials[1], 'base_quantity': '1',
        'lines': [{'component_material_id': materials[0], 'quantity': '800'}]}).json()
    assert client.post(f'/api/v1/boms/{bom["id"]}/activate', headers=auth).status_code == 200
    order = client.post('/api/v1/work-orders', headers=auth, json={
        'bom_id': bom['id'], 'warehouse_id': 1, 'target_quantity': '1'}).json()
    approve_document(client, auth, 'WorkOrder', order['id'])
    assert client.post(f'/api/v1/work-orders/{order["id"]}/release', headers=auth).status_code == 200
    issue = client.post('/api/v1/material-issues', headers=auth, json={
        'work_order_id': order['id'], 'warehouse_id': 1,
        'lines': [{'work_order_line_id': order['lines'][0]['id'], 'quantity': '800'}]}).json()
    approve_document(client, auth, 'MaterialIssue', issue['id'])
    used = client.post(f'/api/v1/material-issues/{issue["id"]}/post', headers=auth, json={
        'lines': [{'material_issue_line_id': issue['lines'][0]['id'],
                   'lots': [{'lot_id': partial['lines'][0]['physical_lots'][0]['id'], 'quantity': '800'}]}]})
    assert used.status_code == 200, used.text
    complete = post(client, auth, record, [lot_line(line, '200', '800')])
    assert complete.status_code == 200, complete.text
    data = complete.json()
    assert data['status'] == 'posted' and data['approval']['status'] == 'executed'
    assert data['lines'][0]['remaining_quantity'] == '0'
    assert [lot['quantity'] for lot in data['lines'][0]['physical_lots']] == ['800', '200']
    assert len({lot['code'] for lot in data['lines'][0]['physical_lots']}) == 2
    with orm_session() as db:
        assert balance(db, 1, materials[0]) == Decimal('200')
    assert post(client, auth, record, [lot_line(line, '200', '800')]).status_code == 409


def test_partial_subset_excess_and_transaction_rollback(inbound_client):
    client, auth, materials = inbound_client
    record = create_inbound(client, auth, materials)
    first, second = record['lines']
    approve_document(client, auth, 'WarehouseInbound', record['id'])
    for lines in [[], [lot_line(first, '1002', '0')],
                  [lot_line(first, '800', '0'), lot_line(second, '1001', '0')],
                  [lot_line(first, '800', '0'), lot_line(first, '1', '0')],
                  [{**lot_line(first, '800', '0'), 'inbound_line_id': 99999}],
                  [lot_line(first, '800', '-1')],
                  [lot_line(first, '800', '0'), {'inbound_line_id': second['id'], 'lots': [{'quantity': '1'}]}]]:
        assert post(client, auth, record, lines).status_code == 422
    with orm_session() as db:
        assert list(db.scalars(select(StockMovement.id))) == []
        assert list(db.scalars(select(PhysicalLot.id))) == []
    response = post(client, auth, record, [lot_line(first, '800', '0')])
    assert response.status_code == 200, response.text
    assert response.json()['lines'][1]['received_quantity'] == '0'
    assert response.json()['lines'][1]['remaining_quantity'] == '1000'
    # 两个客户端读到相同800检查点，只有一个可再收100，另一个须刷新。
    next_request = [lot_line(first, '100', '800')]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: post(client, auth, record, next_request).status_code, range(2)))
    assert sorted(results) == [200, 409]
    assert post(client, auth, record, [lot_line(first, '101', '900')]).status_code == 422
    # 不带批次的旧确认路径只记剩余量，不能重复把已经收过的900记账。
    complete = client.post(f'/api/v1/warehouse-inbounds/{record["id"]}/post', headers=auth)
    assert complete.status_code == 200, complete.text
    assert complete.json()['status'] == 'posted'
    with orm_session() as db:
        assert balance(db, 1, materials[0]) == Decimal('1000')
        assert balance(db, 1, materials[1]) == Decimal('1000')
    approve_document(client, auth, 'WarehouseInbound', record['id'], intent='reverse', reason='整单更正')
    reversed_result = client.post(f'/api/v1/warehouse-inbounds/{record["id"]}/reverse', headers=auth, json={'reason': '整单更正'})
    assert reversed_result.status_code == 201, reversed_result.text
    with orm_session() as db:
        assert balance(db, 1, materials[0]) == 0 and balance(db, 1, materials[1]) == 0


def test_partial_reversal_only_reverses_actual_receipts_and_freezes_amount(inbound_client):
    client, auth, materials = inbound_client
    record = create_inbound(client, auth, materials)
    first = record['lines'][0]
    approve_document(client, auth, 'WarehouseInbound', record['id'])
    assert post(client, auth, record, [lot_line(first, '800', '0')]).status_code == 200
    approve_document(client, auth, 'WarehouseInbound', record['id'], intent='reverse', reason='实收更正')
    # 送审后又续收，旧冲销批准不能悄悄扣回多出的100。
    assert post(client, auth, record, [lot_line(first, '100', '800')]).status_code == 200
    path = f'/api/v1/system/document-approvals/WarehouseInbound/{record["id"]}'
    state = client.get(path, headers=auth, params={'intent': 'reverse'}).json()
    assert not state['content_matches']
    assert client.post(f'/api/v1/warehouse-inbounds/{record["id"]}/reverse', headers=auth,
                       json={'reason': '实收更正'}).status_code == 409
    assert client.post(path + '/withdraw', headers=auth,
                       json={'intent': 'reverse', 'version': state['version']}).status_code == 200
    approve_document(client, auth, 'WarehouseInbound', record['id'], intent='reverse', reason='实收更正')
    reversed_result = client.post(f'/api/v1/warehouse-inbounds/{record["id"]}/reverse', headers=auth,
                                 json={'reason': '实收更正'})
    assert reversed_result.status_code == 201, reversed_result.text
    with orm_session() as db:
        assert balance(db, 1, materials[0]) == 0 and balance(db, 1, materials[1]) == 0
    assert post(client, auth, record, [lot_line(first, '100', '900')]).status_code == 409
    # 冲销后的原批准记录仍留存，但业务余量已关闭，界面不能再提示续收。
    closed = client.get(path, headers=auth).json()
    assert closed['business_status'] == 'reversed' and not closed['can_withdraw']


@pytest.mark.parametrize('invalid_foreign_key', [False, True])
def test_v98_preserves_stock_history_or_rolls_back(monkeypatch, tmp_path, invalid_foreign_key):
    # 结构迁移测试保留真实旧唯一约束、外键、索引和不可修改触发器。
    import sqlite3
    from app.core.database import connection, migrate
    path = tmp_path / 'legacy-v97.db'
    monkeypatch.setenv('NEXORA_DB_PATH', str(path))
    db = sqlite3.connect(path)
    db.executescript('''
        CREATE TABLE stock_movements (
            id INTEGER PRIMARY KEY, source_type TEXT NOT NULL, source_line_id INTEGER NOT NULL,
            quantity TEXT NOT NULL, created_at TEXT NOT NULL,
            UNIQUE(source_type,source_line_id));
        CREATE INDEX legacy_stock_time ON stock_movements(created_at);
        CREATE TRIGGER legacy_no_stock_update BEFORE UPDATE ON stock_movements BEGIN
            SELECT RAISE(ABORT,'immutable'); END;
        CREATE TABLE physical_lot_allocations (
            id INTEGER PRIMARY KEY, movement_id INTEGER REFERENCES stock_movements(id), quantity TEXT);
        INSERT INTO stock_movements VALUES (11,'other_inbound',7,'800.000','2026-10-01');
        INSERT INTO physical_lot_allocations VALUES (31,11,'800.000');
        PRAGMA user_version=97;
    ''')
    if invalid_foreign_key:
        db.execute('INSERT INTO physical_lot_allocations VALUES (32,999,"1")')
    db.commit()
    original_rows = db.execute('SELECT * FROM stock_movements').fetchall()
    original_parts = db.execute('SELECT * FROM physical_lot_allocations').fetchall()
    db.close()
    if invalid_foreign_key:
        with pytest.raises(RuntimeError, match='外键检查失败'):
            migrate()
    else:
        migrate()
        migrate()
    with connection() as db:
        assert [tuple(row) for row in db.execute('SELECT * FROM stock_movements')] == original_rows
        assert [tuple(row) for row in db.execute('SELECT * FROM physical_lot_allocations')] == original_parts
        assert db.execute('PRAGMA user_version').fetchone()[0] == (97 if invalid_foreign_key else 101)
        assert db.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='legacy_stock_time'").fetchone()
        with pytest.raises(sqlite3.IntegrityError, match='immutable'):
            db.execute('UPDATE stock_movements SET quantity="1" WHERE id=11')
        if not invalid_foreign_key:
            db.execute("INSERT INTO stock_movements VALUES (12,'other_inbound',7,'200','2026-10-09')")
            db.execute("INSERT INTO stock_movements VALUES (13,'receipt',7,'100','2026-10-09')")
            with pytest.raises(sqlite3.IntegrityError):
                db.execute("INSERT INTO stock_movements VALUES (14,'receipt',7,'100','2026-10-09')")
