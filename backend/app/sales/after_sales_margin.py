"""售后维修直接毛利的受限只读接口。"""

from fastapi import APIRouter, Depends, HTTPException

from app.access.security import require
from app.core.orm import orm_session
from app.sales.after_sales import get_case, permission
from app.sales.after_sales_rules import repair_margin_data
from app.sales.customer_scope import require_visible_after_sales

router = APIRouter(prefix='/api/v1/after-sales')


@router.get('/cases/{case_id}/repair-margin')
def get_repair_margin(case_id: int, user: dict = Depends(require('after_sales.cost'))):
    permission(user, 'after_sales.view')
    with orm_session() as db:
        row = require_visible_after_sales(db, get_case(db, case_id), user)
        if row.kind != 'repair':
            raise HTTPException(409, '只有维修单可计算维修直接毛利')
        return repair_margin_data(db, row)
