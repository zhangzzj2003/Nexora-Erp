"""v108 扩展转单目标，历史行和约束保留，失败不留下半张表。"""
import sqlite3
import pytest
from app.core.database import _migrate_plan_required as migrate_plan_required


def old_database():
    db = sqlite3.connect(':memory:')
    db.execute('PRAGMA foreign_keys=ON')
    for table in ('users', 'mrp_plans', 'purchase_requests', 'work_orders', 'production_plans'):
        db.execute(f'CREATE TABLE {table} (id INTEGER PRIMARY KEY)')
        db.execute(f'INSERT INTO {table} VALUES (1)')
    db.execute('CREATE TABLE permissions (code TEXT PRIMARY KEY, label TEXT)')
    db.execute("INSERT INTO permissions VALUES ('mrp.convert','自定义转换名称')")
    db.execute('''CREATE TABLE mrp_conversions (
        id INTEGER PRIMARY KEY, plan_id INTEGER NOT NULL REFERENCES mrp_plans(id), suggestion_key TEXT NOT NULL,
        purchase_request_id INTEGER UNIQUE REFERENCES purchase_requests(id), work_order_id INTEGER UNIQUE REFERENCES work_orders(id),
        due_date TEXT NOT NULL, reason TEXT NOT NULL, created_by INTEGER NOT NULL REFERENCES users(id),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(plan_id,suggestion_key),
        CHECK((purchase_request_id IS NOT NULL)+(work_order_id IS NOT NULL)=1))''')
    db.execute("INSERT INTO mrp_conversions VALUES (7,1,'old-work',NULL,1,'2030-01-01','历史制造',1,'2026-01-01')")
    db.execute("INSERT INTO mrp_conversions VALUES (8,1,'old-buy',1,NULL,'2030-01-02','历史采购',1,'2026-01-02')")
    db.commit()
    return db


def test_conversion_migration_preserves_legacy_and_requires_exactly_one_target():
    with old_database() as db:
        before = db.execute('SELECT * FROM mrp_conversions ORDER BY id').fetchall()
        migrate_plan_required(db)
        migrate_plan_required(db)
        columns = 'id,plan_id,suggestion_key,purchase_request_id,work_order_id,due_date,reason,created_by,created_at'
        assert db.execute(f'SELECT {columns} FROM mrp_conversions ORDER BY id').fetchall() == before
        assert db.execute('SELECT production_plan_id FROM mrp_conversions').fetchall() == [(None,), (None,)]
        assert db.execute('SELECT label FROM permissions').fetchone()[0] == '自定义转换名称'
        db.execute("INSERT INTO mrp_conversions (plan_id,suggestion_key,production_plan_id,due_date,reason,created_by) VALUES (1,'new',1,'2030-01-01','先编计划',1)")
        for targets in ('NULL,NULL,NULL', '1,1,NULL', 'NULL,1,1'):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(f"INSERT INTO mrp_conversions (plan_id,suggestion_key,purchase_request_id,work_order_id,production_plan_id,due_date,reason,created_by) VALUES (1,'bad',{targets},'2030-01-01','错误',1)")
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


@pytest.mark.parametrize('failure', ['INSERT INTO mrp_conversions_v108', 'DROP TABLE mrp_conversions', 'ALTER TABLE mrp_conversions_v108'])
def test_conversion_migration_failure_rolls_back(failure):
    db = old_database()
    before = db.execute('SELECT * FROM mrp_conversions').fetchall()
    class BrokenConnection:
        def execute(self, sql, *args):
            if sql.startswith(failure):
                raise RuntimeError('模拟迁移失败')
            return db.execute(sql, *args)
    with pytest.raises(RuntimeError), db:
        # 与正式迁移相同，结构变更必须处于显式事务内。
        db.execute('BEGIN IMMEDIATE')
        migrate_plan_required(BrokenConnection())
    assert db.execute('SELECT * FROM mrp_conversions').fetchall() == before
    assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='mrp_conversions_v108'").fetchall()
    assert 'production_plan_id' not in [row[1] for row in db.execute('PRAGMA table_info(mrp_conversions)')]
    db.close()
