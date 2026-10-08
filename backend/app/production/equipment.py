"""设备台账、日历维护与可追溯的执行验收，业务读写统一 ORM。"""

from app.core.document_responses import NumberedRoute
from app.core.document_approval import record_author
from app.core import document_approval as approval
from app.core.approval_documents import maintenance_snapshot, document_snapshot
import json
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.access.security import require
from app.catalog.material_rules import material_choice_data
from app.core.models import (EquipmentAsset, EquipmentMeterReading, MaintenancePlan, MaintenanceHourPlan,
    MaintenanceJob, MaintenanceDowntime,
    Material, Warehouse, WorkOrder, WarehouseOutbound, WarehouseOutboundLine)
from app.core.orm import orm_session, add_model, model_data
from app.production.equipment_inputs import (EquipmentInput, EquipmentEdit, PlanInput, PlanEdit,
    JobInput, JobEdit, ActionInput, JobAction)
from app.production.equipment_rules import (now, encoded, permission, get, version, unique, active_jobs,
    audit, independent, executors, validate_job, frozen_links, parts_status, parts_ready,
    changes, downtime_data, job_data, RUNNING, authors)
from app.production.equipment_hours import (latest_reading, reading_data, hour_plan_data,
                                            hours_text, audit_hour_plan)

router = APIRouter(route_class=NumberedRoute, prefix='/api/v1/equipment')


def equipment_data(db, row, user, detail=False):
    result = model_data(row)
    meter = latest_reading(db, row.id)
    result['meter_reading'] = reading_data(db, meter) if meter else None
    result['meter_readings'] = [reading_data(db, item) for item in db.scalars(
        select(EquipmentMeterReading).where(EquipmentMeterReading.equipment_id == row.id)
        .order_by(EquipmentMeterReading.id.desc()))] if detail else []
    result['serial_number'] = row.serial_number or ''
    result['running_job_ids'] = list(db.scalars(select(MaintenanceJob.id).where(
        MaintenanceJob.equipment_id == row.id, MaintenanceJob.status.in_(RUNNING))))
    result['changes'] = changes(db, 'equipment', row.id, user) if detail else []
    result['downtimes'] = [downtime_data(db, entry) for entry in db.scalars(select(MaintenanceDowntime)
        .where(MaintenanceDowntime.equipment_id == row.id).order_by(MaintenanceDowntime.id))] if detail else []
    return result


def plan_data(db, row, user, detail=False):
    result = model_data(row)
    result['enabled'] = bool(row.enabled)
    result['due'] = bool(row.enabled) and row.next_due <= now()[:10]
    result['open_job_ids'] = [entry.id for entry in active_jobs(db, plan_id=row.id)]
    result['changes'] = changes(db, 'plan', row.id, user) if detail else []
    return result


@router.get('/overview')
def overview(user: dict = Depends(require('equipment.view'))):
    with orm_session() as db:
        return {'as_of': now(), 'equipment': [equipment_data(db, row, user) for row in db.scalars(
                select(EquipmentAsset).order_by(EquipmentAsset.id))],
            'plans': [plan_data(db, row, user) for row in db.scalars(select(MaintenancePlan).order_by(MaintenancePlan.id))],
            'hour_plans': [hour_plan_data(db, row, user) for row in db.scalars(
                select(MaintenanceHourPlan).order_by(MaintenanceHourPlan.id))],
            'jobs': [job_data(db, row, user, False) for row in db.scalars(select(MaintenanceJob).order_by(MaintenanceJob.id.desc()))],
            'executors': [{'id': actor.id, 'username': actor.username} for actor in executors(db)],
            'materials': [material_choice_data(row)
                for row in db.scalars(select(Material).order_by(Material.id))],
            'warehouses': [{'id': row.id, 'name': row.name} for row in db.scalars(select(Warehouse).order_by(Warehouse.id))],
            'work_orders': [{'id': row.id, 'status': row.status, 'target_quantity': row.target_quantity}
                for row in db.scalars(select(WorkOrder).where(WorkOrder.status != 'cancelled').order_by(WorkOrder.id))]
                if 'production.view' in user['permissions'] else []}


