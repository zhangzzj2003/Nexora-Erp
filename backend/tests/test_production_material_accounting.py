"""四类物料流程对报工、需求计划及逐次出库成本的跨模块约束。"""

from approval_test_helpers import planned_order

from decimal import Decimal
from uuid import uuid4

from approval_test_helpers import approve_document, execute_production_settlement
from app.core.orm import orm_session
from app.production.mrp_sources import collect
from app.production.work_orders import issued_quantity
from test_production_settlements import erp


def create_order(erp, quantity='100', unit_cost='2'):
    client, headers, api, material, receipt, *_ = erp
    raw, product = material('FLOW-RAW'), material('FLOW-PRODUCT')
    receipt(raw, '200', unit_cost)
    bom = api('POST', 'boms', {'product_material_id': product, 'base_quantity': '1',
        'lines': [{'component_material_id': raw, 'quantity': '1'}]}, 201)
    api('POST', f'boms/{bom["id"]}/activate')
    order = planned_order(api, {'bom_id': bom['id'], 'warehouse_id': 1,
        'target_quantity': quantity}, 201)
    approve_document(client, headers, 'WorkOrder', order['id'])
    api('POST', f'work-orders/{order["id"]}/release')
    dispatch = api('POST', 'material-dispatches', {'work_order_id': order['id'], 'warehouse_id': 1,
        'request_id': str(uuid4()), 'lines': [{'work_order_line_id': order['lines'][0]['id'], 'quantity': quantity}]}, 201)
    approve_document(client, headers, 'MaterialDispatch', dispatch['id'])
    return raw, product, order, dispatch


def execute(api, kind, record, quantity):
    return api('POST', f'{kind}/{record["id"]}/execute', {'version': record['version'],
        'request_id': str(uuid4()), 'lines': [{'line_id': record['lines'][0]['id'], 'quantity': quantity}]})


def receipts(api, order):
    return api('GET', f'material-receipts?work_order_id={order["id"]}')['items']


def completion(erp, order, quantity, status=200):
    client, headers, api, *_ = erp
    row = api('POST', 'production-completions', {'work_order_id': order['id'], 'reported_quantity': quantity}, 201)
    api('POST', f'production-completions/{row["id"]}/inspect', {'accepted_quantity': quantity, 'qc_note': '逐批检验合格'})
    approve_document(client, headers, 'ProductionCompletion', row['id'])
    return api('POST', f'production-completions/{row["id"]}/post', status=status)


def test_in_transit_not_usable_or_replanned_and_pending_return_blocks_consumption(erp):
    client, headers, api, *_ = erp
    raw, _, order, dispatch = create_order(erp)
    execute(api, 'material-dispatches', dispatch, '60')
    signed = execute(api, 'material-receipts', receipts(api, order)[0], '58')
    # 库存只扣实际发出 60；MRP 不把未签的 2 再算成新的发料需求。
    stock = next(row for row in api('GET', 'stock?warehouse_id=1') if row['id'] == raw)
    assert Decimal(stock['quantity']) == 140
    with orm_session() as db:
        assert issued_quantity(db, order['lines'][0]['id']) == 58
        reservations = collect(db)['reservations']
        assert Decimal(next(row for row in reservations if row['source_id'] == order['id'])['quantity']) == 40
    returned = api('POST', 'material-returns/flow', {'work_order_id': order['id'], 'warehouse_id': 1,
        'request_id': str(uuid4()), 'reason': '未使用余料', 'lines': [{
            'work_order_line_id': order['lines'][0]['id'], 'source_receipt_line_id': signed['lines'][0]['id'],
            'quantity': '2'}]}, 201)
    completion(erp, order, '57', 409)
    with orm_session() as db:
        assert issued_quantity(db, order['lines'][0]['id']) == 56
    summary = api('GET', f'work-orders/{order["id"]}/material-flow')['lines'][0]
    # 尚未实退不减有效材料，但预留部分不能与报工重复使用。
    assert Decimal(summary['effective_quantity']) == 58
    assert Decimal(summary['available_quantity']) == 56
    assert Decimal(summary['reserved_quantity']) == 2
    api('POST', f'material-returns/flow/{returned["id"]}/close', {'version': returned['version'],
        'request_id': str(uuid4()), 'reason': '生产继续使用，无实物退回'})
    completion(erp, order, '58')
    # 满足物料条件的分批报工允许执行，工单仍然保留交接差额和待发数量。
    assert api('GET', 'work-orders')[0]['status'] == 'in_progress'


