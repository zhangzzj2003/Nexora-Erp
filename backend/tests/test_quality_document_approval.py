"""处置分步批准、真实隔离数量、派生返工与独立更正的事务边界。"""

from concurrent.futures import ThreadPoolExecutor

from fastapi import HTTPException

from app.core import document_approval as workflow
from app.core.models import QualityDisposition
from app.core.orm import orm_session, add_model
from test_quality_rework import quality_erp, payload, action, ROOT
from approval_test_helpers import approve_document


def path(row):
    return f'system/document-approvals/QualityDisposition/{row["id"]}'


def approval_reviewers(api):
    # 各步骤账号各自独立，业务提交人员与执行人员不能替代审核人。
    for index in range(1, 4):
        name = f'quality_step_{index}'
        api('POST', 'users', {'username': name, 'password': 'quality-step-pass-123', 'roles': ['finance']}, 201)
    tokens = [api('POST', 'auth/login', {'username': f'quality_step_{index}',
        'password': 'quality-step-pass-123'})['token'] for index in range(1, 4)]
    return [{'Authorization': 'Bearer ' + token} for token in tokens]


def test_three_steps_fixed_source_child_independent_and_cost_privacy(quality_erp):
    client, admin, actors, api, raw, _, order, _ = quality_erp
    _, completion = order('2', '0')
    reviewers = approval_reviewers(api)
    policy = api('GET', 'system/document-approvals/QualityDisposition')
    api('PUT', 'system/document-approvals/QualityDisposition', {'version': policy['version'],
        'steps': [{'name': name, 'role': 'finance'} for name in ('审核', '核准', '批准')]})
    row = api('POST', ROOT + '/dispositions', payload(completion, kind='rework', quantity='2',
        materials=[{'material_id': raw, 'quantity': '1'}]), 201, actors['author'])
    submitted = action(api, row, 'submit', actors['author'])
    state = api('GET', path(row), actor=actors['keeper'])
    assert state['steps'][1]['name'] == '核准' and state['content_matches']
    assert not any('amount' in item['value'] or '单价' in item['value'] for item in state['summary'])
    action(api, submitted, 'post', status=409)
    action(api, submitted, 'approve', actors['author'], 403)
    api('PUT', 'system/document-approvals/QualityDisposition', {'version': policy['version'] + 1,
        'steps': [{'name': '后续模板', 'role': None}]})
    for index, reviewer in enumerate(reviewers):
        previous = submitted
        submitted = action(api, submitted, 'approve', reviewer)
        assert submitted['version'] == previous['version'] + 1
        assert submitted['status'] == ('approved' if index == 2 else 'submitted')
        if index == 0:
            action(api, submitted, 'approve', reviewer, 403)
    posted = action(api, submitted, 'post', actors['keeper'])
    assert posted['approval']['status'] == 'executed'
    child = next(item for item in api('GET', 'work-orders') if item['id'] == posted['rework_order_id'])
    assert child['status'] == 'draft' and child['lines'][0]['required_quantity'] == '1'
    api('POST', f'work-orders/{child["id"]}/release', status=409)
    child_state = api('POST', f'system/document-approvals/WorkOrder/{child["id"]}/submit', {'version': 0})
    api('POST', f'system/document-approvals/WorkOrder/{child["id"]}/approve',
        {'version': child_state['version']}, 403, actors['author'])
    # 返工仅建草稿，不制造成品入库或再次消耗原不合格品。
    assert not any(m['source_type'] == 'production_completion' for m in api('GET', 'inventory/valuation')['movements'])
    assert [item['action'] for item in api('GET', path(row))['events']] == ['submit', 'approve', 'approve', 'approve', 'execute']


