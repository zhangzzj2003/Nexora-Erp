"""订单资金草稿、最新余额执行、反向独立审批及旧资金迁移保护。"""

from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session
from app.core.database import connection, migrate
from app.core.models import DocumentApprovalEvent, PaymentRecord
from app.core.orm import orm_session
from approval_test_helpers import approve_document
from test_business_orm import erp, receipt

BASE='/api/v1/finance/payment-records'
APPROVAL='/api/v1/system/document-approvals/PaymentRecord'


@pytest.fixture
def funds(erp):
    client,request,_,customer,materials,*_=erp
    inbound=receipt(erp)
    request('POST',f'receipts/{inbound["id"]}/post')
    order=request('POST','sales-orders',{'customer_id':customer,'lines':[{'material_id':materials[0],'quantity':'2','unit_price':'10'}]},201)
    approve_document(client,None,'SalesOrder',order['id'])
    request('POST',f'sales-orders/{order["id"]}/confirm')
    shipment=request('POST','shipments',{'sales_order_id':order['id'],'warehouse_id':1,'lines':[{'material_id':materials[0],'quantity':'2'}]},201)
    approve_document(client,None,'Shipment',shipment['id'])
    request('POST',f'shipments/{shipment["id"]}/post')
    return client,dict(kind='receivable',order_id=order['id'],action='settlement',amount='15.00',reference='BANK-1',note='银行依据')


def new(funds,**extra):
    r=funds[0].post(BASE,json={**funds[1],**extra});assert r.status_code==201,r.text
    return r.json()


def execute(client,row,expected=200):
    r=client.post(f'{BASE}/{row["id"]}/post',json={'version':row['version'],'reason':'独立批准后核对执行'})
    assert r.status_code==expected,r.text
    return r.json() if expected != 500 else r.text


def balance(client):
    return next(r['outstanding_amount'] for r in client.get('/api/v1/finance/accounts').json() if r['kind']=='receivable')


def test_draft_and_approval_do_not_change_balance_sources_or_bank(funds):
    client,_=funds;row=new(funds)
    assert row['status']=='draft' and row['executed_at'] is None and balance(client)=='20.00'
    assert not any(r['source_id']==row['id'] and r['source_type']=='payment_record' for r in client.get('/api/v1/finance/business-journals').json())
    assert not any(r['source_id']==row['id'] and r['source_type']=='order_payment' for r in client.get('/api/v1/finance/bank-reconciliation/overview').json()['sources'])
    execute(client,row,409)
    approve_document(client,None,'PaymentRecord',row['id'],reason='核对银行依据')
    assert balance(client)=='20.00'
    posted=execute(client,row)
    assert posted['status']=='executed' and posted['version']==2 and balance(client)=='5.00'
    assert posted['created_at']==row['created_at'] and posted['amount']==row['amount']
    state=client.get(f'{APPROVAL}/{row["id"]}').json()
    assert state['content_matches'] and state['events'][-1]['reason']=='独立批准后核对执行'
    execute(client,row,409)


def test_concurrent_approved_drafts_recheck_current_balance(funds):
    client,_=funds;rows=[new(funds,reference=f'PARALLEL-{i}') for i in range(2)]
    for row in rows:approve_document(client,None,'PaymentRecord',row['id'],reason='核对可收余额')
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes=list(pool.map(lambda r:client.post(f'{BASE}/{r["id"]}/post',json={'version':1,'reason':'并发执行'}).status_code,rows))
    assert sorted(codes)==[200,409] and balance(client)=='5.00'
    assert sum(r['status']=='executed' for r in client.get(BASE).json())==1