@router.get('/assets/{identifier}')
def equipment_detail(identifier: int, user: dict = Depends(require('equipment.view'))):
    with orm_session() as db:
        return equipment_data(db, get(db, EquipmentAsset, identifier, '设备'), user, True)


def save_equipment(db, payload, user, row=None):
    permission(user, 'equipment.view')
    if row is not None:
        version(row, payload.version)
        if row.status == 'retired' and payload.status != 'retired':
            raise HTTPException(409, '报废设备不能重新启用，须另建新设备档案')
        if active_jobs(db, equipment_id=row.id) and (row.code != payload.code or row.serial_number != (payload.serial_number or None)):
            raise HTTPException(409, '设备有未结束维护工单，不能改绑设备编号或序列号')
        if payload.status != 'active' and (active_jobs(db, equipment_id=row.id) or db.scalar(
                select(MaintenancePlan.id).where(MaintenancePlan.equipment_id == row.id, MaintenancePlan.enabled == 1))
                or db.scalar(select(MaintenanceHourPlan.id).where(
                    MaintenanceHourPlan.equipment_id == row.id, MaintenanceHourPlan.enabled == 1))):
            raise HTTPException(409, '先结束维护工单并停用周期计划，再停用或报废设备')
    values = payload.model_dump(exclude={'reason','version'})
    values['serial_number'] = payload.serial_number or None
    for field in ('code','serial_number'):
        unique(db, EquipmentAsset, field, values[field], row.id if row else None)
    before = model_data(row) if row else None
    if row is None:
        row = add_model(db, EquipmentAsset(**values, version=1, created_by=user['id']))
    else:
        for field, value in values.items():
            setattr(row, field, value)
        row.version += 1
    audit(db, 'equipment', row, 'edit' if before else 'create', before, user, payload.reason)
    return equipment_data(db, row, user, True)


@router.post('/assets', status_code=201)
def create_equipment(payload: EquipmentInput, user: dict = Depends(require('equipment.manage'))):
    with orm_session(write=True) as db:
        return save_equipment(db, payload, user)


@router.put('/assets/{identifier}')
def edit_equipment(identifier: int, payload: EquipmentEdit, user: dict = Depends(require('equipment.manage'))):
    permission(user, 'equipment.view')
    with orm_session(write=True) as db:
        return save_equipment(db, payload, user, get(db, EquipmentAsset, identifier, '设备'))


@router.get('/plans/{identifier}')
def plan_detail(identifier: int, user: dict = Depends(require('equipment.view'))):
    with orm_session() as db:
        return plan_data(db, get(db, MaintenancePlan, identifier, '维护计划'), user, True)


def save_plan(db, payload, user, row=None):
    permission(user, 'equipment.view')
    equipment = get(db, EquipmentAsset, payload.equipment_id, '设备')
    if payload.enabled and equipment.status != 'active':
        raise HTTPException(409, '只有启用设备可以启用周期计划')
    if row is not None:
        version(row, payload.version)
        if active_jobs(db, plan_id=row.id):
            raise HTTPException(409, '计划已有未结束工单，先取消或验收后再修订计划')
    unique(db, MaintenancePlan, 'reference', payload.reference, row.id if row else None)
    if db.scalar(select(MaintenanceHourPlan.id).where(MaintenanceHourPlan.reference == payload.reference).limit(1)):
        raise HTTPException(409, '计划编号已用于运行小时计划')
    values = payload.model_dump(exclude={'reason','version'})
    values['enabled'] = int(payload.enabled)
    before = model_data(row) if row else None
    if row is None:
        row = add_model(db, MaintenancePlan(**values, version=1, created_by=user['id']))
    else:
        for field, value in values.items():
            setattr(row, field, value)
        row.version += 1
    audit(db, 'plan', row, 'edit' if before else 'create', before, user, payload.reason)
    return plan_data(db, row, user, True)


@router.post('/plans', status_code=201)
def create_plan(payload: PlanInput, user: dict = Depends(require('equipment.manage'))):
    with orm_session(write=True) as db:
        return save_plan(db, payload, user)


