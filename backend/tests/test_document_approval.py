"""审批模板、独立人员、内容冻结及真实 SQLite 并发回滚验证。"""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from app.core.approval_catalog import APPROVAL_TYPES
from app.core.database import connection, migrate
from app.core.document_approval import (
    case_data, find_case, mark_executed, policy, record_author,
    require_approved, review, save_policy, submit, withdraw,
)
from app.core.document_types import DOCUMENT_TYPES
from app.core.models import (
    DocumentApprovalAuthor, DocumentApprovalCase, DocumentApprovalEvent,
    DocumentApprovalPolicy, DocumentApprovalPolicyChange, Material, Permission,
    StockMovement, User, UserRole, WarehouseInbound, WarehouseInboundLine,
)
from app.core.orm import orm_session
from app.main import app


@pytest.fixture
def context(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'approvals.db'))
    with TestClient(app, client=('127.0.0.1', 1)) as client:
        assert client.post('/api/v1/setup/admin', json={
            'username': 'admin', 'password': 'secure-pass-123'}).status_code == 201
        login = client.post('/api/v1/auth/login', json={
            'username': 'admin', 'password': 'secure-pass-123'}).json()
        auth = {'Authorization': 'Bearer ' + login['token']}
        for name, role in [('reviewer', 'admin'), ('submitter', 'warehouse'), ('editor', 'admin')]:
            assert client.post('/api/v1/users', headers=auth, json={
                'username': name, 'password': 'secure-pass-123', 'roles': [role]}).status_code == 201
        material = client.post('/api/v1/materials', headers=auth, json={
            'sku': 'APPROVAL', 'name': '审批测试物料', 'unit': '个'}).json()['id']
        result = client.post('/api/v1/warehouse-inbounds', headers=auth, json={
            'warehouse_id': 1, 'reason': 'gift', 'note': '独立审批验证',
            'lines': [{'material_id': material, 'quantity': '10'}]})
        assert result.status_code == 201
        record = result.json()
        yield client, auth, record


def snapshot(db, identifier):
    # 内容由服务端 ORM 查询；数量、参考号、仓库与说明纳入固定快照。
    source = db.get(WarehouseInbound, identifier)
    return {'warehouse_id': source.warehouse_id, 'reference': source.reference,
            'note': source.note, 'reason': source.reason,
            'lines': [{'id': line.id, 'material_id': line.material_id, 'quantity': line.quantity}
                      for line in db.scalars(select(WarehouseInboundLine).where(
                          WarehouseInboundLine.inbound_id == identifier).order_by(WarehouseInboundLine.id))]}


def send(identifier, user_id=1, version=0, **extra):
    with orm_session(write=True) as db:
        return submit(db, 'WarehouseInbound', identifier, snapshot(db, identifier), version, user_id, **extra)


def approve(identifier, user_id=2, version=1, **extra):
    with orm_session(write=True) as db:
        return review(db, 'WarehouseInbound', identifier, snapshot(db, identifier), version, user_id,
                      approve=True, **extra)


def failure(code, operation, *args, **kwargs):
    with pytest.raises(HTTPException) as error:
        operation(*args, **kwargs)
    assert error.value.status_code == code


def test_29_types_and_permissions_are_complete(context):
    client, auth, _ = context
    rows = client.get('/api/v1/system/document-approvals', headers=auth).json()
    assert {row['document_type'] for row in rows} == {item[0] for item in DOCUMENT_TYPES}
    assert all(row['version'] == 1 and row['steps'] == [{'name': '批准', 'role': None}] for row in rows)
    with orm_session() as db:
        for rule in APPROVAL_TYPES.values():
            # 审核、提交、执行均使用已注册的不同领域权限边界。
            for permission in (rule.view_permission, rule.submit_permission,
                               rule.review_permission, rule.execute_permission):
                assert db.get(Permission, permission) is not None, permission
            assert rule.model.__table__.c.document_no is not None


def test_independent_review_and_monotonic_execution(context):
    _, _, source = context
    identifier = source['id']
    assert send(identifier)['status'] == 'submitted'
    failure(403, approve, identifier, user_id=1)
    approved = approve(identifier)
    assert approved['status'] == 'approved' and approved['version'] == 2
    failure(409, approve, identifier, version=1)
    with orm_session(write=True) as db:
        row = require_approved(db, 'WarehouseInbound', identifier, snapshot(db, identifier), 1)
        mark_executed(db, row, 1)
        assert case_data(row)['version'] == 3
    failure(409, send, identifier, version=3)
    with orm_session(write=True) as db:
        failure(409, require_approved, db, 'WarehouseInbound', identifier, snapshot(db, identifier), 1)
    with orm_session() as db:
        events = list(db.scalars(select(DocumentApprovalEvent).order_by(DocumentApprovalEvent.version)))
        assert [(row.action, row.actor_id) for row in events] == [('submit', 1), ('approve', 2), ('execute', 1)]
        assert all(row.created_at for row in events)
        assert db.get(WarehouseInbound, identifier).document_no == source['document_no']


