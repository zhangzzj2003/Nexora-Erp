"""客户关系的来源归属、历史证据、审批职责和并发转单。"""

from approval_test_helpers import approve_document

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from io import BytesIO
import os
import sqlite3

import pytest
from pypdf import PdfReader
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core.database import migrate
from app.core.models import Base, CrmChange, CrmQuote, CrmOpportunity, Customer, SalesOrder, SalesOrderLine, Material, StockMovement, User
from app.core.orm import orm_session
from app.main import app
from app.sales import crm_rules, crm_quotes, crm_forecast, crm_quote_pdf

B = '/api/v1'
C = B + '/crm'


@pytest.fixture
def seeded(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path/'crm.db'))
    monkeypatch.setattr(crm_rules,'today',lambda:'2030-01-01')
    monkeypatch.setattr(crm_quotes,'today',lambda:'2030-01-01')
    monkeypatch.setattr(crm_forecast,'today',lambda:'2030-01-01')
    with TestClient(app,client=('127.0.0.1',12000),raise_server_exceptions=False) as client:
        assert client.post(B+'/setup/admin',json={'username':'admin','password':'secure-pass-123'}).status_code == 201
        def login(name):
            token = client.post(B+'/auth/login',json={'username':name,'password':'secure-pass-123'}).json()['token']
            return {'Authorization':'Bearer '+token}
        admin = login('admin')
        for name,role in (('reviewer','admin'),('seller','seller'),('viewer','viewer')):
            assert client.post(B+'/users',headers=admin,json={'username':name,'password':'secure-pass-123','roles':[role]}).status_code == 201
        customer = client.post(B+'/customers',headers=admin,json={'name':'客户甲'}).json()['id']
        other = client.post(B+'/customers',headers=admin,json={'name':'客户乙'}).json()['id']
        assert client.put(B+f'/customers/{customer}/owner',headers=admin,json={
            'owner_id':3,'version':1,'reason':'分配销售负责人'}).status_code == 200
        materials = [client.post(B+'/materials',headers=admin,json={'sku':f'C{i}','name':f'物料{i}','unit':'件'}).json()['id'] for i in range(2)]
        yield client,admin,login('reviewer'),login('seller'),login('viewer'),customer,other,materials


def base_records(seed):
    client,admin,_,_,_,customer,_,materials = seed
    contact_input = {'customer_id':customer,'name':'王女士','phone':'100','email':'test@example.invalid'}
    contact = client.post(C+'/contacts',headers=admin,json=contact_input)
    assert contact.status_code == 201,contact.text
    opportunity_input = {'customer_id':customer,'contact_id':contact.json()['id'],'title':'设备采购',
        'owner_id':1,'estimated_amount':'100.01','expected_close_date':'2030-01-31'}
    opportunity = client.post(C+'/opportunities',headers=admin,json=opportunity_input)
    assert opportunity.status_code == 201,opportunity.text
    data = {'opportunity_id':opportunity.json()['id'],'contact_id':contact.json()['id'],'reference':'Q-1',
        'valid_until':'2030-01-31','terms':'双方确认后另行安排交货',
        'lines':[{'material_id':mid,'quantity':'1.005','unit_price':'0.9999'} for mid in materials]}
    return contact.json(),opportunity.json(),data


def test_opportunity_probability_forecast_scope_rounding_and_audit(seeded):
    client, admin, _, seller, viewer, customer, other, _ = seeded
    _, old, _ = base_records(seeded)
    assert old['probability_percent'] is None
    assert client.get(C+'/forecast', headers=viewer).status_code == 403
    assert client.get(C+'/forecast', headers=seller).json() == {
        'currency': 'CNY', 'rated_count': 0, 'unrated_count': 1,
        'estimated_amount': '0.00', 'weighted_amount': '0.00', 'rows': []}

    payload = {'customer_id': customer, 'title': '新增预测', 'owner_id': 3,
               'estimated_amount': '100.01', 'probability_percent': 50,
               'expected_close_date': '2030-01-31'}
    for invalid in (-1, 101, True, '50', 50.5):
        assert client.post(C+'/opportunities', headers=seller,
                           json={**payload, 'probability_percent': invalid}).status_code == 422
    first = client.post(C+'/opportunities', headers=seller, json=payload)
    assert first.status_code == 201, first.text
    first = first.json()
    assert first['probability_percent'] == 50
    hidden = client.post(C+'/opportunities', headers=admin,
                         json={**payload, 'customer_id': other, 'title': '其他客户',
                               'probability_percent': 100})
    assert hidden.status_code == 201, hidden.text
    forecast = client.get(C+'/forecast', headers=seller).json()
    assert forecast['rated_count'] == 1
    assert forecast['unrated_count'] == 1
    assert forecast['estimated_amount'] == '100.01'
    assert forecast['weighted_amount'] == '50.01'
    assert forecast['rows'][0]['id'] == first['id']
    assert forecast['rows'][0]['weighted_amount'] == '50.01'
    assert forecast['rows'][0]['overdue'] is False
    assert client.get(C+'/forecast', headers=admin).json()['rated_count'] == 2

    path = C+f'/opportunities/{first["id"]}'
    edit = {key: payload[key] for key in ('customer_id', 'title', 'owner_id',
            'estimated_amount', 'expected_close_date')}
    edit.update(version=first['version'], reason='保留旧客户端评估')
    saved = client.put(path, headers=seller, json=edit)
    assert saved.status_code == 200, saved.text
    assert saved.json()['probability_percent'] == 50
    assert client.put(path, headers=seller, json={**edit, 'probability_percent': 80}).status_code == 409
    changed = client.put(path, headers=seller, json={**edit, 'version': 2,
                           'probability_percent': 0, 'reason': '客户暂缓采购'})
    assert changed.status_code == 200, changed.text
    assert changed.json()['probability_percent'] == 0
    audit = client.get(C+f'/records/opportunity/{first["id"]}/changes', headers=seller).json()
    assert audit[0]['before']['probability_percent'] == 50
    assert audit[0]['after']['probability_percent'] == 0
    assert client.get(C+'/forecast', headers=seller).json()['weighted_amount'] == '0.00'


def test_forecast_excludes_closed_opportunities_and_reopen_resets_assessment(seeded):
    client, admin, _, seller, _, customer, _, _ = seeded
    payload = {'customer_id': customer, 'title': '待核商机', 'owner_id': 3,
               'estimated_amount': '80.00', 'probability_percent': 75,
               'expected_close_date': '2030-01-31'}
    created = client.post(C+'/opportunities', headers=seller, json=payload).json()
    assert client.get(C+'/forecast', headers=seller).json()['weighted_amount'] == '60.00'
    closed = client.put(C+f'/opportunities/{created["id"]}', headers=seller,
                        json={**payload, 'stage': 'lost', 'version': 1,
                              'reason': '项目终止'})
    assert closed.status_code == 200, closed.text
    assert client.get(C+'/forecast', headers=seller).json()['rated_count'] == 0
    reopened = client.post(C+f'/opportunities/{created["id"]}/reopen', headers=seller,
                           json={'version': 2, 'reason': '客户重新启动项目'})
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()['probability_percent'] is None
    assert client.get(C+'/forecast', headers=seller).json()['unrated_count'] == 1
    audit = client.get(C+f'/records/opportunity/{created["id"]}/changes', headers=admin).json()
    assert audit[0]['before']['probability_percent'] == 75
    assert audit[0]['after']['probability_percent'] is None


