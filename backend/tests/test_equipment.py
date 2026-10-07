"""设备维护真实流程、独立处理、库存依赖、并发与写后故障回滚。"""

from approval_test_helpers import approve_document
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.main import app
from app.core.database import migrate
from app.core.models import Base, MaintenanceChange, MaintenanceDowntime
from app.core.orm import orm_session
from app.production.equipment_rules import now

ROOT = 'equipment'


@pytest.fixture
def erp(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'equipment.db'))
    with TestClient(app, client=('127.0.0.1',12000), raise_server_exceptions=False) as client:
        actors = {}
        def api(method, path, payload=None, actor='admin', status=200):
            response = client.request(method, '/api/v1/' + path, json=payload, headers=actors.get(actor, {}))
            assert response.status_code == status, response.text
            return response.json() if status not in (204,500) else None
        def login(name):
            token = api('POST', 'auth/login', {'username':name, 'password':'secure-pass-123'})['token']
            return {'Authorization': 'Bearer ' + token}
        api('POST', 'setup/admin', {'username':'admin', 'password':'secure-pass-123'}, status=201)
        actors['admin'] = login('admin')
        ids = {'admin':1}
        api('POST', 'roles', {'code':'equipment_observer', 'label':'设备查看', 'permissions':['equipment.view']}, status=201)
        for name, role in (('reviewer','admin'), ('third','admin'), ('planner','planner'), ('observer','equipment_observer')):
            ids[name] = api('POST','users',{'username':name,'password':'secure-pass-123','roles':[role]},status=201)['id']
            actors[name] = login(name)
        part = api('POST','materials',{'sku':'SPARE','name':'维护备件','unit':'件'}, status=201)['id']
        inbound = api('POST','warehouse-inbounds',{'warehouse_id':1,'reason':'other','note':'备件期初',
            'lines':[{'material_id':part,'quantity':'10'}]},status=201)
        approve_document(client, actors['admin'], 'WarehouseInbound', inbound['id'])
        api('POST',f'warehouse-inbounds/{inbound["id"]}/post')
        asset = api('POST', ROOT+'/assets', asset_input(), status=201)
        yield client, api, actors, ids, asset, part


def asset_input(**extra):
    return dict(code='EQ-1', name='一号设备', serial_number='SERIAL-1', location='一号车间',
        status='active', reason='登记设备来源', **extra)


def job_input(erp, **extra):
    _, _, _, ids, asset, _ = erp
    return {**dict(reference='M-1', equipment_id=asset['id'], kind='corrective', plan_id=None,
        work_order_id=None, assigned_to=ids['admin'], request_note='轴承异响，检查后更换',
        warehouse_id=None, parts=[], reason='现场故障登记'), **extra}


def plan_input(erp, **extra):
    return {**dict(equipment_id=erp[4]['id'], reference='PM-1', title='周期润滑检查', interval_days=30,
        next_due=now()[:10], enabled=True, reason='登记周期保养制度'), **extra}


def action(api, row, operation, actor='admin', status=200, **extra):
    if operation in ('submit', 'approve', 'reject', 'withdraw'):
        # 只把原送审/审核测试迁移到真实共用入口，不替业务执行隐式批准。
        api('POST', f'system/document-approvals/MaintenanceJob/{row["id"]}/{operation}',
            {'version': row['approval']['version'], 'reason': '按现场记录办理',
             'evidence': '现场记录 W-001', **extra}, actor, status)
        return api('GET', ROOT+f'/jobs/{row["id"]}') if status == 200 else None
    return api('POST', ROOT+f'/jobs/{row["id"]}/{operation}',
        {'version':row['version'], 'reason':'按现场记录办理', 'evidence':'现场记录 W-001', **extra}, actor, status)


def approve_correction(api, row):
    # 验收更正单独送审，固定原因和现场依据；原办理人员不能自审。
    path = f'system/document-approvals/MaintenanceJob/{row["id"]}'
    case = api('GET', path+'?intent=reverse')
    case = api('POST', path+'/submit', {'intent':'reverse', 'version':case['version'],
        'reason':'按现场记录办理', 'evidence':'现场记录 W-001'})
    api('POST', path+'/approve', {'intent':'reverse', 'version':case['version'],
        'reason':'独立复核验收更正', 'evidence':'核对原验收与现场记录'}, actor='third')
    return api('GET', ROOT+f'/jobs/{row["id"]}')


def approved(erp, **extra):
    api = erp[1]
    row = api('POST', ROOT+'/jobs', job_input(erp, **extra), status=201)
    row = action(api, row, 'submit')
    return action(api, row, 'approve', actor='reviewer')


