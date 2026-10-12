"""真实原单、凭证、双重审批与组合转账的事务及更正验收。"""

from datetime import datetime, timezone
from datetime import timedelta
from decimal import Decimal
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select

from approval_test_helpers import approve_document, execute_payment, execute_subledger_payment
from app.core.models import ControlBalanceTransfer, Journal, JournalLine, PaymentRecord
from app.core.orm import orm_session
from test_ledger_foundation import ledger
from test_subledger_openings import subledger
from test_subledger_multiple_controls import multiple_controls
from test_subledger_order_settlements import cross, make_credit, post_source, sale
from test_business_orm import erp, receipt as ordinary_receipt
from test_business_journals import business, generate as ordinary_generate, post as ordinary_post

BASE = 'finance/control-transfers'
TODAY = datetime.now(timezone.utc).date().isoformat()


def test_order_control_transfer_works_without_historical_opening_and_keeps_posted_account(business):
    client, api, mapping, reviewer, context = business
    received = ordinary_receipt(context)
    api('POST', f'receipts/{received["id"]}/post')
    original = ordinary_post(client, ordinary_generate(client, f'receipt:{received["id"]}'), reviewer)
    target = api('POST', 'finance/ledger-accounts', dict(code='AP-OTHER', name='其他应付',
        category='liability', normal_balance='credit', reason='另一控制科目'), 201)
    api('PUT', 'finance/business-journals/policy', dict(version=1, start_date='2026-01-01',
        mapping={**mapping, 'payable': target['id']}, reason='后续映射修订不改旧凭证'))
    source = next(row for row in api('GET', BASE + '/options')['origins'] if row['kind'] == 'payable')['groups'][0]
    assert source['account_id'] == mapping['payable']
    row = api('POST', BASE, dict(kind='payable', operation='reclassify', business_date=TODAY,
        from_scope=choice(source), to_scope={**choice(source),'account_id':target['id'],'fingerprint':None},
        amount='2', reference='NO-HISTORY', reason='仅订单来源核对'), 201)
    data = dict(client=client, api=api)
    executed = post(data, generate(data, row))
    origin = next(row for row in api('GET', BASE + '/options')['origins'] if row['source_id'] == source['source_id'] and row['kind'] == 'payable')
    assert next(row for row in origin['groups'] if row['account_id'] == target['id'])['outstanding_amount'] == '2.00'
    assert api('GET', f'finance/journals/{original["id"]}')['status'] == 'posted'
    assert executed['status'] == 'executed'


def test_cancelled_fixed_journal_keeps_history_and_can_regenerate_from_current_parent_approval(cross):
    row, source = reclassify(cross)
    generated = generate(cross, row)
    old = generated['journal']
    cross['api']('POST', f'finance/journals/{old["id"]}/cancel', dict(version=old['version'],reason='保留旧草稿并重新生成'))
    current = cross['api']('GET', BASE + f'/{row["id"]}')
    assert current['status'] == 'draft' and current['approval']['status'] == 'approved'
    assert current['journal_status'] == 'cancelled'
    replacement = cross['api']('POST', BASE + f'/{row["id"]}/generate', dict(version=current['version'],reference='REGENERATE',reason='按当前批准重新生成'),201)
    assert replacement['journal']['id'] != old['id']
    assert cross['api']('GET', f'finance/journals/{old["id"]}')['status'] == 'cancelled'
    executed = post(cross, replacement)
    assert executed['status'] == 'executed'
    assert group(cross, 'receivable','historical',source['source_id'],5)['outstanding_amount'] == '5.00'


def choices(data):
    return data['api']('GET', BASE + '/options')['origins']


def group(data, kind, source_type, identifier, account=None):
    origin = next(row for row in choices(data) if (row['kind'], row['source_type'], row['source_id']) == (
        kind, source_type, identifier))
    return next(row for row in origin['groups'] if account is None or row['account_id'] == account)


def choice(row):
    return {key: row[key] for key in ('source_type', 'source_id', 'account_id', 'fingerprint')} | {
        'auxiliary': [dict(kind=item['kind'], id=item['id']) for item in row['auxiliary']]}