def test_probability_migration_preserves_old_opportunities_as_unrated(seeded, monkeypatch):
    client, admin, _, _, _, _, _, _ = seeded
    _, opportunity, _ = base_records(seeded)
    path = os.environ['NEXORA_DB_PATH']
    with sqlite3.connect(path) as db:
        db.execute('DROP TABLE inventory_warning_events')
        db.execute('DROP TABLE inventory_warning_observations')
        db.execute('DROP TABLE material_return_reversals')
        db.execute("DELETE FROM role_permissions WHERE permission_code='material_return.reverse'")
        db.execute("DELETE FROM permissions WHERE code='material_return.reverse'")
        db.execute('DROP TABLE material_issue_reversals')
        db.execute("DELETE FROM role_permissions WHERE permission_code='material_issue.reverse'")
        db.execute("DELETE FROM permissions WHERE code='material_issue.reverse'")
        db.execute('ALTER TABLE crm_opportunities DROP COLUMN probability_percent')
        db.execute('PRAGMA user_version = 64')
    migrate()
    migrate()
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 99
        assert db.execute('SELECT probability_percent FROM crm_opportunities WHERE id = ?',
                          (opportunity['id'],)).fetchone()[0] is None
    assert client.get(C+'/forecast', headers=admin).json()['unrated_count'] == 1


def action(client,headers,record,command,reason='核对依据',status=200,**extra):
    if command in ('submit', 'approve', 'reject', 'withdraw'):
        # 真实统一接口携带审批版本，成功后读取原详情获得最新业务版本。
        path = B+f'/system/document-approvals/CrmQuote/{record["id"]}'
        response = client.post(path+'/'+command, headers=headers, json={
            'version': record.get('approval', {}).get('version', 0), 'reason': reason, **extra})
        assert response.status_code == status, response.text
        if status == 200:
            return client.get(C+f'/records/quote/{record["id"]}', headers=headers).json()
        return response.json() if status != 500 else None
    response = client.post(C+f'/quotes/{record["id"]}/{command}',headers=headers,
        json={'version':record['version'],'reason':reason,**extra})
    assert response.status_code == status,response.text
    return response.json() if status != 500 else None


def approved(seed,data):
    client,admin,reviewer,*_ = seed
    quote = client.post(C+'/quotes',headers=admin,json=data)
    assert quote.status_code == 201,quote.text
    quote = action(client,admin,quote.json(),'submit')
    return action(client,reviewer,quote,'approve')


def pdf_text(content: bytes) -> tuple[PdfReader, str]:
    reader = PdfReader(BytesIO(content))
    return reader, '\n'.join(page.extract_text() for page in reader.pages)


def test_approved_quote_pdf_uses_frozen_snapshot_and_no_write(seeded):
    client, admin, reviewer, seller, viewer, customer, other, materials = seeded
    _, opportunity, payload = base_records(seeded)
    draft = client.post(C+'/quotes', headers=admin, json=payload).json()
    path = C+f'/quotes/{draft["id"]}/pdf'
    assert client.get(path, headers=admin).status_code == 409
    assert client.get(path, headers=viewer).status_code == 403
    submitted = action(client, admin, draft, 'submit')
    assert client.get(path, headers=admin).status_code == 409
    quote = action(client, reviewer, submitted, 'approve')
    changes_before = client.get(C+f'/records/quote/{quote["id"]}/changes', headers=admin).json()
    with orm_session(write=True) as db:
        db.get(Customer, customer).name = '客户更名后'
        db.get(Material, materials[0]).name = '物料更名后'
    response = client.get(path, headers=seller)
    assert response.status_code == 200, response.text
    assert response.headers['content-type'].startswith('application/pdf')
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['content-disposition'] == f'attachment; filename="quote-{quote["id"]}.pdf"'
    assert response.content.startswith(b'%PDF-')
    reader, text = pdf_text(response.content)
    assert len(reader.pages) == 1
    for value in ('固定报价', 'Q-1', '客户甲', '王女士', '物料0', '人民币', '2.00', payload['terms']):
        assert value in text
    assert '客户更名后' not in text and '物料更名后' not in text
    assert client.get(C+f'/records/quote/{quote["id"]}/changes', headers=admin).json() == changes_before
    assert client.get(C+'/quotes/999999/pdf', headers=admin).status_code == 404

    other_contact = client.post(C+'/contacts', headers=admin,
                                json={'customer_id': other, 'name': '乙方联系人'}).json()
    other_opportunity = client.post(C+'/opportunities', headers=admin, json={
        'customer_id': other, 'title': '乙方项目', 'owner_id': 1,
        'estimated_amount': '2', 'expected_close_date': '2030-01-31'}).json()
    other_quote = approved(seeded, {**payload, 'opportunity_id': other_opportunity['id'],
                                    'contact_id': other_contact['id'], 'reference': 'Q-other'})
    assert client.get(C+f'/quotes/{other_quote["id"]}/pdf', headers=seller).status_code == 404


def test_quote_pdf_labels_historical_copy_and_rejects_cancelled(seeded, monkeypatch):
    client, admin, _, seller, _, _, _, _ = seeded
    _, opportunity, payload = base_records(seeded)
    quote = approved(seeded, payload)
    monkeypatch.setattr(crm_quote_pdf, 'today', lambda: '2030-02-01')
    response = client.get(C+f'/quotes/{quote["id"]}/pdf', headers=admin)
    assert response.status_code == 200
    assert '有效期已过' in pdf_text(response.content)[1]
    separate = client.post(C+'/quotes', headers=admin,
                           json={**payload, 'reference': 'Q-cancel'}).json()
    separate = action(client, admin, separate, 'submit')
    separate = action(client, seeded[2], separate, 'approve')
    separate = action(client, admin, separate, 'withdraw')
    separate = action(client, admin, separate, 'cancel')
    assert client.get(C+f'/quotes/{separate["id"]}/pdf', headers=admin).status_code == 409
    converted = action(client, seller, quote, 'convert', acceptance_reference='客户接受依据',
                       opportunity_version=opportunity['version'])
    order=next(item for item in client.get('/api/v1/sales-orders',headers=seller).json()
        if item['id']==converted['sales_order_id'])
    assert all(line['warranty_days'] is None and line['warranty_basis']=='' for line in order['lines'])
    assert '已转销售订单' in pdf_text(client.get(C+f'/quotes/{converted["id"]}/pdf',
                                       headers=admin).content)[1]


def test_quote_pdf_paginates_many_lines_and_escapes_terms(seeded):
    client, admin, _, _, _, _, _, _ = seeded
    _, _, payload = base_records(seeded)
    quote = approved(seeded, payload)
    with orm_session() as db:
        snapshot = crm_rules.raw_data(db, 'quote', db.get(CrmQuote, quote['id']))
    snapshot['terms'] = '<script>客户条款</script>\n' + '长期交货安排。'*80
    snapshot['lines'] = [{**snapshot['lines'][0], 'position': index,
                          'material_name': '超长物料名称'*12} for index in range(1, 101)]
    content = crm_quote_pdf.quote_pdf(snapshot, '2030-01-01')
    reader, text = pdf_text(content)
    assert len(reader.pages) > 1
    assert all('物料编码' in page.extract_text() for page in reader.pages[:-1])
    assert '<script>客户条款</script>' in text


