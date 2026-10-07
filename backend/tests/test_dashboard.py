"""首页按权限和真实来源汇总，覆盖跨日更正、缺价与当前未完订单。"""

from approval_test_helpers import approve_document
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.core.orm import orm_session
from app.core.models import (Shipment, ShipmentReversal, Receipt, ReceiptReversal, SalesReturn, SalesReturnReversal,
    AfterSalesCase, ProductionCompletion, ProductionCompletionReversal, RolePermission)


@pytest.fixture
def erp(monkeypatch,tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH',str(tmp_path/'dashboard.db'))
    monkeypatch.setattr('app.reports.dashboard.utc_now',lambda:datetime(2026,10,1,12,tzinfo=timezone.utc))
    with TestClient(app,client=('127.0.0.1',12000)) as client:
        def api(method,path,payload=None,status=200):
            response=client.request(method,'/api/v1/'+path,json=payload)
            assert response.status_code==status,response.text
            # 单据时间与固定统计时钟一起固定，CI 在不同日期运行也能验证边界。
            if method=='POST' and status<300 and path!='dashboard/query':
                with orm_session(write=True) as db:
                    for model in (Shipment,ShipmentReversal,Receipt,ReceiptReversal,SalesReturn,SalesReturnReversal,
                                  AfterSalesCase,ProductionCompletion,ProductionCompletionReversal):
                        for row in db.scalars(select(model)):
                            for field in ('posted_at','created_at','closed_at','reversed_at'):
                                if hasattr(row,field) and getattr(row,field):
                                    setattr(row,field,'2026-10-01 08:00:00')
            return response.json() if response.content else None
        api('POST','setup/admin',{'username':'admin','password':'secure-pass-123'},201)
        admin=api('POST','auth/login',{'username':'admin','password':'secure-pass-123'})['token']
        client.headers['Authorization']='Bearer '+admin
        supplier=api('POST','suppliers',{'name':'供货'},201)['id']
        customer=api('POST','customers',{'name':'客户'},201)['id']
        material=api('POST','materials',{'sku':'DASH','name':'统计商品','unit':'件'},201)['id']
        order=api('POST','purchase-orders',{'supplier_id':supplier,'lines':[{'material_id':material,'quantity':'20','unit_price':'3.125'}]},201)
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, dict(client.headers), 'PurchaseOrder', order['id'])
        api('POST',f'purchase-orders/{order["id"]}/confirm')
        receipt=api('POST','receipts',{'supplier_id':supplier,'purchase_order_id':order['id'],'lines':[{'material_id':material,'quantity':'10'}]},201)
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, dict(client.headers), 'Receipt', receipt['id'])
        api('POST',f'receipts/{receipt["id"]}/post')
        sale=api('POST','sales-orders',{'customer_id':customer,'lines':[{'material_id':material,'quantity':'10','unit_price':'10.5555'}]},201)
        approve_document(client, dict(client.headers), 'SalesOrder', sale['id'])
        api('POST',f'sales-orders/{sale["id"]}/confirm')
        shipment=api('POST','shipments',{'sales_order_id':sale['id'],'warehouse_id':1,'lines':[{'material_id':material,'quantity':'4'}]},201)
        approve_document(client, dict(client.headers), 'Shipment', shipment['id'])
        api('POST',f'shipments/{shipment["id"]}/post')
        yield client,api,admin,supplier,customer,material,order,receipt,sale,shipment


def query(erp,period='7d'):
    return erp[1]('POST','dashboard/query',{'period':period})


def test_real_amounts_precision_pending_and_orm_snapshot(erp):
    result=query(erp)
    assert result['finance']['sales']['current']['amount']=='42.22'
    assert result['finance']['purchase']['current']['amount']=='31.25'
    assert result['sales']=={'draft':0,'waiting':1}
    assert result['purchase']=={'draft':0,'waiting':1}
    assert result['inventory']['positive_positions']==1
    assert result['inventory']['stocked_materials']==1
    assert sum(item['count'] for item in result['composition'])==2
    assert result['from_date']=='2026-09-25' and result['previous_from_date']=='2026-09-18'
    assert len(result['finance']['trend'])==7
    assert sum(Decimal(row['sales']['amount']) for row in result['finance']['trend'])==Decimal('42.22')
    thirty=query(erp,'30d')
    assert len(thirty['finance']['trend'])==30 and thirty['from_date']=='2026-09-02'