def test_maintenance_purchase_request_keeps_source_quantity_and_receipt_evidence(erp):
    _, api, _, _, _, part = erp
    row = approved(erp, warehouse_id=1, parts=[{'material_id': part, 'quantity': '3'}])
    path = ROOT + f'/jobs/{row["id"]}/purchase-requests'
    payload = {'version': row['version'], 'reason': '库内备件不足需采购',
               'evidence': '检修记录 EQ-1', 'parts': [{'material_id': part, 'quantity': '2'}]}
    api('POST', path, {**payload, 'parts': [{'material_id': part + 999, 'quantity': '1'}]}, status=422)
    api('POST', path, {**payload, 'parts': [{'material_id': part, 'quantity': '4'}]}, status=409)
    api('POST', path, payload, actor='observer', status=403)
    row = api('POST', path, payload, status=201)
    request = row['purchase_requests'][0]
    assert request['status'] == 'draft' and request['lines'][0]['quantity'] == '2'
    assert any(change['action'] == 'procure' for change in row['changes'])
    api('POST', path, payload, status=409)
    api('PUT', f'purchase-requests/{request["id"]}',
        {'lines': [{'material_id': part, 'quantity': '99'}]}, status=409)
    api('POST', path, {**payload, 'version': row['version'],
        'parts': [{'material_id': part, 'quantity': '2'}]}, status=409)
    # 申请独立审批后才允许拆单；每张订单继续按原规则单独审批。
    approve_document(erp[0], erp[2]["admin"], "PurchaseRequest", request["id"])
    supplier = api('POST', 'suppliers', {'name': '维修供应商'}, status=201)['id']
    order = api('POST', 'purchase-orders', {'supplier_id': supplier,
        'purchase_request_id': request['id'], 'lines': [{'material_id': part,
        'purchase_request_line_id': api('GET', 'purchase-requests')[0]['lines'][0]['id'],
        'quantity': '2', 'unit_price': '10'}]}, status=201)
    evidence = api('GET', ROOT + f'/jobs/{row["id"]}')['purchase_requests'][0]
    assert evidence['lines'][0]['orders'][0]['id'] == order['id']
    assert evidence['lines'][0]['orders'][0]['quantity'] == '2'
    # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
    approve_document(erp[0], erp[2]['admin'], 'PurchaseOrder', order['id'])
    api('POST', f'purchase-orders/{order["id"]}/confirm')
    goods = api('POST', 'purchase-goods-receipts', {'purchase_order_id': order['id'],
        'warehouse_id': 1, 'reference': '到货 EQ-1', 'lines': [{
        'purchase_order_line_id': order['lines'][0]['id'], 'accepted_quantity': '2',
        'rejected_quantity': '0'}]}, status=201)
    # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
    approve_document(erp[0], erp[2]['admin'], 'PurchaseGoodsReceipt', goods['id'])
    receipt = api('POST', f'purchase-goods-receipts/{goods["id"]}/confirm')
    link = api('GET', ROOT + f'/jobs/{row["id"]}')['purchase_requests'][0]['lines'][0]['orders'][0]['goods_receipts'][0]
    assert link['id'] == goods['id'] and link['inbound_status'] == 'draft'
    # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
    approve_document(erp[0], erp[2]['admin'], 'Receipt', receipt['inbound_receipt_id'])
    api('POST', f'receipts/{receipt["inbound_receipt_id"]}/post')
    link = api('GET', ROOT + f'/jobs/{row["id"]}')['purchase_requests'][0]['lines'][0]['orders'][0]['goods_receipts'][0]
    assert link['inbound_status'] == 'posted' and link['accepted_quantity'] == '2'
    assert api('GET', ROOT + f'/jobs/{row["id"]}', actor='observer')['purchase_requests'] == []


def test_maintenance_purchase_cancel_releases_planned_quantity(erp):
    _, api, _, _, _, part = erp
    row = approved(erp, warehouse_id=1, parts=[{'material_id': part, 'quantity': '1'}])
    path = ROOT + f'/jobs/{row["id"]}/purchase-requests'
    payload = {'version': row['version'], 'reason': '预订备件', 'evidence': '需求记录',
               'parts': [{'material_id': part, 'quantity': '1'}]}
    row = api('POST', path, payload, status=201)
    old = row['purchase_requests'][0]['id']
    api('POST', f'purchase-requests/{old}/cancel')
    row = api('POST', path, {**payload, 'version': row['version']}, status=201)
    assert [request['status'] for request in row['purchase_requests']] == ['cancelled', 'draft']


def reported(erp, **extra):
    api = erp[1]
    row = action(api, approved(erp, **extra), 'start')
    if row['parts_outbound_id']:
        approve_document(erp[0], erp[2]['admin'], 'WarehouseOutbound', row['parts_outbound_id'])
        api('POST',f'warehouse-outbounds/{row["parts_outbound_id"]}/post')
    return action(api, row, 'report', solution='更换轴承并试运行通过', labor_hours='1.25', service_amount='30.10')


