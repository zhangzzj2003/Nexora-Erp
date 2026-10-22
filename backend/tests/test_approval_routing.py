"""金额分支的真实送审、流程冻结、冲突回滚及旧库迁移。"""

import json
import sqlite3
from contextlib import contextmanager
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from test_document_approval import context
from test_purchase_document_approval import purchase, path
from test_business_orm import erp
from test_payment_document_approval import funds, new as new_payment, execute as execute_payment, balance as payment_balance
from test_order_settlement_document_approval import offsets, new as new_offset, execute as execute_offset, balance as offset_balance
from approval_test_helpers import approve_document
from app.core.approval_routing import AMOUNT_BASES, resolve, snapshot_amount, validate_branches
from app.core.database import connection, migrate
from app.core.document_approval import find_case
from app.core.models import DocumentApprovalAuthor, DocumentApprovalEvent, DocumentApprovalPolicyChange
from app.core.orm import orm_session


def branch(low='25', high=None, name='大额流程'):
    return {'name': name, 'min_amount': low, 'max_amount': high,
        'steps': [{'name': '审核', 'role': None, 'action': 'review'},
                  {'name': '批准', 'role': None, 'action': 'approve'}]}


DEFAULT = [{'name': '默认批准', 'role': None, 'action': 'approve'}]


@pytest.mark.parametrize('kind,content,expected', [
    ('PurchaseRequest', {'lines': [{'quantity': '3', 'unit_price': '0.0017'}]}, '.01'),
    ('PurchaseOrder', {'lines': [{'quantity': '3', 'unit_price': '.003333333333',
        'pricing_mode': 'total', 'line_total': '.01'}]}, '.01'),
    ('SalesOrder', {'lines': [{'quantity': '1', 'unit_price': '.005'}] * 2}, '.02'),
    ('CrmQuote', {'lines': [{'quantity': '3', 'unit_price': '.005'}]}, '.02'),
    ('Journal', {'lines': [{'debit': '25', 'credit': '0'}, {'debit': '0', 'credit': '25'}]}, '25'),
    ('ProductionCostSettlement', {'plan': {'header': {'total_amount': '25'}}}, '25'),
    *[(kind, {'amount': '25'}, '25') for kind in AMOUNT_BASES if kind not in (
        'PurchaseRequest', 'PurchaseOrder', 'SalesOrder', 'CrmQuote', 'Journal', 'ProductionCostSettlement')],
])
def test_amount_uses_fixed_business_basis(kind, content, expected):
    assert snapshot_amount(kind, content) == Decimal(expected)


@pytest.mark.parametrize('kind', ['PaymentRecord', 'SubledgerPayment', 'OrderSettlementTransfer',
    'SubledgerSettlement', 'SubledgerOrderSettlement', 'ControlBalanceTransfer'])
def test_signed_money_routes_by_magnitude_without_rewriting_content(kind):
    content = {'amount': '-25.00'}
    steps, evidence = resolve(kind, content, 'execute', DEFAULT, [branch()])
    assert steps == branch()['steps'] and evidence['amount'] == '25.00'
    assert evidence['basis'] == '本单金额绝对值' and evidence['branch']['name'] == '大额流程'
    assert content == {'amount': '-25.00'}


@pytest.mark.parametrize('kind,content', [
    ('PurchaseOrder', {'lines': [{'quantity': '-1', 'unit_price': '25'}]}),
    ('Journal', {'lines': [{'debit': '-25'}]}),
    ('PaymentRecord', {'amount': '-1000000000000000001'}),
])
def test_signed_money_exception_does_not_allow_invalid_quantity_debit_or_magnitude(kind, content):
    with pytest.raises(HTTPException) as error:
        snapshot_amount(kind, content)
    assert error.value.status_code == 409


