"""维护统一审批与原执行证据、下游独立批准及原子回滚。"""

import json
import pytest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core.models import DocumentApprovalCase, DocumentApprovalEvent, MaintenanceJob
from app.core.orm import orm_session
from test_equipment import erp, job_input, action, approved, reported, approve_correction
from test_equipment_attachments import payload, path, PDF


def common(api, row, op, actor='admin', status=200, intent='execute', **extra):
    endpoint = f'system/document-approvals/MaintenanceJob/{row["id"]}'
    case = api('GET', endpoint+f'?intent={intent}')
    return api('POST', endpoint+'/'+op, {'version':case['version'], 'intent':intent,
        'reason':'独立核对维护依据', 'evidence':'现场记录分别存证', **extra}, actor, status)


def test_steps_fixed_authors_child_approval_and_first_procurement_consumes_once(erp):
    _, api, actors, ids, _, part = erp
    api('POST','users',{'username':'fourth','password':'secure-pass-123','roles':['admin']},status=201)
    token=api('POST','auth/login',{'username':'fourth','password':'secure-pass-123'})['token']
    actors['fourth']={'Authorization':'Bearer '+token}
    policy = api('GET', 'system/document-approvals/MaintenanceJob')
    api('PUT', 'system/document-approvals/MaintenanceJob', {'version':policy['version'],
        'steps':[{'name':name, 'role':None} for name in ('审核','核准','批准')]})
    row = api('POST', 'equipment/jobs', job_input(erp, warehouse_id=1,
        parts=[{'material_id':part,'quantity':'3'}]), status=201)
    common(api,row,'submit')
    assert api('GET', f'system/document-approvals/MaintenanceJob/{row['id']}?intent=execute', actor='admin')['can_review']
    common(api,row,'approve',actor='reviewer')
    assert api('GET', f'system/document-approvals/MaintenanceJob/{row['id']}?intent=execute', actor='reviewer')['can_review']
    action(api,api('GET',f'equipment/jobs/{row["id"]}'),'start',status=409)
    common(api,row,'approve',actor='third')
    common(api,row,'approve',actor='fourth')
    row = api('GET',f'equipment/jobs/{row["id"]}')
    request = {'version':row['version'],'reason':'分批采购备件','evidence':'维护清单',
        'parts':[{'material_id':part,'quantity':'1'}]}
    row = api('POST',f'equipment/jobs/{row["id"]}/purchase-requests',request,status=201)
    assert row['approval']['status']=='executed' and row['status']=='approved'
    common(api,row,'withdraw',status=409)
    child = row['purchase_requests'][0]
    assert child['status']=='draft'
    api('POST',f'purchase-requests/{child["id"]}/submit',status=409)
    row = api('POST',f'equipment/jobs/{row["id"]}/purchase-requests',
        {**request,'version':row['version']},status=201)
    row = action(api,row,'start')
    assert row['parts_status']=='draft'
    api('POST',f'warehouse-outbounds/{row["parts_outbound_id"]}/post',status=409)
    case = api('GET',f'system/document-approvals/MaintenanceJob/{row["id"]}')
    assert [entry['action'] for entry in case['events']]==['submit','approve','approve','approve','execute']
    assert [entry['step_name'] for entry in case['events'][1:4]]==['审核','核准','批准']
    assert case['events'][0]['evidence']=='现场记录分别存证' and case['content_matches']


def test_required_evidence_legacy_endpoints_versions_and_withdraw_cancel(erp):
    api = erp[1]
    row = api('POST','equipment/jobs',job_input(erp),status=201)
    for bad in ({'reason':''},{'reason':'x'*201},{'evidence':''},{'evidence':'x'*601},{'version':True}):
        common(api,row,'submit',status=422,**bad)
    api('POST',f'equipment/jobs/{row["id"]}/submit',{'version':row['version'],
        'reason':'旧客户端','evidence':'旧客户端现场依据'},status=409)
    common(api,row,'submit',actor='observer',status=403)
    sent = common(api,row,'submit')
    common(api,row,'approve',actor='reviewer',version=0,status=409)
    row = api('GET',f'equipment/jobs/{row["id"]}')
    action(api,row,'cancel',status=409)
    common(api,row,'withdraw')
    row = api('GET',f'equipment/jobs/{row["id"]}')
    assert row['status']=='draft' and row['approval']['status']=='withdrawn'
    assert action(api,row,'cancel')['status']=='cancelled'
    assert sent['events'][0]['reason']=='独立核对维护依据'


