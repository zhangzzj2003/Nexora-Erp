"""单据关联不推断实际耗用；跨供应商批号、权限与冲销历史保持清晰。"""

import pytest
from decimal import Decimal
from app.core.orm import orm_session
from app.core.models import Receipt,ReceiptLine,PhysicalLotMovementEvidence,StockMovement
from sqlalchemy import select
from approval_test_helpers import approve_document
from test_production_settlements import erp


def test_normal_production_can_query_without_lots_and_never_guesses_supplier(erp):
    client,headers,api,material,receipt,order,complete=erp
    raw,product=material('REF-RAW'),material('REF-PRODUCT');receipt(raw,'100');receipt(raw,'500')
    work,issue=order(raw,product,'200');completions=[complete(work,'100','100') for _ in range(2)]
    row=api('GET',f'work-orders/{work["id"]}/associations')
    component=row['components'][0]
    assert Decimal(component['required_quantity'])==Decimal('200') and component['net_issued_quantity']=='200'
    assert component['issues'][0]['sources']==[] and component['issues'][0]['unassigned_quantity']=='200'
    assert component['purchase_references']==[] and row['scope']=='work_order'
    completion=api('GET',f'production-completions/{completions[1]}/associations?include_references=true')
    assert completion['target']=={'kind':'completion','id':completions[1]} and len(completion['completions'])==2
    assert sorted(Decimal(r['quantity']) for r in completion['components'][0]['purchase_references'])==[Decimal('100'),Decimal('500')]
    # 同物料的两笔采购只能参考，不会自动变成产品或完工单的实际物料来源。
    assert completion['components'][0]['issues'][0]['sources']==[]
    assert 'unit_cost' not in str(row) and 'amount' not in str(row)


@pytest.fixture
def tracked(erp):
    client,headers,api,material,*_=erp;raw,product=material('TRACK-RAW'),material('TRACK-PRODUCT')
    sources=[]
    for index,quantity in enumerate(('100','500')):
        supplier=api('POST','suppliers',{'name':f'不同供应商-{index}'},201)
        row=api('POST','receipts',{'supplier_id':supplier['id'],'lines':[{'material_id':raw,'quantity':quantity}]},201)
        approve_document(client,headers,'Receipt',row['id'])
        posted=api('POST',f'receipts/{row["id"]}/post',{'lines':[{'receipt_line_id':row['lines'][0]['id'],
            'lots':[{'quantity':quantity,'supplier_lot':'SAME-SUPPLIER-CODE'}]}]})
        sources.append((supplier,row,posted['lines'][0]['physical_lots'][0]['id']))
    bom=api('POST','boms',{'product_material_id':product,'base_quantity':'1','lines':[{'component_material_id':raw,'quantity':'1'}]},201)
    api('POST',f'boms/{bom["id"]}/activate')
    work=api('POST','work-orders',{'bom_id':bom['id'],'warehouse_id':1,'target_quantity':'200'},201)
    approve_document(client,headers,'WorkOrder',work['id']);api('POST',f'work-orders/{work["id"]}/release')
    issue=api('POST','material-issues',{'work_order_id':work['id'],'warehouse_id':1,'lines':[{'work_order_line_id':work['lines'][0]['id'],'quantity':'200'}]},201)
    approve_document(client,headers,'MaterialIssue',issue['id'])
    api('POST',f'material-issues/{issue["id"]}/post',{'lines':[{'material_issue_line_id':issue['lines'][0]['id'],
        'lots':[{'lot_id':lot,'quantity':'100'} for _,_,lot in sources]}]})
    return erp,work,issue,sources


def test_mixed_lots_preserve_two_exact_receipts_and_return_history(tracked):
    erp,work,issue,sources=tracked;client,headers,api,*_=erp
    row=api('GET',f'work-orders/{work["id"]}/associations');parts=row['components'][0]['issues'][0]['sources']
    assert len(parts)==2 and {r['source_id'] for r in parts}=={r['id'] for _,r,_ in sources}
    assert {r['supplier_id'] for r in parts}=={supplier['id'] for supplier,_,_ in sources}
    assert all(r['quantity']=='100' and r['source_document_no'] for r in parts)
    returned=api('POST','material-returns',{'material_issue_id':issue['id'],'reason':'退回多领','lines':[{'material_issue_line_id':issue['lines'][0]['id'],'quantity':'50'}]},201)
    approve_document(client,headers,'MaterialReturn',returned['id']);api('POST',f'material-returns/{returned["id"]}/post')
    current=api('GET',f'work-orders/{work["id"]}/associations')['components'][0]
    assert current['net_issued_quantity']=='150' and current['issues'][0]['returned_quantity']=='50'
    assert current['issues'][0]['returns'][0]['document_no']==returned['document_no']
    # 未归批次退料不会被任意摊回某个来源，也不会声称每台成品消耗 75 件。
    assert [r['quantity'] for r in current['issues'][0]['sources']]==['100','100']
    approve_document(client,headers,'MaterialReturn',returned['id'],intent='reverse',reason='更正退料')
    api('POST',f'material-returns/{returned["id"]}/reverse',{'reason':'更正退料'},201)
    current=api('GET',f'work-orders/{work["id"]}/associations')['components'][0]
    assert current['net_issued_quantity']=='200' and current['issues'][0]['returns'][0]['status']=='reversed'


