"""报价附件的客户隔离、原件校验、撤销及旧库升级。"""

import base64
import hashlib
import sqlite3

from sqlalchemy import select

from app.core.database import connection, database_path, migrate
from app.core.models import Base, CrmQuoteAttachment, CrmQuoteAttachmentReversal, Customer
from app.core.orm import orm_session
from app.server import ensure_certificate
from app.service.backup import create_backup, restore_backup
from test_crm import seeded, base_records, B, C

PDF = b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n'


def attachment(content=PDF, name='客户确认.pdf'):
    return {'file_name': name, 'content_base64': base64.b64encode(content).decode(),
        'reason': '客户沟通依据'}


def quote_id(seed, reference='Q-A'):
    client, admin, *_ = seed
    _, _, data = base_records(seed)
    result = client.post(C+'/quotes', headers=admin, json={**data, 'reference': reference})
    assert result.status_code == 201, result.text
    return result.json()['id']


def path(identifier):
    return C+f'/quotes/{identifier}/attachments'


def test_lifecycle_keeps_original_and_quote_version(seeded):
    client, admin, _, seller, *_ = seeded
    identifier = quote_id(seeded)
    before = client.get(C+f'/records/quote/{identifier}', headers=admin).json()
    base = path(identifier)
    uploaded = client.post(base, headers=seller, json=attachment())
    assert uploaded.status_code == 201, uploaded.text
    item = uploaded.json()
    assert item['quote_id'] == identifier and item['sha256'] == hashlib.sha256(PDF).hexdigest()
    assert item['created_by_name'] == 'seller' and item['reversal'] is None
    assert 'content' not in item and 'content_base64' not in item
    assert client.get(base, headers=admin).json()['items'] == [item]
    downloaded = client.get(base+f'/{item["id"]}', headers=seller)
    assert downloaded.content == PDF and downloaded.headers['cache-control'] == 'no-store'
    assert downloaded.headers['x-nexora-sha256'] == item['sha256']
    assert client.post(base, headers=admin, json=attachment()).status_code == 409
    reversed_result = client.post(base+f'/{item["id"]}/reverse', headers=admin,
        json={'reason': '文件有误'})
    assert reversed_result.status_code == 201 and reversed_result.json()['reversal']['reason'] == '文件有误'
    assert client.get(base+f'/{item["id"]}', headers=admin).content == PDF
    assert client.post(base+f'/{item["id"]}/reverse', headers=admin,
        json={'reason': '重复'}).status_code == 409
    assert client.post(base, headers=admin, json=attachment()).status_code == 201
    after = client.get(C+f'/records/quote/{identifier}', headers=admin).json()
    assert after['version'] == before['version'] and after['total_amount'] == before['total_amount']
    with orm_session() as db:
        assert db.get(CrmQuoteAttachment, item['id']).content == PDF
        assert db.scalar(select(CrmQuoteAttachmentReversal.id).where(
            CrmQuoteAttachmentReversal.attachment_id == item['id'])) is not None


def test_input_limit_and_cross_quote_isolation(seeded):
    client, admin, *_ = seeded
    first = quote_id(seeded)
    second = quote_id(seeded, 'Q-B')
    base = path(first)
    for body in (attachment(b'', 'empty.pdf'), attachment(b'bad'),
            attachment(PDF, '../bad.pdf'), attachment(PDF, 'bad.exe'),
            {**attachment(), 'content_base64': '%%%='},
            {**attachment(), 'reason': ' '}, attachment(PDF+b'x'*(5*1024*1024))):
        assert client.post(base, headers=admin, json=body).status_code == 422
    item = client.post(base, headers=admin, json=attachment()).json()
    assert client.get(path(second)+f'/{item["id"]}', headers=admin).status_code == 404
    assert client.post(path(second)+f'/{item["id"]}/reverse', headers=admin,
        json={'reason': '跨单'}).status_code == 404
    for index in range(1, 10):
        assert client.post(base, headers=admin, json=attachment(PDF+str(index).encode())).status_code == 201
    assert client.post(base, headers=admin, json=attachment(PDF+b'overflow')).status_code == 409


