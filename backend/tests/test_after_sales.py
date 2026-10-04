"""售后独立审核、数量占用、客户物品保管和收费来源的真实跨模块约束。"""

import os
import sqlite3
from contextlib import contextmanager
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.main import app
from app.core.database import migrate
from app.core.models import Base, AfterSalesChange, AfterSalesCase, AfterSalesCustody, AfterSalesLabor, Customer, RolePermission
from app.core.orm import orm_session
from app.finance.business_sources import business_sources

ROOT='after-sales/cases'


@pytest.fixture
def erp(monkeypatch,tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH',str(tmp_path/'after-sales.db'))
    with TestClient(app,client=('127.0.0.1',12000),raise_server_exceptions=False) as client:
        def api(method,path,payload=None,actor='admin',status=200):
            response=client.request(method,'/api/v1/'+path,json=payload,headers=actors.get(actor,{}))
            assert response.status_code==status,response.text
            return response.json() if response.content and status != 500 else None
        actors={}
        api('POST','setup/admin',{'username':'admin','password':'secure-pass-123'},status=201)
        def login(name):
            response=client.post('/api/v1/auth/login',json={'username':name,'password':'secure-pass-123'})
            return {'Authorization':'Bearer '+response.json()['token']}
        actors['admin']=login('admin')
        for name,role in (('reviewer','finance'),('seller','seller'),('warehouse','warehouse'),('viewer','viewer')):
            api('POST','users',{'username':name,'password':'secure-pass-123','roles':[role]},status=201)
            actors[name]=login(name)
        customer=api('POST','customers',{'name':'售后客户'},status=201)['id']
        api('PUT',f'customers/{customer}/owner',{'owner_id':3,'version':1,'reason':'交由销售员办理'})
        supplier=api('POST','suppliers',{'name':'售后供货'},status=201)['id']
        material=api('POST','materials',{'sku':'AFTER','name':'售后商品','unit':'件'},status=201)['id']
        part=api('POST','materials',{'sku':'PART','name':'维修备件','unit':'件'},status=201)['id']
        purchase=api('POST','purchase-orders',{'supplier_id':supplier,'lines':[
            {'material_id':m,'quantity':'20','unit_price':'1'} for m in (material,part)]},status=201)
        api('POST',f'purchase-orders/{purchase["id"]}/confirm')
        receipt=api('POST','receipts',{'supplier_id':supplier,'purchase_order_id':purchase['id'],
            'lines':[{'material_id':m,'quantity':'20'} for m in (material,part)]},status=201)
        api('POST',f'receipts/{receipt["id"]}/post')
        order=api('POST','sales-orders',{'customer_id':customer,'lines':[{'material_id':material,'quantity':'10','unit_price':'10'}]},status=201)
        api('POST',f'sales-orders/{order["id"]}/confirm')
        shipment=api('POST','shipments',{'sales_order_id':order['id'],'warehouse_id':1,'lines':[{'material_id':material,'quantity':'10'}]},status=201)
        shipment=api('POST',f'shipments/{shipment["id"]}/post')
        yield client,api,actors,shipment,material,part,order


def payload(erp,kind='repair',reference='AFTER-1',quantity='2',**extra):
    _,_,_,shipment,material,_,_=erp
    result=dict(shipment_line_id=shipment['lines'][0]['id'],reference=reference,kind=kind,quantity=quantity,
        complaint='产品异常待处理',solution='按已确认方案办理',charge_mode='free' if kind=='repair' else 'none',
        fee_amount='0',customer_acceptance='客户书面同意方案 A-001',warehouse_id=None if kind=='repair' else 1,
        replacement_material_id=material if kind=='exchange' else None,replacement_quantity=quantity if kind=='exchange' else None,
        replacement_unit_price='12' if kind=='exchange' else None,parts=[],reason='客户申请登记')
    return {**result,**extra}


def action(api,row,operation,actor='admin',status=200,**extra):
    return api('POST',f'{ROOT}/{row["id"]}/{operation}',{'version':row['version'],'reason':'核对售后依据',
        'evidence':'交接检验记录 A-002',**extra},actor=actor,status=status)


def approved(erp,data):
    api=erp[1]
    row=api('POST',ROOT,data,status=201)
    row=action(api,row,'submit')
    return action(api,row,'approve',actor='reviewer')


def test_repair_labor_record_and_reversal_keep_evidence_without_financial_side_effects(erp):
    _,api,_,_,_,_,order=erp
    row=action(api,approved(erp,payload(erp,charge_mode='charge',fee_amount='5')),'receive')
    path=f'{ROOT}/{row["id"]}/labor'
    api('POST',path,{'version':row['version'],'hours':'1.234','reason':'维修',
        'evidence':'工单记录'},status=422)
    api('POST',path,{'version':row['version'],'hours':1.25,'reason':'维修',
        'evidence':'工单记录'},status=422)
    api('POST',path,{'version':row['version'],'hours':'1.25','reason':'维修',
        'evidence':'工单记录'},actor='seller',status=403)
    row=api('POST',path,{'version':row['version'],'hours':'1.25','reason':'完成拆修',
        'evidence':'维修工单 R-1'},actor='warehouse',status=201)
    original=row['labor'][0]
    assert row['labor_hours']=='1.25' and original['hours']=='1.25'
    assert original['created_by_name']=='warehouse' and row['changes'][-1]['action']=='labor_record'
    api('POST',path,{'version':row['version']-1,'hours':'2','reason':'并发旧版本',
        'evidence':'工单 R-2'},status=409)
    row=api('POST',path,{'version':row['version'],'hours':'0.75','reason':'检验返工',
        'evidence':'维修工单 R-2'},status=201)
    assert row['labor_hours']=='2.00'
    correction=f'{path}/{original["id"]}/reverse'
    row=api('POST',correction,{'version':row['version'],'reason':'原计时重复',
        'evidence':'复核记录 R-3'})
    assert row['labor_hours']=='0.75' and row['labor'][-1]['original_id']==original['id']
    assert row['labor'][0]['hours']=='1.25' and row['changes'][-1]['action']=='labor_reverse'
    api('POST',correction,{'version':row['version'],'reason':'重复更正',
        'evidence':'复核记录 R-3'},status=409)
    assert api('GET',f'{ROOT}/{row["id"]}')['labor_hours']=='0.75'
    account=next(item for item in api('GET','finance/accounts') if item['kind']=='receivable' and item['order_id']==order['id'])
    assert account['business_amount']=='100.00'
    with orm_session() as db:
        assert len(list(db.scalars(select(AfterSalesLabor).where(AfterSalesLabor.case_id==row['id']))))==3
    row=action(api,row,'inspect',inspection_result='pass')
    row=action(api,row,'close')
    api('POST',path,{'version':row['version'],'hours':'1','reason':'结案后补录',
        'evidence':'迟到记录'},status=409)
    assert row['labor_hours']=='0.75'


def test_labor_rejects_other_case_and_non_repair(erp):
    _,api,_,_,_,_,_=erp
    first=action(api,approved(erp,payload(erp)),'receive')
    second=action(api,approved(erp,payload(erp,reference='AFTER-2',quantity='1')),'receive')
    path=f'{ROOT}/{first["id"]}/labor'
    first=api('POST',path,{'version':first['version'],'hours':'1','reason':'维修',
        'evidence':'工单 R-1'},status=201)
    api('POST',f'{ROOT}/{second["id"]}/labor/{first["labor"][0]["id"]}/reverse',
        {'version':second['version'],'reason':'跨单更正','evidence':'复核'},status=404)
    returned=approved(erp,payload(erp,kind='return',reference='AFTER-3',quantity='1'))
    api('POST',f'{ROOT}/{returned["id"]}/labor',
        {'version':returned['version'],'hours':'1','reason':'非维修','evidence':'测试'},status=409)


def test_labor_audit_failure_rolls_back_record_and_version(erp,monkeypatch):
    _,api,_,_,_,_,_=erp
    row=action(api,approved(erp,payload(erp)),'receive')
    def failed_audit(*_args,**_kwargs):
        raise RuntimeError('模拟审计写入失败')
    monkeypatch.setattr('app.sales.after_sales_labor.audit',failed_audit)
    api('POST',f'{ROOT}/{row["id"]}/labor',{'version':row['version'],'hours':'2.50',
        'reason':'维修计时','evidence':'维修工单 R-4'},status=500)
    current=api('GET',f'{ROOT}/{row["id"]}')
    assert current['version']==row['version'] and current['labor']==[] and current['labor_hours']=='0.00'


def test_labor_scope_hides_case_before_reporting_stale_version(erp):
    _,api,_,_,_,_,_=erp
    row=action(api,approved(erp,payload(erp)),'receive')
    with orm_session(write=True) as db:
        db.add(RolePermission(role_code='seller',permission_code='after_sales.labor'))
        db.get(Customer,row['frozen_source']['customer_id']).owner_id=1
    api('POST',f'{ROOT}/{row["id"]}/labor',{'version':row['version']-1,'hours':'1.00',
        'reason':'旧版本','evidence':'工单'},actor='seller',status=404)
    assert api('GET',f'{ROOT}/{row["id"]}')['labor']==[]


def test_paid_repair_keeps_customer_goods_out_of_stock_and_reconciles_original_order(erp):
    _,api,_,shipment,material,_,order=erp
    row=approved(erp,payload(erp,charge_mode='charge',fee_amount='5.50'))
    stock=api('GET','stock'); movements=api('GET','movements')
    row=action(api,row,'receive')
    assert row['custody_quantity']=='2'
    assert api('GET','stock')==stock and api('GET','movements')==movements
    action(api,row,'close',status=409)
    row=action(api,row,'inspect',inspection_result='fail')
    assert row['status']=='received' and row['changes'][-1]['action']=='inspect_fail'
    row=action(api,row,'inspect',inspection_result='pass')
    row=action(api,row,'close')
    assert row['custody_quantity']=='0' and len(row['custody'])==2
    assert api('GET','stock')==stock and api('GET','movements')==movements
    account=next(item for item in api('GET','finance/accounts') if item['kind']=='receivable' and item['order_id']==order['id'])
    assert account['business_amount']=='105.50'
    with orm_session() as db:
        source=business_sources(db)[f'after_sales_repair:{row["id"]}']
        assert source['roles']=={'receivable':'5.50','repair_income':'-5.50'}
        assert source['blockers']==[] and source['movements']==[]
    api('POST','finance/payment-records',{'kind':'receivable','order_id':order['id'],'action':'settlement',
        'amount':'105.50','reference':'服务收款'},status=201)
    row=action(api,row,'reverse')
    account=next(item for item in api('GET','finance/accounts') if item['kind']=='receivable' and item['order_id']==order['id'])
    assert account['business_amount']=='100.00' and account['outstanding_amount']=='-5.50'
    assert len(row['custody'])==2 and row['custody_quantity']=='0'
    api('POST',f'shipments/{shipment["id"]}/reverse',{'reason':'来源更正'},status=201)


def test_repair_parts_use_company_outbound_and_require_effective_posting(erp):
    _,api,_,_,material,part,_=erp
    row=approved(erp,payload(erp,warehouse_id=1,parts=[{'material_id':part,'quantity':'1'}]))
    row=action(api,row,'receive')
    assert row['parts_status']=='draft'
    action(api,row,'inspect',inspection_result='pass',status=409)
    api('POST',f'warehouse-outbounds/{row["parts_outbound_id"]}/post')
    row=action(api,row,'inspect',inspection_result='pass')
    row=action(api,row,'close')
    assert row['parts_status']=='posted'
    stock={item['id']:item['quantity'] for item in api('GET','stock')}
    assert Decimal(stock[material])==10 and Decimal(stock[part])==19
    assert not any(item['source_type'].startswith('after_sales') for item in api('GET','movements'))


def test_return_case_uses_existing_return_and_retains_audited_correction(erp):
    _,api,_,shipment,_,_,order=erp
    row=approved(erp,payload(erp,kind='return'))
    row=action(api,row,'process')
    action(api,row,'close',status=409)
    api('POST',f'sales-returns/{row["sales_return_id"]}/post')
    row=action(api,row,'close')
    action(api,row,'reverse',status=409)
    api('POST',f'shipments/{shipment["id"]}/reverse',{'reason':'已有售后'},status=409)
    api('POST',f'sales-returns/{row["sales_return_id"]}/reverse',{'reason':'退回数量更正'},status=201)
    row=action(api,row,'reverse')
    assert row['status']=='reversed' and row['sales_return_id'] is not None
    assert api('GET','after-sales')['sources'][0]['remaining_quantity']=='10'


def test_exchange_cannot_ship_before_return_or_reverse_return_before_replacement(erp):
    _,api,_,_,material,_,_=erp
    row=action(api,approved(erp,payload(erp,kind='exchange')),'process')
    api('POST',f'sales-orders/{row["replacement_order_id"]}/confirm',status=409)
    api('POST',f'sales-returns/{row["sales_return_id"]}/post')
    api('POST',f'sales-orders/{row["replacement_order_id"]}/confirm')
    action(api,row,'close',status=409)
    replacement=api('POST','shipments',{'sales_order_id':row['replacement_order_id'],'warehouse_id':1,
        'lines':[{'material_id':material,'quantity':'2'}]},status=201)
    api('POST',f'shipments/{replacement["id"]}/post')
    row=action(api,row,'close')
    api('POST',f'sales-returns/{row["sales_return_id"]}/reverse',{'reason':'需先更正换货'},status=409)
    api('POST',f'shipments/{replacement["id"]}/reverse',{'reason':'換货更正'},status=201)
    api('POST',f'sales-returns/{row["sales_return_id"]}/reverse',{'reason':'退货更正'},status=201)
    api('POST',f'sales-orders/{row["replacement_order_id"]}/cancel')
    assert action(api,row,'reverse')['status']=='reversed'


def test_independent_review_tracks_editors_and_versions_and_read_permissions(erp):
    _,api,_,_,_,_,_=erp
    row=api('POST',ROOT,payload(erp),status=201)
    row=api('PUT',f'{ROOT}/{row["id"]}',{**payload(erp), 'version':row['version']},actor='seller')
    row=action(api,row,'submit')
    action(api,row,'approve',status=403)
    action(api,row,'approve',actor='seller',status=403)
    action(api,row,'approve',actor='reviewer',version=row['version']-1,status=409)
    row=action(api,row,'approve',actor='reviewer')
    assert len(row['author_ids'])==2
    api('GET',f'{ROOT}/{row["id"]}',actor='viewer',status=403)
    action(api,row,'receive',actor='seller',status=403)


@pytest.mark.parametrize('bad',[
    {'quantity':'0.0001'}, {'quantity':'NaN'}, {'shipment_line_id':True}, {'fee_amount':'0.001'},
    {'fee_amount':'3','charge_mode':'free'}, {'charge_mode':'none'}, {'status':'closed'},
    {'replacement_material_id':1}, {'customer_acceptance':'  '},
])
def test_strict_input_never_guesses_price_custody_or_client_status(erp,bad):
    erp[1]('POST',ROOT,payload(erp,**bad),status=422)
    assert erp[1]('GET','after-sales')['cases']==[]


def test_pending_cases_and_plain_returns_share_quantity_and_source_guards(erp):
    _,api,_,shipment,_,_,_=erp
    row=api('POST',ROOT,payload(erp,quantity='8'),status=201)
    row=action(api,row,'submit')
    api('POST',f'shipments/{shipment["id"]}/reverse',{'reason':'受占用'},status=409)
    returned=api('POST','sales-returns',{'shipment_id':shipment['id'],'warehouse_id':1,'reason':'普通退货',
        'lines':[{'shipment_line_id':shipment['lines'][0]['id'],'quantity':'3'}]},status=201)
    api('POST',f'sales-returns/{returned["id"]}/post',status=409)
    action(api,row,'cancel')
    api('POST',f'sales-returns/{returned["id"]}/post')
    api('POST',ROOT,payload(erp,quantity='8',reference='AFTER-2'),status=409)


def test_concurrent_submission_and_process_never_double_allocate(erp):
    _,api,_,_,_,_,_=erp
    first=api('POST',ROOT,payload(erp,quantity='6'),status=201)
    second=api('POST',ROOT,payload(erp,quantity='6',reference='AFTER-2'),status=201)
    barrier=Barrier(2)
    client,_,actors,_,_,_,_=erp
    def submit(row):
        barrier.wait(timeout=5)
        return client.post(f'/api/v1/{ROOT}/{row["id"]}/submit',headers=actors['admin'],
            json={'version':row['version'],'reason':'并发数量确认'}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit,[first,second]))==[200,409]
    row=approved(erp,payload(erp,kind='return',quantity='2',reference='AFTER-3'))
    barrier=Barrier(2)
    def process(_):
        barrier.wait(timeout=5)
        return client.post(f'/api/v1/{ROOT}/{row["id"]}/process',headers=actors['admin'],
            json={'version':row['version'],'reason':'并发办理'}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(process,[1,2]))==[200,409]
    assert len(api('GET','sales-returns'))==1


