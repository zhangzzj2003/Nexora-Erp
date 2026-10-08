"""采购申请统一步骤、拆单授权、来源作者及历史记录的真实事务验证。"""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select

from approval_test_helpers import approve_document
from test_document_approval import context
from test_purchase_document_approval import reviewer
from test_mrp import seeded as mrp_erp, approved as approve_mrp, payload as plan_payload, MRP
from test_equipment import erp as equipment_erp, approved as approve_job
from app.core import document_approval as workflow
from app.core.approval_documents import purchase_request_snapshot
from app.core.models import (DocumentApprovalEvent, PurchaseRequest, PurchaseRequestLine,
    PurchaseOrder, PurchaseOrderLine, PurchaseOrderRequestLink)
from app.core.orm import orm_session, add_model


@pytest.fixture
def requisition(context):
    client, auth, inbound = context
    supplier = client.post('/api/v1/suppliers', headers=auth, json={'name': '申请供应商'}).json()['id']
    created = client.post('/api/v1/purchase-requests', headers=auth, json={
        'reference': '申请依据', 'note': '生产备料',
        'lines': [{'material_id': inbound['lines'][0]['material_id'], 'quantity': '10'}]})
    assert created.status_code == 201, created.text
    return client, auth, supplier, created.json()


def path(identifier):
    return f'/api/v1/system/document-approvals/PurchaseRequest/{identifier}'


def order_input(supplier, source, quantity='4'):
    return {'supplier_id': supplier, 'purchase_request_id': source['id'], 'lines': [{
        'purchase_request_line_id': source['lines'][0]['id'], 'material_id': source['lines'][0]['material_id'],
        'quantity': quantity, 'unit_price': '2'}]}


def test_steps_do_not_approve_native_early_and_allow_authorized_self_review(requisition):
    client, auth, supplier, source = requisition
    with orm_session(write=True) as db:
        workflow.save_policy(db, 'PurchaseRequest', [{'name': name, 'role': None}
            for name in ('审核', '核准', '批准')], 1, 1)
    endpoint = path(source['id'])
    state = client.post(endpoint + '/submit', headers=auth, json={'version': 0}).json()
    assert client.get((endpoint + '/approve').removesuffix('/approve'), headers=auth, params={'intent': 'execute'}).json()['can_review']
    review = reviewer(client)
    state = client.post(endpoint + '/approve', headers=review, json={'version': state['version']}).json()
    assert state['status'] == 'submitted' and state['business_status'] == 'submitted'
    assert client.post('/api/v1/purchase-orders', headers=auth,
        json=order_input(supplier, source)).status_code == 409
    assert client.get((endpoint + '/approve').removesuffix('/approve'), headers=review, params={'intent': 'execute'}).json()['can_review']
    # 另外两步分别使用独立人员，旧版本不能覆盖已经作出的审核决定。
    for index in (2, 3):
        name = f'approval_step_{index}'
        client.post('/api/v1/users', headers=auth, json={
            'username': name, 'password': 'secure-pass-123', 'roles': ['admin']})
        token = client.post('/api/v1/auth/login', json={'username': name, 'password': 'secure-pass-123'}).json()['token']
        headers = {'Authorization': 'Bearer ' + token}
        assert client.post(endpoint + '/approve', headers=headers, json={'version': 1}).status_code == 409
        response = client.post(endpoint + '/approve', headers=headers, json={'version': state['version']})
        assert response.status_code == 200, response.text
        state = response.json()
    assert state['status'] == state['business_status'] == 'approved'


