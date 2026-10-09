"""历史原单票据的固定来源、审批兼容和期间证据。"""

import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import document_approval as approval
from app.core.models import (DocumentApprovalCase, SubledgerAttachment, SubledgerAttachmentReversal,
    SubledgerOpening, SubledgerOpeningLine)
from app.core.period_lock import ensure_date_unlocked


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value) -> str:
    return hashlib.sha256(encode(value).encode('utf-8')).hexdigest()


def source_for(record: SubledgerOpening, line: SubledgerOpeningLine) -> dict:
    from app.finance.subledger_openings import line_data
    line = line_data(line)
    return {key: line[key] for key in ('id', 'kind', 'party_id', 'party_name', 'account_id',
        'account_code', 'account_name', 'document_reference', 'document_date', 'debit', 'credit', 'auxiliary')} | {
        'opening_id': record.id, 'opening_version': record.version, 'opening_balance_id': record.opening_balance_id,
        'ledger_opening_version': record.opening_version, 'effective_date': record.effective_date, 'currency': 'CNY'}


def origin_key(source: dict) -> str:
    return digest([source['kind'], source['party_id'], source['document_reference']])


def fingerprint(source: dict) -> str:
    # 行号、基础资料显示名称和辅助项顺序不属于财务来源身份。
    return digest({key: source[key] for key in ('kind', 'party_id', 'account_id', 'document_reference',
        'document_date', 'debit', 'credit', 'opening_balance_id', 'ledger_opening_version', 'effective_date', 'currency')} | {
        'auxiliary': sorted((item['kind'], item['id']) for item in source['auxiliary'])})


def current_sources(db: Session, record: SubledgerOpening) -> list[dict]:
    return [source_for(record, line) for line in db.scalars(select(SubledgerOpeningLine).where(
        SubledgerOpeningLine.opening_id == record.id).order_by(SubledgerOpeningLine.position))]


def match_source(row: SubledgerAttachment, sources: dict[str, dict]) -> tuple[str, int | None]:
    source = sources.get(row.origin_key)
    return ('missing', None) if source is None else (
        'matched' if fingerprint(source) == row.source_fingerprint else 'changed', source['id'])


def pending(db: Session, identifier: int) -> bool:
    return db.scalar(select(DocumentApprovalCase.id).where(
        DocumentApprovalCase.document_type == 'SubledgerOpening', DocumentApprovalCase.document_id == identifier,
        DocumentApprovalCase.status.in_(('submitted', 'approved'))).limit(1)) is not None


def modifiable(db: Session, record: SubledgerOpening) -> bool:
    if record.status not in ('draft', 'rejected', 'confirmed') or pending(db, record.id):
        return False
    try:
        ensure_date_unlocked(db, approval.now(db))
        if record.status != 'confirmed':
            ensure_date_unlocked(db, record.effective_date)
    except HTTPException:
        return False
    return True


def executed_snapshot(db: Session, identifier: int) -> dict | None:
    case = db.scalar(select(DocumentApprovalCase).where(DocumentApprovalCase.document_type == 'SubledgerOpening',
        DocumentApprovalCase.document_id == identifier, DocumentApprovalCase.intent == 'execute',
        DocumentApprovalCase.status == 'executed'))
    return json.loads(case.snapshot_json) if case else None


def frozen_ids(db: Session, identifier: int) -> set[int]:
    return {item['id'] for item in (executed_snapshot(db, identifier) or {}).get('attachments', [])}


def reversals_for(db: Session, identifiers: list[int], cutoff: str | None = None) -> dict:
    if not identifiers:
        return {}
    query = select(SubledgerAttachmentReversal).where(SubledgerAttachmentReversal.attachment_id.in_(identifiers))
    if cutoff:
        query = query.where(SubledgerAttachmentReversal.created_at < cutoff)
    return {row.attachment_id: row for row in db.scalars(query)}


def evidence(row: SubledgerAttachment, reversal: SubledgerAttachmentReversal | None) -> dict:
    return dict(id=row.id, opening_id=row.opening_id, source=json.loads(row.source_json),
        file_name=row.file_name, media_type=row.media_type, byte_count=row.byte_count, sha256=row.sha256,
        reason=row.reason, created_by=row.created_by, created_at=row.created_at,
        reversal=(dict(id=reversal.id, reason=reversal.reason, created_by=reversal.created_by,
            created_at=reversal.created_at) if reversal else None))


def approval_evidence(db: Session, identifier: int) -> list[dict] | None:
    executed = executed_snapshot(db, identifier)
    if executed is not None:
        # v97 已批准正文没有附件键；补录不得使旧摘要或原批准作者失效。
        return executed.get('attachments')
    rows = list(db.scalars(select(SubledgerAttachment).where(
        SubledgerAttachment.opening_id == identifier).order_by(SubledgerAttachment.id)))
    reversals = reversals_for(db, [row.id for row in rows])
    return [evidence(row, reversals.get(row.id)) for row in rows] if rows else None


def validate_sources(db: Session, record: SubledgerOpening) -> None:
    sources = {origin_key(source): source for source in current_sources(db, record)}
    rows = db.scalars(select(SubledgerAttachment).where(SubledgerAttachment.opening_id == record.id,
        ~select(SubledgerAttachmentReversal.id).where(
            SubledgerAttachmentReversal.attachment_id == SubledgerAttachment.id).exists()))
    if any(match_source(row, sources)[0] != 'matched' for row in rows):
        raise HTTPException(409, '有效票据的原单来源已修改或移除，请先追加撤销并按当前原单重新上传')


def archive_evidence(db: Session, end_date: str) -> list[dict]:
    cutoff = end_date + ' 24:00:00'
    rows = list(db.scalars(select(SubledgerAttachment).where(
        SubledgerAttachment.created_at < cutoff).order_by(SubledgerAttachment.id)))
    reversals = reversals_for(db, [row.id for row in rows], cutoff)
    return [evidence(row, reversals.get(row.id)) for row in rows]
