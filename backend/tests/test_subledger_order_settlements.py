"""通过真实业务及过账凭证核对历史与订单核销，不伪造资金和归属。"""

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
import json

import pytest
from sqlalchemy import func, select

from approval_test_helpers import approve_document, execute_payment, execute_order_settlement, prepare_purchase_return
from app.core.models import BusinessJournalSource, Journal, JournalLine, PaymentRecord, StockMovement, SubledgerOrderSettlement
from app.core.orm import orm_session
from test_ledger_foundation import ACCOUNT, ledger
from test_subledger_openings import subledger, create, action, query
from test_subledger_multiple_controls import multiple_controls

BASE = 'finance/subledger-order-settlements'


@pytest.fixture
def cross(multiple_controls):
    client, api, reviewer, opening, payload, project = multiple_controls
    payload = deepcopy(payload)
    payload['lines'][0].update(debit='200')
    payload['lines'][1].update(debit='0', credit='50')
    payload['lines'][3].update(credit='110')
    payload['lines'].append({**deepcopy(payload['lines'][3]), 'document_reference': 'AP-CREDIT', 'debit': '30', 'credit': '0'})
    context = client, api, reviewer, opening, payload, project
    history = create(context)
    for command in ('submit', 'approve', 'confirm'):
        history = action(context, history, command, command == 'approve')
    mapping = dict(receivable=1, payable=2, cash=4)
    for role, category in (('inventory', 'asset'), ('income', 'income'), ('sales_cost', 'expense'), ('price_variance', 'expense')):
        mapping[role] = api('POST', 'finance/ledger-accounts', {**ACCOUNT, 'code': role.upper(), 'name': role,
            'category': category, 'normal_balance': 'credit' if category == 'income' else 'debit'}, 201)['id']
    api('PUT', 'finance/business-journals/policy', dict(version=0, start_date='2026-01-01', mapping=mapping, reason='按原科目核对'))
    material = api('POST', 'materials', dict(sku='CROSS', name='核销物料', unit='件'), 201)['id']
    data = dict(context=context, client=client, api=api, history=history, project=project, mapping=mapping, material=material)
    purchase = api('POST', 'purchase-orders', dict(supplier_id=1,
        lines=[dict(material_id=material, quantity='20', unit_price='4')]), 201)
    approve_document(client, None, 'PurchaseOrder', purchase['id'])
    api('POST', f'purchase-orders/{purchase["id"]}/confirm')
    receipt = api('POST', 'receipts', dict(supplier_id=1, purchase_order_id=purchase['id'],
        lines=[dict(material_id=material, quantity='20')]), 201)
    approve_document(client, None, 'Receipt', receipt['id'])
    receipt = api('POST', f'receipts/{receipt["id"]}/post')
    data.update(purchase=purchase, receipt=receipt)
    data['purchase_journal'] = post_source(data, f'receipt:{receipt["id"]}')
    data['sale'], data['shipment'], data['sale_journal'] = sale(data)
    return data


def post_source(data, key, *, project=None):
    api = data['api']
    source = next(row for row in api('GET', 'finance/business-journals') if row['key'] == key)
    auxiliary = [{ 'kind': 'project', 'id': data['project'] if project is None else project }]
    row = api('POST', 'finance/business-journals/generate', dict(source_key=key, fingerprint=source['fingerprint'],
        policy_version=source['policy_version'], reference='GL-' + key, journal_date=source['minimum_date'],
        reason='原业务已过账依据', auxiliary_by_role={role: auxiliary for role in ('receivable', 'payable') if role in source['roles']}), 201)
    approve_document(data['client'], None, 'Journal', row['id'], reason='独立核对来源凭证')
    row = api('GET', f'finance/journals/{row["id"]}')
    return api('POST', f'finance/journals/{row["id"]}/post', dict(version=row['version'], reason='按批准依据过账'))


def sale(data, *, customer=1, quantity='2', ship_quantity=None, project=None):
    api, client, material = data['api'], data['client'], data['material']
    row = api('POST', 'sales-orders', dict(customer_id=customer,
        lines=[dict(material_id=material, quantity=quantity, unit_price='10')]), 201)
    approve_document(client, None, 'SalesOrder', row['id'])
    api('POST', f'sales-orders/{row["id"]}/confirm')
    shipment = api('POST', 'shipments', dict(sales_order_id=row['id'], warehouse_id=1,
        lines=[dict(material_id=material, quantity=ship_quantity or quantity)]), 201)
    approve_document(client, None, 'Shipment', shipment['id'])
    shipment = api('POST', f'shipments/{shipment["id"]}/post')
    return row, shipment, post_source(data, f'shipment:{shipment["id"]}', project=project)