def test_customer_duplicate_candidates_respect_owner_scope_and_do_not_write(seeded):
    client, admin, _, seller, viewer, customer, other, _ = seeded
    same = client.post(B+'/customers/duplicate-candidates', headers=seller,
                       json={'name': '客 户-甲'})
    assert same.status_code == 200
    assert same.json() == [{'id': customer, 'name': '客户甲', 'match': 'same_name'}]
    assert client.post(B+'/customers/duplicate-candidates', headers=seller,
                       json={'name': '客户乙'}).json() == []
    assert client.post(B+'/customers/duplicate-candidates', headers=admin,
                       json={'name': '客户乙'}).json() == [
                           {'id': other, 'name': '客户乙', 'match': 'same_name'}]
    extended = client.post(B+'/customers', headers=seller,
                           json={'name': '上海华星有限公司'})
    assert extended.status_code == 201
    assert client.post(B+'/customers/duplicate-candidates', headers=seller,
                       json={'name': '上海华星'}).json() == [
                           {'id': extended.json()['id'], 'name': '上海华星有限公司',
                            'match': 'similar_name'}]
    assert client.post(B+'/customers/duplicate-candidates', headers=viewer,
                       json={'name': '客户甲'}).status_code == 403
    for invalid in ({'name': '   '}, {'name': '客户甲', 'owner_id': 3}):
        assert client.post(B+'/customers/duplicate-candidates', headers=seller,
                           json=invalid).status_code == 422
    assert {row['id'] for row in client.get(B+'/customers', headers=admin).json()} == {
        customer, other, extended.json()['id']}


def test_customer_import_previews_scope_and_writes_atomic_owner_audit(seeded):
    client, admin, _, seller, viewer, customer, other, _ = seeded
    preview = client.post(B+'/customers/import-preview', headers=seller,
                          json={'names': ['客户乙', '客 户-甲', '上海华星', '上海华星有限公司']})
    assert preview.status_code == 200
    rows = preview.json()['rows']
    assert rows[0]['candidates'] == []  # 其他负责人客户不可见。
    assert rows[1]['candidates'] == [{'id': customer, 'name': '客户甲',
                                     'match': 'same_name'}]
    assert rows[3]['batch_candidates'] == [3]
    assert preview.json()['can_import'] is False
    assert preview.json()['requires_confirmation'] is True
    assert client.post(B+'/customers/import-preview', headers=viewer,
                       json={'names': ['新客户']}).status_code == 403

    names = ['批量客户甲', '批量客户乙']
    result = client.post(B+'/customers/import', headers=seller,
                         json={'names': names, 'reason': '经客户资料核对'})
    assert result.status_code == 201, result.text
    data = result.json()
    assert len(data['batch_reference']) == 16
    assert [row['name'] for row in data['created']] == names
    assert all(row['owner_id'] == 3 for row in data['created'])
    for index, row in enumerate(data['created'], start=1):
        changes = client.get(B+f'/customers/{row["id"]}/owner-changes', headers=admin).json()
        assert len(changes) == 1
        assert f'{data["batch_reference"]} 第{index}条：经客户资料核对' in changes[0]['reason']
    assert client.post(B+'/customers/import', headers=seller,
                       json={'names': names, 'reason': '重复执行'}).status_code == 409
    assert {row['name'] for row in client.get(B+'/customers', headers=seller).json()
            if row['name'].startswith('批量客户')} == set(names)

    # 隐藏的同名客户依赖数据库唯一约束，且整个导入批次必须回滚。
    conflict = client.post(B+'/customers/import', headers=seller,
                           json={'names': ['回滚客户', '客户乙'], 'reason': '原资料导入'})
    assert conflict.status_code == 409
    variant = client.post(B+'/customers/import', headers=seller,
                          json={'names': ['回滚客户', '客 户-乙'], 'reason': '原资料导入'})
    assert variant.status_code == 409
    assert all(row['name'] != '回滚客户' for row in client.get(B+'/customers', headers=admin).json())


def test_customer_import_rechecks_similar_names_and_rejects_invalid_batches(seeded):
    client, admin, _, seller, _, _, _, _ = seeded
    created = client.post(B+'/customers', headers=seller,
                          json={'name': '上海华星有限公司'})
    assert created.status_code == 201
    payload = {'names': ['新增客户', '上海华星'], 'reason': '销售资料导入'}
    preview = client.post(B+'/customers/import-preview', headers=seller,
                          json={'names': payload['names']}).json()
    assert preview['can_import'] is True
    assert preview['requires_confirmation'] is True
    assert client.post(B+'/customers/import', headers=seller, json=payload).status_code == 409
    assert all(row['name'] != '新增客户' for row in client.get(B+'/customers', headers=admin).json())
    accepted = client.post(B+'/customers/import', headers=seller,
                           json={**payload, 'allow_similar': True})
    assert accepted.status_code == 201, accepted.text
    for invalid in ({'names': []}, {'names': ['客户A', '客 户-A']},
                    {'names': ['\n']}, {'names': ['合格'], 'extra': 1},
                    {'names': ['合格'], 'reason': '依据', 'allow_similar': 'true'}):
        endpoint = '/import' if 'reason' in invalid else '/import-preview'
        assert client.post(B+'/customers'+endpoint, headers=seller,
                           json=invalid).status_code == 422


def test_contact_import_rechecks_scope_and_audits_atomic_batch(seeded):
    client, admin, _, seller, viewer, customer, other, _ = seeded
    rows = [{'customer_id': customer, 'name': '李女士', 'phone': '100'},
            {'customer_id': customer, 'name': '张先生', 'email': 'zhang@example.invalid'}]
    assert client.post(C+'/contacts/import-preview', headers=viewer,
                       json={'rows': rows}).status_code == 403
    preview = client.post(C+'/contacts/import-preview', headers=seller,
                          json={'rows': rows})
    assert preview.status_code == 200, preview.text
    assert [row['customer_name'] for row in preview.json()['rows']] == ['客户甲', '客户甲']
    assert not preview.json()['requires_confirmation']
    result = client.post(C+'/contacts/import', headers=seller,
                         json={'rows': rows, 'reason': '核对原始客户名单'})
    assert result.status_code == 201, result.text
    data = result.json()
    assert len(data['batch_reference']) == 16
    assert [row['name'] for row in data['created']] == ['李女士', '张先生']
    for index, row in enumerate(data['created'], start=1):
        changes = client.get(C+f'/records/contact/{row["id"]}/changes', headers=seller).json()
        assert len(changes) == 1
        assert changes[0]['action'] == 'create'
        assert changes[0]['after']['customer_id'] == customer
        assert f'{data["batch_reference"]} 第{index}条：核对原始客户名单' in changes[0]['reason']
    assert {row['name'] for row in client.get(C+'/overview', headers=seller).json()['contacts']} == {
        '李女士', '张先生'}
    hidden = rows + [{'customer_id': other, 'name': '隐藏客户联系人'}]
    for endpoint, body in (('/import-preview', {'rows': hidden}),
                           ('/import', {'rows': hidden, 'reason': '越权'})):
        response = client.post(C+'/contacts'+endpoint, headers=seller, json=body)
        assert response.status_code == 404
        assert '客户乙' not in response.text
    assert all(row['name'] != '隐藏客户联系人' for row in
               client.get(C+'/overview', headers=admin).json()['contacts'])


