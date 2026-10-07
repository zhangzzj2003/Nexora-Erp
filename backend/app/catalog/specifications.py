"""按模板核验规格，以十进制文本保存数值，并保留原字段含义。"""

import json
import re
from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from app.core.models import Material, MaterialCategory, MaterialSpecField
from app.catalog.categories import category_directory


class SpecValueInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    field_id: int = Field(ge=1)
    status: Literal['filled', 'unknown', 'not_applicable', 'pending'] = 'unknown'
    value: str | bool | None = None
    source: str = Field(default='', max_length=500)

    @field_validator('value')
    @classmethod
    def value_length(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if len(value) > 500:
                raise ValueError('规格值最多 500 字')
        return value


class ExtraAttributeInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    name: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=500)
    unit: str = Field(default='', max_length=20)

    @field_validator('*')
    @classmethod
    def trim_text(cls, value: str) -> str:
        return value.strip()


def normalize_value(field: MaterialSpecField, entry: SpecValueInput, old: dict | None) -> str | bool | None:
    if entry.status != 'filled':
        if entry.value not in (None, ''):
            raise HTTPException(422, f'{field.name}未填写时不能同时提交数值')
        return None
    value = entry.value
    if field.kind == 'boolean':
        if not isinstance(value, bool):
            raise HTTPException(422, f'{field.name}请选择是或否')
        return value
    if not isinstance(value, str) or not value:
        raise HTTPException(422, f'请填写{field.name}')
    if field.kind == 'number':
        # 不经过二进制浮点，严格限制精度和长度，拒绝 NaN、无穷及含单位的文字。
        if not re.fullmatch(r'[+-]?\d{1,24}(?:\.\d{1,12})?', value):
            raise HTTPException(422, f'{field.name}应填写数值（最多 24 位整数、12 位小数），单位为{field.unit or "无"}')
        return format(Decimal(value), 'f').rstrip('0').rstrip('.') if '.' in value else str(Decimal(value))
    if field.kind == 'date':
        try:
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
                raise ValueError()
            date.fromisoformat(value)
        except ValueError:
            raise HTTPException(422, f'{field.name}应为有效日期 YYYY-MM-DD') from None
    if field.kind == 'enum' and not field.allow_custom and value not in json.loads(field.options_json):
        # 常用选项调整后允许沿用原值，不把旧档案的确认参数变成非法新值。
        if old is None or old['value'] != value or old['status'] != entry.status:
            raise HTTPException(422, f'{field.name}请选择模板允许的选项')
    return value


def save_specifications(db: Session, material: Material, values: list[SpecValueInput] | None,
                        template_version: int | None, extras: list[ExtraAttributeInput] | None,
                        *, validate_required: bool) -> None:
    if extras is not None:
        if any(not entry.name or not entry.value for entry in extras) or len({entry.name for entry in extras}) != len(extras):
            raise HTTPException(422, '扩展属性名称和值不能为空，名称不能重复')
        material.extra_attributes_json = json.dumps([entry.model_dump() for entry in extras], ensure_ascii=False)
    if values is None and not validate_required:
        return
    category = db.get(MaterialCategory, material.category_code) if material.category_code else None
    if values is not None and (category is None or template_version != category.template_version):
        raise HTTPException(409, '规格模板已更新，请刷新后核对并保留当前输入')
    old_values = json.loads(material.spec_values_json or '[]')
    old_by_id = {entry['field_id']: entry for entry in old_values}
    fields = list(db.scalars(select(MaterialSpecField).where(MaterialSpecField.category_code == material.category_code,
        MaterialSpecField.enabled == True, MaterialSpecField.deleted == False)))
    by_id = {field.id: field for field in fields}
    submitted = {entry.field_id: entry for entry in values or []}
    if len(submitted) != len(values or []) or any(field_id not in by_id for field_id in submitted):
        raise HTTPException(422, '规格字段重复、已停用或不属于当前子类')
    result = []
    for field in fields:
        entry = submitted.get(field.id)
        if field.required and (entry is None or entry.status != 'filled'):
            raise HTTPException(422, f'{field.name}是必填规格，请核对模板')
        if entry is None:
            continue
        value = normalize_value(field, entry, old_by_id.get(field.id))
        field.used = True
        result.append({**entry.model_dump(), 'value': value, 'category_code': material.category_code,
                       'name': field.name, 'kind': field.kind, 'unit': field.unit})
    if values is not None:
        # 不覆盖其他类别与停用字段的快照；它们在资料卡显示为历史参数。
        combined = [entry for entry in old_values if entry['field_id'] not in by_id] + result
        if len(combined) > 500:
            raise HTTPException(409, '该物料保留的历史规格已达 500 项，请先核对类别使用情况')
        material.spec_values_json = json.dumps(combined, ensure_ascii=False)
        material.spec_template_version = category.template_version


STATUS_LABELS = {'unknown': '未知', 'not_applicable': '不适用', 'pending': '待确认'}


def specification_data(material: Material) -> dict:
    values = json.loads(material.spec_values_json or '[]')
    extras = json.loads(material.extra_attributes_json or '[]')
    db = object_session(material)
    directory = category_directory(db) if db is not None else {}
    fields = {field['id']: field for category in directory.values() for field in category['fields']}
    displayed = []
    summary = []
    for entry in values:
        current = fields.get(entry['field_id'])
        value = {**entry, 'name': current['name'] if current else entry['name'],
                 'historical': entry['category_code'] != material.category_code or not current or not current['enabled']}
        displayed.append(value)
        if not value['historical']:
            text = ('是' if value['value'] else '否') if isinstance(value['value'], bool) else str(value['value'] or '')
            summary.append(f"{value['name']}：{text + value['unit'] if value['status'] == 'filled' else STATUS_LABELS[value['status']]}")
    result = {}
    # 新属性为增量契约，未补齐的历史物料仍返回旧字段，不造空参数。
    if values or material.spec_template_version:
        result.update(spec_values=displayed, spec_summary='；'.join(summary), spec_template_version=material.spec_template_version)
    if extras:
        result['extra_attributes'] = extras
    return result
