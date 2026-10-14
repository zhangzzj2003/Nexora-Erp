"""生产物料实际收发、签收差额、独立审批与重复请求的行为验收。"""
from decimal import Decimal
from uuid import uuid4
import pytest
from approval_test_helpers import approve_document
from test_production_settlements import erp
from test_production_material_accounting import create_order,execute,receipts


def new_request():
    return str(uuid4())


def new_exchange(api,order,receipt,quantity='2',**extra):
    return api('POST','material-exchanges',{'work_order_id':order['id'],'warehouse_id':1,
        'request_id':new_request(),'reason':'装配损坏需等量换新','lines':[{'work_order_line_id':order['lines'][0]['id'],
        'source_receipt_line_id':receipt['lines'][0]['id'],'quantity':quantity,**extra}]},201)


def test_exchange_100_machines_batch_replacement_and_receipt_completion(erp):
    client,headers,api,*_=erp
    raw,_,order,dispatch=create_order(erp)
    execute(api,'material-dispatches',dispatch,'100')
    receipt=execute(api,'material-receipts',receipts(api,order)[0],'100')
    exchange=new_exchange(api,order,receipt)
    api('POST',f'material-exchanges/{exchange["id"]}/execute',{'version':1,'request_id':new_request(),
        'lines':[{'line_id':exchange['lines'][0]['id'],'quantity':'1'}]},409)
    approve_document(client,headers,'MaterialExchange',exchange['id'])
    exchange=execute(api,'material-exchanges',exchange,'1')
    assert Decimal(exchange['lines'][0]['replacement_available_quantity'])==1
    for index in range(2):
        if index:
            exchange=api('GET',f'material-exchanges/{exchange["id"]}')
            exchange=execute(api,'material-exchanges',exchange,'1')
        replacement=api('POST',f'material-exchanges/{exchange["id"]}/create-dispatch',
            {'version':exchange['version'],'request_id':new_request()},201)
        assert replacement['source_document_id']==exchange['id']
        assert Decimal(api('GET',f'material-exchanges/{exchange["id"]}')['lines'][0]['replacement_available_quantity'])==0
        approve_document(client,headers,'MaterialDispatch',replacement['id'])
        execute(api,'material-dispatches',replacement,'1')
        assert api('GET',f'material-exchanges/{exchange["id"]}')['status']=='partial'
        execute(api,'material-receipts',receipts(api,order)[0],'1')
    assert api('GET',f'material-exchanges/{exchange["id"]}')['status']=='completed'
    summary=api('GET',f'work-orders/{order["id"]}/material-flow')['lines'][0]
    assert Decimal(summary['damaged_quantity'])==2
    assert Decimal(summary['effective_quantity'])==100
    stock=next(row for row in api('GET','stock?warehouse_id=1') if row['id']==raw)
    assert Decimal(stock['quantity'])==98
    # 损坏保留原成本，补发增加实际成本，没有第二笔相同的报废损失。
    assert api('GET','production-costs')['orders'][0]['known_material_amount']=='204.00'


def test_execute_retry_stale_version_and_unauthorized_sign(erp):
    client,headers,api,*_=erp
    raw,_,order,dispatch=create_order(erp)
    payload={'version':1,'request_id':new_request(),'lines':[{'line_id':dispatch['lines'][0]['id'],'quantity':'60'}]}
    first=api('POST',f'material-dispatches/{dispatch["id"]}/execute',payload)
    second=api('POST',f'material-dispatches/{dispatch["id"]}/execute',payload)
    assert first==second
    assert len(receipts(api,order))==1
    api('POST',f'material-dispatches/{dispatch["id"]}/execute',{**payload,'request_id':new_request()},409)
    api('POST',f'material-dispatches/{dispatch["id"]}/execute',{**payload,'lines':[{'line_id':payload['lines'][0]['line_id'],'quantity':'59'}]},409)
    receipt=execute(api,'material-receipts',receipts(api,order)[0],'58')
    assert Decimal(receipt['remaining_quantity'])==2
    api('POST',f'material-receipts/{receipt["id"]}/execute',{'version':receipt['version'],'request_id':new_request(),
        'lines':[{'line_id':receipt['lines'][0]['id'],'quantity':'3'}]},409)
    api('POST','users',{'username':'warehouse_flow','password':'secure-pass-123','roles':['warehouse']},201)
    token=api('POST','auth/login',{'username':'warehouse_flow','password':'secure-pass-123'})['token']
    response=client.post(f'/api/v1/material-receipts/{receipt["id"]}/execute',headers={'Authorization':'Bearer '+token},json={
        'version':receipt['version'],'request_id':new_request(),'lines':[{'line_id':receipt['lines'][0]['id'],'quantity':'2'}]})
    assert response.status_code==403
    assert Decimal(next(row for row in api('GET','stock?warehouse_id=1') if row['id']==raw)['quantity'])==140


