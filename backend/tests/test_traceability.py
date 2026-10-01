"""系统批次、调拨、退回及销售需求分配的数量约束。"""
from test_ledger_foundation import ledger
from test_production_settlements import erp
from app.core.orm import orm_session
from app.core.models import StockMovement, InventoryLot, MovementLot, Material, Warehouse
from app.inventory.lots import balance
from sqlalchemy import select


def test_system_lots_follow_transfer_and_fifo(ledger):
    material=ledger.post('/api/v1/materials',json={'sku':'LOT','name':'批次物料','unit':'件'}).json()['id']
    warehouse=ledger.post('/api/v1/warehouses',json={'code':'LOT2','name':'二仓'}).json()['id']
    with orm_session(write=True) as db:
        db.add(StockMovement(warehouse_id=1,material_id=material,quantity='10',source_type='test_inbound',source_id=1,source_line_id=1,created_by=1))
    with orm_session() as db:
        lot=db.scalar(select(InventoryLot).where(InventoryLot.material_id==material));lot_id=lot.id
        assert balance(db,lot,1)==10
    with orm_session(write=True) as db:
        db.add_all([StockMovement(warehouse_id=1,material_id=material,quantity='-3',source_type='transfer_out',source_id=99,source_line_id=99,created_by=1),StockMovement(warehouse_id=warehouse,material_id=material,quantity='3',source_type='transfer_in',source_id=99,source_line_id=99,created_by=1)])
    with orm_session() as db:
        lot=db.get(InventoryLot,lot_id)
        assert balance(db,lot,1)==7 and balance(db,lot,warehouse)==3
        moves=list(db.scalars(select(MovementLot).where(MovementLot.lot_id==lot_id)))
        assert sorted(row.quantity for row in moves)==['-3','10','3']
    report=ledger.post('/api/v1/trace/query',json={'kind':'lot','id':lot_id});assert report.status_code==200,report.text
    page=ledger.post('/api/v1/tables/query',json={'dataset':'snapshot','snapshot_id':report.json()['snapshot_id'],'snapshot_path':'nodes','page':1,'page_size':100}).json()
    assert any(row['kind']=='movement' for row in page['items'])
    assert all('unit_price' not in row and 'total_amount' not in row for row in page['items'])


def test_reversal_uses_original_document_not_same_numbered_other_document(ledger):
    from app.core import models as m
    from app.core.orm import add_model
    from app.inventory.trace import movement_document
    # 原单与冲销单的编号特意不相等，避免偶然相等掩盖错误关联。
    supplier=ledger.post('/api/v1/suppliers',json={'name':'溯源供应商'}).json()['id']
    with orm_session(write=True) as db:
        original=add_model(db,m.Receipt(id=91,supplier_id=supplier,created_by=1))
        reversal=add_model(db,m.ReceiptReversal(receipt_id=original.id,reason='核对',created_by=1))
        movement=m.StockMovement(warehouse_id=1,material_id=1,quantity='-1',source_type='receipt_reversal',source_id=reversal.id,source_line_id=1,created_by=1)
        assert movement_document(db,movement)==('receipt',91)


# 用真实接口贯通销售、生产、完工、出库与退货，避免孤立节点查询代替整条业务链验收。


def test_sales_production_shipment_trace_is_bidirectional_and_quantity_bounded(erp):
    _, _, api, material, receipt, _, complete = erp
    raw, product = material('TRACE-RAW'), material('TRACE-PRODUCT')
    receipt(raw, '5', '3.00')
    customer = api('POST', 'customers', {'name': '溯源客户', 'contact_name': '私有联系人'}, 201)['id']
    sale = api('POST', 'sales-orders', {'customer_id': customer,
        'lines': [{'material_id': product, 'quantity': '2', 'unit_price': '18'}]}, 201)
    api('POST', f'sales-orders/{sale["id"]}/confirm')
    # 分配发生在领料前，工单开始生产后冻结已有销售分配。
    bom = api('POST', 'boms', {'product_material_id': product, 'base_quantity': '1',
        'lines': [{'component_material_id': raw, 'quantity': '1'}]}, 201)
    api('POST', f'boms/{bom["id"]}/activate')
    order = api('POST', 'work-orders', {'bom_id': bom['id'], 'warehouse_id': 1,
        'target_quantity': '2'}, 201)
    allocation = {'work_order_id': order['id'], 'reason': '按销售安排生产',
        'lines': [{'sales_order_line_id': sale['lines'][0]['id'], 'quantity': '2'}]}
    api('PUT', 'trace/allocations', {**allocation,
        'lines': [{**allocation['lines'][0], 'quantity': '3'}]}, 409)
    assert api('PUT', 'trace/allocations', allocation)['allocated_quantity'] == '2'
    another = api('POST', 'work-orders', {'bom_id': bom['id'], 'warehouse_id': 1,
        'target_quantity': '1'}, 201)
    api('PUT', 'trace/allocations', {**allocation, 'work_order_id': another['id'],
        'lines': [{**allocation['lines'][0], 'quantity': '1'}]}, 409)
    api('POST', f'work-orders/{order["id"]}/release')
    issue = api('POST', 'material-issues', {'work_order_id': order['id'], 'warehouse_id': 1,
        'lines': [{'work_order_line_id': order['lines'][0]['id'], 'quantity': '2'}]}, 201)
    api('POST', f'material-issues/{issue["id"]}/post')
    api('PUT', 'trace/allocations', allocation, 409)
    completion = complete(order, reported='2', accepted='2')
    api('PUT', 'trace/allocations', allocation, 409)
    shipment = api('POST', 'shipments', {'sales_order_id': sale['id'], 'warehouse_id': 1,
        'lines': [{'material_id': product, 'quantity': '2'}]}, 201)
    api('POST', f'shipments/{shipment["id"]}/post')
    returned = api('POST', 'sales-returns', {'shipment_id': shipment['id'], 'warehouse_id': 1,
        'reason': '部分退回', 'lines': [{'shipment_line_id': shipment['lines'][0]['id'], 'quantity': '1'}]}, 201)
    api('POST', f'sales-returns/{returned["id"]}/post')

    required = {f'sales_order:{sale["id"]}', f'work_order:{order["id"]}',
        f'material_issue:{issue["id"]}', f'production_completion:{completion}',
        f'shipment:{shipment["id"]}', f'sales_return:{returned["id"]}'}
    # 正向和反向都必须达到同一组单据，并且不能泄露客户私有联系人或销售金额。
    for kind, identifier in [('sales_order', sale['id']), ('shipment', shipment['id'])]:
        result = api('POST', 'trace/query', {'kind': kind, 'id': identifier})
        nodes = api('POST', 'tables/query', {'dataset': 'snapshot', 'snapshot_id': result['snapshot_id'],
            'snapshot_path': 'nodes', 'page': 1, 'page_size': 100})['items']
        edges = api('POST', 'tables/query', {'dataset': 'snapshot', 'snapshot_id': result['snapshot_id'],
            'snapshot_path': 'edges', 'page': 1, 'page_size': 100})['items']
        assert required <= {node['key'] for node in nodes}
        assert any(node['kind'] == 'lot' for node in nodes)
        assert any(edge['relation'] == '销售需求分配' and edge['quantity'] == '2' for edge in edges)
        assert all('total_amount' not in node and 'unit_price' not in node and 'contact_name' not in node for node in nodes)
        assert '私有联系人' not in str(nodes)
