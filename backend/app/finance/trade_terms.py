"""折扣先抵减报价，再按明确的含税口径换算结算单价。"""
from decimal import Decimal, ROUND_HALF_UP
from app.core.models import TradeLineTerms


def settlement_price(line) -> str:
    if line.tax_rate == 0 and line.discount_rate == 0: return str(line.unit_price)
    price = line.unit_price * (Decimal(1) - line.discount_rate / 100)
    if not line.includes_tax:
        price *= Decimal(1) + line.tax_rate / 100
    # 业务单据统一保存四位含税结算单价，分批出入库和退货沿用同一价格。
    return str(price.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP))


def save_terms(db, kind, line_id, line):
    db.add(TradeLineTerms(kind=kind,line_id=line_id,quoted_price=str(line.unit_price),
        tax_rate=str(line.tax_rate),discount_rate=str(line.discount_rate),includes_tax=int(line.includes_tax)))


def terms_data(db, kind, line_id):
    row=db.get(TradeLineTerms,(kind,line_id))
    return {'quoted_price':row.quoted_price,'tax_rate':row.tax_rate,'discount_rate':row.discount_rate,'includes_tax':bool(row.includes_tax)} if row else {}
