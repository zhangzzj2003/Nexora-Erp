"""真实计划、审批、拆单及 MRP 闭环；验证并发与失败均不改变库存。"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal
from uuid import uuid4
import sqlite3

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select, func
from sqlalchemy.orm import Session

from approval_test_helpers import approve_document, receive_legacy_issue
from test_mrp import seeded  # 复用已通过真实接口建立的产品、BOM 和采购库存。
from app.core.models import ProductionPlanRelease, ProductionPlanChange, StockMovement, WorkOrder
from app.core.orm import orm_session
from app.core.database import connection, migrate
from app.production import plans, plan_rules
from app.production.mrp_sources import collect
from app.production.mrp_engine import calculate

BASE = '/api/v1/production/plans'


@pytest.fixture
def context(seeded, monkeypatch):
    monkeypatch.setattr(plans, 'today', lambda: '2030-01-01')
    monkeypatch.setattr(plan_rules, 'today', lambda: '2030-01-01')
    client, admin, reviewer, planner, viewer, materials, _ = seeded
    return client, admin, reviewer, planner, viewer, materials


def draft(context, quantity='10'):
    client, admin, *_ = context
    options = client.get(BASE + '/options', headers=admin)
    assert options.status_code == 200, options.text
    bom = options.json()['boms'][0]
    return {'reference': '一月生产安排', 'note': '按批准日期备料', 'reason': '订单与备货核对',
        'lines': [{'bom_id': bom['id'], 'warehouse_id': 1, 'sales_order_line_id': None,
            'quantity': quantity, 'start_date': '2030-01-05', 'end_date': '2030-01-10', 'priority': 'high'}]}


def create(context, payload=None):
    client, admin, *_ = context
    response = client.post(BASE, headers=admin, json=payload or draft(context))
    assert response.status_code == 201, response.text
    return response.json()


def approved(context, payload=None):
    client, admin, *_ = context
    row = create(context, payload)
    approve_document(client, admin, 'ProductionPlan', row['id'], reason='核对数量与交期')
    return client.get(BASE + f'/{row["id"]}', headers=admin).json()


def release_input(row, quantity='4'):
    return {'version': row['version'], 'approval_version': row['approval']['version'],
        'line_id': row['lines'][0]['id'], 'quantity': quantity,
        'request_id': str(uuid4()), 'reason': '按第一批备料安排下达'}


def counts():
    with orm_session() as db:
        return tuple(db.scalar(select(func.count()).select_from(model))
            for model in (WorkOrder, StockMovement, ProductionPlanRelease))


def test_plan_approval_split_release_and_idempotency(context):
    client, admin, *_ = context
    row = create(context)
    before = counts()
    blocked = client.post(BASE + f'/{row["id"]}/release', headers=admin, json=release_input(row))
    assert blocked.status_code in (409, 422), blocked.text
    assert counts() == before
    approve_document(client, admin, 'ProductionPlan', row['id'], reason='核对计划')
    row = client.get(BASE + f'/{row["id"]}', headers=admin).json()
    request = release_input(row)
    response = client.post(BASE + f'/{row["id"]}/release', headers=admin, json=request)
    assert response.status_code == 201, response.text
    current = response.json()
    assert current['lines'][0]['unreleased_quantity'] == '6.000'
    assert current['releases'][0]['work_order_status'] == 'draft'
    assert current['approval']['status'] == 'executed'
    assert counts() == (before[0] + 1, before[1], before[2] + 1)
    retry = client.post(BASE + f'/{row["id"]}/release', headers=admin, json=request)
    assert retry.status_code == 201 and len(retry.json()['releases']) == 1
    assert client.post(BASE + f'/{row["id"]}/release', headers=admin,
        json={**request, 'quantity': '3'}).status_code == 409
    assert client.post(BASE + f'/{row["id"]}/release', headers=admin,
        json=release_input(current, '7')).status_code == 409
    final = client.post(BASE + f'/{row["id"]}/release', headers=admin, json=release_input(current, '6'))
    assert final.status_code == 201, final.text
    assert final.json()['lines'][0]['unreleased_quantity'] == '0.000'
    assert counts()[1] == before[1]
    order = next(item for item in client.get('/api/v1/work-orders', headers=admin).json()
                 if item['id'] == current['releases'][0]['work_order_id'])
    assert order['production_schedule']['start_date'] == '2030-01-05'
    assert order['approval']['status'] == 'draft'


def test_stale_versions_parallel_release_and_transaction_rollback(context):
    client, admin, *_ = context
    row = approved(context)
    request = release_input(row, '6')
    before = counts()
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: client.post(BASE + f'/{row["id"]}/release', headers=admin,
            json={**request, 'request_id': str(uuid4())}).status_code, range(2)))
    assert sorted(results) == [201, 409]
    assert counts() == (before[0] + 1, before[1], before[2] + 1)
    current = client.get(BASE + f'/{row["id"]}', headers=admin).json()
    request = release_input(current, '4')
    def fail_audit(session, *_):
        if any(isinstance(item, ProductionPlanChange) and item.action == 'release' for item in session.new):
            raise RuntimeError('模拟审计写入失败')
    event.listen(Session, 'before_flush', fail_audit)
    try:
        result = client.post(BASE + f'/{row["id"]}/release', headers=admin, json=request)
        assert result.status_code == 500
    finally:
        event.remove(Session, 'before_flush', fail_audit)
    assert counts() == (before[0] + 1, before[1], before[2] + 1)
    assert client.get(BASE + f'/{row["id"]}', headers=admin).json()['version'] == current['version']


def test_edit_freeze_withdraw_cancel_and_source_bom_validation(context):
    client, admin, *_ = context
    body = draft(context)
    row = approved(context, body)
    assert client.put(BASE + f'/{row["id"]}', headers=admin, json={**body, 'version': row['version']}).status_code == 409
    assert client.post(BASE + f'/{row["id"]}/cancel', headers=admin,
        json={'version': row['version'], 'reason': '变更'}).status_code == 409
    path = f'/api/v1/system/document-approvals/ProductionPlan/{row["id"]}'
    withdrawn = client.post(path + '/withdraw', headers=admin, json={'version': row['approval']['version'], 'reason': '调整排期'})
    assert withdrawn.status_code == 200, withdrawn.text
    body['lines'][0]['quantity'] = '8'
    edited = client.put(BASE + f'/{row["id"]}', headers=admin, json={**body, 'version': row['version']})
    assert edited.status_code == 200, edited.text
    assert edited.json()['lines'][0]['quantity'] == '8.000'
    assert client.post(BASE + f'/{row["id"]}/release', headers=admin, json=release_input(row)).status_code == 409
    current = edited.json()
    cancelled = client.post(BASE + f'/{row["id"]}/cancel', headers=admin,
        json={'version': current['version'], 'reason': '客户取消安排'})
    assert cancelled.status_code == 200 and cancelled.json()['status'] == 'cancelled'
    row = create(context)
    assert client.post('/api/v1/boms/' + str(body['lines'][0]['bom_id']) + '/retire', headers=admin).status_code == 200
    path = f'/api/v1/system/document-approvals/ProductionPlan/{row["id"]}'
    assert client.post(path + '/submit', headers=admin, json={'version': 0, 'reason': '送审'}).status_code == 409


def test_cancelled_work_order_releases_only_its_allocation(context):
    client, admin, *_ = context
    row = approved(context)
    row = client.post(BASE + f'/{row["id"]}/release', headers=admin, json=release_input(row)).json()
    order_id = row['releases'][0]['work_order_id']
    assert client.post(f'/api/v1/work-orders/{order_id}/cancel', headers=admin).status_code == 200
    current = client.get(BASE + f'/{row["id"]}', headers=admin).json()
    assert current['lines'][0]['unreleased_quantity'] == '10.000'
    assert current['releases'][0]['work_order_status'] == 'cancelled'
    assert client.post(BASE + f'/{row["id"]}/cancel', headers=admin,
        json={'version': row['version'], 'reason': '保留已取消工单记录'}).status_code == 200


def test_mrp_counts_approved_plan_and_work_orders_once_at_saved_dates(context):
    client, admin, *_ = context
    row = create(context)
    with orm_session() as db:
        assert not any(source['kind'] == 'production_plan' for source in collect(db)['supplies'])
    approve_document(client, admin, 'ProductionPlan', row['id'], reason='核对并纳入物料计划')
    def source_quantities():
        with orm_session() as db:
            source = collect(db)
        result = calculate(source, '2030-01-01', {}, {}, [])
        return source, result
    source, result = source_quantities()
    assert len([item for item in source['supplies'] if item['kind'] == 'production_plan']) == 1
    product = next(item for item in result['rows'] if item['material_id'] == context[5][0])
    assert product['scheduled_quantity'] == '10.000'
    components = [item for item in source['reservations'] if item['kind'] == 'production_plan_requirement']
    assert {item['due_date'] for item in components} == {'2030-01-05'}
    before_components = {item['material_id']: Decimal(item['quantity']) for item in components}
    row = client.get(BASE + f'/{row["id"]}', headers=admin).json()
    row = client.post(BASE + f'/{row["id"]}/release', headers=admin, json=release_input(row)).json()
    source, result = source_quantities()
    assert sum(Decimal(item['quantity']) for item in source['supplies'] if item['material_id'] == context[5][0]) == 10
    for material_id, quantity in before_components.items():
        assert sum(Decimal(item['quantity']) for item in source['reservations'] if item['material_id'] == material_id) == quantity
    assert all(item['due_date'] == '2030-01-05' for item in source['reservations'])


def test_sales_allocation_and_mrp_demand_not_duplicated(context):
    client, admin, *_ = context
    customer = client.post('/api/v1/customers', headers=admin, json={'name': '计划来源客户'}).json()['id']
    order = client.post('/api/v1/sales-orders', headers=admin, json={'customer_id': customer,
        'reference': '销售来源', 'lines': [{'material_id': context[5][0], 'quantity': '10', 'unit_price': '5'}]}).json()
    approve_document(client, admin, 'SalesOrder', order['id'])
    assert client.post(f'/api/v1/sales-orders/{order["id"]}/confirm', headers=admin).status_code == 200
    body = draft(context, '6')
    body['lines'][0]['sales_order_line_id'] = order['lines'][0]['id']
    row = approved(context, body)
    body['lines'][0]['quantity'] = '5'
    assert client.post(BASE, headers=admin, json=body).status_code == 409
    options = client.get(BASE + '/options', headers=admin).json()
    assert options['sales_lines'][0]['available_quantity'] == '4.000'
    assert 'unit_price' not in options['sales_lines'][0]
    with orm_session() as db:
        source = collect(db)
    assert len(source['demands']) == 1 and source['demands'][0]['quantity'] == '10.000'
    assert source['supplies'][0]['quantity'] == '6.000'
    mismatch = deepcopy(body)
    mismatch['lines'][0]['bom_id'] = client.get(BASE + '/options', headers=admin).json()['boms'][1]['id']
    assert client.post(BASE, headers=admin, json=mismatch).status_code == 422
    row = client.post(BASE + f'/{row["id"]}/release', headers=admin, json=release_input(row, '2')).json()
    cancelled = client.post(BASE + f'/{row["id"]}/cancel', headers=admin,
        json={'version': row['version'], 'reason': '停止未下达安排，保留首批工单'})
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()['releases'][0]['work_order_status'] == 'draft'
    assert client.get(BASE + '/options', headers=admin).json()['sales_lines'][0]['available_quantity'] == '8.000'
    with orm_session() as db:
        source = collect(db)
    assert not any(item['kind'] == 'production_plan' for item in source['supplies'])
    assert sum(Decimal(item['quantity']) for item in source['supplies'] if item['material_id'] == context[5][0]) == 2


@pytest.mark.parametrize('edit', [
    {'quantity': '0'}, {'quantity': 'NaN'}, {'quantity': '1.0001'}, {'bom_id': True},
    {'warehouse_id': 99999}, {'end_date': '2030-01-04'}, {'start_date': '2030-02-30'}, {'priority': 'unknown'},
])
def test_invalid_plan_never_leaves_partial_records(context, edit):
    client, admin, *_ = context
    body = draft(context)
    body['lines'][0].update(edit)
    assert client.post(BASE, headers=admin, json=body).status_code in (422, 409)
    assert client.get(BASE, headers=admin).json() == []


def test_maximum_plan_has_complete_summary_within_shared_dialog_limit(context):
    client, admin, *_ = context
    body = draft(context, '1')
    body['lines'] = [deepcopy(body['lines'][0]) for _ in range(100)]
    row = approved(context, body)
    record = client.get(f'/api/v1/system/document-approvals/ProductionPlan/{row["id"]}', headers=admin).json()
    assert len(record['summary']) == 103
    assert all(len(item['value']) <= 1000 for item in record['summary'])
    assert all('2030-01-05 至 2030-01-10' in item['value'] and '优先' in item['value']
        for item in record['summary'][3:])


def test_permissions_and_late_progress(context, monkeypatch):
    client, admin, reviewer, planner, viewer, _ = context
    assert client.get(BASE, headers=viewer).status_code == 403
    assert client.get(BASE + '/options', headers=planner).status_code == 200
    row = approved(context)
    monkeypatch.setattr(plan_rules, 'today', lambda: '2030-01-11')
    current = client.get(BASE + f'/{row["id"]}', headers=admin).json()
    assert current['overdue_count'] == 1
    assert client.post(BASE + f'/{row["id"]}/release', headers=viewer, json=release_input(row)).status_code == 403
    assert client.post('/api/v1/roles', headers=admin, json={'code': 'release_only', 'label': '只有计划下达',
        'permissions': ['production_plan.view', 'production_plan.release']}).status_code == 201
    assert client.post('/api/v1/users', headers=admin, json={'username': 'limited',
        'password': 'secure-pass-123', 'roles': ['release_only']}).status_code == 201
    token = client.post('/api/v1/auth/login', json={'username': 'limited', 'password': 'secure-pass-123'}).json()['token']
    assert client.post(BASE + f'/{row["id"]}/release', headers={'Authorization': 'Bearer ' + token},
        json=release_input(row)).status_code == 403


def test_multi_product_release_is_independent_of_finished_line_bom(context):
    client, admin, *_ = context
    body = draft(context, '2')
    other_bom = client.get(BASE + '/options', headers=admin).json()['boms'][1]['id']
    body['lines'].append({**body['lines'][0], 'bom_id': other_bom})
    row = approved(context, body)
    row = client.post(BASE + f'/{row["id"]}/release', headers=admin, json=release_input(row, '2')).json()
    # 第一行已全数转为固定工单，停用其旧 BOM 不得影响第二行的合法下达。
    assert client.post(f'/api/v1/boms/{body["lines"][0]["bom_id"]}/retire', headers=admin).status_code == 200
    result = client.post(BASE + f'/{row["id"]}/release', headers=admin,
        json={**release_input(row, '2'), 'line_id': row['lines'][1]['id']})
    assert result.status_code == 201, result.text
    assert len(result.json()['releases']) == 2


def test_invalid_approved_source_cannot_silently_cover_mrp_shortage(context):
    client, admin, *_ = context
    row = approved(context)
    row = client.post(BASE + f'/{row["id"]}/release', headers=admin, json=release_input(row)).json()
    assert client.post(f'/api/v1/boms/{row["lines"][0]["bom_id"]}/retire', headers=admin).status_code == 200
    with orm_session() as db, pytest.raises(HTTPException, match='未下达来源已失效'):
        collect(db)
    # 终止余额后，已生成工单的历史配方和预计产出仍独立有效。
    cancelled = client.post(BASE + f'/{row["id"]}/cancel', headers=admin,
        json={'version': row['version'], 'reason': '版本停用，取消后续安排'})
    assert cancelled.status_code == 200, cancelled.text
    with orm_session() as db:
        source = collect(db)
    assert sum(Decimal(item['quantity']) for item in source['supplies'] if item['material_id'] == context[5][0]) == 4


def test_broken_child_bom_does_not_hide_existing_plans(context):
    client, admin, *_ = context
    existing = create(context)
    options = client.get(BASE + '/options', headers=admin).json()
    parent, child = options['boms']
    replacement = client.post('/api/v1/boms', headers=admin, json={'product_material_id': parent['material_id'],
        'base_quantity': '1', 'lines': [{'component_material_id': child['material_id'], 'component_bom_id': child['id'], 'quantity': '1'}]}).json()
    assert client.post(f'/api/v1/boms/{parent["id"]}/retire', headers=admin).status_code == 200
    assert client.post(f'/api/v1/boms/{replacement["id"]}/activate', headers=admin).status_code == 200
    assert client.post(f'/api/v1/boms/{child["id"]}/retire', headers=admin).status_code == 200
    result = client.get(BASE + '/options', headers=admin)
    assert result.status_code == 200, result.text
    assert replacement['id'] not in [row['id'] for row in result.json()['boms']]
    assert result.json()['unavailable_boms'][0]['id'] == replacement['id']
    assert client.get(BASE, headers=admin).json()[0]['id'] == existing['id']
    assert client.post(BASE + f'/{existing["id"]}/cancel', headers=admin,
        json={'version': existing['version'], 'reason': '配方停用取消原草稿'}).status_code == 200


def test_reported_accepted_rejected_and_reversed_progress(context, monkeypatch):
    client, admin, *_ = context
    row = approved(context, draft(context, '2'))
    row = client.post(BASE + f'/{row["id"]}/release', headers=admin, json=release_input(row, '2')).json()
    order_id = row['releases'][0]['work_order_id']
    order = next(item for item in client.get('/api/v1/work-orders', headers=admin).json() if item['id'] == order_id)
    supplier = client.get('/api/v1/suppliers', headers=admin).json()[0]['id']
    receipt = client.post('/api/v1/receipts', headers=admin, json={'supplier_id': supplier, 'warehouse_id': 1,
        'lines': [{'material_id': line['component_material_id'], 'quantity': line['required_quantity']} for line in order['lines']]}).json()
    approve_document(client, admin, 'Receipt', receipt['id'])
    assert client.post(f'/api/v1/receipts/{receipt["id"]}/post', headers=admin).status_code == 200
    approve_document(client, admin, 'WorkOrder', order_id)
    assert client.post(f'/api/v1/work-orders/{order_id}/release', headers=admin).status_code == 200
    issue = client.post('/api/v1/material-issues', headers=admin, json={'work_order_id': order_id, 'warehouse_id': 1,
        'lines': [{'work_order_line_id': line['id'], 'quantity': line['required_quantity']} for line in order['lines']]}).json()
    approve_document(client, admin, 'MaterialIssue', issue['id'])
    assert client.post(f'/api/v1/material-issues/{issue["id"]}/post', headers=admin).status_code == 200
    receive_legacy_issue(client, admin, issue['id'])
    completions = []
    for accepted in ('0.5', '1'):
        completion = client.post('/api/v1/production-completions', headers=admin,
            json={'work_order_id': order_id, 'reported_quantity': '1'}).json()
        completion_id = completion['id']
        assert client.post(f'/api/v1/production-completions/{completion_id}/inspect', headers=admin,
            json={'accepted_quantity': accepted, 'qc_note': '逐批检验'}).status_code == 200
        approve_document(client, admin, 'ProductionCompletion', completion_id)
        assert client.post(f'/api/v1/production-completions/{completion_id}/post', headers=admin).status_code == 200
        completions.append(completion_id)
        current = client.get(BASE + f'/{row["id"]}', headers=admin).json()
        assert current['progress'] == ('in_progress' if len(completions) == 1 else 'completed')
    line = current['lines'][0]
    assert (line['reported_quantity'], line['accepted_quantity'], line['rejected_quantity']) == ('2.000', '1.500', '0.500')
    monkeypatch.setattr(plan_rules, 'today', lambda: '2030-01-11')
    assert client.get(BASE + f'/{row["id"]}', headers=admin).json()['overdue_count'] == 0
    # 冲销回退进度但保留原计划、拆单和报工证据；不把不合格数量当成合格入库。
    approve_document(client, admin, 'ProductionCompletion', completions[-1], intent='reverse', reason='报工录错')
    assert client.post(f'/api/v1/production-completions/{completions[-1]}/reverse', headers=admin,
        json={'reason': '报工录错'}).status_code == 200
    current = client.get(BASE + f'/{row["id"]}', headers=admin).json()
    assert current['progress'] == 'in_progress' and current['overdue_count'] == 1
    assert current['lines'][0]['remaining_quantity'] == '1.000'
    assert current['lines'][0]['accepted_quantity'] == '0.500'
    assert len(current['releases']) == 1


def remove_plan_schema():
    # 仅在隔离测试库还原升级起点，不删除或改写任何历史业务表。
    with connection() as db:
        for name in ('production_plan_releases', 'production_plan_changes', 'production_plan_lines', 'production_plans'):
            db.execute(f'DROP TABLE {name}')
        db.execute("DELETE FROM role_permissions WHERE permission_code LIKE 'production_plan.%'")
        db.execute("DELETE FROM permissions WHERE code LIKE 'production_plan.%'")
        db.execute("DELETE FROM permission_groups WHERE code='production.plan'")
        db.execute("DELETE FROM document_approval_policies WHERE document_type='ProductionPlan'")
        db.execute('PRAGMA user_version=106')


def test_v106_migration_is_additive_idempotent_and_audit_immutable(context):
    client, admin, *_ = context
    body = draft(context)
    legacy = client.post('/api/v1/work-orders', headers=admin, json={'bom_id': body['lines'][0]['bom_id'],
        'warehouse_id': 1, 'target_quantity': '1'}).json()
    approve_document(client, admin, 'WorkOrder', legacy['id'])
    remove_plan_schema()
    with connection() as db:
        table_names = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if row[0] not in ('permissions', 'permission_groups', 'role_permissions', 'document_approval_policies', 'sqlite_sequence')]
        before = {name: db.execute(f'SELECT * FROM "{name}"').fetchall() for name in table_names}
    migrate()
    migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 107
        assert {name: db.execute(f'SELECT * FROM "{name}"').fetchall() for name in table_names} == before
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute("SELECT COUNT(*) FROM role_permissions WHERE role_code='planner' AND permission_code='production_plan.view'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM role_permissions WHERE role_code='viewer' AND permission_code LIKE 'production_plan.%'").fetchone()[0] == 0
    # 原批准正文不能因为新增关联字段而失效。
    assert client.post(f'/api/v1/work-orders/{legacy["id"]}/release', headers=admin).status_code == 200
    row = approved(context)
    row = client.post(BASE + f'/{row["id"]}/release', headers=admin, json=release_input(row)).json()
    for statement in ('DELETE FROM production_plan_changes', 'UPDATE production_plan_releases SET quantity=\'99\'',
                      "UPDATE production_plans SET document_no='篡改单号'"):
        with pytest.raises(sqlite3.IntegrityError), connection() as db:
            db.execute(statement)


def test_v106_migration_failure_rolls_back_tables_permissions_and_version(context, monkeypatch):
    from contextlib import contextmanager
    from app.core import database
    remove_plan_schema()
    original = database.connection
    @contextmanager
    def failing_connection():
        with original() as db:
            db.set_authorizer(lambda operation, name, *_: sqlite3.SQLITE_DENY
                if operation == sqlite3.SQLITE_CREATE_TABLE and name == 'production_plan_releases' else sqlite3.SQLITE_OK)
            yield db
    monkeypatch.setattr(database, 'connection', failing_connection)
    with pytest.raises(sqlite3.DatabaseError):
        migrate()
    with original() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 106
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='production_plans'").fetchone()
        assert not db.execute("SELECT 1 FROM permissions WHERE code='production_plan.view'").fetchone()
