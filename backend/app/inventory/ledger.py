"""库存台账：同一筛选范围内按流水顺序计算期初、逐笔余额与期末。"""

from app.core.document_responses import NumberedRoute
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.access.security import require
from app.core.models import Warehouse, Material, StockMovement, User
from app.core.orm import orm_session

router = APIRouter(route_class=NumberedRoute, prefix="/api/v1")


class LedgerQuery(BaseModel):
    # 单次最多读取 100 条明细；不传分页参数的旧客户端也使用默认首页。
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    warehouse_id: int | None = Field(default=None, gt=0)
    material_id: int | None = Field(default=None, gt=0)
    from_date: date | None = None
    to_date: date | None = None
    source_type: str | None = Field(default=None, max_length=60, pattern=r"^[a-z_]+$")


@router.post("/inventory-ledger/query")
def query_ledger(filters: LedgerQuery,
                 _: dict = Depends(require("inventory.view"))) -> dict:
    if filters.from_date and filters.to_date and filters.to_date < filters.from_date:
        raise HTTPException(422, "结束日期不能早于开始日期")
    with orm_session() as db:
        if filters.warehouse_id and db.get(Warehouse, filters.warehouse_id) is None:
            raise HTTPException(422, '仓库不存在')
        if filters.material_id and db.get(Material, filters.material_id) is None:
            raise HTTPException(422, '物料不存在')
        # 筛选条件绑定到模型表达式；来源筛选后的余额仍表示该来源的累计变动。
        stmt = select(StockMovement.id, StockMovement.warehouse_id, Warehouse.name.label('warehouse_name'),
            StockMovement.material_id, Material.sku, Material.name.label('material_name'), Material.unit,
            StockMovement.quantity, StockMovement.source_type, StockMovement.source_id, StockMovement.source_line_id,
            StockMovement.created_at, User.username.label('created_by_name')).select_from(StockMovement)
        stmt = stmt.join(Warehouse, Warehouse.id == StockMovement.warehouse_id)
        stmt = stmt.join(Material, Material.id == StockMovement.material_id)
        stmt = stmt.outerjoin(User, User.id == StockMovement.created_by)
        if filters.warehouse_id is not None:
            stmt = stmt.where(StockMovement.warehouse_id == filters.warehouse_id)
        if filters.material_id is not None:
            stmt = stmt.where(StockMovement.material_id == filters.material_id)
        if filters.source_type is not None:
            stmt = stmt.where(StockMovement.source_type == filters.source_type)
        if filters.to_date is not None:
            stmt = stmt.where(func.date(StockMovement.created_at) <= str(filters.to_date))
        # 先在数据库限定当前页，避免把全部流水明细装入内存或传回客户端。
        page_stmt = stmt
        if filters.from_date is not None:
            page_stmt = page_stmt.where(func.date(StockMovement.created_at) >= str(filters.from_date))
        total = db.scalar(select(func.count()).select_from(page_stmt.subquery())) or 0
        page = min(filters.page, max(1, (total + filters.page_size - 1) // filters.page_size))
        rows = [dict(item) for item in db.execute(page_stmt.order_by(
            StockMovement.created_at.desc(), StockMovement.id.desc()
        ).offset((page - 1) * filters.page_size).limit(filters.page_size)).mappings()]
        page_rows = {row['id']: row for row in rows}
        # 数量以字符串保存，不能用 SQLite 浮点 SUM 损失精度；流式读取汇总所需字段，
        # 按时间正序累加 Decimal，仅给当前页保存逐笔结余。期初期末始终覆盖完整筛选范围。
        summary_stmt = stmt.with_only_columns(
            StockMovement.id, StockMovement.warehouse_id, Warehouse.name.label('warehouse_name'),
            StockMovement.material_id, Material.sku, Material.name.label('material_name'), Material.unit,
            StockMovement.quantity, StockMovement.created_at
        ).order_by(StockMovement.created_at, StockMovement.id)
        movement_rows = db.execute(summary_stmt.execution_options(yield_per=1000)).mappings()
        groups: dict[tuple[int, int], dict] = {}
        for item in movement_rows:
            key = (item["warehouse_id"], item["material_id"])
            group = groups.setdefault(key, {
                "warehouse_id": item["warehouse_id"], "warehouse_name": item["warehouse_name"],
                "material_id": item["material_id"], "sku": item["sku"],
                "material_name": item["material_name"], "unit": item["unit"],
                "opening_quantity": Decimal(0), "closing_quantity": Decimal(0),
                "inbound_quantity": Decimal(0), "outbound_quantity": Decimal(0)})
            quantity = Decimal(item["quantity"])
            if filters.from_date and item["created_at"][:10] < str(filters.from_date):
                group["opening_quantity"] += quantity
            else:
                # 收发存复用完整期间汇总，不能从当前页明细反算收入和发出。
                group['inbound_quantity'] += max(quantity, Decimal(0))
                group['outbound_quantity'] += max(-quantity, Decimal(0))
            group["closing_quantity"] += quantity
            if item['id'] in page_rows:
                page_rows[item['id']]['balance_quantity'] = str(group['closing_quantity'])
        for group in groups.values():
            group["closing_quantity"] = str(group["closing_quantity"])
            group["opening_quantity"] = str(group["opening_quantity"])
            group['inbound_quantity'] = str(group['inbound_quantity'])
            group['outbound_quantity'] = str(group['outbound_quantity'])
        return {"groups": list(groups.values()), "rows": rows,
                "total": total, "page": page, "page_size": filters.page_size}
