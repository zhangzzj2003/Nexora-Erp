"""按部门和预计金额选择审批链，提交固化规则，分级审核不允许自审。"""
import json
from decimal import Decimal
from datetime import datetime,timezone
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,Field,model_validator
from sqlalchemy import select
from app.access.security import require
from app.core.orm import orm_session,add_model,model_data
from app.core import models as m
from app.core.input_validation import Reason

router=APIRouter(prefix='/api/v1/purchase/approvals')


class StageInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    role_code:str=Field(min_length=1,max_length=80)
    approver_id:int|None=Field(default=None,gt=0,strict=True)


class RuleInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    department:str=Field(default='',max_length=80)
    minimum:Decimal=Field(default=Decimal(0),ge=0,le=999999999999,decimal_places=2)
    maximum:Decimal|None=Field(default=None,gt=0,le=999999999999,decimal_places=2)
    steps:list[StageInput]=Field(min_length=1,max_length=10)
    @model_validator(mode='after')
    def interval(self):
        if self.maximum is not None and self.maximum<=self.minimum:raise ValueError('金额区间上限须大于下限')
        return self


class PolicyInput(Reason):
    version:int=Field(ge=0,strict=True)
    enabled:bool
    rules:list[RuleInput]=Field(max_length=50)


class DelegateInput(Reason):
    request_id:int=Field(gt=0,strict=True)
    approver_id:int=Field(gt=0,strict=True)
    profile_version:int=Field(gt=0,strict=True)


def audit(db,user,request_id,action,reason,evidence):
    db.add(m.PurchaseApprovalAudit(request_id=request_id,action=action,reason=reason,evidence_json=json.dumps(evidence,ensure_ascii=False),created_by=user['id']))


def profile_data(db,identifier):
    row=db.get(m.PurchaseRequestProfile,identifier)
    if not row:return {'department':'','estimated_total':'0.00','version':0,'approval_round':0,'policy_version':0,'approval_steps':[]}
    steps=[model_data(stage) for stage in db.scalars(select(m.PurchaseApprovalStage).where(m.PurchaseApprovalStage.request_id==identifier,m.PurchaseApprovalStage.round==row.approval_round).order_by(m.PurchaseApprovalStage.position))]
    return {**model_data(row),'approval_steps':steps}


def save_profile(db,identifier,payload,user):
    row=db.get(m.PurchaseRequestProfile,identifier)
    if row and payload.version!=row.version:raise HTTPException(409,'申请资料已变化，请重新读取再保存')
    if row:row.department=payload.department.strip();row.estimated_total=f'{payload.estimated_total:.2f}';row.version+=1
    else:db.add(m.PurchaseRequestProfile(request_id=identifier,department=payload.department.strip(),estimated_total=f'{payload.estimated_total:.2f}',version=1))
    db.flush()
    request=db.get(m.PurchaseRequest,identifier)
    evidence={**profile_data(db,identifier),'reference':request.reference,'note':request.note,
        'lines':[model_data(line) for line in db.scalars(select(m.PurchaseRequestLine).where(m.PurchaseRequestLine.purchase_request_id==identifier))]}
    audit(db,user,identifier,'save','保存申请及预计金额',evidence)


