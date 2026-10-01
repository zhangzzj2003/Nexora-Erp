"""排程冲突、质量数量占用、全不合格成本去向与重复缺料申请。"""
from test_ledger_foundation import ledger
from app.core.orm import orm_session,add_model
from app.core import models as m
from sqlalchemy import select


def tool(client,action,payload):return client.post('/api/v1/production/tools',json={'action':action,'payload':payload})


def snapshot_rows(client,result):return client.post('/api/v1/tables/query',json={'dataset':'snapshot','snapshot_id':result['snapshot_id'],'page':1,'page_size':100}).json()['items']


def seed(client):
    product=client.post('/api/v1/materials',json={'sku':'PLAN-P','name':'计划成品','unit':'件'}).json()['id']
    component=client.post('/api/v1/materials',json={'sku':'PLAN-C','name':'计划组件','unit':'件'}).json()['id']
    bom=client.post('/api/v1/boms',json={'product_material_id':product,'base_quantity':'1','lines':[{'component_material_id':component,'quantity':'2'}]}).json()['id']
    assert client.post(f'/api/v1/boms/{bom}/activate').status_code==200
    order=client.post('/api/v1/work-orders',json={'bom_id':bom,'warehouse_id':1,'target_quantity':'1'}).json()['id']
    return product,component,bom,order


def test_schedule_conflict_and_version(ledger):
    _,_,_,order=seed(ledger)
    center=tool(ledger,'create_center',{'name':'工作中心A','reason':'建档'})
    cid=snapshot_rows(ledger,center.json())[0]['id']
    payload={'work_order_id':order,'center_id':cid,'operation':'装配','starts_at':'2026-10-02T08:00:00+08:00','ends_at':'2026-10-02T09:00:00+08:00','reason':'生产安排'}
    first=tool(ledger,'schedule',payload);assert first.status_code==200,first.text
    assert tool(ledger,'schedule',payload).status_code==409
    second=tool(ledger,'schedule',{**payload,'starts_at':'2026-10-02T09:00:00+08:00','ends_at':'2026-10-02T10:00:00+08:00'});assert second.status_code==200
    row=snapshot_rows(ledger,first.json())[0]
    assert tool(ledger,'schedule',{**payload,'id':row['id'],'version':99}).status_code==409
    assert tool(ledger,'cancel_schedule',{'id':row['id'],'reason':'调整产期'}).status_code==200


def test_mrp_request_recalculates_and_does_not_duplicate(ledger):
    _,component,_,_=seed(ledger)
    scope={'warehouse_id':1,'through_date':'2026-10-10'}
    result=tool(ledger,'mrp',scope);assert result.status_code==200,result.text
    row=next(row for row in snapshot_rows(ledger,result.json()) if row['material_id']==component)
    assert row['shortage_quantity']=='2.000'
    assert tool(ledger,'create_request',scope).status_code==200
    assert tool(ledger,'create_request',scope).status_code==409


def test_all_rejected_scrap_can_settle_without_finished_stock(ledger):
    _,_,_,order=seed(ledger)
    with orm_session(write=True) as db:
        work=db.get(m.WorkOrder,order);work.status='completed'
        completion=add_model(db,m.ProductionCompletion(work_order_id=order,reported_quantity='1',accepted_quantity='0',rejected_quantity='1',status='posted',qc_note='全部不合格',created_by=1,inspected_by=1,posted_by=1,posted_at='2026-10-01 00:00:00'))
        db.add(m.ProductionCostEntry(work_order_id=order,kind='labor',amount='10.00',reference='ALL-FAIL-LABOR',note='',created_by=1));cid=completion.id
    payload={'completion_id':cid,'kind':'scrap','quantity':'1','reason':'质量报废'}
    result=tool(ledger,'quality',payload);assert result.status_code==200,result.text
    assert tool(ledger,'quality',payload).status_code==409
    settled=ledger.post('/api/v1/production-costs/settlements',json={'work_order_id':order,'reference':'ALL-FAIL-SETTLE','note':'全部报废'})
    assert settled.status_code==201,settled.text
    assert settled.json()['accepted_quantity']=='0' and settled.json()['allocations']==[]
    assert settled.json()['quality_costs'][0]['amount']=='10.00'


def test_mrp_deducts_existing_stock_exactly_once(ledger):
    # 两件需求只有一件库存，必须仍报告一件缺口，不能把库存重复抵扣。
    _,component,_,_=seed(ledger)
    with orm_session(write=True) as db:
        db.add(m.StockMovement(warehouse_id=1,material_id=component,quantity='1',source_type='test_opening',source_id=1,source_line_id=1,created_by=1))
    report=tool(ledger,'mrp',{'warehouse_id':1,'through_date':'2026-10-10'})
    assert report.status_code==200,report.text
    row=next(row for row in snapshot_rows(ledger,report.json()) if row['material_id']==component)
    assert row['stock_quantity']=='1' and row['shortage_quantity']=='1.000'


def test_rework_carries_parent_cost_and_requires_parent_settlement(ledger):
    product,_,_,order=seed(ledger)
    with orm_session(write=True) as db:
        db.get(m.WorkOrder,order).status='completed'
        completion=add_model(db,m.ProductionCompletion(work_order_id=order,reported_quantity='1',accepted_quantity='0',rejected_quantity='1',status='posted',qc_note='返工',created_by=1,inspected_by=1,posted_by=1,posted_at='2026-10-01 00:00:00'))
        db.add(m.ProductionCostEntry(work_order_id=order,kind='labor',amount='12.50',reference='PARENT-LABOR',note='',created_by=1));cid=completion.id
    result=tool(ledger,'quality',{'completion_id':cid,'kind':'rework','quantity':'1','reason':'返工修复'})
    assert result.status_code==200,result.text
    child=snapshot_rows(ledger,result.json())[0]['rework_order_id']
    from app.production.quality_costs import carried_cost
    with orm_session() as db:assert carried_cost(db,child)[0] is None
    settled=ledger.post('/api/v1/production-costs/settlements',json={'work_order_id':order,'reference':'PARENT-SETTLE','note':''})
    assert settled.status_code==201,settled.text
    with orm_session() as db:assert str(carried_cost(db,child)[0])=='12.50'
    # 返工结算固化父成本之后，须先冲销返工结算才能更正父成本。
    with orm_session(write=True) as db:
        db.get(m.WorkOrder,child).status='completed'
        finish=add_model(db,m.ProductionCompletion(work_order_id=child,reported_quantity='1',accepted_quantity='1',rejected_quantity='0',status='posted',created_by=1,inspected_by=1,posted_by=1))
        db.add(m.StockMovement(warehouse_id=1,material_id=product,quantity='1',source_type='production_completion',source_id=finish.id,source_line_id=finish.id,created_by=1))
    child_settlement=ledger.post('/api/v1/production-costs/settlements',json={'work_order_id':child,'reference':'CHILD-SETTLE','note':''})
    assert child_settlement.status_code==201,child_settlement.text
    assert child_settlement.json()['total_amount']=='12.50'
    assert ledger.post(f"/api/v1/production-costs/settlements/{settled.json()['id']}/reverse",json={'reason':'更正'}).status_code==409
