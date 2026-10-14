"""库存余额与流水 ORM 查询，数量始终使用 Decimal 汇总。"""

from app.core.document_responses import NumberedRoute
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, or_
from pydantic import BaseModel, Field

from app.access.security import require
from app.core.models import Material, Warehouse, StockMovement, Receipt
from app.catalog.categories import category_directory
from app.core.orm import orm_session, model_data

router = APIRouter(route_class=NumberedRoute, prefix="/api/v1")

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
    'material_return_reversal_id': ('material_return_reversal',),
    # 新流程的出库、正常退料与未签交接退回分别指向真实来源单，避免误跳旧领料记录。
    'material_dispatch_id': ('material_dispatch',),
    'material_dispatch_reversal_id': ('material_dispatch_reversal',),
    'production_material_return_id': ('production_material_return',),
    'production_material_return_reversal_id': ('production_material_return_reversal',),
    'material_receipt_id': ('material_handover_return',),
    'material_receipt_reversal_id': ('material_handover_return_reversal',),
    'production_completion_id': ('production_completion',),
    'production_completion_reversal_id': ('production_completion_reversal',),
}


class StockQuery(BaseModel):
    warehouse_id: int | None = Field(default=None, gt=0)
    material_id: int | None = Field(default=None, gt=0)
    keyword: str = Field(default='', max_length=120)
    category_group: str | None = Field(default=None, max_length=30)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


@router.post('/stock/query')
def query_stock(filters: StockQuery, _: dict = Depends(require('inventory.view'))) -> dict:
    with orm_session() as db:
        if filters.warehouse_id is not None and db.get(Warehouse, filters.warehouse_id) is None:
            raise HTTPException(422, '仓库不存在')
        if filters.material_id is not None and db.get(Material, filters.material_id) is None:
            raise HTTPException(404, '物料不存在')
        directory = category_directory(db)
        conditions = []
        if filters.material_id is not None:
            conditions.append(Material.id == filters.material_id)
        # 分类按档案的父子关系查询；不从物料编号前缀猜测，停用分类仍可核对历史库存。
        if filters.category_group is not None:
            if filters.category_group == '':
                conditions.append(Material.category_code == '')
            else:
                group = directory.get(filters.category_group)
                if not group or group['parent_code'] is not None or group['deleted']:
                    raise HTTPException(422, '物料大类不存在')
                children = [code for code, child in directory.items() if child['parent_code'] == group['code']]
                conditions.append(Material.category_code.in_(children))
        for word in filters.keyword.strip().split():
            conditions.append(or_(Material.sku.icontains(word, autoescape=True),
                                  Material.name.icontains(word, autoescape=True)))
        filtered = select(Material).where(*conditions)
        total = db.scalar(select(func.count()).select_from(filtered.subquery())) or 0
        page = min(filters.page, max(1, (total + filters.page_size - 1) // filters.page_size))
        materials = db.scalars(filtered.order_by(Material.sku, Material.id)
            .offset((page - 1) * filters.page_size).limit(filters.page_size)).all()
        # 完整筛选范围的库存统计采用 Decimal；不从当前页或 SQLite 浮点 SUM 推算。
        quantities: dict[int, Decimal] = {}
        movements = select(StockMovement.material_id, StockMovement.quantity).join(
            Material, Material.id == StockMovement.material_id).where(*conditions)
        if filters.warehouse_id is not None:
            movements = movements.where(StockMovement.warehouse_id == filters.warehouse_id)
        for material_id, quantity in db.execute(movements.execution_options(yield_per=1000)):
            quantities[material_id] = quantities.get(material_id, Decimal(0)) + Decimal(quantity)
        # 只为当前页附带全仓分布；历史有流水但已清零的仓库保留，便于继续追溯。
        balances: dict[int, dict[int, dict]] = {}
        if materials:
            distribution = select(StockMovement.material_id, Warehouse.id, Warehouse.code,
                Warehouse.name, StockMovement.quantity).join(Warehouse, Warehouse.id == StockMovement.warehouse_id).where(
                StockMovement.material_id.in_([material.id for material in materials])).order_by(Warehouse.code, Warehouse.id)
            for material_id, warehouse_id, code, name, quantity in db.execute(distribution.execution_options(yield_per=1000)):
                entry = balances.setdefault(material_id, {}).setdefault(warehouse_id,
                    {'warehouse_id': warehouse_id, 'warehouse_code': code, 'warehouse_name': name, 'quantity': Decimal(0)})
                entry['quantity'] += Decimal(quantity)
        items = []
        for material in materials:
            category = directory.get(material.category_code)
            parent = directory.get(category['parent_code']) if category else None
            warehouses = list(balances.get(material.id, {}).values())
            total_quantity = sum((item['quantity'] for item in warehouses), Decimal(0))
            items.append({**{key: getattr(material, key) for key in ('id', 'sku', 'name', 'unit', 'category_code')},
                'category_group_name': parent['name'] if parent else '未分类',
                'category_name': f"{parent['name']} / {category['name']}" if parent else '未分类',
                'quantity': str(quantities.get(material.id, Decimal(0))), 'total_quantity': str(total_quantity),
                'warehouses': [{**item, 'quantity': str(item['quantity'])} for item in warehouses]})
        positive = sum(quantity > 0 for quantity in quantities.values())
        negative = sum(quantity < 0 for quantity in quantities.values())
        return {'items': items, 'total': total, 'page': page, 'page_size': filters.page_size,
                'summary': {'material_count': total, 'positive_material_count': positive,
                    'zero_material_count': total - positive - negative, 'negative_material_count': negative,
                    # 旧客户端的全局统计字段继续保留，新总览不把采购入库单数当成所有入库。
                    'posted_receipt_count': db.scalar(select(func.count()).select_from(Receipt)
                        .where(Receipt.status == 'posted')) or 0,
                    'movement_count': db.scalar(select(func.count()).select_from(StockMovement)) or 0}}


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
