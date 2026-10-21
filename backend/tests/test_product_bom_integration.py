"""产品用途、多层配方约束以及半成品入库、总装和独立销售的接口闭环。"""

from approval_test_helpers import planned_order

from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from app.core.database import connection, migrate
from app.core.orm import orm_session
from app.production.mrp_sources import collect, fingerprint
from app.production.mrp_engine import calculate
from test_mrp import engine_source, START

from approval_test_helpers import approve_document, execute_production_settlement
from test_production_settlements import erp


def test_product_uses_are_independent_strict_audited_and_preserved_for_legacy_clients(erp):
    _, _, api, material, *_ = erp
    assert api('GET', 'product-bom-features') == {'independent_uses': True, 'component_bom_versions': True}
    board, raw = material('USE-BOARD'), material('USE-RAW')
    product = api('POST', 'products', {'material_id': board, 'kind': 'semi_finished',
        'can_sell': False, 'can_purchase': False, 'can_produce': True}, 201)
    customer = api('POST', 'customers', {'name': '板卡客户'}, 201)['id']
    sale = {'customer_id': customer, 'lines': [{'material_id': board, 'quantity': '1', 'unit_price': '10'}]}
    assert '未允许销售' in api('POST', 'sales-orders', sale, 409)['detail']
    assert '未允许采购' in api('POST', 'purchase-requests', {'lines': [{'material_id': board,
        'quantity': '1', 'unit_price': '1'}]}, 409)['detail']
    api('POST', 'purchase-orders', {'supplier_id': 1, 'lines': [{'material_id': board,
        'quantity': '1', 'unit_price': '1'}]}, 409)
    # 老客户端编辑省略用途，不得意外恢复停售或禁止采购的开关。
    changed = api('PUT', f"products/{product['id']}", {'kind': 'semi_finished',
        'configuration_name': '标准板', 'version': 1, 'reason': '补充配置'})
    assert not changed['can_sell'] and not changed['can_purchase'] and changed['can_produce']
    api('PUT', f"products/{product['id']}", {'kind': 'semi_finished', 'version': 2,
        'reason': '错误开关', 'can_sell': 'false'}, 422)
    api('PUT', f"products/{product['id']}", {'kind': 'semi_finished', 'version': 2,
        'reason': '未知用途不能当作保留', 'can_sell': None}, 422)
    enabled = api('PUT', f"products/{product['id']}", {'kind': 'semi_finished', 'version': 2,
        'reason': '允许板卡独立销售', 'can_sell': True, 'can_produce': False})
    assert enabled['kind'] == 'semi_finished' and enabled['can_sell']
    api('POST', 'sales-orders', sale, 201)
    changes = api('GET', f"products/{product['id']}/changes")
    assert changes[0]['before']['can_sell'] is False and changes[0]['after']['can_sell'] is True
    bom = api('POST', 'boms', {'product_material_id': board,
        'lines': [{'component_material_id': raw, 'quantity': '1'}]}, 201)
    assert '未允许生产' in api('POST', f"boms/{bom['id']}/activate", status=409)['detail']
    api('PUT', f"products/{product['id']}", {'kind': 'semi_finished', 'version': 2,
        'reason': '旧页面误操作', 'can_sell': False}, 409)
    assert api('GET', f"products/{product['id']}")['can_sell'] is True


