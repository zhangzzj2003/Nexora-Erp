"""库存台账：同一筛选范围内按流水顺序计算期初、逐笔余额与期末。"""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.access.security import require
from app.core.models import Warehouse, Material, StockMovement, User
from app.core.orm import orm_session

router = APIRouter(prefix="/api/v1")


class LedgerQuery(BaseModel):
    paged: bool = False
    warehouse_id: int | None = Field(default=None, gt=0)
    material_id: int | None = Field(default=None, gt=0)
    from_date: date | None = None
    to_date: date | None = None
    source_type: str | None = Field(default=None, max_length=60, pattern=r"^[a-z_]+$")


@router.post("/inventory-ledger/query")
def query_ledger(filters: LedgerQuery,
                 user: dict = Depends(require("inventory.view"))) -> dict:
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
        movement_rows = db.execute(stmt.order_by(StockMovement.id)).mappings().all()
        groups: dict[tuple[int, int], dict] = {}
        rows: list[dict] = []
        for item in movement_rows:
            key = (item["warehouse_id"], item["material_id"])
            group = groups.setdefault(key, {
                "warehouse_id": item["warehouse_id"], "warehouse_name": item["warehouse_name"],
                "material_id": item["material_id"], "sku": item["sku"],
                "material_name": item["material_name"], "unit": item["unit"],
                "opening_quantity": Decimal(0), "closing_quantity": Decimal(0)})
            quantity = Decimal(item["quantity"])
            if filters.from_date and item["created_at"][:10] < str(filters.from_date):
                group["opening_quantity"] += quantity
            else:
                group["closing_quantity"] += quantity
                rows.append({**dict(item), "balance_quantity": ""})
        balances = {key: value["opening_quantity"] for key, value in groups.items()}
        for row in rows:
            key = (row["warehouse_id"], row["material_id"])
            balances[key] += Decimal(row["quantity"])
            row["balance_quantity"] = str(balances[key])
        for group in groups.values():
            group["closing_quantity"] = str(group["opening_quantity"] + group["closing_quantity"])
            group["opening_quantity"] = str(group["opening_quantity"])
        result = {"groups": list(groups.values()), "rows": rows}
        if filters.paged:
            from app.query.snapshots import snapshot_metadata
            return snapshot_metadata(result,user,('groups','rows'))
        return result
