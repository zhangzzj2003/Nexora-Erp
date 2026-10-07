"""多仓库库存与调拨；已确认流水只追加，不直接修改余额。"""

from app.core.document_responses import NumberedRoute
import json

from sqlalchemy import select, update, delete, func, literal
from sqlalchemy.orm import Session, aliased
from sqlalchemy.exc import IntegrityError
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from app.core.orm import orm_session, add_model
from app.core.models import Material, PhysicalLot, PhysicalLotAllocation, StockMovement, Transfer, TransferLine, TransferReversal, User, Warehouse, WarehouseChange
from app.access.security import require
from app.inventory.physical_lots import LotPart, lot_balance, post_lot_movement

UserRu = aliased(User)
UserU = aliased(User)
WarehouseDst = aliased(Warehouse)
WarehouseSrc = aliased(Warehouse)

router = APIRouter(route_class=NumberedRoute, prefix="/api/v1")


class WarehouseInput(BaseModel):
    code: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=80)
    version: int | None = Field(default=None, ge=1, strict=True)
    reason: str = Field(default="", max_length=500)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.upper()

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("仓库名称不能为空")
        return value.strip()

    @field_validator("reason")
    @classmethod
    def trim_reason(cls, value: str) -> str:
        return value.strip()


def warehouse_data(row: Warehouse) -> dict:
    return {'id': row.id, 'code': row.code, 'name': row.name, 'version': row.version}


def record_warehouse_change(db: Session, row: Warehouse, action: str,
                            before: dict | None, actor: dict, reason: str) -> None:
    # 仓库可在未被引用时删除；审计不能依赖仍存在的仓库行。
    db.add(WarehouseChange(warehouse_id=row.id, action=action,
        before_json=json.dumps(before, ensure_ascii=False) if before is not None else None,
        after_json=json.dumps(warehouse_data(row), ensure_ascii=False) if action != 'delete' else None,
        reason=reason, changed_by=actor['id']))


def warehouse_change_data(change: WarehouseChange, username: str) -> dict:
    return {'id': change.id, 'warehouse_id': change.warehouse_id, 'action': change.action,
            'before': json.loads(change.before_json) if change.before_json else None,
            'after': json.loads(change.after_json) if change.after_json else None,
            'reason': change.reason, 'changed_by': change.changed_by,
            'changed_by_name': username, 'created_at': change.created_at}


class TransferLineInput(BaseModel):
    material_id: int = Field(gt=0)
    quantity: Decimal

    @field_validator("quantity")
    @classmethod
    def valid_quantity(cls, value: Decimal) -> Decimal:
        # 与入库单使用同一精度约束，防止调拨时凭空产生小数尾差。
        if not value.is_finite() or value <= 0 or value > 1_000_000 or value.as_tuple().exponent < -3:
            raise ValueError("数量须大于零、最多三位小数且不超过一百万")
        return value


class TransferInput(BaseModel):
    from_warehouse_id: int = Field(gt=0)
    to_warehouse_id: int = Field(gt=0)
    reference: str = Field(default="", max_length=100)
    lines: list[TransferLineInput] = Field(min_length=1, max_length=100)


class TransferReverseInput(BaseModel):
    reason: str = Field(min_length=1, max_length=200)

    @field_validator("reason")
    @classmethod
    def valid_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("冲销原因不能为空")
        return value.strip()


class TransferLotPartInput(BaseModel):
    lot_id: int = Field(gt=0)
    quantity: Decimal

    @field_validator('quantity')
    @classmethod
    def valid_quantity(cls, value: Decimal) -> Decimal:
        return TransferLineInput.valid_quantity(value)


class TransferLotLineInput(BaseModel):
    transfer_line_id: int = Field(gt=0)
    lots: list[TransferLotPartInput] = Field(min_length=1, max_length=20)


class TransferPostInput(BaseModel):
    lines: list[TransferLotLineInput] = Field(min_length=1, max_length=100)


def require_warehouse(db: Session, warehouse_id: int) -> None:
    if (
        not db.execute(select(literal(1)).select_from(Warehouse).where((Warehouse.id == warehouse_id)))
        .mappings()
        .first()
    ):
        raise HTTPException(422, "仓库不存在")


def balance(db: Session, warehouse_id: int, material_id: int) -> Decimal:
    # SQLite SUM 会把十进制文本转成浮点数；逐笔使用 Decimal 才能保持库存精度。
    return sum(
        (
            Decimal(row)
            for row in db.scalars(
                select(StockMovement.quantity)
                .select_from(StockMovement)
                .where(StockMovement.warehouse_id == warehouse_id, StockMovement.material_id == material_id)
            )
        ),
        Decimal(0),
    )


