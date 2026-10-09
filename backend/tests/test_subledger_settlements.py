"""真实审批、双边核销、并发限额、锁期与升级回滚。"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest
from sqlalchemy import select

from approval_test_helpers import approve_document, execute_subledger_payment
from app.core.database import connection, migrate
from app.core.models import DocumentApprovalCase, SubledgerSettlement
from app.core.orm import orm_session
from test_subledger_openings import subledger, create, action, query, payment
from test_ledger_foundation import ledger

BASE = '/api/v1/finance/subledger-settlements'


@pytest.fixture
def settlement(subledger):
    lines = deepcopy(subledger[4]['lines'])
    # 保持每个对象、科目、项目总账净额不变，仅拆分真实借贷原单。
    lines[0].update(debit='200')
    lines[1].update(debit='0', credit='50')
    lines[3].update(credit='110')
    lines.append({**lines[3], 'document_reference': 'AP-CREDIT', 'debit': '30', 'credit': '0'})
    record = create(subledger, lines=lines)
    for name in ('submit', 'approve', 'confirm'):
        record = action(subledger, record, name, name == 'approve')
    return subledger, record


def draft(context, **values):
    fixture, record = context
    return fixture[1]('POST', 'finance/subledger-settlements', {
        'from_line_id': record['lines'][1]['id'], 'to_line_id': record['lines'][0]['id'],
        'amount': '30', 'reference': 'OFFSET', 'reason': '双方历史欠款核对', **values}, 201)


def approve(context, row):
    approve_document(context[0][0], None, 'SubledgerSettlement', row['id'], reason='核对历史原单贷方与待结')


def post(context, row, expected=200):
    response = context[0][0].post(f'{BASE}/{row["id"]}/post', json={'version': row['version'], 'reason': '核对后执行'})
    assert response.status_code == expected, response.text
    return response.json()


def test_full_approved_offsets_as_of_reporting_and_no_new_cash_or_ledger(settlement):
    fixture, record = settlement
    before = query(fixture)
    row = draft(settlement)
    assert row['status'] == 'draft' and row['document_no'].startswith('SLS-')
    assert query(fixture)['rows'] == before['rows']
    post(settlement, row, 409)
    approve(settlement, row)
    assert query(fixture)['totals'] == before['totals']
    executed = post(settlement, row)
    assert executed['status'] == 'executed' and executed['version'] == 2
    report = query(fixture)
    assert report['rows'][0]['outstanding_amount'] == '170.00'
    assert report['rows'][1]['outstanding_amount'] == '-20.00'
    assert report['rows'][0]['offset_amount'] == '30.00'
    assert report['rows'][1]['offset_amount'] == '-30.00'
    assert report['rows'][0]['settlements'][0]['document_no'] == executed['document_no']
    assert report['totals']['receivable'] == before['totals']['receivable']
    assert query(fixture, to_date='2026-01-01')['rows'][0]['outstanding_amount'] == '200.00'
    assert '核销净额' in report['csv']
    assert fixture[1]('GET', 'finance/subledger-openings/payments') == []
    assert fixture[1]('GET', 'finance/journals') == []
    post(settlement, row, 409)
    # 已执行核销不能通过撤销期初改写历史，即使后来反向执行也一样。
    fixture[1]('POST', f'finance/subledger-openings/{record["id"]}/reverse',
        {'version': record['version'], 'reason': '重设历史'}, 409)


def test_payable_offsets_and_append_only_reversal(settlement):
    fixture, record = settlement
    row = draft(settlement, from_line_id=record['lines'][4]['id'], to_line_id=record['lines'][3]['id'], amount='30')
    approve(settlement, row); original = post(settlement, row)
    assert query(fixture)['rows'][3]['outstanding_amount'] == '80.00'
    assert query(fixture)['rows'][4]['outstanding_amount'] == '0.00'
    reverse = fixture[1]('POST', f'finance/subledger-settlements/{row["id"]}/reverse', {'reason': '原单核销更正'}, 201)
    assert reverse['amount'] == '-30.00' and reverse['reverses_id'] == row['id']
    assert query(fixture)['rows'][3]['outstanding_amount'] == '80.00'
    fixture[1]('POST', f'finance/subledger-settlements/{row["id"]}/reverse', {'reason': '重复'}, 409)
    approve(settlement, reverse); post(settlement, reverse)
    report = query(fixture)
    assert report['rows'][3]['outstanding_amount'] == '110.00'
    assert report['rows'][4]['outstanding_amount'] == '-30.00'
    saved = fixture[1]('GET', 'finance/subledger-settlements')
    assert next(item for item in saved if item['id'] == original['id'])['amount'] == '30.00'
    fixture[1]('POST', f'finance/subledger-settlements/{reverse["id"]}/reverse', {'reason': '反向再冲销'}, 409)


@pytest.mark.parametrize('mutation,code', [
    ({'amount': '0'}, 422), ({'amount': '1.005'}, 422), ({'amount': 'NaN'}, 422),
    ({'amount': '51'}, 409), ({'from_line_id': True}, 422), ({'to_line_id': 999}, 404),
    ({'reference': '  '}, 422), ({'reason': '  '}, 422), ({'status': 'executed'}, 422),
])
def test_strict_boundaries_do_not_leave_partial_record(settlement, mutation, code):
    fixture, record = settlement
    fixture[1]('POST', 'finance/subledger-settlements', {
        'from_line_id': record['lines'][1]['id'], 'to_line_id': record['lines'][0]['id'],
        'amount': '10', 'reference': 'BAD', 'reason': '输入校验', **mutation}, code)
    assert fixture[1]('GET', 'finance/subledger-settlements') == []


def test_party_kind_and_full_auxiliary_are_checked(settlement):
    fixture, record = settlement
    for source, target, expected in [(2, 0, 409), (4, 0, 409), (1, 1, 422), (0, 1, 409)]:
        fixture[1]('POST', 'finance/subledger-settlements', {
            'from_line_id': record['lines'][source]['id'], 'to_line_id': record['lines'][target]['id'],
            'amount': '10', 'reference': 'SCOPE', 'reason': '不同归属核验'}, expected)
    from app.core.models import SubledgerOpeningLine
    with orm_session(write=True) as db:
        db.get(SubledgerOpeningLine, record['lines'][1]['id']).auxiliary_json = '[]'
    fixture[1]('POST', 'finance/subledger-settlements', {
        'from_line_id': record['lines'][1]['id'], 'to_line_id': record['lines'][0]['id'],
        'amount': '10', 'reference': 'PROJECT', 'reason': '完整辅助不一致'}, 409)


def test_two_approved_drafts_compete_for_latest_credit_in_single_transaction(settlement):
    first, second = draft(settlement, amount='40', reference='A'), draft(settlement, amount='40', reference='B')
    approve(settlement, first); approve(settlement, second)
    client = settlement[0][0]
    def execute(row):
        return client.post(f'{BASE}/{row["id"]}/post', json={'version': 1, 'reason': '并发核销'}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(execute, (first, second))) == [200, 409]
    assert query(settlement[0])['rows'][1]['outstanding_amount'] == '-10.00'
    with orm_session() as db:
        assert len(list(db.scalars(select(SubledgerSettlement).where(SubledgerSettlement.status == 'executed')))) == 1


def test_approved_transfer_rechecks_cash_refund_and_requires_fresh_approval(settlement):
    fixture, record = settlement
    row = draft(settlement, amount='40'); approve(settlement, row)
    paid = payment(fixture, record['lines'][1], action='refund', amount='20', reference='REFUND')
    execute_subledger_payment(fixture[0], None, paid)
    post(settlement, row, 409)
    assert query(fixture)['rows'][1]['outstanding_amount'] == '-30.00'
    assert fixture[1]('GET', 'finance/subledger-settlements')[0]['status'] == 'draft'


def test_cancel_releases_reference_and_reversal_reservation_but_keeps_numbers(settlement):
    fixture = settlement[0]
    row = draft(settlement)
    fixture[1]('POST', f'finance/subledger-settlements/{row["id"]}/cancel', {'version': 1, 'reason': '取消错误草稿'})
    replacement = draft(settlement)
    assert replacement['document_no'] != row['document_no']
    approve(settlement, replacement)
    fixture[1]('POST', f'finance/subledger-settlements/{replacement["id"]}/cancel', {'version': 1, 'reason': '批准不可取消'}, 409)
    post(settlement, replacement)
    reverse = fixture[1]('POST', f'finance/subledger-settlements/{replacement["id"]}/reverse', {'reason': '反向草稿'}, 201)
    fixture[1]('POST', f'finance/subledger-settlements/{reverse["id"]}/cancel', {'version': 1, 'reason': '暂不更正'})
    again = fixture[1]('POST', f'finance/subledger-settlements/{replacement["id"]}/reverse', {'reason': '重新核对'}, 201)
    assert again['document_no'] != reverse['document_no']


def test_execution_event_failure_rolls_back_both_balances(settlement, monkeypatch):
    row = draft(settlement); approve(settlement, row)
    from app.finance import subledger_settlements as module
    original = module.approval.mark_executed
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('模拟审计写后故障')
    monkeypatch.setattr(module.approval, 'mark_executed', fail)
    response = settlement[0][0].post(f'{BASE}/{row["id"]}/post', json={'version': 1, 'reason': '故障回滚'})
    assert response.status_code == 500
    assert query(settlement[0])['rows'][0]['outstanding_amount'] == '200.00'
    with orm_session() as db:
        saved = db.get(SubledgerSettlement, row['id'])
        assert saved.status == 'draft' and saved.version == 1 and saved.executed_at is None
        assert db.scalar(select(DocumentApprovalCase).where(DocumentApprovalCase.document_type == 'SubledgerSettlement')).status == 'approved'


def test_closed_period_keeps_fixed_offset_evidence_and_blocks_reversal(settlement, monkeypatch):
    fixture = settlement[0]
    row = draft(settlement); approve(settlement, row); post(settlement, row)
    from app.finance import period_closing
    monkeypatch.setattr(period_closing, 'utc_today', lambda: '2027-01-01')
    fixture[1]('POST', 'finance/accounting-periods/1/close', {'version': 1, 'reason': '核销归档'})
    evidence = fixture[1]('GET', 'finance/accounting-periods/1/closings')[0]['evidence']['subledger']
    assert evidence['rows'][0]['offset_amount'] == '30.00'
    assert evidence['rows'][0]['settlements'][0]['from_document_reference'] == 'OLD-B'
    fixture[1]('POST', f'finance/subledger-settlements/{row["id"]}/reverse', {'reason': '锁期拒绝'}, 409)


def test_read_permission_is_separate_from_record_and_reverse_and_snapshot_tampering(settlement):
    fixture, record = settlement
    fixture[1]('POST', 'roles', {'code': 'history_reader', 'label': '历史只读', 'permissions': ['subledger_opening.view']}, 201)
    fixture[1]('POST', 'users', {'username': 'history_reader', 'password': 'reader-pass-123', 'roles': ['history_reader']}, 201)
    reader = {'Authorization': 'Bearer ' + fixture[1]('POST', 'auth/login', {'username': 'history_reader', 'password': 'reader-pass-123'})['token']}
    row = draft(settlement); approve(settlement, row)
    assert fixture[1]('GET', 'finance/subledger-settlements', headers=reader)[0]['from_document_reference'] == 'OLD-B'
    fixture[1]('POST', f'finance/subledger-settlements/{row["id"]}/post', {'version': 1, 'reason': '越权'}, 403, reader)
    fixture[1]('POST', f'finance/subledger-settlements/{row["id"]}/reverse', {'reason': '越权'}, 403, reader)
    with orm_session(write=True) as db:
        db.get(SubledgerSettlement, row['id']).amount = '20.00'
    post(settlement, row, 409)
    assert query(fixture)['rows'][0]['outstanding_amount'] == '200.00'


def test_v95_upgrade_preserves_cash_and_rolls_back_failed_table_creation(settlement, monkeypatch):
    fixture = settlement[0]
    with connection() as db:
        db.execute('DROP TABLE subledger_settlements')
        db.execute("DELETE FROM document_approval_policies WHERE document_type='SubledgerSettlement'")
        db.execute('PRAGMA user_version=95')
        original_payments = [tuple(row) for row in db.execute('SELECT * FROM subledger_payments')]
    import app.core.database as database
    original_connection = database.connection
    from contextlib import contextmanager
    @contextmanager
    def broken():
        with original_connection() as db:
            db.set_authorizer(lambda op, name, *_: database.sqlite3.SQLITE_DENY if
                op == database.sqlite3.SQLITE_CREATE_INDEX and name == 'subledger_settlement_reference' else database.sqlite3.SQLITE_OK)
            yield db
    with monkeypatch.context() as patch:
        patch.setattr(database, 'connection', broken)
        with pytest.raises(database.sqlite3.DatabaseError):
            migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 95
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='subledger_settlements'").fetchone()
    migrate(); migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 101
        assert [tuple(row) for row in db.execute('SELECT * FROM subledger_payments')] == original_payments
        assert not db.execute('PRAGMA foreign_key_check').fetchone()
    assert fixture[1]('GET', 'finance/subledger-settlements') == []
