"""维护、售后派生耗材单继续排除原方案编制人员，且独立批准前不扣库存。"""

import pytest

from test_equipment import erp as equipment_erp, job_input, action as equipment_action
from test_after_sales import erp as after_sales_erp, payload, action as after_sales_action


def approval_path(identifier):
    return f'/api/v1/system/document-approvals/WarehouseOutbound/{identifier}'


@pytest.mark.parametrize('legacy', [False, True])
def test_maintenance_editor_cannot_review_derived_outbound(equipment_erp, monkeypatch, legacy):
    client, api, actors, _, _, part = equipment_erp
    data = job_input(equipment_erp, warehouse_id=1, parts=[{'material_id': part, 'quantity': '2'}])
    job = api('POST', 'equipment/jobs', data, status=201)
    # 原方案由第三人修订和送审，后续生成子单仍须保留这位编制人员的排除记录。
    job = api('PUT', f"equipment/jobs/{job['id']}", {**data, 'version': job['version']}, actor='third')
    job = equipment_action(api, job, 'submit', actor='third')
    job = equipment_action(api, job, 'approve', actor='reviewer')
    if legacy:
        # 模拟旧服务转单时未写入新作者表；原编制审计、真实送审与权限校验仍照常执行。
        monkeypatch.setattr('app.production.equipment.record_author', lambda *_: None)
    job = equipment_action(api, job, 'start')
    identifier = job['parts_outbound_id']
    assert client.post(f'/api/v1/warehouse-outbounds/{identifier}/post', headers=actors['admin']).status_code == 409
    state = client.post(approval_path(identifier) + '/submit', headers=actors['reviewer'], json={'version': 0})
    assert state.status_code == 200, state.text
    for author in ('admin', 'third', 'reviewer'):
        assert not client.get(approval_path(identifier), headers=actors[author]).json()['can_review']
        assert client.post(approval_path(identifier) + '/approve', headers=actors[author], json={'version': 1}).status_code == 403
    assert api('GET', 'stock')[0]['quantity'] == '10'


@pytest.mark.parametrize('legacy', [False, True])
def test_after_sales_editor_cannot_review_derived_outbound(after_sales_erp, monkeypatch, legacy):
    client, api, actors, _, _, part, _ = after_sales_erp
    # 使用有完整审核权限的编辑账号，证明拒绝来自作者隔离，而非缺少角色权限。
    token = client.post('/api/v1/auth/login', json={'username': 'independent_reviewer_1',
                                                 'password': 'approval-test-pass-123'}).json()['token']
    editor = {'Authorization': 'Bearer ' + token}
    data = payload(after_sales_erp, warehouse_id=1, parts=[{'material_id': part, 'quantity': '2'}])
    case = api('POST', 'after-sales/cases', data, status=201)
    edited = client.put(f"/api/v1/after-sales/cases/{case['id']}", headers=editor,
                        json={**data, 'version': case['version']})
    assert edited.status_code == 200, edited.text
    case = after_sales_action(api, edited.json(), 'submit')
    case = after_sales_action(api, case, 'approve', actor='reviewer')
    if legacy:
        monkeypatch.setattr('app.sales.after_sales.record_author', lambda *_: None)
    case = after_sales_action(api, case, 'receive')
    identifier = case['parts_outbound_id']
    assert client.post(f'/api/v1/warehouse-outbounds/{identifier}/post', headers=actors['admin']).status_code == 409
    state = client.post(approval_path(identifier) + '/submit', headers=actors['admin'], json={'version': 0})
    assert state.status_code == 200, state.text
    for author in (editor, actors['admin']):
        assert not client.get(approval_path(identifier), headers=author).json()['can_review']
        assert client.post(approval_path(identifier) + '/approve', headers=author, json={'version': 1}).status_code == 403
    assert next(item for item in api('GET', 'stock') if item['id'] == part)['quantity'] == '20'
