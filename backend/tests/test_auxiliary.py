"""辅助核算的真实来源、拆分余额、旧库与失败回滚。"""

import csv
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from io import StringIO

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core.database import connection, migrate
from app.core.models import AuxiliaryAssignment, AuxiliaryItemChange, AuxiliaryPolicyChange, Journal
from app.core.orm import orm_session
from test_ledger_foundation import ledger
from test_journals import journals, payload, action, PATH
from test_opening_balances import confirmed, create as opening_create
from test_profit_transfers import profit, generate as transfer_generate, preview, post as profit_post
from test_statements import statements, query as statement_query
from test_business_orm import erp, receipt
from test_business_journals import business, source as business_source, generate as business_generate

URL = '/api/v1/finance/auxiliary'


def item(client, kind='department', code='DEP', name='研发部'):
    response = client.post(URL + '/items', json=dict(kind=kind, code=code, name=name, reason='确定辅助档案'))
    assert response.status_code == 201, response.text
    return response.json()


def ref(record):
    return dict(kind=record['kind'], id=record['id'])


def policy(client, account_id=1, kinds=None, version=0, start_date='2026-01-01'):
    response = client.put(f'{URL}/policies/{account_id}', json=dict(version=version, start_date=start_date,
        required_kinds=kinds or ['department'], reason='确定科目辅助规则'))
    assert response.status_code == 200, response.text
    return response.json()


def journal(client, reference, auxiliary=None, date='2026-01-10', account_id=1, debit='123.45', credit='0'):
    data = payload(reference)
    data['journal_date'] = date
    data['lines'][0].update(account_id=account_id, debit=debit, credit=credit, auxiliary=auxiliary or [])
    data['lines'][1].update(account_id=2 if account_id == 1 else 1, debit=credit, credit=debit)
    response = client.post(PATH, json=data)
    assert response.status_code == 201, response.text
    return response.json()


def post(journals, record):
    client, reviewer = journals
    return action(client, action(client, action(client, record, 'submit'), 'approve', reviewer), 'post')


def query(client, **changes):
    response = client.post(URL + '/query', json={**dict(account_id=1, kind='department',
        from_date='2026-01-01', to_date='2026-01-31'), **changes})
    assert response.status_code == 200, response.text
    return response.json()


def test_four_dimensions_strict_ids_duplicates_and_audit(journals):
    client, _ = journals
    customer = client.post('/api/v1/customers', json={'name': '客户甲'}).json()
    supplier = client.post('/api/v1/suppliers', json={'name': '供应商甲'}).json()
    department, project = item(client), item(client, 'project', 'PRJ', '新品项目')
    policy(client, kinds=['customer', 'supplier', 'department', 'project'])
    references = [dict(kind='customer', id=customer['id']), dict(kind='supplier', id=supplier['id']), ref(department), ref(project)]
    record = journal(client, 'FOUR', references)
    assert {v['name'] for v in record['lines'][0]['auxiliary']} == {'客户甲', '供应商甲', '研发部', '新品项目'}
    history = client.get(f'{PATH}/{record["id"]}/changes').json()
    assert history[-1]['after']['lines'] == record['lines']
    for bad in ([ref(department), ref(department)], [dict(kind='department', id=True)],
                [dict(kind='employee', id=1)], [dict(kind='department', id=1, name='伪造')]):
        data = payload('INVALID')
        data['lines'][0]['auxiliary'] = bad
        assert client.post(PATH, json=data).status_code == 422
    data = payload('MISSING')
    assert client.post(PATH, json=data).status_code == 409
    data['lines'][0]['auxiliary'] = [dict(kind='project', id=department['id'])]
    assert client.post(PATH, json=data).status_code == 409


def test_policy_changes_revalidate_review_and_cannot_rewrite_posted(journals):
    client, reviewer = journals
    old = post(journals, journal(client, 'HISTORICAL'))
    draft = action(client, journal(client, 'PENDING'), 'submit')
    policy(client)
    response = client.post(f'{PATH}/{draft["id"]}/approve', headers=reviewer,
        json=dict(version=draft['version'], reason='复核'))
    assert response.status_code == 409
    assert client.get(f'{PATH}/{draft["id"]}').json()['version'] == draft['version']
    assert client.get(f'{PATH}/{old["id"]}').json()['lines'][0]['auxiliary'] == []
    report = query(client)
    assert report['rows'][0]['entity_id'] == 0 and report['rows'][0]['name'] == '未分配'
    assert report['totals']['closing_net'] == '123.45'
    assert client.put(URL+'/policies/1', json=dict(version=1, start_date='2026-01-02',
        required_kinds=[], reason='修改启用日')).status_code == 409


