"""退货转单、独立仓库出库与冲销审批，禁止旧入口自动批准子单。"""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from approval_test_helpers import approve_document
from test_document_approval import context
from app.core.document_approval import find_case, save_policy
from app.core.models import PurchaseOrderLine, PurchaseReturn, StockMovement, WarehouseOutbound, WarehouseOutboundLine
from app.core.orm import orm_session, add_model


@pytest.fixture
def returns(context):
    client, auth, inbound = context
    supplier = client.post('/api/v1/suppliers', headers=auth, json={'name': '退货审批供应商'}).json()['id']
    receipt = client.post('/api/v1/receipts', headers=auth, json={
        'supplier_id': supplier, 'lines': [{'material_id': inbound['lines'][0]['material_id'], 'quantity': '10'}]}).json()
    approve_document(client, auth, 'Receipt', receipt['id'])
    assert client.post(f"/api/v1/receipts/{receipt['id']}/post", headers=auth).status_code == 200
    result = client.post('/api/v1/purchase-returns', headers=auth, json={
        'receipt_id': receipt['id'], 'reason': '原物料退回',
        'lines': [{'receipt_line_id': receipt['lines'][0]['id'], 'quantity': '3'}]})
    assert result.status_code == 201, result.text
    return client, auth, result.json(), inbound['lines'][0]['material_id']


def path(kind, identifier):
    return f'/api/v1/system/document-approvals/{kind}/{identifier}'


def release(client, auth, row):
    approve_document(client, auth, 'PurchaseReturn', row['id'])
    result = client.post(f"/api/v1/purchase-returns/{row['id']}/submit", headers=auth)
    assert result.status_code == 200, result.text
    return result.json()['outbound_id']


def test_return_and_generated_outbound_separately_approved(returns):
    client, auth, row, _ = returns
    # 各自固定多步模板；退货批准不产生库存，也不批准下游出库单。
    with orm_session(write=True) as db:
        for kind in ('PurchaseReturn', 'WarehouseOutbound'):
            save_policy(db, kind, [{'name': name, 'role': None} for name in ('核准', '批准')], 1, 1)
    assert client.post(f"/api/v1/purchase-returns/{row['id']}/submit", headers=auth).status_code == 409
    assert client.post(f"/api/v1/purchase-returns/{row['id']}/post", headers=auth).status_code == 409
    outbound_id = release(client, auth, row)
    child = next(item for item in client.get('/api/v1/warehouse-outbounds', headers=auth).json() if item['id'] == outbound_id)
    assert child['status'] == 'draft' and child['approval']['version'] == 0
    assert client.post(f'/api/v1/warehouse-outbounds/{outbound_id}/post', headers=auth).status_code == 409
    assert client.post(f"/api/v1/purchase-returns/{row['id']}/post", headers=auth).status_code == 409
    with orm_session() as db:
        assert find_case(db, 'PurchaseReturn', row['id']).status == 'executed'
        assert db.scalar(select(func.count()).select_from(StockMovement)) == 1
    approve_document(client, auth, 'WarehouseOutbound', outbound_id)
    result = client.post(f'/api/v1/warehouse-outbounds/{outbound_id}/post', headers=auth)
    assert result.status_code == 200, result.text
    assert result.json()['approval']['status'] == 'executed'
    assert result.json()['lines'][0]['physical_lots'] == []
    assert client.post(f"/api/v1/purchase-returns/{row['id']}/submit", headers=auth).status_code == 409
    with orm_session() as db:
        assert db.get(PurchaseReturn, row['id']).status == 'posted'
        assert sum(map(Decimal, db.scalars(select(StockMovement.quantity)))) == 7


def test_derived_outbound_preserves_authors_without_blocking_button_permissions(returns):
    client, auth, row, _ = returns
    approve_document(client, auth, 'PurchaseReturn', row['id'])
    login = client.post('/api/v1/auth/login', json={'username': 'reviewer', 'password': 'secure-pass-123'})
    converter = {'Authorization': 'Bearer ' + login.json()['token']}
    result = client.post(f"/api/v1/purchase-returns/{row['id']}/submit", headers=converter)
    assert result.status_code == 200, result.text
    target = path('WarehouseOutbound', result.json()['outbound_id'])
    assert client.post(target + '/submit', headers=converter, json={'version': 0}).status_code == 200
    for author in (auth, converter):
        assert client.get(target, headers=author).json()['can_review']


