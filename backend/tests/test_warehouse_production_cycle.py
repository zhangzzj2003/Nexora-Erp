"""通过新收发接口验证多仓交接、分批退换料、完工和正式结算共用同一事实链。"""

from approval_test_helpers import planned_order

from decimal import Decimal
from uuid import uuid4

from approval_test_helpers import approve_document, execute_production_settlement
from test_production_settlements import erp
from test_production_material_accounting import create_order


def test_new_material_flow_closes_multi_warehouse_production_and_costs(erp):
    client, headers, api, material, inbound, *_ = erp
    raw, product = material('CYCLE-RAW'), material('CYCLE-PRODUCT')
    inbound(raw, '200', '2')
    raw_store = api('POST', 'warehouses', {'code': 'CYCLE-RAW', 'name': '车间原料仓'}, 201)['id']
    finished_store = api('POST', 'warehouses', {'code': 'CYCLE-FIN', 'name': '成品仓'}, 201)['id']

    def approve(kind, record):
        approve_document(client, headers, kind, record['id'])

    def quantity(warehouse, identifier):
        return Decimal(next(row['quantity'] for row in api('GET', f'stock?warehouse_id={warehouse}') if row['id'] == identifier))

    # 调拨只移动原料与成本，工单的目标仓库独立接收合格成品。
    transfer = api('POST', 'transfers', {'from_warehouse_id': 1, 'to_warehouse_id': raw_store,
        'lines': [{'material_id': raw, 'quantity': '120'}]}, 201)
    approve('Transfer', transfer)
    api('POST', f'transfers/{transfer["id"]}/post')
    bom = api('POST', 'boms', {'product_material_id': product, 'base_quantity': '1',
        'lines': [{'component_material_id': raw, 'quantity': '1'}]}, 201)
    api('POST', f'boms/{bom["id"]}/activate')
    order = planned_order(api, {'bom_id': bom['id'], 'warehouse_id': finished_store,
        'target_quantity': '100'}, 201)
    approve('WorkOrder', order)
    api('POST', f'work-orders/{order["id"]}/release')
    line_id = order['lines'][0]['id']

    def create_flow(path, quantity, **source):
        return api('POST', path, {'work_order_id': order['id'], 'warehouse_id': raw_store,
            'request_id': str(uuid4()), 'reason': '闭环验收逐笔核对',
            'lines': [{'work_order_line_id': line_id, 'quantity': quantity, **source}]}, 201)

    def execute(path, record, amount, action='execute'):
        return api('POST', f'{path}/{record["id"]}/{action}', {'version': record['version'],
            'request_id': str(uuid4()), 'reason': '实物清点交接',
            'lines': [{'line_id': record['lines'][0]['id'], 'quantity': amount}]})

    def receipt_for(dispatch):
        return next(row for row in api('GET', f'material-receipts?work_order_id={order["id"]}')['items']
                    if row['source_document_id'] == dispatch['id'])

    def dispatch_and_sign(amount):
        dispatch = create_flow('material-dispatches', amount)
        approve('MaterialDispatch', dispatch)
        execute('material-dispatches', dispatch, amount)
        return execute('material-receipts', receipt_for(dispatch), amount)

    dispatch = create_flow('material-dispatches', '100')
    approve('MaterialDispatch', dispatch)
    payload = {'version': dispatch['version'], 'request_id': str(uuid4()),
        'lines': [{'line_id': dispatch['lines'][0]['id'], 'quantity': '60'}]}
    dispatch = api('POST', f'material-dispatches/{dispatch["id"]}/execute', payload)
    # 网络原样重试不得再次扣库、生成第二张领料或追加重复流水。
    assert api('POST', f'material-dispatches/{dispatch["id"]}/execute', payload) == dispatch
    assert quantity(raw_store, raw) == 60
    first_signed = execute('material-receipts', receipt_for(dispatch), '58')
    summary = api('GET', f'work-orders/{order["id"]}/material-flow')['lines'][0]
    assert Decimal(summary['in_transit_quantity']) == 2
    assert Decimal(summary['available_quantity']) == 58
    # 批准 100、发出 60、签收 58：待发为 40，未安排为 0，不能用同一个剩余字段混淆。
    order_line = next(row for row in api('GET', 'work-orders') if row['id'] == order['id'])['lines'][0]
    assert Decimal(order_line['pending_dispatch_quantity']) == 40
    assert Decimal(order_line['remaining_quantity']) == 0
    assert Decimal(order_line['in_transit_quantity']) == 2
    first_signed = execute('material-receipts', first_signed, '2', 'handover-return')
    assert quantity(raw_store, raw) == 62
    execute('material-dispatches', dispatch, '40')
    second_receipt = next(row for row in api('GET', f'material-receipts?work_order_id={order["id"]}')['items']
                          if row['id'] != first_signed['id'])
    execute('material-receipts', second_receipt, '40')
    dispatch_and_sign('2')

    # 换料必须交回旧料并补签新料；只补发或只签一部分都不能被视为完成。
    source = {'source_receipt_line_id': first_signed['lines'][0]['id']}
    exchange = create_flow('material-exchanges', '2', **source)
    approve('MaterialExchange', exchange)
    exchange = execute('material-exchanges', exchange, '2')
    replacement = api('POST', f'material-exchanges/{exchange["id"]}/create-dispatch',
        {'version': exchange['version'], 'request_id': str(uuid4())}, 201)
    assert Decimal(next(row for row in api('GET', 'work-orders') if row['id'] == order['id'])['lines'][0]['pending_dispatch_quantity']) == 2
    approve('MaterialDispatch', replacement)
    execute('material-dispatches', replacement, '2')
    signed = execute('material-receipts', receipt_for(replacement), '1')
    assert api('GET', f'material-exchanges/{exchange["id"]}')['status'] == 'partial'
    execute('material-receipts', signed, '1')
    assert api('GET', f'material-exchanges/{exchange["id"]}')['status'] == 'completed'
    assert quantity(raw_store, raw) == 18

    returned = create_flow('material-returns/flow', '10', **source)
    approve('ProductionMaterialReturn', returned)
    assert quantity(raw_store, raw) == 18

    def inspect(amount):
        completion = api('POST', 'production-completions', {'work_order_id': order['id'],
            'reported_quantity': amount}, 201)
        api('POST', f'production-completions/{completion["id"]}/inspect',
            {'accepted_quantity': amount, 'qc_note': '分批全数检验合格'})
        approve('ProductionCompletion', completion)
        return completion

    first = inspect('50')
    api('POST', f'production-completions/{first["id"]}/post')
    final = inspect('50')
    movements_before = api('GET', 'movements')
    # 部分报工可执行；最终完工必须等交接与退换料全部办结，失败不增加成品库存。
    api('POST', f'production-completions/{final["id"]}/post', status=409)
    assert api('GET', 'movements') == movements_before
    assert quantity(finished_store, product) == 50
    returned = execute('material-returns/flow', returned, '4')
    assert quantity(raw_store, raw) == 22
    execute('material-returns/flow', returned, '6')
    assert quantity(raw_store, raw) == 28
    dispatch_and_sign('10')
    api('POST', f'production-completions/{final["id"]}/post')
    assert next(row for row in api('GET', 'work-orders') if row['id'] == order['id'])['status'] == 'completed'

    api('POST', 'production-costs/charges', {'work_order_id': order['id'], 'kind': 'labor',
        'amount': '10', 'reference': 'CYCLE-LABOR'}, 201)
    settlement = api('POST', 'production-costs/settlements', {'work_order_id': order['id'],
        'reference': 'CYCLE-SETTLEMENT'}, 201)
    settlement = execute_production_settlement(client, headers, settlement)
    assert settlement['material_amount'] == '204.00'
    assert settlement['total_amount'] == '214.00'
    assert sum(Decimal(row['amount']) for row in settlement['allocations']) == Decimal('214.00')
    assert quantity(1, raw) == 80
    assert quantity(raw_store, raw) == 18
    assert quantity(finished_store, product) == 100
    valuation = api('GET', 'inventory/valuation')
    assert next(row for row in valuation['materials'] if row['id'] == product)['amount'] == '214.00'
    assert next(row for row in valuation['materials'] if row['id'] == raw)['amount'] == '196.00'
    # 正式结算锁定来源后，不能冲销完工来破坏既有成本分摊。
    api('POST', f'production-completions/{final["id"]}/reverse', {'reason': '结算后误操作'}, 409)
    summary = api('GET', f'work-orders/{order["id"]}/material-flow')
    assert all(row['status'] == 'completed' for key in ('dispatches', 'receipts', 'exchanges', 'returns') for row in summary[key])
    assert Decimal(summary['lines'][0]['in_transit_quantity']) == 0
    assert Decimal(summary['lines'][0]['reserved_quantity']) == 0
    assert Decimal(summary['lines'][0]['effective_quantity']) == 100
    assert Decimal(next(row for row in api('GET', 'work-orders') if row['id'] == order['id'])['lines'][0]['pending_dispatch_quantity']) == 0


