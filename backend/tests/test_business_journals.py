"""业务来源重算、独立审核、跨模块价格锁定和原子去重。"""

from approval_test_helpers import approve_document
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core.models import BusinessJournalPolicyChange, BusinessJournalSource, Journal
from app.core.orm import orm_session
from app.core.database import connection, migrate
from app.finance.business_sources import ROLE_LABELS
from test_business_orm import erp, receipt, completion

BASE = '/api/v1/finance/business-journals'
JOURNALS = '/api/v1/finance/journals'


@pytest.fixture
def business(erp):
    client, request, *_ = erp
    mapping = {}
    for index, role in enumerate(ROLE_LABELS, 1):
        mapping[role] = request('POST', 'finance/ledger-accounts', dict(code=f'A{index}', name=ROLE_LABELS[role],
            category='asset', normal_balance='debit', reason='试用科目'), 201)['id']
    request('POST', 'finance/accounting-periods', dict(code='Y2026', name='试用年',
        start_date='2026-01-01', end_date='2026-12-31', reason='业务凭证'), 201)
    request('POST', 'users', dict(username='reviewer', password='reviewer-pass-123', roles=['finance']), 201)
    token = client.post('/api/v1/auth/login', json=dict(username='reviewer', password='reviewer-pass-123')).json()['token']
    reviewer = {'Authorization': 'Bearer ' + token}
    response = client.put(BASE + '/policy', json=dict(version=0, start_date='2026-01-01', mapping=mapping, reason='核对启用前账务'))
    assert response.status_code == 200, response.text
    return client, request, mapping, reviewer, erp


def source(client, key):
    response = client.get(BASE)
    assert response.status_code == 200, response.text
    return next(item for item in response.json() if item['key'] == key)


def generate(client, key, reference='AUTO-1', expected=201):
    item = source(client, key)
    data = dict(source_key=key, fingerprint=item['fingerprint'], policy_version=item['policy_version'],
        reference=reference, journal_date=item['minimum_date'], reason='原始业务依据')
    response = client.post(BASE + '/generate', json=data)
    assert response.status_code == expected, response.text
    return response.json() if expected != 500 else None


def transition(client, row, action, reviewer=None, expected=200):
    response = client.post(f'{JOURNALS}/{row["id"]}/{action}',
        json=dict(version=row['version'], reason='来源与科目核对'), headers=reviewer)
    assert response.status_code == expected, response.text
    return response.json()


def post(client, row, reviewer):
    row = transition(client, row, 'submit')
    row = transition(client, row, 'approve', reviewer)
    return transition(client, row, 'post')


def test_purchase_sales_and_payments_use_real_sources(business):
    client, request, mapping, reviewer, erp = business
    original = receipt(erp)
    request('POST', f'receipts/{original["id"]}/post')
    key = f'receipt:{original["id"]}'
    assert source(client, key)['roles'] == {'inventory': '62.50', 'payable': '-62.50'}
    row = generate(client, key)
    assert row['business_source']['key'] == key and row['total_debit'] == '62.50'
    generate(client, key, 'DUPLICATE', 409)
    transition(client, transition(client, row, 'submit'), 'approve', expected=409)
    row = client.get(f'{JOURNALS}/{row["id"]}').json()
    row = transition(client, row, 'approve', reviewer)
    row = transition(client, row, 'post')
    assert source(client, key)['journal_status'] == 'posted'
    # 实际销售收入与移动平均出库成本进入同一张平衡凭证。
    sales = request('POST', 'sales-orders', dict(customer_id=erp[3], reference='S1',
        lines=[dict(material_id=erp[4][0], quantity='2', unit_price='7')]), 201)
    request('POST', f'sales-orders/{sales["id"]}/confirm')
    shipment = request('POST', 'shipments', dict(sales_order_id=sales['id'], warehouse_id=1,
        lines=[dict(material_id=erp[4][0], quantity='2')]), 201)
    request('POST', f'shipments/{shipment["id"]}/post')
    key = f'shipment:{shipment["id"]}'
    assert source(client, key)['roles'] == dict(inventory='-6.25', receivable='14.00', income='-14.00', sales_cost='6.25')
    sale_journal = post(client, generate(client, key, 'SALE-1'), reviewer)
    assert sale_journal['total_debit'] == '20.25'
    payment = request('POST', 'finance/payment-records', dict(kind='receivable', order_id=sales['id'],
        action='settlement', amount='14', reference='P1'), 201)
    assert source(client, f'payment_record:{payment["id"]}')['roles'] == {'cash': '14.00', 'receivable': '-14.00'}
    post(client, generate(client, f'payment_record:{payment["id"]}', 'PAY-1'), reviewer)
    reverse = request('POST', f'finance/payment-records/{payment["id"]}/reverse', dict(reason='登记更正'), 201)
    assert source(client, f'payment_record:{reverse["id"]}')['roles'] == {'cash': '-14.00', 'receivable': '14.00'}
    post(client, generate(client, f'payment_record:{reverse["id"]}', 'PAY-REV'), reviewer)
    request('POST', f'shipments/{shipment["id"]}/reverse', dict(reason='出库更正'), 201)
    reverse_key = next(item['key'] for item in client.get(BASE).json() if item['source_type'] == 'shipment_reversal')
    assert source(client, reverse_key)['roles'] == dict(inventory='6.25', receivable='-14.00', income='14.00', sales_cost='-6.25')
    post(client, generate(client, reverse_key, 'SHIP-REV'), reviewer)