def make_credit(data, kind):
    api, client = data['api'], data['client']
    order = data['sale'] if kind == 'receivable' else data['purchase']
    paid = api('POST', 'finance/payment-records', dict(kind=kind, order_id=order['id'], action='settlement',
        amount='20' if kind == 'receivable' else '80', reference='BANK-' + kind), 201)
    paid = execute_payment(client, None, paid)
    post_source(data, f'payment_record:{paid["id"]}')
    if kind == 'receivable':
        shipment = data['shipment']
        returned = api('POST', 'sales-returns', dict(shipment_id=shipment['id'], warehouse_id=1, reason='客户退回',
            lines=[dict(shipment_line_id=shipment['lines'][0]['id'], quantity='1')]), 201)
        approve_document(client, None, 'SalesReturn', returned['id'])
        api('POST', f'sales-returns/{returned["id"]}/post')
        post_source(data, f'sales_return:{returned["id"]}')
    else:
        receipt = data['receipt']
        returned = api('POST', 'purchase-returns', dict(receipt_id=receipt['id'], reason='退回供应商',
            lines=[dict(receipt_line_id=receipt['lines'][0]['id'], quantity='1')]), 201)
        prepare_purchase_return(client, None, returned['id'])
        api('POST', f'purchase-returns/{returned["id"]}/post')
        post_source(data, f'purchase_return:{returned["id"]}')


def draft(data, kind='receivable', direction='historical_credit', expected=201, **changes):
    position = (1 if kind == 'receivable' else 7) if direction == 'historical_credit' else (0 if kind == 'receivable' else 3)
    order = data['sale'] if kind == 'receivable' else data['purchase']
    return data['api']('POST', BASE, {**dict(opening_line_id=data['history']['lines'][position]['id'], order_id=order['id'],
        direction=direction, amount='2', reference='CROSS-' + kind + '-' + direction, reason='核对原科目与完整辅助'), **changes}, expected)


def execute(data, row):
    approve_document(data['client'], None, 'SubledgerOrderSettlement', row['id'], reason='独立核对原单与订单')
    return data['api']('POST', f'{BASE}/{row["id"]}/post', dict(version=row['version'], reason='执行核销'))


def balances(data, line, kind, identifier):
    history = next(row for row in query(data['context'])['rows'] if row['id'] == line)
    order = next(row for row in data['api']('GET', 'finance/accounts') if row['kind'] == kind and row['order_id'] == identifier)
    return Decimal(history['outstanding_amount']), Decimal(order['outstanding_amount'])


@pytest.mark.parametrize('kind', ['receivable', 'payable'])
@pytest.mark.parametrize('direction', ['historical_credit', 'order_credit'])
def test_four_directions_use_actual_posted_scope_and_leave_cash_and_ledger_unchanged(cross, kind, direction):
    if direction == 'order_credit':
        make_credit(cross, kind)
    row = draft(cross, kind, direction)
    api = cross['api']
    assert row['status'] == 'draft' and row['document_no'].startswith('SOL')
    before = balances(cross, row['opening_line_id'], kind, row['order_id'])
    with orm_session() as db:
        counts = [db.scalar(select(func.count()).select_from(model)) for model in (Journal, PaymentRecord, StockMovement)]
    api('POST', f'{BASE}/{row["id"]}/post', dict(version=1, reason='未批准'), 409)
    assert balances(cross, row['opening_line_id'], kind, row['order_id']) == before
    row = execute(cross, row)
    assert row['version'] == 2 and row['status'] == 'executed'
    sign = Decimal(2 if direction == 'historical_credit' else -2)
    after = balances(cross, row['opening_line_id'], kind, row['order_id'])
    assert after == (before[0] + sign, before[1] - sign)
    assert sum(after) == sum(before)
    with orm_session() as db:
        assert counts == [db.scalar(select(func.count()).select_from(model)) for model in (Journal, PaymentRecord, StockMovement)]
    api('POST', f'{BASE}/{row["id"]}/post', dict(version=2, reason='重复执行'), 409)
    assert all(item['order_offset_amount'] == '0.00' for item in query(cross['context'], to_date='2026-01-01')['rows'])


