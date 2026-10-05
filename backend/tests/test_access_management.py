"""验证用户生命周期和权限目录在真实 SQLite 会话中的授权行为。"""

import sqlite3

from fastapi.testclient import TestClient

from app.core.database import connection, migrate
from app.main import app


def test_access_management(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "access.db"))
    base = "/api/v1"
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        assert client.post(f"{base}/setup/admin", json={
            "username": "admin", "password": "admin-password-123"
        }).status_code == 201

        def login(username, password):
            response = client.post(f"{base}/auth/login", json={"username": username, "password": password})
            assert response.status_code == 200, response.text
            return {"Authorization": f"Bearer {response.json()['token']}"}

        admin = login("admin", "admin-password-123")
        permissions = client.get(f"{base}/permissions", headers=admin).json()
        # 已登记权限必须都有中文名称；漏配时不可退回编码或笼统的占位文案。
        assert permissions
        assert all(any("\u4e00" <= char <= "\u9fff" for char in item["label"])
                   and item["label"] != item["code"]
                   and not item["label"].startswith("未命名权限") for item in permissions)
        assert len({item["code"] for item in permissions}) == len(permissions)
        # 入库单、出库单分别挂在仓库模块下，同名操作也可按各自代码独立授权。
        by_code = {item["code"]: item for item in permissions}
        assert by_code["receipt.post"]["group_path"] == [
            {"code": "warehouse", "label": "仓库管理"}, {"code": "warehouse.receipt", "label": "入库单"}]
        assert by_code["shipment.post"]["group_path"] == [
            {"code": "warehouse", "label": "仓库管理"}, {"code": "warehouse.shipment", "label": "出库单"}]
        assert all(len(item["group_path"]) == 2 and item["group_path"][0]["code"] != "other"
                   for item in permissions)
        with connection() as db:
            # 接口应实时使用数据库中的目录名称与归属，不能再由 Python 常量重建。
            db.execute("""UPDATE permission_groups SET label = '采购入库单'
                          WHERE code = 'warehouse.receipt'""")
        updated_permissions = client.get(f"{base}/permissions", headers=admin).json()
        assert next(item for item in updated_permissions if item["code"] == "receipt.post")[
            "group_path"][1]["label"] == "采购入库单"
        renamed = client.put(f"{base}/permissions/inventory.view/label", headers=admin,
                             json={"label": "  查看各仓库存量  "})
        assert renamed.status_code == 200, renamed.text
        assert renamed.json() == {"code": "inventory.view", "label": "查看各仓库存量"}
        with connection() as db:
            # 仅改变展示文案，角色授权继续引用原权限代码。
            assert db.execute("SELECT permission_code FROM role_permissions WHERE role_code = 'viewer'").fetchone()[0] == "inventory.view"
            assert db.execute("SELECT label FROM permissions WHERE code = 'inventory.view'").fetchone()[0] == "查看各仓库存量"
        worker_data = client.post(f"{base}/users", headers=admin, json={
            "username": "worker", "password": "worker-password-123", "roles": ["viewer"]
        }).json()
        worker = login("worker", "worker-password-123")
        assert worker_data["is_active"] is True
        assert client.get(f"{base}/permissions", headers=worker).status_code == 403
        assert client.put(f"{base}/permissions/inventory.view/label", headers=worker,
                          json={"label": "查看库存"}).status_code == 403
        assert client.put(f"{base}/permissions/not_found.view/label", headers=admin,
                          json={"label": "无效权限"}).status_code == 404
        for label in ["  ", "inventory.view", "A" * 61]:
            assert client.put(f"{base}/permissions/inventory.view/label", headers=admin,
                              json={"label": label}).status_code == 422
        assert client.post(f"{base}/roles", headers=worker, json={
            "code": "custom", "label": "自定义", "permissions": []
        }).status_code == 403

        # 自定义角色只接受服务端登记的权限；内置角色禁止修改。
        assert client.post(f"{base}/roles", headers=admin, json={
            "code": "stock_clerk", "label": "库存专员", "permissions": ["unknown.permission"]
        }).status_code == 422
        role = client.post(f"{base}/roles", headers=admin, json={
            "code": "stock_clerk", "label": "库存专员", "permissions": ["inventory.view"]
        })
        assert role.status_code == 201, role.text
        assert role.json()["is_builtin"] is False
        assert client.put(f"{base}/roles/admin", headers=admin, json={
            "label": "管理员", "permissions": []
        }).status_code == 409
        assert client.put(f"{base}/users/{worker_data['id']}/roles", headers=admin,
                          json={"roles": ["stock_clerk"]}).status_code == 200
        material = {"sku": "M-01", "name": "测试物料", "unit": "件"}
        assert client.post(f"{base}/materials", headers=worker, json=material).status_code == 403
        assert client.put(f"{base}/roles/stock_clerk", headers=admin, json={
            "label": "库存资料员", "permissions": ["inventory.view", "catalog.manage"]
        }).status_code == 200
        # 原登录令牌无需重发，服务端每次请求都按最新角色授权。
        assert client.post(f"{base}/materials", headers=worker, json=material).status_code == 201

        # 停用与重置密码都会撤销旧令牌；停用期间不能重新登录。
        assert client.put(f"{base}/users/{worker_data['id']}/status", headers=admin,
                          json={"is_active": False}).json()["is_active"] is False
        assert client.get(f"{base}/stock", headers=worker).status_code == 401
        assert client.post(f"{base}/auth/login", json={
            "username": "worker", "password": "worker-password-123"
        }).status_code == 401
        assert client.put(f"{base}/users/{worker_data['id']}/status", headers=admin,
                          json={"is_active": True}).status_code == 200
        worker = login("worker", "worker-password-123")
        assert client.post(f"{base}/users/{worker_data['id']}/reset-password", headers=admin,
                           json={"password": "new-worker-password-123"}).status_code == 204
        assert client.get(f"{base}/stock", headers=worker).status_code == 401
        assert client.post(f"{base}/auth/login", json={
            "username": "worker", "password": "worker-password-123"
        }).status_code == 401
        worker = login("worker", "new-worker-password-123")
        assert client.post(f"{base}/auth/change-password", headers=worker, json={
            "current_password": "wrong", "new_password": "final-worker-password-123"
        }).status_code == 400
        assert client.get(f"{base}/stock", headers=worker).status_code == 200
        assert client.post(f"{base}/auth/change-password", headers=worker, json={
            "current_password": "new-worker-password-123", "new_password": "final-worker-password-123"
        }).status_code == 204
        assert client.get(f"{base}/stock", headers=worker).status_code == 401
        login("worker", "final-worker-password-123")

        # 停用或撤销管理员权限时，始终保留一位启用的内置管理员。
        assert client.put(f"{base}/users/1/status", headers=admin,
                          json={"is_active": False}).status_code == 409
        second = client.post(f"{base}/users", headers=admin, json={
            "username": "backup", "password": "backup-password-123", "roles": ["admin"]
        }).json()
        backup = login("backup", "backup-password-123")
        assert client.put(f"{base}/users/1/status", headers=backup,
                          json={"is_active": False}).status_code == 200
        assert client.get(f"{base}/users", headers=admin).status_code == 401
        assert client.put(f"{base}/users/{second['id']}/roles", headers=backup,
                          json={"roles": ["viewer"]}).status_code == 409