def test_editor_can_review_and_pending_cancel_requires_withdraw(requisition):
    client, auth, _, source = requisition
    editor = {'Authorization': 'Bearer ' + client.post('/api/v1/auth/login', json={
        'username': 'editor', 'password': 'secure-pass-123'}).json()['token']}
    payload = {'note': '编辑人员修订', 'lines': [{'material_id': source['lines'][0]['material_id'], 'quantity': '8'}]}
    assert client.put(f"/api/v1/purchase-requests/{source['id']}", headers=editor, json=payload).status_code == 200
    endpoint = path(source['id'])
    sent = client.post(endpoint + '/submit', headers=auth, json={'version': 0})
    assert sent.status_code == 200, sent.text
    assert client.get(endpoint, headers=editor).json()['can_review']
    assert client.get((endpoint + '/approve').removesuffix('/approve'), headers=editor, params={'intent': 'execute'}).json()['can_review']
    assert client.put(f"/api/v1/purchase-requests/{source['id']}", headers=auth, json=payload).status_code == 409
    assert client.post(f"/api/v1/purchase-requests/{source['id']}/cancel", headers=auth).status_code == 409
    assert client.post(endpoint + '/withdraw', headers=auth, json={'version': 1}).status_code == 200
    assert client.post(f"/api/v1/purchase-requests/{source['id']}/cancel", headers=auth).status_code == 200


def test_split_conversions_execute_once_and_each_order_is_its_own_draft(requisition):
    client, auth, supplier, source = requisition
    approve_document(client, auth, 'PurchaseRequest', source['id'])
    orders = []
    for amount in ('4', '6'):
        result = client.post('/api/v1/purchase-orders', headers=auth, json=order_input(supplier, source, amount))
        assert result.status_code == 201, result.text
        child = result.json()
        assert child['status'] == 'draft' and child['approval']['version'] == 0
        assert client.post(f"/api/v1/purchase-orders/{child['id']}/confirm", headers=auth).status_code == 409
        orders.append(child)
    state = client.get(path(source['id']), headers=auth).json()
    assert state['status'] == 'executed'
    assert [event['action'] for event in state['events']].count('execute') == 1
    assert client.post('/api/v1/purchase-orders', headers=auth, json=order_input(supplier, source, '1')).status_code == 409
    assert client.post(f"/api/v1/purchase-orders/{orders[0]['id']}/cancel", headers=auth).status_code == 200
    # 取消草稿释放需求额度，仍使用原固定需求授权，不能对原批准追加另一执行事件。
    assert client.post('/api/v1/purchase-orders', headers=auth, json=order_input(supplier, source, '4')).status_code == 201
    assert client.get(path(source['id']), headers=auth).json()['version'] == state['version']


def test_concurrent_conversion_cannot_overdraw_approved_demand(requisition):
    client, auth, supplier, source = requisition
    approve_document(client, auth, 'PurchaseRequest', source['id'])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.post('/api/v1/purchase-orders', headers=auth,
            json=order_input(supplier, source, '6')).status_code, range(2)))
    assert sorted(results) == [201, 409]
    state = client.get(path(source['id']), headers=auth).json()
    assert len([event for event in state['events'] if event['action'] == 'execute']) == 1


def test_execution_event_failure_rolls_back_child_and_authorization(requisition, monkeypatch):
    client, auth, supplier, source = requisition
    before = approve_document(client, auth, 'PurchaseRequest', source['id'])
    original = workflow.append_event
    def fail(db, case, action, *args, **kwargs):
        original(db, case, action, *args, **kwargs)
        if action == 'execute':
            db.flush()
            raise RuntimeError('模拟执行事件写后故障')
    monkeypatch.setattr(workflow, 'append_event', fail)
    with pytest.raises(RuntimeError, match='模拟执行事件'):
        client.post('/api/v1/purchase-orders', headers=auth, json=order_input(supplier, source))
    state = client.get(path(source['id']), headers=auth).json()
    assert state['status'] == 'approved' and state['version'] == before['version']
    with orm_session() as db:
        assert db.scalar(select(func.count()).select_from(PurchaseOrder)) == 0
        assert db.scalar(select(func.count()).select_from(PurchaseOrderRequestLink)) == 0
    assert client.get('/api/v1/purchase-requests', headers=auth).json()[0]['lines'][0]['remaining_quantity'] == '10'


