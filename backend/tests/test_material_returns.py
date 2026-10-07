"""验证退料更正的原单来源、累计上限、库存流水与工单净领料。"""

from approval_test_helpers import approve_document

from fastapi.testclient import TestClient

from app.main import app


def test_material_return_partial_reissue_and_permissions(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "material-return.db"))
    with TestClient(app, client=("127.0.0.1", 12000)) as client:
        base = "/api/v1"
        client.post(f"{base}/setup/admin", json={"username": "admin", "password": "secure-pass-123"})

        def login(username: str) -> dict:
            token = client.post(f"{base}/auth/login", json={
                "username": username, "password": "secure-pass-123"}).json()["token"]
            return {"Authorization": f"Bearer {token}"}

        admin = login("admin")
        for username, role in (("planner", "planner"), ("warehouse", "warehouse"), ("viewer", "viewer")):
            client.post(f"{base}/users", headers=admin, json={
                "username": username, "password": "secure-pass-123", "roles": [role]})
        planner, warehouse, viewer = login("planner"), login("warehouse"), login("viewer")
        supplier = client.post(f"{base}/suppliers", headers=admin, json={"name": "供货方"}).json()["id"]
        product = client.post(f"{base}/materials", headers=admin, json={
            "sku": "FIN", "name": "成品", "unit": "件"}).json()["id"]
        component = client.post(f"{base}/materials", headers=admin, json={
            "sku": "PART", "name": "组件", "unit": "件"}).json()["id"]
        receipt = client.post(f"{base}/receipts", headers=admin, json={
            "supplier_id": supplier, "warehouse_id": 1,
            "lines": [{"material_id": component, "quantity": "4"}]}).json()["id"]
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, admin, 'Receipt', receipt)
        assert client.post(f"{base}/receipts/{receipt}/post", headers=admin).status_code == 200
        bom = client.post(f"{base}/boms", headers=planner, json={
            "product_material_id": product, "base_quantity": "1",
            "lines": [{"component_material_id": component, "quantity": "2"}]}).json()["id"]
        client.post(f"{base}/boms/{bom}/activate", headers=planner)
        target_warehouse = client.post(f"{base}/warehouses", headers=admin, json={
            "code": "PROD", "name": "成品仓"}).json()["id"]
        order = client.post(f"{base}/work-orders", headers=planner, json={
            "bom_id": bom, "warehouse_id": target_warehouse, "target_quantity": "1"}).json()
        approve_document(client, admin, 'WorkOrder', order['id'])
        client.post(f"{base}/work-orders/{order['id']}/release", headers=planner)
        issue = client.post(f"{base}/material-issues", headers=planner, json={
            "work_order_id": order["id"], "warehouse_id": 1,
            "lines": [{"work_order_line_id": order["lines"][0]["id"], "quantity": "2"}]}).json()
        approve_document(client, admin, 'MaterialIssue', issue['id'])
        assert client.post(f"{base}/material-issues/{issue['id']}/post", headers=warehouse).status_code == 200
        issue_line_id = issue["lines"][0]["id"]
        payload = {"material_issue_id": issue["id"], "reason": "未使用，退回原仓",
                   "lines": [{"material_issue_line_id": issue_line_id, "quantity": "1"}]}

        assert client.get(f"{base}/material-returns", headers=viewer).status_code == 403
        assert client.post(f"{base}/material-returns", headers=viewer, json=payload).status_code == 403
        assert client.post(f"{base}/material-returns", headers=planner, json={
            **payload, "reason": "  "}).status_code == 422
        for invalid in ("0", "0.0001", "NaN"):
            assert client.post(f"{base}/material-returns", headers=planner, json={
                **payload, "lines": [{"material_issue_line_id": issue_line_id, "quantity": invalid}]}).status_code == 422
        assert client.post(f"{base}/material-returns", headers=planner, json={
            **payload, "lines": payload["lines"] * 2}).status_code == 422
        assert client.post(f"{base}/material-returns", headers=planner, json={
            **payload, "lines": [{"material_issue_line_id": 99999, "quantity": "1"}]}).status_code == 422
        assert client.post(f"{base}/material-returns", headers=planner, json={
            **payload, "lines": [{"material_issue_line_id": issue_line_id, "quantity": "3"}]}).status_code == 409
        first = client.post(f"{base}/material-returns", headers=planner, json=payload)
        assert first.status_code == 201
        return_id = first.json()["id"]
        stale = client.post(f"{base}/material-returns", headers=planner, json={
            **payload, "lines": [{"material_issue_line_id": issue_line_id, "quantity": "2"}]}).json()["id"]
        assert client.post(f"{base}/material-returns/{return_id}/post", headers=planner).status_code == 403
        approve_document(client, admin, 'MaterialReturn', return_id)
        assert client.post(f"{base}/material-returns/{return_id}/post", headers=warehouse).status_code == 200
        assert client.post(f"{base}/material-returns/{return_id}/post", headers=warehouse).status_code == 409
        assert client.post(f"{base}/material-returns/{return_id}/cancel", headers=warehouse).status_code == 409
        before_stale = len(client.get(f"{base}/movements", headers=admin).json())
        assert client.post(f"{base}/material-returns/{stale}/post", headers=warehouse).status_code == 409
        assert len(client.get(f"{base}/movements", headers=admin).json()) == before_stale
        assert client.post(f"{base}/material-returns/{stale}/cancel", headers=warehouse).status_code == 200

        movement = client.get(f"{base}/movements", headers=admin).json()[0]
        assert movement["source_type"] == "material_return"
        assert movement["material_return_id"] == return_id
        assert movement["source_line_id"] == first.json()["lines"][0]["id"]
        assert movement["warehouse_id"] == 1
        assert movement["quantity"] == "1"
        assert all(item["quantity"] == "0" for item in client.get(
            f"{base}/stock?warehouse_id={target_warehouse}", headers=admin).json())
        current = client.get(f"{base}/work-orders", headers=planner).json()[0]["lines"][0]
        assert current["issued_quantity"] == "1"
        assert current["remaining_quantity"] == "1.000"
        issue_now = client.get(f"{base}/material-issues", headers=planner).json()[0]["lines"][0]
        assert issue_now["returned_quantity"] == "1"
        assert issue_now["returnable_quantity"] == "1"

        # 已退的需料可重新领用，库存回到同一仓库且不覆盖原领料记录。
        reissue = client.post(f"{base}/material-issues", headers=planner, json={
            "work_order_id": order["id"], "warehouse_id": 1,
            "lines": [{"work_order_line_id": order["lines"][0]["id"], "quantity": "1"}]}).json()["id"]
        approve_document(client, admin, 'MaterialIssue', reissue)
        assert client.post(f"{base}/material-issues/{reissue}/post", headers=warehouse).status_code == 200
        assert client.get(f"{base}/work-orders", headers=planner).json()[0]["lines"][0]["remaining_quantity"] == "0.000"
        assert client.get(f"{base}/stock?warehouse_id=1", headers=admin).json()[1]["quantity"] == "2"
