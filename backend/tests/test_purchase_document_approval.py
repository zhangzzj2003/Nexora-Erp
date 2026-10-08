"""采购订单、收货、入库分别审批，实际库存与独立冲销保持同事务。"""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from approval_test_helpers import approve_document
from test_document_approval import context
from app.core.document_approval import find_case, save_policy
from app.core.models import (
    DocumentApprovalAuthor, PurchaseGoodsReceiptLine, PurchaseOrderLine, Receipt,
    ReceiptLine, ReceiptReversal, StockMovement,
)
from app.core.orm import orm_session


@pytest.fixture
def purchase(context):
    client, auth, inbound = context
    supplier = client.post('/api/v1/suppliers', headers=auth, json={'name': '审批供应商'}).json()['id']
    material = inbound['lines'][0]['material_id']
    order = client.post('/api/v1/purchase-orders', headers=auth, json={
        'supplier_id': supplier, 'reference': '供应商参考号',
        'lines': [{'material_id': material, 'quantity': '10', 'unit_price': '2.5'}]})
    assert order.status_code == 201, order.text
    return client, auth, order.json()


def path(kind, identifier):
    return f'/api/v1/system/document-approvals/{kind}/{identifier}'


def reviewer(client):
    login = client.post('/api/v1/auth/login', json={
        'username': 'reviewer', 'password': 'secure-pass-123'})
    return {'Authorization': 'Bearer ' + login.json()['token']}


def goods(client, auth, order, accepted='6', rejected='2'):
    response = client.post('/api/v1/purchase-goods-receipts', headers=auth, json={
        'purchase_order_id': order['id'], 'warehouse_id': 1,
        'lines': [{'purchase_order_line_id': order['lines'][0]['id'],
                   'accepted_quantity': accepted, 'rejected_quantity': rejected,
                   'rejection_reason': '外包装破损' if Decimal(rejected) else ''}]})
    assert response.status_code == 201, response.text
    return response.json()


def receipt(client, auth, order, quantity='6'):
    response = client.post('/api/v1/receipts', headers=auth, json={
        'supplier_id': order['supplier_id'], 'purchase_order_id': order['id'],
        'lines': [{'material_id': order['lines'][0]['material_id'], 'quantity': quantity}]})
    assert response.status_code == 201, response.text
    return response.json()


def confirm_order(client, auth, order):
    approve_document(client, auth, 'PurchaseOrder', order['id'])
    result = client.post(f"/api/v1/purchase-orders/{order['id']}/confirm", headers=auth)
    assert result.status_code == 200, result.text
    return result.json()


def test_each_purchase_stage_needs_independent_approval_and_ordinary_post(purchase):
    client, auth, order = purchase
    # 三张单据各自走不同人的审核、核准、批准，不继承上游的批准结果。
    with orm_session(write=True) as db:
        for kind in ('PurchaseOrder', 'PurchaseGoodsReceipt', 'Receipt'):
            save_policy(db, kind, [{'name': name, 'role': None} for name in ('审核', '核准', '批准')], 1, 1)
    assert client.post(f"/api/v1/purchase-orders/{order['id']}/confirm", headers=auth).status_code == 409
    confirm_order(client, auth, order)
    received = goods(client, auth, order)
    confirm = f"/api/v1/purchase-goods-receipts/{received['id']}/confirm"
    assert client.post(confirm, headers=auth).status_code == 409
    approve_document(client, auth, 'PurchaseGoodsReceipt', received['id'])
    summary = client.get(path('PurchaseGoodsReceipt', received['id']), headers=auth).json()['summary']
    assert summary[-1]['value'] == '合格 6 个；拒收 2 个；原因 外包装破损'
    result = client.post(confirm, headers=auth)
    assert result.status_code == 200, result.text
    identifier = result.json()['inbound_receipt_id']
    child = next(item for item in client.get('/api/v1/receipts', headers=auth).json() if item['id'] == identifier)
    assert child['status'] == 'draft' and child['approval']['version'] == 0
    assert client.post(f'/api/v1/receipts/{identifier}/post', headers=auth).status_code == 409
    approve_document(client, auth, 'Receipt', identifier)
    result = client.post(f'/api/v1/receipts/{identifier}/post', headers=auth)
    assert result.status_code == 200, result.text
    assert result.json()['approval']['status'] == 'executed'
    assert result.json()['lines'][0]['physical_lots'] == []
    with orm_session() as db:
        assert list(db.scalars(select(StockMovement.quantity).where(StockMovement.source_type == 'receipt'))) == ['6']
        for kind, identifier in [('PurchaseOrder', order['id']), ('PurchaseGoodsReceipt', received['id']), ('Receipt', child['id'])]:
            state = find_case(db, kind, identifier)
            assert state.status == 'executed' and state.current_step == 3