def test_contact_import_duplicate_confirmation_and_invalid_rows(seeded):
    client, admin, _, seller, _, customer, _, _ = seeded
    existing = client.post(C+'/contacts', headers=seller,
                           json={'customer_id': customer, 'name': '王女士'})
    assert existing.status_code == 201
    rows = [{'customer_id': customer, 'name': '新联系人'},
            {'customer_id': customer, 'name': '王 女士'},
            {'customer_id': customer, 'name': '新-联系人'}]
    preview = client.post(C+'/contacts/import-preview', headers=seller,
                          json={'rows': rows}).json()
    assert preview['requires_confirmation']
    assert preview['rows'][1]['existing_contact_ids'] == [existing.json()['id']]
    assert preview['rows'][2]['batch_rows'] == [1]
    rejected = client.post(C+'/contacts/import', headers=seller,
                           json={'rows': rows, 'reason': '整理旧表'})
    assert rejected.status_code == 409
    assert [row['name'] for row in client.get(C+'/overview', headers=admin).json()['contacts']] == ['王女士']
    accepted = client.post(C+'/contacts/import', headers=seller,
                           json={'rows': rows, 'reason': '两名同名人员已核对',
                                 'allow_similar': True})
    assert accepted.status_code == 201, accepted.text
    repeated = client.post(C+'/contacts/import', headers=seller,
                           json={'rows': rows, 'reason': '网络超时后重试',
                                 'allow_similar': True})
    assert repeated.status_code == 409
    assert len(client.get(C+'/overview', headers=admin).json()['contacts']) == 4
    for body in ({'rows': []}, {'rows': [{'customer_id': customer, 'name': '  '}]},
                 {'rows': [{'customer_id': customer, 'name': '甲', 'extra': 1}]},
                 {'rows': [{'customer_id': customer, 'name': '甲\n乙'}]}):
        assert client.post(C+'/contacts/import-preview', headers=seller,
                           json=body).status_code == 422
    assert client.post(C+'/contacts/import', headers=seller,
                       json={'rows': [{'customer_id': customer, 'name': '甲'}],
                             'reason': '依据', 'allow_similar': 'true'}).status_code == 422


def test_opportunity_import_is_atomic_scoped_and_audited(seeded):
    client, admin, _, seller, viewer, customer, other, _ = seeded
    contact = client.post(C+'/contacts', headers=seller,
                          json={'customer_id': customer, 'name': '王女士'}).json()
    rows = [{'customer_id': customer, 'title': '项目甲', 'owner_id': 3,
             'estimated_amount': '100.25', 'expected_close_date': '2030-02-01',
             'contact_id': contact['id']},
            {'customer_id': customer, 'title': '项目乙', 'owner_id': 3,
             'estimated_amount': '0.00', 'expected_close_date': '2030-03-01'}]
    assert client.post(C+'/opportunities/import-preview', headers=viewer,
                       json={'rows': rows}).status_code == 403
    checked = client.post(C+'/opportunities/import-preview', headers=seller,
                          json={'rows': rows})
    assert checked.status_code == 200, checked.text
    assert checked.json()['rows'][0]['contact_name'] == '王女士'
    assert checked.json()['rows'][0]['customer_name'] == '客户甲'
    assert not checked.json()['requires_confirmation']
    hidden = rows + [{**rows[0], 'customer_id': other, 'title': '隐藏客户项目', 'contact_id': None}]
    for endpoint, body in (('/import-preview', {'rows': hidden}),
                           ('/import', {'rows': hidden, 'reason': '原清单'})):
        response = client.post(C+'/opportunities'+endpoint, headers=seller, json=body)
        assert response.status_code == 404
        assert '客户乙' not in response.text
    assert client.get(C+'/overview', headers=admin).json()['opportunities'] == []
    result = client.post(C+'/opportunities/import', headers=seller,
                         json={'rows': rows, 'reason': '经客户预算核对'})
    assert result.status_code == 201, result.text
    data = result.json()
    assert len(data['batch_reference']) == 16
    assert [row['title'] for row in data['created']] == ['项目甲', '项目乙']
    for index, item in enumerate(data['created'], start=1):
        record = client.get(C+f'/records/opportunity/{item["id"]}', headers=seller).json()
        changes = client.get(C+f'/records/opportunity/{item["id"]}/changes', headers=seller).json()
        assert record['stage'] == 'prospect' and record['version'] == 1
        assert record['estimated_amount'] == rows[index - 1]['estimated_amount']
        assert changes[0]['action'] == 'create'
        assert f'{data["batch_reference"]} 第{index}条：经客户预算核对' in changes[0]['reason']
    assert client.post(C+'/opportunities/import', headers=seller,
                       json={'rows': rows, 'reason': '网络超时重试', 'allow_similar': True}).status_code == 409


def test_opportunity_import_rechecks_duplicates_and_links(seeded):
    client, admin, _, seller, _, customer, other, _ = seeded
    rows = [{'customer_id': customer, 'title': '同名项目', 'owner_id': 3,
             'estimated_amount': '10.00', 'expected_close_date': '2030-02-01'},
            {'customer_id': customer, 'title': '同名-项目', 'owner_id': 3,
             'estimated_amount': '20.00', 'expected_close_date': '2030-03-01'}]
    preview = client.post(C+'/opportunities/import-preview', headers=seller,
                          json={'rows': rows}).json()
    assert preview['rows'][1]['batch_rows'] == [1]
    assert client.post(C+'/opportunities/import', headers=seller,
                       json={'rows': rows, 'reason': '原名单'}).status_code == 409
    assert client.get(C+'/overview', headers=admin).json()['opportunities'] == []
    accepted = client.post(C+'/opportunities/import', headers=seller,
                           json={'rows': rows, 'reason': '确认是两次独立需求',
                                 'allow_similar': True})
    assert accepted.status_code == 201, accepted.text
    again = [{**rows[0], 'title': '同 名项目'}]
    duplicate = client.post(C+'/opportunities/import-preview', headers=seller,
                            json={'rows': again}).json()
    assert duplicate['rows'][0]['existing_opportunity_ids'] == [accepted.json()['created'][0]['id'],
                                                                accepted.json()['created'][1]['id']]
    for invalid in ({'rows': [{**rows[0], 'owner_id': 99999}]},
                    {'rows': [{**rows[0], 'contact_id': 99999}]},
                    {'rows': [{**rows[0], 'customer_id': other}]}):
        status = 404 if invalid['rows'][0].get('customer_id') == other else 422
        assert client.post(C+'/opportunities/import-preview', headers=seller,
                           json=invalid).status_code == status
    for invalid in ({'rows': []}, {'rows': [{**rows[0], 'estimated_amount': '1.001'}]},
                    {'rows': [{**rows[0], 'expected_close_date': '2030-02-30'}]},
                    {'rows': [{**rows[0], 'stage': 'won'}]}):
        assert client.post(C+'/opportunities/import-preview', headers=seller,
                           json=invalid).status_code == 422


