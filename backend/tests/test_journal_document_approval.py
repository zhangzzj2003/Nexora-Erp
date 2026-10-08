"""总账凭证独立分步、固定附件、旧客户端与原过账事务的真实接口验证。"""

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core.models import DocumentApprovalEvent, Journal, JournalLine, JournalChange
from app.core.orm import orm_session
from test_ledger_foundation import ledger
from test_journals import journals, create, action, PATH
from test_journal_attachments import payload as attachment_input, path as attachment_path, PDF


def state(client, identifier, headers=None):
    response = client.get(f'/api/v1/system/document-approvals/Journal/{identifier}', headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def operate(client, identifier, operation, version, headers=None, expected=200, reason='原票据独立核对'):
    response = client.post(f'/api/v1/system/document-approvals/Journal/{identifier}/{operation}',
        headers=headers, json={'version': version, 'reason': reason})
    assert response.status_code == expected, response.text
    return response.json() if expected != 500 else None


def reviewer(client, name):
    response = client.post('/api/v1/users', json={
        'username': name, 'password': 'journal-approval-test-123', 'roles': ['admin']})
    assert response.status_code == 201, response.text
    login = client.post('/api/v1/auth/login', json={'username': name, 'password': 'journal-approval-test-123'})
    return {'Authorization': 'Bearer ' + login.json()['token']}


def approved(journals):
    client, person = journals
    record = action(client, create(client), 'submit')
    return action(client, record, 'approve', person)


def test_three_fixed_steps_no_self_cancel_or_early_post(journals):
    client, first = journals
    second, third = reviewer(client, 'review_b'), reviewer(client, 'review_c')
    rule = '/api/v1/system/document-approvals/Journal'
    assert client.put(rule, json={'version': 1, 'steps': [
        {'name': name, 'role': None} for name in ('审核', '核准', '批准')]}).status_code == 200
    record = create(client)
    submitted = operate(client, record['id'], 'submit', 0)
    assert client.put(rule, json={'version': 2, 'steps': [{'name': '新规则', 'role': None}]}).status_code == 200
    assert client.get(f'/api/v1/system/document-approvals/Journal/{record['id']}', headers=None, params={'intent': 'execute'}).json()['can_review']
    assert client.post(f'{PATH}/{record["id"]}/cancel', json={'version': 2, 'reason': '绕过撤回'}).status_code == 409
    for index, person in enumerate((first, second, third)):
        current = client.get(f'{PATH}/{record["id"]}').json()
        assert client.post(f'{PATH}/{record["id"]}/post', json={'version': current['version'], 'reason': '未全部批准'}).status_code == 409
        submitted = operate(client, record['id'], 'approve', submitted['version'], person)
        assert [row['name'] for row in submitted['steps']] == ['审核', '核准', '批准']
        if index == 0:
            assert client.get(f'/api/v1/system/document-approvals/Journal/{record['id']}', headers=person, params={'intent': 'execute'}).json()['can_review']
    posted = action(client, client.get(f'{PATH}/{record["id"]}').json(), 'post')
    assert posted['approval']['status'] == 'executed'
    assert [row['action'] for row in state(client, record['id'])['events']] == ['submit', 'approve', 'approve', 'approve', 'execute']
    # 凭证冲销属于另一张独立凭证，原批准不会被继承到它。
    reverse = client.post(f'{PATH}/{record["id"]}/reverse', json={
        'version': posted['version'], 'reference': 'REV-THREE', 'journal_date': '2026-01-20', 'reason': '原票据更正'}).json()
    assert reverse['approval']['version'] == 0 and reverse['status'] == 'draft'
    assert client.post(f'{PATH}/{reverse["id"]}/post', json={'version': 1, 'reason': '直接冲销'}).status_code == 409


def test_attachment_authors_fixed_during_approval_and_posting(journals):
    client, person = journals
    record = create(client)
    original = client.post(attachment_path(record['id']), json=attachment_input(), headers=person).json()
    submitted = operate(client, record['id'], 'submit', 0)
    assert client.get(f'/api/v1/system/document-approvals/Journal/{record['id']}', headers=person, params={'intent': 'execute'}).json()['can_review']
    assert client.post(attachment_path(record['id']), json=attachment_input(PDF + b'new')).status_code == 409
    assert client.post(f'{attachment_path(record["id"])}/{original["id"]}/reverse', json={'reason': '替换票据'}).status_code == 409
    assert not client.get(attachment_path(record['id'])).json()['can_modify']
    independent = reviewer(client, 'independent_attachment_review')
    operate(client, record['id'], 'approve', submitted['version'], independent)
    action(client, client.get(f'{PATH}/{record["id"]}').json(), 'post')
    assert state(client, record['id'])['content_matches']
    assert not client.get(attachment_path(record['id'])).json()['items'][0]['can_reverse']
    assert client.post(f'{attachment_path(record["id"])}/{original["id"]}/reverse', json={'reason': '改原依据'}).status_code == 409
    work = client.post(attachment_path(record['id']), json=attachment_input(PDF + b'post-proof')).json()
    assert work['can_reverse']
    assert client.post(f'{attachment_path(record["id"])}/{work["id"]}/reverse', json={'reason': '补证误传'}).status_code == 201
    assert state(client, record['id'])['content_matches']


def test_withdraw_edit_authors_and_required_opinion(journals):
    client, person = journals
    record = create(client)
    for reason in (' ', '字' * 201):
        operate(client, record['id'], 'submit', 0, expected=422, reason=reason)
    submitted = operate(client, record['id'], 'submit', 0)
    operate(client, record['id'], 'approve', 0, person, expected=409)
    withdrawn = operate(client, record['id'], 'withdraw', submitted['version'])
    assert withdrawn['status'] == 'withdrawn'
    record = client.get(f'{PATH}/{record["id"]}').json()
    from test_journals import payload
    edited = client.put(f'{PATH}/{record["id"]}', headers=person,
        json={**payload(), 'version': record['version'], 'note': '审核人员改编原单'}).json()
    submitted = operate(client, record['id'], 'submit', withdrawn['version'])
    assert client.get(f'/api/v1/system/document-approvals/Journal/{record['id']}', headers=person, params={'intent': 'execute'}).json()['can_review']
    assert edited['status'] == 'draft'


def test_legacy_approved_is_history_only_and_old_client_cannot_post(journals):
    client, person = journals
    record = create(client)
    with orm_session(write=True) as db:
        row = db.get(Journal, record['id'])
        row.status, row.submitted_by, row.submitted_at = 'approved', row.created_by, '2026-01-10 00:00:00'
        row.reviewed_by, row.reviewed_at = 2, '2026-01-10 01:00:00'
    previous = state(client, record['id'])
    assert previous['version'] == 0 and previous['events'] == []
    assert any('升级前' in row['label'] for row in previous['summary'])
    assert client.post(f'{PATH}/{record["id"]}/post', json={'version': 1, 'reason': '原批准'}).status_code == 409
    assert client.post(f'{PATH}/{record["id"]}/submit', json={'version': 1, 'reason': '旧客户端'}).status_code == 409
    submitted = operate(client, record['id'], 'submit', 0)
    operate(client, record['id'], 'approve', submitted['version'], person)
    assert action(client, client.get(f'{PATH}/{record["id"]}').json(), 'post')['status'] == 'posted'


def test_parallel_review_only_once_and_fixed_body_tamper(journals):
    client, person = journals
    record = create(client)
    submitted = operate(client, record['id'], 'submit', 0)
    base = f'/api/v1/system/document-approvals/Journal/{record["id"]}'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.post(base + '/approve', headers=person,
            json={'version': submitted['version'], 'reason': '并发核对'}).status_code, range(2)))
    assert sorted(results) == [200, 409]
    with orm_session(write=True) as db:
        db.get(JournalLine, record['lines'][0]['id']).summary = '审批后篡改摘要'
    assert not state(client, record['id'])['content_matches']
    assert client.post(f'{PATH}/{record["id"]}/post', json={
        'version': client.get(f'{PATH}/{record["id"]}').json()['version'], 'reason': '仍强行过账'}).status_code == 409


