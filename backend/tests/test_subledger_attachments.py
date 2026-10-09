"""历史原单票据的来源变化、审批固定、跨期补录、并发及原子升级。"""

import base64
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from contextlib import contextmanager

import pytest
from sqlalchemy import delete, event, select
from sqlalchemy.orm import Session

from app.core.database import connection, database_path, migrate
from app.core.models import (AccountingPeriod, Base, DocumentApprovalCase, SubledgerAttachment,
    SubledgerAttachmentReversal, RolePermission)
from app.core.orm import orm_session
from app.finance.subledger_attachment_rules import archive_evidence
from app.core.approval_documents import subledger_snapshot
from app.server import ensure_certificate
from app.service.backup import create_backup, restore_backup
from approval_test_helpers import approve_document
from test_ledger_foundation import ledger
from test_subledger_openings import subledger, create, action, confirmed, BASE

PDF = b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n'


def path(record):
    return f'{BASE}/{record["id"]}/attachments'


def payload(record, content=PDF, **changes):
    return dict(file_name='原单.pdf', content_base64=base64.b64encode(content).decode(), reason='原始票据',
        opening_version=record['version'], line_id=record['lines'][0]['id']) | changes


def reverse(client, record, item, **changes):
    return client.post(f'{path(record)}/{item["id"]}/reverse', json=dict(
        opening_version=record['version'], reason='更正原件') | changes)


def test_original_is_immutable_and_reversal_preserves_download(subledger):
    client = subledger[0]
    record = create(subledger)
    response = client.post(path(record), json=payload(record))
    assert response.status_code == 201, response.text
    item = response.json()
    assert item['source']['document_reference'] == 'OLD-A' and item['source_status'] == 'matched'
    assert item['source']['auxiliary'][1]['name'] == '项目甲'
    assert item['sha256'] == hashlib.sha256(PDF).hexdigest() and 'content' not in item
    assert client.get(path(record)).json()['items'] == [item]
    assert client.post(path(record), json=payload(record)).status_code == 409
    assert reverse(client, record, item).status_code == 201
    assert reverse(client, record, item).status_code == 409
    download = client.get(f'{path(record)}/{item["id"]}')
    assert download.content == PDF and download.headers['x-nexora-sha256'] == item['sha256']
    assert client.post(path(record), json=payload(record)).status_code == 201
    with connection() as db:
        for table in ('subledger_attachments', 'subledger_attachment_reversals'):
            for statement in (f'UPDATE {table} SET reason=\'覆盖\'', f'DELETE FROM {table}'):
                with pytest.raises(sqlite3.IntegrityError, match='immutable'):
                    db.execute(statement)


def test_recreated_lines_match_but_stale_versions_never_target_reused_id(subledger):
    client, api = subledger[:2]
    record = create(subledger)
    item = client.post(path(record), json=payload(record)).json()
    saved = api('PUT', f'finance/subledger-openings/{record["id"]}', {**subledger[4], 'version':record['version']})
    listed = client.get(path(record)).json()
    assert listed['items'][0]['source_status'] == 'matched' and listed['opening_version'] == saved['version']
    assert client.post(path(record), json=payload(record, PDF+b'stale')).status_code == 409
    assert reverse(client, record, item).status_code == 409
    assert client.post(path(saved), json=payload(saved, PDF+b'fresh')).status_code == 201
    assert reverse(client, saved, item).status_code == 201


@pytest.mark.parametrize('change', ['amount', 'remove', 'account', 'auxiliary'])
def test_changed_or_removed_source_remains_readable_and_blocks_submission(subledger, change):
    client, api = subledger[:2]
    record = create(subledger)
    item = client.post(path(record), json=payload(record)).json()
    lines = [{**row, 'auxiliary':list(row['auxiliary'])} for row in subledger[4]['lines']]
    controls = list(subledger[4]['control_accounts'])
    if change == 'amount': lines[0]['debit'], lines[1]['debit'] = '90', '60'
    if change == 'remove': lines.pop(0); lines[0]['debit'] = '150'
    if change == 'account':
        api('POST', 'finance/ledger-accounts', dict(code='AR2',name='AR2',category='asset',normal_balance='debit',reason='第二科目'), 201)
        controls.append(dict(kind='receivable', account_id=5)); lines[0]['account_id'] = 5
    if change == 'auxiliary': lines[0]['auxiliary'] = []
    saved = api('PUT', f'finance/subledger-openings/{record["id"]}', {**subledger[4], 'version':1,
        'control_accounts':controls, 'lines':lines})
    page = client.get(path(record)).json()
    assert page['changed_count'] == 1 and page['items'][0]['source_status'] == ('missing' if change=='remove' else 'changed')
    assert page['items'][0]['source']['debit'] == '100.00'
    assert client.get(f'{path(record)}/{item["id"]}').content == PDF
    result = client.post(f'/api/v1/system/document-approvals/SubledgerOpening/{record["id"]}/submit',
        json=dict(version=0,reason='送审'))
    assert result.status_code == 409 and '票据' in result.text
    assert reverse(client, saved, item).status_code == 201
    if change in ('amount', 'remove'):
        assert action(subledger, saved, 'submit')['status'] == 'submitted'