def test_customer_owner_scope_audit_and_transfer_revoke_access(seeded):
    client,admin,reviewer,seller,_,customer,other,materials = seeded
    assert client.post(B+'/customers',headers=seller,json={
        'name':'不可伪造归属','owner_id':1}).status_code == 422
    own_contact = client.post(C+'/contacts',headers=admin,
        json={'customer_id':customer,'name':'销售员客户联系人'}).json()
    other_contact = client.post(C+'/contacts',headers=admin,
        json={'customer_id':other,'name':'其他客户联系人'}).json()
    other_opportunity=client.post(C+'/opportunities',headers=admin,json={
        'customer_id':other,'contact_id':other_contact['id'],'title':'其他客户商机',
        'owner_id':1,'estimated_amount':'2','expected_close_date':'2030-01-31'}).json()
    other_quote_input={'opportunity_id':other_opportunity['id'],'contact_id':other_contact['id'],
        'reference':'Q-OTHER','valid_until':'2030-01-31',
        'lines':[{'material_id':materials[0],'quantity':'1','unit_price':'2'}]}
    other_quote=client.post(C+'/quotes',headers=admin,json=other_quote_input).json()
    assert {row['id'] for row in client.get(C+'/options',headers=seller).json()['customers']} == {customer}
    assert {row['id'] for row in client.get(B+'/customers',headers=seller).json()} == {customer}
    assert {row['id'] for row in client.get(C+'/options',headers=reviewer).json()['customers']} == {customer,other}
    assert [row['id'] for row in client.get(C+'/overview',headers=seller).json()['contacts']] == [own_contact['id']]
    assert client.get(C+'/overview',headers=seller).json()['opportunities'] == []
    assert client.get(C+'/overview',headers=seller).json()['quotes'] == []
    for path in (f'/records/contact/{other_contact["id"]}',
                 f'/records/contact/{other_contact["id"]}/changes'):
        assert client.get(C+path,headers=seller).status_code == 404
    assert client.get(C+f'/records/quote/{other_quote["id"]}',headers=seller).status_code == 404
    assert client.get(C+f'/records/quote/{other_quote["id"]}/changes',headers=seller).status_code == 404
    assert client.post(C+'/quotes',headers=seller,json=other_quote_input).status_code == 404
    assert client.post(C+f'/quotes/{other_quote["id"]}/submit',headers=seller,
        json={'version':1,'reason':'越权提交'}).status_code == 404
    assert client.put(C+f'/contacts/{other_contact["id"]}',headers=seller,json={
        'customer_id':other,'name':'越权修订','version':1,'reason':'尝试'}).status_code == 404
    assert client.post(C+'/contacts',headers=seller,
        json={'customer_id':other,'name':'越权新增'}).status_code == 404
    order_input={'customer_id':other,'reference':'隔离验证',
        'lines':[{'material_id':materials[0],'quantity':'1','unit_price':'2'}]}
    order=client.post(B+'/sales-orders',headers=admin,json=order_input).json()
    assert client.post(B+'/sales-orders',headers=seller,json=order_input).status_code == 404
    assert all(row['id'] != order['id'] for row in client.get(B+'/sales-orders',headers=seller).json())
    assert client.post(B+f'/sales-orders/{order["id"]}/confirm',headers=seller).status_code == 404
    approve_document(client, admin, 'SalesOrder', order['id'])
    assert client.post(B+f'/sales-orders/{order["id"]}/confirm',headers=admin).status_code == 200
    supplier=client.post(B+'/suppliers',headers=admin,json={'name':'隔离测试供货方'}).json()['id']
    receipt=client.post(B+'/receipts',headers=admin,json={'supplier_id':supplier,
        'lines':[{'material_id':materials[0],'quantity':'2'}]}).json()
    # 先完成真实独立审批，保留原业务失败和并发断言。
    approve_document(client, admin, 'Receipt', receipt['id'])
    assert client.post(B+f'/receipts/{receipt["id"]}/post',headers=admin).status_code == 200
    shipment_input={'sales_order_id':order['id'],'warehouse_id':1,
        'lines':[{'material_id':materials[0],'quantity':'1'}]}
    shipment=client.post(B+'/shipments',headers=admin,json=shipment_input).json()
    assert client.post(B+'/shipments',headers=seller,json=shipment_input).status_code == 404
    assert all(row['id'] != shipment['id'] for row in client.get(B+'/shipments',headers=seller).json())
    assert client.post(B+f'/shipments/{shipment["id"]}/cancel',headers=seller).status_code == 404
    approve_document(client, admin, 'Shipment', shipment['id'])
    assert client.post(B+f'/shipments/{shipment["id"]}/post',headers=admin).status_code == 200
    return_input={'shipment_id':shipment['id'],'warehouse_id':1,'reason':'客户退货',
        'lines':[{'shipment_line_id':shipment['lines'][0]['id'],'quantity':'1'}]}
    sales_return=client.post(B+'/sales-returns',headers=admin,json=return_input).json()
    assert client.post(B+'/sales-returns',headers=seller,json=return_input).status_code == 404
    assert all(row['id'] != sales_return['id'] for row in client.get(B+'/sales-returns',headers=seller).json())
    assert client.post(B+f'/sales-returns/{sales_return["id"]}/cancel',headers=seller).status_code == 404
    case_input={'shipment_line_id':shipment['lines'][0]['id'],'reference':'AF-OTHER',
        'kind':'repair','quantity':'1','complaint':'客户报告异常','solution':'核查后维修',
        'charge_mode':'free','fee_amount':'0','customer_acceptance':'已取得客户书面同意',
        'warehouse_id':None,'parts':[],'reason':'客户申请'}
    case=client.post(B+'/after-sales/cases',headers=admin,json=case_input).json()
    assert client.post(B+'/after-sales/cases',headers=seller,json=case_input).status_code == 404
    assert client.get(B+'/after-sales',headers=seller).json()['sources'] == []
    assert client.get(B+'/after-sales',headers=seller).json()['cases'] == []
    assert client.get(B+f'/after-sales/cases/{case["id"]}',headers=seller).status_code == 404
    assert client.put(B+f'/customers/{customer}/owner',headers=seller,json={
        'owner_id':1,'version':2,'reason':'越权'}).status_code == 403
    assert client.put(B+f'/customers/{customer}/owner',headers=admin,json={
        'owner_id':1,'version':1,'reason':'过期版本'}).status_code == 409
    assert client.put(B+f'/customers/{customer}/owner',headers=admin,json={
        'owner_id':999,'version':2,'reason':'账号不存在'}).status_code == 422
    transferred=client.put(B+f'/customers/{customer}/owner',headers=admin,json={
        'owner_id':1,'version':2,'reason':'客户正式移交'}).json()
    assert transferred['owner_id'] == 1 and transferred['version'] == 3
    assert client.get(C+f'/records/contact/{own_contact["id"]}',headers=seller).status_code == 404
    assert client.get(C+'/overview',headers=seller).json()['contacts'] == []
    changes=client.get(B+f'/customers/{customer}/owner-changes',headers=admin).json()
    assert [(row['before_owner_id'],row['after_owner_id'],row['reason']) for row in changes] == [
        (3,1,'客户正式移交'),(1,3,'分配销售负责人'),(None,1,'建立客户')]


