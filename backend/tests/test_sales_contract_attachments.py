"""销售合同附件按版本隔离，原件与撤销证据保留。"""

import base64
import hashlib
import sqlite3
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from app.core.database import connection, database_path, migrate
from app.core.models import Base, SalesOrderContractAttachment
from app.core.orm import orm_session
from app.main import app
from app.server import ensure_certificate
from app.service.backup import create_backup, restore_backup

PDF = b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n'
ROOT = '/api/v1'


def file_input(content=PDF):
    return {'file_name': '签收合同.pdf', 'content_base64': base64.b64encode(content).decode(),
        'reason': '客户签收扫描件'}


def login(client, name):
    response = client.post(f'{ROOT}/auth/login', json={
        'username': name, 'password': 'secure-pass-123'})
    assert response.status_code == 200, response.text
    return {'Authorization': f"Bearer {response.json()['token']}"}


@pytest.fixture
def seeded(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'contract-files.db'))
    with TestClient(app, client=('127.0.0.1', 12000)) as client:
        assert client.post(f'{ROOT}/setup/admin', json={
            'username': 'admin', 'password': 'secure-pass-123'}).status_code == 201
        admin = login(client, 'admin')
        for name, role in [('sellera', 'seller'), ('sellerb', 'seller'), ('warehouse', 'warehouse')]:
            assert client.post(f'{ROOT}/users', headers=admin, json={
                'username': name, 'password': 'secure-pass-123', 'roles': [role]}).status_code == 201
        seller = login(client, 'sellera')
        customer = client.post(f'{ROOT}/customers', headers=seller,
            json={'name': '合同附件客户'}).json()['id']
        material = client.post(f'{ROOT}/materials', headers=admin,
            json={'sku': 'CONTRACT-FILE', 'name': '合同附件物料', 'unit': '件'}).json()['id']
        orders = []
        revisions = []
        for index in (1, 2):
            order = client.post(f'{ROOT}/sales-orders', headers=seller, json={
                'customer_id': customer, 'reference': f'C-FILE-{index}',
                'lines': [{'material_id': material, 'quantity': '1', 'unit_price': '15'}]})
            assert order.status_code == 201, order.text
            order_id = order.json()['id']
            contract = client.post(f'{ROOT}/sales-orders/{order_id}/contract', headers=seller, json={
                'expected_version': 0, 'body': f'合同正文 {index}',
                'acceptance_reference': f'签收记录 {index}', 'reason': '首次登记'})
            assert contract.status_code == 200, contract.text
            orders.append(order_id)
            revisions.append(contract.json()['current']['id'])
        yield client, admin, seller, login(client, 'sellerb'), login(client, 'warehouse'), orders, revisions


def path(order_id, revision_id):
    return f'{ROOT}/sales-orders/{order_id}/contract/revisions/{revision_id}/attachments'


def test_attachment_history_preserves_revision_and_original(seeded):
    client, admin, seller, _, _, orders, revisions = seeded
    order_id, revision_id = orders[0], revisions[0]
    url = path(order_id, revision_id)
    before = client.get(f'{ROOT}/sales-orders/{order_id}/contract', headers=admin).json()
    assert client.get(url, headers=seller).json() == {
        'order_id': order_id, 'revision_id': revision_id, 'can_modify': True, 'items': []}
    uploaded = client.post(url, headers=seller, json=file_input())
    assert uploaded.status_code == 201, uploaded.text
    item = uploaded.json()
    assert item['revision_id'] == revision_id and item['sha256'] == hashlib.sha256(PDF).hexdigest()
    assert item['created_by_name'] == 'sellera' and item['reversal'] is None
    assert 'content' not in item and 'content_base64' not in item
    assert client.get(url, headers=admin).json()['items'] == [item]
    downloaded = client.get(f'{url}/{item["id"]}', headers=admin)
    assert downloaded.content == PDF and downloaded.headers['cache-control'] == 'no-store'
    assert downloaded.headers['x-nexora-sha256'] == item['sha256']
    assert client.post(url, headers=admin, json=file_input()).status_code == 409
    reversed_result = client.post(f'{url}/{item["id"]}/reverse', headers=admin,
        json={'reason': '文件页码不全'})
    assert reversed_result.status_code == 201
    assert reversed_result.json()['reversal']['reason'] == '文件页码不全'
    assert client.get(f'{url}/{item["id"]}', headers=admin).content == PDF
    assert client.post(f'{url}/{item["id"]}/reverse', headers=admin,
        json={'reason': '重复撤销'}).status_code == 409
    assert client.post(url, headers=seller, json=file_input()).status_code == 201
    after = client.get(f'{ROOT}/sales-orders/{order_id}/contract', headers=admin).json()
    assert after == before
    assert client.get(f'{ROOT}/sales-orders', headers=admin).json()[0]['total_amount'] == '15.00'
    with orm_session() as db:
        assert db.get(SalesOrderContractAttachment, item['id']).content == PDF


