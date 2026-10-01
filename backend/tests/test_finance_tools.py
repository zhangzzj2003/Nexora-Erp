"""税价、往来期初、银行方向与辅助核算真实行为回归；末阶段统一运行。"""
from test_ledger_foundation import ledger, ACCOUNT, BASE
from app.core.orm import orm_session
from app.core.models import PaymentRecord, JournalAuxiliary


def call(client,action,payload=None):
    return client.post(BASE+'/tools',json={'action':action,'payload':payload or {}})


def rows(client,result):
    response=client.post('/api/v1/tables/query',json={'dataset':'snapshot','snapshot_id':result['snapshot_id'],'page':1,'page_size':100})
    assert response.status_code==200,response.text
    return response.json()['items']


def test_tax_discount_and_old_default(ledger):
    client=ledger
    customer=client.post('/api/v1/customers',json={'name':'财务客户'}).json()['id']
    material=client.post('/api/v1/materials',json={'sku':'TAX','name':'税价物料','unit':'件'}).json()['id']
    payload={'customer_id':customer,'lines':[{'material_id':material,'quantity':'2','unit_price':'100','tax_rate':'13','discount_rate':'10','includes_tax':False}]}
    result=client.post('/api/v1/sales-orders',json=payload)
    assert result.status_code==201,result.text
    assert result.json()['total_amount']=='203.40'
    assert result.json()['lines'][0]['quoted_price']=='100'
    assert result.json()['lines'][0]['unit_price']=='101.7000'
    payload['lines'][0]['tax_rate']='101'
    assert client.post('/api/v1/sales-orders',json=payload).status_code==422


def test_opening_confirmation_settlement_duplicates_and_audit(ledger):
    account=ledger.post(BASE+'/ledger-accounts',json=ACCOUNT).json()['id']
    customer=ledger.post('/api/v1/customers',json={'name':'期初客户'}).json()['id']
    value={'kind':'receivable','party_id':customer,'effective_date':'2026-01-01','ledger_account_id':account,'amount':'100.00','reference':'OPEN-1','reason':'历史余额'}
    result=call(ledger,'create_opening',value);assert result.status_code==200,result.text
    identifier=rows(ledger,result.json())[0]['id']
    assert call(ledger,'create_opening',value).status_code==409
    payment={'id':identifier,'reason':'收取期初','amount':'20.00','reference':'OP-PAY-1'}
    assert call(ledger,'settle_opening',payment).status_code==409
    assert call(ledger,'confirm_opening',{'id':identifier,'reason':'核对通过'}).status_code==200
    assert call(ledger,'settle_opening',{**payment,'amount':'101.00'}).status_code==409
    paid=call(ledger,'settle_opening',payment);assert paid.status_code==200,paid.text
    assert rows(ledger,paid.json())[0]['outstanding_amount']=='80.00'
    assert call(ledger,'cancel_opening',{'id':identifier,'reason':'取消'}).status_code==409
    audit=rows(ledger,call(ledger,'history').json());assert len(audit)==3
    report=rows(ledger,call(ledger,'reconcile').json());assert report[0]['difference']=='100.00'


def test_bank_import_is_atomic_and_amount_direction_is_checked(ledger):
    customer=ledger.post('/api/v1/customers',json={'name':'银行客户'}).json()['id']
    material=ledger.post('/api/v1/materials',json={'sku':'BANK','name':'银行物料','unit':'件'}).json()['id']
    order=ledger.post('/api/v1/sales-orders',json={'customer_id':customer,'lines':[{'material_id':material,'quantity':'1','unit_price':'50'}]}).json()['id']
    with orm_session(write=True) as db:
        payment=PaymentRecord(kind='receivable',order_id=order,action='settlement',amount='50.00',reference='PAY-BANK',note='',created_by=1)
        db.add(payment);db.flush();pid=payment.id
    row={'bank_account':'BANK-A','statement_date':'2026-01-01','amount':'50.00','reference':'BANK-1'}
    assert call(ledger,'import_bank',{'rows':[row,row],'reason':'导入'}).status_code==409
    assert rows(ledger,call(ledger,'banks').json())==[]
    assert call(ledger,'import_bank',{'rows':[row],'reason':'导入'}).status_code==200
    bid=rows(ledger,call(ledger,'banks').json())[0]['id']
    match={'id':bid,'payment_id':pid,'reason':'金额一致'}
    assert call(ledger,'match_bank',match).status_code==200
    assert call(ledger,'match_bank',match).status_code==409
    assert ledger.post(BASE+f'/payment-records/{pid}/reverse',json={'reason':'冲销'}).status_code==409
    assert call(ledger,'unmatch_bank',{'id':bid,'reason':'重新核对'}).status_code==200
    assert rows(ledger,call(ledger,'banks').json())[0]['payment_id'] is None


# 损益结转发生前后管理报表必须保持相同经营利润，并把权益核对平衡。
from test_profit_transfers import profit, journals, post_record, generate, post


def test_statements_keep_profit_after_transfer_and_balance_equity(profit):
    from decimal import Decimal
    client,_,_=profit
    post_record(profit,'income',Decimal('100.00'),'INCOME')
    post_record(profit,'expense',Decimal('-30.00'),'EXPENSE')
    scope={'from_date':'2026-01-01','to_date':'2026-01-31'}
    before=call(client,'statements',scope);assert before.status_code==200,before.text
    assert before.json()['totals']['net_profit']=='70.00'
    assert before.json()['totals']['balance_difference']=='0.00'
    transfer=generate(client);post(profit,transfer)
    after=call(client,'statements',scope);assert after.status_code==200,after.text
    assert after.json()['totals']['net_profit']=='70.00'
    assert after.json()['totals']['balance_difference']=='0.00'