def test_plan_attachments_frozen_and_work_evidence_keeps_digest_and_child_authors(erp):
    _, api, _, ids, _, part = erp
    row = api('POST','equipment/jobs',job_input(erp,warehouse_id=1,
        parts=[{'material_id':part,'quantity':'1'}]),status=201)
    base=path('job',row['id'])
    item=api('POST',base,payload(),actor='planner',status=201)
    common(api,row,'submit')
    api('POST',base,payload(PDF+b'during review'),status=409)
    api('POST',base+f'/{item["id"]}/reverse',{'reason':'送审后修改'},status=409)
    common(api,row,'approve',actor='planner',status=403)
    common(api,row,'approve',actor='reviewer')
    row=action(api,api('GET',f'equipment/jobs/{row["id"]}'),'start')
    assert not api('GET',base)['items'][0]['can_reverse']
    api('POST',base+f'/{item["id"]}/reverse',{'reason':'替换原方案'},status=409)
    work=api('POST',base,payload(PDF+b'work'),actor='third',status=201)
    assert work['can_reverse']
    api('POST',base+f'/{work["id"]}/reverse',{'reason':'现场补证错误'},status=201)
    case=api('GET',f'system/document-approvals/MaintenanceJob/{row["id"]}')
    assert case['content_matches']
    child=f'system/document-approvals/WarehouseOutbound/{row["parts_outbound_id"]}'
    current=api('POST',child+'/submit',{'version':0})
    api('POST',child+'/approve',{'version':current['version']},actor='planner',status=403)


def test_correction_fixes_reason_evidence_actual_result_and_does_not_fake_stock(erp):
    api=erp[1]
    row=action(api,reported(erp),'accept',actor='reviewer')
    action(api,row,'reverse',status=409)
    case=common(api,row,'submit',intent='reverse',reason='纠正原验收',evidence='固定更正现场记录')
    assert api('GET', f'system/document-approvals/MaintenanceJob/{row['id']}?intent=reverse', actor='admin')['can_review']
    common(api,row,'approve',intent='reverse',actor='third',reason='审核意见不同',evidence='审核依据不同')
    row=api('GET',f'equipment/jobs/{row["id"]}')
    action(api,row,'reverse',reason='纠正原验收',evidence='另一个现场记录',status=409)
    original=api('GET','stock')
    changed=action(api,row,'reverse',reason='纠正原验收',evidence='固定更正现场记录')
    assert changed['status']=='reversed' and api('GET','stock')==original
    stored=api('GET',f'system/document-approvals/MaintenanceJob/{row["id"]}?intent=reverse')
    assert stored['reversal_reason']=='纠正原验收' and stored['reversal_evidence']=='固定更正现场记录'
    assert stored['status']=='executed' and case['summary'][-4]['value']=='更换轴承并试运行通过'


def test_old_native_approval_requires_new_review_and_history_not_fabricated(erp):
    api=erp[1]
    row=api('POST','equipment/jobs',job_input(erp),status=201)
    with orm_session(write=True) as db:
        original=db.get(MaintenanceJob,row['id']);original.status='approved';original.reviewed_by=erp[3]['reviewer']
    row=api('GET',f'equipment/jobs/{row["id"]}')
    action(api,row,'start',status=409)
    case=api('GET',f'system/document-approvals/MaintenanceJob/{row["id"]}')
    assert case['version']==0 and case['events']==[] and case['can_submit']
    assert '升级前流程记录' in case['summary'][-1]['label']
    common(api,row,'submit')
    common(api,row,'approve',actor='third')
    row=action(api,api('GET',f'equipment/jobs/{row["id"]}'),'start')
    with orm_session() as db:
        first=db.scalar(select(DocumentApprovalEvent).order_by(DocumentApprovalEvent.id.desc()))
        assert first.action=='execute'


