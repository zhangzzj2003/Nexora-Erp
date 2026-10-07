"""分户期初固定全量原单与总账依据，批准不替代逐组合勾稽及实际资金保护。"""

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session
from app.core.models import DocumentApprovalEvent, SubledgerOpening, SubledgerOpeningLine
from app.core.orm import orm_session
from test_ledger_foundation import ledger
from test_subledger_openings import subledger, create, action, confirmed, payment, BASE
from test_journal_document_approval import reviewer
from approval_test_helpers import approve_document, execute_subledger_payment

PATH='/api/v1/system/document-approvals/SubledgerOpening'


def current(client, identifier):
    return next(row for row in client.get(BASE).json() if row['id']==identifier)


def state(client, identifier, intent='execute'):
    response=client.get(f'{PATH}/{identifier}',params={'intent':intent})
    assert response.status_code==200,response.text
    return response.json()


def operate(client, identifier, name, version, headers=None, *, intent='execute', reason='逐组合核对原单', expected=200):
    response=client.post(f'{PATH}/{identifier}/{name}',headers=headers,
        json={'version':version,'reason':reason,'intent':intent})
    assert response.status_code==expected,response.text
    return response.json()


def test_three_steps_fixed_template_authors_no_early_enable_and_withdraw(subledger):
    client,api,person,*_=subledger
    steps=[{'name':name,'role':None} for name in ('审核','核准','批准')]
    api('PUT','system/document-approvals/SubledgerOpening',{'version':1,'steps':steps})
    row=create(subledger)
    submitted=operate(client,row['id'],'submit',0)
    operate(client,row['id'],'approve',1,expected=403)
    assert client.post(f'{BASE}/{row["id"]}/confirm',json={'version':2,'reason':'提前启用'}).status_code==409
    assert client.post(f'{BASE}/{row["id"]}/cancel',json={'version':2,'reason':'绕过撤回'}).status_code==409
    api('PUT','system/document-approvals/SubledgerOpening',{'version':2,'steps':[{'name':'新规则','role':None}]})
    first=operate(client,row['id'],'approve',submitted['version'],person)
    operate(client,row['id'],'approve',first['version'],person,expected=403)
    second=operate(client,row['id'],'approve',first['version'],reviewer(client,'subledger_second'))
    assert second['status']=='submitted'
    third=operate(client,row['id'],'approve',second['version'],reviewer(client,'subledger_third'))
    assert third['steps']==steps and third['status']=='approved'
    enabled=action(subledger,current(client,row['id']),'confirm')
    assert enabled['approval']['status']=='executed' and enabled['evidence']['matched']
    assert state(client,row['id'])['content_matches']


def test_reverse_independent_and_later_funds_block_execution(subledger):
    client=subledger[0]
    row=confirmed(subledger)
    assert client.post(f'{BASE}/{row["id"]}/reverse',json={'version':row['version'],'reason':'直接撤销'}).status_code==409
    approved=approve_document(client,None,'SubledgerOpening',row['id'],intent='reverse',reason='更正历史欠款')
    assert any(item['label']=='原确认时间' and item['value']==row['confirmed_at'] for item in approved['summary'])
    assert current(client,row['id'])['status']=='confirmed'
    execute_subledger_payment(client,None,payment(subledger,row['lines'][0]))
    # 独立批准后发生的资金事实仍须阻止撤销，不能抹去原分户金额。
    assert client.post(f'{BASE}/{row["id"]}/reverse',json={'version':row['version'],'reason':'更正历史欠款'}).status_code==409
    assert state(client,row['id'],'reverse')['status']=='approved'
    assert operate(client,row['id'],'withdraw',approved['version'],intent='reverse')['status']=='withdrawn'
    operate(client,row['id'],'submit',approved['version']+1,intent='reverse',reason='更正历史欠款',expected=409)


@pytest.mark.parametrize('name',['confirm','reverse'])
def test_execution_event_failure_keeps_native_basis_and_audit(subledger,name):
    client=subledger[0]
    row=create(subledger)
    approve_document(client,None,'SubledgerOpening',row['id'],reason='分户核对')
    row=current(client,row['id'])
    if name=='reverse':
        row=action(subledger,row,'confirm')
        approve_document(client,None,'SubledgerOpening',row['id'],intent='reverse',reason='分户核对')
        row=current(client,row['id'])
    before=client.get(f'{BASE}/{row["id"]}/changes').json()
    def fail(session,_):
        if any(isinstance(item,DocumentApprovalEvent) and item.action=='execute' for item in session.new):
            raise RuntimeError('模拟审批执行事件失败')
    event.listen(Session,'before_flush',fail)
    try:
        assert client.post(f'{BASE}/{row["id"]}/{name}',json={'version':row['version'],'reason':'分户核对'}).status_code==500
    finally:event.remove(Session,'before_flush',fail)
    assert current(client,row['id'])==row
    assert client.get(f'{BASE}/{row["id"]}/changes').json()==before
    assert action(subledger,row,name)['status']==('confirmed' if name=='confirm' else 'reversed')


def test_complete_500_lines_digest_and_last_line_tamper(subledger):
    client,_,person,_,payload,_=subledger
    # 五百行金额仍与原总账完整组合一致，通用摘要只展示前一百行并明确核对入口。
    lines=[{**payload['lines'][0],'document_reference':f'原单-{index}','debit':'0.30'} for index in range(497)]
    lines.append({**payload['lines'][0],'document_reference':'原单-497','debit':'0.90'})
    lines.extend(payload['lines'][2:])
    row=create(subledger,lines=lines)
    submitted=operate(client,row['id'],'submit',0)
    assert any(item['label']=='原单总数' and item['value']=='500' for item in submitted['summary'])
    assert len(submitted['summary'])<=128 and '前一百行' in submitted['summary'][-1]['value']
    approved=operate(client,row['id'],'approve',submitted['version'],person)
    with orm_session(write=True) as db:
        db.get(SubledgerOpeningLine,row['lines'][-1]['id']).document_reference='末行被篡改'
    assert not state(client,row['id'])['content_matches']
    assert client.post(f'{BASE}/{row["id"]}/confirm',json={'version':current(client,row['id'])['version'],'reason':'执行末行篡改'}).status_code==409
    assert approved['status']=='approved'


def test_legacy_pending_reapproval_and_reason_boundaries(subledger):
    client=subledger[0];row=create(subledger)
    for reason in (' ','字'*201):operate(client,row['id'],'submit',0,reason=reason,expected=422)
    with orm_session(write=True) as db:
        source=db.get(SubledgerOpening,row['id'])
        source.status,source.submitted_by,source.submitted_at='approved',1,'2026-01-01 00:00:00'
        source.reviewed_by,source.reviewed_at=2,'2026-01-01 01:00:00'
    old=state(client,row['id'])
    assert old['version']==0 and old['events']==[] and any('升级前' in item['label'] for item in old['summary'])
    assert client.post(f'{BASE}/{row["id"]}/confirm',json={'version':1,'reason':'原批准'}).status_code==409
    assert client.post(f'{BASE}/{row["id"]}/submit',json={'version':1,'reason':'旧客户端'}).status_code==409
    approve_document(client,None,'SubledgerOpening',row['id'],reason='分户核对')
    assert action(subledger,current(client,row['id']),'confirm')['status']=='confirmed'
