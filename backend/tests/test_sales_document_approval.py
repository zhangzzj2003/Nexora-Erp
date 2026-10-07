"""销售三类单据独立审批、客户权限和数量竞争的真实事务验证。"""

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from approval_test_helpers import approve_document
from test_document_approval import context
from app.core.document_approval import save_policy
from app.core.models import SalesOrderLine, ShipmentLine, SalesReturnLine, StockMovement, DocumentApprovalEvent
from app.core.orm import orm_session


def create_order(client, auth, material, quantity='5'):
    customer = client.post('/api/v1/customers', headers=auth, json={'name': '审批客户'}).json()['id']
    row = client.post('/api/v1/sales-orders', headers=auth, json={'customer_id': customer,
        'lines': [{'material_id': material, 'quantity': quantity, 'unit_price': '12.34',
                   'warranty_days': 30, 'warranty_basis': '签署合同'}]})
    assert row.status_code == 201, row.text
    return row.json()


@pytest.fixture(params=['SalesOrder', 'Shipment', 'SalesReturn'])
def sales_document(context, request):
    client, auth, inbound = context
    approve_document(client, auth, 'WarehouseInbound', inbound['id'])
    assert client.post(f"/api/v1/warehouse-inbounds/{inbound['id']}/post", headers=auth).status_code == 200
    material = inbound['lines'][0]['material_id']
    order = create_order(client, auth, material)
    kind = request.param
    if kind == 'SalesOrder':
        row, endpoint, action = order, 'sales-orders', 'confirm'
    else:
        approve_document(client, auth, 'SalesOrder', order['id'])
        assert client.post(f"/api/v1/sales-orders/{order['id']}/confirm", headers=auth).status_code == 200
        shipment = client.post('/api/v1/shipments', headers=auth, json={
            'sales_order_id': order['id'], 'warehouse_id': 1,
            'lines': [{'material_id': material, 'quantity': '3'}]}).json()
        if kind == 'Shipment':
            row, endpoint, action = shipment, 'shipments', 'post'
        else:
            approve_document(client, auth, 'Shipment', shipment['id'])
            assert client.post(f"/api/v1/shipments/{shipment['id']}/post", headers=auth).status_code == 200
            row = client.post('/api/v1/sales-returns', headers=auth, json={
                'shipment_id': shipment['id'], 'warehouse_id': 1, 'reason': '质量核对',
                'lines': [{'shipment_line_id': shipment['lines'][0]['id'], 'quantity': '2'}]}).json()
            endpoint, action = 'sales-returns', 'post'
    return client, auth, kind, row, '/api/v1/' + endpoint, action


def test_sales_types_require_own_two_person_steps(sales_document):
    client, auth, kind, row, endpoint, action = sales_document
    with orm_session(write=True) as db:
        save_policy(db, kind, [{'name': name, 'role': None} for name in ('核准', '批准')], 1, 1)
    execute = f"{endpoint}/{row['id']}/{action}"
    before = client.get('/api/v1/movements', headers=auth).json()
    # 上游已经执行也不会批准本单，旧客户端的普通确认同样被拒绝。
    assert row['approval']['version'] == 0
    assert client.post(execute, headers=auth).status_code == 409
    assert approve_document(client, auth, kind, row['id'])['current_step'] == 2
    assert client.get('/api/v1/movements', headers=auth).json() == before
    assert client.post(f"{endpoint}/{row['id']}/cancel", headers=auth).status_code == 409
    posted = client.post(execute, headers=auth)
    assert posted.status_code == 200, posted.text
    assert posted.json()['approval']['status'] == 'executed'
    if kind != 'SalesOrder':
        assert posted.json()['lines'][0]['physical_lots'] == []
        reverse = f"{endpoint}/{row['id']}/reverse"
        assert client.post(reverse, headers=auth, json={'reason': '复核更正'}).status_code == 409
        approve_document(client, auth, kind, row['id'], intent='reverse', reason='复核更正')
        assert client.post(reverse, headers=auth, json={'reason': '其他原因'}).status_code == 409
        reversed_row = client.post(reverse, headers=auth, json={'reason': '复核更正'})
        assert reversed_row.status_code == 201, reversed_row.text
        assert reversed_row.json()['reversal_approval']['status'] == 'executed'


def test_sales_concurrent_execution_occurs_once(sales_document):
    client, auth, kind, row, endpoint, action = sales_document
    approve_document(client, auth, kind, row['id'])
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post(f"{endpoint}/{row['id']}/{action}", headers=auth).status_code, range(2)))
    assert sorted(responses) == [200, 409]


def test_sales_changed_body_rejects_approved_document(sales_document):
    client, auth, kind, row, endpoint, action = sales_document
    approve_document(client, auth, kind, row['id'])
    with orm_session(write=True) as db:
        model, parent = {'SalesOrder': (SalesOrderLine, 'sales_order_id'),
                         'Shipment': (ShipmentLine, 'shipment_id'),
                         'SalesReturn': (SalesReturnLine, 'sales_return_id')}[kind]
        db.scalar(select(model).where(getattr(model, parent) == row['id'])).quantity = '1'
    result = client.post(f"{endpoint}/{row['id']}/{action}", headers=auth)
    assert result.status_code == 409 and '批准内容' in result.text