def test_stopped_item_blocks_original_but_reversal_copies_posted_snapshot(journals):
    client, reviewer = journals
    department = item(client)
    policy(client)
    old = post(journals, journal(client, 'ORIGINAL', [ref(department)]))
    draft = journal(client, 'BEFORE-STOP', [ref(department)])
    response = client.put(f'{URL}/items/{department["id"]}', json=dict(version=1, name='已停用新名称',
        is_active=False, reason='组织变更'))
    assert response.status_code == 200
    assert client.post(f'{PATH}/{draft["id"]}/submit', json=dict(version=1, reason='提交')).status_code == 409
    reverse = client.post(f'{PATH}/{old["id"]}/reverse', json=dict(version=old['version'],
        reference='REV', journal_date='2026-01-20', reason='更正历史')).json()
    assert reverse['lines'][0]['auxiliary'] == old['lines'][0]['auxiliary']
    assert reverse['lines'][0]['auxiliary'][0]['name'] == '研发部'
    post(journals, reverse)
    assert query(client)['totals']['closing_net'] == '0.00'


def test_split_opening_reconciles_trial_balance_and_statements(statements):
    profit_data, _ = statements
    client, reviewer, accounts = profit_data
    a, b = item(client), item(client, code='OTHER', name='制造部')
    policy(client)
    lines = [dict(account_id=1, summary='分户期初', debit=amount, credit='0', auxiliary=[ref(dimension)])
        for dimension, amount in ((a, '0.10'), (b, '0.20'))]
    lines.append(dict(account_id=accounts['profit'], summary='权益', debit='0', credit='0.30'))
    opened = confirmed((client, reviewer), lines=lines)
    assert len(opened['lines']) == 3
    report = query(client)
    assert report['totals'] == dict(opening_net='0.30', debit='0.00', credit='0.00', closing_net='0.30')
    trial = client.post('/api/v1/finance/ledger-reports/query', json=dict(kind='trial_balance',
        from_date='2026-01-01', to_date='2026-01-31')).json()
    assert trial['totals']['balanced'] and trial['totals']['opening_debit'] == '0.30'
    result = statement_query(client)
    assert result['totals']['assets'] == result['totals']['equity'] == '0.30'
    assert len(result['opening_sources'][0]['auxiliary']) == 1


def test_same_opening_combination_rejected_independent_of_order(journals):
    client, _ = journals
    a, b = item(client), item(client, 'project', 'PRJ', '项目')
    from test_opening_balances import payload as opening_payload
    lines = [dict(account_id=1, summary='重复', debit='1', credit='0', auxiliary=values)
        for values in ([ref(a), ref(b)], [ref(b), ref(a)])]
    lines.append(dict(account_id=2, summary='对方', debit='0', credit='2'))
    assert client.post('/api/v1/finance/opening-balances', json=opening_payload(lines=lines)).status_code == 422


def test_report_date_boundaries_csv_and_single_dimension_does_not_multiply(journals):
    client, _ = journals
    a, b = item(client), item(client, 'project', 'PRJ', '=SUM(A1)')
    post(journals, journal(client, 'OLD', [ref(a), ref(b)], date='2026-01-09', debit='0.10'))
    post(journals, journal(client, 'IN', [ref(a), ref(b)], date='2026-01-10', debit='0.20'))
    post(journals, journal(client, 'END', [ref(a), ref(b)], date='2026-01-20', credit='0.05', debit='0'))
    post(journals, journal(client, 'FUTURE', [ref(a)], date='2026-01-21', debit='0.40'))
    report = query(client, from_date='2026-01-10', to_date='2026-01-20')
    assert len(report['rows']) == 1
    assert report['totals'] == dict(opening_net='0.10', debit='0.20', credit='0.05', closing_net='0.25')
    assert len(report['rows'][0]['entries']) == 3
    project = query(client, kind='project', from_date='2026-01-10', to_date='2026-01-20')
    csv_rows = list(csv.reader(StringIO(project['csv'].lstrip('\ufeff'))))
    assert csv_rows[2][1].startswith("'")
    assert csv_rows[2][2:] == ['0.10', '0.00', '0.20', '0.05', '0.25', '0.00']
    assert query(client, entity_id=0)['rows'] == []