def test_pending_approval_freezes_all_files_and_confirmed_supplement_does_not_rewrite_approval(subledger):
    client = subledger[0]
    record = create(subledger)
    item = client.post(path(record), json=payload(record)).json()
    record = action(subledger, record, 'submit')
    assert client.post(path(record), json=payload(record, PDF+b'pending')).status_code == 409
    assert reverse(client, record, item).status_code == 409
    record = action(subledger, record, 'approve', True)
    with orm_session() as db:
        case = db.scalar(select(DocumentApprovalCase).where(DocumentApprovalCase.document_type=='SubledgerOpening'))
        original_json, original_hash = case.snapshot_json, case.content_digest
    record = action(subledger, record, 'confirm')
    extra = client.post(path(record), json=payload(record, PDF+b'supplement'))
    assert extra.status_code == 201, extra.text
    assert reverse(client, record, item).status_code == 409
    assert reverse(client, record, extra.json()).status_code == 201
    with orm_session() as db:
        assert subledger_snapshot(db, record['id']) == json.loads(original_json)
        case = db.scalar(select(DocumentApprovalCase).where(DocumentApprovalCase.document_type=='SubledgerOpening'))
        assert case.content_digest == original_hash and case.snapshot_json == original_json
    rows = client.get(path(record)).json()['items']
    assert next(row for row in rows if row['id']==item['id'])['approved_original']


def test_old_approved_and_executed_snapshots_keep_absent_attachment_key(subledger):
    client = subledger[0]
    record = action(subledger, action(subledger, create(subledger), 'submit'), 'approve', True)
    with orm_session() as db:
        original = subledger_snapshot(db, record['id'])
        assert 'attachments' not in original
    record = action(subledger, record, 'confirm')
    assert client.post(path(record), json=payload(record)).status_code == 201
    with orm_session() as db:
        assert subledger_snapshot(db, record['id']) == original


def test_cancelled_and_reversed_plan_is_read_only(subledger):
    client = subledger[0]
    record = create(subledger)
    item = client.post(path(record), json=payload(record)).json()
    record = action(subledger, record, 'cancel')
    assert not client.get(path(record)).json()['can_modify']
    assert client.post(path(record), json=payload(record, PDF+b'later')).status_code == 409
    assert reverse(client, record, item).status_code == 409
    assert client.get(f'{path(record)}/{item["id"]}').content == PDF


def test_permission_is_independent_and_cross_plan_target_is_rejected(subledger):
    client, api = subledger[:2]
    record = create(subledger)
    item = client.post(path(record), json=payload(record)).json()
    role = api('POST','roles',dict(code='reader',label='票据查看',permissions=['subledger_opening.view']),201)
    api('POST','users',dict(username='reader',password='reader-pass-123',roles=[role['code']]),201)
    headers = {'Authorization':'Bearer '+api('POST','auth/login',dict(username='reader',password='reader-pass-123'))['token']}
    assert not client.get(path(record), headers=headers).json()['can_modify']
    assert client.get(f'{path(record)}/{item["id"]}', headers=headers).content == PDF
    assert client.post(path(record), json=payload(record), headers=headers).status_code == 403
    assert client.post(f'{path(record)}/{item["id"]}/reverse',json=dict(opening_version=1,reason='越权'),headers=headers).status_code == 403
    action(subledger, record, 'cancel')
    second = create(subledger, reference='SECOND')
    assert client.get(f'{path(second)}/{item["id"]}').status_code == 404
    assert reverse(client, second, item).status_code == 404
    assert client.post(path(second), json=payload(second,line_id=record['lines'][0]['id'])).status_code == 404


def test_duplicate_race_quota_and_page_boundary(subledger):
    client = subledger[0]
    record = create(subledger)
    gate = Barrier(2)
    def upload(_):
        gate.wait()
        return client.post(path(record),json=payload(record)).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(upload,range(2))) == [201,409]
    for i in range(9):
        assert client.post(path(record),json=payload(record,PDF+str(i).encode())).status_code == 201
    assert client.post(path(record),json=payload(record,PDF+b'overflow')).status_code == 409
    listed = client.get(path(record)+'?page=2&page_size=3').json()
    assert len(listed['items']) == 3 and listed['total'] == listed['active_count'] == 10
    assert client.get(path(record)+'?page_size=101').status_code == 422
    assert reverse(client,record,listed['items'][0]).status_code == 201
    assert client.post(path(record),json=payload(record,PDF+b'overflow')).status_code == 201


