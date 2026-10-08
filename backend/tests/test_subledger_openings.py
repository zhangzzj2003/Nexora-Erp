"""分户期初勾稽、独立审核、资金来源、并发和故障回滚。"""

import csv
from approval_test_helpers import approve_document, execute_subledger_payment
from test_journals import action as journal_action

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from io import StringIO
import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session
from app.core.database import connection, migrate
from app.core.models import SubledgerOpening, SubledgerOpeningChange, SubledgerPayment
from app.core.orm import orm_session
from test_ledger_foundation import ledger, ACCOUNT, PERIOD

BASE = '/api/v1/finance/subledger-openings'
FIN = '/api/v1/finance'


@pytest.fixture
def subledger(ledger):
    client = ledger
    def api(method, path, payload=None, expected=200, headers=None):
        response = client.request(method, '/api/v1/' + path, json=payload, headers=headers)
        assert response.status_code == expected, response.text
        return response.text if expected == 500 else response.json()
    for code, category, normal in (('AR','asset','debit'),('AP','liability','credit'),('EQ','equity','credit'),('CASH','asset','debit')):
        api('POST', 'finance/ledger-accounts', dict(**{**ACCOUNT,'code':code,'name':code,'category':category,'normal_balance':normal}), 201)
    api('POST', 'finance/accounting-periods', {**PERIOD, 'end_date':'2026-12-31'}, 201)
    customers = [api('POST', 'customers', {'name':name}, 201)['id'] for name in ('客户甲','客户乙')]
    supplier = api('POST', 'suppliers', {'name':'供应商甲'}, 201)['id']
    project = api('POST', 'finance/auxiliary/items', dict(kind='project',code='P1',name='项目甲',reason='建档'), 201)['id']
    api('POST', 'users', dict(username='reviewer',password='reviewer-pass-123',roles=['finance']), 201)
    reviewer = {'Authorization':'Bearer ' + api('POST','auth/login', dict(username='reviewer',password='reviewer-pass-123'))['token']}
    def aux(kind, identifier):
        return [dict(kind=kind,id=identifier),dict(kind='project',id=project)]
    opening = api('POST','finance/opening-balances', dict(reference='GL',effective_date='2026-01-01',reason='原试算表',lines=[
        dict(account_id=1,summary='应收甲',debit='150',credit='0',auxiliary=aux('customer',customers[0])),
        dict(account_id=1,summary='应收乙贷方',debit='0',credit='30',auxiliary=aux('customer',customers[1])),
        dict(account_id=2,summary='应付甲',debit='0',credit='80',auxiliary=aux('supplier',supplier)),
        dict(account_id=3,summary='权益',debit='0',credit='40')]),201)
    from test_opening_balances import action as opening_action
    for action in ('submit','approve','confirm'):
        opening = opening_action((client, reviewer), opening, action, action == 'approve')
    payload = dict(reference='SUB',opening_balance_id=opening['id'],opening_version=opening['version'],reason='历史欠款清单',
        control_accounts=[dict(kind='receivable',account_id=1),dict(kind='payable',account_id=2)],lines=[
            dict(kind='receivable',party_id=customers[0],account_id=1,document_reference='OLD-A',document_date='2025-12-01',debit='100',credit='0',auxiliary=[dict(kind='project',id=project)]),
            dict(kind='receivable',party_id=customers[0],account_id=1,document_reference='OLD-B',document_date='2025-12-20',debit='50',credit='0',auxiliary=[dict(kind='project',id=project)]),
            dict(kind='receivable',party_id=customers[1],account_id=1,document_reference='OLD-CREDIT',document_date='2025-12-20',debit='0',credit='30',auxiliary=[dict(kind='project',id=project)]),
            dict(kind='payable',party_id=supplier,account_id=2,document_reference='OLD-AP',document_date='2025-12-20',debit='0',credit='80',auxiliary=[dict(kind='project',id=project)])])
    return client, api, reviewer, opening, payload, project