def test_periodic_maintenance_parts_acceptance_and_reversal(erp):
    _, api, _, _, asset, part = erp
    plan = api('POST', ROOT+'/plans', plan_input(erp), status=201)
    row = approved(erp, kind='preventive', plan_id=plan['id'], warehouse_id=1,
        parts=[{'material_id':part,'quantity':'0.125'}])
    action(api,row,'start',actor='reviewer',status=403)
    row = action(api,row,'start')
    assert row['downtime']['ongoing'] and row['parts_status']=='draft'
    assert api('GET','stock')[0]['quantity']=='10'
    action(api,row,'report',status=409,solution='处理完毕',labor_hours='1',service_amount='0')
    approve_document(erp[0], erp[2]['admin'], 'WarehouseOutbound', row['parts_outbound_id'])
    api('POST',f'warehouse-outbounds/{row["parts_outbound_id"]}/post')
    row = action(api,row,'report',solution='处理完毕',labor_hours='1.25',service_amount='30.10')
    action(api,row,'accept',status=409)
    row = action(api,row,'accept',actor='reviewer')
    assert row['labor_hours']=='1.25' and row['service_amount']=='30.10'
    assert not row['downtime']['ongoing'] and row['downtime']['ended_by']==erp[3]['reviewer']
    assert api('GET',ROOT+f'/plans/{plan["id"]}')['next_due']==(date.fromisoformat(now()[:10])+timedelta(days=30)).isoformat()
    approve_document(erp[0], erp[2]['admin'], 'WarehouseOutbound', row['parts_outbound_id'], intent='reverse', reason='实物已归库')
    api('POST',f'warehouse-outbounds/{row["parts_outbound_id"]}/reverse',{'reason':'实物已归库'},status=409)
    downtime = row['downtime']
    row = approve_correction(api, row)
    row = action(api,row,'reverse')
    assert row['downtime']==downtime and row['plan_roll']['reversal_effect']=='restored_due'
    assert api('GET',ROOT+f'/plans/{plan["id"]}')['next_due']==plan['next_due']
    api('POST',f'warehouse-outbounds/{row["parts_outbound_id"]}/reverse',{'reason':'实物已归库'},status=201)
    assert api('GET','stock')[0]['quantity']=='10.000'
    action(api,row,'reverse',status=409)
    assert api('GET',ROOT+f'/assets/{asset["id"]}')['downtimes']==[downtime]


def test_admin_cannot_review_own_or_edited_request(erp):
    _, api, _, _, _, _ = erp
    row = api('POST',ROOT+'/jobs',job_input(erp),status=201)
    row = action(api,row,'submit')
    action(api,row,'approve',status=403)
    row = action(api,row,'reject',actor='reviewer')
    row = api('PUT',ROOT+f'/jobs/{row["id"]}',{**job_input(erp), 'version':row['version']},actor='reviewer')
    row = action(api,row,'submit')
    action(api,row,'approve',actor='reviewer',status=403)
    row = action(api,row,'approve',actor='third')
    assert row['author_ids']==[1,erp[3]['reviewer']]


def test_rework_preserves_interval_and_all_report_revisions(erp):
    api = erp[1]
    row = reported(erp)
    interval = row['downtime']['id']
    row = action(api,row,'rework',actor='reviewer',evidence='复检发现异响仍需处理')
    assert row['downtime']['ongoing'] and row['downtime']['id']==interval
    row = action(api,row,'report',solution='补充紧固复检通过',labor_hours='2.50',service_amount='40')
    row = action(api,row,'accept',actor='reviewer')
    reports = [change for change in row['changes'] if change['action']=='report']
    assert [change['after']['service_amount'] for change in reports]==['30.10','40.00']
    assert row['downtime']['id']==interval


def test_cancel_requires_draft_outbound_cancel_but_retains_actual_consumption(erp):
    api, part = erp[1], erp[5]
    row = action(api,approved(erp,warehouse_id=1,parts=[{'material_id':part,'quantity':'1'}]),'start')
    action(api,row,'cancel',status=409)
    approve_document(erp[0], erp[2]['admin'], 'WarehouseOutbound', row['parts_outbound_id'])
    api('POST',f'warehouse-outbounds/{row["parts_outbound_id"]}/post')
    row = action(api,row,'cancel',evidence='中途取消，但已使用备件不归库')
    assert row['status']=='cancelled' and row['parts_status']=='posted'
    assert not row['downtime']['ongoing'] and api('GET','stock')[0]['quantity']=='9'
    row = action(api,approved(erp,reference='M-2',warehouse_id=1,parts=[{'material_id':part,'quantity':'1'}]),'start')
    api('POST',f'warehouse-outbounds/{row["parts_outbound_id"]}/cancel')
    row = action(api,row,'cancel')
    assert row['parts_status']=='cancelled' and api('GET','stock')[0]['quantity']=='9'


def test_consumed_parts_reversed_before_acceptance_prevent_false_acceptance(erp):
    api = erp[1]
    row = reported(erp,warehouse_id=1,parts=[{'material_id':erp[5],'quantity':'1'}])
    approve_document(erp[0], erp[2]['admin'], 'WarehouseOutbound', row['parts_outbound_id'], intent='reverse', reason='实际耗材领用错误')
    api('POST',f'warehouse-outbounds/{row["parts_outbound_id"]}/reverse',{'reason':'实际耗材领用错误'},status=201)
    action(api,row,'accept',actor='reviewer',status=409)
    assert api('GET',ROOT+f'/jobs/{row["id"]}')['status']=='reported'