def reclassify(data, kind='receivable', source_type='historical', *, credit=False, amount='5', reference='MOVE'):
    data['client']._transport.raise_server_exceptions = True
    if source_type == 'historical':
        position = (1 if kind == 'receivable' else 7) if credit else (0 if kind == 'receivable' else 3)
        identifier = data['history']['lines'][position]['id']
    else:
        if credit:
            make_credit(data, kind)
        identifier = data['sale' if kind == 'receivable' else 'purchase']['id']
    source = group(data, kind, source_type, identifier)
    target = {**choice(source), 'account_id': 5 if kind == 'receivable' else 6, 'fingerprint': None}
    row = data['api']('POST', BASE, dict(kind=kind, operation='reclassify', business_date=TODAY,
        from_scope=choice(source), to_scope=target, amount=amount, reference=reference, reason='核对原单内部重分类'), 201)
    return row, source


def generate(data, row, expected=201):
    approve_document(data['client'], None, 'ControlBalanceTransfer', row['id'], reason='独立批准完整组合')
    return data['api']('POST', f'{BASE}/{row["id"]}/generate', dict(version=row['version'],
        reference='JV-' + row['reference'], reason='按批准固定组合生成'), expected)


def post(data, generated):
    row = generated['journal']
    approve_document(data['client'], None, 'Journal', row['id'], reason='独立核对转账凭证')
    row = data['api']('GET', f'finance/journals/{row["id"]}')
    data['api']('POST', f'finance/journals/{row["id"]}/post', dict(version=row['version'], reason='真实过账同时生效'))
    return next(row for row in data['api']('GET', BASE) if row['id'] == generated['transfer']['id'])


@pytest.mark.parametrize('kind', ['receivable', 'payable'])
@pytest.mark.parametrize('source_type', ['historical', 'order'])
def test_debit_reclassification_only_posting_changes_groups_and_journal_preserves_origin_total(cross, kind, source_type):
    row, source = reclassify(cross, kind, source_type)
    before = Decimal(source['outstanding_amount'])
    generated = generate(cross, row)
    assert group(cross, kind, source_type, source['source_id'], source['account_id'])['outstanding_amount'] == source['outstanding_amount']
    assert generated['transfer']['status'] == 'draft'
    row = post(cross, generated)
    assert row['status'] == 'executed' and row['document_no'].startswith('CBT-')
    original = group(cross, kind, source_type, source['source_id'], source['account_id'])
    target = group(cross, kind, source_type, source['source_id'], 5 if kind == 'receivable' else 6)
    assert Decimal(original['outstanding_amount']) == before - 5
    assert target['outstanding_amount'] == '5.00'
    assert Decimal(original['outstanding_amount']) + Decimal(target['outstanding_amount']) == before
    with orm_session() as db:
        lines = list(db.scalars(select(JournalLine).where(JournalLine.journal_id == row['journal_id']).order_by(JournalLine.position)))
        sign = Decimal(1 if kind == 'receivable' else -1)
        assert [Decimal(line.debit) - Decimal(line.credit) for line in lines] == [-5 * sign, 5 * sign]
    cross['api']('POST', f'finance/journals/{row["journal_id"]}/reverse', dict(version=4,
        reference='GENERIC-REVERSE', journal_date=TODAY, reason='绕过转账更正'), 409)


def test_reversal_requires_new_approvals_and_restores_both_group_balances(cross):
    draft, source = reclassify(cross)
    original = post(cross, generate(cross, draft))
    reverse = cross['api']('POST', f'{BASE}/{original["id"]}/reverse', dict(version=original['version'],
        business_date=TODAY, reference='CORRECT', reason='追加更正原分类'), 201)
    cross['api']('POST', f'{BASE}/{reverse["id"]}/generate', dict(version=reverse['version'],
        reference='NO-APPROVAL', reason='尚未批准'), 409)
    reverse = post(cross, generate(cross, reverse))
    assert reverse['reverses_id'] == original['id']
    assert group(cross, 'receivable', 'historical', source['source_id'], source['account_id'])['outstanding_amount'] == source['outstanding_amount']
    assert group(cross, 'receivable', 'historical', source['source_id'], 5)['outstanding_amount'] == '0.00'
    with orm_session() as db:
        assert db.get(ControlBalanceTransfer, original['id']).status == 'executed'
        assert db.get(Journal, original['journal_id']).status == 'posted'


