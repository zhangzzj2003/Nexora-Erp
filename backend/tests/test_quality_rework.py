"""从质检隔离数量到报废、返工成本、凭证来源及更正的跨模块风险。"""

from approval_test_helpers import execute_production_settlement, approve_document

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from decimal import Decimal
import os
import sqlite3

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import migrate
from app.core.models import Base, QualityDisposition, QualityDispositionChange, WorkOrder
from app.core.orm import orm_session
from app.main import app

ROOT = 'production-quality'


@pytest.fixture
def quality_erp(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'quality.db'))
    with TestClient(app, client=('127.0.0.1', 12000), raise_server_exceptions=False) as client:
        client.post('/api/v1/setup/admin', json={'username':'admin','password':'secure-pass-123'})
        def login(name):
            token = client.post('/api/v1/auth/login', json={'username':name,'password':'secure-pass-123'}).json()['token']
            return {'Authorization':f'Bearer {token}'}
        admin = login('admin')
        def api(method, path, data=None, status=200, actor=None):
            response = client.request(method, '/api/v1/' + path, json=data, headers=actor or admin)
            assert response.status_code == status, response.text
            return response.json()
        for name, role in (('author','planner'),('reviewer','finance'),('keeper','warehouse'),('seller','seller')):
            api('POST','users',{'username':name,'password':'secure-pass-123','roles':[role]},201)
        actors = {name:login(name) for name in ('author','reviewer','keeper','seller')}
        supplier = api('POST','suppliers',{'name':'质量测试供应商'},201)['id']
        raw = api('POST','materials',{'sku':'RAW-Q','name':'原材料','unit':'件'},201)['id']
        product = api('POST','materials',{'sku':'PRODUCT-Q','name':'成品','unit':'件'},201)['id']
        receipt = api('POST','receipts',{'supplier_id':supplier,'warehouse_id':1,
            'lines':[{'material_id':raw,'quantity':'30'}]},201)
        # 原采购入库先独立审批，质量测试继续验证报废、返工和成本依赖。
        approve_document(client, admin, 'Receipt', receipt['id'])
        api('POST',f'receipts/{receipt["id"]}/post')
        movement = api('GET','inventory/valuation')['movements'][0]
        api('POST','inventory/valuation/inputs',{'movement_id':movement['id'],'unit_cost':'2',
            'reference':'RAW-PRICE','reason':'模拟采购依据'},201)
        bom = api('POST','boms',{'product_material_id':product,'base_quantity':'1',
            'lines':[{'component_material_id':raw,'quantity':'1'}]},201)
        api('POST',f'boms/{bom["id"]}/activate')
        def order(quantity='10', accepted='4'):
            work = api('POST','work-orders',{'bom_id':bom['id'],'warehouse_id':1,'target_quantity':quantity},201)
            approve_document(client, admin, 'WorkOrder', work['id'])
            api('POST',f'work-orders/{work["id"]}/release')
            issue = api('POST','material-issues',{'work_order_id':work['id'],'warehouse_id':1,
                'lines':[{'work_order_line_id':work['lines'][0]['id'],'quantity':quantity}]},201)
            approve_document(client, admin, 'MaterialIssue', issue['id'])
            api('POST',f'material-issues/{issue["id"]}/post')
            completion = complete(work['id'], quantity, accepted)
            return work, completion
        def complete(order_id, reported, accepted):
            completion = api('POST','production-completions',{'work_order_id':order_id,'reported_quantity':reported},201)
            api('POST',f'production-completions/{completion["id"]}/inspect',{'accepted_quantity':accepted,'qc_note':'尺寸超差，隔离处理'})
            approve_document(client, admin, 'ProductionCompletion', completion['id'])
            return api('POST',f'production-completions/{completion["id"]}/post')
        yield client, admin, actors, api, raw, product, order, complete


def payload(completion, kind='scrap', quantity='1', treatment='expense', reference='Q-1', materials=None):
    return dict(completion_id=completion['id'], reference=reference, kind=kind, quantity=quantity,
        loss_treatment='carry' if kind == 'rework' else treatment, defect='尺寸检验不合格',
        action_note='按质量决定报废' if kind == 'scrap' else '重整后重新检验', reason='按检验记录处置',
        warehouse_id=1 if kind == 'rework' else None, materials=materials or [])