def test_source_queries_follow_permissions_and_positive_ids(tracked):
    erp,work,*_=tracked;client,headers,api,*_=erp
    api('POST','roles',{'code':'production_reader','label':'仅看生产','permissions':['production.view']},201)
    api('POST','users',{'username':'observer','password':'secure-pass-123','roles':['production_reader']},201)
    token=client.post('/api/v1/auth/login',json={'username':'observer','password':'secure-pass-123'}).json()['token']
    response=client.get(f'/api/v1/work-orders/{work["id"]}/associations?include_references=true',headers={'Authorization':'Bearer '+token})
    assert response.status_code==200,response.text;row=response.json()
    assert not row['inventory_visible'] and not row['references_included']
    assert row['components'][0]['issues'][0]['sources']==[] and row['components'][0]['purchase_references']==[]
    assert row['components'][0]['issues'][0]['unassigned_quantity'] is None
    assert '不同供应商' not in response.text and 'supplier_id' not in response.text
    assert client.get(f'/api/v1/work-orders/{work["id"]}/associations').status_code==401
    api('GET','work-orders/0/associations',status=422);api('GET','production-completions/999/associations',status=404)


def test_purchase_references_are_bounded_and_not_current_stock(erp):
    _,_,api,material,receipt,order,_=erp;raw,product=material('BOUNDED-RAW'),material('BOUNDED-PRODUCT')
    receipt(raw,'1');work,_=order(raw,product)
    with orm_session(write=True) as db:
        original=db.scalar(select(Receipt))
        for index in range(55):
            row=Receipt(supplier_id=original.supplier_id,status='posted',reference=f'OLD-{index}',created_by=1,posted_at='2020-01-01 00:00:00')
            db.add(row);db.flush();db.add(ReceiptLine(receipt_id=row.id,material_id=raw,quantity='1'))
        row=Receipt(supplier_id=original.supplier_id,status='posted',reference='FUTURE',created_by=1,posted_at='2999-01-01 00:00:00')
        db.add(row);db.flush();db.add(ReceiptLine(receipt_id=row.id,material_id=raw,quantity='1'))
    row=api('GET',f'work-orders/{work["id"]}/associations?include_references=true')
    assert len(row['components'][0]['purchase_references'])==50 and row['reference_limit']==50
    assert all(r['posted_at']<'2999' for r in row['components'][0]['purchase_references'])


def test_late_evidence_and_its_reversal_do_not_guess_unknown_origins(erp):
    _,_,api,material,receipt,order,_=erp
    raw,product=material('LATE-RAW'),material('LATE-PRODUCT')
    origin_id=receipt(raw,'2')
    work,issue=order(raw,product)
    with orm_session() as db:
        movement_id=db.scalar(select(StockMovement.id).where(StockMovement.source_type=='material_issue',StockMovement.source_id==issue['id']))
    base='inventory/physical-lots'
    pair=api('POST',f'{base}/evidence-pairs',{'inbound_movement_id':origin_id,'outbound_movement_id':movement_id,'quantity':'1','evidence':'现场签收标签与领用交接记录逐件核对'},201)
    component=api('GET',f'work-orders/{work["id"]}/associations')['components'][0]
    source=component['issues'][0]['sources'][0]
    assert source['evidence_kind']=='supplement' and source['supplier_id'] and source['source_document_no']
    assert Decimal(component['issues'][0]['unassigned_quantity'])==0
    api('POST',f'{base}/evidence-pairs/{pair["id"]}/reverse',{'reason':'原领料包装标签辨认有误'},201)
    component=api('GET',f'work-orders/{work["id"]}/associations')['components'][0]
    assert component['issues'][0]['sources']==[] and Decimal(component['issues'][0]['unassigned_quantity'])==1


def test_unknown_origin_lot_never_guesses_a_supplier_receipt(tracked):
    erp,work,issue,sources=tracked
    _,_,api,*_=erp
    # 模拟历史批次缺失原始采购流水；外部批号相同也不能借同物料采购记录补猜来源。
    from app.core.models import PhysicalLot
    with orm_session(write=True) as db:
        lot=db.get(PhysicalLot,sources[0][2]);lot.origin_movement_id=None
    parts=api('GET',f'work-orders/{work["id"]}/associations')['components'][0]['issues'][0]['sources']
    unknown=next(part for part in parts if part['lot_id']==sources[0][2])
    assert unknown['supplier_id'] is None and unknown['source_document_no'] is None
    assert next(part for part in parts if part['lot_id']==sources[1][2])['supplier_id'] is not None
