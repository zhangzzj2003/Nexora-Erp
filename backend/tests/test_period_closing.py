from approval_test_helpers import execute_production_settlement, approve_document
"""结账证据、并发、历史成本锁定及追加式跨期更正的真实风险。"""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core.database import connection, migrate
from app.core.models import (AccountingPeriod, AccountingPeriodChange, InventoryCostInput,
    Material, PeriodClosing, StockMovement)
from app.core.orm import orm_session
from test_journals import journals, posted, create, action, payload, PATH
from test_ledger_foundation import ledger, PERIOD, BASE
from test_production_settlements import erp
from test_opening_balances import confirmed

PERIODS = BASE + '/accounting-periods'


def command(client, period_id=1, version=1, name='close', status=200, headers=None):
    response = client.post(f'{PERIODS}/{period_id}/{name}',
        json=dict(version=version, reason='核对单据及期末余额'), headers=headers)
    assert response.status_code == status, response.text
    return response.json() if status != 500 else response.text


def check(client, period_id=1):
    response = client.get(f'{PERIODS}/{period_id}/closing-check')
    assert response.status_code == 200, response.text
    return response.json()


def history(client, period_id=1):
    response = client.get(f'{PERIODS}/{period_id}/closings')
    assert response.status_code == 200, response.text
    return response.json()


def test_close_reopen_reclose_archive_and_late_journal_correction(journals):
    client, reviewer = journals
    original = posted(journals)
    assert check(client)['can_close']
    result = command(client)
    assert result['period']['status'] == 'closed' and result['period']['version'] == 2
    first = history(client)[0]
    assert first['evidence']['ledger']['totals']['debit'] == '123.45'
    assert first['evidence']['posted_journal_ids'] == [original['id']]
    assert first['reason'] and first['created_by_name'] == 'admin'
    assert client.post(PATH, json=payload('LOCKED')).status_code == 409
    assert client.put(f'{PERIODS}/1', json=dict(version=2, name='改名', reason='锁期')).status_code == 409
    command(client, version=2, status=409)
    client.post(PERIODS, json={**PERIOD, 'code':'FEB', 'start_date':'2026-02-01', 'end_date':'2026-02-28'})
    reversal = client.post(f'{PATH}/{original["id"]}/reverse', json=dict(version=original['version'],
        reason='后续期间更正', reference='LATE', journal_date='2026-02-10'))
    assert reversal.status_code == 201, reversal.text
    row = action(client, reversal.json(), 'submit')
    row = action(client, row, 'approve', reviewer)
    action(client, row, 'post')
    assert history(client)[0] == first
    command(client, version=2, name='reopen')
    assert [item['action'] for item in history(client)] == ['reopen','close']
    assert history(client)[1] == first
    command(client, version=3)
    records = history(client)
    assert records[0]['period_version'] == 4 and records[2] == first
    assert records[0]['evidence']['ledger']['totals'] == first['evidence']['ledger']['totals']
    assert len(client.get(f'{PERIODS}/1/changes').json()) == 4


def test_order_future_gap_and_version_guards(journals, monkeypatch):
    client, _ = journals
    client.post(PERIODS, json={**PERIOD, 'code':'MAR', 'start_date':'2026-03-01', 'end_date':'2026-03-31'})
    assert 'earlier_open' in [item['code'] for item in check(client, 2)['blockers']]
    command(client, 2, status=409)
    monkeypatch.setattr('app.finance.period_closing.utc_today', lambda:'2026-01-31')
    assert 'not_ended' in [item['code'] for item in check(client)['blockers']]
    command(client, status=409)
    monkeypatch.setattr('app.finance.period_closing.utc_today', lambda:'2026-04-01')
    command(client)
    command(client, version=1, name='reopen', status=409)
    command(client, 2)
    command(client, version=2, name='reopen', status=409)
    # 二月虽未建期间，也不能在三月已结后新插一个历史期间。
    assert client.post(PERIODS, json={**PERIOD, 'code':'FEB', 'start_date':'2026-02-01',
        'end_date':'2026-02-28'}).status_code == 409
    command(client, 2, version=2, name='reopen')
    command(client, version=2, name='reopen')
    assert client.post(PERIODS, json={**PERIOD, 'code':'FEB', 'start_date':'2026-02-01',
        'end_date':'2026-02-28'}).status_code == 201