def start_approval(db,identifier,user):
    profile=db.get(m.PurchaseRequestProfile,identifier)
    if not profile:profile=add_model(db,m.PurchaseRequestProfile(request_id=identifier,department='',estimated_total='0.00',version=1))
    profile.approval_round+=1;profile.version+=1
    policy=db.get(m.PurchaseApprovalPolicy,1);profile.policy_version=policy.version if policy and policy.enabled else 0
    if policy and policy.enabled:
        rules=json.loads(policy.rules_json);amount=Decimal(profile.estimated_total)
        matches=[row for row in rules if row['department'] in ('',profile.department) and amount>=Decimal(row['minimum']) and (row['maximum'] is None or amount<Decimal(row['maximum']))]
        matches.sort(key=lambda row:(row['department']==profile.department,Decimal(row['minimum'])),reverse=True)
        if not matches:raise HTTPException(409,'没有匹配的审批规则，请管理员补齐部门或金额区间')
        request=db.get(m.PurchaseRequest,identifier)
        for position,step in enumerate(matches[0]['steps'],1):
            if step['approver_id'] in (request.created_by,user['id']):raise HTTPException(409,'审批人不能是申请人或提交人，请调整规则')
            db.add(m.PurchaseApprovalStage(request_id=identifier,round=profile.approval_round,position=position,
                role_code=step['role_code'],approver_id=step['approver_id'],status='pending'))
    db.flush();audit(db,user,identifier,'submit','提交审批',profile_data(db,identifier))


def current_stage(db,identifier,user):
    profile=db.get(m.PurchaseRequestProfile,identifier)
    if not profile or not profile.policy_version:return None
    stage=db.scalar(select(m.PurchaseApprovalStage).where(m.PurchaseApprovalStage.request_id==identifier,m.PurchaseApprovalStage.round==profile.approval_round,m.PurchaseApprovalStage.status=='pending').order_by(m.PurchaseApprovalStage.position).limit(1))
    if stage is None:raise HTTPException(409,'本轮没有待处理的审批节点')
    request=db.get(m.PurchaseRequest,identifier)
    if user['id'] in (request.created_by,request.submitted_by):raise HTTPException(403,'申请人或提交人不能审批自己的采购申请')
    if stage.approver_id is not None:
        if stage.approver_id!=user['id']:raise HTTPException(403,'当前审批节点已指定其他审批人')
    elif stage.role_code not in user['roles']:raise HTTPException(403,'当前审批节点不属于你的岗位')
    if db.scalar(select(m.PurchaseApprovalStage.position).where(m.PurchaseApprovalStage.request_id==identifier,m.PurchaseApprovalStage.round==profile.approval_round,m.PurchaseApprovalStage.reviewed_by==user['id'])):
        raise HTTPException(403,'同一账号不能重复审批同一申请的多个节点')
    return stage


def review_approval(db,identifier,user,approved,reason=''):
    request=db.get(m.PurchaseRequest,identifier)
    if request is None:raise HTTPException(404,'采购申请不存在')
    if request.status!='submitted':raise HTTPException(409,'仅已提交的采购申请可审批')
    stage=current_stage(db,identifier,user)
    if stage:
        stage.status='approved' if approved else 'rejected';stage.reviewed_by=user['id'];stage.reviewed_at=datetime.now(timezone.utc).isoformat()
        profile=db.get(m.PurchaseRequestProfile,identifier);profile.version+=1;db.flush()
        if not approved:
            for item in db.scalars(select(m.PurchaseApprovalStage).where(m.PurchaseApprovalStage.request_id==identifier,m.PurchaseApprovalStage.round==profile.approval_round,m.PurchaseApprovalStage.status=='pending')):item.status='cancelled'
        if approved and db.scalar(select(m.PurchaseApprovalStage.position).where(m.PurchaseApprovalStage.request_id==identifier,m.PurchaseApprovalStage.round==profile.approval_round,m.PurchaseApprovalStage.status=='pending')):
            audit(db,user,identifier,'approve_stage','节点批准',profile_data(db,identifier));return False
    audit(db,user,identifier,'approve' if approved else 'reject',reason or '批准申请',profile_data(db,identifier));return True


@router.get('')
def policy(user:dict=Depends(require('purchase_request.view'))):
    with orm_session() as db:
        row=db.get(m.PurchaseApprovalPolicy,1)
        return {'version':row.version,'enabled':bool(row.enabled),'rules':json.loads(row.rules_json)} if row else {'version':0,'enabled':False,'rules':[]}