def test_plan_and_equipment_cannot_be_changed_under_open_jobs(erp):
    api, asset = erp[1], erp[4]
    plan = api('POST',ROOT+'/plans',plan_input(erp),status=201)
    row = api('POST',ROOT+'/jobs',job_input(erp,kind='preventive',plan_id=plan['id']),status=201)
    api('PUT',ROOT+f'/plans/{plan["id"]}',{**plan_input(erp,enabled=False),'version':plan['version']},status=409)
    api('PUT',ROOT+f'/assets/{asset["id"]}',{**asset_input(),'status':'inactive','version':asset['version']},status=409)
    action(api,row,'cancel')
    plan = api('PUT',ROOT+f'/plans/{plan["id"]}',{**plan_input(erp,enabled=False),'version':plan['version']})
    asset = api('PUT',ROOT+f'/assets/{asset["id"]}',{**asset_input(),'status':'retired','version':asset['version']})
    api('PUT',ROOT+f'/assets/{asset["id"]}',{**asset_input(),'version':asset['version']},status=409)
    api('POST',ROOT+'/jobs',job_input(erp),status=409)
    assert not plan['enabled']


def test_reversal_preserves_a_newer_explicit_schedule(erp):
    api = erp[1]
    plan = api('POST',ROOT+'/plans',plan_input(erp),status=201)
    row = action(api,reported(erp,kind='preventive',plan_id=plan['id']),'accept',actor='reviewer')
    advanced = api('GET',ROOT+f'/plans/{plan["id"]}')
    newer = api('PUT',ROOT+f'/plans/{plan["id"]}',{**plan_input(erp,next_due='2028-01-01'),'version':advanced['version']})
    row = approve_correction(api, row)
    row = action(api,row,'reverse')
    assert row['plan_roll']['reversal_effect']=='retained_newer_schedule'
    assert api('GET',ROOT+f'/plans/{plan["id"]}')==newer


def test_future_plan_cannot_submit_and_duplicate_occurrence_is_reserved(erp):
    api = erp[1]
    plan = api('POST',ROOT+'/plans',plan_input(erp,next_due='2099-01-01'),status=201)
    row = api('POST',ROOT+'/jobs',job_input(erp,kind='preventive',plan_id=plan['id']),status=201)
    action(api,row,'submit',status=409)
    api('POST',ROOT+'/jobs',job_input(erp,reference='M-2',kind='preventive',plan_id=plan['id']),status=409)
    action(api,row,'cancel')
    api('POST',ROOT+'/jobs',job_input(erp,reference='M-2',kind='preventive',plan_id=plan['id']),status=201)


@pytest.mark.parametrize('case',['start','occurrence','version'])
def test_concurrent_operations_cannot_overlap_or_overwrite(erp,case):
    client, api, actors, _, _, _ = erp
    if case=='start':
        rows = [approved(erp,reference=f'M-{index}') for index in range(2)]
        requests = [('POST',ROOT+f'/jobs/{row["id"]}/start',{'version':row['version'],'reason':'开始','evidence':'现场'}) for row in rows]
        expected=[200,409]
    elif case=='occurrence':
        plan = api('POST',ROOT+'/plans',plan_input(erp),status=201)
        requests=[('POST',ROOT+'/jobs',job_input(erp,reference=f'M-{index}',kind='preventive',plan_id=plan['id'])) for index in range(2)]
        expected=[201,409]
    else:
        asset=erp[4]
        requests=[('PUT',ROOT+f'/assets/{asset["id"]}',{**asset_input(),'name':f'修订{index}','version':asset['version']}) for index in range(2)]
        expected=[200,409]
    barrier=Barrier(2)
    def write(request):
        barrier.wait(timeout=5)
        method,path,payload=request
        return client.request(method,'/api/v1/'+path,json=payload,headers=actors['admin']).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(write,requests))==expected
    with orm_session() as db:
        assert len(list(db.scalars(select(MaintenanceDowntime))))==(1 if case=='start' else 0)


