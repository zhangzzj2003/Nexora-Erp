"""历史分户资金的固定原单、独立审批、执行与迁移，不能把草稿当作真实资金。"""

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session
from app.core.database import connection, migrate
from app.core.models import DocumentApprovalEvent, SubledgerPayment, SubledgerOpeningLine
from app.core.orm import orm_session
from app.finance.business_sources import business_sources
from approval_test_helpers import approve_document, execute_subledger_payment
from test_ledger_foundation import ledger
from test_subledger_openings import subledger, confirmed, payment, query, BASE
from test_journal_document_approval import reviewer

PATH='/api/v1/system/document-approvals/SubledgerPayment'


def state(client, row):
    response=client.get(f'{PATH}/{row["id"]}')
    assert response.status_code==200,response.text
    return response.json()


def act(client,row,name,version,headers=None,expected=200,reason='核对原单与银行回单'):
    response=client.post(f'{PATH}/{row["id"]}/{name}',headers=headers,json={'version':version,'reason':reason})
    assert response.status_code==expected,response.text
    return response.json()


def execute(client,row,name='post',expected=200):
    response=client.post(f'{BASE}/payments/{row["id"]}/{name}',json={'version':row['version'],'reason':'执行分户资金核对'})
    assert response.status_code==expected,response.text
    return response.json() if expected != 500 else response.text


def test_three_steps_fixed_original_and_no_funds_until_execution(subledger):
    client,api,*_=subledger
    opening=confirmed(subledger)
    api('PUT','system/document-approvals/SubledgerPayment',{'version':1,'steps':[{'name':name,'role':None} for name in ('审核','核准','批准')]})
    row=payment(subledger,opening['lines'][0])
    assert row['status']=='draft' and row['executed_at'] is None
    assert query(subledger)['rows'][0]['outstanding_amount']=='100.00'
    assert client.get('/api/v1/finance/bank-reconciliation/overview').json()['sources']==[]
    assert f'subledger_payment:{row["id"]}' not in [s['key'] for s in client.get('/api/v1/finance/business-journals').json()]
    execute(client,row,expected=409)
    submitted=act(client,row,'submit',0)
    act(client,row,'approve',submitted['version'],expected=403)
    execute(client,row,'cancel',expected=409)
    assert any(s['label']=='完整辅助归属' and '项目甲' in s['value'] for s in submitted['summary'])
    for index in range(3):
        actor=reviewer(client,f'funds_reviewer_{index}')
        submitted=act(client,row,'approve',submitted['version'],actor)
        if index<2:act(client,row,'approve',submitted['version'],actor,expected=403)
    assert submitted['status']=='approved' and query(subledger)['rows'][0]['outstanding_amount']=='100.00'
    result=execute(client,row)
    assert result['approval']['status']=='executed' and result['executed_at'] and result['executed_by']
    assert query(subledger)['rows'][0]['outstanding_amount']=='90.00'
    assert state(client,row)['events'][-1]['reason']=='执行分户资金核对'
    execute(client,row,expected=409)


def test_execute_event_failure_rolls_back_money_and_timestamp(subledger):
    client=subledger[0];opening=confirmed(subledger);row=payment(subledger,opening['lines'][0])
    approve_document(client,None,'SubledgerPayment',row['id'],reason='核对资金')
    def fail(session,_):
        if any(isinstance(item,DocumentApprovalEvent) and item.action=='execute' for item in session.new):
            raise RuntimeError('模拟资金执行证据失败')
    event.listen(Session,'before_flush',fail)
    try:execute(client,row,expected=500)
    finally:event.remove(Session,'before_flush',fail)
    current=next(r for r in client.get(BASE+'/payments').json() if r['id']==row['id'])
    assert current['status']=='draft' and current['version']==1 and current['executed_at'] is None
    assert state(client,row)['status']=='approved' and query(subledger)['rows'][0]['outstanding_amount']=='100.00'
    assert execute(client,row)['status']=='executed'


def test_cancel_releases_reference_and_reversal_reservation_without_reusing_number(subledger):
    client=subledger[0];opening=confirmed(subledger);line=opening['lines'][0]
    row=payment(subledger,line);approve_document(client,None,'SubledgerPayment',row['id'],reason='核对资金')
    row=execute(client,row)
    original=dict(row)
    draft=subledger[1]('POST',f'finance/subledger-openings/payments/{row["id"]}/reverse',{'reason':'原回单录错'},201)
    assert query(subledger)['rows'][0]['outstanding_amount']=='90.00'
    cancelled=execute(client,draft,'cancel')
    assert cancelled['status']=='cancelled' and cancelled['cancellation_reason']
    new=subledger[1]('POST',f'finance/subledger-openings/payments/{row["id"]}/reverse',{'reason':'重新更正回单'},201)
    assert new['id']!=draft['id'] and new['document_no']!=draft['document_no']
    new=execute_subledger_payment(client,None,new)
    assert new['amount']=='-10.00' and new['reverses_id']==row['id']
    assert query(subledger)['rows'][0]['outstanding_amount']=='100.00'
    assert next(r for r in client.get(BASE+'/payments').json() if r['id']==row['id'])==original
    ordinary=payment(subledger,line,reference='CANCEL-REF')
    execute(client,ordinary,'cancel')
    replacement=payment(subledger,line,reference='CANCEL-REF')
    assert ordinary['document_no']!=replacement['document_no']