@router.put('')
def configure(data:PolicyInput,user:dict=Depends(require('users.manage'))):
    if 'admin' not in user['roles']:raise HTTPException(403,'只有管理员可配置公司审批链')
    with orm_session(write=True) as db:
        row=db.get(m.PurchaseApprovalPolicy,1)
        if data.version!=(row.version if row else 0):raise HTTPException(409,'审批规则已变化，请刷新后保存')
        if data.enabled and not data.rules:raise HTTPException(422,'启用审批链须至少配置一个规则')
        for rule in data.rules:
            for step in rule.steps:
                if db.get(m.Role,step.role_code) is None or not db.get(m.RolePermission,(step.role_code,'purchase_request.review')):raise HTTPException(422,'审批岗位须具备采购申请审批权限')
                if step.approver_id:
                    person=db.get(m.User,step.approver_id)
                    if person is None or not person.is_active or not db.get(m.UserRole,(person.id,step.role_code)):raise HTTPException(422,'指定审批人须是该岗位的启用账号')
        for index,first in enumerate(data.rules):
            for other in data.rules[index+1:]:
                if first.department==other.department and first.minimum<(other.maximum or Decimal('1e20')) and other.minimum<(first.maximum or Decimal('1e20')):raise HTTPException(422,'同一部门的审批金额区间不能重叠')
        rules=[item.model_dump(mode='json') for item in data.rules]
        if row:row.version+=1;row.enabled=int(data.enabled);row.rules_json=json.dumps(rules,ensure_ascii=False)
        else:row=add_model(db,m.PurchaseApprovalPolicy(id=1,version=1,enabled=int(data.enabled),rules_json=json.dumps(rules,ensure_ascii=False)))
        db.flush();audit(db,user,None,'configure',data.reason,{'version':row.version,'enabled':bool(row.enabled),'rules':rules})
        return {'version':row.version,'enabled':bool(row.enabled),'rules':rules}


@router.put('/delegate')
def delegate(data:DelegateInput,user:dict=Depends(require('users.manage'))):
    if 'admin' not in user['roles']:raise HTTPException(403,'只有管理员可指定临时代审')
    with orm_session(write=True) as db:
        profile=db.get(m.PurchaseRequestProfile,data.request_id);request=db.get(m.PurchaseRequest,data.request_id)
        if profile is None or profile.version!=data.profile_version or request.status!='submitted':raise HTTPException(409,'申请状态已变化，请刷新后重试')
        stage=db.scalar(select(m.PurchaseApprovalStage).where(m.PurchaseApprovalStage.request_id==request.id,m.PurchaseApprovalStage.round==profile.approval_round,m.PurchaseApprovalStage.status=='pending').order_by(m.PurchaseApprovalStage.position))
        target=db.get(m.User,data.approver_id)
        from app.access.security import user_details
        if stage is None or target is None or not target.is_active or 'purchase_request.review' not in user_details(db,target.id)['permissions'] or target.id in (request.created_by,request.submitted_by):raise HTTPException(409,'代审人须为可审批且非申请／提交人的启用账号')
        before=stage.approver_id;stage.approver_id=target.id;profile.version+=1
        audit(db,user,request.id,'delegate',data.reason,{'position':stage.position,'before_approver':before,'after_approver':target.id})
        return profile_data(db,request.id)


def cancel_approval(db,identifier,user):
    # 取消申请同步终止在途节点并提高版本，防止页面仍把旧节点当成可审批。
    profile=db.get(m.PurchaseRequestProfile,identifier)
    if profile:
        profile.version+=1
        for stage in db.scalars(select(m.PurchaseApprovalStage).where(m.PurchaseApprovalStage.request_id==identifier,
                m.PurchaseApprovalStage.round==profile.approval_round,m.PurchaseApprovalStage.status=='pending')):
            stage.status='cancelled'
    db.flush();audit(db,user,identifier,'cancel','取消采购申请',profile_data(db,identifier))
