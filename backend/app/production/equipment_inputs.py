"""设备维护边界输入；数量和声明费用使用 Decimal，不接受浮点隐式补齐。"""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    reason: str = Field(min_length=1, max_length=200)


class EquipmentInput(Input):
    code: str = Field(min_length=1, max_length=40, pattern=r'^[A-Za-z0-9_-]+$')
    name: str = Field(min_length=1, max_length=100)
    serial_number: str = Field(default='', max_length=80)
    location: str = Field(min_length=1, max_length=120)
    status: Literal['active','inactive','retired'] = 'active'

    @field_validator('code')
    @classmethod
    def normalize(cls, value):
        return value.upper()


class EquipmentEdit(EquipmentInput):
    version: int = Field(gt=0, strict=True)


class PlanInput(Input):
    equipment_id: int = Field(gt=0, strict=True)
    reference: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=120)
    interval_days: int = Field(ge=1, le=3650, strict=True)
    next_due: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    enabled: bool = Field(default=True, strict=True)

    @field_validator('next_due')
    @classmethod
    def valid_date(cls, value):
        if not 2000 <= date.fromisoformat(value).year <= 2099:
            raise ValueError('计划日期须在 2000 至 2099 年之间')
        return value


class PlanEdit(PlanInput):
    version: int = Field(gt=0, strict=True)


class Part(BaseModel):
    model_config = ConfigDict(extra='forbid')
    material_id: int = Field(gt=0, strict=True)
    quantity: Decimal

    @field_validator('quantity', mode='before')
    @classmethod
    def no_float(cls, value):
        if isinstance(value, (float, bool)):
            raise ValueError('数量请使用十进制文本')
        return value

    @field_validator('quantity')
    @classmethod
    def precision(cls, value):
        if not value.is_finite() or value <= 0 or value > 1_000_000 or value.as_tuple().exponent < -3:
            raise ValueError('耗材数量须大于零、最多三位小数且不超过一百万')
        return value


class JobInput(Input):
    reference: str = Field(min_length=1, max_length=100)
    equipment_id: int = Field(gt=0, strict=True)
    kind: Literal['preventive','corrective']
    plan_id: int | None = Field(default=None, gt=0, strict=True)
    hour_plan_id: int | None = Field(default=None, gt=0, strict=True)
    work_order_id: int | None = Field(default=None, gt=0, strict=True)
    assigned_to: int = Field(gt=0, strict=True)
    request_note: str = Field(min_length=1, max_length=600)
    warehouse_id: int | None = Field(default=None, gt=0, strict=True)
    parts: list[Part] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def links(self):
        if (self.kind == 'preventive') != ((self.plan_id is not None) != (self.hour_plan_id is not None)):
            raise ValueError('周期维护须且只能关联一种计划，故障维护不能关联计划')
        if bool(self.parts) != (self.warehouse_id is not None):
            raise ValueError('耗材须指定仓库，无耗材不能指定仓库')
        if len({part.material_id for part in self.parts}) != len(self.parts):
            raise ValueError('耗材物料不能重复')
        return self


class JobEdit(JobInput):
    version: int = Field(gt=0, strict=True)


class ActionInput(Input):
    version: int = Field(gt=0, strict=True)
    evidence: str = Field(min_length=1, max_length=600)
    solution: str | None = Field(default=None, min_length=1, max_length=600)
    labor_hours: Decimal | None = None
    service_amount: Decimal | None = None

    @field_validator('labor_hours', 'service_amount', mode='before')
    @classmethod
    def no_float(cls, value):
        if isinstance(value, (float, bool)):
            raise ValueError('工时和声明费用请使用十进制文本')
        return value

    @field_validator('labor_hours', 'service_amount')
    @classmethod
    def precision(cls, value, info):
        limit = 100_000 if info.field_name == 'labor_hours' else 1_000_000_000
        if value is not None and (not value.is_finite() or value < 0 or value > limit or value.as_tuple().exponent < -2):
            raise ValueError('工时及声明费用须非负且最多两位小数')
        return value


JobAction = Literal['submit','approve','reject','start','report','rework','accept','cancel','reverse']