def test_v60_owner_upgrade_keeps_existing_customers_unassigned(seeded, remove_equipment_hour_schema):
    client,admin,_,seller,_,customer,other,_ = seeded
    with sqlite3.connect(os.environ['NEXORA_DB_PATH']) as db:
        names=db.execute('SELECT id,name FROM customers ORDER BY id').fetchall()
        remove_equipment_hour_schema(db)
        db.execute('DROP TABLE customer_owner_changes')
        db.execute('DROP INDEX customer_owner_lookup')
        db.execute('ALTER TABLE customers DROP COLUMN owner_id')
        db.execute('ALTER TABLE customers DROP COLUMN version')
        for code in ('customer.assign','customer.view_all'):
            db.execute('DELETE FROM role_permissions WHERE permission_code=?',(code,))
            db.execute('DELETE FROM permissions WHERE code=?',(code,))
        db.execute('PRAGMA user_version=60')
    migrate();migrate()
    with sqlite3.connect(os.environ['NEXORA_DB_PATH']) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 99
        assert db.execute('SELECT id,name FROM customers ORDER BY id').fetchall() == names
        assert db.execute('SELECT COUNT(*) FROM customers WHERE owner_id IS NULL').fetchone()[0] == 2
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    assert client.get(C+'/options',headers=seller).json()['customers'] == []
    assert {row['id'] for row in client.get(C+'/options',headers=admin).json()['customers']} == {customer,other}


def test_complete_crm_workflow_keeps_snapshot_and_does_not_post_stock(seeded):
    client,admin,reviewer,seller,viewer,customer,other,materials = seeded
    contact,opportunity,data = base_records(seeded)
    assert client.get(C+'/overview',headers=viewer).status_code == 403
    assert client.get(C+'/options',headers=seller).status_code == 200
    quote = approved(seeded,data)
    assert quote['total_amount'] == '2.00'
    with orm_session(write=True) as db:
        db.get(Material,materials[0]).name = '后续更名'
    edited = client.put(C+f'/contacts/{contact["id"]}',headers=admin,json={
        'customer_id':customer,'name':'新联系人名称','phone':'200','version':1,'reason':'更正资料'})
    assert edited.status_code == 200,edited.text
    frozen = client.get(C+f'/records/quote/{quote["id"]}',headers=admin).json()
    assert frozen['party']['phone'] == '100'
    assert frozen['contact_name'] == '王女士'
    assert frozen['lines'][0]['material_name'] == '物料0'
    converted = action(client,seller,quote,'convert',acceptance_reference='客户确认邮件编号 1',opportunity_version=opportunity['version'])
    assert converted['status'] == 'converted'
    order = next(row for row in client.get(B+'/sales-orders',headers=admin).json() if row['id'] == converted['sales_order_id'])
    assert order['status'] == 'draft' and order['total_amount'] == quote['total_amount']
    assert [row['quantity'] for row in order['lines']] == ['1.005','1.005']
    with orm_session() as db:
        assert list(db.scalars(select(StockMovement))) == []
    history = client.get(C+f'/records/quote/{quote["id"]}/changes',headers=admin).json()
    assert [row['action'] for row in history] == ['convert','approve','submit','create']
    assert history[0]['before']['sales_order_id'] is None
    assert history[0]['after']['sales_order_id'] == order['id']
    assert history[0]['changed_by_name'] == 'seller'
    # 已转单并不等于收款或出库，仍必须经过既有订单流程。
    approve_document(client, admin, 'SalesOrder', order['id'])
    assert client.post(B+f'/sales-orders/{order["id"]}/confirm',headers=admin).status_code == 200


def test_review_permissions_apply_after_edit_and_resubmission(seeded):
    client,admin,reviewer,seller,*_ = seeded
    _,_,data = base_records(seeded)
    quote = client.post(C+'/quotes',headers=seller,json=data).json()
    quote = action(client,admin,quote,'submit')
    assert client.get(B+f'/system/document-approvals/CrmQuote/{quote["id"]}',headers=admin).json()['can_review']
    action(client,seller,quote,'approve',status=403)
    quote = action(client,reviewer,quote,'reject',reason='价格须更正')
    quote = client.put(C+f'/quotes/{quote["id"]}',headers=admin,json={**data,
        'version':quote['version'],'reason':'修订价格','lines':[{'material_id':data['lines'][0]['material_id'],'quantity':'2','unit_price':'3'}]}).json()
    assert quote['status'] == 'draft' and quote['total_amount'] == '6.00'
    quote = action(client,seller,quote,'submit')
    assert client.get(B+f'/system/document-approvals/CrmQuote/{quote["id"]}',headers=admin).json()['can_review']
    quote = action(client,reviewer,quote,'approve')
    assert set(quote['review_blocked']) == {1,3}
    audits = client.get(C+f'/records/quote/{quote["id"]}/changes',headers=admin).json()
    edit = next(row for row in audits if row['action'] == 'edit')
    assert edit['before']['total_amount'] == '2.00'
    assert edit['after']['total_amount'] == '6.00'


def test_invalid_links_inactive_contacts_and_disabled_owner_are_rejected(seeded):
    client,admin,_,_,_,customer,other,_ = seeded
    contact,opportunity,data = base_records(seeded)
    assert client.post(C+'/opportunities',headers=admin,json={'customer_id':other,'contact_id':contact['id'],
        'title':'错误归属','owner_id':1,'estimated_amount':'1','expected_close_date':'2030-01-31'}).status_code == 422
    assert client.post(C+'/activities',headers=admin,json={'customer_id':other,'opportunity_id':opportunity['id'],
        'subject':'错误归属','owner_id':1,'due_date':'2030-01-01'}).status_code == 422
    assert client.put(C+f'/contacts/{contact["id"]}',headers=admin,json={'customer_id':other,'name':'转客户',
        'version':1,'reason':'转移'}).status_code == 409
    client.put(C+f'/contacts/{contact["id"]}',headers=admin,json={'customer_id':customer,'name':'王女士',
        'is_active':False,'version':1,'reason':'离职'})
    assert client.post(C+'/quotes',headers=admin,json=data).status_code == 422
    with orm_session(write=True) as db:
        db.get(User,3).is_active = 0
    assert client.post(C+'/activities',headers=admin,json={'customer_id':customer,
        'subject':'负责人停用','owner_id':3,'due_date':'2030-01-01'}).status_code == 422