@pytest.mark.parametrize('action_name',['start','accept'])
def test_write_after_audit_failure_rolls_back_links_downtime_and_schedule(erp,action_name):
    api=erp[1]
    plan=api('POST',ROOT+'/plans',plan_input(erp),status=201)
    options={'kind':'preventive','plan_id':plan['id'],'warehouse_id':1,'parts':[{'material_id':erp[5],'quantity':'1'}]}
    row=approved(erp,**options) if action_name=='start' else reported(erp,**options)
    before=api('GET',ROOT+f'/jobs/{row["id"]}')
    sources=api('GET','warehouse-outbounds')
    previous_plan=api('GET',ROOT+f'/plans/{plan["id"]}')
    def before_flush(session,*_):
        if any(isinstance(entry,MaintenanceChange) and entry.action==('start' if action_name=='start' else 'advance') for entry in session.new):
            session.info['fail_equipment_after_flush']=True
    def after_flush(session,*_):
        if session.info.pop('fail_equipment_after_flush',False):
            raise RuntimeError('模拟数据库已写入后的设备维护故障')
    event.listen(Session,'before_flush',before_flush)
    event.listen(Session,'after_flush_postexec',after_flush)
    try:
        action(api,row,action_name,actor='admin' if action_name=='start' else 'reviewer',status=500)
    finally:
        event.remove(Session,'before_flush',before_flush)
        event.remove(Session,'after_flush_postexec',after_flush)
    after=api('GET',ROOT+f'/jobs/{row["id"]}')
    # 开放停机时长会自然增长；回滚核对保留数据库证据，不能把当前时长当成已存字段。
    if before['downtime']:
        before['downtime'].pop('seconds')
        after['downtime'].pop('seconds')
    assert after==before
    assert api('GET','warehouse-outbounds')==sources
    assert api('GET',ROOT+f'/plans/{plan["id"]}')==previous_plan
    action(api,row,action_name,actor='admin' if action_name=='start' else 'reviewer')


@pytest.mark.parametrize('extra',[
    {'equipment_id':True}, {'kind':'preventive'}, {'assigned_to':9999},
    {'parts':[{'material_id':1,'quantity':'-1'}],'warehouse_id':1},
    {'parts':[{'material_id':1,'quantity':'0.0001'}],'warehouse_id':1},
    {'parts':[{'material_id':1,'quantity':0.1}],'warehouse_id':1},
    {'parts':[{'material_id':1,'quantity':'1'},{'material_id':1,'quantity':'1'}],'warehouse_id':1},
    {'warehouse_id':1}, {'reference':'   '}, {'reason':' '}, {'unknown':'SQL'},
])
def test_job_input_rejects_invalid_boundaries_without_side_effects(erp,extra):
    api=erp[1]
    api('POST',ROOT+'/jobs',job_input(erp,**extra),status=422)
    assert api('GET',ROOT+'/overview')['jobs']==[]


def test_actor_permissions_optional_production_links_and_audit_redaction(erp):
    _,api,_,_,_,part=erp
    product=api('POST','materials',{'sku':'PRODUCT','name':'生产产品','unit':'件'},status=201)['id']
    bom=api('POST','boms',{'product_material_id':product,'lines':[{'component_material_id':part,'quantity':'1'}]},status=201)
    api('POST',f'boms/{bom["id"]}/activate')
    order=api('POST','work-orders',{'bom_id':bom['id'],'warehouse_id':1,'target_quantity':'1'},status=201)
    row=api('POST',ROOT+'/jobs',job_input(erp,work_order_id=order['id']),status=201)
    visible=api('GET',ROOT+f'/jobs/{row["id"]}',actor='observer')
    assert visible['work_order_linked'] and visible['work_order_id'] is None and visible['work_order_snapshot'] is None
    assert visible['changes'][0]['after']['work_order_json']=='{}' and not visible['can_edit']
    assert api('GET',ROOT+'/overview',actor='observer')['work_orders']==[]
    assert visible['allowed_actions']==[]
    api('POST',ROOT+'/assets',asset_input(),actor='observer',status=403)
    action(api,row,'submit',actor='observer',status=403)
    api('POST',f'work-orders/{order["id"]}/cancel')
    action(api,row,'submit',status=409)
    action(api,row,'cancel')
    api('GET',ROOT+'/overview',actor='anonymous',status=401)


def test_recorded_work_survives_production_cancellation_and_executor_revocation(erp):
    _,api,_,ids,_,part=erp
    product=api('POST','materials',{'sku':'OUTPUT','name':'生产产品','unit':'件'},status=201)['id']
    bom=api('POST','boms',{'product_material_id':product,'lines':[{'component_material_id':part,'quantity':'1'}]},status=201)
    api('POST',f'boms/{bom["id"]}/activate')
    order=api('POST','work-orders',{'bom_id':bom['id'],'warehouse_id':1,'target_quantity':'1'},status=201)
    row=approved(erp,work_order_id=order['id'],assigned_to=ids['planner'])
    row=action(api,row,'start',actor='planner')
    api('POST',f'work-orders/{order["id"]}/cancel')
    row=action(api,row,'report',actor='planner',solution='设备已修复',labor_hours='0',service_amount='0')
    api('PUT',f'users/{ids["planner"]}/status',{'is_active':False})
    row=action(api,row,'accept',actor='reviewer')
    assert row['work_order_current_status']=='cancelled' and row['work_order_snapshot']['status']=='draft'
    assert row['status']=='accepted' and row['labor_hours']=='0.00' and row['service_amount']=='0.00'