def test_audit_failure_after_flush_rolls_back_linked_draft_and_releases_retry(erp):
    _,api,_,_,_,_,_=erp
    row=approved(erp,payload(erp,kind='exchange'))
    def fail(db,*_):
        if any(isinstance(item,AfterSalesChange) and item.action=='process' for item in db.new):
            db.info['fail_after_sales']=True
    def after(db,*_):
        if db.info.pop('fail_after_sales',False):
            raise RuntimeError('模拟关联单据及审计刷新后失败')
    event.listen(Session,'before_flush',fail); event.listen(Session,'after_flush_postexec',after)
    try:
        action(api,row,'process',status=500)
    finally:
        event.remove(Session,'before_flush',fail); event.remove(Session,'after_flush_postexec',after)
    assert api('GET','sales-returns')==[] and len(api('GET','sales-orders'))==1
    original=api('GET',f'{ROOT}/{row["id"]}')
    assert original['version']==row['version'] and original['status']=='approved'
    assert action(api,row,'process')['replacement_order_id'] is not None


def test_cancel_received_repair_requires_actual_handover_and_no_bill(erp):
    _,api,_,_,_,_,_=erp
    row=action(api,approved(erp,payload(erp,charge_mode='charge',fee_amount='5')),'receive')
    action(api,row,'cancel',evidence='',status=422)
    row=action(api,row,'cancel')
    assert row['custody_quantity']=='0' and len(row['custody'])==2
    assert not any(item['source_type'].startswith('after_sales') for item in api('GET','finance/receivables-payables')['entries'])


