"""实例级单据审批模板；领域业务接口随后接入同一事务服务。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.access.security import current_user
from app.core.approval_catalog import APPROVAL_TYPES, approval_type
from app.core.document_approval import actor, policy, policy_data, save_policy
from app.core.models import DocumentApprovalPolicy
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