def test_unknown_report_values_and_running_equipment_identity_are_protected(erp):
    api,asset=erp[1],erp[4]
    row=api('POST',ROOT+'/jobs',job_input(erp),status=201)
    assert row['labor_hours'] is None and row['service_amount'] is None
    api('PUT',ROOT+f'/assets/{asset["id"]}',{**asset_input(),'serial_number':'DIFFERENT','version':asset['version']},status=409)
    assert api('GET',ROOT+f'/assets/{asset["id"]}')['serial_number']==asset['serial_number']


def test_executor_revocation_and_stale_versions_leave_evidence_unchanged(erp):
    api=erp[1]
    row=api('POST',ROOT+'/jobs',job_input(erp,assigned_to=erp[3]['planner']),status=201)
    updated=action(api,row,'submit')
    action(api,row,'submit',status=409)
    api('PUT',f'users/{erp[3]["planner"]}/status',{'is_active':False})
    action(api,updated,'approve',actor='reviewer',status=409)
    assert api('GET',ROOT+f'/jobs/{row["id"]}')['status']=='submitted'
    assert api('GET',ROOT+f'/jobs/{row["id"]}')['changes']==updated['changes']


def test_asset_unique_serials_and_missing_or_bad_inputs(erp):
    api=erp[1]
    api('POST',ROOT+'/assets',asset_input(),status=409)
    api('POST',ROOT+'/assets',{**asset_input(),'code':'EQ-2'},status=409)
    for number in (2,3):
        api('POST',ROOT+'/assets',{**asset_input(),'code':f'EQ-{number}','serial_number':''},status=201)
    api('GET',ROOT+'/assets/9999',status=404)
    api('POST',ROOT+'/plans',plan_input(erp,next_due='2026-02-30'),status=422)
    row=approved(erp)
    action(api,row,'start',solution='此操作不应写入报工字段',status=422)
    row=action(api,row,'start')
    action(api,row,'report',status=422)
    action(api,row,'report',solution='完成',labor_hours='NaN',service_amount='0',status=422)
    action(api,row,'report',solution='完成',labor_hours='1',service_amount='0.001',status=422)


def test_write_permission_does_not_replace_view_permission_or_expose_profiles(erp):
    _,api,actors,_,_,_=erp
    api('POST','roles',{'code':'equipment_writer','label':'仅维护权限','permissions':['equipment.manage','equipment.create']},status=201)
    api('POST','users',{'username':'writer','password':'secure-pass-123','roles':['equipment_writer']},status=201)
    token=api('POST','auth/login',{'username':'writer','password':'secure-pass-123'})['token']
    actors['writer']={'Authorization':'Bearer '+token}
    api('POST',ROOT+'/assets',{**asset_input(),'code':'EQ-2','serial_number':''},actor='writer',status=403)
    api('PUT',ROOT+'/assets/9999',{**asset_input(),'version':1},actor='writer',status=403)
    api('PUT',ROOT+'/plans/9999',{**plan_input(erp),'version':1},actor='writer',status=403)
    api('PUT',ROOT+'/jobs/9999',{**job_input(erp),'version':1},actor='writer',status=403)
    overview=api('GET',ROOT+'/overview',actor='observer')
    assert len(overview['equipment'])==1
    assert all(set(actor)=={'id','username'} for actor in overview['executors'])


def test_v52_upgrade_is_idempotent_and_preserves_old_business(erp,remove_equipment_schema):
    with sqlite3.connect(os.environ['NEXORA_DB_PATH']) as db:
        before=db.execute('SELECT * FROM stock_movements ORDER BY id').fetchall()
        remove_equipment_schema(db)
        db.execute('PRAGMA user_version=52')
    migrate(); migrate()
    with sqlite3.connect(os.environ['NEXORA_DB_PATH']) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]== 90
        assert db.execute('SELECT * FROM stock_movements ORDER BY id').fetchall()==before
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
        assert db.execute("SELECT COUNT(*) FROM permissions WHERE code LIKE 'equipment.%'").fetchone()[0]==11
    assert len(Base.metadata.tables)== 192


def test_v52_migration_failure_does_not_leave_partial_tables(erp,remove_equipment_schema,monkeypatch):
    from contextlib import contextmanager
    from app.core import database
    with sqlite3.connect(os.environ['NEXORA_DB_PATH']) as db:
        remove_equipment_schema(db)
        db.execute('PRAGMA user_version=52')
    original=database.connection
    @contextmanager
    def fail_new_schema():
        with original() as db:
            db.set_authorizer(lambda action,name,*_: sqlite3.SQLITE_DENY
                if action==sqlite3.SQLITE_CREATE_TABLE and name=='maintenance_jobs' else sqlite3.SQLITE_OK)
            yield db
    with monkeypatch.context() as scoped:
        scoped.setattr(database,'connection',fail_new_schema)
        with pytest.raises(sqlite3.DatabaseError):
            migrate()
    with sqlite3.connect(os.environ['NEXORA_DB_PATH']) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==52
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='equipment_assets'").fetchone()
        assert not db.execute("SELECT 1 FROM permissions WHERE code='equipment.view'").fetchone()
    migrate()