def test_v51_upgrade_is_idempotent_preserves_sales_and_models(erp,remove_after_sales_schema):
    with sqlite3.connect(os.environ['NEXORA_DB_PATH']) as db:
        before=db.execute('SELECT * FROM sales_orders').fetchall()
        remove_after_sales_schema(db); db.execute('PRAGMA user_version=51')
    migrate(); migrate()
    with sqlite3.connect(os.environ['NEXORA_DB_PATH']) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]== 77
        assert db.execute('SELECT * FROM sales_orders').fetchall()==before
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
    assert len(Base.metadata.tables)== 176


def test_v63_labor_upgrade_preserves_cases_and_rolls_back_on_failure(erp,remove_after_sales_labor_schema,monkeypatch):
    import app.core.database as database
    _,api,_,_,_,_,_=erp
    case=approved(erp,payload(erp))
    with database.connection() as db:
        remove_after_sales_labor_schema(db)
        db.execute('PRAGMA user_version=63')
    original=database.connection
    @contextmanager
    def failing():
        with original() as db:
            db.set_authorizer(lambda operation,name,*_: sqlite3.SQLITE_DENY if operation==sqlite3.SQLITE_CREATE_TABLE
                and name=='after_sales_labor' else sqlite3.SQLITE_OK)
            yield db
    monkeypatch.setattr(database,'connection',failing)
    with pytest.raises(Exception):
        migrate()
    monkeypatch.setattr(database,'connection',original)
    with original() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==63
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='after_sales_labor'").fetchone()
        assert not db.execute("SELECT 1 FROM permissions WHERE code='after_sales.labor'").fetchone()
    migrate();migrate()
    with original() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]== 77
        assert db.execute('SELECT status FROM after_sales_cases WHERE id=?',(case['id'],)).fetchone()[0]=='approved'
        assert db.execute("SELECT COUNT(*) FROM role_permissions WHERE permission_code='after_sales.labor'").fetchone()[0]==2


