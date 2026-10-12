"""采购双向计价的保存、审批冻结、迁移兼容与财务金额回归。"""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.core.database import connection, migrate
from app.core.orm import orm_session
from app.core.models import PurchaseRequestLine
from app.purchase.pricing import PurchasePricingInput, purchase_amount
from app.finance.routes import entry
from approval_test_helpers import approve_document
from test_purchase_requests import setup


def test_price_calculation_boundaries():
    assert PurchasePricingInput(quantity='3', unit_price='.335').line_total == Decimal('1.01')
    line = PurchasePricingInput(quantity='3000', pricing_mode='total', line_total='10')
    assert line.unit_price == Decimal('.003333333333')
    assert line.line_total == Decimal('10.00')
    # 半分必须按原始比例计算，不由近似单价再次乘回。
    assert purchase_amount('1.5', '.003333333333', '3', '.01', 'total') == Decimal('.01')
    assert purchase_amount('3000', str(line.unit_price), '3000', '10', 'total') == Decimal('10.00')
    row = dict(source_line_id=1,party_id=1,party_name='测试',source_id=1,order_id=1,
               material_id=1,sku='TEST',quantity='1.5',unit_price='.003333333333',
               order_quantity='3',order_total='.01',pricing_mode='total',posted_by=1,posted_at='2026-10-12')
    assert entry(row,'payable','receipt',1)['amount'] == '0.01'
    assert entry(row,'payable','receipt_reversal',-1)['amount'] == '-0.01'


@pytest.mark.parametrize('fields', [
    {'quantity':'0'}, {'quantity':'-1'}, {'quantity':'NaN'}, {'quantity':'1.0001'},
    {'quantity':'1000001'}, {'unit_price':'-1'}, {'unit_price':'Infinity'},
    {'unit_price':'.00001'}, {'unit_price':'1000000001'},
    {'pricing_mode':'total'}, {'pricing_mode':'total','line_total':'-1'},
    {'pricing_mode':'total','line_total':'.001'}, {'pricing_mode':'total','line_total':'NaN'},
    {'pricing_mode':'total','line_total':'1000000001'}, {'pricing_mode':'invalid'},
])
def test_invalid_price_is_rejected(fields):
    with pytest.raises(ValueError):
        PurchasePricingInput(**{'quantity':'1', **fields})


def test_request_price_roundtrip_conversion_and_approval_freeze(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'pricing.db'))
    with TestClient(app, client=('127.0.0.1',12345)) as client:
        base, admin, supplier, material = setup(client)
        payload={'lines':[{'material_id':material,'quantity':'3000','pricing_mode':'total','line_total':'10.00'}]}
        created=client.post(base+'/purchase-requests',headers=admin,json=payload)
        assert created.status_code == 201, created.text
        request=created.json();line=request['lines'][0]
        assert line['line_total']=='10.00'
        assert line['unit_price']=='0.003333333333'
        loaded=client.get(base+'/purchase-requests',headers=admin).json()[0]
        assert loaded['lines']==request['lines']
        revised=client.put(f"{base}/purchase-requests/{request['id']}",headers=admin,json=payload)
        assert revised.status_code==200
        line=revised.json()['lines'][0]
        approve_document(client,admin,'PurchaseRequest',request['id'])
        order=client.post(base+'/purchase-orders',headers=admin,json={
            'supplier_id':supplier,'purchase_request_id':request['id'],
            'lines':[{'material_id':material,'purchase_request_line_id':line['id'],
                      'quantity':'3000','pricing_mode':'total','line_total':'10.00'}]})
        assert order.status_code==201,order.text
        assert order.json()['total_amount']=='10.00'
        assert order.json()['lines'][0]['unit_price']=='0.003333333333'
        assert client.put(f"{base}/purchase-requests/{request['id']}",headers=admin,json=payload).status_code==409
        # 修改已批准价格会触发固定正文校验，不能以原批准继续执行。
        other=client.post(base+'/purchase-requests',headers=admin,json=payload).json()
        approve_document(client,admin,'PurchaseRequest',other['id'])
        with orm_session(write=True) as db:
            target=db.scalar(select(PurchaseRequestLine).where(PurchaseRequestLine.purchase_request_id==other['id']))
            target.line_total='11.00'
        tampered=client.post(base+'/purchase-orders',headers=admin,json={
            'supplier_id':supplier,'purchase_request_id':other['id'],
            'lines':[{'material_id':material,'purchase_request_line_id':other['lines'][0]['id'],
                      'quantity':'3000','unit_price':'1'}]})
        assert tampered.status_code==409,tampered.text
        # 空价格申请兼容历史；订单必须有价格，零元则可显式填写。
        legacy=client.post(base+'/purchase-requests',headers=admin,json={'lines':[{'material_id':material,'quantity':'1'}]}).json()
        assert legacy['lines'][0]['unit_price'] is None
        assert client.post(base+'/purchase-orders',headers=admin,json={'supplier_id':supplier,'lines':[{'material_id':material,'quantity':'1'}]}).status_code==422
        assert client.post(base+'/purchase-orders',headers=admin,json={'supplier_id':supplier,'lines':[{'material_id':material,'quantity':'1','unit_price':'0'}]}).status_code==201