def test_input_boundaries_and_party_account_auxiliary_mismatches_leave_no_partial_record(cross):
    for changes, status in [({'amount': '0'}, 422), ({'amount': '1.005'}, 422), ({'amount': 'NaN'}, 422),
            ({'opening_line_id': True}, 422), ({'order_id': 999}, 422), ({'reference': ' '}, 422),
            ({'reason': ' '}, 422), ({'status': 'executed'}, 422), ({'amount': '21'}, 409),
            ({'opening_line_id': cross['history']['lines'][5]['id']}, 409)]:
        draft(cross, expected=status, **changes)
    other, _, _ = sale(cross, customer=2)
    draft(cross, order_id=other['id'], expected=409)
    project = cross['api']('POST', 'finance/auxiliary/items', dict(kind='project', code='P2', name='项目乙', reason='另立项目'), 201)['id']
    other, _, _ = sale(cross, project=project)
    draft(cross, order_id=other['id'], expected=409)
    assert cross['api']('GET', BASE) == []


def test_multi_control_order_limits_only_exact_group_and_ignores_current_generic_mapping(cross):
    api, client = cross['api'], cross['client']
    order, _, _ = sale(cross, quantity='4', ship_quantity='2')
    api('PUT', 'finance/business-journals/policy', dict(version=1, start_date='2026-01-01',
        mapping={**cross['mapping'], 'receivable': 5}, reason='后续业务使用第二科目'))
    shipment = api('POST', 'shipments', dict(sales_order_id=order['id'], warehouse_id=1,
        lines=[dict(material_id=cross['material'], quantity='2')]), 201)
    approve_document(client, None, 'Shipment', shipment['id'])
    api('POST', f'shipments/{shipment["id"]}/post')
    post_source(cross, f'shipment:{shipment["id"]}')
    line = cross['history']['lines'][5]['id']
    draft(cross, opening_line_id=line, order_id=order['id'], amount='25', expected=409)
    row = execute(cross, draft(cross, opening_line_id=line, order_id=order['id'], amount='15'))
    assert row['account_id'] == 5
    scope = next(item for item in api('GET', BASE + '/options')['orders'] if item['kind'] == 'receivable' and item['order_id'] == order['id'])
    assert not scope['blockers']
    assert {item['account_id']: item['outstanding_amount'] for item in scope['groups']} == {1: '20.00', 5: '5.00'}
    # 当前映射已变更，原已过账订单仍按原科目核销。
    assert execute(cross, draft(cross, reference='OLD-MAPPING'))['account_id'] == 1


def test_competing_approved_drafts_consume_latest_order_limit_atomically(cross):
    rows = [draft(cross, amount='15', reference=value) for value in ('A', 'B')]
    for row in rows:
        approve_document(cross['client'], None, 'SubledgerOrderSettlement', row['id'], reason='核对竞争额度')
    def post(row):
        return cross['client'].post('/api/v1/' + BASE + f'/{row["id"]}/post',
            json=dict(version=1, reason='并发执行')).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(post, rows)) == [200, 409]
    assert balances(cross, rows[0]['opening_line_id'], 'receivable', rows[0]['order_id']) == (Decimal('-35'), Decimal('5'))


def test_event_failure_rolls_back_execution_and_approval(cross, monkeypatch):
    row = draft(cross)
    approve_document(cross['client'], None, 'SubledgerOrderSettlement', row['id'], reason='核对回滚')
    before = balances(cross, row['opening_line_id'], row['kind'], row['order_id'])
    from app.core import document_approval as approval
    original = approval.mark_executed
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('模拟审批审计后的故障')
    monkeypatch.setattr(approval, 'mark_executed', fail)
    cross['api']('POST', f'{BASE}/{row["id"]}/post', dict(version=1, reason='故障回滚'), 500)
    assert balances(cross, row['opening_line_id'], row['kind'], row['order_id']) == before
    with orm_session() as db:
        saved = db.get(SubledgerOrderSettlement, row['id'])
        assert saved.status == 'draft' and saved.version == 1 and saved.executed_at is None
        assert approval.find_case(db, 'SubledgerOrderSettlement', row['id']).status == 'approved'


