"""余量终止保留库存财务事实，并在原事务拒绝过期实绩及未解决的上下游承诺。"""

from concurrent.futures import ThreadPoolExecutor
import re
import sqlite3

import pytest
from sqlalchemy import select

from approval_test_helpers import approve_document
from app.core.database import migrate
from app.core.models import SalesOrder
from app.core.orm import orm_session
from app.production.mrp_sources import collect
from test_sales_return_amounts import context, fingerprints
from test_mrp import seeded, payload as mrp_payload
from test_production_plans import release_input


def close_input(order):
    return {'reason': '客户确认取消剩余交付', 'expected_lines': [
        {'line_id': row['id'], 'shipped_quantity': row['shipped_quantity']} for row in order['lines']]}


def partial(context):
    _, _, _, request, execute, ship, _ = context
    full = ship('4')
    execute('Shipment', 'shipments', full['id'], intent='reverse')
    draft = request('POST', 'shipments', {'sales_order_id': full['sales_order_id'], 'warehouse_id': 1,
        'lines': [{'material_id': full['lines'][0]['material_id'], 'quantity': '1'}]}, 201)
    shipment = execute('Shipment', 'shipments', draft['id'])
    order = next(row for row in request('GET', 'sales-orders') if row['id'] == full['sales_order_id'])
    return order, shipment


def test_closure_preserves_money_and_history_even_after_return_and_reversal(context):
    _, _, _, request, execute, _, return_draft = context
    order, shipment = partial(context)
    before = fingerprints()
    finance = request('GET', 'finance/receivables-payables')
    stock = request('GET', 'stock')
    saved = request('POST', f"sales-orders/{order['id']}/close", close_input(order))
    assert saved['status'] == 'closed' and saved['lines'][0]['remaining_quantity'] == '0'
    assert saved['total_amount'] == order['total_amount']
    assert saved['closure']['lines'][0]['closed_quantity'] == '3'
    assert saved['closure']['created_by_name'] == 'admin'
    assert 'closure_json' not in saved
    assert fingerprints() == before
    assert request('GET', 'finance/receivables-payables') == finance
    assert request('GET', 'stock') == stock
    with orm_session() as db:
        assert not collect(db)['demands']
    request('POST', 'shipments', {'sales_order_id': order['id'], 'warehouse_id': 1,
        'lines': [{'material_id': order['lines'][0]['material_id'], 'quantity': '1'}]}, 409)
    returned = execute('SalesReturn', 'sales-returns', return_draft(shipment)['id'])
    execute('SalesReturn', 'sales-returns', returned['id'], intent='reverse')
    execute('Shipment', 'shipments', shipment['id'], intent='reverse')
    current = next(row for row in request('GET', 'sales-orders') if row['id'] == order['id'])
    assert current['status'] == 'closed' and current['lines'][0]['remaining_quantity'] == '0'
    assert current['lines'][0]['shipped_quantity'] == '0'
    assert current['closure'] == saved['closure']
    request('POST', f"sales-orders/{order['id']}/cancel", expected=409)
    # 持久化证据也禁止被其他 ORM 路径误改，不能只依赖按钮隐藏。
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError, match='终止证据不可修改'):
        with orm_session(write=True) as db:
            db.get(SalesOrder, order['id']).closure_json = None


def test_closure_rejects_stale_snapshot_pending_shipment_and_duplicate_commit(context):
    client, headers, _, request, _, *_ = context
    order, _ = partial(context)
    path = f"sales-orders/{order['id']}/close"
    request('POST', path, {**close_input(order), 'reason': ' '}, 422)
    request('POST', path, {**close_input(order), 'expected_lines': [
        {'line_id': order['lines'][0]['id'], 'shipped_quantity': '0'}]}, 409)
    shipment = request('POST', 'shipments', {'sales_order_id': order['id'], 'warehouse_id': 1,
        'lines': [{'material_id': order['lines'][0]['material_id'], 'quantity': '1'}]}, 201)
    assert '出库草稿' in request('POST', path, close_input(order), 409)['detail']
    request('POST', f"shipments/{shipment['id']}/cancel")
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post('/api/v1/' + path,
            headers=headers, json=close_input(order)).status_code, range(2)))
    assert sorted(responses) == [200, 409]


