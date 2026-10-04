"""凭证附件的内容校验、权限、期间锁定与追加式撤销。"""

import base64
import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import select

from app.core.database import connection, database_path, migrate
from app.core.models import AccountingPeriod, Base, JournalAttachment, JournalAttachmentReversal
from app.core.orm import orm_session
from app.server import ensure_certificate
from app.service.backup import create_backup, restore_backup
from test_ledger_foundation import ledger
from test_journals import journals, create, action, PATH

PDF = b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n'


def payload(content=PDF, file_name='票据.pdf'):
    return dict(file_name=file_name, content_base64=base64.b64encode(content).decode(), reason='补录原始凭据')


def path(journal_id):
    return f'{PATH}/{journal_id}/attachments'


def test_upload_download_reversal_and_reupload(journals):
    client, _ = journals
    journal = create(client)
    base = path(journal['id'])
    response = client.post(base, json=payload())
    assert response.status_code == 201, response.text
    item = response.json()
    assert item['file_name'] == '票据.pdf' and item['byte_count'] == len(PDF)
    assert item['sha256'] == hashlib.sha256(PDF).hexdigest()
    assert item['created_by_name'] and item['reversal'] is None
    assert 'content' not in item and 'content_base64' not in item
    listed = client.get(base).json()
    assert listed['can_modify'] and listed['items'] == [item]
    download = client.get(f'{base}/{item["id"]}')
    assert download.status_code == 200 and download.content == PDF
    assert download.headers['content-type'].startswith('application/octet-stream')
    assert download.headers['x-nexora-sha256'] == item['sha256']
    assert download.headers['x-nexora-file-extension'] == '.pdf'
    assert client.post(base, json=payload()).status_code == 409
    reverse = client.post(f'{base}/{item["id"]}/reverse', json={'reason': '票据版本错误'})
    assert reverse.status_code == 201, reverse.text
    assert reverse.json()['reversal']['reason'] == '票据版本错误'
    assert client.post(f'{base}/{item["id"]}/reverse', json={'reason': '重复'}).status_code == 409
    assert client.get(f'{base}/{item["id"]}').content == PDF
    replacement = client.post(base, json=payload())
    assert replacement.status_code == 201
    assert replacement.json()['id'] != item['id']
    with orm_session() as db:
        assert db.get(JournalAttachment, item['id']).content == PDF
        assert db.scalar(select(JournalAttachmentReversal.id).where(
            JournalAttachmentReversal.attachment_id == item['id'])) is not None


@pytest.mark.parametrize('value,file_name', [
    (b'', '票据.pdf'), (b'not pdf', '票据.pdf'), (PDF, '../票据.pdf'),
    (PDF, '票据.exe'), (PDF, '票据.png'), (b'\xff\xd8\xffnot-jpeg', '票据.jpg'),
])
def test_invalid_content_and_name_rejected(journals, value, file_name):
    client, _ = journals
    journal = create(client)
    response = client.post(path(journal['id']), json=payload(value, file_name))
    assert response.status_code == 422, response.text
    assert client.get(path(journal['id'])).json()['items'] == []


def test_malformed_base64_size_and_missing_record(journals):
    client, _ = journals
    journal = create(client)
    base = path(journal['id'])
    for data in [
        {**payload(), 'content_base64': '%%%='},
        {**payload(), 'content_base64': base64.b64encode(PDF + b'x' * (5 * 1024 * 1024)).decode()},
        {**payload(), 'reason': ' '},
    ]:
        assert client.post(base, json=data).status_code == 422
    assert client.get(path(9999)).status_code == 404
    assert client.post(path(9999), json=payload()).status_code == 404
    assert client.get(f'{base}/9999').status_code == 404
    assert client.post(f'{base}/9999/reverse', json={'reason': '查无'}).status_code == 404


def test_period_and_cancelled_journal_are_immutable(journals):
    client, reviewer = journals
    draft = create(client)
    cancelled = action(client, draft, 'cancel')
    assert client.get(path(cancelled['id'])).json()['can_modify'] is False
    assert client.post(path(cancelled['id']), json=payload()).status_code == 409
    posted_journal = action(client, create(client, 'J002'), 'submit')
    posted_journal = action(client, posted_journal, 'approve', reviewer)
    posted_journal = action(client, posted_journal, 'post')
    base = path(posted_journal['id'])
    attachment = client.post(base, json=payload()).json()
    with orm_session(write=True) as db:
        db.get(AccountingPeriod, posted_journal['period_id']).status = 'closed'
    assert client.get(base).json()['can_modify'] is False
    assert client.get(f'{base}/{attachment["id"]}').content == PDF
    assert client.post(base, json=payload(PDF + b'\n')).status_code == 409
    assert client.post(f'{base}/{attachment["id"]}/reverse', json={'reason': '结账后'}).status_code == 409
    assert client.get(base).json()['items'][0]['reversal'] is None