def action(api, row, command, actor=None, status=200, reason='复核质量依据'):
    # 既有业务回归显式使用统一送审，原执行与依赖断言继续走真实接口。
    if command in ('submit', 'approve', 'reject', 'withdraw'):
        path = f'system/document-approvals/QualityDisposition/{row["id"]}'
        state = api('GET', path, actor=actor)
        result = api('POST', path + '/' + command,
            {'version': state['version'], 'reason': reason}, status, actor)
        return api('GET', f'{ROOT}/dispositions/{row["id"]}', actor=actor) if status == 200 else result
    return api('POST',f'{ROOT}/dispositions/{row["id"]}/{command}',
        {'version':row['version'],'reason':reason},status,actor)


def posted(api, actors, data):
    row = api('POST',ROOT+'/dispositions',data,201,actors['author'])
    row = action(api,row,'submit',actors['author'])
    row = action(api,row,'approve',actors['reviewer'])
    return action(api,row,'post')


def settle(quality_erp, order_id, reference='SETTLE-Q', status=201):
    client, admin, _, api, *_ = quality_erp
    row = api('POST','production-costs/settlements',{'work_order_id':order_id,'reference':reference},status)
    return execute_production_settlement(client, admin, row) if status == 201 else row


def test_mixed_loss_rework_costs_stock_and_dependency_chain(quality_erp):
    _,_,actors,api,raw,product,order,complete = quality_erp
    original, completion = order()
    normal = posted(api,actors,payload(completion,quantity='2',treatment='absorb',reference='NORMAL'))
    loss = posted(api,actors,payload(completion,quantity='1',reference='LOSS'))
    rework = posted(api,actors,payload(completion,kind='rework',quantity='3',reference='REWORK',
        materials=[{'material_id':raw,'quantity':'1'}]))
    child = next(row for row in api('GET','work-orders') if row['id'] == rework['rework_order_id'])
    assert child['rework_completion_id'] == completion['id'] and child['lines'][0]['required_quantity'] == '1'
    assert api('GET',ROOT)['cases'][0]['remaining_quantity'] == '0'
    approve_document(quality_erp[0], quality_erp[1], 'WorkOrder', child['id'])
    api('POST',f'work-orders/{child["id"]}/release')
    issue = api('POST','material-issues',{'work_order_id':child['id'],'warehouse_id':1,
        'lines':[{'work_order_line_id':child['lines'][0]['id'],'quantity':'1'}]},201)
    approve_document(quality_erp[0], quality_erp[1], 'MaterialIssue', issue['id'])
    api('POST',f'material-issues/{issue["id"]}/post')
    complete(child['id'],'3','3')
    api('POST','production-costs/charges',{'work_order_id':child['id'],'kind':'labor','amount':'3','reference':'REPAIR-LABOR'},201)
    settle(quality_erp,child['id'],'EARLY',409)
    unknown = next(row for row in api('GET','production-costs')['orders'] if row['work_order_id']==child['id'])
    assert unknown['rework_amount'] is None and unknown['total_amount'] is None and unknown['unpriced_rework']
    parent = settle(quality_erp,original['id'])
    assert parent['total_amount'] == '20.00' and parent['allocations'][0]['amount'] == '12.00'
    values = {row['disposition_id']:row['amount'] for row in parent['quality_allocations']}
    assert values == {normal['id']:'0.00',loss['id']:'2.00',rework['id']:'6.00'}
    assert sum(Decimal(value) for value in values.values()) + Decimal(parent['allocations'][0]['amount']) == Decimal('20')
    child_settlement = settle(quality_erp,child['id'],'CHILD')
    assert child_settlement['rework_amount'] == '6.00' and child_settlement['total_amount'] == '11.00'
    assert child_settlement['rework_sources'][0]['origin_settlement_id'] == parent['id']
    stock = next(row for row in api('GET','inventory/valuation')['materials'] if row['id'] == product)
    assert stock['quantity'] == '7' and stock['amount'] == '23.00'
    approve_document(quality_erp[0],quality_erp[1],'ProductionCostSettlement',parent['id'],intent='reverse',reason='重核原料')
    api('POST',f'production-costs/settlements/{parent["id"]}/reverse',{'reason':'重核原料'},409)
    source = next(row for row in api('GET','finance/business-journals') if row['key'] == f'quality_loss:{loss["id"]}')
    assert source['roles'] == {'quality_loss':'2.00','work_in_progress':'-2.00'}
    approve_document(quality_erp[0],quality_erp[1],'ProductionCostSettlement',child_settlement['id'],intent='reverse',reason='先更正返工成本')
    api('POST',f'production-costs/settlements/{child_settlement["id"]}/reverse',{'reason':'先更正返工成本'})

    api('POST',f'production-costs/settlements/{parent["id"]}/reverse',{'reason':'重核原料'})
    assert next(row for row in api('GET','production-costs')['orders'] if row['work_order_id'] == child['id'])['total_amount'] is None


