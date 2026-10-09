"""历史原单附件：原件不可改写，更正仅追加撤销，草稿按完整来源核对。"""

import hashlib

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import Response
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.access.security import require
from app.core import document_approval as approval
from app.core.attachment_files import AttachmentInput, ReversalInput, decode_content, MAX_ATTACHMENTS
from app.core.document_responses import NumberedRoute
from app.core.models import SubledgerAttachment, SubledgerAttachmentReversal, SubledgerOpeningLine, User
from app.core.orm import add_model, orm_session
from app.finance import subledger_attachment_rules as rules
from app.finance.subledger_openings import get_record

router = APIRouter(route_class=NumberedRoute, prefix='/api/v1/finance/subledger-openings')


class UploadInput(AttachmentInput):
    opening_version: int = Field(gt=0, strict=True)
    line_id: int = Field(gt=0, strict=True)


class ReverseInput(ReversalInput):
    opening_version: int = Field(gt=0, strict=True)


def access_actor(db: Session, user: dict, *, write: bool = False) -> dict:
    # 依赖授权与写锁之间可能发生撤权，必须在同一业务事务内重新核对。
    current = approval.actor(db, user['id'], 'subledger_opening.view')
    if write and 'subledger_opening.attachment' not in current['permissions']:
        raise HTTPException(403, '没有维护历史原单附件的权限')
    return current


def get_attachment(db: Session, opening_id: int, identifier: int) -> SubledgerAttachment:
    row = db.get(SubledgerAttachment, identifier)
    if row is None or row.opening_id != opening_id:
        raise HTTPException(404, '原单附件不存在')
    return row


def active_query(identifier: int):
    return select(SubledgerAttachment).where(SubledgerAttachment.opening_id == identifier,
        ~select(SubledgerAttachmentReversal.id).where(
            SubledgerAttachmentReversal.attachment_id == SubledgerAttachment.id).exists())


def projection(db: Session, record, rows: list, user: dict) -> list[dict]:
    sources = {rules.origin_key(source): source for source in rules.current_sources(db, record)}
    reversals = rules.reversals_for(db, [row.id for row in rows])
    actor_ids = {row.created_by for row in rows} | {row.created_by for row in reversals.values()}
    names = dict(db.execute(select(User.id, User.username).where(User.id.in_(actor_ids))).all())
    can_modify = 'subledger_opening.attachment' in user['permissions'] and rules.modifiable(db, record)
    frozen = rules.frozen_ids(db, record.id)
    result = []
    for row in rows:
        status, current_line_id = rules.match_source(row, sources)
        data = rules.evidence(row, reversals.get(row.id))
        data.update(source_status=status, current_line_id=current_line_id,
            created_by_name=names.get(row.created_by), approved_original=row.id in frozen,
            can_reverse=can_modify and row.id not in frozen and row.id not in reversals)
        if data['reversal']:
            data['reversal']['created_by_name'] = names.get(reversals[row.id].created_by)
        result.append(data)
    return result


@router.get('/{opening_id}/attachments')
def list_attachments(opening_id: int = Path(gt=0), page: int = Query(default=1, ge=1, le=1000000),
        page_size: int = Query(default=50, ge=1, le=100), user: dict = Depends(require('subledger_opening.view'))) -> dict:
    with orm_session() as db:
        user = access_actor(db, user)
        record = get_record(db, opening_id)
        query = select(SubledgerAttachment).where(SubledgerAttachment.opening_id == opening_id)
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        rows = list(db.scalars(query.order_by(SubledgerAttachment.id.desc()).offset((page - 1) * page_size).limit(page_size)))
        active = list(db.scalars(active_query(opening_id)))
        sources = rules.current_sources(db, record)
        source_map = {rules.origin_key(source): source for source in sources}
        return dict(opening_id=opening_id, opening_version=record.version, opening_status=record.status,
            can_modify='subledger_opening.attachment' in user['permissions'] and rules.modifiable(db, record),
            page=page, page_size=page_size, total=total, active_count=len(active),
            changed_count=sum(rules.match_source(row, source_map)[0] != 'matched' for row in active),
            lines=sources, items=projection(db, record, rows, user))


