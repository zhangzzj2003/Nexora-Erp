"""固定计划分步审批、剩余建议转换和派生单据职责分离。"""

import json
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor

from fastapi import HTTPException
from sqlalchemy import select

from app.core import document_approval as workflow
from app.core.models import MrpPlan, MrpConversion, PurchaseRequest, WorkOrder
from app.core.orm import orm_session
from test_mrp import seeded, payload, approved, approval_action, BASE, MRP


def path(identifier):
    return BASE + f'/system/document-approvals/MrpPlan/{identifier}'


def plan_detail(client, admin, identifier):
    return client.get(MRP + f'/plans/{identifier}', headers=admin).json()


def convert(client, actor, row, suggestion, status=201):
    response = client.post(MRP + f'/plans/{row["id"]}/convert', headers=actor, json={
        'version': row['version'], 'suggestion_key': suggestion['key'], 'warehouse_id': 1, 'reason': '按固定建议转单'})
    assert response.status_code == status, response.text
    return response.json()


def test_three_steps_partial_conversion_and_independent_children(seeded):
    client, admin, reviewer, planner, _, materials, _ = seeded
    reviewers = [reviewer]
    for index in (2, 3):
        username = f'mrp_step_{index}'
        assert client.post(BASE + '/users', headers=admin, json={
            'username': username, 'password': 'secure-pass-123', 'roles': ['admin']}).status_code == 201
        token = client.post(BASE + '/auth/login', json={'username': username, 'password': 'secure-pass-123'}).json()['token']
        reviewers.append({'Authorization': 'Bearer ' + token})
    policy = client.get(BASE + '/system/document-approvals/MrpPlan', headers=admin).json()
    assert client.put(BASE + '/system/document-approvals/MrpPlan', headers=admin, json={
        'version': policy['version'], 'steps': [{'name': name, 'role': None} for name in ('审核', '核准', '批准')]}).status_code == 200
    row = client.post(MRP + '/plans', headers=admin, json=payload(client, admin, materials)).json()
    initial = plan_detail(client, admin, row['id'])
    stock = client.get(BASE + '/stock', headers=admin).json()
    approval_action(client, planner, row['id'], 'submit', '固定需求和供给日期')
    state = client.get(path(row['id']), headers=admin).json()
    assert state['can_review']
    # 模板修改只作用下一轮，当前三步和完整计算快照继续固定。
    assert client.put(BASE + '/system/document-approvals/MrpPlan', headers=admin, json={
        'version': policy['version'] + 1, 'steps': [{'name': '新模板', 'role': None}]}).status_code == 200
    for index, actor in enumerate(reviewers):
        row = approval_action(client, actor, row['id'], 'approve', '核对原固定结果')
        assert row['status'] == ('approved' if index == 2 else 'submitted')
        if index < 2:
            convert(client, planner, row, initial['snapshot']['suggestions'][0], 409)
            current = client.get(path(row['id']), headers=actor).json()
            assert current['can_review']
    suggestions = initial['snapshot']['suggestions']
    first = convert(client, planner, row, suggestions[0])
    child_type = 'WorkOrder' if first['work_order_id'] else 'PurchaseRequest'
    child_id = first['work_order_id'] or first['purchase_request_id']
    child_path = BASE + f'/system/document-approvals/{child_type}/{child_id}'
    child = client.get(child_path, headers=admin).json()
    assert child['business_status'] == 'draft' and child['status'] == 'draft'
    sent = client.post(child_path + '/submit', headers=admin, json={'version': 0}).json()
    assert client.get(child_path, headers=admin).json()['can_review']
    assert client.post(child_path + '/approve', headers=planner, json={'version': sent['version']}).status_code == 403
    # 其他建议的转换人不进入已生成子单的作者摘要，也不重复执行原计划。
    row = plan_detail(client, admin, row['id'])
    assert row['approval']['status'] == 'executed'
    convert(client, reviewers[2], row, suggestions[1])
    assert client.get(child_path, headers=admin).json()['content_matches']
    row = plan_detail(client, admin, row['id'])
    convert(client, planner, row, suggestions[2])
    final = client.get(path(row['id']), headers=admin).json()
    assert [event['action'] for event in final['events']] == ['submit', 'approve', 'approve', 'approve', 'execute']
    assert not final['can_submit'] and not final['can_withdraw'] and final['content_matches']
    assert plan_detail(client, admin, row['id'])['snapshot'] == initial['snapshot']
    assert client.get(BASE + '/stock', headers=admin).json() == stock


