import sqlite3

from fastapi.testclient import TestClient

from app.main import app
from app.core.database import migrate


def test_health_contract(monkeypatch, tmp_path):
    # 健康检查也会触发启动迁移，测试数据库必须与用户数据隔离。
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "health.db"))
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok", "service": "nexora-api", "version": "0.1.0"
        }


def test_openapi_includes_health_schema(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "schema.db"))
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()
        assert "/api/v1/health" in schema["paths"]
        assert "HealthResponse" in schema["components"]["schemas"]


def test_server_identity_persists_and_remote_bootstrap_is_forbidden(monkeypatch, tmp_path):
    # 身份随 SQLite 一起保留，未初始化期间局域网设备不能抢注管理员。
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "identity.db"))
    monkeypatch.setenv("NEXORA_INSTANCE_NAME", "测试服务端")
    with TestClient(app, client=("192.168.1.25", 11223)) as remote:
        info = remote.get("/api/v1/server/info").json()
        assert info["name"] == "测试服务端"
        assert info["ready"] is False
        assert remote.post("/api/v1/setup/admin", json={
            "username": "attacker", "password": "secure-pass-123"
        }).status_code == 403
    with TestClient(app, client=("127.0.0.1", 11224)) as local:
        assert local.get("/api/v1/server/info").json()["id"] == info["id"]
        assert local.post("/api/v1/setup/admin", json={
            "username": "admin", "password": "secure-pass-123"
        }).status_code == 201
        assert local.get("/api/v1/server/info").json()["ready"] is True


def test_existing_v1_database_keeps_users(monkeypatch, tmp_path):
    # 用完整的旧版业务表升级，验证历史账号、入库和库存流水都留在主仓库。
    database = tmp_path / "existing.db"
    monkeypatch.setenv("NEXORA_DB_PATH", str(database))
    with sqlite3.connect(database) as db:
        db.executescript("""
            CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, password_hash TEXT);
            CREATE TABLE roles (code TEXT PRIMARY KEY, label TEXT NOT NULL);
            CREATE TABLE permissions (code TEXT PRIMARY KEY);
            CREATE TABLE role_permissions (role_code TEXT, permission_code TEXT);
            CREATE TABLE suppliers (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE materials (id INTEGER PRIMARY KEY, sku TEXT, name TEXT, unit TEXT);
            CREATE TABLE receipts (id INTEGER PRIMARY KEY, supplier_id INTEGER, reference TEXT,
                status TEXT, created_by INTEGER, posted_by INTEGER, created_at TEXT, posted_at TEXT);
            CREATE TABLE receipt_lines (id INTEGER PRIMARY KEY, receipt_id INTEGER,
                material_id INTEGER, quantity TEXT);
            CREATE TABLE stock_movements (id INTEGER PRIMARY KEY, material_id INTEGER,
                quantity TEXT, receipt_line_id INTEGER, created_at TEXT);
            INSERT INTO roles VALUES ('admin', '管理员');
            INSERT INTO users VALUES (7, 'existing', 'unchanged');
            INSERT INTO suppliers VALUES (1, '旧供应商');
            INSERT INTO materials VALUES (1, 'OLD', '旧物料', '件');
            INSERT INTO receipts VALUES (3, 1, 'REF', 'posted', 7, 7, '2026-01-01', '2026-01-02');
            INSERT INTO receipt_lines VALUES (5, 3, 1, '2.125');
            INSERT INTO stock_movements VALUES (8, 1, '2.125', 5, '2026-01-02');
        """)
        db.execute("PRAGMA user_version = 1")
    migrate()
    with sqlite3.connect(database) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 101
        assert db.execute("SELECT label FROM permissions WHERE code = 'bom.activate'").fetchone()[0] == "启用生产物料清单版本"
        assert db.execute("SELECT username, password_hash, is_active FROM users WHERE id = 7").fetchone() == (
            "existing", "unchanged", 1)
        assert db.execute("SELECT COUNT(*) FROM server_identity").fetchone()[0] == 1
        assert db.execute("SELECT is_builtin FROM roles WHERE code = 'admin'").fetchone()[0] == 1
        assert db.execute("SELECT receipt_id, warehouse_id FROM receipt_warehouses").fetchone() == (3, 1)
        assert db.execute("SELECT id, warehouse_id, quantity, source_type, source_id, source_line_id, created_by "
                          "FROM stock_movements").fetchone() == (8, 1, '2.125', 'receipt', 3, 5, 7)
        assert db.execute("SELECT COUNT(*) FROM receipt_order_links").fetchone()[0] == 0
