"""多控制科目逐组合勾稽、原科目资金凭证及追加证据。"""

from copy import deepcopy
from decimal import Decimal

import pytest

from approval_test_helpers import approve_document, execute_subledger_payment
from app.core.models import SubledgerOpening
from app.core.orm import orm_session
from test_ledger_foundation import ACCOUNT, ledger
from test_opening_balances import action as opening_action
from test_journals import action as journal_action
from test_subledger_openings import subledger, create, action, payment, query


@pytest.fixture
def multiple_controls(subledger):
    client, api, reviewer, opening, payload, project = subledger
    ar = api('POST', 'finance/ledger-accounts', {**ACCOUNT, 'code': 'AR2', 'name': '其他应收'}, 201)
    ap = api('POST', 'finance/ledger-accounts', {
        **ACCOUNT, 'code': 'AP2', 'name': '其他应付', 'category': 'liability', 'normal_balance': 'credit'}, 201)
    controls = deepcopy(payload['control_accounts']) + [
        {'kind': 'receivable', 'account_id': ar['id']}, {'kind': 'payable', 'account_id': ap['id']}]
    lines = deepcopy(payload['lines']) + [
        {**deepcopy(payload['lines'][0]), 'account_id': ar['id'], 'document_reference': 'AR2-DEBT'},
        {**deepcopy(payload['lines'][0]), 'account_id': ar['id'], 'document_reference': 'AR2-CREDIT', 'debit': '0', 'credit': '30'},
        {**deepcopy(payload['lines'][3]), 'account_id': ap['id'], 'document_reference': 'AP2-DEBT', 'credit': '20'}]
    # 使用真实撤销、重新批准的正式期初，不直接改写已经确认的总账依据。
    approve_document(client, None, 'OpeningBalance', opening['id'], intent='reverse', reason='期初核对')
    opening_action((client, reviewer), opening, 'reverse')
    # 正式期初按科目与完整辅助组合汇总，历史分户仍保留每张原始单据。
    grouped = {}
    for line in lines:
        auxiliary = [{'kind': 'customer' if line['kind'] == 'receivable' else 'supplier', 'id': line['party_id']},
            *deepcopy(line['auxiliary'])]
        key = (line['account_id'], tuple(sorted((item['kind'], item['id']) for item in auxiliary)))
        if key not in grouped:
            grouped[key] = {'amount': Decimal('0'), 'auxiliary': auxiliary}
        grouped[key]['amount'] += Decimal(line['debit']) - Decimal(line['credit'])
    basis = [dict(account_id=key[0], summary='多科目历史依据',
        debit=str(max(value['amount'], Decimal('0'))), credit=str(max(-value['amount'], Decimal('0'))),
        auxiliary=value['auxiliary']) for key, value in grouped.items()]
    basis.append(dict(account_id=3, summary='权益', debit='0', credit='90'))
    opening = api('POST', 'finance/opening-balances', {
        'reference': 'GL-MULTI', 'effective_date': '2026-01-01', 'reason': '核对多个控制科目', 'lines': basis}, 201)
    for command in ('submit', 'approve', 'confirm'):
        opening = opening_action((client, reviewer), opening, command, command == 'approve')
    return client, api, reviewer, opening, {**payload, 'opening_balance_id': opening['id'],
        'opening_version': opening['version'], 'control_accounts': controls, 'lines': lines}, project


def confirm(context):
    row = create(context)
    for command in ('submit', 'approve', 'confirm'):
        row = action(context, row, command, command == 'approve')
    return row


def policy(context, version=0, receivable=1, payable=2):
    return context[1]('PUT', 'finance/business-journals/policy', {
        'version': version, 'start_date': '2026-01-01',
        'mapping': {'receivable': receivable, 'payable': payable, 'cash': 4}, 'reason': '往来科目核对'})


def generate(context, source, version=1, reference='MULTI-PAY', expected=201, **changes):
    return context[1]('POST', 'finance/business-journals/generate', {
        'source_key': source['key'], 'fingerprint': source['fingerprint'], 'policy_version': version,
        'reference': reference, 'journal_date': source['source_date'], 'reason': '原科目资金入账', **changes}, expected)