@pytest.mark.parametrize('bad', [
    [branch('-1')], [branch('0.001')], [branch('NaN')], [branch('1e3')], [branch('1000000000000000001')],
    [branch('25', '25')], [branch('26', '25')], [branch(True)],
    [branch('0', '25'), branch('24', '30', '重叠')],
    [branch('0', '25'), branch('25', None)], [dict(branch(), forged=True)],
])
def test_invalid_ranges_never_become_valid_policies(bad):
    with pytest.raises(HTTPException) as error:
        validate_branches(None, 'PurchaseOrder', bad, lambda _, steps: steps)
    assert error.value.status_code == 422


def test_adjacent_bounds_and_reverse_intent_are_unambiguous():
    rules = validate_branches(None, 'PaymentRecord', [branch('0', '25', '小额'), branch('25')], lambda _, steps: steps)
    assert resolve('PaymentRecord', {'amount': '24.99'}, 'execute', DEFAULT, rules)[1]['branch']['name'] == '小额'
    assert resolve('PaymentRecord', {'amount': '25.00'}, 'execute', DEFAULT, rules)[1]['branch']['name'] == '大额流程'
    assert resolve('PaymentRecord', {'amount': '25'}, 'execute', DEFAULT, [rules[0]])[0] == DEFAULT
    steps, evidence = resolve('PaymentRecord', {}, 'reverse', DEFAULT, rules)
    assert steps == DEFAULT and evidence['mode'] == 'reverse_default' and evidence['amount'] is None


@pytest.mark.parametrize('content', [
    {'lines': []}, {'lines': [{'quantity': '3', 'unit_price': None}]},
    {'lines': [{'quantity': '3', 'unit_price': 'NaN'}]},
    {'lines': [{'quantity': '3', 'unit_price': '1', 'pricing_mode': 'total'}]},
])
def test_missing_or_invalid_amount_is_not_zero(content):
    with pytest.raises(HTTPException) as error:
        snapshot_amount('PurchaseRequest', content)
    assert error.value.status_code == 409


def configure(client, auth, *, version=1, branches=None, kind='PurchaseOrder', steps=None):
    return client.put('/api/v1/system/document-approvals/' + kind, headers=auth,
        json={'version': version, 'steps': steps or DEFAULT, 'branches': branches if branches is not None else [branch()]})


def act(client, auth, order, action, version):
    return client.post(path('PurchaseOrder', order['id']) + '/' + action, headers=auth,
        json={'version': version, 'intent': 'execute', 'reason': '核对本次依据'})


@pytest.mark.parametrize('fixture,kind,base,create,execute,balance,amount', [
    ('funds', 'PaymentRecord', '/api/v1/finance/payment-records', new_payment,
        execute_payment, payment_balance, '15.00'),
    ('offsets', 'OrderSettlementTransfer', '/api/v1/finance/order-settlements', new_offset,
        execute_offset, offset_balance, '6.00'),
])
def test_real_negative_counterdocument_requires_full_amount_branch_before_restoring_balance(
        request, fixture, kind, base, create, execute, balance, amount):
    data = request.getfixturevalue(fixture)
    client, _ = data
    current_balance = lambda: balance(client if fixture == 'funds' else data)
    before = current_balance()
    original = create(data)
    approve_document(client, None, kind, original['id'], reason='核对原始单据')
    execute(client, original)
    after = current_balance()
    assert after != before
    assert configure(client, {}, kind=kind, branches=[branch('1')]).status_code == 200
    response = client.post(f"{base}/{original['id']}/reverse", json={'reason': '更正原始经济事项'})
    assert response.status_code == 201, response.text
    counter = response.json()
    assert counter['amount'] == '-' + amount
    endpoint = path(kind, counter['id'])
    sent = client.post(endpoint + '/submit', json={'version': 0, 'intent': 'execute', 'reason': '独立核对反向单据'})
    assert sent.status_code == 200, sent.text
    assert sent.json()['routing']['amount'] == amount and len(sent.json()['steps']) == 2
    first = client.post(endpoint + '/approve', json={'version': 1, 'reason': '复核反向金额'})
    assert first.status_code == 200 and first.json()['status'] == 'submitted'
    blocked = client.post(f"{base}/{counter['id']}/post", json={'version': counter['version'], 'reason': '尚未批准'})
    assert blocked.status_code == 409 and current_balance() == after
    final = client.post(endpoint + '/approve', json={'version': 2, 'reason': '批准反向金额'})
    assert final.status_code == 200 and final.json()['status'] == 'approved'
    posted = execute(client, counter)
    assert posted['amount'] == counter['amount'] and current_balance() == before


