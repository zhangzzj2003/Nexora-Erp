"""库存余额与流水 ORM 查询，数量始终使用 Decimal 汇总。"""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.access.security import require
from app.core.models import Material, Warehouse, StockMovement
from app.core.orm import orm_session, model_data

router = APIRouter(prefix="/api/v1")

# 保留旧桌面接口的单据链接字段，调拨的一出一入指向同一张来源单据。
MOVEMENT_LINKS = {
    'receipt_id': ('receipt',), 'receipt_reversal_id': ('receipt_reversal',),
    'other_inbound_id': ('other_inbound',), 'other_inbound_reversal_id': ('other_inbound_reversal',),
    'other_outbound_id': ('other_outbound',), 'other_outbound_reversal_id': ('other_outbound_reversal',),
    'transfer_id': ('transfer_out', 'transfer_in'),
    'transfer_reversal_id': ('transfer_reversal_out', 'transfer_reversal_in'),
    'adjustment_id': ('adjustment',), 'adjustment_reversal_id': ('adjustment_reversal',),
    'stocktake_id': ('stocktake',), 'stocktake_reversal_id': ('stocktake_reversal',),
    'shipment_id': ('shipment',), 'shipment_reversal_id': ('shipment_reversal',),
    'sales_return_id': ('sales_return',), 'sales_return_reversal_id': ('sales_return_reversal',),
    'purchase_return_id': ('purchase_return',), 'purchase_return_reversal_id': ('purchase_return_reversal',),
    'material_issue_id': ('material_issue',),
    'material_issue_reversal_id': ('material_issue_reversal',),
    'material_return_id': ('material_return',),
    'production_completion_id': ('production_completion',),
    'production_completion_reversal_id': ('production_completion_reversal',),
}


@router.get("/stock")
def list_stock(warehouse_id: int | None = None, _: dict = Depends(require("inventory.view"))) -> list[dict]:
    with orm_session() as db:
        if warehouse_id is not None and db.get(Warehouse, warehouse_id) is None:
            raise HTTPException(422, '仓库不存在')
        movements = select(StockMovement.material_id, StockMovement.quantity)
        if warehouse_id is not None:
            movements = movements.where(StockMovement.warehouse_id == warehouse_id)
        # 不在 SQLite 内求和，避免十进制文本被转换为浮点数。
        quantities: dict[int, Decimal] = {}
        for material_id, quantity in db.execute(movements):
            quantities[material_id] = quantities.get(material_id, Decimal(0)) + Decimal(quantity)
        return [{key: getattr(material, key) for key in ('id', 'sku', 'name', 'unit')} |
                {'quantity': str(quantities.get(material.id, Decimal(0)))}
                for material in db.scalars(select(Material).order_by(Material.sku))]


@router.get("/movements")
def list_movements(_: dict = Depends(require("inventory.view"))) -> list[dict]:
    with orm_session() as db:
        rows = db.execute(select(StockMovement, Warehouse.name, Material)
            .join(Material, Material.id == StockMovement.material_id)
            .join(Warehouse, Warehouse.id == StockMovement.warehouse_id)
            .order_by(StockMovement.id.desc()))
        return [{**model_data(movement), 'warehouse_name': warehouse_name, 'sku': material.sku,
                 'material_name': material.name, 'unit': material.unit,
                 **{key: movement.source_id if movement.source_type in sources else None
                    for key, sources in MOVEMENT_LINKS.items()}}
                for movement, warehouse_name, material in rows]