def test_legacy_permission_codes_gain_labels(monkeypatch, tmp_path, remove_v39_schema):
    path = tmp_path / "legacy-permissions.db"
    monkeypatch.setenv("NEXORA_DB_PATH", str(path))
    with sqlite3.connect(path) as db:
        # 模拟 v24 旧库：权限表只有代码，迁移须保留已有角色关联所用的代码。
        # 物料参数与批次期初升级依赖旧版基础表，最小权限夹具补上空的历史表。
        db.execute("CREATE TABLE materials (id INTEGER PRIMARY KEY, sku TEXT, name TEXT, unit TEXT)")
        db.execute("CREATE TABLE suppliers (id INTEGER PRIMARY KEY, name TEXT)")
        db.execute("CREATE TABLE warehouses (id INTEGER PRIMARY KEY, code TEXT, name TEXT)")
        db.execute("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, created_at TEXT)")
        db.execute("CREATE TABLE stock_movements (id INTEGER PRIMARY KEY, warehouse_id INTEGER, material_id INTEGER, quantity TEXT)")
        db.execute("CREATE TABLE permissions (code TEXT PRIMARY KEY)")
        # 旧权限库的最小角色关联表，供新版权限种子验证升级路径。
        db.execute("CREATE TABLE role_permissions (role_code TEXT, permission_code TEXT)")
        db.execute("INSERT INTO permissions(code) VALUES ('bom.activate'), ('future.view')")
        remove_v39_schema(db)
        db.execute("PRAGMA user_version = 24")
    migrate()
    with connection() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 80
        labels = dict(db.execute("SELECT code, label FROM permissions").fetchall())
        assert labels["bom.activate"] == "启用生产物料清单版本"
        assert labels["future.view"] == "未命名权限"
        assert labels["purchase_request.review"] == "审批采购申请"
        # 升级后新增权限必须同时登记中文名称，不再产生裸代码展示。
        try:
            db.execute("INSERT INTO permissions(code) VALUES ('new.view')")
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("缺少名称的权限不应写入目录")
        try:
            db.execute("INSERT INTO permissions(code, label) VALUES ('new.view', '查看新功能')")
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("缺少所属单据的权限不应写入目录")
        try:
            db.execute("""INSERT INTO permissions(code, label, group_code)
                          VALUES ('new.view', '查看新功能', 'warehouse')""")
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("操作权限不能直接挂在模块节点下")
        assert db.execute("""SELECT group_code FROM permissions
                             WHERE code = 'future.view'""").fetchone()[0] == "other.unclassified"


