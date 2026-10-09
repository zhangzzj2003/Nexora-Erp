"""真实接口验证首次设置、并发编号、事务回滚及历史证据不变。"""

import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.core.document_numbering import NUMBERED_MODELS, document_date, next_number, configuration
from app.core.document_types import DOCUMENT_TYPES
from app.core.models import WarehouseInbound, DocumentNumberSequence, DocumentNumberingSetting
from app.core.orm import orm_session


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'numbering.db'))
    with TestClient(app, client=('127.0.0.1', 1)) as client:
        assert client.post('/api/v1/setup/admin', json={'username': 'admin', 'password': 'secure-pass-123'}).status_code == 201
        login = client.post('/api/v1/auth/login', json={'username': 'admin', 'password': 'secure-pass-123'}).json()
        client.headers['Authorization'] = 'Bearer ' + login['token']
        yield client


def settings(client, **changes):
    return client.put('/api/v1/system/document-numbering', json={
        'style': 'english', 'timezone_mode': 'utc', 'timezone': None, 'version': 0, **changes})


def inbound(client, note='测试编号'):
    return client.post('/api/v1/warehouse-inbounds', json={'warehouse_id': 1, 'reason': 'other', 'note': note,
        'lines': [{'material_id': 1, 'quantity': '1'}]})


def seed_material(client):
    result = client.post('/api/v1/materials', json={'sku': 'NUMBER-TEST', 'name': '编号测试物料', 'unit': '个'})
    assert result.status_code == 201, result.text
    return result.json()['id']


def test_setup_required_permissions_and_validation(client):
    assert client.get('/api/v1/system/document-numbering').json()['configured'] is False
    assert inbound(client).status_code == 409
    assert client.post('/api/v1/materials', json={'name': 'test', 'unit': '个'}).status_code == 409
    assert client.post('/api/v1/reports/query', json={'report': 'inventory_balance'}).status_code != 409
    assert settings(client, style='unknown').status_code == 422
    assert settings(client, timezone_mode='specified', timezone='Not/AZone').status_code == 422
    assert settings(client, timezone='Asia/Shanghai').status_code == 422
    user = client.post('/api/v1/users', json={'username': 'viewer', 'password': 'secure-pass-123', 'roles': ['viewer']})
    assert user.status_code == 201
    login = client.post('/api/v1/auth/login', json={'username': 'viewer', 'password': 'secure-pass-123'}).json()
    auth = {'Authorization': 'Bearer ' + login['token']}
    assert client.get('/api/v1/system/document-numbering', headers=auth).status_code == 200
    assert client.put('/api/v1/system/document-numbering', headers=auth,
        json={'style': 'pinyin', 'timezone_mode': 'utc', 'timezone': None, 'version': 0}).status_code == 403
    assert client.get('/api/v1/stock', headers=auth).status_code == 200


@pytest.mark.parametrize('style,prefix', [('pinyin', 'QTRK'), ('english', 'OIN')])
def test_generated_number_immutable_cancelled_not_reused(client, style, prefix):
    assert settings(client, style=style).status_code == 200
    seed_material(client)
    first = inbound(client)
    assert first.status_code == 201, first.text
    row = first.json()
    assert row['document_no'].startswith(prefix + '-') and row['document_no'].endswith('-000001')
    assert row['reference'] == ''
    assert client.post(f"/api/v1/warehouse-inbounds/{row['id']}/cancel").json()['document_no'] == row['document_no']
    assert inbound(client).json()['document_no'].endswith('-000002')
    config = client.get('/api/v1/system/document-numbering').json()
    assert config['locked'] is True
    assert settings(client, version=config['version']).status_code == 409
    with pytest.raises(Exception, match='业务单号生成后不能修改'):
        with orm_session(write=True) as db:
            db.get(WarehouseInbound, row['id']).document_no = 'fake'
    assert next(item for item in client.get('/api/v1/warehouse-inbounds').json() if item['id'] == row['id'])['document_no'] == row['document_no']


def test_policy_can_change_only_before_first_number_and_stale_save(client):
    first = settings(client)
    assert first.status_code == 200 and not first.json()['locked']
    assert settings(client, version=0).status_code == 409
    result = settings(client, version=1, style='pinyin', timezone_mode='specified', timezone='Asia/Shanghai')
    assert result.status_code == 200 and result.json()['version'] == 2


@pytest.mark.parametrize('name,table,pinyin,english', DOCUMENT_TYPES)
def test_all_29_families_distinct_and_transactional(client, name, table, pinyin, english):
    settings(client)
    model = next(model for model in NUMBERED_MODELS if model.__name__ == name)
    with orm_session(write=True) as db:
        config = configuration(db)
        first = next_number(db, model, '2026-10-06 16:01:00', config)
        assert first == f'{english}-20261006-000001'
        assert next_number(db, model, '2026-10-06 16:02:00', config).endswith('-000002')
        assert next_number(db, model, '2026-10-07 00:00:00', config).endswith('-000001')
        config.style = 'pinyin'
        assert next_number(db, model, '2026-10-07 00:01:00', config).startswith(pinyin + '-')
    assert model.__table__.c.document_no is not None


