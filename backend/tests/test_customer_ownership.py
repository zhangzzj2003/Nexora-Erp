"""客户私有、订单共享、金额独立授权及转交并发的真实接口回归。"""
from fastapi.testclient import TestClient
from app.main import app
from app.core.orm import orm_session
from app.core.models import CustomerChange
from sqlalchemy import select


def test_customer_scope_order_money_and_transfers(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'ownership.db'))
    with TestClient(app, client=('127.0.0.1', 12345)) as client:
        base='/api/v1'
        client.post(base+'/setup/admin', json={'username':'admin','password':'admin-password-123'})
        def login(name):
            token=client.post(base+'/auth/login',json={'username':name,'password':name+'-password-123'}).json()['token']
            return {'Authorization':'Bearer '+token}
        admin=login('admin')
        ids={}
        for name,role in [('alice','seller'),('bob','seller'),('finance','finance'),('warehouse','warehouse'),('planner','planner')]:
            ids[name]=client.post(base+'/users',headers=admin,json={'username':name,'password':name+'-password-123','roles':[role]}).json()['id']
        alice,bob,finance,warehouse=[login(name) for name in ('alice','bob','finance','warehouse')]
        customer=client.post(base+'/customers',headers=alice,json={'name':'客户甲','contact_name':'联系人甲','phone':'13800138000','address':'私有地址'}).json()
        cid=customer['id']
        assert customer['owner_id']==ids['alice']
        assert client.get(base+'/customers',headers=bob).json()==[]
        assert client.get(f'{base}/customers/{cid}',headers=bob).status_code==404
        assert client.get(f'{base}/customers/{cid}/history',headers=bob).status_code==404
        assert client.post(base+'/customers',headers=bob,json={'name':'越权','owner_id':ids['alice']}).status_code==403
        assert client.get(base+'/customers',headers=warehouse).status_code==403
        material=client.post(base+'/materials',headers=admin,json={'sku':'A','name':'物料','unit':'件'}).json()['id']
        supplier=client.post(base+'/suppliers',headers=admin,json={'name':'测试供应商'}).json()['id']
        receipt=client.post(base+'/receipts',headers=admin,json={'supplier_id':supplier,'warehouse_id':1,'lines':[{'material_id':material,'quantity':'5'}]}).json()['id']
        assert client.post(f'{base}/receipts/{receipt}/post',headers=admin).status_code==200
        payload={'customer_id':cid,'lines':[{'material_id':material,'quantity':'2','unit_price':'123.45'}]}
        assert client.post(base+'/sales-orders',headers=bob,json=payload).status_code==404
        created=client.post(base+'/sales-orders',headers=alice,json=payload)
        assert created.status_code==201,created.text
        order=created.json()
        oid=order['id']
        # 列表和写操作返回值都脱敏；数量和协作进度继续可见。
        shared=client.get(base+'/sales-orders',headers=bob).json()[0]
        assert shared['customer_name']=='客户甲' and shared['lines'][0]['quantity']=='2'
        assert shared['amount_visible'] is False and shared['total_amount'] is None
        assert shared['lines'][0]['unit_price'] is None and shared['lines'][0]['line_total'] is None
        planned=client.get(base+'/sales-orders',headers=login('planner'))
        assert planned.status_code==200 and planned.json()[0]['total_amount'] is None
        assert 'contact_name' not in shared and 'address' not in shared
        confirmed=client.post(f'{base}/sales-orders/{oid}/confirm',headers=bob).json()
        assert confirmed['amount_visible'] is False and confirmed['total_amount'] is None
        assert client.get(base+'/sales-orders',headers=finance).json()[0]['total_amount']=='246.90'
        shipment=client.post(base+'/shipments',headers=warehouse,json={'sales_order_id':oid,'warehouse_id':1,'lines':[{'material_id':material,'quantity':'1'}]}).json()['id']
        assert client.post(f'{base}/shipments/{shipment}/post',headers=warehouse).status_code==200
        line=client.get(base+'/shipments',headers=warehouse).json()[0]['lines'][0]['id']
        returned=client.post(base+'/sales-returns',headers=bob,json={'shipment_id':shipment,'warehouse_id':1,'reason':'退回','lines':[{'shipment_line_id':line,'quantity':'1'}]})
        assert returned.status_code==201,returned.text
        assert returned.json()['total_amount'] is None
        posted=client.post(f"{base}/sales-returns/{returned.json()['id']}/post",headers=warehouse)
        assert posted.status_code==200,posted.text
        assert posted.json()['lines'][0]['unit_price'] is None
        assert client.get(base+'/sales-returns',headers=alice).json()[0]['total_amount']=='123.45'

        # 客户转交不会连带转交订单金额；旧负责商务不可继续访问客户档案。
        update={**customer,'owner_id':ids['bob'],'reason':'商务转交'}
        saved=client.put(f'{base}/customers/{cid}',headers=admin,json=update)
        assert saved.status_code==200,saved.text
        assert client.put(f'{base}/customers/{cid}',headers=admin,json=update).status_code==409
        assert client.get(f'{base}/customers/{cid}',headers=alice).status_code==404
        assert client.get(base+'/sales-orders',headers=alice).json()[0]['amount_visible'] is True
        assert client.get(base+'/sales-orders',headers=bob).json()[0]['amount_visible'] is False
        transfer={'owner_id':ids['bob'],'version':order['owner_version'],'reason':'订单一并转交'}
        url=f'{base}/customers/orders/{oid}/owner'
        assert client.put(url,headers=bob,json=transfer).status_code==403
        assert client.put(url,headers=admin,json=transfer).status_code==200
        assert client.put(url,headers=admin,json=transfer).status_code==409
        assert client.get(base+'/sales-orders',headers=alice).json()[0]['amount_visible'] is False
        assert client.get(base+'/sales-orders',headers=bob).json()[0]['amount_visible'] is True
        current=saved.json()
        assert client.put(f'{base}/customers/{cid}',headers=bob,json={**current,'is_active':False,'reason':'暂不合作'}).status_code==200
        assert client.post(base+'/sales-orders',headers=bob,json=payload).status_code==409
        with orm_session() as db:
            changes=list(db.scalars(select(CustomerChange).where(CustomerChange.customer_id==cid)))
            assert [row.action for row in changes]==['create','transfer','order_transfer','update']


def test_finance_permission_cannot_bypass_amount_scope(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path/'no-bypass.db'))
    with TestClient(app, client=('127.0.0.1',12345)) as client:
        base='/api/v1'
        client.post(base+'/setup/admin',json={'username':'admin','password':'admin-password-123'})
        def login(name):
            return {'Authorization':'Bearer '+client.post(base+'/auth/login',json={'username':name,'password':name+'-password-123'}).json()['token']}
        admin=login('admin')
        role=client.post(base+'/roles',headers=admin,json={'code':'limited','label':'受限查看','permissions':['finance.view','sales.view','journal.view']})
        assert role.status_code==201,role.text
        client.post(base+'/users',headers=admin,json={'username':'limited','password':'limited-password-123','roles':['limited']})
        limited=login('limited')
        for path in ('finance/overview','finance/receivables-payables','finance/payment-records','finance/accounts','finance/journals'):
            assert client.get(base+'/'+path,headers=limited).status_code==403