def test_net_zero_income_still_clears_each_auxiliary_combination(profit):
    client, reviewer, accounts = profit
    a, b = item(client, 'project', 'A', '盈利项目'), item(client, 'project', 'B', '调整项目')
    policy(client, accounts['income'], ['project'])
    profit_post(profit, journal(client, 'PROFIT-A', [ref(a)], account_id=accounts['income'], debit='0', credit='10'))
    profit_post(profit, journal(client, 'PROFIT-B', [ref(b)], account_id=accounts['income'], debit='10', credit='0'))
    evidence = preview(client)['evidence']
    assert evidence['net_profit'] == '0.00' and len(evidence['rows']) == 2 and len(evidence['lines']) == 4
    # 停用历史项目也不能阻断按原快照清零。
    client.put(f'{URL}/items/{a["id"]}', json=dict(version=1, name='停用项目', is_active=False, reason='结束'))
    transfer = transfer_generate(client)
    assert {v['name'] for line in transfer['lines'] for v in line['auxiliary']} == {'盈利项目', '调整项目'}
    profit_post(profit, transfer)
    assert preview(client)['evidence']['rows'] == []
    report = query(client, account_id=accounts['income'], kind='project')
    assert all(row['closing_debit'] == row['closing_credit'] == '0.00' for row in report['rows'])


def test_business_partner_is_real_source_and_explicit_department_required(business):
    client, request, mapping, _, erp_data = business
    received = receipt(erp_data)
    request('POST', f'receipts/{received["id"]}/post')
    key = f'receipt:{received["id"]}'
    a = item(client)
    policy(client, mapping['payable'], ['supplier', 'department'])
    current = business_source(client, key)
    assert current['auxiliary_defaults'][0]['kind'] == 'supplier'
    data = dict(source_key=key, fingerprint=current['fingerprint'], policy_version=current['policy_version'],
        reference='BUS-AUX', journal_date=current['source_date'], reason='业务辅助')
    assert client.post('/api/v1/finance/business-journals/generate', json=data).status_code == 409
    bad = dict(auxiliary_by_role={'payable': [dict(kind='supplier', id=9999), ref(a)]})
    assert client.post('/api/v1/finance/business-journals/generate', json={**data, **bad}).status_code == 409
    response = client.post('/api/v1/finance/business-journals/generate', json={**data,
        'auxiliary_by_role': {'payable': [ref(a)]}})
    assert response.status_code == 201, response.text
    payable = next(line for line in response.json()['lines'] if line['account_id'] == mapping['payable'])
    assert {value['kind'] for value in payable['auxiliary']} == {'supplier', 'department'}


def test_parallel_versions_and_audit_failure_roll_back(journals):
    client, _ = journals
    a = item(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(lambda name: client.put(f'{URL}/items/{a["id"]}', json=dict(version=1,
            name=name, is_active=True, reason='并发更新')).status_code, ['甲', '乙']))
    assert sorted(codes) == [200, 409]

    def fail(db, *_):
        if any(isinstance(value, AuxiliaryAssignment) for value in db.new):
            raise RuntimeError('模拟辅助写入失败')

    event.listen(Session, 'before_flush', fail)
    try:
        data = payload('ROLLBACK')
        data['lines'][0]['auxiliary'] = [ref(a)]
        assert client.post(PATH, json=data).status_code == 500
    finally:
        event.remove(Session, 'before_flush', fail)
    with orm_session() as db:
        assert db.scalar(select(Journal.id).where(Journal.reference == 'ROLLBACK')) is None
        assert list(db.scalars(select(AuxiliaryAssignment))) == []
        assert len(list(db.scalars(select(AuxiliaryItemChange)))) == 2
    assert journal(client, 'ROLLBACK', [ref(a)])['id']


def test_policy_audit_failure_and_retry(journals):
    client, _ = journals

    def fail(db, *_):
        if any(isinstance(value, AuxiliaryPolicyChange) for value in db.new):
            raise RuntimeError('模拟规则审计失败')

    event.listen(Session, 'before_flush', fail)
    try:
        assert client.put(URL+'/policies/1', json=dict(version=0, start_date='2026-01-01',
            required_kinds=['project'], reason='初次配置')).status_code == 500
    finally:
        event.remove(Session, 'before_flush', fail)
    assert client.get(URL+'/options').json()['auxiliary_policies'] == []
    assert policy(client)['version'] == 1


