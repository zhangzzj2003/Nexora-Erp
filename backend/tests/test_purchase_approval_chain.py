"""审批提交快照、节点岗位、禁止自审及重复节点回归。"""
from test_ledger_foundation import ledger


def login(client,name):return {'Authorization':'Bearer '+client.post('/api/v1/auth/login',json={'username':name,'password':'secure-pass-123'}).json()['token']}


def test_policy_snapshot_sequential_approval_and_self_guard(ledger):
    client=ledger;url='/api/v1/purchase/approvals'
    for name in ('review1','review2'):
        result=client.post('/api/v1/users',json={'username':name,'password':'secure-pass-123','roles':['admin']});assert result.status_code==201
    ids={row['username']:row['id'] for row in client.get('/api/v1/users').json()}
    policy={'version':0,'enabled':True,'reason':'分级审批','rules':[{'department':'','minimum':'0','maximum':None,'steps':[{'role_code':'admin','approver_id':ids['review1']},{'role_code':'admin','approver_id':ids['review2']}]}]}
    saved=client.put(url,json=policy);assert saved.status_code==200,saved.text
    material=client.post('/api/v1/materials',json={'sku':'APR','name':'审批物料','unit':'件'}).json()['id']
    request=client.post('/api/v1/purchase-requests',json={'department':'生产','estimated_total':'200','lines':[{'material_id':material,'quantity':'1'}]}).json()['id']
    endpoint=f'/api/v1/purchase-requests/{request}'
    submitted=client.post(endpoint+'/submit');assert submitted.status_code==200,submitted.text
    assert submitted.json()['policy_version']==1 and len(submitted.json()['approval_steps'])==2
    # 修改公司规则不会减少已提交申请的节点数。
    assert client.put(url,json={**policy,'version':1,'enabled':False}).status_code==200
    assert client.post(endpoint+'/approve').status_code==403
    reviewer1,reviewer2=login(client,'review1'),login(client,'review2')
    assert client.post(endpoint+'/approve',headers=reviewer2).status_code==403
    first=client.post(endpoint+'/approve',headers=reviewer1);assert first.status_code==200 and first.json()['status']=='submitted'
    assert client.post(endpoint+'/approve',headers=reviewer1).status_code==403
    approved=client.post(endpoint+'/approve',headers=reviewer2);assert approved.status_code==200 and approved.json()['status']=='approved'
    assert client.post(endpoint+'/approve',headers=reviewer2).status_code==409


def test_policy_overlapping_intervals_and_version_rejected(ledger):
    rule={'department':'生产','minimum':'0','maximum':'100','steps':[{'role_code':'admin','approver_id':None}]}
    endpoint='/api/v1/purchase/approvals'
    assert ledger.put(endpoint,json={'version':0,'enabled':True,'reason':'规则','rules':[rule,rule]}).status_code==422
    saved=ledger.put(endpoint,json={'version':0,'enabled':True,'reason':'规则','rules':[rule]});assert saved.status_code==200
    assert ledger.put(endpoint,json={'version':0,'enabled':False,'reason':'规则','rules':[rule]}).status_code==409


def test_cancel_terminates_pending_steps_and_history_is_paged(ledger):
    rule={'department':'','minimum':'0','maximum':None,'steps':[{'role_code':'admin','approver_id':None}]}
    assert ledger.put('/api/v1/purchase/approvals',json={'version':0,'enabled':True,'reason':'规则','rules':[rule]}).status_code==200
    material=ledger.post('/api/v1/materials',json={'sku':'CANCEL-APR','name':'审批物料','unit':'件'}).json()['id']
    created=ledger.post('/api/v1/purchase-requests',json={'reference':'保留原需求','lines':[{'material_id':material,'quantity':'2'}]}).json()
    path=f"/api/v1/purchase-requests/{created['id']}"
    submitted=ledger.post(path+'/submit').json()
    cancelled=ledger.post(path+'/cancel');assert cancelled.status_code==200,cancelled.text
    assert cancelled.json()['version']>submitted['version']
    assert all(step['status']=='cancelled' for step in cancelled.json()['approval_steps'])
    history=ledger.post('/api/v1/tables/query',json={'dataset':'purchaseApprovalHistory','page':1,'page_size':2})
    assert history.status_code==200,history.text
    assert history.json()['total']==4 and len(history.json()['items'])==2
    assert history.json()['items'][0]['action']=='cancel'
