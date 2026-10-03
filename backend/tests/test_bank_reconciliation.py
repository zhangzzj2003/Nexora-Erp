"""银行流水与两类收付款的精确勾对、撤销和升级回归。"""

import os
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
                    amount='7.50', reference='历史付款', created_at='2026-10-03')
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
        assert db.execute('PRAGMA user_version').fetchone()[0] == 69
        assert db.execute("SELECT COUNT(*) FROM permissions WHERE code LIKE 'bank_reconciliation.%'").fetchone()[0] == 5
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