def test_cross_period_reversal_does_not_erase_original_day(erp):
    _,api,_,_,_,_,_,_,_,shipment=erp
    approve_document(erp[0], dict(erp[0].headers), 'Shipment', shipment['id'], intent='reverse', reason='原出库更正')
    api('POST',f'shipments/{shipment["id"]}/reverse',{'reason':'原出库更正'},201)
    with orm_session(write=True) as db:
        db.get(Shipment,shipment['id']).posted_at='2026-09-24 23:59:59'
        db.scalar(select(ShipmentReversal).where(ShipmentReversal.shipment_id==shipment['id'])).created_at='2026-09-25 00:00:00'
    result=query(erp)
    assert result['finance']['sales']['previous']['amount']=='42.22'
    assert result['finance']['sales']['current']['amount']=='-42.22'
    assert result['finance']['trend'][0]['sales']['amount']=='-42.22'
    assert result['sales']['waiting']==1
    assert next(item['count'] for item in result['composition'] if item['key']=='shipment')==0
    assert result['finance']['evidence'][0]['source_type'] in ('shipment_reversal','receipt')


def test_missing_price_is_unknown_not_zero_and_future_events_are_excluded(erp):
    _,api,_,supplier,_,material,_,receipt,_,shipment=erp
    free=api('POST','receipts',{'supplier_id':supplier,'lines':[{'material_id':material,'quantity':'1'}]},201)
    # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
    approve_document(erp[0], dict(erp[0].headers), 'Receipt', free['id'])
    api('POST',f'receipts/{free["id"]}/post')
    result=query(erp)
    purchase=result['finance']['purchase']['current']
    assert purchase['amount'] is None and purchase['known_amount']=='31.25' and purchase['unpriced_count']==1
    with orm_session(write=True) as db:
        db.get(Receipt,free['id']).posted_at='2026-10-01 12:00:01'
        db.get(Shipment,shipment['id']).posted_at='2026-10-02 00:00:00'
    result=query(erp)
    assert result['finance']['purchase']['current']['amount']=='31.25'
    assert result['finance']['sales']['current']['amount']=='0.00'
    assert result['finance']['evidence_total']==1


def test_draft_cancelled_and_fully_delivered_orders_do_not_inflate_waiting(erp):
    _,api,_,_,customer,material,_,_,sale,_=erp
    draft=api('POST','sales-orders',{'customer_id':customer,'lines':[{'material_id':material,'quantity':'1','unit_price':'100'}]},201)
    api('POST',f'sales-orders/{draft["id"]}/cancel')
    final=api('POST','shipments',{'sales_order_id':sale['id'],'warehouse_id':1,'lines':[{'material_id':material,'quantity':'6'}]},201)
    approve_document(erp[0], dict(erp[0].headers), 'Shipment', final['id'])
    api('POST',f'shipments/{final["id"]}/post')
    result=query(erp)
    assert result['sales']=={'draft':0,'waiting':0}
    assert result['finance']['sales']['current']['amount']=='105.55'


def test_permissions_apply_to_each_domain_and_live_revocation(erp):
    client,api,_,*_=erp
    role=api('POST','roles',{'code':'dash_reader','label':'销售统计','permissions':['sales.view']},201)
    api('POST','users',{'username':'limited','password':'secure-pass-123','roles':[role['code']]},201)
    token=api('POST','auth/login',{'username':'limited','password':'secure-pass-123'})['token']
    client.headers['Authorization']='Bearer '+token
    result=query(erp)
    assert result['sales']['waiting']==1
    assert result['finance'] is None and result['purchase'] is None and result['inventory'] is None and result['production'] is None
    assert [row['key'] for row in result['composition']]==['shipment']
    with orm_session(write=True) as db:
        db.delete(db.get(RolePermission,('dash_reader','sales.view')))
    result=query(erp)
    assert all(result[key] is None for key in ('sales','purchase','finance','inventory','production'))
    assert result['composition']==[]
    client.headers.clear()
    api('POST','dashboard/query',{'period':'7d'},401)