def test_real_order_routes_at_boundary_and_freezes_until_execution(purchase):
    client, auth, order = purchase
    result = configure(client, auth)
    assert result.status_code == 200, result.text
    assert result.json()['branches'][0]['min_amount'] == '25.00'
    assert result.json()['amount_basis'] == '订单逐行金额合计'
    response = act(client, auth, order, 'submit', 0)
    assert response.status_code == 200, response.text
    sent = response.json()
    assert sent['routing']['amount'] == '25.00' and sent['routing']['branch']['name'] == '大额流程'
    assert sent['policy_version'] == 2 and len(sent['steps']) == 2
    # 修改默认规则和金额门槛不能更改正在审批的内容或减少剩余步骤。
    assert configure(client, auth, version=2, branches=[branch('100')]).status_code == 200
    first = act(client, auth, order, 'approve', 1)
    assert first.status_code == 200, first.text
    assert first.json()['status'] == 'submitted'
    assert client.post(f"/api/v1/purchase-orders/{order['id']}/confirm", headers=auth).status_code == 409
    final = act(client, auth, order, 'approve', 2)
    assert final.status_code == 200 and final.json()['status'] == 'approved'
    assert final.json()['routing'] == sent['routing']
    assert client.post(f"/api/v1/purchase-orders/{order['id']}/confirm", headers=auth).status_code == 200
    with orm_session() as db:
        case = find_case(db, 'PurchaseOrder', order['id'])
        assert case.status == 'executed'
        events = list(db.scalars(select(DocumentApprovalEvent).where(DocumentApprovalEvent.case_id == case.id).order_by(DocumentApprovalEvent.id)))
        assert [row.action for row in events] == ['submit', 'approve', 'approve', 'execute']
        assert all(json.loads(row.state_json)['routing_evidence']['rules'][0]['min_amount'] == '25.00' for row in events)


def test_resubmission_uses_new_rule_but_keeps_previous_route(purchase):
    client, auth, order = purchase
    assert configure(client, auth).status_code == 200
    assert act(client, auth, order, 'submit', 0).status_code == 200
    assert act(client, auth, order, 'withdraw', 1).status_code == 200
    assert configure(client, auth, version=2, branches=[branch('100')]).status_code == 200
    sent = act(client, auth, order, 'submit', 2)
    assert sent.status_code == 200, sent.text
    data = sent.json()
    assert data['generation'] == 2 and data['routing']['branch'] is None and data['steps'] == DEFAULT
    assert data['events'][0]['routing']['branch']['name'] == '大额流程'
    assert data['events'][-1]['routing']['branch'] is None


def test_policy_conflict_legacy_client_and_invalid_branch_leave_audit_unchanged(purchase):
    client, auth, _ = purchase
    assert configure(client, auth).status_code == 200
    login = client.post('/api/v1/auth/login', json={'username': 'submitter', 'password': 'secure-pass-123'}).json()
    assert configure(client, {'Authorization': 'Bearer ' + login['token']}, version=2).status_code == 403
    assert client.put('/api/v1/system/document-approvals/PurchaseOrder', headers=auth,
        json={'version': 2, 'steps': DEFAULT, 'branches': None}).status_code == 422
    assert configure(client, auth).status_code == 409
    assert client.put('/api/v1/system/document-approvals/PurchaseOrder', headers=auth,
        json={'version': 2, 'steps': DEFAULT}).status_code == 409
    assert configure(client, auth, version=2, branches=[branch('0', '25'), branch('24', None, '重叠')]).status_code == 422
    assert configure(client, auth, kind='WarehouseInbound').status_code == 422
    with orm_session() as db:
        changes = list(db.scalars(select(DocumentApprovalPolicyChange)))
        assert len(changes) == 1
        assert json.loads(changes[0].after_json)['branches'][0]['name'] == '大额流程'
    assert configure(client, auth, version=2, branches=[]).status_code == 200
    with orm_session() as db:
        change = db.scalar(select(DocumentApprovalPolicyChange).order_by(DocumentApprovalPolicyChange.id.desc()))
        assert json.loads(change.before_json)['branches'] and json.loads(change.after_json)['branches'] == []