@pytest.mark.parametrize('kind', ['receivable', 'payable'])
@pytest.mark.parametrize('source_type', ['historical', 'order'])
def test_credit_reclassification_derives_opposite_gl_direction(cross, kind, source_type):
    row, source = reclassify(cross, kind, source_type, credit=True, amount='2')
    before = Decimal(source['outstanding_amount'])
    row = post(cross, generate(cross, row))
    assert row['from_delta'] == '2.00'
    assert Decimal(group(cross, kind, source_type, source['source_id'], source['account_id'])['outstanding_amount']) == before + 2
    assert group(cross, kind, source_type, source['source_id'], 5 if kind == 'receivable' else 6)['outstanding_amount'] == '-2.00'


@pytest.mark.parametrize('kind', ['receivable', 'payable'])
@pytest.mark.parametrize('source_type', ['historical', 'order'])
@pytest.mark.parametrize('credit', [False, True])
def test_followup_funds_freeze_selected_group_and_journal_ignores_generic_mapping(cross, kind, source_type, credit):
    api, client = cross['api'], cross['client']
    row, source = reclassify(cross, kind, source_type, credit=credit, amount='2')
    transfer = post(cross, generate(cross, row))
    account = 5 if kind == 'receivable' else 6
    selected = group(cross, kind, source_type, source['source_id'], account)
    fixed = {key: choice(selected)[key] for key in ('account_id', 'auxiliary', 'fingerprint')}
    action = 'refund' if credit else 'settlement'
    if source_type == 'order':
        path = 'finance/payment-records'
        payload = dict(kind=kind, order_id=source['source_id'], action=action, amount='1', reference='FUNDS')
        api('POST', path, payload, 409)
        api('POST', path, {**payload, 'amount': '3', 'control_scope': fixed}, 409)
        paid = api('POST', path, {**payload, 'control_scope': fixed}, 201)
        paid = execute_payment(client, None, paid)
        key = f'payment_record:{paid["id"]}'
    else:
        path = f'finance/subledger-openings/lines/{source["source_id"]}/payments'
        payload = dict(action=action, amount='1', reference='FUNDS', reason='按真实组合资金')
        api('POST', path, payload, 409)
        api('POST', path, {**payload, 'amount': '3', 'control_scope': fixed}, 409)
        paid = api('POST', path, {**payload, 'control_scope': fixed}, 201)
        paid = execute_subledger_payment(client, None, paid)
        key = f'subledger_payment:{paid["id"]}'
    journal = post_source(cross, key)
    assert paid['control_scope']['account_id'] == account
    with orm_session() as db:
        saved = db.scalar(select(JournalLine).where(JournalLine.journal_id == journal['id'], JournalLine.account_id == account))
        assert saved is not None
    expected = '-1.00' if credit else '1.00'
    assert group(cross, kind, source_type, source['source_id'], account)['outstanding_amount'] == expected
    api('POST', f'{BASE}/{transfer["id"]}/reverse', dict(version=transfer['version'],
        business_date=TODAY, reference='DEPENDENT', reason='仍有下游资金'), 409)


def test_competing_approved_transfers_recheck_actual_balance_at_journal_post(cross):
    first, source = reclassify(cross, amount='120', reference='FIRST')
    second, _ = reclassify(cross, amount='120', reference='SECOND')
    first, second = generate(cross, first), generate(cross, second)
    for generated in (first, second):
        approve_document(cross['client'], None, 'Journal', generated['journal']['id'], reason='批准不预占余额')
    journal = cross['api']('GET', f'finance/journals/{first["journal"]["id"]}')
    cross['api']('POST', f'finance/journals/{journal["id"]}/post', dict(version=journal['version'], reason='先过账'))
    journal = cross['api']('GET', f'finance/journals/{second["journal"]["id"]}')
    cross['api']('POST', f'finance/journals/{journal["id"]}/post', dict(version=journal['version'], reason='额度已变化'), 409)
    assert group(cross, 'receivable', 'historical', source['source_id'], source['account_id'])['outstanding_amount'] == '80.00'
    assert cross['api']('GET', f'finance/journals/{journal["id"]}')['status'] == 'approved'


