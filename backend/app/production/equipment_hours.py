"""设备运行小时读数与按表计阈值触发的保养计划。"""

import json
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.access.security import require
from app.core.models import (EquipmentAsset, EquipmentMeterReading, MaintenanceHourPlan,
                             MaintenanceHourPlanChange,
                             MaintenancePlan, User)
from app.core.orm import add_model, model_data, orm_session
from app.production.equipment_rules import active_jobs, encoded, get, permission, version

router = APIRouter(prefix='/api/v1/equipment')
HUNDREDTH = Decimal('0.01')


def hours_text(value: Decimal) -> str:
    return str(value.quantize(HUNDREDTH))


def latest_reading(db, equipment_id: int) -> EquipmentMeterReading | None:
    return db.scalar(select(EquipmentMeterReading).where(EquipmentMeterReading.equipment_id == equipment_id)
                     .order_by(EquipmentMeterReading.id.desc()).limit(1))


def reading_data(db, row: EquipmentMeterReading) -> dict:
    return {**model_data(row), 'correction': bool(row.correction),
            'recorded_by_name': get(db, User, row.recorded_by, '登记人').username}


def hour_plan_data(db, row: MaintenanceHourPlan, user: dict, detail: bool = False) -> dict:
    reading = latest_reading(db, row.equipment_id)
    result = model_data(row)
    result['enabled'] = bool(row.enabled)
    result['current_hours'] = reading.hours if reading else None
    result['current_reading_id'] = reading.id if reading else None
    result['due'] = bool(row.enabled and reading and Decimal(reading.hours) >= Decimal(row.next_due_hours))
    result['open_job_ids'] = [job.id for job in active_jobs(db, hour_plan_id=row.id)]
    result['changes'] = hour_plan_changes(db, row.id) if detail else []
    return result


def hour_plan_changes(db, plan_id: int) -> list[dict]:
    return [dict(id=change.id, action=change.action, reason=change.reason,
        evidence=change.evidence, changed_by=change.changed_by, changed_by_name=user_name,
        created_at=change.created_at,
        before=json.loads(change.before_json) if change.before_json else None,
        after=json.loads(change.after_json)) for change, user_name in db.execute(
        select(MaintenanceHourPlanChange, User.username)
        .join(User, User.id == MaintenanceHourPlanChange.changed_by)
        .where(MaintenanceHourPlanChange.plan_id == plan_id)
        .order_by(MaintenanceHourPlanChange.id))]


def audit_hour_plan(db, row: MaintenanceHourPlan, action: str, before: dict | None,
                    user: dict, reason: str, evidence: str = '') -> None:
    db.flush()
    db.add(MaintenanceHourPlanChange(plan_id=row.id, action=action,
        before_json=encoded(before) if before else None, after_json=encoded(model_data(row)),
        reason=reason, evidence=evidence, changed_by=user['id']))
    db.flush()


class HoursInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    equipment_id: int = Field(gt=0, strict=True)
    hours: Decimal
    reference: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=200)
    previous_reading_id: int | None = Field(default=None, gt=0, strict=True)
    correction: bool = Field(default=False, strict=True)

    @field_validator('hours', mode='before')
    @classmethod
    def reject_float(cls, value):
        if isinstance(value, (float, bool)):
            raise ValueError('运行小时请使用十进制文本')
        return value

    @field_validator('hours')
    @classmethod
    def valid_hours(cls, value):
        if not value.is_finite() or value < 0 or value > 1_000_000_000 or value.as_tuple().exponent < -2:
            raise ValueError('运行小时须非负、最多两位小数且不超过十亿')
        return value


class HourPlanInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    equipment_id: int = Field(gt=0, strict=True)
    reference: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=120)
    interval_hours: Decimal
    next_due_hours: Decimal
    enabled: bool = Field(default=True, strict=True)
    reason: str = Field(min_length=1, max_length=200)

    @field_validator('interval_hours', 'next_due_hours', mode='before')
    @classmethod
    def reject_float(cls, value):
        if isinstance(value, (float, bool)):
            raise ValueError('运行小时请使用十进制文本')
        return value

    @field_validator('interval_hours', 'next_due_hours')
    @classmethod
    def valid_hours(cls, value, info):
        lower = 0 if info.field_name == 'next_due_hours' else Decimal('0.01')
        upper = 1_000_000_000 if info.field_name == 'next_due_hours' else 1_000_000
        if not value.is_finite() or value < lower or value > upper or value.as_tuple().exponent < -2:
            raise ValueError('保养小时阈值须在允许范围内，最多两位小数')
        return value


