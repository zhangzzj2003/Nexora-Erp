"""实例级单据审批模板；领域业务接口随后接入同一事务服务。"""

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.access.security import current_user
from app.core.approval_catalog import APPROVAL_TYPES, approval_type
from app.core.document_approval import actor, policy, policy_data, save_policy
from app.core import document_approval as workflow
from app.core.approval_documents import (
    current_snapshot, document_pending, document_snapshot, document_source, document_summary, submit_permission,
    native_review_evidence, sync_native_review,
)
from app.core.models import DocumentApprovalAuthor, DocumentApprovalEvent, DocumentApprovalPolicy, User
from app.core.orm import orm_session

router = APIRouter(prefix='/api/v1/system/document-approvals')


class ApprovalStepInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=40)
    role: str | None = Field(default=None, min_length=1, max_length=100)


class ApprovalPolicyInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: int = Field(ge=1, strict=True)
    steps: list[ApprovalStepInput] = Field(min_length=1, max_length=5)


@router.get('')
def list_policies(user: dict = Depends(current_user)) -> list[dict]:
    with orm_session() as db:
        user = actor(db, user['id'])
        # 普通人员只看到原领域可查看的模板，模板入口不会扩大单据权限。
        return [{**policy_data(row), 'title': APPROVAL_TYPES[row.document_type].title}
                for row in db.scalars(select(DocumentApprovalPolicy).order_by(DocumentApprovalPolicy.document_type))
                if row.document_type in APPROVAL_TYPES and ('admin' in user['roles'] or
                   APPROVAL_TYPES[row.document_type].view_permission in user['permissions'])]


@router.get('/{document_type}')
def get_policy(document_type: str, user: dict = Depends(current_user)) -> dict:
    with orm_session() as db:
        rule = approval_type(document_type)
        user = actor(db, user['id'])
        if 'admin' not in user['roles'] and rule.view_permission not in user['permissions']:
            raise HTTPException(403, '没有查看此类单据审批规则的权限')
        return {**policy_data(policy(db, document_type)), 'title': rule.title}


@router.put('/{document_type}')
def configure_policy(document_type: str, payload: ApprovalPolicyInput,
                     user: dict = Depends(current_user)) -> dict:
    with orm_session(write=True) as db:
        return {**save_policy(db, document_type, [step.model_dump() for step in payload.steps],
                             payload.version, user['id']), 'title': approval_type(document_type).title}


# 单据动作携带读取到的审批版本；不能用客户端传来的业务内容替换服务端快照。
class ApprovalActionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: int = Field(ge=0, strict=True)
    intent: Literal['execute', 'reverse'] = 'execute'
    reason: str = Field(default='', max_length=500)


def document_access(db, document_type: str, identifier: int, user_id: int):
    # 单据查询也按原业务权限检查，不继承模板管理的管理员快捷入口。
    rule = approval_type(document_type)
    user = actor(db, user_id, rule.view_permission)
    source = document_source(db, document_type, identifier)
    # 通用审批入口必须沿用原客户归属检查，拒绝跨客户的查询、送审与审核。
    from app.sales.customer_scope import require_visible_order, require_visible_shipment, require_visible_return
    scope = {'SalesOrder': require_visible_order, 'Shipment': require_visible_shipment,
             'SalesReturn': require_visible_return}.get(document_type)
    if scope is not None:
        scope(db, identifier, user)
    return rule, user, source


