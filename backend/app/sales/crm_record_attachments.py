"""联系人、跟进与商机的附件留存和追加式撤销。"""

from app.core.document_responses import NumberedRoute
import hashlib
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.access.security import require
from app.core.attachment_files import AttachmentInput, ReversalInput, decode_content, MAX_ATTACHMENTS
from app.core.models import CrmRecordAttachment, CrmRecordAttachmentReversal, User
from app.core.orm import add_model, orm_session
from app.sales.crm_rules import OPEN_STAGES, get_record

router = APIRouter(route_class=NumberedRoute, prefix='/api/v1/crm/records')
RecordKind = Literal['contact', 'activity', 'opportunity']


def visible_record(db: Session, kind: RecordKind, identifier: int, user: dict):
    if 'crm.view' not in user['permissions']:
        raise HTTPException(403, '没有执行此操作的权限')
    return get_record(db, kind, identifier, user=user)


def modifiable(kind: RecordKind, record) -> bool:
    # 已结束的资料保留当时证据；重开商机后才可再次补充附件。
    if kind == 'contact':
        return bool(record.is_active)
    if kind == 'activity':
        return record.status == 'planned'
    return record.stage in OPEN_STAGES


def attachment_data(db: Session, row: CrmRecordAttachment) -> dict:
    reversal = db.scalar(select(CrmRecordAttachmentReversal).where(
        CrmRecordAttachmentReversal.attachment_id == row.id))
    return dict(id=row.id, entity_kind=row.entity_kind, entity_id=row.entity_id,
        file_name=row.file_name, media_type=row.media_type, byte_count=row.byte_count,
        sha256=row.sha256, reason=row.reason, created_by=row.created_by,
        created_at=row.created_at,
        created_by_name=db.scalar(select(User.username).where(User.id == row.created_by)),
        reversal=(dict(id=reversal.id, reason=reversal.reason, created_by=reversal.created_by,
            created_at=reversal.created_at,
            created_by_name=db.scalar(select(User.username).where(User.id == reversal.created_by)))
            if reversal else None))


def get_attachment(db: Session, kind: RecordKind, identifier: int,
                   attachment_id: int) -> CrmRecordAttachment:
    row = db.get(CrmRecordAttachment, attachment_id)
    if row is None or row.entity_kind != kind or row.entity_id != identifier:
        raise HTTPException(404, '客户关系附件不存在')
    return row


@router.get('/{kind}/{identifier}/attachments')
def list_attachments(kind: RecordKind, identifier: int = Path(gt=0),
        user: dict = Depends(require('crm.view'))) -> dict:
    with orm_session() as db:
        record = visible_record(db, kind, identifier, user)
        rows = db.scalars(select(CrmRecordAttachment).where(
            CrmRecordAttachment.entity_kind == kind,
            CrmRecordAttachment.entity_id == identifier).order_by(CrmRecordAttachment.id)).all()
        return dict(entity_kind=kind, entity_id=identifier,
            can_modify=modifiable(kind, record),
            items=[attachment_data(db, row) for row in rows])


@router.post('/{kind}/{identifier}/attachments', status_code=201)
def add_attachment(data: AttachmentInput, kind: RecordKind,
        identifier: int = Path(gt=0), user: dict = Depends(require('crm.attachment'))) -> dict:
    content, media_type = decode_content(data)
    digest = hashlib.sha256(content).hexdigest()
    with orm_session(write=True) as db:
        record = visible_record(db, kind, identifier, user)
        if not modifiable(kind, record):
            raise HTTPException(409, '客户关系资料已停用或结束，不能添加附件')
        active = select(CrmRecordAttachment.id).where(
            CrmRecordAttachment.entity_kind == kind,
            CrmRecordAttachment.entity_id == identifier,
            ~select(CrmRecordAttachmentReversal.id).where(
                CrmRecordAttachmentReversal.attachment_id == CrmRecordAttachment.id).exists())
        if db.scalar(select(func.count()).select_from(active.subquery())) >= MAX_ATTACHMENTS:
            raise HTTPException(409, '单条资料最多保留 10 个有效附件')
        if db.scalar(active.where(CrmRecordAttachment.sha256 == digest).limit(1)) is not None:
            raise HTTPException(409, '此资料已有相同内容的有效附件')
        row = add_model(db, CrmRecordAttachment(entity_kind=kind, entity_id=identifier,
            file_name=data.file_name, media_type=media_type, byte_count=len(content),
            sha256=digest, content=content, reason=data.reason, created_by=user['id']))
        return attachment_data(db, row)


@router.get('/{kind}/{identifier}/attachments/{attachment_id}')
def download_attachment(kind: RecordKind, identifier: int = Path(gt=0),
        attachment_id: int = Path(gt=0), user: dict = Depends(require('crm.view'))) -> Response:
    with orm_session() as db:
        visible_record(db, kind, identifier, user)
        row = get_attachment(db, kind, identifier, attachment_id)
        if len(row.content) != row.byte_count or hashlib.sha256(row.content).hexdigest() != row.sha256:
            raise HTTPException(409, '附件内容校验失败，请联系管理员检查备份')
        suffix = '.' + row.file_name.rsplit('.', 1)[-1].lower()
        return Response(content=row.content, media_type='application/octet-stream', headers={
            'Cache-Control': 'no-store',
            'Content-Disposition': f'attachment; filename="crm-{kind}-{identifier}-{attachment_id}{suffix}"',
            'X-Nexora-SHA256': row.sha256, 'X-Nexora-File-Extension': suffix,
        })


@router.post('/{kind}/{identifier}/attachments/{attachment_id}/reverse', status_code=201)
def reverse_attachment(data: ReversalInput, kind: RecordKind,
        identifier: int = Path(gt=0), attachment_id: int = Path(gt=0),
        user: dict = Depends(require('crm.attachment'))) -> dict:
    try:
        with orm_session(write=True) as db:
            record = visible_record(db, kind, identifier, user)
            row = get_attachment(db, kind, identifier, attachment_id)
            if not modifiable(kind, record):
                raise HTTPException(409, '客户关系资料已停用或结束，不能撤销附件')
            if db.scalar(select(CrmRecordAttachmentReversal.id).where(
                    CrmRecordAttachmentReversal.attachment_id == row.id)) is not None:
                raise HTTPException(409, '附件已撤销')
            add_model(db, CrmRecordAttachmentReversal(attachment_id=row.id,
                reason=data.reason, created_by=user['id']))
            return attachment_data(db, row)
    except IntegrityError:
        raise HTTPException(409, '附件已撤销') from None
