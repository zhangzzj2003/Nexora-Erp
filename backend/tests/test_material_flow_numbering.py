"""生产物料同名集合与库存来源必须保留各自主单编号。"""
from uuid import uuid4

from approval_test_helpers import approve_document
from test_production_settlements import erp
from test_production_material_accounting import create_order, execute, receipts


def test_work_order_flow_collections_and_generated_dispatch_keep_own_numbers(erp):
    client, headers, api, *_ = erp
    _, _, order, dispatch = create_order(erp)
    execute(api, 'material-dispatches', dispatch, '10')
    receipt = execute(api, 'material-receipts', receipts(api, order)[0], '10')
    source = {'work_order_line_id': order['lines'][0]['id'],
              'source_receipt_line_id': receipt['lines'][0]['id'], 'quantity': '2'}
    exchange = api('POST', 'material-exchanges', {'work_order_id': order['id'], 'warehouse_id': 1,
        'request_id': str(uuid4()), 'reason': '损坏等量换新', 'lines': [source]}, 201)
    approve_document(client, headers, 'MaterialExchange', exchange['id'])
    exchange = execute(api, 'material-exchanges', exchange, '2')
    replacement = api('POST', f'material-exchanges/{exchange["id"]}/create-dispatch',
        {'version': exchange['version'], 'request_id': str(uuid4())}, 201)
    # 生成补发的路径属于换料接口，返回的仍须为独立发料单号。
    direct = api('GET', f'material-dispatches/{replacement["id"]}')
    assert replacement['document_no'] == direct['document_no']
    assert replacement['document_no'] != exchange['document_no']
    returned = api('POST', 'material-returns/flow', {'work_order_id': order['id'], 'warehouse_id': 1,
        'request_id': str(uuid4()), 'reason': '未耗用余料', 'lines': [{**source, 'quantity': '3'}]}, 201)
    summary = api('GET', f'work-orders/{order["id"]}/material-flow')
    for key, base, expected in (
        ('dispatches', 'material-dispatches', dispatch),
        ('dispatches', 'material-dispatches', replacement),
        ('receipts', 'material-receipts', receipt),
        ('exchanges', 'material-exchanges', exchange),
        ('returns', 'material-returns/flow', returned),
    ):
        nested = next(row for row in summary[key] if row['id'] == expected['id'])
        direct = api('GET', f'{base}/{expected["id"]}')
        assert nested['document_no'] == direct['document_no'] == expected['document_no']
    # 夹具同时存在同 ID 采购入库，生产领料绝不能被补成采购入库号。
    assert summary['receipts'][0]['document_no'] != api('GET', 'receipts')[0]['document_no']


def test_material_flow_movements_and_reversals_point_to_original_header_numbers(erp):
    client, headers, api, *_ = erp
    _, _, order, dispatch = create_order(erp)
    execute(api, 'material-dispatches', dispatch, '100')
    receipt = execute(api, 'material-receipts', receipts(api, order)[0], '98')
    receipt = api('POST', f'material-receipts/{receipt["id"]}/handover-return', {
        'version': receipt['version'], 'request_id': str(uuid4()), 'reason': '两件未交接实物退仓',
        'lines': [{'line_id': receipt['lines'][0]['id'], 'quantity': '2'}]})
    returned = api('POST', 'material-returns/flow', {'work_order_id': order['id'], 'warehouse_id': 1,
        'request_id': str(uuid4()), 'reason': '四件可用余料退回', 'lines': [{
            'work_order_line_id': order['lines'][0]['id'],
            'source_receipt_line_id': receipt['lines'][0]['id'], 'quantity': '4'}]}, 201)
    approve_document(client, headers, 'ProductionMaterialReturn', returned['id'])
    returned = execute(api, 'material-returns/flow', returned, '4')
    expected = {'material_dispatch': dispatch['document_no'],
                'material_handover_return': receipt['document_no'],
                'production_material_return': returned['document_no']}
    # 先退料、再签收交接、最后发料，依赖顺序更正后每种反向流水仍引用原主单。
    for base, model, document in (
        ('material-returns/flow', 'ProductionMaterialReturn', returned),
        ('material-receipts', 'MaterialReceipt', receipt),
        ('material-dispatches', 'MaterialDispatch', dispatch),
    ):
        current = api('GET', f'{base}/{document["id"]}')
        reason = '核对后更正登记'
        approve_document(client, headers, model, current['id'], intent='reverse', reason=reason)
        api('POST', f'{base}/{current["id"]}/reverse', {'version': current['version'],
            'request_id': str(uuid4()), 'reason': reason})
    rows = api('POST', 'inventory-ledger/query', {})['rows']
    for source, number in expected.items():
        for suffix in ('', '_reversal'):
            facts = [row for row in rows if row['source_type'] == source + suffix]
            assert facts
            assert all(row['source_document_no'] == number for row in facts)
