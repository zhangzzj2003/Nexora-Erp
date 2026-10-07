"""核销草稿隔离、独立审核与实时余额执行；反向更正保留原经济事实。"""

from concurrent.futures import ThreadPoolExecutor
import sqlite3
import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session
from app.core.database import connection, migrate
from app.core.models import OrderSettlementTransfer, DocumentApprovalEvent, AccountingPeriod
from app.core.orm import orm_session
from approval_test_helpers import approve_document, execute_payment
from test_business_orm import erp
from test_payment_document_approval import funds
from test_journal_document_approval import reviewer

BASE='/api/v1/finance/order-settlements'
APPROVAL='/api/v1/system/document-approvals/OrderSettlementTransfer'


@pytest.fixture
def offsets(funds):
    client,payload=funds
    source=payload['order_id']
    response=client.post('/api/v1/finance/payment-records',json={**payload,'amount':'20'})
    assert response.status_code==201,response.text
    execute_payment(client,None,response.json())
    shipment=next(s for s in client.get('/api/v1/shipments').json() if s['sales_order_id']==source)
    returned=client.post('/api/v1/sales-returns',json={'shipment_id':shipment['id'],'warehouse_id':1,'reason':'退回一件',
        'lines':[{'shipment_line_id':shipment['lines'][0]['id'],'quantity':'1'}]})
    assert returned.status_code==201,returned.text
    approve_document(client,None,'SalesReturn',returned.json()['id'])
    assert client.post(f'/api/v1/sales-returns/{returned.json()["id"]}/post').status_code==200
    original=next(s for s in client.get('/api/v1/sales-orders').json() if s['id']==source)
    target=client.post('/api/v1/sales-orders',json={'customer_id':original['customer_id'],
        'lines':[{'material_id':original['lines'][0]['material_id'],'quantity':'2','unit_price':'10'}]}).json()
    approve_document(client,None,'SalesOrder',target['id'])
    assert client.post(f'/api/v1/sales-orders/{target["id"]}/confirm').status_code==200
    shipment=client.post('/api/v1/shipments',json={'sales_order_id':target['id'],'warehouse_id':1,
        'lines':[{'material_id':target['lines'][0]['material_id'],'quantity':'2'}]}).json()
    approve_document(client,None,'Shipment',shipment['id'])
    assert client.post(f'/api/v1/shipments/{shipment["id"]}/post').status_code==200
    return client,dict(kind='receivable',from_order_id=source,to_order_id=target['id'],amount='6.00',reference='OFFSET',reason='同客户退货抵扣')


def new(offsets,**extra):
    r=offsets[0].post(BASE,json={**offsets[1],**extra});assert r.status_code==201,r.text
    return r.json()


def balance(offsets):
    rows={r['order_id']:r for r in offsets[0].get('/api/v1/finance/accounts').json() if r['kind']=='receivable'}
    return tuple(rows[offsets[1][key]]['outstanding_amount'] for key in ('from_order_id','to_order_id'))


def execute(client,row,action='post',expected=200):
    r=client.post(f'{BASE}/{row["id"]}/{action}',json={'version':row['version'],'reason':'执行核销依据'})
    assert r.status_code==expected,r.text
    return r.json() if expected!=500 else r.text


