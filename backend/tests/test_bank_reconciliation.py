"""银行流水与两类收付款的精确勾对、撤销和升级回归。"""

import os
import base64
import hashlib
import sqlite3
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.core.database import migrate
from app.core.models import PaymentRecord, SubledgerOpeningLine, SubledgerPayment
from app.core.orm import add_model, orm_session
from app.finance.bank_reconciliation import source
from app.main import app


def test_bank_lines_match_exact_direction_and_keep_reversal_history(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'bank.db'))
    with TestClient(app, client=('127.0.0.1', 12000)) as client:
        base = '/api/v1'
        assert client.post(base + '/setup/admin', json={
            'username': 'admin', 'password': 'secure-pass-123'}).status_code == 201
        token = client.post(base + '/auth/login', json={
            'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
        admin = {'Authorization': 'Bearer ' + token}
        path = base + '/finance/bank-reconciliation'
        assert client.get(path + '/overview').status_code == 401
        assert client.post(base + '/users', headers=admin, json={
            'username': 'buyer', 'password': 'secure-pass-123', 'roles': ['buyer']}).status_code == 201
        buyer_token = client.post(base + '/auth/login', json={
            'username': 'buyer', 'password': 'secure-pass-123'}).json()['token']
        assert client.get(path + '/overview', headers={'Authorization': 'Bearer ' + buyer_token}).status_code == 403

        account = client.post(path + '/accounts', headers=admin, json={
            'code': 'OPERATING', 'name': '基本户'}).json()
        assert account['code'] == 'OPERATING'
        assert client.post(path + '/accounts', headers=admin, json={
            'code': 'OPERATING', 'name': '重复'}).status_code == 409
        with orm_session(write=True) as db:
            incoming = add_model(db, PaymentRecord(kind='receivable', order_id=7, action='settlement',
                amount='12.30', reference='人工收款', note='', created_by=1))
            outgoing = add_model(db, PaymentRecord(kind='payable', order_id=9, action='settlement',
                amount='12.30', reference='人工付款', note='', created_by=1))
            income_id, expense_id = incoming.id, outgoing.id

        line = lambda transaction_id, amount: dict(transaction_id=transaction_id,
            occurred_on='2026-10-03', amount=amount, counterparty='往来方')
        imported = client.post(path + '/lines/import', headers=admin, json={
            'account_id': account['id'], 'lines': [line('BANK-IN', '12.30'), line('BANK-OUT', '-12.30')]}).json()
        assert imported['imported_count'] == 2
        inbound_id, outbound_id = imported['line_ids']
        assert client.post(path + '/lines/import', headers=admin, json={
            'account_id': account['id'], 'lines': [line('NEW', '1.00'), line('BANK-IN', '12.30')]}).status_code == 409
        assert len(client.get(path + '/overview', headers=admin).json()['lines']) == 2
        wrong = dict(statement_line_id=inbound_id, source_type='order_payment',
            source_id=expense_id, reason='核对银行交易号')
        assert client.post(path + '/matches', headers=admin, json=wrong).status_code == 409
        wrong['source_id'] = income_id
        matched = client.post(path + '/matches', headers=admin, json=wrong)
        assert matched.status_code == 201
        assert client.post(path + '/matches', headers=admin, json=wrong).status_code == 409
        outbound = {**wrong, 'statement_line_id': outbound_id, 'source_id': expense_id}
        assert client.post(path + '/matches', headers=admin, json=outbound).status_code == 201
        overview = client.get(path + '/overview', headers=admin).json()
        assert {item['match_id'] for item in overview['lines']} == {matched.json()['id'],
            overview['matches'][0]['id']}
        assert next(item for item in overview['sources'] if item['source_id'] == expense_id)['bank_amount'] == '-12.30'
        reverse = client.post(path + f'/matches/{matched.json()["id"]}/reverse', headers=admin,
            json={'reason': '银行流水关联错误'})
        assert reverse.status_code == 201
        assert client.post(path + f'/matches/{matched.json()["id"]}/reverse', headers=admin,
            json={'reason': '重复撤销'}).status_code == 409
        assert client.post(path + '/matches', headers=admin, json=wrong).status_code == 201
        evidence = client.get(path + '/overview', headers=admin).json()['matches']
        assert any(item['id'] == matched.json()['id'] and item['reversal']['reason'] == '银行流水关联错误'
                   for item in evidence)
        assert len(evidence) == 3


def test_bank_input_validation_and_subledger_direction(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'bank-validation.db'))
    with TestClient(app, client=('127.0.0.1', 12000)) as client:
        base = '/api/v1'
        client.post(base + '/setup/admin', json={'username': 'admin', 'password': 'secure-pass-123'})
        token = client.post(base + '/auth/login', json={
            'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
        headers = {'Authorization': 'Bearer ' + token}
        path = base + '/finance/bank-reconciliation'
        account_id = client.post(path + '/accounts', headers=headers,
            json={'code': 'CHECKING', 'name': '结算账户'}).json()['id']
        line = dict(transaction_id='BAD', occurred_on='2026-10-03', amount='1.234')
        for invalid in ({**line}, {**line, 'amount': 1.23}, {**line, 'amount': '1e2'},
                        {**line, 'amount': '0.00'},
                        {**line, 'amount': '1.00', 'occurred_on': '2026-02-30'}):
            response = client.post(path + '/lines/import', headers=headers,
                json={'account_id': account_id, 'lines': [invalid]})
            assert response.status_code == 422
        assert client.post(path + '/lines/import', headers=headers,
            json={'account_id': account_id, 'lines': [
                {**line, 'amount': '1.00'}, {**line, 'amount': '2.00'}]}).status_code == 422
        assert client.get(path + '/overview', headers=headers).json()['lines'] == []

    class FakeSession:
        def get(self, model, identifier):
            if model is SubledgerPayment:
                return SimpleNamespace(id=identifier, opening_line_id=3, action='settlement',
                    amount='7.50', reference='历史付款', created_at='2026-10-03',status='executed',executed_at=None)
            if model is SubledgerOpeningLine:
                return SimpleNamespace(kind='payable', document_reference='OLD-9')
            return None

    item = source(FakeSession(), 'subledger_payment', 2)
    assert item['bank_amount'] == '-7.50'
    assert item['label'] == '历史原单 OLD-9'


def test_v68_upgrade_adds_bank_models_and_permissions(monkeypatch, tmp_path):
    path = tmp_path / 'bank-upgrade.db'
    monkeypatch.setenv('NEXORA_DB_PATH', str(path))
    migrate()
    with sqlite3.connect(path) as db:
        for table in ('bank_match_reversals', 'bank_matches', 'bank_statement_lines', 'bank_accounts'):
            db.execute(f'DROP TABLE {table}')
        db.execute("DELETE FROM role_permissions WHERE permission_code LIKE 'bank_reconciliation.%'")
        db.execute("DELETE FROM permissions WHERE code LIKE 'bank_reconciliation.%'")
        db.execute("DELETE FROM permission_groups WHERE code='finance.bank_reconciliation'")
        db.execute('PRAGMA user_version = 68')
    migrate()
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 92
        assert db.execute("SELECT COUNT(*) FROM permissions WHERE code LIKE 'bank_reconciliation.%'").fetchone()[0] == 7
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_csv_preview_import_provenance_and_atomic_conflicts(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'bank-csv.db'))
    with TestClient(app, client=('127.0.0.1', 12000)) as client:
        base = '/api/v1'
        client.post(base + '/setup/admin', json={'username': 'admin', 'password': 'secure-pass-123'})
        token = client.post(base + '/auth/login', json={
            'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
        headers = {'Authorization': 'Bearer ' + token}
        path = base + '/finance/bank-reconciliation'
        account = client.post(path + '/accounts', headers=headers,
            json={'code': 'CSV', 'name': '导入账户'}).json()['id']
        raw = ('transaction_id,occurred_on,amount,counterparty,note\r\n'
            'CSV-1,2026-10-03,12.30,甲,"含,逗号"\r\n'
            'CSV-2,2026-10-03,-2.00,乙,\r\n').encode('utf-8')
        payload = dict(account_id=account, file_name='statement.csv',
            content_base64=base64.b64encode(raw).decode())
        assert client.post(path + '/imports/csv/preview', json=payload).status_code == 401
        assert client.post(base + '/users', headers=headers, json={
            'username': 'buyer', 'password': 'secure-pass-123', 'roles': ['buyer']}).status_code == 201
        buyer_token = client.post(base + '/auth/login', json={
            'username': 'buyer', 'password': 'secure-pass-123'}).json()['token']
        buyer = {'Authorization': 'Bearer ' + buyer_token}
        assert client.post(path + '/imports/csv/preview', headers=buyer, json=payload).status_code == 403
        assert client.post(path + '/imports/csv', headers=buyer, json=payload).status_code == 403
        preview = client.post(path + '/imports/csv/preview', headers=headers, json=payload)
        assert preview.status_code == 200
        assert preview.json()['can_import'] is True
        assert preview.json()['row_count'] == 2
        assert preview.json()['sha256'] == hashlib.sha256(raw).hexdigest()
        assert client.get(path + '/overview', headers=headers).json()['imports'] == []
        imported = client.post(path + '/imports/csv', headers=headers, json=payload)
        assert imported.status_code == 201
        assert imported.json()['imported_count'] == 2
        overview = client.get(path + '/overview', headers=headers).json()
        assert overview['imports'][0]['sha256'] == preview.json()['sha256']
        assert overview['imports'][0]['row_count'] == 2
        assert all(line['import_batch_id'] == imported.json()['batch_id'] for line in overview['lines'])
        assert next(line for line in overview['lines'] if line['transaction_id'] == 'CSV-1')['note'] == '含,逗号'
        assert client.post(path + '/imports/csv', headers=headers, json=payload).status_code == 409
        conflict = raw.replace(b'CSV-1', b'CSV-3').replace(b'CSV-2', b'CSV-1')
        other = {**payload, 'content_base64': base64.b64encode(conflict).decode()}
        assert client.post(path + '/imports/csv', headers=headers, json=other).status_code == 409
        overview = client.get(path + '/overview', headers=headers).json()
        assert len(overview['imports']) == 1
        assert len(overview['lines']) == 2


def test_csv_rejects_invalid_rows_and_file_without_partial_write(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'bank-csv-invalid.db'))
    with TestClient(app, client=('127.0.0.1', 12000)) as client:
        base = '/api/v1'
        client.post(base + '/setup/admin', json={'username': 'admin', 'password': 'secure-pass-123'})
        token = client.post(base + '/auth/login', json={
            'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
        headers = {'Authorization': 'Bearer ' + token}
        path = base + '/finance/bank-reconciliation'
        account = client.post(path + '/accounts', headers=headers,
            json={'code': 'INVALID', 'name': '校验账户'}).json()['id']
        header = 'transaction_id,occurred_on,amount,counterparty,note\n'
        good = 'A,2026-10-03,1.00,甲,\n'
        invalid = [header + good + 'B,2026-02-30,2.00,乙,\n',
            header + good + good, 'wrong,header\n' + good,
            header + good + 'C,2026-10-03,1.001,丙,\n']
        for content in invalid:
            payload = dict(account_id=account, file_name='invalid.csv',
                content_base64=base64.b64encode(content.encode()).decode())
            assert client.post(path + '/imports/csv/preview', headers=headers, json=payload).status_code == 422
            assert client.post(path + '/imports/csv', headers=headers, json=payload).status_code == 422
        assert client.post(path + '/imports/csv', headers=headers, json={
            'account_id': account, 'file_name': '../invalid.csv',
            'content_base64': base64.b64encode((header + good).encode()).decode()}).status_code == 422
        assert client.get(path + '/overview', headers=headers).json()['lines'] == []
        assert client.get(path + '/overview', headers=headers).json()['imports'] == []


def test_v69_upgrade_preserves_manual_bank_lines(monkeypatch, tmp_path):
    path = tmp_path / 'bank-v69.db'
    monkeypatch.setenv('NEXORA_DB_PATH', str(path))
    with TestClient(app, client=('127.0.0.1', 12000)) as client:
        base = '/api/v1'
        client.post(base + '/setup/admin', json={'username': 'admin', 'password': 'secure-pass-123'})
        token = client.post(base + '/auth/login', json={
            'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
        headers = {'Authorization': 'Bearer ' + token}
        route = base + '/finance/bank-reconciliation'
        account = client.post(route + '/accounts', headers=headers,
            json={'code': 'LEGACY', 'name': '旧账户'}).json()['id']
        assert client.post(route + '/lines/import', headers=headers, json={'account_id': account,
            'lines': [{'transaction_id': 'OLD-1', 'occurred_on': '2026-10-03',
                'amount': '1.00', 'counterparty': '', 'note': ''}]}).status_code == 201
    with sqlite3.connect(path) as db:
        db.execute('DROP INDEX bank_statement_lines_import_batch')
        db.execute('ALTER TABLE bank_statement_lines DROP COLUMN import_batch_id')
        db.execute('DROP TABLE bank_import_batches')
        db.execute('PRAGMA user_version = 69')
    migrate()
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 92
        assert 'import_batch_id' in {row[1] for row in db.execute('PRAGMA table_info(bank_statement_lines)')}
        assert db.execute("SELECT transaction_id,import_batch_id FROM bank_statement_lines").fetchall() == [('OLD-1', None)]
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
