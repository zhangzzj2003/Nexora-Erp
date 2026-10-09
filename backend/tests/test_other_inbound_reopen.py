"""取消/冲销重开的单次额度、新审批和双向来源证据。"""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import sqlite3

import pytest
from sqlalchemy import select
from app.core.models import WarehouseInbound, WarehouseInboundReopen, StockMovement
from app.core.orm import orm_session
from app.core.database import connection, migrate
from app.inventory.warehouse import balance
from approval_test_helpers import approve_document
from test_other_inbound_partial_receiving import inbound_client, create_inbound, post, lot_line


def body(material, quantity='1000'):
    return {'warehouse_id': 1, 'reason': 'other', 'note': '重开更正说明', 'reference': '参考',
            'lines': [{'material_id': material, 'quantity': quantity}]}


def records(client, auth):
    return client.get('/api/v1/warehouse-inbounds', headers=auth).json()


def test_cancelled_reopen_atomic_once_and_bidirectional_trace(inbound_client):
    client, auth, materials = inbound_client
    original = create_inbound(client, auth, materials[:1])
    endpoint = f'/api/v1/warehouse-inbounds/{original["id"]}'
    assert client.post(endpoint + '/reopen', headers=auth, json=body(materials[0])).status_code == 409
    assert client.post(endpoint + '/cancel', headers=auth).status_code == 200
    # 失败不占次数、不留空新单；并发保存仅允许一张新草稿。
    assert client.post(endpoint + '/reopen', headers=auth, json=body(999999)).status_code == 422
    assert len(records(client, auth)) == 1
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: client.post(endpoint + '/reopen', headers=auth, json=body(materials[0], '900')), range(2)))
    assert sorted(r.status_code for r in replies) == [201, 409]
    created = next(r.json() for r in replies if r.status_code == 201)
    assert created['id'] != original['id'] and created['document_no'] != original['document_no']
    assert created['status'] == 'draft' and created['approval']['status'] == 'draft'
    assert created['lines'][0]['id'] != original['lines'][0]['id']
    assert created['lines'][0]['physical_lots'] == [] and created['lines'][0]['quantity'] == '900'
    old = next(r for r in records(client, auth) if r['id'] == original['id'])
    assert old['status'] == 'cancelled' and old['reopened_as_id'] == created['id']
    assert old['reopen_trace'] == created['reopen_trace']
    link = created['reopen_trace'][0]
    assert (link['source_id'], link['new_id'], link['kind']) == (old['id'], created['id'], 'cancelled')
    assert link['created_by_name'] == 'admin' and link['created_at']
    for r in (old, created):
        trace = client.get(f'/api/v1/system/document-approvals/WarehouseInbound/{r["id"]}', headers=auth).json()
        assert trace['reopen_trace'] == [link]
    assert client.post(endpoint + '/reopen', headers=auth, json=body(materials[0])).status_code == 409
    assert client.post(f'/api/v1/warehouse-inbounds/{created["id"]}/post', headers=auth).status_code == 409
    # 后代取消后可从后代重开一次；父单额度不恢复，两段链路均留存。
    child = f'/api/v1/warehouse-inbounds/{created["id"]}'
    assert client.post(child + '/cancel', headers=auth).status_code == 200
    grandchild = client.post(child + '/reopen', headers=auth, json=body(materials[0])).json()
    mid = next(r for r in records(client, auth) if r['id'] == created['id'])
    assert len(mid['reopen_trace']) == 2 and mid['reopened_as_id'] == grandchild['id']
    with orm_session() as db:
        assert balance(db, 1, materials[0]) == Decimal(0)
        assert len(list(db.scalars(select(StockMovement)))) == 0


@pytest.mark.parametrize('partial', [False, True])
def test_reversed_reopen_keeps_stock_history_and_requires_new_approval(inbound_client, partial):
    client, auth, materials = inbound_client
    original = create_inbound(client, auth, materials[:1])
    identifier = original['id']
    endpoint = f'/api/v1/warehouse-inbounds/{identifier}'
    approve_document(client, auth, 'WarehouseInbound', identifier)
    if partial:
        assert post(client, auth, original, [lot_line(original['lines'][0], '800', '0')]).status_code == 200
    else:
        assert client.post(endpoint + '/post', headers=auth).status_code == 200
    assert client.post(endpoint + '/reopen', headers=auth, json=body(materials[0])).status_code == 409
    approve_document(client, auth, 'WarehouseInbound', identifier, intent='reverse', reason='重复登记')
    assert client.post(endpoint + '/reverse', headers=auth, json={'reason': '重复登记'}).status_code == 201
    before = records(client, auth)[0]
    with orm_session() as db:
        ledger = [(row.id, row.quantity) for row in db.scalars(select(StockMovement).order_by(StockMovement.id))]
    reply = client.post(endpoint + '/reopen', headers=auth, json=body(materials[0]))
    assert reply.status_code == 201, reply.text
    new = reply.json()
    assert new['reopen_trace'][0]['kind'] == 'reversed'
    assert new['reversal_id'] is None and new['approval']['status'] == 'draft'
    after = next(r for r in records(client, auth) if r['id'] == identifier)
    for field in ['status', 'reversal_id', 'reversal_reason', 'reversed_at', 'lines', 'approval', 'reversal_approval']:
        assert after[field] == before[field]
    with orm_session() as db:
        assert ledger == [(row.id, row.quantity) for row in db.scalars(select(StockMovement).order_by(StockMovement.id))]
        assert balance(db, 1, materials[0]) == 0
    assert client.post(f'/api/v1/warehouse-inbounds/{new["id"]}/post', headers=auth).status_code == 409
    approve_document(client, auth, 'WarehouseInbound', new['id'])
    assert client.post(f'/api/v1/warehouse-inbounds/{new["id"]}/post', headers=auth).status_code == 200
    assert client.post(endpoint + '/reopen', headers=auth, json=body(materials[0])).status_code == 409


def test_reopen_permission_missing_source_and_upgrade_evidence(inbound_client):
    client, auth, materials = inbound_client
    old = create_inbound(client, auth, materials[:1])
    assert client.post(f'/api/v1/warehouse-inbounds/{old["id"]}/cancel', headers=auth).status_code == 200
    assert client.post('/api/v1/warehouse-inbounds/999999/reopen', headers=auth, json=body(materials[0])).status_code == 404
    created = client.post('/api/v1/users', headers=auth, json={'username': 'readonly', 'password': 'secure-pass-123', 'roles': ['viewer']})
    assert created.status_code == 201, created.text
    token = client.post('/api/v1/auth/login', json={'username': 'readonly', 'password': 'secure-pass-123'}).json()['token']
    assert client.post(f'/api/v1/warehouse-inbounds/{old["id"]}/reopen', headers={'Authorization': 'Bearer ' + token}, json=body(materials[0])).status_code == 403
    # v98 历史单升级后不凭参考号伪造来源，重复启动不重复建证据。
    with connection() as db:
        db.execute('DROP TABLE warehouse_inbound_reopens')
        db.execute('PRAGMA user_version=98')
    migrate(); migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 99
        assert db.execute('SELECT count(*) FROM warehouse_inbound_reopens').fetchone()[0] == 0
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    new = client.post(f'/api/v1/warehouse-inbounds/{old["id"]}/reopen', headers=auth, json=body(materials[0])).json()
    with connection() as db:
        for sql in ['UPDATE warehouse_inbound_reopens SET kind="reversed"', 'DELETE FROM warehouse_inbound_reopens']:
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(sql)
    assert new['reopen_trace'][0]['kind'] == 'cancelled'