@pytest.mark.parametrize('kind', ['PurchaseOrder', 'PurchaseGoodsReceipt', 'Receipt'])
def test_purchase_self_review_snapshot_change_and_withdraw(purchase, kind):
    client, auth, order = purchase
    record, model, field, changed = order, PurchaseOrderLine, 'unit_price', '9'
    if kind != 'PurchaseOrder':
        confirm_order(client, auth, order)
        if kind == 'PurchaseGoodsReceipt':
            record = goods(client, auth, order)
            model, field, changed = PurchaseGoodsReceiptLine, 'rejection_reason', '新的拒收原因'
        else:
            record = receipt(client, auth, order)
            model, field, changed = ReceiptLine, 'quantity', '7'
    endpoint = path(kind, record['id'])
    sent = client.post(endpoint + '/submit', headers=auth, json={'version': 0})
    assert sent.status_code == 200, sent.text
    assert client.get((endpoint + '/approve').removesuffix('/approve'), headers=auth, params={'intent': 'execute'}).json()['can_review']
    with orm_session(write=True) as db:
        # 模拟另一旧写入边界篡改正文，批准和执行都不能使用过期内容。
        setattr(db.get(model, record['lines'][0]['id']), field, changed)
    state = client.get(endpoint, headers=auth).json()
    assert state['content_matches'] is False and state['can_review'] is False
    assert client.post(endpoint + '/approve', headers=reviewer(client), json={'version': 1}).status_code == 409
    withdrawn = client.post(endpoint + '/withdraw', headers=auth, json={'version': 1})
    assert withdrawn.status_code == 200, withdrawn.text
    assert client.post(endpoint + '/submit', headers=auth, json={'version': 1}).status_code == 409
    sent = client.post(endpoint + '/submit', headers=auth, json={'version': 2})
    assert sent.status_code == 200 and sent.json()['generation'] == 2
    assert client.post(endpoint + '/reject', headers=reviewer(client), json={'version': 3, 'reason': ''}).status_code == 422
    rejected = client.post(endpoint + '/reject', headers=reviewer(client), json={'version': 3, 'reason': '请核对明细'})
    assert rejected.status_code == 200 and rejected.json()['status'] == 'rejected'
    assert rejected.json()['events'][-1]['reason'] == '请核对明细'


def test_receipt_lot_failure_rolls_back_approval_and_inventory(purchase):
    client, auth, order = purchase
    confirm_order(client, auth, order)
    child = receipt(client, auth, order)
    approve_document(client, auth, 'Receipt', child['id'])
    invalid = client.post(f"/api/v1/receipts/{child['id']}/post", headers=auth, json={
        'lines': [{'receipt_line_id': child['lines'][0]['id'], 'lots': [{'quantity': '5'}]}]})
    assert invalid.status_code == 422, invalid.text
    with orm_session() as db:
        assert find_case(db, 'Receipt', child['id']).status == 'approved'
        assert db.get(Receipt, child['id']).status == 'draft'
        assert db.scalar(select(func.count()).select_from(StockMovement)) == 0
    valid = client.post(f"/api/v1/receipts/{child['id']}/post", headers=auth, json={
        'lines': [{'receipt_line_id': child['lines'][0]['id'], 'lots': [{'quantity': '6'}]}]})
    assert valid.status_code == 200, valid.text
    assert valid.json()['lines'][0]['physical_lots'][0]['code'].startswith('R')


def test_receipt_rechecks_remaining_quantity_after_approval(purchase):
    client, auth, order = purchase
    confirm_order(client, auth, order)
    first, second = receipt(client, auth, order, '6'), receipt(client, auth, order, '6')
    for item in (first, second):
        approve_document(client, auth, 'Receipt', item['id'])
    assert client.post(f"/api/v1/receipts/{first['id']}/post", headers=auth).status_code == 200
    assert client.post(f"/api/v1/receipts/{second['id']}/post", headers=auth).status_code == 409
    with orm_session() as db:
        assert find_case(db, 'Receipt', second['id']).status == 'approved'
        assert db.get(Receipt, second['id']).status == 'draft'
        assert db.scalar(select(func.count()).select_from(StockMovement)) == 1


def test_receipt_reverse_requires_fixed_reason_and_independent_approval(purchase):
    client, auth, order = purchase
    confirm_order(client, auth, order)
    child = receipt(client, auth, order)
    approve_document(client, auth, 'Receipt', child['id'])
    assert client.post(f"/api/v1/receipts/{child['id']}/post", headers=auth).status_code == 200
    endpoint = f"/api/v1/receipts/{child['id']}/reverse"
    assert client.post(endpoint, headers=auth, json={'reason': '重复入库'}).status_code == 409
    approve_document(client, auth, 'Receipt', child['id'], intent='reverse', reason='重复入库')
    assert client.post(endpoint, headers=auth, json={'reason': '另一原因'}).status_code == 409
    result = client.post(endpoint, headers=auth, json={'reason': '重复入库'})
    assert result.status_code == 201 and result.json()['reversal_approval']['status'] == 'executed'
    assert client.post(endpoint, headers=auth, json={'reason': '重复入库'}).status_code == 409
    with orm_session() as db:
        assert db.scalar(select(func.count()).select_from(ReceiptReversal)) == 1
        assert sum(map(Decimal, db.scalars(select(StockMovement.quantity)))) == 0


