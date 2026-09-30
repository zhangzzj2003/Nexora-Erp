"""系统批次、调拨、退回及销售需求分配的数量约束。"""
from test_ledger_foundation import ledger
from app.core.orm import orm_session
from app.core.models import StockMovement, InventoryLot, MovementLot, Material, Warehouse
from app.inventory.lots import balance
from sqlalchemy import select


def test_system_lots_follow_transfer_and_fifo(ledger):
    material=ledger.post('/api/v1/materials',json={'sku':'LOT','name':'批次物料','unit':'件'}).json()['id']
    warehouse=ledger.post('/api/v1/warehouses',json={'name':'二仓'}).json()['id']
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
