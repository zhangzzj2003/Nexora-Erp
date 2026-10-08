"""生产四类单据独立审批与质检、净领料、库存事务边界验证。"""

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from approval_test_helpers import approve_document
from test_document_approval import context
from test_mrp import seeded as mrp_erp, payload as mrp_payload, approved as approve_mrp, MRP
from test_quality_rework import quality_erp, payload as quality_payload, posted as post_quality, action as quality_action
from app.core.document_approval import save_policy
from app.core.models import WorkOrder, MaterialIssueLine, MaterialReturnLine, ProductionCompletion, DocumentApprovalEvent, UserRole
from app.core.orm import orm_session


def prepare_order(client, auth, inbound):
    approve_document(client, auth, 'WarehouseInbound', inbound['id'])
    assert client.post(f"/api/v1/warehouse-inbounds/{inbound['id']}/post", headers=auth).status_code == 200
    product = client.post('/api/v1/materials', headers=auth, json={'sku': 'APPROVAL-PRODUCT',
        'name': '审批成品', 'unit': '件'}).json()['id']
    bom = client.post('/api/v1/boms', headers=auth, json={'product_material_id': product,
        'base_quantity': '1', 'lines': [{'component_material_id': inbound['lines'][0]['material_id'],
                                       'quantity': '2'}]}).json()
    assert client.post(f"/api/v1/boms/{bom['id']}/activate", headers=auth).status_code == 200
    order = client.post('/api/v1/work-orders', headers=auth, json={'bom_id': bom['id'],
        'warehouse_id': 1, 'target_quantity': '3', 'reference': '生产独立审批'}).json()
    return order


@pytest.fixture(params=['WorkOrder', 'MaterialIssue', 'MaterialReturn', 'ProductionCompletion'])
def production_document(context, request):
    client, auth, inbound = context
    order = prepare_order(client, auth, inbound)
    kind = request.param
    if kind == 'WorkOrder':
        return client, auth, kind, order, '/api/v1/work-orders', 'release'
    approve_document(client, auth, 'WorkOrder', order['id'])
    assert client.post(f"/api/v1/work-orders/{order['id']}/release", headers=auth).status_code == 200
    issue = client.post('/api/v1/material-issues', headers=auth, json={'work_order_id': order['id'],
        'warehouse_id': 1, 'lines': [{'work_order_line_id': order['lines'][0]['id'], 'quantity': '6'}]}).json()
    if kind == 'MaterialIssue':
        return client, auth, kind, issue, '/api/v1/material-issues', 'post'
    approve_document(client, auth, 'MaterialIssue', issue['id'])
    assert client.post(f"/api/v1/material-issues/{issue['id']}/post", headers=auth).status_code == 200
    if kind == 'MaterialReturn':
        row = client.post('/api/v1/material-returns', headers=auth, json={'material_issue_id': issue['id'],
            'reason': '余料退回', 'lines': [{'material_issue_line_id': issue['lines'][0]['id'], 'quantity': '2'}]}).json()
        return client, auth, kind, row, '/api/v1/material-returns', 'post'
    row = client.post('/api/v1/production-completions', headers=auth, json={
        'work_order_id': order['id'], 'reported_quantity': '2'}).json()
    path = f"/api/v1/system/document-approvals/ProductionCompletion/{row['id']}"
    # 报工草稿不能送审替代质检；先由另一人员登记合格和不合格数量。
    assert client.post(path + '/submit', headers=auth, json={'version': 0}).status_code == 409
    inspector = {'Authorization': 'Bearer ' + client.post('/api/v1/auth/login',
        json={'username': 'editor', 'password': 'secure-pass-123'}).json()['token']}
    inspected = client.post(f"/api/v1/production-completions/{row['id']}/inspect", headers=inspector,
        json={'accepted_quantity': '1', 'qc_note': '一件不合格'}).json()
    return client, auth, kind, inspected, '/api/v1/production-completions', 'post'


