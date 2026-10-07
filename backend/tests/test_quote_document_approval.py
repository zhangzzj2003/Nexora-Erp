"""报价统一审批的固定依据、原领域约束、客户范围及同事务转单验证。"""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select

from test_crm import seeded, base_records, action, B, C
from test_crm_quote_attachments import attachment, PDF
from app.core import document_approval as workflow
from app.core.models import (CrmQuote, CrmChange, CrmOpportunity, Customer, Material,
    SalesOrder, DocumentApprovalAuthor, DocumentApprovalCase, DocumentApprovalEvent)
from app.core.orm import orm_session
from app.sales import crm_quotes


@pytest.fixture
def quotation(seeded):
    client, admin, reviewer, seller, *_ = seeded
    contact, opportunity, payload = base_records(seeded)
    created = client.post(C+'/quotes', headers=admin, json=payload)
    assert created.status_code == 201, created.text
    return client, admin, reviewer, seller, created.json(), opportunity, payload


def endpoint(identifier):
    return B+f'/system/document-approvals/CrmQuote/{identifier}'


def new_reviewer(client, admin, name):
    assert client.post(B+'/users', headers=admin, json={
        'username': name, 'password': 'secure-pass-123', 'roles': ['admin']}).status_code == 201
    token = client.post(B+'/auth/login', json={'username': name, 'password': 'secure-pass-123'}).json()['token']
    return {'Authorization': 'Bearer '+token}


def test_steps_freeze_party_labels_and_policy_before_final_approval(quotation):
    client, admin, reviewer, _, quote, opportunity, data = quotation
    with orm_session(write=True) as db:
        workflow.save_policy(db, 'CrmQuote', [{'name': name, 'role': None}
            for name in ('审核', '核准', '批准')], 1, 1)
        db.get(Customer, quote['customer_id']).name = '送审时客户名'
        db.get(Material, data['lines'][0]['material_id']).name = '送审时物料名'
    sent = action(client, admin, quote, 'submit', reason='固定商务与附件依据')
    assert sent['party']['customer_name'] == '送审时客户名'
    assert sent['lines'][0]['material_name'] == '送审时物料名'
    assert sent['version'] == 2 and sent['approval']['version'] == 1
    with orm_session(write=True) as db:
        db.get(Customer, quote['customer_id']).name = '后续客户名'
        db.get(Material, data['lines'][0]['material_id']).name = '后续物料名'
        workflow.save_policy(db, 'CrmQuote', [{'name': '新模板', 'role': None}], 2, 1)
    path = endpoint(quote['id'])
    state = client.get(path, headers=reviewer).json()
    assert state['content_matches'] and state['policy_version'] == 2
    assert state['summary'][0]['value'] == '送审时客户名'
    assert any(row['label'].endswith('送审时物料名') for row in state['summary'])
    action(client, admin, sent, 'approve', status=403)
    first = action(client, reviewer, sent, 'approve')
    assert first['status'] == first['approval']['status'] == 'submitted'
    action(client, reviewer, first, 'approve', status=403)
    # 原转单接口也不能越过尚未完成的核准、批准步骤。
    action(client, admin, first, 'convert', status=409, opportunity_version=1, acceptance_reference='接受依据')
    for name in ('quote_check', 'quote_authorize'):
        first = action(client, new_reviewer(client, admin, name), first, 'approve')
    assert first['status'] == first['approval']['status'] == 'approved'
    assert [step['name'] for step in first['approval']['steps']] == ['审核', '核准', '批准']
    assert client.get(path, headers=admin).json()['events'][0]['reason'] == '固定商务与附件依据'


def test_attachment_authors_cannot_review_quote_or_derived_order(quotation):
    client, admin, reviewer, _, quote, opportunity, _ = quotation
    path = C+f'/quotes/{quote["id"]}/attachments'
    added = client.post(path, headers=reviewer, json=attachment())
    assert added.status_code == 201, added.text
    quote = action(client, admin, quote, 'submit')
    action(client, reviewer, quote, 'approve', status=403)
    independent = new_reviewer(client, admin, 'quote_attachment_review')
    quote = action(client, independent, quote, 'approve')
    converted = action(client, admin, quote, 'convert', opportunity_version=1, acceptance_reference='客户签字')
    child = next(row for row in client.get(B+'/sales-orders', headers=admin).json()
                 if row['id'] == converted['sales_order_id'])
    assert child['status'] == 'draft' and child['approval']['version'] == 0
    child_path = B+f'/system/document-approvals/SalesOrder/{child["id"]}'
    sent = client.post(child_path+'/submit', headers=admin, json={'version': 0})
    assert sent.status_code == 200, sent.text
    assert not client.get(child_path, headers=reviewer).json()['can_review']
    assert client.post(child_path+'/approve', headers=reviewer, json={'version': 1}).status_code == 403