def create(subledger, **changes):
    return subledger[1]('POST','finance/subledger-openings',{**subledger[4],**changes},201)


def action(subledger, record, name, review=False):
    client = subledger[0]
    if name in ('submit','approve','reject','withdraw'):
        # 显式调用真实分户审批入口，原确认、资金及勾稽断言保留原领域路径。
        response = client.post(f'/api/v1/system/document-approvals/SubledgerOpening/{record["id"]}/{name}',
            json={'version': record['approval']['version'], 'reason': '分户核对'}, headers=subledger[2] if review else None)
        assert response.status_code == 200, response.text
        return next(row for row in client.get(BASE).json() if row['id'] == record['id'])
    return subledger[1]('POST',f'finance/subledger-openings/{record["id"]}/{name}',
        dict(version=record['version'],reason='分户核对'),headers=subledger[2] if review else None)


def confirmed(subledger):
    record = action(subledger, create(subledger), 'submit')
    return action(subledger, action(subledger, record, 'approve', True), 'confirm')


def payment(subledger, line, **values):
    return subledger[1]('POST',f'finance/subledger-openings/lines/{line["id"]}/payments',
        {**dict(action='settlement',amount='10',reference='BANK',reason='银行回单'),**values},201)


def query(subledger, **values):
    return subledger[1]('POST','finance/subledger-openings/query',{**dict(to_date='2026-12-31'),**values})


def test_complete_lifecycle_snapshots_and_exact_subledger_balances(subledger):
    client, api, *_ = subledger
    record = create(subledger)
    check = api('GET',f'finance/subledger-openings/{record["id"]}/check')
    assert check['matched'] and len(check['rows']) == 3
    assert [row['ledger_amount'] for row in check['rows']] == ['150.00','-30.00','-80.00']
    api('POST','finance/subledger-openings/query',dict(to_date='2026-12-31'),409)
    record = action(subledger, record, 'submit')
    api('POST',f'finance/subledger-openings/{record["id"]}/approve',dict(version=2,reason='自审'),409)
    record = action(subledger, action(subledger, record, 'approve',True), 'confirm')
    assert record['evidence'] == check
    report = query(subledger)
    assert report['totals'] == dict(receivable=dict(opening_amount='120.00',settled_amount='0.00',outstanding_amount='120.00'),
        payable=dict(opening_amount='80.00',settled_amount='0.00',outstanding_amount='80.00'))
    csv_rows = list(csv.reader(StringIO(report['csv'])))
    assert len(csv_rows) == 5 and csv_rows[1][-3:] == ['100.00','0.00','100.00']
    assert [row['action'] for row in api('GET',f'finance/subledger-openings/{record["id"]}/changes')] == ['create','submit','approve','confirm']
    assert api('GET','finance/overview')['accounts'] == []
    # 导入只扩充分户依据，不再往总账增加一遍期初金额。
    gl = api('POST','finance/ledger-reports/query',dict(kind='trial_balance',from_date='2026-01-01',to_date='2026-12-31'))
    assert gl['totals']['opening_debit'] == gl['totals']['opening_credit'] == '120.00'
    assert client.delete(f'{BASE}/{record["id"]}').status_code == 405


def test_equal_company_total_does_not_hide_wrong_party_or_project(subledger):
    client, api, _, _, payload, _ = subledger
    lines = [dict(row) for row in payload['lines']]
    lines[0]['party_id'] = lines[2]['party_id']
    record = create(subledger, lines=lines)
    check = api('GET',f'finance/subledger-openings/{record["id"]}/check')
    assert not check['matched'] and any(row['difference'] != '0.00' for row in check['rows'])
    api('POST',f'system/document-approvals/SubledgerOpening/{record["id"]}/submit',dict(version=0,reason='合计相等仍须核对'),409)
    changed = [dict(row) for row in payload['lines']]
    changed[0]['auxiliary'] = []
    saved = api('PUT',f'finance/subledger-openings/{record["id"]}',{**payload,'version':1,'lines':changed})
    assert saved['version'] == 2 and not api('GET',f'finance/subledger-openings/{record["id"]}/check')['matched']
    api('PUT',f'finance/subledger-openings/{record["id"]}',{**payload,'version':1},409)


