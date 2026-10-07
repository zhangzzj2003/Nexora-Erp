"""独立库存调整单：异人审批与仓库确认后才追加库存流水。"""

from app.core.document_responses import NumberedRoute
from app.core import document_approval as approval
from app.core.approval_documents import adjustment_snapshot, document_snapshot
from sqlalchemy import select, update, func, literal
from sqlalchemy.orm import Session, aliased

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from app.access.security import require
from app.core.orm import orm_session, add_model
from app.core.models import (
    Material,
    PhysicalLot,
    PhysicalLotAllocation,
    StockAdjustment,
    StockAdjustmentLine,
    StockAdjustmentReversal,
    StockMovement,
    User,
    Warehouse,
)
from app.inventory.warehouse import balance, require_warehouse
from app.inventory.physical_lots import LotPart, lot_balance, post_lot_movement
from app.inventory.lot_inputs import PhysicalLotPartInput

UserCreator = aliased(User)
UserPoster = aliased(User)
UserReverser = aliased(User)
UserReviewer = aliased(User)

router = APIRouter(route_class=NumberedRoute, prefix="/api/v1")


class AdjustmentLineInput(BaseModel):
    material_id: int = Field(gt=0)
    quantity: Decimal

    @field_validator("quantity")
    @classmethod
    def valid_quantity(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value == 0 or abs(value) > 1_000_000 or value.as_tuple().exponent < -3:
            raise ValueError("调整量不能为零，绝对值不超过一百万且最多三位小数")
        return value


class AdjustmentInput(BaseModel):
    warehouse_id: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=200)
    reference: str = Field(default="", max_length=100)
    lines: list[AdjustmentLineInput] = Field(min_length=1, max_length=100)

    @field_validator("reason")
    @classmethod
    def valid_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("调整原因不能为空")
        return value.strip()


class ReasonInput(BaseModel):
    reason: str = Field(min_length=1, max_length=200)

    @field_validator("reason")
    @classmethod
    def valid_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("原因不能为空")
        return value.strip()


class AdjustmentLotPartInput(PhysicalLotPartInput):
    lot_id: int | None = Field(default=None, gt=0)

    @model_validator(mode='after')
    def existing_lot_has_no_new_origin(self):
        if self.lot_id is not None and any((
            self.supplier_lot, self.manufactured_on, self.expires_on)):
            raise ValueError('已有批次不能同时登记新批次来源字段')
        return self


class AdjustmentLotLineInput(BaseModel):
    adjustment_line_id: int = Field(gt=0)
    lots: list[AdjustmentLotPartInput] = Field(min_length=1, max_length=20)


class AdjustmentPostInput(BaseModel):
    lines: list[AdjustmentLotLineInput] = Field(min_length=1, max_length=100)


