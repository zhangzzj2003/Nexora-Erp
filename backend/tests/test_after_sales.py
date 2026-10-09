"""售后独立审核、数量占用、客户物品保管和收费来源的真实跨模块约束。"""

from approval_test_helpers import approve_document, execute_payment, journal_approval_request
import os
import sqlite3
from contextlib import contextmanager
from decimal import Decimal
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.main import app
from app.core.database import migrate
from app.core.models import Base, AfterSalesChange, AfterSalesCase, AfterSalesCustody, AfterSalesLabor, AfterSalesLaborCost, AfterSalesResponsibility, Customer, RolePermission
from app.core.orm import orm_session
from app.finance.business_sources import business_sources
from app.sales.after_sales_rules import archive_cases

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
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, actors['admin'], 'PurchaseOrder', purchase['id'])
        api('POST',f'purchase-orders/{purchase["id"]}/confirm')
        receipt=api('POST','receipts',{'supplier_id':supplier,'purchase_order_id':purchase['id'],
            'lines':[{'material_id':m,'quantity':'20'} for m in (material,part)]},status=201)
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, actors['admin'], 'Receipt', receipt['id'])
        api('POST',f'receipts/{receipt["id"]}/post')
        order=api('POST','sales-orders',{'customer_id':customer,'lines':[{'material_id':material,'quantity':'10','unit_price':'10'}]},status=201)
        approve_document(client, actors['admin'], 'SalesOrder', order['id'])
        api('POST',f'sales-orders/{order["id"]}/confirm')
        shipment=api('POST','shipments',{'sales_order_id':order['id'],'warehouse_id':1,'lines':[{'material_id':material,'quantity':'10'}]},status=201)
        approve_document(client, actors['admin'], 'Shipment', shipment['id'])
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
    if operation in ('submit', 'approve', 'reject', 'withdraw') and 'version' not in extra:
        # 原测试显式改走统一步骤，其他实际交接仍使用原业务版本接口。
        state=api('GET',f'system/document-approvals/AfterSalesCase/{row["id"]}',actor=actor)
        result=api('POST',f'system/document-approvals/AfterSalesCase/{row["id"]}/{operation}',
            {'version':state['version'],'reason':extra.get('reason','核对售后依据')},actor=actor,status=status)
        return api('GET',f'{ROOT}/{row["id"]}',actor=actor) if status==200 else result
    return api('POST',f'{ROOT}/{row["id"]}/{operation}',{'version':row['version'],'reason':'核对售后依据',
        'evidence':'交接检验记录 A-002',**extra},actor=actor,status=status)


def approved(erp,data):
    api=erp[1]
    row=api('POST',ROOT,data,status=201)
    row=action(api,row,'submit')
    return action(api,row,'approve',actor='reviewer')


def test_responsibility_assessment_is_independent_append_only_and_does_not_change_fees(erp):
    _,api,_,_,_,_,_=erp
    row=api('POST',ROOT,payload(erp,charge_mode='charge',fee_amount='5.50'),status=201)
    path=f'{ROOT}/{row["id"]}/responsibility'
    first=dict(version=row['version'],outcome='company',basis='检验记录 R-1：装配缺陷',reason='独立核定')
    api('POST',path,first,actor='reviewer',status=409)
    row=action(api,row,'submit')
    api('POST',path,{**first,'version':row['version']},actor='admin',status=403)
    api('POST',path,{**first,'version':row['version']},actor='seller',status=403)
    api('POST',path,{**first,'version':row['version']},actor='viewer',status=403)
    assessed=api('POST',path,{**first,'version':row['version']},actor='reviewer',status=201)
    assert assessed['responsibility']['outcome']=='company'
    assert assessed['responsibility']['basis']=='检验记录 R-1：装配缺陷'
    assert assessed['responsibility']['assessed_by_name']=='reviewer'
    assert assessed['fee_amount']=='5.50' and assessed['charge_mode']=='charge'
    assert assessed['changes'][-1]['action']=='assess_responsibility'
    api('POST',path,{**first,'version':assessed['version']},actor='reviewer',status=409)
    api('POST',path,{**first,'version':row['version']},actor='reviewer',status=409)
    corrected=api('POST',path,dict(version=assessed['version'],outcome='third_party',
        basis='供方复检记录 S-2',reason='补充供方检验结果'),actor='reviewer',status=201)
    assert [item['outcome'] for item in corrected['responsibilities']]==['company','third_party']
    assert corrected['responsibility']['reason']=='补充供方检验结果'
    assert corrected['fee_amount']=='5.50'
    with orm_session() as db:
        archive=next(item for item in archive_cases(db,'2099-12-31') if item['case']['id']==row['id'])
        assert archive['responsibility']['outcome']=='third_party'
        assert len(archive['responsibilities'])==2


@pytest.mark.parametrize('outcome,basis',[
    ('automatic','检验记录'),('company','  '),('company','a'*401),
])
def test_responsibility_rejects_invalid_decision_or_basis(erp,outcome,basis):
    _,api,_,_,_,_,_=erp
    row=action(api,api('POST',ROOT,payload(erp),status=201),'submit')
    api('POST',f'{ROOT}/{row["id"]}/responsibility',dict(version=row['version'],
        outcome=outcome,basis=basis,reason='核定'),actor='reviewer',status=422)
    assert api('GET',f'{ROOT}/{row["id"]}')['responsibilities']==[]