def test_handover_return_restores_stock_but_does_not_fabricate_signature(erp):
    client,headers,api,*_=erp
    raw,_,order,dispatch=create_order(erp)
    execute(api,'material-dispatches',dispatch,'60')
    receipt=execute(api,'material-receipts',receipts(api,order)[0],'58')
    receipt=api('POST',f'material-receipts/{receipt["id"]}/handover-return',{'version':receipt['version'],
        'request_id':new_request(),'reason':'实物清点两件退回原仓','lines':[{'line_id':receipt['lines'][0]['id'],'quantity':'2'}]})
    assert receipt['status']=='completed'
    assert Decimal(receipt['received_quantity'])==58
    assert Decimal(next(row for row in api('GET','stock?warehouse_id=1') if row['id']==raw)['quantity'])==142
    summary=api('GET',f'work-orders/{order["id"]}/material-flow')['lines'][0]
    assert Decimal(summary['dispatchable_quantity'])==2
    assert Decimal(summary['effective_quantity'])==58


def test_replacement_handover_releases_only_replacement_allowance(erp):
    client,headers,api,*_=erp
    _,_,order,dispatch=create_order(erp)
    execute(api,'material-dispatches',dispatch,'100')
    receipt=execute(api,'material-receipts',receipts(api,order)[0],'100')
    exchange=new_exchange(api,order,receipt)
    approve_document(client,headers,'MaterialExchange',exchange['id'])
    exchange=execute(api,'material-exchanges',exchange,'2')
    replacement=api('POST',f'material-exchanges/{exchange["id"]}/create-dispatch',{'version':exchange['version'],'request_id':new_request()},201)
    approve_document(client,headers,'MaterialDispatch',replacement['id'])
    execute(api,'material-dispatches',replacement,'2')
    pending=receipts(api,order)[0]
    api('POST',f'material-receipts/{pending["id"]}/handover-return',{'version':pending['version'],'request_id':new_request(),
        'reason':'补发材料未交接，实物退回','lines':[{'line_id':pending['lines'][0]['id'],'quantity':'2'}]})
    summary=api('GET',f'work-orders/{order["id"]}/material-flow')['lines'][0]
    assert Decimal(summary['dispatchable_quantity'])==0
    exchange=api('GET',f'material-exchanges/{exchange["id"]}')
    assert Decimal(exchange['lines'][0]['replacement_available_quantity'])==2
    resend=api('POST',f'material-exchanges/{exchange["id"]}/create-dispatch',{'version':exchange['version'],'request_id':new_request()},201)
    assert Decimal(resend['planned_quantity'])==2


def test_source_reservations_loss_evidence_and_cross_order_are_protected(erp):
    client,headers,api,*_=erp
    _,_,order,dispatch=create_order(erp)
    execute(api,'material-dispatches',dispatch,'100')
    receipt=execute(api,'material-receipts',receipts(api,order)[0],'100')
    source={'work_order_line_id':order['lines'][0]['id'],'source_receipt_line_id':receipt['lines'][0]['id'],'quantity':'100'}
    payload={'work_order_id':order['id'],'warehouse_id':1,'request_id':new_request(),'reason':'损坏','lines':[{**source,'disposal':'loss'}]}
    api('POST','material-exchanges',payload,422)
    exchange=api('POST','material-exchanges',{**payload,'lines':[{**source,'disposal':'loss','evidence':'现场确认材料完全损耗'}]},201)
    api('POST','material-returns/flow',{**payload,'request_id':new_request(),'lines':[source]},409)
    api('POST',f'material-exchanges/{exchange["id"]}/close',{'version':exchange['version'],'request_id':new_request(),'reason':'核对后取消申请'})
    returned=api('POST','material-returns/flow',{**payload,'request_id':new_request(),'lines':[source]},201)
    assert returned['status']=='draft'


