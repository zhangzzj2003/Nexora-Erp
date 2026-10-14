"""生产物料输入边界；数量使用十进制并显式禁止未知字段。"""
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class FlowInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class QuantityInput(FlowInput):
    quantity: Decimal

    @field_validator('quantity')
    @classmethod
    def quantity_value(cls, value):
        if not value.is_finite() or value <= 0 or value > 1_000_000 or value.as_tuple().exponent < -3:
            raise ValueError('数量须大于零、最多三位小数且不超过一百万')
        return value


class FlowLineInput(QuantityInput):
    work_order_line_id: int = Field(gt=0, strict=True)
    source_receipt_line_id: int | None = Field(default=None, gt=0, strict=True)
    legacy_issue_line_id: int | None = Field(default=None, gt=0, strict=True)
    exchange_line_id: int | None = Field(default=None, gt=0, strict=True)
    disposal: Literal['physical','loss'] = 'physical'
    evidence: str = Field(default='', max_length=500)


class FlowCreateInput(FlowInput):
    request_id: str = Field(min_length=8, max_length=100)
    work_order_id: int = Field(gt=0, strict=True)
    warehouse_id: int = Field(gt=0, strict=True)
    reference: str = Field(default='', max_length=100)
    reason: str = Field(default='', max_length=200)
    note: str = Field(default='', max_length=500)
    lines: list[FlowLineInput] = Field(min_length=1, max_length=100)


class FlowUpdateInput(FlowCreateInput):
    version: int = Field(ge=1, strict=True)


class FlowActionInput(FlowInput):
    request_id: str = Field(min_length=8, max_length=100)
    version: int = Field(ge=1, strict=True)
    reason: str = Field(default='', max_length=200)


class FlowLotInput(QuantityInput):
    lot_id: int = Field(gt=0, strict=True)


class FlowExecuteLineInput(QuantityInput):
    line_id: int = Field(gt=0, strict=True)
    lots: list[FlowLotInput] = Field(default_factory=list,max_length=100)


class FlowExecuteInput(FlowActionInput):
    lines: list[FlowExecuteLineInput] = Field(min_length=1,max_length=100)