def test_receipt_action_does_not_grant_same_action_on_shipment(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "document-actions.db"))
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        assert client.post("/api/v1/setup/admin", json={
            "username": "admin", "password": "admin-password-123"
        }).status_code == 201
        token = client.post("/api/v1/auth/login", json={
            "username": "admin", "password": "admin-password-123"
        }).json()["token"]
        admin = {"Authorization": f"Bearer {token}"}
        assert client.post("/api/v1/roles", headers=admin, json={
            "code": "receipt_approver", "label": "入库确认员", "permissions": ["receipt.post"]
        }).status_code == 201
        assert client.post("/api/v1/users", headers=admin, json={
            "username": "clerk", "password": "clerk-password-123", "roles": ["receipt_approver"]
        }).status_code == 201
        clerk_token = client.post("/api/v1/auth/login", json={
            "username": "clerk", "password": "clerk-password-123"
        }).json()["token"]
        clerk = {"Authorization": f"Bearer {clerk_token}"}
        assert client.get("/api/v1/auth/me", headers=clerk).json()["permissions"] == ["receipt.post"]
        # 同属仓库模块不会继承兄弟单据的操作；入库权限先过授权再查找单据。
        assert client.post("/api/v1/shipments/1/post", headers=clerk).status_code == 403
        assert client.post("/api/v1/receipts/1/post", headers=clerk).status_code == 404