def test_four_controls_reconcile_individually_and_keep_signed_originals(multiple_controls):
    context = multiple_controls
    record = create(context)
    check = context[1]('GET', f'finance/subledger-openings/{record["id"]}/check')
    assert check['matched'] and len(check['rows']) == 5
    totals = {identifier: sum(Decimal(row['ledger_amount']) for row in check['rows'] if row['account_id'] == identifier)
        for identifier in (1, 2, 5, 6)}
    assert totals == {1: Decimal('120'), 2: Decimal('-80'), 5: Decimal('70'), 6: Decimal('-20')}
    for command in ('submit', 'approve', 'confirm'):
        record = action(context, record, command, command == 'approve')
    assert record['control_accounts'] == context[4]['control_accounts'] and record['evidence'] == check
    report = query(context)
    assert report['totals']['receivable']['outstanding_amount'] == '190.00'
    assert report['totals']['payable']['outstanding_amount'] == '100.00'
    assert [row['opening_amount'] for row in report['rows'][-3:]] == ['100.00', '-30.00', '20.00']
    assert 'AR2' in report['csv'] and 'AP2' in report['csv']
    assert context[1]('GET', 'finance/journals') == []


def test_company_total_cannot_hide_cross_account_difference(multiple_controls):
    context = multiple_controls
    lines = deepcopy(context[4]['lines'])
    lines[0]['account_id'] = 5
    record = create(context, lines=lines)
    check = context[1]('GET', f'finance/subledger-openings/{record["id"]}/check')
    assert not check['matched'] and sum(Decimal(row['difference']) for row in check['rows']) == 0
    assert {row['account_id']: row['difference'] for row in check['rows'] if row['difference'] != '0.00'} == {
        1: '-100.00', 5: '100.00'}
    context[1]('POST', f'system/document-approvals/SubledgerOpening/{record["id"]}/submit',
        {'version': 0, 'reason': '不能合并不同科目差额'}, 409)
    assert context[1]('GET', 'finance/subledger-openings')[0]['status'] == 'draft'


@pytest.mark.parametrize('mutation,expected', [
    ('duplicate', 422), ('shared_kind', 422), ('bool', 422), ('unknown', 409),
    ('equity', 409), ('wrong_line_kind', 409), ('over_limit', 422),
])
def test_control_boundaries_leave_no_partial_plan(multiple_controls, mutation, expected):
    context = multiple_controls
    payload = deepcopy(context[4])
    if mutation == 'duplicate': payload['control_accounts'].append(payload['control_accounts'][0])
    if mutation == 'shared_kind': payload['control_accounts'].append({'kind': 'payable', 'account_id': 5})
    if mutation == 'bool': payload['control_accounts'][2]['account_id'] = True
    if mutation == 'unknown': payload['control_accounts'][2]['account_id'] = 999
    if mutation == 'equity': payload['control_accounts'][2]['account_id'] = 3
    if mutation == 'wrong_line_kind': payload['lines'][4]['kind'] = 'payable'
    if mutation == 'over_limit': payload['control_accounts'] = [{'kind': 'receivable', 'account_id': i} for i in range(1, 502)]
    context[1]('POST', 'finance/subledger-openings', payload, expected)
    assert context[1]('GET', 'finance/subledger-openings') == []


def test_removing_used_control_rolls_back_body_lines_and_version(multiple_controls):
    context = multiple_controls
    record = create(context)
    payload = deepcopy(context[4])
    payload['control_accounts'] = [item for item in payload['control_accounts'] if item['account_id'] != 5]
    context[1]('PUT', f'finance/subledger-openings/{record["id"]}', {**payload, 'version': record['version']}, 409)
    assert context[1]('GET', 'finance/subledger-openings')[0] == record
    changes = context[1]('GET', f'finance/subledger-openings/{record["id"]}/changes')
    assert len(changes) == 1 and changes[0]['after']['control_accounts'] == record['control_accounts']


def test_mapping_stays_in_selected_kind_and_scope_is_frozen_by_approval(multiple_controls):
    context = multiple_controls
    policy(context, payable=6)
    record = create(context)
    assert len(record['control_accounts']) == 4
    policy(context, 1, receivable=5, payable=6)
    context[1]('PUT', 'finance/business-journals/policy', {
        'version': 2, 'start_date': '2026-01-01', 'mapping': {'receivable': 6, 'payable': 2, 'cash': 4}, 'reason': '错误类别'}, 409)
    record = action(context, action(context, record, 'submit'), 'approve', True)
    with orm_session(write=True) as db:
        db.get(SubledgerOpening, record['id']).control_accounts_json = '[{"kind":"receivable","account_id":1},{"kind":"payable","account_id":2}]'
    context[1]('POST', f'finance/subledger-openings/{record["id"]}/confirm',
        {'version': record['version'], 'reason': '批准范围已变化'}, 409)
    assert context[1]('GET', 'finance/subledger-openings')[0]['evidence'] is None