def test_execute_event_failure_rolls_back_native_post_and_audit(journals):
    client, _ = journals
    record = approved(journals)
    before = client.get(f'{PATH}/{record["id"]}/changes').json()
    def fail(db, *_):
        if any(isinstance(item, DocumentApprovalEvent) and item.action == 'execute' for item in db.new):
            raise RuntimeError('模拟过账审批事件失败')
    event.listen(Session, 'before_flush', fail)
    try:
        assert client.post(f'{PATH}/{record["id"]}/post', json={'version': record['version'], 'reason': '故障回滚'}).status_code == 500
    finally:
        event.remove(Session, 'before_flush', fail)
    assert client.get(f'{PATH}/{record["id"]}/changes').json() == before
    assert client.get(f'{PATH}/{record["id"]}').json()['status'] == 'approved'
    assert state(client, record['id'])['status'] == 'approved'
    assert action(client, record, 'post')['approval']['status'] == 'executed'


def test_full_one_hundred_lines_and_ten_fixed_attachments_remain_readable(journals):
    client, _ = journals
    # 实际上限正文必须可读，不能只把前端摘要限制放宽却漏掉尾行或历史票据指纹。
    lines = [{'account_id': 1 if position % 2 == 0 else 2, 'summary': f'分录 {position}',
        'debit': '0.01' if position % 2 == 0 else '0',
        'credit': '0' if position % 2 == 0 else '0.01'} for position in range(100)]
    record = client.post(PATH, json={'reference': 'MAX-LINES', 'journal_date': '2026-01-10',
        'note': '完整正文', 'reason': '原始分录', 'lines': lines}).json()
    for index in range(10):
        response = client.post(attachment_path(record['id']), json=attachment_input(PDF + str(index).encode()))
        assert response.status_code == 201, response.text
    with orm_session(write=True) as db:
        row = db.get(Journal, record['id'])
        row.submitted_by, row.submitted_at = row.created_by, '2026-01-10 00:00:00'
    submitted = operate(client, record['id'], 'submit', 0)
    assert 110 < len(submitted['summary']) <= 128
    assert any('分录 99' in row['value'] for row in submitted['summary'])
    assert sum(row['label'] == '固定附件' for row in submitted['summary']) == 10
    assert any('升级前' in row['label'] for row in submitted['summary'])


