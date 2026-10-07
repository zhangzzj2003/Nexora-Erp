"""预计成本不能生效；独立批准后才能计价，实时来源与故障保持事务一致。"""

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session
from app.core.models import DocumentApprovalEvent
from app.core.orm import orm_session
from approval_test_helpers import approve_document, execute_production_settlement
from test_production_settlements import erp
from test_journal_document_approval import reviewer

BASE='production-costs/settlements'
APPROVAL='system/document-approvals/ProductionCostSettlement'


@pytest.fixture
def costs(erp):
    client,headers,api,material,receipt,order,complete=erp
    client.headers.update(headers)
    raw,product=material('QA-RAW'),material('QA-PRODUCT');receipt(raw,'10','2.5555')
    work,issue=order(raw,product,'3');finished=[complete(work) for _ in range(3)]
    for kind,amount in [('labor','0.01'),('overhead','0.02')]:api('POST','production-costs/charges',{'work_order_id':work['id'],'kind':kind,'amount':amount,'reference':kind},201)
    return erp,work,issue,product,finished


def new(costs,reference='COST'):
    erp,work,*_=costs
    return erp[2]('POST',BASE,{'work_order_id':work['id'],'reference':reference},201)


def test_three_steps_planned_costs_do_not_change_inventory_or_lock_sources(costs):
    erp,work,issue,product,_=costs;client,headers,api,*_=erp;row=new(costs)
    api('PUT','system/document-approvals/ProductionCostSettlement',{'version':1,'steps':[{'name':n,'role':None} for n in ('审核','核准','批准')]})
    assert row['status']=='draft' and row['total_amount']=='7.70'
    assert [a['amount'] for a in row['allocations']]==['2.57','2.56','2.57']
    report=api('GET','inventory/valuation');assert next(m for m in report['materials'] if m['id']==product)['amount'] is None
    assert api('GET','production-costs')['orders'][0]['settlement_id'] is None
    api('POST',f'{BASE}/{row["id"]}/post',{'version':1,'reason':'提前结算'},409)
    state=api('POST',f'{APPROVAL}/{row["id"]}/submit',{'version':0,'reason':'复核分摊来源'})
    api('POST',f'{APPROVAL}/{row["id"]}/approve',{'version':state['version'],'reason':'自己批准'},403)
    for i in range(3):
        actor=reviewer(client,f'cost_reviewer_{i}')
        r=client.post('/api/v1/'+f'{APPROVAL}/{row["id"]}/approve',headers=actor,json={'version':state['version'],'reason':'核对来源成本'})
        assert r.status_code==200,r.text;state=r.json()
        if i<2:assert client.post('/api/v1/'+f'{APPROVAL}/{row["id"]}/approve',headers=actor,json={'version':state['version'],'reason':'重复批准'}).status_code==403
    assert state['status']=='approved' and api('GET','production-costs')['orders'][0]['settlement_id'] is None
    row=api('POST',f'{BASE}/{row["id"]}/post',{'version':1,'reason':'复核正式结算'})
    assert row['status']=='active' and row['version']==2 and row['executed_at'] and row['approval']['status']=='executed'
    assert next(m for m in api('GET','inventory/valuation')['materials'] if m['id']==product)['amount']=='7.70'
    api('POST','production-costs/charges',{'work_order_id':work['id'],'kind':'labor','amount':'1','reference':'LATE'},409)
    assert api('GET',f'{APPROVAL}/{row["id"]}')['content_matches']


def test_changed_cost_requires_new_draft_and_cancel_retains_number(costs):
    erp,work,*_=costs;client,headers,api,*_=erp;row=new(costs)
    approve_document(client,headers,'ProductionCostSettlement',row['id'],reason='核对成本')
    api('POST','production-costs/charges',{'work_order_id':work['id'],'kind':'labor','amount':'1','reference':'LATE'},201)
    assert not api('GET',f'{APPROVAL}/{row["id"]}')['content_matches']
    api('POST',f'{BASE}/{row["id"]}/post',{'version':1,'reason':'已过期批准'},409)
    state=api('GET',f'{APPROVAL}/{row["id"]}')
    api('POST',f'{APPROVAL}/{row["id"]}/withdraw',{'version':state['version'],'reason':'成本变化'})
    api('POST',f'{BASE}/{row["id"]}/cancel',{'version':1,'reason':'重新核对来源'})
    later=new(costs,reference='COST-NEW')
    assert later['document_no']!=row['document_no'] and later['total_amount']=='8.70'
    assert execute_production_settlement(client,headers,later)['status']=='active'