def test_attachment_scope_version_permission_and_terminal_lock(seeded):
    client, admin, seller, other_seller, warehouse, orders, revisions = seeded
    url = path(orders[0], revisions[0])
    assert client.get(url).status_code == 401
    assert client.get(url, headers=other_seller).status_code == 404
    assert client.post(url, headers=other_seller, json=file_input()).status_code == 404
    assert client.get(url, headers=warehouse).status_code == 200
    assert client.post(url, headers=warehouse, json=file_input()).status_code == 403
    assert client.get(path(orders[1], revisions[0]), headers=admin).status_code == 404
    assert client.post(path(orders[1], revisions[0]), headers=admin, json=file_input()).status_code == 404
    item = client.post(url, headers=admin, json=file_input()).json()
    assert client.get(f'{path(orders[1], revisions[1])}/{item["id"]}', headers=admin).status_code == 404
    assert client.post(f'{path(orders[1], revisions[1])}/{item["id"]}/reverse', headers=admin,
        json={'reason': '跨版本'}).status_code == 404
    newer = client.post(f'{ROOT}/sales-orders/{orders[0]}/contract', headers=admin, json={
        'expected_version': 1, 'body': '合同正文修订',
        'acceptance_reference': '补充签收', 'reason': '补充条款'})
    assert newer.status_code == 200
    newer_url = path(orders[0], newer.json()['current']['id'])
    assert client.get(f'{newer_url}/{item["id"]}', headers=admin).status_code == 404
    assert client.post(f'{newer_url}/{item["id"]}/reverse', headers=admin,
        json={'reason': '跨正文版本'}).status_code == 404
    assert client.post(f'{ROOT}/sales-orders/{orders[0]}/cancel', headers=admin).status_code == 200
    assert client.get(url, headers=admin).json()['can_modify'] is False
    assert client.get(f'{url}/{item["id"]}', headers=admin).content == PDF
    assert client.post(url, headers=admin, json=file_input(PDF+b'new')).status_code == 409
    assert client.post(f'{url}/{item["id"]}/reverse', headers=admin,
        json={'reason': '取消后'}).status_code == 409


def test_attachment_validates_input_limit_and_download_integrity(seeded):
    client, admin, *_rest, orders, revisions = seeded
    url = path(orders[0], revisions[0])
    for body in (file_input(b''), file_input(b'bad'),
            {**file_input(), 'file_name': '../bad.pdf'},
            {**file_input(), 'file_name': 'bad.exe'},
            {**file_input(), 'content_base64': '%%%='},
            {**file_input(), 'reason': ' '},
            file_input(PDF+b'x'*(5*1024*1024))):
        assert client.post(url, headers=admin, json=body).status_code == 422
    item = client.post(url, headers=admin, json=file_input()).json()
    for index in range(1, 10):
        assert client.post(url, headers=admin, json=file_input(PDF+str(index).encode())).status_code == 201
    assert client.post(url, headers=admin, json=file_input(PDF+b'overflow')).status_code == 409
    with orm_session(write=True) as db:
        db.get(SalesOrderContractAttachment, item['id']).content = b'tampered'
    assert client.get(f'{url}/{item["id"]}', headers=admin).status_code == 409


def test_online_backup_keeps_contract_original_and_reversal(seeded, tmp_path):
    client, admin, *_rest, orders, revisions = seeded
    url = path(orders[0], revisions[0])
    item = client.post(url, headers=admin, json=file_input()).json()
    assert client.post(f'{url}/{item["id"]}/reverse', headers=admin,
        json={'reason': '替换扫描件'}).status_code == 201
    data_dir = database_path().parent
    with connection() as db:
        instance_id = db.execute('SELECT id FROM server_identity').fetchone()[0]
    # 测试库使用临时名称，建立与服务入口同名的在线快照后验证归档。
    with sqlite3.connect(database_path()) as source, sqlite3.connect(data_dir / 'nexora.db') as target:
        source.backup(target)
    ensure_certificate(data_dir, instance_id)
    archive = tmp_path / 'contract-files.nexora-backup'
    create_backup(data_dir, archive)
    restored = tmp_path / 'restored'
    restore_backup(archive, restored)
    with sqlite3.connect(restored / 'nexora.db') as db:
        assert db.execute('SELECT content, sha256 FROM sales_order_contract_attachments WHERE id=?',
            (item['id'],)).fetchone() == (PDF, hashlib.sha256(PDF).hexdigest())
        assert db.execute('SELECT reason FROM sales_order_contract_attachment_reversals WHERE attachment_id=?',
            (item['id'],)).fetchone() == ('替换扫描件',)


def test_attachment_upgrade_rolls_back_and_keeps_contract(monkeypatch, tmp_path):
    import app.core.database as database

    path_db = tmp_path / 'upgrade.db'
    monkeypatch.setenv('NEXORA_DB_PATH', str(path_db))
    migrate()
    with sqlite3.connect(path_db) as db:
        db.execute('DROP TABLE sales_order_contract_attachment_reversals')
        db.execute('DROP TABLE sales_order_contract_attachments')
        db.execute('PRAGMA user_version = 81')
    original = database.connection

    @contextmanager
    def failing():
        with original() as db:
            db.set_authorizer(lambda operation, name, *_: sqlite3.SQLITE_DENY
                if operation == sqlite3.SQLITE_CREATE_TABLE
                and name == 'sales_order_contract_attachment_reversals' else sqlite3.SQLITE_OK)
            yield db

    monkeypatch.setattr(database, 'connection', failing)
    with pytest.raises(sqlite3.DatabaseError):
        migrate()
    monkeypatch.setattr(database, 'connection', original)
    with sqlite3.connect(path_db) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 81
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='sales_order_contract_attachments'").fetchone()
    migrate()
    migrate()
    with sqlite3.connect(path_db) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 87
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    assert len(Base.metadata.tables) == 185
