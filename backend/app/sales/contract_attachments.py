"""销售合同原件按正文版本留存，撤销只追加证据。"""

import hashlib

from fastapi import APIRouter, Depends, HTTPException, Path
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.access.security import require
from app.core.attachment_files import AttachmentInput, ReversalInput, decode_content, MAX_ATTACHMENTS
from app.core.models import (SalesOrderContractAttachment,
    SalesOrderContractAttachmentReversal, SalesOrderContractRevision, User)
from app.core.orm import add_model, orm_session
from app.sales.customer_scope import require_visible_order

router = APIRouter(prefix='/api/v1/sales-orders')


def visible_revision(db: Session, order_id: int, revision_id: int, user: dict):
    if 'sales.view' not in user['permissions']:
        raise HTTPException(403, '没有查看销售订单的权限')
    order = require_visible_order(db, order_id, user)
    revision = db.get(SalesOrderContractRevision, revision_id)
    if revision is None or revision.sales_order_id != order_id:
        raise HTTPException(404, '销售合同版本不存在')
    return order, revision


def attachment_data(db: Session, row: SalesOrderContractAttachment) -> dict:
    reversal = db.scalar(select(SalesOrderContractAttachmentReversal).where(
        SalesOrderContractAttachmentReversal.attachment_id == row.id))
    return dict(id=row.id, revision_id=row.revision_id, file_name=row.file_name,
        media_type=row.media_type, byte_count=row.byte_count, sha256=row.sha256,
        reason=row.reason, created_by=row.created_by, created_at=row.created_at,
        created_by_name=db.scalar(select(User.username).where(User.id == row.created_by)),
        reversal=(dict(id=reversal.id, reason=reversal.reason, created_by=reversal.created_by,
            created_at=reversal.created_at,
            created_by_name=db.scalar(select(User.username).where(User.id == reversal.created_by)))
            if reversal else None))


def get_attachment(db: Session, revision_id: int, attachment_id: int) -> SalesOrderContractAttachment:
    row = db.get(SalesOrderContractAttachment, attachment_id)
    if row is None or row.revision_id != revision_id:
        raise HTTPException(404, '合同附件不存在')
    return row


@router.get('/{order_id}/contract/revisions/{revision_id}/attachments')
def list_attachments(order_id: int = Path(gt=0), revision_id: int = Path(gt=0),
        user: dict = Depends(require('sales.view'))) -> dict:
    with orm_session() as db:
        order, _ = visible_revision(db, order_id, revision_id, user)
        rows = db.scalars(select(SalesOrderContractAttachment).where(
            SalesOrderContractAttachment.revision_id == revision_id)
            .order_by(SalesOrderContractAttachment.id)).all()
        return dict(order_id=order_id, revision_id=revision_id,
            can_modify=order.status != 'cancelled',
            items=[attachment_data(db, row) for row in rows])


@router.post('/{order_id}/contract/revisions/{revision_id}/attachments', status_code=201)
def add_attachment(data: AttachmentInput, order_id: int = Path(gt=0),
        revision_id: int = Path(gt=0),
        user: dict = Depends(require('sales_order.confirm'))) -> dict:
    content, media_type = decode_content(data)
    digest = hashlib.sha256(content).hexdigest()
    with orm_session(write=True) as db:
        order, _ = visible_revision(db, order_id, revision_id, user)
        if order.status == 'cancelled':
            raise HTTPException(409, '已取消销售订单不能添加合同附件')
        active = select(SalesOrderContractAttachment.id).where(
            SalesOrderContractAttachment.revision_id == revision_id,
            ~select(SalesOrderContractAttachmentReversal.id).where(
                SalesOrderContractAttachmentReversal.attachment_id == SalesOrderContractAttachment.id).exists())
        if db.scalar(select(func.count()).select_from(active.subquery())) >= MAX_ATTACHMENTS:
            raise HTTPException(409, '单个合同版本最多保留 10 个有效附件')
        if db.scalar(active.where(SalesOrderContractAttachment.sha256 == digest).limit(1)) is not None:
            raise HTTPException(409, '此合同版本已有相同内容的有效附件')
        row = add_model(db, SalesOrderContractAttachment(revision_id=revision_id,
            file_name=data.file_name, media_type=media_type, byte_count=len(content),
            sha256=digest, content=content, reason=data.reason, created_by=user['id']))
        return attachment_data(db, row)


@router.get('/{order_id}/contract/revisions/{revision_id}/attachments/{attachment_id}')
def download_attachment(order_id: int = Path(gt=0), revision_id: int = Path(gt=0),
        attachment_id: int = Path(gt=0), user: dict = Depends(require('sales.view'))) -> Response:
    with orm_session() as db:
        visible_revision(db, order_id, revision_id, user)
        row = get_attachment(db, revision_id, attachment_id)
        if len(row.content) != row.byte_count or hashlib.sha256(row.content).hexdigest() != row.sha256:
            raise HTTPException(409, '合同附件内容校验失败，请联系管理员检查备份')
        suffix = '.' + row.file_name.rsplit('.', 1)[-1].lower()
        return Response(content=row.content, media_type='application/octet-stream', headers={
            'Cache-Control': 'no-store',
            'Content-Disposition': f'attachment; filename="sales-contract-{order_id}-{revision_id}-{attachment_id}{suffix}"',
            'X-Nexora-SHA256': row.sha256, 'X-Nexora-File-Extension': suffix,
        })


@router.post('/{order_id}/contract/revisions/{revision_id}/attachments/{attachment_id}/reverse', status_code=201)
def reverse_attachment(data: ReversalInput, order_id: int = Path(gt=0),
        revision_id: int = Path(gt=0), attachment_id: int = Path(gt=0),
        user: dict = Depends(require('sales_order.confirm'))) -> dict:
    try:
        with orm_session(write=True) as db:
            order, _ = visible_revision(db, order_id, revision_id, user)
            row = get_attachment(db, revision_id, attachment_id)
            if order.status == 'cancelled':
                raise HTTPException(409, '已取消销售订单不能撤销合同附件')
            if db.scalar(select(SalesOrderContractAttachmentReversal.id).where(
                    SalesOrderContractAttachmentReversal.attachment_id == row.id)) is not None:
                raise HTTPException(409, '合同附件已撤销')
            add_model(db, SalesOrderContractAttachmentReversal(attachment_id=row.id,
                reason=data.reason, created_by=user['id']))
            return attachment_data(db, row)
    except IntegrityError:
        raise HTTPException(409, '合同附件已撤销') from None