def test_permissions_and_cross_journal_scope(journals):
    client, _ = journals
    first = create(client)
    second = create(client, 'J002')
    item = client.post(path(first['id']), json=payload()).json()
    response = client.post('/api/v1/roles', json={
        'code': 'attachment_observer', 'label': '附件观察', 'permissions': ['journal.view']})
    assert response.status_code == 201, response.text
    response = client.post('/api/v1/users', json={
        'username': 'attachment_observer', 'password': 'permission-pass-123',
        'roles': ['attachment_observer']})
    assert response.status_code == 201, response.text
    token = client.post('/api/v1/auth/login', json={
        'username': 'attachment_observer', 'password': 'permission-pass-123'}).json()['token']
    viewer = {'Authorization': 'Bearer ' + token}
    assert client.get(path(first['id']), headers=viewer).status_code == 200
    assert client.get(f'{path(first["id"])}/{item["id"]}', headers=viewer).content == PDF
    assert client.post(path(first['id']), json=payload(), headers=viewer).status_code == 403
    assert client.post(f'{path(first["id"])}/{item["id"]}/reverse',
        json={'reason': '越权'}, headers=viewer).status_code == 403
    assert client.post('/api/v1/roles', json={
        'code': 'attachment_only', 'label': '仅附件',
        'permissions': ['journal.attachment']}).status_code == 201
    assert client.post('/api/v1/users', json={
        'username': 'attachment_only', 'password': 'permission-pass-123',
        'roles': ['attachment_only']}).status_code == 201
    token = client.post('/api/v1/auth/login', json={
        'username': 'attachment_only', 'password': 'permission-pass-123'}).json()['token']
    writer = {'Authorization': 'Bearer ' + token}
    assert client.post(path(first['id']), json=payload(PDF + b'\n'), headers=writer).status_code == 403
    assert client.post(f'{path(first["id"])}/{item["id"]}/reverse',
        json={'reason': '越权'}, headers=writer).status_code == 403
    assert client.get(f'{path(second["id"])}/{item["id"]}').status_code == 404
    assert client.post(f'{path(second["id"])}/{item["id"]}/reverse',
        json={'reason': '跨凭证'}).status_code == 404


def test_concurrent_duplicate_upload_only_one_wins(journals):
    client, _ = journals
    journal = create(client)
    base = path(journal['id'])
    gate = Barrier(2)

    def upload(_):
        gate.wait()
        return client.post(base, json=payload()).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(upload, range(2))) == [201, 409]
    assert len(client.get(base).json()['items']) == 1


def test_active_attachment_limit_releases_only_after_audited_reversal(journals):
    client, _ = journals
    journal = create(client)
    base = path(journal['id'])
    ids = []
    for index in range(10):
        response = client.post(base, json=payload(PDF + str(index).encode()))
        assert response.status_code == 201, response.text
        ids.append(response.json()['id'])
    assert client.post(base, json=payload(PDF + b'overflow')).status_code == 409
    assert client.post(f'{base}/{ids[0]}/reverse', json={'reason': '改用新票据'}).status_code == 201
    assert client.post(base, json=payload(PDF + b'overflow')).status_code == 201
    assert len(client.get(base).json()['items']) == 11


def test_upgrade_from_72_preserves_journal_and_adds_static_models(journals):
    client, _ = journals
    journal = create(client)
    with connection() as db:
        db.execute('DROP TABLE crm_record_attachment_reversals')
        db.execute('DROP TABLE crm_record_attachments')
        db.execute("DELETE FROM role_permissions WHERE permission_code='crm.attachment'")
        db.execute("DELETE FROM permissions WHERE code='crm.attachment'")
        db.execute('DROP TABLE crm_quote_attachment_reversals')
        db.execute('DROP TABLE crm_quote_attachments')
        db.execute("DELETE FROM role_permissions WHERE permission_code='crm_quote.attachment'")
        db.execute("DELETE FROM permissions WHERE code='crm_quote.attachment'")
        db.execute('DROP TABLE after_sales_attachment_reversals')
        db.execute('DROP TABLE after_sales_attachments')
        db.execute("DELETE FROM role_permissions WHERE permission_code='after_sales.attachment'")
        db.execute("DELETE FROM permissions WHERE code='after_sales.attachment'")
        db.execute('DROP TABLE journal_attachment_reversals')
        db.execute('DROP TABLE journal_attachments')
        db.execute("DELETE FROM role_permissions WHERE permission_code='journal.attachment'")
        db.execute("DELETE FROM permissions WHERE code='journal.attachment'")
        db.execute('PRAGMA user_version = 72')
    migrate()
    migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 76
        assert db.execute('SELECT reference FROM journals WHERE id=?', (journal['id'],)).fetchone()[0] == 'J001'
        assert db.execute("SELECT count(*) FROM role_permissions WHERE permission_code='journal.attachment'").fetchone()[0] == 2
    assert len(Base.metadata.tables) == 174
    assert client.post(path(journal['id']), json=payload()).status_code == 201


def test_online_backup_restores_attachment_bytes_and_audit(journals, tmp_path):
    client, _ = journals
    journal = create(client)
    item = client.post(path(journal['id']), json=payload()).json()
    assert client.post(f'{path(journal["id"])}/{item["id"]}/reverse',
        json={'reason': '备份前更正'}).status_code == 201
    data_dir = database_path().parent
    with connection() as db:
        instance_id = db.execute('SELECT id FROM server_identity').fetchone()[0]
    # 测试夹具的数据库文件名不同于正式服务入口，先生成同内容的在线快照。
    with sqlite3.connect(database_path()) as source, sqlite3.connect(data_dir / 'nexora.db') as target:
        source.backup(target)
    ensure_certificate(data_dir, instance_id)
    archive = tmp_path / 'attachment.nexora-backup'
    create_backup(data_dir, archive)
    restored = tmp_path / 'restored'
    restore_backup(archive, restored)
    with sqlite3.connect(restored / 'nexora.db') as db:
        saved = db.execute('SELECT content,sha256 FROM journal_attachments WHERE id=?',
            (item['id'],)).fetchone()
        assert saved == (PDF, hashlib.sha256(PDF).hexdigest())
        assert db.execute('SELECT reason FROM journal_attachment_reversals WHERE attachment_id=?',
            (item['id'],)).fetchone() == ('备份前更正',)
