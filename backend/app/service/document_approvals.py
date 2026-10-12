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
    native_review_evidence, sync_native_review, maintenance_execution_snapshot,
)
from app.core.models import DocumentApprovalEvent, DocumentApprovalPolicy, User, WarehouseInboundReversal
from app.core.orm import orm_session

router = APIRouter(prefix='/api/v1/system/document-approvals')


class ApprovalStepInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=40)
    role: str | None = Field(default=None, min_length=1, max_length=100)
    # 省略时兼容旧模板；新客户端显式选择按钮动作，不用显示名称作为权限代码。
    action: Literal['review', 'verify', 'approve'] | None = None


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
        return {**save_policy(db, document_type, [step.model_dump(exclude_unset=True) | {'role': step.role} for step in payload.steps],
                             payload.version, user['id']), 'title': approval_type(document_type).title}


# 单据动作携带读取到的审批版本；不能用客户端传来的业务内容替换服务端快照。
class ApprovalActionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: int = Field(ge=0, strict=True)
    intent: Literal['execute', 'reverse'] = 'execute'
    reason: str = Field(default='', max_length=500)
    # 维护原接口分别保存操作原因和现场依据，不合并为一段不可辨别的审批意见。
    evidence: str | None = Field(default=None, max_length=600)


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
    if document_type == 'AfterSalesCase':
        from app.sales.customer_scope import require_visible_after_sales
        require_visible_after_sales(db, source, user)
    if document_type == 'CrmQuote':
        from app.sales.crm_rules import get_record
        get_record(db, 'quote', identifier, user=user)
    if document_type == 'ControlBalanceTransfer':
        from app.finance.control_balance_transfers import require_origin_view
        for saved in (json.loads(source.from_scope_json), json.loads(source.to_scope_json)):
            require_origin_view(db, user_id, saved)
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
    if intent == 'reverse' and document_type in ('OpeningBalance', 'SubledgerOpening') and row:
        content_matches = content_matches and json.loads(row.snapshot_json)['confirmation'] == {
            'confirmed_by': source.confirmed_by, 'confirmed_at': source.confirmed_at}
    if intent == 'reverse' and document_type == 'MaintenanceJob' and row:
        content_matches = content_matches and workflow.digest(maintenance_execution_snapshot(db, identifier))[1] == workflow.digest(json.loads(row.snapshot_json)['execution'])[1]
    # 其他入库冲销冻结已入库额度，续收后明确显示内容变化，不能沿用旧批准。
    inbound_received = {}
    if document_type == 'WarehouseInbound':
        from app.inventory.inbounds import received_by_line, reopen_trace
        inbound_received = received_by_line(db, identifier)
        if intent == 'reverse' and row:
            frozen_received = json.loads(row.snapshot_json).get('received_quantities')
            content_matches = content_matches and (frozen_received == {str(key): str(value) for key, value in inbound_received.items()}
                if frozen_received is not None else source.status == 'posted')
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
    # 查询按钮与提交接口使用相同的当前步骤权限，不根据人员参与历史或模板职务排除。
    can_review = pending and content_matches and state['status'] == 'submitted'
    if can_review:
        can_review = rule.step_permission(state['steps'][state['current_step']]) in permissions
    permission = submit_permission(document_type, intent, source) or rule.submit_permission
    events = []
    if row is not None:
        # 仅返回审批记录的人员、时间和意见，不向通用入口暴露领域快照或其他客户信息。
        events = [{'id': event.id, 'version': event.version, 'generation': event.generation,
                   'action': event.action, 'step': event.step, 'actor_id': event.actor_id,
                   'step_name': json.loads(event.state_json)['steps'][event.step]['name']
                       if event.action in ('approve', 'reject') else None,
                   'actor_name': name, 'reason': event.reason, 'created_at': event.created_at,
                   **({'evidence': json.loads(event.state_json).get('operation_evidence', '')} if document_type == 'MaintenanceJob' else {})}
                  for event, name in db.execute(select(DocumentApprovalEvent, User.username)
                      .join(User, User.id == DocumentApprovalEvent.actor_id)
                      .where(DocumentApprovalEvent.case_id == row.id).order_by(DocumentApprovalEvent.id))]
    # 部分冲销的审核摘要展示实收数量，不能把原计划数量误当本次扣库存量。
    summary_content = frozen_content
    if document_type == 'WarehouseInbound' and intent == 'reverse':
        quantities = json.loads(row.snapshot_json).get('received_quantities', {}) if row else {
            str(key): str(value) for key, value in inbound_received.items()}
        if quantities:
            summary_content = {**frozen_content, 'lines': [{**line, 'quantity': quantities.get(str(line['id']), '0')}
                for line in frozen_content['lines']]}
    summary = document_summary(db, document_type, summary_content)
    if document_type in ('StockAdjustment', 'PurchaseRequest', 'CrmQuote', 'AfterSalesCase', 'QualityDisposition', 'MrpPlan', 'MaintenanceJob', 'Journal', 'OpeningBalance', 'SubledgerOpening') and intent == 'execute':
        # 升级前记录只作历史核对；首次送审后从不可改写的事件恢复。
        previous = native_review_evidence(db, document_type, identifier) if row is None else None
        if row:
            first = db.scalar(select(DocumentApprovalEvent).where(
                DocumentApprovalEvent.case_id == row.id).order_by(DocumentApprovalEvent.id))
            previous = json.loads(first.state_json).get('prior_native_review') if first else None
        if previous:
            old_status = {'draft': '草稿', 'submitted': '待审批', 'approved': '已批准',
                          'rejected': '已驳回', 'cancelled': '已取消', 'posted': '已确认', 'confirmed': '已确认', 'reversed': '已撤销'}
            parts = [f"原状态：{old_status.get(previous['status'], previous['status'])}"]
            for label, field in [('提交', 'submitted'), ('审核', 'reviewed')]:
                person = db.get(User, previous[f'{field}_by']) if previous[f'{field}_by'] else None
                if person:
                    parts.append(f"{label}：{person.username} · {previous[f'{field}_at']}")
            if previous['review_reason']:
                parts.append(f"意见：{previous['review_reason']}")
            summary.append({'label': '升级前流程记录（仅供历史核对）', 'value': '；'.join(parts)})
    if document_type in ('OpeningBalance', 'SubledgerOpening') and intent == 'reverse':
        # 撤销核对原实际确认人员和时间，不能把原启用批准当作撤销授权。
        confirmation = json.loads(row.snapshot_json)['confirmation'] if row and state['status'] not in ('rejected', 'withdrawn') else {
            'confirmed_by': source.confirmed_by, 'confirmed_at': source.confirmed_at}
        confirmer = db.get(User, confirmation['confirmed_by']) if confirmation['confirmed_by'] else None
        summary.extend([{'label': '原确认人员', 'value': confirmer.username if confirmer else '—'},
            {'label': '原确认时间', 'value': confirmation['confirmed_at'] or '—'}])
    if document_type == 'MaintenanceJob' and intent == 'reverse':
        execution = json.loads(row.snapshot_json)['execution'] if row and state['status'] not in ('rejected', 'withdrawn') else maintenance_execution_snapshot(db, identifier)
        summary.extend({'label': label, 'value': str(execution[field]) if execution[field] is not None else '—'}
            for label, field in [('实际处理结果', 'solution'), ('实际工时', 'labor_hours'),
                ('声明外委费用', 'service_amount'), ('原验收时间', 'accepted_at')])
    # 部分入库冲销后关闭余量，审批页面也不能再提示用户继续入库。
    business_status = source.status
    if document_type == 'WarehouseInbound':
        if db.scalar(select(WarehouseInboundReversal.id).where(WarehouseInboundReversal.inbound_id == identifier)):
            business_status = 'reversed'
        elif source.status == 'draft' and any(inbound_received.values()):
            business_status = 'partially_posted'
    # 摘要数量来自送审快照；资料名称只用于识别，不会改变已批准的业务内容。
    return {**state, 'document_type': document_type, 'document_id': identifier, 'intent': intent,
            'document_no': source.document_no, 'business_status': business_status,
            'summary': summary, 'content_matches': content_matches,
            'reversal_reason': json.loads(row.snapshot_json).get('reversal_reason', '') if row else '',
            **({'reversal_evidence': json.loads(row.snapshot_json).get('reversal_evidence', '') if row else ''} if document_type == 'MaintenanceJob' else {}),
            'can_submit': pending and permission in permissions and state['status'] in ('draft', 'withdrawn', 'rejected'),
            'can_review': can_review,
            'can_withdraw': pending and permission in permissions and state['status'] in ('submitted', 'approved')
                and (state['submitted_by'] == user_id or 'admin' in user['roles']),
            'events': events,
            **({'reopen_trace': reopen_trace(db, identifier)}
                if document_type == 'WarehouseInbound' else {})}


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
        rule, user, source = document_access(db, document_type, identifier, user['id'])
        if document_type != 'MaintenanceJob' and payload.evidence is not None:
            raise HTTPException(422, '此类单据不接受维护现场依据')
        evidence = payload.evidence or ''
        if document_type == 'MaintenanceJob' and action in ('submit', 'approve', 'reject') and (
                not payload.reason.strip() or len(payload.reason.strip()) > 200 or not evidence.strip()):
            raise HTTPException(422, '维护操作原因与现场依据必填')
        row = workflow.find_case(db, document_type, identifier, payload.intent)
        fixed_evidence = evidence if action == 'submit' else (
            json.loads(row.snapshot_json).get('reversal_evidence', '') if row else '')
        reason = payload.reason if action == 'submit' else (
            json.loads(row.snapshot_json).get('reversal_reason', '') if row else '')
        if document_type in ('PaymentRecord', 'SubledgerPayment', 'OrderSettlementTransfer', 'SubledgerSettlement', 'ControlBalanceTransfer'):
            if document_type == 'PaymentRecord':
                from app.finance.routes import validate_payment
            elif document_type == 'OrderSettlementTransfer':
                from app.finance.order_settlements import validate_transfer as validate_payment
            elif document_type == 'SubledgerSettlement':
                from app.finance.subledger_settlements import validate_settlement as validate_payment
            elif document_type == 'ControlBalanceTransfer':
                from app.finance.control_balance_transfers import validate_transfer as validate_payment
            else:
                from app.finance.subledger_openings import validate_payment
            permission = submit_permission(document_type, payload.intent, source) or rule.submit_permission
            if action in ('approve', 'reject'):
                workflow.require_review_actor(db, document_type, row, user['id'])
            else:
                workflow.actor(db, user['id'], permission)
            workflow.check_version(row.version if row else 0, payload.version)
            if action != 'withdraw' and (not payload.reason.strip() or len(payload.reason.strip()) > 200):
                raise HTTPException(422, '资金审批依据必填，最多二百字')
            if action in ('submit', 'approve'):
                validate_payment(db, source)
        if document_type == 'ProductionCostSettlement':
            permission = submit_permission(document_type,payload.intent,source) or rule.submit_permission
            if action in ('approve', 'reject'):
                workflow.require_review_actor(db, document_type, row, user['id'])
            else:
                workflow.actor(db, user['id'], permission)
            workflow.check_version(row.version if row else 0,payload.version)
            if action != 'withdraw' and (not payload.reason.strip() or len(payload.reason.strip())>200):
                raise HTTPException(422,'结算审批依据必填，最多二百字')
            if action in ('submit','approve') and payload.intent == 'execute':
                from app.production.settlements import validate_settlement
                validate_settlement(db,source)
        native = native_review_evidence(db, document_type, identifier)
        prior = native if row is None and payload.intent == 'execute' else None
        before = None
        if document_type in ('CrmQuote', 'AfterSalesCase', 'QualityDisposition', 'MrpPlan', 'MaintenanceJob', 'Journal', 'OpeningBalance', 'SubledgerOpening') and payload.intent == 'execute':
            # 使用外层业务事务准备固定正文，失败时原资料、原审计与审批事件全部回滚。
            if document_type == 'CrmQuote':
                from app.sales.crm_quotes import prepare_approval_action
            elif document_type == 'AfterSalesCase':
                from app.sales.after_sales import prepare_approval_action
            elif document_type == 'QualityDisposition':
                from app.production.quality import prepare_approval_action
            elif document_type == 'MrpPlan':
                from app.production.mrp import prepare_approval_action
            elif document_type == 'SubledgerOpening':
                from app.finance.subledger_openings import prepare_approval_action
            elif document_type == 'OpeningBalance':
                from app.finance.opening_balances import prepare_approval_action
            elif document_type == 'Journal':
                from app.finance.journals import prepare_approval_action
            else:
                from app.production.equipment import prepare_approval_action
            if action in ('approve', 'reject'):
                workflow.require_review_actor(db, document_type, row, user['id'])
            else:
                workflow.actor(db, user['id'], rule.submit_permission)
            workflow.check_version(row.version if row else 0, payload.version)
            document_pending(db, document_type, identifier, payload.intent)
            if action == 'submit':
                # 送审人先进入固定作者范围，原领域审计追加后不会改变审批摘要。
                for author_id in {user['id'], source.created_by, *([native['submitted_by']] if native and native['submitted_by'] else [])}:
                    workflow.record_author(db, document_type, identifier, author_id)
            before = prepare_approval_action(db, source, action, user, payload.reason, evidence) if document_type == 'MaintenanceJob' else prepare_approval_action(db, source, action, user, payload.reason)
        if document_type in ('AfterSalesCase', 'QualityDisposition') and payload.intent == 'reverse' and action in ('submit', 'approve', 'reject') and (not payload.reason.strip() or len(payload.reason.strip()) > 200):
            raise HTTPException(422, '更正审核依据必填，最多二百字')
        extra_authors = []
        if document_type in ('AfterSalesCase', 'QualityDisposition') and payload.intent == 'reverse' and action == 'submit':
            from app.core.models import AfterSalesChange, QualityDispositionChange
            change_model = AfterSalesChange if document_type == 'AfterSalesCase' else QualityDispositionChange
            source_field = change_model.case_id if document_type == 'AfterSalesCase' else change_model.disposition_id
            workflow.actor(db, user['id'], submit_permission(document_type, payload.intent, source))
            workflow.check_version(row.version if row else 0, payload.version)
            document_pending(db, document_type, identifier, payload.intent)
            extra_authors = list(db.scalars(select(change_model.changed_by).where(
                source_field == identifier,
                change_model.action.not_in(('approve', 'reject', 'withdraw')))))
            # 原审核与实际办理记录继续存证；审批资格统一由当前步骤的按钮权限决定。
            # 旧已执行单没有执行快照，先登记更正申请人及原办理作者，再固定当前正文。
            for author_id in {source.created_by, user['id'], *extra_authors}:
                workflow.record_author(db, document_type, identifier, author_id)
        if document_type == 'MaintenanceJob' and payload.intent == 'reverse' and action == 'submit':
            from app.core.models import MaintenanceChange, EquipmentAttachment, EquipmentAttachmentReversal
            workflow.actor(db, user['id'], 'equipment.reverse')
            workflow.check_version(row.version if row else 0, payload.version)
            document_pending(db, document_type, identifier, payload.intent)
            extra_authors = list(db.scalars(select(MaintenanceChange.changed_by).where(
                MaintenanceChange.entity_type == 'job', MaintenanceChange.entity_id == identifier,
                MaintenanceChange.action.not_in(('approve', 'reject', 'withdraw')))))
            attachments = list(db.scalars(select(EquipmentAttachment).where(EquipmentAttachment.job_id == identifier)))
            extra_authors.extend(item.created_by for item in attachments)
            extra_authors.extend(db.scalars(select(EquipmentAttachmentReversal.created_by).where(
                EquipmentAttachmentReversal.attachment_id.in_([item.id for item in attachments]))))
            for author_id in {source.created_by, user['id'], *extra_authors}:
                workflow.record_author(db, document_type, identifier, author_id)
        if document_type in ('OpeningBalance', 'SubledgerOpening') and payload.intent == 'reverse':
            if document_type == 'OpeningBalance':
                from app.finance.opening_balances import prepare_approval_action
            else:
                from app.finance.subledger_openings import prepare_approval_action
            if action in ('approve', 'reject'):
                workflow.require_review_actor(db, document_type, row, user['id'])
            else:
                workflow.actor(db, user['id'], submit_permission(document_type, 'reverse'))
            workflow.check_version(row.version if row else 0, payload.version)
            document_pending(db, document_type, identifier, payload.intent)
            prepare_approval_action(db, source, action, user, payload.reason, payload.intent)
            if action == 'submit':
                # 实际确认人员和撤销申请人仍记录在作者范围，授权由当前步骤按钮权限决定。
                extra_authors = [source.confirmed_by] if source.confirmed_by is not None else []
                for author_id in {source.created_by, user['id'], *extra_authors}:
                    workflow.record_author(db, document_type, identifier, author_id)
        content = document_snapshot(db, document_type, identifier, payload.intent, reason, fixed_evidence)
        if action == 'submit':
            # 派生草稿保留原方案编制人员；作者范围取自服务端快照，客户端无法指定。
            original = content['document'] if payload.intent == 'reverse' else content
            result = workflow.submit(db, document_type, identifier, content, payload.version, user['id'],
                            authors=[*extra_authors, *original.get('source_author_ids', ()),
                                     *([native['submitted_by']] if native and native['submitted_by'] else [])],
                            prior_state=prior, reason=payload.reason, evidence=evidence,
                            intent=payload.intent, permission=submit_permission(document_type, payload.intent, source))
        elif action in ('approve', 'reject'):
            result = workflow.review(db, document_type, identifier, content, payload.version, user['id'],
                            approve=action == 'approve', reason=payload.reason, intent=payload.intent, evidence=evidence)
        else:
            result = workflow.withdraw(db, document_type, identifier, payload.version, user['id'],
                              intent=payload.intent, permission=submit_permission(document_type, payload.intent, source))
        if payload.intent == 'execute':
            if document_type == 'SubledgerOpening':
                from app.finance.subledger_openings import sync_approval_action
                sync_approval_action(db, source, action, result, user['id'], payload.reason, before)
            elif document_type == 'OpeningBalance':
                from app.finance.opening_balances import sync_approval_action
                sync_approval_action(db, source, action, result, user['id'], payload.reason, before)
            elif document_type == 'Journal':
                from app.finance.journals import sync_approval_action
                sync_approval_action(db, source, action, result, user['id'], payload.reason, before)
            elif document_type == 'CrmQuote':
                from app.sales.crm_quotes import sync_approval_action
                sync_approval_action(db, source, action, result, user['id'], payload.reason, before)
            elif document_type == 'AfterSalesCase':
                from app.sales.after_sales import sync_approval_action
                sync_approval_action(db, source, action, result, user['id'], payload.reason, before)
            elif document_type == 'QualityDisposition':
                from app.production.quality import sync_approval_action
                sync_approval_action(db, source, action, result, user['id'], payload.reason, before)
            elif document_type == 'MaintenanceJob':
                from app.production.equipment import sync_approval_action
                sync_approval_action(db, source, action, result, user['id'], payload.reason, evidence, before)
            elif document_type == 'MrpPlan':
                from app.production.mrp import sync_approval_action
                sync_approval_action(db, source, action, result, user['id'], payload.reason, before)
            else:
                sync_native_review(db, document_type, identifier, action, result, user['id'], payload.reason)
        return document_state(db, document_type, identifier, payload.intent, user['id'])