def adjustment_data(db: Session, adjustment_id: int) -> dict:
    row = (
        db.execute(
            select(
                StockAdjustment.id,
                StockAdjustment.warehouse_id,
                StockAdjustment.reason,
                StockAdjustment.reference,
                StockAdjustment.status,
                StockAdjustment.created_by,
                StockAdjustment.submitted_by,
                StockAdjustment.reviewed_by,
                StockAdjustment.posted_by,
                StockAdjustment.cancelled_by,
                StockAdjustment.review_reason,
                StockAdjustment.created_at,
                StockAdjustment.submitted_at,
                StockAdjustment.reviewed_at,
                StockAdjustment.posted_at,
                StockAdjustment.cancelled_at,
                Warehouse.name.label("warehouse_name"),
                UserCreator.username.label("created_by_name"),
                UserReviewer.username.label("reviewed_by_name"),
                UserPoster.username.label("posted_by_name"),
                StockAdjustmentReversal.id.label("reversal_id"),
                StockAdjustmentReversal.reason.label("reversal_reason"),
                StockAdjustmentReversal.created_at.label("reversed_at"),
                StockAdjustmentReversal.created_by.label("reversed_by"),
                UserReverser.username.label("reversed_by_name"),
            )
            .select_from(StockAdjustment)
            .join(Warehouse, (Warehouse.id == StockAdjustment.warehouse_id))
            .join(UserCreator, (UserCreator.id == StockAdjustment.created_by))
            .outerjoin(UserReviewer, (UserReviewer.id == StockAdjustment.reviewed_by))
            .outerjoin(UserPoster, (UserPoster.id == StockAdjustment.posted_by))
            .outerjoin(StockAdjustmentReversal, (StockAdjustmentReversal.adjustment_id == StockAdjustment.id))
            .outerjoin(UserReverser, (UserReverser.id == StockAdjustmentReversal.created_by))
            .where((StockAdjustment.id == adjustment_id))
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(404, "库存调整单不存在")
    lines = (
        db.execute(
            select(
                StockAdjustmentLine.id,
                StockAdjustmentLine.material_id,
                Material.sku,
                Material.name.label("material_name"),
                Material.unit,
                StockAdjustmentLine.quantity,
            )
            .select_from(StockAdjustmentLine)
            .join(Material, (Material.id == StockAdjustmentLine.material_id))
            .where((StockAdjustmentLine.adjustment_id == adjustment_id))
            .order_by(StockAdjustmentLine.id)
        )
        .mappings()
        .all()
    )
    lots_by_line: dict[int, list[dict]] = {}
    for line_id, lot, allocation in db.execute(
        select(StockMovement.source_line_id, PhysicalLot, PhysicalLotAllocation)
        .join(PhysicalLotAllocation, PhysicalLotAllocation.movement_id == StockMovement.id)
        .join(PhysicalLot, PhysicalLot.id == PhysicalLotAllocation.lot_id)
        .where(StockMovement.source_type == 'adjustment', StockMovement.source_id == adjustment_id)
        .order_by(StockMovement.source_line_id, PhysicalLotAllocation.id)
    ):
        lots_by_line.setdefault(line_id, []).append({
            'id': lot.id, 'code': lot.code, 'quantity': format(abs(Decimal(allocation.quantity)), 'f'),
            'source_kind': lot.source_kind, 'supplier_lot': lot.supplier_lot,
            'manufactured_on': lot.manufactured_on, 'expires_on': lot.expires_on,
        })
    return {**dict(row), 'approval': approval.case_data(approval.find_case(db, 'StockAdjustment', adjustment_id)),
        'reversal_approval': approval.case_data(approval.find_case(db, 'StockAdjustment', adjustment_id, 'reverse')), 'lines': [{**dict(line), 'physical_lots': lots_by_line.get(line['id'], [])}
                                  for line in lines]}


@router.get("/stock-adjustments")
def list_adjustments(_: dict = Depends(require("adjustment.view"))) -> list[dict]:
    with orm_session() as db:
        ids = [
            row
            for row in db.scalars(
                select(StockAdjustment.id).select_from(StockAdjustment).order_by(StockAdjustment.id.desc())
            )
        ]
        return [adjustment_data(db, item_id) for item_id in ids]


@router.post("/stock-adjustments", status_code=201)
def create_adjustment(payload: AdjustmentInput, user: dict = Depends(require("adjustment.create"))) -> dict:
    if len({line.material_id for line in payload.lines}) != len(payload.lines):
        raise HTTPException(422, "一张调整单不能重复选择同一物料")
    with orm_session(write=True) as db:
        require_warehouse(db, payload.warehouse_id)
        for line in payload.lines:
            if (
                not db.execute(
                    select(literal(1)).select_from(Material).where((Material.id == line.material_id))
                )
                .mappings()
                .first()
            ):
                raise HTTPException(422, f"物料 #{line.material_id} 不存在")
        item_id = add_model(
            db,
            StockAdjustment(
                warehouse_id=payload.warehouse_id,
                reason=payload.reason,
                reference=payload.reference.strip(),
                created_by=user["id"],
            ),
        ).id
        db.add_all(
            [
                StockAdjustmentLine(
                    adjustment_id=item_id, material_id=line.material_id, quantity=str(line.quantity)
                )
                for line in payload.lines
            ]
        )
        return adjustment_data(db, item_id)


# 原无版本审批接口停止接受动作；旧客户端须升级到统一审批入口，不能绕过模板或冲突检查。
@router.post("/stock-adjustments/{adjustment_id}/submit")
def submit_adjustment(adjustment_id: int, user: dict = Depends(require("adjustment.submit"))) -> dict:
    raise HTTPException(409, "请使用统一单据审批入口提交，原接口不支持审批版本")


@router.post("/stock-adjustments/{adjustment_id}/approve")
def approve_adjustment(adjustment_id: int, user: dict = Depends(require("adjustment.review"))) -> dict:
    raise HTTPException(409, "请使用统一单据审批入口审核，原接口不支持审批版本")


@router.post("/stock-adjustments/{adjustment_id}/reject")
def reject_adjustment(adjustment_id: int, payload: ReasonInput,
                      user: dict = Depends(require("adjustment.review"))) -> dict:
    raise HTTPException(409, "请使用统一单据审批入口驳回，原接口不支持审批版本")


@router.post("/stock-adjustments/{adjustment_id}/cancel")
def cancel_adjustment(adjustment_id: int, user: dict = Depends(require("adjustment.cancel"))) -> dict:
    with orm_session(write=True) as db:
        pending = approval.find_case(db, 'StockAdjustment', adjustment_id)
        if pending and pending.status in ('submitted', 'approved'):
            raise HTTPException(409, '请先撤回审批再取消单据')
        row = (
            db.execute(
                select(StockAdjustment.status)
                .select_from(StockAdjustment)
                .where((StockAdjustment.id == adjustment_id))
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "库存调整单不存在")
        if row["status"] not in ("draft", "submitted", "approved", "rejected"):
            raise HTTPException(409, "此调整单已处理")
        db.execute(
            update(StockAdjustment)
            .where((StockAdjustment.id == adjustment_id))
            .values(status="cancelled", cancelled_by=user["id"], cancelled_at=func.current_timestamp())
        )
        return adjustment_data(db, adjustment_id)


@router.get('/stock-adjustments/{adjustment_id}/available-lots')
def available_adjustment_lots(adjustment_id: int,
                              _: dict = Depends(require('adjustment.post'))) -> dict:
    with orm_session() as db:
        adjustment = db.get(StockAdjustment, adjustment_id)
        if adjustment is None:
            raise HTTPException(404, '库存调整单不存在')
        if adjustment.status != 'approved':
            raise HTTPException(409, '只能查询已审批调整单的可用批次')
        lines = list(db.execute(select(StockAdjustmentLine.id, StockAdjustmentLine.material_id,
                                       StockAdjustmentLine.quantity)
                                .where(StockAdjustmentLine.adjustment_id == adjustment_id)
                                .order_by(StockAdjustmentLine.id)).mappings())
        lots = list(db.scalars(select(PhysicalLot).where(
            PhysicalLot.material_id.in_({line['material_id'] for line in lines}))
            .order_by(PhysicalLot.id)))
        by_material = {line['material_id']: [] for line in lines}
        for lot in lots:
            quantity = lot_balance(db, adjustment.warehouse_id, lot.id)
            if quantity < 0:
                continue
            by_material[lot.material_id].append({
                'lot_id': lot.id, 'code': lot.code, 'source_kind': lot.source_kind,
                'quantity': format(quantity, 'f'), 'supplier_lot': lot.supplier_lot,
                'manufactured_on': lot.manufactured_on, 'expires_on': lot.expires_on,
            })
        return {'adjustment_id': adjustment_id, 'warehouse_id': adjustment.warehouse_id,
                'lines': [{'adjustment_line_id': line['id'], 'material_id': line['material_id'],
                           'quantity': line['quantity'], 'lots': by_material[line['material_id']]}
                          for line in lines]}


@router.post("/stock-adjustments/{adjustment_id}/post")
def post_adjustment(adjustment_id: int, payload: AdjustmentPostInput | None = None,
                    user: dict = Depends(require("adjustment.post"))) -> dict:
    with orm_session(write=True) as db:
        # 批准正文与本次执行内容必须一致，不能通过旧确认接口绕过审批。
        approved = approval.require_approved(db, 'StockAdjustment', adjustment_id,
            adjustment_snapshot(db, adjustment_id), user['id'])
        row = (
            db.execute(
                select(StockAdjustment.status, StockAdjustment.warehouse_id)
                .select_from(StockAdjustment)
                .where((StockAdjustment.id == adjustment_id))
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "库存调整单不存在")
        if row["status"] != "approved":
            raise HTTPException(409, "只有已审批调整单可确认")
        lines = (
            db.execute(
                select(
                    StockAdjustmentLine.id,
                    StockAdjustmentLine.adjustment_id,
                    StockAdjustmentLine.material_id,
                    StockAdjustmentLine.quantity,
                )
                .select_from(StockAdjustmentLine)
                .where((StockAdjustmentLine.adjustment_id == adjustment_id))
            )
            .mappings()
            .all()
        )
        for line in lines:
            if balance(db, row["warehouse_id"], line["material_id"]) + Decimal(line["quantity"]) < 0:
                raise HTTPException(409, f"物料 #{line['material_id']} 库存不足")
        lot_lines = {line.adjustment_line_id: line for line in payload.lines} if payload else None
        if lot_lines is not None and (len(lot_lines) != len(payload.lines)
                                      or set(lot_lines) != {line['id'] for line in lines}):
            raise HTTPException(422, '批次明细必须与调整单逐行对应')
        for line in lines:
            quantity = Decimal(line['quantity'])
            movement = StockMovement(
                warehouse_id=row['warehouse_id'], material_id=line['material_id'],
                quantity=line['quantity'], source_type='adjustment', source_id=adjustment_id,
                source_line_id=line['id'], created_by=user['id'],
            )
            if lot_lines is None:
                db.add(movement)
                continue
            parts = lot_lines[line['id']].lots
            if sum((part.quantity for part in parts), Decimal(0)) != abs(quantity):
                raise HTTPException(422, f'调整明细 #{line["id"]} 的批次数量之和不匹配')
            existing_ids = [part.lot_id for part in parts if part.lot_id is not None]
            if len(set(existing_ids)) != len(existing_ids):
                raise HTTPException(422, '一行调整不能重复选择同一已有实物批次')
            if quantity < 0 and any(part.lot_id is None for part in parts):
                raise HTTPException(422, '负向调整只能扣减已有实物批次')
            selected = []
            new_lots = []
            for index, part in enumerate(parts, 1):
                if part.lot_id is not None:
                    selected.append(LotPart(part.lot_id, part.quantity.copy_sign(quantity)))
                    continue
                lot = add_model(db, PhysicalLot(
                    material_id=line['material_id'],
                    code=f'AD{adjustment_id}-L{line["id"]}-P{index}',
                    source_kind='adjustment', supplier_lot=part.supplier_lot,
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
            update(StockAdjustment)
            .where((StockAdjustment.id == adjustment_id))
            .values(status="posted", posted_by=user["id"], posted_at=func.current_timestamp())
        )
        approval.mark_executed(db, approved, user['id'])
        return adjustment_data(db, adjustment_id)


@router.post("/stock-adjustments/{adjustment_id}/reverse", status_code=201)
def reverse_adjustment(
    adjustment_id: int, payload: ReasonInput, user: dict = Depends(require("adjustment.reverse"))
) -> dict:
    with orm_session(write=True) as db:
        # 批准正文与本次执行内容必须一致，不能通过旧确认接口绕过审批。
        approved = approval.require_approved(db, 'StockAdjustment', adjustment_id,
            document_snapshot(db, 'StockAdjustment', adjustment_id, 'reverse', payload.reason), user['id'], intent='reverse', permission='adjustment.reverse')
        row = (
            db.execute(
                select(StockAdjustment.status, StockAdjustment.warehouse_id)
                .select_from(StockAdjustment)
                .where((StockAdjustment.id == adjustment_id))
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "库存调整单不存在")
        if (
            row["status"] != "posted"
            or db.execute(
                select(literal(1))
                .select_from(StockAdjustmentReversal)
                .where((StockAdjustmentReversal.adjustment_id == adjustment_id))
            )
            .mappings()
            .first()
        ):
            raise HTTPException(409, "只能冲销尚未冲销的已确认调整单")
        lines = (
            db.execute(
                select(
                    StockAdjustmentLine.id,
                    StockAdjustmentLine.adjustment_id,
                    StockAdjustmentLine.material_id,
                    StockAdjustmentLine.quantity,
                )
                .select_from(StockAdjustmentLine)
                .where((StockAdjustmentLine.adjustment_id == adjustment_id))
            )
            .mappings()
            .all()
        )
        for line in lines:
            if balance(db, row["warehouse_id"], line["material_id"]) - Decimal(line["quantity"]) < 0:
                raise HTTPException(409, f"物料 #{line['material_id']} 库存不足，无法冲销")
        reversal_id = add_model(
            db,
            StockAdjustmentReversal(
                adjustment_id=adjustment_id, reason=payload.reason, created_by=user["id"]
            ),
        ).id
        for line in lines:
            movement = StockMovement(
                warehouse_id=row['warehouse_id'], material_id=line['material_id'],
                quantity=str(-Decimal(line['quantity'])), source_type='adjustment_reversal',
                source_id=reversal_id, source_line_id=line['id'], created_by=user['id'],
            )
            allocations = list(db.scalars(select(PhysicalLotAllocation)
                .join(StockMovement, StockMovement.id == PhysicalLotAllocation.movement_id)
                .where(StockMovement.source_type == 'adjustment',
                       StockMovement.source_id == adjustment_id,
                       StockMovement.source_line_id == line['id'])
                .order_by(PhysicalLotAllocation.id)))
            if allocations:
                if sum((Decimal(part.quantity) for part in allocations), Decimal(0)) != Decimal(line['quantity']):
                    raise HTTPException(409, '原调整批次分配不完整，无法冲销')
                post_lot_movement(db, movement, [LotPart(
                    part.lot_id, -Decimal(part.quantity), part.id) for part in allocations])
            else:
                db.add(movement)
        approval.mark_executed(db, approved, user['id'], permission='adjustment.reverse')
        return adjustment_data(db, adjustment_id)