@pytest.mark.parametrize('field,changed', [('quantity', '11'), ('note', '正文变化')])
def test_changed_approved_body_cannot_be_consumed_even_after_first_conversion(requisition, field, changed):
    client, auth, supplier, source = requisition
    approve_document(client, auth, 'PurchaseRequest', source['id'])
    assert client.post('/api/v1/purchase-orders', headers=auth, json=order_input(supplier, source)).status_code == 201
    with orm_session(write=True) as db:
        row = db.get(PurchaseRequestLine, source['lines'][0]['id']) if field == 'quantity' else db.get(PurchaseRequest, source['id'])
        setattr(row, field, changed)
    assert client.post('/api/v1/purchase-orders', headers=auth, json=order_input(supplier, source)).status_code == 409


def test_old_partially_converted_request_requires_new_approval_and_preserves_old_order(requisition):
    client, auth, supplier, source = requisition
    with orm_session(write=True) as db:
        native = db.get(PurchaseRequest, source['id'])
        native.status, native.submitted_by, native.reviewed_by = 'approved', 1, 2
        native.submitted_at, native.reviewed_at, native.review_reason = '2025-01-01', '2025-01-02', '升级前审核意见'
        old = add_model(db, PurchaseOrder(supplier_id=supplier, reference='旧订单', created_by=1, status='confirmed'))
        line = add_model(db, PurchaseOrderLine(purchase_order_id=old.id,
            material_id=source['lines'][0]['material_id'], quantity='3', unit_price='2'))
        db.add(PurchaseOrderRequestLink(purchase_order_line_id=line.id, purchase_request_line_id=source['lines'][0]['id']))
        old_id, old_no = old.id, old.document_no
    assert client.post('/api/v1/purchase-orders', headers=auth, json=order_input(supplier, source)).status_code == 409
    approved = approve_document(client, auth, 'PurchaseRequest', source['id'])
    assert any('升级前流程' in row['label'] and '升级前审核意见' in row['value'] for row in approved['summary'])
    assert client.post('/api/v1/purchase-orders', headers=auth, json=order_input(supplier, source, '7')).status_code == 201
    with orm_session() as db:
        old = db.get(PurchaseOrder, old_id)
        assert old.document_no == old_no and old.status == 'confirmed'
        case = workflow.find_case(db, 'PurchaseRequest', source['id'])
        first = db.scalar(select(DocumentApprovalEvent).where(DocumentApprovalEvent.case_id == case.id)
                          .order_by(DocumentApprovalEvent.id))
        assert json.loads(first.state_json)['prior_native_review']['review_reason'] == '升级前审核意见'


def test_fully_converted_legacy_request_is_read_only_without_fake_approval(requisition):
    client, auth, supplier, source = requisition
    with orm_session(write=True) as db:
        db.get(PurchaseRequest, source['id']).status = 'approved'
        old = add_model(db, PurchaseOrder(supplier_id=supplier, reference='全量旧订单', created_by=1, status='confirmed'))
        line = add_model(db, PurchaseOrderLine(purchase_order_id=old.id,
            material_id=source['lines'][0]['material_id'], quantity='10', unit_price='2'))
        db.add(PurchaseOrderRequestLink(purchase_order_line_id=line.id, purchase_request_line_id=source['lines'][0]['id']))
    state = client.get(path(source['id']), headers=auth).json()
    assert state['version'] == 0 and not state['can_submit'] and state['events'] == []
    assert client.post(path(source['id']) + '/submit', headers=auth, json={'version': 0}).status_code == 409
    with orm_session() as db:
        assert workflow.find_case(db, 'PurchaseRequest', source['id']) is None