def test_invalid_files_and_strict_source_ids_have_no_partial_writes(subledger):
    client = subledger[0]
    record = create(subledger)
    for data in [payload(record,b''),payload(record,b'not-pdf'),payload(record,file_name='../票据.pdf'),
            payload(record,opening_version=True),payload(record,line_id=True),payload(record,content_base64='%%%='),
            payload(record,PDF+b'x'*(5*1024*1024)),payload(record,reason=' '),payload(record,unknown='unexpected')]:
        assert client.post(path(record),json=data).status_code == 422
    assert client.get(path(record)).json()['total'] == 0


def test_current_date_lock_and_rollback_after_blob_flush(subledger, monkeypatch):
    client = subledger[0]
    record = confirmed(subledger)
    # 原期初已结账仍可在当前开放日期补录；原批准来源始终不变。
    with orm_session(write=True) as db:
        db.get(AccountingPeriod,1).end_date, db.get(AccountingPeriod,1).status = '2026-01-31','closed'
    item = client.post(path(record),json=payload(record))
    assert item.status_code == 201, item.text
    from app.core import document_approval as approval
    with monkeypatch.context() as patch:
        patch.setattr(approval,'now',lambda _: '2026-01-31 10:00:00')
        assert client.post(path(record),json=payload(record,PDF+b'locked')).status_code == 409
    def fail(session, _):
        if any(isinstance(row,SubledgerAttachment) for row in session.identity_map.values()):
            raise RuntimeError('模拟附件提交失败')
    event.listen(Session,'before_commit',fail)
    try:
        assert client.post(path(record),json=payload(record,PDF+b'rollback')).status_code == 500
    finally:
        event.remove(Session,'before_commit',fail)
    assert client.get(path(record)).json()['total'] == 1


def test_archive_cutoff_and_backup_preserve_original_and_reversal(subledger, tmp_path):
    client = subledger[0]
    record = create(subledger)
    item = client.post(path(record),json=payload(record)).json()
    assert reverse(client,record,item).status_code == 201
    with orm_session() as db:
        assert archive_evidence(db,'2025-12-31') == []
        archived = archive_evidence(db,'2999-12-31')
        assert archived[0]['sha256'] == item['sha256'] and archived[0]['reversal']['reason'] == '更正原件'
        assert 'content' not in archived[0] and 'source_status' not in archived[0]
    data_dir = database_path().parent
    with connection() as db:
        instance_id = db.execute('SELECT id FROM server_identity').fetchone()[0]
    with sqlite3.connect(database_path()) as source, sqlite3.connect(data_dir/'nexora.db') as target:
        source.backup(target)
    ensure_certificate(data_dir,instance_id)
    archive = tmp_path/'original.nexora-backup'
    create_backup(data_dir,archive)
    restored = tmp_path/'restored'
    restore_backup(archive,restored)
    with sqlite3.connect(restored/'nexora.db') as db:
        assert db.execute('SELECT content,sha256 FROM subledger_attachments').fetchone() == (PDF,item['sha256'])
        assert db.execute('SELECT reason FROM subledger_attachment_reversals').fetchone() == ('更正原件',)


def test_v99_upgrade_is_atomic_retryable_and_does_not_modify_legacy_evidence(subledger):
    record = confirmed(subledger)
    with connection() as db:
        original = db.execute('SELECT snapshot_json FROM document_approval_cases WHERE document_type=\'SubledgerOpening\'').fetchone()[0]
        db.execute('DROP TABLE subledger_attachment_reversals')
        db.execute('DROP TABLE subledger_attachments')
        db.execute("DELETE FROM role_permissions WHERE permission_code='subledger_opening.attachment'")
        db.execute("DELETE FROM permissions WHERE code='subledger_opening.attachment'")
        db.execute('PRAGMA user_version = 99')
        # 后半段权限迁移故障不能留下前半段文件表。
        db.execute("CREATE TRIGGER fail_attachment_permission BEFORE INSERT ON permissions WHEN NEW.code='subledger_opening.attachment' BEGIN SELECT RAISE(ABORT,'test upgrade fault'); END")
    with pytest.raises(sqlite3.IntegrityError,match='test upgrade fault'):
        migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 99
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='subledger_attachments'").fetchone()
        db.execute('DROP TRIGGER fail_attachment_permission')
    migrate(); migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 101
        assert db.execute('SELECT snapshot_json FROM document_approval_cases WHERE document_type=\'SubledgerOpening\'').fetchone()[0] == original
        assert db.execute("SELECT count(*) FROM role_permissions WHERE permission_code='subledger_opening.attachment'").fetchone()[0] == 2
    assert len(Base.metadata.tables) == 202
    assert subledger[0].post(path(record),json=payload(record)).status_code == 201


