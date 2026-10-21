"""销售草稿可修订，但审批、客户隔离、并发版本和库存事实不能被绕过。"""

from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from approval_test_helpers import approve_document
from app.core.models import SalesDraftChange, StockMovement
from app.core.orm import orm_session
from test_sales_return_amounts import context
from test_crm import seeded, base_records, approved as approved_quote, action as quote_action
from test_after_sales import erp, payload as after_sales_input, approved as approved_after_sales, action as after_sales_action


def order_input(request):
    return {'customer_id': request('GET', 'customers')[0]['id'], 'reference': '客户需求',
            'lines': [{'material_id': request('GET', 'materials')[0]['id'], 'quantity': '2',
                       'unit_price': '0.335', 'warranty_days': None, 'warranty_basis': ''}]}


def test_order_revision_preserves_identity_history_and_approval_lock(context):
    client, headers, _, request, execute, *_ = context
    payload = order_input(request)
    order = request('POST', 'sales-orders', payload, 201)
    assert order['draft_version'] == 0
    changed = {**payload, 'reference': '补充保修', 'expected_version': 0, 'revision_reason': '客户确认条款',
               'lines': [{**payload['lines'][0], 'warranty_days': 365, 'warranty_basis': '合同第一条'}]}
    saved = request('PUT', f"sales-orders/{order['id']}", changed)
    assert saved['id'] == order['id'] and saved['draft_version'] == 1
    assert saved['lines'][0]['id'] == order['lines'][0]['id']
    history = request('GET', f"sales-drafts/SalesOrder/{order['id']}/changes")
    assert history[0]['before']['lines'][0]['warranty_days'] is None
    assert history[0]['after']['lines'][0]['warranty_days'] == 365
    request('PUT', f"sales-orders/{order['id']}", changed, 409)
    approve_document(client, headers, 'SalesOrder', order['id'])
    request('PUT', f"sales-orders/{order['id']}", {**changed, 'expected_version': 1, 'reference': '不可偷改'}, 409)
    state = request('GET', f"system/document-approvals/SalesOrder/{order['id']}")
    request('POST', f"system/document-approvals/SalesOrder/{order['id']}/withdraw", {'version': state['version']})
    request('PUT', f"sales-orders/{order['id']}", {**changed, 'expected_version': 1, 'reference': '撤回后修订'})
    execute('SalesOrder', 'sales-orders', order['id'])
    request('PUT', f"sales-orders/{order['id']}", {**changed, 'expected_version': 2}, 409)
    assert len(request('GET', f"sales-drafts/SalesOrder/{order['id']}/changes")) == 2


def test_shipment_and_return_drafts_revalidate_source_and_only_post_changes_stock(context):
    _, _, _, request, execute, ship, draft = context
    source = ship('4')
    execute('Shipment', 'shipments', source['id'], intent='reverse')
    body = {'sales_order_id': source['sales_order_id'], 'warehouse_id': 1,
            'reference': '', 'lines': [{'material_id': source['lines'][0]['material_id'], 'quantity': '2'}]}
    shipment = request('POST', 'shipments', body, 201)
    revision = {**body, 'expected_version': 0, 'revision_reason': '确认分批交货',
                'lines': [{**body['lines'][0], 'quantity': '3'}]}
    updated = request('PUT', f"shipments/{shipment['id']}", revision)
    assert updated['draft_version'] == 1 and updated['lines'][0]['quantity'] == '3'
    request('PUT', f"shipments/{shipment['id']}", {**revision, 'expected_version': 1,
        'lines': [{**body['lines'][0], 'quantity': '5'}]}, 409)
    with orm_session() as db:
        assert db.scalar(select(StockMovement.id).where(StockMovement.source_type == 'shipment',
                                                        StockMovement.source_id == shipment['id'])) is None
    posted = execute('Shipment', 'shipments', shipment['id'])
    returned = draft(posted, '2')
    changed = {'shipment_id': posted['id'], 'warehouse_id': 1, 'reason': '退回一件',
               'expected_version': 0, 'revision_reason': '核对实际退货数量',
               'lines': [{'shipment_line_id': posted['lines'][0]['id'], 'quantity': '1'}]}
    saved = request('PUT', f"sales-returns/{returned['id']}", changed)
    assert saved['draft_version'] == 1 and saved['lines'][0]['id'] == returned['lines'][0]['id']
    assert execute('SalesReturn', 'sales-returns', returned['id'])['total_amount'] == '0.34'
    request('PUT', f"sales-returns/{returned['id']}", {**changed, 'expected_version': 1}, 409)


def test_concurrent_revision_does_not_overwrite_and_invalid_input_has_no_audit(context):
    client, headers, _, request, *_ = context
    body = order_input(request)
    order = request('POST', 'sales-orders', body, 201)
    changed = {**body, 'expected_version': 0, 'revision_reason': '核对客户要求'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda reference: client.put(f"/api/v1/sales-orders/{order['id']}",
            headers=headers, json={**changed, 'reference': reference}), ['修订甲', '修订乙']))
    assert sorted(result.status_code for result in results) == [200, 409]
    request('PUT', f"sales-orders/{order['id']}", {**changed, 'expected_version': 1,
        'lines': [*body['lines'], *body['lines']]}, 422)
    request('PUT', f"sales-orders/{order['id']}", {**changed, 'expected_version': 1, 'revision_reason': ' '}, 422)
    with orm_session() as db:
        assert len(list(db.scalars(select(SalesDraftChange)))) == 1


