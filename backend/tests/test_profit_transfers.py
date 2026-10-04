"""损益清零、来源冻结、倒序更正与原子事务的真实风险。"""

from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core.database import connection, migrate
from app.core.models import Journal, JournalChange, ProfitTransfer, ProfitTransferPolicyChange
from app.core.orm import orm_session
from test_journals import journals, action, PATH
from test_ledger_foundation import ledger, ACCOUNT, PERIOD, BASE
from test_opening_balances import confirmed

URL = BASE + '/profit-transfers'


@pytest.fixture
def profit(journals):
    client, reviewer = journals
    accounts = {}
    for code, category, direction in [('income','income','credit'), ('expense','expense','debit'),
            ('sales_cost','cost','debit'), ('wip','cost','debit'), ('profit','equity','credit'),
            ('other_profit','equity','credit')]:
        response = client.post(BASE + '/ledger-accounts', json={**ACCOUNT, 'code':code,
            'name':code, 'category':category, 'normal_balance':direction})
        assert response.status_code == 201, response.text
        accounts[code] = response.json()['id']
    policy = dict(version=0, start_date='2026-01-01', target_account_id=accounts['profit'],
        cost_account_ids=[accounts['sales_cost']], reason='公司确认的结转范围')
    assert client.put(URL + '/policy', json=policy).status_code == 200
    return client, reviewer, accounts


def post_record(profit, account, amount, reference='SOURCE', date='2026-01-10'):
    client, reviewer, accounts = profit
    income = amount > 0
    amount = f'{abs(amount):.2f}'
    lines = [dict(account_id=accounts[account], summary='实际损益', debit='0' if income else amount,
        credit=amount if income else '0'), dict(account_id=1, summary='资金', debit=amount if income else '0',
        credit='0' if income else amount)]
    response = client.post(PATH, json=dict(reference=reference, journal_date=date,
        note='', reason='原始票据', lines=lines))
    assert response.status_code == 201, response.text
    return post(profit, response.json())


def post(profit, record):
    client, reviewer, _ = profit
    return action(client, action(client, action(client, record, 'submit'), 'approve', reviewer), 'post')


def preview(client, period_id=1):
    response = client.get(f'{URL}/periods/{period_id}')
    assert response.status_code == 200, response.text
    return response.json()


def generate(client, reference='TRANSFER', period_id=1, status=201, changes=None):
    item = preview(client, period_id)
    data = dict(period_id=period_id, period_version=item['period']['version'],
        policy_version=item['policy_version'], fingerprint=item['fingerprint'], reference=reference, reason='期末核对')
    response = client.post(URL + '/generate', json={**data, **(changes or {})})
    assert response.status_code == status, response.text
    return response.json() if status != 500 else None


def check(client, period_id=1):
    return client.get(f'{BASE}/accounting-periods/{period_id}/closing-check').json()


def period_action(client, period_id, action_name):
    period = next(item for item in client.get(BASE + '/accounting-periods').json() if item['id'] == period_id)
    response = client.post(f'{BASE}/accounting-periods/{period_id}/{action_name}',
        json=dict(version=period['version'], reason='核对损益及证据'))
    assert response.status_code == 200, response.text
    return response.json()


def reverse(profit, record, reference='REVERSE', date=None):
    client, _, _ = profit
    response = client.post(f'{PATH}/{record["id"]}/reverse', json=dict(version=record['version'],
        reference=reference, journal_date=date or record['journal_date'], reason='更正结转'))
    assert response.status_code == 201, response.text
    return response.json()


def test_profit_lifecycle_closing_and_archived_evidence(profit):
    client, reviewer, accounts = profit
    post_record(profit, 'income', 100)
    post_record(profit, 'expense', -40, 'EXPENSE')
    item = preview(client)
    assert item['can_generate'] and item['evidence']['net_profit'] == '60.00'
    assert 'profit_transfer_pending' in [row['code'] for row in check(client)['blockers']]
    record = generate(client)
    assert record['journal_date'] == '2026-01-31' and record['total_debit'] == '100.00'
    assert record['profit_transfer']['evidence']['fingerprint'] == item['fingerprint']
    generate(client, 'DUPLICATE', status=409)
    assert client.put(f'{PATH}/{record["id"]}', json=dict(reference='EDIT', journal_date=record['journal_date'],
        note='', version=1, reason='伪造', lines=[{key:line[key] for key in ('account_id','summary','debit','credit')} for line in record['lines']])).status_code == 409
    submitted = action(client, record, 'submit')
    assert client.post(f'{PATH}/{record["id"]}/approve', json=dict(version=2, reason='自审')).status_code == 409
    record = action(client, action(client, submitted, 'approve', reviewer), 'post')
    assert preview(client)['evidence']['rows'] == [] and check(client)['can_close']
    period_action(client, 1, 'close')
    evidence = client.get(f'{BASE}/accounting-periods/1/closings').json()[0]['evidence']['profit_transfer']
    assert evidence['journal_id'] == record['id'] and evidence['residuals'] == []
    # 归档保留生成时科目名称，重命名不改变经济来源。
    account = next(item for item in client.get(BASE + '/ledger-accounts').json() if item['id'] == accounts['income'])
    assert client.put(f'{BASE}/ledger-accounts/{account["id"]}', json=dict(version=1, name='主营收入', is_active=True, reason='准确命名')).status_code == 200
    assert client.get(f'{PATH}/{record["id"]}').json()['profit_transfer']['evidence']['rows'][0]['name'] != '主营收入'


