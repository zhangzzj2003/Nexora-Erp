"""生产工单以启用 BOM 创建需料快照，并汇总净领料数量。"""

from app.core import document_approval as approval
from app.core.approval_documents import work_order_snapshot
from app.core.document_responses import NumberedRoute
from sqlalchemy import select, update, func, literal
from sqlalchemy.orm import Session
from decimal import Decimal, ROUND_CEILING

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.core.orm import orm_session, add_model
from app.core.models import (
    Bom,
    BomLine,
    Material,
    MaterialIssue,
    MaterialIssueLine,
    MaterialIssueReversal,
    MaterialReturn,
    MaterialReturnLine,
    MaterialReturnReversal,
    ProductionCompletion,
    ProductionCompletionReversal,
    User,
    Warehouse,
    WorkOrder,
    WorkOrderLine,
    QualityDisposition,
)
from app.inventory.warehouse import require_warehouse
from app.access.security import require

router = APIRouter(route_class=NumberedRoute, prefix="/api/v1")


class WorkOrderInput(BaseModel):
    bom_id: int = Field(gt=0)
    warehouse_id: int = Field(gt=0)
    target_quantity: Decimal
    reference: str = Field(default="", max_length=100)
    note: str = Field(default="", max_length=200)

    @field_validator("target_quantity")
    @classmethod
    def valid_quantity(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 0 or value > 1_000_000 or value.as_tuple().exponent < -3:
            raise ValueError("目标产量须大于零、最多三位小数且不超过一百万")
        return value


def issued_quantity(db: Session, work_order_line_id: int) -> Decimal:
    # 原领料、冲销和退料都保留，可领量只累计仍有效的已确认单据。
    issued = sum(
        (
            Decimal(row)
            for row in db.scalars(
                select(MaterialIssueLine.quantity)
                .select_from(MaterialIssueLine)
                .join(MaterialIssue, MaterialIssue.id == MaterialIssueLine.material_issue_id)
                .where(
                    MaterialIssueLine.work_order_line_id == work_order_line_id,
                    MaterialIssue.status == "posted",
                    ~select(MaterialIssueReversal.id).where(
                        MaterialIssueReversal.material_issue_id == MaterialIssue.id).exists(),
                )
            )
        ),
        Decimal(0),
    )
    returned = sum(
        (
            Decimal(row)
            for row in db.scalars(
                select(MaterialReturnLine.quantity)
                .select_from(MaterialReturnLine)
                .join(MaterialReturn, MaterialReturn.id == MaterialReturnLine.material_return_id)
                .join(MaterialIssueLine, MaterialIssueLine.id == MaterialReturnLine.material_issue_line_id)
                .where(
                    MaterialIssueLine.work_order_line_id == work_order_line_id,
                    MaterialReturn.status == "posted",
                    ~select(MaterialReturnReversal.id).where(
                        MaterialReturnReversal.material_return_id == MaterialReturn.id).exists(),
                )
            )
        ),
        Decimal(0),
    )
    return issued - returned


def posted_completion_totals(db: Session, order_id: int) -> tuple[Decimal, Decimal, Decimal]:
    rows = db.execute(
        select(
            ProductionCompletion.reported_quantity,
            ProductionCompletion.accepted_quantity,
            ProductionCompletion.rejected_quantity,
        )
        .select_from(ProductionCompletion)
        .where(
            ProductionCompletion.work_order_id == order_id,
            ProductionCompletion.status == "posted",
            ~select(literal(1))
            .select_from(ProductionCompletionReversal)
            .where(ProductionCompletionReversal.production_completion_id == ProductionCompletion.id)
            .exists(),
        )
    ).mappings()
    totals = [Decimal(0), Decimal(0), Decimal(0)]
    for row in rows:
        for index, field in enumerate(("reported_quantity", "accepted_quantity", "rejected_quantity")):
            totals[index] += Decimal(row[field])
    return totals[0], totals[1], totals[2]


def required_for_output(
    required_quantity: Decimal, target_quantity: Decimal, reported_quantity: Decimal
) -> Decimal:
    # 分批报工按累计产出向上取整需料，最后一批不会突破工单原需料快照。
    return (required_quantity * reported_quantity / target_quantity).quantize(
        Decimal("0.001"), rounding=ROUND_CEILING
    )


def work_order_data(db: Session, order_id: int) -> dict:
    row = (
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
                Bom.version.label("bom_version"),
                Bom.product_material_id,
                Material.sku.label("product_sku"),
                Material.name.label("product_name"),
                Material.unit.label("product_unit"),
                Warehouse.name.label("warehouse_name"),
                User.username.label("created_by_name"),
            )
            .select_from(WorkOrder)
            .join(Bom, (Bom.id == WorkOrder.bom_id))
            .join(Material, (Material.id == Bom.product_material_id))
            .join(Warehouse, (Warehouse.id == WorkOrder.warehouse_id))
            .join(User, (User.id == WorkOrder.created_by))
            .where((WorkOrder.id == order_id))
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(404, "生产工单不存在")
    lines = (
        db.execute(
            select(
                WorkOrderLine.id,
                WorkOrderLine.component_material_id,
                Material.sku,
                Material.name.label("material_name"),
                Material.unit,
                WorkOrderLine.required_quantity,
            )
            .select_from(WorkOrderLine)
            .join(Material, (Material.id == WorkOrderLine.component_material_id))
            .where((WorkOrderLine.work_order_id == order_id))
            .order_by(WorkOrderLine.id)
        )
        .mappings()
        .all()
    )
    details = []
    for line in lines:
        issued = issued_quantity(db, line["id"])
        details.append(
            {
                **dict(line),
                "issued_quantity": str(issued),
                "remaining_quantity": str(Decimal(line["required_quantity"]) - issued),
            }
        )
    reported, accepted, rejected = posted_completion_totals(db, order_id)
    rework = db.scalar(select(QualityDisposition).where(QualityDisposition.rework_order_id == order_id))
    return {
        **dict(row),
        "approval": approval.case_data(approval.find_case(db, "WorkOrder", order_id)),
        "lines": details,
        "reported_quantity": str(reported),
        "accepted_quantity": str(accepted),
        "rejected_quantity": str(rejected),
        "remaining_output_quantity": str(Decimal(row["target_quantity"]) - reported),
        "rework_disposition_id": rework.id if rework else None,
        "rework_completion_id": rework.completion_id if rework else None,
        "rework_reference": rework.reference if rework else None,
    }


@router.get("/work-orders")
def list_work_orders(_: dict = Depends(require("production.view"))) -> list[dict]:
    with orm_session() as db:
        ids = [
            row
            for row in db.scalars(select(WorkOrder.id).select_from(WorkOrder).order_by(WorkOrder.id.desc()))
        ]
        return [work_order_data(db, order_id) for order_id in ids]


def create_work_order_in_session(db: Session, payload: WorkOrderInput, user: dict) -> dict:
    bom = (
        db.execute(
            select(Bom.status, Bom.base_quantity).select_from(Bom).where((Bom.id == payload.bom_id))
        )
        .mappings()
        .first()
    )
    if not bom:
        raise HTTPException(422, "BOM 不存在")
    if bom["status"] != "active":
        raise HTTPException(409, "只有启用中的 BOM 可用于新工单")
    require_warehouse(db, payload.warehouse_id)
    requirements = []
    for line in db.execute(
        select(BomLine.component_material_id, BomLine.quantity)
        .select_from(BomLine)
        .where((BomLine.bom_id == payload.bom_id))
    ).mappings():
        # 需求按库存的三位精度向上取整，防止比例换算后低估领料量。
        needed = (
            payload.target_quantity * Decimal(line["quantity"]) / Decimal(bom["base_quantity"])
        ).quantize(Decimal("0.001"), rounding=ROUND_CEILING)
        if needed > 1_000_000:
            raise HTTPException(422, "工单组件需求超过一百万，请拆分工单")
        requirements.append((line["component_material_id"], str(needed)))
    if not requirements:
        raise HTTPException(409, "BOM 没有组件，无法创建工单")
    cursor = add_model(
        db,
        WorkOrder(
            bom_id=payload.bom_id,
            warehouse_id=payload.warehouse_id,
            target_quantity=str(payload.target_quantity),
            reference=payload.reference.strip(),
            note=payload.note.strip(),
            created_by=user["id"],
        ),
    )
    db.add_all(
        [
            WorkOrderLine(
                work_order_id=cursor.id, component_material_id=material_id, required_quantity=quantity
            )
            for material_id, quantity in requirements
        ]
    )
    return work_order_data(db, cursor.id)


@router.post("/work-orders", status_code=201)
def create_work_order(payload: WorkOrderInput, user: dict = Depends(require("work_order.create"))) -> dict:
    with orm_session(write=True) as db:
        return create_work_order_in_session(db, payload, user)


@router.post("/work-orders/{order_id}/release")
def release_work_order(order_id: int, user: dict = Depends(require("work_order.release"))) -> dict:
    with orm_session(write=True) as db:
        row = (
            db.execute(
                select(WorkOrder.status, Bom.status.label("bom_status"))
                .select_from(WorkOrder)
                .join(Bom, (Bom.id == WorkOrder.bom_id))
                .where((WorkOrder.id == order_id))
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "生产工单不存在")
        if row["status"] != "draft":
            raise HTTPException(409, "只有工单草稿可以下达")
        rework = db.scalar(select(QualityDisposition).where(QualityDisposition.rework_order_id == order_id))
        if rework is not None and rework.status != 'posted':
            raise HTTPException(409, '返工来源已更正，不能下达此工单')
        if rework is None and row["bom_status"] != "active":
            raise HTTPException(409, "BOM 已停用，请取消草稿并使用新版本建单")
        # 无追加材料的返工仍需下达，随后可登记人工并报工；不虚构组件出库。
        # 独立批准不替代原数量/质检校验，执行记录与业务流水必须共同提交或回滚。
        approved = approval.require_approved(db, 'WorkOrder', order_id, work_order_snapshot(db, order_id), user['id'])
        status = 'in_progress' if rework is not None and db.scalar(select(WorkOrderLine.id).where(
            WorkOrderLine.work_order_id == order_id).limit(1)) is None else 'released'
        db.execute(
            update(WorkOrder)
            .where((WorkOrder.id == order_id))
            .values(status=status, released_by=user["id"], released_at=func.current_timestamp())
        )
        approval.mark_executed(db, approved, user['id'])
        return work_order_data(db, order_id)


@router.post("/work-orders/{order_id}/cancel")
def cancel_work_order(order_id: int, user: dict = Depends(require("work_order.cancel"))) -> dict:
    with orm_session(write=True) as db:
        pending = approval.find_case(db, 'WorkOrder', order_id)
        if pending and pending.status in ('submitted', 'approved'):
            raise HTTPException(409, '请先撤回审批再取消单据')
        row = (
            db.execute(select(WorkOrder.status).select_from(WorkOrder).where((WorkOrder.id == order_id)))
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "生产工单不存在")
        if db.scalar(select(QualityDisposition.id).where(QualityDisposition.rework_order_id == order_id,
            QualityDisposition.status == 'posted')) is not None:
            raise HTTPException(409, '关联返工工单须在不合格品处置页更正来源后取消，不能遗失被占用的不合格数量')
        # 发料后由后续更正流程处理，不能用取消抹去真实库存流水。
        if row["status"] not in ("draft", "released"):
            raise HTTPException(409, "已发料或已完工的生产工单不可取消")
        db.execute(
            update(WorkOrder)
            .where((WorkOrder.id == order_id))
            .values(status="cancelled", cancelled_by=user["id"], cancelled_at=func.current_timestamp())
        )
        return work_order_data(db, order_id)