def test_v42_upgrade_failure_does_not_leave_partial_closing_schema(journals, remove_closing_schema):
    # 模拟权限迁移在建表之后失败，版本与新表必须一起回滚，恢复后仍能正常升级。
    import sqlite3
    with connection() as db:
        remove_closing_schema(db)
        db.execute('PRAGMA user_version=42')
        db.execute("""CREATE TRIGGER fail_closing_permissions BEFORE INSERT ON permissions
            WHEN NEW.code='accounting_period.closing_view'
            BEGIN SELECT RAISE(ABORT, '模拟权限迁移失败'); END""")
    with pytest.raises(sqlite3.IntegrityError, match='模拟权限迁移失败'):
        migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 42
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='period_closings'").fetchall()
        db.execute('DROP TRIGGER fail_closing_permissions')
    migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 96
        assert db.execute('SELECT COUNT(*) FROM period_closings').fetchone()[0] == 0


def test_precheck_is_revalidated_and_pending_journal_can_be_cancelled(journals):
    client, _ = journals
    assert check(client)['can_close']
    row = create(client)
    result = check(client)
    assert result['blockers'][0]['code'] == 'pending_journals'
    assert result['blockers'][0]['ids'] == [row['id']]
    command(client, status=409)
    action(client, row, 'cancel')
    command(client)


def test_opening_is_locked_even_without_posted_journal(journals):
    client, _ = journals
    record = confirmed(journals)
    command(client)
    assert history(client)[0]['evidence']['ledger']['totals']['closing_debit'] == '123.45'
    assert client.post(f'/api/v1/finance/opening-balances/{record["id"]}/reverse',
        json=dict(version=record['version'], reason='回改期初')).status_code == 409
    command(client, version=2, name='reopen')
    from approval_test_helpers import execute_production_settlement, approve_document
    approve_document(client, None, 'OpeningBalance', record['id'], intent='reverse', reason='重新核对')
    assert client.post(f'/api/v1/finance/opening-balances/{record["id"]}/reverse',
        json=dict(version=record['version'], reason='重新核对')).status_code == 200
    assert not check(client)['can_close']


def test_inventory_cutoff_missing_prices_and_closed_source_lock(journals):
    client, _ = journals
    item = client.post('/api/v1/materials', json=dict(sku='COST', name='原材料', unit='件')).json()
    with orm_session(write=True) as db:
        old = StockMovement(warehouse_id=1, material_id=item['id'], quantity='2', source_type='other_inbound',
            source_id=1, source_line_id=1, created_by=1, created_at='2026-01-31 23:59:59')
        future = StockMovement(warehouse_id=1, material_id=item['id'], quantity='1', source_type='other_inbound',
            source_id=2, source_line_id=2, created_by=1, created_at='2026-02-01 00:00:00')
        db.add_all([old, future]); db.flush()
        old_id, future_id = old.id, future.id
    result = check(client)
    assert result['movement_count'] == 1
    assert result['blockers'][0]['ids'] == [old_id]
    command(client, status=409)
    def price(movement, reference):
        return client.post('/api/v1/inventory/valuation/inputs',
            json=dict(movement_id=movement, unit_cost='2.5555', reference=reference, reason='核价依据'))
    assert price(old_id, 'OLD').status_code == 201
    assert check(client)['inventory_total'] == '5.11'
    command(client)
    original = history(client)[0]
    assert price(old_id, 'DENIED').status_code == 409
    assert price(future_id, 'FUTURE').status_code == 201
    assert history(client)[0] == original
    with orm_session() as db:
        assert len(list(db.scalars(select(InventoryCostInput)))) == 2
    command(client, version=2, name='reopen')
    assert price(old_id, 'REOPEN').status_code == 201


@pytest.mark.parametrize('active', [True, False])
def test_production_allocations_cannot_reprice_closed_movements(erp, active):
    _, _, api, material, receipt, work_order, complete = erp
    raw, product = material('RAW'), material('PRODUCT')
    receipt(raw, '2', '10')
    order, _ = work_order(raw, product)
    complete(order)
    if active:
        settlement = api('POST', 'production-costs/settlements',
            dict(work_order_id=order['id'], reference='INITIAL'), 201)
        settlement = execute_production_settlement(erp[0], erp[1], settlement)
    else:
        movement = next(item for item in api('GET','inventory/valuation')['movements']
            if item['source_type'] == 'production_completion')
        api('POST','inventory/valuation/inputs', dict(movement_id=movement['id'],
            unit_cost='10', reference='MANUAL', reason='暂核完工'), 201)
    with orm_session(write=True) as db:
        for row in db.scalars(select(StockMovement)):
            row.created_at = '2026-01-10 10:00:00'
    api('POST','finance/accounting-periods', PERIOD, 201)
    api('POST','finance/accounting-periods/1/close', dict(version=1, reason='成本核对'))
    if active:
        api('POST', f'production-costs/settlements/{settlement["id"]}/reverse', dict(reason='回改'), 409)
    else:
        api('POST','production-costs/settlements', dict(work_order_id=order['id'], reference='LATE'), 409)
    api('POST','finance/accounting-periods/1/reopen', dict(version=2, reason='补成本'))
    if active:
        approve_document(erp[0], erp[1], 'ProductionCostSettlement', settlement['id'], intent='reverse', reason='重开更正')
        api('POST', f'production-costs/settlements/{settlement["id"]}/reverse', dict(reason='重开更正'))
    else:
        api('POST','production-costs/settlements', dict(work_order_id=order['id'], reference='LATE'), 201)