def test_exchange_cancelled_during_processing_has_a_complete_correction_path(erp):
    _,api,_,_,_,_,_=erp
    row=action(api,approved(erp,payload(erp,kind='exchange')),'process')
    api('POST',f'sales-returns/{row["sales_return_id"]}/post')
    api('POST',f'sales-orders/{row["replacement_order_id"]}/cancel')
    action(api,row,'cancel',status=409)
    api('POST',f'sales-returns/{row["sales_return_id"]}/reverse',{'reason':'客户取消换货'},status=201)
    assert action(api,row,'cancel')['status']=='cancelled'
    assert api('GET','after-sales')['sources'][0]['remaining_quantity']=='10'


def test_v51_upgrade_failure_rolls_back_tables_permissions_and_version(erp,remove_after_sales_schema,monkeypatch):
    import app.core.database as database
    with database.connection() as db:
        remove_after_sales_schema(db);db.execute('PRAGMA user_version=51')
    original=database.connection
    @contextmanager
    def failing():
        with original() as db:
            db.set_authorizer(lambda operation,name,*_: sqlite3.SQLITE_DENY if operation==sqlite3.SQLITE_CREATE_TABLE
                and name=='after_sales_custody' else sqlite3.SQLITE_OK)
            yield db
    monkeypatch.setattr(database,'connection',failing)
    with pytest.raises(Exception):
        migrate()
    with original() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==51
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='after_sales_cases'").fetchone()
        assert not db.execute("SELECT 1 FROM permissions WHERE code LIKE 'after_sales.%'").fetchone()


