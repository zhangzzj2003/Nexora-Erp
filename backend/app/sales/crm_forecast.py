"""商机概率预测；只汇总当前可见的开放商机，不产生财务发生额。"""

from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.access.security import require
from app.core.models import CrmOpportunity, Customer, User
from app.core.orm import orm_session
from app.sales.crm_rules import OPEN_STAGES, today
from app.sales.customer_scope import visible_customers


router = APIRouter(prefix='/api/v1/crm')
CENT = Decimal('0.01')


@router.get('/forecast')
def forecast(user: dict = Depends(require('crm.view'))) -> dict:
    with orm_session() as db:
        query = visible_customers(select(CrmOpportunity).join(
            Customer, Customer.id == CrmOpportunity.customer_id).where(
            CrmOpportunity.stage.in_(OPEN_STAGES)).order_by(
            CrmOpportunity.expected_close_date, CrmOpportunity.id), user)
        rows = list(db.scalars(query))
        rated = []
        unrated_count = 0
        total_estimated = Decimal('0.00')
        total_weighted = Decimal('0.00')
        current_date = today()
        for row in rows:
            if row.probability_percent is None:
                unrated_count += 1
                continue
            estimated = Decimal(row.estimated_amount)
            weighted = (estimated * row.probability_percent / 100).quantize(CENT, rounding=ROUND_HALF_UP)
            total_estimated += estimated
            total_weighted += weighted
            owner = db.get(User, row.owner_id)
            rated.append({'id': row.id, 'customer_id': row.customer_id,
                          'customer_name': db.get(Customer, row.customer_id).name,
                          'title': row.title, 'owner_name': owner.full_name or owner.username,
                          'stage': row.stage, 'expected_close_date': row.expected_close_date,
                          'estimated_amount': str(estimated.quantize(CENT)),
                          'probability_percent': row.probability_percent,
                          'weighted_amount': str(weighted),
                          'overdue': row.expected_close_date < current_date})
        return {'currency': 'CNY', 'rated_count': len(rated),
                'unrated_count': unrated_count,
                'estimated_amount': str(total_estimated.quantize(CENT)),
                'weighted_amount': str(total_weighted.quantize(CENT)), 'rows': rated}