def test_production_types_require_own_steps_and_preserve_business_checks(production_document):
    client, auth, kind, row, endpoint, action = production_document
    with orm_session(write=True) as db:
        save_policy(db, kind, [{'name': name, 'role': None} for name in ('核准', '批准')], 1, 1)
    execute = f"{endpoint}/{row['id']}/{action}"
    before = client.get('/api/v1/movements', headers=auth).json()
    assert row['approval']['version'] == 0
    assert client.post(execute, headers=auth).status_code == 409
    approved = approve_document(client, auth, kind, row['id'])
    assert approved['current_step'] == 2
    assert client.post(f"{endpoint}/{row['id']}/cancel", headers=auth).status_code == 409
    assert client.get('/api/v1/movements', headers=auth).json() == before
    if kind == 'ProductionCompletion':
        inspector = {'Authorization': 'Bearer ' + client.post('/api/v1/auth/login',
            json={'username': 'editor', 'password': 'secure-pass-123'}).json()['token']}
        path = f"/api/v1/system/document-approvals/{kind}/{row['id']}"
        assert not client.get(path, headers=inspector).json()['can_review']
    posted = client.post(execute, headers=auth)
    assert posted.status_code == 200, posted.text
    assert posted.json()['approval']['status'] == 'executed'
    if kind == 'WorkOrder':
        return
    assert (posted.json()['physical_lots'] if kind == 'ProductionCompletion'
            else posted.json()['lines'][0]['physical_lots']) == []
    reverse = f"{endpoint}/{row['id']}/reverse"
    assert client.post(reverse, headers=auth, json={'reason': '数量复核'}).status_code == 409
    approve_document(client, auth, kind, row['id'], intent='reverse', reason='数量复核')
    assert client.post(reverse, headers=auth, json={'reason': '改写原因'}).status_code == 409
    reversed_row = client.post(reverse, headers=auth, json={'reason': '数量复核'})
    assert reversed_row.status_code in (200, 201), reversed_row.text
    assert reversed_row.json()['reversal_approval']['status'] == 'executed'


def test_production_concurrent_execution_occurs_once(production_document):
    client, auth, kind, row, endpoint, action = production_document
    approve_document(client, auth, kind, row['id'])
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post(f"{endpoint}/{row['id']}/{action}", headers=auth).status_code, range(2)))
    assert sorted(responses) == [200, 409]


def test_production_changed_body_rejects_approved_document(production_document):
    client, auth, kind, row, endpoint, action = production_document
    approve_document(client, auth, kind, row['id'])
    with orm_session(write=True) as db:
        model, parent, field = {'WorkOrder': (WorkOrder, 'id', 'reference'),
            'MaterialIssue': (MaterialIssueLine, 'material_issue_id', 'quantity'),
            'MaterialReturn': (MaterialReturnLine, 'material_return_id', 'quantity'),
            'ProductionCompletion': (ProductionCompletion, 'id', 'qc_note')}[kind]
        setattr(db.scalar(select(model).where(getattr(model, parent) == row['id'])), field,
                '1' if field == 'quantity' else '审批后改写')
    result = client.post(f"{endpoint}/{row['id']}/{action}", headers=auth)
    assert result.status_code == 409 and '批准内容' in result.text


def test_production_failure_rolls_back_business_and_approval(production_document):
    client, auth, kind, row, endpoint, action = production_document
    approved = approve_document(client, auth, kind, row['id'])
    before = client.get('/api/v1/movements', headers=auth).json()
    def failure(db, _):
        # 执行事件写入后的故障必须把原领域状态和库存一起回滚。
        if any(isinstance(item, DocumentApprovalEvent) and item.action == 'execute' for item in db.new):
            raise RuntimeError('测试生产提交故障')
    event.listen(Session, 'after_flush', failure)
    try:
        with pytest.raises(RuntimeError, match='测试生产提交故障'):
            client.post(f"{endpoint}/{row['id']}/{action}", headers=auth)
    finally:
        event.remove(Session, 'after_flush', failure)
    state = client.get(f"/api/v1/system/document-approvals/{kind}/{row['id']}", headers=auth).json()
    assert state['status'] == 'approved' and state['version'] == approved['version']
    assert client.get('/api/v1/movements', headers=auth).json() == before


