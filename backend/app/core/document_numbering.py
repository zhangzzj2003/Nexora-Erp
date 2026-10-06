"""实例编号规则、时区换算及同事务流水分配。"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones, reset_tzpath

from fastapi import HTTPException
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.core import models
from app.core.document_types import DOCUMENT_TYPES

# 指定时区统一读取随服务打包的 tzdata，避免不同操作系统的时区库版本漂移。
reset_tzpath(())

NUMBERED_MODELS = {getattr(models, name): (table, pinyin, english)
                   for name, table, pinyin, english in DOCUMENT_TYPES}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def business_time(value: datetime, mode: str, zone: str | None) -> datetime:
    # 本机模式每次读取服务器系统时区；指定模式由 IANA 数据处理夏令时。
    if mode == 'server':
        return value.astimezone()
    return value.astimezone(timezone.utc if mode == 'utc' else ZoneInfo(zone))


def document_date(value: str | None, config) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        local = business_time(parsed, config.timezone_mode, config.timezone)
        # 早年历史时间在各平台的 strftime 年份补零行为不同，明确保证八位日期。
        return f'{local.year:04d}{local.month:02d}{local.day:02d}'
    except (ValueError, TypeError, AttributeError, OverflowError):
        # 缺失日期不能伪造为升级当天；单号仍保持稳定且可查询。
        return '00000000'


def configuration(db: Session):
    return db.get(models.DocumentNumberingSetting, 1)


def configuration_data(db: Session) -> dict:
    record = configuration(db)
    now = utc_now()
    selected = business_time(now, record.timezone_mode, record.timezone) if record and record.style else now.astimezone()
    return {'configured': bool(record and record.style), 'style': record.style if record else None,
            'timezone_mode': record.timezone_mode if record else 'server',
            'timezone': record.timezone if record else None,
            'version': record.version if record else 0, 'locked': bool(record and record.locked),
            'configured_by': record.configured_by if record else None,
            'configured_at': record.configured_at if record else None,
            'server_time': now.astimezone().isoformat(), 'business_time': selected.isoformat(),
            'business_date': selected.strftime('%Y%m%d'),
            'timezones': sorted(available_timezones()),
            'backfilled_count': record.backfilled_count if record else 0,
            'undated_count': record.undated_count if record else 0}


def next_number(db: Session, model_type, created_at: str, config) -> str:
    table, pinyin, english = NUMBERED_MODELS[model_type]
    date = document_date(created_at, config)
    key = (table, date)
    # before_flush 内未提交的序列表也须复用，保证一次转单多张主单不会分到同号。
    cache = db.info.setdefault('document_sequences', {})
    sequence = cache.get(key)
    if sequence is None:
        sequence = db.get(models.DocumentNumberSequence, key)
        if sequence is None:
            sequence = models.DocumentNumberSequence(document_type=table, business_date=date, last_number=0)
            db.add(sequence)
        cache[key] = sequence
    sequence.last_number += 1
    prefix = pinyin if config.style == 'pinyin' else english
    config.locked = True
    return f'{prefix}-{date}-{sequence.last_number:06d}'


def assign_documents(db: Session, *_):
    # 只处理白名单主单，审计明细、流水、附件和批次不取得业务单号。
    fresh = [row for row in db.new if type(row) in NUMBERED_MODELS]
    for row in db.dirty:
        if (not db.info.get('backfilling_documents') and type(row) in NUMBERED_MODELS
                and inspect(row).attrs.document_no.history.has_changes()):
            raise HTTPException(409, '业务单号生成后不能修改')
    if not fresh:
        return
    config = configuration(db)
    if not config or not config.style:
        raise HTTPException(409, '请先由管理员设置单据编号规则')
    for row in fresh:
        # 生成时间和数据库创建时间采用同一个 UTC 时刻，避免午夜跨日。
        if row.document_no is not None:
            raise HTTPException(422, '业务单号由服务端自动生成，不能指定')
        if not row.created_at:
            row.created_at = utc_now().strftime('%Y-%m-%d %H:%M:%S')
        row.document_no = next_number(db, type(row), row.created_at, config)


def historical_order(row):
    # 老记录可能混用 UTC 文本与带偏移的 ISO 时间，按真实创建时刻再按 ID 排序。
    try:
        value = datetime.fromisoformat(row.created_at.replace('Z', '+00:00'))
        return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc), row.id)
    except (ValueError, TypeError, AttributeError, OverflowError):
        return (datetime.min.replace(tzinfo=timezone.utc), row.id)


def save_configuration(db: Session, payload, user: dict) -> dict:
    record = configuration(db)
    current_version = record.version if record else 0
    if payload.version != current_version:
        raise HTTPException(409, '编号规则已由其他管理员修改，请重新读取')
    if record and record.locked:
        raise HTTPException(409, '已有业务单号，编号规则已锁定')
    if payload.timezone_mode == 'specified':
        try:
            ZoneInfo(payload.timezone or '')
        except (ZoneInfoNotFoundError, ValueError):
            raise HTTPException(422, '请选择有效的 IANA 时区') from None
    elif payload.timezone is not None:
        raise HTTPException(422, '只有指定时区模式可以填写时区')
    if record is None:
        record = models.DocumentNumberingSetting(id=1, version=0, locked=False,
                                                backfilled_count=0, undated_count=0)
        db.add(record)
    record.style, record.timezone_mode, record.timezone = payload.style, payload.timezone_mode, payload.timezone
    record.version += 1
    record.configured_by, record.configured_at = user['id'], utc_now().strftime('%Y-%m-%d %H:%M:%S')
    db.flush()
    # 补号与规则保存处于同一写事务；不触碰原凭据、数量、状态和固定 JSON 快照。
    for model_type in NUMBERED_MODELS:
        for row in sorted(db.scalars(select(model_type).where(model_type.document_no.is_(None))), key=historical_order):
            date = document_date(row.created_at, record)
            row.document_no = next_number(db, model_type, row.created_at, record)
            record.backfilled_count += 1
            record.undated_count += int(date == '00000000')
            # 历史补号是唯一允许修改空编号的受控边界。
            db.info['backfilling_documents'] = True
        db.flush()
    db.info.pop('backfilling_documents', None)
    return configuration_data(db)
