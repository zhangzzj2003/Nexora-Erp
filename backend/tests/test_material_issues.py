"""验证分批领料、库存与剩余需料的事务核对，以及不可改写的流水来源。"""

from approval_test_helpers import approve_document

from fastapi.testclient import TestClient

from app.main import app


def test_material_issue_partial_post_and_permissions(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "material-issue.db"))
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
        supplier = client.post(f"{base}/suppliers", headers=admin, json={"name": "组件供应商"}).json()["id"]
        product = client.post(f"{base}/materials", headers=admin, json={
            "sku": "FIN", "name": "成品", "unit": "件"}).json()["id"]
        components = [client.post(f"{base}/materials", headers=admin, json={
            "sku": f"PART-{index}", "name": f"组件{index}", "unit": "件"}).json()["id"]
            for index in (1, 2)]
        receipt = client.post(f"{base}/receipts", headers=admin, json={
            "supplier_id": supplier, "warehouse_id": 1,
            "lines": [{"material_id": component, "quantity": "2"} for component in components]}).json()["id"]
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, admin, 'Receipt', receipt)
        assert client.post(f"{base}/receipts/{receipt}/post", headers=admin).status_code == 200
        second_warehouse = client.post(f"{base}/warehouses", headers=admin, json={
            "code": "PROD", "name": "生产仓"}).json()["id"]
        bom = client.post(f"{base}/boms", headers=planner, json={
            "product_material_id": product, "base_quantity": "1",
            "lines": [{"component_material_id": component, "quantity": "2"}
                      for component in components]}).json()["id"]
        client.post(f"{base}/boms/{bom}/activate", headers=planner)
        order = client.post(f"{base}/work-orders", headers=planner, json={
            "bom_id": bom, "warehouse_id": second_warehouse, "target_quantity": "1"}).json()
        order_id = order["id"]
        line_ids = [line["id"] for line in order["lines"]]
        payload = {"work_order_id": order_id, "warehouse_id": 1,
                   "reference": "ISSUE-001", "lines": [{"work_order_line_id": line_ids[0], "quantity": "1"}]}

        assert client.get(f"{base}/material-issues", headers=viewer).status_code == 403
        assert client.post(f"{base}/material-issues", headers=viewer, json=payload).status_code == 403
        assert client.post(f"{base}/material-issues", headers=planner, json=payload).status_code == 409
        approve_document(client, admin, 'WorkOrder', order_id)
        client.post(f"{base}/work-orders/{order_id}/release", headers=planner)
        for invalid in ("0", "0.0001", "NaN"):
            assert client.post(f"{base}/material-issues", headers=planner, json={
                **payload, "lines": [{"work_order_line_id": line_ids[0], "quantity": invalid}]}).status_code == 422
        assert client.post(f"{base}/material-issues", headers=planner, json={
            **payload, "lines": payload["lines"] * 2}).status_code == 422
        assert client.post(f"{base}/material-issues", headers=planner, json={
            **payload, "lines": [{"work_order_line_id": 99999, "quantity": "1"}]}).status_code == 422
        assert client.post(f"{base}/material-issues", headers=planner, json={
            **payload, "lines": [{"work_order_line_id": line_ids[0], "quantity": "3"}]}).status_code == 409
        assert client.post(f"{base}/material-issues", headers=planner, json={
            **payload, "warehouse_id": 99999}).status_code == 422
        draft = client.post(f"{base}/material-issues", headers=planner, json=payload)
        assert draft.status_code == 201
        issue_id = draft.json()["id"]
        assert client.get(f"{base}/work-orders", headers=planner).json()[0]["lines"][0]["remaining_quantity"] == "2.000"
        assert client.post(f"{base}/material-issues/{issue_id}/post", headers=planner).status_code == 403
        approve_document(client, admin, 'MaterialIssue', issue_id)
        assert client.post(f"{base}/material-issues/{issue_id}/post", headers=warehouse).status_code == 200
        assert client.post(f"{base}/material-issues/{issue_id}/post", headers=warehouse).status_code == 409
        assert client.post(f"{base}/material-issues/{issue_id}/cancel", headers=warehouse).status_code == 409
        current = client.get(f"{base}/work-orders", headers=planner).json()[0]
        assert current["status"] == "in_progress"
        assert current["lines"][0]["issued_quantity"] == "1"
        assert current["lines"][0]["remaining_quantity"] == "1.000"
        assert client.post(f"{base}/work-orders/{order_id}/cancel", headers=planner).status_code == 409
        movement = client.get(f"{base}/movements", headers=admin).json()[0]
        assert movement["source_type"] == "material_issue"
        assert movement["material_issue_id"] == issue_id
        assert movement["source_line_id"] == draft.json()["lines"][0]["id"]
        assert movement["quantity"] == "-1"

        # 第一组件在生产仓可用、第二组件缺货时，整张双行领料单不能部分扣料。
        transfer = client.post(f"{base}/transfers", headers=admin, json={
            "from_warehouse_id": 1, "to_warehouse_id": second_warehouse,
            "lines": [{"material_id": components[0], "quantity": "1"}]}).json()["id"]
        approve_document(client, admin, 'Transfer', transfer)
        client.post(f"{base}/transfers/{transfer}/post", headers=admin)
        mixed = client.post(f"{base}/material-issues", headers=warehouse, json={
            **payload, "warehouse_id": second_warehouse,
            "lines": [{"work_order_line_id": line_id, "quantity": "1"} for line_id in line_ids]}).json()["id"]
        before_mixed = len(client.get(f"{base}/movements", headers=admin).json())
        assert client.post(f"{base}/material-issues/{mixed}/post", headers=warehouse).status_code == 409
        assert len(client.get(f"{base}/movements", headers=admin).json()) == before_mixed
        assert client.get(f"{base}/stock?warehouse_id={second_warehouse}", headers=admin).json()[1]["quantity"] == "1"
        assert client.post(f"{base}/material-issues/{mixed}/cancel", headers=warehouse).status_code == 200
        transfer_back = client.post(f"{base}/transfers", headers=admin, json={
            "from_warehouse_id": second_warehouse, "to_warehouse_id": 1,
            "lines": [{"material_id": components[0], "quantity": "1"}]}).json()["id"]
        approve_document(client, admin, 'Transfer', transfer_back)
        client.post(f"{base}/transfers/{transfer_back}/post", headers=admin)

        # 两份草稿都可以建立，先确认的一份会让后确认的超出剩余需料。
        remaining = {**payload, "lines": [{"work_order_line_id": line_ids[0], "quantity": "1"}]}
        first = client.post(f"{base}/material-issues", headers=warehouse, json=remaining).json()["id"]
        stale = client.post(f"{base}/material-issues", headers=warehouse, json=remaining).json()["id"]
        approve_document(client, admin, 'MaterialIssue', first)
        assert client.post(f"{base}/material-issues/{first}/post", headers=warehouse).status_code == 200
        assert client.post(f"{base}/material-issues/{stale}/post", headers=warehouse).status_code == 409
        assert client.post(f"{base}/material-issues/{stale}/cancel", headers=warehouse).status_code == 200
        assert client.get(f"{base}/work-orders", headers=planner).json()[0]["lines"][0]["remaining_quantity"] == "0.000"
        assert client.get(f"{base}/stock?warehouse_id=1", headers=admin).json()[1]["quantity"] == "0"
        assert client.get(f"{base}/stock?warehouse_id={second_warehouse}", headers=admin).json()[0]["quantity"] == "0"

        # 任一组件缺货都必须整单回滚，不得先扣另一组件。
        shortage = client.post(f"{base}/material-issues", headers=warehouse, json={
            **payload, "lines": [{"work_order_line_id": line_ids[1], "quantity": "2"}],
            "warehouse_id": second_warehouse}).json()["id"]
        before = len(client.get(f"{base}/movements", headers=admin).json())
        assert client.post(f"{base}/material-issues/{shortage}/post", headers=warehouse).status_code == 409
        assert len(client.get(f"{base}/movements", headers=admin).json()) == before
        assert client.get(f"{base}/material-issues", headers=warehouse).json()[0]["status"] == "draft"