def test_completion_authorized_inspector_can_review_own_result(context):
    client, auth, inbound = context
    order = prepare_order(client, auth, inbound)
    approve_document(client, auth, 'WorkOrder', order['id'])
    client.post(f"/api/v1/work-orders/{order['id']}/release", headers=auth)
    issue = client.post('/api/v1/material-issues', headers=auth, json={'work_order_id': order['id'],
        'warehouse_id': 1, 'lines': [{'work_order_line_id': order['lines'][0]['id'], 'quantity': '6'}]}).json()
    approve_document(client, auth, 'MaterialIssue', issue['id'])
    client.post(f"/api/v1/material-issues/{issue['id']}/post", headers=auth)
    row = client.post('/api/v1/production-completions', headers=auth, json={
        'work_order_id': order['id'], 'reported_quantity': '1'}).json()
    inspector = {'Authorization': 'Bearer ' + client.post('/api/v1/auth/login',
        json={'username': 'editor', 'password': 'secure-pass-123'}).json()['token']}
    client.post(f"/api/v1/production-completions/{row['id']}/inspect", headers=inspector,
        json={'accepted_quantity': '1', 'qc_note': '合格'})
    path = f"/api/v1/system/document-approvals/ProductionCompletion/{row['id']}"
    assert client.post(path + '/submit', headers=auth, json={'version': 0}).status_code == 200
    assert client.get(path, headers=inspector).json()['can_review']
    assert client.get((path + '/approve').removesuffix('/approve'), headers=inspector, params={'intent': 'execute'}).json()['can_review']

def test_mrp_generated_work_order_preserves_authors_and_button_permissions(mrp_erp):
    client, admin, reviewer, planner, _, materials, _ = mrp_erp
    plan = approve_mrp(client, admin, reviewer, mrp_payload(client, admin, materials))
    plan = client.get(MRP + f"/plans/{plan['id']}", headers=admin).json()
    suggestion = next(row for row in plan['snapshot']['suggestions'] if row['material_id'] == materials[0])
    converted = client.post(MRP + f"/plans/{plan['id']}/convert", headers=planner,
        json={'version': plan['version'], 'suggestion_key': suggestion['key'],
              'warehouse_id': 1, 'reason': '已审核计划转工单'})
    assert converted.status_code == 201, converted.text
    identifier = converted.json()['work_order_id']
    assert client.post(f'/api/v1/work-orders/{identifier}/release', headers=admin).status_code == 409
    path = f'/api/v1/system/document-approvals/WorkOrder/{identifier}'
    assert client.post(path + '/submit', headers=reviewer, json={'version': 0}).status_code == 200
    # 管理员与计划员的作者身份仍保留，审批资格由当前按钮权限决定。
    assert client.get(path, headers=admin).json()['can_review']
    assert client.get((path + '/approve').removesuffix('/approve'), headers=admin, params={'intent': 'execute'}).json()['can_review']
    assert not client.get(path, headers=planner).json()['can_review']
    assert client.post('/api/v1/users', headers=admin, json={'username': 'child_reviewer',
        'password': 'secure-pass-123', 'roles': ['admin']}).status_code == 201
    token = client.post('/api/v1/auth/login', json={'username': 'child_reviewer',
        'password': 'secure-pass-123'}).json()['token']
    independent = {'Authorization': 'Bearer ' + token}
    approved = client.post(path + '/approve', headers=independent, json={'version': 1})
    assert approved.status_code == 200, approved.text
    # 同计划的其他建议由另一人员转出，不能让已批准工单的作者摘要随之变化。
    current = client.get(MRP + f"/plans/{plan['id']}", headers=admin).json()
    other = next(row for row in current['snapshot']['suggestions'] if row['material_id'] == materials[1])
    assert client.post(MRP + f"/plans/{plan['id']}/convert", headers=independent,
        json={'version': current['version'], 'suggestion_key': other['key'],
              'warehouse_id': 1, 'reason': '同计划另一个建议'}).status_code == 201
    assert client.post(f'/api/v1/work-orders/{identifier}/release', headers=admin).status_code == 200