def test_reversal_is_new_draft_cancel_releases_reservation_without_money_change(funds):
    client,_=funds;row=new(funds);approve_document(client,None,'PaymentRecord',row['id'],reason='收款核对');original=execute(client,row)
    reverse=client.post(f'{BASE}/{row["id"]}/reverse',json={'reason':'重复收款'}).json()
    assert reverse['status']=='draft' and reverse['amount']=='-15.00' and balance(client)=='5.00'
    assert client.post(f'{BASE}/{row["id"]}/reverse',json={'reason':'重复冲销'}).status_code==409
    assert client.post(f'{BASE}/{reverse["id"]}/cancel',json={'version':1,'reason':'撤销错误反向草稿'}).status_code==200
    later=client.post(f'{BASE}/{row["id"]}/reverse',json={'reason':'另行核对更正'}).json()
    assert later['id']!=reverse['id']
    approve_document(client,None,'PaymentRecord',later['id'],reason='核对原资金更正')
    execute(client,later)
    assert balance(client)=='20.00'
    assert next(r for r in client.get(BASE).json() if r['id']==original['id'])==original


def test_execution_event_failure_rolls_back_status_money_and_time(funds):
    client,_=funds;row=new(funds);approve_document(client,None,'PaymentRecord',row['id'],reason='收款核对')
    def fail(session,_):
        if any(isinstance(r,DocumentApprovalEvent) and r.action=='execute' for r in session.new):raise RuntimeError('模拟执行事件写入失败')
    event.listen(Session,'before_flush',fail)
    try:execute(client,row,500)
    finally:event.remove(Session,'before_flush',fail)
    stored=next(r for r in client.get(BASE).json() if r['id']==row['id'])
    assert stored['status']=='draft' and stored['executed_at'] is None and balance(client)=='20.00'
    assert stored['approval']['status']=='approved'
    execute(client,row)


def test_fixed_amount_tamper_cannot_execute(funds):
    client,_=funds;row=new(funds);approve_document(client,None,'PaymentRecord',row['id'],reason='收款核对')
    with orm_session(write=True) as db:db.get(PaymentRecord,row['id']).amount='1.00'
    execute(client,row,409)
    assert balance(client)=='20.00'


def test_multistep_self_review_and_pending_cancel_require_withdraw(funds):
    client,_=funds
    steps=[{'name':name,'role':None} for name in ('审核','核准','批准')]
    assert client.put('/api/v1/system/document-approvals/PaymentRecord',json={'version':1,'steps':steps}).status_code==200
    row=new(funds)
    sent=client.post(f'{APPROVAL}/{row["id"]}/submit',json={'version':0,'reason':'核对银行回单'}).json()
    assert sent['steps']==steps
    assert client.get((f"{APPROVAL}/{row['id']}/approve").removesuffix('/approve'), headers=None, params={'intent': 'execute'}).json()['can_review']
    assert client.post(f'{BASE}/{row["id"]}/cancel',json={'version':1,'reason':'直接取消'}).status_code==409
    assert client.post(f'{APPROVAL}/{row["id"]}/withdraw',json={'version':1}).status_code==200
    assert client.post(f'{BASE}/{row["id"]}/cancel',json={'version':1,'reason':'重录银行依据'}).status_code==200
    # 取消草稿原单保留，参考号可用于更正草稿；无任何资金影响。
    replacement=new(funds)
    assert replacement['id']!=row['id'] and balance(client)=='20.00'


def test_period_closed_after_approval_blocks_execution(funds):
    from datetime import datetime,timezone
    from app.core.models import AccountingPeriod
    client,_=funds;row=new(funds)
    approve_document(client,None,'PaymentRecord',row['id'],reason='核对可收款')
    today=datetime.now(timezone.utc).date().isoformat()
    with orm_session(write=True) as db:
        db.add(AccountingPeriod(code='LOCKED',name='隔离锁期',start_date=today,end_date=today,status='closed',version=1,created_by=1))
    execute(client,row,409)
    assert balance(client)=='20.00'