def meter_input(erp, hours, previous=None, **extra):
    return {**dict(equipment_id=erp[4]['id'], hours=hours, reference=f'METER-{hours}',
        reason='现场表计拍照登记', previous_reading_id=previous, correction=False), **extra}


def hour_plan_input(erp, **extra):
    return {**dict(equipment_id=erp[4]['id'], reference='PH-1', title='每十小时检查',
        interval_hours='10.00', next_due_hours='110.00', enabled=True,
        reason='建立按实际运行小时维护的规则'), **extra}


def test_hour_plan_due_acceptance_and_audited_reversal(erp):
    api = erp[1]
    initial = api('POST', ROOT+'/meter-readings', meter_input(erp, '100.00'), status=201)
    plan = api('POST', ROOT+'/hour-plans', hour_plan_input(erp), status=201)
    assert not plan['due'] and plan['current_hours'] == '100.00'
    row = api('POST', ROOT+'/jobs', job_input(erp, kind='preventive',
        hour_plan_id=plan['id']), status=201)
    assert row['plan_due_hours'] == '110.00' and row['plan_meter_reading_id'] == initial['id']
    action(api, row, 'submit', status=409)
    reading = api('POST', ROOT+'/meter-readings', meter_input(erp, '110.00', initial['id']), status=201)
    assert api('GET', ROOT+f'/hour-plans/{plan["id"]}')['due']
    row = action(api, row, 'submit')
    row = action(api, row, 'approve', actor='reviewer')
    row = action(api, row, 'start')
    row = action(api, row, 'report', solution='达到保养小时后检查完毕', labor_hours='0.50', service_amount='0')
    row = action(api, row, 'accept', actor='reviewer')
    advanced = api('GET', ROOT+f'/hour-plans/{plan["id"]}')
    assert advanced['next_due_hours'] == '120.00' and not advanced['due']
    assert row['plan_roll']['reading_id'] == reading['id']
    assert [change['action'] for change in advanced['changes']] == ['create', 'advance']
    row = approve_correction(api, row)
    row = action(api, row, 'reverse')
    assert row['plan_roll']['reversal_effect'] == 'restored_due'
    restored = api('GET', ROOT+f'/hour-plans/{plan["id"]}')
    assert restored['next_due_hours'] == '110.00' and restored['due']
    assert [change['action'] for change in restored['changes']] == ['create', 'advance', 'restore_due']


def test_meter_correction_and_stale_reading_are_auditable(erp):
    api = erp[1]
    first = api('POST', ROOT+'/meter-readings', meter_input(erp, '20'), status=201)
    api('POST', ROOT+'/meter-readings', meter_input(erp, '19', first['id']), status=409)
    api('POST', ROOT+'/meter-readings', meter_input(erp, '19', first['id'], correction=True),
        actor='observer', status=403)
    corrected = api('POST', ROOT+'/meter-readings', meter_input(erp, '19', first['id'],
        correction=True), actor='planner', status=201)
    assert corrected['correction'] and corrected['previous_reading_id'] == first['id']
    api('POST', ROOT+'/meter-readings', meter_input(erp, '21', first['id']), status=409)
    api('POST', ROOT+'/meter-readings', meter_input(erp, '21', corrected['id'],
        reference=first['reference']), status=409)
    readings = api('GET', ROOT+f'/meter-readings?equipment_id={erp[4]["id"]}')
    assert [row['id'] for row in readings] == [corrected['id'], first['id']]
    assert api('GET', ROOT+f'/assets/{erp[4]["id"]}')['meter_reading']['hours'] == '19.00'


def test_hour_plan_requires_baseline_and_rechecks_source(erp):
    api = erp[1]
    api('POST', ROOT+'/hour-plans', hour_plan_input(erp), status=409)
    first = api('POST', ROOT+'/meter-readings', meter_input(erp, '100'), status=201)
    plan = api('POST', ROOT+'/hour-plans', hour_plan_input(erp), status=201)
    api('POST', ROOT+'/plans', plan_input(erp, reference=plan['reference']), status=409)
    row = api('POST', ROOT+'/jobs', job_input(erp, kind='preventive',
        hour_plan_id=plan['id']), status=201)
    api('POST', ROOT+'/jobs', job_input(erp, reference='M-2', kind='preventive',
        hour_plan_id=plan['id']), status=409)
    api('PUT', ROOT+f'/hour-plans/{plan["id"]}', {**hour_plan_input(erp),
        'version':plan['version'], 'enabled':False}, status=409)
    action(api, row, 'cancel')
    plan = api('PUT', ROOT+f'/hour-plans/{plan["id"]}', {**hour_plan_input(erp),
        'version':plan['version'], 'next_due_hours':'100.00'})
    row = api('POST', ROOT+'/jobs', job_input(erp, reference='M-2', kind='preventive',
        hour_plan_id=plan['id']), status=201)
    row = action(api, row, 'submit')
    lower = api('POST', ROOT+'/meter-readings', meter_input(erp, '90', first['id'],
        correction=True), actor='planner', status=201)
    action(api, row, 'approve', actor='reviewer', status=409)
    api('POST', ROOT+'/meter-readings', meter_input(erp, '100', lower['id'],
        reference='METER-100-复核'), status=201)
    row = action(api, row, 'approve', actor='reviewer')
    assert row['status'] == 'approved'