@pytest.mark.parametrize('mutation', ('duplicate','bool_id','unknown_party','wrong_account','future_document','bad_amount','auxiliary_party'))
def test_input_boundary_does_not_create_partial_plan(subledger, mutation):
    client, api, _, _, payload, _ = subledger
    lines = [dict(row) for row in payload['lines']]
    expected = 422
    if mutation == 'duplicate': lines.append(lines[0])
    if mutation == 'bool_id': lines[0]['party_id'] = True
    if mutation == 'unknown_party': lines[0]['party_id'] = 999; expected = 409
    if mutation == 'wrong_account': lines[0]['account_id'] = 2; expected = 409
    if mutation == 'future_document': lines[0]['document_date'] = '2026-01-01'; expected = 409
    if mutation == 'bad_amount': lines[0]['debit'] = '1e2'
    if mutation == 'auxiliary_party': lines[0]['auxiliary'] = [dict(kind='customer',id=1)]
    api('POST','finance/subledger-openings',{**payload,'lines':lines},expected)
    assert api('GET','finance/subledger-openings') == []


def test_cancel_reverse_dependency_and_replacement_gap(subledger):
    _, api, _, opening, _, _ = subledger
    record = create(subledger)
    api('POST',f'finance/opening-balances/{opening["id"]}/reverse',dict(version=4,reason='先撤总账'),409)
    record = action(subledger, record, 'cancel')
    record = create(subledger, reference='SECOND')
    for name in ('submit','approve','confirm'):
        record = action(subledger, record, name, name == 'approve')
    approve_document(subledger[0], None, 'SubledgerOpening', record['id'], intent='reverse', reason='分户核对')
    record = next(row for row in subledger[0].get(BASE).json() if row['id'] == record['id'])
    record = action(subledger, record, 'reverse')
    api('POST','finance/subledger-openings/query',dict(to_date='2026-12-31'),409)
    replacement = create(subledger, reference='REPLACEMENT')
    replacement = action(subledger, replacement, 'cancel')
    api('POST','finance/subledger-openings/query',dict(to_date='2026-12-31'),409)
    # 取消替代草稿不能绕开已撤销方案留下的启用门槛。
    from app.finance.subledger_rules import check_subledger
    with orm_session() as db:
        with pytest.raises(Exception, match='原分户期初已撤销'):
            check_subledger(db)


def test_parallel_creation_confirmation_and_no_duplicate_audit(subledger):
    client, api, _, _, payload, _ = subledger
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda reference: client.post(BASE,json={**payload,'reference':reference}),('A','B')))
    assert sorted(row.status_code for row in responses) == [201,409]
    record = next(row.json() for row in responses if row.status_code == 201)
    record = action(subledger, action(subledger, record, 'submit'), 'approve',True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post(f'{BASE}/{record["id"]}/confirm',
            json=dict(version=record['version'],reason='启用')),range(2)))
    assert sorted(row.status_code for row in responses) == [200,409]
    assert len(api('GET',f'finance/subledger-openings/{record["id"]}/changes')) == 4