def test_v79_responsibility_upgrade_is_atomic_and_preserves_old_cases(erp,monkeypatch):
    import app.core.database as database
    _,api,_,_,_,_,_=erp
    old=api('POST',ROOT,payload(erp),status=201)
    with database.connection() as db:
        db.execute('DROP TABLE after_sales_responsibilities')
        db.execute('PRAGMA user_version=79')
    original=database.connection
    @contextmanager
    def failing():
        with original() as db:
            db.set_authorizer(lambda operation,name,*_: sqlite3.SQLITE_DENY if operation==sqlite3.SQLITE_CREATE_TABLE
                and name=='after_sales_responsibilities' else sqlite3.SQLITE_OK)
            yield db
    monkeypatch.setattr(database,'connection',failing)
    with pytest.raises(sqlite3.DatabaseError):
        migrate()
    monkeypatch.setattr(database,'connection',original)
    with original() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==79
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='after_sales_responsibilities'").fetchone()
    migrate();migrate()
    with original() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]== 101
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='after_sales_responsibilities'").fetchone()
    assert api('GET',f'{ROOT}/{old["id"]}')['responsibilities']==[]


def test_responsibility_archive_uses_period_cutoff_instead_of_latest_revision(erp):
    _,api,_,_,_,_,_=erp
    row=action(api,api('POST',ROOT,payload(erp),status=201),'submit')
    path=f'{ROOT}/{row["id"]}/responsibility'
    row=api('POST',path,dict(version=row['version'],outcome='company',basis='原检验记录',
        reason='初次核定'),actor='reviewer',status=201)
    row=api('POST',path,dict(version=row['version'],outcome='customer',basis='后续客户确认书',
        reason='追加证据更正'),actor='reviewer',status=201)
    with orm_session(write=True) as db:
        db.get(AfterSalesResponsibility,row['responsibility']['id']).created_at='2027-01-01 00:00:00'
        last=db.scalars(select(AfterSalesChange).where(AfterSalesChange.case_id==row['id'])
            .order_by(AfterSalesChange.id.desc())).first()
        last.created_at='2027-01-01 00:00:00'
    with orm_session() as db:
        old=next(item for item in archive_cases(db,'2026-12-31') if item['case']['id']==row['id'])
        current=next(item for item in archive_cases(db,'2027-01-01') if item['case']['id']==row['id'])
    assert old['responsibility']['outcome']=='company' and len(old['responsibilities'])==1
    assert current['responsibility']['outcome']=='customer' and len(current['responsibilities'])==2


def test_order_warranty_terms_follow_shipment_into_case_and_cannot_be_overridden(erp):
    _,api,_,_,material,_,old_order=erp
    old_case=api('POST',ROOT,payload(erp,reference='W-LEGACY'),status=201)
    assert old_case['warranty_status']=='unknown'
    order=api('POST','sales-orders',{'customer_id':old_order['customer_id'],'lines':[
        {'material_id':material,'quantity':'2','unit_price':'10',
         'warranty_days':365,'warranty_basis':'  销售合同 W-365  '}]},status=201)
    assert order['lines'][0]['warranty_days']==365
    assert order['lines'][0]['warranty_basis']=='销售合同 W-365'
    approve_document(erp[0], erp[2]['admin'], 'SalesOrder', order['id'])
    api('POST',f'sales-orders/{order["id"]}/confirm')
    shipment=api('POST','shipments',{'sales_order_id':order['id'],'warehouse_id':1,
        'lines':[{'material_id':material,'quantity':'2'}]},status=201)
    approve_document(erp[0], erp[2]['admin'], 'Shipment', shipment['id'])
    shipment=api('POST',f'shipments/{shipment["id"]}/post')
    source_id=shipment['lines'][0]['id']
    original=next(item for item in api('GET','after-sales')['sources'] if item['shipment_line_id']==source_id)
    assert (original['warranty_days'],original['warranty_basis'])==(365,'销售合同 W-365')
    data=payload(erp,reference='W-AUTO',shipment_line_id=source_id,quantity='1')
    api('POST',ROOT,{**data,'warranty_days':30,'warranty_basis':'擅自修改'},status=409)
    row=api('POST',ROOT,data,status=201)
    assert (row['warranty_days'],row['warranty_basis'])==(365,'销售合同 W-365')
    assert row['frozen_source']['warranty_days']==365
    assert row['warranty_status']=='within_period'
    api('PUT',f'{ROOT}/{row["id"]}',{**data,'version':row['version'],
        'warranty_days':30,'warranty_basis':'擅自修改'},status=409)
    assert api('GET',f'{ROOT}/{row["id"]}')['version']==row['version']
    edited=api('PUT',f'{ROOT}/{row["id"]}',{**data,'version':row['version'],'solution':'核对后办理'},actor='seller')
    assert edited['warranty_days']==365
    with orm_session() as db:
        archived=next(item for item in archive_cases(db,'2099-12-31') if item['case']['id']==row['id'])
    assert archived['case']['warranty_basis']=='销售合同 W-365'