def test_old_client_reasons_withdraw_reservations_and_permissions(quality_erp):
    _, _, actors, api, _, _, order, _ = quality_erp
    _, completion = order('1', '0')
    row = api('POST', ROOT + '/dispositions', payload(completion), 201, actors['author'])
    for command in ('submit', 'approve', 'reject'):
        api('POST', f'{ROOT}/dispositions/{row["id"]}/{command}', {'version': 1, 'reason': '旧客户端'}, 409)
    api('GET', path(row), status=403, actor=actors['seller'])
    for reason in (' ', '字' * 201):
        api('POST', path(row) + '/submit', {'version': 0, 'reason': reason}, 422, actors['author'])
    submitted = action(api, row, 'submit', actors['author'])
    assert api('GET', ROOT)['cases'][0]['remaining_quantity'] == '0'
    action(api, submitted, 'cancel', status=409)
    withdrawn = action(api, submitted, 'withdraw', actors['author'])
    assert withdrawn['status'] == 'draft' and api('GET', ROOT)['cases'][0]['remaining_quantity'] == '1'
    cancelled = action(api, withdrawn, 'cancel', actors['author'])
    assert cancelled['status'] == 'cancelled'


def test_editor_author_propagation_and_fixed_material_labels(quality_erp):
    client, admin, actors, api, raw, _, order, _ = quality_erp
    _, completion = order('1', '0')
    data = payload(completion, kind='rework', materials=[{'material_id': raw, 'quantity': '1'}])
    row = api('POST', ROOT + '/dispositions', data, 201, actors['author'])
    row = api('PUT', f'{ROOT}/dispositions/{row["id"]}', {**data, 'version': row['version']})
    row = action(api, row, 'submit', actors['author'])
    action(api, row, 'approve', status=403)
    row = action(api, row, 'approve', actors['reviewer'])
    row = action(api, row, 'post', actors['keeper'])
    child_path = f'system/document-approvals/WorkOrder/{row["rework_order_id"]}'
    state = api('POST', child_path + '/submit', {'version': 0})
    for actor in (admin, actors['author'], actors['keeper']):
        api('POST', child_path + '/approve', {'version': state['version']}, 403, actor)
    assert api('GET', path(row))['content_matches']


def test_submit_failure_restores_frozen_source_and_audit(quality_erp, monkeypatch):
    _, _, actors, api, _, _, order, _ = quality_erp
    _, completion = order('1', '0')
    row = api('POST', ROOT + '/dispositions', payload(completion), 201, actors['author'])
    from app.production import quality
    original = quality.audit
    def fail(*args):
        original(*args)
        raise HTTPException(409, '模拟原处置审计失败')
    monkeypatch.setattr(quality, 'audit', fail)
    api('POST', path(row) + '/submit', {'version': 0, 'reason': '送审依据'}, 409, actors['author'])
    assert api('GET', f'{ROOT}/dispositions/{row["id"]}') == row
    assert api('GET', path(row))['events'] == []
    assert api('GET', ROOT)['cases'][0]['remaining_quantity'] == '1'


def test_execute_event_failure_rolls_back_child_and_native_version(quality_erp, monkeypatch):
    client, admin, actors, api, _, _, order, _ = quality_erp
    _, completion = order('1', '0')
    row = api('POST', ROOT + '/dispositions', payload(completion, kind='rework'), 201)
    approve_document(client, admin, 'QualityDisposition', row['id'], reason='返工复核')
    row = api('GET', f'{ROOT}/dispositions/{row["id"]}')
    original = workflow.mark_executed
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise HTTPException(409, '模拟执行事件失败')
    monkeypatch.setattr(workflow, 'mark_executed', fail)
    action(api, row, 'post', status=409)
    assert api('GET', f'{ROOT}/dispositions/{row["id"]}') == row
    assert len(api('GET', 'work-orders')) == 1
    assert api('GET', path(row))['status'] == 'approved'