def test_post_failure_rolls_back_journal_transfer_and_both_approval_execution_events(cross, monkeypatch):
    from app.finance import control_balance_transfers as transfers
    row, source = reclassify(cross)
    generated = generate(cross, row)
    approve_document(cross['client'], None, 'Journal', generated['journal']['id'], reason='准备事务故障验收')
    journal = cross['api']('GET', f'finance/journals/{generated["journal"]["id"]}')
    def fail(*args, **kwargs):
        raise RuntimeError('测试追加审计失败，必须整体回滚')
    monkeypatch.setattr(transfers, 'audit', fail)
    with pytest.raises(RuntimeError, match='整体回滚'):
        cross['api']('POST', f'finance/journals/{journal["id"]}/post', dict(version=journal['version'], reason='故障注入'))
    assert cross['api']('GET', f'finance/journals/{journal["id"]}')['status'] == 'approved'
    assert next(item for item in cross['api']('GET', BASE) if item['id'] == row['id'])['status'] == 'draft'
    assert group(cross, 'receivable', 'historical', source['source_id'], source['account_id'])['outstanding_amount'] == source['outstanding_amount']
    for model, identifier in (('Journal', journal['id']), ('ControlBalanceTransfer', row['id'])):
        state = cross['client'].get(f'/api/v1/system/document-approvals/{model}/{identifier}').json()
        assert state['status'] == 'approved'


@pytest.mark.parametrize('kind', ['receivable', 'payable'])
@pytest.mark.parametrize('source_type,target_type', [('historical','historical'), ('historical','order'),
    ('order','historical'), ('order','order')])
def test_all_origin_pairs_allocate_credit_with_equal_gl_and_no_cash(cross, kind, source_type, target_type):
    api, client = cross['api'], cross['client']
    if source_type == 'order':
        make_credit(cross, kind)
        source_id = cross['sale' if kind == 'receivable' else 'purchase']['id']
    else:
        source_id = cross['history']['lines'][1 if kind == 'receivable' else 7]['id']
    if target_type == 'historical':
        target_id = cross['history']['lines'][4 if kind == 'receivable' else 6]['id']
    elif source_type == 'historical':
        transfer, _ = reclassify(cross, kind, 'order', amount='5', reference='TARGET')
        post(cross, generate(cross, transfer))
        target_id = cross['sale' if kind == 'receivable' else 'purchase']['id']
    else:
        if kind == 'receivable':
            order, _, _ = sale(cross)
        else:
            order = api('POST', 'purchase-orders', dict(supplier_id=1,
                lines=[dict(material_id=cross['material'], quantity='1', unit_price='4')]), 201)
            approve_document(client, None, 'PurchaseOrder', order['id'])
            api('POST', f'purchase-orders/{order["id"]}/confirm')
            receipt = api('POST', 'receipts', dict(supplier_id=1, purchase_order_id=order['id'],
                lines=[dict(material_id=cross['material'], quantity='1')]), 201)
            approve_document(client, None, 'Receipt', receipt['id'])
            api('POST', f'receipts/{receipt["id"]}/post')
            post_source(cross, f'receipt:{receipt["id"]}')
        target_id = order['id']
        saved = group(cross, kind, 'order', target_id)
        transfer = api('POST', BASE, dict(kind=kind, operation='reclassify', business_date=TODAY,
            from_scope=choice(saved), to_scope={**choice(saved), 'account_id': 5 if kind == 'receivable' else 6,
                'fingerprint': None}, amount='2', reference='TARGET', reason='固定第二订单组合'), 201)
        post(cross, generate(cross, transfer))
    source = group(cross, kind, source_type, source_id, 1 if kind == 'receivable' else 2)
    target = group(cross, kind, target_type, target_id, 5 if kind == 'receivable' else 6)
    before = Decimal(source['outstanding_amount']), Decimal(target['outstanding_amount'])
    payments = api('GET', 'finance/payment-records')
    row = api('POST', BASE, dict(kind=kind, operation='allocate', business_date=TODAY,
        from_scope=choice(source), to_scope=choice(target), amount='1', reference='ALLOCATE', reason='跨组合贷方分配'), 201)
    row = post(cross, generate(cross, row))
    after = (Decimal(group(cross, kind, source_type, source_id, source['account_id'])['outstanding_amount']),
        Decimal(group(cross, kind, target_type, target_id, target['account_id'])['outstanding_amount']))
    assert after == (before[0] + 1, before[1] - 1)
    assert sum(after) == sum(before)
    assert api('GET', 'finance/payment-records') == payments