def test_append_only_inverse_duplicate_cancel_and_original_journal_protection(cross):
    api = cross['api']
    original = execute(cross, draft(cross))
    journal = cross['sale_journal']
    today = datetime.now(timezone.utc).date().isoformat()
    api('POST', f'finance/journals/{journal["id"]}/reverse', dict(version=journal['version'], reference='BLOCKED',
        journal_date=today, reason='先撤销核销'), 409)
    inverse = api('POST', f'{BASE}/{original["id"]}/reverse', dict(reason='追加更正'), 201)
    api('POST', f'{BASE}/{original["id"]}/reverse', dict(reason='重复更正'), 409)
    api('POST', f'{BASE}/{inverse["id"]}/cancel', dict(version=1, reason='取消反向草稿'))
    inverse = api('POST', f'{BASE}/{original["id"]}/reverse', dict(reason='重新更正'), 201)
    assert inverse['reverses_document_no'] == original['document_no'] and inverse['amount'] == '-2.00'
    execute(cross, inverse)
    assert balances(cross, original['opening_line_id'], original['kind'], original['order_id']) == (Decimal('-50'), Decimal('20'))
    assert next(row for row in api('GET', BASE) if row['id'] == original['id'])['amount'] == '2.00'
    api('POST', f'{BASE}/{inverse["id"]}/reverse', dict(reason='反向再冲销'), 409)
    api('POST', f'finance/journals/{journal["id"]}/reverse', dict(version=journal['version'], reference='RELEASED',
        journal_date=today, reason='核销已撤销'), 201)


def test_preexisting_journal_reversal_cannot_post_after_bridge_execution(cross):
    api, journal = cross['api'], cross['sale_journal']
    inverse = api('POST', f'finance/journals/{journal["id"]}/reverse', dict(version=journal['version'], reference='QUEUED',
        journal_date=datetime.now(timezone.utc).date().isoformat(), reason='核销前编制'), 201)
    approve_document(cross['client'], None, 'Journal', inverse['id'], reason='审批冲销凭证')
    inverse = api('GET', f'finance/journals/{inverse["id"]}')
    execute(cross, draft(cross))
    api('POST', f'finance/journals/{inverse["id"]}/post', dict(version=inverse['version'], reason='排队冲销'), 409)


def test_separate_read_permission_and_pending_snapshot_tampering(cross):
    api = cross['api']
    for code, permissions in [('bridge_reader', ['subledger_order_settlement.view']), ('history_reader', ['subledger_opening.view']),
            ('cash_writer', ['finance.record'])]:
        api('POST', 'roles', dict(code=code, label=code, permissions=permissions), 201)
        api('POST', 'users', dict(username=code, password='permission-test-123', roles=[code]), 201)
    def auth(code):
        return {'Authorization': 'Bearer ' + api('POST', 'auth/login', dict(username=code, password='permission-test-123'))['token']}
    row = draft(cross)
    assert api('GET', BASE, headers=auth('bridge_reader'))[0]['id'] == row['id']
    assert api('GET', BASE + '/options', headers=auth('bridge_reader'))['orders']
    for code in ('history_reader', 'cash_writer'):
        api('GET', BASE, expected=403, headers=auth(code))
        api('GET', BASE + '/options', expected=403, headers=auth(code))
        api('POST', BASE, dict(opening_line_id=row['opening_line_id'], order_id=row['order_id'], direction=row['direction'],
            amount='1', reference='UNAUTHORIZED', reason='无权限'), 403, auth(code))
    api('POST', f'{BASE}/{row["id"]}/post', dict(version=1, reason='只读不能执行'), 403, auth('bridge_reader'))
    approve_document(cross['client'], None, 'SubledgerOrderSettlement', row['id'], reason='核对冻结金额')
    with orm_session(write=True) as db:
        db.get(SubledgerOrderSettlement, row['id']).amount = '1.00'
    api('POST', f'{BASE}/{row["id"]}/post', dict(version=1, reason='已批准正文变更'), 409)