def test_repair_fee_and_correction_generate_independently_reviewed_balanced_journals(erp):
    from app.finance.business_sources import ROLE_LABELS
    from app.finance.ledger_reports import LedgerReportQuery, trial_balance
    _,api,_,_,_,_,_=erp
    row=action(api,action(api,approved(erp,payload(erp,charge_mode='charge',fee_amount='5.50')),
        'receive'),'inspect',inspection_result='pass')
    row=action(api,row,'close')
    mapping={role:api('POST','finance/ledger-accounts',dict(code=f'A{index}',name=label,
        category='asset',normal_balance='debit',reason='维修费用测试科目'),status=201)['id']
        for index,(role,label) in enumerate(ROLE_LABELS.items(),1)}
    api('POST','finance/accounting-periods',dict(code='AFTER-YEAR',name='售后测试年',
        start_date='2026-01-01',end_date='2026-12-31',reason='核对收费凭证'),status=201)
    api('PUT','finance/business-journals/policy',dict(version=0,start_date='2026-01-01',mapping=mapping,reason='核对启用'))
    def post_source(key,reference):
        source=next(item for item in api('GET','finance/business-journals') if item['key']==key)
        journal=api('POST','finance/business-journals/generate',dict(source_key=key,
            fingerprint=source['fingerprint'],policy_version=source['policy_version'],reference=reference,
            journal_date=source['minimum_date'],reason='核对客户同意及交付'),status=201)
        path=f'finance/journals/{journal["id"]}'
        journal=api('POST',path+'/submit',dict(version=journal['version'],reason='核对来源'))
        api('POST',path+'/approve',dict(version=journal['version'],reason='不能自审'),status=409)
        journal=api('POST',path+'/approve',dict(version=journal['version'],reason='独立审核'),actor='reviewer')
        return api('POST',path+'/post',dict(version=journal['version'],reason='登记售后费用'))
    original=post_source(f'after_sales_repair:{row["id"]}','REPAIR-FEE')
    assert original['total_debit']=='5.50'
    with orm_session() as db:
        assert business_sources(db)[f'after_sales_repair:{row["id"]}']['movements']==[]
    action(api,row,'reverse')
    correction=post_source(f'after_sales_repair_reversal:{row["id"]}','REPAIR-FEE-REV')
    assert correction['total_debit']=='5.50'
    assert api('GET',f'finance/journals/{original["id"]}')['status']=='posted'
    with orm_session() as db:
        balances,totals=trial_balance(db,LedgerReportQuery(kind='trial_balance',from_date='2026-01-01',to_date='2026-12-31'))
        assert totals['balanced']
        for account_id in (mapping['receivable'],mapping['repair_income']):
            balance=next(value for value in balances if int(value['account_id'])==account_id)
            assert balance['closing_debit']==balance['closing_credit']=='0.00'


