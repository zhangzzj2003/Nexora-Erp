"""验证工单从启用 BOM 固定需料快照、状态流转和权限边界。"""

from approval_test_helpers import approve_document

from fastapi.testclient import TestClient

from app.main import app


def test_work_order_snapshot_permissions_and_lifecycle(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "work-orders.db"))
    with TestClient(app, client=("127.0.0.1", 12000)) as client:
        base = "/api/v1"
        client.post(f"{base}/setup/admin", json={"username": "admin", "password": "secure-pass-123"})

        def login(username: str) -> dict:
            token = client.post(f"{base}/auth/login", json={
                "username": username, "password": "secure-pass-123"}).json()["token"]
            return {"Authorization": f"Bearer {token}"}

        admin = login("admin")
        for username, role in (("planner", "planner"), ("warehouse", "warehouse"), ("viewer", "viewer")):
            assert client.post(f"{base}/users", headers=admin, json={
                "username": username, "password": "secure-pass-123", "roles": [role]}).status_code == 201
        planner, warehouse, viewer = login("planner"), login("warehouse"), login("viewer")
        product = client.post(f"{base}/materials", headers=admin, json={
            "sku": "FINISHED", "name": "成品", "unit": "件"}).json()["id"]
        component = client.post(f"{base}/materials", headers=admin, json={
            "sku": "PART", "name": "组件", "unit": "件"}).json()["id"]
        replacement_component = client.post(f"{base}/materials", headers=admin, json={
            "sku": "PART2", "name": "替代组件", "unit": "件"}).json()["id"]

        def make_bom(material_id: int, quantity: str) -> int:
            response = client.post(f"{base}/boms", headers=planner, json={
                "product_material_id": product, "base_quantity": "3",
                "lines": [{"component_material_id": material_id, "quantity": quantity}]})
            assert response.status_code == 201
            return response.json()["id"]

        first_bom = make_bom(component, "1")
        payload = {"bom_id": first_bom, "warehouse_id": 1, "target_quantity": "1",
                   "reference": "WO-001", "note": "试产"}
        assert client.get(f"{base}/work-orders", headers=viewer).status_code == 403
        assert client.get(f"{base}/work-orders", headers=warehouse).status_code == 200
        assert client.post(f"{base}/work-orders", headers=warehouse, json=payload).status_code == 403
        assert client.post(f"{base}/work-orders", headers=planner, json=payload).status_code == 409
        assert client.post(f"{base}/work-orders", headers=planner, json={
            **payload, "warehouse_id": 999999}).status_code == 409  # BOM 仍未启用
        assert client.post(f"{base}/boms/{first_bom}/activate", headers=planner).status_code == 200
        for bad_quantity in ("0", "0.0001", "1000001", "NaN"):
            assert client.post(f"{base}/work-orders", headers=planner, json={
                **payload, "target_quantity": bad_quantity}).status_code == 422
        assert client.post(f"{base}/work-orders", headers=planner, json={
            **payload, "warehouse_id": 999999}).status_code == 422

        draft = client.post(f"{base}/work-orders", headers=planner, json=payload)
        assert draft.status_code == 201
        order_id = draft.json()["id"]
        assert draft.json()["status"] == "draft"
        assert draft.json()["bom_version"] == 1
        assert draft.json()["lines"][0]["required_quantity"] == "0.334"
        assert draft.json()["reference"] == "WO-001"
        assert client.post(f"{base}/work-orders/{order_id}/release", headers=warehouse).status_code == 403
        approve_document(client, admin, 'WorkOrder', order_id)
        assert client.post(f"{base}/work-orders/{order_id}/release", headers=planner).json()["status"] == "released"
        assert client.post(f"{base}/work-orders/{order_id}/release", headers=planner).status_code == 409
        assert client.post(f"{base}/work-orders/{order_id}/cancel", headers=planner).json()["status"] == "cancelled"
        assert client.post(f"{base}/work-orders/{order_id}/cancel", headers=planner).status_code == 409

        # 停用旧 BOM 后，已下达工单保留原需料；未下达草稿须按新版重建。
        released = client.post(f"{base}/work-orders", headers=planner, json=payload).json()
        approve_document(client, admin, 'WorkOrder', released['id'])
        assert client.post(f"{base}/work-orders/{released['id']}/release", headers=planner).status_code == 200
        pending = client.post(f"{base}/work-orders", headers=planner, json=payload).json()
        assert client.post(f"{base}/boms/{first_bom}/retire", headers=planner).status_code == 200
        assert client.post(f"{base}/work-orders/{pending['id']}/release", headers=planner).status_code == 409
        second_bom = make_bom(replacement_component, "2")
        assert client.post(f"{base}/boms/{second_bom}/activate", headers=planner).status_code == 200
        new_order = client.post(f"{base}/work-orders", headers=planner, json={
            **payload, "bom_id": second_bom}).json()
        assert new_order["bom_version"] == 2
        assert new_order["lines"][0]["component_material_id"] == replacement_component
        history = client.get(f"{base}/work-orders", headers=warehouse).json()
        old = next(item for item in history if item["id"] == released["id"])
        assert old["lines"][0]["component_material_id"] == component
        assert old["lines"][0]["required_quantity"] == "0.334"
        assert client.get(f"{base}/movements", headers=admin).json() == []


def test_work_order_rejects_component_requirement_over_limit(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "work-order-limit.db"))
    with TestClient(app, client=("127.0.0.1", 12000)) as client:
        base = "/api/v1"
        client.post(f"{base}/setup/admin", json={"username": "admin", "password": "secure-pass-123"})
        token = client.post(f"{base}/auth/login", json={
            "username": "admin", "password": "secure-pass-123"}).json()["token"]
        auth = {"Authorization": f"Bearer {token}"}
        product = client.post(f"{base}/materials", headers=auth, json={
            "sku": "P", "name": "成品", "unit": "件"}).json()["id"]
        component = client.post(f"{base}/materials", headers=auth, json={
            "sku": "C", "name": "组件", "unit": "件"}).json()["id"]
        bom = client.post(f"{base}/boms", headers=auth, json={
            "product_material_id": product, "base_quantity": "0.001",
            "lines": [{"component_material_id": component, "quantity": "1000000"}]}).json()["id"]
        client.post(f"{base}/boms/{bom}/activate", headers=auth)
        assert client.post(f"{base}/work-orders", headers=auth, json={
            "bom_id": bom, "warehouse_id": 1, "target_quantity": "2"}).status_code == 422
        assert client.get(f"{base}/work-orders", headers=auth).json() == []
