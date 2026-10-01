"""本地 SQLite 连接与版本迁移。"""

import os
import sqlite3
import uuid
from contextlib import contextmanager
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
        if version > 50:
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
            # 老客户待管理员分配；历史订单保留创建商务，避免客户转交扩大金额访问范围。
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS customer_profiles (
                customer_id INTEGER PRIMARY KEY REFERENCES customers(id), owner_id INTEGER REFERENCES users(id),
                contact_name TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',
                address TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
                version INTEGER NOT NULL DEFAULT 1 CHECK(version>0))""")
            # 兼容早期只有权限目录的数据库，完整业务库仍回填历史归属。
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='customers'").fetchone():
                db.execute("INSERT OR IGNORE INTO customer_profiles(customer_id) SELECT id FROM customers")
            db.execute("CREATE INDEX IF NOT EXISTS customer_profiles_owner ON customer_profiles(owner_id,customer_id)")
            db.execute("""CREATE TABLE IF NOT EXISTS sales_order_owners (
                order_id INTEGER PRIMARY KEY REFERENCES sales_orders(id), owner_id INTEGER REFERENCES users(id),
                version INTEGER NOT NULL DEFAULT 1 CHECK(version>0))""")
            # 兼容早期只有权限目录的数据库，完整业务库仍回填历史归属。
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sales_orders'").fetchone():
                db.execute("INSERT OR IGNORE INTO sales_order_owners(order_id,owner_id) SELECT id,created_by FROM sales_orders")
            db.execute("CREATE INDEX IF NOT EXISTS sales_order_owners_owner ON sales_order_owners(owner_id,order_id)")
            db.execute("""CREATE TABLE IF NOT EXISTS customer_changes (
                id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id),
                order_id INTEGER REFERENCES sales_orders(id), action TEXT NOT NULL,
                before_json TEXT, after_json TEXT NOT NULL, reason TEXT NOT NULL,
                changed_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
            for code,label,group in [('customer.view','查看本人客户资料','sales.customer'),
                                     ('sales_amount.all','查看全部销售金额','sales.sales')]:
                db.execute("INSERT OR IGNORE INTO permissions(code,label,group_code) VALUES (?,?,?)",(code,label,group))
            db.executemany("INSERT OR IGNORE INTO role_permissions(role_code,permission_code) VALUES (?,?)",
                [('admin','customer.view'),('seller','customer.view'),('admin','sales_amount.all'),('finance','sales_amount.all'),('finance','sales.view')])
            db.execute("PRAGMA user_version = 46")

        if version < 47:
            # 仅结构迁移使用底层 DDL；业务读写仍走 ORM 会话。
            from sqlalchemy.schema import CreateTable
            from sqlalchemy.dialects import sqlite
            from app.core.models import Base
            for name in ('trade_line_terms','journal_auxiliaries','party_openings','party_opening_payments','bank_statements','bank_matches','finance_tool_audits'):
                db.execute(str(CreateTable(Base.metadata.tables[name], if_not_exists=True).compile(dialect=sqlite.dialect())))
            db.execute('PRAGMA user_version = 47')

        if version < 48:
            from sqlalchemy.schema import CreateTable
            from sqlalchemy.dialects import sqlite
            from app.core.models import Base
            for name in ('sales_work_allocations','inventory_lots','movement_lots','trace_audits'):
                db.execute(str(CreateTable(Base.metadata.tables[name], if_not_exists=True).compile(dialect=sqlite.dialect())))
            db.execute("INSERT OR IGNORE INTO permissions(code,label,group_code) VALUES ('trace.view','查看单据与批次溯源','warehouse.inventory')")
            db.executemany("INSERT OR IGNORE INTO role_permissions(role_code,permission_code) VALUES (?,'trace.view')",[(role,) for role in ('admin','warehouse','seller','planner')])
            # 计划员需要共享销售数量以分配工单；金额仍由独立授权脱敏。
            db.execute("INSERT OR IGNORE INTO role_permissions(role_code,permission_code) VALUES ('planner','sales.view')")
            db.execute('PRAGMA user_version = 48')

        if version < 49:
            from sqlalchemy.schema import CreateTable
            from sqlalchemy.dialects import sqlite
            from app.core.models import Base
            for name in ('material_planning_policies','work_centers','production_schedules','quality_dispositions','production_quality_costs','production_plan_audits'):
                db.execute(str(CreateTable(Base.metadata.tables[name],if_not_exists=True).compile(dialect=sqlite.dialect())))
            db.execute('PRAGMA user_version = 49')

        if version < 50:
            from sqlalchemy.schema import CreateTable
            from sqlalchemy.dialects import sqlite
            from app.core.models import Base
            for name in ('purchase_approval_policies','purchase_request_profiles','purchase_approval_stages','purchase_approval_audits'):
                db.execute(str(CreateTable(Base.metadata.tables[name],if_not_exists=True).compile(dialect=sqlite.dialect())))
            db.execute('PRAGMA user_version = 50')