def test_code_labels_are_repaired_without_overwriting_custom_names(monkeypatch, tmp_path, remove_v39_schema):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "permission-labels.db"))
    migrate()
    with connection() as db:
        # 模拟旧版服务端：部分权限被保存为代码，另有管理员自定义名称。
        db.execute("UPDATE permissions SET label = code WHERE code IN ('bom.activate', 'finance.record')")
        db.execute("UPDATE permissions SET label = '未命名权限' WHERE code = 'production.view'")
        db.execute("UPDATE permissions SET label = '查看仓库实时库存' WHERE code = 'inventory.view'")
        grants = db.execute("SELECT role_code, permission_code FROM role_permissions ORDER BY 1, 2").fetchall()
        db.execute("DROP TABLE inventory_cost_inputs")
        db.execute("DELETE FROM role_permissions WHERE permission_code LIKE 'inventory_valuation.%'")
        db.execute("DELETE FROM permissions WHERE code LIKE 'inventory_valuation.%'")
        db.execute("DELETE FROM permission_groups WHERE code = 'finance.inventory_valuation'")
        db.execute("DELETE FROM role_permissions WHERE permission_code = 'purchase_return.submit'")
        db.execute("DELETE FROM permissions WHERE code = 'purchase_return.submit'")
        db.execute("DELETE FROM role_permissions WHERE permission_code IN ('purchase_report.view', 'inventory_report.view')")
        db.execute("DELETE FROM permissions WHERE code IN ('purchase_report.view', 'inventory_report.view')")
        db.execute("DELETE FROM permission_groups WHERE code IN ('purchase.reports', 'warehouse.reports')")
        db.execute("DROP TABLE stock_adjustment_reversals")
        db.execute("DROP TABLE stock_adjustment_lines")
        db.execute("DROP TABLE stock_adjustments")
        db.execute("DELETE FROM role_permissions WHERE permission_code LIKE 'adjustment.%'")
        db.execute("DELETE FROM permissions WHERE code LIKE 'adjustment.%'")
        db.execute("DELETE FROM permission_groups WHERE code = 'warehouse.adjustment'")
        db.execute("DROP TABLE warehouse_outbound_reversals")
        db.execute("DROP TABLE warehouse_outbound_lines")
        db.execute("DROP TABLE warehouse_outbounds")
        db.execute("DELETE FROM role_permissions WHERE permission_code LIKE 'other_outbound.%'")
        db.execute("DELETE FROM permissions WHERE code LIKE 'other_outbound.%'")
        db.execute("DELETE FROM permission_groups WHERE code = 'warehouse.other_outbound'")
        db.execute("DROP TABLE warehouse_inbound_reversals")
        db.execute("DROP TABLE warehouse_inbound_lines")
        db.execute("DROP TABLE warehouse_inbounds")
        db.execute("DELETE FROM role_permissions WHERE permission_code LIKE 'other_inbound.%'")
        db.execute("DELETE FROM permissions WHERE code LIKE 'other_inbound.%'")
        db.execute("DELETE FROM permission_groups WHERE code = 'warehouse.other_inbound'")
        db.execute("DROP TABLE purchase_goods_receipt_lines")
        db.execute("DROP TABLE purchase_goods_receipts")
        db.execute("DELETE FROM role_permissions WHERE permission_code LIKE 'purchase_receiving.%'")
        db.execute("DELETE FROM permissions WHERE code LIKE 'purchase_receiving.%'")
        db.execute("DELETE FROM permission_groups WHERE code = 'purchase.receiving'")
        # 人工回退版本测试须一并移除新版申请结构，才能模拟真实 v25 库。
        db.execute("DROP TABLE purchase_order_request_links")
        db.execute("DROP TABLE purchase_request_lines")
        db.execute("DROP TABLE purchase_requests")
        db.execute("DELETE FROM role_permissions WHERE permission_code LIKE 'purchase_request.%'")
        db.execute("DELETE FROM permissions WHERE code LIKE 'purchase_request.%'")
        db.execute("DELETE FROM permission_groups WHERE code = 'purchase.purchase_request'")
        db.execute("DROP TABLE supplier_materials")
        # 还原成升级前的 v25 表结构，验证中文修复与目录落库连续迁移。
        db.execute("DROP TRIGGER permissions_group_required_insert")
        db.execute("DROP TRIGGER permissions_group_required_update")
        db.execute("ALTER TABLE permissions DROP COLUMN group_code")
        db.execute("DROP TABLE permission_groups")
        # 回退版本夹具同步移除新版菜单表，模拟真实旧库。
        db.execute("DROP TABLE menu_icon_changes")
        db.execute("DROP TABLE menu_icons")
        remove_v39_schema(db)
        db.execute("PRAGMA user_version = 25")

    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        assert client.post("/api/v1/setup/admin", json={
            "username": "admin", "password": "admin-password-123"
        }).status_code == 201
        login = client.post("/api/v1/auth/login", json={
            "username": "admin", "password": "admin-password-123"
        })
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        labels = {item["code"]: item["label"] for item in
                  client.get("/api/v1/permissions", headers=headers).json()}
        assert labels["bom.activate"] == "启用生产物料清单版本"
        assert labels["finance.record"] == "登记收付款"
        assert labels["production.view"] == "查看生产业务"
        assert labels["inventory.view"] == "查看仓库实时库存"

    migrate()
    with connection() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 80
        assert db.execute("SELECT role_code, permission_code FROM role_permissions ORDER BY 1, 2").fetchall() == grants
        assert db.execute("SELECT label FROM permissions WHERE code = 'inventory.view'").fetchone()[0] == "查看仓库实时库存"
