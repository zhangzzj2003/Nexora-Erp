"""验证移动平均、来源沿用、缺价隔离以及人工核价修订留痕。"""

from fastapi.testclient import TestClient

from app.core.database import connection, migrate
from app.main import app


def test_moving_average_and_late_price_audit(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "valuation.db"))
    with TestClient(app, client=("127.0.0.1", 12000)) as client:
        base = "/api/v1"
        client.post(f"{base}/setup/admin", json={"username": "admin", "password": "secure-pass-123"})

        def login(username):
            token = client.post(f"{base}/auth/login", json={
                "username": username, "password": "secure-pass-123"}).json()["token"]
            return {"Authorization": f"Bearer {token}"}

        admin = login("admin")
        client.post(f"{base}/users", headers=admin, json={
            "username": "viewer", "password": "secure-pass-123", "roles": ["viewer"]})
        viewer = login("viewer")
        url = f"{base}/inventory/valuation"
        assert client.get(url, headers=viewer).status_code == 403
        supplier = client.post(f"{base}/suppliers", headers=admin,
                               json={"name": "供应商"}).json()["id"]
        customer = client.post(f"{base}/customers", headers=admin,
                               json={"name": "客户"}).json()["id"]
        material = client.post(f"{base}/materials", headers=admin,
                               json={"sku": "COST", "name": "成本物料", "unit": "件"}).json()["id"]
        receipt_movements = []
        for price in ("5", "10"):
            order = client.post(f"{base}/purchase-orders", headers=admin, json={
                "supplier_id": supplier,
                "lines": [{"material_id": material, "quantity": "10", "unit_price": price}]}).json()["id"]
            assert client.post(f"{base}/purchase-orders/{order}/confirm",
                               headers=admin).status_code == 200
            receipt = client.post(f"{base}/receipts", headers=admin, json={
                "supplier_id": supplier, "purchase_order_id": order,
                "lines": [{"material_id": material, "quantity": "10"}]}).json()["id"]
            assert client.post(f"{base}/receipts/{receipt}/post", headers=admin).status_code == 200
            receipt_movements.append(client.get(f"{base}/movements", headers=admin).json()[0]["id"])
        snapshot = client.get(url, headers=admin).json()
        assert snapshot["total_amount"] == "150.00"
        assert snapshot["materials"][0]["average_unit_cost"] == "7.5000"
        assert client.post(f"{url}/inputs", headers=admin, json={
            "movement_id": receipt_movements[0], "unit_cost": "1", "reference": "X",
            "reason": "错误覆盖"}).status_code == 409

        order = client.post(f"{base}/sales-orders", headers=admin, json={
            "customer_id": customer,
            "lines": [{"material_id": material, "quantity": "5", "unit_price": "20"}]}).json()["id"]
        client.post(f"{base}/sales-orders/{order}/confirm", headers=admin)
        shipment = client.post(f"{base}/shipments", headers=admin, json={
            "sales_order_id": order, "warehouse_id": 1,
            "lines": [{"material_id": material, "quantity": "5"}]}).json()
        client.post(f"{base}/shipments/{shipment['id']}/post", headers=admin)
        assert client.get(url, headers=admin).json()["total_amount"] == "112.50"
        returned = client.post(f"{base}/sales-returns", headers=admin, json={
            "shipment_id": shipment["id"], "warehouse_id": 1, "reason": "退回",
            "lines": [{"shipment_line_id": shipment["lines"][0]["id"], "quantity": "2"}]}).json()["id"]
        client.post(f"{base}/sales-returns/{returned}/post", headers=admin)
        assert client.get(url, headers=admin).json()["total_amount"] == "127.50"

        inbound = client.post(f"{base}/warehouse-inbounds", headers=admin, json={
            "warehouse_id": 1, "reason": "gift", "note": "赠品入库", "reference": "GIFT-1",
            "lines": [{"material_id": material, "quantity": "3"}]}).json()["id"]
        client.post(f"{base}/warehouse-inbounds/{inbound}/post", headers=admin)
        unpriced = client.get(url, headers=admin).json()
        movement_id = unpriced["unpriced_movement_ids"][0]
        assert unpriced["total_amount"] is None
        assert unpriced["materials"][0]["amount"] is None
        assert client.post(f"{url}/inputs", headers=viewer, json={
            "movement_id": movement_id, "unit_cost": "12", "reference": "INV-1",
            "reason": "赠品核价"}).status_code == 403
        assert client.post(f"{url}/inputs", headers=admin, json={
            "movement_id": movement_id, "unit_cost": "12", "reference": "INV-1",
            "reason": "赠品核价"}).status_code == 201
        assert client.post(f"{url}/inputs", headers=admin, json={
            "movement_id": movement_id, "unit_cost": "12", "reference": "INV-1",
            "reason": "误重复提交"}).status_code == 409
        priced = client.get(url, headers=admin).json()
        assert priced["total_amount"] == "163.50"
        assert priced["materials"][0]["quantity"] == "20"
        assert client.post(f"{url}/inputs", headers=admin, json={
            "movement_id": movement_id, "unit_cost": "11", "reference": "INV-2",
            "reason": "修订原核价"}).status_code == 201
        revised = client.get(url, headers=admin).json()
        assert revised["total_amount"] == "160.50"
        source = next(item for item in revised["movements"] if item["id"] == movement_id)
        assert source["cost_source"] == "manual"
        assert source["unit_cost"] == "11.0000"
        assert source["cost_input_id"] is not None
        history = client.get(f"{url}/inputs", headers=admin).json()
        assert [item["unit_cost"] for item in history] == ["11", "12"]
        assert all(item["created_by_name"] == "admin" for item in history)


