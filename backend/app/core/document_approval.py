"""通用审批事务服务；领域适配器负责内容、可见性及业务状态校验。"""

import hashlib
import json
from collections.abc import Mapping, Sequence

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.access.security import user_details
from app.core.approval_catalog import approval_type
from app.core.models import (
    DocumentApprovalAuthor, DocumentApprovalCase, DocumentApprovalEvent,
    DocumentApprovalPolicy, DocumentApprovalPolicyChange, Role, User,
)


def encoded(value) -> str:
    # 禁止 NaN/隐式字符串转换；稳定序列化保证审批核对的是同一份服务端内容。
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(snapshot: Mapping) -> tuple[str, str]:
    content = encoded(snapshot)
    return content, hashlib.sha256(content.encode('utf-8')).hexdigest()


def now(db: Session) -> str:
    # SQLAlchemy 对 current_timestamp 返回 datetime，业务库统一保存为文本日期。
    return str(db.scalar(select(func.current_timestamp())))


def write_transaction(db: Session) -> None:
    # 所有状态变化必须与主单操作共用 BEGIN IMMEDIATE，防止批准与执行间发生竞态。
    if not db.connection().get_execution_options().get('sqlite_write'):
        raise RuntimeError('审批写操作必须在业务写事务内执行')


def actor(db: Session, user_id: int, permission: str | None = None) -> dict:
    # 再次读取当前数据库授权，不能信任客户端角色或过期的登录快照。
    user = user_details(db, user_id)
    if not user['is_active']:
        raise HTTPException(401, '账号已停用')
    if permission and permission not in user['permissions']:
        raise HTTPException(403, '没有执行此审批操作的权限')
    return user


def check_version(actual: int, expected: int) -> None:
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
        raise HTTPException(422, '审批版本无效')
    if actual != expected:
        raise HTTPException(409, '审批内容已更新，请重新读取后操作')


def validate_steps(db: Session, steps: Sequence[Mapping]) -> list[dict]:
    if not isinstance(steps, (list, tuple)) or not 1 <= len(steps) <= 5:
        raise HTTPException(422, '审批步骤须为一至五步')
    result = []
    for step in steps:
        if not isinstance(step, Mapping) or set(step) != {'name', 'role'}:
            raise HTTPException(422, '审批步骤字段无效')
        name, role = step['name'], step['role']
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 40:
            raise HTTPException(422, '审批步骤名称须为一至四十字')
        if role is not None and (not isinstance(role, str) or db.get(Role, role) is None):
            raise HTTPException(422, '审批步骤角色不存在')
        result.append({'name': name.strip(), 'role': role})
    return result


def policy(db: Session, document_type: str) -> DocumentApprovalPolicy:
    approval_type(document_type)
    row = db.get(DocumentApprovalPolicy, document_type)
    if row is None:
        raise HTTPException(409, '审批模板尚未初始化，请升级服务端')
    return row


def policy_data(row: DocumentApprovalPolicy) -> dict:
    return {'document_type': row.document_type, 'version': row.version,
            'steps': json.loads(row.steps_json), 'configured_by': row.configured_by,
            'configured_at': row.configured_at}


def save_policy(db: Session, document_type: str, steps: Sequence[Mapping],
                version: int, user_id: int) -> dict:
    write_transaction(db)
    if 'admin' not in actor(db, user_id)['roles']:
        raise HTTPException(403, '仅管理员可以配置单据审批步骤')
    row = policy(db, document_type)
    check_version(row.version, version)
    checked = validate_steps(db, steps)
    before = row.steps_json
    row.steps_json, row.version = encoded(checked), row.version + 1
    row.configured_by, row.configured_at = user_id, now(db)
    db.add(DocumentApprovalPolicyChange(document_type=document_type, version=row.version,
        before_json=before, after_json=row.steps_json, changed_by=user_id))
    db.flush()
    return policy_data(row)


def find_case(db: Session, document_type: str, document_id: int,
              intent: str = 'execute') -> DocumentApprovalCase | None:
    approval_type(document_type)
    if intent not in ('execute', 'reverse') or type(document_id) is not int or document_id <= 0:
        raise HTTPException(422, '审批单据或操作意图无效')
    return db.scalar(select(DocumentApprovalCase).where(
        DocumentApprovalCase.document_type == document_type,
        DocumentApprovalCase.document_id == document_id, DocumentApprovalCase.intent == intent))


def record_author(db: Session, document_type: str, document_id: int, user_id: int) -> None:
    write_transaction(db)
    rule = approval_type(document_type)
    if db.get(rule.model, document_id) is None:
        raise HTTPException(404, '审批单据不存在')
    if db.get(User, user_id) is None:
        raise HTTPException(422, '单据操作人员不存在')
    if db.scalar(select(DocumentApprovalCase.id).where(
            DocumentApprovalCase.document_type == document_type,
            DocumentApprovalCase.document_id == document_id,
            DocumentApprovalCase.status.in_(('submitted', 'approved')))) is not None:
        # 领域编辑入口在写入前调用此边界；不能先批准后再补写作者或修改内容。
        raise HTTPException(409, '单据正在审批或已批准，请先撤回后再编辑')
    key = (document_type, document_id, user_id)
    if db.get(DocumentApprovalAuthor, key) is None:
        db.add(DocumentApprovalAuthor(document_type=document_type, document_id=document_id, user_id=user_id))
        db.flush()


