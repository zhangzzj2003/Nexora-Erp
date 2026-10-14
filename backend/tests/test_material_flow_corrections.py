"""更正按整张单据累计额度，并保持正式库存、批次与现场补证一致。"""
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from approval_test_helpers import approve_document
from app.core.models import PhysicalLotAllocation
from app.core.orm import orm_session
from app.inventory.physical_lots import lot_balance
from test_production_settlements import erp
from test_production_material_accounting import create_order, execute, receipts
from test_material_flow_lots import flow_lots


def stock(api, raw):
    return Decimal(next(row for row in api('GET', 'stock?warehouse_id=1') if row['id'] == raw)['quantity'])


def reverse_payload(document):
    return {'version': document['version'], 'request_id': str(uuid4()), 'reason': '重新核对原实物收发记录'}


@pytest.mark.parametrize('actually_dispatched', [False, True])
def test_return_correction_aggregates_multiple_signed_sources(erp, actually_dispatched):
    client, headers, api, *_ = erp
    raw, _, order, dispatch = create_order(erp)
    for _ in range(2):
        dispatch = execute(api, 'material-dispatches', dispatch, '50')
        execute(api, 'material-receipts', receipts(api, order)[0], '50')
    returned = api('POST', 'material-returns/flow', {'work_order_id': order['id'], 'warehouse_id': 1,
        'request_id': str(uuid4()), 'reason': '两个签收来源分别退回十件', 'lines': [{
            'work_order_line_id': order['lines'][0]['id'], 'source_receipt_line_id': row['lines'][0]['id'],
            'quantity': '10'} for row in receipts(api, order)]}, 201)
    approve_document(client, headers, 'ProductionMaterialReturn', returned['id'])
    returned = api('POST', f'material-returns/flow/{returned["id"]}/execute', {
        'version': returned['version'], 'request_id': str(uuid4()),
        'lines': [{'line_id': row['id'], 'quantity': '10'} for row in returned['lines']]})
    later = api('POST', 'material-dispatches', {'work_order_id': order['id'], 'warehouse_id': 1,
        'request_id': str(uuid4()), 'lines': [{'work_order_line_id': order['lines'][0]['id'], 'quantity': '10'}]}, 201)
    if actually_dispatched:
        approve_document(client, headers, 'MaterialDispatch', later['id'])
        later = execute(api, 'material-dispatches', later, '10')
    payload = reverse_payload(returned)
    approve_document(client, headers, 'ProductionMaterialReturn', returned['id'], intent='reverse', reason=payload['reason'])
    before_stock = stock(api, raw)
    endpoint = f'material-returns/flow/{returned["id"]}'
    api('POST', endpoint + '/reverse', payload, 409)
    current = api('GET', endpoint)
    # 90 + 10 的逐行校验会放行，整单恢复 20 必须失败且不能消费批准或追加流水。
    assert stock(api, raw) == before_stock
    assert current['version'] == returned['version']
    assert current['executions'] == returned['executions']
    assert current['reversal_approval']['status'] == 'approved'
    if not actually_dispatched:
        api('POST', f'material-dispatches/{later["id"]}/close', {
            'version': later['version'], 'request_id': str(uuid4()), 'reason': '先释放后续未执行额度'})
        corrected = api('POST', endpoint + '/reverse', payload)
        assert corrected['status'] == 'reversed'
        assert stock(api, raw) == 100


def prepare_correction(erp, kind, seed_batch=False):
    client, headers, api, *_ = erp
    raw, _, order, dispatch = create_order(erp)
    inbound = next(row for row in api('GET', 'movements') if row['source_type'] == 'receipt')
    lot_id = None
    if seed_batch:
        lot_id = api('POST', f'inventory/physical-lots/movements/{inbound["id"]}/evidence', {
            'quantity': '200', 'supplier_lot': 'A', 'evidence': '现场逐件核对原采购入库全部为批次A'}, 201)['lot_id']
    dispatch = execute(api, 'material-dispatches', dispatch, '100')
    if kind == 'dispatch':
        document, base, model, source = dispatch, 'material-dispatches', 'MaterialDispatch', 'material_dispatch'
    else:
        receipt = execute(api, 'material-receipts', receipts(api, order)[0], '98' if kind == 'handover' else '100')
        if kind == 'handover':
            document = api('POST', f'material-receipts/{receipt["id"]}/handover-return', {
                'version': receipt['version'], 'request_id': str(uuid4()), 'reason': '两件未交接实物退仓',
                'lines': [{'line_id': receipt['lines'][0]['id'], 'quantity': '2'}]})
            base, model, source = 'material-receipts', 'MaterialReceipt', 'material_handover_return'
        else:
            document = api('POST', 'material-returns/flow', {'work_order_id': order['id'], 'warehouse_id': 1,
                'request_id': str(uuid4()), 'reason': '可用余料退回', 'lines': [{
                    'work_order_line_id': order['lines'][0]['id'],
                    'source_receipt_line_id': receipt['lines'][0]['id'], 'quantity': '10'}]}, 201)
            approve_document(client, headers, 'ProductionMaterialReturn', document['id'])
            document = execute(api, 'material-returns/flow', document, '10')
            base, model, source = 'material-returns/flow', 'ProductionMaterialReturn', 'production_material_return'
    movement = next(row for row in api('GET', 'movements') if row['source_type'] == source)
    return api, client, headers, raw, document, base, model, movement, lot_id, inbound