def test_unpriced_stock_clears_only_after_full_depletion(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "unpriced.db"))
    with TestClient(app, client=("127.0.0.1", 12000)) as client:
        base = "/api/v1"
        client.post(f"{base}/setup/admin", json={"username": "admin", "password": "secure-pass-123"})
        token = client.post(f"{base}/auth/login", json={
            "username": "admin", "password": "secure-pass-123"}).json()["token"]
        admin = {"Authorization": f"Bearer {token}"}
        material = client.post(f"{base}/materials", headers=admin, json={
            "sku": "OLD", "name": "旧库存", "unit": "件"}).json()["id"]
        inbound = client.post(f"{base}/warehouse-inbounds", headers=admin, json={
            "warehouse_id": 1, "reason": "opening", "note": "期初入库",
            "lines": [{"material_id": material, "quantity": "2"}]}).json()["id"]
        client.post(f"{base}/warehouse-inbounds/{inbound}/post", headers=admin)
        assert client.get(f"{base}/inventory/valuation", headers=admin).json()["total_amount"] is None
        outbound = client.post(f"{base}/warehouse-outbounds", headers=admin, json={
            "warehouse_id": 1, "reason": "sample", "note": "样品出库",
            "lines": [{"material_id": material, "quantity": "2"}]}).json()["id"]
        assert client.post(f"{base}/warehouse-outbounds/{outbound}/post", headers=admin).status_code == 200
        result = client.get(f"{base}/inventory/valuation", headers=admin).json()
        assert result["materials"][0]["amount"] == "0.00"
        assert result["total_amount"] == "0.00"


def test_v35_upgrade_preserves_stock_and_adds_cost_permissions(monkeypatch, tmp_path, remove_v39_schema):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "upgrade.db"))
    migrate()
    with connection() as db:
        db.execute("INSERT INTO materials(sku, name, unit) VALUES ('OLD', '旧物料', '件')")
        db.execute("DROP TABLE inventory_cost_inputs")
        db.execute("DELETE FROM role_permissions WHERE permission_code LIKE 'inventory_valuation.%'")
        db.execute("DELETE FROM permissions WHERE code LIKE 'inventory_valuation.%'")
        db.execute("DELETE FROM permission_groups WHERE code = 'finance.inventory_valuation'")
        # 回退版本夹具同步移除新版菜单表，模拟真实旧库。
        db.execute("DROP TABLE menu_icon_changes")
        db.execute("DROP TABLE menu_icons")
        remove_v39_schema(db)
        db.execute("PRAGMA user_version = 35")
    migrate()
    migrate()
    with connection() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 64
        assert db.execute("SELECT name FROM materials WHERE sku = 'OLD'").fetchone()[0] == "旧物料"
        assert db.execute("SELECT COUNT(*) FROM inventory_cost_inputs").fetchone()[0] == 0
        grants = set(db.execute("""SELECT role_code FROM role_permissions
            WHERE permission_code = 'inventory_valuation.view'""").fetchall())
        assert {row[0] for row in grants} == {"admin", "finance"}