def test_independent_correction_fixed_reason_and_pending_child_dependency(quality_erp):
    client, admin, actors, api, _, _, order, _ = quality_erp
    _, completion = order('1', '0')
    row = api('POST', ROOT + '/dispositions', payload(completion, kind='rework'), 201)
    approve_document(client, admin, 'QualityDisposition', row['id'], reason='返工复核')
    row = action(api, api('GET', f'{ROOT}/dispositions/{row["id"]}'), 'post', actors['keeper'])
    action(api, row, 'reverse', status=409)
    submitted = api('POST', path(row) + '/submit', {'version': 0, 'intent': 'reverse', 'reason': '原方案误录'})
    for actor in (admin, actors['keeper']):
        api('POST', path(row) + '/approve', {'intent': 'reverse', 'version': submitted['version'], 'reason': '自审'}, 403, actor)
    approved = api('POST', path(row) + '/approve', {'intent': 'reverse', 'version': submitted['version'], 'reason': '独立核对'}, actor=actors['reviewer'])
    action(api, row, 'reverse', reason='更换原因', status=409)
    child_path = f'system/document-approvals/WorkOrder/{row["rework_order_id"]}'
    child = api('POST', child_path + '/submit', {'version': 0})
    action(api, row, 'reverse', reason='原方案误录', status=409)
    assert api('GET', path(row) + '?intent=reverse')['status'] == 'approved'
    api('POST', child_path + '/withdraw', {'version': child['version']})
    result = action(api, row, 'reverse', reason='原方案误录')
    assert result['status'] == 'reversed' and result['reversal_approval']['status'] == 'executed'
    assert api('GET', ROOT)['cases'][0]['remaining_quantity'] == '1'
    child_order = next(item for item in api('GET', 'work-orders') if item['id'] == row['rework_order_id'])
    assert child_order['status'] == 'cancelled'
    assert api('GET', path(row))['content_matches']


def test_legacy_pending_requires_new_approval_and_posted_history_is_readonly(quality_erp):
    client, admin, _, api, _, _, order, _ = quality_erp
    _, completion = order('2', '0')
    draft = api('POST', ROOT + '/dispositions', payload(completion, reference='LEGACY-PENDING'), 201)
    with orm_session(write=True) as db:
        old = db.get(QualityDisposition, draft['id'])
        old.status, old.reviewed_by, old.reviewed_at = 'approved', 1, '2026-10-01 00:00:00'
        historical = add_model(db, QualityDisposition(completion_id=old.completion_id, reference='LEGACY-POSTED',
            kind=old.kind, quantity=old.quantity, loss_treatment=old.loss_treatment, defect=old.defect,
            action_note=old.action_note, source_json=old.source_json, materials_json=old.materials_json,
            status='posted', version=4, created_by=1, posted_by=1, posted_at='2026-10-01 00:00:00'))
        historical_id = historical.id
    action(api, api('GET', f'{ROOT}/dispositions/{draft["id"]}'), 'post', status=409)
    state = api('GET', path(draft))
    assert state['version'] == 0 and any('升级前' in item['label'] for item in state['summary'])
    state = api('GET', f'system/document-approvals/QualityDisposition/{historical_id}')
    assert not state['can_submit'] and state['events'] == []
    # 升级不补造审批；旧已执行处置仍可按独立更正流程纠正。
    approve_document(client, admin, 'QualityDisposition', historical_id, intent='reverse', reason='历史更正')
    action(api, api('GET', f'{ROOT}/dispositions/{historical_id}'), 'reverse', reason='历史更正')


def test_concurrent_submit_has_one_generation(quality_erp):
    client, admin, _, api, _, _, order, _ = quality_erp
    _, completion = order('1', '0')
    row = api('POST', ROOT + '/dispositions', payload(completion), 201)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post('/api/v1/' + path(row) + '/submit',
            headers=admin, json={'version': 0, 'reason': '并发送审依据'}), range(2)))
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert len(api('GET', path(row))['events']) == 1


def test_hundred_fixed_materials_fit_approval_summary(quality_erp):
    _, _, _, api, _, _, order, _ = quality_erp
    _, completion = order('1', '0')
    from app.core.models import Material
    # 使用真实材料和服务端方案上限，覆盖一百行加正文及旧流程的摘要边界。
    with orm_session(write=True) as db:
        identifiers = [add_model(db, Material(sku=f'Q-MAX-{i}', name=f'追加材料{i}', unit='个')).id for i in range(100)]
    row = api('POST', ROOT + '/dispositions', payload(completion, kind='rework',
        materials=[{'material_id': identifier, 'quantity': '1'} for identifier in identifiers]), 201)
    state = api('POST', path(row) + '/submit', {'version': 0, 'reason': '逐行核对材料'})
    assert len(state['summary']) == 109
    assert sum(item['label'] == '追加材料' for item in state['summary']) == 100
    assert state['summary'][0]['value'] == completion['document_no']