def test_all_rejected_scrap_can_settle_without_manufacturing_inventory(quality_erp):
    _,_,actors,api,_,product,order,_ = quality_erp
    original,completion = order('1','0')
    settle(quality_erp,original['id'],status=409)
    scrap = posted(api,actors,payload(completion))
    result = settle(quality_erp,original['id'])
    assert result['accepted_quantity'] == '0' and result['allocations'] == []
    assert result['quality_allocations'][0]['amount'] == '2.00'
    assert not any(row['source_type']=='production_completion' for row in api('GET','inventory/valuation')['movements'])
    assert all(row['id'] != product or Decimal(row['quantity']) == 0 for row in api('GET','inventory/valuation')['materials'])
    action(api,scrap,'reverse',status=409)


def test_posted_loss_journal_protects_settlement_until_reviewed_reversal(quality_erp):
    from app.finance.business_sources import ROLE_LABELS
    _,_,actors,api,_,_,order,_ = quality_erp
    work,completion = order('1','0')
    loss = posted(api,actors,payload(completion))
    mapping = {role:api('POST','finance/ledger-accounts',dict(code=f'Q{index}',name=label,
        category='asset',normal_balance='debit',reason='质量损失测试科目'),201)['id']
        for index,(role,label) in enumerate(ROLE_LABELS.items(),1)}
    api('POST','finance/accounting-periods',dict(code='QUALITY-YEAR',name='质量测试年',
        start_date='2026-01-01',end_date='2026-12-31',reason='核对业务凭证'),201)
    api('PUT','finance/business-journals/policy',dict(version=0,start_date='2026-01-01',mapping=mapping,reason='核对启用'))
    pending = next(row for row in api('GET','finance/business-journals') if row['key']==f'quality_loss:{loss["id"]}')
    assert pending['blockers']
    settlement = settle(quality_erp,work['id'])
    source = next(row for row in api('GET','finance/business-journals') if row['key']==pending['key'])
    journal = api('POST','finance/business-journals/generate',dict(source_key=source['key'],
        fingerprint=source['fingerprint'],policy_version=source['policy_version'],reference='QUALITY-LOSS',
        journal_date=source['minimum_date'],reason='按质量审批及结算'),201)
    def journal_post(row):
        path=f'finance/journals/{row["id"]}'
        approve_document(quality_erp[0],quality_erp[1],'Journal',row['id'],reason='核对质量来源')
        row=api('GET',path)
        return api('POST',path+'/post',dict(version=row['version'],reason='登记损失'))
    journal = journal_post(journal)
    assert journal['total_debit']=='2.00'
    reverse_path=f'production-costs/settlements/{settlement["id"]}/reverse'
    approve_document(quality_erp[0],quality_erp[1],'ProductionCostSettlement',settlement['id'],intent='reverse',reason='更正来源')
    api('POST',reverse_path,{'reason':'更正来源'},409)
    reversal=api('POST',f'finance/journals/{journal["id"]}/reverse',dict(version=journal['version'],
        reference='QUALITY-LOSS-REV',journal_date=journal['journal_date'],reason='先冲销质量损失'),201)
    state=api('GET',f'system/document-approvals/ProductionCostSettlement/{settlement["id"]}?intent=reverse')
    api('POST',f'system/document-approvals/ProductionCostSettlement/{settlement["id"]}/withdraw',{'version':state['version'],'intent':'reverse','reason':'更正原因重新核对'})
    approve_document(quality_erp[0],quality_erp[1],'ProductionCostSettlement',settlement['id'],intent='reverse',reason='冲销草稿不算过账')
    api('POST',reverse_path,{'reason':'冲销草稿不算过账'},409)
    journal_post(reversal)
    state=api('GET',f'system/document-approvals/ProductionCostSettlement/{settlement["id"]}?intent=reverse')
    api('POST',f'system/document-approvals/ProductionCostSettlement/{settlement["id"]}/withdraw',{'version':state['version'],'intent':'reverse','reason':'更正原因重新核对'})
    approve_document(quality_erp[0],quality_erp[1],'ProductionCostSettlement',settlement['id'],intent='reverse',reason='冲销质量损失后更正来源')
    api('POST',reverse_path,{'reason':'冲销质量损失后更正来源'})