def test_pending_and_approved_attachments_are_locked_until_withdraw(quotation):
    client, admin, reviewer, _, quote, _, _ = quotation
    path = C+f'/quotes/{quote["id"]}/attachments'
    item = client.post(path, headers=admin, json=attachment()).json()
    quote = action(client, admin, quote, 'submit')
    for stage in ('submitted', 'approved'):
        assert quote['status'] == stage
        assert not client.get(path, headers=admin).json()['can_modify']
        assert client.post(path, headers=admin, json=attachment(PDF+b'new')).status_code == 409
        assert client.post(path+f'/{item["id"]}/reverse', headers=admin, json={'reason': '替换'}).status_code == 409
        assert client.get(path+f'/{item["id"]}', headers=admin).content == PDF
        if stage == 'submitted':
            quote = action(client, reviewer, quote, 'approve')
    action(client, admin, quote, 'cancel', status=409)
    quote = action(client, admin, quote, 'withdraw')
    assert quote['status'] == 'draft'
    assert client.post(path+f'/{item["id"]}/reverse', headers=reviewer, json={'reason': '核实错误附件'}).status_code == 201
    quote = action(client, admin, quote, 'submit')
    action(client, reviewer, quote, 'approve', status=403)
    state = client.get(endpoint(quote['id']), headers=admin).json()
    assert any('已撤销' in row['value'] for row in state['summary'])
    quote = action(client, admin, quote, 'withdraw')
    assert action(client, admin, quote, 'cancel')['status'] == 'cancelled'


def test_customer_scope_and_old_clients_cannot_bypass_steps(quotation):
    client, admin, reviewer, seller, quote, _, _ = quotation
    for command, person in (('submit', admin), ('approve', reviewer), ('reject', reviewer)):
        assert client.post(C+f'/quotes/{quote["id"]}/{command}', headers=person,
                           json={'version': 1, 'reason': '旧客户端'}).status_code == 409
    with orm_session(write=True) as db:
        db.get(Customer, quote['customer_id']).owner_id = 1
    path = endpoint(quote['id'])
    assert client.get(path, headers=seller).status_code == 404
    for command in ('submit', 'approve', 'reject', 'withdraw'):
        assert client.post(path+'/'+command, headers=seller, json={'version': 0, 'reason': '跨客户'}).status_code == 404
    # 旧端点也先执行原客户范围检查，不能暴露其他客户的记录状态。
    assert client.post(C+f'/quotes/{quote["id"]}/submit', headers=seller,
                       json={'version': 1, 'reason': '旧客户端跨客户'}).status_code == 404


def test_dynamic_expiry_between_steps_does_not_block_rejection(quotation, monkeypatch):
    client, admin, reviewer, _, quote, _, _ = quotation
    with orm_session(write=True) as db:
        workflow.save_policy(db, 'CrmQuote', [{'name': name, 'role': None}
            for name in ('审核', '批准')], 1, 1)
    quote = action(client, admin, quote, 'submit')
    quote = action(client, reviewer, quote, 'approve')
    other = new_reviewer(client, admin, 'quote_expiry_review')
    monkeypatch.setattr(crm_quotes, 'today', lambda: '2030-02-01')
    action(client, other, quote, 'approve', status=409)
    rejected = action(client, other, quote, 'reject', reason='有效期已过')
    assert rejected['status'] == 'rejected' and rejected['approval']['status'] == 'rejected'


def test_reason_and_versions_preserve_quote_and_approval_history(quotation):
    client, admin, reviewer, _, quote, _, _ = quotation
    for command, person in (('submit', admin),):
        action(client, person, quote, command, reason=' ', status=422)
    sent = action(client, admin, quote, 'submit')
    action(client, reviewer, sent, 'approve', reason='', status=422)
    action(client, reviewer, quote, 'approve', status=409)
    state = client.get(endpoint(quote['id']), headers=admin).json()
    assert state['version'] == 1 and len(state['events']) == 1
    assert client.get(C+f'/records/quote/{quote["id"]}', headers=admin).json()['version'] == 2


def test_prepare_freeze_and_author_registration_roll_back_on_submit_failure(quotation, monkeypatch):
    client, admin, _, seller, quote, _, data = quotation
    with orm_session(write=True) as db:
        db.get(Material, data['lines'][0]['material_id']).name = '提交前改名'
    original = workflow.append_event
    def fail(db, row, action, *args, **kwargs):
        original(db, row, action, *args, **kwargs)
        if action == 'submit':
            raise RuntimeError('模拟送审事件写入后失败')
    monkeypatch.setattr(workflow, 'append_event', fail)
    action(client, seller, quote, 'submit', status=500)
    restored = client.get(C+f'/records/quote/{quote["id"]}', headers=admin).json()
    assert restored == quote
    with orm_session() as db:
        assert list(db.scalars(select(DocumentApprovalCase))) == []
        assert list(db.scalars(select(DocumentApprovalEvent))) == []
        assert db.get(DocumentApprovalAuthor, ('CrmQuote', quote['id'], 3)) is None
        assert len(list(db.scalars(select(CrmChange).where(CrmChange.entity_kind == 'quote')))) == 1