def test_activity_overdue_and_immutable_closure(seeded):
    client,admin,_,seller,_,customer,*_ = seeded
    response = client.post(C+'/activities',headers=seller,json={'customer_id':customer,'subject':'回访客户',
        'owner_id':3,'due_date':'2029-12-31','note':'电话跟进'})
    assert response.status_code == 201,response.text
    activity = response.json()
    assert activity['overdue']
    path = C+f'/activities/{activity["id"]}'
    completed = client.post(path+'/complete',headers=seller,json={'version':1,'reason':'已确认技术规格'}).json()
    assert completed['status'] == 'completed' and not completed['overdue'] and completed['closed_by'] == 3
    assert client.post(path+'/cancel',headers=admin,json={'version':2,'reason':'重写历史'}).status_code == 409
    assert client.post(path+'/complete',headers=admin,json={'version':1,'reason':'过期版本'}).status_code == 409
    changes = client.get(C+f'/records/activity/{activity["id"]}/changes',headers=admin).json()
    assert len(changes) == 2 and changes[0]['before']['result'] == ''


def test_quotes_require_approval_acceptance_both_permissions_and_current_versions(seeded):
    client,admin,reviewer,seller,viewer,*_ = seeded
    _,opportunity,data = base_records(seeded)
    quote = client.post(C+'/quotes',headers=admin,json=data).json()
    action(client,seller,quote,'convert',status=409,acceptance_reference='接受依据',opportunity_version=1)
    quote = action(client,admin,quote,'submit')
    action(client,seller,quote,'convert',status=409,acceptance_reference='接受依据',opportunity_version=1)
    quote = action(client,reviewer,quote,'approve')
    action(client,seller,quote,'convert',status=422,acceptance_reference=' ',opportunity_version=1)
    action(client,seller,quote,'convert',status=409,acceptance_reference='接受依据',opportunity_version=2)
    assert client.put(C+f'/quotes/{quote["id"]}',headers=admin,json={**data,'version':quote['version'],'reason':'改已批报价'}).status_code == 409
    client.post(B+'/roles',headers=admin,json={'code':'crm_only','label':'仅能转报价','permissions':['crm.view','crm_quote.convert']})
    client.post(B+'/users',headers=admin,json={'username':'convert_only','password':'secure-pass-123','roles':['crm_only']})
    token = client.post(B+'/auth/login',json={'username':'convert_only','password':'secure-pass-123'}).json()['token']
    action(client,{'Authorization':'Bearer '+token},quote,'convert',status=403,acceptance_reference='接受依据',opportunity_version=1)
    action(client,viewer,quote,'convert',status=403,acceptance_reference='接受依据',opportunity_version=1)
    with orm_session() as db:
        assert list(db.scalars(select(SalesOrder))) == []


def test_expiration_uses_server_day_at_submit_review_and_conversion(seeded,monkeypatch):
    client,admin,reviewer,seller,*_ = seeded
    _,_,data = base_records(seeded)
    quote = approved(seeded,data)
    monkeypatch.setattr(crm_quotes,'today',lambda:'2030-02-01')
    action(client,seller,quote,'convert',status=409,acceptance_reference='已接受',opportunity_version=1)
    assert client.post(C+'/quotes',headers=admin,json={**data,'reference':'Q-expired'}).status_code == 422
    monkeypatch.setattr(crm_quotes,'today',lambda:'2030-01-01')
    draft = client.post(C+'/quotes',headers=admin,json={**data,'reference':'Q-draft'}).json()
    pending = action(client,admin,draft,'submit')
    monkeypatch.setattr(crm_quotes,'today',lambda:'2030-02-01')
    action(client,reviewer,pending,'approve',status=409)
    action(client,reviewer,pending,'reject')


def test_cancelled_order_does_not_reuse_quote_and_reopen_is_audited(seeded):
    client,admin,_,seller,*_ = seeded
    _,opp,data = base_records(seeded)
    quote = approved(seeded,data)
    converted = action(client,seller,quote,'convert',acceptance_reference='第一次接受',opportunity_version=1)
    path = C+f'/opportunities/{opp["id"]}/reopen'
    assert client.post(path,headers=admin,json={'version':2,'reason':'订单仍有效'}).status_code == 409
    action(client,admin,converted,'cancel',status=409)
    client.post(B+f'/sales-orders/{converted["sales_order_id"]}/cancel',headers=admin)
    assert client.post(path,headers=seller,json={'version':2,'reason':'原订单取消，重谈'}).status_code == 200
    action(client,seller,converted,'convert',status=409,acceptance_reference='再次接受',opportunity_version=3)
    second = approved(seeded,{**data,'reference':'Q-2'})
    action(client,seller,second,'convert',acceptance_reference='第二次接受',opportunity_version=3)
    audits = client.get(C+f'/records/opportunity/{opp["id"]}/changes',headers=admin).json()
    assert [row['action'] for row in audits] == ['convert','reopen','convert','create']


def test_concurrent_conversion_of_two_quotes_cannot_duplicate_opportunity_order(seeded):
    client,admin,_,seller,*_ = seeded
    _,opp,data = base_records(seeded)
    first = approved(seeded,data)
    second = approved(seeded,{**data,'reference':'Q-2'})
    def run(quote):
        return client.post(C+f'/quotes/{quote["id"]}/convert',headers=seller,json={
            'version':quote['version'],'opportunity_version':1,'acceptance_reference':'确认','reason':'转单'}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run,(first,second))) == [200,409]
    with orm_session() as db:
        assert len(list(db.scalars(select(SalesOrder)))) == 1
        assert db.get(CrmOpportunity,opp['id']).version == 2


def test_audit_failure_rolls_back_order_opportunity_and_quote_then_releases_lock(seeded):
    client,admin,_,seller,*_ = seeded
    _,opp,data = base_records(seeded)
    quote = approved(seeded,data)
    def fail_audit(db,*_):
        if any(isinstance(row,CrmChange) and row.action == 'convert' for row in db.new):
            raise RuntimeError('模拟审计写入故障')
    event.listen(Session,'before_flush',fail_audit)
    try:
        action(client,seller,quote,'convert',status=500,acceptance_reference='接受',opportunity_version=1)
    finally:
        event.remove(Session,'before_flush',fail_audit)
    with orm_session() as db:
        assert db.get(CrmQuote,quote['id']).status == 'approved'
        assert db.get(CrmOpportunity,opp['id']).stage == 'prospect'
        assert list(db.scalars(select(SalesOrder))) == list(db.scalars(select(SalesOrderLine))) == []
    action(client,seller,quote,'convert',acceptance_reference='接受',opportunity_version=1)


def test_concurrent_contact_edit_rejects_stale_writer(seeded):
    client,admin,*_ = seeded
    contact,_,_ = base_records(seeded)
    def run(name):
        return client.put(C+f'/contacts/{contact["id"]}',headers=admin,json={
            'customer_id':contact['customer_id'],'name':name,'version':1,'reason':'资料核对'}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run,('甲','乙'))) == [200,409]
    assert len(client.get(C+f'/records/contact/{contact["id"]}/changes',headers=admin).json()) == 2


