"""业务测试显式送审工具；不会拦截请求、自动批准或放宽生产权限。"""


def approve_document(client, author_headers, document_type, identifier, *, intent='execute', reason=''):
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
        created = client.post('/api/v1/users', headers=author_headers,
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