def test_editor_submitter_cannot_self_review_after_resubmission(context):
    identifier = context[2]['id']
    with orm_session(write=True) as db:
        record_author(db, 'WarehouseInbound', identifier, 4)
    send(identifier, user_id=3)
    failure(403, approve, identifier, user_id=3)
    failure(403, approve, identifier, user_id=4)
    with orm_session(write=True) as db:
        withdrawn = withdraw(db, 'WarehouseInbound', identifier, 1, 3)
        assert withdrawn['version'] == 2
    send(identifier, user_id=1, version=2)
    failure(403, approve, identifier, user_id=4, version=3)
    failure(403, approve, identifier, user_id=3, version=3)
    assert approve(identifier, version=3)['status'] == 'approved'
    with orm_session() as db:
        assert list(db.scalars(select(DocumentApprovalAuthor.user_id).order_by(DocumentApprovalAuthor.user_id))) == [1, 3, 4]


def test_multiple_steps_freeze_template_and_require_different_people(context):
    identifier = context[2]['id']
    with orm_session(write=True) as db:
        save_policy(db, 'WarehouseInbound', [{'name': '审核', 'role': 'admin'},
                                             {'name': '批准', 'role': None}], 1, 1)
    send(identifier)
    with orm_session(write=True) as db:
        save_policy(db, 'WarehouseInbound', [{'name': '新版一步', 'role': None}], 2, 1)
    first = approve(identifier)
    assert first['status'] == 'submitted' and first['current_step'] == 1
    assert first['policy_version'] == 2 and len(first['steps']) == 2
    failure(403, approve, identifier, version=2)
    final = approve(identifier, user_id=4, version=2)
    assert final['status'] == 'approved' and final['current_step'] == 2


def test_edit_author_boundary_freezes_pending_and_approved_content(context):
    identifier = context[2]['id']
    send(identifier)
    for approved in (False, True):
        if approved:
            approve(identifier)
        with orm_session(write=True) as db:
            failure(409, record_author, db, 'WarehouseInbound', identifier, 4)
    with orm_session(write=True) as db:
        withdraw(db, 'WarehouseInbound', identifier, 2, 1)
        record_author(db, 'WarehouseInbound', identifier, 4)
    with orm_session() as db:
        assert db.get(DocumentApprovalAuthor, ('WarehouseInbound', identifier, 4)) is not None


def test_content_changed_rejected_at_review_and_execution(context):
    identifier = context[2]['id']
    send(identifier)
    with orm_session(write=True) as db:
        db.execute(update(WarehouseInboundLine).where(WarehouseInboundLine.inbound_id == identifier).values(quantity='11'))
    failure(409, approve, identifier)
    with orm_session(write=True) as db:
        withdraw(db, 'WarehouseInbound', identifier, 1, 1)
    send(identifier, version=2)
    approve(identifier, version=3)
    with orm_session(write=True) as db:
        db.execute(update(WarehouseInbound).where(WarehouseInbound.id == identifier).values(note='批准后内容变化'))
    with orm_session(write=True) as db:
        failure(409, require_approved, db, 'WarehouseInbound', identifier, snapshot(db, identifier), 1)


def test_rejection_reason_and_history_preserved(context):
    identifier = context[2]['id']
    send(identifier)
    with orm_session(write=True) as db:
        failure(422, review, db, 'WarehouseInbound', identifier, snapshot(db, identifier), 1, 2,
                approve=False, reason='  ')
    with orm_session(write=True) as db:
        rejected = review(db, 'WarehouseInbound', identifier, snapshot(db, identifier), 1, 2,
                          approve=False, reason=' 数量依据不足 ')
        assert rejected['status'] == 'rejected'
    with orm_session(write=True) as db:
        db.get(WarehouseInbound, identifier).note = '补充数量依据'
    send(identifier, version=2)
    with orm_session() as db:
        rows = list(db.scalars(select(DocumentApprovalEvent).order_by(DocumentApprovalEvent.id)))
        assert rows[1].reason == '数量依据不足'
        assert json.loads(rows[0].state_json)['snapshot']['note'] == '独立审批验证'
        assert json.loads(rows[-1].state_json)['snapshot']['note'] == '补充数量依据'
        assert rows[-1].generation == 2


