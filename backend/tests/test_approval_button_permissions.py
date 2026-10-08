"""角色分配、三种按钮授权、自审及实时撤权的完整接口回归。"""

from sqlalchemy import select

from app.core.approval_catalog import APPROVAL_TYPES
from app.core.database import connection, migrate
from app.core.models import DocumentApprovalAuthor, DocumentApprovalEvent
from app.core.orm import orm_session
from test_document_approval import context, approval_api


def role(client, admin, code, permissions):
    payload = {'code': code, 'label': '按钮权限验证', 'permissions': permissions}
    assert client.post('/api/v1/roles', headers=admin, json=payload).status_code == 201
    account = client.post('/api/v1/users', headers=admin, json={
        'username': code, 'password': 'secure-pass-123', 'roles': [code]})
    assert account.status_code == 201
    login = client.post('/api/v1/auth/login', json={'username': code, 'password': 'secure-pass-123'}).json()
    return {'Authorization': 'Bearer ' + login['token']}


def test_catalog_and_custom_roles_gate_each_step_without_person_exclusions(context):
    client, admin, source = context
    identifier = source['id']
    catalog = {row['code']: row for row in client.get('/api/v1/permissions', headers=admin).json()}
    for rule in APPROVAL_TYPES.values():
        codes = [rule.step_permission({'name': '', 'action': action}) for action in ('review', 'verify', 'approve')]
        assert len(set(codes)) == 3
        assert all(code in catalog for code in codes)
        assert len({catalog[code]['group_path'][-1]['code'] for code in codes}) == 1
    steps = [{'name': '数量核对', 'role': 'admin', 'action': 'review'},
             {'name': '责任核对', 'role': None, 'action': 'verify'},
             {'name': '最终决定', 'role': None, 'action': 'approve'}]
    saved = client.put('/api/v1/system/document-approvals/WarehouseInbound', headers=admin,
        json={'version': 1, 'steps': steps})
    assert saved.status_code == 200, saved.text
    permissions = ['other_inbound.view', 'other_inbound.create']
    actors = {action: role(client, admin, 'button_' + action, permissions + ['other_inbound.' + action])
              for action in ('review', 'verify', 'approve')}
    viewer = role(client, admin, 'button_viewer', permissions + ['other_inbound.post'])
    sent = approval_api(client, admin, identifier, 'submit', version=0)
    assert sent.status_code == 200 and sent.json()['can_review']
    # 旧指定职务不阻止自定义角色；授权仅取当前步骤，不允许跳步或执行权限代替审批。
    for index, action in enumerate(('review', 'verify', 'approve')):
        version = index + 1
        for name, headers in {**actors, 'viewer': viewer}.items():
            state = approval_api(client, headers, identifier).json()
            assert state['can_review'] is (name == action)
            if name != action:
                denied = approval_api(client, headers, identifier, 'approve', version=version)
                assert denied.status_code == 403
                assert approval_api(client, admin, identifier).json()['version'] == version
        accepted = approval_api(client, actors[action], identifier, 'approve', version=version)
        assert accepted.status_code == 200, accepted.text
    assert accepted.json()['status'] == 'approved'
    # 已批准后只能执行，重复点击不会增加事件或跳过版本。
    assert approval_api(client, actors['approve'], identifier, 'approve', version=4).status_code == 409
    history = accepted.json()['events']
    assert [event['step_name'] for event in history if event['action'] == 'approve'] == [s['name'] for s in steps]


