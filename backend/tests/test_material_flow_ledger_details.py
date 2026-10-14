"""新生产物料流水及反向流水沿用台账只读详情与双重查看权限。"""
from uuid import uuid4

import pytest

from approval_test_helpers import approve_document
from test_inventory_ledger_details import detail
from test_production_settlements import erp
from test_production_material_accounting import create_order, execute, receipts


@pytest.fixture
def flow_movements(erp):
    client, auth, api, *_ = erp
    _, _, order, dispatch = create_order(erp)
    execute(api, 'material-dispatches', dispatch, '100')
    receipt = execute(api, 'material-receipts', receipts(api, order)[0], '98')
    receipt = api('POST', f'material-receipts/{receipt["id"]}/handover-return', {
        'version': receipt['version'], 'request_id': str(uuid4()), 'reason': '两件未交接实物退仓',
        'lines': [{'line_id': receipt['lines'][0]['id'], 'quantity': '2'}]})
    returned = api('POST', 'material-returns/flow', {'work_order_id': order['id'], 'warehouse_id': 1,
        'request_id': str(uuid4()), 'reason': '可用余料退回', 'lines': [{
            'work_order_line_id': order['lines'][0]['id'],
            'source_receipt_line_id': receipt['lines'][0]['id'], 'quantity': '4'}]}, 201)
    approve_document(client, auth, 'ProductionMaterialReturn', returned['id'])
    returned = execute(api, 'material-returns/flow', returned, '4')
    expected = {'material_dispatch': ('MaterialDispatch', dispatch),
                'material_handover_return': ('MaterialReceipt', receipt),
                'production_material_return': ('ProductionMaterialReturn', returned)}
    for base, model, document in (
        ('material-returns/flow', 'ProductionMaterialReturn', returned),
        ('material-receipts', 'MaterialReceipt', receipt),
        ('material-dispatches', 'MaterialDispatch', dispatch),
    ):
        current = api('GET', f'{base}/{document["id"]}')
        reason = '重新核对收发记录'
        approve_document(client, auth, model, current['id'], intent='reverse', reason=reason)
        api('POST', f'{base}/{current["id"]}/reverse', {'version': current['version'],
            'request_id': str(uuid4()), 'reason': reason})
    rows = [row for row in api('POST', 'inventory-ledger/query', {})['rows']
            if row['source_type'].removesuffix('_reversal') in expected]
    assert len(rows) == 6
    return client, auth, api, expected, rows


def assert_read_only_details(client, auth, expected, rows):
    for row in rows:
        response = detail(client, auth, row['id'])
        assert response.status_code == 200, response.text
        document = response.json()['document']
        model, original = expected[row['source_type'].removesuffix('_reversal')]
        assert (document['document_type'], document['document_id'], document['document_no']) == (
            model, original['id'], original['document_no'])
        assert document['intent'] == ('reverse' if row['source_type'].endswith('_reversal') else 'execute')
        assert not any(document[key] for key in ('can_submit', 'can_review', 'can_withdraw'))
        if model == 'MaterialReceipt' and document['intent'] == 'execute':
            assert document['events'] == [] and document['steps'] == []
            assert {'label': '签收方式', 'value': '无需普通审批，按权限确认签收；更正另行审批'} in document['summary']


def test_new_flow_original_and_reversal_details_use_original_header_and_read_only_flags(flow_movements):
    client, auth, api, expected, rows = flow_movements
    assert_read_only_details(client, auth, expected, rows)
    receipt = expected['material_handover_return'][1]
    # 台账只读适配不能放开签收普通送审入口，也不补造审批记录。
    api('POST', f'system/document-approvals/MaterialReceipt/{receipt["id"]}/submit',
        {'intent': 'execute', 'version': 0}, 422)


@pytest.mark.parametrize('permissions, allowed', [
    (['inventory.view'], False), (['material_flow.view'], False),
    (['inventory.view', 'material_flow.view'], True),
])
def test_new_flow_ledger_details_require_inventory_and_flow_view(flow_movements, permissions, allowed):
    client, auth, api, expected, rows = flow_movements
    api('POST', 'roles', {'code': 'flow_ledger_reader', 'label': '生产台账查看', 'permissions': permissions}, 201)
    api('POST', 'users', {'username': 'flow_ledger_reader', 'password': 'secure-pass-123',
        'roles': ['flow_ledger_reader']}, 201)
    token = api('POST', 'auth/login', {'username': 'flow_ledger_reader', 'password': 'secure-pass-123'})['token']
    viewer = {'Authorization': 'Bearer ' + token}
    if allowed:
        assert_read_only_details(client, viewer, expected, rows)
    else:
        for row in rows:
            assert detail(client, viewer, row['id']).status_code == 403
    assert detail(client, {}, rows[0]['id']).status_code == 401