def test_boundaries_reject_spoofed_party_scope_and_stale_or_excess_amount_without_records(cross):
    source = group(cross, 'receivable', 'historical', cross['history']['lines'][0]['id'])
    payload = dict(kind='receivable', operation='reclassify', business_date=TODAY,
        from_scope=choice(source), to_scope={**choice(source), 'account_id': 5, 'fingerprint': None},
        amount='5', reference='INVALID', reason='边界验收')
    for changes, status in (({'amount':'0'},422), ({'amount':'1.001'},422), ({'amount':'NaN'},422),
            ({'amount':'201'},409), ({'kind':'payable'},409), ({'status':'executed'},422),
            ({'business_date':'2099-01-01'},409), ({'reference':' '},422), ({'reason':' '},422)):
        cross['api']('POST', BASE, {**payload, **changes}, status)
    for target, status in (({**payload['to_scope'], 'source_id':True},422),
            ({**payload['to_scope'], 'account_id':4},409),
            ({**payload['to_scope'], 'auxiliary':[dict(kind='customer',id=2)]},409),
            ({**payload['to_scope'], 'party_id':2},422)):
        cross['api']('POST', BASE, {**payload, 'to_scope':target}, status)
    assert cross['api']('GET', BASE) == []


@pytest.mark.parametrize('kind', ['receivable', 'payable'])
def test_same_control_account_can_reclassify_full_auxiliary_without_changing_origin_total(cross, kind):
    project = cross['api']('POST', 'finance/auxiliary/items', dict(kind='project', code='P-NEW', name='新项目组合', reason='建档'), 201)['id']
    source = group(cross, kind, 'historical', cross['history']['lines'][0 if kind == 'receivable' else 3]['id'])
    target = {**choice(source), 'fingerprint': None, 'auxiliary':[
        dict(kind='customer' if kind == 'receivable' else 'supplier', id=1), dict(kind='project', id=project)]}
    row = cross['api']('POST', BASE, dict(kind=kind, operation='reclassify', business_date=TODAY,
        from_scope=choice(source), to_scope=target, amount='7', reference='AUX-MOVE', reason='完整辅助内部重分类'), 201)
    post(cross, generate(cross, row))
    origin = next(row for row in choices(cross) if (row['kind'], row['source_type'], row['source_id']) == (
        kind, 'historical', source['source_id']))
    assert origin['outstanding_amount'] == source['outstanding_amount']
    assert len(origin['groups']) == 2 and all(row['account_id'] == source['account_id'] for row in origin['groups'])
    assert next(row for row in origin['groups'] if any(item['kind'] == 'project' and item['id'] == project
        for item in row['auxiliary']))['outstanding_amount'] == '7.00'