def test_three_steps_fixed_orders_and_no_balance_until_execution(offsets):
    client,_=offsets;row=new(offsets)
    r=client.put('/api/v1/system/document-approvals/OrderSettlementTransfer',json={'version':1,
        'steps':[{'name':n,'role':None} for n in ('审核','核准','批准')]});assert r.status_code==200,r.text
    assert row['status']=='draft' and balance(offsets)==('-10.00','20.00')
    overview=client.get('/api/v1/finance/overview').json()['transfers']
    assert overview[0]['document_no']==row['document_no'] and row['document_no'].startswith('OSL-')
    execute(client,row,expected=409)
    response=client.post(f'{APPROVAL}/{row["id"]}/submit',json={'version':0,'reason':'核对双方订单'})
    assert response.status_code==200,response.text
    state=response.json()
    assert client.post(f'{APPROVAL}/{row["id"]}/approve',json={'version':state['version'],'reason':'本人审核'}).status_code==403
    execute(client,row,'cancel',409)
    assert any(v['label']=='来源订单' and v['value'].startswith('SO-') for v in state['summary'])
    for i in range(3):
        headers=reviewer(client,f'offset_reviewer_{i}')
        response=client.post(f'{APPROVAL}/{row["id"]}/approve',headers=headers,json={'version':state['version'],'reason':'核对单据'})
        assert response.status_code==200,response.text;state=response.json()
        if i<2:assert client.post(f'{APPROVAL}/{row["id"]}/approve',headers=headers,json={'version':state['version'],'reason':'再次审核'}).status_code==403
    assert state['status']=='approved' and balance(offsets)==('-10.00','20.00')
    posted=execute(client,row)
    assert posted['version']==2 and posted['executed_by'] and posted['approval']['status']=='executed'
    assert balance(offsets)==('-4.00','14.00')
    assert client.get(f'{APPROVAL}/{row["id"]}').json()['events'][-1]['reason']=='执行核销依据'
    execute(client,row,expected=409)
    # 订单内抵扣不是第二笔收付款，不产生银行来源或新资金记录。
    assert len(client.get('/api/v1/finance/payment-records').json())==1
    assert not any(s['source_type']=='order_settlement' for s in client.get('/api/v1/finance/bank-reconciliation/overview').json()['sources'])


def test_concurrent_approved_drafts_recheck_credit(offsets):
    client,_=offsets;rows=[new(offsets,reference=f'RACE-{i}') for i in range(2)]
    for r in rows:approve_document(client,None,'OrderSettlementTransfer',r['id'],reason='核对余额')
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes=list(pool.map(lambda r:client.post(f'{BASE}/{r["id"]}/post',json={'version':1,'reason':'并行核销'}).status_code,rows))
    assert sorted(codes)==[200,409] and balance(offsets)==('-4.00','14.00')
    assert sum(r['status']=='executed' for r in client.get(BASE).json())==1


def test_event_failure_rolls_back_balance_and_execution(offsets):
    client,_=offsets;row=new(offsets);approve_document(client,None,'OrderSettlementTransfer',row['id'],reason='核对依据')
    def fail(session,_):
        if any(isinstance(r,DocumentApprovalEvent) and r.action=='execute' for r in session.new):raise RuntimeError('执行审计失败')
    event.listen(Session,'before_flush',fail)
    try:execute(client,row,expected=500)
    finally:event.remove(Session,'before_flush',fail)
    current=client.get(BASE).json()[0]
    assert current['status']=='draft' and current['executed_at'] is None and current['version']==1
    assert current['approval']['status']=='approved' and balance(offsets)==('-10.00','20.00')
    execute(client,row)


def test_cancel_releases_refs_and_reversal_reservation_without_reusing_numbers(offsets):
    client,_=offsets;draft=new(offsets);execute(client,draft,'cancel')
    row=new(offsets);assert row['document_no']!=draft['document_no']
    approve_document(client,None,'OrderSettlementTransfer',row['id'],reason='核对单据');original=execute(client,row)
    response=client.post(f'{BASE}/{row["id"]}/reverse',json={'reason':'重新核对关联'})
    assert response.status_code==201,response.text;reverse=response.json()
    assert balance(offsets)==('-4.00','14.00') and reverse['status']=='draft'
    execute(client,reverse,expected=409)
    execute(client,reverse,'cancel')
    later=client.post(f'{BASE}/{row["id"]}/reverse',json={'reason':'原关联录错'}).json()
    assert later['document_no']!=reverse['document_no'] and later['amount']=='-6.00'
    approve_document(client,None,'OrderSettlementTransfer',later['id'],reason='独立核对原核销')
    execute(client,later)
    assert balance(offsets)==('-10.00','20.00')
    assert next(r for r in client.get(BASE).json() if r['id']==row['id'])==original