@router.put('/plans/{identifier}')
def edit_plan(identifier: int, payload: PlanEdit, user: dict = Depends(require('equipment.manage'))):
    permission(user, 'equipment.view')
    with orm_session(write=True) as db:
        return save_plan(db, payload, user, get(db, MaintenancePlan, identifier, '维护计划'))


@router.get('/jobs/{identifier}')
def job_detail(identifier: int, user: dict = Depends(require('equipment.view'))):
    with orm_session() as db:
        return job_data(db, get(db, MaintenanceJob, identifier, '维护工单'), user)


def save_job(db, payload, user, row=None):
    permission(user, 'equipment.view')
    if row is not None:
        version(row, payload.version)
        if row.status not in ('draft','rejected'):
            raise HTTPException(409, '只能修订草稿或驳回的维护工单')
        if row.work_order_id is not None:
            permission(user, 'production.view')
    equipment, plan, hour_plan, order = validate_job(db, payload, user, row.id if row else None)
    unique(db, MaintenanceJob, 'reference', payload.reference, row.id if row else None)
    values = payload.model_dump(exclude={'reason','version','parts'})
    meter = latest_reading(db, equipment.id) if hour_plan else None
    values.update(parts_json=encoded([{'material_id': part.material_id, 'quantity': str(part.quantity)} for part in payload.parts]),
        plan_version=(plan or hour_plan).version if (plan or hour_plan) else None,
        plan_due_date=plan.next_due if plan else None,
        plan_due_hours=hour_plan.next_due_hours if hour_plan else None,
        plan_meter_reading_id=meter.id if meter else None,
        equipment_json=encoded(model_data(equipment)), work_order_json=encoded(model_data(order)) if order else '{}')
    before = model_data(row) if row else None
    if row is None:
        row = add_model(db, MaintenanceJob(**values, version=1, status='draft', created_by=user['id'],
            solution='', labor_hours=None, service_amount=None, plan_roll_json='{}'))
    else:
        for field, value in values.items():
            setattr(row, field, value)
        row.version += 1
        row.status = 'draft'
    record_author(db, 'MaintenanceJob', row.id, user['id'])
    audit(db, 'job', row, 'edit' if before else 'create', before, user, payload.reason)
    return job_data(db, row, user)


@router.post('/jobs', status_code=201)
def create_job(payload: JobInput, user: dict = Depends(require('equipment.create'))):
    with orm_session(write=True) as db:
        return save_job(db, payload, user)


@router.put('/jobs/{identifier}')
def edit_job(identifier: int, payload: JobEdit, user: dict = Depends(require('equipment.create'))):
    permission(user, 'equipment.view')
    with orm_session(write=True) as db:
        return save_job(db, payload, user, get(db, MaintenanceJob, identifier, '维护工单'))


def finish_downtime(db, row, user, reason):
    entry = db.scalar(select(MaintenanceDowntime).where(MaintenanceDowntime.job_id == row.id))
    if entry and entry.ended_at is None:
        entry.ended_at = now()
        entry.ended_by = user['id']
        entry.close_reason = reason


def prepare_approval_action(db, row, action, user, reason, evidence):
    # 新审批仍要求原来的两项依据；审核失效来源可驳回，不要求修复来源后才能拒绝。
    if action in ('submit', 'approve', 'reject'):
        if not reason.strip() or len(reason.strip()) > 200 or not evidence.strip() or len(evidence.strip()) > 600:
            raise HTTPException(422, '维护操作原因与现场依据必填，分别最多二百字和六百字')
    if action in ('submit', 'approve'):
        frozen_links(db, row, check_meter_due=True)
        if row.plan_due_date and row.plan_due_date > now()[:10]:
            raise HTTPException(409, '周期计划尚未到期，不能提前提交或批准')
    return model_data(row)