def test_period_check_archives_quality_allocations_and_locks_corrections(quality_erp,monkeypatch):
    _,_,actors,api,_,_,order,_ = quality_erp
    work,completion=order('1','0')
    loss=posted(api,actors,payload(completion))
    api('POST','finance/accounting-periods',dict(code='QUALITY-YEAR',name='质量测试年',
        start_date='2026-01-01',end_date='2026-12-31',reason='核对质量成本'),201)
    monkeypatch.setattr('app.finance.period_closing.utc_today',lambda:'2027-01-01')
    path='finance/accounting-periods/1'
    check=api('GET',path+'/closing-check')
    assert 'unsettled_quality' in {row['code'] for row in check['blockers']}
    api('POST',path+'/close',{'version':1,'reason':'来源尚未结算'},409)
    settlement=settle(quality_erp,work['id'])
    check=api('GET',path+'/closing-check')
    assert check['can_close'],check['blockers']
    api('POST',path+'/close',{'version':1,'reason':'核对已固定质量成本'})
    evidence=api('GET',path+'/closings')[0]['evidence']['quality']
    assert evidence[0]['disposition']['id']==loss['id']
    assert evidence[0]['allocations'][0]['amount']=='2.00'
    api('POST',f'production-costs/settlements/{settlement["id"]}/reverse',{'reason':'不得更正关闭期间'},409)
    action(api,loss,'reverse',status=409)
    assert api('GET',path+'/closings')[0]['evidence']['quality']==evidence


def test_normal_loss_needs_accepted_output_and_explicit_correction(quality_erp):
    _,_,actors,api,_,_,order,_ = quality_erp
    original,completion = order('1','0')
    normal = posted(api,actors,payload(completion,treatment='absorb'))
    settle(quality_erp,original['id'],status=409)
    approve_document(quality_erp[0], quality_erp[1], 'QualityDisposition', normal['id'], intent='reverse', reason='复核质量依据')
    reversed_row = action(api,normal,'reverse')
    assert reversed_row['status'] == 'reversed'
    posted(api,actors,payload(completion,reference='ABNORMAL'))
    assert settle(quality_erp,original['id'])['total_amount'] == '2.00'


def test_labor_only_rework_reinspection_and_recursive_rejection(quality_erp):
    _,_,actors,api,_,product,order,complete = quality_erp
    original,completion = order('1','0')
    rework = posted(api,actors,payload(completion,kind='rework'))
    child_id = rework['rework_order_id']
    approve_document(quality_erp[0], quality_erp[1], 'WorkOrder', child_id)
    child = api('POST',f'work-orders/{child_id}/release')
    assert child['status'] == 'in_progress' and child['lines'] == []
    child_completion = complete(child_id,'1','0')
    final_loss = posted(api,actors,payload(child_completion,reference='REINSPECTION-LOSS'))
    settle(quality_erp,original['id'])
    result = settle(quality_erp,child_id,'REPAIR-COST')
    assert result['rework_amount'] == '2.00' and result['quality_allocations'][0]['amount'] == '2.00'
    assert result['quality_allocations'][0]['disposition_id'] == final_loss['id']
    assert not any(row['material_id']==product for row in api('GET','inventory/valuation')['movements'])