@pytest.mark.parametrize('terms',[
    {'warranty_days':30}, {'warranty_basis':'合同'},
    {'warranty_days':0,'warranty_basis':'合同'},
    {'warranty_days':True,'warranty_basis':'合同'},
    {'warranty_days':30,'warranty_basis':'  '},
])
def test_order_warranty_rejects_incomplete_or_invalid_terms(erp,terms):
    _,api,_,_,material,_,old_order=erp
    api('POST','sales-orders',{'customer_id':old_order['customer_id'],'lines':[
        {'material_id':material,'quantity':'1','unit_price':'10',**terms}]},status=422)


def test_v78_order_warranty_upgrade_is_atomic_and_keeps_old_orders_unknown(erp,monkeypatch):
    import app.core.database as database
    _,api,_,_,_,_,old_order=erp
    with sqlite3.connect(os.environ['NEXORA_DB_PATH']) as db:
        db.execute('ALTER TABLE sales_order_lines DROP COLUMN warranty_days')
        db.execute('ALTER TABLE sales_order_lines DROP COLUMN warranty_basis')
        db.execute('PRAGMA user_version=78')
    original=database.connection
    @contextmanager
    def failing():
        with original() as db:
            alters=0
            def deny_second_alter(operation,*_):
                nonlocal alters
                if operation==sqlite3.SQLITE_ALTER_TABLE:
                    alters+=1
                    if alters==2:
                        return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            db.set_authorizer(deny_second_alter)
            yield db
    monkeypatch.setattr(database,'connection',failing)
    with pytest.raises(sqlite3.DatabaseError):
        migrate()
    monkeypatch.setattr(database,'connection',original)
    with sqlite3.connect(os.environ['NEXORA_DB_PATH']) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==78
        assert 'warranty_days' not in {item[1] for item in db.execute('PRAGMA table_info(sales_order_lines)')}
    migrate();migrate()
    with sqlite3.connect(os.environ['NEXORA_DB_PATH']) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]== 101
        assert db.execute('SELECT warranty_days,warranty_basis FROM sales_order_lines WHERE sales_order_id=?',
            (old_order['id'],)).fetchone()==(None,'')
    old=next(item for item in api('GET','sales-orders') if item['id']==old_order['id'])
    assert old['lines'][0]['warranty_days'] is None


def test_warranty_period_uses_frozen_shipment_and_original_application_date(erp):
    _,api,_,_,_,_,_=erp
    unknown=api('POST',ROOT,payload(erp,reference='W-UNKNOWN'),status=201)
    assert unknown['warranty_status']=='unknown' and unknown['warranty_expires_on'] is None
    assert unknown['warranty_days'] is None and unknown['warranty_basis']==''
    data=payload(erp,reference='W-1',warranty_days=30,warranty_basis='销售合同第 3 条')
    row=api('POST',ROOT,data,status=201)
    shipped_on=date.fromisoformat(row['frozen_source']['posted_at'][:10])
    expires_on=shipped_on+timedelta(days=30)
    assert row['warranty_expires_on']==expires_on.isoformat()
    assert row['warranty_status']=='within_period'
    with orm_session(write=True) as db:
        db.get(AfterSalesCase,row['id']).created_at=expires_on.isoformat()+' 23:59:59'
    row=api('GET',f'{ROOT}/{row["id"]}')
    assert row['warranty_status']=='within_period' and row['warranty_applied_on']==expires_on.isoformat()
    with orm_session(write=True) as db:
        db.get(AfterSalesCase,row['id']).created_at=(expires_on+timedelta(days=1)).isoformat()+' 00:00:00'
    row=api('GET',f'{ROOT}/{row["id"]}')
    assert row['warranty_status']=='expired'
    edited=api('PUT',f'{ROOT}/{row["id"]}',{**data,'version':row['version'],'warranty_days':60,
        'warranty_basis':'合同补充协议第 2 条'},actor='seller')
    assert edited['warranty_applied_on']==row['warranty_applied_on']
    assert edited['warranty_status']=='within_period'
    assert edited['changes'][-1]['before']['warranty_days']==30
    assert edited['changes'][-1]['after']['warranty_basis']=='合同补充协议第 2 条'
    assert api('GET',f'{ROOT}/{unknown["id"]}')['warranty_status']=='unknown'


@pytest.mark.parametrize('extra',[
    {'warranty_days':0,'warranty_basis':'合同'},
    {'warranty_days':36501,'warranty_basis':'合同'},
    {'warranty_days':True,'warranty_basis':'合同'},
    {'warranty_days':1.5,'warranty_basis':'合同'},
    {'warranty_days':30,'warranty_basis':'  '},
    {'warranty_days':None,'warranty_basis':'合同'},
])
def test_warranty_requires_consistent_bounded_contract_terms(erp,extra):
    _,api,_,_,_,_,_=erp
    api('POST',ROOT,payload(erp,**extra),status=422)
    assert api('GET','after-sales')['cases']==[]


