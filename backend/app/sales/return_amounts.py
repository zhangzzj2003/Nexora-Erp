"""销售退货按原出库明细分摊分位尾差，确认后固定金额以保留历史凭证。"""

from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import SalesOrderLine, SalesReturn, SalesReturnLine, SalesReturnReversal, ShipmentLine


def return_amount(quantity: str, unit_price: str, settlement_amount: str | None = None) -> Decimal:
    # 未升级的已确认单据没有固定金额，必须保持旧口径，不能改写已过账来源。
    if settlement_amount is not None:
        return Decimal(settlement_amount)
    return (Decimal(quantity) * Decimal(unit_price)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def allocate_return_amount(shipped: Decimal, returned: Decimal, quantity: Decimal,
                           unit_price: Decimal, previous_amount: Decimal) -> Decimal:
    source_amount = return_amount(str(shipped), str(unit_price))
    remaining_amount = source_amount - previous_amount
    if remaining_amount < 0:
        raise HTTPException(409, '历史退货金额已超过原出库金额，请先核对并冲销有误的退货单')
    if returned + quantity > shipped or quantity <= 0:
        raise HTTPException(409, '原出库明细剩余可退数量不足')
    # 先累计数量再取分位，避免每次各自四舍五入；全部退完时恰好冲减原出库金额。
    target = return_amount(str(returned + quantity), str(unit_price))
    # 旧单或部分冲销可能留下分位偏差，限于剩余金额内分摊，不能生成负向退款。
    return min(remaining_amount, max(Decimal('0.00'), target - previous_amount))


def settlement_for_return(db: Session, shipment_line_id: int, quantity: Decimal) -> str:
    source = db.execute(select(ShipmentLine.quantity, SalesOrderLine.unit_price)
        .join(SalesOrderLine, SalesOrderLine.id == ShipmentLine.sales_order_line_id)
        .where(ShipmentLine.id == shipment_line_id)).one()
    previous_quantity = Decimal(0)
    previous_amount = Decimal(0)
    # 只扣除当前有效退货；被冲销单的原固定金额仍留在历史来源中供冲销精确还原。
    for line in db.scalars(select(SalesReturnLine)
            .join(SalesReturn, SalesReturn.id == SalesReturnLine.sales_return_id)
            .outerjoin(SalesReturnReversal, SalesReturnReversal.sales_return_id == SalesReturn.id)
            .where(SalesReturnLine.shipment_line_id == shipment_line_id,
                   SalesReturn.status == 'posted', SalesReturnReversal.id.is_(None))):
        previous_quantity += Decimal(line.quantity)
        previous_amount += return_amount(line.quantity, source.unit_price, line.settlement_amount)
    return str(allocate_return_amount(Decimal(source.quantity), previous_quantity, quantity,
                                      Decimal(source.unit_price), previous_amount))
