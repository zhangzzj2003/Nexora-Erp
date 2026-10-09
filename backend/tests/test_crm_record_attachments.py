"""联系人、跟进及商机附件的客户隔离、状态冻结与恢复验证。"""

import base64
import hashlib
import sqlite3

from app.core.database import connection, database_path, migrate
from app.core.models import Base, CrmRecordAttachment, CrmRecordAttachmentReversal, Customer
from app.core.orm import orm_session
from app.server import ensure_certificate
from app.service.backup import create_backup, restore_backup
from test_crm import seeded, base_records, C

PDF = b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n'


def payload(content=PDF, name='客户来函.pdf'):
    return {'file_name': name, 'content_base64': base64.b64encode(content).decode(),
        'reason': '客户沟通依据'}


def path(kind, identifier):
    return C+f'/records/{kind}/{identifier}/attachments'


def records(seed):
    client, admin, *_ = seed
    contact, opportunity, _ = base_records(seed)
    activity = client.post(C+'/activities', headers=admin, json={
        'customer_id': contact['customer_id'], 'contact_id': contact['id'],
        'opportunity_id': opportunity['id'], 'subject': '确认规格',
        'owner_id': 3, 'due_date': '2030-01-20'}).json()
    return {'contact': contact, 'activity': activity, 'opportunity': opportunity}


def test_all_record_kinds_keep_original_and_reversal(seeded):
    client, admin, _, seller, *_ = seeded
    for kind, record in records(seeded).items():
        base = path(kind, record['id'])
        uploaded = client.post(base, headers=seller, json=payload())
        assert uploaded.status_code == 201, uploaded.text
        item = uploaded.json()
        assert item['entity_kind'] == kind and item['entity_id'] == record['id']
        assert item['sha256'] == hashlib.sha256(PDF).hexdigest()
        assert item['created_by_name'] == 'seller' and item['reversal'] is None
        assert 'content' not in item and 'content_base64' not in item
        assert client.get(base, headers=admin).json()['items'] == [item]
        downloaded = client.get(base+f'/{item["id"]}', headers=admin)
        assert downloaded.content == PDF and downloaded.headers['cache-control'] == 'no-store'
        assert client.post(base, headers=admin, json=payload()).status_code == 409
        reversed_result = client.post(base+f'/{item["id"]}/reverse', headers=admin,
            json={'reason': '误传旧件'})
        assert reversed_result.status_code == 201
        assert reversed_result.json()['reversal']['reason'] == '误传旧件'
        assert client.get(base+f'/{item["id"]}', headers=admin).content == PDF
        assert client.post(base+f'/{item["id"]}/reverse', headers=admin,
            json={'reason': '重复'}).status_code == 409
        assert client.post(base, headers=admin, json=payload()).status_code == 201
        after = client.get(C+f'/records/{kind}/{record["id"]}', headers=admin).json()
        assert after['version'] == record['version']
        with orm_session() as db:
            assert db.get(CrmRecordAttachment, item['id']).content == PDF
            assert db.query(CrmRecordAttachmentReversal).filter_by(attachment_id=item['id']).count() == 1


def test_input_limit_cross_kind_and_customer_scope(seeded):
    client, admin, _, seller, viewer, customer, *_ = seeded
    all_records = records(seeded)
    contact_id = all_records['contact']['id']
    base = path('contact', contact_id)
    for body in (payload(b''), payload(b'bad'), payload(PDF, '../bad.pdf'),
            payload(PDF, 'bad.exe'), {**payload(), 'content_base64': '%%%='},
            {**payload(), 'reason': ' '}, payload(PDF+b'x'*(5*1024*1024))):
        assert client.post(base, headers=admin, json=body).status_code == 422
    assert client.get(base, headers=viewer).status_code == 403
    assert client.post(base, headers=viewer, json=payload()).status_code == 403
    item = client.post(base, headers=admin, json=payload()).json()
    assert client.get(path('activity', all_records['activity']['id'])+f'/{item["id"]}',
        headers=admin).status_code == 404
    assert client.post(path('opportunity', all_records['opportunity']['id'])+f'/{item["id"]}/reverse',
        headers=admin, json={'reason': '跨记录'}).status_code == 404
    for index in range(1, 10):
        assert client.post(base, headers=admin, json=payload(PDF+str(index).encode())).status_code == 201
    assert client.post(base, headers=admin, json=payload(PDF+b'overflow')).status_code == 409
    with orm_session(write=True) as db:
        db.get(Customer, customer).owner_id = 1
    assert client.get(base, headers=seller).status_code == 404
    assert client.post(base, headers=seller, json=payload()).status_code == 404
    assert client.get(base+f'/{item["id"]}', headers=seller).status_code == 404