def test_execution_event_failure_rolls_back_inventory_and_lock(costs):
    erp,work,_,product,_=costs;client,headers,api,*_=erp;row=new(costs)
    approve_document(client,headers,'ProductionCostSettlement',row['id'],reason='核对成本')
    def fail(session,_,__):
        if any(isinstance(r,DocumentApprovalEvent) and r.action=='execute' for r in session.new):raise RuntimeError('结算审计失败')
    event.listen(Session,'before_flush',fail)
    try:
        with pytest.raises(RuntimeError,match='结算审计失败'):
            client.post('/api/v1/'+f'{BASE}/{row["id"]}/post',headers=headers,json={'version':1,'reason':'执行成本'})
    finally:event.remove(Session,'before_flush',fail)
    current=api('GET',BASE)[0]
    assert current['status']=='draft' and current['version']==1 and current['executed_at'] is None and current['approval']['status']=='approved'
    assert next(m for m in api('GET','inventory/valuation')['materials'] if m['id']==product)['amount'] is None
    assert api('POST',f'{BASE}/{row["id"]}/post',{'version':1,'reason':'重试执行'})['status']=='active'


def test_concurrent_approved_drafts_only_one_can_lock_work_order(costs):
    from concurrent.futures import ThreadPoolExecutor
    client,headers,*_=costs[0]
    rows=[new(costs,reference=f'RACE-{i}') for i in range(2)]
    for row in rows:approve_document(client,headers,'ProductionCostSettlement',row['id'],reason='核对同工单')
    # 两张预计草稿都可核对，但同一工单只能有一张当前正式结算。
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes=list(pool.map(lambda row:client.post('/api/v1/'+f'{BASE}/{row["id"]}/post',headers=headers,
            json={'version':1,'reason':'并行正式结算'}).status_code,rows))
    assert sorted(codes)==[200,409]
    assert sum(r['status']=='active' for r in costs[0][2]('GET',BASE))==1


def test_reversal_needs_separate_approval_and_keeps_original_plan(costs):
    client,headers,api,*_=costs[0];row=execute_production_settlement(client,headers,new(costs))
    api('POST',f'{BASE}/{row["id"]}/reverse',{'reason':'原结算需更正'},409)
    state=api('POST',f'{APPROVAL}/{row["id"]}/submit',{'version':0,'intent':'reverse','reason':'原结算需更正'})
    api('POST',f'{APPROVAL}/{row["id"]}/approve',{'version':state['version'],'intent':'reverse','reason':'自己更正自己批准'},403)
    actor=reviewer(client,'cost_reverse_reviewer')
    response=client.post('/api/v1/'+f'{APPROVAL}/{row["id"]}/approve',headers=actor,
        json={'version':state['version'],'intent':'reverse','reason':'独立核对更正'})
    assert response.status_code==200,response.text
    api('POST',f'{BASE}/{row["id"]}/reverse',{'reason':'替换批准原因'},409)
    result=api('POST',f'{BASE}/{row["id"]}/reverse',{'reason':'原结算需更正'})
    assert result['status']=='reversed' and result['version']==3 and result['document_no']==row['document_no']
    assert result['total_amount']==row['total_amount'] and result['allocations']==row['allocations']
    assert result['approval']['status']=='executed' and result['reversal_approval']['status']=='executed'
    assert api('GET','production-costs')['orders'][0]['settlement_id'] is None
    api('POST',f'{BASE}/{row["id"]}/reverse',{'reason':'原结算需更正'},409)


def test_legacy_v92_preserves_cost_plan_number_and_no_fabricated_review(costs):
    from app.core.database import connection,migrate
    row=new(costs);client,headers,api,*_=costs[0]
    # 结构迁移夹具模拟旧库字段；业务快照、子分摊及原编号均不重算。
    with connection() as db:
        for column in ('status','version','executed_by','executed_at','cancelled_by','cancelled_at','cancellation_reason'):
            db.execute(f'ALTER TABLE production_cost_settlements DROP COLUMN {column}')
        before=tuple(db.execute('SELECT * FROM production_cost_settlements').fetchone())
        allocations=[tuple(r) for r in db.execute('SELECT * FROM production_cost_allocations')]
        db.execute('PRAGMA user_version=92')
    migrate();migrate()
    with connection() as db:
        after=db.execute('SELECT * FROM production_cost_settlements').fetchone()
        assert tuple(after)[:len(before)]==before and after['status']=='active' and after['executed_by']==after['created_by']
        assert after['executed_at']==after['created_at']
        assert [tuple(r) for r in db.execute('SELECT * FROM production_cost_allocations')]==allocations
        assert db.execute('SELECT COUNT(*) FROM document_approval_cases WHERE document_type=?',('ProductionCostSettlement',)).fetchone()[0]==0
    current=api('GET',BASE)[0]
    assert current['document_no']==row['document_no'] and current['total_amount']==row['total_amount']
    assert current['approval']['status']=='draft' and api('GET',f'{APPROVAL}/{row["id"]}')['events']==[]
