"""不合格品按实际报工比例分担成本，报废和返工各有独立成本去向。"""
from decimal import Decimal, ROUND_HALF_UP
from fastapi import HTTPException
from sqlalchemy import select
from app.core.models import (ProductionCompletion, ProductionCompletionReversal, QualityDisposition,
    ProductionQualityCost, ProductionSettlementReversal)


def quality_allocations(db,order_id,total):
    completions=list(db.scalars(select(ProductionCompletion).where(ProductionCompletion.work_order_id==order_id,
        ProductionCompletion.status=='posted',~select(ProductionCompletionReversal.id).where(
            ProductionCompletionReversal.production_completion_id==ProductionCompletion.id).exists())))
    reported=sum((Decimal(row.reported_quantity) for row in completions),Decimal(0))
    dispositions=[]
    for row in completions:
        items=list(db.scalars(select(QualityDisposition).where(QualityDisposition.completion_id==row.id)))
        if sum((Decimal(item.quantity) for item in items),Decimal(0))!=Decimal(row.rejected_quantity):
            raise HTTPException(409,'须先完成全部不合格品的报废或返工处置，才能结算成本')
        dispositions.extend(items)
    amounts=[];quantity=Decimal(0);allocated=Decimal(0)
    for item in sorted(dispositions,key=lambda item:item.id):
        quantity+=Decimal(item.quantity)
        cumulative=(total*quantity/reported).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)
        amounts.append((item,cumulative-allocated));allocated=cumulative
    return amounts, total-allocated


def carried_cost(db,order_id):
    items=list(db.scalars(select(QualityDisposition).where(QualityDisposition.rework_order_id==order_id)))
    amount=Decimal(0);parents=[]
    for item in items:
        row=db.scalar(select(ProductionQualityCost).where(ProductionQualityCost.disposition_id==item.id,
            ~select(ProductionSettlementReversal.id).where(ProductionSettlementReversal.settlement_id==ProductionQualityCost.settlement_id).exists()))
        if row is None:return None,[]
        amount+=Decimal(row.amount);parents.append(row.settlement_id)
    return amount,parents