def test_v77_warranty_upgrade_keeps_old_cases_unknown_and_is_idempotent(erp,monkeypatch):
    import app.core.database as database
    _,api,_,_,_,_,_=erp
    old=api('POST',ROOT,payload(erp),status=201)
    with sqlite3.connect(os.environ['NEXORA_DB_PATH']) as db:
        db.execute('ALTER TABLE after_sales_cases DROP COLUMN warranty_days')
        db.execute('ALTER TABLE after_sales_cases DROP COLUMN warranty_basis')
        db.execute('PRAGMA user_version=77')
    original=database.connection
    @contextmanager
    def failing():
        with original() as db:
            alters=0
            def deny_second_alter(operation,*_):
                nonlocal alters
                if operation==sqlite3.SQLITE_ALTER_TABLE:
                    alters+=1
                    if alters==2:
                        return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            db.set_authorizer(deny_second_alter)
            yield db
    monkeypatch.setattr(database,'connection',failing)
    with pytest.raises(sqlite3.DatabaseError):
        migrate()
    monkeypatch.setattr(database,'connection',original)
    with original() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==77
        assert 'warranty_days' not in {item[1] for item in db.execute('PRAGMA table_info(after_sales_cases)')}
    migrate();migrate()
    with sqlite3.connect(os.environ['NEXORA_DB_PATH']) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]== 101
        assert db.execute('SELECT warranty_days,warranty_basis FROM after_sales_cases WHERE id=?',
            (old['id'],)).fetchone()==(None,'')
    assert api('GET',f'{ROOT}/{old["id"]}')['warranty_status']=='unknown'


def test_warranty_terms_are_frozen_in_period_archive(erp):
    _,api,_,_,_,_,_=erp
    row=api('POST',ROOT,payload(erp,warranty_days=30,warranty_basis='客户合同 W-1'),status=201)
    with orm_session() as db:
        archived=next(item for item in archive_cases(db,'2099-12-31') if item['case']['id']==row['id'])
    assert archived['case']['warranty_days']==30
    assert archived['case']['warranty_basis']=='客户合同 W-1'
    assert archived['case']['warranty_expires_on']==row['warranty_expires_on']
    assert archived['case']['warranty_status']==row['warranty_status']


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


def test_labor_cost_is_finance_only_append_only_and_excludes_reversed_hours(erp):
    _,api,_,_,_,_,_=erp
    row=action(api,approved(erp,payload(erp)),'receive')
    labor_path=f'{ROOT}/{row["id"]}/labor'
    row=api('POST',labor_path,dict(version=row['version'],hours='1.25',reason='拆机',
        evidence='维修工单 R-11'),actor='warehouse',status=201)
    original=row['labor'][0]
    cost_path=f'{ROOT}/{row["id"]}/labor-cost'
    assert 'labor_cost' not in row
    api('GET',cost_path,actor='warehouse',status=403)
    api('GET',cost_path,actor='seller',status=403)
    before=api('GET',cost_path,actor='reviewer')
    assert before['missing_labor_ids']==[original['id']] and before['total_amount']=='0.00'
    value_path=f'{cost_path}/{original["id"]}'
    first=dict(version=row['version'],hourly_rate='23.45',reason='按内部标准核价',evidence='费率批准表 C-1')
    api('POST',value_path,first,actor='warehouse',status=403)
    api('POST',value_path,{**first,'hourly_rate':23.45},actor='reviewer',status=422)
    api('POST',value_path,{**first,'hourly_rate':'2e1'},actor='reviewer',status=422)
    api('POST',value_path,{**first,'hourly_rate':'0'},actor='reviewer',status=422)
    valued=api('POST',value_path,first,actor='reviewer',status=201)
    assert valued['total_amount']=='29.31' and valued['missing_labor_ids']==[]
    assert valued['entries'][0]['latest']['hourly_rate']=='23.45'
    assert valued['history'][0]['amount']=='29.31'
    assert 'labor_cost' not in api('GET',f'{ROOT}/{row["id"]}',actor='warehouse')
    api('POST',value_path,first,actor='reviewer',status=409)
    api('POST',value_path,{**first,'version':valued['case_version']},actor='reviewer',status=409)
    corrected=api('POST',value_path,{**first,'version':valued['case_version'],
        'hourly_rate':'20.00','reason':'修正费率','evidence':'批准表 C-2'},actor='reviewer',status=201)
    assert corrected['total_amount']=='25.00' and len(corrected['history'])==2
    voided=api('POST',value_path,{**first,'version':corrected['case_version'],
        'hourly_rate':None,'reason':'撤销错误核价','evidence':'复核单 C-3'},actor='reviewer',status=201)
    assert voided['total_amount']=='0.00' and voided['missing_labor_ids']==[original['id']]
    restored=api('POST',value_path,{**first,'version':voided['case_version'],
        'hourly_rate':'20.00'},actor='reviewer',status=201)
    row=api('GET',f'{ROOT}/{row["id"]}')
    assert row['version']==restored['case_version']
    row=api('POST',f'{labor_path}/{original["id"]}/reverse',dict(version=row['version'],
        reason='原计时重复',evidence='复核单 R-12'),actor='warehouse')
    inactive=api('GET',cost_path,actor='reviewer')
    assert inactive['total_amount']=='0.00' and inactive['missing_labor_ids']==[]
    assert inactive['entries'][0]['reversed'] and len(inactive['history'])==4
    api('POST',value_path,{**first,'version':row['version']},actor='reviewer',status=409)
    with orm_session() as db:
        archive=next(item for item in archive_cases(db,'2099-12-31') if item['case']['id']==row['id'])
        assert archive['labor_cost']['total_amount']=='0.00'
        assert len(list(db.scalars(select(AfterSalesLaborCost))))==4


