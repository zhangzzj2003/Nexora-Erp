"""报价附件留存；原件与撤销证据分别追加保存。"""

import hashlib

from fastapi import APIRouter, Depends, HTTPException, Path
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.access.security import require
from app.core.attachment_files import AttachmentInput, ReversalInput, decode_content, MAX_ATTACHMENTS
from app.core.models import CrmQuote, CrmQuoteAttachment, CrmQuoteAttachmentReversal, User
from app.core.orm import add_model, orm_session
from app.sales.crm_rules import get_record

router = APIRouter(prefix='/api/v1/crm/quotes')


def visible_quote(db: Session, quote_id: int, user: dict) -> CrmQuote:
    if 'crm.view' not in user['permissions']:
        raise HTTPException(403, '没有执行此操作的权限')
    return get_record(db, 'quote', quote_id, user=user)


def modifiable(quote: CrmQuote) -> bool:
    # 附件不参与报价正文冻结或独立审核；终态只保留历史查阅。
    return quote.status in ('draft', 'submitted', 'approved', 'rejected')


def attachment_data(db: Session, row: CrmQuoteAttachment) -> dict:
    reversal = db.scalar(select(CrmQuoteAttachmentReversal).where(
        CrmQuoteAttachmentReversal.attachment_id == row.id))
    return dict(id=row.id, quote_id=row.quote_id, file_name=row.file_name,
        media_type=row.media_type, byte_count=row.byte_count, sha256=row.sha256,
        reason=row.reason, created_by=row.created_by, created_at=row.created_at,
        created_by_name=db.scalar(select(User.username).where(User.id == row.created_by)),
        reversal=(dict(id=reversal.id, reason=reversal.reason, created_by=reversal.created_by,
            created_at=reversal.created_at,
            created_by_name=db.scalar(select(User.username).where(User.id == reversal.created_by)))
            if reversal else None))


def get_attachment(db: Session, quote_id: int, attachment_id: int) -> CrmQuoteAttachment:
    row = db.get(CrmQuoteAttachment, attachment_id)
    if row is None or row.quote_id != quote_id:
        raise HTTPException(404, '报价附件不存在')
    return row


@router.get('/{quote_id}/attachments')
def list_attachments(quote_id: int = Path(gt=0),
        user: dict = Depends(require('crm.view'))) -> dict:
    with orm_session() as db:
        quote = visible_quote(db, quote_id, user)
        rows = db.scalars(select(CrmQuoteAttachment).where(
            CrmQuoteAttachment.quote_id == quote_id).order_by(CrmQuoteAttachment.id)).all()
        return dict(quote_id=quote_id, can_modify=modifiable(quote),
            items=[attachment_data(db, row) for row in rows])


@router.post('/{quote_id}/attachments', status_code=201)
def add_attachment(data: AttachmentInput, quote_id: int = Path(gt=0),
        user: dict = Depends(require('crm_quote.attachment'))) -> dict:
    content, media_type = decode_content(data)
    digest = hashlib.sha256(content).hexdigest()
    with orm_session(write=True) as db:
        quote = visible_quote(db, quote_id, user)
        if not modifiable(quote):
            raise HTTPException(409, '报价已取消或转单，不能添加附件')
        active = select(CrmQuoteAttachment.id).where(
            CrmQuoteAttachment.quote_id == quote_id,
            ~select(CrmQuoteAttachmentReversal.id).where(
                CrmQuoteAttachmentReversal.attachment_id == CrmQuoteAttachment.id).exists())
        if db.scalar(select(func.count()).select_from(active.subquery())) >= MAX_ATTACHMENTS:
            raise HTTPException(409, '单张报价最多保留 10 个有效附件')
        if db.scalar(active.where(CrmQuoteAttachment.sha256 == digest).limit(1)) is not None:
            raise HTTPException(409, '此报价已有相同内容的有效附件')
        row = add_model(db, CrmQuoteAttachment(quote_id=quote_id,
            file_name=data.file_name, media_type=media_type, byte_count=len(content),
            sha256=digest, content=content, reason=data.reason, created_by=user['id']))
        return attachment_data(db, row)


@router.get('/{quote_id}/attachments/{attachment_id}')
def download_attachment(quote_id: int = Path(gt=0), attachment_id: int = Path(gt=0),
        user: dict = Depends(require('crm.view'))) -> Response:
    with orm_session() as db:
        visible_quote(db, quote_id, user)
        row = get_attachment(db, quote_id, attachment_id)
        if len(row.content) != row.byte_count or hashlib.sha256(row.content).hexdigest() != row.sha256:
            raise HTTPException(409, '附件内容校验失败，请联系管理员检查备份')
        suffix = '.' + row.file_name.rsplit('.', 1)[-1].lower()
        return Response(content=row.content, media_type='application/octet-stream', headers={
            'Cache-Control': 'no-store',
            'Content-Disposition': f'attachment; filename="crm-quote-{quote_id}-{attachment_id}{suffix}"',
            'X-Nexora-SHA256': row.sha256, 'X-Nexora-File-Extension': suffix,
        })


@router.post('/{quote_id}/attachments/{attachment_id}/reverse', status_code=201)
def reverse_attachment(data: ReversalInput, quote_id: int = Path(gt=0),
        attachment_id: int = Path(gt=0),
        user: dict = Depends(require('crm_quote.attachment'))) -> dict:
    try:
        with orm_session(write=True) as db:
            quote = visible_quote(db, quote_id, user)
            row = get_attachment(db, quote_id, attachment_id)
            if not modifiable(quote):
                raise HTTPException(409, '报价已取消或转单，不能撤销附件')
            if db.scalar(select(CrmQuoteAttachmentReversal.id).where(
                    CrmQuoteAttachmentReversal.attachment_id == row.id)) is not None:
                raise HTTPException(409, '附件已撤销')
            add_model(db, CrmQuoteAttachmentReversal(attachment_id=row.id,
                reason=data.reason, created_by=user['id']))
            return attachment_data(db, row)
    except IntegrityError:
        raise HTTPException(409, '附件已撤销') from None