def test_pending_dispatch_excludes_closed_balance_and_includes_legacy_draft(erp):
    _, _, api, *_ = erp
    _, _, order, dispatch = create_order(erp)

    def pending():
        return Decimal(next(row for row in api('GET', 'work-orders') if row['id'] == order['id'])['lines'][0]['pending_dispatch_quantity'])

    assert pending() == 100
    dispatch = api('POST', f'material-dispatches/{dispatch["id"]}/execute', {'version': dispatch['version'],
        'request_id': str(uuid4()), 'lines': [{'line_id': dispatch['lines'][0]['id'], 'quantity': '60'}]})
    assert pending() == 40
    api('POST', f'material-dispatches/{dispatch["id"]}/close', {'version': dispatch['version'],
        'request_id': str(uuid4()), 'reason': '后续四十件取消备料'})
    # 关闭余额仅取消未发计划，已发六十件仍等待生产签收，不能消失或再次计入待发。
    assert pending() == 0
    line = next(row for row in api('GET', 'work-orders') if row['id'] == order['id'])['lines'][0]
    assert Decimal(line['in_transit_quantity']) == 60
    assert Decimal(line['remaining_quantity']) == 40
    legacy = api('POST', 'material-issues', {'work_order_id': order['id'], 'warehouse_id': 1,
        'lines': [{'work_order_line_id': line['id'], 'quantity': '40'}]}, 201)
    assert pending() == 40
    api('POST', f'material-issues/{legacy["id"]}/cancel')
    assert pending() == 0