def test_upgrade_preserves_old_prices_and_approval(monkeypatch,tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH',str(tmp_path/'upgrade.db'))
    with TestClient(app,client=('127.0.0.1',12345)) as client:
        base,admin,supplier,material=setup(client)
        request=client.post(base+'/purchase-requests',headers=admin,json={'lines':[{'material_id':material,'quantity':'3'}]}).json()
        order=client.post(base+'/purchase-orders',headers=admin,json={'supplier_id':supplier,'lines':[{'material_id':material,'quantity':'3','unit_price':'2.50'}]}).json()
        approve_document(client,admin,'PurchaseRequest',request['id'])
        approve_document(client,admin,'PurchaseOrder',order['id'])
        with connection() as db:
            # 结构回退用于真实重放升级，不通过修改业务价格模拟迁移。
            for table in ('purchase_request_lines','purchase_order_lines'):
                for column in ('pricing_mode','line_total'):
                    db.execute(f'ALTER TABLE {table} DROP COLUMN {column}')
            db.execute('ALTER TABLE purchase_request_lines DROP COLUMN unit_price')
            db.execute('PRAGMA user_version=101')
        migrate();migrate()
        loaded=client.get(base+'/purchase-orders',headers=admin).json()[0]
        assert loaded['total_amount']=='7.50'
        assert loaded['lines'][0]['unit_price']=='2.50'
        assert client.post(f"{base}/purchase-orders/{order['id']}/confirm",headers=admin).status_code==200
        converted=client.post(base+'/purchase-orders',headers=admin,json={'supplier_id':supplier,'purchase_request_id':request['id'],
            'lines':[{'material_id':material,'purchase_request_line_id':request['lines'][0]['id'],'quantity':'1','unit_price':'2'}]})
        assert converted.status_code==201,converted.text


def test_total_priced_receipt_and_return_use_original_amount(monkeypatch,tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH',str(tmp_path/'financial-pricing.db'))
    with TestClient(app,client=('127.0.0.1',12345)) as client:
        base,admin,supplier,material=setup(client)
        order=client.post(base+'/purchase-orders',headers=admin,json={'supplier_id':supplier,
            'lines':[{'material_id':material,'quantity':'3','pricing_mode':'total','line_total':'.01'}]}).json()
        approve_document(client,admin,'PurchaseOrder',order['id'])
        assert client.post(f"{base}/purchase-orders/{order['id']}/confirm",headers=admin).status_code==200
        receipt=client.post(base+'/receipts',headers=admin,json={'supplier_id':supplier,'warehouse_id':1,
            'purchase_order_id':order['id'],'lines':[{'material_id':material,'quantity':'1.5'}]}).json()
        approve_document(client,admin,'Receipt',receipt['id'])
        assert client.post(f"{base}/receipts/{receipt['id']}/post",headers=admin).status_code==200
        from app.finance.routes import financial_entries
        with orm_session() as db:
            assert financial_entries(db)[0]['amount']=='0.01'
            from app.inventory.valuation import calculate_valuation
            assert calculate_valuation(db).report['movements'][0]['amount']=='0.01'
        returned=client.post(base+'/purchase-returns',headers=admin,json={'receipt_id':receipt['id'],
            'reason':'价格回归测试','lines':[{'receipt_line_id':receipt['lines'][0]['id'],'quantity':'1.5'}]})
        assert returned.status_code==201,returned.text
        assert returned.json()['total_amount']=='0.01'
