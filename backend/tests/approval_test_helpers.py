"""业务测试显式送审工具；不会拦截请求、自动批准或放宽生产权限。"""


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
