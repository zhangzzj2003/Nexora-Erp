"""本地 SQLite 连接与版本迁移。"""

import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Iterator

from app.access.permission_seed import DEFAULT_PERMISSION_LABELS, PERMISSION_GROUP_PATHS


def database_path() -> Path:
    # 测试和部署可覆盖路径；默认数据放在用户目录，避免写入安装目录。
    return Path(os.environ.get("NEXORA_DB_PATH", Path.home() / ".nexora-erp" / "nexora.db"))


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(path, timeout=10)
    if os.name != "nt":
        # ERP 业务数据库仅允许当前系统用户读取，即使数据目录位于共享父目录。
        os.chmod(path, 0o600)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA busy_timeout = 10000")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def migrate() -> None:
    with connection() as db:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version > 76:
            raise RuntimeError(f"数据库版本 {version} 高于当前程序支持的版本")
        if version == 0:
            # 整个初始迁移放在一个事务中，避免中途失败留下半套表。
            db.executescript("""
            BEGIN IMMEDIATE;
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE roles (
                code TEXT PRIMARY KEY,
                label TEXT NOT NULL
            );
            CREATE TABLE permissions (
                code TEXT PRIMARY KEY
            );
            CREATE TABLE role_permissions (
                role_code TEXT NOT NULL REFERENCES roles(code),
                permission_code TEXT NOT NULL REFERENCES permissions(code),
                PRIMARY KEY (role_code, permission_code)
            );
            CREATE TABLE user_roles (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role_code TEXT NOT NULL REFERENCES roles(code),
                PRIMARY KEY (user_id, role_code)
            );
            CREATE TABLE sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at INTEGER NOT NULL
            );
            CREATE TABLE suppliers (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE materials (
                id INTEGER PRIMARY KEY,
                sku TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                unit TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE receipts (
                id INTEGER PRIMARY KEY,
                supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
                reference TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'posted')),
                created_by INTEGER NOT NULL REFERENCES users(id),
                posted_by INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                posted_at TEXT
            );
            CREATE TABLE receipt_lines (
                id INTEGER PRIMARY KEY,
                receipt_id INTEGER NOT NULL REFERENCES receipts(id),
                material_id INTEGER NOT NULL REFERENCES materials(id),
                quantity TEXT NOT NULL,
                UNIQUE (receipt_id, material_id)
            );
            CREATE TABLE stock_movements (
                id INTEGER PRIMARY KEY,
                material_id INTEGER NOT NULL REFERENCES materials(id),
                quantity TEXT NOT NULL,
                receipt_line_id INTEGER NOT NULL UNIQUE REFERENCES receipt_lines(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO roles(code, label) VALUES
                ('admin', '管理员'), ('buyer', '采购员'),
                ('warehouse', '仓库员'), ('viewer', '查看员');
            INSERT INTO permissions(code) VALUES
                ('users.manage'), ('catalog.manage'), ('inventory.view'),
                ('receipt.create'), ('receipt.post');
            INSERT INTO role_permissions(role_code, permission_code) VALUES
                ('admin', 'users.manage'), ('admin', 'catalog.manage'),
                ('admin', 'inventory.view'), ('admin', 'receipt.create'),
                ('admin', 'receipt.post'),
                ('buyer', 'catalog.manage'), ('buyer', 'inventory.view'),
                ('buyer', 'receipt.create'),
                ('warehouse', 'catalog.manage'), ('warehouse', 'inventory.view'),
                ('warehouse', 'receipt.post'),
                ('viewer', 'inventory.view');
            PRAGMA user_version = 1;
            COMMIT;
            """)
        if version < 2:
            # 服务端身份与业务数据库一起保存，升级旧数据库不会改变任何业务记录。
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE server_identity (id TEXT PRIMARY KEY, name TEXT NOT NULL)")
            db.execute("INSERT INTO server_identity(id, name) VALUES (?, ?)",
                       (str(uuid.uuid4()), os.environ.get("NEXORA_INSTANCE_NAME", "Nexora ERP 服务端")))
            db.execute("PRAGMA user_version = 2")
            db.commit()
        if version < 3:
            # 旧用户默认保持启用；内置角色标记为只读，避免误改造成全员权限漂移。
            db.execute("BEGIN IMMEDIATE")
            db.execute("ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))")
            db.execute("ALTER TABLE roles ADD COLUMN is_builtin INTEGER NOT NULL DEFAULT 0 CHECK (is_builtin IN (0, 1))")
            db.execute("UPDATE roles SET is_builtin = 1 WHERE code IN ('admin', 'buyer', 'warehouse', 'viewer')")
            db.execute("PRAGMA user_version = 3")
        if version < 4:
            # 为历史入库和库存流水指定主仓库，再把流水改成可记录调拨等来源的通用账本。
            # 迁移全程持有写锁；任一步失败都会回滚，避免出现只有一半仓库字段的数据。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE warehouses (
                id INTEGER PRIMARY KEY,
                code TEXT NOT NULL UNIQUE COLLATE NOCASE,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            db.execute("INSERT INTO warehouses(id, code, name) VALUES (1, 'MAIN', '主仓库')")
            db.execute("""CREATE TABLE receipt_warehouses (
                receipt_id INTEGER PRIMARY KEY REFERENCES receipts(id),
                warehouse_id INTEGER NOT NULL REFERENCES warehouses(id)
            )""")
            db.execute("INSERT INTO receipt_warehouses(receipt_id, warehouse_id) SELECT id, 1 FROM receipts")
            db.execute("ALTER TABLE stock_movements RENAME TO stock_movements_legacy")
            db.execute("""CREATE TABLE stock_movements (
                id INTEGER PRIMARY KEY,
                warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
                material_id INTEGER NOT NULL REFERENCES materials(id),
                quantity TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_id INTEGER NOT NULL,
                source_line_id INTEGER NOT NULL,
                created_by INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (source_type, source_line_id)
            )""")
            db.execute("""INSERT INTO stock_movements(
                id, warehouse_id, material_id, quantity, source_type, source_id,
                source_line_id, created_by, created_at)
                SELECT sm.id, rw.warehouse_id, sm.material_id, sm.quantity, 'receipt',
                       rl.receipt_id, rl.id, r.posted_by, sm.created_at
                FROM stock_movements_legacy sm
                JOIN receipt_lines rl ON rl.id = sm.receipt_line_id
                JOIN receipts r ON r.id = rl.receipt_id
                JOIN receipt_warehouses rw ON rw.receipt_id = r.id""")
            db.execute("DROP TABLE stock_movements_legacy")
            db.execute("CREATE INDEX stock_movements_balance ON stock_movements(warehouse_id, material_id)")
            db.execute("""CREATE TABLE transfers (
                id INTEGER PRIMARY KEY,
                from_warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
                to_warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
                reference TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'posted')),
                created_by INTEGER NOT NULL REFERENCES users(id),
                posted_by INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                posted_at TEXT,
                CHECK (from_warehouse_id <> to_warehouse_id)
            )""")
            db.execute("""CREATE TABLE transfer_lines (
                id INTEGER PRIMARY KEY,
                transfer_id INTEGER NOT NULL REFERENCES transfers(id),
                material_id INTEGER NOT NULL REFERENCES materials(id),
                quantity TEXT NOT NULL,
                UNIQUE (transfer_id, material_id)
            )""")
            db.executemany("INSERT INTO permissions(code) VALUES (?)",
                           [(code,) for code in ("warehouse.manage", "transfer.create", "transfer.post")])
            db.executemany("INSERT INTO role_permissions(role_code, permission_code) VALUES (?, ?)",
                           [(role, code) for role in ("admin", "warehouse")
                            for code in ("warehouse.manage", "transfer.create", "transfer.post")])
            db.execute("PRAGMA user_version = 4")
        if version < 5:
            # 采购订单和入库明细使用关联表，历史自由入库单无需改写或猜测订单来源。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE purchase_orders (
                id INTEGER PRIMARY KEY,
                supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
                reference TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN
                    ('draft', 'confirmed', 'partially_received', 'received', 'cancelled')),
                created_by INTEGER NOT NULL REFERENCES users(id),
                confirmed_by INTEGER REFERENCES users(id),
                cancelled_by INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                confirmed_at TEXT,
                cancelled_at TEXT
            )""")
            db.execute("""CREATE TABLE purchase_order_lines (
                id INTEGER PRIMARY KEY,
                purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id),
                material_id INTEGER NOT NULL REFERENCES materials(id),
                quantity TEXT NOT NULL,
                unit_price TEXT NOT NULL,
                UNIQUE (purchase_order_id, material_id)
            )""")
            db.execute("""CREATE TABLE receipt_order_links (
                receipt_line_id INTEGER PRIMARY KEY REFERENCES receipt_lines(id),
                purchase_order_line_id INTEGER NOT NULL REFERENCES purchase_order_lines(id)
            )""")
            db.execute("CREATE INDEX receipt_order_links_order_line ON receipt_order_links(purchase_order_line_id)")
            db.executemany("INSERT INTO permissions(code) VALUES (?)",
                           [(code,) for code in ("purchase_order.create", "purchase_order.confirm",
                                                "purchase_order.cancel")])
            db.executemany("INSERT INTO role_permissions(role_code, permission_code) VALUES (?, ?)",
                           [(role, code) for role in ("admin", "buyer")
                            for code in ("purchase_order.create", "purchase_order.confirm",
                                         "purchase_order.cancel")])
            db.execute("PRAGMA user_version = 5")
        if version < 6:
            # 盘点保存建单时的账面量；确认时若账面量已变化，须重新盘点，避免覆盖期间交易。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE stocktakes (
                id INTEGER PRIMARY KEY,
                warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
                reference TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'posted', 'cancelled')),
                created_by INTEGER NOT NULL REFERENCES users(id),
                posted_by INTEGER REFERENCES users(id),
                cancelled_by INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                posted_at TEXT,
                cancelled_at TEXT
            )""")
            db.execute("""CREATE TABLE stocktake_lines (
                id INTEGER PRIMARY KEY,
                stocktake_id INTEGER NOT NULL REFERENCES stocktakes(id),
                material_id INTEGER NOT NULL REFERENCES materials(id),
                book_quantity TEXT NOT NULL,
                counted_quantity TEXT NOT NULL,
                movement_id INTEGER NOT NULL,
                UNIQUE (stocktake_id, material_id)
            )""")
            db.executemany("INSERT INTO permissions(code) VALUES (?)",
                           [(code,) for code in ("stocktake.create", "stocktake.post", "stocktake.cancel")])
            db.executemany("INSERT INTO role_permissions(role_code, permission_code) VALUES (?, ?)",
                           [(role, code) for role in ("admin", "warehouse")
                            for code in ("stocktake.create", "stocktake.post", "stocktake.cancel")])
            db.execute("PRAGMA user_version = 6")
        if version < 7:
            # 销售订单与出库明细独立存储；确认出库时才消耗库存和订单剩余量。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE customers (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            db.execute("""CREATE TABLE sales_orders (
                id INTEGER PRIMARY KEY,
                customer_id INTEGER NOT NULL REFERENCES customers(id),
                reference TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN
                    ('draft', 'confirmed', 'partially_shipped', 'shipped', 'cancelled')),
                created_by INTEGER NOT NULL REFERENCES users(id),
                confirmed_by INTEGER REFERENCES users(id),
                cancelled_by INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                confirmed_at TEXT,
                cancelled_at TEXT
            )""")
            db.execute("""CREATE TABLE sales_order_lines (
                id INTEGER PRIMARY KEY,
                sales_order_id INTEGER NOT NULL REFERENCES sales_orders(id),
                material_id INTEGER NOT NULL REFERENCES materials(id),
                quantity TEXT NOT NULL,
                unit_price TEXT NOT NULL,
                UNIQUE (sales_order_id, material_id)
            )""")
            db.execute("""CREATE TABLE shipments (
                id INTEGER PRIMARY KEY,
                sales_order_id INTEGER NOT NULL REFERENCES sales_orders(id),
                warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
                reference TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'posted', 'cancelled')),
                created_by INTEGER NOT NULL REFERENCES users(id),
                posted_by INTEGER REFERENCES users(id),
                cancelled_by INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                posted_at TEXT,
                cancelled_at TEXT
            )""")
            db.execute("""CREATE TABLE shipment_lines (
                id INTEGER PRIMARY KEY,
                shipment_id INTEGER NOT NULL REFERENCES shipments(id),
                sales_order_line_id INTEGER NOT NULL REFERENCES sales_order_lines(id),
                quantity TEXT NOT NULL,
                UNIQUE (shipment_id, sales_order_line_id)
            )""")
            db.execute("CREATE INDEX shipment_lines_order_line ON shipment_lines(sales_order_line_id)")
            db.execute("INSERT INTO roles(code, label, is_builtin) VALUES ('seller', '销售员', 1)")
            db.executemany("INSERT INTO permissions(code) VALUES (?)", [(code,) for code in (
                "sales.view", "customer.manage", "sales_order.create", "sales_order.confirm",
                "sales_order.cancel", "shipment.create", "shipment.post", "shipment.cancel")])
            grants = {"admin": ("sales.view", "customer.manage", "sales_order.create",
                                 "sales_order.confirm", "sales_order.cancel", "shipment.create", "shipment.post",
                                 "shipment.cancel"),
                      "seller": ("inventory.view", "sales.view", "customer.manage", "sales_order.create",
                                 "sales_order.confirm", "sales_order.cancel", "shipment.create", "shipment.cancel"),
                      "warehouse": ("sales.view", "shipment.create", "shipment.post", "shipment.cancel")}
            db.executemany("INSERT INTO role_permissions(role_code, permission_code) VALUES (?, ?)",
                           [(role, permission) for role, permissions in grants.items()
                            for permission in permissions])
            db.execute("PRAGMA user_version = 7")
        if version < 8:
            # 退货单关联原出库明细；保留原负库存流水，确认退货时另记正向流水。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE sales_returns (
                id INTEGER PRIMARY KEY,
                shipment_id INTEGER NOT NULL REFERENCES shipments(id),
                warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
                reason TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'posted', 'cancelled')),
                created_by INTEGER NOT NULL REFERENCES users(id),
                posted_by INTEGER REFERENCES users(id),
                cancelled_by INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                posted_at TEXT,
                cancelled_at TEXT
            )""")
            db.execute("""CREATE TABLE sales_return_lines (
                id INTEGER PRIMARY KEY,
                sales_return_id INTEGER NOT NULL REFERENCES sales_returns(id),
                shipment_line_id INTEGER NOT NULL REFERENCES shipment_lines(id),
                quantity TEXT NOT NULL,
                UNIQUE (sales_return_id, shipment_line_id)
            )""")
            db.execute("CREATE INDEX sales_return_lines_shipment ON sales_return_lines(shipment_line_id)")
            db.executemany("INSERT INTO permissions(code) VALUES (?)", [(code,) for code in (
                "sales_return.create", "sales_return.post", "sales_return.cancel")])
            grants = {"admin": ("sales_return.create", "sales_return.post", "sales_return.cancel"),
                      "seller": ("sales_return.create", "sales_return.cancel"),
                      "warehouse": ("sales_return.create", "sales_return.post", "sales_return.cancel")}
            db.executemany("INSERT INTO role_permissions(role_code, permission_code) VALUES (?, ?)",
                           [(role, permission) for role, permissions in grants.items()
                            for permission in permissions])
            db.execute("PRAGMA user_version = 8")
        if version < 9:
            # 采购退货只关联已确认入库明细，原入库与正向流水始终保留。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE purchase_returns (
                id INTEGER PRIMARY KEY,
                receipt_id INTEGER NOT NULL REFERENCES receipts(id),
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'posted', 'cancelled')),
                created_by INTEGER NOT NULL REFERENCES users(id),
                posted_by INTEGER REFERENCES users(id),
                cancelled_by INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                posted_at TEXT,
                cancelled_at TEXT
            )""")
            db.execute("""CREATE TABLE purchase_return_lines (
                id INTEGER PRIMARY KEY,
                purchase_return_id INTEGER NOT NULL REFERENCES purchase_returns(id),
                receipt_line_id INTEGER NOT NULL REFERENCES receipt_lines(id),
                quantity TEXT NOT NULL,
                UNIQUE (purchase_return_id, receipt_line_id)
            )""")
            db.execute("CREATE INDEX purchase_return_lines_receipt ON purchase_return_lines(receipt_line_id)")
            db.executemany("INSERT INTO permissions(code) VALUES (?)", [(code,) for code in (
                "purchase_return.create", "purchase_return.post", "purchase_return.cancel")])
            grants = {"admin": ("purchase_return.create", "purchase_return.post", "purchase_return.cancel"),
                      "buyer": ("purchase_return.create", "purchase_return.cancel"),
                      "warehouse": ("purchase_return.create", "purchase_return.post", "purchase_return.cancel")}
            db.executemany("INSERT INTO role_permissions(role_code, permission_code) VALUES (?, ?)",
                           [(role, permission) for role, permissions in grants.items()
                            for permission in permissions])
            db.execute("PRAGMA user_version = 9")
        if version < 10:
            # 金额查询单独授权；历史已确认单据无需改写即可纳入应收应付清单。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO roles(code, label, is_builtin) VALUES ('finance', '财务员', 1)")
            db.execute("INSERT INTO permissions(code) VALUES ('finance.view')")
            db.executemany("INSERT INTO role_permissions(role_code, permission_code) VALUES (?, ?)",
                           [(role, "finance.view") for role in ("admin", "finance")])
            db.execute("PRAGMA user_version = 10")
        if version < 11:
            # 收付款只追加记录；冲销另记反向行，不能删除或改写原付款。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE payment_records (
                id INTEGER PRIMARY KEY,
                kind TEXT NOT NULL CHECK (kind IN ('receivable', 'payable')),
                order_id INTEGER NOT NULL,
                action TEXT NOT NULL CHECK (action IN ('settlement', 'refund', 'reversal')),
                amount TEXT NOT NULL,
                reference TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                reverses_id INTEGER UNIQUE REFERENCES payment_records(id),
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            db.execute("""CREATE UNIQUE INDEX payment_records_reference
                ON payment_records(kind, order_id, action, reference) WHERE action <> 'reversal'""")
            db.executemany("INSERT INTO permissions(code) VALUES (?)", [(code,) for code in (
                "finance.record", "finance.reverse")])
            db.executemany("INSERT INTO role_permissions(role_code, permission_code) VALUES (?, ?)",
                           [(role, permission) for role in ("admin", "finance")
                            for permission in ("finance.record", "finance.reverse")])
            db.execute("PRAGMA user_version = 11")
        if version < 12:
            # 每个成品保留 BOM 历史版本，同一时刻只允许一个版本启用。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE boms (
                id INTEGER PRIMARY KEY,
                product_material_id INTEGER NOT NULL REFERENCES materials(id),
                version INTEGER NOT NULL,
                base_quantity TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'retired', 'cancelled')),
                created_by INTEGER NOT NULL REFERENCES users(id),
                activated_by INTEGER REFERENCES users(id),
                retired_by INTEGER REFERENCES users(id),
                cancelled_by INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                activated_at TEXT,
                retired_at TEXT,
                cancelled_at TEXT,
                UNIQUE (product_material_id, version)
            )""")
            db.execute("""CREATE UNIQUE INDEX boms_one_active_product
                ON boms(product_material_id) WHERE status = 'active'""")
            db.execute("""CREATE TABLE bom_lines (
                id INTEGER PRIMARY KEY,
                bom_id INTEGER NOT NULL REFERENCES boms(id),
                component_material_id INTEGER NOT NULL REFERENCES materials(id),
                quantity TEXT NOT NULL,
                UNIQUE (bom_id, component_material_id)
            )""")
            db.execute("INSERT INTO roles(code, label, is_builtin) VALUES ('planner', '生产计划员', 1)")
            db.executemany("INSERT INTO permissions(code) VALUES (?)", [(code,) for code in (
                "production.view", "bom.create", "bom.activate", "bom.retire", "bom.cancel")])
            grants = {"admin": ("production.view", "bom.create", "bom.activate", "bom.retire", "bom.cancel"),
                      "planner": ("inventory.view", "production.view", "bom.create", "bom.activate",
                                  "bom.retire", "bom.cancel"),
                      "warehouse": ("production.view",)}
            db.executemany("INSERT INTO role_permissions(role_code, permission_code) VALUES (?, ?)",
                           [(role, permission) for role, permissions in grants.items()
                            for permission in permissions])
            db.execute("PRAGMA user_version = 12")
        if version < 13:
            # 工单固定引用 BOM 版本并快照需料数量；后续版本切换不影响旧工单。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE work_orders (
                id INTEGER PRIMARY KEY,
                bom_id INTEGER NOT NULL REFERENCES boms(id),
                warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
                target_quantity TEXT NOT NULL,
                reference TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN
                    ('draft', 'released', 'in_progress', 'completed', 'cancelled')),
                created_by INTEGER NOT NULL REFERENCES users(id),
                released_by INTEGER REFERENCES users(id),
                cancelled_by INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                released_at TEXT,
                cancelled_at TEXT
            )""")
            db.execute("""CREATE TABLE work_order_lines (
                id INTEGER PRIMARY KEY,
                work_order_id INTEGER NOT NULL REFERENCES work_orders(id),
                component_material_id INTEGER NOT NULL REFERENCES materials(id),
                required_quantity TEXT NOT NULL,
                UNIQUE (work_order_id, component_material_id)
            )""")
            db.execute("CREATE INDEX work_orders_bom ON work_orders(bom_id)")
            db.executemany("INSERT INTO permissions(code) VALUES (?)", [(code,) for code in (
                "work_order.create", "work_order.release", "work_order.cancel")])
            db.executemany("INSERT INTO role_permissions(role_code, permission_code) VALUES (?, ?)",
                           [(role, permission) for role in ("admin", "planner")
                            for permission in ("work_order.create", "work_order.release", "work_order.cancel")])
            db.execute("PRAGMA user_version = 13")
        if version < 14:
            # 每次领料保留独立草稿和确认记录，库存流水以领料明细为不可变来源。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE material_issues (
                id INTEGER PRIMARY KEY,
                work_order_id INTEGER NOT NULL REFERENCES work_orders(id),
                warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
                reference TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'posted', 'cancelled')),
                created_by INTEGER NOT NULL REFERENCES users(id),
                posted_by INTEGER REFERENCES users(id),
                cancelled_by INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                posted_at TEXT,
                cancelled_at TEXT
            )""")
            db.execute("""CREATE TABLE material_issue_lines (
                id INTEGER PRIMARY KEY,
                material_issue_id INTEGER NOT NULL REFERENCES material_issues(id),
                work_order_line_id INTEGER NOT NULL REFERENCES work_order_lines(id),
                quantity TEXT NOT NULL,
                UNIQUE (material_issue_id, work_order_line_id)
            )""")
            db.execute("CREATE INDEX material_issues_order ON material_issues(work_order_id)")
            db.execute("CREATE INDEX material_issue_lines_order_line ON material_issue_lines(work_order_line_id)")
            db.executemany("INSERT INTO permissions(code) VALUES (?)", [(code,) for code in (
                "material_issue.create", "material_issue.post", "material_issue.cancel")])
            grants = {"admin": ("material_issue.create", "material_issue.post", "material_issue.cancel"),
                      "planner": ("material_issue.create", "material_issue.cancel"),
                      "warehouse": ("material_issue.create", "material_issue.post", "material_issue.cancel")}
            db.executemany("INSERT INTO role_permissions(role_code, permission_code) VALUES (?, ?)",
                           [(role, permission) for role, permissions in grants.items()
                            for permission in permissions])
            db.execute("PRAGMA user_version = 14")
        if version < 15:
            # 退料单独留痕并关联原领料明细，避免覆盖已经发生的扣料流水。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE material_returns (
                id INTEGER PRIMARY KEY,
                material_issue_id INTEGER NOT NULL REFERENCES material_issues(id),
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'posted', 'cancelled')),
                created_by INTEGER NOT NULL REFERENCES users(id),
                posted_by INTEGER REFERENCES users(id),
                cancelled_by INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                posted_at TEXT,
                cancelled_at TEXT
            )""")
            db.execute("""CREATE TABLE material_return_lines (
                id INTEGER PRIMARY KEY,
                material_return_id INTEGER NOT NULL REFERENCES material_returns(id),
                material_issue_line_id INTEGER NOT NULL REFERENCES material_issue_lines(id),
                quantity TEXT NOT NULL,
                UNIQUE (material_return_id, material_issue_line_id)
            )""")
            db.execute("CREATE INDEX material_returns_issue ON material_returns(material_issue_id)")
            db.execute("CREATE INDEX material_return_lines_issue_line ON material_return_lines(material_issue_line_id)")
            db.executemany("INSERT INTO permissions(code) VALUES (?)", [(code,) for code in (
                "material_return.create", "material_return.post", "material_return.cancel")])
            grants = {"admin": ("material_return.create", "material_return.post", "material_return.cancel"),
                      "planner": ("material_return.create", "material_return.cancel"),
                      "warehouse": ("material_return.create", "material_return.post", "material_return.cancel")}
            db.executemany("INSERT INTO role_permissions(role_code, permission_code) VALUES (?, ?)",
                           [(role, permission) for role, permissions in grants.items()
                            for permission in permissions])
            db.execute("PRAGMA user_version = 15")
        if version < 16:
            # 完工报工与质检结果独立留痕，只有确认后的合格数进入成品库存。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("ALTER TABLE work_orders ADD COLUMN completed_by INTEGER REFERENCES users(id)")
            db.execute("ALTER TABLE work_orders ADD COLUMN completed_at TEXT")
            db.execute("""CREATE TABLE production_completions (
                id INTEGER PRIMARY KEY,
                work_order_id INTEGER NOT NULL REFERENCES work_orders(id),
                reported_quantity TEXT NOT NULL,
                accepted_quantity TEXT,
                rejected_quantity TEXT,
                reference TEXT NOT NULL DEFAULT '',
                qc_note TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'inspected', 'posted', 'cancelled')),
                created_by INTEGER NOT NULL REFERENCES users(id),
                inspected_by INTEGER REFERENCES users(id),
                posted_by INTEGER REFERENCES users(id),
                cancelled_by INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                inspected_at TEXT,
                posted_at TEXT,
                cancelled_at TEXT
            )""")
            db.execute("CREATE INDEX production_completions_order ON production_completions(work_order_id)")
            db.executemany("INSERT INTO permissions(code) VALUES (?)", [(code,) for code in (
                "production_completion.create", "production_completion.inspect",
                "production_completion.post", "production_completion.cancel")])
            grants = {"admin": ("production_completion.create", "production_completion.inspect",
                                "production_completion.post", "production_completion.cancel"),
                      "planner": ("production_completion.create", "production_completion.cancel"),
                      "warehouse": ("production_completion.inspect", "production_completion.post")}
            db.executemany("INSERT INTO role_permissions(role_code, permission_code) VALUES (?, ?)",
                           [(role, permission) for role, permissions in grants.items()
                            for permission in permissions])
            db.execute("PRAGMA user_version = 16")
        if version < 17:
            # 冲销单独留痕，原报工和质检事实保持不变；一张完工单最多冲销一次。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE production_completion_reversals (
                id INTEGER PRIMARY KEY,
                production_completion_id INTEGER NOT NULL UNIQUE REFERENCES production_completions(id),
                reason TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            db.execute("INSERT INTO permissions(code) VALUES ('production_completion.reverse')")
            db.execute("""INSERT INTO role_permissions(role_code, permission_code)
                VALUES ('admin', 'production_completion.reverse')""")
            db.execute("PRAGMA user_version = 17")
        if version < 18:
            # 生产核价和人工、制造费用只追加记录；更正通过独立冲销保留原金额。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE production_cost_entries (
                id INTEGER PRIMARY KEY,
                work_order_id INTEGER NOT NULL REFERENCES work_orders(id),
                kind TEXT NOT NULL CHECK (kind IN ('material', 'labor', 'overhead')),
                material_issue_line_id INTEGER REFERENCES material_issue_lines(id),
                unit_cost TEXT,
                amount TEXT,
                reference TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            db.execute("CREATE INDEX production_cost_entries_order ON production_cost_entries(work_order_id)")
            db.execute("""CREATE TABLE production_cost_reversals (
                id INTEGER PRIMARY KEY,
                entry_id INTEGER NOT NULL UNIQUE REFERENCES production_cost_entries(id),
                reason TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            db.executemany("INSERT INTO permissions(code) VALUES (?)", [(code,) for code in (
                "production_cost.view", "production_cost.record", "production_cost.reverse")])
            grants = {"admin": ("production_cost.view", "production_cost.record", "production_cost.reverse"),
                      "finance": ("production_cost.view", "production_cost.record", "production_cost.reverse"),
                      "planner": ("production_cost.view",)}
            db.executemany("INSERT INTO role_permissions(role_code, permission_code) VALUES (?, ?)",
                           [(role, permission) for role, permissions in grants.items()
                            for permission in permissions])
            db.execute("PRAGMA user_version = 18")
        if version < 19:
            # 盘点冲销单独留痕并限制一单一次，原实盘快照和差异流水不得改写。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE stocktake_reversals (
                id INTEGER PRIMARY KEY,
                stocktake_id INTEGER NOT NULL UNIQUE REFERENCES stocktakes(id),
                reason TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            db.execute("INSERT INTO permissions(code) VALUES ('stocktake.reverse')")
            db.execute("""INSERT INTO role_permissions(role_code, permission_code)
                VALUES ('admin', 'stocktake.reverse')""")
            db.execute("PRAGMA user_version = 19")
        if version < 20:
            # 调拨冲销保留原双向流水，唯一约束阻止同一调拨单被重复退回。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE transfer_reversals (
                id INTEGER PRIMARY KEY,
                transfer_id INTEGER NOT NULL UNIQUE REFERENCES transfers(id),
                reason TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            db.execute("INSERT INTO permissions(code) VALUES ('transfer.reverse')")
            db.execute("""INSERT INTO role_permissions(role_code, permission_code)
                VALUES ('admin', 'transfer.reverse')""")
            db.execute("PRAGMA user_version = 20")
        if version < 21:
            # 已确认销售退货通过唯一冲销单追溯纠错，保留原退货与原应收来源。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE sales_return_reversals (
                id INTEGER PRIMARY KEY,
                sales_return_id INTEGER NOT NULL UNIQUE REFERENCES sales_returns(id),
                reason TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            db.execute("INSERT INTO permissions(code) VALUES ('sales_return.reverse')")
            db.execute("""INSERT INTO role_permissions(role_code, permission_code)
                VALUES ('admin', 'sales_return.reverse')""")
            db.execute("PRAGMA user_version = 21")
        if version < 22:
            # 已确认采购退货通过唯一冲销单恢复净收货，原应付来源继续保留。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE purchase_return_reversals (
                id INTEGER PRIMARY KEY,
                purchase_return_id INTEGER NOT NULL UNIQUE REFERENCES purchase_returns(id),
                reason TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            db.execute("INSERT INTO permissions(code) VALUES ('purchase_return.reverse')")
            db.execute("""INSERT INTO role_permissions(role_code, permission_code)
                VALUES ('admin', 'purchase_return.reverse')""")
            db.execute("PRAGMA user_version = 22")
        if version < 23:
            # 入库冲销保留已确认原单和流水，唯一关联保证来源可审计。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE receipt_reversals (
                id INTEGER PRIMARY KEY,
                receipt_id INTEGER NOT NULL UNIQUE REFERENCES receipts(id),
                reason TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            db.execute("INSERT INTO permissions(code) VALUES ('receipt.reverse')")
            db.execute("""INSERT INTO role_permissions(role_code, permission_code)
                VALUES ('admin', 'receipt.reverse')""")
            db.execute("PRAGMA user_version = 23")
        if version < 24:
            # 出库冲销与原出库一对一，保留已确认单据及其应收、库存流水。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE shipment_reversals (
                id INTEGER PRIMARY KEY,
                shipment_id INTEGER NOT NULL UNIQUE REFERENCES shipments(id),
                reason TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            db.execute("INSERT INTO permissions(code) VALUES ('shipment.reverse')")
            db.execute("""INSERT INTO role_permissions(role_code, permission_code)
                VALUES ('admin', 'shipment.reverse')""")
            db.execute("PRAGMA user_version = 24")
        if version < 25:
            # 先给旧权限补齐名称，再强制后续权限登记携带名称；授权关系仍引用稳定代码。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("ALTER TABLE permissions ADD COLUMN label TEXT NOT NULL DEFAULT ''")
            db.executemany("UPDATE permissions SET label = ? WHERE code = ?",
                           [(label, code) for code, label in DEFAULT_PERMISSION_LABELS.items()])
            db.execute("UPDATE permissions SET label = '未命名权限' WHERE label = ''")
            db.execute("""CREATE TRIGGER permissions_label_required_insert
                          BEFORE INSERT ON permissions WHEN TRIM(NEW.label) = ''
                          BEGIN SELECT RAISE(ABORT, '权限名称不能为空'); END""")
            db.execute("""CREATE TRIGGER permissions_label_required_update
                          BEFORE UPDATE OF label ON permissions WHEN TRIM(NEW.label) = ''
                          BEGIN SELECT RAISE(ABORT, '权限名称不能为空'); END""")
            db.execute("PRAGMA user_version = 25")
        if version < 26:
            # 旧版已存入权限代码或通用占位名时补齐中文；保留管理员自行修改的名称。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.executemany(
                """UPDATE permissions SET label = ?
                   WHERE code = ? AND (label = code OR label = '未命名权限')""",
                [(label, code) for code, label in DEFAULT_PERMISSION_LABELS.items()],
            )
            db.execute("PRAGMA user_version = 26")
        if version < 27:
            # 模块、单据及操作的归属一次性落库；之后接口直接读取数据库，允许名称独立调整。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE permission_groups (
                code TEXT PRIMARY KEY,
                label TEXT NOT NULL CHECK (TRIM(label) <> ''),
                parent_code TEXT REFERENCES permission_groups(code),
                sort_order INTEGER NOT NULL
            )""")
            groups = list(dict.fromkeys(PERMISSION_GROUP_PATHS.values()))
            for sort_order, (module, _) in enumerate(groups):
                db.execute("""INSERT OR IGNORE INTO permission_groups(code, label, parent_code, sort_order)
                              VALUES (?, ?, NULL, ?)""", (*module, sort_order))
            db.execute("""INSERT INTO permission_groups(code, label, parent_code, sort_order)
                          VALUES ('other', '其他权限', NULL, 999)""")
            for sort_order, (module, document) in enumerate(groups):
                # 单据代码包含模块前缀，避免不同模块出现同名节点时互相覆盖。
                db.execute("""INSERT INTO permission_groups(code, label, parent_code, sort_order)
                              VALUES (?, ?, ?, ?)""",
                           (f"{module[0]}.{document[0]}", document[1], module[0], sort_order))
            db.execute("""INSERT INTO permission_groups(code, label, parent_code, sort_order)
                          VALUES ('other.unclassified', '待分类权限', 'other', 999)""")
            db.execute("ALTER TABLE permissions ADD COLUMN group_code TEXT REFERENCES permission_groups(code)")
            for prefix, (module, document) in PERMISSION_GROUP_PATHS.items():
                db.execute("""UPDATE permissions SET group_code = ?
                              WHERE SUBSTR(code, 1, ?) = ?""",
                           (f"{module[0]}.{document[0]}", len(prefix) + 1, f"{prefix}."))
            db.execute("""UPDATE permissions SET group_code = 'other.unclassified'
                          WHERE group_code IS NULL""")
            db.execute("""CREATE TRIGGER permissions_group_required_insert
                          BEFORE INSERT ON permissions
                          WHEN NOT EXISTS (
                              SELECT 1 FROM permission_groups
                              WHERE code = NEW.group_code AND parent_code IS NOT NULL
                          )
                          BEGIN SELECT RAISE(ABORT, '权限所属单据无效'); END""")
            db.execute("""CREATE TRIGGER permissions_group_required_update
                          BEFORE UPDATE OF group_code ON permissions
                          WHEN NOT EXISTS (
                              SELECT 1 FROM permission_groups
                              WHERE code = NEW.group_code AND parent_code IS NOT NULL
                          )
                          BEGIN SELECT RAISE(ABORT, '权限所属单据无效'); END""")
            db.execute("PRAGMA user_version = 27")

        if version < 28:
            # 同一物料可由多家供应商供货，绑定关系不复制物料档案。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE supplier_materials (
                supplier_id INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
                material_id INTEGER NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
                PRIMARY KEY (supplier_id, material_id)
            )""")
            db.execute("CREATE INDEX supplier_materials_material ON supplier_materials(material_id)")
            db.execute("PRAGMA user_version = 28")

        if version < 29:
            # 申请与订单明细保持独立引用；旧订单不补造申请来源。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE purchase_requests (
                id INTEGER PRIMARY KEY,
                reference TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN
                    ('draft', 'submitted', 'approved', 'rejected', 'cancelled')),
                created_by INTEGER NOT NULL REFERENCES users(id),
                submitted_by INTEGER REFERENCES users(id),
                reviewed_by INTEGER REFERENCES users(id),
                cancelled_by INTEGER REFERENCES users(id),
                review_reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                submitted_at TEXT,
                reviewed_at TEXT,
                cancelled_at TEXT
            )""")
            db.execute("""CREATE TABLE purchase_request_lines (
                id INTEGER PRIMARY KEY,
                purchase_request_id INTEGER NOT NULL REFERENCES purchase_requests(id),
                material_id INTEGER NOT NULL REFERENCES materials(id),
                quantity TEXT NOT NULL,
                UNIQUE (purchase_request_id, material_id)
            )""")
            db.execute("""CREATE TABLE purchase_order_request_links (
                purchase_order_line_id INTEGER PRIMARY KEY REFERENCES purchase_order_lines(id),
                purchase_request_line_id INTEGER NOT NULL REFERENCES purchase_request_lines(id)
            )""")
            db.execute("CREATE INDEX purchase_order_request_links_request_line ON purchase_order_request_links(purchase_request_line_id)")
            request_permissions = (
                ("purchase_request.view", "查看采购申请"),
                ("purchase_request.create", "创建和修改采购申请"),
                ("purchase_request.submit", "提交采购申请"),
                ("purchase_request.review", "审批采购申请"),
                ("purchase_request.cancel", "取消采购申请"),
            )
            db.execute("""INSERT INTO permission_groups(code, label, parent_code, sort_order)
                VALUES ('purchase.purchase_request', '采购申请', 'purchase', 100)""")
            db.executemany("INSERT INTO permissions(code, label, group_code) VALUES (?, ?, 'purchase.purchase_request')",
                           request_permissions)
            db.executemany("INSERT INTO role_permissions(role_code, permission_code) VALUES (?, ?)",
                           [(role, code) for role in ("admin", "buyer", "warehouse")
                            for code in ("purchase_request.view", "purchase_request.create",
                                         "purchase_request.submit", "purchase_request.cancel")])
            db.execute("INSERT INTO role_permissions(role_code, permission_code) VALUES ('admin', 'purchase_request.review')")
            db.execute("PRAGMA user_version = 29")

        if version < 30:
            # 收货事实与入库确认分开保存；每张已确认收货最多生成一张待入库单。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE purchase_goods_receipts (
                id INTEGER PRIMARY KEY,
                purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id),
                warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
                inbound_receipt_id INTEGER UNIQUE REFERENCES receipts(id),
                reference TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'confirmed', 'cancelled')),
                created_by INTEGER NOT NULL REFERENCES users(id),
                confirmed_by INTEGER REFERENCES users(id),
                cancelled_by INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                confirmed_at TEXT,
                cancelled_at TEXT
            )""")
            db.execute("""CREATE TABLE purchase_goods_receipt_lines (
                id INTEGER PRIMARY KEY,
                goods_receipt_id INTEGER NOT NULL REFERENCES purchase_goods_receipts(id),
                purchase_order_line_id INTEGER NOT NULL REFERENCES purchase_order_lines(id),
                accepted_quantity TEXT NOT NULL,
                rejected_quantity TEXT NOT NULL,
                rejection_reason TEXT NOT NULL DEFAULT '',
                UNIQUE (goods_receipt_id, purchase_order_line_id)
            )""")
            db.execute("CREATE INDEX purchase_goods_receipt_lines_order ON purchase_goods_receipt_lines(purchase_order_line_id)")
            db.execute("""INSERT INTO permission_groups(code, label, parent_code, sort_order)
                VALUES ('purchase.receiving', '采购收货', 'purchase', 110)""")
            receiving_permissions = (
                ("purchase_receiving.view", "查看采购收货"),
                ("purchase_receiving.create", "创建采购收货单"),
                ("purchase_receiving.confirm", "确认采购收货"),
                ("purchase_receiving.cancel", "取消采购收货草稿"),
            )
            db.executemany("INSERT INTO permissions(code, label, group_code) VALUES (?, ?, 'purchase.receiving')",
                           receiving_permissions)
            db.executemany("INSERT INTO role_permissions(role_code, permission_code) VALUES (?, ?)",
                           [(role, code) for role in ("admin", "buyer", "warehouse")
                            for code in ("purchase_receiving.view", "purchase_receiving.create",
                                         "purchase_receiving.cancel")])
            db.executemany("INSERT INTO role_permissions(role_code, permission_code) VALUES (?, ?)",
                           [(role, "purchase_receiving.confirm") for role in ("admin", "warehouse")])
            db.execute("PRAGMA user_version = 30")

        if version < 31:
            # 非采购入库独立记账，避免无单价来源被误列为采购应付。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE warehouse_inbounds (
                id INTEGER PRIMARY KEY,
                warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
                reason TEXT NOT NULL CHECK (reason IN ('opening', 'gift', 'other')),
                note TEXT NOT NULL,
                reference TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'posted', 'cancelled')),
                created_by INTEGER NOT NULL REFERENCES users(id),
                posted_by INTEGER REFERENCES users(id),
                cancelled_by INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                posted_at TEXT,
                cancelled_at TEXT
            )""")
            db.execute("""CREATE TABLE warehouse_inbound_lines (
                id INTEGER PRIMARY KEY,
                inbound_id INTEGER NOT NULL REFERENCES warehouse_inbounds(id),
                material_id INTEGER NOT NULL REFERENCES materials(id),
                quantity TEXT NOT NULL,
                UNIQUE (inbound_id, material_id)
            )""")
            db.execute("""CREATE TABLE warehouse_inbound_reversals (
                id INTEGER PRIMARY KEY,
                inbound_id INTEGER NOT NULL UNIQUE REFERENCES warehouse_inbounds(id),
                reason TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            db.execute("""INSERT INTO permission_groups(code, label, parent_code, sort_order)
                VALUES ('warehouse.other_inbound', '其他入库', 'warehouse', 120)""")
            inbound_permissions = (
                ("other_inbound.view", "查看其他入库"),
                ("other_inbound.create", "创建其他入库单"),
                ("other_inbound.post", "确认其他入库"),
                ("other_inbound.cancel", "取消其他入库草稿"),
                ("other_inbound.reverse", "冲销其他入库"),
            )
            db.executemany("INSERT INTO permissions(code, label, group_code) VALUES (?, ?, 'warehouse.other_inbound')",
                           inbound_permissions)
            db.executemany("INSERT INTO role_permissions(role_code, permission_code) VALUES (?, ?)",
                           [(role, code) for role in ("admin", "warehouse")
                            for code in ("other_inbound.view", "other_inbound.create",
                                         "other_inbound.post", "other_inbound.cancel")])
            db.executemany("INSERT INTO role_permissions(role_code, permission_code) VALUES (?, ?)",
                           [("admin", "other_inbound.reverse")])
            db.execute("PRAGMA user_version = 31")

        if version < 32:
            # 仓库出库单先承载其他出库；后续采购退货可关联同一单据类型。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE warehouse_outbounds (
                id INTEGER PRIMARY KEY,
                warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
                source_kind TEXT NOT NULL DEFAULT 'other' CHECK (source_kind IN ('other', 'purchase_return')),
                reason TEXT NOT NULL,
                note TEXT NOT NULL,
                reference TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'posted', 'cancelled')),
                created_by INTEGER NOT NULL REFERENCES users(id),
                posted_by INTEGER REFERENCES users(id),
                cancelled_by INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                posted_at TEXT,
                cancelled_at TEXT
            )""")
            db.execute("""CREATE TABLE warehouse_outbound_lines (
                id INTEGER PRIMARY KEY,
                outbound_id INTEGER NOT NULL REFERENCES warehouse_outbounds(id),
                material_id INTEGER NOT NULL REFERENCES materials(id),
                quantity TEXT NOT NULL,
                UNIQUE (outbound_id, material_id)
            )""")
            db.execute("""CREATE TABLE warehouse_outbound_reversals (
                id INTEGER PRIMARY KEY,
                outbound_id INTEGER NOT NULL UNIQUE REFERENCES warehouse_outbounds(id),
                reason TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            db.execute("""INSERT INTO permission_groups(code, label, parent_code, sort_order)
                VALUES ('warehouse.other_outbound', '其他出库', 'warehouse', 130)""")
            outbound_permissions = (
                ("other_outbound.view", "查看仓库出库"),
                ("other_outbound.create", "创建其他出库单"),
                ("other_outbound.post", "确认仓库出库"),
                ("other_outbound.cancel", "取消出库草稿"),
                ("other_outbound.reverse", "冲销其他出库"),
            )
            db.executemany("INSERT INTO permissions(code, label, group_code) VALUES (?, ?, 'warehouse.other_outbound')",
                           outbound_permissions)
            db.executemany("INSERT INTO role_permissions(role_code, permission_code) VALUES (?, ?)",
                           [(role, code) for role in ("admin", "warehouse")
                            for code in ("other_outbound.view", "other_outbound.create",
                                         "other_outbound.post", "other_outbound.cancel")])
            db.execute("INSERT INTO role_permissions(role_code, permission_code) VALUES ('admin', 'other_outbound.reverse')")
            db.execute("PRAGMA user_version = 32")

        if version < 33:
            # 旧退货保留历史流水；仅为已确认的旧单据补关联出库单，不重放库存。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("ALTER TABLE warehouse_outbounds ADD COLUMN purchase_return_id INTEGER REFERENCES purchase_returns(id)")
            db.execute("CREATE UNIQUE INDEX warehouse_outbound_return_unique ON warehouse_outbounds(purchase_return_id)")
            if db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'purchase_returns'").fetchone():
                legacy_returns = db.execute("""SELECT pr.id, pr.reason, pr.created_by, pr.posted_by,
                pr.created_at, pr.posted_at, rw.warehouse_id FROM purchase_returns pr
                JOIN receipt_warehouses rw ON rw.receipt_id = pr.receipt_id
                WHERE pr.status = 'posted'""").fetchall()
            else:
                legacy_returns = []
            for item in legacy_returns:
                outbound_id = db.execute("""INSERT INTO warehouse_outbounds(warehouse_id, source_kind,
                    reason, note, reference, status, created_by, posted_by, created_at, posted_at,
                    purchase_return_id) VALUES (?, 'purchase_return', 'purchase_return', ?, ?,
                    'posted', ?, ?, ?, ?, ?)""",
                    (item['warehouse_id'], item['reason'], f"采购退货 #{item['id']}",
                     item['created_by'], item['posted_by'], item['created_at'], item['posted_at'], item['id'])).lastrowid
                db.execute("""INSERT INTO warehouse_outbound_lines(outbound_id, material_id, quantity)
                    SELECT ?, rl.material_id, prl.quantity FROM purchase_return_lines prl
                    JOIN receipt_lines rl ON rl.id = prl.receipt_line_id
                    WHERE prl.purchase_return_id = ?""", (outbound_id, item['id']))
            db.execute("""INSERT INTO permissions(code, label, group_code)
                VALUES ('purchase_return.submit', '提交采购退货待仓库出库', 'purchase.purchase_return')""")
            db.execute("""INSERT INTO role_permissions(role_code, permission_code)
                SELECT role_code, 'purchase_return.submit' FROM role_permissions
                WHERE permission_code = 'purchase_return.create'""")
            db.execute("PRAGMA user_version = 33")

        if version < 34:
            # 调整单与盘点分离，只有异人审批后的仓库确认才能产生库存流水。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE stock_adjustments (
                id INTEGER PRIMARY KEY,
                warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
                reason TEXT NOT NULL,
                reference TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN
                    ('draft', 'submitted', 'approved', 'rejected', 'cancelled', 'posted')),
                created_by INTEGER NOT NULL REFERENCES users(id),
                submitted_by INTEGER REFERENCES users(id),
                reviewed_by INTEGER REFERENCES users(id),
                posted_by INTEGER REFERENCES users(id),
                cancelled_by INTEGER REFERENCES users(id),
                review_reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                submitted_at TEXT, reviewed_at TEXT, posted_at TEXT, cancelled_at TEXT
            )""")
            db.execute("""CREATE TABLE stock_adjustment_lines (
                id INTEGER PRIMARY KEY,
                adjustment_id INTEGER NOT NULL REFERENCES stock_adjustments(id),
                material_id INTEGER NOT NULL REFERENCES materials(id),
                quantity TEXT NOT NULL,
                UNIQUE (adjustment_id, material_id)
            )""")
            db.execute("""CREATE TABLE stock_adjustment_reversals (
                id INTEGER PRIMARY KEY,
                adjustment_id INTEGER NOT NULL UNIQUE REFERENCES stock_adjustments(id),
                reason TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            db.execute("""INSERT INTO permission_groups(code, label, parent_code, sort_order)
                VALUES ('warehouse.adjustment', '库存调整', 'warehouse', 140)""")
            adjustment_permissions = (
                ('adjustment.view', '查看库存调整'),
                ('adjustment.create', '创建库存调整'),
                ('adjustment.submit', '提交库存调整'),
                ('adjustment.review', '审批库存调整'),
                ('adjustment.cancel', '取消库存调整'),
                ('adjustment.post', '确认库存调整'),
                ('adjustment.reverse', '冲销库存调整'),
            )
            db.executemany("INSERT INTO permissions(code, label, group_code) VALUES (?, ?, 'warehouse.adjustment')",
                           adjustment_permissions)
            db.executemany("INSERT INTO role_permissions(role_code, permission_code) VALUES (?, ?)",
                           [(role, code) for role in ('admin', 'warehouse')
                            for code in ('adjustment.view', 'adjustment.create', 'adjustment.submit',
                                         'adjustment.review', 'adjustment.cancel', 'adjustment.post')])
            db.execute("INSERT INTO role_permissions(role_code, permission_code) VALUES ('admin', 'adjustment.reverse')")
            db.execute("PRAGMA user_version = 34")

        if version < 35:
            # 采购与库存报表分别授权，避免采购岗位自动获得所有库存统计权限。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""INSERT INTO permission_groups(code, label, parent_code, sort_order)
                VALUES ('purchase.reports', '采购报表', 'purchase', 150)""")
            db.execute("""INSERT INTO permission_groups(code, label, parent_code, sort_order)
                VALUES ('warehouse.reports', '库存报表', 'warehouse', 150)""")
            db.execute("""INSERT INTO permissions(code, label, group_code)
                VALUES ('purchase_report.view', '查看采购报表', 'purchase.reports')""")
            db.execute("""INSERT INTO permissions(code, label, group_code)
                VALUES ('inventory_report.view', '查看库存报表', 'warehouse.reports')""")
            db.executemany("INSERT INTO role_permissions(role_code, permission_code) VALUES (?, ?)",
                           [(role, 'purchase_report.view') for role in ('admin', 'buyer')])
            db.executemany("INSERT INTO role_permissions(role_code, permission_code) VALUES (?, ?)",
                           [(role, 'inventory_report.view') for role in ('admin', 'warehouse')])
            db.execute("PRAGMA user_version = 35")

        if version < 36:
            # 核价修订只追加新记录；历史库存流水及原始单据保持不变。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE inventory_cost_inputs (
                id INTEGER PRIMARY KEY,
                movement_id INTEGER NOT NULL REFERENCES stock_movements(id),
                unit_cost TEXT NOT NULL,
                reference TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (movement_id, reference)
            )""")
            db.execute("CREATE INDEX inventory_cost_inputs_movement ON inventory_cost_inputs(movement_id, id)")
            db.execute("""INSERT INTO permission_groups(code, label, parent_code, sort_order)
                VALUES ('finance.inventory_valuation', '库存计价', 'finance', 160)""")
            db.executemany("""INSERT INTO permissions(code, label, group_code)
                VALUES (?, ?, 'finance.inventory_valuation')""", [
                ('inventory_valuation.view', '查看库存计价'),
                ('inventory_valuation.record', '登记库存核价')])
            db.executemany("INSERT INTO role_permissions(role_code, permission_code) VALUES (?, ?)",
                           [(role, code) for role in ('admin', 'finance')
                            for code in ('inventory_valuation.view', 'inventory_valuation.record')])
            db.execute("PRAGMA user_version = 36")


        if version < 37:
            # 为已有账号补空资料，不改变账号、密码和角色；工号仅在填写时要求唯一。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
            if columns:
                for column in ("full_name", "employee_no", "phone"):
                    if column not in columns:
                        db.execute(f"ALTER TABLE users ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
                db.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_employee_no ON users(employee_no COLLATE NOCASE) WHERE employee_no != ''")
            # 资料修改保存前后快照与操作者，便于追溯账号信息变更。
            db.execute("""CREATE TABLE IF NOT EXISTS user_profile_changes (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                changed_by INTEGER NOT NULL REFERENCES users(id),
                before_json TEXT NOT NULL,
                after_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            db.execute("PRAGMA user_version = 37")

        if version < 38:
            # 配置与变更记录独立于业务数据；恢复默认保留版本，防止旧客户端覆盖。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE menu_icons (
                key TEXT PRIMARY KEY, icon TEXT, version INTEGER NOT NULL
            )""")
            db.execute("""CREATE TABLE menu_icon_changes (
                id INTEGER PRIMARY KEY, menu_key TEXT NOT NULL,
                before_icon TEXT, after_icon TEXT,
                changed_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            db.execute("PRAGMA user_version = 38")

        if version < 39:
            # 结算保存不可变快照，冲销独立追加；写锁保护同一工单不被重复结算。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE production_cost_settlements (
                id INTEGER PRIMARY KEY,
                work_order_id INTEGER NOT NULL REFERENCES work_orders(id),
                reference TEXT NOT NULL, note TEXT NOT NULL,
                material_amount TEXT NOT NULL, labor_amount TEXT NOT NULL,
                overhead_amount TEXT NOT NULL, total_amount TEXT NOT NULL,
                accepted_quantity TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (work_order_id, reference)
            )""")
            db.execute("""CREATE TABLE production_settlement_reversals (
                id INTEGER PRIMARY KEY,
                settlement_id INTEGER NOT NULL UNIQUE REFERENCES production_cost_settlements(id),
                reason TEXT NOT NULL, created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            db.execute("""CREATE TABLE production_cost_allocations (
                settlement_id INTEGER NOT NULL REFERENCES production_cost_settlements(id),
                completion_id INTEGER NOT NULL REFERENCES production_completions(id),
                movement_id INTEGER NOT NULL REFERENCES stock_movements(id),
                quantity TEXT NOT NULL, amount TEXT NOT NULL,
                PRIMARY KEY (settlement_id, movement_id)
            )""")
            db.execute("""CREATE TABLE production_settlement_sources (
                settlement_id INTEGER NOT NULL REFERENCES production_cost_settlements(id),
                material_issue_line_id INTEGER NOT NULL REFERENCES material_issue_lines(id),
                movement_id INTEGER NOT NULL REFERENCES stock_movements(id),
                net_quantity TEXT NOT NULL, unit_cost TEXT NOT NULL, amount TEXT NOT NULL,
                cost_source TEXT NOT NULL, cost_entry_id INTEGER REFERENCES production_cost_entries(id),
                PRIMARY KEY (settlement_id, material_issue_line_id)
            )""")
            db.execute("""CREATE TABLE production_settlement_dependencies (
                settlement_id INTEGER NOT NULL REFERENCES production_cost_settlements(id),
                kind TEXT NOT NULL CHECK (kind IN ('input', 'settlement')), source_id INTEGER NOT NULL,
                PRIMARY KEY (settlement_id, kind, source_id)
            )""")
            db.execute("""CREATE TABLE production_settlement_charges (
                settlement_id INTEGER NOT NULL REFERENCES production_cost_settlements(id),
                entry_id INTEGER NOT NULL REFERENCES production_cost_entries(id),
                PRIMARY KEY (settlement_id, entry_id)
            )""")
            db.executemany("""INSERT INTO permissions(code, label, group_code)
                VALUES (?, ?, 'production.production_cost')""", [
                ('production_cost.settle', '结算完工成本'),
                ('production_cost.reopen', '冲销成本结算')])
            db.executemany("INSERT INTO role_permissions(role_code, permission_code) VALUES (?, ?)",
                           [(role, code) for role in ('admin', 'finance')
                            for code in ('production_cost.settle', 'production_cost.reopen')])
            db.execute("PRAGMA user_version = 39")

        if version < 40:
            # 总账基础资料独立于业务往来余额；不猜测旧业务的科目或会计期间。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE ledger_accounts (
                id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                category TEXT NOT NULL CHECK (category IN ('asset','liability','equity','income','expense','cost')),
                normal_balance TEXT NOT NULL CHECK (normal_balance IN ('debit','credit')),
                is_active INTEGER NOT NULL CHECK (is_active IN (0,1)),
                version INTEGER NOT NULL CHECK (version > 0),
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            db.execute("""CREATE TABLE accounting_periods (
                id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
                start_date TEXT NOT NULL, end_date TEXT NOT NULL CHECK (end_date >= start_date),
                status TEXT NOT NULL CHECK (status IN ('open','closed')),
                version INTEGER NOT NULL CHECK (version > 0),
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            for table, source, key in (
                ('ledger_account_changes', 'ledger_accounts', 'account_id'),
                ('accounting_period_changes', 'accounting_periods', 'period_id'),
            ):
                db.execute(f"""CREATE TABLE {table} (
                    id INTEGER PRIMARY KEY, {key} INTEGER NOT NULL REFERENCES {source}(id),
                    before_json TEXT, after_json TEXT NOT NULL, reason TEXT NOT NULL,
                    changed_by INTEGER NOT NULL REFERENCES users(id),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )""")
            groups = [('finance.ledger_accounts', '总账科目'), ('finance.accounting_periods', '会计期间')]
            db.executemany("INSERT INTO permission_groups(code, label, parent_code, sort_order) VALUES (?, ?, 'finance', ?)",
                           [(code, label, 50 + index) for index, (code, label) in enumerate(groups)])
            operations = [
                ('ledger_account.view', '查看总账科目', 'finance.ledger_accounts'),
                ('ledger_account.manage', '维护总账科目', 'finance.ledger_accounts'),
                ('accounting_period.view', '查看会计期间', 'finance.accounting_periods'),
                ('accounting_period.manage', '维护会计期间', 'finance.accounting_periods'),
            ]
            db.executemany("INSERT INTO permissions(code, label, group_code) VALUES (?, ?, ?)", operations)
            db.executemany("INSERT INTO role_permissions(role_code, permission_code) VALUES (?, ?)",
                           [(role, code) for role in ('admin', 'finance') for code, _, _ in operations])
            db.execute("PRAGMA user_version = 40")

        if version < 41:
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE journals (
                id INTEGER PRIMARY KEY, reference TEXT NOT NULL UNIQUE,
                journal_date TEXT NOT NULL, period_id INTEGER NOT NULL REFERENCES accounting_periods(id),
                note TEXT NOT NULL, currency TEXT NOT NULL DEFAULT 'CNY' CHECK(currency = 'CNY'),
                status TEXT NOT NULL CHECK(status IN ('draft','submitted','approved','rejected','posted','cancelled')),
                version INTEGER NOT NULL CHECK(version > 0),
                reversal_of_id INTEGER REFERENCES journals(id),
                created_by INTEGER NOT NULL REFERENCES users(id),
                submitted_by INTEGER REFERENCES users(id), reviewed_by INTEGER REFERENCES users(id),
                posted_by INTEGER REFERENCES users(id), cancelled_by INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                submitted_at TEXT, reviewed_at TEXT, posted_at TEXT, cancelled_at TEXT
            )""")
            db.execute("""CREATE UNIQUE INDEX journals_active_reversal ON journals(reversal_of_id)
                WHERE reversal_of_id IS NOT NULL AND status != 'cancelled'""")
            db.execute("""CREATE TABLE journal_lines (
                id INTEGER PRIMARY KEY, journal_id INTEGER NOT NULL REFERENCES journals(id),
                position INTEGER NOT NULL, account_id INTEGER NOT NULL REFERENCES ledger_accounts(id),
                account_code TEXT NOT NULL, account_name TEXT NOT NULL, category TEXT NOT NULL,
                normal_balance TEXT NOT NULL, summary TEXT NOT NULL, debit TEXT NOT NULL, credit TEXT NOT NULL,
                UNIQUE(journal_id, position)
            )""")
            db.execute("""CREATE TABLE journal_changes (
                id INTEGER PRIMARY KEY, journal_id INTEGER NOT NULL REFERENCES journals(id),
                action TEXT NOT NULL, before_json TEXT, after_json TEXT NOT NULL, reason TEXT NOT NULL,
                changed_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            db.execute("INSERT INTO permission_groups(code,label,parent_code,sort_order) VALUES ('finance.journals','总账凭证','finance',52)")
            operations = [('journal.view','查看总账凭证'), ('journal.create','建立和修改凭证'),
                ('journal.submit','提交凭证'), ('journal.review','审核凭证'), ('journal.post','过账凭证'),
                ('journal.cancel','取消未过账凭证'), ('journal.reverse','建立冲销凭证')]
            db.executemany("INSERT INTO permissions(code,label,group_code) VALUES (?,?,'finance.journals')", operations)
            db.executemany("INSERT INTO role_permissions(role_code,permission_code) VALUES (?,?)",
                [(role, code) for role in ('admin','finance') for code, _ in operations])
            db.execute("PRAGMA user_version = 41")


        if version < 42:
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE opening_balances (
                id INTEGER PRIMARY KEY, reference TEXT NOT NULL UNIQUE,
                effective_date TEXT NOT NULL, period_id INTEGER NOT NULL REFERENCES accounting_periods(id),
                note TEXT NOT NULL, currency TEXT NOT NULL DEFAULT 'CNY' CHECK(currency='CNY'),
                status TEXT NOT NULL CHECK(status IN ('draft','submitted','approved','rejected','confirmed','cancelled','reversed')),
                version INTEGER NOT NULL CHECK(version>0), active_key INTEGER UNIQUE CHECK(active_key=1),
                created_by INTEGER NOT NULL REFERENCES users(id),
                submitted_by INTEGER REFERENCES users(id), reviewed_by INTEGER REFERENCES users(id),
                confirmed_by INTEGER REFERENCES users(id), cancelled_by INTEGER REFERENCES users(id), reversed_by INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                submitted_at TEXT, reviewed_at TEXT, confirmed_at TEXT, cancelled_at TEXT, reversed_at TEXT,
                CHECK ((status IN ('cancelled','reversed') AND active_key IS NULL) OR
                       (status NOT IN ('cancelled','reversed') AND active_key IS NOT NULL))
            )""")
            db.execute("""CREATE TABLE opening_balance_lines (
                id INTEGER PRIMARY KEY, opening_balance_id INTEGER NOT NULL REFERENCES opening_balances(id),
                position INTEGER NOT NULL, account_id INTEGER NOT NULL REFERENCES ledger_accounts(id),
                account_code TEXT NOT NULL, account_name TEXT NOT NULL, category TEXT NOT NULL,
                normal_balance TEXT NOT NULL, summary TEXT NOT NULL, debit TEXT NOT NULL, credit TEXT NOT NULL,
                UNIQUE(opening_balance_id,position), UNIQUE(opening_balance_id,account_id)
            )""")
            db.execute("""CREATE TABLE opening_balance_changes (
                id INTEGER PRIMARY KEY, opening_balance_id INTEGER NOT NULL REFERENCES opening_balances(id),
                action TEXT NOT NULL, before_json TEXT, after_json TEXT NOT NULL, reason TEXT NOT NULL,
                changed_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            db.execute("INSERT INTO permission_groups(code,label,parent_code,sort_order) VALUES ('finance.opening_balances','期初余额','finance',53)")
            operations = [('opening_balance.view','查看期初余额'), ('opening_balance.create','建立和修改期初余额'),
                ('opening_balance.submit','提交期初余额'), ('opening_balance.review','审核期初余额'),
                ('opening_balance.confirm','确认期初余额'), ('opening_balance.cancel','取消未确认期初余额'),
                ('opening_balance.reverse','撤销未发生过账的期初余额')]
            db.executemany("INSERT INTO permissions(code,label,group_code) VALUES (?,?,'finance.opening_balances')",operations)
            db.executemany("INSERT INTO role_permissions(role_code,permission_code) VALUES (?,?)",
                [(role,code) for role in ('admin','finance') for code,_ in operations])
            db.execute("PRAGMA user_version = 42")

        if version < 43:
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE period_closings (
                id INTEGER PRIMARY KEY, period_id INTEGER NOT NULL REFERENCES accounting_periods(id),
                period_version INTEGER NOT NULL CHECK(period_version>0),
                action TEXT NOT NULL CHECK(action IN ('close','reopen')), snapshot_json TEXT NOT NULL,
                reason TEXT NOT NULL, created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(period_id,period_version)
            )""")
            operations = [('accounting_period.closing_view','查看结账检查与业务证据'), ('accounting_period.close','结账会计期间'), ('accounting_period.reopen','重开会计期间')]
            db.executemany("INSERT INTO permissions(code,label,group_code) VALUES (?,?,'finance.accounting_periods')", operations)
            db.executemany("INSERT INTO role_permissions(role_code,permission_code) VALUES (?,?)",
                [('admin',code) for code,_ in operations] + [('finance','accounting_period.close'), ('finance','accounting_period.closing_view')])
            db.execute("PRAGMA user_version = 43")

        if version < 44:
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE business_journal_policies (
                id INTEGER PRIMARY KEY CHECK(id=1), start_date TEXT NOT NULL,
                mapping_json TEXT NOT NULL, version INTEGER NOT NULL CHECK(version>0),
                changed_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            db.execute("""CREATE TABLE business_journal_policy_changes (
                id INTEGER PRIMARY KEY, before_json TEXT, after_json TEXT NOT NULL,
                reason TEXT NOT NULL, changed_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            db.execute("""CREATE TABLE business_journal_sources (
                id INTEGER PRIMARY KEY, journal_id INTEGER NOT NULL UNIQUE REFERENCES journals(id),
                source_key TEXT NOT NULL, active_key TEXT UNIQUE, source_json TEXT NOT NULL,
                mapping_json TEXT NOT NULL, policy_version INTEGER NOT NULL CHECK(policy_version>0),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CHECK(active_key IS NULL OR active_key=source_key)
            )""")
            db.execute("CREATE INDEX business_journal_sources_key ON business_journal_sources(source_key)")
            db.execute("INSERT INTO permission_groups(code,label,parent_code,sort_order) VALUES ('finance.business_journals','业务凭证','finance',54)")
            operations = [('business_journal.view','查看业务凭证来源'),
                ('business_journal.configure','配置业务凭证科目'), ('business_journal.generate','生成业务凭证草稿')]
            db.executemany("INSERT INTO permissions(code,label,group_code) VALUES (?,?,'finance.business_journals')",operations)
            db.executemany("INSERT INTO role_permissions(role_code,permission_code) VALUES (?,?)",
                [(role,code) for role in ('admin','finance') for code,_ in operations])
            db.execute("PRAGMA user_version = 44")

        if version < 45:
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE profit_transfer_policies (
                id INTEGER PRIMARY KEY CHECK(id=1), start_date TEXT NOT NULL,
                target_account_id INTEGER NOT NULL REFERENCES ledger_accounts(id),
                cost_account_ids_json TEXT NOT NULL, version INTEGER NOT NULL CHECK(version>0),
                changed_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            db.execute("""CREATE TABLE profit_transfer_policy_changes (
                id INTEGER PRIMARY KEY, before_json TEXT, after_json TEXT NOT NULL,
                reason TEXT NOT NULL, changed_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            db.execute("""CREATE TABLE profit_transfers (
                id INTEGER PRIMARY KEY, journal_id INTEGER NOT NULL UNIQUE REFERENCES journals(id),
                period_id INTEGER NOT NULL REFERENCES accounting_periods(id),
                active_period_id INTEGER UNIQUE REFERENCES accounting_periods(id),
                evidence_json TEXT NOT NULL, policy_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CHECK(active_period_id IS NULL OR active_period_id=period_id)
            )""")
            db.execute("CREATE INDEX profit_transfers_period ON profit_transfers(period_id)")
            db.execute("INSERT INTO permission_groups(code,label,parent_code,sort_order) VALUES ('finance.profit_transfers','损益结转','finance',55)")
            operations = [('profit_transfer.view','查看损益结转与来源'),
                ('profit_transfer.configure','配置损益结转科目'), ('profit_transfer.generate','生成损益结转草稿')]
            db.executemany("INSERT INTO permissions(code,label,group_code) VALUES (?,?,'finance.profit_transfers')", operations)
            db.executemany("INSERT INTO role_permissions(role_code,permission_code) VALUES (?,?)",
                [(role, code) for role in ('admin','finance') for code, _ in operations])
            db.execute("PRAGMA user_version = 45")

        if version < 46:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE financial_statement_policies (
                id INTEGER PRIMARY KEY CHECK(id=1), configuration_json TEXT NOT NULL,
                version INTEGER NOT NULL CHECK(version>0), changed_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('''CREATE TABLE financial_statement_policy_changes (
                id INTEGER PRIMARY KEY, before_json TEXT NOT NULL, after_json TEXT NOT NULL,
                reason TEXT NOT NULL, changed_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('''CREATE TABLE financial_statements (
                id INTEGER PRIMARY KEY, from_date TEXT NOT NULL, to_date TEXT NOT NULL,
                policy_version INTEGER NOT NULL CHECK(policy_version>0), fingerprint TEXT NOT NULL UNIQUE,
                snapshot_json TEXT NOT NULL, reason TEXT NOT NULL, created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, CHECK(from_date<=to_date))''')
            db.execute("INSERT INTO permission_groups(code,label,parent_code,sort_order) VALUES ('finance.statements','财务报表','finance',60)")
            operations = [('financial_statement.view','查看财务报表与归档'),
                ('financial_statement.configure','配置财务报表项目'), ('financial_statement.archive','归档财务报表')]
            db.executemany("INSERT INTO permissions(code,label,group_code) VALUES (?,?,'finance.statements')", operations)
            db.executemany('INSERT INTO role_permissions(role_code,permission_code) VALUES (?,?)',
                [(role, code) for role in ('admin', 'finance') for code, _ in operations])
            db.execute('PRAGMA user_version = 46')

        if version < 47:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            # 保留旧行编号和全部快照，只移除每科目一行的约束；新辅助表在重建后创建。
            db.execute('''CREATE TABLE opening_balance_lines_v47 (
                id INTEGER PRIMARY KEY, opening_balance_id INTEGER NOT NULL REFERENCES opening_balances(id),
                position INTEGER NOT NULL, account_id INTEGER NOT NULL REFERENCES ledger_accounts(id),
                account_code TEXT NOT NULL, account_name TEXT NOT NULL, category TEXT NOT NULL,
                normal_balance TEXT NOT NULL, summary TEXT NOT NULL, debit TEXT NOT NULL, credit TEXT NOT NULL,
                UNIQUE(opening_balance_id,position))''')
            db.execute('INSERT INTO opening_balance_lines_v47 SELECT * FROM opening_balance_lines')
            db.execute('DROP TABLE opening_balance_lines')
            db.execute('ALTER TABLE opening_balance_lines_v47 RENAME TO opening_balance_lines')
            db.execute('''CREATE TABLE auxiliary_items (
                id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('department','project')),
                code TEXT NOT NULL, name TEXT NOT NULL, is_active INTEGER NOT NULL CHECK(is_active IN (0,1)),
                version INTEGER NOT NULL CHECK(version>0), created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(kind,code))''')
            db.execute('''CREATE TABLE auxiliary_item_changes (
                id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL REFERENCES auxiliary_items(id),
                before_json TEXT, after_json TEXT NOT NULL, reason TEXT NOT NULL,
                changed_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('''CREATE TABLE auxiliary_policies (
                id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL UNIQUE REFERENCES ledger_accounts(id),
                start_date TEXT NOT NULL, required_kinds_json TEXT NOT NULL, version INTEGER NOT NULL CHECK(version>0),
                changed_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('''CREATE TABLE auxiliary_policy_changes (
                id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES ledger_accounts(id),
                before_json TEXT NOT NULL, after_json TEXT NOT NULL, reason TEXT NOT NULL,
                changed_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('''CREATE TABLE auxiliary_assignments (
                id INTEGER PRIMARY KEY,
                journal_line_id INTEGER REFERENCES journal_lines(id) ON DELETE CASCADE,
                opening_line_id INTEGER REFERENCES opening_balance_lines(id) ON DELETE CASCADE,
                kind TEXT NOT NULL CHECK(kind IN ('customer','supplier','department','project')),
                customer_id INTEGER REFERENCES customers(id), supplier_id INTEGER REFERENCES suppliers(id),
                item_id INTEGER REFERENCES auxiliary_items(id), code_snapshot TEXT NOT NULL, name_snapshot TEXT NOT NULL,
                CHECK((journal_line_id IS NOT NULL)+(opening_line_id IS NOT NULL)=1),
                CHECK((kind='customer' AND customer_id IS NOT NULL AND supplier_id IS NULL AND item_id IS NULL) OR
                      (kind='supplier' AND supplier_id IS NOT NULL AND customer_id IS NULL AND item_id IS NULL) OR
                      (kind IN ('department','project') AND item_id IS NOT NULL AND customer_id IS NULL AND supplier_id IS NULL)),
                UNIQUE(journal_line_id,kind), UNIQUE(opening_line_id,kind))''')
            db.execute("INSERT INTO permission_groups(code,label,parent_code,sort_order) VALUES ('finance.auxiliary','辅助核算','finance',57)")
            operations = [('auxiliary.view','查看辅助核算与变更记录'),
                ('auxiliary.configure','配置科目辅助核算规则'), ('auxiliary.manage','维护部门与项目辅助档案')]
            db.executemany("INSERT INTO permissions(code,label,group_code) VALUES (?,?,'finance.auxiliary')", operations)
            db.executemany('INSERT INTO role_permissions(role_code,permission_code) VALUES (?,?)',
                [(role, code) for role in ('admin', 'finance') for code, _ in operations])
            db.execute('PRAGMA user_version = 47')

        if version < 48:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE subledger_openings (
                id INTEGER PRIMARY KEY, reference TEXT NOT NULL UNIQUE,
                opening_balance_id INTEGER NOT NULL REFERENCES opening_balances(id),
                opening_version INTEGER NOT NULL CHECK(opening_version>0), effective_date TEXT NOT NULL,
                control_accounts_json TEXT NOT NULL, evidence_json TEXT, note TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('draft','submitted','approved','rejected','confirmed','cancelled','reversed')),
                version INTEGER NOT NULL CHECK(version>0), active_key INTEGER UNIQUE CHECK(active_key IS NULL OR active_key=1),
                created_by INTEGER NOT NULL REFERENCES users(id), submitted_by INTEGER REFERENCES users(id),
                reviewed_by INTEGER REFERENCES users(id), confirmed_by INTEGER REFERENCES users(id),
                cancelled_by INTEGER REFERENCES users(id), reversed_by INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, submitted_at TEXT, reviewed_at TEXT,
                confirmed_at TEXT, cancelled_at TEXT, reversed_at TEXT)''')
            db.execute('''CREATE TABLE subledger_opening_lines (
                id INTEGER PRIMARY KEY, opening_id INTEGER NOT NULL REFERENCES subledger_openings(id),
                position INTEGER NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('receivable','payable')),
                account_id INTEGER NOT NULL REFERENCES ledger_accounts(id), account_code TEXT NOT NULL, account_name TEXT NOT NULL,
                customer_id INTEGER REFERENCES customers(id), supplier_id INTEGER REFERENCES suppliers(id),
                document_reference TEXT NOT NULL, document_date TEXT NOT NULL,
                debit TEXT NOT NULL, credit TEXT NOT NULL, auxiliary_json TEXT NOT NULL,
                UNIQUE(opening_id,position),
                CHECK((kind='receivable' AND customer_id IS NOT NULL AND supplier_id IS NULL) OR
                      (kind='payable' AND supplier_id IS NOT NULL AND customer_id IS NULL)))''')
            db.execute('''CREATE TABLE subledger_opening_changes (
                id INTEGER PRIMARY KEY, opening_id INTEGER NOT NULL REFERENCES subledger_openings(id),
                action TEXT NOT NULL, before_json TEXT, after_json TEXT NOT NULL, reason TEXT NOT NULL,
                changed_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('''CREATE TABLE subledger_payments (
                id INTEGER PRIMARY KEY, opening_line_id INTEGER NOT NULL REFERENCES subledger_opening_lines(id),
                action TEXT NOT NULL CHECK(action IN ('settlement','refund','reversal')),
                amount TEXT NOT NULL, reference TEXT NOT NULL, note TEXT NOT NULL,
                reverses_id INTEGER UNIQUE REFERENCES subledger_payments(id),
                created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(opening_line_id,action,reference))''')
            db.execute("INSERT INTO permission_groups(code,label,parent_code,sort_order) VALUES ('finance.subledger_openings','分户期初','finance',53)")
            operations = [('subledger_opening.' + action, label) for action, label in (
                ('view','查看分户期初与未结余额'), ('create','建立及修改分户期初'), ('submit','提交分户期初'),
                ('review','独立审核分户期初'), ('confirm','确认分户期初'), ('cancel','取消分户期初'), ('reverse','撤销未使用分户期初'))]
            db.executemany("INSERT INTO permissions(code,label,group_code) VALUES (?,?,'finance.subledger_openings')", operations)
            db.executemany('INSERT INTO role_permissions(role_code,permission_code) VALUES (?,?)',
                [(role, code) for role in ('admin','finance') for code, _ in operations])
            db.execute('PRAGMA user_version = 48')

        if version < 49:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE mrp_policies (
                material_id INTEGER PRIMARY KEY REFERENCES materials(id),
                supply_mode TEXT NOT NULL CHECK(supply_mode IN ('auto','buy','make')),
                lead_time_days INTEGER NOT NULL CHECK(lead_time_days BETWEEN 0 AND 365),
                safety_stock TEXT NOT NULL, minimum_quantity TEXT NOT NULL, multiple_quantity TEXT NOT NULL,
                version INTEGER NOT NULL CHECK(version>0), changed_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('''CREATE TABLE mrp_policy_changes (
                id INTEGER PRIMARY KEY, material_id INTEGER NOT NULL REFERENCES materials(id),
                before_json TEXT, after_json TEXT NOT NULL, reason TEXT NOT NULL,
                changed_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('''CREATE TABLE mrp_plans (
                id INTEGER PRIMARY KEY, reference TEXT NOT NULL UNIQUE, input_json TEXT NOT NULL,
                snapshot_json TEXT NOT NULL, fingerprint TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('draft','submitted','approved','rejected','cancelled')),
                version INTEGER NOT NULL CHECK(version>0), created_by INTEGER NOT NULL REFERENCES users(id),
                submitted_by INTEGER REFERENCES users(id), reviewed_by INTEGER REFERENCES users(id),
                cancelled_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                submitted_at TEXT, reviewed_at TEXT, cancelled_at TEXT)''')
            db.execute('''CREATE TABLE mrp_plan_changes (
                id INTEGER PRIMARY KEY, plan_id INTEGER NOT NULL REFERENCES mrp_plans(id),
                action TEXT NOT NULL, before_json TEXT, after_json TEXT NOT NULL, reason TEXT NOT NULL,
                changed_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('''CREATE TABLE mrp_conversions (
                id INTEGER PRIMARY KEY, plan_id INTEGER NOT NULL REFERENCES mrp_plans(id), suggestion_key TEXT NOT NULL,
                purchase_request_id INTEGER UNIQUE REFERENCES purchase_requests(id),
                work_order_id INTEGER UNIQUE REFERENCES work_orders(id), due_date TEXT NOT NULL,
                reason TEXT NOT NULL, created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(plan_id,suggestion_key),
                CHECK((purchase_request_id IS NOT NULL)+(work_order_id IS NOT NULL)=1))''')
            db.execute("INSERT INTO permission_groups(code,label,parent_code,sort_order) VALUES ('production.mrp','物料需求计划','production',5)")
            operations = [('mrp.' + action, label) for action, label in (
                ('view','查看物料计划与来源'), ('configure','维护物料计划参数'), ('create','计算物料需求计划'),
                ('submit','提交物料需求计划'), ('review','独立审核物料需求计划'),
                ('cancel','取消物料需求计划'), ('convert','将物料计划转为申请或工单'))]
            db.executemany("INSERT INTO permissions(code,label,group_code) VALUES (?,?,'production.mrp')", operations)
            db.executemany('INSERT INTO role_permissions(role_code,permission_code) VALUES (?,?)',
                [('admin', code) for code, _ in operations] +
                [('planner', code) for code, _ in operations if code != 'mrp.review'] + [('finance','mrp.view')])
            db.executemany('INSERT OR IGNORE INTO role_permissions(role_code,permission_code) VALUES (?,?)',
                [('planner', 'purchase_request.' + action) for action in ('view','create','submit','cancel')])
            db.execute('PRAGMA user_version = 49')

        if version < 50:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE crm_contacts (
                id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id),
                name TEXT NOT NULL, job_title TEXT NOT NULL, phone TEXT NOT NULL, email TEXT NOT NULL, note TEXT NOT NULL,
                is_active INTEGER NOT NULL CHECK(is_active IN (0,1)), version INTEGER NOT NULL CHECK(version>0),
                created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('''CREATE TABLE crm_opportunities (
                id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id),
                contact_id INTEGER REFERENCES crm_contacts(id), title TEXT NOT NULL,
                owner_id INTEGER NOT NULL REFERENCES users(id),
                stage TEXT NOT NULL CHECK(stage IN ('prospect','qualified','proposal','negotiation','won','lost')),
                estimated_amount TEXT NOT NULL, expected_close_date TEXT NOT NULL, note TEXT NOT NULL,
                version INTEGER NOT NULL CHECK(version>0), created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('''CREATE TABLE crm_activities (
                id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id),
                contact_id INTEGER REFERENCES crm_contacts(id), opportunity_id INTEGER REFERENCES crm_opportunities(id),
                subject TEXT NOT NULL, owner_id INTEGER NOT NULL REFERENCES users(id), due_date TEXT NOT NULL,
                note TEXT NOT NULL, result TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('planned','completed','cancelled')),
                version INTEGER NOT NULL CHECK(version>0), created_by INTEGER NOT NULL REFERENCES users(id),
                closed_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, closed_at TEXT)''')
            db.execute('''CREATE TABLE crm_quotes (
                id INTEGER PRIMARY KEY, opportunity_id INTEGER NOT NULL REFERENCES crm_opportunities(id),
                customer_id INTEGER NOT NULL REFERENCES customers(id), contact_id INTEGER REFERENCES crm_contacts(id),
                reference TEXT NOT NULL UNIQUE, valid_until TEXT NOT NULL, terms TEXT NOT NULL, party_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('draft','submitted','approved','rejected','cancelled','converted')),
                version INTEGER NOT NULL CHECK(version>0), created_by INTEGER NOT NULL REFERENCES users(id),
                submitted_by INTEGER REFERENCES users(id), reviewed_by INTEGER REFERENCES users(id),
                converted_by INTEGER REFERENCES users(id), sales_order_id INTEGER UNIQUE REFERENCES sales_orders(id),
                acceptance_reference TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                submitted_at TEXT, reviewed_at TEXT, converted_at TEXT,
                CHECK((status='converted' AND sales_order_id IS NOT NULL AND acceptance_reference IS NOT NULL) OR
                      (status!='converted' AND sales_order_id IS NULL AND acceptance_reference IS NULL)))''')
            db.execute('''CREATE TABLE crm_quote_lines (
                id INTEGER PRIMARY KEY, quote_id INTEGER NOT NULL REFERENCES crm_quotes(id), position INTEGER NOT NULL,
                material_id INTEGER NOT NULL REFERENCES materials(id), sku TEXT NOT NULL,
                material_name TEXT NOT NULL, unit TEXT NOT NULL, quantity TEXT NOT NULL, unit_price TEXT NOT NULL,
                UNIQUE(quote_id,position), UNIQUE(quote_id,material_id))''')
            db.execute('''CREATE TABLE crm_changes (
                id INTEGER PRIMARY KEY, entity_kind TEXT NOT NULL CHECK(entity_kind IN ('contact','activity','opportunity','quote')),
                entity_id INTEGER NOT NULL CHECK(entity_id>0), action TEXT NOT NULL,
                before_json TEXT, after_json TEXT NOT NULL, reason TEXT NOT NULL,
                changed_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('CREATE INDEX crm_changes_entity ON crm_changes(entity_kind,entity_id,id)')
            db.execute("INSERT INTO permission_groups(code,label,parent_code,sort_order) VALUES ('sales.crm','客户关系与报价','sales',5)")
            operations = [('crm.view','查看客户关系及报价'), ('crm_contact.manage','维护客户联系人'),
                ('crm_activity.manage','登记及处理客户跟进'), ('crm_opportunity.manage','维护销售商机'),
                ('crm_quote.create','建立及修订报价'), ('crm_quote.submit','提交报价'),
                ('crm_quote.review','独立审核报价'), ('crm_quote.cancel','取消未转单报价'),
                ('crm_quote.convert','将报价转为销售订单')]
            db.executemany("INSERT INTO permissions(code,label,group_code) VALUES (?,?,'sales.crm')", operations)
            db.executemany('INSERT INTO role_permissions(role_code,permission_code) VALUES (?,?)',
                [('admin', code) for code, _ in operations] +
                [('seller', code) for code, _ in operations if code != 'crm_quote.review'])
            db.execute('PRAGMA user_version = 50')

        if version < 51:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            db.execute("ALTER TABLE production_cost_settlements ADD COLUMN rework_amount TEXT NOT NULL DEFAULT '0.00'")
            db.execute('''CREATE TABLE quality_dispositions (
                id INTEGER PRIMARY KEY, completion_id INTEGER NOT NULL REFERENCES production_completions(id),
                reference TEXT NOT NULL UNIQUE, kind TEXT NOT NULL CHECK(kind IN ('scrap','rework')),
                quantity TEXT NOT NULL, loss_treatment TEXT NOT NULL CHECK(loss_treatment IN ('absorb','expense','carry')),
                defect TEXT NOT NULL, action_note TEXT NOT NULL, warehouse_id INTEGER REFERENCES warehouses(id),
                materials_json TEXT NOT NULL, source_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('draft','submitted','approved','rejected','cancelled','posted','reversed')),
                version INTEGER NOT NULL CHECK(version>0), rework_order_id INTEGER UNIQUE REFERENCES work_orders(id),
                created_by INTEGER NOT NULL REFERENCES users(id), submitted_by INTEGER REFERENCES users(id),
                reviewed_by INTEGER REFERENCES users(id), posted_by INTEGER REFERENCES users(id), reversed_by INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, submitted_at TEXT, reviewed_at TEXT, posted_at TEXT, reversed_at TEXT,
                CHECK((kind='scrap' AND loss_treatment IN ('absorb','expense') AND warehouse_id IS NULL AND rework_order_id IS NULL)
                   OR (kind='rework' AND loss_treatment='carry' AND warehouse_id IS NOT NULL)))''')
            db.execute('CREATE INDEX quality_dispositions_completion ON quality_dispositions(completion_id,status)')
            db.execute('''CREATE TABLE quality_disposition_changes (
                id INTEGER PRIMARY KEY, disposition_id INTEGER NOT NULL REFERENCES quality_dispositions(id),
                action TEXT NOT NULL, before_json TEXT, after_json TEXT NOT NULL, reason TEXT NOT NULL,
                changed_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('''CREATE TABLE quality_cost_allocations (
                settlement_id INTEGER NOT NULL REFERENCES production_cost_settlements(id),
                disposition_id INTEGER NOT NULL REFERENCES quality_dispositions(id), quantity TEXT NOT NULL,
                amount TEXT NOT NULL, kind TEXT NOT NULL, loss_treatment TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(settlement_id,disposition_id))''')
            db.execute('''CREATE TABLE production_rework_sources (
                settlement_id INTEGER NOT NULL REFERENCES production_cost_settlements(id),
                disposition_id INTEGER NOT NULL REFERENCES quality_dispositions(id),
                origin_settlement_id INTEGER NOT NULL REFERENCES production_cost_settlements(id), amount TEXT NOT NULL,
                PRIMARY KEY(settlement_id,disposition_id))''')
            db.execute("INSERT INTO permission_groups(code,label,parent_code,sort_order) VALUES ('production.quality','不合格品处置与返工','production',6)")
            operations = [('quality.' + action, label) for action, label in (
                ('view','查看不合格品及处置证据'), ('create','建立及修订不合格品处置'),
                ('submit','提交不合格品处置'), ('review','独立审核不合格品处置'),
                ('post','确认报废或建立返工工单'), ('cancel','取消未确认处置'), ('reverse','更正已确认处置'))]
            db.executemany("INSERT INTO permissions(code,label,group_code) VALUES (?,?,'production.quality')", operations)
            db.executemany('INSERT INTO role_permissions(role_code,permission_code) VALUES (?,?)',
                [('admin', code) for code, _ in operations] +
                [('planner', 'quality.' + action) for action in ('view','create','submit','cancel')] +
                [('warehouse', 'quality.view'), ('warehouse', 'quality.post'), ('finance', 'quality.view'), ('finance', 'quality.review')])
            db.execute('PRAGMA user_version = 51')

        if version < 52:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE after_sales_cases (
                id INTEGER PRIMARY KEY, reference TEXT NOT NULL UNIQUE,
                shipment_line_id INTEGER NOT NULL REFERENCES shipment_lines(id),
                kind TEXT NOT NULL CHECK(kind IN ('return','exchange','repair')), quantity TEXT NOT NULL,
                complaint TEXT NOT NULL, solution TEXT NOT NULL, source_json TEXT NOT NULL,
                charge_mode TEXT NOT NULL CHECK(charge_mode IN ('none','free','charge')),
                fee_amount TEXT NOT NULL, customer_acceptance TEXT NOT NULL,
                warehouse_id INTEGER REFERENCES warehouses(id),
                replacement_material_id INTEGER REFERENCES materials(id), replacement_quantity TEXT, replacement_unit_price TEXT,
                parts_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('draft','submitted','approved','rejected','processing','received','repaired','closed','cancelled','reversed')),
                version INTEGER NOT NULL CHECK(version>0),
                sales_return_id INTEGER UNIQUE REFERENCES sales_returns(id),
                replacement_order_id INTEGER UNIQUE REFERENCES sales_orders(id),
                parts_outbound_id INTEGER UNIQUE REFERENCES warehouse_outbounds(id),
                created_by INTEGER NOT NULL REFERENCES users(id), submitted_by INTEGER REFERENCES users(id),
                reviewed_by INTEGER REFERENCES users(id), closed_by INTEGER REFERENCES users(id), reversed_by INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, submitted_at TEXT, reviewed_at TEXT, closed_at TEXT, reversed_at TEXT)''')
            db.execute('CREATE INDEX after_sales_source ON after_sales_cases(shipment_line_id,status)')
            db.execute('''CREATE TABLE after_sales_changes (
                id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL REFERENCES after_sales_cases(id),
                action TEXT NOT NULL, before_json TEXT, after_json TEXT NOT NULL, reason TEXT NOT NULL,
                evidence TEXT NOT NULL, changed_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('''CREATE TABLE after_sales_custody (
                id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL REFERENCES after_sales_cases(id),
                action TEXT NOT NULL CHECK(action IN ('receive','return')), quantity TEXT NOT NULL,
                evidence TEXT NOT NULL, created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute("INSERT INTO permission_groups(code,label,parent_code,sort_order) VALUES ('sales.after_sales','售后退换修','sales',6)")
            operations = [('after_sales.' + action, label) for action, label in (
                ('view','查看售后及保管证据'), ('create','编制及修订售后申请'), ('submit','提交售后申请'),
                ('review','独立审核售后方案'), ('process','办理退货或换货'), ('receive','登记客户维修品及耗材草稿'),
                ('inspect','维修检验'), ('close','办理交付并结案'), ('cancel','取消未完成售后'), ('reverse','更正已结案售后'))]
            db.executemany("INSERT INTO permissions(code,label,group_code) VALUES (?,?,'sales.after_sales')", operations)
            db.executemany('INSERT INTO role_permissions(role_code,permission_code) VALUES (?,?)',
                [('admin', code) for code, _ in operations] +
                [('seller', 'after_sales.' + action) for action in ('view','create','submit','process','close','cancel')] +
                [('warehouse', 'after_sales.' + action) for action in ('view','receive','inspect','close')] +
                [('finance', 'after_sales.view'), ('finance', 'after_sales.review')])
            db.execute('PRAGMA user_version = 52')

        if version < 53:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE equipment_assets (
                id INTEGER PRIMARY KEY,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                serial_number TEXT UNIQUE,
                location TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('active','inactive','retired')),
                version INTEGER NOT NULL CHECK(version>0),
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('''CREATE TABLE maintenance_plans (
                id INTEGER PRIMARY KEY,
                equipment_id INTEGER NOT NULL REFERENCES equipment_assets(id),
                reference TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                interval_days INTEGER NOT NULL CHECK(interval_days BETWEEN 1 AND 3650),
                next_due TEXT NOT NULL,
                enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
                version INTEGER NOT NULL CHECK(version>0),
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('''CREATE TABLE maintenance_jobs (
                id INTEGER PRIMARY KEY,
                reference TEXT NOT NULL UNIQUE,
                equipment_id INTEGER NOT NULL REFERENCES equipment_assets(id),
                kind TEXT NOT NULL CHECK(kind IN ('preventive','corrective')),
                plan_id INTEGER REFERENCES maintenance_plans(id),
                plan_version INTEGER,
                plan_due_date TEXT,
                work_order_id INTEGER REFERENCES work_orders(id),
                assigned_to INTEGER NOT NULL REFERENCES users(id),
                request_note TEXT NOT NULL,
                equipment_json TEXT NOT NULL,
                work_order_json TEXT NOT NULL,
                parts_json TEXT NOT NULL,
                warehouse_id INTEGER REFERENCES warehouses(id),
                parts_outbound_id INTEGER REFERENCES warehouse_outbounds(id) UNIQUE,
                status TEXT NOT NULL CHECK(status IN ('draft','submitted','approved','rejected','in_progress','reported','accepted','cancelled','reversed')),
                version INTEGER NOT NULL CHECK(version>0),
                solution TEXT NOT NULL,
                labor_hours TEXT,
                service_amount TEXT,
                plan_roll_json TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                reviewed_by INTEGER REFERENCES users(id),
                reported_by INTEGER REFERENCES users(id),
                accepted_by INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                started_at TEXT,
                reported_at TEXT,
                accepted_at TEXT)''')
            db.execute('''CREATE TABLE maintenance_downtimes (
                id INTEGER PRIMARY KEY,
                equipment_id INTEGER NOT NULL REFERENCES equipment_assets(id),
                job_id INTEGER NOT NULL REFERENCES maintenance_jobs(id) UNIQUE,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                close_reason TEXT NOT NULL,
                started_by INTEGER NOT NULL REFERENCES users(id),
                ended_by INTEGER REFERENCES users(id))''')
            db.execute('''CREATE TABLE maintenance_changes (
                id INTEGER PRIMARY KEY,
                entity_type TEXT NOT NULL CHECK(entity_type IN ('equipment','plan','job')),
                entity_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                before_json TEXT,
                after_json TEXT NOT NULL,
                reason TEXT NOT NULL,
                evidence TEXT NOT NULL,
                changed_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute("CREATE UNIQUE INDEX maintenance_plan_occurrence ON maintenance_jobs(plan_id,plan_due_date) WHERE plan_id IS NOT NULL AND status NOT IN ('cancelled','reversed')")
            db.execute("CREATE UNIQUE INDEX maintenance_equipment_running ON maintenance_jobs(equipment_id) WHERE status IN ('in_progress','reported')")
            db.execute('CREATE INDEX maintenance_entity_changes ON maintenance_changes(entity_type,entity_id,id)')
            db.execute("INSERT INTO permission_groups(code,label,parent_code,sort_order) VALUES ('production.equipment','设备维护','production',7)")
            operations = [('equipment.' + action, label) for action, label in (
                ('view','查看设备维护与停机证据'), ('manage','维护设备台账与周期计划'),
                ('create','编制及修订维护工单'), ('submit','提交维护工单'), ('review','独立审核维护工单'),
                ('execute','执行维护与报工'), ('accept','独立验收维护结果'),
                ('cancel','取消未验收维护工单'), ('reverse','更正已验收维护工单'))]
            db.executemany("INSERT INTO permissions(code,label,group_code) VALUES (?,?,'production.equipment')", operations)
            db.executemany('INSERT INTO role_permissions(role_code,permission_code) VALUES (?,?)',
                [('admin', code) for code, _ in operations] +
                [('planner', 'equipment.' + action) for action in ('view','manage','create','submit','execute','cancel')] +
                [('warehouse', 'equipment.view'), ('warehouse', 'equipment.execute')])
            db.execute('PRAGMA user_version = 53')

        if version < 54:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            # 只增加空资料列，保留旧物料 ID、编码、供货关系与库存/业务外键。
            db.execute("ALTER TABLE materials ADD COLUMN category_code TEXT NOT NULL DEFAULT ''")
            db.execute("ALTER TABLE materials ADD COLUMN specification TEXT NOT NULL DEFAULT ''")
            db.execute("ALTER TABLE materials ADD COLUMN package TEXT NOT NULL DEFAULT ''")
            db.execute("ALTER TABLE materials ADD COLUMN brand TEXT NOT NULL DEFAULT ''")
            db.execute("ALTER TABLE materials ADD COLUMN manufacturer_part_number TEXT NOT NULL DEFAULT ''")
            db.execute("ALTER TABLE materials ADD COLUMN electrical_value TEXT NOT NULL DEFAULT ''")
            db.execute("ALTER TABLE materials ADD COLUMN tolerance TEXT NOT NULL DEFAULT ''")
            db.execute("ALTER TABLE materials ADD COLUMN rated_voltage TEXT NOT NULL DEFAULT ''")
            db.execute("ALTER TABLE materials ADD COLUMN rated_power TEXT NOT NULL DEFAULT ''")
            db.execute("ALTER TABLE materials ADD COLUMN temperature_range TEXT NOT NULL DEFAULT ''")
            db.execute("ALTER TABLE materials ADD COLUMN compliance TEXT NOT NULL DEFAULT ''")
            db.execute("ALTER TABLE materials ADD COLUMN notes TEXT NOT NULL DEFAULT ''")
            db.execute('ALTER TABLE materials ADD COLUMN version INTEGER NOT NULL DEFAULT 1 CHECK(version>0)')
            db.execute('CREATE TABLE material_code_sequences (prefix TEXT PRIMARY KEY, last_number INTEGER NOT NULL CHECK(last_number BETWEEN 0 AND 999999))')
            db.execute("""CREATE TABLE material_changes (
                id INTEGER PRIMARY KEY, material_id INTEGER NOT NULL, sku TEXT NOT NULL,
                action TEXT NOT NULL CHECK(action IN ('create','update','delete')),
                before_json TEXT, after_json TEXT, reason TEXT NOT NULL,
                changed_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
            db.execute('CREATE INDEX material_change_history ON material_changes(material_id,id)')
            # 从旧库同格式编码初始化流水；不改历史物料，也不猜测其所属类别。
            from app.catalog.material_rules import CATEGORY_CODES
            for row in db.execute('SELECT sku FROM materials').fetchall():
                match = re.fullmatch(r'([A-Z]{2}-[A-Z]{2})-(\d{6})', row['sku'])
                if match and match[1] in CATEGORY_CODES:
                    db.execute("INSERT INTO material_code_sequences(prefix,last_number) VALUES (?,?) ON CONFLICT(prefix) DO UPDATE SET last_number=MAX(last_number,excluded.last_number)",
                               (match[1], int(match[2])))
            db.execute('PRAGMA user_version = 54')

        if version < 55:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE inventory_warning_rules (id INTEGER PRIMARY KEY, warehouse_id INTEGER NOT NULL REFERENCES warehouses(id), material_id INTEGER NOT NULL REFERENCES materials(id), threshold TEXT NOT NULL, enabled INTEGER NOT NULL CHECK(enabled IN (0,1)), version INTEGER NOT NULL CHECK(version>0), created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(warehouse_id,material_id))')
            db.execute('CREATE TABLE inventory_warning_changes (id INTEGER PRIMARY KEY, rule_id INTEGER NOT NULL REFERENCES inventory_warning_rules(id), before_json TEXT, after_json TEXT NOT NULL, reason TEXT NOT NULL, changed_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
            db.execute('CREATE INDEX inventory_warning_history ON inventory_warning_changes(rule_id,id)')
            db.execute("INSERT INTO permission_groups(code,label,parent_code,sort_order) VALUES ('warehouse.warnings','库存预警','warehouse',9)")
            db.execute("INSERT INTO permissions(code,label,group_code) VALUES ('inventory_warning.manage','维护库存预警阈值','warehouse.warnings')")
            db.executemany('INSERT INTO role_permissions(role_code,permission_code) VALUES (?,?)', [('admin','inventory_warning.manage'),('warehouse','inventory_warning.manage')])
            db.execute('PRAGMA user_version = 55')

        if version < 56:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE physical_lots (
                id INTEGER PRIMARY KEY,
                material_id INTEGER NOT NULL REFERENCES materials(id),
                code TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                supplier_lot TEXT,
                manufactured_on TEXT,
                expires_on TEXT,
                origin_movement_id INTEGER REFERENCES stock_movements(id),
                created_by INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(material_id,code))''')
            db.execute('''CREATE TABLE physical_lot_openings (
                id INTEGER PRIMARY KEY,
                lot_id INTEGER NOT NULL REFERENCES physical_lots(id),
                warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
                quantity TEXT NOT NULL,
                checkpoint_movement_id INTEGER NOT NULL,
                evidence TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(lot_id,warehouse_id))''')
            db.execute('''CREATE TABLE physical_lot_allocations (
                id INTEGER PRIMARY KEY,
                lot_id INTEGER NOT NULL REFERENCES physical_lots(id),
                movement_id INTEGER NOT NULL REFERENCES stock_movements(id),
                quantity TEXT NOT NULL,
                original_allocation_id INTEGER REFERENCES physical_lot_allocations(id),
                UNIQUE(lot_id,movement_id))''')
            db.execute('CREATE INDEX physical_lot_allocation_history ON physical_lot_allocations(lot_id,movement_id)')
            db.execute('CREATE UNIQUE INDEX physical_lot_reversal_once ON physical_lot_allocations(original_allocation_id)')
            # 旧流水没有真实批次证据，只对升级时的逐仓净结存建立未识别期初。
            checkpoint = db.execute('SELECT COALESCE(MAX(id),0) FROM stock_movements').fetchone()[0]
            balances: dict[tuple[int, int], Decimal] = {}
            for warehouse_id, material_id, quantity in db.execute(
                'SELECT warehouse_id,material_id,quantity FROM stock_movements ORDER BY id'
            ):
                key = (warehouse_id, material_id)
                balances[key] = balances.get(key, Decimal(0)) + Decimal(quantity)
            for (warehouse_id, material_id), quantity in sorted(balances.items()):
                if quantity == 0:
                    continue
                lot = db.execute('''INSERT INTO physical_lots(material_id,code,source_kind)
                    VALUES (?,?,'legacy')''',
                    (material_id, f'LEGACY-W{warehouse_id}-M{material_id}'))
                db.execute('''INSERT INTO physical_lot_openings(
                    lot_id,warehouse_id,quantity,checkpoint_movement_id,evidence)
                    VALUES (?,?,?,?,?)''',
                    (lot.lastrowid, warehouse_id, str(quantity), checkpoint,
                     '旧库存无实物批次证据；仅按升级时逐仓净结存建立未识别期初'))
            db.execute('PRAGMA user_version = 56')

        if version < 57:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE physical_lot_reclassifications (
                id INTEGER PRIMARY KEY,
                legacy_lot_id INTEGER NOT NULL REFERENCES physical_lots(id),
                verified_lot_id INTEGER NOT NULL REFERENCES physical_lots(id),
                warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
                quantity TEXT NOT NULL,
                evidence TEXT NOT NULL,
                original_reclassification_id INTEGER REFERENCES physical_lot_reclassifications(id),
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('CREATE INDEX physical_lot_reclassification_legacy ON physical_lot_reclassifications(legacy_lot_id,warehouse_id)')
            db.execute('CREATE INDEX physical_lot_reclassification_verified ON physical_lot_reclassifications(verified_lot_id,warehouse_id)')
            db.execute('CREATE UNIQUE INDEX physical_lot_reclassification_reversal_once ON physical_lot_reclassifications(original_reclassification_id)')
            db.execute("INSERT INTO permission_groups(code,label,parent_code,sort_order) VALUES ('warehouse.physical_lots','实物批次','warehouse',10)")
            db.execute("INSERT INTO permissions(code,label,group_code) VALUES ('physical_lot.reclassify','历史批次补证','warehouse.physical_lots')")
            db.executemany('INSERT INTO role_permissions(role_code,permission_code) VALUES (?,?)',
                           [('admin','physical_lot.reclassify'), ('warehouse','physical_lot.reclassify')])
            db.execute('PRAGMA user_version = 57')

        if version < 58:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE physical_lot_movement_checkpoints (
                id INTEGER PRIMARY KEY CHECK(id=1), movement_id INTEGER NOT NULL,
                basis TEXT NOT NULL)''')
            opening_checkpoint = db.execute(
                'SELECT MAX(checkpoint_movement_id) FROM physical_lot_openings').fetchone()[0]
            # 旧版没有保存空结存时的升级检查点；保守地排除无法判定时期的旧流水。
            checkpoint = opening_checkpoint if opening_checkpoint is not None else db.execute(
                'SELECT COALESCE(MAX(id),0) FROM stock_movements').fetchone()[0]
            basis = 'v56_opening' if opening_checkpoint is not None else 'v58_conservative'
            db.execute('INSERT INTO physical_lot_movement_checkpoints(id,movement_id,basis) VALUES (1,?,?)',
                       (checkpoint, basis))
            db.execute('''CREATE TABLE physical_lot_movement_evidence (
                id INTEGER PRIMARY KEY,
                movement_id INTEGER NOT NULL REFERENCES stock_movements(id),
                lot_id INTEGER NOT NULL REFERENCES physical_lots(id),
                quantity TEXT NOT NULL, evidence TEXT NOT NULL,
                original_evidence_id INTEGER REFERENCES physical_lot_movement_evidence(id),
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('CREATE INDEX physical_lot_movement_evidence_movement ON physical_lot_movement_evidence(movement_id,id)')
            db.execute('CREATE INDEX physical_lot_movement_evidence_lot ON physical_lot_movement_evidence(lot_id,id)')
            db.execute('CREATE UNIQUE INDEX physical_lot_movement_evidence_reverse_once ON physical_lot_movement_evidence(original_evidence_id)')
            db.execute('CREATE INDEX IF NOT EXISTS physical_lot_allocation_movement ON physical_lot_allocations(movement_id)')
            db.execute("INSERT INTO permissions(code,label,group_code) VALUES ('physical_lot.movement_evidence','旧流水逐笔补证','warehouse.physical_lots')")
            db.executemany('INSERT INTO role_permissions(role_code,permission_code) VALUES (?,?)',
                           [('admin','physical_lot.movement_evidence'), ('warehouse','physical_lot.movement_evidence')])
            db.execute('PRAGMA user_version = 58')

        if version < 59:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE physical_lot_evidence_pairs (
                id INTEGER PRIMARY KEY,
                inbound_movement_id INTEGER NOT NULL REFERENCES stock_movements(id),
                outbound_movement_id INTEGER NOT NULL REFERENCES stock_movements(id),
                inbound_evidence_id INTEGER NOT NULL REFERENCES physical_lot_movement_evidence(id),
                outbound_evidence_id INTEGER NOT NULL REFERENCES physical_lot_movement_evidence(id),
                lot_id INTEGER NOT NULL REFERENCES physical_lots(id),
                quantity TEXT NOT NULL, evidence TEXT NOT NULL,
                original_pair_id INTEGER REFERENCES physical_lot_evidence_pairs(id),
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('CREATE UNIQUE INDEX physical_lot_evidence_pair_reversal_once ON physical_lot_evidence_pairs(original_pair_id)')
            db.execute('CREATE INDEX physical_lot_evidence_pair_lot ON physical_lot_evidence_pairs(lot_id,id)')
            db.execute('CREATE INDEX physical_lot_evidence_pair_inbound ON physical_lot_evidence_pairs(inbound_evidence_id)')
            db.execute('CREATE INDEX physical_lot_evidence_pair_outbound ON physical_lot_evidence_pairs(outbound_evidence_id)')
            db.execute('PRAGMA user_version = 59')

        if version < 60:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE physical_lot_evidence_groups (
                id INTEGER PRIMARY KEY,
                lot_id INTEGER NOT NULL REFERENCES physical_lots(id),
                warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
                material_id INTEGER NOT NULL REFERENCES materials(id),
                evidence TEXT NOT NULL,
                original_group_id INTEGER REFERENCES physical_lot_evidence_groups(id),
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('''CREATE TABLE physical_lot_evidence_group_pairs (
                group_id INTEGER NOT NULL REFERENCES physical_lot_evidence_groups(id),
                pair_id INTEGER NOT NULL REFERENCES physical_lot_evidence_pairs(id),
                position INTEGER NOT NULL,
                PRIMARY KEY(group_id,pair_id), UNIQUE(pair_id), UNIQUE(group_id,position))''')
            db.execute('CREATE UNIQUE INDEX physical_lot_evidence_group_reverse_once ON physical_lot_evidence_groups(original_group_id)')
            db.execute('CREATE INDEX physical_lot_evidence_group_lot ON physical_lot_evidence_groups(lot_id,id)')
            db.execute('PRAGMA user_version = 60')

        if version < 61:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            # 旧客户没有可核验的归属证据，保留未分配状态，由管理员逐一认领或转交。
            customer_columns = {row['name'] for row in db.execute('PRAGMA table_info(customers)')}
            if 'owner_id' not in customer_columns:
                db.execute('ALTER TABLE customers ADD COLUMN owner_id INTEGER REFERENCES users(id)')
            if 'version' not in customer_columns:
                db.execute('ALTER TABLE customers ADD COLUMN version INTEGER NOT NULL DEFAULT 1 CHECK(version>0)')
            db.execute('CREATE INDEX IF NOT EXISTS customer_owner_lookup ON customers(owner_id,id)')
            db.execute('''CREATE TABLE IF NOT EXISTS customer_owner_changes (
                id INTEGER PRIMARY KEY,
                customer_id INTEGER NOT NULL REFERENCES customers(id),
                before_owner_id INTEGER REFERENCES users(id),
                after_owner_id INTEGER NOT NULL REFERENCES users(id),
                version INTEGER NOT NULL CHECK(version>0),
                reason TEXT NOT NULL,
                changed_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('CREATE INDEX IF NOT EXISTS customer_owner_change_history ON customer_owner_changes(customer_id,id)')
            db.execute("INSERT OR IGNORE INTO permissions(code,label,group_code) VALUES ('customer.assign','分配客户负责人','sales.customer')")
            db.execute("INSERT OR IGNORE INTO role_permissions(role_code,permission_code) VALUES ('admin','customer.assign')")
            db.execute("INSERT OR IGNORE INTO permissions(code,label,group_code) VALUES ('customer.view_all','查看全部客户归属','sales.customer')")
            db.executemany('INSERT OR IGNORE INTO role_permissions(role_code,permission_code) VALUES (?,?)',
                           [(role,'customer.view_all') for role in ('admin','warehouse','finance')])
            db.execute('PRAGMA user_version = 61')

        if version < 62:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            supplier_columns = {row['name'] for row in db.execute('PRAGMA table_info(suppliers)')}
            if 'version' not in supplier_columns:
                db.execute('ALTER TABLE suppliers ADD COLUMN version INTEGER NOT NULL DEFAULT 1 CHECK(version>0)')
            warehouse_columns = {row['name'] for row in db.execute('PRAGMA table_info(warehouses)')}
            if 'version' not in warehouse_columns:
                db.execute('ALTER TABLE warehouses ADD COLUMN version INTEGER NOT NULL DEFAULT 1 CHECK(version>0)')
            # 历史档案不能推断修改人和修改依据，只从升级后的真实操作开始记审计。
            db.execute('''CREATE TABLE IF NOT EXISTS supplier_changes (
                id INTEGER PRIMARY KEY, supplier_id INTEGER NOT NULL,
                action TEXT NOT NULL, before_json TEXT, after_json TEXT,
                reason TEXT NOT NULL, changed_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('CREATE INDEX IF NOT EXISTS supplier_change_history ON supplier_changes(supplier_id,id)')
            db.execute('''CREATE TABLE IF NOT EXISTS warehouse_changes (
                id INTEGER PRIMARY KEY, warehouse_id INTEGER NOT NULL,
                action TEXT NOT NULL, before_json TEXT, after_json TEXT,
                reason TEXT NOT NULL, changed_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('CREATE INDEX IF NOT EXISTS warehouse_change_history ON warehouse_changes(warehouse_id,id)')
            db.execute('PRAGMA user_version = 62')

        if version < 63:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE equipment_meter_readings (
                id INTEGER PRIMARY KEY,
                equipment_id INTEGER NOT NULL REFERENCES equipment_assets(id),
                hours TEXT NOT NULL, reference TEXT NOT NULL, reason TEXT NOT NULL,
                previous_reading_id INTEGER REFERENCES equipment_meter_readings(id),
                correction INTEGER NOT NULL CHECK(correction IN (0,1)),
                recorded_by INTEGER NOT NULL REFERENCES users(id),
                recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(equipment_id,reference))''')
            db.execute('CREATE INDEX equipment_meter_history ON equipment_meter_readings(equipment_id,id)')
            db.execute('''CREATE TABLE maintenance_hour_plans (
                id INTEGER PRIMARY KEY,
                equipment_id INTEGER NOT NULL REFERENCES equipment_assets(id),
                reference TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
                interval_hours TEXT NOT NULL, next_due_hours TEXT NOT NULL,
                enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
                version INTEGER NOT NULL CHECK(version>0),
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('CREATE INDEX maintenance_hour_plan_equipment ON maintenance_hour_plans(equipment_id,id)')
            db.execute('''CREATE TABLE maintenance_hour_plan_changes (
                id INTEGER PRIMARY KEY,
                plan_id INTEGER NOT NULL REFERENCES maintenance_hour_plans(id),
                action TEXT NOT NULL, before_json TEXT, after_json TEXT NOT NULL,
                reason TEXT NOT NULL, evidence TEXT NOT NULL,
                changed_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('CREATE INDEX maintenance_hour_plan_history ON maintenance_hour_plan_changes(plan_id,id)')
            db.execute('ALTER TABLE maintenance_jobs ADD COLUMN hour_plan_id INTEGER REFERENCES maintenance_hour_plans(id)')
            db.execute('ALTER TABLE maintenance_jobs ADD COLUMN plan_due_hours TEXT')
            db.execute('ALTER TABLE maintenance_jobs ADD COLUMN plan_meter_reading_id INTEGER REFERENCES equipment_meter_readings(id)')
            db.execute("CREATE UNIQUE INDEX maintenance_hour_occurrence ON maintenance_jobs(hour_plan_id,plan_due_hours) WHERE hour_plan_id IS NOT NULL AND status NOT IN ('cancelled','reversed')")
            db.execute("INSERT INTO permissions(code,label,group_code) VALUES ('equipment.meter','登记设备运行小时','production.equipment')")
            db.executemany('INSERT INTO role_permissions(role_code,permission_code) VALUES (?,?)',
                           [(role,'equipment.meter') for role in ('admin','planner','warehouse')])
            db.execute('PRAGMA user_version = 63')

        if version < 64:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE after_sales_labor (
                id INTEGER PRIMARY KEY,
                case_id INTEGER NOT NULL REFERENCES after_sales_cases(id),
                action TEXT NOT NULL CHECK(action IN ('record','reverse')),
                hours TEXT NOT NULL,
                original_id INTEGER UNIQUE REFERENCES after_sales_labor(id),
                reason TEXT NOT NULL, evidence TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('CREATE INDEX after_sales_labor_case ON after_sales_labor(case_id,id)')
            db.execute("INSERT INTO permissions(code,label,group_code) VALUES ('after_sales.labor','登记与更正维修工时','sales.after_sales')")
            db.executemany('INSERT INTO role_permissions(role_code,permission_code) VALUES (?,?)',
                           [(role,'after_sales.labor') for role in ('admin','warehouse')])
            db.execute('PRAGMA user_version = 64')

        if version < 65:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            # 历史商机没有经过概率评估，保留 NULL，不能用阶段推断既有预测。
            columns = {row['name'] for row in db.execute('PRAGMA table_info(crm_opportunities)')}
            if 'probability_percent' not in columns:
                db.execute('ALTER TABLE crm_opportunities ADD COLUMN probability_percent INTEGER CHECK(probability_percent BETWEEN 0 AND 100)')
            db.execute('PRAGMA user_version = 65')

        if version < 66:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE material_issue_reversals (
                id INTEGER PRIMARY KEY,
                material_issue_id INTEGER NOT NULL UNIQUE REFERENCES material_issues(id),
                reason TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute("INSERT INTO permissions(code,label,group_code) VALUES ('material_issue.reverse','冲销已确认生产领料','production.material_issue')")
            db.execute("INSERT INTO role_permissions(role_code,permission_code) VALUES ('admin','material_issue.reverse')")
            db.execute('PRAGMA user_version = 66')

        if version < 67:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE material_return_reversals (
                id INTEGER PRIMARY KEY,
                material_return_id INTEGER NOT NULL UNIQUE REFERENCES material_returns(id),
                reason TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute("INSERT INTO permissions(code,label,group_code) VALUES ('material_return.reverse','冲销已确认生产退料','production.material_return')")
            db.execute("INSERT INTO role_permissions(role_code,permission_code) VALUES ('admin','material_return.reverse')")
            db.execute('PRAGMA user_version = 67')

        if version < 68:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE inventory_warning_observations (
                rule_id INTEGER PRIMARY KEY REFERENCES inventory_warning_rules(id),
                status TEXT NOT NULL CHECK(status IN ('normal','low','out_of_stock','disabled')),
                quantity TEXT NOT NULL,
                observed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('''CREATE TABLE inventory_warning_events (
                id INTEGER PRIMARY KEY,
                rule_id INTEGER NOT NULL REFERENCES inventory_warning_rules(id),
                warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
                material_id INTEGER NOT NULL REFERENCES materials(id),
                previous_status TEXT CHECK(previous_status IS NULL OR previous_status IN ('normal','low','out_of_stock','disabled')),
                status TEXT NOT NULL CHECK(status IN ('low','out_of_stock')),
                quantity TEXT NOT NULL, threshold TEXT NOT NULL, shortage TEXT NOT NULL,
                rule_version INTEGER NOT NULL,
                warehouse_code TEXT NOT NULL, warehouse_name TEXT NOT NULL,
                sku TEXT NOT NULL, material_name TEXT NOT NULL, unit TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('CREATE INDEX inventory_warning_events_warehouse ON inventory_warning_events(warehouse_id,id)')
            db.execute('CREATE INDEX inventory_warning_events_rule ON inventory_warning_events(rule_id,id)')
            db.execute('PRAGMA user_version = 68')

        if version < 69:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE IF NOT EXISTS bank_accounts (
                id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('''CREATE TABLE IF NOT EXISTS bank_statement_lines (
                id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES bank_accounts(id),
                transaction_id TEXT NOT NULL, occurred_on TEXT NOT NULL, amount TEXT NOT NULL,
                counterparty TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(account_id, transaction_id))''')
            db.execute('''CREATE TABLE IF NOT EXISTS bank_matches (
                id INTEGER PRIMARY KEY,
                statement_line_id INTEGER NOT NULL REFERENCES bank_statement_lines(id),
                source_type TEXT NOT NULL CHECK(source_type IN ('order_payment','subledger_payment')),
                source_id INTEGER NOT NULL, reason TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('''CREATE TABLE IF NOT EXISTS bank_match_reversals (
                id INTEGER PRIMARY KEY, match_id INTEGER NOT NULL UNIQUE REFERENCES bank_matches(id),
                reason TEXT NOT NULL, created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('CREATE INDEX IF NOT EXISTS bank_matches_statement ON bank_matches(statement_line_id,id)')
            db.execute('CREATE INDEX IF NOT EXISTS bank_matches_source ON bank_matches(source_type,source_id,id)')
            db.execute("INSERT OR IGNORE INTO permission_groups(code,label,parent_code,sort_order) VALUES ('finance.bank_reconciliation','银行勾对','finance',54)")
            operations = [('bank_reconciliation.' + action, label) for action, label in (
                ('view','查看银行流水与勾对'), ('account','登记银行账户'),
                ('record','登记银行流水'), ('match','勾对收付款'), ('reverse','撤销银行勾对'))]
            db.executemany("INSERT OR IGNORE INTO permissions(code,label,group_code) VALUES (?,?,'finance.bank_reconciliation')", operations)
            db.executemany('INSERT OR IGNORE INTO role_permissions(role_code,permission_code) VALUES (?,?)',
                [(role, code) for role in ('admin','finance') for code, _ in operations])
            db.execute('PRAGMA user_version = 69')

        if version < 70:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE IF NOT EXISTS bank_import_batches (
                id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES bank_accounts(id),
                file_name TEXT NOT NULL, sha256 TEXT NOT NULL, row_count INTEGER NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(account_id, sha256))''')
            columns = {row[1] for row in db.execute('PRAGMA table_info(bank_statement_lines)')}
            if 'import_batch_id' not in columns:
                db.execute('ALTER TABLE bank_statement_lines ADD COLUMN import_batch_id INTEGER REFERENCES bank_import_batches(id)')
            db.execute('CREATE INDEX IF NOT EXISTS bank_statement_lines_import_batch ON bank_statement_lines(import_batch_id,id)')
            db.execute('PRAGMA user_version = 70')

        if version < 71:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            account_columns = {row[1] for row in db.execute('PRAGMA table_info(bank_accounts)')}
            for column, declaration in (
                ('ledger_account_id', 'INTEGER REFERENCES ledger_accounts(id)'),
                ('opening_balance', 'TEXT'), ('effective_date', 'TEXT'),
                ('version', 'INTEGER NOT NULL DEFAULT 1')):
                if column not in account_columns:
                    db.execute(f'ALTER TABLE bank_accounts ADD COLUMN {column} {declaration}')
            db.execute('CREATE UNIQUE INDEX IF NOT EXISTS bank_accounts_ledger_account ON bank_accounts(ledger_account_id) WHERE ledger_account_id IS NOT NULL')
            db.execute('''CREATE TABLE IF NOT EXISTS bank_account_changes (
                id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES bank_accounts(id),
                before_json TEXT NOT NULL, after_json TEXT NOT NULL, reason TEXT NOT NULL,
                changed_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('''CREATE TABLE IF NOT EXISTS bank_ledger_match_groups (
                id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES bank_accounts(id),
                amount TEXT NOT NULL, reason TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('''CREATE TABLE IF NOT EXISTS bank_ledger_match_members (
                id INTEGER PRIMARY KEY, group_id INTEGER NOT NULL REFERENCES bank_ledger_match_groups(id),
                side TEXT NOT NULL CHECK(side IN ('bank','book')),
                source_id INTEGER NOT NULL,
                bank_line_id INTEGER REFERENCES bank_statement_lines(id),
                journal_line_id INTEGER REFERENCES journal_lines(id),
                amount TEXT NOT NULL,
                CHECK((side='bank' AND bank_line_id=source_id AND journal_line_id IS NULL)
                    OR (side='book' AND journal_line_id=source_id AND bank_line_id IS NULL)))''')
            db.execute('CREATE INDEX IF NOT EXISTS bank_ledger_match_members_source ON bank_ledger_match_members(side,source_id,group_id)')
            db.execute('''CREATE TABLE IF NOT EXISTS bank_ledger_match_reversals (
                id INTEGER PRIMARY KEY, group_id INTEGER NOT NULL UNIQUE REFERENCES bank_ledger_match_groups(id),
                reason TEXT NOT NULL, created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('''CREATE TABLE IF NOT EXISTS bank_balance_reports (
                id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES bank_accounts(id),
                as_of_date TEXT NOT NULL, declared_bank_closing TEXT NOT NULL,
                fingerprint TEXT NOT NULL, snapshot_json TEXT NOT NULL, reason TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('CREATE INDEX IF NOT EXISTS bank_balance_reports_scope ON bank_balance_reports(account_id,as_of_date,id)')
            db.execute('''CREATE TABLE IF NOT EXISTS bank_balance_report_decisions (
                id INTEGER PRIMARY KEY, report_id INTEGER NOT NULL REFERENCES bank_balance_reports(id),
                action TEXT NOT NULL CHECK(action IN ('approve','reject','supersede')),
                reason TEXT NOT NULL, created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS bank_balance_report_terminal ON bank_balance_report_decisions(report_id) WHERE action IN ('approve','reject')")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS bank_balance_report_supersede ON bank_balance_report_decisions(report_id) WHERE action='supersede'")
            operations = [('bank_reconciliation.reconcile', '编制银行余额调节表'),
                          ('bank_reconciliation.review', '复核银行余额调节表')]
            db.executemany("INSERT OR IGNORE INTO permissions(code,label,group_code) VALUES (?,?,'finance.bank_reconciliation')", operations)
            db.executemany('INSERT OR IGNORE INTO role_permissions(role_code,permission_code) VALUES (?,?)',
                [(role, code) for role in ('admin','finance') for code, _ in operations])
            db.execute('PRAGMA user_version = 71')

        if version < 72:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE IF NOT EXISTS bank_opening_items (
                id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES bank_accounts(id),
                side TEXT NOT NULL CHECK(side IN ('bank','book')),
                occurred_on TEXT NOT NULL, amount TEXT NOT NULL,
                reference TEXT NOT NULL, description TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(account_id,side,reference))''')
            db.execute('CREATE INDEX IF NOT EXISTS bank_opening_items_account ON bank_opening_items(account_id,side,id)')
            db.execute('''CREATE TABLE IF NOT EXISTS bank_opening_clearances (
                id INTEGER PRIMARY KEY,
                opening_item_id INTEGER NOT NULL REFERENCES bank_opening_items(id),
                reason TEXT NOT NULL, created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('CREATE INDEX IF NOT EXISTS bank_opening_clearances_item ON bank_opening_clearances(opening_item_id,id)')
            db.execute('''CREATE TABLE IF NOT EXISTS bank_opening_clearance_members (
                id INTEGER PRIMARY KEY,
                clearance_id INTEGER NOT NULL REFERENCES bank_opening_clearances(id),
                side TEXT NOT NULL CHECK(side IN ('bank','book')),
                source_id INTEGER NOT NULL,
                bank_line_id INTEGER REFERENCES bank_statement_lines(id),
                journal_line_id INTEGER REFERENCES journal_lines(id),
                amount TEXT NOT NULL,
                CHECK((side='bank' AND bank_line_id=source_id AND journal_line_id IS NULL)
                    OR (side='book' AND journal_line_id=source_id AND bank_line_id IS NULL)))''')
            db.execute('CREATE INDEX IF NOT EXISTS bank_opening_clearance_members_source ON bank_opening_clearance_members(side,source_id,clearance_id)')
            db.execute('''CREATE TABLE IF NOT EXISTS bank_opening_clearance_reversals (
                id INTEGER PRIMARY KEY,
                clearance_id INTEGER NOT NULL UNIQUE REFERENCES bank_opening_clearances(id),
                reason TEXT NOT NULL, created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('PRAGMA user_version = 72')

        if version < 73:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE IF NOT EXISTS journal_attachments (
                id INTEGER PRIMARY KEY,
                journal_id INTEGER NOT NULL REFERENCES journals(id),
                file_name TEXT NOT NULL, media_type TEXT NOT NULL,
                byte_count INTEGER NOT NULL, sha256 TEXT NOT NULL,
                content BLOB NOT NULL, reason TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('CREATE INDEX IF NOT EXISTS journal_attachments_journal ON journal_attachments(journal_id,id)')
            db.execute('''CREATE TABLE IF NOT EXISTS journal_attachment_reversals (
                id INTEGER PRIMARY KEY,
                attachment_id INTEGER NOT NULL UNIQUE REFERENCES journal_attachments(id),
                reason TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute("INSERT OR IGNORE INTO permissions(code,label,group_code) VALUES ('journal.attachment','管理凭证附件','finance.journals')")
            db.executemany('INSERT OR IGNORE INTO role_permissions(role_code,permission_code) VALUES (?,?)',
                [(role, 'journal.attachment') for role in ('admin', 'finance')])
            db.execute('PRAGMA user_version = 73')

        if version < 74:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE IF NOT EXISTS after_sales_attachments (
                id INTEGER PRIMARY KEY,
                case_id INTEGER NOT NULL REFERENCES after_sales_cases(id),
                file_name TEXT NOT NULL, media_type TEXT NOT NULL,
                byte_count INTEGER NOT NULL, sha256 TEXT NOT NULL,
                content BLOB NOT NULL, reason TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('CREATE INDEX IF NOT EXISTS after_sales_attachments_case ON after_sales_attachments(case_id,id)')
            db.execute('''CREATE TABLE IF NOT EXISTS after_sales_attachment_reversals (
                id INTEGER PRIMARY KEY,
                attachment_id INTEGER NOT NULL UNIQUE REFERENCES after_sales_attachments(id),
                reason TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute("INSERT OR IGNORE INTO permissions(code,label,group_code) VALUES ('after_sales.attachment','管理售后附件','sales.after_sales')")
            db.executemany('INSERT OR IGNORE INTO role_permissions(role_code,permission_code) VALUES (?,?)',
                [(role, 'after_sales.attachment') for role in ('admin', 'seller', 'warehouse')])
            db.execute('PRAGMA user_version = 74')

        if version < 75:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE IF NOT EXISTS crm_quote_attachments (
                id INTEGER PRIMARY KEY,
                quote_id INTEGER NOT NULL REFERENCES crm_quotes(id),
                file_name TEXT NOT NULL, media_type TEXT NOT NULL,
                byte_count INTEGER NOT NULL, sha256 TEXT NOT NULL,
                content BLOB NOT NULL, reason TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('CREATE INDEX IF NOT EXISTS crm_quote_attachments_quote ON crm_quote_attachments(quote_id,id)')
            db.execute('''CREATE TABLE IF NOT EXISTS crm_quote_attachment_reversals (
                id INTEGER PRIMARY KEY,
                attachment_id INTEGER NOT NULL UNIQUE REFERENCES crm_quote_attachments(id),
                reason TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute("INSERT OR IGNORE INTO permissions(code,label,group_code) VALUES ('crm_quote.attachment','管理报价附件','sales.crm')")
            db.executemany('INSERT OR IGNORE INTO role_permissions(role_code,permission_code) VALUES (?,?)',
                [(role, 'crm_quote.attachment') for role in ('admin', 'seller')])
            db.execute('PRAGMA user_version = 75')

        if version < 76:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE IF NOT EXISTS crm_record_attachments (
                id INTEGER PRIMARY KEY,
                entity_kind TEXT NOT NULL CHECK (entity_kind IN ('contact','activity','opportunity')),
                entity_id INTEGER NOT NULL,
                file_name TEXT NOT NULL, media_type TEXT NOT NULL,
                byte_count INTEGER NOT NULL, sha256 TEXT NOT NULL,
                content BLOB NOT NULL, reason TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('CREATE INDEX IF NOT EXISTS crm_record_attachments_entity ON crm_record_attachments(entity_kind,entity_id,id)')
            db.execute('''CREATE TABLE IF NOT EXISTS crm_record_attachment_reversals (
                id INTEGER PRIMARY KEY,
                attachment_id INTEGER NOT NULL UNIQUE REFERENCES crm_record_attachments(id),
                reason TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute("INSERT OR IGNORE INTO permissions(code,label,group_code) VALUES ('crm.attachment','管理客户关系资料附件','sales.crm')")
            db.executemany('INSERT OR IGNORE INTO role_permissions(role_code,permission_code) VALUES (?,?)',
                [(role, 'crm.attachment') for role in ('admin', 'seller')])
            db.execute('PRAGMA user_version = 76')
