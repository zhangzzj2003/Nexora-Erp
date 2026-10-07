"""设备维护来源、状态与证据；共用调用方 ORM 事务。"""

import json
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select

from app.core.models import (EquipmentAsset, MaintenancePlan, MaintenanceHourPlan, MaintenanceJob, MaintenanceChange,
    MaintenanceDowntime, User, UserRole, RolePermission, Material, WorkOrder,
    WarehouseOutbound, WarehouseOutboundReversal)
from app.core.orm import model_data
from app.core import document_approval as approval
from app.core.approval_documents import maintenance_snapshot
from app.inventory.warehouse import require_warehouse

TERMINAL = ('accepted','cancelled','reversed')
RUNNING = ('in_progress','reported')


def now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def permission(user, code):
    if code not in user['permissions']:
        raise HTTPException(403, '没有执行此操作的权限')


def get(db, model, identifier, label):
    row = db.get(model, identifier)
    if row is None:
        raise HTTPException(404, f'{label}不存在')
    return row


def version(row, supplied):
    if row.version != supplied:
        raise HTTPException(409, '记录已被修改，请刷新证据后重试，不能覆盖其他人的更正')


def unique(db, model, field, value, identifier=None):
    if value is not None and db.scalar(select(model.id).where(getattr(model, field) == value,
            model.id != identifier if identifier is not None else model.id > 0)) is not None:
        raise HTTPException(409, '编号或序列号已存在')


def active_jobs(db, **filters):
    statement = select(MaintenanceJob).where(MaintenanceJob.status.not_in(TERMINAL))
    for key, value in filters.items():
        statement = statement.where(getattr(MaintenanceJob, key) == value)
    return list(db.scalars(statement))


def audit(db, kind, row, action, before, user, reason, evidence=''):
    db.flush()
    db.add(MaintenanceChange(entity_type=kind, entity_id=row.id, action=action,
        before_json=encoded(before) if before is not None else None, after_json=encoded(model_data(row)),
        reason=reason, evidence=evidence, changed_by=user['id']))
    db.flush()


def authors(db, row):
    identifiers = {row.created_by}
    identifiers.update(db.scalars(select(MaintenanceChange.changed_by).where(
        MaintenanceChange.entity_type == 'job', MaintenanceChange.entity_id == row.id,
        MaintenanceChange.action.in_(('create','edit','submit')))))
    identifiers.update(maintenance_snapshot(db, row.id)['source_author_ids'])
    return sorted(identifiers)


def independent(db, row, user, acceptance=False):
    excluded = set(authors(db, row))
    if acceptance:
        excluded.update((row.assigned_to, row.reported_by))
    if user['id'] in excluded:
        raise HTTPException(409, '须由未参与编制、提交或执行的独立人员处理，管理员也不能自审')


def executors(db):
    # 仅提供有执行权限的启用账号编号及用户名，不返回联系方式或完整角色资料。
    return list(db.execute(select(User.id, User.username).join(UserRole, UserRole.user_id == User.id)
        .join(RolePermission, RolePermission.role_code == UserRole.role_code)
        .where(User.is_active == 1, RolePermission.permission_code == 'equipment.execute')
        .distinct().order_by(User.id)).all())