def test_rework_generated_order_recovers_original_disposition_author(quality_erp):
    client, admin, actors, api, _, _, order, _ = quality_erp
    _, completion = order('1', '0')
    disposition = post_quality(api, actors, quality_payload(completion, kind='rework'))
    identifier = disposition['rework_order_id']
    path = f'/api/v1/system/document-approvals/WorkOrder/{identifier}'
    assert client.post(f'/api/v1/work-orders/{identifier}/release', headers=admin).status_code == 409
    assert client.post(path + '/submit', headers=admin, json={'version': 0}).status_code == 200
    with orm_session(write=True) as db:
        # 后续升为管理员获得按钮权限即可审批；原编制身份仍用于溯源。
        db.add(UserRole(user_id=2, role_code='admin'))
    assert client.get(path, headers=actors['author']).json()['can_review']
    assert client.get((path + '/approve').removesuffix('/approve'), headers=actors['author'], params={'intent': 'execute'}).json()['can_review']
    token = client.post('/api/v1/auth/login', json={'username': 'independent_reviewer_1',
        'password': 'approval-test-pass-123'}).json()['token']
    independent = {'Authorization': 'Bearer ' + token}
    assert client.post(path + '/approve', headers=independent, json={'version': 1}).status_code == 200
    assert client.post(f'/api/v1/work-orders/{identifier}/release', headers=admin).status_code == 200


def test_historical_released_order_keeps_original_flow_without_fabricated_approval(context):
    client, auth, inbound = context
    order = prepare_order(client, auth, inbound)
    with orm_session(write=True) as db:
        # 模拟升级前已下达工单；升级只保留旧事实，不为它追加虚构批准。
        row = db.get(WorkOrder, order['id'])
        row.status, row.released_by, row.released_at = 'released', 1, '2025-01-01 08:00:00'
    path = f"/api/v1/system/document-approvals/WorkOrder/{order['id']}"
    state = client.get(path, headers=auth).json()
    assert state['business_status'] == 'released'
    assert state['version'] == 0 and state['events'] == [] and not state['can_submit']
    assert client.post(path + '/submit', headers=auth, json={'version': 0}).status_code == 409
    assert client.get('/api/v1/work-orders', headers=auth).json()[0]['released_at'] == '2025-01-01 08:00:00'


def test_rework_source_correction_cannot_cancel_approved_child_without_withdrawal(quality_erp):
    client, admin, actors, api, _, _, order, _ = quality_erp
    _, completion = order('1', '0')
    disposition = post_quality(api, actors, quality_payload(completion, kind='rework'))
    identifier = disposition['rework_order_id']
    approved = approve_document(client, admin, 'WorkOrder', identifier)
    # 更正自身也先独立批准，再验证下游批准不能被上游静默取消。
    approve_document(client, admin, 'QualityDisposition', disposition['id'], intent='reverse', reason='质量方案更正')
    # 先撤回子单自己的审批，才能通过上游更正取消尚未使用的返工工单。
    path = f'/api/v1/production-quality/dispositions/{disposition["id"]}/reverse'
    blocked = client.post(path, headers=admin, json={'version': disposition['version'], 'reason': '质量方案更正'})
    assert blocked.status_code == 409 and '撤回返工工单审批' in blocked.text
    child_path = f'/api/v1/system/document-approvals/WorkOrder/{identifier}'
    assert client.get(child_path, headers=admin).json()['status'] == 'approved'
    assert client.post(child_path + '/withdraw', headers=admin, json={'version': approved['version']}).status_code == 200
    assert quality_action(api, disposition, 'reverse', reason='质量方案更正')['status'] == 'reversed'
    state = client.get(child_path, headers=admin).json()
    assert state['status'] == 'withdrawn' and state['business_status'] == 'cancelled'
