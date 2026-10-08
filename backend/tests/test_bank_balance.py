"""银行余额调节的已过账来源、分组勾对、独立复核及失效证据。"""

import base64
import hashlib
import json
import sqlite3

from app.core.database import database_path, migrate
from app.core.models import Base
from test_journals import journals
from test_ledger_foundation import ledger
from test_opening_balances import confirmed
from test_ledger_reports import make

BASE = '/api/v1/finance'
PATH = BASE + '/bank-balance'
LINES = BASE + '/bank-reconciliation'


def setup_bank(journals):
    client, _ = journals
    confirmed(journals)
    account = client.post(LINES + '/accounts', json={'code': 'OPERATING', 'name': '基本户'})
    assert account.status_code == 201, account.text
    account = account.json()
    binding = client.post(PATH + f'/accounts/{account["id"]}/binding', json={
        'ledger_account_id': 1, 'opening_balance': '123.45',
        'effective_date': '2026-01-01', 'version': account['version'],
        'reason': '核对总账期初及银行期初凭据'})
    assert binding.status_code == 200, binding.text
    return account['id']


def bank_line(client, account_id, transaction_id, amount, day='2026-01-10'):
    response = client.post(LINES + '/lines/import', json={'account_id': account_id,
        'lines': [{'transaction_id': transaction_id, 'occurred_on': day,
            'amount': amount, 'counterparty': '往来方', 'note': ''}]})
    assert response.status_code == 201, response.text
    return response.json()['line_ids'][0]


def scope(account_id, closing='133.45', day='2026-01-10'):
    return {'account_id': account_id, 'as_of_date': day, 'declared_bank_closing': closing}