def test_cutoff_projection_keeps_original_effect_after_next_day_reversal(cross, monkeypatch):
    from app.finance import control_balance_transfers as transfers, control_balance_projection as projection, order_ledger_scope as orders
    draft, source = reclassify(cross)
    original = post(cross, generate(cross, draft))
    with orm_session() as db:
        before = projection.public_origins(db, TODAY)
    class NextDay(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(days=1)
    for module in (transfers, projection, orders):
        monkeypatch.setattr(module, 'datetime', NextDay)
    tomorrow = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
    reverse = cross['api']('POST', f'{BASE}/{original["id"]}/reverse', dict(version=original['version'],
        business_date=tomorrow, reference='TOMORROW', reason='次日追加更正'), 201)
    post(cross, generate(cross, reverse))
    with orm_session() as db:
        assert projection.public_origins(db, TODAY) == before
        assert len(projection.executed_transfers(db, TODAY)) == 1
        assert len(projection.executed_transfers(db, tomorrow)) == 2
        current = projection.public_origins(db)
        origin = next(row for row in current if (row['kind'], row['source_type'], row['source_id']) == (
            'receivable', 'historical', source['source_id']))
        assert next(row for row in origin['groups'] if row['account_id'] == 5)['outstanding_amount'] == '0.00'


def draft_source(data, key):
    source = next(row for row in data['api']('GET', 'finance/business-journals') if row['key'] == key)
    return data['api']('POST', 'finance/business-journals/generate', dict(source_key=key,
        fingerprint=source['fingerprint'], policy_version=source['policy_version'], reference='DRAFT-' + key,
        journal_date=source['minimum_date'], reason='固定资金归属，凭证暂未过账'), 201)


def scoped_funds(data, source_type, source, amount='1', reference='SCOPED'):
    selected = group(data, 'receivable', source_type, source['source_id'], 5)
    fixed = {key: choice(selected)[key] for key in ('account_id', 'auxiliary', 'fingerprint')}
    if source_type == 'order':
        row = data['api']('POST', 'finance/payment-records', dict(kind='receivable', order_id=source['source_id'],
            action='settlement', amount=amount, reference=reference, control_scope=fixed), 201)
        return execute_payment(data['client'], None, row), f'payment_record:{row["id"]}'
    row = data['api']('POST', f'finance/subledger-openings/lines/{source["source_id"]}/payments', dict(
        action='settlement', amount=amount, reference=reference, reason='按已转账完整组合', control_scope=fixed), 201)
    return execute_subledger_payment(data['client'], None, row), f'subledger_payment:{row["id"]}'


@pytest.mark.parametrize('source_type', ['historical', 'order'])
def test_unposted_scoped_funds_reserve_group_even_when_source_journal_draft_exists(cross, source_type):
    from app.finance.control_balance_projection import group_data, project_origins, origin_key
    row, source = reclassify(cross, source_type=source_type, amount='2')
    post(cross, generate(cross, row))
    paid, key = scoped_funds(cross, source_type, source, amount='1.50')
    draft_source(cross, key)
    with orm_session() as db:
        origin = project_origins(db, for_funds=True)[origin_key('receivable', source_type, source['source_id'])]
        selected = next(group_data(origin, group) for group in origin.groups.values() if group.account_id == 5)
    assert selected['outstanding_amount'] == '0.50' and not selected['blockers']
    fixed = {key: choice(selected)[key] for key in ('account_id', 'auxiliary', 'fingerprint')}
    if source_type == 'order':
        path = 'finance/payment-records'
        payload = dict(kind='receivable', order_id=source['source_id'], action='settlement',
            amount='0.51', reference='OVER', control_scope=fixed)
    else:
        path = f'finance/subledger-openings/lines/{source["source_id"]}/payments'
        payload = dict(action='settlement', amount='0.51', reference='OVER', reason='超过真实组合', control_scope=fixed)
    cross['api']('POST', path, payload, 409)
    assert group(cross, 'receivable', source_type, source['source_id'], 5)['blockers']
    approval_type = 'PaymentRecord' if source_type == 'order' else 'SubledgerPayment'
    state = cross['client'].get(f'/api/v1/system/document-approvals/{approval_type}/{paid["id"]}').json()
    assert next(item['value'] for item in state['summary'] if item['label'] == '控制科目') == 'AR2'


@pytest.mark.parametrize('source_type', ['historical', 'order'])
def test_downstream_funds_and_gl_must_be_corrected_before_transfer_reversal(cross, source_type):
    row, source = reclassify(cross, source_type=source_type, amount='2')
    original = post(cross, generate(cross, row))
    paid, key = scoped_funds(cross, source_type, source)
    post_source(cross, key)
    path = ('finance/payment-records' if source_type == 'order' else 'finance/subledger-openings/payments')
    inverse = cross['api']('POST', f'{path}/{paid["id"]}/reverse', dict(reason='先冲销真实资金'), 201)
    inverse = (execute_payment if source_type == 'order' else execute_subledger_payment)(cross['client'], None, inverse)
    payload = dict(version=original['version'], business_date=TODAY, reference='RESTORE', reason='资金已更正后复核分类')
    cross['api']('POST', f'{BASE}/{original["id"]}/reverse', payload, 409)
    reverse_key = ('payment_record' if source_type == 'order' else 'subledger_payment') + f':{inverse["id"]}'
    post_source(cross, reverse_key)
    counter = cross['api']('POST', f'{BASE}/{original["id"]}/reverse', payload, 201)
    post(cross, generate(cross, counter))
    assert group(cross, 'receivable', source_type, source['source_id'], source['account_id'])['outstanding_amount'] == source['outstanding_amount']


def test_actual_concurrent_journal_post_uses_one_shared_orm_transaction(cross):
    generated = [generate(cross, reclassify(cross, amount='120', reference=reference)[0]) for reference in ('RACE-A','RACE-B')]
    rows = []
    for item in generated:
        approve_document(cross['client'], None, 'Journal', item['journal']['id'], reason='独立批准并发草稿')
        rows.append(cross['api']('GET', f'finance/journals/{item["journal"]["id"]}'))
    def execute(row):
        return cross['client'].post(f'/api/v1/finance/journals/{row["id"]}/post',
            json=dict(version=row['version'], reason='并发真实过账')).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(execute, rows)) == [200, 409]
    assert sorted(row['status'] for row in cross['api']('GET', BASE)) == ['draft','executed']


