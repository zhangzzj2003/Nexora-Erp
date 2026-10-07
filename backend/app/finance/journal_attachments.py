"""总账凭证的不可变附件及追加式撤销证据。"""

from app.core.document_responses import NumberedRoute
import hashlib

from fastapi import APIRouter, Depends, HTTPException, Path
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.access.security import require
from app.core.attachment_files import AttachmentInput, ReversalInput, decode_content, MAX_ATTACHMENTS
from app.core.models import AccountingPeriod, Journal, JournalAttachment, JournalAttachmentReversal, User
from app.core.orm import add_model, orm_session
from app.finance.journals import get_journal

router = APIRouter(route_class=NumberedRoute, prefix='/api/v1/finance/journals')


def modifiable(db: Session, journal: Journal) -> bool:
    period = db.get(AccountingPeriod, journal.period_id)
    return bool(journal.status != 'cancelled' and period and period.status == 'open'
        and period.start_date <= journal.journal_date <= period.end_date)


def attachment_data(db: Session, row: JournalAttachment) -> dict:
    reversal = db.scalar(select(JournalAttachmentReversal).where(
        JournalAttachmentReversal.attachment_id == row.id))
    return dict(id=row.id, journal_id=row.journal_id, file_name=row.file_name,
        media_type=row.media_type, byte_count=row.byte_count, sha256=row.sha256,
        reason=row.reason, created_by=row.created_by, created_at=row.created_at,
        created_by_name=db.scalar(select(User.username).where(User.id == row.created_by)),
        reversal=(dict(id=reversal.id, reason=reversal.reason, created_by=reversal.created_by,
            created_at=reversal.created_at,
            created_by_name=db.scalar(select(User.username).where(User.id == reversal.created_by)))
            if reversal else None))


def get_attachment(db: Session, journal_id: int, attachment_id: int) -> JournalAttachment:
    row = db.get(JournalAttachment, attachment_id)
    if row is None or row.journal_id != journal_id:
        raise HTTPException(404, '凭证附件不存在')
    return row


@router.get('/{journal_id}/attachments')
def list_attachments(journal_id: int = Path(gt=0),
        _: dict = Depends(require('journal.view'))) -> dict:
    with orm_session() as db:
        journal = get_journal(db, journal_id)
        rows = db.scalars(select(JournalAttachment).where(
            JournalAttachment.journal_id == journal_id).order_by(JournalAttachment.id)).all()
        return dict(journal_id=journal_id, can_modify=modifiable(db, journal),
            items=[attachment_data(db, row) for row in rows])


@router.post('/{journal_id}/attachments', status_code=201)
def add_attachment(data: AttachmentInput, journal_id: int = Path(gt=0),
        user: dict = Depends(require('journal.attachment')),
        _: dict = Depends(require('journal.view'))) -> dict:
    content, media_type = decode_content(data)
    digest = hashlib.sha256(content).hexdigest()
    with orm_session(write=True) as db:
        journal = get_journal(db, journal_id)
        if not modifiable(db, journal):
            raise HTTPException(409, '凭证已取消或期间已结账，不能添加附件')
        active = select(JournalAttachment.id).where(
            JournalAttachment.journal_id == journal_id,
            ~select(JournalAttachmentReversal.id).where(
                JournalAttachmentReversal.attachment_id == JournalAttachment.id).exists())
        if db.scalar(select(func.count()).select_from(active.subquery())) >= MAX_ATTACHMENTS:
            raise HTTPException(409, '单张凭证最多保留 10 个有效附件')
        if db.scalar(active.where(JournalAttachment.sha256 == digest).limit(1)) is not None:
            raise HTTPException(409, '此凭证已有相同内容的有效附件')
        row = add_model(db, JournalAttachment(journal_id=journal_id,
            file_name=data.file_name, media_type=media_type, byte_count=len(content),
            sha256=digest, content=content, reason=data.reason, created_by=user['id']))
        return attachment_data(db, row)


@router.get('/{journal_id}/attachments/{attachment_id}')
def download_attachment(journal_id: int = Path(gt=0), attachment_id: int = Path(gt=0),
        _: dict = Depends(require('journal.view'))) -> Response:
    with orm_session() as db:
        get_journal(db, journal_id)
        row = get_attachment(db, journal_id, attachment_id)
        if len(row.content) != row.byte_count or hashlib.sha256(row.content).hexdigest() != row.sha256:
            raise HTTPException(409, '附件内容校验失败，请联系管理员检查备份')
        suffix = '.' + row.file_name.rsplit('.', 1)[-1].lower()
        return Response(content=row.content, media_type='application/octet-stream', headers={
            'Cache-Control': 'no-store', 'Content-Disposition': f'attachment; filename="journal-{journal_id}-{attachment_id}{suffix}"',
            'X-Nexora-SHA256': row.sha256, 'X-Nexora-File-Extension': suffix,
        })


@router.post('/{journal_id}/attachments/{attachment_id}/reverse', status_code=201)
def reverse_attachment(data: ReversalInput, journal_id: int = Path(gt=0),
        attachment_id: int = Path(gt=0), user: dict = Depends(require('journal.attachment')),
        _: dict = Depends(require('journal.view'))) -> dict:
    try:
        with orm_session(write=True) as db:
            journal = get_journal(db, journal_id)
            row = get_attachment(db, journal_id, attachment_id)
            if not modifiable(db, journal):
                raise HTTPException(409, '凭证已取消或期间已结账，不能撤销附件')
            if db.scalar(select(JournalAttachmentReversal.id).where(
                    JournalAttachmentReversal.attachment_id == row.id)) is not None:
                raise HTTPException(409, '附件已撤销')
            add_model(db, JournalAttachmentReversal(attachment_id=row.id,
                reason=data.reason, created_by=user['id']))
            return attachment_data(db, row)
    except IntegrityError:
        raise HTTPException(409, '附件已撤销') from None