@pytest.mark.parametrize('mode,zone,source,date', [
    ('utc', None, '2026-10-06 16:00:00', '20261006'),
    ('utc', None, '0001-01-01 00:00:00', '00010101'),
    ('specified', 'Asia/Shanghai', '2026-10-06 16:00:00', '20261007'),
    ('specified', 'America/New_York', '2026-03-08T06:59:00+00:00', '20260308'),
    ('specified', 'America/New_York', '2026-11-01T06:01:00+00:00', '20261101'),
    ('specified', 'Asia/Shanghai', 'missing', '00000000'),
])
def test_dates_midnight_dst_and_missing(mode, zone, source, date):
    assert document_date(source, SimpleNamespace(timezone_mode=mode, timezone=zone)) == date


def test_server_zone_ignores_client_and_follows_server(client, monkeypatch):
    import time
    if not hasattr(time, 'tzset'):
        # Windows 没有进程级 tzset，仍验证本机换算与客户端请求参数无关。
        source = datetime(2026, 10, 6, 16, tzinfo=timezone.utc)
        config = SimpleNamespace(timezone_mode='server', timezone=None)
        assert document_date(source.isoformat(), config) == source.astimezone().strftime('%Y%m%d')
        first = client.get('/api/v1/system/document-numbering').json()
        second = client.get('/api/v1/system/document-numbering', headers={'X-Timezone': 'Pacific/Honolulu'}).json()
        assert first['business_date'] == second['business_date']
        return
    original = os.environ.get('TZ')
    try:
        monkeypatch.setenv('TZ', 'Asia/Shanghai'); time.tzset()
        config = SimpleNamespace(timezone_mode='server', timezone=None)
        assert document_date('2026-10-06 16:00:00', config) == '20261007'
        monkeypatch.setenv('TZ', 'UTC'); time.tzset()
        assert document_date('2026-10-06 16:00:00', config) == '20261006'
    finally:
        if original is None: monkeypatch.delenv('TZ', raising=False)
        else: monkeypatch.setenv('TZ', original)
        time.tzset()


def test_parallel_clients_unique_and_rollback(client):
    settings(client); seed_material(client)
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda i: inbound(client, f'并发 {i}'), range(8)))
    assert all(response.status_code == 201 for response in responses)
    numbers = [response.json()['document_no'] for response in responses]
    assert len(set(numbers)) == 8
    with pytest.raises(RuntimeError, match='模拟失败'):
        with orm_session(write=True) as db:
            row = WarehouseInbound(warehouse_id=1, reason='other', note='回滚', reference='', created_by=1)
            db.add(row); db.flush()
            assert row.document_no.endswith('-000009')
            raise RuntimeError('模拟失败')
    assert inbound(client).json()['document_no'].endswith('-000009')


def test_historical_backfill_atomic_snapshots_and_restart(client, monkeypatch):
    # 模拟升级前真实旧单：未确认和已取消单都补号，不猜测供应商原始批号。
    with sqlite3.connect(os.environ['NEXORA_DB_PATH']) as db:
        db.execute("INSERT INTO warehouse_inbounds(warehouse_id,reason,note,reference,status,created_by,created_at) VALUES(1,'other','旧单','原依据','cancelled',1,'2026-10-06 16:00:00')")
        db.execute("INSERT INTO warehouse_inbounds(warehouse_id,reason,note,reference,status,created_by,created_at) VALUES(1,'other','异常日期','保留','draft',1,'未知')")
    before = client.get('/api/v1/warehouse-inbounds').json()
    assert all(row['document_no'] is None for row in before)
    import app.core.document_numbering as numbering
    original = numbering.next_number
    calls = []
    def fail_second(*args):
        calls.append(1)
        if len(calls) == 2: raise RuntimeError('补号失败')
        return original(*args)
    monkeypatch.setattr(numbering, 'next_number', fail_second)
    with pytest.raises(RuntimeError, match='补号失败'):
        settings(client, timezone_mode='specified', timezone='Asia/Shanghai')
    assert not client.get('/api/v1/system/document-numbering').json()['configured']
    assert all(row['document_no'] is None for row in client.get('/api/v1/warehouse-inbounds').json())
    monkeypatch.setattr(numbering, 'next_number', original)
    result = settings(client, timezone_mode='specified', timezone='Asia/Shanghai')
    assert result.status_code == 200, result.text
    assert result.json()['backfilled_count'] == 2 and result.json()['undated_count'] == 1
    after = client.get('/api/v1/warehouse-inbounds').json()
    by_note = {row['note']: row for row in after}
    assert by_note['旧单']['document_no'] == 'OIN-20261007-000001'
    assert by_note['异常日期']['document_no'] == 'OIN-00000000-000001'
    assert [{key: value for key, value in row.items() if key != 'document_no'} for row in after] == [
        {key: value for key, value in row.items() if key != 'document_no'} for row in before]
    from app.core.database import migrate
    migrate()
    assert client.get('/api/v1/warehouse-inbounds').json() == after


