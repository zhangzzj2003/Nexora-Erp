"""销售合同正文只追加版本，不能覆盖原单金额和保修证据。"""

import sqlite3
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from app.core.database import migrate
from app.core.models import Base
from app.main import app


def test_sales_contract_revisions_preserve_history_and_order_terms(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'contracts.db'))
    with TestClient(app, client=('127.0.0.1', 12000)) as client:
        base = '/api/v1'
        assert client.post(f'{base}/setup/admin', json={
            'username': 'admin', 'password': 'secure-pass-123'}).status_code == 201
        token = client.post(f'{base}/auth/login', json={
            'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
        admin = {'Authorization': f'Bearer {token}'}
        customer = client.post(f'{base}/customers', headers=admin,
                               json={'name': '合同客户'}).json()['id']
        material = client.post(f'{base}/materials', headers=admin,
                               json={'sku': 'CONTRACT', 'name': '合同物料', 'unit': '件'}).json()['id']
        order = client.post(f'{base}/sales-orders', headers=admin, json={
            'customer_id': customer, 'reference': 'C-1', 'lines': [{
                'material_id': material, 'quantity': '2', 'unit_price': '12.50',
                'warranty_days': 30, 'warranty_basis': '保修条款 1'}]})
        assert order.status_code == 201
        order_id = order.json()['id']
        url = f'{base}/sales-orders/{order_id}/contract'
        assert client.get(url).status_code == 401
        assert client.get(url, headers=admin).json() == {
            'sales_order_id': order_id, 'status': 'draft', 'version': 0,
            'current': None, 'history': []}

        first = {'expected_version': 0, 'body': ' 合同全文第一版 ',
                 'acceptance_reference': ' 客户签署 A ', 'reason': ' 首次登记 '}
        assert client.post(url, json=first).status_code == 401
        assert client.post(url, headers=admin, json={**first, 'body': '  '}).status_code == 422
        created = client.post(url, headers=admin, json=first)
        assert created.status_code == 200
        assert created.json()['version'] == 1
        assert created.json()['current']['body'] == '合同全文第一版'
        assert created.json()['current']['acceptance_reference'] == '客户签署 A'
        assert created.json()['current']['reason'] == '首次登记'
        assert created.json()['current']['created_by_name'] == 'admin'
        assert client.post(url, headers=admin, json=first).status_code == 409
        assert client.post(url, headers=admin, json={
            **first, 'expected_version': 1}).status_code == 409

        assert client.post(f'{base}/sales-orders/{order_id}/confirm', headers=admin).status_code == 200
        second = client.post(url, headers=admin, json={
            'expected_version': 1, 'body': '合同全文第二版',
            'acceptance_reference': '客户签署 B', 'reason': '补充交付约定'})
        assert second.status_code == 200
        assert [row['version'] for row in second.json()['history']] == [2, 1]
        assert [row['body'] for row in second.json()['history']] == ['合同全文第二版', '合同全文第一版']
        saved = client.get(f'{base}/sales-orders', headers=admin).json()[0]
        assert saved['total_amount'] == '25.00'
        assert saved['lines'][0]['warranty_days'] == 30
        assert saved['lines'][0]['warranty_basis'] == '保修条款 1'
        assert client.post(f'{base}/sales-orders/{order_id}/cancel', headers=admin).status_code == 200
        assert client.post(url, headers=admin, json={
            **first, 'expected_version': 2}).status_code == 409
        assert client.get(url, headers=admin).json()['version'] == 2


def test_sales_contract_uses_customer_scope_and_order_permissions(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'scope.db'))
    with TestClient(app, client=('127.0.0.1', 12000)) as client:
        base = '/api/v1'
        client.post(f'{base}/setup/admin', json={'username': 'admin', 'password': 'secure-pass-123'})

        def login(username):
            token = client.post(f'{base}/auth/login', json={
                'username': username, 'password': 'secure-pass-123'}).json()['token']
            return {'Authorization': f'Bearer {token}'}

        admin = login('admin')
        for name in ('sellera', 'sellerb'):
            assert client.post(f'{base}/users', headers=admin, json={
                'username': name, 'password': 'secure-pass-123', 'roles': ['seller']}).status_code == 201
        seller_a, seller_b = login('sellera'), login('sellerb')
        customer = client.post(f'{base}/customers', headers=seller_a,
                               json={'name': '私有客户'}).json()['id']
        material = client.post(f'{base}/materials', headers=admin,
                               json={'sku': 'PRIVATE', 'name': '物料', 'unit': '件'}).json()['id']
        order = client.post(f'{base}/sales-orders', headers=seller_a, json={
            'customer_id': customer, 'lines': [{
                'material_id': material, 'quantity': '1', 'unit_price': '1'}]}).json()['id']
        url = f'{base}/sales-orders/{order}/contract'
        assert client.get(url, headers=seller_b).status_code == 404
        assert client.post(url, headers=seller_b, json={
            'expected_version': 0, 'body': '正文',
            'acceptance_reference': '签收', 'reason': '登记'}).status_code == 404
        assert client.get(url, headers=admin).status_code == 200
        assert client.get(f'{base}/sales-orders/99999/contract', headers=admin).status_code == 404


def test_contract_migration_is_atomic_and_preserves_existing_orders(monkeypatch, tmp_path):
    import app.core.database as database

    path = tmp_path / 'upgrade.db'
    monkeypatch.setenv('NEXORA_DB_PATH', str(path))
    migrate()
    with sqlite3.connect(path) as db:
        db.execute('DROP TABLE sales_order_contract_revisions')
        db.execute('PRAGMA user_version = 80')
        before = db.execute('SELECT * FROM sales_orders').fetchall()

    original = database.connection

    @contextmanager
    def failing():
        with original() as db:
            db.set_authorizer(lambda operation, name, *_: sqlite3.SQLITE_DENY
                if operation == sqlite3.SQLITE_CREATE_TABLE
                and name == 'sales_order_contract_revisions' else sqlite3.SQLITE_OK)
            yield db

    monkeypatch.setattr(database, 'connection', failing)
    with pytest.raises(sqlite3.DatabaseError):
        migrate()
    monkeypatch.setattr(database, 'connection', original)
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 80
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='sales_order_contract_revisions'").fetchone()
    migrate()
    migrate()
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 83
        assert db.execute('SELECT * FROM sales_orders').fetchall() == before
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    assert len(Base.metadata.tables) == 181