@pytest.mark.parametrize('kind', ['dispatch', 'return', 'handover'])
def test_flow_correction_reverses_complete_physical_lot_evidence(erp, kind):
    api, client, headers, raw, document, base, model, movement, lot_id, _ = prepare_correction(erp, kind, kind == 'dispatch')
    quantity = Decimal(movement['quantity'])
    evidence = api('POST', f'inventory/physical-lots/movements/{movement["id"]}/evidence', {
        'quantity': str(abs(quantity)), **({'lot_id': lot_id} if lot_id else {'supplier_lot': 'RETURN-A'}),
        'evidence': '现场完整核对本次收发实物所属批次'}, 201)
    lot_id = evidence['lot_id']
    with orm_session() as db:
        before_lot = lot_balance(db, 1, lot_id)
    before_stock = stock(api, raw)
    payload = reverse_payload(document)
    approve_document(client, headers, model, document['id'], intent='reverse', reason=payload['reason'])
    api('POST', f'{base}/{document["id"]}/reverse', payload)
    reversal = next(row for row in api('GET', 'movements') if row['source_type'] == movement['source_type'] + '_reversal')
    assert stock(api, raw) == before_stock - quantity
    with orm_session() as db:
        assert lot_balance(db, 1, lot_id) == before_lot - quantity
        parts = list(db.scalars(select(PhysicalLotAllocation).where(PhysicalLotAllocation.movement_id == reversal['id'])))
        assert len(parts) == 1 and parts[0].lot_id == lot_id
        assert Decimal(parts[0].quantity) == -quantity
        assert parts[0].original_allocation_id is None


@pytest.mark.parametrize('kind', ['dispatch', 'return', 'handover'])
def test_flow_correction_blocks_incomplete_physical_lot_evidence(erp, kind):
    api, client, headers, raw, document, base, model, movement, lot_id, _ = prepare_correction(erp, kind, kind == 'dispatch')
    api('POST', f'inventory/physical-lots/movements/{movement["id"]}/evidence', {
        'quantity': '1', **({'lot_id': lot_id} if lot_id else {'supplier_lot': 'PARTIAL-A'}),
        'evidence': '现场目前仅核实一件所属批次'}, 201)
    payload = reverse_payload(document)
    approve_document(client, headers, model, document['id'], intent='reverse', reason=payload['reason'])
    before_stock = stock(api, raw)
    api('POST', f'{base}/{document["id"]}/reverse', payload, 409)
    assert stock(api, raw) == before_stock
    assert api('GET', f'{base}/{document["id"]}')['executions'] == document['executions']


@pytest.mark.parametrize('kind', ['return', 'handover'])
def test_flow_correction_does_not_consume_identified_stock_for_unassigned_return(erp, kind):
    api, client, headers, raw, document, base, model, _, _, inbound = prepare_correction(erp, kind)
    # 其他入库的补证耗尽未归批差额；即使正式库存充足，也不能用已识别批次冲销未知来源退入。
    before_stock = stock(api, raw)
    api('POST', f'inventory/physical-lots/movements/{inbound["id"]}/evidence', {
        'quantity': str(before_stock), 'supplier_lot': 'ORIGINAL-A', 'evidence': '现场核对当前库存均属原采购入库批次'}, 201)
    payload = reverse_payload(document)
    approve_document(client, headers, model, document['id'], intent='reverse', reason=payload['reason'])
    api('POST', f'{base}/{document["id"]}/reverse', payload, 409)
    assert stock(api, raw) == before_stock
    assert api('GET', f'{base}/{document["id"]}')['executions'] == document['executions']


def test_flow_correction_preserves_original_explicit_lot_allocations(flow_lots):
    api, client, headers, _, raw, dispatch, _, lot_a, lot_b = flow_lots
    # 原本明确选批的出库更正继续关联原分配，不因支持现场补证丢失原有批次来源。
    payload = reverse_payload(dispatch)
    approve_document(client, headers, 'MaterialDispatch', dispatch['id'], intent='reverse', reason=payload['reason'])
    api('POST', f'material-dispatches/{dispatch["id"]}/reverse', payload)
    assert stock(api, raw) == 200
    reversal = next(row for row in api('GET', 'movements') if row['source_type'] == 'material_dispatch_reversal')
    with orm_session() as db:
        assert lot_balance(db, 1, lot_a) == lot_balance(db, 1, lot_b) == 100
        parts = list(db.scalars(select(PhysicalLotAllocation).where(PhysicalLotAllocation.movement_id == reversal['id'])))
        assert len(parts) == 2
        assert all(part.original_allocation_id is not None and Decimal(part.quantity) == 30 for part in parts)