def test_loss_zero_net_and_cost_scope(profit):
    client, _, accounts = profit
    post_record(profit, 'expense', -80)
    post_record(profit, 'wip', -12, 'WIP')
    item = preview(client)
    assert item['evidence']['net_profit'] == '-80.00'
    assert item['evidence']['excluded_cost_accounts'][0]['balance'] == '12.00'
    record = generate(client)
    target = next(line for line in record['lines'] if line['account_id'] == accounts['profit'])
    assert target['debit'] == '80.00'
    post(profit, record)
    assert check(client)['can_close']


def test_zero_net_still_clears_each_account(profit):
    client, _, accounts = profit
    post_record(profit, 'income', 10)
    post_record(profit, 'sales_cost', -10, 'COGS')
    assert preview(client)['evidence']['net_profit'] == '0.00'
    record = generate(client)
    assert len(record['lines']) == 2 and all(line['account_id'] != accounts['profit'] for line in record['lines'])
    post(profit, record)
    assert check(client)['can_close']
    generate(client, 'ZERO', status=409)


def test_stale_preview_and_draft_must_be_cancelled(profit):
    client, _, _ = profit
    post_record(profit, 'income', 50)
    old = preview(client)
    post_record(profit, 'income', 20, 'LATER')
    generate(client, status=409, changes={'fingerprint':old['fingerprint']})
    record = generate(client)
    post_record(profit, 'expense', -5, 'LATE-EXPENSE')
    assert client.post(f'{PATH}/{record["id"]}/submit', json=dict(version=1, reason='旧来源')).status_code == 409
    action(client, record, 'cancel')
    replacement = generate(client, 'NEW')
    assert replacement['profit_transfer']['evidence']['net_profit'] == '65.00'


def test_posted_transfer_protects_late_source_and_rolls_back(profit):
    client, reviewer, accounts = profit
    post_record(profit, 'income', 50)
    record = post(profit, generate(client))
    # 非纳管成本及普通资产分录不改写结转来源，可以继续过账。
    post_record(profit, 'wip', -12, 'WIP-LATE')
    response = client.post(PATH, json=dict(reference='LATE', journal_date='2026-01-15', note='', reason='补录',
        lines=[dict(account_id=accounts['income'], summary='收入', debit='0', credit='1'),
            dict(account_id=1, summary='现金', debit='1', credit='0')]))
    late = action(client, action(client, response.json(), 'submit'), 'approve', reviewer)
    denied = client.post(f'{PATH}/{late["id"]}/post', json=dict(version=late['version'], reason='补过账'))
    assert denied.status_code == 409 and '倒序冲销' in denied.text
    assert client.get(f'{PATH}/{late["id"]}').json()['status'] == 'approved'
    assert len(client.get(f'{PATH}/{late["id"]}/changes').json()) == 3
    action(client, late, 'cancel')
    reversal = reverse(profit, record)
    # 草稿冲销不解除来源保护或重复生成限制。
    generate(client, 'NOT-YET', status=409)
    post(profit, reversal)
    assert generate(client, 'REBUILD')['profit_transfer']['evidence']['net_profit'] == '50.00'


def test_reversal_requires_original_period_and_reopen(profit):
    client, _, _ = profit
    post_record(profit, 'income', 50)
    record = post(profit, generate(client))
    client.post(BASE + '/accounting-periods', json={**PERIOD, 'code':'FEB', 'start_date':'2026-02-01', 'end_date':'2026-02-28'})
    assert client.post(f'{PATH}/{record["id"]}/reverse', json=dict(version=4, reference='CROSS',
        journal_date='2026-02-28', reason='跨期错误')).status_code == 409
    period_action(client, 1, 'close')
    assert client.post(f'{PATH}/{record["id"]}/reverse', json=dict(version=4, reference='CLOSED',
        journal_date='2026-01-31', reason='未重开')).status_code == 409
    period_action(client, 1, 'reopen')
    post(profit, reverse(profit, record))
    assert 'profit_transfer_pending' in [row['code'] for row in check(client)['blockers']]
    post(profit, generate(client, 'REBUILD'))
    period_action(client, 1, 'close')