def test_submitted_order_and_goods_cannot_cancel_without_withdraw(purchase):
    client, auth, order = purchase
    endpoint = path('PurchaseOrder', order['id'])
    assert client.post(endpoint + '/submit', headers=auth, json={'version': 0}).status_code == 200
    assert client.post(f"/api/v1/purchase-orders/{order['id']}/cancel", headers=auth).status_code == 409
    assert client.post(endpoint + '/withdraw', headers=auth, json={'version': 1}).status_code == 200
    approve_document(client, auth, 'PurchaseOrder', order['id'])
    assert client.post(f"/api/v1/purchase-orders/{order['id']}/cancel", headers=auth).status_code == 409
    assert client.post(f"/api/v1/purchase-orders/{order['id']}/confirm", headers=auth).status_code == 200
    received = goods(client, auth, order)
    approve_document(client, auth, 'PurchaseGoodsReceipt', received['id'])
    assert client.post(f"/api/v1/purchase-goods-receipts/{received['id']}/cancel", headers=auth).status_code == 409


def test_receipt_derived_authors_and_domain_read_permission(purchase):
    client, auth, order = purchase
    confirm_order(client, auth, order)
    received = goods(client, auth, order)
    approve_document(client, auth, 'PurchaseGoodsReceipt', received['id'])
    confirmer = reviewer(client)
    confirmed = client.post(f"/api/v1/purchase-goods-receipts/{received['id']}/confirm", headers=confirmer)
    assert confirmed.status_code == 200, confirmed.text
    child_id = confirmed.json()['inbound_receipt_id']
    with orm_session() as db:
        assert db.get(DocumentApprovalAuthor, ('Receipt', child_id, order['created_by'])) is not None
    endpoint = path('Receipt', child_id)
    assert client.post(endpoint + '/submit', headers=confirmer, json={'version': 0}).status_code == 200
    assert client.get((endpoint + '/approve').removesuffix('/approve'), headers=auth, params={'intent': 'execute'}).json()['can_review']
    client.post('/api/v1/roles', headers=auth, json={
        'code': 'production_observer', 'label': '仅生产查看', 'permissions': ['production.view']})
    client.post('/api/v1/users', headers=auth, json={
        'username': 'limited_observer', 'password': 'secure-pass-123', 'roles': ['production_observer']})
    login = client.post('/api/v1/auth/login', json={'username': 'limited_observer', 'password': 'secure-pass-123'})
    warehouse = {'Authorization': 'Bearer ' + login.json()['token']}
    assert client.get(path('PurchaseGoodsReceipt', received['id']), headers=warehouse).status_code == 403
    # 没有原领域查看权限时，通用审批入口也不能暴露供应商和采购详情。
    assert client.post(path('PurchaseGoodsReceipt', received['id']) + '/approve', headers=warehouse,
                       json={'version': 2}).status_code == 403


def test_receipt_withdraw_and_post_compete_atomically(purchase):
    client, auth, order = purchase
    confirm_order(client, auth, order)
    child = receipt(client, auth, order)
    state = approve_document(client, auth, 'Receipt', child['id'])
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(client.post, f"/api/v1/receipts/{child['id']}/post", headers=auth),
                   pool.submit(client.post, path('Receipt', child['id']) + '/withdraw', headers=auth,
                               json={'version': state['version']})]
        results = [future.result().status_code for future in futures]
    assert sorted(results) == [200, 409]
    with orm_session() as db:
        state = find_case(db, 'Receipt', child['id'])
        source = db.get(Receipt, child['id'])
        movements = db.scalar(select(func.count()).select_from(StockMovement))
        assert (state.status, source.status, movements) in [('withdrawn', 'draft', 0), ('executed', 'posted', 1)]


def test_receipt_approval_freezes_ownership_of_order_line(purchase):
    client, auth, order = purchase
    confirm_order(client, auth, order)
    child = receipt(client, auth, order)
    approve_document(client, auth, 'Receipt', child['id'])
    other_material = client.post('/api/v1/materials', headers=auth, json={
        'sku': 'OTHER-APPROVAL', 'name': '另一审批物料', 'unit': '个'}).json()['id']
    another = client.post('/api/v1/purchase-orders', headers=auth, json={
        'supplier_id': order['supplier_id'], 'lines': [{'material_id': other_material,
                                                     'quantity': '10', 'unit_price': '9'}]}).json()
    with orm_session(write=True) as db:
        # 即使原订单行 ID 未变，也不能把它移到另一张订单后复用批准结果。
        db.get(PurchaseOrderLine, order['lines'][0]['id']).purchase_order_id = another['id']
    result = client.post(f"/api/v1/receipts/{child['id']}/post", headers=auth)
    assert result.status_code == 409 and '批准内容' in result.json()['detail']
    with orm_session() as db:
        assert find_case(db, 'Receipt', child['id']).status == 'approved'
        assert db.scalar(select(func.count()).select_from(StockMovement)) == 0