def test_fixed_child_recipe_does_not_follow_new_default_or_rewrite_historical_orders(erp):
    _, _, api, material, *_ = erp
    raw, board, final, other = [material(code) for code in ('PIN-RAW', 'PIN-BOARD', 'PIN-FINAL', 'PIN-OTHER')]
    child = api('POST', 'boms', {'product_material_id': board,
        'lines': [{'component_material_id': raw, 'quantity': '2'}]}, 201)
    # 草稿和其他产出物料的版本都不能充当此组件的已发布配方。
    payload = {'product_material_id': final, 'lines': [{'component_material_id': board,
        'quantity': '1', 'component_bom_id': child['id']}]}
    api('POST', 'boms', payload, 422)
    api('POST', f"boms/{child['id']}/activate")
    api('POST', 'boms', {**payload, 'lines': [{**payload['lines'][0], 'component_material_id': other}]}, 422)
    parent = api('POST', 'boms', payload, 201)
    api('POST', f"boms/{parent['id']}/activate")
    order_payload = {'bom_id': parent['id'], 'warehouse_id': 1, 'target_quantity': '3'}
    order = planned_order(api, order_payload, 201)
    assert len(order['lines']) == 1 and order['lines'][0]['component_material_id'] == board
    assert Decimal(order['lines'][0]['required_quantity']) == 3
    before = api('GET', f"boms/{parent['id']}")
    assert before['lines'][0]['component_bom_version'] == 1
    api('POST', f"boms/{child['id']}/retire")
    newer = api('POST', 'boms', {'product_material_id': board, 'source_bom_id': child['id'],
        'lines': [{'component_material_id': raw, 'quantity': '3'}]}, 201)
    api('POST', f"boms/{newer['id']}/activate")
    assert '修订上层' in planned_order(api, order_payload, 409)['detail']
    assert '修订上层' in api('GET', 'production/mrp/options', status=409)['detail']
    current = api('GET', f"boms/{parent['id']}")
    assert current['lines'][0]['component_bom_id'] == child['id']
    assert current['lines'][0]['component_bom_version'] == 1
    historical = next(row for row in api('GET', 'work-orders') if row['id'] == order['id'])
    assert historical['lines'] == order['lines']
    # 复制派生只建立新草稿，必须显式选择新的下层版本，再停用旧上层。
    revised = api('POST', 'boms', {**payload, 'source_bom_id': parent['id'],
        'lines': [{**payload['lines'][0], 'component_bom_id': newer['id']}]}, 201)
    api('POST', f"boms/{parent['id']}/retire")
    api('POST', f"boms/{revised['id']}/activate")
    planned_order(api, {**order_payload, 'bom_id': revised['id']}, 201)
    api('GET', 'production/mrp/options')


def test_board_stock_then_assembly_does_not_duplicate_material_cost_and_board_can_ship(erp):
    client, headers, api, material, inbound, _, complete = erp
    raw, board, shell, final = [material(code) for code in ('FLOW-RAW', 'FLOW-PCBA', 'FLOW-SHELL', 'FLOW-FINAL')]
    api('POST', 'products', {'material_id': board, 'kind': 'semi_finished', 'can_sell': True}, 201)
    api('POST', 'products', {'material_id': final, 'kind': 'finished'}, 201)
    inbound(raw, '10', '2')
    inbound(shell, '2', '3')

    def stock(identifier):
        return Decimal(next(row['quantity'] for row in api('GET', 'stock') if row['id'] == identifier))

    def produce(bom, quantity, labor):
        api('POST', f"boms/{bom['id']}/activate")
        order = planned_order(api, {'bom_id': bom['id'], 'warehouse_id': 1,
            'target_quantity': quantity}, 201)
        approve_document(client, headers, 'WorkOrder', order['id'])
        api('POST', f"work-orders/{order['id']}/release")
        # 经当前仓库发料及生产签收流程领用，只取工单第一层组件。
        dispatch = api('POST', 'material-dispatches', {'work_order_id': order['id'], 'warehouse_id': 1,
            'request_id': str(uuid4()), 'reason': '多层生产验证', 'lines': [
                {'work_order_line_id': line['id'], 'quantity': line['required_quantity']} for line in order['lines']]}, 201)
        approve_document(client, headers, 'MaterialDispatch', dispatch['id'])
        api('POST', f"material-dispatches/{dispatch['id']}/execute", {'version': dispatch['version'],
            'request_id': str(uuid4()), 'lines': [{'line_id': line['id'], 'quantity': line['quantity']}
                for line in dispatch['lines']]})
        receipt = api('GET', f"material-receipts?work_order_id={order['id']}")['items'][0]
        api('POST', f"material-receipts/{receipt['id']}/execute", {'version': receipt['version'],
            'request_id': str(uuid4()), 'lines': [{'line_id': line['id'], 'quantity': line['quantity']}
                for line in receipt['lines']]})
        complete(order, quantity, quantity)
        api('POST', 'production-costs/charges', {'work_order_id': order['id'], 'kind': 'labor',
            'amount': labor, 'reference': f"LABOR-{order['id']}"}, 201)
        settlement = api('POST', 'production-costs/settlements', {'work_order_id': order['id'], 'reference': f"COST-{order['id']}"}, 201)
        return order, execute_production_settlement(client, headers, settlement)

    board_bom = api('POST', 'boms', {'product_material_id': board,
        'lines': [{'component_material_id': raw, 'quantity': '2'}]}, 201)
    _, first_cost = produce(board_bom, '2', '2')
    assert first_cost['total_amount'] == '10.00'
    assert stock(raw) == 6 and stock(board) == 2
    final_bom = api('POST', 'boms', {'product_material_id': final,
        'lines': [{'component_material_id': board, 'quantity': '1', 'component_bom_id': board_bom['id']},
                  {'component_material_id': shell, 'quantity': '1'}]}, 201)
    final_order, final_cost = produce(final_bom, '1', '1')
    assert {line['component_material_id'] for line in final_order['lines']} == {board, shell}
    assert final_cost['material_amount'] == '8.00' and final_cost['total_amount'] == '9.00'
    assert stock(raw) == 6 and stock(board) == 1 and stock(final) == 1
    customer = api('POST', 'customers', {'name': '独立板卡客户'}, 201)['id']
    sale = api('POST', 'sales-orders', {'customer_id': customer,
        'lines': [{'material_id': board, 'quantity': '1', 'unit_price': '20'}]}, 201)
    approve_document(client, headers, 'SalesOrder', sale['id'])
    api('POST', f"sales-orders/{sale['id']}/confirm")
    shipment = api('POST', 'shipments', {'sales_order_id': sale['id'], 'warehouse_id': 1,
        'lines': [{'material_id': board, 'quantity': '1'}]}, 201)
    approve_document(client, headers, 'Shipment', shipment['id'])
    api('POST', f"shipments/{shipment['id']}/post")
    assert stock(board) == 0 and stock(raw) == 6
    valuation = api('GET', 'inventory/valuation')
    assert next(row for row in valuation['movements'] if row['source_type'] == 'shipment')['amount'] == '-5.00'


