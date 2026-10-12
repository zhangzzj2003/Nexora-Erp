"""采购行计价：金额输入保留原值，反算单价仅用于展示与单位成本。"""
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


def valid_quantity(value: Decimal) -> Decimal:
    if not value.is_finite() or value <= 0 or value > 1_000_000 or value.as_tuple().exponent < -3:
        raise ValueError('数量须大于零、最多三位小数且不超过一百万')
    return value


def valid_unit_price(value: Decimal) -> Decimal:
    if not value.is_finite() or value < 0 or value > 10**9 or value.as_tuple().exponent < -4:
        raise ValueError('单价须非负、最多四位小数且不超过十亿')
    return value


class UnitPriceLineInput(BaseModel):
    # 销售订单及报价仍复用原四位单价规则，不跟随采购扩展为双向计价。
    material_id: int = Field(gt=0)
    quantity: Decimal
    unit_price: Decimal
    valid_quantity = field_validator('quantity')(valid_quantity)
    valid_unit_price = field_validator('unit_price')(valid_unit_price)


class PurchasePricingInput(BaseModel):
    quantity: Decimal
    pricing_mode: Literal['unit_price', 'total'] = 'unit_price'
    unit_price: Decimal | None = None
    line_total: Decimal | None = None

    @model_validator(mode='after')
    def calculate_price(self):
        # 先校验数量，再进行除法；非有限值、零和过多小数都不能进入计算。
        quantity = self.quantity
        valid_quantity(quantity)
        if self.pricing_mode == 'total':
            total = self.line_total
            if total is None or not total.is_finite() or total < 0 or total > 10**15 or total.as_tuple().exponent < -2:
                raise ValueError('总价须非负、最多两位小数且不超过一千万亿元')
            if total > quantity * Decimal(10**9):
                raise ValueError('反算单价不能超过十亿元')
            self.line_total = total.quantize(Decimal('.01'))
            self.unit_price = (total / quantity).quantize(Decimal('.000000000001'), rounding=ROUND_HALF_UP)
        elif self.unit_price is not None:
            price = self.unit_price
            valid_unit_price(price)
            self.line_total = (quantity * price).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
        elif self.line_total is not None:
            raise ValueError('价格依据不完整，请重新填写单价或总价')
        return self


def pricing_values(line: PurchasePricingInput) -> dict:
    # 申请允许暂不定价；历史申请不补造零价，总价模式保存原始金额依据。
    return {'pricing_mode': line.pricing_mode,
            'unit_price': str(line.unit_price) if line.unit_price is not None else None,
            'line_total': str(line.line_total) if line.line_total is not None else None}


def purchase_amount(quantity: str, unit_price: str, order_quantity: str | None = None,
                    order_total: str | None = None, pricing_mode: str | None = None) -> Decimal:
    # 应付与退货按原始总价比例计价，避免 0.01 / 3 的近似单价破坏半分舍入。
    value = Decimal(quantity) * Decimal(unit_price)
    if pricing_mode == 'total' and order_total is not None and order_quantity is not None:
        value = Decimal(quantity) * Decimal(order_total) / Decimal(order_quantity)
    return value.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