def test_two_administrators_compete_for_initial_rule(client):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda style: settings(client, style=style), ('english', 'pinyin')))
    assert sorted(result.status_code for result in results) == [200, 409]


def test_backup_restore_retains_policy_numbers_and_sequence(client, tmp_path, monkeypatch):
    from pathlib import Path
    from app.service.backup import create_backup, restore_backup
    from app.server import ensure_certificate
    settings(client, style='pinyin', timezone_mode='specified', timezone='Asia/Shanghai')
    seed_material(client)
    first = inbound(client).json()
    source = Path(os.environ['NEXORA_DB_PATH']).parent
    # 备份服务固定使用 nexora.db；本用例隔离复制已生成编号的测试实例。
    with sqlite3.connect(os.environ['NEXORA_DB_PATH']) as db, sqlite3.connect(source / 'nexora.db') as target:
        db.backup(target)
        identity = db.execute('SELECT id FROM server_identity').fetchone()[0]
    ensure_certificate(source, identity)
    archive = tmp_path / 'numbered.nexora-backup'
    create_backup(source, archive)
    restored = tmp_path / 'restored'
    restore_backup(archive, restored)
    monkeypatch.setenv('NEXORA_DB_PATH', str(restored / 'nexora.db'))
    config = client.get('/api/v1/system/document-numbering').json()
    assert config['locked'] and config['style'] == 'pinyin' and config['timezone'] == 'Asia/Shanghai'
    assert client.get('/api/v1/warehouse-inbounds').json()[0]['document_no'] == first['document_no']
    assert inbound(client).json()['document_no'].endswith('-000002')


def test_historical_order_respects_absolute_time_and_duplicate_dates(client):
    with sqlite3.connect(os.environ['NEXORA_DB_PATH']) as db:
        for timestamp in ('2026-10-07T01:00:00+08:00', '2026-10-06T18:00:00+00:00', '2026-10-07T01:00:00+08:00'):
            db.execute("INSERT INTO warehouse_inbounds(warehouse_id,reason,note,reference,status,created_by,created_at) VALUES(1,'other','','','draft',1,?)", (timestamp,))
    settings(client)
    rows = sorted(client.get('/api/v1/warehouse-inbounds').json(), key=lambda row: row['id'])
    assert [row['document_no'] for row in rows] == ['OIN-20261006-000001', 'OIN-20261006-000003', 'OIN-20261006-000002']


def test_configuration_write_lock_returns_retryable_conflict(client, monkeypatch):
    from contextlib import contextmanager
    from sqlalchemy.exc import OperationalError
    from app.service import document_numbering

    @contextmanager
    def locked_session(**kwargs):
        # 模拟另一位管理员长时间补号，而不是向用户返回数据库内部异常。
        raise OperationalError('BEGIN IMMEDIATE', {}, sqlite3.OperationalError('database is locked'))
        yield
    monkeypatch.setattr(document_numbering, 'orm_session', locked_session)
    assert settings(client).status_code == 409


def test_v88_migration_failure_rolls_back_all_numbering_structure(client, monkeypatch):
    from contextlib import contextmanager
    from app.core import database

    path = database.database_path()
    with sqlite3.connect(path) as db:
        # 还原升级前结构；保留原账户和各业务表，仅撤下第 88 版新增部分。
        for _, table, _, _ in DOCUMENT_TYPES:
            db.execute(f'DROP INDEX {table}_document_no')
            db.execute(f'ALTER TABLE {table} DROP COLUMN document_no')
        db.execute('DROP TABLE document_number_sequences')
        db.execute('DROP TABLE document_numbering_settings')
        db.execute('PRAGMA user_version=87')
        original_users = db.execute('SELECT id,username FROM users').fetchall()
    original_connection = database.connection

    class InterruptedMigration:
        def __init__(self, db): self.db = db
        def __getattr__(self, name): return getattr(self.db, name)
        def execute(self, statement, *args):
            if statement.startswith('ALTER TABLE purchase_goods_receipts ADD COLUMN document_no'):
                raise RuntimeError('模拟迁移中断')
            return self.db.execute(statement, *args)

    @contextmanager
    def interrupted_connection():
        with original_connection() as db:
            yield InterruptedMigration(db)
    monkeypatch.setattr(database, 'connection', interrupted_connection)
    with pytest.raises(RuntimeError, match='模拟迁移中断'):
        database.migrate()
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 87
        assert 'document_no' not in {row[1] for row in db.execute('PRAGMA table_info(purchase_requests)')}
        assert db.execute("SELECT name FROM sqlite_master WHERE name='document_numbering_settings'").fetchall() == []
        assert db.execute('SELECT id,username FROM users').fetchall() == original_users
    monkeypatch.setattr(database, 'connection', original_connection)
    database.migrate(); database.migrate()
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 100
        assert db.execute('SELECT style FROM document_numbering_settings').fetchone()[0] is None
        assert db.execute('SELECT id,username FROM users').fetchall() == original_users
        for _, table, _, _ in DOCUMENT_TYPES:
            assert 'document_no' in {row[1] for row in db.execute(f'PRAGMA table_info({table})')}