def test_live_permission_revocation_and_disabled_reviewer(context):
    identifier = context[2]['id']
    send(identifier)
    with orm_session(write=True) as db:
        db.execute(delete(UserRole).where(UserRole.user_id == 2))
        db.add(UserRole(user_id=2, role_code='warehouse'))
    failure(403, approve, identifier)
    with orm_session(write=True) as db:
        db.get(User, 4).is_active = 0
    failure(401, approve, identifier, user_id=4)


def test_step_role_is_checked_against_current_roles(context):
    identifier = context[2]['id']
    with orm_session(write=True) as db:
        save_policy(db, 'WarehouseInbound', [{'name': '仓库审核', 'role': 'warehouse'}], 1, 1)
    send(identifier)
    failure(403, approve, identifier)
    with orm_session(write=True) as db:
        db.add(UserRole(user_id=2, role_code='warehouse'))
    assert approve(identifier)['status'] == 'approved'


def test_concurrent_approval_has_one_decision(context):
    identifier = context[2]['id']
    send(identifier)

    def decide(user_id):
        try:
            approve(identifier, user_id=user_id)
            return 200
        except HTTPException as error:
            return error.status_code

    # 两个真实写事务争用同一个版本，必须只有一个成功。
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(decide, [2, 4])) == [200, 409]
    with orm_session() as db:
        assert db.scalar(select(func.count()).select_from(DocumentApprovalEvent).where(
            DocumentApprovalEvent.action == 'approve')) == 1


def test_failed_execution_rolls_back_stock_and_approval(context):
    identifier = context[2]['id']
    send(identifier)
    approve(identifier)
    with pytest.raises(RuntimeError, match='模拟业务失败'):
        with orm_session(write=True) as db:
            case = require_approved(db, 'WarehouseInbound', identifier, snapshot(db, identifier), 1)
            material_id = db.scalar(select(Material.id))
            db.add(StockMovement(warehouse_id=1, material_id=material_id, quantity='10',
                source_type='other_inbound', source_id=identifier, source_line_id=1, created_by=1))
            mark_executed(db, case, 1)
            raise RuntimeError('模拟业务失败')
    with orm_session() as db:
        assert find_case(db, 'WarehouseInbound', identifier).status == 'approved'
        assert db.scalar(select(func.count()).select_from(StockMovement)) == 0
        assert db.scalar(select(func.count()).select_from(DocumentApprovalEvent)) == 2


def test_audit_is_immutable_even_with_bulk_orm_operations(context):
    identifier = context[2]['id']
    send(identifier)
    with pytest.raises(IntegrityError, match='审批历史不能修改或删除'):
        with orm_session(write=True) as db:
            db.execute(update(DocumentApprovalEvent).values(reason='篡改'))
    with pytest.raises(IntegrityError, match='审批历史不能修改或删除'):
        with orm_session(write=True) as db:
            db.execute(delete(DocumentApprovalAuthor))
    with orm_session() as db:
        assert db.scalar(select(DocumentApprovalEvent.reason)) == ''


def test_write_boundary_and_unapproved_execution(context):
    identifier = context[2]['id']
    with orm_session() as db:
        with pytest.raises(RuntimeError, match='业务写事务'):
            submit(db, 'WarehouseInbound', identifier, snapshot(db, identifier), 0, 1)
    with orm_session(write=True) as db:
        failure(409, require_approved, db, 'WarehouseInbound', identifier, snapshot(db, identifier), 1)
    failure(422, send, identifier, version=True)
    failure(409, send, identifier, version=5)
    with orm_session() as db:
        assert find_case(db, 'WarehouseInbound', identifier) is None


def test_policy_api_validation_authorization_and_conflict(context):
    client, auth, _ = context
    url = '/api/v1/system/document-approvals/WarehouseInbound'
    payload = {'version': 1, 'steps': [{'name': '审核', 'role': None}]}
    assert client.get(url).status_code == 401
    login = client.post('/api/v1/auth/login', json={
        'username': 'submitter', 'password': 'secure-pass-123'}).json()
    warehouse = {'Authorization': 'Bearer ' + login['token']}
    assert client.get(url, headers=warehouse).status_code == 200
    assert client.get('/api/v1/system/document-approvals/Journal', headers=warehouse).status_code == 403
    assert client.put(url, headers=warehouse, json=payload).status_code == 403
    for invalid in [
        {**payload, 'version': True}, {**payload, 'version': '1'},
        {**payload, 'steps': []}, {**payload, 'steps': [{'name': '  ', 'role': None}]},
        {**payload, 'steps': [{'name': '批准', 'role': 'not-a-role'}]},
        {**payload, 'steps': [{'name': '批准', 'role': None, 'permission': 'users.manage'}]},
    ]:
        assert client.put(url, headers=auth, json=invalid).status_code == 422
    result = client.put(url, headers=auth, json=payload)
    assert result.status_code == 200 and result.json()['version'] == 2
    assert client.put(url, headers=auth, json=payload).status_code == 409
    assert client.put('/api/v1/system/document-approvals/users', headers=auth, json=payload).status_code == 422
    with orm_session() as db:
        assert db.scalar(select(func.count()).select_from(DocumentApprovalPolicyChange)) == 1