def test_reverse_submit_and_execution_require_reverse_permission(funds):
    client,_=funds;row=new(funds);approve_document(client,None,'PaymentRecord',row['id'],reason='核对收款');execute(client,row)
    reverse=client.post(f'{BASE}/{row["id"]}/reverse',json={'reason':'原资金更正'}).json()
    assert client.post('/api/v1/roles',json={'code':'fund_writer','label':'仅建资金','permissions':['finance.view','finance.record']}).status_code==201
    assert client.post('/api/v1/users',json={'username':'limited_writer','password':'approval-test-pass-123','roles':['fund_writer']}).status_code==201
    token=client.post('/api/v1/auth/login',json={'username':'limited_writer','password':'approval-test-pass-123'}).json()['token']
    headers={'Authorization':'Bearer '+token}
    assert not client.get(f'{APPROVAL}/{reverse["id"]}',headers=headers).json()['can_submit']
    assert client.post(f'{APPROVAL}/{reverse["id"]}/submit',headers=headers,json={'version':0,'reason':'越权冲销'}).status_code==403
    approve_document(client,None,'PaymentRecord',reverse['id'],reason='独立核对原资金')
    assert client.post(f'{BASE}/{reverse["id"]}/post',headers=headers,json={'version':1,'reason':'越权执行'}).status_code==403
    assert balance(client)=='5.00'


def test_legacy_source_fingerprint_survives_89_upgrade(funds):
    from app.finance.business_sources import business_sources
    client,_=funds;row=new(funds)
    approve_document(client,None,'PaymentRecord',row['id'],reason='原资金核对');execute(client,row)
    with orm_session() as db:
        before=business_sources(db)[f'payment_record:{row["id"]}']['fingerprint']
    with connection() as db:
        # 模拟旧资金结构，升级只增审批状态，不改旧经济内容和编号。
        db.execute('DROP INDEX payment_records_active_reversal');db.execute('DROP INDEX payment_records_reference')
        for field in ('status','version','executed_by','executed_at','cancelled_by','cancelled_at','cancellation_reason'):
            db.execute(f'ALTER TABLE payment_records DROP COLUMN {field}')
        db.execute("CREATE UNIQUE INDEX payment_records_reference ON payment_records(kind,order_id,action,reference) WHERE action <> 'reversal'")
        db.execute('PRAGMA user_version=89')
    migrate()
    with orm_session() as db:
        assert business_sources(db)[f'payment_record:{row["id"]}']['fingerprint']==before


def test_89_migration_keeps_original_money_identity_and_no_fake_approval(monkeypatch,tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH',str(tmp_path/'legacy-payment.db'))
    with connection() as db:
        db.executescript("""PRAGMA user_version=89;CREATE TABLE users(id INTEGER PRIMARY KEY);
        INSERT INTO users VALUES(1);
        CREATE TABLE payment_records(id INTEGER PRIMARY KEY,kind TEXT,order_id INTEGER,action TEXT,amount TEXT,
        reference TEXT,note TEXT,reverses_id INTEGER UNIQUE REFERENCES payment_records(id),created_by INTEGER REFERENCES users(id),
        created_at TEXT,document_no TEXT UNIQUE);
        INSERT INTO payment_records VALUES(1,'receivable',9,'settlement','10.00','OLD','原凭据',NULL,1,'2026-01-03 00:00:00','PAY-20260103-000001');
        INSERT INTO payment_records VALUES(2,'receivable',9,'reversal','-10.00','REV','原冲销',1,1,'2026-01-04 00:00:00','PAY-20260104-000001');""")
        before=[dict(r) for r in db.execute('SELECT * FROM payment_records ORDER BY id')]
    migrate();migrate()
    with connection() as db:
        after=[dict(r) for r in db.execute('SELECT * FROM payment_records ORDER BY id')]
        assert [{key:r[key] for key in before[0]} for r in after]==before
        assert all(r['status']=='executed' and r['executed_at']==r['created_at'] and r['executed_by']==1 for r in after)
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='document_approval_events'").fetchone()
        assert not db.execute('PRAGMA foreign_key_check').fetchone()