@pytest.mark.parametrize('phase', ['submitted', 'approved'])
def test_order_contract_cannot_change_during_approval(context, phase):
    client, auth, inbound = context
    order = create_order(client, auth, inbound['lines'][0]['material_id'])
    url = f"/api/v1/sales-orders/{order['id']}/contract"
    body = {'expected_version': 0, 'body': '双方合同正文', 'acceptance_reference': '客户签署原件', 'reason': '首次登记'}
    assert client.post(url, headers=auth, json=body).status_code == 200
    if phase == 'approved':
        approve_document(client, auth, 'SalesOrder', order['id'])
    else:
        assert client.post(f"/api/v1/system/document-approvals/SalesOrder/{order['id']}/submit",
                           headers=auth, json={'version': 0}).status_code == 200
    result = client.post(url, headers=auth, json={**body, 'expected_version': 1, 'body': '未经审批更改'})
    assert result.status_code == 409
    state = client.get(f"/api/v1/system/document-approvals/SalesOrder/{order['id']}", headers=auth).json()
    assert state['content_matches'] and any(part['value'] == body['body'] for part in state['summary'])


def test_sales_approval_enforces_customer_scope_for_every_action(sales_document):
    client, auth, kind, row, _, _ = sales_document
    assert client.post('/api/v1/users', headers=auth, json={
        'username': 'outside_seller', 'password': 'secure-pass-123', 'roles': ['seller']}).status_code == 201
    other = {'Authorization': 'Bearer ' + client.post('/api/v1/auth/login', json={
        'username': 'outside_seller', 'password': 'secure-pass-123'}).json()['token']}
    path = f"/api/v1/system/document-approvals/{kind}/{row['id']}"
    assert client.get(path, headers=other).status_code == 404
    for action in ('submit', 'approve', 'reject', 'withdraw'):
        assert client.post(path + '/' + action, headers=other, json={'version': 0, 'reason': '核对'}).status_code == 404


def test_stock_failure_keeps_shipment_approval_and_all_movements(sales_document):
    client, auth, kind, row, endpoint, action = sales_document
    approved = approve_document(client, auth, kind, row['id'])
    before = client.get('/api/v1/movements', headers=auth).json()

    def failure(db, _):
        # 流水已在原事务内落库后模拟故障，不能只回滚业务而保留已执行审批。
        if any(isinstance(item, DocumentApprovalEvent) and item.action == 'execute' for item in db.new):
            raise RuntimeError('测试销售库存故障')

    event.listen(Session, 'after_flush', failure)
    try:
        with pytest.raises(RuntimeError, match='测试销售库存故障'):
            client.post(f"{endpoint}/{row['id']}/{action}", headers=auth)
    finally:
        event.remove(Session, 'after_flush', failure)
    state = client.get(f"/api/v1/system/document-approvals/{kind}/{row['id']}", headers=auth).json()
    assert state['status'] == 'approved' and state['version'] == approved['version']
    assert client.get('/api/v1/movements', headers=auth).json() == before


def test_contract_editor_and_attachment_evidence_are_part_of_approval(context):
    from test_sales_contract_attachments import file_input
    client, auth, inbound = context
    editor = {'Authorization': 'Bearer ' + client.post('/api/v1/auth/login',
        json={'username': 'editor', 'password': 'secure-pass-123'}).json()['token']}
    order = create_order(client, auth, inbound['lines'][0]['material_id'])
    contract_url = f"/api/v1/sales-orders/{order['id']}/contract"
    revision = client.post(contract_url, headers=editor, json={'expected_version': 0,
        'body': '编辑人录入合同', 'acceptance_reference': '签署记录', 'reason': '合同依据'}).json()['current']
    attachment_url = contract_url + f"/revisions/{revision['id']}/attachments"
    attachment = client.post(attachment_url, headers=editor, json=file_input()).json()
    path = f"/api/v1/system/document-approvals/SalesOrder/{order['id']}"
    assert client.post(path + '/submit', headers=auth, json={'version': 0}).status_code == 200
    # 编辑合同的人即使有管理员权限也不能审核；原件追加/撤销均不得绕过固定正文。
    assert not client.get(path, headers=editor).json()['can_review']
    assert client.post(path + '/approve', headers=editor, json={'version': 1}).status_code == 403
    assert client.post(attachment_url, headers=auth, json=file_input(b'%PDF-1.4\nnew\n%%EOF')).status_code == 409
    assert client.post(attachment_url + f"/{attachment['id']}/reverse", headers=auth,
                       json={'reason': '未经审批撤销'}).status_code == 409
    assert client.get(path, headers=auth).json()['content_matches']