def sync_approval_action(db, row, action, state, user_id, reason, evidence, before):
    row.status = 'draft' if action == 'withdraw' else state['status']
    if action == 'submit':
        row.reviewed_by = None
    elif action in ('approve', 'reject'):
        row.reviewed_by = user_id
    row.version += 1
    audit(db, 'job', row, action, before, {'id': user_id},
          reason.strip() or '撤回维护工单审批', evidence.strip())


@router.post('/jobs/{identifier}/{action}')
def change_job(identifier: int, action: JobAction, payload: ActionInput,
               user: dict = Depends(require('equipment.view'))):
    operation = {'approve':'review','reject':'review','start':'execute','report':'execute','rework':'accept'}.get(action, action)
    permission(user, 'equipment.' + operation)
    report_fields = (payload.solution, payload.labor_hours, payload.service_amount)
    if action == 'report' and any(value is None for value in report_fields):
        raise HTTPException(422, '报工须填写处理结果、工时和声明外委费用，免费也须明确填零')
    if action != 'report' and any(value is not None for value in report_fields):
        raise HTTPException(422, '只有报工操作可以提交处理结果、工时和声明费用')
    with orm_session(write=True) as db:
        row = get(db, MaintenanceJob, identifier, '维护工单')
        version(row, payload.version)
        if action in ('submit', 'approve', 'reject'):
            raise HTTPException(409, '请从本单统一审批入口完成审核、核准与批准')
        case = None
        if action == 'start':
            case = approval.require_maintenance_approved(db, row.id, maintenance_snapshot(db, row.id),
                user['id'], 'equipment.execute')
        elif action == 'reverse':
            case = approval.require_approved(db, 'MaintenanceJob', row.id,
                document_snapshot(db, 'MaintenanceJob', row.id, 'reverse', payload.reason, payload.evidence),
                user['id'], intent='reverse', permission='equipment.reverse')
        elif action == 'cancel':
            pending = approval.find_case(db, 'MaintenanceJob', row.id)
            if pending and pending.status in ('submitted', 'approved'):
                raise HTTPException(409, '请先撤回本单尚未执行的审批，再取消')
        before = model_data(row)
        expected = {'submit': ('draft','rejected'), 'approve': ('submitted',), 'reject': ('submitted',),
            'start': ('approved',), 'report': ('in_progress',), 'rework': ('reported',),
            'accept': ('reported',), 'cancel': ('draft','rejected','submitted','approved','in_progress','reported'),
            'reverse': ('accepted',)}
        if row.status not in expected[action]:
            raise HTTPException(409, '当前工单状态不能执行此操作')
        if action in ('approve','reject','accept','rework'):
            independent(db, row, user, action in ('accept','rework'))
        if action in ('start','report') and user['id'] != row.assigned_to:
            raise HTTPException(403, '只有工单指定的执行人可以开始维护或报工')
        if action in ('submit','approve','start','report','accept'):
            # 已实际报工的证据不因执行人后续停用而失效；生产关联只说明影响，不代替维护实物记录。
            frozen_links(db, row, check_executor=action != 'accept',
                check_work_order=action in ('submit','approve','start'),
                check_meter_due=action in ('submit','approve','start'))
        if action == 'start':
            if db.scalar(select(MaintenanceJob.id).where(MaintenanceJob.equipment_id == row.equipment_id,
                    MaintenanceJob.status.in_(RUNNING))):
                raise HTTPException(409, '设备已有执行中的维护工单，不能重叠停机')
            parts = json.loads(row.parts_json)
            if parts:
                permission(user, 'other_outbound.create')
                outbound = add_model(db, WarehouseOutbound(warehouse_id=row.warehouse_id, source_kind='other',
                    reason='other', note=f'设备维护耗材 {row.reference}'[:200], reference=row.reference, created_by=user['id']))
                db.add_all([WarehouseOutboundLine(outbound_id=outbound.id, **part) for part in parts])
                row.parts_outbound_id = outbound.id
                # 保留原维护方案作者范围用于溯源，耗材出库按其当前步骤按钮权限审批。
                for author_id in authors(db, row):
                    record_author(db, 'WarehouseOutbound', outbound.id, author_id)
            row.status = 'in_progress'
            row.started_at = now()
            db.add(MaintenanceDowntime(equipment_id=row.equipment_id, job_id=row.id, started_at=row.started_at,
                close_reason='', started_by=user['id']))
        elif action == 'report':
            parts_ready(db, row)
            row.solution = payload.solution
            row.labor_hours = str(payload.labor_hours.quantize(Decimal('0.01')))
            row.service_amount = str(payload.service_amount.quantize(Decimal('0.01')))
            row.reported_by = user['id']
            row.reported_at = now()
            row.status = 'reported'
        elif action == 'rework':
            row.status = 'in_progress'
        elif action == 'accept':
            parts_ready(db, row)
            row.status = 'accepted'
            row.accepted_by = user['id']
            row.accepted_at = now()
            finish_downtime(db, row, user, payload.evidence)
            if row.plan_id:
                plan = get(db, MaintenancePlan, row.plan_id, '维护计划')
                previous = model_data(plan)
                plan.next_due = (date.fromisoformat(row.accepted_at[:10]) + timedelta(days=plan.interval_days)).isoformat()
                plan.version += 1
                audit(db, 'plan', plan, 'advance', previous, user, payload.reason, payload.evidence)
                row.plan_roll_json = encoded({'before': previous, 'after': model_data(plan), 'reversal_effect': None})
            elif row.hour_plan_id:
                plan = get(db, MaintenanceHourPlan, row.hour_plan_id, '运行小时计划')
                reading = latest_reading(db, row.equipment_id)
                if reading is None:
                    raise HTTPException(409, '设备缺少运行小时读数，不能推进保养计划')
                previous = model_data(plan)
                plan.next_due_hours = hours_text(max(Decimal(plan.next_due_hours), Decimal(reading.hours))
                    + Decimal(plan.interval_hours))
                plan.version += 1
                audit_hour_plan(db, plan, 'advance', previous, user, payload.reason, payload.evidence)
                row.plan_roll_json = encoded({'before': previous, 'after': model_data(plan),
                                              'reading_id': reading.id, 'reversal_effect': None})
        elif action == 'cancel':
            if parts_status(db, row) == 'draft':
                raise HTTPException(409, '先取消关联耗材出库草稿，再取消维护工单')
            # 已实际领用的耗材保留原库存流水；取消维护记录不能冒充实物归库。
            row.status = 'cancelled'
            finish_downtime(db, row, user, payload.evidence)
        elif action == 'reverse':
            row.status = 'reversed'
            roll = json.loads(row.plan_roll_json)
            if roll:
                plan = (get(db, MaintenanceHourPlan, row.hour_plan_id, '运行小时计划') if row.hour_plan_id
                        else get(db, MaintenancePlan, row.plan_id, '维护计划'))
                later = db.scalar(select(MaintenanceJob.id).where(
                    (MaintenanceJob.hour_plan_id == plan.id if row.hour_plan_id
                     else MaintenanceJob.plan_id == plan.id), MaintenanceJob.id > row.id,
                    MaintenanceJob.status.not_in(('cancelled','reversed'))))
                if not later and model_data(plan) == roll['after']:
                    previous = model_data(plan)
                    if row.hour_plan_id:
                        plan.next_due_hours = roll['before']['next_due_hours']
                    else:
                        plan.next_due = roll['before']['next_due']
                    plan.version += 1
                    if row.hour_plan_id:
                        audit_hour_plan(db, plan, 'restore_due', previous, user, payload.reason, payload.evidence)
                    else:
                        audit(db, 'plan', plan, 'restore_due', previous, user, payload.reason, payload.evidence)
                    roll['reversal_effect'] = 'restored_due'
                else:
                    roll['reversal_effect'] = 'retained_newer_schedule'
                row.plan_roll_json = encoded(roll)
        row.version += 1
        audit(db, 'job', row, action, before, user, payload.reason, payload.evidence)
        if case is not None and case.status == 'approved':
            approval.mark_executed(db, case, user['id'], permission='equipment.reverse' if action == 'reverse' else 'equipment.execute')
        return job_data(db, row, user)