def test_execution_event_failure_rolls_back_quote_opportunity_and_child(quotation, monkeypatch):
    client, admin, reviewer, _, quote, opportunity, _ = quotation
    quote = action(client, admin, quote, 'submit')
    quote = action(client, reviewer, quote, 'approve')
    original = workflow.append_event
    def fail(db, row, action, *args, **kwargs):
        original(db, row, action, *args, **kwargs)
        if action == 'execute':
            raise RuntimeError('模拟执行事件写入后失败')
    monkeypatch.setattr(workflow, 'append_event', fail)
    action(client, admin, quote, 'convert', status=500, opportunity_version=1, acceptance_reference='客户确认')
    assert client.get(C+f'/records/quote/{quote["id"]}', headers=admin).json() == quote
    with orm_session() as db:
        assert list(db.scalars(select(SalesOrder))) == []
        assert db.get(CrmOpportunity, opportunity['id']).version == 1
        assert db.scalar(select(DocumentApprovalCase).where(DocumentApprovalCase.document_type == 'CrmQuote')).status == 'approved'
    monkeypatch.setattr(workflow, 'append_event', original)
    converted = action(client, admin, quote, 'convert', opportunity_version=1, acceptance_reference='客户确认')
    state = client.get(endpoint(quote['id']), headers=admin).json()
    assert state['status'] == 'executed' and len(state['events']) == 3
    action(client, admin, converted, 'convert', status=409, opportunity_version=2, acceptance_reference='重复')


def test_legacy_approved_is_archived_and_converted_history_is_readonly(quotation):
    client, admin, reviewer, _, quote, _, _ = quotation
    # 用旧主单原字段构造升级前事实，不补造新步骤或新批准人员。
    with orm_session(write=True) as db:
        row = db.get(CrmQuote, quote['id'])
        row.status, row.submitted_by, row.reviewed_by = 'approved', 1, 2
        row.submitted_at, row.reviewed_at = '2025-01-01 01:00:00', '2025-01-01 02:00:00'
    legacy = client.get(C+f'/records/quote/{quote["id"]}', headers=admin).json()
    action(client, admin, legacy, 'convert', status=409, opportunity_version=1, acceptance_reference='旧批准')
    state = client.get(endpoint(quote['id']), headers=admin).json()
    assert state['version'] == 0 and state['can_submit']
    sent = action(client, admin, legacy, 'submit')
    approved = action(client, reviewer, sent, 'approve')
    with orm_session() as db:
        first = db.scalar(select(DocumentApprovalEvent).order_by(DocumentApprovalEvent.id))
        prior = json.loads(first.state_json)['prior_native_review']
        assert prior['status'] == 'approved' and prior['reviewed_at'] == '2025-01-01 02:00:00'
    converted = action(client, admin, approved, 'convert', opportunity_version=1, acceptance_reference='新接受依据')
    assert converted['approval']['status'] == 'executed'
    assert not client.get(endpoint(quote['id']), headers=admin).json()['can_submit']


def test_concurrent_submit_only_freezes_and_versions_once(quotation):
    client, admin, _, _, quote, _, _ = quotation
    def run(_):
        return client.post(endpoint(quote['id'])+'/submit', headers=admin,
            json={'version': 0, 'reason': '并发送审'}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, (1, 2))) == [200, 409]
    saved = client.get(C+f'/records/quote/{quote["id"]}', headers=admin).json()
    assert saved['version'] == 2 and saved['approval']['version'] == 1
    assert len(client.get(endpoint(quote['id']), headers=admin).json()['events']) == 1


def test_maximum_quote_lines_and_attachment_summaries_stay_bounded(quotation):
    client, admin, _, _, quote, _, payload = quotation
    # 最大合法正文仍能在受限协议返回，不能因为附件摘要占位挤掉物料依据。
    with orm_session(write=True) as db:
        rows = [Material(sku=f'QA-LINE-{index}', name=f'上限物料{index}', unit='件') for index in range(98)]
        db.add_all(rows)
        db.flush()
        materials = [row.id for row in rows]
    edited = client.put(C+f'/quotes/{quote["id"]}', headers=admin, json={**payload,
        'version': 1, 'reason': '验证最大合法明细', 'lines': [*payload['lines'],
            *[{'material_id': identifier, 'quantity': '1', 'unit_price': '1'} for identifier in materials]]})
    assert edited.status_code == 200, edited.text
    for index in range(10):
        assert client.post(C+f'/quotes/{quote["id"]}/attachments', headers=admin,
            json=attachment(PDF+str(index).encode())).status_code == 201
    state = client.get(endpoint(quote['id']), headers=admin).json()
    assert len(state['summary']) == 117
    assert len([row for row in state['summary'] if row['label'] == '附件依据']) == 10
