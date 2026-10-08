"""调拨、盘点和原库存调整审批的事务边界、历史证据及旧客户端保护。"""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from approval_test_helpers import approve_document
from test_document_approval import context
from app.core.document_approval import find_case, save_policy
from app.core.models import DocumentApprovalEvent, StockAdjustment, StockMovement, TransferLine, StocktakeLine, StockAdjustmentLine
from app.core.orm import orm_session


def path(kind, identifier):
    return f'/api/v1/system/document-approvals/{kind}/{identifier}'


@pytest.fixture(params=['Transfer', 'Stocktake', 'StockAdjustment'])
def warehouse_document(context, request):
    client, auth, inbound = context
    approve_document(client, auth, 'WarehouseInbound', inbound['id'])
    assert client.post(f"/api/v1/warehouse-inbounds/{inbound['id']}/post", headers=auth).status_code == 200
    material = inbound['lines'][0]['material_id']
    kind = request.param
    endpoint = {'Transfer': 'transfers', 'Stocktake': 'stocktakes', 'StockAdjustment': 'stock-adjustments'}[kind]
    if kind == 'Transfer':
        target = client.post('/api/v1/warehouses', headers=auth, json={'code': 'DEST', 'name': '目标仓'}).json()['id']
        payload = {'from_warehouse_id': 1, 'to_warehouse_id': target, 'lines': [{'material_id': material, 'quantity': '3'}]}
    elif kind == 'Stocktake':
        payload = {'warehouse_id': 1, 'lines': [{'material_id': material, 'counted_quantity': '13'}]}
    else:
        payload = {'warehouse_id': 1, 'reason': '实物差异核对', 'lines': [{'material_id': material, 'quantity': '3'}]}
    result = client.post('/api/v1/' + endpoint, headers=auth, json=payload)
    assert result.status_code == 201, result.text
    return client, auth, kind, result.json(), '/api/v1/' + endpoint


def test_three_warehouse_types_require_independent_steps_and_reverse(warehouse_document):
    client, auth, kind, row, endpoint = warehouse_document
    with orm_session(write=True) as db:
        save_policy(db, kind, [{'name': name, 'role': None} for name in ('核准', '批准')], 1, 1)
    before = len(client.get('/api/v1/movements', headers=auth).json())
    # 普通确认同样需要批准，不以有无实物批次请求体决定审批。
    assert client.post(f"{endpoint}/{row['id']}/post", headers=auth).status_code == 409
    approved = approve_document(client, auth, kind, row['id'])
    assert approved['current_step'] == 2
    assert len(client.get('/api/v1/movements', headers=auth).json()) == before
    if kind != 'Transfer':
        assert client.post(f"{endpoint}/{row['id']}/cancel", headers=auth).status_code == 409
    posted = client.post(f"{endpoint}/{row['id']}/post", headers=auth)
    assert posted.status_code == 200, posted.text
    assert posted.json()['approval']['status'] == 'executed'
    assert posted.json()['lines'][0]['physical_lots'] == []
    assert client.post(f"{endpoint}/{row['id']}/post", headers=auth).status_code == 409
    reverse = f"{endpoint}/{row['id']}/reverse"
    assert client.post(reverse, headers=auth, json={'reason': '核对更正'}).status_code == 409
    approve_document(client, auth, kind, row['id'], intent='reverse', reason='核对更正')
    # 冲销也冻结原因；普通执行的批准不能替代冲销批准。
    assert client.post(reverse, headers=auth, json={'reason': '另一个原因'}).status_code == 409
    result = client.post(reverse, headers=auth, json={'reason': '核对更正'})
    assert result.status_code == (201 if kind == 'StockAdjustment' else 200), result.text
    assert result.json()['reversal_approval']['status'] == 'executed'


def test_concurrent_warehouse_confirmation_executes_once(warehouse_document):
    client, auth, kind, row, endpoint = warehouse_document
    approve_document(client, auth, kind, row['id'])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.post(f"{endpoint}/{row['id']}/post", headers=auth).status_code, range(2)))
    assert sorted(results) == [200, 409]
    state = client.get(path(kind, row['id']), headers=auth).json()
    assert [item['action'] for item in state['events']] == ['submit', 'approve', 'execute']