def test_closing_archives_open_custody_and_fee_and_rolls_back_locked_corrections(erp,monkeypatch):
    _,api,_,_,_,_,_=erp
    closed=action(api,action(api,approved(erp,payload(erp,charge_mode='charge',fee_amount='5.50')),
        'receive'),'inspect',inspection_result='pass')
    closed=action(api,closed,'close')
    held=action(api,approved(erp,payload(erp,reference='HELD',quantity='1')),'receive')
    held=api('POST',f'{ROOT}/{held["id"]}/labor',{'version':held['version'],'hours':'1.50',
        'reason':'维修诊断','evidence':'维修工单 R-9'},status=201)
    api('POST','finance/accounting-periods',dict(code='AFTER-YEAR',name='售后测试年',
        start_date='2026-01-01',end_date='2026-12-31',reason='核对客户保管'),status=201)
    monkeypatch.setattr('app.finance.period_closing.utc_today',lambda:'2027-01-01')
    path='finance/accounting-periods/1'
    check=api('GET',path+'/closing-check')
    assert check['can_close'],check['blockers']
    api('POST',path+'/close',dict(version=1,reason='核对售后费用及客户保管'))
    evidence=api('GET',path+'/closings')[0]['evidence']['after_sales']
    assert evidence[0]['case']['fee_amount']=='5.50' and evidence[0]['custody_quantity']=='0'
    assert evidence[1]['case']['status']=='received' and evidence[1]['custody_quantity']=='1'
    assert evidence[1]['labor_hours']=='1.50' and evidence[1]['labor'][0]['evidence']=='维修工单 R-9'
    assert evidence[1]['custody'][0]['evidence']=='交接检验记录 A-002'
    action(api,closed,'reverse',status=409)
    action(api,held,'cancel',status=409)
    api('POST',f'{ROOT}/{held["id"]}/labor',{'version':held['version'],'hours':'1',
        'reason':'锁期追加','evidence':'迟到工单'},status=409)
    assert api('GET',f'{ROOT}/{held["id"]}')==held
    assert api('GET',path+'/closings')[0]['evidence']['after_sales']==evidence


def test_archive_uses_last_audit_before_end_instead_of_future_case_state(erp):
    from app.sales.after_sales_rules import archive_cases
    _,api,_,_,_,_,_=erp
    held=action(api,approved(erp,payload(erp)),'receive')
    cancelled=action(api,held,'cancel')
    with orm_session(write=True) as db:
        for model in (AfterSalesChange,AfterSalesCustody):
            last=db.scalars(select(model).where(model.case_id==held['id']).order_by(model.id.desc())).first()
            last.created_at='2027-01-01 00:00:00'
    with orm_session() as db:
        frozen=archive_cases(db,'2026-12-31')[0]
        assert frozen['case']['status']=='received' and frozen['custody_quantity']=='2'
        assert len(frozen['custody'])==1
        assert archive_cases(db,'2027-01-01')[0]['case']['status']==cancelled['status']
