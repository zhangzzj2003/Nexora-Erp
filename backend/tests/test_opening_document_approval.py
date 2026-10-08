"""总账期初逐步审批、确认和独立撤销；验证真实账务门槛与原子回滚。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session
from app.core.models import DocumentApprovalEvent, OpeningBalance
from app.core.orm import orm_session
from test_ledger_foundation import ledger
from test_journals import journals
from test_opening_balances import create, action, BASE
from test_journal_document_approval import reviewer
from approval_test_helpers import approve_document

PATH = '/api/v1/system/document-approvals/OpeningBalance'


def state(client, identifier, intent='execute', headers=None):
    response = client.get(f'{PATH}/{identifier}', params={'intent': intent}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def operate(client, identifier, name, version, headers=None, *, intent='execute', reason='核对启用试算表', expected=200):
    response = client.post(f'{PATH}/{identifier}/{name}', headers=headers,
        json={'version': version, 'intent': intent, 'reason': reason})
    assert response.status_code == expected, response.text
    return response.json()


def current(client, identifier):
    return next(row for row in client.get(BASE).json() if row['id'] == identifier)


def test_three_steps_fixed_template_authors_and_no_early_confirmation(journals):
    client, person = journals
    policy = client.get('/api/v1/system/document-approvals/OpeningBalance').json()
    steps = [{'name': name, 'role': None} for name in ('审核', '核准', '批准')]
    assert client.put('/api/v1/system/document-approvals/OpeningBalance',
        json={'version': policy['version'], 'steps': steps}).status_code == 200
    row = create(journals)
    submitted = operate(client, row['id'], 'submit', 0)
    assert client.get(f'/api/v1/system/document-approvals/OpeningBalance/{row["id"]}', headers=None, params={'intent': 'execute'}).json()['can_review']
    assert client.post(f'{BASE}/{row["id"]}/confirm', json={'version': 2, 'reason': '提前确认'}).status_code == 409
    assert client.post(f'{BASE}/{row["id"]}/cancel', json={'version': 2, 'reason': '绕过撤回'}).status_code == 409
    newer = client.get('/api/v1/system/document-approvals/OpeningBalance').json()
    assert client.put('/api/v1/system/document-approvals/OpeningBalance',
        json={'version': newer['version'], 'steps': [{'name': '新流程', 'role': None}]}).status_code == 200
    first = operate(client, row['id'], 'approve', submitted['version'], person)
    assert client.get(f'/api/v1/system/document-approvals/OpeningBalance/{row["id"]}', headers=person, params={'intent': 'execute'}).json()['can_review']
    second = operate(client, row['id'], 'approve', first['version'], reviewer(client, 'opening_second'))
    assert second['status'] == 'submitted'
    third = operate(client, row['id'], 'approve', second['version'], reviewer(client, 'opening_third'))
    assert third['status'] == 'approved' and third['steps'] == steps
    confirmed = action(journals, current(client, row['id']), 'confirm')
    assert confirmed['status'] == 'confirmed' and confirmed['approval']['status'] == 'executed'
    assert state(client, row['id'])['content_matches']


def test_reverse_independent_fixed_reason_original_authors_and_confirmation(journals):
    client, _ = journals
    row = create(journals)
    approve_document(client, None, 'OpeningBalance', row['id'], reason='核对原余额')
    row = action(journals, current(client, row['id']), 'confirm')
    assert client.post(f'{BASE}/{row["id"]}/reverse', json={'version': row['version'], 'reason': '直接撤销'}).status_code == 409
    # 确认人员有按钮权限即可审批自己提出的撤销；原期初批准仍为已执行。
    pending = operate(client, row['id'], 'submit', 0, intent='reverse', reason='原试算表更正')
    assert client.get(f'/api/v1/system/document-approvals/OpeningBalance/{row["id"]}', headers=None, params={'intent': 'reverse'}).json()['can_review']
    approved = operate(client, row['id'], 'approve', pending['version'], reviewer(client, 'opening_reverse'),
        intent='reverse', reason='独立核对撤销')
    assert approved['status'] == 'approved'
    assert any(item['label'] == '原确认时间' and item['value'] == row['confirmed_at'] for item in approved['summary'])
    before = current(client, row['id'])
    assert before['status'] == 'confirmed' and before['approval']['status'] == 'executed'
    assert client.post(f'{BASE}/{row["id"]}/reverse', json={'version': row['version'], 'reason': '更换执行原因'}).status_code == 409
    response = client.post(f'{BASE}/{row["id"]}/reverse', json={'version': row['version'], 'reason': before['reversal_reason']})
    assert response.status_code == 200, response.text
    reverse = response.json()
    assert reverse['status'] == 'reversed' and reverse['lines'] == row['lines'] and reverse['active_key'] is None
    assert reverse['reversal_approval']['status'] == 'executed'
    assert state(client, row['id'], 'reverse')['content_matches']
    assert client.post(f'{BASE}/{row["id"]}/reverse', json={'version': reverse['version'], 'reason': before['reversal_reason']}).status_code == 409


@pytest.mark.parametrize('name', ['confirm', 'reverse'])
def test_execute_event_failure_rolls_back_original_state_and_native_audit(journals, name):
    client, _ = journals
    row = create(journals)
    approve_document(client, None, 'OpeningBalance', row['id'], reason='期初核对')
    row = current(client, row['id'])
    if name == 'reverse':
        row = action(journals, row, 'confirm')
        approve_document(client, None, 'OpeningBalance', row['id'], intent='reverse', reason='期初核对')
        row = current(client, row['id'])
    before = client.get(f'{BASE}/{row["id"]}/changes').json()
    def fail(session, _):
        if any(isinstance(item, DocumentApprovalEvent) and item.action == 'execute' for item in session.new):
            raise RuntimeError('模拟审批执行记录失败')
    event.listen(Session, 'before_flush', fail)
    try:
        assert client.post(f'{BASE}/{row["id"]}/{name}', json={'version': row['version'], 'reason': '期初核对'}).status_code == 500
    finally:
        event.remove(Session, 'before_flush', fail)
    assert current(client, row['id']) == row
    assert client.get(f'{BASE}/{row["id"]}/changes').json() == before
    assert action(journals, row, name)['status'] == ('confirmed' if name == 'confirm' else 'reversed')


def test_legacy_approval_cannot_enable_and_confirmed_history_can_request_reverse(journals):
    client, person = journals
    row = create(journals)
    with orm_session(write=True) as db:
        source = db.get(OpeningBalance, row['id'])
        source.status = 'approved'
        source.submitted_by, source.submitted_at = 1, '2026-01-01 00:00:00'
        source.reviewed_by, source.reviewed_at = 2, '2026-01-01 01:00:00'
    original = state(client, row['id'])
    assert original['version'] == 0 and original['events'] == []
    assert any('升级前' in line['label'] for line in original['summary'])
    assert client.post(f'{BASE}/{row["id"]}/confirm', json={'version': 1, 'reason': '旧批准启用'}).status_code == 409
    assert client.post(f'{BASE}/{row["id"]}/approve', json={'version': 1, 'reason': '旧客户端'}).status_code == 409
    # 真正已确认旧单只保存历史，不补造新启用批准，但可独立审批撤销。
    with orm_session(write=True) as db:
        source = db.get(OpeningBalance, row['id'])
        source.status, source.confirmed_by, source.confirmed_at = 'confirmed', 1, '2026-01-01 02:00:00'
    submitted = operate(client, row['id'], 'submit', 0, intent='reverse', reason='期初核对')
    operate(client, row['id'], 'approve', submitted['version'], person, intent='reverse')
    reversed_record = action(journals, current(client, row['id']), 'reverse')
    assert reversed_record['approval']['version'] == 0 and reversed_record['reversal_approval']['status'] == 'executed'


def test_concurrent_review_body_tamper_and_invalid_account_can_withdraw(journals):
    client, person = journals
    row = create(journals)
    submitted = operate(client, row['id'], 'submit', 0)
    gate = Barrier(2)
    def race(_):
        gate.wait()
        return client.post(f'{PATH}/{row["id"]}/approve', headers=person,
            json={'version': submitted['version'], 'reason': '独立核对'}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(race, range(2))) == [200, 409]
    with orm_session(write=True) as db:
        db.get(OpeningBalance, row['id']).note = '批准后篡改'
    assert not state(client, row['id'])['content_matches']
    assert client.post(f'{BASE}/{row["id"]}/confirm', json={'version': current(client, row['id'])['version'], 'reason': '执行篡改内容'}).status_code == 409
    withdrawn = operate(client, row['id'], 'withdraw', state(client, row['id'])['version'])
    assert client.put('/api/v1/finance/ledger-accounts/1', json={'version': 1, 'name': '现金', 'is_active': False, 'reason': '停用'}).status_code == 200
    operate(client, row['id'], 'submit', withdrawn['version'], expected=409)
    assert current(client, row['id'])['status'] == 'draft'


def test_reverse_approval_cannot_bypass_later_posted_journal(journals):
    client, person = journals
    row = create(journals)
    approve_document(client, None, 'OpeningBalance', row['id'], reason='期初核对')
    row = action(journals, current(client, row['id']), 'confirm')
    reverse = approve_document(client, None, 'OpeningBalance', row['id'], intent='reverse', reason='期初核对')
    from test_journals import create as create_journal, action as journal_action
    journal = journal_action(client, journal_action(client, create_journal(client), 'submit'), 'approve', person)
    journal_action(client, journal, 'post')
    # 批准之后发生的真实过账仍须阻止撤销，原金额和两套审批状态一起保留。
    assert client.post(f'{BASE}/{row["id"]}/reverse', json={'version': row['version'], 'reason': '期初核对'}).status_code == 409
    assert current(client, row['id'])['status'] == 'confirmed'
    assert state(client, row['id'], 'reverse')['status'] == 'approved'
    assert operate(client, row['id'], 'withdraw', reverse['version'], intent='reverse')['status'] == 'withdrawn'


def test_finance_opinion_boundary_and_stale_version_do_not_modify_native_record(journals):
    client, person = journals
    row = create(journals)
    for reason in (' ', '字' * 201):
        operate(client, row['id'], 'submit', 0, reason=reason, expected=422)
    submitted = operate(client, row['id'], 'submit', 0)
    before = current(client, row['id'])
    operate(client, row['id'], 'approve', 0, person, expected=409)
    for reason in (' ', '字' * 201):
        operate(client, row['id'], 'approve', submitted['version'], person, reason=reason, expected=422)
    assert current(client, row['id']) == before