def test_closure_enforces_customer_scope_and_permission(context):
    client, _, _, request, *_ = context
    order, _ = partial(context)
    for username, role, expected in [('other_seller', 'seller', 404), ('viewer', 'viewer', 403)]:
        request('POST', 'users', {'username': username, 'password': 'secure-pass-123', 'roles': [role]}, 201)
        token = client.post('/api/v1/auth/login', json={'username': username, 'password': 'secure-pass-123'}).json()['token']
        response = client.post(f"/api/v1/sales-orders/{order['id']}/close",
            headers={'Authorization': f'Bearer {token}'}, json=close_input(order))
        assert response.status_code == expected, response.text


def test_closure_failure_rolls_back_status_and_evidence(context, monkeypatch):
    _, _, _, request, *_ = context
    order, _ = partial(context)
    from app.finance import business_journals
    def fail(_):
        raise RuntimeError('模拟事务提交失败')
    monkeypatch.setattr(business_journals, 'validate_posted_sources', fail)
    with pytest.raises(RuntimeError, match='模拟事务'):
        request('POST', f"sales-orders/{order['id']}/close", close_input(order))
    with orm_session() as db:
        row = db.get(SalesOrder, order['id'])
        assert row.status == 'partially_shipped' and row.closure_json is None


@pytest.fixture
def connected(seeded):
    client, admin, _, _, _, materials, supplier = seeded
    def request(method, route, body=None, expected=200):
        response = client.request(method, '/api/v1/' + route, headers=admin, json=body)
        assert response.status_code == expected, response.text
        return response.json()
    def execute(kind, route, identifier, action='post'):
        approve_document(client, admin, kind, identifier)
        return request('POST', f'{route}/{identifier}/{action}')
    receipt = request('POST', 'receipts', {'supplier_id': supplier, 'lines': [
        {'material_id': materials[0], 'quantity': '1'}]}, 201)
    execute('Receipt', 'receipts', receipt['id'])
    customer = request('POST', 'customers', {'name': '终止客户'}, 201)
    order = request('POST', 'sales-orders', {'customer_id': customer['id'], 'lines': [
        {'material_id': materials[0], 'quantity': '10', 'unit_price': '1'}]}, 201)
    execute('SalesOrder', 'sales-orders', order['id'], 'confirm')
    shipment = request('POST', 'shipments', {'sales_order_id': order['id'], 'warehouse_id': 1,
        'lines': [{'material_id': materials[0], 'quantity': '1'}]}, 201)
    execute('Shipment', 'shipments', shipment['id'])
    order = request('GET', 'sales-orders')[0]
    return request, order, client, admin, materials


def test_closure_checks_cancelled_production_plan_still_has_live_work_order(connected):
    request, order, client, admin, _ = connected
    bom = request('GET', 'production/plans/options')['boms'][0]
    plan = request('POST', 'production/plans', {'reference': '交付安排', 'reason': '核对订单', 'note': '',
        'lines': [{'bom_id': bom['id'], 'warehouse_id': 1, 'quantity': '2',
        'sales_order_line_id': order['lines'][0]['id'], 'start_date': '2030-01-05', 'end_date': '2030-01-10'}]}, 201)
    path = f"sales-orders/{order['id']}/close"
    assert '生产计划' in request('POST', path, close_input(order), 409)['detail']
    approve_document(client, admin, 'ProductionPlan', plan['id'])
    plan = request('GET', f"production/plans/{plan['id']}")
    plan = request('POST', f"production/plans/{plan['id']}/release", release_input(plan, '1'), 201)
    work_id = plan['releases'][0]['work_order_id']
    request('POST', f"production/plans/{plan['id']}/cancel", {'version': plan['version'], 'reason': '停止余量'})
    assert '未完工工单' in request('POST', path, close_input(order), 409)['detail']
    request('POST', f'work-orders/{work_id}/cancel')
    assert request('POST', path, close_input(order))['status'] == 'closed'
    assert request('GET', 'production/plans/options')['sales_lines'] == []


