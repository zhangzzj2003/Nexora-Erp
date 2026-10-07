"""报表范围、结转排除、完整映射、历史归档和事务回滚的真实风险。"""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import sqlite3

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core.database import connection, migrate
from app.core.models import FinancialStatement, FinancialStatementPolicyChange
from app.core.orm import orm_session
from test_journals import journals, action, PATH
from test_ledger_foundation import ledger, BASE
from test_profit_transfers import profit, post_record, post, generate
from test_period_closing import command
from test_opening_balances import confirmed, create as create_opening

URL = BASE + '/statements'
FILTERS = dict(from_date='2026-01-01', to_date='2026-01-31')


@pytest.fixture
def statements(profit):
    client, _, accounts = profit
    policy = dict(version=0, reason='公司确认报表项目',
        lines=[dict(code=g.upper(), name=g, group=g) for g in ('asset','liability','equity','revenue','expense')],
        allocations=[], manual_transfer_ids=[])
    for account in client.get(BASE+'/ledger-accounts').json():
        group = {'income':'revenue', 'cost':'expense'}.get(account['category'], account['category'])
        if account['id'] == accounts['wip']:
            group = 'asset'
        policy['allocations'].append(dict(account_id=account['id'], line_code=group.upper()))
    response = client.put(URL+'/policy', json=policy)
    assert response.status_code == 200, response.text
    return profit, policy


def query(client, **changes):
    r = client.post(URL+'/query', json={**FILTERS, **changes})
    assert r.status_code == 200, r.text
    return r.json()


def archived(client, item, status=201):
    r = client.post(URL+'/archive', json={**item['filters'], 'policy_version':item['policy_version'],
        'fingerprint':item['fingerprint'], 'reason':'财务核对后的报表快照'})
    assert r.status_code == status, r.text
    return r.json() if status != 500 else r.text


def sources(profit):
    post_record(profit, 'income', Decimal('0.30'), 'REVENUE')
    post_record(profit, 'expense', Decimal('-0.10'), 'EXPENSE')
    post_record(profit, 'sales_cost', Decimal('-0.05'), 'SALES-COST')
    post_record(profit, 'wip', Decimal('-0.20'), 'WIP')


def close(profit):
    client, _, _ = profit
    post(profit, generate(client))
    command(client)


def test_precise_statement_before_and_after_transfer_and_archive(statements):
    profit, _ = statements
    client, _, accounts = profit
    sources(profit)
    before = query(client)
    assert before['totals'] == dict(assets='0.15', liabilities='0.00', equity='0.15',
        unclosed_profit='0.15', opening_difference='0.00', closing_difference='0.00',
        revenue='0.30', expense='0.15', net_profit='0.15')
    assert not before['can_archive']
    assert any(a['account_id']==accounts['wip'] and a['group']=='asset' for a in before['contributions'])
    close(profit)
    after = query(client)
    assert after['totals']['unclosed_profit'] == '0.00'
    assert after['totals']['net_profit'] == before['totals']['net_profit']
    assert after['totals']['assets'] == after['totals']['equity'] == '0.15'
    assert after['can_archive'] and any(s['excluded_from_income'] for s in after['sources'])
    archived(client, before, 409)
    saved = archived(client, after)
    assert saved['snapshot']['csv'] == after['csv']
    assert client.get(URL+'/archives').json()[0]['id'] == saved['id']
    # 展示关联单号不写入固定归档；原财务来源仍逐字段一致。
    assert all(row['journal_document_no'].startswith('JV-') for row in after['sources'])
    assert client.get(URL+f'/archives/{saved["id"]}').json()['snapshot']['sources'] == [
        {key: value for key, value in row.items() if not key.endswith('_document_no')} for row in after['sources']]
    archived(client, after, 409)


def test_archive_preserves_configuration_names_after_changes(statements):
    profit, policy = statements
    client, _, _ = profit
    sources(profit); close(profit)
    saved = archived(client, query(client))
    policy['version']=1
    policy['lines'][0]['name']='新资产项目'
    assert client.put(URL+'/policy', json=policy).status_code==200
    assert query(client)['policy_version']==2
    old=client.get(URL+f'/archives/{saved["id"]}').json()['snapshot']
    assert old['policy_version']==1 and old['balance_rows'][0]['name']=='asset'
    history=client.get(URL+'/policy/changes').json()
    assert history[0]['before']['version']==1 and history[0]['after']['version']==2


def test_unmapped_nonzero_and_cost_scope_block_archive(statements):
    profit, policy = statements
    client, _, accounts=profit
    sources(profit); close(profit)
    policy['version']=1
    policy['allocations']=[a for a in policy['allocations'] if a['account_id']!=1]
    assert client.put(URL+'/policy', json=policy).status_code==200
    item=query(client)
    assert item['unmapped'][0]['account_id']==1 and not item['can_archive']
    archived(client,item,409)
    policy['version']=2
    policy['allocations'].append(dict(account_id=1,line_code='ASSET'))
    next(a for a in policy['allocations'] if a['account_id']==accounts['wip'])['line_code']='EXPENSE'
    assert client.put(URL+'/policy', json=policy).status_code==200
    assert any('成本范围' in b for b in query(client)['blockers'])