def test_concurrent_close_and_reopen_versions(journals):
    client, _ = journals
    def run(name, version):
        with ThreadPoolExecutor(max_workers=2) as pool:
            return sorted(pool.map(lambda _: client.post(f'{PERIODS}/1/{name}',
                json=dict(version=version, reason='并发')).status_code, range(2)))
    assert run('close',1) == [200,409]
    assert len(history(client)) == 1
    assert run('reopen',2) == [200,409]
    assert len(history(client)) == 2


@pytest.mark.parametrize('action_name', ['close','reopen'])
def test_snapshot_or_audit_failure_rolls_back_status_and_version(journals, action_name):
    client, _ = journals
    version = 1
    if action_name == 'reopen':
        command(client); version = 2
    def fail(_session, _context, _instances):
        if any(isinstance(item, AccountingPeriodChange) for item in _session.new):
            raise RuntimeError('模拟审计保存失败')
    event.listen(Session,'before_flush',fail)
    try:
        command(client, version=version, name=action_name, status=500)
    finally:
        event.remove(Session,'before_flush',fail)
    with orm_session() as db:
        record = db.get(AccountingPeriod,1)
        assert record.version == version
        assert record.status == ('open' if action_name == 'close' else 'closed')
    assert len(history(client)) == version - 1
    command(client, version=version, name=action_name)


def test_server_clock_backdating_rolls_back_related_changes(journals):
    client, _ = journals
    command(client)
    with pytest.raises(HTTPException, match='409'):
        with orm_session(write=True) as db:
            material = Material(sku='BACKDATED', name='不能半提交', unit='件')
            db.add(material); db.flush()
            db.add(StockMovement(warehouse_id=1, material_id=material.id, quantity='1',
                source_type='other_inbound', source_id=99, source_line_id=99,
                created_by=1, created_at='2026-01-31 23:59:59'))
    with orm_session() as db:
        assert not list(db.scalars(select(Material)))
        assert not list(db.scalars(select(StockMovement)))


def test_explicit_read_and_write_permissions_and_v42_migration(journals, remove_closing_schema):
    client, reviewer = journals
    assert client.post('/api/v1/roles', json=dict(code='metadata',label='仅期间资料',
        permissions=['accounting_period.view'])).status_code == 201
    client.post('/api/v1/users', json=dict(username='metadata',password='secure-pass-123',roles=['metadata']))
    token = client.post('/api/v1/auth/login', json=dict(username='metadata',password='secure-pass-123')).json()['token']
    headers = dict(Authorization='Bearer '+token)
    for path in ('closing-check','closings'):
        assert client.get(f'{PERIODS}/1/{path}',headers=headers).status_code == 403
    for name in ('close','reopen'):
        command(client, name=name, headers=headers, status=403)
    command(client, headers=reviewer)
    command(client, version=2, name='reopen', headers=reviewer, status=403)
    assert client.post(f'{PERIODS}/1/reopen', json=dict(version=True, reason='无效')).status_code == 422
    assert client.get(f'{PERIODS}/999/closings').status_code == 404
    assert client.get(f'{PERIODS}/0/closing-check').status_code == 422
    with connection() as db:
        remove_closing_schema(db)
        db.execute('PRAGMA user_version=42')
    migrate(); migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 96
        assert db.execute('SELECT COUNT(*) FROM period_closings').fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM role_permissions WHERE permission_code='accounting_period.close'").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM role_permissions WHERE permission_code='accounting_period.reopen'").fetchone()[0] == 1
    # 迁移不为外部已关闭的期间虚构结账证据。
    command(client, version=2, name='reopen', status=409)