def test_parent_approval_and_source_journal_cannot_be_bypassed_at_post(cross):
    draft, _ = reclassify(cross, source_type='order')
    generated = generate(cross, draft)
    approve_document(cross['client'], None, 'Journal', generated['journal']['id'], reason='独立批准待过账')
    path = f'/api/v1/system/document-approvals/ControlBalanceTransfer/{draft["id"]}'
    state = cross['client'].get(path).json()
    response = cross['client'].post(path + '/withdraw', json=dict(version=state['version'], reason='重新核对分类'))
    assert response.status_code == 200, response.text
    journal = cross['api']('GET', f'finance/journals/{generated["journal"]["id"]}')
    cross['api']('POST', f'finance/journals/{journal["id"]}/post', dict(version=journal['version'], reason='父单批准已撤回'), 409)
    approve_document(cross['client'], None, 'ControlBalanceTransfer', draft['id'], reason='重新独立批准')
    cross['api']('POST', f'finance/journals/{journal["id"]}/post', dict(version=journal['version'], reason='当前双批准齐备'))
    source = cross['api']('GET', f'finance/journals/{cross["sale_journal"]["id"]}')
    cross['api']('POST', f'finance/journals/{source["id"]}/reverse', dict(version=source['version'],
        reference='ORPHAN', journal_date=TODAY, reason='不能绕过依赖撤销原凭证'), 409)


def test_v100_migration_rollback_retry_preserves_legacy_approval_and_source_fingerprints(cross):
    from app.core.database import connection, migrate
    from app.finance.business_sources import business_sources
    api, client = cross['api'], cross['client']
    api('POST', 'roles', dict(code='custom_cash', label='自定义财务', permissions=['finance.view']), 201)
    paid = api('POST', 'finance/payment-records', dict(kind='receivable', order_id=cross['sale']['id'],
        action='settlement', amount='1', reference='LEGACY'), 201)
    execute_payment(client, None, paid)
    post_source(cross, f'payment_record:{paid["id"]}')
    with orm_session() as db:
        fingerprints = {key: row['fingerprint'] for key, row in business_sources(db).items()}
    with connection() as db:
        facts = [tuple(row) for row in db.execute('SELECT * FROM journals')]
        approvals = [tuple(row) for row in db.execute('SELECT id, snapshot_json, content_digest FROM document_approval_cases')]
        db.execute('DROP TABLE control_balance_transfer_changes')
        db.execute('DROP TABLE control_balance_transfers')
        for table in ('payment_records','subledger_payments'):
            db.execute(f'ALTER TABLE {table} DROP COLUMN control_scope_json')
        db.execute("DELETE FROM document_approval_policies WHERE document_type='ControlBalanceTransfer'")
        db.execute("DELETE FROM role_permissions WHERE permission_code LIKE 'control_transfer.%'")
        db.execute("DELETE FROM permissions WHERE code LIKE 'control_transfer.%'")
        db.execute('PRAGMA user_version = 100')
        db.execute("CREATE TRIGGER fail_transfer_permission BEFORE INSERT ON permissions WHEN NEW.code='control_transfer.reverse' BEGIN SELECT RAISE(ABORT,'transfer migration fault'); END")
    with pytest.raises(sqlite3.IntegrityError, match='transfer migration fault'):
        migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 100
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='control_balance_transfers'").fetchone()
        for table in ('payment_records','subledger_payments'):
            assert 'control_scope_json' not in {row[1] for row in db.execute(f'PRAGMA table_info({table})')}
        db.execute('DROP TRIGGER fail_transfer_permission')
    migrate()
    migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 101
        assert [tuple(row) for row in db.execute('SELECT * FROM journals')] == facts
        assert [tuple(row) for row in db.execute('SELECT id, snapshot_json, content_digest FROM document_approval_cases')] == approvals
        assert not db.execute('PRAGMA foreign_key_check').fetchone()
        assert {row[0] for row in db.execute("SELECT role_code FROM role_permissions WHERE permission_code='control_transfer.post'")} == {'admin','finance'}
    with orm_session() as db:
        assert {key: row['fingerprint'] for key, row in business_sources(db).items()} == fingerprints


