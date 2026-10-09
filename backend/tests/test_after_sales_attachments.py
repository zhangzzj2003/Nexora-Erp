"""售后附件的客户隔离、不可变原文、撤销及升级验证。"""

import base64
import hashlib
import sqlite3

from sqlalchemy import select

from app.core.database import connection, database_path, migrate
from app.core.models import AfterSalesAttachment, AfterSalesAttachmentReversal, Customer
from app.core.orm import orm_session
from app.server import ensure_certificate
from app.service.backup import create_backup, restore_backup
from test_after_sales import erp, payload, action, approved, ROOT

PDF = b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n'


def attachment(content=PDF, name='故障照片.pdf'):
    return {'file_name': name, 'content_base64': base64.b64encode(content).decode(),
        'reason': '客户现场提供'}


def path(case_id):
    return f'{ROOT}/{case_id}/attachments'


def test_lifecycle_and_terminal_lock(erp):
    client, api, actors, *_ = erp
    case = api('POST', ROOT, payload(erp), status=201)
    base = path(case['id'])
    item = api('POST', base, attachment(), actor='seller', status=201)
    assert item['case_id'] == case['id'] and item['sha256'] == hashlib.sha256(PDF).hexdigest()
    assert item['created_by_name'] == 'seller' and item['reversal'] is None
    assert 'content' not in item and 'content_base64' not in item
    assert api('GET', base)['items'] == [item]
    response = client.get('/api/v1/' + base + f'/{item["id"]}', headers=actors['seller'])
    assert response.content == PDF and response.headers['cache-control'] == 'no-store'
    assert response.headers['x-nexora-sha256'] == item['sha256']
    api('POST', base, attachment(), status=409)
    reversed_item = api('POST', base + f'/{item["id"]}/reverse', {'reason': '传错文件'}, status=201)
    assert reversed_item['reversal']['created_by_name'] == 'admin'
    assert client.get('/api/v1/' + base + f'/{item["id"]}', headers=actors['seller']).content == PDF
    api('POST', base + f'/{item["id"]}/reverse', {'reason': '重复'}, status=409)
    second = api('POST', base, attachment(), status=201)
    assert second['id'] != item['id']
    with orm_session() as db:
        assert db.get(AfterSalesAttachment, item['id']).content == PDF
        assert db.scalar(select(AfterSalesAttachmentReversal.id).where(
            AfterSalesAttachmentReversal.attachment_id == item['id'])) is not None
    case = action(api, case, 'cancel')
    assert api('GET', base)['can_modify'] is False
    api('POST', base, attachment(), status=409)
    api('POST', base + f'/{second["id"]}/reverse', {'reason': '结案后'}, status=409)
    assert api('GET', base)['items'][0]['reversal']['reason'] == '传错文件'


def test_rejects_invalid_content_limits_and_cross_case(erp):
    client, api, _, *_ = erp
    first = api('POST', ROOT, payload(erp), status=201)
    second = api('POST', ROOT, payload(erp, reference='AFTER-2'), status=201)
    base = path(first['id'])
    for body in (attachment(b'', 'blank.pdf'), attachment(b'bad'),
            attachment(PDF, '../bad.pdf'), attachment(PDF, 'bad.exe'),
            {**attachment(), 'content_base64': '%%%='},
            {**attachment(), 'reason': ' '},
            attachment(PDF + b'x' * (5 * 1024 * 1024))):
        api('POST', base, body, status=422)
    item = api('POST', base, attachment(), status=201)
    api('GET', path(second['id']) + f'/{item["id"]}', status=404)
    api('POST', path(second['id']) + f'/{item["id"]}/reverse', {'reason': '跨单'}, status=404)
    for index in range(1, 10):
        api('POST', base, attachment(PDF + str(index).encode()), status=201)
    api('POST', base, attachment(PDF + b'overflow'), status=409)
    assert len(api('GET', base)['items']) == 10


def test_permission_and_customer_scope(erp):
    _, api, _, *_ = erp
    case = api('POST', ROOT, payload(erp), status=201)
    base = path(case['id'])
    api('POST', base, attachment(), actor='reviewer', status=403)
    api('GET', base, actor='viewer', status=403)
    with orm_session(write=True) as db:
        db.get(Customer, case['frozen_source']['customer_id']).owner_id = 1
    api('GET', base, actor='seller', status=404)
    api('POST', base, attachment(), actor='seller', status=404)
    item = api('POST', base, attachment(), actor='admin', status=201)
    api('GET', base + f'/{item["id"]}', actor='seller', status=404)
    api('POST', base + f'/{item["id"]}/reverse', {'reason': '误传'}, actor='seller', status=404)


def test_closed_case_keeps_attachment_read_only(erp):
    _, api, *_ = erp
    case = api('POST', ROOT, payload(erp), status=201)
    base = path(case['id'])
    item = api('POST', base, attachment(), status=201)
    case = action(api, case, 'submit')
    case = action(api, case, 'approve', actor='reviewer')
    case = action(api, case, 'receive')
    case = action(api, case, 'inspect', inspection_result='pass')
    action(api, case, 'close')
    assert api('GET', base)['can_modify'] is False
    assert api('GET', base)['items'][0]['id'] == item['id']
    api('POST', base, attachment(PDF + b'late'), status=409)
    api('POST', base + f'/{item["id"]}/reverse', {'reason': '结案后'}, status=409)


def test_v73_upgrade_preserves_cases_and_replays_safely(erp):
    _, api, *_ = erp
    case = api('POST', ROOT, payload(erp), status=201)
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
        db.execute('PRAGMA user_version=73')
    migrate()
    migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 101
        assert db.execute('SELECT status FROM after_sales_cases WHERE id=?', (case['id'],)).fetchone()[0] == 'draft'
        assert db.execute("SELECT COUNT(*) FROM role_permissions WHERE permission_code='after_sales.attachment'").fetchone()[0] == 3
    api('POST', path(case['id']), attachment(), status=201)


def test_online_backup_keeps_original_and_reversal(erp, tmp_path):
    _, api, *_ = erp
    case = api('POST', ROOT, payload(erp), status=201)
    item = api('POST', path(case['id']), attachment(), status=201)
    api('POST', path(case['id']) + f'/{item["id"]}/reverse', {'reason': '原件替换'}, status=201)
    data_dir = database_path().parent
    with connection() as db:
        instance_id = db.execute('SELECT id FROM server_identity').fetchone()[0]
    # 测试数据库名称与服务入口不同，先建立同内容在线快照。
    with sqlite3.connect(database_path()) as source, sqlite3.connect(data_dir / 'nexora.db') as target:
        source.backup(target)
    ensure_certificate(data_dir, instance_id)
    archive = tmp_path / 'after-sales.nexora-backup'
    create_backup(data_dir, archive)
    restored = tmp_path / 'restored'
    restore_backup(archive, restored)
    with sqlite3.connect(restored / 'nexora.db') as db:
        saved = db.execute('SELECT content,sha256 FROM after_sales_attachments WHERE id=?',
            (item['id'],)).fetchone()
        assert saved == (PDF, hashlib.sha256(PDF).hexdigest())
        assert db.execute('SELECT reason FROM after_sales_attachment_reversals WHERE attachment_id=?',
            (item['id'],)).fetchone() == ('原件替换',)