def test_legacy_pending_outbound_requires_parent_and_child_approval(returns):
    client, auth, row, material = returns
    # 模拟旧服务只生成子单但尚未扣库存；复用原 ID，不制造第二张子单或虚构历史批准。
    with orm_session(write=True) as db:
        child = add_model(db, WarehouseOutbound(warehouse_id=1, source_kind='purchase_return',
            reason='purchase_return', note=row['reason'], purchase_return_id=row['id'], created_by=1))
        identifier = child.id
        db.add(WarehouseOutboundLine(outbound_id=identifier, material_id=material, quantity='3'))
    state = approve_document(client, auth, 'WarehouseOutbound', identifier)
    assert client.post(f'/api/v1/warehouse-outbounds/{identifier}/post', headers=auth).status_code == 409
    assert client.post(path('WarehouseOutbound', identifier) + '/withdraw', headers=auth,
                       json={'version': state['version']}).status_code == 200
    assert release(client, auth, row) == identifier
    approve_document(client, auth, 'WarehouseOutbound', identifier)
    assert client.post(f'/api/v1/warehouse-outbounds/{identifier}/post', headers=auth).status_code == 200
    with orm_session() as db:
        assert db.scalar(select(func.count()).select_from(WarehouseOutbound)) == 1


def test_child_cannot_change_approved_return_quantities(returns):
    client, auth, row, _ = returns
    identifier = release(client, auth, row)
    with orm_session(write=True) as db:
        db.scalar(select(WarehouseOutboundLine).where(WarehouseOutboundLine.outbound_id == identifier)).quantity = '4'
    approve_document(client, auth, 'WarehouseOutbound', identifier)
    result = client.post(f'/api/v1/warehouse-outbounds/{identifier}/post', headers=auth)
    assert result.status_code == 409 and '内容不一致' in result.json()['detail']
    with orm_session() as db:
        assert find_case(db, 'WarehouseOutbound', identifier).status == 'approved'
        assert db.scalar(select(func.count()).select_from(StockMovement)) == 1


def test_return_cancel_cannot_silently_cancel_approved_child(returns):
    client, auth, row, _ = returns
    identifier = release(client, auth, row)
    state = approve_document(client, auth, 'WarehouseOutbound', identifier)
    cancel = f"/api/v1/purchase-returns/{row['id']}/cancel"
    assert client.post(cancel, headers=auth).status_code == 409
    assert client.post(path('WarehouseOutbound', identifier) + '/withdraw', headers=auth,
                       json={'version': state['version']}).status_code == 200
    assert client.post(cancel, headers=auth).status_code == 200
    assert client.post(f'/api/v1/warehouse-outbounds/{identifier}/post', headers=auth).status_code == 409


def test_legacy_and_warehouse_post_compete_in_same_transaction(returns):
    client, auth, row, _ = returns
    identifier = release(client, auth, row)
    approve_document(client, auth, 'WarehouseOutbound', identifier)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(client.post, endpoint, headers=auth) for endpoint in (
            f"/api/v1/purchase-returns/{row['id']}/post", f'/api/v1/warehouse-outbounds/{identifier}/post')]
        assert sorted(job.result().status_code for job in jobs) == [200, 409]
    with orm_session() as db:
        assert find_case(db, 'WarehouseOutbound', identifier).status == 'executed'
        assert db.scalar(select(func.count()).select_from(StockMovement).where(
            StockMovement.source_type == 'purchase_return')) == 1


def test_warehouse_dispatch_permission_does_not_require_parent_conversion_permission(returns):
    client, auth, row, _ = returns
    identifier = release(client, auth, row)
    approve_document(client, auth, 'WarehouseOutbound', identifier)
    # 只给仓库原查看/执行权限；不通过审批查询额外暴露供应商或采购价格。
    assert client.post('/api/v1/roles', headers=auth, json={'code': 'dispatch_only', 'label': '仅仓库出库',
        'permissions': ['other_outbound.view', 'other_outbound.post']}).status_code == 201
    assert client.post('/api/v1/users', headers=auth, json={'username': 'dispatcher',
        'password': 'secure-pass-123', 'roles': ['dispatch_only']}).status_code == 201
    token = client.post('/api/v1/auth/login', json={'username': 'dispatcher', 'password': 'secure-pass-123'}).json()['token']
    actor = {'Authorization': 'Bearer ' + token}
    summary = client.get(path('WarehouseOutbound', identifier), headers=actor).json()['summary']
    assert all('供应商' not in item['label'] and '单价' not in item['value'] for item in summary)
    assert client.get(path('PurchaseReturn', row['id']), headers=actor).status_code == 403
    assert client.post(f"/api/v1/purchase-returns/{row['id']}/post", headers=actor).status_code == 403
    assert client.post(f'/api/v1/warehouse-outbounds/{identifier}/post', headers=actor).status_code == 200