def test_unpriced_request_rolls_back_case_and_author_writes(context):
    client, auth, inbound = context
    request = client.post('/api/v1/purchase-requests', headers=auth, json={
        'reference': '未定价申请', 'lines': [{'material_id': inbound['lines'][0]['material_id'], 'quantity': '3'}]})
    assert request.status_code == 201, request.text
    identifier = request.json()['id']
    assert configure(client, auth, kind='PurchaseRequest').status_code == 200
    with orm_session() as db:
        authors = db.scalar(select(func.count()).select_from(DocumentApprovalAuthor))
    response = client.post(path('PurchaseRequest', identifier) + '/submit', headers=auth,
        json={'version': 0, 'intent': 'execute', 'reason': ''})
    assert response.status_code == 409, response.text
    with orm_session() as db:
        assert find_case(db, 'PurchaseRequest', identifier) is None
        assert db.scalar(select(func.count()).select_from(DocumentApprovalAuthor)) == authors


def test_v111_upgrade_preserves_existing_approval_evidence(purchase):
    client, auth, order = purchase
    assert act(client, auth, order, 'submit', 0).status_code == 200
    with connection() as db:
        before = [tuple(row) for row in db.execute('SELECT * FROM document_approval_events')]
        db.execute('ALTER TABLE document_approval_policies DROP COLUMN branches_json')
        db.execute('ALTER TABLE document_approval_cases DROP COLUMN routing_json')
        db.execute('PRAGMA user_version = 111')
    migrate()
    migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 112
        assert [tuple(row) for row in db.execute('SELECT * FROM document_approval_events')] == before
        assert db.execute('SELECT branches_json FROM document_approval_policies WHERE document_type=?', ('PurchaseOrder',)).fetchone()[0] == '[]'
    response = act(client, auth, order, 'approve', 1)
    assert response.status_code == 200 and response.json()['status'] == 'approved'
    assert 'routing' not in response.json()


def test_new_column_migration_failure_rolls_back_both_columns_and_version(purchase, monkeypatch):
    from app.core import database
    original = database.connection
    with original() as db:
        db.execute('ALTER TABLE document_approval_policies DROP COLUMN branches_json')
        db.execute('ALTER TABLE document_approval_cases DROP COLUMN routing_json')
        db.execute('PRAGMA user_version = 111')

    class FailingConnection:
        def __init__(self, db):
            self.db = db

        def __getattr__(self, name):
            return getattr(self.db, name)

        def execute(self, statement, *args):
            if 'ADD COLUMN routing_json' in statement:
                raise sqlite3.OperationalError('模拟第二个字段迁移失败')
            return self.db.execute(statement, *args)

    @contextmanager
    def failing():
        with original() as db:
            yield FailingConnection(db)

    monkeypatch.setattr(database, 'connection', failing)
    with pytest.raises(sqlite3.OperationalError, match='模拟第二个字段迁移失败'):
        migrate()
    with original() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 111
        assert 'branches_json' not in {row[1] for row in db.execute('PRAGMA table_info(document_approval_policies)')}
        assert 'routing_json' not in {row[1] for row in db.execute('PRAGMA table_info(document_approval_cases)')}
    monkeypatch.setattr(database, 'connection', original)
    migrate()
