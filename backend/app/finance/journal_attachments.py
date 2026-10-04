"""总账凭证的不可变附件及追加式撤销证据。"""

import base64
import binascii
import hashlib
import re

from fastapi import APIRouter, Depends, HTTPException, Path
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.access.security import require
from app.core.models import AccountingPeriod, Journal, JournalAttachment, JournalAttachmentReversal, User
from app.core.orm import add_model, orm_session
from app.finance.journals import get_journal

router = APIRouter(prefix='/api/v1/finance/journals')
MAX_BYTES = 5 * 1024 * 1024
MAX_ATTACHMENTS = 10
FORMATS = {
    '.pdf': 'application/pdf',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
}


def safe_name(value: str) -> str:
    name = value.strip()
    if (not name or len(name) > 120 or name in ('.', '..') or name.endswith('.')
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)):
        raise ValueError('附件文件名无效')
    if not any(name.lower().endswith(suffix) for suffix in FORMATS):
        raise ValueError('仅支持 PDF、PNG 和 JPEG 附件')
    return name


class AttachmentInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    file_name: str = Field(min_length=1, max_length=120)
    content_base64: str = Field(min_length=1, max_length=6_990_508)
    reason: str = Field(min_length=1, max_length=200)

    @field_validator('file_name')
    @classmethod
    def valid_file_name(cls, value: str) -> str:
        return safe_name(value)

    @field_validator('reason')
    @classmethod
    def valid_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('附件依据不能为空')
        return value.strip()


class ReversalInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reason: str = Field(min_length=1, max_length=200)

    @field_validator('reason')
    @classmethod
    def valid_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('撤销原因不能为空')
        return value.strip()


def decode_content(data: AttachmentInput) -> tuple[bytes, str]:
    try:
        content = base64.b64decode(data.content_base64, validate=True)
    except binascii.Error:
        raise HTTPException(422, '附件内容须为 Base64 编码') from None
    if not content or len(content) > MAX_BYTES:
        raise HTTPException(422, '附件须为非空且不超过 5 MiB')
    suffix = '.' + data.file_name.rsplit('.', 1)[-1].lower()
    media_type = FORMATS[suffix]
    valid = (content.startswith(b'%PDF-') and b'%%EOF' in content[-1024:]
        if media_type == 'application/pdf' else
        content.startswith(b'\x89PNG\r\n\x1a\n')
        if media_type == 'image/png' else
        content.startswith(b'\xff\xd8\xff') and content.endswith(b'\xff\xd9'))
    if not valid:
        raise HTTPException(422, '附件内容与文件格式不符')
    return content, media_type


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