def test_ended_records_are_read_only(seeded):
    client, admin, *_ = seeded
    all_records = records(seeded)
    contact = all_records['contact']
    activity = all_records['activity']
    opportunity = all_records['opportunity']
    for kind, record in all_records.items():
        assert client.post(path(kind, record['id']), headers=admin, json=payload()).status_code == 201
    edited = client.put(C+f'/contacts/{contact["id"]}', headers=admin, json={
        'customer_id': contact['customer_id'], 'name': contact['name'],
        'is_active': False, 'version': contact['version'], 'reason': '联系人停用'})
    assert edited.status_code == 200, edited.text
    closed = client.post(C+f'/activities/{activity["id"]}/complete', headers=admin,
        json={'version': activity['version'], 'reason': '跟进完成'})
    assert closed.status_code == 200, closed.text
    lost = client.put(C+f'/opportunities/{opportunity["id"]}', headers=admin, json={
        'customer_id': opportunity['customer_id'], 'contact_id': None,
        'title': opportunity['title'], 'owner_id': opportunity['owner_id'],
        'stage': 'lost', 'estimated_amount': opportunity['estimated_amount'],
        'expected_close_date': opportunity['expected_close_date'],
        'version': opportunity['version'], 'reason': '项目终止'})
    assert lost.status_code == 200, lost.text
    for kind, record in all_records.items():
        base = path(kind, record['id'])
        item = client.get(base, headers=admin).json()['items'][0]
        assert client.get(base, headers=admin).json()['can_modify'] is False
        assert client.post(base, headers=admin, json=payload(PDF+b'later')).status_code == 409
        assert client.post(base+f'/{item["id"]}/reverse', headers=admin,
            json={'reason': '终态'}).status_code == 409
        assert client.get(base+f'/{item["id"]}', headers=admin).content == PDF
    reopened = client.post(C+f'/opportunities/{opportunity["id"]}/reopen', headers=admin,
        json={'version': lost.json()['version'], 'reason': '重新洽谈'})
    assert reopened.status_code == 200, reopened.text
    assert client.post(path('opportunity', opportunity['id']), headers=admin,
        json=payload(PDF+b'new')).status_code == 201


def test_v75_upgrade_is_idempotent(seeded):
    client, admin, *_ = seeded
    contact = records(seeded)['contact']
    with connection() as db:
        db.execute('DROP TABLE crm_record_attachment_reversals')
        db.execute('DROP TABLE crm_record_attachments')
        db.execute("DELETE FROM role_permissions WHERE permission_code='crm.attachment'")
        db.execute("DELETE FROM permissions WHERE code='crm.attachment'")
        db.execute('PRAGMA user_version=75')
    migrate()
    migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 100
        assert db.execute('SELECT name FROM crm_contacts WHERE id=?',
            (contact['id'],)).fetchone()[0] == contact['name']
        assert db.execute("SELECT COUNT(*) FROM role_permissions WHERE permission_code='crm.attachment'").fetchone()[0] == 2
    assert len(Base.metadata.tables) == 200
    assert client.post(path('contact', contact['id']), headers=admin, json=payload()).status_code == 201


def test_online_backup_keeps_record_attachment_and_reversal(seeded, tmp_path):
    client, admin, *_ = seeded
    contact = records(seeded)['contact']
    base = path('contact', contact['id'])
    item = client.post(base, headers=admin, json=payload()).json()
    assert client.post(base+f'/{item["id"]}/reverse', headers=admin,
        json={'reason': '更换客户来函'}).status_code == 201
    data_dir = database_path().parent
    with connection() as db:
        instance_id = db.execute('SELECT id FROM server_identity').fetchone()[0]
    # 测试库使用临时名称，归档前建立与服务入口同名的在线快照。
    with sqlite3.connect(database_path()) as source, sqlite3.connect(data_dir / 'nexora.db') as target:
        source.backup(target)
    ensure_certificate(data_dir, instance_id)
    archive = tmp_path / 'crm-record.nexora-backup'
    create_backup(data_dir, archive)
    restored = tmp_path / 'restored'
    restore_backup(archive, restored)
    with sqlite3.connect(restored / 'nexora.db') as db:
        assert db.execute('SELECT content, sha256 FROM crm_record_attachments WHERE id=?',
            (item['id'],)).fetchone() == (PDF, hashlib.sha256(PDF).hexdigest())
        assert db.execute('SELECT reason FROM crm_record_attachment_reversals WHERE attachment_id=?',
            (item['id'],)).fetchone() == ('更换客户来函',)