def test_repair_margin_combines_recognized_fee_parts_and_labor_without_hiding_gaps(erp):
    _,api,_,_,_,part,_=erp
    row=approved(erp,payload(erp,reference='MARGIN-1',charge_mode='charge',fee_amount='50.00',
        warehouse_id=1,parts=[{'material_id':part,'quantity':'2'}]))
    margin_path=f'{ROOT}/{row["id"]}/repair-margin'
    api('GET',margin_path,actor='warehouse',status=403)
    api('GET',margin_path,actor='seller',status=403)
    pending=api('GET',margin_path,actor='reviewer')
    assert not pending['finalized'] and not pending['complete'] and pending['parts_pending']
    assert pending['revenue']=='0.00' and pending['direct_margin'] is None
    row=action(api,row,'receive')
    row=api('POST',f'{ROOT}/{row["id"]}/labor',dict(version=row['version'],hours='1.50',
        reason='拆机维修',evidence='维修工单 M-1'),actor='warehouse',status=201)
    labor_id=row['labor'][0]['id']
    approve_document(erp[0], erp[2]['admin'], 'WarehouseOutbound', row['parts_outbound_id'])
    api('POST',f'warehouse-outbounds/{row["parts_outbound_id"]}/post')
    row=action(api,row,'inspect',inspection_result='pass')
    row=action(api,row,'close')
    incomplete=api('GET',margin_path,actor='reviewer')
    assert incomplete['revenue']=='50.00' and incomplete['material_cost']=='2.00'
    assert incomplete['labor_cost'] is None and incomplete['missing_labor_ids']==[labor_id]
    assert incomplete['direct_margin'] is None and not incomplete['complete']
    api('POST',f'{ROOT}/{row["id"]}/labor-cost/{labor_id}',dict(version=row['version'],
        hourly_rate='20.00',reason='按标准核价',evidence='内部费率表 M-1'),actor='reviewer',status=201)
    complete=api('GET',margin_path,actor='reviewer')
    assert complete['complete'] and complete['finalized']
    assert (complete['revenue'],complete['material_cost'],complete['labor_cost'],
        complete['total_direct_cost'],complete['direct_margin'])==('50.00','2.00','30.00','32.00','18.00')
    assert len(complete['movements'])==1 and complete['movements'][0]['cost']=='2.00'
    assert complete['movements'][0]['source_line_id'] and complete['movements'][0]['cost_source']=='moving_average'
    assert 'repair_margin' not in api('GET',f'{ROOT}/{row["id"]}',actor='warehouse')
    row=api('GET',f'{ROOT}/{row["id"]}')
    approve_document(erp[0], erp[2]['admin'], 'AfterSalesCase', row['id'], intent='reverse', reason='核对售后依据')
    action(api,row,'reverse')
    reversed_margin=api('GET',margin_path,actor='reviewer')
    assert reversed_margin['complete'] and reversed_margin['revenue']=='0.00'
    assert reversed_margin['direct_margin']=='-32.00'
    with orm_session() as db:
        archive=next(item for item in archive_cases(db,'2099-12-31') if item['case']['id']==row['id'])
        assert archive['repair_margin']['direct_margin']=='-32.00'


def test_repair_margin_rejects_non_repair_case(erp):
    api=erp[1]
    row=api('POST',ROOT,payload(erp,kind='return',reference='MARGIN-RETURN'),status=201)
    api('GET',f'{ROOT}/{row["id"]}/repair-margin',actor='reviewer',status=409)


def test_repair_margin_honors_customer_scope(erp):
    api=erp[1]
    row=approved(erp,payload(erp,reference='MARGIN-SCOPE'))
    with orm_session(write=True) as db:
        db.add(RolePermission(role_code='seller',permission_code='after_sales.cost'))
    path=f'{ROOT}/{row["id"]}/repair-margin'
    assert api('GET',path,actor='seller')['case_id']==row['id']
    with orm_session(write=True) as db:
        db.get(Customer,row['frozen_source']['customer_id']).owner_id=1
    api('GET',path,actor='seller',status=404)