def test_warehouse_business_failure_rolls_back_approval(warehouse_document):
    client, auth, kind, row, endpoint = warehouse_document
    approved = approve_document(client, auth, kind, row['id'])
    before = len(client.get('/api/v1/movements', headers=auth).json())

    def fail_after_flush(db, _):
        # 实际业务流水已经写入数据库事务后制造故障，确认审批事件与库存一起回滚。
        if any(isinstance(item, StockMovement) for item in db.new):
            raise RuntimeError('测试仓库流水提交故障')

    event.listen(Session, 'after_flush', fail_after_flush)
    try:
        with pytest.raises(RuntimeError, match='测试仓库流水提交故障'):
            client.post(f"{endpoint}/{row['id']}/post", headers=auth)
    finally:
        event.remove(Session, 'after_flush', fail_after_flush)
    state = client.get(path(kind, row['id']), headers=auth).json()
    assert state['status'] == 'approved' and state['version'] == approved['version']
    assert len(client.get('/api/v1/movements', headers=auth).json()) == before
    assert client.post(f"{endpoint}/{row['id']}/post", headers=auth).status_code == 200


def test_stocktake_checkpoint_is_frozen_even_when_quantities_match(context):
    client, auth, inbound = context
    row = client.post('/api/v1/stocktakes', headers=auth, json={'warehouse_id': 1,
        'lines': [{'material_id': inbound['lines'][0]['material_id'], 'counted_quantity': '0'}]}).json()
    approve_document(client, auth, 'Stocktake', row['id'])
    # 改动原盘点依据也必须重新送审，不能只比较实盘数量。
    with orm_session(write=True) as db:
        db.scalar(select(StocktakeLine).where(StocktakeLine.stocktake_id == row['id'])).movement_id = 987
    result = client.post(f"/api/v1/stocktakes/{row['id']}/post", headers=auth)
    assert result.status_code == 409 and '批准内容' in result.text


def test_adjustment_upgrade_keeps_old_review_without_treating_it_as_new_approval(context):
    client, auth, inbound = context
    row = client.post('/api/v1/stock-adjustments', headers=auth, json={'warehouse_id': 1,
        'reason': '升级前待执行', 'lines': [{'material_id': inbound['lines'][0]['material_id'], 'quantity': '2'}]}).json()
    identifier = row['id']
    # 旧数据库可能停在已批准但未执行，不能直接确认，也不能丢失原审核资料。
    with orm_session(write=True) as db:
        source = db.get(StockAdjustment, identifier)
        source.status, source.submitted_by, source.submitted_at = 'approved', 3, '2025-01-01 09:00:00'
        source.reviewed_by, source.reviewed_at, source.review_reason = 2, '2025-01-02 10:00:00', '原审核说明'
    target = path('StockAdjustment', identifier)
    initial = client.get(target, headers=auth).json()
    assert initial['version'] == 0 and initial['can_submit'] and initial['events'] == []
    assert '原审核说明' in initial['summary'][-1]['value']
    assert client.post(f'/api/v1/stock-adjustments/{identifier}/post', headers=auth).status_code == 409
    for action in ('submit', 'approve', 'reject'):
        assert client.post(f'/api/v1/stock-adjustments/{identifier}/{action}', headers=auth,
            json={'reason': '旧接口审核'}).status_code == 409
    state = client.post(target + '/submit', headers=auth, json={'version': 0}).json()
    assert state['business_status'] == 'submitted' and '原审核说明' in state['summary'][-1]['value']
    login = client.post('/api/v1/auth/login', json={'username': 'submitter', 'password': 'secure-pass-123'}).json()
    original_submitter = {'Authorization': 'Bearer ' + login['token']}
    assert client.get((target + '/approve').removesuffix('/approve'), headers=original_submitter, params={'intent': 'execute'}).json()['can_review']
    login = client.post('/api/v1/auth/login', json={'username': 'reviewer', 'password': 'secure-pass-123'}).json()
    reviewer = {'Authorization': 'Bearer ' + login['token']}
    approved = client.post(target + '/approve', headers=reviewer, json={'version': 1, 'reason': '新审核意见'})
    assert approved.status_code == 200, approved.text
    assert approved.json()['business_status'] == 'approved'
    assert '原审核说明' in approved.json()['summary'][-1]['value']
    with orm_session() as db:
        case = find_case(db, 'StockAdjustment', identifier)
        first = db.scalar(select(DocumentApprovalEvent).where(DocumentApprovalEvent.case_id == case.id)
                          .order_by(DocumentApprovalEvent.id))
        assert json.loads(first.state_json)['prior_native_review']['reviewed_at'] == '2025-01-02 10:00:00'
        assert db.get(StockAdjustment, identifier).review_reason == '新审核意见'
    assert client.post(f'/api/v1/stock-adjustments/{identifier}/post', headers=auth).status_code == 200


