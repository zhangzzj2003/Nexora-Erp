"""仓库盘点单：保留账面快照，只通过确认差异流水调整库存。"""

from app.core.document_responses import NumberedRoute
from sqlalchemy import select, update, func, literal
from sqlalchemy.orm import Session, aliased
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.orm import orm_session, add_model
from app.core.models import (
    Material,
    PhysicalLot,
    PhysicalLotAllocation,
    StockMovement,
    Stocktake,
    StocktakeLine,
    StocktakeReversal,
    User,
    Warehouse,
)
from app.inventory.warehouse import balance, require_warehouse
from app.inventory.physical_lots import LotPart, lot_balance, post_lot_movement
from app.inventory.lot_inputs import PhysicalLotPartInput
from app.access.security import require

UserRu = aliased(User)
UserU = aliased(User)

router = APIRouter(route_class=NumberedRoute, prefix="/api/v1")


class StocktakeLineInput(BaseModel):
    material_id: int = Field(gt=0)
    counted_quantity: Decimal

    @field_validator("counted_quantity")
    @classmethod
    def valid_count(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value < 0 or value > 1_000_000 or value.as_tuple().exponent < -3:
            raise ValueError("实盘数量须为零至一百万，最多三位小数")
        return value


class StocktakeInput(BaseModel):
    warehouse_id: int = Field(gt=0)
    reference: str = Field(default="", max_length=100)
    lines: list[StocktakeLineInput] = Field(min_length=1, max_length=100)


class StocktakeReverseInput(BaseModel):
    reason: str = Field(min_length=1, max_length=200)

    @field_validator("reason")
    @classmethod
    def valid_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("冲销原因不能为空")
        return value.strip()


class StocktakeLotPartInput(PhysicalLotPartInput):
    lot_id: int | None = Field(default=None, gt=0)

    @model_validator(mode='after')
    def existing_lot_has_no_new_origin(self):
        if self.lot_id is not None and any((
            self.supplier_lot, self.manufactured_on, self.expires_on)):
            raise ValueError('已有批次不能同时登记新批次来源字段')
        return self


class StocktakeLotLineInput(BaseModel):
    stocktake_line_id: int = Field(gt=0)
    lots: list[StocktakeLotPartInput] = Field(min_length=1, max_length=20)


class StocktakePostInput(BaseModel):
    lines: list[StocktakeLotLineInput] = Field(min_length=1, max_length=100)


def movement_checkpoint(db: Session, warehouse_id: int, material_id: int) -> int:
    # 即使期间出入库相抵后余额未变，流水编号仍能识别已经过时的实盘结果。
    return db.scalar(
        select(func.coalesce(func.max(StockMovement.id), 0))
        .select_from(StockMovement)
        .where(StockMovement.warehouse_id == warehouse_id, StockMovement.material_id == material_id)
    )


def stocktake_data(db: Session, stocktake_id: int) -> dict:
    row = (
        db.execute(
            select(
                Stocktake.id,
                Stocktake.warehouse_id,
                Stocktake.reference,
                Stocktake.status,
                Stocktake.created_by,
                Stocktake.posted_by,
                Stocktake.cancelled_by,
                Stocktake.created_at,
                Stocktake.posted_at,
                Stocktake.cancelled_at,
                Warehouse.name.label("warehouse_name"),
                UserU.username.label("created_by_name"),
                StocktakeReversal.id.label("reversal_id"),
                StocktakeReversal.reason.label("reversal_reason"),
                StocktakeReversal.created_by.label("reversed_by"),
                UserRu.username.label("reversed_by_name"),
                StocktakeReversal.created_at.label("reversed_at"),
            )
            .select_from(Stocktake)
            .join(Warehouse, (Warehouse.id == Stocktake.warehouse_id))
            .join(UserU, (UserU.id == Stocktake.created_by))
            .outerjoin(StocktakeReversal, (StocktakeReversal.stocktake_id == Stocktake.id))
            .outerjoin(UserRu, (UserRu.id == StocktakeReversal.created_by))
            .where((Stocktake.id == stocktake_id))
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(404, "盘点单不存在")
    lines = (
        db.execute(
            select(
                StocktakeLine.id,
                StocktakeLine.material_id,
                Material.sku,
                Material.name.label("material_name"),
                Material.unit,
                StocktakeLine.book_quantity,
                StocktakeLine.counted_quantity,
            )
            .select_from(StocktakeLine)
            .join(Material, (Material.id == StocktakeLine.material_id))
            .where((StocktakeLine.stocktake_id == stocktake_id))
            .order_by(StocktakeLine.id)
        )
        .mappings()
        .all()
    )
    lots_by_line: dict[int, list[dict]] = {}
    for line_id, lot, allocation in db.execute(
        select(StockMovement.source_line_id, PhysicalLot, PhysicalLotAllocation)
        .join(PhysicalLotAllocation, PhysicalLotAllocation.movement_id == StockMovement.id)
        .join(PhysicalLot, PhysicalLot.id == PhysicalLotAllocation.lot_id)
        .where(StockMovement.source_type == 'stocktake', StockMovement.source_id == stocktake_id)
        .order_by(StockMovement.source_line_id, PhysicalLotAllocation.id)
    ):
        lots_by_line.setdefault(line_id, []).append({
            'id': lot.id, 'code': lot.code, 'quantity': format(abs(Decimal(allocation.quantity)), 'f'),
            'source_kind': lot.source_kind, 'supplier_lot': lot.supplier_lot,
            'manufactured_on': lot.manufactured_on, 'expires_on': lot.expires_on,
        })
    return {
        **dict(row),
        "lines": [
            {
                **dict(line),
                "difference": str(Decimal(line["counted_quantity"]) - Decimal(line["book_quantity"])),
                'physical_lots': lots_by_line.get(line['id'], []),
            }
            for line in lines
        ],
    }


@router.get("/stocktakes")
def list_stocktakes(_: dict = Depends(require("inventory.view"))) -> list[dict]:
    with orm_session() as db:
        ids = [
            row
            for row in db.scalars(select(Stocktake.id).select_from(Stocktake).order_by(Stocktake.id.desc()))
        ]
        return [stocktake_data(db, stocktake_id) for stocktake_id in ids]


@router.post("/stocktakes", status_code=201)
def create_stocktake(payload: StocktakeInput, user: dict = Depends(require("stocktake.create"))) -> dict:
    if len({line.material_id for line in payload.lines}) != len(payload.lines):
        raise HTTPException(422, "一张盘点单不能重复选择同一物料")
    with orm_session(write=True) as db:
        # 建单与读取账面库存共用写事务，形成可审计的一致快照。
        require_warehouse(db, payload.warehouse_id)
        for line in payload.lines:
            if (
                not db.execute(
                    select(literal(1)).select_from(Material).where((Material.id == line.material_id))
                )
                .mappings()
                .first()
            ):
                raise HTTPException(422, "物料不存在")
        cursor = add_model(
            db,
            Stocktake(
                warehouse_id=payload.warehouse_id, reference=payload.reference.strip(), created_by=user["id"]
            ),
        )
        db.add_all(
            [
                StocktakeLine(
                    stocktake_id=cursor.id,
                    material_id=line.material_id,
                    book_quantity=str(balance(db, payload.warehouse_id, line.material_id)),
                    counted_quantity=str(line.counted_quantity),
                    movement_id=movement_checkpoint(db, payload.warehouse_id, line.material_id),
                )
                for line in payload.lines
            ]
        )
        return stocktake_data(db, cursor.id)


@router.get('/stocktakes/{stocktake_id}/available-lots')
def available_stocktake_lots(stocktake_id: int, _: dict = Depends(require('stocktake.post'))) -> dict:
    with orm_session() as db:
        stocktake = db.get(Stocktake, stocktake_id)
        if stocktake is None:
            raise HTTPException(404, '盘点单不存在')
        if stocktake.status != 'draft':
            raise HTTPException(409, '只能查询盘点草稿的可用批次')
        lines = list(db.execute(select(StocktakeLine.id, StocktakeLine.material_id,
                                       StocktakeLine.book_quantity, StocktakeLine.counted_quantity)
                                .where(StocktakeLine.stocktake_id == stocktake_id)
                                .order_by(StocktakeLine.id)).mappings())
        lots = list(db.scalars(select(PhysicalLot).where(
            PhysicalLot.material_id.in_({line['material_id'] for line in lines}))
            .order_by(PhysicalLot.id)))
        by_material = {line['material_id']: [] for line in lines}
        for lot in lots:
            quantity = lot_balance(db, stocktake.warehouse_id, lot.id)
            if quantity < 0:
                continue
            by_material[lot.material_id].append({
                'lot_id': lot.id, 'code': lot.code, 'source_kind': lot.source_kind,
                'quantity': format(quantity, 'f'), 'supplier_lot': lot.supplier_lot,
                'manufactured_on': lot.manufactured_on, 'expires_on': lot.expires_on,
            })
        return {'stocktake_id': stocktake_id, 'warehouse_id': stocktake.warehouse_id,
                'lines': [{'stocktake_line_id': line['id'], 'material_id': line['material_id'],
                           'book_quantity': line['book_quantity'],
                           'counted_quantity': line['counted_quantity'],
                           'difference': format(Decimal(line['counted_quantity'])
                                                - Decimal(line['book_quantity']), 'f'),
                           'lots': by_material[line['material_id']]}
                          for line in lines]}


@router.post("/stocktakes/{stocktake_id}/post")
def post_stocktake(stocktake_id: int, payload: StocktakePostInput | None = None,
                   user: dict = Depends(require("stocktake.post"))) -> dict:
    with orm_session(write=True) as db:
        # 写锁覆盖快照核对、差异流水与状态，期间入库或调拨不会被盘点吞掉。
        stocktake = (
            db.execute(
                select(
                    Stocktake.id,
                    Stocktake.warehouse_id,
                    Stocktake.reference,
                    Stocktake.status,
                    Stocktake.created_by,
                    Stocktake.posted_by,
                    Stocktake.cancelled_by,
                    Stocktake.created_at,
                    Stocktake.posted_at,
                    Stocktake.cancelled_at,
                )
                .select_from(Stocktake)
                .where((Stocktake.id == stocktake_id))
            )
            .mappings()
            .first()
        )
        if not stocktake:
            raise HTTPException(404, "盘点单不存在")
        if stocktake["status"] != "draft":
            raise HTTPException(409, "此盘点单已处理")
        lines = (
            db.execute(
                select(
                    StocktakeLine.id,
                    StocktakeLine.stocktake_id,
                    StocktakeLine.material_id,
                    StocktakeLine.book_quantity,
                    StocktakeLine.counted_quantity,
                    StocktakeLine.movement_id,
                )
                .select_from(StocktakeLine)
                .where((StocktakeLine.stocktake_id == stocktake_id))
            )
            .mappings()
            .all()
        )
        for line in lines:
            if (
                balance(db, stocktake["warehouse_id"], line["material_id"]) != Decimal(line["book_quantity"])
                or movement_checkpoint(db, stocktake["warehouse_id"], line["material_id"])
                != line["movement_id"]
            ):
                raise HTTPException(409, f"物料 #{line['material_id']} 的账面库存已变化，请重新盘点")
        difference_lines = {line['id'] for line in lines if
                            Decimal(line['counted_quantity']) != Decimal(line['book_quantity'])}
        lot_lines = {line.stocktake_line_id: line for line in payload.lines} if payload else None
        if lot_lines is not None and (len(lot_lines) != len(payload.lines)
                                      or set(lot_lines) != difference_lines):
            raise HTTPException(422, '批次明细必须与非零盘点差异逐行对应')
        for line in lines:
            difference = Decimal(line["counted_quantity"]) - Decimal(line["book_quantity"])
            if difference:
                # 零差异不生成虚假的库存变动；非零差异记录原单据、明细和操作者。
                movement = StockMovement(
                    warehouse_id=stocktake["warehouse_id"],
                    material_id=line["material_id"],
                    quantity=str(difference),
                    source_type="stocktake",
                    source_id=stocktake_id,
                    source_line_id=line["id"],
                    created_by=user["id"],
                )
                if lot_lines is None:
                    db.add(movement)
                    continue
                parts = lot_lines[line['id']].lots
                if sum((part.quantity for part in parts), Decimal(0)) != abs(difference):
                    raise HTTPException(422, f'盘点明细 #{line["id"]} 的批次数量之和不匹配')
                existing_ids = [part.lot_id for part in parts if part.lot_id is not None]
                if len(set(existing_ids)) != len(existing_ids):
                    raise HTTPException(422, '一行盘点不能重复选择同一已有实物批次')
                if difference < 0 and any(part.lot_id is None for part in parts):
                    raise HTTPException(422, '盘亏只能扣减已有实物批次')
                selected = []
                new_lots = []
                for index, part in enumerate(parts, 1):
                    if part.lot_id is not None:
                        selected.append(LotPart(part.lot_id, part.quantity.copy_sign(difference)))
                        continue
                    lot = add_model(db, PhysicalLot(
                        material_id=line['material_id'],
                        code=f'ST{stocktake_id}-L{line["id"]}-P{index}',
                        source_kind='stocktake', supplier_lot=part.supplier_lot,
                        manufactured_on=part.manufactured_on.isoformat()
                        if part.manufactured_on else None,
                        expires_on=part.expires_on.isoformat() if part.expires_on else None,
                        created_by=user['id']))
                    selected.append(LotPart(lot.id, part.quantity))
                    new_lots.append(lot)
                post_lot_movement(db, movement, selected)
                for lot in new_lots:
                    lot.origin_movement_id = movement.id
        db.execute(
            update(Stocktake)
            .where((Stocktake.id == stocktake_id))
            .values(status="posted", posted_by=user["id"], posted_at=func.current_timestamp())
        )
        return stocktake_data(db, stocktake_id)


@router.post("/stocktakes/{stocktake_id}/cancel")
def cancel_stocktake(stocktake_id: int, user: dict = Depends(require("stocktake.cancel"))) -> dict:
    with orm_session(write=True) as db:
        row = (
            db.execute(select(Stocktake.status).select_from(Stocktake).where((Stocktake.id == stocktake_id)))
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "盘点单不存在")
        if row["status"] != "draft":
            raise HTTPException(409, "只有草稿盘点单可取消；已确认差异须另建更正单")
        db.execute(
            update(Stocktake)
            .where((Stocktake.id == stocktake_id))
            .values(status="cancelled", cancelled_by=user["id"], cancelled_at=func.current_timestamp())
        )
        return stocktake_data(db, stocktake_id)


@router.post("/stocktakes/{stocktake_id}/reverse")
def reverse_stocktake(
    stocktake_id: int, payload: StocktakeReverseInput, user: dict = Depends(require("stocktake.reverse"))
) -> dict:
    with orm_session(write=True) as db:
        # 写锁覆盖重复冲销、当前库存核对与补偿流水，避免并发操作生成负库存。
        stocktake = (
            db.execute(
                select(
                    Stocktake.id,
                    Stocktake.warehouse_id,
                    Stocktake.reference,
                    Stocktake.status,
                    Stocktake.created_by,
                    Stocktake.posted_by,
                    Stocktake.cancelled_by,
                    Stocktake.created_at,
                    Stocktake.posted_at,
                    Stocktake.cancelled_at,
                )
                .select_from(Stocktake)
                .where((Stocktake.id == stocktake_id))
            )
            .mappings()
            .first()
        )
        if not stocktake:
            raise HTTPException(404, "盘点单不存在")
        if stocktake["status"] != "posted":
            raise HTTPException(409, "只有已确认盘点单可冲销")
        if (
            db.execute(
                select(literal(1))
                .select_from(StocktakeReversal)
                .where((StocktakeReversal.stocktake_id == stocktake_id))
            )
            .mappings()
            .first()
        ):
            raise HTTPException(409, "此盘点单已冲销")
        lines = (
            db.execute(
                select(
                    StocktakeLine.id,
                    StocktakeLine.stocktake_id,
                    StocktakeLine.material_id,
                    StocktakeLine.book_quantity,
                    StocktakeLine.counted_quantity,
                    StocktakeLine.movement_id,
                )
                .select_from(StocktakeLine)
                .where((StocktakeLine.stocktake_id == stocktake_id))
            )
            .mappings()
            .all()
        )
        for line in lines:
            difference = Decimal(line["counted_quantity"]) - Decimal(line["book_quantity"])
            if difference > 0 and balance(db, stocktake["warehouse_id"], line["material_id"]) < difference:
                raise HTTPException(
                    409, f"物料 #{line['material_id']} 的当前库存不足以冲销盘盈，请先核对实物"
                )
        reversal_id = add_model(
            db, StocktakeReversal(stocktake_id=stocktake_id, reason=payload.reason, created_by=user["id"])
        ).id
        for line in lines:
            difference = Decimal(line["counted_quantity"]) - Decimal(line["book_quantity"])
            if difference:
                # 冲销只追加反向流水；零差异盘点保留冲销记录但不制造零数量流水。
                movement = StockMovement(
                    warehouse_id=stocktake["warehouse_id"],
                    material_id=line["material_id"],
                    quantity=str(-difference),
                    source_type="stocktake_reversal",
                    source_id=reversal_id,
                    source_line_id=line["id"],
                    created_by=user["id"],
                )
                allocations = list(db.scalars(select(PhysicalLotAllocation)
                    .join(StockMovement, StockMovement.id == PhysicalLotAllocation.movement_id)
                    .where(StockMovement.source_type == 'stocktake',
                           StockMovement.source_id == stocktake_id,
                           StockMovement.source_line_id == line['id'])
                    .order_by(PhysicalLotAllocation.id)))
                if allocations:
                    if sum((Decimal(part.quantity) for part in allocations), Decimal(0)) != difference:
                        raise HTTPException(409, '原盘点批次分配不完整，无法冲销')
                    post_lot_movement(db, movement, [LotPart(
                        part.lot_id, -Decimal(part.quantity), part.id) for part in allocations])
                else:
                    db.add(movement)
        return stocktake_data(db, stocktake_id)