def test_fixed_body_versions_forged_metadata_and_closed_period(offsets):
    client,_=offsets;row=new(offsets);approve_document(client,None,'OrderSettlementTransfer',row['id'],reason='核对依据')
    for change in ({'version':True},{'version':0},{'reason':' '},{'reason':'字'*201},{'approved_by':1}):
        assert client.post(f'{BASE}/{row["id"]}/post',json={'version':1,'reason':'依据',**change}).status_code==422
    assert client.post(BASE,json={**offsets[1],'reference':'FORGED','status':'executed'}).status_code==422
    with orm_session(write=True) as db:db.get(OrderSettlementTransfer,row['id']).amount='5.00'
    assert not client.get(f'{APPROVAL}/{row["id"]}').json()['content_matches'];execute(client,row,expected=409)
    with orm_session(write=True) as db:
        db.get(OrderSettlementTransfer,row['id']).amount='6.00'
        from datetime import datetime,timezone
        today=datetime.now(timezone.utc).date().isoformat()
        db.add(AccountingPeriod(code='LOCK',name='锁期',start_date=today,end_date=today,status='closed',version=1,created_by=1))
    execute(client,row,expected=409);assert balance(offsets)==('-10.00','20.00')


def test_record_permission_cannot_submit_or_execute_reverse(offsets):
    client,_=offsets;row=new(offsets);approve_document(client,None,'OrderSettlementTransfer',row['id'],reason='核对依据');execute(client,row)
    reverse=client.post(f'{BASE}/{row["id"]}/reverse',json={'reason':'错单更正'}).json()
    r=client.post('/api/v1/roles',json={'code':'offset_writer','label':'仅登记','permissions':['finance.view','finance.record']});assert r.status_code==201,r.text
    assert client.post('/api/v1/users',json={'username':'offset_writer','password':'writer-pass-123','roles':['offset_writer']}).status_code==201
    headers={'Authorization':'Bearer '+client.post('/api/v1/auth/login',json={'username':'offset_writer','password':'writer-pass-123'}).json()['token']}
    assert client.post(f'{APPROVAL}/{reverse["id"]}/submit',headers=headers,json={'version':0,'reason':'越权'}).status_code==403
    approve_document(client,None,'OrderSettlementTransfer',reverse['id'],reason='核对更正')
    assert client.post(f'{BASE}/{reverse["id"]}/post',headers=headers,json={'version':1,'reason':'越权'}).status_code==403
    assert balance(offsets)==('-4.00','14.00')


def test_legacy_migration_preserves_offsets_without_fabricated_approval(monkeypatch,tmp_path):
    path=tmp_path/'legacy-offset-91.db';monkeypatch.setenv('NEXORA_DB_PATH',str(path))
    with sqlite3.connect(path) as db:
        # 原库含真实反向外键及参考号索引，迁移重复运行也必须保持原事实。
        db.executescript('''CREATE TABLE users(id INTEGER PRIMARY KEY);INSERT INTO users VALUES(1);
        CREATE TABLE order_settlement_transfers(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,party_id INTEGER NOT NULL,
          from_order_id INTEGER NOT NULL,to_order_id INTEGER NOT NULL,amount TEXT NOT NULL,reference TEXT NOT NULL,
          reason TEXT NOT NULL,reverses_id INTEGER UNIQUE REFERENCES order_settlement_transfers(id),
          created_by INTEGER NOT NULL REFERENCES users(id),created_at TEXT NOT NULL,document_no TEXT UNIQUE);
        CREATE UNIQUE INDEX order_settlement_reference ON order_settlement_transfers(kind,from_order_id,to_order_id,reference) WHERE reverses_id IS NULL;
        INSERT INTO order_settlement_transfers VALUES(1,'receivable',1,4,5,'6.00','REF','抵扣',NULL,1,'2026-01-01','OSL-20260101-000001');
        INSERT INTO order_settlement_transfers VALUES(2,'receivable',1,4,5,'-6.00','REV','更正',1,1,'2026-01-02','OSL-20260102-000001');
        PRAGMA user_version=91;''')
        before=db.execute('SELECT * FROM order_settlement_transfers ORDER BY id').fetchall()
    migrate();migrate()
    with connection() as db:
        after=db.execute('SELECT * FROM order_settlement_transfers ORDER BY id').fetchall()
        assert [tuple(r)[:len(before[0])] for r in after]==before
        assert all(r['status']=='executed' and r['executed_at']==r['created_at'] and r['executed_by']==1 for r in after)
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='document_approval_events'").fetchone() is None
