"""业务测试显式送审工具；不会拦截请求、自动批准或放宽生产权限。"""


def receive_legacy_issue(client, signer_headers, issue_id):
    """夹具显式签收旧发料接口产生的新领料单，不把出库事实伪装为实收。"""
    from uuid import uuid4
    issues = client.get('/api/v1/material-issues', headers=signer_headers)
    assert issues.status_code == 200, issues.text
    issue = next(row for row in issues.json() if row['id'] == issue_id)
    receipt_id = issue['material_receipt_id']
    assert receipt_id is not None, issue
    result = client.get(f'/api/v1/material-receipts/{receipt_id}', headers=signer_headers)
    assert result.status_code == 200, result.text
    receipt = result.json()
    result = client.post(f'/api/v1/material-receipts/{receipt_id}/execute', headers=signer_headers,
        json={'version': receipt['version'], 'request_id': str(uuid4()), 'reason': '生产现场逐项核对实收',
              'lines': [{'line_id': line['id'], 'quantity': line['remaining_quantity']} for line in receipt['lines']]})
    assert result.status_code == 200, result.text
    return result.json()


def reverse_legacy_receipt(client, actor_headers, issue_id, reason='签收登记有误'):
    """更正夹具显式批准并撤销签收事实，再由原发料冲销恢复库存。"""
    from uuid import uuid4
    issue = next(row for row in client.get('/api/v1/material-issues', headers=actor_headers).json()
                 if row['id'] == issue_id)
    identifier = issue['material_receipt_id']
    approve_document(client, actor_headers, 'MaterialReceipt', identifier, intent='reverse', reason=reason)
    receipt = client.get(f'/api/v1/material-receipts/{identifier}', headers=actor_headers).json()
    response = client.post(f'/api/v1/material-receipts/{identifier}/reverse', headers=actor_headers,
        json={'version': receipt['version'], 'request_id': str(uuid4()), 'reason': reason})
    assert response.status_code == 200, response.text
    return response.json()


def approve_document(client, author_headers, document_type, identifier, *, intent='execute', reason='', account_headers=None):
    path = f'/api/v1/system/document-approvals/{document_type}/{identifier}'
    state = client.get(path, headers=author_headers, params={'intent': intent})
    assert state.status_code == 200, state.text
    assert state.json()['can_submit'], state.text
    submitted = client.post(path + '/submit', headers=author_headers,
        json={'version': state.json()['version'], 'intent': intent, 'reason': reason})
    assert submitted.status_code == 200, submitted.text
    state = submitted.json()
    for index, step in enumerate(state['steps'], 1):
        # 每一步使用独立测试人员，并通过真实账号和审批接口，保证被测领域仍受服务端审批边界保护。
        username = f'independent_reviewer_{index}'
        roles = sorted(set(['admin', *([step['role']] if step['role'] else [])]))
        created = client.post('/api/v1/users', headers=account_headers if account_headers is not None else author_headers,
            json={'username': username, 'password': 'approval-test-pass-123', 'roles': roles})
        assert created.status_code in (201, 409), created.text
        login = client.post('/api/v1/auth/login', json={
            'username': username, 'password': 'approval-test-pass-123'})
        assert login.status_code == 200, login.text
        reviewer = {'Authorization': 'Bearer ' + login.json()['token']}
        assert client.get(path, headers=reviewer, params={'intent': intent}).json()['can_review']
        approved = client.post(path + '/approve', headers=reviewer,
            json={'version': state['version'], 'intent': intent, 'reason': '测试独立核对'})
        assert approved.status_code == 200, approved.text
        state = approved.json()
    assert state['status'] == 'approved', state
    return state


def prepare_purchase_return(client, author_headers, identifier):
    # 业务夹具显式完成两张单据的审批，保留旧确认接口的数量、权限与回滚断言。
    approve_document(client, author_headers, 'PurchaseReturn', identifier)
    converted = client.post(f'/api/v1/purchase-returns/{identifier}/submit', headers=author_headers)
    assert converted.status_code == 200, converted.text
    row = converted.json()
    approve_document(client, author_headers, 'WarehouseOutbound', row['outbound_id'])
    return row


def journal_approval_request(client, record, action, *, reason, headers=None):
    # 失败路径也显式测试新版本审批，不能用旧接口固定返回的冲突掩盖来源和期间回归。
    path = f'/api/v1/system/document-approvals/Journal/{record["id"]}'
    return client.post(path + '/' + action, headers=headers,
        json={'version': record['approval']['version'], 'reason': reason})


def execute_payment(client, author_headers, record, *, account_headers=None):
    # 仅供业务夹具显式调用；建单请求保持草稿语义，独立批准后再走真实执行入口。
    approve_document(client, author_headers, 'PaymentRecord', record['id'], reason='核对资金原始依据', account_headers=account_headers)
    result = client.post(f'/api/v1/finance/payment-records/{record["id"]}/post', headers=author_headers,
        json={'version': record['version'], 'reason': '核对后执行资金'})
    assert result.status_code == 200, result.text
    return result.json()