def test_manual_transfer_and_reversal_excluded_only_when_explicit(statements):
    profit, policy=statements
    client, _, accounts=profit
    post_record(profit,'income',Decimal('10.00'))
    response=client.post(PATH,json=dict(reference='MANUAL-CLOSE',journal_date='2026-01-31',reason='手工结转',
        lines=[dict(account_id=accounts['income'],summary='结转',debit='10',credit='0'),
               dict(account_id=accounts['profit'],summary='本年利润',debit='0',credit='10')]))
    assert response.status_code==201,response.text
    manual=post(profit,response.json())
    unclassified=query(client)
    assert unclassified['totals']['revenue']=='0.00'
    assert unclassified['unclassified_transfers']==[manual['id']]
    assert any('手工结转' in b for b in unclassified['blockers'])
    policy.update(version=1,manual_transfer_ids=[manual['id']])
    assert client.put(URL+'/policy',json=policy).status_code==200
    assert query(client)['totals']['revenue']=='10.00'
    r=client.post(PATH+f'/{manual["id"]}/reverse',json=dict(version=manual['version'],reference='UNDO',
        journal_date='2026-01-31',reason='取消手工结转'))
    assert r.status_code==201,r.text
    post(profit,r.json())
    result=query(client)
    assert result['totals']['revenue']=='10.00' and result['totals']['unclosed_profit']=='10.00'
    assert len([s for s in result['sources'] if s['excluded_from_income']])==4


def test_policy_failure_rolls_back_and_version_is_not_overwritten(statements):
    profit, policy=statements
    client, _, _=profit
    assert client.put(URL+'/policy',json=policy).status_code==409
    policy['version']=1; policy['lines'][0]['name']='失败修改'
    def fail(session, _):
        if any(isinstance(x,FinancialStatementPolicyChange) for x in session.new):
            raise RuntimeError('模拟审计故障')
    event.listen(Session,'before_flush',fail)
    try:
        assert client.put(URL+'/policy',json=policy).status_code==500
    finally:
        event.remove(Session,'before_flush',fail)
    current=client.get(URL+'/options').json()['policy']
    assert current['version']==1 and current['lines'][0]['name']=='asset'


def test_archive_atomic_failure_and_parallel_deduplication(statements):
    profit,_=statements
    client,_,_=profit
    sources(profit);close(profit)
    item=query(client)
    def fail(session,_):
        if any(isinstance(x,FinancialStatement) for x in session.new):
            raise RuntimeError('模拟归档故障')
    event.listen(Session,'before_flush',fail)
    try:
        archived(client,item,500)
    finally:
        event.remove(Session,'before_flush',fail)
    assert client.get(URL+'/archives').json()==[]
    data={**FILTERS, 'policy_version':1,'fingerprint':item['fingerprint'],'reason':'并发归档'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses=list(pool.map(lambda _:client.post(URL+'/archive',json=data).status_code,range(2)))
    assert sorted(statuses)==[201,409]
    with orm_session() as db:
        assert len(list(db.scalars(select(FinancialStatement))))==1


def test_dates_permissions_and_unconfigured_policy(ledger):
    assert ledger.post(URL+'/query',json=FILTERS).status_code==409
    assert ledger.post(URL+'/query',json={**FILTERS,'to_date':'invalid'}).status_code==422
    assert ledger.post(URL+'/query',json={**FILTERS,'to_date':'2025-01-01'}).status_code==422
    assert ledger.get(URL+'/archives/1').status_code==404
    assert ledger.post('/api/v1/roles',json=dict(code='statement_read',label='报表只读',permissions=['financial_statement.view'])).status_code==201
    ledger.post('/api/v1/users',json=dict(username='statement_viewer',password='viewer-pass-123',roles=['statement_read']))
    token=ledger.post('/api/v1/auth/login',json=dict(username='statement_viewer',password='viewer-pass-123')).json()['token']
    headers={'Authorization':'Bearer '+token}
    assert ledger.get(URL+'/options',headers=headers).status_code==200
    assert ledger.post(URL+'/archive',headers=headers,json={**FILTERS,'policy_version':1,'fingerprint':'a'*64,'reason':'越权'}).status_code==403


def test_input_constraints_and_invalid_manual_classification(statements):
    profit,policy=statements
    client,_,_=profit
    assert client.put(URL+'/policy',json={**policy,'version':True}).status_code==422
    assert client.put(URL+'/policy',json={**policy,'allocations':policy['allocations']*2}).status_code==422
    assert client.put(URL+'/policy',json={**policy,'lines':policy['lines']*2}).status_code==422
    bad={**policy,'version':1,'allocations':[dict(account_id=1,line_code='EQUITY')]}
    assert client.put(URL+'/policy',json=bad).status_code==409
    post_record(profit,'income',Decimal('1.00'))
    assert client.put(URL+'/policy',json={**policy,'version':1,'manual_transfer_ids':[1]}).status_code==409
    assert client.put(URL+'/policy',json={**policy,'version':1,'manual_transfer_ids':[True]}).status_code==422


def test_v45_migration_atomic_retry(statements,remove_statement_schema):
    profit,_=statements
    with connection() as db:
        remove_statement_schema(db)
        db.execute('PRAGMA user_version=45')
        db.execute("""CREATE TRIGGER fail_statement_permissions BEFORE INSERT ON permissions
            WHEN NEW.code='financial_statement.view' BEGIN SELECT RAISE(ABORT,'模拟报表迁移失败'); END""")
    with pytest.raises(sqlite3.IntegrityError,match='模拟报表迁移失败'):
        migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==45
        assert not db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'financial_statement%'").fetchall()
        db.execute('DROP TRIGGER fail_statement_permissions')
    migrate();migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]== 90


