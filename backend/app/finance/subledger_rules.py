"""分户启用的跨模块约束；复用调用方事务，不依赖路由模块。"""

import json
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.models import SubledgerOpening


def active_subledger(db: Session) -> SubledgerOpening | None:
    return db.scalar(select(SubledgerOpening).where(SubledgerOpening.active_key == 1))


def check_subledger(db: Session, date: str | None = None) -> None:
    record = active_subledger(db)
    if record is None:
        if db.scalar(select(SubledgerOpening.id).where(SubledgerOpening.status == 'reversed').limit(1)) is not None:
            raise HTTPException(409, '原分户期初已撤销，须先确认替代方案')
        return
    if record.status != 'confirmed':
        raise HTTPException(409, '分户期初尚未确认，须先完成独立审核确认或取消未启用方案')
    if date is not None and date[:10] < record.effective_date:
        raise HTTPException(409, '业务日期不能早于分户启用日')


def protect_opening(db: Session, identifier: int) -> None:
    record = active_subledger(db)
    if record and record.opening_balance_id == identifier:
        raise HTTPException(409, '总账期初已被有效分户方案引用，须先取消或撤销分户方案')


def validate_control_mapping(control_accounts: list[dict], mapping: dict) -> None:
    identifiers: dict[str, set[int]] = {}
    for item in control_accounts:
        identifiers.setdefault(item['kind'], set()).add(item['account_id'])
    for kind, selected in identifiers.items():
        if kind in mapping and mapping[kind] not in selected:
            raise HTTPException(409, '业务凭证应收应付科目须属于分户期初的对应控制范围')


def check_control_mapping(db: Session, mapping: dict) -> None:
    record = active_subledger(db)
    if record is not None:
        validate_control_mapping(json.loads(record.control_accounts_json), mapping)
