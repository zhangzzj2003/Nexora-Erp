"""已结算工单须先冲销结算，再修改其成本或完工来源。"""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.models import ProductionCostSettlement, ProductionSettlementReversal
from app.core.orm import model_data


def active_settlement(db: Session, order_id: int) -> dict | None:
    row = db.scalar(
        select(ProductionCostSettlement)
        .where(
            ProductionCostSettlement.work_order_id == order_id,
            ProductionCostSettlement.status == 'active',
            ~select(ProductionSettlementReversal.id)
            .where(ProductionSettlementReversal.settlement_id == ProductionCostSettlement.id)
            .exists(),
        )
        .order_by(ProductionCostSettlement.id.desc())
        .limit(1)
    )
    return model_data(row) if row is not None else None


def ensure_unsettled(db: Session, order_id: int) -> None:
    if active_settlement(db, order_id) is not None:
        raise HTTPException(409, "工单成本已结算，须先冲销成本结算再更正")