def test_opening_is_balance_only_and_pending_opening_blocks(statements):
    profit,_=statements
    client,reviewer,accounts=profit
    draft=create_opening((client,reviewer))
    assert client.post(URL+'/query',json=FILTERS).status_code==409
    from test_opening_balances import action as opening_action
    opening_action((client,reviewer),draft,'cancel')
    confirmed((client,reviewer),reference='OPEN-CONFIRMED',lines=[dict(account_id=1,summary='现金',debit='0.21',credit='0'),
        dict(account_id=accounts['profit'],summary='权益',debit='0',credit='0.21')])
    item=query(client)
    assert item['totals']['assets']==item['totals']['equity']=='0.21'
    assert item['totals']['net_profit']=='0.00' and item['opening_balance_id']
    assert len(item['opening_sources'])==2
    assert client.post(URL+'/query',json={**FILTERS,'from_date':'2025-12-31'}).status_code==409


def test_income_boundaries_exclude_prior_and_future_and_pending_blocks(statements):
    profit,_=statements
    client,_,_=profit
    post_record(profit,'income',Decimal('0.10'),'OLD','2026-01-09')
    post_record(profit,'income',Decimal('0.20'),'START','2026-01-10')
    post_record(profit,'expense',Decimal('-0.05'),'END','2026-01-20')
    post_record(profit,'income',Decimal('100.00'),'FUTURE','2026-01-21')
    item=query(client,from_date='2026-01-10',to_date='2026-01-20')
    assert item['totals']['net_profit']=='0.15'
    assert item['totals']['assets']==item['totals']['equity']=='0.25'
    assert item['totals']['unclosed_profit']=='0.25' and not item['can_archive']
    assert 'FUTURE' not in {s['reference'] for s in item['sources']}
    from test_journals import payload
    draft=client.post(PATH,json=payload('PENDING')).json()
    item=query(client)
    assert item['pending'][0]['id']==draft['id']
    assert any('未处理凭证' in b for b in item['blockers'])


def test_csv_formula_safety_and_stale_configuration(statements):
    import csv
    from io import StringIO
    profit,policy=statements
    client,_,_=profit
    sources(profit);close(profit)
    old=query(client)
    policy['version']=1;policy['lines'][0]['name']='=1+1'
    assert client.put(URL+'/policy',json=policy).status_code==200
    archived(client,old,409)
    current=query(client)
    data=list(csv.reader(StringIO(current['csv'].lstrip('\ufeff'))))
    assert any("'=1+1" in row for row in data)
    assert current['balance_rows'][0]['name']=='=1+1'
    assert archived(client,current)['snapshot']['policy']['lines'][0]['name']=='=1+1'


def test_account_metadata_change_invalidates_reviewed_report_and_old_archive_keeps_names(statements):
    profit, _ = statements
    client, _, accounts = profit
    sources(profit)
    close(profit)
    reviewed = query(client)
    assert all(item['opening'] != '-0.00' for item in reviewed['contributions'])
    saved = archived(client, reviewed)
    account = next(item for item in client.get(BASE+'/ledger-accounts').json() if item['id'] == 1)
    changed = client.put(BASE+f"/ledger-accounts/{account['id']}", json=dict(
        name='新现金名称', is_active=account['is_active'],
        version=account['version'], reason='核对科目名称'))
    assert changed.status_code == 200, changed.text
    archived(client, reviewed, 409)
    current = query(client)
    assert current['fingerprint'] != reviewed['fingerprint']
    assert next(item for item in current['account_snapshots'] if item['id'] == account['id'])['name'] == '新现金名称'
    archived(client, current)
    old = client.get(URL+f"/archives/{saved['id']}").json()['snapshot']
    assert next(item for item in old['account_snapshots'] if item['id'] == account['id'])['name'] == account['name']