def case_data(row: DocumentApprovalCase | None) -> dict:
    if row is None:
        return {'version': 0, 'status': 'draft', 'generation': 0, 'current_step': 0,
                'steps': [], 'policy_version': None, 'submitted_by': None,
                'submitted_at': None, 'executed_by': None, 'executed_at': None}
    # 默认查询只返回流程状态；敏感单据快照由领域授权后的详情入口提供。
    return {'version': row.version, 'status': row.status, 'generation': row.generation,
            'current_step': row.current_step, 'steps': json.loads(row.steps_json),
            'policy_version': row.policy_version, 'submitted_by': row.submitted_by,
            'submitted_at': row.submitted_at, 'executed_by': row.executed_by,
            'executed_at': row.executed_at}


def append_event(db: Session, row: DocumentApprovalCase, action: str,
                 user_id: int, reason: str, step: int, *, prior_state: Mapping | None = None) -> None:
    row.updated_at = now(db)
    # 事件保留全量快照；重新送审只改变当前状态，不覆盖历次批准的内容。
    state = {**case_data(row), 'snapshot': json.loads(row.snapshot_json),
             'authors': json.loads(row.authors_json), 'content_digest': row.content_digest}
    if prior_state is not None:
        # 升级前流程单独存证，后续投影更新不能覆盖原人员、时间或意见。
        state['prior_native_review'] = dict(prior_state)
    db.add(DocumentApprovalEvent(case_id=row.id, version=row.version, generation=row.generation,
        action=action, step=step, actor_id=user_id, reason=reason, state_json=encoded(state)))
    db.flush()


def submit(db: Session, document_type: str, document_id: int, snapshot: Mapping,
           version: int, user_id: int, *, authors: Sequence[int] = (),
           intent: str = 'execute', permission: str | None = None,
           prior_state: Mapping | None = None, reason: str = '') -> dict:
    write_transaction(db)
    rule = approval_type(document_type)
    actor(db, user_id, permission or rule.submit_permission)
    row = find_case(db, document_type, document_id, intent)
    check_version(row.version if row else 0, version)
    if row and row.status not in ('rejected', 'withdrawn'):
        raise HTTPException(409, '只有未送审、驳回或撤回的单据可以送审')
    source = db.get(rule.model, document_id)
    if source is None:
        raise HTTPException(404, '审批单据不存在')
    content, content_digest = digest(snapshot)
    creator = getattr(source, 'created_by', None)
    # 不能因为遗漏作者字段而默认允许自审。
    if not isinstance(creator, int) or creator <= 0:
        raise HTTPException(409, '单据缺少建单人员，无法进行独立审批')
    if any(type(author_id) is not int or author_id <= 0 for author_id in authors):
        raise HTTPException(422, '单据操作人员无效')
    for author_id in sorted(set([creator, user_id, *authors])):
        record_author(db, document_type, document_id, author_id)
    all_authors = list(db.scalars(select(DocumentApprovalAuthor.user_id).where(
        DocumentApprovalAuthor.document_type == document_type,
        DocumentApprovalAuthor.document_id == document_id).order_by(DocumentApprovalAuthor.user_id)))
    template = policy(db, document_type)
    submitted_at = now(db)
    if row is None:
        row = DocumentApprovalCase(document_type=document_type, document_id=document_id, intent=intent,
            version=1, generation=1, policy_version=template.version, steps_json=template.steps_json,
            snapshot_json=content, content_digest=content_digest, authors_json=encoded(all_authors),
            current_step=0, status='submitted', submitted_by=user_id, submitted_at=submitted_at, updated_at=submitted_at)
        db.add(row)
    else:
        row.version += 1
        row.generation += 1
        row.policy_version, row.steps_json = template.version, template.steps_json
        row.snapshot_json, row.content_digest, row.authors_json = content, content_digest, encoded(all_authors)
        row.current_step, row.status = 0, 'submitted'
        row.submitted_by, row.submitted_at = user_id, submitted_at
    db.flush()
    append_event(db, row, 'submit', user_id, reason.strip(), 0, prior_state=prior_state)
    return case_data(row)


def checked_case(db: Session, document_type: str, document_id: int,
                 version: int, snapshot: Mapping, intent: str) -> DocumentApprovalCase:
    row = find_case(db, document_type, document_id, intent)
    check_version(row.version if row else 0, version)
    if row is None:
        raise HTTPException(409, '单据尚未送审')
    if row.content_digest != digest(snapshot)[1]:
        raise HTTPException(409, '单据内容已变化，请撤回或驳回后重新送审')
    return row