def test_two_administrators_cannot_overwrite_policy(context):
    def configure(input):
        name, user_id = input
        try:
            with orm_session(write=True) as db:
                save_policy(db, 'WarehouseInbound', [{'name': name, 'role': None}], 1, user_id)
            return 200
        except HTTPException as error:
            return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(configure, [('审核后批准', 1), ('独立批准', 2)])) == [200, 409]


def test_migration_replay_keeps_numbers_and_does_not_invent_approvals(context):
    identifier = context[2]['id']
    with connection() as db:
        # 真实重建第 88 版形态，避免新表留在旧库夹具中让迁移假通过。
        for table in ('document_approval_events', 'document_approval_authors',
                      'document_approval_cases', 'document_approval_policy_changes', 'document_approval_policies'):
            db.execute(f'DROP TABLE {table}')
        for permission in {rule.review_permission for rule in APPROVAL_TYPES.values() if not rule.native_workflow}:
            db.execute('DELETE FROM role_permissions WHERE permission_code=?', (permission,))
            db.execute('DELETE FROM permissions WHERE code=?', (permission,))
        db.execute('PRAGMA user_version=88')
    migrate()
    with orm_session() as db:
        assert db.get(WarehouseInbound, identifier).document_no == context[2]['document_no']
        assert db.scalar(select(func.count()).select_from(DocumentApprovalCase)) == 0
        assert db.scalar(select(func.count()).select_from(DocumentApprovalPolicy)) == 29
    send(identifier)
    approve(identifier)
    migrate()
    with orm_session() as db:
        assert find_case(db, 'WarehouseInbound', identifier).version == 2
        assert db.scalar(select(func.count()).select_from(DocumentApprovalEvent)) == 2
        assert policy(db, 'WarehouseInbound').version == 1


def test_upgrade_failure_rolls_back_schema_and_permissions(context, monkeypatch):
    from app.core import database
    original = database.connection
    with original() as db:
        for table in ('document_approval_events', 'document_approval_authors',
                      'document_approval_cases', 'document_approval_policy_changes', 'document_approval_policies'):
            db.execute(f'DROP TABLE {table}')
        for permission in {rule.review_permission for rule in APPROVAL_TYPES.values() if not rule.native_workflow}:
            db.execute('DELETE FROM role_permissions WHERE permission_code=?', (permission,))
            db.execute('DELETE FROM permissions WHERE code=?', (permission,))
        db.execute('PRAGMA user_version=88')

    class FailingConnection:
        def __init__(self, db):
            self.db = db

        def __getattr__(self, name):
            return getattr(self.db, name)

        def execute(self, statement, *args):
            if 'CREATE TABLE IF NOT EXISTS document_approval_cases' in statement:
                raise sqlite3.OperationalError('模拟审批迁移失败')
            return self.db.execute(statement, *args)

    @contextmanager
    def failing_connection():
        with original() as db:
            yield FailingConnection(db)

    monkeypatch.setattr(database, 'connection', failing_connection)
    with pytest.raises(sqlite3.OperationalError, match='模拟审批迁移失败'):
        migrate()
    with original() as db:
        # 失败不能留下部分模板、权限或更高版本，也不能影响原业务编号。
        assert db.execute('PRAGMA user_version').fetchone()[0] == 88
        assert db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'document_approval_%'").fetchall() == []
        assert db.execute("SELECT code FROM permissions WHERE code='other_inbound.review'").fetchall() == []
        assert db.execute('SELECT document_no FROM warehouse_inbounds WHERE id=?',
                          (context[2]['id'],)).fetchone()[0] == context[2]['document_no']
    monkeypatch.setattr(database, 'connection', original)
    migrate()
    with orm_session() as db:
        assert db.get(DocumentApprovalPolicy, 'WarehouseInbound') is not None