def test_existing_account_keeps_v71_report_fingerprint(journals):
    client, _ = journals
    opening = confirmed(journals)
    account = client.post(LINES + '/accounts', json={'code': 'LEGACY-BANK', 'name': '旧账户'}).json()
    bound = client.post(PATH + f'/accounts/{account["id"]}/binding', json={
        'ledger_account_id': 1, 'opening_balance': '123.45',
        'effective_date': '2026-01-01', 'version': account['version'],
        'reason': '旧版银行期初核对'})
    assert bound.status_code == 200, bound.text
    evidence = dict(account_id=account['id'], account_version=bound.json()['version'],
        ledger_account_id=1, opening_balance='123.45', effective_date='2026-01-01',
        as_of_date='2026-01-01', formal_opening_id=opening['id'],
        declared_bank_closing='123.45', bank_lines=[], book_lines=[], matches=[],
        ledger_opening='123.45')
    original = hashlib.sha256(json.dumps(evidence, sort_keys=True,
        separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    response = client.post(PATH + '/preview', json=scope(account['id'], '123.45', '2026-01-01'))
    assert response.status_code == 200, response.text
    assert response.json()['fingerprint'] == original


def test_v71_upgrade_keeps_existing_bank_report_and_creates_opening_tables(journals):
    client, _ = journals
    account_id = setup_bank(journals)
    report = client.post(PATH + '/reports', json={**scope(account_id, '123.45', '2026-01-01'),
        'reason': '升级前调节表'}).json()
    with sqlite3.connect(database_path()) as db:
        for table in ('bank_opening_clearance_reversals', 'bank_opening_clearance_members',
                      'bank_opening_clearances', 'bank_opening_items'):
            db.execute(f'DROP TABLE {table}')
        db.execute('PRAGMA user_version = 71')
    migrate()
    migrate()
    overview = client.get(PATH + '/overview').json()
    assert overview['opening_items'] == overview['opening_clearances'] == []
    assert overview['reports'][0]['id'] == report['id']
    assert overview['reports'][0]['stale'] is False
    with sqlite3.connect(database_path()) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 97
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_opening_unreached_items_clear_with_later_evidence_and_keep_history(journals):
    client, reviewer = journals
    confirmed(journals)
    account = client.post(LINES + '/accounts', json={'code': 'OPENING', 'name': '期初未达户'}).json()
    account_id = account['id']
    binding = client.post(PATH + f'/accounts/{account_id}/binding', json={
        'ledger_account_id': 1, 'opening_balance': '135.45',
        'effective_date': '2026-01-01', 'version': account['version'],
        'reason': '核对启用日前的对账单和总账',
        'opening_items': [
            {'side': 'bank', 'occurred_on': '2025-12-30', 'amount': '20.00',
             'reference': 'BANK-OLD', 'description': '银行已收企业未记'},
            {'side': 'book', 'occurred_on': '2025-12-31', 'amount': '8.00',
             'reference': 'BOOK-OLD', 'description': '企业已收银行未记'}]})
    assert binding.status_code == 200, binding.text
    opening = {item['side']: item for item in client.get(PATH + '/overview').json()['opening_items']}
    assert len(opening) == 2
    first = client.post(PATH + '/preview', json=scope(account_id, '135.45')).json()
    assert first['balanced'] is True
    assert first['adjusted_bank'] == first['adjusted_book'] == '143.45'
    assert len(first['bank_opening_unmatched']) == len(first['book_opening_unmatched']) == 1
    old = client.post(PATH + '/reports', json={**scope(account_id, '135.45'),
        'reason': '期初未达项首次调节'}).json()
    assert client.post(PATH + f'/reports/{old["id"]}/decision', headers=reviewer,
        json={'action': 'approve', 'reason': '期初凭据核实'}).status_code == 201
    journal = make(journals, 'OPENING-BOOK', '2026-01-10', '20.00')
    line_id = bank_line(client, account_id, 'OPENING-BANK', '8.00')
    book_id = journal['lines'][0]['id']
    wrong = client.post(PATH + f'/opening-items/{opening["bank"]["id"]}/clearances', json={
        'source_ids': [book_id, book_id], 'reason': '重复来源'})
    assert wrong.status_code == 422
    bank_clearance = client.post(PATH + f'/opening-items/{opening["bank"]["id"]}/clearances',
        json={'source_ids': [book_id], 'reason': '已过账收款凭证'})
    assert bank_clearance.status_code == 201, bank_clearance.text
    assert client.post(PATH + '/ledger-matches', json={'account_id': account_id,
        'bank_line_ids': [line_id], 'journal_line_ids': [book_id],
        'reason': '不可重复占用'}).status_code == 409
    book_clearance = client.post(PATH + f'/opening-items/{opening["book"]["id"]}/clearances',
        json={'source_ids': [line_id], 'reason': '银行流水已到账'})
    assert book_clearance.status_code == 201, book_clearance.text
    current = client.post(PATH + '/preview', json=scope(account_id, '143.45')).json()
    assert current['balanced'] is True
    assert current['bank_opening_unmatched'] == current['book_opening_unmatched'] == []
    assert current['bank_unmatched'] == current['book_unmatched'] == []
    assert len(current['clearance_evidence']) == 2
    assert client.get(PATH + '/overview').json()['reports'][0]['stale'] is True
    reversed_response = client.post(PATH + f'/opening-clearances/{bank_clearance.json()["id"]}/reverse',
        json={'reason': '凭证依据需重新核查'})
    assert reversed_response.status_code == 201
    assert client.post(PATH + f'/opening-clearances/{bank_clearance.json()["id"]}/reverse',
        json={'reason': '重复撤销'}).status_code == 409
    after = client.post(PATH + '/preview', json=scope(account_id, '143.45')).json()
    assert len(after['bank_opening_unmatched']) == len(after['book_unmatched']) == 1
    assert after['balanced'] is True
    overview = client.get(PATH + '/overview').json()
    assert next(item for item in overview['opening_clearances']
        if item['id'] == bank_clearance.json()['id'])['reversal']['reason'] == '凭证依据需重新核查'


def test_opening_binding_rejects_unbalanced_or_invalid_items_without_partial_write(journals):
    client, _ = journals
    confirmed(journals)
    account = client.post(LINES + '/accounts', json={'code': 'BAD-OPENING', 'name': '错误期初'}).json()
    base = {'ledger_account_id': 1, 'opening_balance': '133.45',
        'effective_date': '2026-01-01', 'version': account['version'], 'reason': '核对期初'}
    path = PATH + f'/accounts/{account["id"]}/binding'
    assert client.post(path, json={**base, 'opening_items': []}).status_code == 409
    item = {'side': 'bank', 'occurred_on': '2025-12-31', 'amount': '10.00',
        'reference': 'OLD', 'description': '期初银行已收'}
    assert client.post(path, json={**base, 'opening_items': [{**item,
        'occurred_on': '2026-01-01'}]}).status_code == 422
    assert client.post(path, json={**base, 'opening_items': [item, item]}).status_code == 422
    assert client.post(path, json={**base, 'opening_items': [{**item,
        'amount': '10.001'}]}).status_code == 422
    assert client.get(PATH + '/overview').json()['opening_items'] == []
    assert client.get(PATH + '/overview').json()['accounts'][0]['version'] == 1


def test_opening_clearance_respects_report_cutoff_and_negative_direction(journals):
    client, _ = journals
    confirmed(journals)
    account = client.post(LINES + '/accounts', json={'code': 'OPEN-OUT', 'name': '期初未达付款'}).json()
    account_id = account['id']
    bound = client.post(PATH + f'/accounts/{account_id}/binding', json={
        'ledger_account_id': 1, 'opening_balance': '119.45',
        'effective_date': '2026-01-01', 'version': account['version'],
        'reason': '核对期初支出', 'opening_items': [{
            'side': 'bank', 'occurred_on': '2025-12-31', 'amount': '-4.00',
            'reference': 'BANK-OUT-OLD', 'description': '银行已付企业未记'}]})
    assert bound.status_code == 200, bound.text
    item_id = client.get(PATH + '/overview').json()['opening_items'][0]['id']
    early = scope(account_id, '119.45', '2026-01-05')
    preview = client.post(PATH + '/preview', json=early).json()
    assert preview['balanced'] is True
    assert preview['adjusted_bank'] == preview['adjusted_book'] == '119.45'
    report = client.post(PATH + '/reports', json={**early,
        'reason': '月初期初未达付款仍未入账'}).json()
    journal = make(journals, 'OLD-OUT', '2026-01-10', '4.00', credit_first=True)
    source_id = journal['lines'][0]['id']
    clearance = client.post(PATH + f'/opening-items/{item_id}/clearances', json={
        'source_ids': [source_id], 'reason': '月中已补记付款'})
    assert clearance.status_code == 201, clearance.text
    early_after = client.post(PATH + '/preview', json=early).json()
    assert early_after['fingerprint'] == preview['fingerprint']
    assert len(early_after['bank_opening_unmatched']) == 1
    assert client.get(PATH + '/overview').json()['reports'][0]['stale'] is False
    month_end = client.post(PATH + '/preview', json=scope(account_id, '119.45', '2026-01-31')).json()
    assert month_end['balanced'] is True
    assert month_end['bank_opening_unmatched'] == month_end['book_unmatched'] == []
    assert client.post(PATH + f'/opening-items/{item_id}/clearances', json={
        'source_ids': [source_id], 'reason': '重复核销'}).status_code == 409
    assert report['snapshot']['bank_opening_unmatched'][0]['id'] == item_id


def test_grouped_bank_and_posted_ledger_reconcile_with_independent_review(journals):
    client, reviewer = journals
    account_id = setup_bank(journals)
    journal = make(journals, 'BANK-BOOK', '2026-01-10', '10.00')
    first = bank_line(client, account_id, 'BANK-4', '4.00')
    second = bank_line(client, account_id, 'BANK-6', '6.00')
    before = client.post(PATH + '/preview', json=scope(account_id))
    assert before.status_code == 200, before.text
    assert before.json()['balanced'] is True
    assert len(before.json()['bank_unmatched']) == 2
    assert len(before.json()['book_unmatched']) == 1
    match = client.post(PATH + '/ledger-matches', json={
        'account_id': account_id, 'bank_line_ids': [first, second],
        'journal_line_ids': [journal['lines'][0]['id']], 'reason': '核对两笔入账合并凭证'})
    assert match.status_code == 201, match.text
    assert match.json()['amount'] == '10.00'
    assert client.post(PATH + '/ledger-matches', json={
        'account_id': account_id, 'bank_line_ids': [first],
        'journal_line_ids': [journal['lines'][0]['id']], 'reason': '重复'}).status_code == 409
    preview = client.post(PATH + '/preview', json=scope(account_id)).json()
    assert preview['bank_unmatched'] == [] and preview['book_unmatched'] == []
    assert preview['bank_closing_computed'] == '133.45'
    report = client.post(PATH + '/reports', json={**scope(account_id), 'reason': '月末核对原始对账单'})
    assert report.status_code == 201, report.text
    report_id = report.json()['id']
    assert client.post(PATH + f'/reports/{report_id}/decision', json={
        'action': 'approve', 'reason': '复核无误'}).status_code == 403
    approved = client.post(PATH + f'/reports/{report_id}/decision', headers=reviewer,
        json={'action': 'approve', 'reason': '核对银行凭据及总账'})
    assert approved.status_code == 201, approved.text
    assert client.post(PATH + f'/reports/{report_id}/decision', headers=reviewer,
        json={'action': 'approve', 'reason': '重复'}).status_code == 409
    overview = client.get(PATH + '/overview').json()
    assert overview['reports'][0]['status'] == 'approved'
    assert overview['reports'][0]['snapshot']['fingerprint'] == preview['fingerprint']
    assert overview['matches'][0]['members'][0]['side'] in ('bank', 'book')


def test_unreached_items_adjust_both_sides_and_source_changes_block_review(journals):
    client, reviewer = journals
    account_id = setup_bank(journals)
    journal = make(journals, 'BOOK-ONLY', '2026-01-10', '5.00')
    bank_line(client, account_id, 'BANK-ONLY', '2.00')
    current = scope(account_id, '125.45')
    preview = client.post(PATH + '/preview', json=current).json()
    assert preview['book_closing'] == '128.45'
    assert preview['adjusted_bank'] == preview['adjusted_book'] == '130.45'
    assert preview['balanced'] is True
    assert preview['book_unmatched'][0]['id'] == journal['lines'][0]['id']
    report = client.post(PATH + '/reports', json={**current, 'reason': '留存未达项'}).json()
    bank_line(client, account_id, 'LATE', '1.00')
    stale = client.post(PATH + f'/reports/{report["id"]}/decision', headers=reviewer,
        json={'action': 'approve', 'reason': '复核'})
    assert stale.status_code == 409
    assert '来源已变化' in stale.json()['detail']
    assert client.get(PATH + '/overview').json()['reports'][0]['status'] == 'draft'
    assert client.get(PATH + '/overview').json()['reports'][0]['stale'] is True
    rejected = client.post(PATH + f'/reports/{report["id"]}/decision', headers=reviewer,
        json={'action': 'reject', 'reason': '银行流水已补登，需重编'})
    assert rejected.status_code == 201
    assert client.get(PATH + '/overview').json()['reports'][0]['status'] == 'rejected'


def test_binding_and_match_guard_invalid_scope(journals):
    client, _ = journals
    account = client.post(LINES + '/accounts', json={'code': 'UNBOUND', 'name': '未绑定'}).json()
    assert client.post(PATH + '/preview', json=scope(account['id'])).status_code == 409
    assert client.post(PATH + f'/accounts/{account["id"]}/binding', json={
        'ledger_account_id': 1, 'opening_balance': '0.00',
        'effective_date': '2026-01-01', 'version': 1, 'reason': '尚无期初'}).status_code == 409
    confirmed(journals)
    bad = client.post(PATH + f'/accounts/{account["id"]}/binding', json={
        'ledger_account_id': 1, 'opening_balance': '0.001',
        'effective_date': '2026-01-01', 'version': 1, 'reason': '金额精度错误'})
    assert bad.status_code == 422
    unequal = client.post(PATH + f'/accounts/{account["id"]}/binding', json={
        'ledger_account_id': 1, 'opening_balance': '120.00',
        'effective_date': '2026-01-01', 'version': 1, 'reason': '期初不符'})
    assert unequal.status_code == 409
    good = client.post(PATH + f'/accounts/{account["id"]}/binding', json={
        'ledger_account_id': 1, 'opening_balance': '123.45',
        'effective_date': '2026-01-01', 'version': 1, 'reason': '确认银行期初'})
    assert good.status_code == 200, good.text
    assert good.json()['version'] == 2
    assert client.post(PATH + f'/accounts/{account["id"]}/binding', json={
        'ledger_account_id': 1, 'opening_balance': '125.45',
        'effective_date': '2026-01-01', 'version': 1, 'reason': '旧版本覆盖'}).status_code == 409
    assert client.post(LINES + '/lines/import', json={'account_id': account['id'],
        'lines': [{'transaction_id': 'OLD', 'occurred_on': '2025-12-31',
            'amount': '1.00'}]}).status_code == 409
    assert client.get(PATH + '/overview').json()['account_changes'][0]['reason'] == '确认银行期初'


def test_ledger_binding_is_unique_and_conflict_preserves_audit(journals):
    client, _ = journals
    first_id = setup_bank(journals)
    second = client.post(LINES + '/accounts', json={'code': 'SECOND', 'name': '另一个银行户'}).json()
    conflict = client.post(PATH + f'/accounts/{second["id"]}/binding', json={
        'ledger_account_id': 1, 'opening_balance': '123.45',
        'effective_date': '2026-01-01', 'version': 1, 'reason': '错误的重复绑定'})
    assert conflict.status_code == 409
    overview = client.get(PATH + '/overview').json()
    assert next(item for item in overview['accounts'] if item['id'] == second['id'])['version'] == 1
    assert len(overview['account_changes']) == 1
    assert overview['account_changes'][0]['account_id'] == first_id


def test_csv_import_rechecks_bound_opening_date_without_partial_batch(journals):
    client, _ = journals
    account_id = setup_bank(journals)
    content = ('transaction_id,occurred_on,amount,counterparty,note\n'
        'VALID,2026-01-10,1.00,甲,收款\n'
        'EARLY,2025-12-31,1.00,乙,旧流水\n').encode()
    payload = {'account_id': account_id, 'file_name': 'opening.csv',
        'content_base64': base64.b64encode(content).decode()}
    assert client.post(LINES + '/imports/csv/preview', json=payload).status_code == 409
    assert client.post(LINES + '/imports/csv', json=payload).status_code == 409
    assert client.get(LINES + '/overview').json()['lines'] == []


def test_outgoing_unreached_items_and_match_reversal(journals):
    client, _ = journals
    account_id = setup_bank(journals)
    journal = make(journals, 'OUTGOING', '2026-01-10', '4.00', credit_first=True)
    line_id = bank_line(client, account_id, 'BANK-OUT', '-2.00')
    preview = client.post(PATH + '/preview', json=scope(account_id, '121.45')).json()
    assert preview['book_closing'] == '119.45'
    assert preview['adjusted_bank'] == preview['adjusted_book'] == '117.45'
    assert preview['balanced'] is True
    bad = client.post(PATH + '/ledger-matches', json={'account_id': account_id,
        'bank_line_ids': [line_id], 'journal_line_ids': [journal['lines'][0]['id']],
        'reason': '金额不同'})
    assert bad.status_code == 409
    second = bank_line(client, account_id, 'BANK-OUT-2', '-2.00')
    group = client.post(PATH + '/ledger-matches', json={'account_id': account_id,
        'bank_line_ids': [line_id, second], 'journal_line_ids': [journal['lines'][0]['id']],
        'reason': '两笔出账对应同一分录'})
    assert group.status_code == 201, group.text
    assert group.json()['amount'] == '-4.00'
    reverse = client.post(PATH + f'/ledger-matches/{group.json()["id"]}/reverse',
        json={'reason': '银行交易号核对错误'})
    assert reverse.status_code == 201
    assert client.post(PATH + f'/ledger-matches/{group.json()["id"]}/reverse',
        json={'reason': '重复'}).status_code == 409
    assert len(client.post(PATH + '/preview', json=scope(account_id, '119.45')).json()['bank_unmatched']) == 2


def test_new_reviewed_report_supersedes_old_source_snapshot(journals):
    client, reviewer = journals
    account_id = setup_bank(journals)
    make(journals, 'FIRST', '2026-01-10', '10.00')
    bank_line(client, account_id, 'FIRST-BANK', '10.00')
    first = client.post(PATH + '/reports', json={**scope(account_id), 'reason': '首次银行凭据'}).json()
    assert client.post(PATH + f'/reports/{first["id"]}/decision', headers=reviewer,
        json={'action': 'approve', 'reason': '核对相符'}).status_code == 201
    duplicate = client.post(PATH + '/reports', json={**scope(account_id), 'reason': '重复留存'}).json()
    assert client.post(PATH + f'/reports/{duplicate["id"]}/decision', headers=reviewer,
        json={'action': 'approve', 'reason': '重复复核'}).status_code == 409
    make(journals, 'SECOND', '2026-01-10', '5.00')
    bank_line(client, account_id, 'SECOND-BANK', '5.00')
    overview = client.get(PATH + '/overview').json()
    assert next(item for item in overview['reports'] if item['id'] == first['id'])['stale'] is True
    replacement = client.post(PATH + '/reports', json={**scope(account_id, '138.45'),
        'reason': '补入银行流水和已过账凭证'}).json()
    assert client.post(PATH + f'/reports/{replacement["id"]}/decision', headers=reviewer,
        json={'action': 'approve', 'reason': '重新核对相符'}).status_code == 201
    reports = {item['id']: item for item in client.get(PATH + '/overview').json()['reports']}
    assert reports[first['id']]['status'] == 'superseded'
    assert reports[replacement['id']]['status'] == 'approved'


def test_v70_upgrade_keeps_bank_data_and_adds_reconciliation_schema(monkeypatch, tmp_path):
    path = tmp_path / 'bank-balance-v70.db'
    monkeypatch.setenv('NEXORA_DB_PATH', str(path))
    migrate()
    with sqlite3.connect(path) as db:
        for table in ('bank_opening_clearance_reversals', 'bank_opening_clearance_members',
                      'bank_opening_clearances', 'bank_opening_items',
                      'bank_balance_report_decisions', 'bank_balance_reports',
                      'bank_ledger_match_reversals', 'bank_ledger_match_members',
                      'bank_ledger_match_groups', 'bank_account_changes'):
            db.execute(f'DROP TABLE {table}')
        db.execute('DROP INDEX bank_accounts_ledger_account')
        for column in ('ledger_account_id', 'opening_balance', 'effective_date', 'version'):
            db.execute(f'ALTER TABLE bank_accounts DROP COLUMN {column}')
        db.execute("DELETE FROM role_permissions WHERE permission_code IN ('bank_reconciliation.reconcile','bank_reconciliation.review')")
        db.execute("DELETE FROM permissions WHERE code IN ('bank_reconciliation.reconcile','bank_reconciliation.review')")
        db.execute('PRAGMA user_version = 70')
    migrate()
    migrate()
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 97
        assert {name for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")} >= {
            'bank_opening_items', 'bank_opening_clearances',
            'bank_opening_clearance_members', 'bank_opening_clearance_reversals'}
        assert {row[1] for row in db.execute('PRAGMA table_info(bank_accounts)')} >= {
            'ledger_account_id', 'opening_balance', 'effective_date', 'version'}
        assert db.execute("SELECT COUNT(*) FROM permissions WHERE code LIKE 'bank_reconciliation.%'").fetchone()[0] == 7
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    assert len(Base.metadata.tables) == 197
