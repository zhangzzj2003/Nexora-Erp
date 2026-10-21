"""覆盖退货尾差、冲销重退、旧账升级及库存失败的事务边界。"""

from decimal import Decimal
import sqlite3

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from approval_test_helpers import approve_document
from app.core.database import migrate
from app.core.models import SalesReturnLine, StockMovement
from app.core.orm import orm_session
from app.finance.business_sources import business_sources
from app.main import app
from app.sales.return_amounts import allocate_return_amount


@pytest.fixture
def context(monkeypatch, tmp_path):
    path = tmp_path / 'return-amounts.db'
    monkeypatch.setenv('NEXORA_DB_PATH', str(path))
    with TestClient(app, client=('127.0.0.1', 12000)) as client:
        client.post('/api/v1/setup/admin', json={'username': 'admin', 'password': 'secure-pass-123'})
        token = client.post('/api/v1/auth/login', json={
            'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
        headers = {'Authorization': f'Bearer {token}'}

        def request(method, route, payload=None, expected=200):
            response = client.request(method, f'/api/v1/{route}', headers=headers, json=payload)
            assert response.status_code == expected, response.text
            return response.json()

        def execute(kind, route, identifier, *, intent='execute'):
            reason = '退货金额回归验证'
            approve_document(client, headers, kind, identifier, intent=intent, reason=reason)
            action = 'reverse' if intent == 'reverse' else ('confirm' if kind == 'SalesOrder' else 'post')
            return request('POST', f'{route}/{identifier}/{action}',
                           {'reason': reason} if intent == 'reverse' else None,
                           201 if intent == 'reverse' else 200)

        customer = request('POST', 'customers', {'name': '尾差客户'}, 201)['id']
        supplier = request('POST', 'suppliers', {'name': '尾差供应商'}, 201)['id']
        material = request('POST', 'materials', {'sku': 'ROUND', 'name': '尾差物料', 'unit': '件'}, 201)['id']

        def ship(quantity='2', price='0.335'):
            # 采购与出库均通过真实审批，以同时验证库存、应收和来源凭证计算。
            receipt = request('POST', 'receipts', {'supplier_id': supplier,
                'lines': [{'material_id': material, 'quantity': quantity}]}, 201)
            execute('Receipt', 'receipts', receipt['id'])
            order = request('POST', 'sales-orders', {'customer_id': customer,
                'lines': [{'material_id': material, 'quantity': quantity, 'unit_price': price}]}, 201)
            execute('SalesOrder', 'sales-orders', order['id'])
            shipment = request('POST', 'shipments', {'sales_order_id': order['id'], 'warehouse_id': 1,
                'lines': [{'material_id': material, 'quantity': quantity}]}, 201)
            return execute('Shipment', 'shipments', shipment['id'])

        def draft(shipment, quantity='1'):
            return request('POST', 'sales-returns', {'shipment_id': shipment['id'], 'warehouse_id': 1,
                'reason': '客户退回', 'lines': [{'shipment_line_id': shipment['lines'][0]['id'],
                                               'quantity': quantity}]}, 201)

        yield client, headers, path, request, execute, ship, draft


@pytest.mark.parametrize(('quantity', 'price', 'parts', 'expected'), [
    ('2', '0.335', ['1', '1'], ['0.34', '0.33']),
    ('3', '0.0049', ['1', '1', '1'], ['0.00', '0.01', '0.00']),
    ('4', '0.005', ['1', '1', '1', '1'], ['0.01', '0.00', '0.01', '0.00']),
    ('1', '0.335', ['0.333', '0.333', '0.334'], ['0.11', '0.11', '0.12']),
    ('2', '0', ['1', '1'], ['0.00', '0.00']),
])
def test_split_returns_clear_receivable(context, quantity, price, parts, expected):
    _, _, _, request, execute, ship, draft = context
    shipment = ship(quantity, price)
    for part, expected_amount in zip(parts, expected, strict=True):
        document = draft(shipment, part)
        posted = execute('SalesReturn', 'sales-returns', document['id'])
        assert posted['total_amount'] == expected_amount
        assert posted['lines'][0]['line_total'] == expected_amount
    report = request('GET', 'finance/receivables-payables')
    assert report['receivable_amount'] == '0.00'
    account = next(item for item in request('GET', 'finance/accounts') if item['kind'] == 'receivable')
    assert account['outstanding_amount'] == '0.00'


def fingerprints():
    with orm_session() as db:
        return {key: item['fingerprint'] for key, item in business_sources(db).items()}


def test_prepared_drafts_recalculate_once_and_reversal_preserves_amount(context):
    _, _, _, request, execute, ship, draft = context
    shipment = ship()
    first, second = draft(shipment), draft(shipment)
    # 两张草稿均预估 0.34，实际确认次序决定尾差分摊，不能固定草稿时的估算。
    assert first['total_amount'] == second['total_amount'] == '0.34'
    posted_second = execute('SalesReturn', 'sales-returns', second['id'])
    original = fingerprints()
    posted_first = execute('SalesReturn', 'sales-returns', first['id'])
    assert posted_second['total_amount'] == '0.34'
    assert posted_first['total_amount'] == '0.33'
    assert fingerprints()[f"sales_return:{second['id']}"] == original[f"sales_return:{second['id']}"]
    request('POST', f"sales-returns/{first['id']}/post", expected=409)
    execute('SalesReturn', 'sales-returns', second['id'], intent='reverse')
    report = request('GET', 'finance/receivables-payables')
    assert report['receivable_amount'] == '0.34'
    reversal = next(item for item in report['entries'] if item['source_type'] == 'sales_return_reversal')
    assert reversal['amount'] == '0.34'
    before_retry = fingerprints()
    retry = draft(shipment)
    assert execute('SalesReturn', 'sales-returns', retry['id'])['total_amount'] == '0.34'
    assert request('GET', 'finance/receivables-payables')['receivable_amount'] == '0.00'
    # 后续重退不改变任何已有业务凭证的经济指纹，包括已冲销单的原来源。
    assert all(fingerprints()[key] == value for key, value in before_retry.items())


def test_lot_failure_rolls_back_fixed_amount_and_allows_retry(context):
    client, headers, _, request, execute, ship, draft = context
    document = draft(ship())
    line_id = document['lines'][0]['id']
    approve_document(client, headers, 'SalesReturn', document['id'])
    request('POST', f"sales-returns/{document['id']}/post", {'lines': [
        {'return_line_id': line_id, 'lots': [{'quantity': '0.5'}]}]}, expected=422)
    with orm_session() as db:
        assert db.get(SalesReturnLine, line_id).settlement_amount is None
        assert db.scalar(select(StockMovement.id).where(StockMovement.source_type == 'sales_return',
                                                        StockMovement.source_id == document['id'])) is None
    state = request('GET', f"system/document-approvals/SalesReturn/{document['id']}")
    assert state['status'] == 'approved'
    assert request('POST', f"sales-returns/{document['id']}/post")['total_amount'] == '0.34'


def test_migration_keeps_legacy_amount_and_new_return_absorbs_residual(context):
    _, _, path, request, execute, ship, draft = context
    shipment = ship()
    first = execute('SalesReturn', 'sales-returns', draft(shipment)['id'])
    before = fingerprints()
    # 还原升级前结构，检验迁移只增列，不补算旧单或改写来源凭证。
    with sqlite3.connect(path) as db:
        db.execute('DROP TABLE sales_draft_changes')
        db.execute('ALTER TABLE sales_return_lines DROP COLUMN settlement_amount')
        db.execute('PRAGMA user_version = 109')
    migrate()
    migrate()
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 110
        assert db.execute('SELECT settlement_amount FROM sales_return_lines').fetchone()[0] is None
    assert fingerprints() == before
    second = execute('SalesReturn', 'sales-returns', draft(shipment)['id'])
    assert second['total_amount'] == '0.33'
    assert request('GET', 'finance/receivables-payables')['receivable_amount'] == '0.00'
    assert fingerprints()[f"sales_return:{first['id']}"] == before[f"sales_return:{first['id']}"]
    execute('SalesReturn', 'sales-returns', first['id'], intent='reverse')
    assert request('GET', 'finance/receivables-payables')['receivable_amount'] == '0.34'


def test_legacy_over_refund_is_preserved_and_blocks_new_post(context):
    _, _, _, request, execute, ship, draft = context
    shipment = ship('4', '0.005')
    for _ in range(3):
        execute('SalesReturn', 'sales-returns', draft(shipment)['id'])
    # 模拟旧版三次独立舍入：各退 0.01，已经超过原出库 0.02，不能静默改旧账。
    with orm_session(write=True) as db:
        db.execute(update(SalesReturnLine).values(settlement_amount=None))
    assert request('GET', 'finance/receivables-payables')['receivable_amount'] == '-0.01'
    pending = draft(shipment)
    client, headers = context[:2]
    approve_document(client, headers, 'SalesReturn', pending['id'])
    error = request('POST', f"sales-returns/{pending['id']}/post", expected=409)
    assert '历史退货金额已超过' in error['detail']
    with orm_session() as db:
        assert db.get(SalesReturnLine, pending['lines'][0]['id']).settlement_amount is None


def test_reversal_rounding_never_creates_negative_refund():
    # 冲销后净数量对应的理论金额可能小于留存金额，小额重退先分摊零，最终结清。
    assert allocate_return_amount(Decimal('2'), Decimal('0.015'), Decimal('0.001'),
                                  Decimal('0.335'), Decimal('0.01')) == Decimal('0.00')
    assert allocate_return_amount(Decimal('2'), Decimal('0.015'), Decimal('1.985'),
                                  Decimal('0.335'), Decimal('0.01')) == Decimal('0.66')
    with pytest.raises(HTTPException):
        allocate_return_amount(Decimal('2'), Decimal('2'), Decimal('1'), Decimal('0.335'), Decimal('0.67'))


def test_migration_failure_rolls_back_column_and_version(context, monkeypatch):
    from contextlib import contextmanager
    from app.core import database

    _, _, path, *_ = context
    with sqlite3.connect(path) as db:
        db.execute('DROP TABLE sales_draft_changes')
        db.execute('ALTER TABLE sales_return_lines DROP COLUMN settlement_amount')
        db.execute('PRAGMA user_version = 109')
    original = database.connection

    @contextmanager
    def failing_connection():
        with original() as db:
            # 注入版本更新失败，确认加列和版本号处于同一事务，重试不会留下半次升级。
            db.set_authorizer(lambda operation, name, value, *_: sqlite3.SQLITE_DENY
                if operation == sqlite3.SQLITE_PRAGMA and name == 'user_version' and value == '110'
                else sqlite3.SQLITE_OK)
            yield db

    monkeypatch.setattr(database, 'connection', failing_connection)
    with pytest.raises(sqlite3.DatabaseError):
        migrate()
    with original() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 109
        assert 'settlement_amount' not in {row[1] for row in db.execute('PRAGMA table_info(sales_return_lines)')}
        assert not list(db.execute('PRAGMA table_info(sales_draft_changes)'))