def test_creator_with_all_permissions_can_complete_three_steps_and_reject_own_document(context):
    client, admin, source = context
    identifier = source['id']
    steps = [{'name': label, 'role': None, 'action': action}
             for label, action in [('审核', 'review'), ('核准', 'verify'), ('批准', 'approve')]]
    assert client.put('/api/v1/system/document-approvals/WarehouseInbound', headers=admin,
        json={'version': 1, 'steps': steps}).status_code == 200
    assert approval_api(client, admin, identifier, 'submit', version=0).status_code == 200
    assert approval_api(client, admin, identifier, 'reject', version=1, reason='').status_code == 422
    rejected = approval_api(client, admin, identifier, 'reject', version=1, reason='补充凭据')
    assert rejected.status_code == 200 and rejected.json()['status'] == 'rejected'
    assert approval_api(client, admin, identifier, 'submit', version=2).status_code == 200
    for version in (3, 4, 5):
        state = approval_api(client, admin, identifier).json()
        assert state['can_review']
        result = approval_api(client, admin, identifier, 'approve', version=version)
        assert result.status_code == 200
        if version < 5:
            assert client.post(f'/api/v1/warehouse-inbounds/{identifier}/post', headers=admin).status_code == 409
    assert result.json()['status'] == 'approved'
    assert client.post(f'/api/v1/warehouse-inbounds/{identifier}/post', headers=admin).status_code == 200
    with orm_session() as db:
        assert db.get(DocumentApprovalAuthor, ('WarehouseInbound', identifier, 1)) is not None
        assert {event.actor_id for event in db.scalars(select(DocumentApprovalEvent))} == {1}


def test_permission_revocation_takes_effect_for_existing_login_and_rejection(context):
    client, admin, source = context
    headers = role(client, admin, 'button_revoked', ['other_inbound.view', 'other_inbound.approve'])
    identifier = source['id']
    approval_api(client, admin, identifier, 'submit', version=0)
    assert approval_api(client, headers, identifier).json()['can_review']
    response = client.put('/api/v1/roles/button_revoked', headers=admin,
        json={'label': '已撤销批准权限', 'permissions': ['other_inbound.view']})
    assert response.status_code == 200
    assert not approval_api(client, headers, identifier).json()['can_review']
    for action in ('approve', 'reject'):
        assert approval_api(client, headers, identifier, action, version=1, reason='旧登录尝试').status_code == 403
    assert approval_api(client, admin, identifier).json()['version'] == 1


def test_v95_migration_preserves_fixed_snapshots_and_only_extends_existing_review_roles(context):
    client, admin, source = context
    approval_api(client, admin, source['id'], 'submit', version=0)
    role(client, admin, 'button_legacy', ['other_inbound.view', 'other_inbound.review'])
    role(client, admin, 'button_ungranted', ['other_inbound.view'])
    with connection() as db:
        # 模拟 v94 权限目录，业务正文、审批实例及不可改写事件保持原样。
        events = [tuple(row) for row in db.execute('SELECT * FROM document_approval_events')]
        cases = [tuple(row) for row in db.execute('SELECT * FROM document_approval_cases')]
        db.execute("DELETE FROM role_permissions WHERE permission_code IN ('other_inbound.verify','other_inbound.approve')")
        db.execute("DELETE FROM permissions WHERE code IN ('other_inbound.verify','other_inbound.approve')")
        db.execute('PRAGMA user_version = 94')
    migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 95
        assert [tuple(row) for row in db.execute('SELECT * FROM document_approval_events')] == events
        assert [tuple(row) for row in db.execute('SELECT * FROM document_approval_cases')] == cases
        granted = {row[0] for row in db.execute("SELECT permission_code FROM role_permissions WHERE role_code='button_legacy'")}
        assert {'other_inbound.review', 'other_inbound.verify', 'other_inbound.approve'} <= granted
        assert list(db.execute("SELECT 1 FROM role_permissions WHERE role_code='button_ungranted' AND permission_code LIKE '%.approve'")) == []
    # 重放不会重授管理员之后主动撤掉的权限。
    client.put('/api/v1/roles/button_legacy', headers=admin,
        json={'label': '仅审核', 'permissions': ['other_inbound.view', 'other_inbound.review']})
    migrate()
    assert next(row for row in client.get('/api/v1/roles', headers=admin).json()
                if row['code'] == 'button_legacy')['permissions'] == ['other_inbound.review', 'other_inbound.view']