def test_period_archive_freezes_both_offsets_and_blocks_locked_inverse(cross, monkeypatch):
    row = execute(cross, draft(cross))
    from app.finance import period_closing, profit_transfers
    monkeypatch.setattr(period_closing, 'utc_today', lambda: '2027-01-01')
    monkeypatch.setattr(profit_transfers, 'utc_today', lambda: '2027-01-01')
    api = cross['api']
    api('PUT', 'finance/profit-transfers/policy', dict(version=0, start_date='2026-01-01', target_account_id=3,
        cost_account_ids=[], reason='期末损益核对'))
    preview = api('GET', 'finance/profit-transfers/periods/1')
    journal = api('POST', 'finance/profit-transfers/generate', dict(period_id=1, period_version=1,
        policy_version=preview['policy_version'], fingerprint=preview['fingerprint'], reference='PROFIT', reason='期末结转'), 201)
    approve_document(cross['client'], None, 'Journal', journal['id'], reason='独立核对损益结转')
    journal = api('GET', f'finance/journals/{journal["id"]}')
    api('POST', f'finance/journals/{journal["id"]}/post', dict(version=journal['version'], reason='执行结转'))
    api('POST', 'finance/accounting-periods/1/close', dict(version=1, reason='完整核销归档'))
    archive = api('GET', 'finance/accounting-periods/1/closings')[0]
    assert archive['evidence']['subledger_order_settlements'][0]['id'] == row['id']
    assert archive['evidence']['subledger']['rows'][1]['order_offset_amount'] == '-2.00'
    api('POST', f'{BASE}/{row["id"]}/reverse', dict(reason='锁期冲销'), 409)
    assert api('GET', 'finance/accounting-periods/1/closings')[0] == archive


def test_legacy_fixed_summary_proves_original_scope_but_missing_proof_never_guesses(cross):
    with orm_session(write=True) as db:
        binding = db.scalar(select(BusinessJournalSource).where(BusinessJournalSource.journal_id == cross['sale_journal']['id']))
        snapshot = json.loads(binding.source_json)
        snapshot.pop('role_positions')
        binding.source_json = json.dumps(snapshot, ensure_ascii=False)
    row = draft(cross)
    assert row['account_id'] == 1
    with orm_session(write=True) as db:
        control = db.scalar(select(JournalLine).where(JournalLine.journal_id == cross['sale_journal']['id'], JournalLine.account_id == 1))
        control.summary = '旧外部凭证缺少用途依据'
    draft(cross, reference='UNKNOWN', expected=409)
    scope = next(item for item in cross['api']('GET', BASE + '/options')['orders'] if item['kind'] == 'receivable')
    assert any('唯一可核对' in message for message in scope['blockers'])


def test_approved_bridge_rejects_reversed_source_basis_and_keeps_draft(cross):
    api, journal = cross['api'], cross['sale_journal']
    row = draft(cross)
    approve_document(cross['client'], None, 'SubledgerOrderSettlement', row['id'], reason='固定原凭证依据')
    inverse = api('POST', f'finance/journals/{journal["id"]}/reverse', dict(version=journal['version'], reference='BEFORE-EXECUTION',
        journal_date=datetime.now(timezone.utc).date().isoformat(), reason='原凭证先冲销'), 201)
    approve_document(cross['client'], None, 'Journal', inverse['id'], reason='原凭证冲销批准')
    inverse = api('GET', f'finance/journals/{inverse["id"]}')
    api('POST', f'finance/journals/{inverse["id"]}/post', dict(version=inverse['version'], reason='先执行冲销'))
    api('POST', f'{BASE}/{row["id"]}/post', dict(version=1, reason='原依据已经冲销'), 409)
    assert api('GET', BASE)[0]['status'] == 'draft'
    draft(cross, reference='UNPOSTED', expected=409)


def test_payment_limits_include_executed_bridge_and_cancel_releases_reference(cross):
    api = cross['api']
    cancelled = draft(cross)
    api('POST', f'{BASE}/{cancelled["id"]}/cancel', dict(version=1, reason='取消错单'))
    replacement = draft(cross)
    assert replacement['document_no'] != cancelled['document_no']
    execute(cross, replacement)
    api('POST', 'finance/payment-records', dict(kind='receivable', order_id=cross['sale']['id'], action='settlement',
        amount='19', reference='TOO-MUCH'), 409)
    api('POST', 'finance/payment-records', dict(kind='receivable', order_id=cross['sale']['id'], action='settlement',
        amount='18', reference='REMAINING'), 201)
    line = replacement['opening_line_id']
    api('POST', f'finance/subledger-openings/lines/{line}/payments', dict(action='refund', amount='49', reference='TOO-MUCH', reason='余额已核销'), 409)
    api('POST', f'finance/subledger-openings/lines/{line}/payments', dict(action='refund', amount='48', reference='REMAINING', reason='最新退款额度'), 201)


