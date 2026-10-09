"""已结期间的成本来源锁定，跨模块共用同一写事务。"""

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.models import (
    AccountingPeriod, InventoryCostInput, PaymentRecord, OrderSettlementTransfer, SubledgerSettlement, ProductionCostEntry,
    ProductionCostReversal, ProductionCostSettlement, ProductionSettlementReversal,
    StockMovement, SubledgerPayment, QualityDispositionChange, AfterSalesChange, AfterSalesCustody,
    AfterSalesLabor, AfterSalesLaborCost, AfterSalesResponsibility, SubledgerAttachment, SubledgerAttachmentReversal,
)


def closed_through(db: Session) -> str | None:
    return db.scalar(select(func.max(AccountingPeriod.end_date)).where(AccountingPeriod.status == 'closed'))


def ensure_date_unlocked(db: Session, value: str) -> None:
    boundary = closed_through(db)
    # 空档和首次期间之前的来源也会进入后续余额，不能从空档绕过锁期。
    if boundary is not None and value[:10] <= boundary:
        raise HTTPException(409, f'成本来源已锁定至 {boundary}，须先按倒序重开相关会计期间')


def ensure_movement_unlocked(db: Session, movement_id: int) -> None:
    movement = db.get(StockMovement, movement_id)
    if movement is not None:
        ensure_date_unlocked(db, movement.created_at)


def write_boundary(db: Session) -> tuple[str | None, dict]:
    boundary = closed_through(db)
    models = (StockMovement, PaymentRecord, OrderSettlementTransfer, SubledgerSettlement, SubledgerPayment, InventoryCostInput, ProductionCostEntry,
              ProductionCostReversal, ProductionCostSettlement, ProductionSettlementReversal, QualityDispositionChange,
              AfterSalesChange, AfterSalesCustody, AfterSalesLabor, AfterSalesLaborCost, AfterSalesResponsibility,
              SubledgerAttachment, SubledgerAttachmentReversal)
    return boundary, ({model: db.scalar(select(func.max(model.id))) or 0 for model in models}
                      if boundary is not None else {})


def validate_appended_dates(db: Session, boundary: str | None, heads: dict) -> None:
    if boundary is None:
        return
    # 所有这些业务接口用服务端 UTC 时间追加记录；时钟回退也不能写入锁期。
    for model, head in heads.items():
        timestamp = func.coalesce(model.executed_at, model.created_at) if model in (PaymentRecord, SubledgerPayment, OrderSettlementTransfer, SubledgerSettlement, ProductionCostSettlement) else model.created_at
        query = select(model.id).where(model.id > head, timestamp < boundary + ' 24:00:00')
        if model in (PaymentRecord, SubledgerPayment, OrderSettlementTransfer, SubledgerSettlement):
            # 待审草稿不属于资金事实；执行已有草稿的日期另在执行事务内核对。
            query = query.where(model.status == 'executed')
        if model is ProductionCostSettlement:
            query = query.where(model.status == 'active')
        if db.scalar(query.limit(1)) is not None:
            raise HTTPException(409, f'业务记录时间落入已结期间（锁定至 {boundary}），本次操作已回滚')