def test_repair_margin_waits_for_missing_stock_price_and_recomputes_after_valuation(erp):
    api=erp[1];part=erp[5]
    inbound=api('POST','warehouse-inbounds',dict(warehouse_id=1,reason='gift',
        note='待核价入库',reference='MARGIN-IN',lines=[dict(material_id=part,quantity='1')]),status=201)
    approve_document(erp[0], erp[2]['admin'], 'WarehouseInbound', inbound['id'])
    api('POST',f'warehouse-inbounds/{inbound["id"]}/post')
    source_id=api('GET','inventory/valuation')['unpriced_movement_ids'][0]
    row=approved(erp,payload(erp,reference='MARGIN-UNPRICED',warehouse_id=1,
        parts=[dict(material_id=part,quantity='1')]))
    row=action(api,row,'receive')
    approve_document(erp[0], erp[2]['admin'], 'WarehouseOutbound', row['parts_outbound_id'])
    api('POST',f'warehouse-outbounds/{row["parts_outbound_id"]}/post')
    row=action(api,row,'inspect',inspection_result='pass')
    row=action(api,row,'close')
    path=f'{ROOT}/{row["id"]}/repair-margin'
    pending=api('GET',path,actor='reviewer')
    assert pending['material_cost'] is None and pending['direct_margin'] is None
    assert len(pending['unpriced_movement_ids'])==1
    api('POST','inventory/valuation/inputs',dict(movement_id=source_id,unit_cost='5',
        reference='MARGIN-PRICE',reason='核对入库价格'),status=201)
    valued=api('GET',path,actor='reviewer')
    assert valued['complete'] and valued['unpriced_movement_ids']==[]
    assert valued['material_cost']=='1.19' and valued['direct_margin']=='-1.19'


def test_labor_cost_checks_scope_author_and_transaction_rollback(erp,monkeypatch):
    _,api,_,_,_,_,_=erp
    row=action(api,approved(erp,payload(erp)),'receive')
    row=api('POST',f'{ROOT}/{row["id"]}/labor',dict(version=row['version'],hours='2',
        reason='维修',evidence='工单 R-13'),actor='warehouse',status=201)
    path=f'{ROOT}/{row["id"]}/labor-cost/{row["labor"][0]["id"]}'
    data=dict(version=row['version'],hourly_rate='15.00',reason='成本核价',evidence='内部标准 C-4')
    api('POST',f'{ROOT}/{row["id"]}/labor-cost/999999',data,actor='reviewer',status=404)
    with orm_session(write=True) as db:
        db.add(RolePermission(role_code='warehouse',permission_code='after_sales.cost'))
        db.add(RolePermission(role_code='seller',permission_code='after_sales.cost'))
    api('POST',path,data,actor='warehouse',status=403)
    with orm_session(write=True) as db:
        db.get(Customer,row['frozen_source']['customer_id']).owner_id=1
    api('POST',path,{**data,'version':row['version']-1},actor='seller',status=404)
    with orm_session(write=True) as db:
        db.get(Customer,row['frozen_source']['customer_id']).owner_id=1
    def failed_audit(*_args,**_kwargs):
        raise RuntimeError('模拟审计失败')
    monkeypatch.setattr('app.sales.after_sales_labor_cost.audit',failed_audit)
    api('POST',path,data,actor='reviewer',status=500)
    current=api('GET',f'{ROOT}/{row["id"]}')
    assert current['version']==row['version']
    assert api('GET',f'{ROOT}/{row["id"]}/labor-cost',actor='reviewer')['history']==[]


def test_v82_labor_cost_upgrade_is_atomic_and_preserves_labor(erp,monkeypatch):
    import app.core.database as database
    _,api,_,_,_,_,_=erp
    row=action(api,approved(erp,payload(erp)),'receive')
    row=api('POST',f'{ROOT}/{row["id"]}/labor',dict(version=row['version'],hours='1.50',
        reason='维修',evidence='工单 R-14'),actor='warehouse',status=201)
    with database.connection() as db:
        db.execute('DROP TABLE after_sales_labor_costs')
        db.execute("DELETE FROM role_permissions WHERE permission_code='after_sales.cost'")
        db.execute("DELETE FROM permissions WHERE code='after_sales.cost'")
        db.execute('PRAGMA user_version=82')
    original=database.connection
    @contextmanager
    def failing():
        with original() as db:
            db.set_authorizer(lambda operation,name,*_: sqlite3.SQLITE_DENY
                if operation==sqlite3.SQLITE_INSERT and name=='permissions' else sqlite3.SQLITE_OK)
            yield db
    monkeypatch.setattr(database,'connection',failing)
    with pytest.raises(sqlite3.DatabaseError):
        migrate()
    monkeypatch.setattr(database,'connection',original)
    with database.connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==82
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='after_sales_labor_costs'").fetchone()
        assert db.execute('SELECT COUNT(*) FROM after_sales_labor').fetchone()[0]==1
    migrate()
    migrate()
    with orm_session() as db:
        assert 'after_sales_labor_costs' in Base.metadata.tables
        assert db.scalar(select(AfterSalesLaborCost.id).limit(1)) is None
    assert api('GET',f'{ROOT}/{row["id"]}/labor-cost',actor='reviewer')['missing_labor_ids']==[row['labor'][0]['id']]


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
    paid=api('POST','finance/payment-records',{'kind':'receivable','order_id':order['id'],'action':'settlement',
        'amount':'105.50','reference':'服务收款'},status=201)
    execute_payment(erp[0],erp[2]['admin'],paid)
    approve_document(erp[0], erp[2]['admin'], 'AfterSalesCase', row['id'], intent='reverse', reason='核对售后依据')
    row=action(api,row,'reverse')
    account=next(item for item in api('GET','finance/accounts') if item['kind']=='receivable' and item['order_id']==order['id'])
    assert account['business_amount']=='100.00' and account['outstanding_amount']=='-5.50'
    assert len(row['custody'])==2 and row['custody_quantity']=='0'
    approve_document(erp[0], erp[2]['admin'], 'Shipment', shipment['id'], intent='reverse', reason='来源更正')
    api('POST',f'shipments/{shipment["id"]}/reverse',{'reason':'来源更正'},status=201)