def test_returns_and_fee_reversal_keep_independent_sources(business):
    client, request, _, reviewer, erp = business
    received = receipt(erp)
    request('POST', f'receipts/{received["id"]}/post')
    returned = request('POST', 'purchase-returns', dict(receipt_id=received['id'], reason='退货',
        lines=[dict(receipt_line_id=received['lines'][0]['id'], quantity='1')]), 201)
    request('POST', f'purchase-returns/{returned["id"]}/post')
    key = f'purchase_return:{returned["id"]}'
    assert source(client, key)['roles'] == {'inventory': '-3.12', 'payable': '3.13', 'price_variance': '-0.01'}
    post(client, generate(client, key, 'PUR-RET'), reviewer)
    request('POST', f'purchase-returns/{returned["id"]}/reverse', dict(reason='退货更正'), 201)
    reverse_key = next(item['key'] for item in client.get(BASE).json() if item['source_type'] == 'purchase_return_reversal')
    assert source(client, reverse_key)['roles'] == {'inventory': '3.12', 'payable': '-3.13', 'price_variance': '0.01'}
    post(client, generate(client, reverse_key, 'PUR-RET-REV'), reviewer)
    sales = request('POST', 'sales-orders', dict(customer_id=erp[3], reference='SALE',
        lines=[dict(material_id=erp[4][0], quantity='2', unit_price='7')]), 201)
    request('POST', f'sales-orders/{sales["id"]}/confirm')
    shipment = request('POST', 'shipments', dict(sales_order_id=sales['id'], warehouse_id=1,
        lines=[dict(material_id=erp[4][0], quantity='2')]), 201)
    request('POST', f'shipments/{shipment["id"]}/post')
    returned = request('POST', 'sales-returns', dict(shipment_id=shipment['id'], warehouse_id=1, reason='客户退回',
        lines=[dict(shipment_line_id=shipment['lines'][0]['id'], quantity='1')]), 201)
    request('POST', f'sales-returns/{returned["id"]}/post')
    key = f'sales_return:{returned["id"]}'
    assert source(client, key)['roles'] == {'inventory': '3.13', 'receivable': '-7.00', 'income': '7.00', 'sales_cost': '-3.13'}
    post(client, generate(client, key, 'SALE-RET'), reviewer)
    finished = completion(erp)
    charge = request('POST', 'production-costs/charges', dict(work_order_id=finished['work_order_id'],
        kind='overhead', amount='2.50', reference='FEE'), 201)
    post(client, generate(client, f'production_charge:{charge["id"]}', 'FEE-J'), reviewer)
    reversal = request('POST', f'production-costs/{charge["id"]}/reverse', dict(reason='费用更正'))
    key = f'production_charge_reversal:{reversal["reversal_id"]}'
    assert source(client, key)['roles'] == {'work_in_progress': '-2.50', 'overhead_accrual': '2.50'}
    post(client, generate(client, key, 'FEE-REV'), reviewer)