def validate_job(db, payload, user, identifier=None):
    equipment = get(db, EquipmentAsset, payload.equipment_id, '设备')
    if equipment.status != 'active':
        raise HTTPException(409, '设备须处于启用状态')
    plan = get(db, MaintenancePlan, payload.plan_id, '维护计划') if payload.plan_id else None
    hour_plan = get(db, MaintenanceHourPlan, payload.hour_plan_id, '运行小时计划') if payload.hour_plan_id else None
    if plan and (not plan.enabled or plan.equipment_id != equipment.id):
        raise HTTPException(409, '维护计划须启用且属于所选设备')
    if plan and db.scalar(select(MaintenanceJob.id).where(MaintenanceJob.plan_id == plan.id,
            MaintenanceJob.plan_due_date == plan.next_due, MaintenanceJob.status.not_in(('cancelled','reversed')),
            MaintenanceJob.id != identifier if identifier is not None else MaintenanceJob.id > 0)):
        raise HTTPException(409, '本次计划到期已有关联工单，不能重复领取')
    if hour_plan and (not hour_plan.enabled or hour_plan.equipment_id != equipment.id):
        raise HTTPException(409, '运行小时计划须启用且属于所选设备')
    if hour_plan and db.scalar(select(MaintenanceJob.id).where(MaintenanceJob.hour_plan_id == hour_plan.id,
            MaintenanceJob.plan_due_hours == hour_plan.next_due_hours,
            MaintenanceJob.status.not_in(('cancelled','reversed')),
            MaintenanceJob.id != identifier if identifier is not None else MaintenanceJob.id > 0)):
        raise HTTPException(409, '本次运行小时阈值已有关联工单，不能重复领取')
    if payload.assigned_to not in {actor.id for actor in executors(db)}:
        raise HTTPException(422, '执行人须为启用且有设备维护执行权限的账号')
    order = None
    if payload.work_order_id:
        permission(user, 'production.view')
        order = get(db, WorkOrder, payload.work_order_id, '生产工单')
        if order.status == 'cancelled':
            raise HTTPException(409, '不能关联已取消生产工单')
    if payload.parts:
        require_warehouse(db, payload.warehouse_id)
    for part in payload.parts:
        get(db, Material, part.material_id, '耗材物料')
    return equipment, plan, hour_plan, order


def frozen_links(db, row, *, check_executor=True, check_work_order=True, check_meter_due=False):
    equipment = get(db, EquipmentAsset, row.equipment_id, '设备')
    if equipment.status != 'active':
        raise HTTPException(409, '设备已停用或报废')
    if row.plan_id:
        plan = get(db, MaintenancePlan, row.plan_id, '维护计划')
        if not plan.enabled or plan.version != row.plan_version or plan.next_due != row.plan_due_date:
            raise HTTPException(409, '计划来源已变化，请取消旧工单后重新编制')
    if row.hour_plan_id:
        plan = get(db, MaintenanceHourPlan, row.hour_plan_id, '运行小时计划')
        if not plan.enabled or plan.version != row.plan_version or plan.next_due_hours != row.plan_due_hours:
            raise HTTPException(409, '运行小时计划来源已变化，请取消旧工单后重新编制')
        if check_meter_due:
            from app.production.equipment_hours import latest_reading
            reading = latest_reading(db, row.equipment_id)
            if reading is None or Decimal(reading.hours) < Decimal(row.plan_due_hours):
                raise HTTPException(409, '设备当前运行小时尚未达到保养阈值')
    if check_work_order and row.work_order_id and get(db, WorkOrder, row.work_order_id, '生产工单').status == 'cancelled':
        raise HTTPException(409, '关联生产工单已取消，请取消维护工单后重新编制')
    if check_executor and row.assigned_to not in {actor.id for actor in executors(db)}:
        raise HTTPException(409, '执行人已停用或失去执行权限，请取消后重新分派')


def parts_status(db, row):
    if row.parts_outbound_id is None:
        return None
    outbound = db.get(WarehouseOutbound, row.parts_outbound_id)
    if db.scalar(select(WarehouseOutboundReversal.id).where(
            WarehouseOutboundReversal.outbound_id == row.parts_outbound_id)):
        return 'reversed'
    return outbound.status if outbound else 'missing'


def parts_ready(db, row):
    if json.loads(row.parts_json) and parts_status(db, row) != 'posted':
        raise HTTPException(409, '耗材出库须有效确认后才能报工或验收')