def test_independent_review_freeze_versions_permissions_and_cost_privacy(quality_erp):
    _,admin,actors,api,_,_,order,_ = quality_erp
    _,completion = order('2','0')
    row = api('POST',ROOT+'/dispositions',payload(completion,quantity='2'),201,actors['author'])
    submitted = action(api,row,'submit',actors['author'])
    action(api,submitted,'approve',actors['author'],403)
    api('GET',ROOT,status=403,actor=actors['seller'])
    api('PUT',f'{ROOT}/dispositions/{row["id"]}',{**payload(completion,quantity='2'),'version':submitted['version']},409)
    rejected = action(api,submitted,'reject',actors['reviewer'])
    edited = api('PUT',f'{ROOT}/dispositions/{row["id"]}',{**payload(completion,quantity='2'),
        'version':rejected['version'],'reason':'复核损失依据'},actor=admin)
    submitted = action(api,edited,'submit')
    assert api('GET',f'system/document-approvals/QualityDisposition/{submitted["id"]}')['can_review']
    action(api,submitted,'cancel',actors['reviewer'],403)
    action(api,row,'cancel',status=409)
    approved = action(api,submitted,'approve',actors['reviewer'])
    confirmed = action(api,approved,'post',actors['keeper'])
    original = api('GET',ROOT)['cases'][0]['work_order_id']
    settle(quality_erp,original)
    private = api('GET',f'{ROOT}/dispositions/{row["id"]}',actor=actors['keeper'])
    assert private['cost_allocation']['amount'] is None and not private['cost_visible']
    assert api('GET',f'{ROOT}/dispositions/{row["id"]}')['cost_allocation']['amount'] == '4.00'
    assert confirmed['frozen_source']['qc_note'] == '尺寸超差，隔离处理'
    assert len(private['changes']) == 7


@pytest.mark.parametrize('field,value', [('quantity','NaN'),('quantity','-1'),('quantity','0.0001'),
    ('completion_id',True),('warehouse_id',True),('loss_treatment','guess'),('action_note',' '),('unexpected','x')])
def test_strict_payload_rejection_does_not_create_dispositions(quality_erp,field,value):
    _,_,_,api,_,_,order,_ = quality_erp
    _,completion = order('1','0')
    api('POST',ROOT+'/dispositions',{**payload(completion),field:value},422)
    assert api('GET',ROOT)['dispositions'] == []


def test_parallel_submit_and_post_prevent_overallocation_or_duplicate_rework(quality_erp):
    client,admin,actors,api,_,_,order,_ = quality_erp
    _,completion = order('1','0')
    rows = [api('POST',ROOT+'/dispositions',payload(completion,kind='rework',reference=f'R-{i}'),201) for i in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda row: client.post(f'/api/v1/system/document-approvals/QualityDisposition/{row["id"]}/submit',
            headers=admin,json={'version':0,'reason':'并发质量处理'}),rows))
    assert sorted(response.status_code for response in responses) == [200,409]
    approved_id = next(response.json()['document_id'] for response in responses if response.status_code == 200)
    submitted = api('GET', f'{ROOT}/dispositions/{approved_id}')
    api('POST',f'production-completions/{completion["id"]}/reverse',{'reason':'修改来源'},409)
    approved = action(api,submitted,'approve',actors['reviewer'])
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post('/api/v1/'+ROOT+f'/dispositions/{approved["id"]}/post',
            headers=admin,json={'version':approved['version'],'reason':'并发确认'}),range(2)))
    assert sorted(response.status_code for response in responses) == [200,409]
    with orm_session() as db:
        assert len(list(db.scalars(select(WorkOrder)))) == 2