def test_old_client_reason_versions_permissions_and_withdraw(seeded):
    client, admin, reviewer, planner, viewer, materials, _ = seeded
    row = client.post(MRP + '/plans', headers=admin, json=payload(client, admin, materials)).json()
    for action in ('submit', 'approve', 'reject'):
        assert client.post(MRP + f'/plans/{row["id"]}/{action}', headers=admin,
            json={'version': row['version'], 'reason': '旧入口'}).status_code == 409
    assert client.get(path(row['id']), headers=viewer).status_code == 403
    for reason in (' ', '字' * 501):
        assert client.post(path(row['id']) + '/submit', headers=planner, json={'version': 0, 'reason': reason}).status_code == 422
    row = approval_action(client, planner, row['id'], 'submit', '提交依据')
    assert client.post(MRP + f'/plans/{row["id"]}/cancel', headers=planner,
        json={'version': row['version'], 'reason': '待审取消'}).status_code == 409
    assert client.post(path(row['id']) + '/approve', headers=reviewer, json={'version': 0, 'reason': '旧审批版本'}).status_code == 409
    row = approval_action(client, planner, row['id'], 'withdraw', '')
    assert row['status'] == 'draft'
    assert client.post(MRP + f'/plans/{row["id"]}/cancel', headers=planner,
        json={'version': row['version'], 'reason': '撤回后取消'}).status_code == 200


def test_stale_sources_block_approval_but_allow_rejection_without_rewriting(seeded):
    client, admin, reviewer, _, _, materials, _ = seeded
    row = client.post(MRP + '/plans', headers=admin, json=payload(client, admin, materials)).json()
    initial = plan_detail(client, admin, row['id'])
    approval_action(client, admin, row['id'], 'submit', '确认原来源')
    assert client.put(MRP + f'/policies/{materials[2]}', headers=admin, json={
        'version': 0, 'supply_mode': 'buy', 'lead_time_days': 2, 'safety_stock': '0',
        'minimum_quantity': '0', 'multiple_quantity': '0', 'reason': '改变供应周期'}).status_code == 200
    state = client.get(path(row['id']), headers=reviewer).json()
    assert client.post(path(row['id']) + '/approve', headers=reviewer,
        json={'version': state['version'], 'reason': '过期批准'}).status_code == 409
    rejected = approval_action(client, reviewer, row['id'], 'reject', '来源已变化，要求重算')
    assert rejected['status'] == 'rejected'
    assert plan_detail(client, admin, row['id'])['snapshot'] == initial['snapshot']


def test_execution_event_failure_rolls_back_target_link_versions_and_audit(seeded, monkeypatch):
    client, admin, reviewer, planner, _, materials, _ = seeded
    row = approved(client, admin, reviewer, payload(client, admin, materials))
    initial = plan_detail(client, admin, row['id'])
    original = workflow.append_event
    def fail(db, case, action, *args):
        original(db, case, action, *args)
        if case.document_type == 'MrpPlan' and action == 'execute':
            raise HTTPException(409, '模拟计划执行事件故障')
    monkeypatch.setattr(workflow, 'append_event', fail)
    convert(client, planner, row, initial['snapshot']['suggestions'][0], 409)
    with orm_session() as db:
        assert not list(db.scalars(select(MrpConversion)))
        assert not list(db.scalars(select(WorkOrder)))
        assert not list(db.scalars(select(PurchaseRequest)))
    assert plan_detail(client, admin, row['id'])['version'] == initial['version']
    state = client.get(path(row['id']), headers=admin).json()
    assert state['status'] == 'approved' and len(state['events']) == 2
    assert len(client.get(MRP + f'/plans/{row["id"]}/changes', headers=admin).json()) == 3