@pytest.mark.parametrize('operation',['start','procure'])
def test_execute_event_failure_rolls_back_child_downtime_native_audit_and_approval(erp,operation):
    api=erp[1]
    row=approved(erp,warehouse_id=1,parts=[{'material_id':erp[5],'quantity':'1'}])
    before=api('GET',f'equipment/jobs/{row["id"]}');children=api('GET','warehouse-outbounds');requests=api('GET','purchase-requests')
    def execute(status=200):
        if operation=='start':
            return action(api,row,'start',status=status)
        # 首次派生申请也须和执行事件原子回滚，不能留下占用额度的半张子单。
        return api('POST',f'equipment/jobs/{row["id"]}/purchase-requests',{'version':row['version'],
            'reason':'首次申请备件','evidence':'现场维护依据','parts':[{'material_id':erp[5],'quantity':'1'}]},status=201 if status==200 else status)
    def fault(session,*_):
        if any(isinstance(item,DocumentApprovalEvent) and item.action=='execute' for item in session.new):
            raise RuntimeError('模拟审批执行留痕故障')
    event.listen(Session,'before_flush',fault)
    try:
        execute(status=500)
    finally:
        event.remove(Session,'before_flush',fault)
    assert api('GET',f'equipment/jobs/{row["id"]}')==before
    assert api('GET','warehouse-outbounds')==children
    assert api('GET','purchase-requests')==requests
    assert execute()['approval']['status']=='executed'


def test_concurrent_submit_and_tampered_plan_cannot_execute(erp):
    client, api, actors, _, _, _=erp
    row=api('POST','equipment/jobs',job_input(erp),status=201)
    barrier=Barrier(2)
    def submit(_):
        barrier.wait(timeout=5)
        return client.post(f'/api/v1/system/document-approvals/MaintenanceJob/{row["id"]}/submit',
            json={'version':0,'reason':'并发送审','evidence':'分别核对现场'},headers=actors['admin']).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit,range(2)))==[200,409]
    common(api,row,'approve',actor='reviewer')
    row=api('GET',f'equipment/jobs/{row["id"]}')
    with orm_session(write=True) as db:
        db.get(MaintenanceJob,row['id']).request_note='模拟批准正文被改写'
    action(api,row,'start',status=409)
    assert api('GET','equipment/overview')['jobs'][0]['downtime'] is None
    assert not api('GET',f'system/document-approvals/MaintenanceJob/{row["id"]}')['content_matches']


def test_correction_actual_result_tamper_blocks_review_and_keeps_original_snapshot(erp):
    api=erp[1]
    row=action(api,reported(erp),'accept',actor='reviewer')
    case=common(api,row,'submit',intent='reverse')
    with orm_session(write=True) as db:
        original=db.get(MaintenanceJob,row['id']);original.solution='模拟原验收结果被改写'
    record=api('GET',f'system/document-approvals/MaintenanceJob/{row["id"]}?intent=reverse')
    assert not record['content_matches'] and not record['can_review']
    common(api,row,'approve',intent='reverse',actor='third',status=409)
    assert record['summary']==case['summary']
    common(api,row,'withdraw',intent='reverse')


def test_generic_maintenance_summary_does_not_leak_production_source(erp):
    api=erp[1]
    product=api('POST','materials',{'sku':'PRIVATE-PRODUCTION','name':'隐私生产资料','unit':'件'},status=201)['id']
    bom=api('POST','boms',{'product_material_id':product,'lines':[{'component_material_id':erp[5],'quantity':'1'}]},status=201)
    api('POST',f'boms/{bom["id"]}/activate')
    order=api('POST','work-orders',{'bom_id':bom['id'],'warehouse_id':1,'target_quantity':'1',
        'reference':'禁止设备查看者读取的生产依据'},status=201)
    row=api('POST','equipment/jobs',job_input(erp,work_order_id=order['id']),status=201)
    record=api('GET',f'system/document-approvals/MaintenanceJob/{row["id"]}',actor='observer')
    assert '有生产关联' in json.dumps(record,ensure_ascii=False)
    assert '禁止设备查看者读取的生产依据' not in json.dumps(record,ensure_ascii=False)
    assert 'PRIVATE-PRODUCTION' not in json.dumps(record,ensure_ascii=False)
    assert 'work_order_json' not in record and not record['can_submit']
