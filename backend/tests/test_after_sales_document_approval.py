"""售后统一步骤、方案附件固定、独立更正与原事务回滚的跨模块验收。"""

import base64
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import select

from app.core import document_approval as workflow
from app.core.models import (AfterSalesCase, AfterSalesChange, AfterSalesCustody, Customer,
    DocumentApprovalEvent, SalesReturn, SalesOrder, WarehouseOutbound)
from app.core.orm import orm_session
from approval_test_helpers import approve_document
from test_after_sales import erp, payload, action, approved, ROOT


def path(row):
    return f'system/document-approvals/AfterSalesCase/{row["id"]}'


def upload(api, row, actor='admin', suffix=b''):
    return api('POST', f'{ROOT}/{row["id"]}/attachments', dict(file_name='方案.pdf',
        content_base64=base64.b64encode(b'%PDF-1.7\nproof\n%%EOF' + suffix).decode(), reason='客户故障依据'),
        actor=actor, status=201)


def new_actor(erp, name):
    client, api, actors, *_ = erp
    api('POST', 'users', dict(username=name, password='secure-pass-123', roles=['admin']), status=201)
    result=client.post('/api/v1/auth/login', json=dict(username=name, password='secure-pass-123'))
    actors[name]={'Authorization':'Bearer '+result.json()['token']}
    return name


def test_three_steps_freeze_plan_and_allow_authorized_people(erp):
    _, api, *_ = erp
    with orm_session(write=True) as db:
        workflow.save_policy(db, 'AfterSalesCase', [dict(name=name, role=None)
            for name in ('审核', '核准', '批准')], 1, 1)
    row=api('POST', ROOT, payload(erp,kind='exchange'), status=201)
    row=action(api,row,'submit')
    assert row['version']==2 and row['approval']['version']==1
    with orm_session(write=True) as db:
        db.get(Customer,row['frozen_source']['customer_id']).name='后续客户名称'
        workflow.save_policy(db, 'AfterSalesCase', [dict(name='新规则',role=None)], 2, 1)
    state=api('GET',path(row))
    assert state['content_matches'] and state['policy_version']==2
    assert state['summary'][0]['value']=='售后客户'
    assert api('GET', f'system/document-approvals/AfterSalesCase/{row['id']}?intent=execute', actor='admin')['can_review']
    row=action(api,row,'approve',actor='reviewer')
    assert row['status']=='submitted'
    assert api('GET', f'system/document-approvals/AfterSalesCase/{row['id']}?intent=execute', actor='reviewer')['can_review']
    action(api,row,'process',status=409)
    for name in ('after_check','after_authorize'):
        row=action(api,row,'approve',actor=new_actor(erp,name))
    assert row['status']==row['approval']['status']=='approved'
    assert [step['name'] for step in row['approval']['steps']]==['审核','核准','批准']
    row=action(api,row,'process')
    assert row['approval']['status']=='executed'
    assert next(item for item in api('GET','sales-returns') if item['id']==row['sales_return_id'])['status']=='draft'
    assert next(item for item in api('GET','sales-orders') if item['id']==row['replacement_order_id'])['approval']['version']==0


def test_attachments_freeze_plan_but_allow_later_work_evidence(erp):
    _, api, *_=erp
    row=api('POST',ROOT,payload(erp),status=201)
    author=new_actor(erp,'after_plan_attachment_author')
    item=upload(api,row,actor=author)
    row=action(api,row,'submit')
    assert api('GET', f'system/document-approvals/AfterSalesCase/{row['id']}?intent=execute', actor=author)['can_review']
    assert not api('GET',f'{ROOT}/{row["id"]}/attachments')['can_modify']
    api('POST',f'{ROOT}/{row["id"]}/attachments/{item["id"]}/reverse',{'reason':'不能替换待审证据'},status=409)
    row=action(api,row,'approve',actor=new_actor(erp,'after_independent'))
    action(api,row,'cancel',status=409)
    row=action(api,row,'receive')
    late=upload(api,row,suffix=b'workphoto')
    listing=api('GET',f'{ROOT}/{row["id"]}/attachments')
    assert listing['can_modify'] and not listing['items'][0]['can_reverse'] and listing['items'][1]['can_reverse']
    api('POST',f'{ROOT}/{row["id"]}/attachments/{item["id"]}/reverse',{'reason':'原方案附件不可撤销'},status=409)
    api('POST',f'{ROOT}/{row["id"]}/attachments/{late["id"]}/reverse',{'reason':'作业重复附件'},status=201)
    state=api('GET',path(row))
    assert state['content_matches'] and len([item for item in state['summary'] if item['label']=='方案附件'])==1
    row=action(api,row,'inspect',inspection_result='pass')
    row=action(api,row,'close')
    assert row['custody_quantity']=='0' and len(row['custody'])==2


