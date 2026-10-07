"""资金审批结构迁移：原金额、编号与凭证指纹字段保持原值。"""

import re
import sqlite3


def migrate_payment_records(db: sqlite3.Connection) -> None:
    table = 'payment_records'
    original = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    if original is None:
        # 仅权限的旧结构诊断夹具不包含业务表，不能凭空生成残缺的资金表。
        return
    if 'status' in {row[1] for row in db.execute(f'PRAGMA table_info({table})')}:
        return
    indexes = [row[0] for row in db.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL", (table,))]
    # SQLite 不能删除内联 UNIQUE；临时表原样复制全部列，仅取消后的草稿释放引用及参考号。
    statement = re.sub(r'CREATE TABLE\s+"?payment_records"?', 'CREATE TABLE payment_records_approval_upgrade', original[0], count=1, flags=re.I)
    statement = re.sub(r'(reverses_id\s+INTEGER)\s+UNIQUE', r'\1', statement, count=1, flags=re.I)
    db.execute(statement)
    db.execute(f'INSERT INTO payment_records_approval_upgrade SELECT * FROM {table}')
    db.execute(f'DROP TABLE {table}')
    db.execute('ALTER TABLE payment_records_approval_upgrade RENAME TO payment_records')
    for column in ("status TEXT NOT NULL DEFAULT 'executed' CHECK(status IN ('draft','executed','cancelled'))",
                   'version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0)',
                   'executed_by INTEGER REFERENCES users(id)', 'executed_at TEXT',
                   'cancelled_by INTEGER REFERENCES users(id)', 'cancelled_at TEXT',
                   "cancellation_reason TEXT NOT NULL DEFAULT ''"):
        db.execute(f'ALTER TABLE {table} ADD COLUMN {column}')
    # 迁移保留旧登记时间与人员作为执行事实，不补造审批、流水或业务凭证。
    db.execute('UPDATE payment_records SET executed_by=created_by, executed_at=created_at')
    for statement in indexes:
        if 'payment_records_reference' in statement:
            statement += " AND status <> 'cancelled'"
        db.execute(statement)
    db.execute("CREATE UNIQUE INDEX payment_records_active_reversal ON payment_records(reverses_id) WHERE status <> 'cancelled'")