def test_generator_checks_fingerprint_configuration_date_and_cannot_edit(business):
    client, request, mapping, _, erp = business
    received = receipt(erp)
    request('POST', f'receipts/{received["id"]}/post')
    key = f'receipt:{received["id"]}'
    item = source(client, key)
    data = dict(source_key=key, fingerprint=item['fingerprint'], policy_version=1,
        reference='FRESH', journal_date=item['source_date'], reason='核对')
    assert client.post(BASE+'/generate', json={**data, 'fingerprint':'0'*64}).status_code == 409
    assert client.post(BASE+'/generate', json={**data, 'policy_version':2}).status_code == 409
    assert client.post(BASE+'/generate', json={**data, 'journal_date':'2026-12-31'}).status_code == 409
    assert client.post(BASE+'/generate', json={**data, 'source_key':'../users'}).status_code == 422
    row = generate(client, key)
    assert client.put(f'{JOURNALS}/{row["id"]}', json=dict(version=row['version'], reference='EDIT',
        journal_date=row['journal_date'], reason='试图覆盖金额', lines=[dict(account_id=mapping['inventory'],summary='伪造',debit='1',credit='0'),
        dict(account_id=mapping['payable'],summary='伪造',debit='0',credit='1')])).status_code == 409
    transition(client, row, 'cancel')
    assert client.post(BASE+'/generate', json={**data, 'journal_date':'2026-12-31'}).status_code == 409


def test_cosmetic_master_rename_keeps_posted_economic_snapshot(business):
    client, request, _, reviewer, erp = business
    received = receipt(erp); request('POST', f'receipts/{received["id"]}/post')
    row = post(client, generate(client, f'receipt:{received["id"]}'), reviewer)
    old_name = row['business_source']['evidence']['labels'][f'material:{erp[4][0]}']
    request('PUT', f'materials/{erp[4][0]}', dict(sku='ORM-0', name='更名物料',unit='件',version=1))
    current = source(client, f'receipt:{received["id"]}')
    assert current['fingerprint'] == row['business_source']['evidence']['fingerprint']
    assert current['labels'][f'material:{erp[4][0]}'] != old_name
    assert client.get(f'{JOURNALS}/{row["id"]}').json()['business_source']['evidence']['labels'][f'material:{erp[4][0]}'] == old_name


def test_stale_cost_blocks_draft_and_posted_cost_change_rolls_back(business):
    client, request, _, reviewer, erp = business
    inbound = request('POST', 'warehouse-inbounds', dict(warehouse_id=1, reference='FREE', reason='other', note='其他来源',
        lines=[dict(material_id=erp[4][0], quantity='3')]), 201)
    approve_document(client, None, 'WarehouseInbound', inbound['id'])
    request('POST', f'warehouse-inbounds/{inbound["id"]}/post')
    key = f'other_inbound:{inbound["id"]}'
    generate(client, key, expected=409)
    movement = source(client, key)['movements'][0]['id']
    request('POST', 'inventory/valuation/inputs', dict(movement_id=movement, unit_cost='1.115', reference='C1', reason='核价'), 201)
    row = generate(client, key)
    # 新核价使旧草稿失效，不能继续沿用客户端缓存金额。
    request('POST', 'inventory/valuation/inputs', dict(movement_id=movement, unit_cost='2', reference='C2', reason='更正'), 201)
    transition(client, row, 'submit', expected=409)
    transition(client, row, 'cancel')
    row = post(client, generate(client, key, 'AUTO-2'), reviewer)
    before = request('GET', 'inventory/valuation/inputs')
    request('POST', 'inventory/valuation/inputs', dict(movement_id=movement, unit_cost='3', reference='C3', reason='更正'), 409)
    assert request('GET', 'inventory/valuation/inputs') == before
    # 关联冲销也必须独立审核过账，之后才能改价和重新生成。
    reversal = client.post(f'{JOURNALS}/{row["id"]}/reverse', json=dict(version=row['version'],
        reason='改价前冲销', reference='GL-REV', journal_date=row['journal_date'])).json()
    post(client, reversal, reviewer)
    request('POST', 'inventory/valuation/inputs', dict(movement_id=movement, unit_cost='3', reference='C3', reason='更正'), 201)
    assert post(client, generate(client, key, 'AUTO-3'), reviewer)['total_debit'] == '9.00'