def test_receipt_correction_requires_approval_and_retains_in_transit(erp):
    client,headers,api,*_=erp
    raw,_,order,dispatch=create_order(erp)
    execute(api,'material-dispatches',dispatch,'60')
    receipt=execute(api,'material-receipts',receipts(api,order)[0],'58')
    payload={'version':receipt['version'],'request_id':new_request(),'reason':'签收数量登记错误，重新清点'}
    api('POST',f'material-receipts/{receipt["id"]}/reverse',payload,409)
    approve_document(client,headers,'MaterialReceipt',receipt['id'],intent='reverse',reason=payload['reason'])
    receipt=api('POST',f'material-receipts/{receipt["id"]}/reverse',payload)
    assert receipt['status']=='draft'
    assert Decimal(receipt['received_quantity'])==0
    assert Decimal(receipt['remaining_quantity'])==60
    assert any(row['action']=='reverse' for row in receipt['executions'])
    assert Decimal(next(row for row in api('GET','stock?warehouse_id=1') if row['id']==raw)['quantity'])==140
    assert Decimal(api('GET',f'work-orders/{order["id"]}/material-flow')['lines'][0]['dispatchable_quantity'])==0


def test_failed_multi_line_execution_rolls_back_stock_approval_and_request_key(erp):
    client,headers,api,*_=erp
    raw,_,order,dispatch=create_order(erp)
    request_id=new_request()
    invalid={'version':1,'request_id':request_id,'lines':[
        {'line_id':dispatch['lines'][0]['id'],'quantity':'60'}, {'line_id':99999,'quantity':'1'}]}
    api('POST',f'material-dispatches/{dispatch["id"]}/execute',invalid,422)
    assert Decimal(next(row for row in api('GET','stock?warehouse_id=1') if row['id']==raw)['quantity'])==200
    current=api('GET',f'material-dispatches/{dispatch["id"]}')
    assert current['version']==1 and current['executions']==[]
    assert current['approval']['status']=='approved'
    assert receipts(api,order)==[]
    api('POST',f'material-dispatches/{dispatch["id"]}/execute',{**invalid,'lines':invalid['lines'][:1]})
    assert Decimal(next(row for row in api('GET','stock?warehouse_id=1') if row['id']==raw)['quantity'])==140


@pytest.mark.parametrize('duplicate_request',[False,True])
def test_concurrent_dispatch_never_duplicates_stock(erp,duplicate_request):
    from concurrent.futures import ThreadPoolExecutor
    client,headers,api,*_=erp
    raw,_,order,dispatch=create_order(erp)
    first={'version':1,'request_id':new_request(),'lines':[{'line_id':dispatch['lines'][0]['id'],'quantity':'60'}]}
    second=first if duplicate_request else {**first,'request_id':new_request()}
    def send(payload):
        return client.post(f'/api/v1/material-dispatches/{dispatch["id"]}/execute',headers=headers,json=payload)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(send,[first,second]))
    assert sorted(response.status_code for response in results)==([200,200] if duplicate_request else [200,409])
    assert Decimal(next(row for row in api('GET','stock?warehouse_id=1') if row['id']==raw)['quantity'])==140
    assert len(receipts(api,order))==1


def test_return_reversal_requires_free_normal_dispatch_allowance(erp):
    client,headers,api,*_=erp
    _,_,order,dispatch=create_order(erp)
    execute(api,'material-dispatches',dispatch,'100')
    signed=execute(api,'material-receipts',receipts(api,order)[0],'100')
    returned=api('POST','material-returns/flow',{'work_order_id':order['id'],'warehouse_id':1,'request_id':new_request(),
        'reason':'正常余料','lines':[{'work_order_line_id':order['lines'][0]['id'],'source_receipt_line_id':signed['lines'][0]['id'],'quantity':'10'}]},201)
    approve_document(client,headers,'ProductionMaterialReturn',returned['id'])
    returned=execute(api,'material-returns/flow',returned,'10')
    api('POST','material-dispatches',{'work_order_id':order['id'],'warehouse_id':1,'request_id':new_request(),
        'lines':[{'work_order_line_id':order['lines'][0]['id'],'quantity':'10'}]},201)
    reason='退料登记有误'
    approve_document(client,headers,'ProductionMaterialReturn',returned['id'],intent='reverse',reason=reason)
    api('POST',f'material-returns/flow/{returned["id"]}/reverse',{'version':returned['version'],'request_id':new_request(),'reason':reason},409)