def test_v46_migration_preserves_rows_and_atomic_retry(journals, remove_auxiliary_schema):
    old = opening_create(journals)
    with connection() as db:
        remove_auxiliary_schema(db)
        db.execute('CREATE UNIQUE INDEX legacy_opening_account ON opening_balance_lines(opening_balance_id,account_id)')
        db.execute('PRAGMA user_version=46')
        db.execute("""CREATE TRIGGER fail_auxiliary_permission BEFORE INSERT ON permissions
            WHEN NEW.code='auxiliary.view' BEGIN SELECT RAISE(ABORT,'辅助迁移失败'); END""")
    with pytest.raises(sqlite3.IntegrityError, match='辅助迁移失败'):
        migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 46
        assert db.execute("SELECT name FROM sqlite_master WHERE name='legacy_opening_account'").fetchone()
        assert not db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'auxiliary_%'").fetchall()
        assert [dict(row) for row in db.execute('SELECT * FROM opening_balance_lines ORDER BY position')] == [
            {key: value for key, value in row.items() if key != 'auxiliary'} for row in old['lines']]
        db.execute('DROP TRIGGER fail_auxiliary_permission')
    migrate(); migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 69
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    assert journals[0].get('/api/v1/finance/opening-balances').json()[0]['lines'] == old['lines']


def test_permissions_and_invalid_query(journals):
    client, _ = journals
    client.post('/api/v1/users', json=dict(username='reader', password='reader-pass-123', roles=['viewer']))
    token = client.post('/api/v1/auth/login', json=dict(username='reader', password='reader-pass-123')).json()['token']
    headers = {'Authorization': 'Bearer ' + token}
    assert client.get(URL+'/options', headers=headers).status_code == 403
    assert client.post(URL+'/items', headers=headers, json=dict(kind='department', code='X', name='越权', reason='测试')).status_code == 403
    client.post('/api/v1/roles', json=dict(code='aux_reader', label='辅助只读', permissions=['auxiliary.view']))
    client.post('/api/v1/users', json=dict(username='aux_reader', password='reader-pass-123', roles=['aux_reader']))
    token = client.post('/api/v1/auth/login', json=dict(username='aux_reader', password='reader-pass-123')).json()['token']
    headers = {'Authorization': 'Bearer ' + token}
    assert client.get(URL+'/options', headers=headers).status_code == 200
    assert client.post(URL+'/query', headers=headers, json=dict(account_id=1, kind='department',
        from_date='2026-01-01', to_date='2026-01-31')).status_code == 200
    assert client.put(URL+'/policies/1', headers=headers, json=dict(version=0, start_date='2026-01-01',
        required_kinds=[], reason='越权')).status_code == 403
    for changes in (dict(account_id=True), dict(from_date='2026-02-01', to_date='2026-01-31'), dict(kind='employee'), dict(entity_id=-1)):
        data = dict(account_id=1, kind='department', from_date='2026-01-01', to_date='2026-01-31')
        assert client.post(URL+'/query', json={**data, **changes}).status_code == 422


def test_closing_evidence_freezes_auxiliary_and_counts_unassigned(journals):
    client, _ = journals
    a = item(client)
    record = post(journals, journal(client, 'CLOSING', [ref(a)]))
    response = client.get('/api/v1/finance/accounting-periods/1/closing-check')
    assert response.status_code == 200, response.text
    response = client.post('/api/v1/finance/accounting-periods/1/close', json=dict(version=1, reason='核对期间及辅助来源'))
    assert response.status_code == 200, response.text
    auxiliary = client.get('/api/v1/finance/accounting-periods/1/closings').json()[0]['evidence']['auxiliary']
    assert auxiliary['unassigned_count'] == 1
    assert auxiliary['lines'][0]['auxiliary'] == record['lines'][0]['auxiliary']
    client.put(f'{URL}/items/{a["id"]}', json=dict(version=1, name='改名后', is_active=True, reason='档案改名'))
    assert client.get('/api/v1/finance/accounting-periods/1/closings').json()[0]['evidence']['auxiliary'] == auxiliary
