"""生产报工经质检确认后，将合格成品入目标仓库。"""

from sqlalchemy import select, update, func, literal
from sqlalchemy.orm import Session, aliased
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.core.orm import orm_session, add_model
from app.core.models import (
    Bom,
    Material,
    ProductionCompletion,
    ProductionCompletionReversal,
    StockMovement,
    User,
    Warehouse,
    WorkOrder,
    WorkOrderLine,
)
from app.inventory.warehouse import balance
from app.access.security import require
from app.production.work_orders import issued_quantity, posted_completion_totals, required_for_output
from app.production.cost_lock import ensure_unsettled

UserCreator = aliased(User)
UserInspector = aliased(User)
UserReverser = aliased(User)

router = APIRouter(prefix="/api/v1")


class CompletionInput(BaseModel):
    work_order_id: int = Field(gt=0)
    reported_quantity: Decimal
    reference: str = Field(default="", max_length=100)

    @field_validator("reported_quantity")
    @classmethod
    def valid_quantity(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 0 or value > 1_000_000 or value.as_tuple().exponent < -3:
            raise ValueError("报工数量须大于零、最多三位小数且不超过一百万")
        return value


class InspectionInput(BaseModel):
    accepted_quantity: Decimal
    qc_note: str = Field(min_length=1, max_length=200)

    @field_validator("accepted_quantity")
    @classmethod
    def valid_quantity(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value < 0 or value > 1_000_000 or value.as_tuple().exponent < -3:
            raise ValueError("合格数量须为非负数、最多三位小数且不超过一百万")
        return value

    @field_validator("qc_note")
    @classmethod
    def trim_note(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("质检说明不能为空")
        return value.strip()


class ReversalInput(BaseModel):
    reason: str = Field(min_length=1, max_length=200)

    @field_validator("reason")
    @classmethod
    def trim_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("冲销原因不能为空")
        return value.strip()


def completion_data(db: Session, completion_id: int) -> dict:
    row = (
        db.execute(
            select(
                ProductionCompletion.id,
                ProductionCompletion.work_order_id,
                ProductionCompletion.reported_quantity,
                ProductionCompletion.accepted_quantity,
                ProductionCompletion.rejected_quantity,
                ProductionCompletion.reference,
                ProductionCompletion.qc_note,
                ProductionCompletion.status,
                ProductionCompletion.created_by,
                ProductionCompletion.inspected_by,
                ProductionCompletion.posted_by,
                ProductionCompletion.cancelled_by,
                ProductionCompletion.created_at,
                ProductionCompletion.inspected_at,
                ProductionCompletion.posted_at,
                ProductionCompletion.cancelled_at,
                WorkOrder.warehouse_id,
                Warehouse.name.label("warehouse_name"),
                Bom.product_material_id,
                Material.sku.label("product_sku"),
                Material.name.label("product_name"),
                Material.unit.label("product_unit"),
                UserCreator.username.label("created_by_name"),
                UserInspector.username.label("inspected_by_name"),
                ProductionCompletionReversal.id.label("reversal_id"),
                ProductionCompletionReversal.reason.label("reversal_reason"),
                ProductionCompletionReversal.created_by.label("reversed_by"),
                ProductionCompletionReversal.created_at.label("reversed_at"),
                UserReverser.username.label("reversed_by_name"),
            )
            .select_from(ProductionCompletion)
            .join(WorkOrder, (WorkOrder.id == ProductionCompletion.work_order_id))
            .join(Warehouse, (Warehouse.id == WorkOrder.warehouse_id))
            .join(Bom, (Bom.id == WorkOrder.bom_id))
            .join(Material, (Material.id == Bom.product_material_id))
            .join(UserCreator, (UserCreator.id == ProductionCompletion.created_by))
            .outerjoin(UserInspector, (UserInspector.id == ProductionCompletion.inspected_by))
            .outerjoin(
                ProductionCompletionReversal,
                (ProductionCompletionReversal.production_completion_id == ProductionCompletion.id),
            )
            .outerjoin(UserReverser, (UserReverser.id == ProductionCompletionReversal.created_by))
            .where((ProductionCompletion.id == completion_id))
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(404, "生产完工单不存在")
    result = dict(row)
    if result["reversal_id"] is not None:
        result["status"] = "reversed"
    return result


@router.get("/production-completions")
def list_completions(_: dict = Depends(require("production.view"))) -> list[dict]:
    with orm_session() as db:
        ids = [
            row
            for row in db.scalars(
                select(ProductionCompletion.id)
                .select_from(ProductionCompletion)
                .order_by(ProductionCompletion.id.desc())
            )
        ]
        return [completion_data(db, completion_id) for completion_id in ids]


@router.post("/production-completions", status_code=201)
def create_completion(
    payload: CompletionInput, user: dict = Depends(require("production_completion.create"))
) -> dict:
    with orm_session(write=True) as db:
        order = (
            db.execute(
                select(WorkOrder.status, WorkOrder.target_quantity)
                .select_from(WorkOrder)
                .where((WorkOrder.id == payload.work_order_id))
            )
            .mappings()
            .first()
        )
        if not order:
            raise HTTPException(422, "生产工单不存在")
        if order["status"] != "in_progress":
            raise HTTPException(409, "只有生产中的工单可以报工")
        posted, _, _ = posted_completion_totals(db, payload.work_order_id)
        if payload.reported_quantity > Decimal(order["target_quantity"]) - posted:
            raise HTTPException(409, "报工数量超出工单剩余目标产量")
        cursor = add_model(
            db,
            ProductionCompletion(
                work_order_id=payload.work_order_id,
                reported_quantity=str(payload.reported_quantity),
                reference=payload.reference.strip(),
                created_by=user["id"],
            ),
        )
        return completion_data(db, cursor.id)


@router.post("/production-completions/{completion_id}/inspect")
def inspect_completion(
    completion_id: int,
    payload: InspectionInput,
    user: dict = Depends(require("production_completion.inspect")),
) -> dict:
    with orm_session(write=True) as db:
        row = (
            db.execute(
                select(
                    ProductionCompletion.status,
                    ProductionCompletion.reported_quantity,
                    WorkOrder.status.label("work_order_status"),
                )
                .select_from(ProductionCompletion)
                .join(WorkOrder, (WorkOrder.id == ProductionCompletion.work_order_id))
                .where((ProductionCompletion.id == completion_id))
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "生产完工单不存在")
        if row["status"] != "draft":
            raise HTTPException(409, "只有报工草稿可以质检")
        if row["work_order_status"] != "in_progress":
            raise HTTPException(409, "生产工单当前不可质检")
        reported = Decimal(row["reported_quantity"])
        if payload.accepted_quantity > reported:
            raise HTTPException(422, "合格数量不能超过报工数量")
        rejected = reported - payload.accepted_quantity
        db.execute(
            update(ProductionCompletion)
            .where((ProductionCompletion.id == completion_id))
            .values(
                status="inspected",
                accepted_quantity=str(payload.accepted_quantity),
                rejected_quantity=str(rejected),
                qc_note=payload.qc_note,
                inspected_by=user["id"],
                inspected_at=func.current_timestamp(),
            )
        )
        return completion_data(db, completion_id)


@router.post("/production-completions/{completion_id}/post")
def post_completion(completion_id: int, user: dict = Depends(require("production_completion.post"))) -> dict:
    with orm_session(write=True) as db:
        # 同一写锁覆盖目标产量、净领料、合格品入库和工单状态，避免并行报工超量。
        completion = (
            db.execute(
                select(
                    ProductionCompletion.id,
                    ProductionCompletion.work_order_id,
                    ProductionCompletion.reported_quantity,
                    ProductionCompletion.accepted_quantity,
                    ProductionCompletion.rejected_quantity,
                    ProductionCompletion.reference,
                    ProductionCompletion.qc_note,
                    ProductionCompletion.status,
                    ProductionCompletion.created_by,
                    ProductionCompletion.inspected_by,
                    ProductionCompletion.posted_by,
                    ProductionCompletion.cancelled_by,
                    ProductionCompletion.created_at,
                    ProductionCompletion.inspected_at,
                    ProductionCompletion.posted_at,
                    ProductionCompletion.cancelled_at,
                )
                .select_from(ProductionCompletion)
                .where((ProductionCompletion.id == completion_id))
            )
            .mappings()
            .first()
        )
        if not completion:
            raise HTTPException(404, "生产完工单不存在")
        if completion["status"] != "inspected":
            raise HTTPException(409, "完工单须先质检且不能重复确认")
        order = (
            db.execute(
                select(
                    WorkOrder.id,
                    WorkOrder.bom_id,
                    WorkOrder.warehouse_id,
                    WorkOrder.target_quantity,
                    WorkOrder.reference,
                    WorkOrder.note,
                    WorkOrder.status,
                    WorkOrder.created_by,
                    WorkOrder.released_by,
                    WorkOrder.cancelled_by,
                    WorkOrder.created_at,
                    WorkOrder.released_at,
                    WorkOrder.cancelled_at,
                    WorkOrder.completed_by,
                    WorkOrder.completed_at,
                    Bom.product_material_id,
                )
                .select_from(WorkOrder)
                .join(Bom, (Bom.id == WorkOrder.bom_id))
                .where((WorkOrder.id == completion["work_order_id"]))
            )
            .mappings()
            .first()
        )
        if order["status"] != "in_progress":
            raise HTTPException(409, "生产工单当前不可完工入库")
        posted, _, _ = posted_completion_totals(db, order["id"])
        # 目标数按实际报工总数累计，质检不合格品也占用本工单的报工目标。
        total = posted + Decimal(completion["reported_quantity"])
        target = Decimal(order["target_quantity"])
        if total > target:
            raise HTTPException(409, "完工数量超出工单目标产量")
        for line in db.execute(
            select(WorkOrderLine.id, WorkOrderLine.component_material_id, WorkOrderLine.required_quantity)
            .select_from(WorkOrderLine)
            .where((WorkOrderLine.work_order_id == order["id"]))
        ).mappings():
            needed = required_for_output(Decimal(line["required_quantity"]), target, total)
            if issued_quantity(db, line["id"]) < needed:
                raise HTTPException(409, f"组件 #{line['component_material_id']} 领料不足，不能确认完工")
        accepted = Decimal(completion["accepted_quantity"])
        # 不合格品只留在质检记录中，不进入可用成品库存。
        if accepted > 0:
            add_model(
                db,
                StockMovement(
                    warehouse_id=order["warehouse_id"],
                    material_id=order["product_material_id"],
                    quantity=str(accepted),
                    source_type="production_completion",
                    source_id=completion_id,
                    source_line_id=completion_id,
                    created_by=user["id"],
                ),
            )
        db.execute(
            update(ProductionCompletion)
            .where((ProductionCompletion.id == completion_id))
            .values(status="posted", posted_by=user["id"], posted_at=func.current_timestamp())
        )
        if total == target:
            db.execute(
                update(WorkOrder)
                .where((WorkOrder.id == order["id"]))
                .values(status="completed", completed_by=user["id"], completed_at=func.current_timestamp())
            )
        return completion_data(db, completion_id)


@router.post("/production-completions/{completion_id}/cancel")
def cancel_completion(
    completion_id: int, user: dict = Depends(require("production_completion.cancel"))
) -> dict:
    with orm_session(write=True) as db:
        row = (
            db.execute(
                select(ProductionCompletion.status)
                .select_from(ProductionCompletion)
                .where((ProductionCompletion.id == completion_id))
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "生产完工单不存在")
        if row["status"] not in ("draft", "inspected"):
            raise HTTPException(409, "已确认完工单不可取消，须另行更正")
        db.execute(
            update(ProductionCompletion)
            .where((ProductionCompletion.id == completion_id))
            .values(status="cancelled", cancelled_by=user["id"], cancelled_at=func.current_timestamp())
        )
        return completion_data(db, completion_id)


@router.post("/production-completions/{completion_id}/reverse")
def reverse_completion(
    completion_id: int, payload: ReversalInput, user: dict = Depends(require("production_completion.reverse"))
) -> dict:
    with orm_session(write=True) as db:
        # 库存核对、冲销凭据、负向流水和工单状态在同一写事务内完成。
        row = (
            db.execute(
                select(
                    ProductionCompletion.id,
                    ProductionCompletion.work_order_id,
                    ProductionCompletion.reported_quantity,
                    ProductionCompletion.accepted_quantity,
                    ProductionCompletion.rejected_quantity,
                    ProductionCompletion.reference,
                    ProductionCompletion.qc_note,
                    ProductionCompletion.status,
                    ProductionCompletion.created_by,
                    ProductionCompletion.inspected_by,
                    ProductionCompletion.posted_by,
                    ProductionCompletion.cancelled_by,
                    ProductionCompletion.created_at,
                    ProductionCompletion.inspected_at,
                    ProductionCompletion.posted_at,
                    ProductionCompletion.cancelled_at,
                    WorkOrder.warehouse_id,
                    Bom.product_material_id,
                    WorkOrder.status.label("order_status"),
                )
                .select_from(ProductionCompletion)
                .join(WorkOrder, (WorkOrder.id == ProductionCompletion.work_order_id))
                .join(Bom, (Bom.id == WorkOrder.bom_id))
                .where((ProductionCompletion.id == completion_id))
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "生产完工单不存在")
        if row["status"] != "posted":
            raise HTTPException(409, "只有已确认的完工单可以冲销")
        ensure_unsettled(db, row["work_order_id"])
        from app.core.models import QualityDisposition
        if db.scalar(select(QualityDisposition.id).where(QualityDisposition.completion_id==completion_id).limit(1)):
            raise HTTPException(409,"完工单已有不合格品处置，不能冲销原报工")
        if (
            db.execute(
                select(literal(1))
                .select_from(ProductionCompletionReversal)
                .where((ProductionCompletionReversal.production_completion_id == completion_id))
            )
            .mappings()
            .first()
        ):
            raise HTTPException(409, "此完工单已冲销")
        accepted = Decimal(row["accepted_quantity"])
        if accepted > 0 and balance(db, row["warehouse_id"], row["product_material_id"]) < accepted:
            raise HTTPException(409, "目标仓库合格成品库存不足，无法冲销；请先处理后续出库或调拨")
        cursor = add_model(
            db,
            ProductionCompletionReversal(
                production_completion_id=completion_id, reason=payload.reason, created_by=user["id"]
            ),
        )
        if accepted > 0:
            # 以冲销单为来源新增反向流水，不修改原入库流水。
            add_model(
                db,
                StockMovement(
                    warehouse_id=row["warehouse_id"],
                    material_id=row["product_material_id"],
                    quantity=str(-accepted),
                    source_type="production_completion_reversal",
                    source_id=cursor.id,
                    source_line_id=cursor.id,
                    created_by=user["id"],
                ),
            )
        if row["order_status"] == "completed":
            db.execute(
                update(WorkOrder)
                .where((WorkOrder.id == row["work_order_id"]))
                .values(status="in_progress", completed_by=None, completed_at=None)
            )
        return completion_data(db, completion_id)