def test_rejected_legacy_remainder_cannot_delete_old_order_source_lines(requisition):
    client, auth, supplier, source = requisition
    with orm_session(write=True) as db:
        db.get(PurchaseRequest, source['id']).status = 'approved'
        old = add_model(db, PurchaseOrder(supplier_id=supplier, reference='待审剩余旧订单', created_by=1, status='confirmed'))
        line = add_model(db, PurchaseOrderLine(purchase_order_id=old.id,
            material_id=source['lines'][0]['material_id'], quantity='3', unit_price='2'))
        db.add(PurchaseOrderRequestLink(purchase_order_line_id=line.id, purchase_request_line_id=source['lines'][0]['id']))
    endpoint = path(source['id'])
    assert client.post(endpoint + '/submit', headers=auth, json={'version': 0}).status_code == 200
    assert client.post(endpoint + '/reject', headers=reviewer(client), json={
        'version': 1, 'reason': '剩余需求待确认'}).status_code == 200
    revised = client.put(f"/api/v1/purchase-requests/{source['id']}", headers=auth, json={
        'lines': [{'material_id': source['lines'][0]['material_id'], 'quantity': '1'}]})
    assert revised.status_code == 409 and '来源行' in revised.text
    current = client.get('/api/v1/purchase-requests', headers=auth).json()[0]
    assert current['lines'][0]['id'] == source['lines'][0]['id'] and current['lines'][0]['remaining_quantity'] == '7'


def test_downstream_order_recovers_request_author_and_editor(requisition):
    client, auth, supplier, source = requisition
    editor = {'Authorization': 'Bearer ' + client.post('/api/v1/auth/login', json={
        'username': 'editor', 'password': 'secure-pass-123'}).json()['token']}
    payload = {'lines': [{'material_id': source['lines'][0]['material_id'], 'quantity': '10'}]}
    assert client.put(f"/api/v1/purchase-requests/{source['id']}", headers=editor, json=payload).status_code == 200
    source = client.get('/api/v1/purchase-requests', headers=auth).json()[0]
    approve_document(client, auth, 'PurchaseRequest', source['id'])
    converted = client.post('/api/v1/purchase-orders', headers=reviewer(client), json=order_input(supplier, source)).json()
    endpoint = f"/api/v1/system/document-approvals/PurchaseOrder/{converted['id']}"
    assert client.post(endpoint + '/submit', headers=reviewer(client), json={'version': 0}).status_code == 200
    for author in (auth, editor):
        assert client.get(endpoint, headers=author).json()['can_review']
        assert client.get((endpoint + '/approve').removesuffix('/approve'), headers=author, params={'intent': 'execute'}).json()['can_review']


def test_mrp_generated_request_preserves_original_plan_author(mrp_erp):
    client, admin, review, planner, _, materials, _ = mrp_erp
    plan = approve_mrp(client, admin, review, plan_payload(client, admin, materials))
    plan = client.get(MRP + f"/plans/{plan['id']}", headers=admin).json()
    suggestion = next(row for row in plan['snapshot']['suggestions'] if row['supply_mode'] == 'buy')
    result = client.post(MRP + f"/plans/{plan['id']}/convert", headers=planner, json={
        'version': plan['version'], 'suggestion_key': suggestion['key'], 'warehouse_id': 1, 'reason': '计划采购'})
    assert result.status_code == 201, result.text
    endpoint = path(result.json()['purchase_request_id'])
    assert client.post(endpoint + '/submit', headers=review, json={'version': 0}).status_code == 200
    assert client.get(endpoint, headers=admin).json()['can_review']
    assert client.get((endpoint + '/approve').removesuffix('/approve'), headers=admin, params={'intent': 'execute'}).json()['can_review']


def test_maintenance_generated_request_preserves_original_job_author(equipment_erp):
    client, api, actors, _, _, part = equipment_erp
    row = approve_job(equipment_erp, warehouse_id=1, parts=[{'material_id': part, 'quantity': '3'}])
    result = api('POST', f"equipment/jobs/{row['id']}/purchase-requests", {
        'version': row['version'], 'reason': '备件补购', 'evidence': '现场检修记录',
        'parts': [{'material_id': part, 'quantity': '2'}]}, actor='reviewer', status=201)
    endpoint = path(result['purchase_requests'][0]['id'])
    assert client.post(endpoint + '/submit', headers=actors['third'], json={'version': 0}).status_code == 200
    assert client.get(endpoint, headers=actors['admin']).json()['can_review']
    assert client.get(endpoint, headers=actors['reviewer']).json()['can_review']
    with orm_session() as db:
        assert 1 in purchase_request_snapshot(db, result['purchase_requests'][0]['id'])['source_author_ids']