def changes(db, kind, identifier, user):
    rows = db.execute(select(MaintenanceChange, User.username).join(User, User.id == MaintenanceChange.changed_by)
        .where(MaintenanceChange.entity_type == kind, MaintenanceChange.entity_id == identifier)
        .order_by(MaintenanceChange.id)).all()
    def redact(snapshot):
        if snapshot is not None and kind == 'job' and 'production.view' not in user['permissions']:
            snapshot['work_order_id'] = None
            snapshot['work_order_json'] = '{}'
        return snapshot
    return [dict(id=row.id, action=row.action, reason=row.reason, evidence=row.evidence,
        changed_by=row.changed_by, changed_by_name=name, created_at=row.created_at,
        before=redact(json.loads(row.before_json)) if row.before_json is not None else None,
        after=redact(json.loads(row.after_json))) for row, name in rows]


def downtime_data(db, row):
    result = model_data(row)
    end = row.ended_at or now()
    result['seconds'] = max(0, int((datetime.fromisoformat(end) - datetime.fromisoformat(row.started_at)).total_seconds()))
    result['ongoing'] = row.ended_at is None
    result['started_by_name'] = db.get(User, row.started_by).username
    result['ended_by_name'] = db.get(User, row.ended_by).username if row.ended_by else None
    return result


def available_actions(db, row, user):
    policy = {'draft': ('cancel',), 'rejected': ('cancel',),
        'submitted': ('cancel',), 'approved': ('start','cancel'),
        'in_progress': ('report','cancel'), 'reported': ('accept','rework','cancel'), 'accepted': ('reverse',)}
    operation_permission = {'approve':'review','reject':'review','start':'execute','report':'execute','rework':'accept'}
    excluded = set(authors(db, row))
    case = approval.find_case(db, 'MaintenanceJob', row.id)
    reversal = approval.find_case(db, 'MaintenanceJob', row.id, 'reverse')
    return [action for action in policy.get(row.status, ())
        if (action != 'start' or case is not None and case.status in ('approved', 'executed'))
        and (action != 'reverse' or reversal is not None and reversal.status == 'approved')
        and (action != 'cancel' or case is None or case.status not in ('submitted', 'approved'))
        and f'equipment.{operation_permission.get(action, action)}' in user['permissions']
        and (action not in ('approve','reject','accept','rework') or user['id'] not in excluded)
        and (action not in ('accept','rework') or user['id'] not in (row.assigned_to, row.reported_by))
        and (action not in ('start','report') or user['id'] == row.assigned_to)]


def job_data(db, row, user, detail=True):
    result = model_data(row)
    for field in ('equipment','work_order','parts','plan_roll'):
        result[field + '_snapshot' if field in ('equipment','work_order') else field] = json.loads(result.pop(field + '_json'))
    result['work_order_linked'] = row.work_order_id is not None
    result['work_order_current_status'] = (db.get(WorkOrder, row.work_order_id).status
        if row.work_order_id is not None and 'production.view' in user['permissions'] else None)
    if 'production.view' not in user['permissions']:
        result['work_order_id'] = None
        result['work_order_snapshot'] = None
    result['created_by_name'] = db.get(User, row.created_by).username
    result['assigned_to_name'] = db.get(User, row.assigned_to).username
    result['author_ids'] = authors(db, row)
    result['parts_status'] = parts_status(db, row)
    if detail and 'purchase_request.view' in user['permissions']:
        from app.production.equipment_procurement import procurement_data
        result['purchase_requests'] = procurement_data(db, row.id)
    else:
        result['purchase_requests'] = []
    result['approval'] = approval.case_data(approval.find_case(db, 'MaintenanceJob', row.id))
    result['reversal_approval'] = approval.case_data(approval.find_case(db, 'MaintenanceJob', row.id, 'reverse'))
    result['allowed_actions'] = available_actions(db, row, user)
    result['can_edit'] = (row.status in ('draft','rejected') and 'equipment.create' in user['permissions']
                          and (row.work_order_id is None or 'production.view' in user['permissions']))
    downtime = db.scalar(select(MaintenanceDowntime).where(MaintenanceDowntime.job_id == row.id))
    result['downtime'] = downtime_data(db, downtime) if downtime else None
    result['changes'] = changes(db, 'job', row.id, user) if detail else []
    return result