@router.post('/{opening_id}/attachments', status_code=201)
def add_attachment(data: UploadInput, opening_id: int = Path(gt=0),
        user: dict = Depends(require('subledger_opening.attachment')),
        _: dict = Depends(require('subledger_opening.view'))) -> dict:
    content, media_type = decode_content(data)
    sha256 = hashlib.sha256(content).hexdigest()
    with orm_session(write=True) as db:
        user = access_actor(db, user, write=True)
        record = get_record(db, opening_id, data.opening_version)
        if not rules.modifiable(db, record):
            raise HTTPException(409, '审批期间、已撤销或日期已锁定，不能添加原单附件')
        line = db.get(SubledgerOpeningLine, data.line_id)
        if line is None or line.opening_id != record.id:
            raise HTTPException(404, '当前方案原单不存在，请刷新后重试')
        source = rules.source_for(record, line)
        key = rules.origin_key(source)
        active = active_query(opening_id).where(SubledgerAttachment.origin_key == key)
        if db.scalar(select(func.count()).select_from(active.subquery())) >= MAX_ATTACHMENTS:
            raise HTTPException(409, '每张历史原单最多保留 10 个有效附件')
        if db.scalar(active.where(SubledgerAttachment.sha256 == sha256).limit(1)) is not None:
            raise HTTPException(409, '此历史原单已有相同内容的有效附件')
        row = add_model(db, SubledgerAttachment(opening_id=opening_id, origin_key=key,
            source_fingerprint=rules.fingerprint(source), source_json=rules.encode(source),
            file_name=data.file_name, media_type=media_type, byte_count=len(content), sha256=sha256,
            content=content, reason=data.reason, created_by=user['id']))
        if record.status != 'confirmed':
            approval.record_author(db, 'SubledgerOpening', opening_id, user['id'])
        return projection(db, record, [row], user)[0]


@router.get('/{opening_id}/attachments/{attachment_id}')
def download_attachment(opening_id: int = Path(gt=0), attachment_id: int = Path(gt=0),
        user: dict = Depends(require('subledger_opening.view'))) -> Response:
    with orm_session() as db:
        access_actor(db, user)
        get_record(db, opening_id)
        row = get_attachment(db, opening_id, attachment_id)
        if len(row.content) != row.byte_count or hashlib.sha256(row.content).hexdigest() != row.sha256:
            raise HTTPException(409, '附件内容校验失败，请联系管理员检查备份')
        suffix = '.' + row.file_name.rsplit('.', 1)[-1].lower()
        return Response(content=row.content, media_type='application/octet-stream', headers={
            'Cache-Control': 'no-store', 'Content-Disposition': f'attachment; filename="subledger-{opening_id}-{attachment_id}{suffix}"',
            'X-Nexora-SHA256': row.sha256, 'X-Nexora-File-Extension': suffix})


@router.post('/{opening_id}/attachments/{attachment_id}/reverse', status_code=201)
def reverse_attachment(data: ReverseInput, opening_id: int = Path(gt=0), attachment_id: int = Path(gt=0),
        user: dict = Depends(require('subledger_opening.attachment')),
        _: dict = Depends(require('subledger_opening.view'))) -> dict:
    with orm_session(write=True) as db:
        user = access_actor(db, user, write=True)
        record = get_record(db, opening_id, data.opening_version)
        row = get_attachment(db, opening_id, attachment_id)
        if not rules.modifiable(db, record) or row.id in rules.frozen_ids(db, opening_id):
            raise HTTPException(409, '原批准附件、审批期间、已撤销或日期已锁定，不能撤销附件')
        if rules.reversals_for(db, [row.id]):
            raise HTTPException(409, '附件已撤销')
        add_model(db, SubledgerAttachmentReversal(attachment_id=row.id, reason=data.reason, created_by=user['id']))
        if record.status != 'confirmed':
            approval.record_author(db, 'SubledgerOpening', opening_id, user['id'])
        return projection(db, record, [row], user)[0]