def test_separate_page_and_source_permissions_do_not_expand_origins_or_allow_post(cross):
    api = cross['api']
    for code, permissions in [('transfer_reader',['control_transfer.view']),
            ('source_reader',['finance.view','subledger_opening.view']),
            ('cash_reader',['finance.view','finance.record']),
            ('journal_poster',['journal.view','journal.post','finance.view','subledger_opening.view'])]:
        api('POST', 'roles', dict(code=code, label=code, permissions=permissions), 201)
        api('POST', 'users', dict(username=code, password='permission-test-123', roles=[code]), 201)
    def auth(code):
        return {'Authorization': 'Bearer ' + api('POST', 'auth/login', dict(username=code,password='permission-test-123'))['token']}
    draft, source = reclassify(cross)
    generated = generate(cross, draft)
    assert api('GET', BASE, headers=auth('transfer_reader')) == []
    options = api('GET', BASE + '/options', headers=auth('transfer_reader'))
    assert options['origins'] == []
    assert not any(item['kind'] in ('customer','supplier') for item in options['auxiliary_items'])
    api('GET', BASE + f'/{draft["id"]}', expected=403, headers=auth('transfer_reader'))
    api('GET', BASE, expected=403, headers=auth('source_reader'))
    api('GET', BASE + f'/funds-options?kind=receivable&source_type=historical&source_id={source["source_id"]}',
        expected=403, headers=auth('cash_reader'))
    order = cross['sale']['id']
    result = api('GET', BASE + f'/funds-options?kind=receivable&source_type=order&source_id={order}', headers=auth('cash_reader'))
    assert not result['required'] and result['origin']['source_id'] == order
    approve_document(cross['client'], None, 'Journal', generated['journal']['id'], reason='独立核对权限')
    journal = api('GET', f'finance/journals/{generated["journal"]["id"]}')
    api('POST', f'finance/journals/{journal["id"]}/post', dict(version=journal['version'],reason='仅凭证权限'),
        403, auth('journal_poster'))
    assert next(row for row in api('GET', BASE) if row['id'] == draft['id'])['status'] == 'draft'
    api('GET', BASE + '/balances?to_date=2026-02-31', expected=422)
    api('GET', BASE + '/balances?to_date=2099-01-01', expected=422)


@pytest.mark.parametrize('source_type', ['historical', 'order'])
def test_cancel_requires_current_origin_view_and_keeps_draft_and_audit_on_denial(cross, source_type):
    api = cross['api']
    row, _ = reclassify(cross, source_type=source_type)
    required = 'subledger_opening.view' if source_type == 'historical' else 'finance.view'
    other = 'finance.view' if source_type == 'historical' else 'subledger_opening.view'
    permissions = ['control_transfer.view', 'control_transfer.create', other]
    api('POST', 'roles', dict(code='cancel_operator', label='取消转账操作员', permissions=permissions), 201)
    api('POST', 'users', dict(username='cancel_operator', password='permission-test-123', roles=['cancel_operator']), 201)
    headers = {'Authorization': 'Bearer ' + api('POST', 'auth/login',
        dict(username='cancel_operator', password='permission-test-123'))['token']}
    before = api('GET', BASE + f'/{row["id"]}')
    changes = api('GET', BASE + f'/{row["id"]}/changes')
    payload = dict(version=row['version'], reason='取消未生效转账')
    api('POST', BASE + f'/{row["id"]}/cancel', payload, 403, headers)
    assert api('GET', BASE + f'/{row["id"]}') == before
    assert api('GET', BASE + f'/{row["id"]}/changes') == changes
    # 同一登录会话按当前权限核对，补齐原单查看权限后才能取消。
    api('PUT', 'roles/cancel_operator', dict(label='取消转账操作员', permissions=[*permissions, required]))
    cancelled = api('POST', BASE + f'/{row["id"]}/cancel', payload, headers=headers)
    assert cancelled['status'] == 'cancelled' and cancelled['version'] == row['version'] + 1
    history = api('GET', BASE + f'/{row["id"]}/changes')
    assert len(history) == len(changes) + 1 and history[-1]['action'] == 'cancel'