def test_closure_checks_mrp_purchase_commitment_and_invalidates_old_calculation(connected):
    request, order, client, admin, materials = connected
    body = mrp_payload(client, admin, materials)
    body['manual_demands'] = []
    plan = request('POST', 'production/mrp/plans', body, 201)
    approve_document(client, admin, 'MrpPlan', plan['id'], reason='核对订单余量与采购建议')
    plan = request('GET', f"production/mrp/plans/{plan['id']}")
    buy = next(row for row in plan['snapshot']['suggestions'] if row['supply_mode'] == 'buy')
    conversion = request('POST', f"production/mrp/plans/{plan['id']}/convert", {
        'version': plan['version'], 'suggestion_key': buy['key'], 'reason': '采购缺料', 'reference': ''}, 201)
    path = f"sales-orders/{order['id']}/close"
    assert '物料计划' in request('POST', path, close_input(order), 409)['detail']
    request_id = conversion['purchase_request_id']
    approve_document(client, admin, 'PurchaseRequest', request_id, reason='核对采购数量')
    source = next(row for row in request('GET', 'purchase-requests') if row['id'] == request_id)
    purchase = request('POST', 'purchase-orders', {'supplier_id': request('GET', 'suppliers')[0]['id'],
        'purchase_request_id': request_id, 'lines': [{'purchase_request_line_id': row['id'],
        'material_id': row['material_id'], 'quantity': row['quantity'], 'unit_price': '1'} for row in source['lines']]}, 201)
    # 申请余额已转完仍须追到采购订单，不能误把未收货采购视作已解决。
    assert '物料计划' in request('POST', path, close_input(order), 409)['detail']
    request('POST', f"purchase-orders/{purchase['id']}/cancel")
    request('POST', f"purchase-requests/{conversion['purchase_request_id']}/cancel")
    request('POST', path, close_input(order))
    checked = request('GET', f"production/mrp/plans/{plan['id']}/check")
    assert checked['matched'] is False


def test_closure_migration_preserves_original_orders(context):
    _, _, path, request, *_ = context
    order, _ = partial(context)
    # 真正还原 v109 的订单列，验证升级不会补造终止历史。
    restore_v109_orders(path)
    migrate()
    upgraded = next(row for row in request('GET', 'sales-orders') if row['id'] == order['id'])
    assert upgraded == order
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE name='sales_orders_document_no'").fetchone()[0] == 1
    assert request('POST', f"sales-orders/{order['id']}/close", close_input(upgraded))['status'] == 'closed'


def restore_v109_orders(path):
    # 测试只回退表结构，原数据、编号索引和触发器逐项保留，用于真实升级及失败回滚验证。
    with sqlite3.connect(path) as db:
        db.execute('DROP TRIGGER sales_order_closure_immutable')
        db.execute('ALTER TABLE sales_orders DROP COLUMN closure_json')
        sql = db.execute("SELECT sql FROM sqlite_master WHERE name='sales_orders'").fetchone()[0]
        objects = [row[0] for row in db.execute("SELECT sql FROM sqlite_master WHERE tbl_name='sales_orders' AND type IN ('index','trigger') AND sql IS NOT NULL")]
        sql = re.sub(r'CREATE TABLE\s+"?sales_orders"?', 'CREATE TABLE sales_orders_legacy', sql, count=1)
        db.execute(sql.replace(", 'closed'", ''))
        db.execute('INSERT INTO sales_orders_legacy SELECT * FROM sales_orders')
        db.execute('DROP TABLE sales_orders')
        db.execute('ALTER TABLE sales_orders_legacy RENAME TO sales_orders')
        for statement in objects:
            db.execute(statement)
        db.execute('PRAGMA user_version = 109')


def test_closure_table_rebuild_failure_preserves_legacy_data(context, monkeypatch):
    from contextlib import contextmanager
    from app.core import database
    _, _, path, _, *_ = context
    order, _ = partial(context)
    restore_v109_orders(path)
    original = database.connection
    @contextmanager
    def failed_connection():
        with original() as db:
            db.set_authorizer(lambda operation, name, value, *_: sqlite3.SQLITE_DENY
                if operation == sqlite3.SQLITE_PRAGMA and name == 'user_version' and value == '110' else sqlite3.SQLITE_OK)
            yield db
    monkeypatch.setattr(database, 'connection', failed_connection)
    with pytest.raises(sqlite3.DatabaseError):
        migrate()
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 109
        assert 'closure_json' not in {row[1] for row in db.execute('PRAGMA table_info(sales_orders)')}
        assert "'closed'" not in db.execute("SELECT sql FROM sqlite_master WHERE name='sales_orders'").fetchone()[0]
        assert db.execute('SELECT status FROM sales_orders WHERE id=?', (order['id'],)).fetchone()[0] == 'partially_shipped'
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