def test_changed_complete_auxiliary_and_period_closed_after_approval_block_execution(subledger,monkeypatch):
    client=subledger[0];opening=confirmed(subledger);row=payment(subledger,opening['lines'][0])
    approve_document(client,None,'SubledgerPayment',row['id'],reason='核对资金')
    with orm_session(write=True) as db:
        db.get(SubledgerOpeningLine,row['opening_line_id']).document_reference='篡改原历史单'
    assert not state(client,row)['content_matches']
    execute(client,row,expected=409)
    with orm_session(write=True) as db:
        db.get(SubledgerOpeningLine,row['opening_line_id']).document_reference='OLD-A'
    from app.finance import period_closing
    monkeypatch.setattr(period_closing,'utc_today',lambda:'2027-01-01')
    assert client.post('/api/v1/finance/accounting-periods/1/close',json={'version':1,'reason':'资金仍为草稿，期末核对'}).status_code==200
    execute(client,row,expected=409)
    assert query(subledger)['rows'][0]['outstanding_amount']=='100.00'


def test_record_permission_cannot_submit_or_execute_reverse(subledger):
    client,api,*_=subledger;opening=confirmed(subledger)
    row=execute_subledger_payment(client,None,payment(subledger,opening['lines'][0]))
    reverse=api('POST',f'finance/subledger-openings/payments/{row["id"]}/reverse',{'reason':'更正资金'},201)
    api('POST','roles',{'code':'sub_fund_writer','label':'仅登记资金','permissions':['subledger_opening.view','finance.record']},201)
    api('POST','users',{'username':'fund_writer','password':'writer-pass-123','roles':['sub_fund_writer']},201)
    headers={'Authorization':'Bearer '+api('POST','auth/login',{'username':'fund_writer','password':'writer-pass-123'})['token']}
    assert not client.get(f'{PATH}/{reverse["id"]}',headers=headers).json()['can_submit']
    act(client,reverse,'submit',0,headers,expected=403)
    approve_document(client,None,'SubledgerPayment',reverse['id'],reason='独立反向核对')
    assert client.post(f'{BASE}/payments/{reverse["id"]}/post',headers=headers,json={'version':1,'reason':'绕过冲销权限'}).status_code==403
    assert query(subledger)['rows'][0]['outstanding_amount']=='90.00'


def test_migration_keeps_existing_money_auxiliary_and_economic_fingerprint(subledger):
    client=subledger[0];opening=confirmed(subledger)
    row=execute_subledger_payment(client,None,payment(subledger,opening['lines'][0]))
    with orm_session() as db:
        original=business_sources(db)[f'subledger_payment:{row["id"]}']['fingerprint']
    # 独立测试库回到上一版经济字段，验证升级不重算或改写来源固定指纹。
    with connection() as db:
        db.execute('DROP INDEX subledger_payments_reference')
        db.execute('DROP INDEX subledger_payments_active_reversal')
        for name in ('status','version','executed_by','executed_at','cancelled_by','cancelled_at','cancellation_reason'):
            db.execute(f'ALTER TABLE subledger_payments DROP COLUMN {name}')
        before=tuple(db.execute('SELECT * FROM subledger_payments WHERE id=?',(row['id'],)).fetchone())
        db.execute('PRAGMA user_version=90')
    migrate();migrate()
    with connection() as db:
        after=db.execute('SELECT * FROM subledger_payments WHERE id=?',(row['id'],)).fetchone()
        assert tuple(after)[:len(before)]==before and after['status']=='executed'
        assert after['executed_at']==after['created_at'] and db.execute('PRAGMA foreign_key_check').fetchall()==[]
    with orm_session() as db:
        assert business_sources(db)[f'subledger_payment:{row["id"]}']['fingerprint']==original


def test_legacy_funds_get_execution_facts_without_fabricated_approval(monkeypatch,tmp_path):
    import sqlite3
    path=tmp_path/'legacy-subpay-90.db';monkeypatch.setenv('NEXORA_DB_PATH',str(path))
    with sqlite3.connect(path) as db:
        # 最小上一版结构保留真实外键与两笔原/反向资金，升级不能补造审批事件。
        db.executescript('''CREATE TABLE users(id INTEGER PRIMARY KEY); INSERT INTO users VALUES(1);
            CREATE TABLE subledger_opening_lines(id INTEGER PRIMARY KEY); INSERT INTO subledger_opening_lines VALUES(1);
            CREATE TABLE subledger_payments(id INTEGER PRIMARY KEY,opening_line_id INTEGER NOT NULL REFERENCES subledger_opening_lines(id),
                action TEXT NOT NULL,amount TEXT NOT NULL,reference TEXT NOT NULL,note TEXT NOT NULL,
                reverses_id INTEGER UNIQUE REFERENCES subledger_payments(id),created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL,document_no TEXT UNIQUE,UNIQUE(opening_line_id,action,reference));
            INSERT INTO subledger_payments VALUES(1,1,'settlement','7.50','BANK','原回单',NULL,1,'2026-01-02 03:00:00','SLP-20260102-000001');
            INSERT INTO subledger_payments VALUES(2,1,'reversal','-7.50','REV','更正',1,1,'2026-01-03 03:00:00','SLP-20260103-000001');
            PRAGMA user_version=90;''')
        before=db.execute('SELECT * FROM subledger_payments ORDER BY id').fetchall()
    migrate();migrate()
    with sqlite3.connect(path) as db:
        db.row_factory=sqlite3.Row;after=db.execute('SELECT * FROM subledger_payments ORDER BY id').fetchall()
        assert [tuple(row)[:len(before[0])] for row in after]==before
        assert all(row['status']=='executed' and row['executed_by']==1 and row['executed_at']==row['created_at'] for row in after)
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='document_approval_events'").fetchone() is None
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