def test_lost_stage_requires_cancellation_of_active_approval(seeded):
    client,admin,*_ = seeded
    contact,opp,data = base_records(seeded)
    quote = approved(seeded,data)
    edit = {'customer_id':opp['customer_id'],'contact_id':contact['id'],'title':opp['title'],'owner_id':1,
        'stage':'lost','estimated_amount':'0','expected_close_date':'2030-01-31','version':1,'reason':'预算取消'}
    assert client.put(C+f'/opportunities/{opp["id"]}',headers=admin,json=edit).status_code == 409
    quote = action(client,admin,quote,'withdraw')
    action(client,admin,quote,'cancel')
    assert client.put(C+f'/opportunities/{opp["id"]}',headers=admin,json=edit).status_code == 200
    assert client.post(C+'/quotes',headers=admin,json={**data,'reference':'Q-2'}).status_code == 409


def test_strict_payload_boundaries_and_duplicate_reference(seeded):
    client,admin,*_ = seeded
    _,_,data = base_records(seeded)
    for patch in ({'opportunity_id':True},{'status':'approved'},{'reference':' '},{'valid_until':'2030-02-30'},
        {'lines':[{**data['lines'][0],'quantity':'0'}]}, {'lines':[{**data['lines'][0],'unit_price':'0.00001'}]},
        {'lines':[{**data['lines'][0],'material_id':True}]}, {'lines':[data['lines'][0],data['lines'][0]]}):
        response = client.post(C+'/quotes',headers=admin,json={**data,**patch})
        assert response.status_code == 422,response.text
    quote = client.post(C+'/quotes',headers=admin,json=data).json()
    assert client.post(C+'/quotes',headers=admin,json=data).status_code == 409
    action(client,admin,quote,'submit',status=422,reason=' ')
    assert client.get(C+'/records/wrong/1',headers=admin).status_code == 422
    assert client.get(C+'/records/quote/999/changes',headers=admin).status_code == 404


@pytest.mark.parametrize('stage', ['draft', 'submitted', 'approved'])
def test_contact_disabled_after_quote_blocks_actions_but_preserves_snapshot(seeded, stage):
    client,admin,reviewer,seller,*_ = seeded
    contact,opp,data = base_records(seeded)
    quote = client.post(C+'/quotes',headers=admin,json=data).json()
    if stage in ('submitted','approved'):
        quote = action(client,admin,quote,'submit')
    if stage == 'approved':
        quote = action(client,reviewer,quote,'approve')
    response = client.put(C+f'/contacts/{contact["id"]}',headers=admin,json={
        'customer_id':contact['customer_id'],'name':'已离职联系人','is_active':False,'version':1,'reason':'离职'})
    assert response.status_code == 200,response.text
    record = client.get(C+f'/records/quote/{quote["id"]}',headers=admin).json()
    assert not record['contact_active'] and record['party']['contact_name'] == '王女士'
    command = {'draft':'submit','submitted':'approve','approved':'convert'}[stage]
    actor = reviewer if stage == 'submitted' else seller
    extra = {'acceptance_reference':'接受依据','opportunity_version':opp['version']} if stage == 'approved' else {}
    action(client,actor,quote,command,status=422,**extra)
    after = client.get(C+f'/records/quote/{quote["id"]}',headers=admin).json()
    assert after == record
    with orm_session() as db:
        assert list(db.scalars(select(SalesOrder))) == []


def test_duplicate_quote_edit_rolls_back_reference_lines_and_audit(seeded):
    client,admin,*_ = seeded
    _,_,data = base_records(seeded)
    original = client.post(C+'/quotes',headers=admin,json=data).json()
    second = client.post(C+'/quotes',headers=admin,json={**data,'reference':'Q-2'}).json()
    audits = client.get(C+f'/records/quote/{second["id"]}/changes',headers=admin).json()
    response = client.put(C+f'/quotes/{second["id"]}',headers=admin,json={**data,
        'version':1,'reason':'模拟编号重复','lines':[{'material_id':data['lines'][0]['material_id'],'quantity':'2','unit_price':'3'}]})
    assert response.status_code == 409,response.text
    assert client.get(C+f'/records/quote/{second["id"]}',headers=admin).json() == second
    assert client.get(C+f'/records/quote/{original["id"]}',headers=admin).json() == original
    assert client.get(C+f'/records/quote/{second["id"]}/changes',headers=admin).json() == audits


def test_v49_upgrade_is_idempotent_preserves_business_and_models(seeded,remove_crm_schema):
    with sqlite3.connect(os.environ['NEXORA_DB_PATH']) as db:
        before = db.execute('SELECT id,name,created_at FROM customers ORDER BY id').fetchall()
        remove_crm_schema(db)
        db.execute('PRAGMA user_version=49')
    migrate(); migrate()
    with sqlite3.connect(os.environ['NEXORA_DB_PATH']) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 99
        assert db.execute('SELECT id,name,created_at FROM customers ORDER BY id').fetchall() == before
        assert db.execute('SELECT COUNT(*) FROM customers WHERE owner_id IS NULL').fetchone()[0] == len(before)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        assert db.execute("SELECT COUNT(*) FROM role_permissions WHERE role_code='seller' AND permission_code='crm.view'").fetchone()[0] == 1
        assert not db.execute("SELECT 1 FROM role_permissions WHERE role_code='seller' AND permission_code='crm_quote.review'").fetchone()
        assert len(Base.metadata.tables) == 198


def test_crm_upgrade_failure_rolls_back_schema_and_permissions(seeded,remove_crm_schema,monkeypatch):
    import app.core.database as database
    with database.connection() as db:
        remove_crm_schema(db)
        db.execute('PRAGMA user_version=49')
    original = database.connection
    @contextmanager
    def failing():
        with original() as db:
            db.set_authorizer(lambda operation,name,*_: sqlite3.SQLITE_DENY
                if operation == sqlite3.SQLITE_CREATE_TABLE and name == 'crm_changes' else sqlite3.SQLITE_OK)
            yield db
    monkeypatch.setattr(database,'connection',failing)
    with pytest.raises(Exception):
        migrate()
    with original() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 49
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='crm_quotes'").fetchone()
        assert not db.execute("SELECT 1 FROM permissions WHERE code='crm.view'").fetchone()


def test_converted_order_excludes_original_quote_submitter_without_new_author_rows(seeded):
    from app.core.models import DocumentApprovalAuthor, UserRole
    client, admin, reviewer, seller, *_ = seeded
    _, opportunity, data = base_records(seeded)
    quote = client.post(C + '/quotes', headers=admin, json=data).json()
    quote = action(client, seller, quote, 'submit')
    quote = action(client, reviewer, quote, 'approve')
    converted = action(client, admin, quote, 'convert', acceptance_reference='客户确认依据',
                       opportunity_version=opportunity['version'])
    identifier = converted['sales_order_id']
    with orm_session(write=True) as db:
        # 模拟没有新作者记录的旧派生草稿；原报价提交人升级为管理员后拥有按钮权限，可以审批。
        assert db.scalar(select(DocumentApprovalAuthor.user_id).where(
            DocumentApprovalAuthor.document_type == 'SalesOrder', DocumentApprovalAuthor.document_id == identifier)) is None
        db.add(UserRole(user_id=3, role_code='admin'))
    path = B + f'/system/document-approvals/SalesOrder/{identifier}'
    assert client.post(path + '/submit', headers=admin, json={'version': 0}).status_code == 200
    assert client.get(path, headers=seller).json()['can_review']
    assert client.post(path + '/approve', headers=reviewer, json={'version': 1}).status_code == 200