def test_repair_parts_use_company_outbound_and_require_effective_posting(erp):
    _,api,_,_,material,part,_=erp
    row=approved(erp,payload(erp,warehouse_id=1,parts=[{'material_id':part,'quantity':'1'}]))
    row=action(api,row,'receive')
    assert row['parts_status']=='draft'
    action(api,row,'inspect',inspection_result='pass',status=409)
    approve_document(erp[0], erp[2]['admin'], 'WarehouseOutbound', row['parts_outbound_id'])
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
    approve_document(erp[0], erp[2]['admin'], 'SalesReturn', row['sales_return_id'])
    api('POST',f'sales-returns/{row["sales_return_id"]}/post')
    row=action(api,row,'close')
    action(api,row,'reverse',status=409)
    api('POST',f'shipments/{shipment["id"]}/reverse',{'reason':'已有售后'},status=409)
    approve_document(erp[0], erp[2]['admin'], 'SalesReturn', row['sales_return_id'], intent='reverse', reason='退回数量更正')
    api('POST',f'sales-returns/{row["sales_return_id"]}/reverse',{'reason':'退回数量更正'},status=201)
    approve_document(erp[0], erp[2]['admin'], 'AfterSalesCase', row['id'], intent='reverse', reason='核对售后依据')
    row=action(api,row,'reverse')
    assert row['status']=='reversed' and row['sales_return_id'] is not None
    assert api('GET','after-sales')['sources'][0]['remaining_quantity']=='10'


def test_exchange_cannot_ship_before_return_or_reverse_return_before_replacement(erp):
    _,api,_,_,material,_,_=erp
    row=action(api,approved(erp,payload(erp,kind='exchange')),'process')
    api('POST',f'sales-orders/{row["replacement_order_id"]}/confirm',status=409)
    approve_document(erp[0], erp[2]['admin'], 'SalesReturn', row['sales_return_id'])
    api('POST',f'sales-returns/{row["sales_return_id"]}/post')
    approve_document(erp[0], erp[2]['admin'], 'SalesOrder', row['replacement_order_id'])
    api('POST',f'sales-orders/{row["replacement_order_id"]}/confirm')
    action(api,row,'close',status=409)
    replacement=api('POST','shipments',{'sales_order_id':row['replacement_order_id'],'warehouse_id':1,
        'lines':[{'material_id':material,'quantity':'2'}]},status=201)
    approve_document(erp[0], erp[2]['admin'], 'Shipment', replacement['id'])
    api('POST',f'shipments/{replacement["id"]}/post')
    row=action(api,row,'close')
    api('POST',f'sales-returns/{row["sales_return_id"]}/reverse',{'reason':'需先更正换货'},status=409)
    approve_document(erp[0], erp[2]['admin'], 'Shipment', replacement['id'], intent='reverse', reason='換货更正')
    api('POST',f'shipments/{replacement["id"]}/reverse',{'reason':'換货更正'},status=201)
    approve_document(erp[0], erp[2]['admin'], 'SalesReturn', row['sales_return_id'], intent='reverse', reason='退货更正')
    api('POST',f'sales-returns/{row["sales_return_id"]}/reverse',{'reason':'退货更正'},status=201)
    api('POST',f'sales-orders/{row["replacement_order_id"]}/cancel')
    approve_document(erp[0], erp[2]['admin'], 'AfterSalesCase', row['id'], intent='reverse', reason='核对售后依据')
    assert action(api,row,'reverse')['status']=='reversed'


def test_independent_review_tracks_editors_and_versions_and_read_permissions(erp):
    _,api,_,_,_,_,_=erp
    row=api('POST',ROOT,payload(erp),status=201)
    row=api('PUT',f'{ROOT}/{row["id"]}',{**payload(erp), 'version':row['version']},actor='seller')
    row=action(api,row,'submit')
    assert api('GET',f'system/document-approvals/AfterSalesCase/{row["id"]}')['can_review']
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
    row=action(api,row,'withdraw')
    action(api,row,'cancel')
    approve_document(erp[0], erp[2]['admin'], 'SalesReturn', returned['id'])
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
        return client.post(f'/api/v1/system/document-approvals/AfterSalesCase/{row["id"]}/submit',headers=actors['admin'],
            json={'version':0,'reason':'并发数量确认'}).status_code
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
        assert db.execute('PRAGMA user_version').fetchone()[0]== 101
        assert db.execute('SELECT * FROM sales_orders').fetchall()==before
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
    assert len(Base.metadata.tables)== 202


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
        assert db.execute('PRAGMA user_version').fetchone()[0]== 101
        assert db.execute('SELECT status FROM after_sales_cases WHERE id=?',(case['id'],)).fetchone()[0]=='approved'
        assert db.execute("SELECT COUNT(*) FROM role_permissions WHERE permission_code='after_sales.labor'").fetchone()[0]==2