def document_state(db, document_type: str, identifier: int, intent: str, user_id: int) -> dict:
    rule, user, source = document_access(db, document_type, identifier, user_id)
    row = workflow.find_case(db, document_type, identifier, intent)
    state = workflow.case_data(row)
    current_content = current_snapshot(db, document_type, identifier)
    frozen_content = json.loads(row.snapshot_json) if row else current_content
    if intent == 'reverse' and row:
        frozen_content = frozen_content['document']
    content_matches = workflow.digest(current_content)[1] == workflow.digest(frozen_content)[1]
    if state['status'] in ('rejected', 'withdrawn'):
        # 重新送审前展示当前正文；上一轮固定内容仍完整保存在不可改写的事件中。
        frozen_content = current_content
        content_matches = True
    permissions = user['permissions']
    pending = True
    try:
        document_pending(db, document_type, identifier, intent)
    except HTTPException as error:
        if error.status_code != 409:
            raise
        pending = False
    authors = list(db.scalars(select(DocumentApprovalAuthor.user_id).where(
        DocumentApprovalAuthor.document_type == document_type,
        DocumentApprovalAuthor.document_id == identifier)))
    can_review = pending and content_matches and state['status'] == 'submitted' and rule.review_permission in permissions
    if can_review:
        step = state['steps'][state['current_step']]
        can_review = (user_id not in authors and user_id not in json.loads(row.authors_json)
            and (step['role'] is None or step['role'] in user['roles'])
            and db.scalar(select(DocumentApprovalEvent.id).where(
                DocumentApprovalEvent.case_id == row.id,
                DocumentApprovalEvent.generation == row.generation,
                DocumentApprovalEvent.action == 'approve', DocumentApprovalEvent.actor_id == user_id)) is None)
    permission = submit_permission(document_type, intent) or rule.submit_permission
    events = []
    if row is not None:
        # 仅返回审批记录的人员、时间和意见，不向通用入口暴露领域快照或其他客户信息。
        events = [{'id': event.id, 'version': event.version, 'generation': event.generation,
                   'action': event.action, 'step': event.step, 'actor_id': event.actor_id,
                   'step_name': json.loads(event.state_json)['steps'][event.step]['name']
                       if event.action in ('approve', 'reject') else None,
                   'actor_name': name, 'reason': event.reason, 'created_at': event.created_at}
                  for event, name in db.execute(select(DocumentApprovalEvent, User.username)
                      .join(User, User.id == DocumentApprovalEvent.actor_id)
                      .where(DocumentApprovalEvent.case_id == row.id).order_by(DocumentApprovalEvent.id))]
    summary = document_summary(db, document_type, frozen_content)
    if document_type in ('StockAdjustment', 'PurchaseRequest') and intent == 'execute':
        # 升级前记录只作历史核对；首次送审后从不可改写的事件恢复。
        previous = native_review_evidence(db, document_type, identifier) if row is None else None
        if row:
            first = db.scalar(select(DocumentApprovalEvent).where(
                DocumentApprovalEvent.case_id == row.id).order_by(DocumentApprovalEvent.id))
            previous = json.loads(first.state_json).get('prior_native_review') if first else None
        if previous:
            old_status = {'draft': '草稿', 'submitted': '待审批', 'approved': '已批准',
                          'rejected': '已驳回', 'cancelled': '已取消', 'posted': '已确认'}
            parts = [f"原状态：{old_status.get(previous['status'], previous['status'])}"]
            for label, field in [('提交', 'submitted'), ('审核', 'reviewed')]:
                person = db.get(User, previous[f'{field}_by']) if previous[f'{field}_by'] else None
                if person:
                    parts.append(f"{label}：{person.username} · {previous[f'{field}_at']}")
            if previous['review_reason']:
                parts.append(f"意见：{previous['review_reason']}")
            summary.append({'label': '升级前流程记录（仅供历史核对）', 'value': '；'.join(parts)})
    # 摘要数量来自送审快照；资料名称只用于识别，不会改变已批准的业务内容。
    return {**state, 'document_type': document_type, 'document_id': identifier, 'intent': intent,
            'document_no': source.document_no, 'business_status': source.status,
            'summary': summary, 'content_matches': content_matches,
            'reversal_reason': json.loads(row.snapshot_json).get('reversal_reason', '') if row else '',
            'can_submit': pending and permission in permissions and state['status'] in ('draft', 'withdrawn', 'rejected'),
            'can_review': can_review,
            'can_withdraw': pending and permission in permissions and state['status'] in ('submitted', 'approved')
                and (state['submitted_by'] == user_id or 'admin' in user['roles']),
            'events': events}


@router.get('/{document_type}/{identifier}')
def get_document_approval(document_type: str, identifier: int,
                          intent: Literal['execute', 'reverse'] = 'execute',
                          user: dict = Depends(current_user)) -> dict:
    with orm_session() as db:
        return document_state(db, document_type, identifier, intent, user['id'])


@router.post('/{document_type}/{identifier}/{action}')
def act_document_approval(document_type: str, identifier: int,
                          action: Literal['submit', 'approve', 'reject', 'withdraw'],
                          payload: ApprovalActionInput, user: dict = Depends(current_user)) -> dict:
    with orm_session(write=True) as db:
        document_access(db, document_type, identifier, user['id'])
        row = workflow.find_case(db, document_type, identifier, payload.intent)
        reason = payload.reason if action == 'submit' else (
            json.loads(row.snapshot_json).get('reversal_reason', '') if row else '')
        content = document_snapshot(db, document_type, identifier, payload.intent, reason)
        native = native_review_evidence(db, document_type, identifier)
        prior = native if row is None and payload.intent == 'execute' else None
        if action == 'submit':
            # 派生草稿同时排除原方案编制人员；作者范围取自服务端快照，客户端无法指定。
            original = content['document'] if payload.intent == 'reverse' else content
            result = workflow.submit(db, document_type, identifier, content, payload.version, user['id'],
                            authors=[*original.get('source_author_ids', ()),
                                     *([native['submitted_by']] if native and native['submitted_by'] else [])],
                            prior_state=prior,
                            intent=payload.intent, permission=submit_permission(document_type, payload.intent))
        elif action in ('approve', 'reject'):
            result = workflow.review(db, document_type, identifier, content, payload.version, user['id'],
                            approve=action == 'approve', reason=payload.reason, intent=payload.intent)
        else:
            result = workflow.withdraw(db, document_type, identifier, payload.version, user['id'],
                              intent=payload.intent, permission=submit_permission(document_type, payload.intent))
        if payload.intent == 'execute':
            sync_native_review(db, document_type, identifier, action, result, user['id'], payload.reason)
        return document_state(db, document_type, identifier, payload.intent, user['id'])