def test_parallel_payments_credit_refund_reversal_and_as_of_date(subledger):
    client, api, *_ = subledger
    record = confirmed(subledger)
    positive, _, credit, payable = record['lines']
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda reference: client.post(f'{BASE}/lines/{positive["id"]}/payments',
            json=dict(action='settlement',amount='70',reference=reference,reason='资金回单')),('BANK-A','BANK-B')))
    assert [row.status_code for row in responses] == [201,201]
    drafts=[row.json() for row in responses]
    for draft in drafts:
        approve_document(client,None,'SubledgerPayment',draft['id'],reason='核对分户银行回单')
    # 草稿不占余额，执行在同一写锁重新核对，两个七十元草稿仅一笔可生效。
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda row: client.post(f'{BASE}/payments/{row["id"]}/post',json={'version':row['version'],'reason':'执行资金'}),drafts))
    assert sorted(row.status_code for row in responses)==[200,409]
    paid=next(row.json() for row in responses if row.status_code==200)
    refund = execute_subledger_payment(client,None,payment(subledger,credit,action='refund',amount='20',reference='REFUND'))
    execute_subledger_payment(client,None,payment(subledger,payable,amount='80',reference='PAYABLE'))
    api('POST',f'finance/subledger-openings/lines/{credit["id"]}/payments',dict(action='settlement',amount='1',reference='BAD',reason='错误'),409)
    report = query(subledger)
    assert report['totals']['receivable']['outstanding_amount'] == '70.00'
    assert report['totals']['payable']['outstanding_amount'] == '0.00'
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post(f'{BASE}/payments/{paid["id"]}/reverse',json=dict(reason='误登记')),range(2)))
    assert sorted(row.status_code for row in responses) == [201,409]
    execute_subledger_payment(client,None,next(row.json() for row in responses if row.status_code==201))
    assert query(subledger)['totals']['receivable']['outstanding_amount'] == '140.00'
    before = query(subledger,to_date='2026-01-01')
    assert before['totals']['receivable']['settled_amount'] == '0.00'
    api('POST',f'finance/subledger-openings/{record["id"]}/reverse',dict(version=4,reason='已冲销仍不可重设'),409)
    assert api('GET','finance/subledger-openings/payments')[0]['reverses_id'] == paid['id']


def test_business_journal_sources_keep_true_party_and_auxiliary(subledger):
    _, api, reviewer, *_ = subledger
    record = confirmed(subledger)
    paid = execute_subledger_payment(subledger[0],None,payment(subledger,record['lines'][0]))
    api('PUT','finance/business-journals/policy',dict(version=0,start_date='2026-01-01',mapping={'receivable':1,'payable':2,'cash':4},reason='来源科目'))
    api('PUT','finance/business-journals/policy',dict(version=1,start_date='2026-01-01',mapping={'receivable':4,'cash':4},reason='错误改科目'),409)
    source = next(item for item in api('GET','finance/business-journals') if item['key'] == f'subledger_payment:{paid["id"]}')
    assert source['roles'] == dict(cash='10.00',receivable='-10.00') and source['can_generate']
    assert {item['kind'] for item in source['auxiliary_defaults']} == {'customer','project'}
    generated = api('POST','finance/business-journals/generate',dict(source_key=source['key'],fingerprint=source['fingerprint'],
        policy_version=1,reference='SUB-PAY',journal_date=source['source_date'],reason='回单凭证'),201)
    assert all({item['kind'] for item in line['auxiliary']} == {'customer','project'} for line in generated['lines'])
    for name in ('submit','approve','post'):
        generated = journal_action(subledger[0], generated, name, reviewer if name == 'approve' else None)
    # 资金冲销为新增业务事件，原已过账来源保持不变。
    reversed_record = api('POST',f'finance/subledger-openings/payments/{paid["id"]}/reverse',dict(reason='回单登记更正'),201)
    execute_subledger_payment(subledger[0],None,reversed_record)
    keys = [item['key'] for item in api('GET','finance/business-journals')]
    assert f'subledger_payment:{reversed_record["id"]}' in keys
    assert query(subledger)['totals']['receivable']['outstanding_amount'] == '120.00'


def test_audit_or_response_failure_rolls_back_entire_plan_and_payment(subledger, monkeypatch):
    _, api, *_ = subledger
    from app.finance import subledger_openings as module
    original = module.audit
    def failed(*args):
        original(*args)
        raise RuntimeError('模拟完整审计后失败')
    monkeypatch.setattr(module,'audit',failed)
    api('POST','finance/subledger-openings',subledger[4],500)
    assert api('GET','finance/subledger-openings') == []
    monkeypatch.setattr(module,'audit',original)
    record = confirmed(subledger)
    original_payment = module.payment_data
    monkeypatch.setattr(module,'payment_data',lambda *_: (_ for _ in ()).throw(RuntimeError('响应失败')))
    api('POST',f'finance/subledger-openings/lines/{record["lines"][0]["id"]}/payments',
        dict(action='settlement',amount='10',reference='FAIL',reason='回单'),500)
    monkeypatch.setattr(module,'payment_data',original_payment)
    with orm_session() as db:
        assert list(db.scalars(select(SubledgerPayment))) == []
    assert query(subledger)['totals']['receivable']['settled_amount'] == '0.00'