def test_changed_warehouse_body_cannot_execute_existing_approval(warehouse_document):
    client, auth, kind, row, endpoint = warehouse_document
    approve_document(client, auth, kind, row['id'])
    with orm_session(write=True) as db:
        model, field = {'Transfer': (TransferLine, 'transfer_id'),
                        'Stocktake': (StocktakeLine, 'stocktake_id'),
                        'StockAdjustment': (StockAdjustmentLine, 'adjustment_id')}[kind]
        line = db.scalar(select(model).where(getattr(model, field) == row['id']))
        if kind == 'Stocktake':
            line.counted_quantity = '14'
        else:
            line.quantity = '4'
    before = len(client.get('/api/v1/movements', headers=auth).json())
    result = client.post(f"{endpoint}/{row['id']}/post", headers=auth)
    assert result.status_code == 409 and '批准内容' in result.text
    assert len(client.get('/api/v1/movements', headers=auth).json()) == before


def test_adjustment_reject_withdraw_resubmit_tracks_native_status(context):
    client, auth, inbound = context
    row = client.post('/api/v1/stock-adjustments', headers=auth, json={'warehouse_id': 1,
        'reason': '差异', 'lines': [{'material_id': inbound['lines'][0]['material_id'], 'quantity': '2'}]}).json()
    target = path('StockAdjustment', row['id'])
    reviewer = {'Authorization': 'Bearer ' + client.post('/api/v1/auth/login',
        json={'username': 'reviewer', 'password': 'secure-pass-123'}).json()['token']}
    assert client.post(target + '/submit', headers=auth, json={'version': 0}).status_code == 200
    assert client.post(target + '/reject', headers=reviewer, json={'version': 1}).status_code == 422
    result = client.post(target + '/reject', headers=reviewer, json={'version': 1, 'reason': '核对依据不足'})
    assert result.status_code == 200 and result.json()['business_status'] == 'rejected'
    assert client.post(target + '/submit', headers=auth, json={'version': 2}).json()['generation'] == 2
    assert client.post(target + '/approve', headers=reviewer, json={'version': 2}).status_code == 409
    assert client.post(target + '/withdraw', headers=auth, json={'version': 3}).json()['business_status'] == 'draft'
    assert client.post(f"/api/v1/stock-adjustments/{row['id']}/cancel", headers=auth).status_code == 200
    state = client.get(target, headers=auth).json()
    assert not state['can_submit'] and len(state['events']) == 4


def test_historical_adjustment_preserves_execution_and_allows_authorized_original_submitter_reverse(context):
    client, auth, inbound = context
    row = client.post('/api/v1/stock-adjustments', headers=auth, json={'warehouse_id': 1,
        'reason': '旧确认', 'lines': [{'material_id': inbound['lines'][0]['material_id'], 'quantity': '2'}]}).json()
    # 模拟升级前已执行的主单，不补造新流程批准，原提交人员按当前冲销步骤按钮权限审批。
    with orm_session(write=True) as db:
        source = db.get(StockAdjustment, row['id'])
        source.status, source.submitted_by, source.submitted_at = 'posted', 3, '2025-01-01 09:00:00'
        source.reviewed_by, source.reviewed_at = 2, '2025-01-02 09:00:00'
    target = path('StockAdjustment', row['id'])
    assert client.get(target, headers=auth).json()['events'] == []
    assert client.post(target + '/submit', headers=auth, json={'version': 0}).status_code == 409
    assert client.post(target + '/submit', headers=auth,
        json={'version': 0, 'intent': 'reverse', 'reason': '复核冲销'}).status_code == 200
    original = {'Authorization': 'Bearer ' + client.post('/api/v1/auth/login',
        json={'username': 'submitter', 'password': 'secure-pass-123'}).json()['token']}
    assert client.get((target + '/approve').removesuffix('/approve'), headers=original, params={'intent': 'reverse'}).json()['can_review']
    assert client.get(target, headers=auth).json()['events'] == []