def test_revision_and_history_respect_customer_visibility(context):
    client, _, _, request, *_ = context
    body = order_input(request)
    order = request('POST', 'sales-orders', body, 201)
    request('POST', 'users', {'username': 'other_seller', 'password': 'secure-pass-123', 'roles': ['seller']}, 201)
    token = client.post('/api/v1/auth/login', json={'username': 'other_seller', 'password': 'secure-pass-123'}).json()['token']
    headers = {'Authorization': f'Bearer {token}'}
    for method, path, payload in [
        ('PUT', f"sales-orders/{order['id']}", {**body, 'expected_version': 0, 'revision_reason': '越权修改'}),
        ('GET', f"sales-drafts/SalesOrder/{order['id']}/changes", None),
    ]:
        result = client.request(method, f'/api/v1/{path}', headers=headers, json=payload)
        assert result.status_code == 404


def test_quote_converted_draft_can_complete_warranty_without_rewriting_quote(seeded):
    client, admin, *_ = seeded
    _, opportunity, body = base_records(seeded)
    quote = approved_quote(seeded, body)
    converted = quote_action(client, admin, quote, 'convert', acceptance_reference='客户确认',
                             opportunity_version=opportunity['version'])
    original_quote = client.get(f"/api/v1/crm/records/quote/{quote['id']}", headers=admin).json()
    order = next(row for row in client.get('/api/v1/sales-orders', headers=admin).json()
                 if row['id'] == converted['sales_order_id'])
    response = client.put(f"/api/v1/sales-orders/{order['id']}", headers=admin, json={
        'customer_id': order['customer_id'], 'reference': order['reference'], 'expected_version': 0,
        'revision_reason': '补齐已确认保修条款', 'lines': [{
            'material_id': line['material_id'], 'quantity': line['quantity'], 'unit_price': line['unit_price'],
            'warranty_days': 365, 'warranty_basis': '客户确认邮件'} for line in order['lines']]})
    assert response.status_code == 200, response.text
    assert all(line['warranty_days'] == 365 for line in response.json()['lines'])
    assert response.json()['total_amount'] == order['total_amount']
    assert client.get(f"/api/v1/crm/records/quote/{quote['id']}", headers=admin).json() == original_quote
    approve_document(client, admin, 'SalesOrder', order['id'])
    assert client.post(f"/api/v1/sales-orders/{order['id']}/confirm", headers=admin).status_code == 200


def test_after_sales_generated_drafts_cannot_bypass_approved_solution(erp):
    _, api, *_ = erp
    case = after_sales_action(api, approved_after_sales(erp, after_sales_input(erp, kind='exchange')), 'process')
    order = next(row for row in api('GET', 'sales-orders') if row['id'] == case['replacement_order_id'])
    returned = next(row for row in api('GET', 'sales-returns') if row['id'] == case['sales_return_id'])
    assert '售后' in order['draft_edit_block_reason'] and '售后' in returned['draft_edit_block_reason']
    api('PUT', f"sales-orders/{order['id']}", {'customer_id': order['customer_id'], 'expected_version': 0,
        'revision_reason': '尝试修改换货价格', 'lines': [{'material_id': order['lines'][0]['material_id'],
        'quantity': '1', 'unit_price': '99'}]}, status=409)
    api('PUT', f"sales-returns/{returned['id']}", {'shipment_id': returned['shipment_id'], 'warehouse_id': 1,
        'reason': '修改数量', 'expected_version': 0, 'revision_reason': '尝试修改售后退货数量',
        'lines': [{'shipment_line_id': returned['lines'][0]['shipment_line_id'], 'quantity': '1'}]}, status=409)


def test_rejected_draft_requires_new_approval_and_failed_audit_rolls_back(context):
    import pytest
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    _, _, _, request, *_ = context
    body = order_input(request)
    order = request('POST', 'sales-orders', body, 201)
    path = f"system/document-approvals/SalesOrder/{order['id']}"
    current = request('GET', path)
    submitted = request('POST', path+'/submit', {'version': current['version']})
    request('POST', path+'/reject', {'version': submitted['version'], 'reason': '需修改数量'})
    change = {**body, 'reference': '驳回后修改', 'expected_version': 0, 'revision_reason': '按审批意见更正'}

    def fail_history(session, *_):
        if any(isinstance(row, SalesDraftChange) for row in session.new):
            raise RuntimeError('模拟修订审计写入失败')

    # 即便正文与明细已经更新，追加历史失败也必须整体回滚。
    event.listen(Session, 'before_flush', fail_history)
    try:
        with pytest.raises(RuntimeError, match='修订审计'):
            request('PUT', f"sales-orders/{order['id']}", change)
    finally:
        event.remove(Session, 'before_flush', fail_history)
    unchanged = request('GET', 'sales-orders')[0]
    assert unchanged['reference'] == body['reference'] and unchanged['draft_version'] == 0
    saved = request('PUT', f"sales-orders/{order['id']}", change)
    assert saved['approval']['status'] == 'rejected'
    request('POST', f"sales-orders/{order['id']}/confirm", expected=409)