def test_later_transfer_requires_reverse_order(profit):
    client, reviewer, _ = profit
    post_record(profit, 'income', 50)
    jan = post(profit, generate(client))
    period_action(client, 1, 'close')
    client.post(BASE + '/accounting-periods', json={**PERIOD, 'code':'FEB', 'start_date':'2026-02-01', 'end_date':'2026-02-28'})
    post_record(profit, 'income', 20, 'FEB-INCOME', '2026-02-10')
    assert preview(client, 2)['evidence']['net_profit'] == '20.00'
    feb = post(profit, generate(client, 'FEB-TRANSFER', 2))
    period_action(client, 1, 'reopen')
    reverse_jan = reverse(profit, jan)
    submitted = action(client, reverse_jan, 'submit')
    approved = action(client, submitted, 'approve', reviewer)
    denied = client.post(f'{PATH}/{approved["id"]}/post', json=dict(version=3, reason='先改一月'))
    assert denied.status_code == 409 and '倒序' in denied.text
    action(client, approved, 'cancel')
    post(profit, reverse(profit, feb, 'FEB-REVERSE'))
    post(profit, reverse(profit, jan, 'JAN-REVERSE'))


def test_policy_boundaries_versions_and_atomic_audit(profit):
    client, _, accounts = profit
    policy = client.get(URL + '/policy').json()['policy']
    change = {**{key:policy[key] for key in ('version','start_date','target_account_id','cost_account_ids')}, 'reason':'修改配置'}
    for fields, status in [({'version':0},409), ({'start_date':'2026-02-01'},409),
            ({'target_account_id':accounts['income']},409), ({'cost_account_ids':[accounts['expense']]},409),
            ({'cost_account_ids':[True]},422), ({'cost_account_ids':[accounts['sales_cost']]*2},422), ({},409)]:
        assert client.put(URL + '/policy', json={**change, **fields}).status_code == status
    def fail_audit(session, *_):
        if any(isinstance(item, ProfitTransferPolicyChange) for item in session.new):
            raise RuntimeError('模拟配置审计失败')
    event.listen(Session, 'before_flush', fail_audit)
    try:
        assert client.put(URL + '/policy', json={**change, 'target_account_id':accounts['other_profit']}).status_code == 500
    finally:
        event.remove(Session, 'before_flush', fail_audit)
    assert client.get(URL + '/policy').json()['policy'] == policy
    post_record(profit, 'income', 50)
    draft = generate(client)
    assert client.put(URL + '/policy', json={**change, 'target_account_id':accounts['other_profit']}).status_code == 200
    assert client.post(f'{PATH}/{draft["id"]}/submit', json=dict(version=1, reason='旧配置')).status_code == 409
    history = client.get(URL + '/policy/changes').json()
    assert len(history) == 2 and history[0]['before']['target_account_id'] == accounts['profit']


def test_generation_atomic_failure_and_parallel_deduplication(profit):
    client, _, _ = profit
    post_record(profit, 'income', 50)
    def fail_source(session, *_):
        if any(isinstance(item, ProfitTransfer) for item in session.new):
            raise RuntimeError('模拟结转来源失败')
    event.listen(Session, 'before_flush', fail_source)
    try:
        generate(client, status=500)
    finally:
        event.remove(Session, 'before_flush', fail_source)
    with orm_session() as db:
        assert db.scalar(select(Journal.id).where(Journal.reference == 'TRANSFER')) is None
        assert list(db.scalars(select(ProfitTransfer))) == []
    item = preview(client)
    data = dict(period_id=1, period_version=1, policy_version=1, fingerprint=item['fingerprint'], reason='并发')
    def call(reference):
        return client.post(URL + '/generate', json={**data, 'reference':reference}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(call, ('PARALLEL-1','PARALLEL-2'))) == [201,409]


def test_opening_balances_included_with_precise_cents(profit):
    client, reviewer, accounts = profit
    confirmed((client, reviewer), lines=[dict(account_id=accounts['income'], summary='损益历史', debit='0', credit='0.11'),
        dict(account_id=1, summary='现金', debit='0.11', credit='0')])
    from decimal import Decimal
    post_record(profit, 'income', Decimal('0.10'))
    assert preview(client)['evidence']['net_profit'] == '0.21'
    record = generate(client)
    assert record['profit_transfer']['evidence']['opening_sources'][0]['credit'] == '0.11'
    post(profit, record)
    assert check(client)['can_close']


