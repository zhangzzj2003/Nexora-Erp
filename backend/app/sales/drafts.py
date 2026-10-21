"""销售草稿统一版本与审计边界，不修改已确认业务事实。"""

import json

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import document_approval as approval
from app.core.models import AfterSalesCase, SalesDraftChange


class DraftRevisionInput(BaseModel):
    model_config = {'extra': 'forbid'}
    expected_version: int = Field(strict=True, ge=0)
    revision_reason: str = Field(min_length=1, max_length=200)

    @field_validator('revision_reason')
    @classmethod
    def required_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('请填写草稿修订原因')
        return value.strip()


def draft_version(db: Session, kind: str, identifier: int) -> int:
    return db.scalar(select(func.max(SalesDraftChange.version)).where(
        SalesDraftChange.document_type == kind, SalesDraftChange.document_id == identifier)) or 0


def draft_metadata(db: Session, kind: str, identifier: int, status: str) -> dict:
    blocked = ''
    if status != 'draft':
        blocked = '仅未确认的草稿可修订'
    elif kind == 'SalesOrder' and db.scalar(select(AfterSalesCase.id).where(
            AfterSalesCase.replacement_order_id == identifier)):
        blocked = '此订单由售后换货方案生成，请从售后流程更正来源'
    elif kind == 'SalesReturn' and db.scalar(select(AfterSalesCase.id).where(
            AfterSalesCase.sales_return_id == identifier)):
        blocked = '此退货由售后方案生成，请从售后流程更正来源'
    else:
        case = approval.find_case(db, kind, identifier)
        if case and case.status in ('submitted', 'approved'):
            blocked = '单据正在审批或已批准，请先撤回后再修订'
    return {'draft_version': draft_version(db, kind, identifier), 'draft_edit_block_reason': blocked}


def begin_revision(db: Session, kind: str, document, payload: DraftRevisionInput, user_id: int) -> int:
    state = draft_metadata(db, kind, document.id, document.status)
    if state['draft_edit_block_reason']:
        raise HTTPException(409, state['draft_edit_block_reason'])
    if state['draft_version'] != payload.expected_version:
        raise HTTPException(409, '草稿已被其他人修订，请刷新并核对最新内容后重试')
    # 作者记录与正文、版本同事务提交；审批锁定时不能先改正文再检查。
    approval.record_author(db, kind, document.id, user_id)
    return state['draft_version'] + 1


def revision_content(document: dict) -> dict:
    # 只保存可修订正文和当时的展示资料，不把审批进度、库存余额写成草稿变更。
    fields = ('customer_id', 'customer_name', 'sales_order_id', 'shipment_id', 'warehouse_id',
              'warehouse_name', 'reference', 'reason')
    line_fields = ('id', 'shipment_line_id', 'material_id', 'sku', 'material_name', 'unit',
                   'quantity', 'unit_price', 'warranty_days', 'warranty_basis')
    return {**{key: document[key] for key in fields if key in document},
            'lines': [{key: line[key] for key in line_fields if key in line} for line in document['lines']]}


def finish_revision(db: Session, kind: str, identifier: int, version: int, before: dict, after: dict,
                    reason: str, user_id: int) -> None:
    previous, current = revision_content(before), revision_content(after)
    if previous == current:
        raise HTTPException(409, '草稿内容没有变化，无需重复保存')
    db.add(SalesDraftChange(document_type=kind, document_id=identifier, version=version,
        before_json=json.dumps(previous, ensure_ascii=False), after_json=json.dumps(current, ensure_ascii=False),
        reason=reason, changed_by=user_id))
    db.flush()