def test_pending_plan_blocks_post_and_locks_confirmed_basis(subledger):
    _, api, reviewer, *_ = subledger
    record = create(subledger)
    journal = api('POST','finance/journals',dict(reference='MANUAL',journal_date='2026-02-01',reason='凭证依据',lines=[
        dict(account_id=4,summary='资金',debit='1',credit='0'),dict(account_id=3,summary='权益',debit='0',credit='1')]),201)
    for name in ('submit','approve'):
        journal = journal_action(subledger[0], journal, name, reviewer if name == 'approve' else None)
    api('POST',f'finance/journals/{journal["id"]}/post',dict(version=journal['version'],reason='未启用'),409)
    for name in ('submit','approve','confirm'):
        record = action(subledger, record, name, name == 'approve')
    journal = api('POST',f'finance/journals/{journal["id"]}/post',dict(version=journal['version'],reason='已核对分户'))
    api('POST',f'finance/subledger-openings/{record["id"]}/reverse',dict(version=4,reason='已有过账'),409)


def test_independent_review_includes_previous_editor_and_confirm_failure_rolls_back(subledger, monkeypatch):
    _, api, reviewer, _, payload, _ = subledger
    from app.finance import subledger_openings as module
    record = create(subledger)
    record = api('PUT',f'finance/subledger-openings/{record["id"]}',{**payload,'version':1,'reason':'第二人编辑'},headers=reviewer)
    record = action(subledger, record, 'submit')
    api('POST',f'finance/subledger-openings/{record["id"]}/approve',dict(version=3,reason='编辑人自审'),409,reviewer)
    api('POST','users',dict(username='third',password='third-pass-123',roles=['finance']),201)
    headers = {'Authorization':'Bearer ' + api('POST','auth/login',dict(username='third',password='third-pass-123'))['token']}
    reviewed = api('POST',f'system/document-approvals/SubledgerOpening/{record["id"]}/approve',dict(version=record['approval']['version'],reason='第三人审核'),headers=headers)
    record = next(row for row in api('GET','finance/subledger-openings') if row['id'] == record['id'])
    original = module.audit
    def fail_confirmation(*args):
        original(*args)
        if args[3] == 'confirm': raise RuntimeError('确认审计后失败')
    monkeypatch.setattr(module,'audit',fail_confirmation)
    api('POST',f'finance/subledger-openings/{record["id"]}/confirm',dict(version=4,reason='启用'),500)
    unchanged = api('GET','finance/subledger-openings')[0]
    assert unchanged['status'] == 'approved' and unchanged['version'] == 4 and unchanged['evidence'] is None
    assert len(api('GET',f'finance/subledger-openings/{record["id"]}/changes')) == 4


def test_existing_business_is_not_silently_added_to_imported_debt(subledger):
    client, api, *_ = subledger
    material = api('POST','materials',dict(sku='OLD',name='旧物料',unit='件'),201)['id']
    receipt = api('POST','receipts',dict(supplier_id=1,lines=[dict(material_id=material,quantity='1')]),201)
    # 先独立审批已有采购入库，再验证历史债务不会吞并新业务来源。
    approve_document(client, dict(client.headers), 'Receipt', receipt['id'])
    api('POST',f'receipts/{receipt["id"]}/post')
    api('POST','finance/subledger-openings',subledger[4],409)
    assert api('GET','finance/subledger-openings') == []