def test_attachment_author_can_review_any_derived_document(erp):
    client,api,actors,*_=erp
    author=new_actor(erp,'after_attachment_author')
    for kind in ('repair','exchange'):
        data=payload(erp,kind=kind,reference='ATT-'+kind,quantity='1')
        if kind=='repair':data.update(warehouse_id=1,parts=[dict(material_id=erp[5],quantity='1')])
        row=api('POST',ROOT,data,status=201)
        upload(api,row,actor=author,suffix=kind.encode())
        row=action(api,row,'submit')
        row=action(api,row,'approve',actor='reviewer')
        row=action(api,row,'receive' if kind=='repair' else 'process')
        children=[('WarehouseOutbound',row['parts_outbound_id'])] if kind=='repair' else [
            ('SalesReturn',row['sales_return_id']),('SalesOrder',row['replacement_order_id'])]
        for typ,identifier in children:
            p=f'system/document-approvals/{typ}/{identifier}'
            api('POST',p+'/submit',{'version':0})
            state=api('GET',p,actor=author)
            assert state['can_review']  # 附件作者持有子单批准权限时也可审批。
            approved = api('POST',p+'/approve',{'version':state['version']},actor=author)
            assert approved['status'] == 'approved'


def test_legacy_endpoints_scope_reason_and_withdraw_reservation(erp):
    _,api,*_=erp
    row=api('POST',ROOT,payload(erp,quantity='8'),status=201)
    for operation,actor in (('submit','admin'),('approve','reviewer'),('reject','reviewer')):
        api('POST',f'{ROOT}/{row["id"]}/{operation}',{'version':1,'reason':'旧客户端'},actor=actor,status=409)
    for reason in (' ', '长'*201):
        api('POST',path(row)+'/submit',{'version':0,'reason':reason},status=422)
    row=action(api,row,'submit')
    api('POST',ROOT,payload(erp,reference='SECOND',quantity='3'),status=409)
    row=action(api,row,'withdraw')
    api('POST',ROOT,payload(erp,reference='SECOND',quantity='3'),status=201)
    assert row['status']=='draft' and row['changes'][-1]['action']=='withdraw'
    with orm_session(write=True) as db:
        db.get(Customer,row['frozen_source']['customer_id']).owner_id=1
    api('GET',path(row),actor='seller',status=404)
    for operation in ('submit','approve','reject','withdraw'):
        api('POST',path(row)+'/'+operation,{'version':2,'reason':'跨客户'},actor='seller',status=404)


def test_execute_event_failure_rolls_back_children_custody_and_versions(erp,monkeypatch):
    _,api,*_=erp
    row=approved(erp,payload(erp,kind='exchange'))
    original=workflow.append_event
    def fail(db,record,operation,*args,**kwargs):
        # 在原业务已建立关联草稿后模拟事件故障，必须与子单一起回滚。
        if record.document_type=='AfterSalesCase' and operation=='execute':raise RuntimeError('事件存储异常')
        return original(db,record,operation,*args,**kwargs)
    monkeypatch.setattr(workflow,'append_event',fail)
    with orm_session() as db:
        count=len(list(db.scalars(select(SalesOrder.id))))
    action(api,row,'process',status=500)
    current=api('GET',f'{ROOT}/{row["id"]}')
    assert current['version']==row['version'] and current['approval']['status']=='approved'
    assert current['sales_return_id'] is None and current['replacement_order_id'] is None
    with orm_session() as db:
        assert not list(db.scalars(select(SalesReturn.id)))
        assert len(list(db.scalars(select(SalesOrder.id))))==count
    repair=approved(erp,payload(erp,reference='ROLL-REPAIR',warehouse_id=1,parts=[dict(material_id=erp[5],quantity='1')]))
    action(api,repair,'receive',status=500)
    with orm_session() as db:
        assert not list(db.scalars(select(AfterSalesCustody.id)))
        assert not list(db.scalars(select(WarehouseOutbound.id)))


def test_closed_correction_is_independent_fixed_reason_and_preserves_custody(erp):
    client,api,actors,*_=erp
    row=approved(erp,payload(erp,charge_mode='charge',fee_amount='5.50'))
    row=action(api,row,'receive');row=action(api,row,'inspect',inspection_result='pass');row=action(api,row,'close')
    action(api,row,'reverse',status=409)
    approval=approve_document(client,actors['admin'],'AfterSalesCase',row['id'],intent='reverse',reason='核对售后依据')
    assert approval['status']=='approved' and row['reversal_approval']['version']==0
    api('POST',f'{ROOT}/{row["id"]}/reverse',{'version':row['version'],'reason':'擅自改原因'},status=409)
    assert not api('GET',path(row)+'?intent=reverse')['can_review']
    changed=action(api,row,'reverse')
    assert changed['reversal_approval']['status']=='executed' and changed['custody']==row['custody']
    assert changed['closed_at']==row['closed_at'] and changed['status']=='reversed'
    action(api,changed,'reverse',status=409)


