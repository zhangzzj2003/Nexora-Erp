"""售后单附件留存；只追加撤销证据，不覆盖原文件。"""

from app.core.document_responses import NumberedRoute
import hashlib
import json
from app.core.document_approval import find_case, record_author

from fastapi import APIRouter, Depends, HTTPException, Path
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.access.security import require
from app.core.attachment_files import AttachmentInput, ReversalInput, decode_content, MAX_ATTACHMENTS
from app.core.models import AfterSalesAttachment, AfterSalesAttachmentReversal, AfterSalesCase, User
from app.core.orm import add_model, orm_session
from app.sales.after_sales import get_case, permission
from app.sales.customer_scope import require_visible_after_sales

router = APIRouter(route_class=NumberedRoute, prefix='/api/v1/after-sales/cases')


def visible_case(db: Session, case_id: int, user: dict) -> AfterSalesCase:
    permission(user, 'after_sales.view')
    return require_visible_after_sales(db, get_case(db, case_id), user)


def modifiable(case: AfterSalesCase) -> bool:
    return case.status in ('draft', 'rejected',
        'processing', 'received', 'repaired')


def attachment_data(db: Session, row: AfterSalesAttachment) -> dict:
    reversal = db.scalar(select(AfterSalesAttachmentReversal).where(
        AfterSalesAttachmentReversal.attachment_id == row.id))
    approved = find_case(db, 'AfterSalesCase', row.case_id)
    frozen = approved is not None and approved.status == 'executed' and any(
        item['id'] == row.id for item in json.loads(approved.snapshot_json)['attachments'])
    return dict(can_reverse=not frozen, id=row.id, case_id=row.case_id, file_name=row.file_name,
        media_type=row.media_type, byte_count=row.byte_count, sha256=row.sha256,
        reason=row.reason, created_by=row.created_by, created_at=row.created_at,
        created_by_name=db.scalar(select(User.username).where(User.id == row.created_by)),
        reversal=(dict(id=reversal.id, reason=reversal.reason, created_by=reversal.created_by,
            created_at=reversal.created_at,
            created_by_name=db.scalar(select(User.username).where(User.id == reversal.created_by)))
            if reversal else None))


def get_attachment(db: Session, case_id: int, attachment_id: int) -> AfterSalesAttachment:
    row = db.get(AfterSalesAttachment, attachment_id)
    if row is None or row.case_id != case_id:
        raise HTTPException(404, '售后附件不存在')
    return row


@router.get('/{case_id}/attachments')
def list_attachments(case_id: int = Path(gt=0),
        user: dict = Depends(require('after_sales.view'))) -> dict:
    with orm_session() as db:
        case = visible_case(db, case_id, user)
        rows = db.scalars(select(AfterSalesAttachment).where(
            AfterSalesAttachment.case_id == case_id).order_by(AfterSalesAttachment.id)).all()
        return dict(case_id=case_id, can_modify=modifiable(case),
            items=[attachment_data(db, row) for row in rows])


@router.post('/{case_id}/attachments', status_code=201)
def add_attachment(data: AttachmentInput, case_id: int = Path(gt=0),
        user: dict = Depends(require('after_sales.attachment'))) -> dict:
    content, media_type = decode_content(data)
    digest = hashlib.sha256(content).hexdigest()
    with orm_session(write=True) as db:
        case = visible_case(db, case_id, user)
        if not modifiable(case):
            raise HTTPException(409, '审批期间请先撤回；已结案、取消或更正的售后单不能添加附件')
        active = select(AfterSalesAttachment.id).where(
            AfterSalesAttachment.case_id == case_id,
            ~select(AfterSalesAttachmentReversal.id).where(
                AfterSalesAttachmentReversal.attachment_id == AfterSalesAttachment.id).exists())
        if db.scalar(select(func.count()).select_from(active.subquery())) >= MAX_ATTACHMENTS:
            raise HTTPException(409, '单张售后单最多保留 10 个有效附件')
        if db.scalar(active.where(AfterSalesAttachment.sha256 == digest).limit(1)) is not None:
            raise HTTPException(409, '此售后单已有相同内容的有效附件')
        if case.status in ('draft', 'rejected'):
            record_author(db, 'AfterSalesCase', case.id, user['id'])
        row = add_model(db, AfterSalesAttachment(case_id=case_id,
            file_name=data.file_name, media_type=media_type, byte_count=len(content),
            sha256=digest, content=content, reason=data.reason, created_by=user['id']))
        return attachment_data(db, row)


@router.get('/{case_id}/attachments/{attachment_id}')
def download_attachment(case_id: int = Path(gt=0), attachment_id: int = Path(gt=0),
        user: dict = Depends(require('after_sales.view'))) -> Response:
    with orm_session() as db:
        visible_case(db, case_id, user)
        row = get_attachment(db, case_id, attachment_id)
        if len(row.content) != row.byte_count or hashlib.sha256(row.content).hexdigest() != row.sha256:
            raise HTTPException(409, '附件内容校验失败，请联系管理员检查备份')
        suffix = '.' + row.file_name.rsplit('.', 1)[-1].lower()
        return Response(content=row.content, media_type='application/octet-stream', headers={
            'Cache-Control': 'no-store',
            'Content-Disposition': f'attachment; filename="after-sales-{case_id}-{attachment_id}{suffix}"',
            'X-Nexora-SHA256': row.sha256, 'X-Nexora-File-Extension': suffix,
        })


@router.post('/{case_id}/attachments/{attachment_id}/reverse', status_code=201)
def reverse_attachment(data: ReversalInput, case_id: int = Path(gt=0),
        attachment_id: int = Path(gt=0),
        user: dict = Depends(require('after_sales.attachment'))) -> dict:
    try:
        with orm_session(write=True) as db:
            case = visible_case(db, case_id, user)
            row = get_attachment(db, case_id, attachment_id)
            if not modifiable(case):
                raise HTTPException(409, '审批期间请先撤回；已结案、取消或更正的售后单不能撤销附件')
            approved = find_case(db, 'AfterSalesCase', case_id)
            if approved is not None and approved.status == 'executed' and any(
                    item['id'] == row.id for item in json.loads(approved.snapshot_json)['attachments']):
                raise HTTPException(409, '已执行方案的批准附件须保留，请追加后续作业证据')
            if case.status in ('draft', 'rejected'):
                record_author(db, 'AfterSalesCase', case.id, user['id'])
            if db.scalar(select(AfterSalesAttachmentReversal.id).where(
                    AfterSalesAttachmentReversal.attachment_id == row.id)) is not None:
                raise HTTPException(409, '附件已撤销')
            add_model(db, AfterSalesAttachmentReversal(attachment_id=row.id,
                reason=data.reason, created_by=user['id']))
            return attachment_data(db, row)
    except IntegrityError:
        raise HTTPException(409, '附件已撤销') from None