def test_closed_period_evidence_keeps_names_and_locks_new_payment_timestamp(subledger, monkeypatch):
    _, api, *_ = subledger
    record = confirmed(subledger)
    execute_subledger_payment(subledger[0],None,payment(subledger,record['lines'][0]))
    # 结账使用实际服务端日期；模拟已结束期间，核对快照与时钟回退锁期。
    from app.finance import period_closing
    monkeypatch.setattr(period_closing,'utc_today',lambda:'2027-01-01')
    closed = api('POST','finance/accounting-periods/1/close',dict(version=1,reason='验收归档'))
    archived = api('GET','finance/accounting-periods/1/closings')[0]['evidence']['subledger']
    assert archived['opening']['evidence'] == record['evidence']
    assert archived['rows'][0]['outstanding_amount'] == '90.00'
    api('POST',f'finance/subledger-openings/lines/{record["lines"][0]["id"]}/payments',
        dict(action='settlement',amount='1',reference='LOCKED',reason='锁期内'),409)
    assert len(api('GET','finance/subledger-openings/payments')) == 1
    api('PUT',f'finance/auxiliary/items/{subledger[5]}',dict(version=1,name='项目更名',is_active=True,reason='改名'))
    assert api('GET','finance/accounting-periods/1/closings')[0]['evidence']['subledger'] == archived
    assert query(subledger)['rows'][0]['party_name'] == '客户甲'


def test_read_only_permissions_and_csv_escape(subledger):
    _, api, *_ = subledger
    lines = [dict(row) for row in subledger[4]['lines']]
    lines[0]['document_reference'] = '=DANGEROUS'
    record = create(subledger, lines=lines)
    for name in ('submit','approve','confirm'):
        record = action(subledger, record, name, name == 'approve')
    api('POST','roles',dict(code='sub_read',label='分户只读',permissions=['subledger_opening.view']),201)
    api('POST','users',dict(username='sub_reader',password='reader-pass-123',roles=['sub_read']),201)
    headers = {'Authorization':'Bearer ' + api('POST','auth/login',dict(username='sub_reader',password='reader-pass-123'))['token']}
    report = api('POST','finance/subledger-openings/query',dict(to_date='2026-12-31'),headers=headers)
    assert "'=DANGEROUS" in report['csv']
    assert api('GET','finance/subledger-openings',headers=headers)[0]['status'] == 'confirmed'
    api('GET','finance/subledger-openings/options',expected=403,headers=headers)
    api('POST',f'finance/subledger-openings/lines/{record["lines"][0]["id"]}/payments',
        dict(action='settlement',amount='1',reference='FORBIDDEN',reason='越权'),403,headers)
    api('POST','finance/subledger-openings/query',dict(to_date='2025-12-31'),409)
    api('POST','finance/subledger-openings/query',dict(to_date='2026-12-31',party_id=True),422)


def test_v47_upgrade_is_atomic_and_keeps_old_amounts(subledger, remove_subledger_schema, monkeypatch):
    _, api, _, opening, *_ = subledger
    with connection() as db:
        remove_subledger_schema(db)
        db.execute('PRAGMA user_version=47')
        original = [tuple(row) for row in db.execute('SELECT * FROM opening_balance_lines ORDER BY id')]
    import app.core.database as database
    original_connection = database.connection
    from contextlib import contextmanager
    @contextmanager
    def failed_connection():
        with original_connection() as db:
            db.set_authorizer(lambda operation,arg,*_: database.sqlite3.SQLITE_DENY
                if operation == database.sqlite3.SQLITE_CREATE_TABLE and arg == 'subledger_payments'
                else database.sqlite3.SQLITE_OK)
            yield db
    monkeypatch.setattr(database,'connection',failed_connection)
    with pytest.raises(Exception): migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 47
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='subledger_openings'").fetchone()
    monkeypatch.setattr(database,'connection',original_connection)
    migrate(); migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 95
        assert [tuple(row) for row in db.execute('SELECT * FROM opening_balance_lines ORDER BY id')] == original
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    assert api('GET','finance/subledger-openings') == []