def test_concurrent_submit_only_reserves_and_audits_once(erp):
    client,api,actors,*_=erp
    row=api('POST',ROOT,payload(erp),status=201)
    barrier=Barrier(2)
    def submit():
        barrier.wait()
        return client.post('/api/v1/'+path(row)+'/submit',headers=actors['admin'],json={'version':0,'reason':'并发提交'}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:submit(),range(2)))
    assert sorted(results)==[200,409]
    current=api('GET',f'{ROOT}/{row["id"]}')
    assert current['version']==2 and current['approval']['version']==1
    assert [item['action'] for item in current['changes']]==['create','submit']


def test_legacy_approved_needs_new_approval_and_processed_is_read_only(erp):
    _,api,*_=erp
    row=api('POST',ROOT,payload(erp),status=201)
    with orm_session(write=True) as db:
        old=db.get(AfterSalesCase,row['id'])
        old.status='approved';old.submitted_by=1;old.submitted_at='2026-01-01 00:00:00'
        old.reviewed_by=2;old.reviewed_at='2026-01-02 00:00:00'
    row=api('GET',f'{ROOT}/{row["id"]}')
    action(api,row,'receive',status=409)
    row=action(api,row,'submit')
    state=api('GET',path(row))
    assert state['summary'][-1]['label']=='升级前流程记录（仅供历史核对）'
    row=action(api,row,'approve',actor='reviewer');row=action(api,row,'receive')
    legacy=api('POST',ROOT,payload(erp,reference='LEGACY-PROCESSED'),status=201)
    with orm_session(write=True) as db:
        # 升级前已有交接事实通过原模型构造，不删除本次新审批或伪造历史批准。
        db.get(AfterSalesCase,legacy['id']).status='received'
        db.add(AfterSalesCustody(case_id=legacy['id'],action='receive',quantity=legacy['quantity'],
            evidence='原历史交接',created_by=1))
    state=api('GET',path(legacy))
    assert not state['can_submit'] and not state['can_review'] and not state['can_withdraw']
    assert state['version']==0 and state['business_status']=='received'


def test_submit_event_failure_restores_native_snapshot_and_authors(erp,monkeypatch):
    _,api,*_=erp
    row=api('POST',ROOT,payload(erp),status=201)
    with orm_session(write=True) as db:
        original_json=db.get(AfterSalesCase,row['id']).source_json
        db.get(Customer,row['frozen_source']['customer_id']).name='送审阶段才出现的新名称'
    original=workflow.append_event
    def fail(db,record,operation,*args,**kwargs):
        if record.document_type=='AfterSalesCase' and operation=='submit':raise RuntimeError('送审事件失败')
        return original(db,record,operation,*args,**kwargs)
    monkeypatch.setattr(workflow,'append_event',fail)
    action(api,row,'submit',status=500)
    current=api('GET',f'{ROOT}/{row["id"]}')
    assert current['version']==1 and current['status']=='draft' and current['approval']['version']==0
    with orm_session() as db:
        assert db.get(AfterSalesCase,row['id']).source_json==original_json
        assert [item.action for item in db.scalars(select(AfterSalesChange).where(AfterSalesChange.case_id==row['id']))]==['create']


def test_legacy_closed_case_can_obtain_new_independent_correction(erp):
    client,api,actors,*_=erp
    row=api('POST',ROOT,payload(erp),status=201)
    with orm_session(write=True) as db:
        old=db.get(AfterSalesCase,row['id']);old.status='closed';old.closed_by=1;old.closed_at='2026-01-01 00:00:00'
        db.add_all([AfterSalesCustody(case_id=row['id'],action=operation,quantity=row['quantity'],
            evidence='原历史实际交接',created_by=1) for operation in ('receive','return')])
    current=api('GET',f'{ROOT}/{row["id"]}')
    assert current['approval']['version']==0 and current['reversal_approval']['version']==0
    # 升级前已结案记录没有新的执行快照，更正申请仍能固定正文并独立审完。
    approve_document(client,actors['admin'],'AfterSalesCase',row['id'],intent='reverse',reason='核对售后依据')
    changed=action(api,current,'reverse')
    assert changed['status']=='reversed' and changed['approval']['version']==0
    assert changed['custody']==current['custody'] and changed['reversal_approval']['status']=='executed'