def test_policy_version_permissions_and_audit_failure(business):
    client, _, mapping, _, _ = business
    config = dict(version=1, start_date='2026-01-01', mapping={**mapping, 'cash': mapping['receivable']}, reason='资金科目核对')
    assert client.put(BASE + '/policy', json={**config, 'version': 0}).status_code == 409
    assert client.put(BASE + '/policy', json={**config, 'start_date': '2026-02-01'}).status_code == 409
    assert client.put(BASE + '/policy', json={**config, 'mapping': {'cash': True}}).status_code == 422

    def fail(session, *_):
        if any(isinstance(item, BusinessJournalPolicyChange) for item in session.new):
            raise RuntimeError('模拟审计故障')

    event.listen(Session, 'before_flush', fail)
    try:
        assert client.put(BASE + '/policy', json=config).status_code == 500
    finally:
        event.remove(Session, 'before_flush', fail)
    assert client.get(BASE + '/policy').json()['policy']['version'] == 1
    assert client.put(BASE + '/policy', json=config).json()['version'] == 2
    assert len(client.get(BASE + '/policy/changes').json()) == 2


def test_concurrent_generate_saves_one_source_and_journal(business):
    client, request, _, _, erp = business
    record = receipt(erp)
    request('POST', f'receipts/{record["id"]}/post')
    key = f'receipt:{record["id"]}'
    item = source(client, key)
    barrier = Barrier(2)

    def attempt(index):
        barrier.wait(timeout=5)
        return client.post(BASE + '/generate', json=dict(source_key=key, fingerprint=item['fingerprint'],
            policy_version=1, reference=f'PARALLEL-{index}', journal_date=item['source_date'], reason='并发核对')).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, (1, 2))) == [201, 409]
    with orm_session() as db:
        assert len(list(db.scalars(select(BusinessJournalSource)))) == 1


def test_inventory_accounting_amount_clears_fractional_tail(business):
    client, request, _, _, erp = business
    record = request('POST', 'warehouse-inbounds', dict(warehouse_id=1, reason='other', note='分位尾差',
        lines=[dict(material_id=erp[4][0], quantity='3')]), 201)
    approve_document(client, None, 'WarehouseInbound', record['id'])
    request('POST', f'warehouse-inbounds/{record["id"]}/post')
    movement = source(client, f'other_inbound:{record["id"]}')['movements'][0]['id']
    request('POST', 'inventory/valuation/inputs', dict(movement_id=movement, unit_cost='1.005', reference='ROUND', reason='核价'), 201)
    for index in range(3):
        row = request('POST', 'warehouse-outbounds', dict(warehouse_id=1, reason='other', note='分批出清',
            lines=[dict(material_id=erp[4][0], quantity='1')]), 201)
        request('POST', f'warehouse-outbounds/{row["id"]}/post')
    report = request('GET', 'inventory/valuation')
    assert [item['accounting_amount'] for item in report['movements']] == ['3.02', '-1.01', '-1.00', '-1.01']
    assert sum(Decimal(item['accounting_amount']) for item in report['movements']) == Decimal(report['total_amount']) == 0


def test_generation_fault_rolls_back_source_lines_and_journal(business):
    client, request, _, _, erp = business
    record = receipt(erp)
    request('POST', f'receipts/{record["id"]}/post')
    key = f'receipt:{record["id"]}'

    def fail(session, *_):
        if any(isinstance(item, BusinessJournalSource) for item in session.new):
            raise RuntimeError('模拟凭证来源保存故障')

    event.listen(Session, 'before_flush', fail)
    try:
        generate(client, key, expected=500)
    finally:
        event.remove(Session, 'before_flush', fail)
    with orm_session() as db:
        assert not list(db.scalars(select(BusinessJournalSource)))
        assert not list(db.scalars(select(Journal)))
    generate(client, key)