def test_post_audit_failure_rolls_back_rework_order_and_quantity(quality_erp,monkeypatch):
    _,_,actors,api,_,_,order,_ = quality_erp
    _,completion = order('1','0')
    row = api('POST',ROOT+'/dispositions',payload(completion,kind='rework'),201)
    approved = action(api,action(api,row,'submit'),'approve',actors['reviewer'])
    from app.production import quality
    original = quality.audit
    def fail_after_audit(*args):
        original(*args)
        raise HTTPException(409,'模拟确认后审计故障')
    monkeypatch.setattr(quality,'audit',fail_after_audit)
    action(api,approved,'post',status=409)
    current = api('GET',f'{ROOT}/dispositions/{row["id"]}')
    assert current == approved
    assert len(api('GET','work-orders')) == 1
    monkeypatch.setattr(quality,'audit',original)
    assert action(api,approved,'post')['rework_order_id'] is not None


def test_rework_reverse_cancels_source_only_after_downstream_correction(quality_erp):
    _,_,actors,api,_,_,order,complete = quality_erp
    _,completion = order('1','0')
    row = posted(api,actors,payload(completion,kind='rework'))
    api('POST',f'work-orders/{row["rework_order_id"]}/cancel',status=409)
    approve_document(quality_erp[0], quality_erp[1], 'WorkOrder', row['rework_order_id'])
    api('POST',f'work-orders/{row["rework_order_id"]}/release')
    child_completion = complete(row['rework_order_id'],'1','1')
    action(api,row,'reverse',status=409)
    # 独立审批完成后，再验证原库存约束或失败回滚。
    approve_document(quality_erp[0], quality_erp[1], 'ProductionCompletion', child_completion['id'], intent='reverse', reason='返工数量复核')
    api('POST',f'production-completions/{child_completion["id"]}/reverse',{'reason':'返工数量复核'})
    approve_document(quality_erp[0], quality_erp[1], 'QualityDisposition', row['id'], intent='reverse', reason='复核质量依据')
    reversed_row = action(api,row,'reverse')
    assert reversed_row['rework_order_id'] == row['rework_order_id']
    assert api('GET',ROOT)['cases'][0]['remaining_quantity'] == '1'
    assert next(order for order in api('GET','work-orders') if order['id']==row['rework_order_id'])['status'] == 'cancelled'
    action(api,reversed_row,'reverse',status=409)


def test_v50_upgrade_preserves_records_and_static_models(quality_erp,remove_quality_schema):
    _,_,_,api,_,_,order,_ = quality_erp
    original,_ = order('1','0')
    with sqlite3.connect(os.environ['NEXORA_DB_PATH']) as db:
        before = db.execute('SELECT * FROM work_orders').fetchall()
        remove_quality_schema(db)
        db.execute('PRAGMA user_version=50')
    migrate(); migrate()
    with sqlite3.connect(os.environ['NEXORA_DB_PATH']) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 100
        assert db.execute('SELECT * FROM work_orders').fetchall() == before
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        assert len(Base.metadata.tables) == 200
        assert db.execute("SELECT COUNT(*) FROM permissions WHERE code LIKE 'quality.%'").fetchone()[0] == 9
    assert api('GET',ROOT)['cases'][0]['work_order_id'] == original['id']


def test_upgrade_failure_rolls_back_column_tables_and_permissions(quality_erp,remove_quality_schema,monkeypatch):
    import app.core.database as database
    with database.connection() as db:
        remove_quality_schema(db)
        db.execute('PRAGMA user_version=50')
    original = database.connection
    @contextmanager
    def failing():
        with original() as db:
            db.set_authorizer(lambda operation,name,*_: sqlite3.SQLITE_DENY if operation == sqlite3.SQLITE_CREATE_TABLE
                and name == 'quality_disposition_changes' else sqlite3.SQLITE_OK)
            yield db
    monkeypatch.setattr(database,'connection',failing)
    with pytest.raises(Exception):
        migrate()
    with original() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 50
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='quality_dispositions'").fetchone()
        assert not any(row[1]=='rework_amount' for row in db.execute('PRAGMA table_info(production_cost_settlements)'))