def transfer_data(db: Session, transfer_id: int) -> dict:
    row = (
        db.execute(
            select(
                Transfer.id,
                Transfer.from_warehouse_id,
                Transfer.to_warehouse_id,
                Transfer.reference,
                Transfer.status,
                Transfer.created_by,
                Transfer.posted_by,
                Transfer.created_at,
                Transfer.posted_at,
                WarehouseSrc.name.label("from_warehouse_name"),
                WarehouseDst.name.label("to_warehouse_name"),
                UserU.username.label("created_by_name"),
                TransferReversal.id.label("reversal_id"),
                TransferReversal.reason.label("reversal_reason"),
                TransferReversal.created_by.label("reversed_by"),
                UserRu.username.label("reversed_by_name"),
                TransferReversal.created_at.label("reversed_at"),
            )
            .select_from(Transfer)
            .join(WarehouseSrc, (WarehouseSrc.id == Transfer.from_warehouse_id))
            .join(WarehouseDst, (WarehouseDst.id == Transfer.to_warehouse_id))
            .join(UserU, (UserU.id == Transfer.created_by))
            .outerjoin(TransferReversal, (TransferReversal.transfer_id == Transfer.id))
            .outerjoin(UserRu, (UserRu.id == TransferReversal.created_by))
            .where((Transfer.id == transfer_id))
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(404, "调拨单不存在")
    lines = (
        db.execute(
            select(
                TransferLine.id,
                TransferLine.material_id,
                Material.sku,
                Material.name.label("material_name"),
                Material.unit,
                TransferLine.quantity,
            )
            .select_from(TransferLine)
            .join(Material, (Material.id == TransferLine.material_id))
            .where((TransferLine.transfer_id == transfer_id))
            .order_by(TransferLine.id)
        )
        .mappings()
        .all()
    )
    lots_by_line: dict[int, list[dict]] = {}
    for line_id, lot, allocation in db.execute(
        select(StockMovement.source_line_id, PhysicalLot, PhysicalLotAllocation)
        .join(PhysicalLotAllocation, PhysicalLotAllocation.movement_id == StockMovement.id)
        .join(PhysicalLot, PhysicalLot.id == PhysicalLotAllocation.lot_id)
        .where(StockMovement.source_type == 'transfer_out', StockMovement.source_id == transfer_id)
        .order_by(StockMovement.source_line_id, PhysicalLotAllocation.id)
    ):
        lots_by_line.setdefault(line_id, []).append({
            'id': lot.id, 'code': lot.code, 'quantity': format(-Decimal(allocation.quantity), 'f'),
            'source_kind': lot.source_kind, 'supplier_lot': lot.supplier_lot,
            'manufactured_on': lot.manufactured_on, 'expires_on': lot.expires_on,
        })
    return {**dict(row), 'lines': [
        {**dict(line), 'physical_lots': lots_by_line.get(line['id'], [])} for line in lines]}


@router.get("/warehouses")
def list_warehouses(_: dict = Depends(require("inventory.view"))) -> list[dict]:
    with orm_session() as db:
        return [warehouse_data(row) for row in db.scalars(select(Warehouse).order_by(Warehouse.id))]


@router.get("/warehouses/{warehouse_id}")
def warehouse_detail(warehouse_id: int, _: dict = Depends(require("inventory.view"))) -> dict:
    with orm_session() as db:
        row = db.get(Warehouse, warehouse_id)
        if row is None:
            raise HTTPException(404, '仓库不存在')
        return warehouse_data(row)


@router.get("/warehouse-changes")
def recent_warehouse_changes(before_id: int | None = Query(default=None, gt=0),
                             limit: int = Query(default=100, ge=1, le=500),
                             _: dict = Depends(require("inventory.view"))) -> list[dict]:
    with orm_session() as db:
        statement = select(WarehouseChange, User.username).join(User, User.id == WarehouseChange.changed_by)
        if before_id is not None:
            statement = statement.where(WarehouseChange.id < before_id)
        return [warehouse_change_data(change, username) for change, username in
                db.execute(statement.order_by(WarehouseChange.id.desc()).limit(limit))]


@router.get("/warehouses/{warehouse_id}/changes")
def warehouse_changes(warehouse_id: int, _: dict = Depends(require("inventory.view"))) -> list[dict]:
    with orm_session() as db:
        rows = db.execute(select(WarehouseChange, User.username).join(User, User.id == WarehouseChange.changed_by)
            .where(WarehouseChange.warehouse_id == warehouse_id).order_by(WarehouseChange.id.desc())).all()
        if not rows and db.get(Warehouse, warehouse_id) is None:
            raise HTTPException(404, '仓库不存在')
        return [warehouse_change_data(change, username) for change, username in rows]


@router.post("/warehouses", status_code=201)
def create_warehouse(payload: WarehouseInput, actor: dict = Depends(require("warehouse.manage"))) -> dict:
    with orm_session(write=True) as db:
        try:
            row = add_model(db, Warehouse(code=payload.code, name=payload.name, version=1))
        except IntegrityError:
            raise HTTPException(409, "仓库编码或名称已存在") from None
        record_warehouse_change(db, row, 'create', None, actor, payload.reason or '新增仓库')
        return warehouse_data(row)


@router.get("/transfers")
def list_transfers(_: dict = Depends(require("inventory.view"))) -> list[dict]:
    with orm_session() as db:
        ids = [
            row for row in db.scalars(select(Transfer.id).select_from(Transfer).order_by(Transfer.id.desc()))
        ]
        return [transfer_data(db, transfer_id) for transfer_id in ids]


@router.post("/transfers", status_code=201)
def create_transfer(payload: TransferInput, user: dict = Depends(require("transfer.create"))) -> dict:
    if payload.from_warehouse_id == payload.to_warehouse_id:
        raise HTTPException(422, "来源仓库与目标仓库不能相同")
    if len({line.material_id for line in payload.lines}) != len(payload.lines):
        raise HTTPException(422, "一张调拨单不能重复选择同一物料")
    with orm_session(write=True) as db:
        require_warehouse(db, payload.from_warehouse_id)
        require_warehouse(db, payload.to_warehouse_id)
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
            Transfer(
                from_warehouse_id=payload.from_warehouse_id,
                to_warehouse_id=payload.to_warehouse_id,
                reference=payload.reference.strip(),
                created_by=user["id"],
            ),
        )
        db.add_all(
            [
                TransferLine(transfer_id=cursor.id, material_id=line.material_id, quantity=str(line.quantity))
                for line in payload.lines
            ]
        )
        return transfer_data(db, cursor.id)


@router.get('/transfers/{transfer_id}/available-lots')
def available_transfer_lots(transfer_id: int, _: dict = Depends(require('transfer.post'))) -> dict:
    with orm_session() as db:
        transfer = db.get(Transfer, transfer_id)
        if transfer is None:
            raise HTTPException(404, '调拨单不存在')
        if transfer.status != 'draft':
            raise HTTPException(409, '只能查询调拨草稿的可用批次')
        lines = list(db.execute(select(TransferLine.id, TransferLine.material_id, TransferLine.quantity)
                                .where(TransferLine.transfer_id == transfer_id)
                                .order_by(TransferLine.id)).mappings())
        materials = {line['material_id'] for line in lines}
        lots = list(db.scalars(select(PhysicalLot).where(
            PhysicalLot.material_id.in_(materials)).order_by(PhysicalLot.id)))
        available = {material_id: [] for material_id in materials}
        for lot in lots:
            quantity = lot_balance(db, transfer.from_warehouse_id, lot.id)
            if quantity > 0:
                available[lot.material_id].append({
                    'lot_id': lot.id, 'code': lot.code, 'source_kind': lot.source_kind,
                    'quantity': format(quantity, 'f'), 'supplier_lot': lot.supplier_lot,
                    'manufactured_on': lot.manufactured_on, 'expires_on': lot.expires_on,
                })
        return {'transfer_id': transfer_id, 'from_warehouse_id': transfer.from_warehouse_id,
                'to_warehouse_id': transfer.to_warehouse_id,
                'lines': [{'transfer_line_id': line['id'], 'material_id': line['material_id'],
                           'quantity': line['quantity'], 'lots': available[line['material_id']]}
                          for line in lines]}


@router.post("/transfers/{transfer_id}/post")
def post_transfer(transfer_id: int, payload: TransferPostInput | None = None,
                  user: dict = Depends(require("transfer.post"))) -> dict:
    with orm_session(write=True) as db:
        # 写锁覆盖库存检查、双向流水和状态变更，阻止并发调拨超出可用量。
        transfer = (
            db.execute(
                select(
                    Transfer.id,
                    Transfer.from_warehouse_id,
                    Transfer.to_warehouse_id,
                    Transfer.reference,
                    Transfer.status,
                    Transfer.created_by,
                    Transfer.posted_by,
                    Transfer.created_at,
                    Transfer.posted_at,
                )
                .select_from(Transfer)
                .where((Transfer.id == transfer_id))
            )
            .mappings()
            .first()
        )
        if not transfer:
            raise HTTPException(404, "调拨单不存在")
        if transfer["status"] != "draft":
            raise HTTPException(409, "此调拨单已经确认")
        lines = (
            db.execute(
                select(TransferLine.id, TransferLine.material_id, TransferLine.quantity)
                .select_from(TransferLine)
                .where((TransferLine.transfer_id == transfer_id))
            )
            .mappings()
            .all()
        )
        lot_lines = {line.transfer_line_id: line for line in payload.lines} if payload else None
        if lot_lines is not None and (len(lot_lines) != len(payload.lines)
                                      or set(lot_lines) != {line['id'] for line in lines}):
            raise HTTPException(422, '批次明细必须与调拨明细逐行对应')
        for line in lines:
            quantity = Decimal(line["quantity"])
            if balance(db, transfer["from_warehouse_id"], line["material_id"]) < quantity:
                raise HTTPException(409, f"物料 #{line['material_id']} 在来源仓库的库存不足")
        for line in lines:
            quantity = Decimal(line["quantity"])
            # 一张单据生成等额出入两笔流水，并记录操作者与单据明细来源。
            outgoing = StockMovement(
                warehouse_id=transfer["from_warehouse_id"],
                material_id=line["material_id"],
                quantity=str(-quantity),
                source_type="transfer_out",
                source_id=transfer_id,
                source_line_id=line["id"],
                created_by=user["id"],
            )
            incoming = StockMovement(
                warehouse_id=transfer["to_warehouse_id"],
                material_id=line["material_id"],
                quantity=str(quantity),
                source_type="transfer_in",
                source_id=transfer_id,
                source_line_id=line["id"],
                created_by=user["id"],
            )
            if lot_lines is None:
                db.add_all([outgoing, incoming])
                continue
            parts = lot_lines[line['id']].lots
            if len({part.lot_id for part in parts}) != len(parts):
                raise HTTPException(422, '一行调拨不能重复选择同一实物批次')
            if sum((part.quantity for part in parts), Decimal(0)) != quantity:
                raise HTTPException(422, f'调拨明细 #{line["id"]} 的批次数量之和不匹配')
            post_lot_movement(db, outgoing, [LotPart(part.lot_id, -part.quantity) for part in parts])
            post_lot_movement(db, incoming, [LotPart(part.lot_id, part.quantity) for part in parts])
        db.execute(
            update(Transfer)
            .where((Transfer.id == transfer_id))
            .values(status="posted", posted_by=user["id"], posted_at=func.current_timestamp())
        )
        return transfer_data(db, transfer_id)


@router.post("/transfers/{transfer_id}/reverse")
def reverse_transfer(
    transfer_id: int, payload: TransferReverseInput, user: dict = Depends(require("transfer.reverse"))
) -> dict:
    with orm_session(write=True) as db:
        # 写锁内一次核对目标仓剩余库存并写入双向反向流水，避免只退回部分明细。
        transfer = (
            db.execute(
                select(
                    Transfer.id,
                    Transfer.from_warehouse_id,
                    Transfer.to_warehouse_id,
                    Transfer.reference,
                    Transfer.status,
                    Transfer.created_by,
                    Transfer.posted_by,
                    Transfer.created_at,
                    Transfer.posted_at,
                )
                .select_from(Transfer)
                .where((Transfer.id == transfer_id))
            )
            .mappings()
            .first()
        )
        if not transfer:
            raise HTTPException(404, "调拨单不存在")
        if transfer["status"] != "posted":
            raise HTTPException(409, "只有已确认调拨单可冲销")
        if (
            db.execute(
                select(literal(1))
                .select_from(TransferReversal)
                .where((TransferReversal.transfer_id == transfer_id))
            )
            .mappings()
            .first()
        ):
            raise HTTPException(409, "此调拨单已冲销")
        lines = (
            db.execute(
                select(TransferLine.id, TransferLine.material_id, TransferLine.quantity)
                .select_from(TransferLine)
                .where((TransferLine.transfer_id == transfer_id))
            )
            .mappings()
            .all()
        )
        for line in lines:
            if balance(db, transfer["to_warehouse_id"], line["material_id"]) < Decimal(line["quantity"]):
                raise HTTPException(
                    409, f"物料 #{line['material_id']} 在原目标仓库的库存不足，请先调回后再冲销"
                )
        reversal_id = add_model(
            db, TransferReversal(transfer_id=transfer_id, reason=payload.reason, created_by=user["id"])
        ).id
        for line in lines:
            quantity = Decimal(line["quantity"])
            # 来源类型区分退回的出入两侧，并用原调拨明细编号串起四笔流水。
            outgoing = StockMovement(
                warehouse_id=transfer["to_warehouse_id"],
                material_id=line["material_id"],
                quantity=str(-quantity),
                source_type="transfer_reversal_out",
                source_id=reversal_id,
                source_line_id=line["id"],
                created_by=user["id"],
            )
            incoming = StockMovement(
                warehouse_id=transfer["from_warehouse_id"],
                material_id=line["material_id"],
                quantity=str(quantity),
                source_type="transfer_reversal_in",
                source_id=reversal_id,
                source_line_id=line["id"],
                created_by=user["id"],
            )
            source_parts = list(db.scalars(select(PhysicalLotAllocation)
                .join(StockMovement, StockMovement.id == PhysicalLotAllocation.movement_id)
                .where(StockMovement.source_type == 'transfer_out',
                       StockMovement.source_id == transfer_id,
                       StockMovement.source_line_id == line['id'])
                .order_by(PhysicalLotAllocation.id)))
            target_parts = list(db.scalars(select(PhysicalLotAllocation)
                .join(StockMovement, StockMovement.id == PhysicalLotAllocation.movement_id)
                .where(StockMovement.source_type == 'transfer_in',
                       StockMovement.source_id == transfer_id,
                       StockMovement.source_line_id == line['id'])
                .order_by(PhysicalLotAllocation.id)))
            if not source_parts and not target_parts:
                db.add_all([outgoing, incoming])
                continue
            source_quantities = {part.lot_id: -Decimal(part.quantity) for part in source_parts}
            target_quantities = {part.lot_id: Decimal(part.quantity) for part in target_parts}
            if (len(source_quantities) != len(source_parts)
                    or len(target_quantities) != len(target_parts)
                    or source_quantities != target_quantities
                    or sum(source_quantities.values(), Decimal(0)) != quantity):
                raise HTTPException(409, '原调拨两侧批次分配不完整，无法冲销')
            post_lot_movement(db, outgoing, [LotPart(
                part.lot_id, -Decimal(part.quantity), part.id) for part in target_parts])
            post_lot_movement(db, incoming, [LotPart(
                part.lot_id, -Decimal(part.quantity), part.id) for part in source_parts])
        return transfer_data(db, transfer_id)


@router.put("/warehouses/{warehouse_id}")
def update_warehouse(
    warehouse_id: int, payload: WarehouseInput, actor: dict = Depends(require("warehouse.manage"))
) -> dict:
    with orm_session(write=True) as db:
        row = db.get(Warehouse, warehouse_id)
        if row is None:
            raise HTTPException(404, "仓库不存在")
        if payload.version != row.version:
            raise HTTPException(409, '仓库资料已更新或未提供版本，请重新加载后编辑')
        if not payload.reason:
            raise HTTPException(422, '请填写仓库资料修改原因')
        if payload.code == row.code and payload.name == row.name:
            raise HTTPException(409, '仓库资料没有变化')
        before = warehouse_data(row)
        row.code, row.name, row.version = payload.code, payload.name, row.version + 1
        try:
            db.flush()
        except IntegrityError:
            raise HTTPException(409, "仓库编码或名称已存在") from None
        record_warehouse_change(db, row, 'update', before, actor, payload.reason)
        return warehouse_data(row)


@router.delete("/warehouses/{warehouse_id}", status_code=204)
def delete_warehouse(warehouse_id: int, version: int = Query(ge=1),
                     actor: dict = Depends(require("warehouse.manage"))) -> None:
    # 旧客户端建单默认引用 1 号主仓库，不能删除该兼容入口。
    if warehouse_id == 1:
        raise HTTPException(409, "默认主仓库不能删除")
    with orm_session(write=True) as db:
        row = db.get(Warehouse, warehouse_id)
        if row is None:
            raise HTTPException(404, "仓库不存在")
        if version != row.version:
            raise HTTPException(409, '仓库资料已更新，请重新加载后删除')
        before = warehouse_data(row)
        try:
            db.delete(row)
            db.flush()
        except IntegrityError:
            raise HTTPException(409, "仓库已被业务单据或库存记录引用，不能删除") from None
        record_warehouse_change(db, row, 'delete', before, actor, '删除未被引用的仓库')