def test_submit_audit_failure_restores_native_state_and_approval(seeded, monkeypatch):
    client, admin, _, _, _, materials, _ = seeded
    row = client.post(MRP + '/plans', headers=admin, json=payload(client, admin, materials)).json()
    from app.production import mrp
    original = mrp.record_change
    def fail(db, record, action, *args):
        original(db, record, action, *args)
        if action == 'submit':
            raise HTTPException(409, '模拟计划原审计失败')
    monkeypatch.setattr(mrp, 'record_change', fail)
    assert client.post(path(row['id']) + '/submit', headers=admin, json={'version': 0, 'reason': '提交依据'}).status_code == 409
    current = plan_detail(client, admin, row['id'])
    assert current['status'] == 'draft' and current['version'] == row['version']
    assert client.get(path(row['id']), headers=admin).json()['events'] == []


def test_legacy_approval_is_history_and_cannot_authorize_conversion(seeded):
    client, admin, reviewer, planner, _, materials, _ = seeded
    row = client.post(MRP + '/plans', headers=admin, json=payload(client, admin, materials)).json()
    reviewer_id = client.get(BASE + '/auth/me', headers=reviewer).json()['id']
    with orm_session(write=True) as db:
        source = db.get(MrpPlan, row['id'])
        source.status, source.submitted_by, source.reviewed_by = 'approved', source.created_by, reviewer_id
        source.submitted_at = source.reviewed_at = '2026-10-07 12:00:00'
    detail = plan_detail(client, admin, row['id'])
    convert(client, planner, detail, detail['snapshot']['suggestions'][0], 409)
    state = client.get(path(row['id']), headers=admin).json()
    assert state['events'] == [] and state['status'] == 'draft'
    assert any('升级前流程记录' in item['label'] for item in state['summary'])
    approval_action(client, admin, row['id'], 'submit', '升级后确认来源')
    row = approval_action(client, reviewer, row['id'], 'approve', '重新独立批准')
    convert(client, planner, row, detail['snapshot']['suggestions'][0])
    assert client.get(path(row['id']), headers=admin).json()['content_matches']


def test_concurrent_submission_only_one_generation_and_fixed_body_tampering(seeded):
    client, admin, reviewer, planner, _, materials, _ = seeded
    data = payload(client, admin, materials)
    # 使用真实引擎生成超出摘要展示上限的建议，验证完整正文仍全部参与批准校验。
    data['manual_demands'] = [{'material_id': materials[2], 'quantity': '100',
        'due_date': (date.fromisoformat(data['start_date']) + timedelta(days=index)).isoformat(),
        'reference': f'日需求-{index}'} for index in range(101)]
    row = client.post(MRP + '/plans', headers=admin, json=data).json()
    summary = client.get(path(row['id']), headers=admin).json()['summary']
    assert row['suggestion_count'] == 101 and len(summary) <= 110
    assert sum(item['label'] == '固定供给建议' for item in summary) == 100
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.post(path(row['id']) + '/submit', headers=admin,
            json={'version': 0, 'reason': '并发送审'}).status_code, range(2)))
    assert sorted(results) == [200, 409]
    row = approval_action(client, reviewer, row['id'], 'approve', '独立批准')
    initial = plan_detail(client, admin, row['id'])
    # 即使篡改的尾部记录未在通用摘要展示，完整快照哈希仍会拒绝转换。
    with orm_session(write=True) as db:
        source = db.get(MrpPlan, row['id'])
        content = json.loads(source.snapshot_json)
        content['rows'][-1]['gross_quantity'] = '999.000'
        source.snapshot_json = json.dumps(content, ensure_ascii=False)
    convert(client, planner, row, initial['snapshot']['suggestions'][0], 409)
    assert not client.get(path(row['id']), headers=admin).json()['content_matches']