def test_query_filters_counts_and_pages_use_full_matching_population(erp):
    _,_,api,*_=erp
    _,_,order,dispatch=create_order(erp)
    api('POST',f'material-dispatches/{dispatch["id"]}/close',{'version':1,'request_id':new_request(),'reason':'改按三批计划发料'})
    for index in range(3):
        api('POST','material-dispatches',{'work_order_id':order['id'],'warehouse_id':1,'request_id':new_request(),
            'reference':f'FILTER-{index}','lines':[{'work_order_line_id':order['lines'][0]['id'],'quantity':'20'}]},201)
    first=api('GET','material-dispatches?page_size=1&page=1&q=FLOW-RAW')
    second=api('GET','material-dispatches?page_size=1&page=2&q=FLOW-RAW')
    assert first['total']==second['total']==4
    assert first['summary']==second['summary']
    assert first['items'][0]['id']!=second['items'][0]['id']
    assert first['summary']['draft']==3 and first['summary']['closed']==1
    assert first['work_orders'][0]['id']==order['id']
    assert first['warehouses'][0]['id']==1
    filtered=api('GET','material-dispatches?page_size=1&status=draft&q=FILTER')
    assert filtered['total']==3 and filtered['summary']['draft']==3
    assert api('GET','material-dispatches?q=NOT-EXISTS')['total']==0
    api('GET','material-dispatches?date_from=2026-13-40',status=422)


def test_query_local_date_boundaries_match_display_and_counts(erp):
    from app.core.orm import orm_session
    from app.core.models import MaterialDispatch
    _,_,api,*_=erp
    _,_,order,dispatch=create_order(erp)
    api('POST',f'material-dispatches/{dispatch["id"]}/close',{'version':1,'request_id':new_request(),'reason':'按日期边界核对'})
    documents=[dispatch]
    for index in range(3):
        documents.append(api('POST','material-dispatches',{'work_order_id':order['id'],'warehouse_id':1,
            'request_id':new_request(),'lines':[{'work_order_line_id':order['lines'][0]['id'],'quantity':'1'}]},201))
    # 中国时区 14 日完整一天对应 UTC 13 日 16 时至 14 日 16 时，结束边界不包含。
    timestamps=['2026-10-13 15:59:59','2026-10-13 16:00:00','2026-10-14 15:59:59','2026-10-14 16:00:00']
    with orm_session(write=True) as db:
        for document,timestamp in zip(documents,timestamps):
            db.get(MaterialDispatch,document['id']).created_at=timestamp
    result=api('GET','material-dispatches?date_from=2026-10-14&date_to=2026-10-14&timezone_offset_minutes=-480&page_size=1')
    assert result['total']==2 and result['summary']['draft']==2 and result['summary']['closed']==0
    assert result['items'][0]['id']==documents[2]['id']
    api('GET','material-dispatches?timezone_offset_minutes=841',status=422)


def test_receipt_handover_correction_cannot_reuse_reallocated_normal_quota(erp):
    client,headers,api,*_=erp
    _,_,order,dispatch=create_order(erp)
    execute(api,'material-dispatches',dispatch,'100')
    signed=execute(api,'material-receipts',receipts(api,order)[0],'98')
    signed=api('POST',f'material-receipts/{signed["id"]}/handover-return',{'version':signed['version'],'request_id':new_request(),
        'reason':'清点两件未交接退回','lines':[{'line_id':signed['lines'][0]['id'],'quantity':'2'}]})
    api('POST','material-dispatches',{'work_order_id':order['id'],'warehouse_id':1,'request_id':new_request(),
        'lines':[{'work_order_line_id':order['lines'][0]['id'],'quantity':'2'}]},201)
    reason='交接退回登记有误'
    approve_document(client,headers,'MaterialReceipt',signed['id'],intent='reverse',reason=reason)
    api('POST',f'material-receipts/{signed["id"]}/reverse',{'version':signed['version'],'request_id':new_request(),'reason':reason},409)


def test_receipt_resign_and_second_correction_use_a_new_approval_generation(erp):
    client,headers,api,*_=erp
    _,_,order,dispatch=create_order(erp)
    execute(api,'material-dispatches',dispatch,'60')
    receipt=execute(api,'material-receipts',receipts(api,order)[0],'58')
    for index in range(2):
        reason=f'第{index+1}次签收登记更正'
        approve_document(client,headers,'MaterialReceipt',receipt['id'],intent='reverse',reason=reason)
        receipt=api('POST',f'material-receipts/{receipt["id"]}/reverse',{'version':receipt['version'],'request_id':new_request(),'reason':reason})
        assert Decimal(receipt['received_quantity'])==0
        assert receipt['reversal_approval']['generation']==index+1
        receipt=execute(api,'material-receipts',receipt,'58')
    state=api('GET',f'system/document-approvals/MaterialReceipt/{receipt["id"]}?intent=reverse')
    assert state['can_submit'] is True
    assert len([event for event in state['events'] if event['action']=='execute'])==2
