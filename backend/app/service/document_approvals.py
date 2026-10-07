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
from app.core.approval_documents import document_snapshot, submit_permission, inbound_pending, inbound_snapshot
from app.core.models import DocumentApprovalAuthor, DocumentApprovalEvent, DocumentApprovalPolicy, Material, User, Warehouse
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
    if document_type != 'WarehouseInbound':
        raise HTTPException(409, '此类单据的统一审批入口尚未接入')
    source = db.get(rule.model, identifier)
    if source is None:
        raise HTTPException(404, '单据不存在')
    return rule, user, source


def document_state(db, document_type: str, identifier: int, intent: str, user_id: int) -> dict:
    rule, user, source = document_access(db, document_type, identifier, user_id)
    row = workflow.find_case(db, document_type, identifier, intent)
    state = workflow.case_data(row)
    current_content = inbound_snapshot(db, identifier)
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
        inbound_pending(db, identifier, intent)
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
    warehouse = db.get(Warehouse, frozen_content['warehouse_id'])
    summary = [{'label': '仓库', 'value': warehouse.name if warehouse else str(frozen_content['warehouse_id'])},
               {'label': '用途', 'value': {'opening': '期初补录', 'gift': '赠品', 'other': '其他'}[frozen_content['reason']]},
               {'label': '参考号', 'value': frozen_content['reference'] or '—'},
               {'label': '入库说明', 'value': frozen_content['note']}]
    for line in frozen_content['lines']:
        material = db.get(Material, line['material_id'])
        summary.append({'label': f'{material.sku} · {material.name}' if material else str(line['material_id']),
                        'value': f"{line['quantity']} {material.unit if material else ''}"})
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
        if action == 'submit':
            workflow.submit(db, document_type, identifier, content, payload.version, user['id'],
                            intent=payload.intent, permission=submit_permission(document_type, payload.intent))
        elif action in ('approve', 'reject'):
            workflow.review(db, document_type, identifier, content, payload.version, user['id'],
                            approve=action == 'approve', reason=payload.reason, intent=payload.intent)
        else:
            workflow.withdraw(db, document_type, identifier, payload.version, user['id'],
                              intent=payload.intent, permission=submit_permission(document_type, payload.intent))
        return document_state(db, document_type, identifier, payload.intent, user['id'])