def test_generated_child_failure_rolls_back_parent_execution(returns):
    client, auth, row, _ = returns
    approve_document(client, auth, 'PurchaseReturn', row['id'])
    from test_business_orm import fail_after_model_flush
    before, after = fail_after_model_flush(WarehouseOutbound)
    event.listen(Session, 'before_flush', before)
    event.listen(Session, 'after_flush_postexec', after)
    try:
        # 模拟真实子单写入后故障，父审批不能留下“已转出库”的半成功状态。
        with pytest.raises(RuntimeError, match='模拟业务写入后故障'):
            client.post(f"/api/v1/purchase-returns/{row['id']}/submit", headers=auth)
    finally:
        event.remove(Session, 'before_flush', before)
        event.remove(Session, 'after_flush_postexec', after)
    with orm_session() as db:
        assert find_case(db, 'PurchaseReturn', row['id']).status == 'approved'
        assert db.scalar(select(func.count()).select_from(WarehouseOutbound)) == 0
    assert client.post(f"/api/v1/purchase-returns/{row['id']}/submit", headers=auth).status_code == 200


def test_return_freezes_original_purchase_price(returns):
    client, auth, row, material = returns
    # 退货金额沿用来源价格；来源行 ID 不变也不能在批准后悄悄改变价格。
    order = client.post('/api/v1/purchase-orders', headers=auth, json={'supplier_id': row['supplier_id'],
        'lines': [{'material_id': material, 'quantity': '5', 'unit_price': '2'}]}).json()
    approve_document(client, auth, 'PurchaseOrder', order['id'])
    assert client.post(f"/api/v1/purchase-orders/{order['id']}/confirm", headers=auth).status_code == 200
    receipt = client.post('/api/v1/receipts', headers=auth, json={'supplier_id': row['supplier_id'],
        'purchase_order_id': order['id'], 'lines': [{'material_id': material, 'quantity': '5'}]}).json()
    approve_document(client, auth, 'Receipt', receipt['id'])
    assert client.post(f"/api/v1/receipts/{receipt['id']}/post", headers=auth).status_code == 200
    returned = client.post('/api/v1/purchase-returns', headers=auth, json={'receipt_id': receipt['id'],
        'reason': '价格来源固定', 'lines': [{'receipt_line_id': receipt['lines'][0]['id'], 'quantity': '1'}]}).json()
    approve_document(client, auth, 'PurchaseReturn', returned['id'])
    with orm_session(write=True) as db:
        db.get(PurchaseOrderLine, order['lines'][0]['id']).unit_price = '9'
    result = client.post(f"/api/v1/purchase-returns/{returned['id']}/submit", headers=auth)
    assert result.status_code == 409 and '批准内容' in result.json()['detail']
    with orm_session() as db:
        assert find_case(db, 'PurchaseReturn', returned['id']).status == 'approved'
        assert db.scalar(select(func.count()).select_from(WarehouseOutbound)) == 0


@pytest.mark.parametrize('kind', ['PurchaseReturn', 'WarehouseOutbound'])
def test_reverse_needs_own_fixed_reason_approval(returns, kind):
    client, auth, row, material = returns
    if kind == 'PurchaseReturn':
        identifier = row['id']
        child = release(client, auth, row)
        approve_document(client, auth, 'WarehouseOutbound', child)
        assert client.post(f'/api/v1/warehouse-outbounds/{child}/post', headers=auth).status_code == 200
        endpoint = f'/api/v1/purchase-returns/{identifier}/reverse'
    else:
        created = client.post('/api/v1/warehouse-outbounds', headers=auth, json={
            'warehouse_id': 1, 'reason': 'sample', 'note': '样品发出',
            'lines': [{'material_id': material, 'quantity': '2'}]})
        identifier = created.json()['id']
        approve_document(client, auth, kind, identifier)
        assert client.post(f'/api/v1/warehouse-outbounds/{identifier}/post', headers=auth).status_code == 200
        endpoint = f'/api/v1/warehouse-outbounds/{identifier}/reverse'
    assert client.post(endpoint, headers=auth, json={'reason': '实际未发出'}).status_code == 409
    approve_document(client, auth, kind, identifier, intent='reverse', reason='实际未发出')
    assert client.post(endpoint, headers=auth, json={'reason': '临时改原因'}).status_code == 409
    result = client.post(endpoint, headers=auth, json={'reason': '实际未发出'})
    assert result.status_code == 201, result.text
    assert result.json()['reversal_approval']['status'] == 'executed'
    if kind == 'PurchaseReturn':
        # 仓库保留原出库记录，同时显示父退货的实际冲销关联。
        outbound = next(item for item in client.get('/api/v1/warehouse-outbounds', headers=auth).json()
                        if item['id'] == child)
        assert outbound['purchase_return_reversal_id'] == result.json()['reversal_id']
        assert outbound['reversal_id'] is None
    with orm_session() as db:
        assert sum(map(Decimal, db.scalars(select(StockMovement.quantity)))) == 10