def test_v96_upgrade_is_atomic_preserves_all_ledger_facts_and_only_grants_builtin_roles(cross, monkeypatch):
    from contextlib import contextmanager
    from app.core import database
    from app.core.database import connection, migrate
    from app.core.models import Base
    api = cross['api']
    api('POST', 'roles', dict(code='custom_finance', label='自定义财务', permissions=['finance.view']), 201)
    with connection() as db:
        db.execute('DROP TABLE subledger_order_settlements')
        db.execute("DELETE FROM document_approval_policies WHERE document_type='SubledgerOrderSettlement'")
        db.execute("DELETE FROM role_permissions WHERE permission_code='subledger_order_settlement.view'")
        db.execute("DELETE FROM permissions WHERE code='subledger_order_settlement.view'")
        db.execute('PRAGMA user_version=96')
        facts = [tuple(row) for row in db.execute('SELECT * FROM journals')]
    original = database.connection
    @contextmanager
    def broken():
        with original() as db:
            db.set_authorizer(lambda op, name, *_: database.sqlite3.SQLITE_DENY if
                op == database.sqlite3.SQLITE_CREATE_INDEX and name == 'subledger_order_settlement_reversal' else database.sqlite3.SQLITE_OK)
            yield db
    with monkeypatch.context() as patch:
        patch.setattr(database, 'connection', broken)
        with pytest.raises(database.sqlite3.DatabaseError):
            migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 96
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='subledger_order_settlements'").fetchone()
    migrate(); migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 97
        assert [tuple(row) for row in db.execute('SELECT * FROM journals')] == facts
        assert not db.execute('PRAGMA foreign_key_check').fetchone()
        assert {row[0] for row in db.execute("SELECT role_code FROM role_permissions WHERE permission_code='subledger_order_settlement.view'")} == {'admin', 'finance'}
        assert db.execute("SELECT COUNT(*) FROM document_approval_policies WHERE document_type='SubledgerOrderSettlement'").fetchone()[0] == 1
    assert len(Base.metadata.tables) == 197


def test_legacy_order_chain_captures_all_proofs_and_protects_indirect_changes(cross):
    api, client = cross['api'], cross['client']
    make_credit(cross, 'receivable')
    target, _, _ = sale(cross)
    transfer = api('POST', 'finance/order-settlements', dict(kind='receivable', from_order_id=cross['sale']['id'],
        to_order_id=target['id'], amount='6', reference='LEGACY-SAME', reason='同组合旧订单抵扣'), 201)
    execute_order_settlement(client, None, transfer)
    row = execute(cross, draft(cross, order_id=target['id']))
    assert any(item.get('journal_id') == cross['sale_journal']['id'] for item in row['order_evidence'])
    assert any(item['type'] == 'order_settlement' for item in row['order_evidence'])
    assert balances(cross, row['opening_line_id'], row['kind'], target['id'])[1] == Decimal('12')
    journal = cross['sale_journal']
    api('POST', f'finance/journals/{journal["id"]}/reverse', dict(version=journal['version'], reference='INDIRECT',
        journal_date=datetime.now(timezone.utc).date().isoformat(), reason='间接来源不能拆除'), 409)
    api('PUT', 'finance/business-journals/policy', dict(version=1, start_date='2026-01-01',
        mapping={**cross['mapping'], 'receivable': 5}, reason='新订单用第二科目'))
    different, _, _ = sale(cross)
    payload = dict(kind='receivable', from_order_id=cross['sale']['id'], to_order_id=different['id'],
        amount='2', reference='CROSS-SCOPE', reason='禁止拆开间接归属')
    api('POST', 'finance/order-settlements', payload, 409)
    inverse = api('POST', f'{BASE}/{row["id"]}/reverse', dict(reason='先撤销依赖'), 201)
    execute(cross, inverse)
    old_cross = api('POST', 'finance/order-settlements', payload, 201)
    execute_order_settlement(client, None, old_cross)
    # 没有跨组合归属字段的旧事实仍保留，但缺口向整条链传播，不能猜测现有额度。
    scope = next(item for item in api('GET', BASE + '/options')['orders'] if item['kind'] == 'receivable' and item['order_id'] == target['id'])
    assert any('核销链' in message for message in scope['blockers'])
    draft(cross, order_id=target['id'], reference='AMBIGUOUS', expected=409)
    reverse = api('POST', f'finance/order-settlements/{old_cross["id"]}/reverse', dict(reason='撤销旧跨归属抵扣'), 201)
    execute_order_settlement(client, None, reverse)
    assert not next(item for item in api('GET', BASE + '/options')['orders'] if item['kind'] == 'receivable' and item['order_id'] == target['id'])['blockers']