def test_disabled_accounts_and_unconfigured_closing(profit):
    client, _, accounts = profit
    post_record(profit, 'income', 50)
    assert client.put(f'{BASE}/ledger-accounts/{accounts["income"]}', json=dict(version=1,
        name='income', is_active=False, reason='停用测试')).status_code == 200
    assert not preview(client)['can_generate']
    assert '停用' in '；'.join(preview(client)['blockers'])
    generate(client, status=409)
    # 未配置时有损益余额不能绕过检查直接结账。
    with orm_session(write=True) as db:
        from app.core.models import ProfitTransferPolicy
        db.delete(db.get(ProfitTransferPolicy, 1))
    assert 'profit_transfer_pending' in [row['code'] for row in check(client)['blockers']]


def test_pending_journals_period_order_and_cutoff(profit, monkeypatch):
    client, _, accounts = profit
    post_record(profit, 'income', 50)
    monkeypatch.setattr('app.finance.profit_transfers.utc_today', lambda: '2026-01-31')
    assert '已结束' in '；'.join(preview(client)['blockers'])
    generate(client, status=409)
    monkeypatch.setattr('app.finance.profit_transfers.utc_today', lambda: '2026-04-01')
    client.post(BASE + '/accounting-periods', json={**PERIOD, 'code':'FEB', 'start_date':'2026-02-01', 'end_date':'2026-02-28'})
    assert '更早' in '；'.join(preview(client, 2)['blockers'])
    response = client.post(PATH, json=dict(reference='PENDING', journal_date='2026-01-20', note='', reason='未处理',
        lines=[dict(account_id=accounts['income'], summary='收入', debit='0', credit='1'),
            dict(account_id=1, summary='现金', debit='1', credit='0')]))
    pending = response.json()
    assert not preview(client)['can_generate']
    generate(client, status=409)
    action(client, pending, 'cancel')
    draft = generate(client)
    another = client.post(PATH, json=dict(reference='LATE-DRAFT', journal_date='2026-01-20', note='', reason='未处理',
        lines=[dict(account_id=accounts['income'], summary='收入', debit='0', credit='1'),
            dict(account_id=1, summary='现金', debit='1', credit='0')])).json()
    assert client.post(f'{PATH}/{draft["id"]}/submit', json=dict(version=1, reason='还有未处理')).status_code == 409
    action(client, another, 'cancel')
    post(profit, draft)
    period_action(client, 1, 'close')
    assert preview(client, 2)['evidence']['rows'] == []


def test_precision_and_total_limit_without_truncation(profit):
    from decimal import Decimal
    client, _, _ = profit
    post_record(profit, 'income', Decimal('999999999999.99'))
    post_record(profit, 'income', Decimal('0.01'), 'CENT')
    item = preview(client)
    assert item['evidence']['net_profit'] == '1000000000000.00'
    assert not item['can_generate'] and '超出' in '；'.join(item['blockers'])
    generate(client, status=409)


def test_permissions_input_and_migration_failure(profit, remove_transfer_schema):
    client, _, _ = profit
    assert client.post('/api/v1/roles', json=dict(code='profit_reader', label='损益只读', permissions=['profit_transfer.view'])).status_code == 201
    client.post('/api/v1/users', json=dict(username='viewer', password='viewer-pass-123', roles=['profit_reader']))
    token = client.post('/api/v1/auth/login', json=dict(username='viewer', password='viewer-pass-123')).json()['token']
    headers = {'Authorization':'Bearer ' + token}
    assert client.get(URL + '/policy', headers=headers).status_code == 200
    assert client.get(URL + '/periods/1', headers=headers).status_code == 200
    data = dict(period_id=1, period_version=1, policy_version=1, fingerprint='a'*64, reference='DENIED', reason='越权')
    assert client.post(URL + '/generate', headers=headers, json=data).status_code == 403
    assert client.post(URL + '/generate', json={**data, 'lines':[], 'journal_date':'2026-01-10'}).status_code == 422
    assert client.post(URL + '/generate', json={**data, 'period_id':True}).status_code == 422
    with connection() as db:
        remove_transfer_schema(db)
        db.execute('PRAGMA user_version=44')
        db.execute("""CREATE TRIGGER fail_profit_permissions BEFORE INSERT ON permissions
            WHEN NEW.code='profit_transfer.view' BEGIN SELECT RAISE(ABORT, '模拟损益结转迁移失败'); END""")
    with pytest.raises(sqlite3.IntegrityError, match='模拟损益结转迁移失败'):
        migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 44
        assert not db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'profit_transfer%'").fetchall()
        db.execute('DROP TRIGGER fail_profit_permissions')
    migrate()
    migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 73
        assert db.execute("SELECT count(*) FROM permissions WHERE code LIKE 'profit_transfer.%'").fetchone()[0] == 3