def review(db: Session, document_type: str, document_id: int, snapshot: Mapping,
           version: int, user_id: int, *, approve: bool, reason: str = '',
           intent: str = 'execute') -> dict:
    write_transaction(db)
    user = actor(db, user_id, approval_type(document_type).review_permission)
    row = checked_case(db, document_type, document_id, version, snapshot, intent)
    if row.status != 'submitted':
        raise HTTPException(409, '只能审核正在送审的单据')
    if user_id in json.loads(row.authors_json) or db.get(
            DocumentApprovalAuthor, (document_type, document_id, user_id)) is not None:
        raise HTTPException(403, '建单、编辑或提交人员不能审核自己的单据')
    step = json.loads(row.steps_json)[row.current_step]
    if step['role'] is not None and step['role'] not in user['roles']:
        raise HTTPException(403, '当前人员不属于本步骤指定的审批角色')
    previous = db.scalar(select(DocumentApprovalEvent.id).where(
        DocumentApprovalEvent.case_id == row.id, DocumentApprovalEvent.generation == row.generation,
        DocumentApprovalEvent.action == 'approve', DocumentApprovalEvent.actor_id == user_id))
    if previous:
        raise HTTPException(403, '不同审批步骤须由不同人员完成')
    if not isinstance(reason, str) or len(reason.strip()) > 500 or (not approve and not reason.strip()):
        raise HTTPException(422, '驳回原因必填，审批意见最多五百字')
    current_step = row.current_step
    row.version += 1
    if approve:
        row.current_step += 1
        if row.current_step == len(json.loads(row.steps_json)):
            row.status = 'approved'
    else:
        row.status = 'rejected'
    append_event(db, row, 'approve' if approve else 'reject', user_id, reason.strip(), current_step)
    return case_data(row)


def withdraw(db: Session, document_type: str, document_id: int,
             version: int, user_id: int, *, intent: str = 'execute',
             permission: str | None = None) -> dict:
    write_transaction(db)
    user = actor(db, user_id, permission or approval_type(document_type).submit_permission)
    row = find_case(db, document_type, document_id, intent)
    check_version(row.version if row else 0, version)
    if row is None or row.status not in ('submitted', 'approved'):
        raise HTTPException(409, '只能撤回尚未执行的送审或已批准单据')
    if row.submitted_by != user_id and 'admin' not in user['roles']:
        raise HTTPException(403, '只有提交人员或管理员可以撤回审批')
    row.status, row.version = 'withdrawn', row.version + 1
    append_event(db, row, 'withdraw', user_id, '', row.current_step)
    return case_data(row)


def require_approved(db: Session, document_type: str, document_id: int, snapshot: Mapping,
                     user_id: int, *, intent: str = 'execute', permission: str | None = None) -> DocumentApprovalCase:
    write_transaction(db)
    rule = approval_type(document_type)
    actor(db, user_id, permission or rule.execute_permission)
    row = find_case(db, document_type, document_id, intent)
    if row is None or row.status != 'approved':
        raise HTTPException(409, '请先提交单据并完成独立审批')
    if row.content_digest != digest(snapshot)[1]:
        raise HTTPException(409, '执行内容与批准内容不一致，请重新送审')
    return row


def mark_executed(db: Session, row: DocumentApprovalCase, user_id: int,
                  *, permission: str | None = None) -> None:
    write_transaction(db)
    actor(db, user_id, permission or approval_type(row.document_type).execute_permission)
    if row.status != 'approved':
        raise HTTPException(409, '审批已执行或失效')
    # 此方法在领域执行成功后调用；领域失败时审批事件与主单一起回滚。
    row.status, row.version = 'executed', row.version + 1
    row.executed_by, row.executed_at = user_id, now(db)
    append_event(db, row, 'execute', user_id, '', row.current_step)


def require_conversion_approved(db: Session, document_type: str, document_id: int,
                                snapshot: Mapping, user_id: int) -> DocumentApprovalCase:
    # 申请和物料计划可拆成多张原单；只对此类需求授权允许重复转换，不能放宽库存或资金的单次执行边界。
    if document_type not in ('PurchaseRequest', 'MrpPlan'):
        raise HTTPException(422, '此类单据不支持分批转换授权')
    write_transaction(db)
    actor(db, user_id, approval_type(document_type).execute_permission)
    row = find_case(db, document_type, document_id)
    if row is None or row.status not in ('approved', 'executed'):
        raise HTTPException(409, '请先送审并完成本单独立审批')
    if row.content_digest != digest(snapshot)[1]:
        raise HTTPException(409, '单据内容与批准内容不一致，请重新送审')
    # 实际可转数量仍由领域在同一写事务核对；后续拆单不追加虚假的重复批准或执行事件。
    return row