def test_customer_scope_permissions_and_terminal_lock(seeded):
    client, admin, _, seller, viewer, customer, *_ = seeded
    identifier = quote_id(seeded)
    base = path(identifier)
    assert client.get(base, headers=viewer).status_code == 403
    assert client.post(base, headers=viewer, json=attachment()).status_code == 403
    with orm_session(write=True) as db:
        db.get(Customer, customer).owner_id = 1
    assert client.get(base, headers=seller).status_code == 404
    assert client.post(base, headers=seller, json=attachment()).status_code == 404
    item = client.post(base, headers=admin, json=attachment()).json()
    assert client.get(base+f'/{item["id"]}', headers=seller).status_code == 404
    assert client.post(base+f'/{item["id"]}/reverse', headers=seller,
        json={'reason': '误传'}).status_code == 404
    quote = client.get(C+f'/records/quote/{identifier}', headers=admin).json()
    cancelled = client.post(C+f'/quotes/{identifier}/cancel', headers=admin,
        json={'version': quote['version'], 'reason': '作废报价'})
    assert cancelled.status_code == 200, cancelled.text
    assert client.get(base, headers=admin).json()['can_modify'] is False
    assert client.post(base, headers=admin, json=attachment(PDF+b'late')).status_code == 409
    assert client.post(base+f'/{item["id"]}/reverse', headers=admin,
        json={'reason': '终态后'}).status_code == 409
    assert client.get(base+f'/{item["id"]}', headers=admin).content == PDF


def test_v74_upgrade_is_idempotent_and_keeps_quote(seeded):
    client, admin, *_ = seeded
    identifier = quote_id(seeded)
    with connection() as db:
        db.execute('DROP TABLE crm_record_attachment_reversals')
        db.execute('DROP TABLE crm_record_attachments')
        db.execute("DELETE FROM role_permissions WHERE permission_code='crm.attachment'")
        db.execute("DELETE FROM permissions WHERE code='crm.attachment'")
        db.execute('DROP TABLE crm_quote_attachment_reversals')
        db.execute('DROP TABLE crm_quote_attachments')
        db.execute("DELETE FROM role_permissions WHERE permission_code='crm_quote.attachment'")
        db.execute("DELETE FROM permissions WHERE code='crm_quote.attachment'")
        db.execute('PRAGMA user_version=74')
    migrate()
    migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 76
        assert db.execute('SELECT status FROM crm_quotes WHERE id=?', (identifier,)).fetchone()[0] == 'draft'
        assert db.execute("SELECT COUNT(*) FROM role_permissions WHERE permission_code='crm_quote.attachment'").fetchone()[0] == 2
    assert len(Base.metadata.tables) == 174
    assert client.post(path(identifier), headers=admin, json=attachment()).status_code == 201


def test_online_backup_keeps_quote_attachment_and_reversal(seeded, tmp_path):
    client, admin, *_ = seeded
    identifier = quote_id(seeded)
    base = path(identifier)
    item = client.post(base, headers=admin, json=attachment()).json()
    assert client.post(base+f'/{item["id"]}/reverse', headers=admin,
        json={'reason': '替换客户签收件'}).status_code == 201
    data_dir = database_path().parent
    with connection() as db:
        instance_id = db.execute('SELECT id FROM server_identity').fetchone()[0]
    # 测试库使用临时名称，建立与服务入口同名的在线快照后验证归档。
    with sqlite3.connect(database_path()) as source, sqlite3.connect(data_dir / 'nexora.db') as target:
        source.backup(target)
    ensure_certificate(data_dir, instance_id)
    archive = tmp_path / 'crm-quote.nexora-backup'
    create_backup(data_dir, archive)
    restored = tmp_path / 'restored'
    restore_backup(archive, restored)
    with sqlite3.connect(restored / 'nexora.db') as db:
        assert db.execute('SELECT content, sha256 FROM crm_quote_attachments WHERE id=?',
            (item['id'],)).fetchone() == (PDF, hashlib.sha256(PDF).hexdigest())
        assert db.execute('SELECT reason FROM crm_quote_attachment_reversals WHERE attachment_id=?',
            (item['id'],)).fetchone() == ('替换客户签收件',)