def test_common_approval_preserves_separate_read_and_review_permissions(journals):
    client, person = journals
    record = action(client, create(client), 'submit')
    assert client.post('/api/v1/roles', json={'code': 'journal_read_only', 'label': '凭证只读',
        'permissions': ['journal.view']}).status_code == 201
    assert client.post('/api/v1/users', json={'username': 'journal_observer',
        'password': 'journal-approval-test-123', 'roles': ['journal_read_only']}).status_code == 201
    token = client.post('/api/v1/auth/login', json={'username': 'journal_observer', 'password': 'journal-approval-test-123'}).json()['token']
    observer = {'Authorization': 'Bearer ' + token}
    assert not state(client, record['id'], observer)['can_review']
    operate(client, record['id'], 'approve', record['approval']['version'], observer, expected=403)
    operate(client, record['id'], 'approve', record['approval']['version'], person)


def test_approve_only_role_can_use_native_journal_step_without_review_permission(journals):
    client, _ = journals
    # 财务领域的前置检查也须使用当前动作；不能另加旧 journal.review 门槛。
    created = client.post('/api/v1/roles', json={'code': 'journal_approver', 'label': '凭证批准',
        'permissions': ['journal.view', 'journal.approve']})
    assert created.status_code == 201
    client.post('/api/v1/users', json={'username': 'journal_approver',
        'password': 'journal-approval-test-123', 'roles': ['journal_approver']})
    login = client.post('/api/v1/auth/login', json={'username': 'journal_approver',
        'password': 'journal-approval-test-123'}).json()
    headers = {'Authorization': 'Bearer ' + login['token']}
    assert 'journal.review' not in login['user']['permissions']
    record = create(client)
    sent = operate(client, record['id'], 'submit', 0)
    assert state(client, record['id'], headers)['can_review']
    result = operate(client, record['id'], 'approve', sent['version'], headers)
    assert result['status'] == result['business_status'] == 'approved'