class HourPlanEdit(HourPlanInput):
    version: int = Field(gt=0, strict=True)


@router.get('/meter-readings')
def list_meter_readings(equipment_id: int = Query(gt=0),
                        user: dict = Depends(require('equipment.view'))) -> list[dict]:
    with orm_session() as db:
        get(db, EquipmentAsset, equipment_id, '设备')
        return [reading_data(db, row) for row in db.scalars(select(EquipmentMeterReading)
            .where(EquipmentMeterReading.equipment_id == equipment_id)
            .order_by(EquipmentMeterReading.id.desc()))]


@router.post('/meter-readings', status_code=201)
def record_meter_reading(payload: HoursInput, user: dict = Depends(require('equipment.meter'))) -> dict:
    permission(user, 'equipment.view')
    with orm_session(write=True) as db:
        equipment = get(db, EquipmentAsset, payload.equipment_id, '设备')
        if equipment.status != 'active':
            raise HTTPException(409, '只能登记启用设备的运行小时')
        latest = latest_reading(db, equipment.id)
        if payload.previous_reading_id != (latest.id if latest else None):
            raise HTTPException(409, '设备读数已变化，请读取最新记录后重试')
        if payload.correction:
            permission(user, 'equipment.manage')
        elif latest and payload.hours < Decimal(latest.hours):
            raise HTTPException(409, '运行小时不能倒退；错误读数须由资料管理员登记更正')
        row = EquipmentMeterReading(equipment_id=equipment.id, hours=hours_text(payload.hours),
            reference=payload.reference, reason=payload.reason,
            previous_reading_id=latest.id if latest else None, correction=int(payload.correction),
            recorded_by=user['id'])
        try:
            add_model(db, row)
        except IntegrityError:
            raise HTTPException(409, '此设备读数依据编号已使用') from None
        return reading_data(db, row)


@router.get('/hour-plans/{identifier}')
def hour_plan_detail(identifier: int, user: dict = Depends(require('equipment.view'))) -> dict:
    with orm_session() as db:
        return hour_plan_data(db, get(db, MaintenanceHourPlan, identifier, '运行小时计划'), user, True)


def save_hour_plan(db, payload: HourPlanInput, user: dict, row: MaintenanceHourPlan | None = None) -> dict:
    permission(user, 'equipment.view')
    equipment = get(db, EquipmentAsset, payload.equipment_id, '设备')
    if payload.enabled and equipment.status != 'active':
        raise HTTPException(409, '只有启用设备可以启用运行小时计划')
    if latest_reading(db, equipment.id) is None:
        raise HTTPException(409, '先登记设备运行小时基线，再建立保养计划')
    if row:
        version(row, payload.version)
        if active_jobs(db, hour_plan_id=row.id):
            raise HTTPException(409, '计划已有未结束工单，先结束或取消后再修订')
    if db.scalar(select(MaintenancePlan.id).where(MaintenancePlan.reference == payload.reference).limit(1)):
        raise HTTPException(409, '计划编号已用于日历维护计划')
    if db.scalar(select(MaintenanceHourPlan.id).where(
            MaintenanceHourPlan.reference == payload.reference,
            MaintenanceHourPlan.id != row.id if row else MaintenanceHourPlan.id > 0).limit(1)):
        raise HTTPException(409, '运行小时计划编号已存在')
    values = payload.model_dump(exclude={'reason', 'version'})
    values['interval_hours'] = hours_text(payload.interval_hours)
    values['next_due_hours'] = hours_text(payload.next_due_hours)
    values['enabled'] = int(payload.enabled)
    before = model_data(row) if row else None
    if row is None:
        row = add_model(db, MaintenanceHourPlan(**values, version=1, created_by=user['id']))
    else:
        for field, value in values.items():
            setattr(row, field, value)
        row.version += 1
    audit_hour_plan(db, row, 'edit' if before else 'create', before, user, payload.reason)
    return hour_plan_data(db, row, user, True)


@router.post('/hour-plans', status_code=201)
def create_hour_plan(payload: HourPlanInput, user: dict = Depends(require('equipment.manage'))) -> dict:
    with orm_session(write=True) as db:
        return save_hour_plan(db, payload, user)


@router.put('/hour-plans/{identifier}')
def edit_hour_plan(identifier: int, payload: HourPlanEdit,
                   user: dict = Depends(require('equipment.manage'))) -> dict:
    with orm_session(write=True) as db:
        return save_hour_plan(db, payload, user, get(db, MaintenanceHourPlan, identifier, '运行小时计划'))