def test_hour_inputs_reject_float_and_invalid_combinations(erp):
    api = erp[1]
    api('POST', ROOT+'/meter-readings', meter_input(erp, 1.5), status=422)
    api('POST', ROOT+'/meter-readings', meter_input(erp, '-1'), status=422)
    api('POST', ROOT+'/meter-readings', meter_input(erp, '1.001'), status=422)
    api('POST', ROOT+'/hour-plans', hour_plan_input(erp, interval_hours=1.5), status=422)
    api('POST', ROOT+'/jobs', job_input(erp, kind='preventive'), status=422)
    api('POST', ROOT+'/jobs', job_input(erp, kind='preventive', plan_id=1,
        hour_plan_id=1), status=422)


def remove_hour_schema(db):
    # 回放旧版本迁移时撤下后续新增结构，避免第 64 和 66 版重复建表。
    db.execute('DROP TABLE IF EXISTS after_sales_attachment_reversals')
    db.execute('DROP TABLE IF EXISTS after_sales_attachments')
    db.execute("DELETE FROM role_permissions WHERE permission_code='after_sales.attachment'")
    db.execute("DELETE FROM permissions WHERE code='after_sales.attachment'")
    db.execute('DROP TABLE IF EXISTS inventory_warning_events')
    db.execute('DROP TABLE IF EXISTS inventory_warning_observations')
    db.execute('DROP TABLE IF EXISTS material_return_reversals')
    db.execute("DELETE FROM role_permissions WHERE permission_code='material_return.reverse'")
    db.execute("DELETE FROM permissions WHERE code='material_return.reverse'")
    db.execute('DROP TABLE IF EXISTS material_issue_reversals')
    db.execute("DELETE FROM role_permissions WHERE permission_code='material_issue.reverse'")
    db.execute("DELETE FROM permissions WHERE code='material_issue.reverse'")
    db.execute('DROP TABLE IF EXISTS after_sales_labor')
    db.execute("DELETE FROM role_permissions WHERE permission_code='after_sales.labor'")
    db.execute("DELETE FROM permissions WHERE code='after_sales.labor'")
    db.execute('DROP INDEX maintenance_hour_occurrence')
    for column in ('plan_meter_reading_id', 'plan_due_hours', 'hour_plan_id'):
        db.execute(f'ALTER TABLE maintenance_jobs DROP COLUMN {column}')
    for table in ('maintenance_hour_plan_changes', 'maintenance_hour_plans', 'equipment_meter_readings'):
        db.execute(f'DROP TABLE {table}')
    db.execute("DELETE FROM role_permissions WHERE permission_code='equipment.meter'")
    db.execute("DELETE FROM permissions WHERE code='equipment.meter'")
    db.execute('PRAGMA user_version=62')


def test_v62_hour_migration_preserves_calendar_business_and_is_idempotent(erp):
    with sqlite3.connect(os.environ['NEXORA_DB_PATH']) as db:
        old_jobs = db.execute('SELECT id,status,plan_id FROM maintenance_jobs ORDER BY id').fetchall()
        remove_hour_schema(db)
    migrate(); migrate()
    with sqlite3.connect(os.environ['NEXORA_DB_PATH']) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 90
        assert db.execute('SELECT id,status,plan_id FROM maintenance_jobs ORDER BY id').fetchall() == old_jobs
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        assert db.execute("SELECT COUNT(*) FROM permissions WHERE code='equipment.meter'").fetchone()[0] == 1


def test_v62_hour_migration_rolls_back_on_schema_failure(erp, monkeypatch):
    from contextlib import contextmanager
    from app.core import database
    with sqlite3.connect(os.environ['NEXORA_DB_PATH']) as db:
        remove_hour_schema(db)
    original = database.connection
    @contextmanager
    def fail_hour_plan():
        with original() as db:
            db.set_authorizer(lambda operation, name, *_: sqlite3.SQLITE_DENY
                if operation == sqlite3.SQLITE_CREATE_TABLE and name == 'maintenance_hour_plans'
                else sqlite3.SQLITE_OK)
            yield db
    with monkeypatch.context() as scoped:
        scoped.setattr(database, 'connection', fail_hour_plan)
        with pytest.raises(sqlite3.DatabaseError):
            migrate()
    with sqlite3.connect(os.environ['NEXORA_DB_PATH']) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 62
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='equipment_meter_readings'").fetchone() is None
    migrate()