def test_reversal_approval_freezes_supplements_and_reversed_plan_keeps_originals(subledger):
    client = subledger[0]
    record = confirmed(subledger)
    item = client.post(path(record),json=payload(record)).json()
    approve_document(client,None,'SubledgerOpening',record['id'],intent='reverse',reason='分户核对')
    record = next(row for row in client.get(BASE).json() if row['id']==record['id'])
    assert client.post(path(record),json=payload(record,PDF+b'pending-reverse')).status_code == 409
    assert reverse(client,record,item).status_code == 409
    record = action(subledger,record,'reverse')
    assert record['status'] == 'reversed' and not client.get(path(record)).json()['can_modify']
    assert reverse(client,record,item).status_code == 409
    assert client.get(f'{path(record)}/{item["id"]}').content == PDF


def test_post_flush_clock_rollback_is_rejected_for_upload_and_reversal(subledger):
    client = subledger[0]
    record = confirmed(subledger)
    item = client.post(path(record),json=payload(record)).json()
    with orm_session(write=True) as db:
        db.get(AccountingPeriod,1).end_date,db.get(AccountingPeriod,1).status = '2026-01-31','closed'
    def clock_back(session,*_):
        for row in session.new:
            if isinstance(row,(SubledgerAttachment,SubledgerAttachmentReversal)):
                row.created_at = '2026-01-31 23:59:59'
    event.listen(Session,'before_flush',clock_back)
    try:
        response = client.post(path(record),json=payload(record,PDF+b'clock-back'))
        assert response.status_code == 409 and '回滚' in response.text
        response = reverse(client,record,item)
        assert response.status_code == 409 and '回滚' in response.text
    finally:
        event.remove(Session,'before_flush',clock_back)
    listed = client.get(path(record)).json()
    assert listed['total'] == 1 and listed['items'][0]['reversal'] is None


def test_period_attachment_reversal_uses_its_own_cutoff_and_old_archive_is_fixed(subledger):
    client = subledger[0]
    record = confirmed(subledger)
    timestamp = ['2026-02-10 12:00:00']
    def set_time(session,*_):
        for row in session.new:
            if isinstance(row,(SubledgerAttachment,SubledgerAttachmentReversal)):
                row.created_at = timestamp[0]
    event.listen(Session,'before_flush',set_time)
    try:
        item = client.post(path(record),json=payload(record)).json()
        with orm_session() as db:
            archived = archive_evidence(db,'2026-02-28')
        fixed_json = json.dumps(archived)
        timestamp[0] = '2026-03-01 00:00:00'
        assert reverse(client,record,item).status_code == 201
        with orm_session() as db:
            assert archive_evidence(db,'2026-02-28') == json.loads(fixed_json)
            assert archive_evidence(db,'2026-03-31')[0]['reversal'] is not None
    finally:
        event.remove(Session,'before_flush',set_time)


@pytest.mark.parametrize('operation', ['upload','reverse','list','download'])
def test_revocation_between_dependency_and_transaction_is_enforced(subledger, monkeypatch, operation):
    client = subledger[0]
    record = create(subledger)
    item = client.post(path(record),json=payload(record)).json()
    from app.finance import subledger_attachments as files
    permission = 'subledger_opening.attachment' if operation in ('upload','reverse') else 'subledger_opening.view'
    original_session = files.orm_session
    @contextmanager
    def raced_session(*,write=False):
        with original_session(write=True) as db:
            db.execute(delete(RolePermission).where(RolePermission.role_code=='admin',RolePermission.permission_code==permission))
        with original_session(write=write) as db:
            yield db
    with monkeypatch.context() as patch:
        patch.setattr(files,'orm_session',raced_session)
        response = (client.post(path(record),json=payload(record,PDF+b'race')) if operation=='upload'
            else reverse(client,record,item) if operation=='reverse'
            else client.get(path(record)) if operation=='list'
            else client.get(f'{path(record)}/{item["id"]}'))
        assert response.status_code == 403, response.text
    with orm_session() as db:
        assert len(list(db.scalars(select(SubledgerAttachment)))) == 1
        assert not list(db.scalars(select(SubledgerAttachmentReversal)))
