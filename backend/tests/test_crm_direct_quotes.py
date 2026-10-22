"""客户直接报价保持原审批、归属和并发约束；迁移不改写历史证据。"""
import os
import re
import sqlite3

from test_crm import seeded, base_records, action, approved, B, C
from app.core.database import migrate
from test_crm_quote_attachments import attachment, PDF


def test_direct_quote_edit_approval_pdf_and_convert(seeded):
    client, admin, reviewer, seller, _, customer, _, materials = seeded
    payload = {'customer_id': customer, 'opportunity_id': None, 'reference': 'DIRECT-1',
               'valid_until': '2030-01-31', 'terms': '客户直接询价',
               'lines': [{'material_id': materials[0], 'quantity': '2', 'unit_price': '0.335'}]}
    created = client.post(C+'/quotes', headers=seller, json=payload)
    assert created.status_code == 201, created.text
    quote = created.json()
    assert quote['opportunity_id'] is None and quote['opportunity_stage'] is None
    assert quote['opportunity_version'] is None and quote['total_amount'] == '0.67'
    assert client.get(C+'/overview', headers=admin).json()['opportunities'] == []
    edited = client.put(C+f'/quotes/{quote["id"]}', headers=seller,
                        json={**payload, 'version': quote['version'], 'reason': '补充交货条款', 'terms': '确认后交货'})
    assert edited.status_code == 200, edited.text
    quote = edited.json()
    action(client, seller, quote, 'convert', status=409, acceptance_reference='客户接受')
    submitted = action(client, seller, quote, 'submit')
    quote = action(client, reviewer, submitted, 'approve')
    pdf = client.get(C+f'/quotes/{quote["id"]}/pdf', headers=seller)
    assert pdf.status_code == 200 and pdf.content.startswith(b'%PDF-')
    action(client, seller, quote, 'convert', status=422, opportunity_version=1, acceptance_reference='客户接受')
    converted = action(client, seller, quote, 'convert', acceptance_reference='客户接受', opportunity_version=None)
    assert converted['status'] == 'converted' and converted['opportunity_id'] is None
    orders = client.get(B+'/sales-orders', headers=seller).json()
    order = next(row for row in orders if row['id'] == converted['sales_order_id'])
    assert order['status'] == 'draft' and order['customer_id'] == customer and order['total_amount'] == '0.67'
    action(client, seller, quote, 'convert', status=409, acceptance_reference='重复请求')
    assert client.get(C+'/overview', headers=admin).json()['opportunities'] == []
    changes = client.get(C+f'/records/quote/{quote["id"]}/changes', headers=seller).json()
    assert [row['action'] for row in changes] == ['convert', 'approve', 'submit', 'edit', 'create']


def test_direct_quote_customer_scope_associations_and_versions(seeded):
    client, admin, _, seller, viewer, customer, other, _ = seeded
    contact, opportunity, payload = base_records(seeded)
    direct = {**payload, 'opportunity_id': None, 'customer_id': customer, 'reference': 'DIRECT-SCOPE'}
    for headers, body, expected in [
        (seller, {**direct, 'customer_id': other, 'contact_id': None}, 404),
        (viewer, direct, 403), (admin, {**direct, 'customer_id': None}, 422),
        (admin, {**direct, 'customer_id': other}, 422),
        (admin, {**payload, 'customer_id': other}, 422),
        (admin, {**direct, 'customer_id': True}, 422),
    ]:
        response = client.post(C+'/quotes', headers=headers, json=body)
        assert response.status_code == expected, response.text
    quote = client.post(C+'/quotes', headers=seller, json=direct).json()
    for changes in ({'customer_id': other}, {'opportunity_id': opportunity['id']}, {'version': 99}):
        response = client.put(C+f'/quotes/{quote["id"]}', headers=admin,
                              json={**direct, 'version': quote['version'], 'reason': '验证边界', **changes})
        assert response.status_code == 409, response.text
    # 既有商机报价仍拒绝空版本和旧版本，不能因新流程而绕过原保护。
    linked = approved(seeded, payload)
    action(client, admin, linked, 'convert', status=422, opportunity_version=None, acceptance_reference='已接受')
    action(client, admin, linked, 'convert', status=409, opportunity_version=99, acceptance_reference='已接受')
    converted = action(client, admin, linked, 'convert', opportunity_version=opportunity['version'], acceptance_reference='已接受')
    assert converted['opportunity_stage'] == 'won'


def test_v111_preserves_quote_evidence_and_constraints(seeded):
    client, admin, _, _, _, _, _, _ = seeded
    _, _, payload = base_records(seeded)
    quote = client.post(C+'/quotes', headers=admin, json=payload).json()
    uploaded = client.post(C+f'/quotes/{quote["id"]}/attachments', headers=admin, json=attachment())
    assert uploaded.status_code == 201, uploaded.text
    attachment_id = uploaded.json()['id']
    quote = action(client, admin, quote, 'submit')
    quote = action(client, seeded[2], quote, 'approve')
    path = os.environ['NEXORA_DB_PATH']
    # 将真实样例恢复为上一版非空关联表，再验证完整重建而非只修改版本号。
    with sqlite3.connect(path) as db:
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE 'crm_%' OR name LIKE 'document_approval%')")]
        before = {table: db.execute(f'SELECT * FROM {table}').fetchall() for table in tables}
        ddl = db.execute("SELECT sql FROM sqlite_master WHERE name='crm_quotes'").fetchone()[0]
        dependents = [row[0] for row in db.execute("SELECT sql FROM sqlite_master WHERE tbl_name='crm_quotes' AND type IN ('index','trigger') AND sql IS NOT NULL")]
        ddl = ddl.replace('opportunity_id INTEGER', 'opportunity_id INTEGER NOT NULL', 1)
        ddl = re.sub(r'CREATE TABLE\s+"?crm_quotes"?', 'CREATE TABLE crm_quotes_old', ddl, count=1)
        db.execute(ddl)
        db.execute('INSERT INTO crm_quotes_old SELECT * FROM crm_quotes')
        db.execute('DROP TABLE crm_quotes')
        db.execute('ALTER TABLE crm_quotes_old RENAME TO crm_quotes')
        for statement in dependents:
            db.execute(statement)
        db.execute('PRAGMA user_version=110')
    migrate()
    migrate()
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 112
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert {table: db.execute(f'SELECT * FROM {table}').fetchall() for table in tables} == before
        assert next(row for row in db.execute('PRAGMA table_info(crm_quotes)') if row[1] == 'opportunity_id')[3] == 0
        assert {row[0] for row in db.execute("SELECT sql FROM sqlite_master WHERE tbl_name='crm_quotes' AND type IN ('index','trigger') AND sql IS NOT NULL")} == set(dependents)
    assert client.get(C+f'/quotes/{quote["id"]}/attachments/{attachment_id}', headers=admin).content == PDF
    current = client.get(C+f'/records/quote/{quote["id"]}', headers=admin)
    assert current.status_code == 200 and current.json()['approval']['status'] == 'approved'
    direct = client.post(C+'/quotes', headers=admin, json={**payload, 'customer_id': quote['customer_id'], 'opportunity_id': None, 'reference': 'AFTER-MIGRATION'})
    assert direct.status_code == 201, direct.text