def execute_subledger_payment(client, author_headers, record):
    # 分户草稿明确走独立审批与真实执行，余额回归不能用建单代替资金事实。
    approve_document(client, author_headers, 'SubledgerPayment', record['id'], reason='核对历史原单及银行回单')
    result = client.post(f'/api/v1/finance/subledger-openings/payments/{record["id"]}/post', headers=author_headers,
        json={'version': record['version'], 'reason': '核对后执行分户资金'})
    assert result.status_code == 200, result.text
    return result.json()


def execute_order_settlement(client, author_headers, record, *, account_headers=None):
    # 核销夹具显式独立批准再执行，不能把建单响应当成已改变余额的经济事实。
    approve_document(client, author_headers, 'OrderSettlementTransfer', record['id'], reason='核对同一往来双方订单', account_headers=account_headers)
    result = client.post(f'/api/v1/finance/order-settlements/{record["id"]}/post', headers=author_headers,
        json={'version': record['version'], 'reason': '核对后执行核销'})
    assert result.status_code == 200, result.text
    return result.json()


def execute_production_settlement(client, author_headers, record, *, account_headers=None):
    # 预计分摊先独立核对批准，再通过原写事务正式计价并锁定成本来源。
    approve_document(client,author_headers,'ProductionCostSettlement',record['id'],reason='核对生产数量费用与分摊来源', account_headers=account_headers)
    response=client.post(f'/api/v1/production-costs/settlements/{record["id"]}/post',headers=author_headers,
        json={'version':record['version'],'reason':'独立批准后正式结算'})
    assert response.status_code==200,response.text
    return response.json()


def create_planned_work_order(client, *, headers, json, account_headers=None):
    """下游业务夹具显式走计划编制、独立审批和分批生成，不模拟旧建单接口成功。"""
    from uuid import uuid4
    from httpx import Response
    from app.production.plans import today
    plan = client.post('/api/v1/production/plans', headers=headers, json={
        'reference': json.get('reference') or '业务验收生产计划', 'note': json.get('note', ''),
        'reason': '业务验收安排', 'lines': [{'bom_id': json['bom_id'], 'warehouse_id': json['warehouse_id'],
        'quantity': json['target_quantity'], 'start_date': today(), 'end_date': today()}]})
    if plan.status_code != 201:
        return plan
    row = plan.json()
    approve_document(client, headers, 'ProductionPlan', row['id'], reason='核对生产安排', account_headers=account_headers)
    row = client.get(f'/api/v1/production/plans/{row["id"]}', headers=headers).json()
    released = client.post(f'/api/v1/production/plans/{row["id"]}/release', headers=headers, json={
        'version': row['version'], 'approval_version': row['approval']['version'], 'line_id': row['lines'][0]['id'],
        'quantity': json['target_quantity'], 'reason': '按批准计划生成', 'request_id': str(uuid4())})
    if released.status_code != 201:
        return released
    identifier = released.json()['releases'][0]['work_order_id']
    orders = client.get('/api/v1/work-orders', headers=headers)
    assert orders.status_code == 200, orders.text
    return Response(201, json=next(row for row in orders.json() if row['id'] == identifier))


def seed_legacy_work_order(client, *, headers, json):
    """仅用于旧数据兼容用例：直接布置升级前工单，不恢复已关闭的 HTTP 建单入口。"""
    from httpx import Response
    from app.core.orm import orm_session
    from app.production.work_orders import WorkOrderInput, create_work_order_in_session
    actor = client.get('/api/v1/auth/me', headers=headers)
    assert actor.status_code == 200, actor.text
    with orm_session(write=True) as db:
        row = create_work_order_in_session(db, WorkOrderInput(**json), actor.json())
    # 走真实列表读取补充单号，与升级前 HTTP 回执的字段保持一致。
    orders = client.get('/api/v1/work-orders', headers=headers)
    assert orders.status_code == 200, orders.text
    return Response(201, json=next(order for order in orders.json() if order['id'] == row['id']))


def planned_order(api, payload, status=201):
    """带状态断言的 API 夹具显式走计划及逐步审批，普通请求函数保持原样。"""
    from app.production.plans import today
    from uuid import uuid4
    row = api('POST', 'production/plans', {'reference': payload.get('reference') or '生产回归计划',
        'note':payload.get('note',''), 'reason':'按业务验收编制', 'lines':[{
        'bom_id':payload['bom_id'], 'warehouse_id':payload['warehouse_id'], 'quantity':payload['target_quantity'],
        'start_date':today(), 'end_date':today()}]}, status=status)
    if status != 201:
        return row
    path = f'system/document-approvals/ProductionPlan/{row["id"]}'
    case = api('GET', path)
    case = api('POST', path+'/submit', {'version':case['version'], 'reason':'核对计划'})
    while case['status'] == 'submitted':
        case = api('POST', path+'/approve', {'version':case['version'], 'reason':'按当前步骤权限核对'})
    assert case['status'] == 'approved', case
    row = api('GET', f'production/plans/{row["id"]}')
    row = api('POST', f'production/plans/{row["id"]}/release', {
        'version':row['version'], 'approval_version':row['approval']['version'], 'line_id':row['lines'][0]['id'],
        'quantity':payload['target_quantity'], 'reason':'按批准计划生成工单', 'request_id':str(uuid4())}, status=201)
    return next(order for order in api('GET', 'work-orders') if order['id']==row['releases'][0]['work_order_id'])