def test_104_upgrade_adds_only_defaults_and_preserves_audits_stock_and_mrp_fingerprint(erp):
    _, _, api, material, *_ = erp
    raw, board = material('MIGRATE-RAW'), material('MIGRATE-PCBA')
    bom = api('POST', 'boms', {'product_material_id': board,
        'lines': [{'component_material_id': raw, 'quantity': '2'}]}, 201)
    api('POST', f"boms/{bom['id']}/activate")
    order = planned_order(api, {'bom_id': bom['id'], 'warehouse_id': 1, 'target_quantity': '3'}, 201)
    profile = api('POST', 'products/query', {})['items'][0]
    audits = api('GET', f"products/{profile['id']}/changes")
    stock = api('GET', 'stock')
    with orm_session() as db:
        before = fingerprint(collect(db))
    # 明确模拟真实第 104 版缺列状态，而非只降低版本号后重复执行空迁移。
    with connection() as db:
        for name in ('can_sell', 'can_purchase', 'can_produce'):
            db.execute(f'ALTER TABLE product_profiles DROP COLUMN {name}')
        db.execute('ALTER TABLE bom_lines DROP COLUMN component_bom_id')
        db.execute('PRAGMA user_version = 104')
    migrate(); migrate()
    current = api('GET', f"products/{profile['id']}")
    assert all(current[field] is True for field in ('can_sell', 'can_purchase', 'can_produce'))
    assert api('GET', f"boms/{bom['id']}")['lines'][0]['component_bom_id'] is None
    assert api('GET', f"products/{profile['id']}/changes") == audits
    assert api('GET', 'stock') == stock
    assert next(row for row in api('GET', 'work-orders') if row['id'] == order['id']) == order
    with orm_session() as db:
        assert fingerprint(collect(db)) == before
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 109
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_mrp_restrictions_apply_to_shortages_without_discarding_interchangeable_stock():
    source = engine_source()
    source['product_restrictions'] = [{'material_id': 1, 'can_purchase': True, 'can_produce': False},
                                      {'material_id': 3, 'can_purchase': False, 'can_produce': True}]
    demand = [{'material_id': 1, 'quantity': '1', 'due_date': START, 'reference': '库存够用'}]
    with pytest.raises(HTTPException, match='未允许生产'):
        calculate(source, START, {}, {}, demand)
    # 库存够用时不凭空要求生产，销售现存的半成品仍可正常安排。
    source['movements'].append({'material_id': 1, 'quantity': '1'})
    assert calculate(source, START, {}, {}, demand)['suggestions'] == []
    with pytest.raises(HTTPException, match='未允许采购'):
        calculate(source, START, {}, {}, [{'material_id': 3, 'quantity': '8', 'due_date': START, 'reference': '采购受限'}])