def test_customer_return_and_correction_keep_daily_net_and_effective_document_count(erp):
    _,api,_,_,_,_,_,_,_,shipment=erp
    row=api('POST','sales-returns',{'shipment_id':shipment['id'],'warehouse_id':1,'reason':'客户退回',
        'lines':[{'shipment_line_id':shipment['lines'][0]['id'],'quantity':'1'}]},201)
    approve_document(erp[0], dict(erp[0].headers), 'SalesReturn', row['id'])
    api('POST',f'sales-returns/{row["id"]}/post')
    assert query(erp)['finance']['sales']['current']['amount']=='31.66'
    approve_document(erp[0], dict(erp[0].headers), 'SalesReturn', row['id'], intent='reverse', reason='退货更正')
    api('POST',f'sales-returns/{row["id"]}/reverse',{'reason':'退货更正'},201)
    result=query(erp)
    assert result['finance']['sales']['current']['amount']=='42.22'
    assert result['finance']['sales']['current']['source_line_count']==3
    assert next(item['count'] for item in result['composition'] if item['key']=='shipment')==1


def test_repair_fee_requires_actual_delivery_and_correction_preserves_original(erp):
    client,api,admin,_,_,_,_,_,_,shipment=erp
    api('POST','users',{'username':'reviewer','password':'secure-pass-123','roles':['finance']},201)
    reviewer=api('POST','auth/login',{'username':'reviewer','password':'secure-pass-123'})['token']
    row=api('POST','after-sales/cases',dict(shipment_line_id=shipment['lines'][0]['id'],reference='DASH-FEE',kind='repair',quantity='1',
        complaint='产品异常',solution='维修后交还',charge_mode='charge',fee_amount='5.50',customer_acceptance='客户同意收费',warehouse_id=None,
        replacement_material_id=None,replacement_quantity=None,replacement_unit_price=None,parts=[],reason='登记客户委托'),201)
    def change(action,**extra):
        nonlocal row
        row=api('POST',f'after-sales/cases/{row["id"]}/{action}',{'version':row['version'],'reason':'核对证据','evidence':'实际检验交接记录',**extra})
    change('submit')
    client.headers['Authorization']='Bearer '+reviewer;change('approve')
    client.headers['Authorization']='Bearer '+admin
    change('receive');change('inspect',inspection_result='pass')
    assert query(erp)['finance']['sales']['current']['amount']=='42.22'
    change('close')
    assert query(erp)['finance']['sales']['current']['amount']=='47.72'
    change('reverse')
    result=query(erp)
    assert result['finance']['sales']['current']['amount']=='42.22'
    assert {'after_sales_repair','after_sales_repair_reversal'} <= {item['source_type'] for item in result['finance']['evidence']}


def test_production_released_in_progress_inspection_and_posting_counts(erp):
    _,api,_,_,_,material,_,_,_,_=erp
    product=api('POST','materials',{'sku':'FINISH','name':'成品','unit':'箱'},201)['id']
    bom=api('POST','boms',{'product_material_id':product,'base_quantity':'1','lines':[{'component_material_id':material,'quantity':'1'}]},201)
    api('POST',f'boms/{bom["id"]}/activate')
    order=api('POST','work-orders',{'bom_id':bom['id'],'warehouse_id':1,'target_quantity':'1'},201)
    assert query(erp)['production']['draft']==1
    approve_document(erp[0], dict(erp[0].headers), 'WorkOrder', order['id'])
    api('POST',f'work-orders/{order["id"]}/release')
    assert query(erp)['production']['released']==1
    issue=api('POST','material-issues',{'work_order_id':order['id'],'warehouse_id':1,'lines':[{'work_order_line_id':order['lines'][0]['id'],'quantity':'1'}]},201)
    approve_document(erp[0], dict(erp[0].headers), 'MaterialIssue', issue['id'])
    api('POST',f'material-issues/{issue["id"]}/post')
    assert query(erp)['production']['released']==1
    completion=api('POST','production-completions',{'work_order_id':order['id'],'reported_quantity':'1'},201)
    assert query(erp)['production']['awaiting_inspection']==1
    api('POST',f'production-completions/{completion["id"]}/inspect',{'accepted_quantity':'1','qc_note':'核对合格'})
    assert query(erp)['production']['awaiting_post']==1
    approve_document(erp[0], dict(erp[0].headers), 'ProductionCompletion', completion['id'])
    api('POST',f'production-completions/{completion["id"]}/post')
    result=query(erp)
    assert result['production']=={'draft':0,'released':0,'awaiting_inspection':0,'awaiting_post':0}
    assert result['inventory']['stocked_materials']==2
    assert next(item['count'] for item in result['composition'] if item['key']=='production_completion')==1


@pytest.mark.parametrize('payload',[{'period':'365d'},{'period':True},{'period':'7d','permissions':['finance.view']},{'from_date':'2000-01-01'}])
def test_query_rejects_untrusted_scope(erp,payload):
    erp[1]('POST','dashboard/query',payload,422)