def test_production_wip_and_charge_sources_are_priced_and_locked(business):
    client, request, _, reviewer, erp = business
    record = receipt(erp)
    request('POST', f'receipts/{record["id"]}/post')
    finished = completion(erp)
    issue = next(item for item in client.get(BASE).json() if item['source_type'] == 'material_issue')
    assert issue['roles'] == {'inventory': '-12.50', 'work_in_progress': '12.50'}
    post(client, generate(client, issue['key'], 'ISSUE'), reviewer)
    charge = request('POST', 'production-costs/charges', dict(work_order_id=finished['work_order_id'],
        kind='labor', amount='1.50', reference='LABOR'), 201)
    assert source(client, f'production_charge:{charge["id"]}')['roles'] == {'work_in_progress': '1.50', 'labor_accrual': '-1.50'}
    post(client, generate(client, f'production_charge:{charge["id"]}', 'LABOR-J'), reviewer)
    request('POST', f'production-completions/{finished["id"]}/post')
    generate(client, f'production_completion:{finished["id"]}', 'COMPLETE', 409)
    settlement = request('POST', 'production-costs/settlements', dict(work_order_id=finished['work_order_id'], reference='COST'), 201)
    assert source(client, f'production_completion:{finished["id"]}')['roles'] == {'inventory': '14.00', 'work_in_progress': '-14.00'}
    post(client, generate(client, f'production_completion:{finished["id"]}', 'COMPLETE'), reviewer)
    # 结算冲销不能暗改已经进总账的完工成本。
    request('POST', f'production-costs/settlements/{settlement["id"]}/reverse', dict(reason='重结'), 409)


def test_closing_requires_posted_business_coverage(business, monkeypatch):
    client, request, _, reviewer, erp = business
    monkeypatch.setattr('app.finance.period_closing.utc_today', lambda: '2027-01-01')
    record = receipt(erp)
    request('POST', f'receipts/{record["id"]}/post')
    check = client.get('/api/v1/finance/accounting-periods/1/closing-check').json()
    assert 'pending_business_sources' in [item['code'] for item in check['blockers']]
    row = generate(client, f'receipt:{record["id"]}')
    transition(client, row, 'cancel')
    assert 'pending_business_sources' in [item['code'] for item in client.get('/api/v1/finance/accounting-periods/1/closing-check').json()['blockers']]
    post(client, generate(client, f'receipt:{record["id"]}', 'REGEN'), reviewer)
    assert client.get('/api/v1/finance/accounting-periods/1/closing-check').json()['can_close']


def test_business_permissions_do_not_follow_general_journal_access(business):
    client, request, _, _, _ = business
    role = 'business_viewer'
    request('POST', 'roles', dict(code=role, label='只看来源', permissions=['business_journal.view']), 201)
    request('POST', 'users', dict(username='viewer', password='viewer-pass-123', roles=[role]), 201)
    token = client.post('/api/v1/auth/login', json=dict(username='viewer', password='viewer-pass-123')).json()['token']
    headers = {'Authorization': 'Bearer ' + token}
    assert client.get(BASE, headers=headers).status_code == 200
    assert client.get(BASE + '/policy', headers=headers).status_code == 200
    assert client.put(BASE + '/policy', headers=headers, json=dict(version=1, start_date='2026-01-01',
        mapping={'inventory': 1}, reason='越权修改')).status_code == 403
    assert client.post(BASE + '/generate', headers=headers, json=dict(source_key='receipt:1', fingerprint='a'*64,
        policy_version=1, reference='DENIED', journal_date='2026-01-01', reason='越权')).status_code == 403


def test_v43_upgrade_atomic_failure_and_idempotent_retry(business, remove_transfer_schema):
    import sqlite3
    with connection() as db:
        remove_transfer_schema(db)
        for table in ('business_journal_sources', 'business_journal_policy_changes', 'business_journal_policies'):
            db.execute(f'DROP TABLE {table}')
        for code in ('business_journal.view', 'business_journal.configure', 'business_journal.generate'):
            db.execute('DELETE FROM role_permissions WHERE permission_code=?', (code,))
            db.execute('DELETE FROM permissions WHERE code=?', (code,))
        db.execute("DELETE FROM permission_groups WHERE code='finance.business_journals'")
        db.execute('PRAGMA user_version=43')
        db.execute("""CREATE TRIGGER fail_business_permissions BEFORE INSERT ON permissions
            WHEN NEW.code='business_journal.view'
            BEGIN SELECT RAISE(ABORT, '模拟业务凭证迁移故障'); END""")
    with pytest.raises(sqlite3.IntegrityError, match='模拟业务凭证迁移故障'):
        migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 43
        assert not db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'business_journal_%'").fetchall()
        db.execute('DROP TRIGGER fail_business_permissions')
    migrate()
    migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 89
        assert db.execute("SELECT COUNT(*) FROM permissions WHERE code LIKE 'business_journal.%'").fetchone()[0] == 3