@pytest.mark.parametrize('line_index,kind,account_id', [(4, 'receivable', 5), (6, 'payable', 6)])
def test_payment_journal_keeps_original_account_after_default_mapping_changes(multiple_controls, line_index, kind, account_id):
    context = multiple_controls
    record = confirm(context)
    policy(context)
    paid = execute_subledger_payment(context[0], None, payment(context, record['lines'][line_index]))
    source = next(row for row in context[1]('GET', 'finance/business-journals') if row['key'] == f'subledger_payment:{paid["id"]}')
    assert source['can_generate']
    journal = generate(context, source)
    assert {line['account_id'] for line in journal['lines']} == {4, account_id}
    assert journal['business_source']['mapping'][kind] == account_id
    assert all({item['kind'] for item in line['auxiliary']} == {'customer' if kind == 'receivable' else 'supplier', 'project'}
        for line in journal['lines'])
    assert context[1]('GET', 'finance/business-journals/policy')['policy']['mapping'][kind] != account_id
    policy(context, 1, receivable=5, payable=6)
    unchanged = next(row for row in context[1]('GET', 'finance/business-journals') if row['key'] == source['key'])
    assert unchanged['fingerprint'] == source['fingerprint']
    for command in ('submit', 'approve', 'post'):
        journal = journal_action(context[0], journal, command, context[2] if command == 'approve' else None)
    assert journal['business_source']['mapping'][kind] == account_id
    assert query(context)['rows'][line_index]['outstanding_amount'] == ('90.00' if kind == 'receivable' else '10.00')


def test_original_account_is_used_even_without_default_party_mapping(multiple_controls):
    context = multiple_controls
    record = confirm(context)
    context[1]('PUT', 'finance/business-journals/policy', {
        'version': 0, 'start_date': '2026-01-01', 'mapping': {'cash': 4}, 'reason': '现金用途配置'})
    paid = execute_subledger_payment(context[0], None, payment(context, record['lines'][4]))
    source = next(row for row in context[1]('GET', 'finance/business-journals') if row['key'] == f'subledger_payment:{paid["id"]}')
    assert source['can_generate']
    journal = generate(context, source)
    assert {line['account_id'] for line in journal['lines']} == {4, 5}
    # 固定原单科目并不允许把原部门或项目换成另一套辅助归属。
    context[1]('POST', 'finance/journals/' + str(journal['id']) + '/cancel', {'version': journal['version'], 'reason': '重新核对'})
    generate(context, source, reference='BAD-AUX', expected=409,
        auxiliary_by_role={'receivable': [{'kind': 'project', 'id': 999}]})


def test_inactive_original_account_blocks_generation_and_failed_write_leaves_no_journal(multiple_controls):
    context = multiple_controls
    record = confirm(context)
    policy(context)
    paid = execute_subledger_payment(context[0], None, payment(context, record['lines'][4]))
    context[1]('PUT', 'finance/ledger-accounts/5', {'version': 1, 'name': '其他应收', 'is_active': False, 'reason': '停用核对'})
    source = next(row for row in context[1]('GET', 'finance/business-journals') if row['key'] == f'subledger_payment:{paid["id"]}')
    assert not source['can_generate'] and any('科目' in blocker for blocker in source['blockers'])
    generate(context, source, expected=409)
    assert context[1]('GET', 'finance/journals') == []


def test_multi_controls_do_not_allow_cross_account_offsets(multiple_controls):
    context = multiple_controls
    record = confirm(context)
    context[1]('POST', 'finance/subledger-settlements', {
        'from_line_id': record['lines'][5]['id'], 'to_line_id': record['lines'][0]['id'],
        'amount': '10', 'reference': 'CROSS', 'reason': '不同科目不能内部相抵'}, 409)
    assert context[1]('GET', 'finance/subledger-settlements') == []


def test_closing_keeps_all_control_accounts_and_frozen_comparisons(multiple_controls, monkeypatch):
    context = multiple_controls
    record = confirm(context)
    from app.finance import period_closing
    monkeypatch.setattr(period_closing, 'utc_today', lambda: '2027-01-01')
    context[1]('POST', 'finance/accounting-periods/1/close', {'version': 1, 'reason': '多科目核对归档'})
    archived = context[1]('GET', 'finance/accounting-periods/1/closings')[0]['evidence']['subledger']
    assert archived['opening']['control_accounts'] == record['control_accounts']
    assert len(archived['opening']['evidence']['rows']) == 5 and len(archived['rows']) == 7
    context[1]('PUT', 'finance/ledger-accounts/5', {'version': 1, 'name': '更名后的应收科目', 'is_active': True, 'reason': '名称维护'})
    assert context[1]('GET', 'finance/accounting-periods/1/closings')[0]['evidence']['subledger'] == archived
