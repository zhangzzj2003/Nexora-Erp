"""采购申请审批与分批转单数量查询。"""

from app.core.document_responses import NumberedRoute
# 本模块保留申请数量和转单规则，审批统一从带版本的公共入口完成。
from app.core import document_approval as approval
from sqlalchemy import select, update, delete, func, literal
from sqlalchemy.orm import Session, aliased
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.access.security import require
from app.production.mrp_rules import protect_request
from app.core.orm import orm_session, add_model
from app.core.models import (
    Material,
    MaintenancePurchaseRequest,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderRequestLink,
    PurchaseRequest,
    PurchaseRequestLine,
    User,
)

UserCreator = aliased(User)
UserReviewer = aliased(User)

router = APIRouter(route_class=NumberedRoute, prefix="/api/v1")


class RequestLineInput(BaseModel):
    material_id: int = Field(gt=0)
    quantity: Decimal

    @field_validator("quantity")
    @classmethod
    def valid_quantity(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 0 or value > 1_000_000 or value.as_tuple().exponent < -3:
            raise ValueError("数量须大于零、最多三位小数且不超过一百万")
        return value


class PurchaseRequestInput(BaseModel):
    reference: str = Field(default="", max_length=100)
    note: str = Field(default="", max_length=500)
    lines: list[RequestLineInput] = Field(min_length=1, max_length=100)


class ReviewReasonInput(BaseModel):
    reason: str = Field(min_length=1, max_length=200)

    @field_validator("reason")
    @classmethod
    def valid_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("驳回原因不能为空")
        return value.strip()


def ordered_quantity(db: Session, request_line_id: int) -> Decimal:
    # 草稿订单也占用申请额度，取消后才释放，避免并发转单超量。
    return sum(
        (
            Decimal(row)
            for row in db.scalars(
                select(PurchaseOrderLine.quantity)
                .select_from(PurchaseOrderRequestLink)
                .join(
                    PurchaseOrderLine, PurchaseOrderLine.id == PurchaseOrderRequestLink.purchase_order_line_id
                )
                .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
                .where(
                    PurchaseOrderRequestLink.purchase_request_line_id == request_line_id,
                    PurchaseOrder.status != "cancelled",
                )
            )
        ),
        Decimal(0),
    )


def request_data(db: Session, request_id: int) -> dict:
    row = (
        db.execute(
            select(
                PurchaseRequest.id,
                PurchaseRequest.reference,
                PurchaseRequest.note,
                PurchaseRequest.status,
                PurchaseRequest.created_by,
                PurchaseRequest.submitted_by,
                PurchaseRequest.reviewed_by,
                PurchaseRequest.cancelled_by,
                PurchaseRequest.review_reason,
                PurchaseRequest.created_at,
                PurchaseRequest.submitted_at,
                PurchaseRequest.reviewed_at,
                PurchaseRequest.cancelled_at,
                UserCreator.username.label("created_by_name"),
                UserReviewer.username.label("reviewed_by_name"),
            )
            .select_from(PurchaseRequest)
            .join(UserCreator, (UserCreator.id == PurchaseRequest.created_by))
            .outerjoin(UserReviewer, (UserReviewer.id == PurchaseRequest.reviewed_by))
            .where((PurchaseRequest.id == request_id))
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(404, "采购申请不存在")
    lines = []
    for item in db.execute(
        select(
            PurchaseRequestLine.id,
            PurchaseRequestLine.material_id,
            Material.sku,
            Material.name.label("material_name"),
            Material.unit,
            PurchaseRequestLine.quantity,
        )
        .select_from(PurchaseRequestLine)
        .join(Material, (Material.id == PurchaseRequestLine.material_id))
        .where((PurchaseRequestLine.purchase_request_id == request_id))
        .order_by(PurchaseRequestLine.id)
    ).mappings():
        ordered = ordered_quantity(db, item["id"])
        lines.append(
            {
                **dict(item),
                "ordered_quantity": str(ordered),
                "remaining_quantity": str(Decimal(item["quantity"]) - ordered),
            }
        )
    return {**dict(row), "approval": approval.case_data(approval.find_case(db, "PurchaseRequest", request_id)), "lines": lines}


def validate_lines(db: Session, payload: PurchaseRequestInput) -> None:
    if len({line.material_id for line in payload.lines}) != len(payload.lines):
        raise HTTPException(422, "一张申请不能重复选择同一物料")
    for line in payload.lines:
        if (
            not db.execute(select(literal(1)).select_from(Material).where((Material.id == line.material_id)))
            .mappings()
            .first()
        ):
            raise HTTPException(422, f"物料 #{line.material_id} 不存在")


@router.get("/purchase-requests")
def list_purchase_requests(_: dict = Depends(require("purchase_request.view"))) -> list[dict]:
    with orm_session() as db:
        ids = [
            row
            for row in db.scalars(
                select(PurchaseRequest.id).select_from(PurchaseRequest).order_by(PurchaseRequest.id.desc())
            )
        ]
        return [request_data(db, request_id) for request_id in ids]


def create_purchase_request_in_session(db: Session, payload: PurchaseRequestInput, user: dict) -> dict:
    validate_lines(db, payload)
    cursor = add_model(
        db,
        PurchaseRequest(
            reference=payload.reference.strip(), note=payload.note.strip(), created_by=user["id"]
        ),
    )
    db.add_all(
        [
            PurchaseRequestLine(
                purchase_request_id=cursor.id, material_id=line.material_id, quantity=str(line.quantity)
            )
            for line in payload.lines
        ]
    )
    return request_data(db, cursor.id)


@router.post("/purchase-requests", status_code=201)
def create_purchase_request(payload: PurchaseRequestInput, user: dict = Depends(require("purchase_request.create"))) -> dict:
    with orm_session(write=True) as db:
        return create_purchase_request_in_session(db, payload, user)


@router.put("/purchase-requests/{request_id}")
def update_purchase_request(
    request_id: int, payload: PurchaseRequestInput, user: dict = Depends(require("purchase_request.create"))
) -> dict:
    with orm_session(write=True) as db:
        protect_request(db, request_id)
        row = (
            db.execute(
                select(PurchaseRequest.status)
                .select_from(PurchaseRequest)
                .where((PurchaseRequest.id == request_id))
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "采购申请不存在")
        if row["status"] not in ("draft", "rejected"):
            raise HTTPException(409, "只能修改草稿或已驳回的申请")
        # 升级前已部分转单的申请可以审查剩余需求，但不能删除旧订单仍引用的来源行。
        if db.scalar(select(PurchaseOrderRequestLink.purchase_order_line_id)
                .join(PurchaseRequestLine, PurchaseRequestLine.id == PurchaseOrderRequestLink.purchase_request_line_id)
                .where(PurchaseRequestLine.purchase_request_id == request_id).limit(1)) is not None:
            raise HTTPException(409, "申请已有转单记录，不能改写原需求或删除来源行")
        if db.scalar(select(MaintenancePurchaseRequest.id).where(
                MaintenancePurchaseRequest.purchase_request_id == request_id)):
            raise HTTPException(409, "维护工单来源采购申请不能直接修订，请取消后从工单重新创建")
        approval.record_author(db, "PurchaseRequest", request_id, user["id"])
        validate_lines(db, payload)
        db.execute(delete(PurchaseRequestLine).where((PurchaseRequestLine.purchase_request_id == request_id)))
        db.add_all(
            [
                PurchaseRequestLine(
                    purchase_request_id=request_id, material_id=line.material_id, quantity=str(line.quantity)
                )
                for line in payload.lines
            ]
        )
        db.execute(
            update(PurchaseRequest)
            .where((PurchaseRequest.id == request_id))
            .values(
                reference=payload.reference.strip(),
                note=payload.note.strip(),
                status="draft",
                submitted_by=None,
                submitted_at=None,
                reviewed_by=None,
                reviewed_at=None,
                review_reason="",
            )
        )
        return request_data(db, request_id)


# 旧入口没有审批版本，不能保证步骤、自审或并发边界，保留权限校验后明确拒绝。
@router.post("/purchase-requests/{request_id}/submit")
def submit_purchase_request(request_id: int, _: dict = Depends(require("purchase_request.submit"))) -> dict:
    raise HTTPException(409, "请使用带版本的单据审批入口送审")


@router.post("/purchase-requests/{request_id}/approve")
def approve_purchase_request(request_id: int, _: dict = Depends(require("purchase_request.review"))) -> dict:
    raise HTTPException(409, "请使用带版本的单据审批入口批准")


@router.post("/purchase-requests/{request_id}/reject")
def reject_purchase_request(request_id: int, payload: ReviewReasonInput,
                            _: dict = Depends(require("purchase_request.review"))) -> dict:
    raise HTTPException(409, "请使用带版本的单据审批入口驳回")


@router.post("/purchase-requests/{request_id}/cancel")
def cancel_purchase_request(
    request_id: int, user: dict = Depends(require("purchase_request.cancel"))
) -> dict:
    with orm_session(write=True) as db:
        pending = approval.find_case(db, 'PurchaseRequest', request_id)
        if pending and pending.status in ('submitted', 'approved'):
            raise HTTPException(409, '请先撤回审批再取消申请')
        row = (
            db.execute(
                select(PurchaseRequest.status)
                .select_from(PurchaseRequest)
                .where((PurchaseRequest.id == request_id))
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "采购申请不存在")
        if row["status"] == "cancelled":
            raise HTTPException(409, "采购申请已取消")
        if (
            db.execute(
                select(literal(1))
                .select_from(PurchaseOrderRequestLink)
                .join(
                    PurchaseOrderLine,
                    (PurchaseOrderLine.id == PurchaseOrderRequestLink.purchase_order_line_id),
                )
                .join(PurchaseOrder, (PurchaseOrder.id == PurchaseOrderLine.purchase_order_id))
                .join(
                    PurchaseRequestLine,
                    (PurchaseRequestLine.id == PurchaseOrderRequestLink.purchase_request_line_id),
                )
                .where(
                    PurchaseRequestLine.purchase_request_id == request_id, PurchaseOrder.status != "cancelled"
                )
                .limit(1)
            )
            .mappings()
            .first()
        ):
            raise HTTPException(409, "申请已被有效采购订单使用，不能取消")
        db.execute(
            update(PurchaseRequest)
            .where((PurchaseRequest.id == request_id))
            .values(status="cancelled", cancelled_by=user["id"], cancelled_at=func.current_timestamp())
        )
        return request_data(db, request_id)