def test_summary_separates_legacy_return_reservation_from_effective_material(erp):
    _, _, api, material, inbound, work_order, *_ = erp
    raw, product = material('LEGACY-SUMMARY-RAW'), material('LEGACY-SUMMARY-PRODUCT')
    inbound(raw, '20', '2')
    order, issue = work_order(raw, product, '10')
    api('POST', 'material-returns', {'material_issue_id': issue['id'], 'reason': '旧入口余料待退',
        'lines': [{'material_issue_line_id': issue['lines'][0]['id'], 'quantity': '2'}]}, 201)
    # 兼容入口的草稿与新单据预留使用同一汇总口径，不把未入库材料提前扣作实退。
    summary = api('GET', f'work-orders/{order["id"]}/material-flow')['lines'][0]
    assert Decimal(summary['effective_quantity']) == 10
    assert Decimal(summary['available_quantity']) == 8
    assert Decimal(summary['reserved_quantity']) == 2
    assert Decimal(summary['returned_quantity']) == 0


def test_dispatch_costs_and_settlement_preserve_each_actual_execution_price(erp):
    client, headers, api, _, inbound, *_ = erp
    raw, _, order, dispatch = create_order(erp)
    dispatch = execute(api, 'material-dispatches', dispatch, '40')
    execute(api, 'material-receipts', receipts(api, order)[0], '40')
    inbound(raw, '160', '4')
    # 原料先出 40 后补入 160，第二次移动均价变为 3 元，不能覆盖第一笔 2 元。
    dispatch = execute(api, 'material-dispatches', dispatch, '60')
    execute(api, 'material-receipts', receipts(api, order)[0], '60')
    cost = api('GET', 'production-costs')
    assert cost['orders'][0]['known_material_amount'] == '260.00'
    sources = cost['material_sources']
    assert len(sources) == 2
    assert {Decimal(row['unit_cost']) for row in sources} == {Decimal(2), Decimal(3)}
    assert len({row['movement_id'] for row in sources}) == 2
    completion(erp, order, '100')
    settlement = api('POST', 'production-costs/settlements', {'work_order_id': order['id'], 'reference': 'FLOW-COST'}, 201)
    settlement = execute_production_settlement(client, headers, settlement)
    assert settlement['material_amount'] == '260.00'
    assert len(settlement['material_sources']) == 2
    assert {Decimal(row['unit_cost']) for row in settlement['material_sources']} == {Decimal(2), Decimal(3)}


def test_good_return_uses_original_execution_cost_instead_of_current_average(erp):
    client, headers, api, _, inbound, *_ = erp
    raw, _, order, dispatch = create_order(erp)
    execute(api, 'material-dispatches', dispatch, '100')
    signed = execute(api, 'material-receipts', receipts(api, order)[0], '100')
    inbound(raw, '100', '8')
    returned = api('POST', 'material-returns/flow', {'work_order_id': order['id'], 'warehouse_id': 1,
        'request_id': str(uuid4()), 'reason': '可用余料返库', 'lines': [{
            'work_order_line_id': order['lines'][0]['id'], 'source_receipt_line_id': signed['lines'][0]['id'],
            'quantity': '10'}]}, 201)
    approve_document(client, headers, 'ProductionMaterialReturn', returned['id'])
    execute(api, 'material-returns/flow', returned, '4')
    returned = api('GET', f'material-returns/flow/{returned["id"]}')
    execute(api, 'material-returns/flow', returned, '6')
    report = api('GET', 'inventory/valuation')
    return_movements = [row for row in report['movements'] if row['source_type'] == 'production_material_return']
    assert len(return_movements) == 2
    assert {Decimal(row['unit_cost']) for row in return_movements} == {Decimal(2)}
    assert api('GET', 'production-costs')['orders'][0]['known_material_amount'] == '180.00'


def test_unknown_dispatch_cost_cannot_be_formally_settled(erp):
    _, _, api, *_ = erp
    _, _, order, dispatch = create_order(erp, unit_cost=None)
    execute(api, 'material-dispatches', dispatch, '100')
    execute(api, 'material-receipts', receipts(api, order)[0], '100')
    completion(erp, order, '100')
    report = api('GET', 'production-costs')
    assert report['orders'][0]['total_amount'] is None
    assert report['unpriced_lines'][0]['material_dispatch_id'] == dispatch['id']
    api('POST', 'production-costs/settlements', {'work_order_id': order['id'], 'reference': 'UNKNOWN-FLOW'}, 409)
