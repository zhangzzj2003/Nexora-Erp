"""以真实接口验证少签批次、退换料共用来源与在制成本方向。"""

from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from approval_test_helpers import approve_document, receive_legacy_issue
from app.core.models import MaterialFlowExecutionLot
from app.core.orm import orm_session
from app.finance.business_sources import business_sources
from app.main import app


@pytest.fixture
def flow_lots(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'production-flow-lots.db'))
    with TestClient(app, client=('127.0.0.1', 12000)) as client:
        client.post('/api/v1/setup/admin', json={'username': 'admin', 'password': 'secure-pass-123'})
        token = client.post('/api/v1/auth/login', json={'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
        auth = {'Authorization': 'Bearer ' + token}

        def api(method, path, data=None, status=200):
            response = client.request(method, '/api/v1/' + path, json=data, headers=auth)
            assert response.status_code == status, response.text
            return response.json()

        raw = api('POST', 'materials', {'sku': 'COVER', 'name': '上盖', 'unit': '个'}, 201)['id']
        product = api('POST', 'materials', {'sku': 'MACHINE', 'name': '机器', 'unit': '台'}, 201)['id']
        inbound = api('POST', 'warehouse-inbounds', {'warehouse_id': 1, 'reason': 'other',
            'note': '现场期初核对', 'lines': [{'material_id': raw, 'quantity': '200'}]}, 201)
        approve_document(client, auth, 'WarehouseInbound', inbound['id'])
        inbound = api('POST', f'warehouse-inbounds/{inbound["id"]}/post', {'lines': [{
            'inbound_line_id': inbound['lines'][0]['id'], 'lots': [{'quantity': '100', 'supplier_lot': 'A'},
                                                               {'quantity': '100', 'supplier_lot': 'B'}]}]})
        lot_a, lot_b = [row['id'] for row in inbound['lines'][0]['physical_lots']]
        movement = next(row for row in api('GET', 'movements') if row['source_type'] == 'other_inbound')
        api('POST', 'inventory/valuation/inputs', {'movement_id': movement['id'], 'unit_cost': '3',
            'reference': '原料核价', 'reason': '核对原料期初成本'}, 201)
        bom = api('POST', 'boms', {'product_material_id': product, 'base_quantity': '1',
            'lines': [{'component_material_id': raw, 'quantity': '1'}]}, 201)
        api('POST', f'boms/{bom["id"]}/activate')
        order = api('POST', 'work-orders', {'bom_id': bom['id'], 'warehouse_id': 1, 'target_quantity': '100'}, 201)
        approve_document(client, auth, 'WorkOrder', order['id'])
        api('POST', f'work-orders/{order["id"]}/release')
        dispatch = api('POST', 'material-dispatches', {'request_id': str(uuid4()), 'work_order_id': order['id'],
            'warehouse_id': 1, 'lines': [{'work_order_line_id': order['lines'][0]['id'], 'quantity': '100'}]}, 201)
        approve_document(client, auth, 'MaterialDispatch', dispatch['id'])
        dispatch = api('POST', f'material-dispatches/{dispatch["id"]}/execute', {
            'request_id': str(uuid4()), 'version': dispatch['version'], 'lines': [{'line_id': dispatch['lines'][0]['id'],
            'quantity': '60', 'lots': [{'lot_id': lot_a, 'quantity': '30'}, {'lot_id': lot_b, 'quantity': '30'}]}]})
        receipt = api('GET', 'material-receipts')['items'][0]
        yield api, client, auth, order, raw, dispatch, receipt, lot_a, lot_b


def action(row, quantity, lots=None):
    return {'request_id': str(uuid4()), 'version': row['version'], 'reason': '实物交接核对',
            'lines': [{'line_id': row['lines'][0]['id'], 'quantity': quantity,
                       **({'lots': lots} if lots is not None else {})}]}


def test_partial_signature_cannot_return_an_unsigned_lot(flow_lots):
    api, client, auth, order, raw, dispatch, receipt, lot_a, lot_b = flow_lots
    endpoint = f'material-receipts/{receipt["id"]}'
    # 两个批次少签两个时必须明确少收批次，系统不能自行猜测。
    api('POST', endpoint + '/execute', action(receipt, '58'), 422)
    signed = api('POST', endpoint + '/execute', action(receipt, '58', [
        {'lot_id': lot_a, 'quantity': '30'}, {'lot_id': lot_b, 'quantity': '28'}]))
    summary = api('GET', f'work-orders/{order["id"]}/material-flow')
    assert Decimal(summary['lines'][0]['effective_quantity']) == 58
    assert Decimal(summary['lines'][0]['in_transit_quantity']) == 2
    # A 已全签收，待签差额只能来自 B；失败不能生成入库流水。
    api('POST', endpoint + '/handover-return', action(signed, '2', [{'lot_id': lot_a, 'quantity': '2'}]), 409)
    returned_handover = api('POST', endpoint + '/handover-return', action(signed, '2', [{'lot_id': lot_b, 'quantity': '2'}]))
    assert returned_handover['status'] == 'completed'
    returned = api('POST', 'material-returns/flow', {'request_id': str(uuid4()), 'work_order_id': order['id'],
        'warehouse_id': 1, 'reason': '多余可用上盖退回', 'lines': [{'work_order_line_id': order['lines'][0]['id'],
        'source_receipt_line_id': signed['lines'][0]['id'], 'quantity': '29'}]}, 201)
    approve_document(client, auth, 'ProductionMaterialReturn', returned['id'])
    # B 只有 28 个已签收，不能用 A 的总签收余额冒充 B 的可退数量。
    api('POST', f'material-returns/flow/{returned["id"]}/execute', action(returned, '29', [{'lot_id': lot_b, 'quantity': '29'}]), 409)
    returned = api('POST', f'material-returns/flow/{returned["id"]}/execute', action(returned, '28', [{'lot_id': lot_b, 'quantity': '28'}]))
    assert Decimal(returned['remaining_quantity']) == 1
    stock = next(row for row in api('GET', 'stock') if row['id'] == raw)
    assert Decimal(stock['quantity']) == 170
    with orm_session() as db:
        assert list(db.scalars(select(MaterialFlowExecutionLot.id)))
        sources = business_sources(db)
    assert sources[f'material_dispatch:{dispatch["id"]}']['roles'] == {'inventory': '-180.00', 'work_in_progress': '180.00'}
    assert sources[f'production_material_return:{returned["id"]}']['roles'] == {'inventory': '84.00', 'work_in_progress': '-84.00'}
    assert sources[f'material_handover_return:{receipt["id"]}']['roles'] == {'inventory': '6.00', 'work_in_progress': '-6.00'}


def test_partial_known_and_unknown_source_requires_actual_lot_selection(flow_lots):
    api, client, auth, order, _, dispatch, _, lot_a, _ = flow_lots
    # 第二次出库未指定批次，现场仅补证其中 5 个；其余 35 个保持未知来源。
    api('POST', f'material-dispatches/{dispatch["id"]}/execute', action(dispatch, '40'))
    pending = api('GET', 'material-receipts')['items'][0]
    movement = next(row for row in api('GET', 'movements') if row['source_type'] == 'material_dispatch'
                    and Decimal(row['quantity']) == -40)
    api('POST', f'inventory/physical-lots/movements/{movement["id"]}/evidence', {
        'quantity': '5', 'lot_id': lot_a, 'evidence': '现场只核实其中五个上盖属于此批次'}, 201)
    endpoint = f'material-receipts/{pending["id"]}'
    api('POST', endpoint + '/execute', action(pending, '5'), 422)
    assert api('GET', endpoint)['executions'] == []
    # 全量交接可保留已知 5 个和未知 35 个；不能把 40 个都冒充已知批次。
    signed = api('POST', endpoint + '/execute', action(pending, '40'))
    fact_id = signed['executions'][0]['lines'][0]['id']
    with orm_session() as db:
        lots = list(db.scalars(select(MaterialFlowExecutionLot).where(
            MaterialFlowExecutionLot.execution_line_id == fact_id)))
        assert len(lots) == 1 and lots[0].lot_id == lot_a and Decimal(lots[0].quantity) == 5
    returned = api('POST', 'material-returns/flow', {'request_id': str(uuid4()), 'work_order_id': order['id'],
        'warehouse_id': 1, 'reason': '退回已核对上盖', 'lines': [{'work_order_line_id': order['lines'][0]['id'],
        'source_receipt_line_id': signed['lines'][0]['id'], 'quantity': '5'}]}, 201)
    approve_document(client, auth, 'ProductionMaterialReturn', returned['id'])
    path = f'material-returns/flow/{returned["id"]}/execute'
    api('POST', path, action(returned, '5'), 422)
    api('POST', path, action(returned, '5', [{'lot_id': lot_a, 'quantity': '5'}]))


def test_late_evidence_cannot_reassign_unknown_signed_material_to_pending_handover(flow_lots):
    api, _, _, _, _, dispatch, _, lot_a, _ = flow_lots
    api('POST', f'material-dispatches/{dispatch["id"]}/execute', action(dispatch, '40'))
    pending = api('GET', 'material-receipts')['items'][0]
    api('POST', f'material-receipts/{pending["id"]}/execute', action(pending, '38'))
    movement = next(row for row in api('GET', 'movements') if row['source_type'] == 'material_dispatch'
                    and Decimal(row['quantity']) == -40)
    result = api('POST', f'inventory/physical-lots/movements/{movement["id"]}/evidence', {
        'quantity': '5', 'lot_id': lot_a, 'evidence': '事后拟将已发出的五个上盖补充归批'}, 409)
    assert '交接' in result['detail']
    # 拒绝后待签的 2 个仍保持未知，不能依据新补证冒充任意已知批次。
    assert api('GET', f'material-receipts/{pending["id"]}/available-lots')['lines'][0]['lots'] == []


@pytest.mark.parametrize('historical_direct', [False, True])
def test_legacy_return_uses_signed_lots_and_shares_new_return_capacity(flow_lots, historical_direct):
    api, client, auth, template, _, _, _, lot_a, lot_b = flow_lots
    order = api('POST', 'work-orders', {'bom_id': template['bom_id'], 'warehouse_id': 1,
        'target_quantity': '10'}, 201)
    approve_document(client, auth, 'WorkOrder', order['id'])
    api('POST', f'work-orders/{order["id"]}/release')
    issue = api('POST', 'material-issues', {'work_order_id': order['id'], 'warehouse_id': 1,
        'lines': [{'work_order_line_id': order['lines'][0]['id'], 'quantity': '10'}]}, 201)
    approve_document(client, auth, 'MaterialIssue', issue['id'])
    issue = api('POST', f'material-issues/{issue["id"]}/post', {'lines': [{
        'material_issue_line_id': issue['lines'][0]['id'], 'lots': [
            {'lot_id': lot_a, 'quantity': '5'}, {'lot_id': lot_b, 'quantity': '5'}]}]})
    if historical_direct:
        from app.core.database import database_path, migrate
        from test_production_material_migration import restore_v102_material_schema
        # 真正走旧库迁移标记历史直接领料，不伪造生产签收事实。
        restore_v102_material_schema(database_path())
        migrate()
    else:
        receipt = api('GET', f'material-receipts/{issue["material_receipt_id"]}')
        receipt = api('POST', f'material-receipts/{receipt["id"]}/execute', action(receipt, '5', [
            {'lot_id': lot_a, 'quantity': '5'}]))
    old_return = api('POST', 'material-returns', {'material_issue_id': issue['id'], 'reason': '可用余料退回',
        'lines': [{'material_issue_line_id': issue['lines'][0]['id'], 'quantity': '5'}]}, 201)
    approve_document(client, auth, 'MaterialReturn', old_return['id'])
    old_path = f'material-returns/{old_return["id"]}'
    old_payload = lambda lot: {'lines': [{'return_line_id': old_return['lines'][0]['id'],
        'lots': [{'lot_id': lot, 'quantity': '5'}]}]}
    if not historical_direct:
        # B 尚未签收，即使原出库记有 B，也不能从旧退料入口提前入库。
        api('POST', old_path + '/post', old_payload(lot_b), 422)
        receipt = api('POST', f'material-receipts/{receipt["id"]}/execute', action(receipt, '5', [
            {'lot_id': lot_b, 'quantity': '5'}]))
    new_return = api('POST', 'material-returns/flow', {'request_id': str(uuid4()), 'work_order_id': order['id'],
        'warehouse_id': 1, 'reason': '另批余料退回', 'lines': [{'work_order_line_id': order['lines'][0]['id'],
            'legacy_issue_line_id': issue['lines'][0]['id'], 'quantity': '5'}]}, 201)
    approve_document(client, auth, 'ProductionMaterialReturn', new_return['id'])
    api('POST', f'material-returns/flow/{new_return["id"]}/execute', action(new_return, '5', [
        {'lot_id': lot_a, 'quantity': '5'}]))
    # A 已从新入口入库，旧单只能接收仍可退的 B；失败不能追加库存流水。
    before = api('GET', 'movements')
    api('POST', old_path + '/post', old_payload(lot_a), 409)
    assert api('GET', 'movements') == before
    options = api('GET', old_path + '/available-lots')['lines'][0]['lots']
    assert [(row['lot_id'], Decimal(row['quantity'])) for row in options] == [(lot_b, Decimal(5))]
    api('POST', old_path + '/post', old_payload(lot_b))


def test_unallocated_legacy_return_does_not_guess_lot_for_entire_remaining_source(flow_lots):
    api, client, auth, template, _, _, _, lot_a, lot_b = flow_lots
    order = api('POST', 'work-orders', {'bom_id': template['bom_id'], 'warehouse_id': 1,
        'target_quantity': '10'}, 201)
    approve_document(client, auth, 'WorkOrder', order['id'])
    api('POST', f'work-orders/{order["id"]}/release')
    issue = api('POST', 'material-issues', {'work_order_id': order['id'], 'warehouse_id': 1,
        'lines': [{'work_order_line_id': order['lines'][0]['id'], 'quantity': '10'}]}, 201)
    approve_document(client, auth, 'MaterialIssue', issue['id'])
    issue = api('POST', f'material-issues/{issue["id"]}/post', {'lines': [{
        'material_issue_line_id': issue['lines'][0]['id'], 'lots': [
            {'lot_id': lot_a, 'quantity': '5'}, {'lot_id': lot_b, 'quantity': '5'}]}]})
    receive_legacy_issue(client, auth, issue['id'])
    old_return = api('POST', 'material-returns', {'material_issue_id': issue['id'], 'reason': '旧客户端未登记批次',
        'lines': [{'material_issue_line_id': issue['lines'][0]['id'], 'quantity': '5'}]}, 201)
    approve_document(client, auth, 'MaterialReturn', old_return['id'])
    api('POST', f'material-returns/{old_return["id"]}/post')
    returned = api('POST', 'material-returns/flow', {'request_id': str(uuid4()), 'work_order_id': order['id'],
        'warehouse_id': 1, 'reason': '核对剩余材料退回', 'lines': [{'work_order_line_id': order['lines'][0]['id'],
            'legacy_issue_line_id': issue['lines'][0]['id'], 'quantity': '5'}]}, 201)
    approve_document(client, auth, 'ProductionMaterialReturn', returned['id'])
    path = f'material-returns/flow/{returned["id"]}'
    before = api('GET', 'movements')
    # 虽然本次退完剩余 5 个，旧退料没有批次证据，系统不能自行认定剩余全部属于 A。
    api('POST', path + '/execute', action(returned, '5'), 422)
    assert api('GET', 'movements') == before
    assert api('GET', path)['executions'] == []
    posted = api('POST', path + '/execute', action(returned, '5', [{'lot_id': lot_b, 'quantity': '5'}]))
    fact_id = posted['executions'][0]['lines'][0]['id']
    with orm_session() as db:
        lots = list(db.scalars(select(MaterialFlowExecutionLot).where(
            MaterialFlowExecutionLot.execution_line_id == fact_id)))
        assert [(row.lot_id, Decimal(row.quantity)) for row in lots] == [(lot_b, Decimal(5))]
    assert posted['status'] == 'completed'
