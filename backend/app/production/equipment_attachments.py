"""设备台账与维护工单附件，原文保留并追加撤销记录。"""

from app.core.document_responses import NumberedRoute
import hashlib
import json
from app.core import document_approval as approval
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.access.security import require
from app.core.attachment_files import AttachmentInput, ReversalInput, decode_content, MAX_ATTACHMENTS
from app.core.models import EquipmentAsset, EquipmentAttachment, EquipmentAttachmentReversal, MaintenanceJob, User
from app.core.orm import add_model, orm_session
from app.production.equipment_rules import TERMINAL, get

router = APIRouter(route_class=NumberedRoute, prefix='/api/v1/equipment')
AttachmentKind = Literal['asset', 'job']


def parent(db: Session, kind: AttachmentKind, identifier: int):
    return get(db, EquipmentAsset if kind == 'asset' else MaintenanceJob,
               identifier, '设备' if kind == 'asset' else '维护工单')


def can_modify(db: Session, kind: AttachmentKind, row) -> bool:
    # 历史设备与终态工单只供核对，后续补证需另立业务记录。
    if kind == 'asset':
        return row.status != 'retired'
    case = approval.find_case(db, 'MaintenanceJob', row.id)
    return row.status not in TERMINAL and (case is None or case.status not in ('submitted', 'approved'))


def can_reverse(db: Session, row: EquipmentAttachment) -> bool:
    kind = 'asset' if row.asset_id is not None else 'job'
    record = parent(db, kind, row.asset_id if kind == 'asset' else row.job_id)
    if not can_modify(db, kind, record):
        return False
    case = approval.find_case(db, 'MaintenanceJob', row.job_id) if row.job_id else None
    # 实际作业可补证，原批准附件不能随之撤销或改写。
    return not (case and case.status == 'executed' and row.id in
        {item['id'] for item in json.loads(case.snapshot_json)['attachments']})


def scope(kind: AttachmentKind, identifier: int):
    return EquipmentAttachment.asset_id == identifier if kind == 'asset' else EquipmentAttachment.job_id == identifier


def attachment_data(db: Session, row: EquipmentAttachment) -> dict:
    reversal = db.scalar(select(EquipmentAttachmentReversal).where(
        EquipmentAttachmentReversal.attachment_id == row.id))
    return dict(id=row.id, can_reverse=can_reverse(db, row), entity_kind='asset' if row.asset_id is not None else 'job',
        entity_id=row.asset_id if row.asset_id is not None else row.job_id,
        file_name=row.file_name, media_type=row.media_type, byte_count=row.byte_count,
        sha256=row.sha256, reason=row.reason, created_by=row.created_by,
        created_at=row.created_at,
        created_by_name=db.scalar(select(User.username).where(User.id == row.created_by)),
        reversal=(dict(id=reversal.id, reason=reversal.reason, created_by=reversal.created_by,
            created_at=reversal.created_at,
            created_by_name=db.scalar(select(User.username).where(User.id == reversal.created_by)))
            if reversal else None))


def get_attachment(db: Session, kind: AttachmentKind, identifier: int,
                   attachment_id: int) -> EquipmentAttachment:
    row = db.get(EquipmentAttachment, attachment_id)
    if row is None or (row.asset_id if kind == 'asset' else row.job_id) != identifier:
        raise HTTPException(404, '设备维护附件不存在')
    return row


@router.get('/{kind}/{identifier}/attachments')
def list_attachments(kind: AttachmentKind, identifier: int = Path(gt=0),
        user: dict = Depends(require('equipment.view'))) -> dict:
    with orm_session() as db:
        record = parent(db, kind, identifier)
        rows = db.scalars(select(EquipmentAttachment).where(scope(kind, identifier))
            .order_by(EquipmentAttachment.id)).all()
        return dict(entity_kind=kind, entity_id=identifier,
            can_modify=can_modify(db, kind, record),
            items=[attachment_data(db, row) for row in rows])