def test_exchange_cancelled_during_processing_has_a_complete_correction_path(erp):
    _,api,_,_,_,_,_=erp
    row=action(api,approved(erp,payload(erp,kind='exchange')),'process')
    approve_document(erp[0], erp[2]['admin'], 'SalesReturn', row['sales_return_id'])
    api('POST',f'sales-returns/{row["sales_return_id"]}/post')
    api('POST',f'sales-orders/{row["replacement_order_id"]}/cancel')
    action(api,row,'cancel',status=409)
    approve_document(erp[0], erp[2]['admin'], 'SalesReturn', row['sales_return_id'], intent='reverse', reason='客户取消换货')
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
        # 建单人具有按钮权限即可审批；这里保留另一角色核对来源及批准的业务链。
        submitted=journal_approval_request(erp[0],journal,'submit',reason='核对来源',headers=erp[2]['admin'])
        assert submitted.status_code==200,submitted.text
        journal=api('GET',path)
        assert api('GET',f'system/document-approvals/Journal/{journal["id"]}')['can_review']
        reviewed=journal_approval_request(erp[0],journal,'approve',reason='独立审核',headers=erp[2]['reviewer'])
        assert reviewed.status_code==200,reviewed.text
        journal=api('GET',path)
        return api('POST',path+'/post',dict(version=journal['version'],reason='登记售后费用'))
    original=post_source(f'after_sales_repair:{row["id"]}','REPAIR-FEE')
    assert original['total_debit']=='5.50'
    with orm_session() as db:
        assert business_sources(db)[f'after_sales_repair:{row["id"]}']['movements']==[]
    approve_document(erp[0], erp[2]['admin'], 'AfterSalesCase', row['id'], intent='reverse', reason='核对售后依据')
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
    cost_path=f'{ROOT}/{held["id"]}/labor-cost/{held["labor"][0]["id"]}'
    cost=api('POST',cost_path,dict(version=held['version'],hourly_rate='20.00',
        reason='期末内部核价',evidence='费率批准单 C-9'),actor='reviewer',status=201)
    assert cost['total_amount']=='30.00'
    held=api('GET',f'{ROOT}/{held["id"]}')
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
    assert evidence[1]['labor_cost']['total_amount']=='30.00'
    assert evidence[0]['repair_margin']['direct_margin']=='5.50'
    assert evidence[1]['repair_margin']['direct_margin'] is None
    assert evidence[1]['labor_cost']['history'][0]['evidence']=='费率批准单 C-9'
    assert evidence[1]['custody'][0]['evidence']=='交接检验记录 A-002'
    with orm_session(write=True) as db:
        db.add(RolePermission(role_code='warehouse',permission_code='accounting_period.closing_view'))
    limited=api('GET',path+'/closings',actor='warehouse')[0]['evidence']['after_sales']
    assert 'labor_cost' not in limited[1] and 'repair_margin' not in limited[1]
    assert limited[1]['labor_hours']=='1.50'
    action(api,closed,'reverse',status=409)
    action(api,held,'cancel',status=409)
    api('POST',f'{ROOT}/{held["id"]}/labor',{'version':held['version'],'hours':'1',
        'reason':'锁期追加','evidence':'迟到工单'},status=409)
    api('POST',cost_path,dict(version=held['version'],hourly_rate='21.00',
        reason='锁期后核价',evidence='迟到批准'),actor='reviewer',status=409)
    api('POST',f'{ROOT}/{closed["id"]}/responsibility',dict(version=closed['version'],
        outcome='company',basis='锁期后补充的核定依据',reason='补记'),actor='reviewer',status=409)
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


def test_after_sales_children_exclude_original_submitter_before_new_author_migration(erp):
    from app.core.models import DocumentApprovalAuthor, UserRole
    client, api, actors, *_ = erp
    row = api('POST', ROOT, payload(erp, kind='exchange'), status=201)
    row = action(api, row, 'submit', actor='seller')
    row = action(api, row, 'approve', actor='reviewer')
    row = action(api, row, 'process')
    for kind, identifier in [('SalesOrder', row['replacement_order_id']), ('SalesReturn', row['sales_return_id'])]:
        with orm_session() as db:
            assert db.scalar(select(DocumentApprovalAuthor.user_id).where(
                DocumentApprovalAuthor.document_type == kind, DocumentApprovalAuthor.document_id == identifier)) is None
    with orm_session(write=True) as db:
        # 原售后编制记录保留用于溯源，后续授予按钮权限即可审批子单。
        db.add(UserRole(user_id=3, role_code='admin'))
    for kind, identifier in [('SalesOrder', row['replacement_order_id']), ('SalesReturn', row['sales_return_id'])]:
        path = f'/api/v1/system/document-approvals/{kind}/{identifier}'
        assert client.post(path + '/submit', headers=actors['admin'], json={'version': 0}).status_code == 200
        assert client.get(path, headers=actors['seller']).json()['can_review']
