"""重分类后的资金选择实际完整余额组合；旧资金不自动回填或改写。"""

import json
from decimal import Decimal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.finance.auxiliary_rules import AuxiliaryReference, combination


def scope_key(account_id: int, auxiliary: list) -> tuple:
    return account_id, combination(auxiliary)


class FundsScopeChoice(BaseModel):
    model_config = ConfigDict(extra='forbid')
    account_id: int = Field(gt=0, strict=True)
    auxiliary: list[AuxiliaryReference] = Field(min_length=1, max_length=4)
    fingerprint: str = Field(pattern=r'^[0-9a-f]{64}$')

    @field_validator('auxiliary')
    @classmethod
    def unique_kinds(cls, values):
        if len({item.kind for item in values}) != len(values):
            raise ValueError('每类辅助信息只能选择一个')
        return sorted(values, key=lambda item: item.kind)


def touched_origin(db: Session, key: tuple) -> bool:
    from app.finance.control_balance_projection import executed_transfers, saved_origin
    return any(key in (saved_origin(json.loads(row.from_scope_json)), saved_origin(json.loads(row.to_scope_json)))
        for row in executed_transfers(db))


def select_scope(db: Session, kind: str, source_type: str, identifier: int,
                 choice: FundsScopeChoice | None) -> str | None:
    from app.finance.control_balance_projection import encode, group_data, origin_key, project_origins
    key = origin_key(kind, source_type, identifier)
    if choice is None:
        if touched_origin(db, key):
            raise HTTPException(409, '原单已有组合转账，请明确选择真实余额组合，不能沿用旧科目默认值')
        return None
    origin = project_origins(db, for_funds=True).get(key)
    if origin is None or origin.blockers:
        raise HTTPException(409, '资金归属缺少可核对的完整组合来源')
    group = origin.groups.get(scope_key(choice.account_id, choice.auxiliary))
    if group is None:
        raise HTTPException(409, '所选资金组合不存在')
    public = group_data(origin, group)
    if public['fingerprint'] != choice.fingerprint:
        raise HTTPException(409, '资金组合金额或来源已变化，请刷新核对后编制')
    return encode({key: public[key] for key in ('kind', 'source_type', 'source_id', 'party_id',
        'account_id', 'auxiliary', 'evidence')})


def validate_funds(db: Session, row, kind: str, source_type: str, identifier: int) -> bool:
    from app.finance.control_balance_projection import origin_key, project_origins, saved_origin
    key = origin_key(kind, source_type, identifier)
    if row.control_scope_json is None:
        if row.reverses_id is not None:
            protect_payment(db, 'payment_record' if source_type == 'order' else 'subledger_payment', row.reverses_id)
            return False
        if touched_origin(db, key):
            raise HTTPException(409, '旧资金草稿未固定转账后的组合，须取消后重新编制')
        return False
    fixed = json.loads(row.control_scope_json)
    origin = project_origins(db, for_funds=True).get(key)
    if origin is None or origin.blockers or saved_origin(fixed) != key or fixed['party_id'] != origin.party_id:
        raise HTTPException(409, '固定资金组合原来源或往来身份已变化')
    group = origin.groups.get(scope_key(fixed['account_id'], fixed['auxiliary']))
    if group is None:
        raise HTTPException(409, '固定资金组合已无真实来源')
    if row.reverses_id is None:
        limit = group.amount if row.action == 'settlement' else -group.amount
        if abs(Decimal(row.amount)) > limit:
            raise HTTPException(409, '资金超过所选完整组合最新可用余额')
    else:
        protect_payment(db, 'payment_record' if source_type == 'order' else 'subledger_payment', row.reverses_id)
    return True


def protect_payment(db: Session, source_type: str, identifier: int) -> None:
    from app.finance.control_balance_transfers import active_transfers
    for transfer in active_transfers(db):
        evidence = json.loads(transfer.evidence_json)
        for side in ('source', 'target'):
            if any(item.get('source_key') == f'{source_type}:{identifier}' or
                    item.get('type') == 'historical_payment' and source_type == 'subledger_payment' and item.get('payment_id') == identifier
                    for item in evidence[side]['evidence']):
                raise HTTPException(409, '资金已成为生效组合转账依据，请先倒序更正转账')


def ensure_legacy_origin(db: Session, kind: str, source_type: str, identifier: int) -> None:
    # 旧核销仅保存原科目或订单身份，无法表达重分类后明确的组合选择。
    # 新组合之间的分配从完整转账入口办理，不能拿原单净额替代旧组合额度。
    from app.finance.control_balance_transfers import active_transfers
    from app.finance.control_balance_projection import origin_key, saved_origin
    key = origin_key(kind, source_type, identifier)
    if any(key in (saved_origin(json.loads(row.from_scope_json)), saved_origin(json.loads(row.to_scope_json)))
            for row in active_transfers(db)):
        raise HTTPException(409, '此原单已有生效组合转账，请从往来余额转账入口选择完整组合办理或先倒序更正')