@router.post('/{kind}/{identifier}/attachments', status_code=201)
def add_attachment(data: AttachmentInput, kind: AttachmentKind,
        identifier: int = Path(gt=0), user: dict = Depends(require('equipment.attachment'))) -> dict:
    content, media_type = decode_content(data)
    digest = hashlib.sha256(content).hexdigest()
    with orm_session(write=True) as db:
        if 'equipment.view' not in user['permissions']:
            raise HTTPException(403, '没有执行此操作的权限')
        record = parent(db, kind, identifier)
        if not can_modify(db, kind, record):
            raise HTTPException(409, '设备已报废或维护工单已结束，不能添加附件')
        active = select(EquipmentAttachment.id).where(scope(kind, identifier),
            ~select(EquipmentAttachmentReversal.id).where(
                EquipmentAttachmentReversal.attachment_id == EquipmentAttachment.id).exists())
        if db.scalar(select(func.count()).select_from(active.subquery())) >= MAX_ATTACHMENTS:
            raise HTTPException(409, '单条资料最多保留 10 个有效附件')
        if db.scalar(active.where(EquipmentAttachment.sha256 == digest).limit(1)) is not None:
            raise HTTPException(409, '此资料已有相同内容的有效附件')
        row = add_model(db, EquipmentAttachment(
            asset_id=identifier if kind == 'asset' else None,
            job_id=identifier if kind == 'job' else None,
            file_name=data.file_name, media_type=media_type, byte_count=len(content),
            sha256=digest, content=content, reason=data.reason, created_by=user['id']))
        if kind == 'job':
            case = approval.find_case(db, 'MaintenanceJob', identifier)
            if case is None or case.status != 'executed':
                approval.record_author(db, 'MaintenanceJob', identifier, user['id'])
        return attachment_data(db, row)


@router.get('/{kind}/{identifier}/attachments/{attachment_id}')
def download_attachment(kind: AttachmentKind, identifier: int = Path(gt=0),
        attachment_id: int = Path(gt=0), user: dict = Depends(require('equipment.view'))) -> Response:
    with orm_session() as db:
        parent(db, kind, identifier)
        row = get_attachment(db, kind, identifier, attachment_id)
        if len(row.content) != row.byte_count or hashlib.sha256(row.content).hexdigest() != row.sha256:
            raise HTTPException(409, '附件内容校验失败，请联系管理员检查备份')
        suffix = '.' + row.file_name.rsplit('.', 1)[-1].lower()
        return Response(content=row.content, media_type='application/octet-stream', headers={
            'Cache-Control': 'no-store',
            'Content-Disposition': f'attachment; filename="equipment-{kind}-{identifier}-{attachment_id}{suffix}"',
            'X-Nexora-SHA256': row.sha256, 'X-Nexora-File-Extension': suffix,
        })


@router.post('/{kind}/{identifier}/attachments/{attachment_id}/reverse', status_code=201)
def reverse_attachment(data: ReversalInput, kind: AttachmentKind,
        identifier: int = Path(gt=0), attachment_id: int = Path(gt=0),
        user: dict = Depends(require('equipment.attachment'))) -> dict:
    try:
        with orm_session(write=True) as db:
            if 'equipment.view' not in user['permissions']:
                raise HTTPException(403, '没有执行此操作的权限')
            record = parent(db, kind, identifier)
            row = get_attachment(db, kind, identifier, attachment_id)
            if not can_reverse(db, row):
                raise HTTPException(409, '原批准附件、审批期间或终态附件不能撤销')
            if db.scalar(select(EquipmentAttachmentReversal.id).where(
                    EquipmentAttachmentReversal.attachment_id == row.id)) is not None:
                raise HTTPException(409, '附件已撤销')
            if kind == 'job':
                case = approval.find_case(db, 'MaintenanceJob', identifier)
                if case is None or case.status != 'executed':
                    approval.record_author(db, 'MaintenanceJob', identifier, user['id'])
            add_model(db, EquipmentAttachmentReversal(attachment_id=row.id,
                reason=data.reason, created_by=user['id']))
            return attachment_data(db, row)
    except IntegrityError:
        raise HTTPException(409, '附件已撤销') from None
