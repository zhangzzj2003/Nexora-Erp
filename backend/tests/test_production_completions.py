"""验证分批报工、质检、需料下限和合格成品的入库来源。"""

from approval_test_helpers import approve_document

from fastapi.testclient import TestClient

from app.main import app


def test_completion_quality_gate_and_partial_stock(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "completion.db"))
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
        component = client.post(f"{base}/materials", headers=admin, json={
            "sku": "PART", "name": "组件", "unit": "件"}).json()["id"]
        receipt = client.post(f"{base}/receipts", headers=admin, json={
            "supplier_id": supplier, "warehouse_id": 1,
            "lines": [{"material_id": component, "quantity": "4"}]}).json()["id"]
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, admin, 'Receipt', receipt)
        client.post(f"{base}/receipts/{receipt}/post", headers=admin)
        target_warehouse = client.post(f"{base}/warehouses", headers=admin, json={
            "code": "FIN", "name": "成品仓"}).json()["id"]
        bom = client.post(f"{base}/boms", headers=planner, json={
            "product_material_id": product, "base_quantity": "1",
            "lines": [{"component_material_id": component, "quantity": "2"}]}).json()["id"]
        client.post(f"{base}/boms/{bom}/activate", headers=planner)
        order = client.post(f"{base}/work-orders", headers=planner, json={
            "bom_id": bom, "warehouse_id": target_warehouse, "target_quantity": "2"}).json()
        order_id, line_id = order["id"], order["lines"][0]["id"]

        assert client.get(f"{base}/production-completions", headers=viewer).status_code == 403
        assert client.post(f"{base}/production-completions", headers=viewer, json={
            "work_order_id": order_id, "reported_quantity": "1"}).status_code == 403
        assert client.post(f"{base}/production-completions", headers=planner, json={
            "work_order_id": order_id, "reported_quantity": "1"}).status_code == 409
        client.post(f"{base}/work-orders/{order_id}/release", headers=planner)
        first_issue = client.post(f"{base}/material-issues", headers=planner, json={
            "work_order_id": order_id, "warehouse_id": 1,
            "lines": [{"work_order_line_id": line_id, "quantity": "1"}]}).json()
        client.post(f"{base}/material-issues/{first_issue['id']}/post", headers=warehouse)
        for invalid in ("0", "0.0001", "NaN", "3"):
            expected = 409 if invalid == "3" else 422
            assert client.post(f"{base}/production-completions", headers=planner, json={
                "work_order_id": order_id, "reported_quantity": invalid}).status_code == expected
        payload = {"work_order_id": order_id, "reported_quantity": "1", "reference": "COMP-1"}
        first = client.post(f"{base}/production-completions", headers=planner, json=payload)
        assert first.status_code == 201
        first_id = first.json()["id"]
        stale = client.post(f"{base}/production-completions", headers=planner, json={
            **payload, "reported_quantity": "2"}).json()["id"]
        assert client.post(f"{base}/production-completions/{first_id}/post", headers=warehouse).status_code == 409
        assert client.post(f"{base}/production-completions/{first_id}/inspect", headers=planner,
                           json={"accepted_quantity": "0.5", "qc_note": "抽检合格"}).status_code == 403
        assert client.post(f"{base}/production-completions/{first_id}/inspect", headers=warehouse,
                           json={"accepted_quantity": "1.1", "qc_note": "数量错误"}).status_code == 422
        assert client.post(f"{base}/production-completions/{first_id}/inspect", headers=warehouse,
                           json={"accepted_quantity": "0.5", "qc_note": "  "}).status_code == 422
        inspected = client.post(f"{base}/production-completions/{first_id}/inspect", headers=warehouse,
                                json={"accepted_quantity": "0.5", "qc_note": "抽检发现半数不合格"})
        assert inspected.status_code == 200
        assert inspected.json()["rejected_quantity"] == "0.5"
        assert client.post(f"{base}/production-completions/{first_id}/inspect", headers=warehouse,
                           json={"accepted_quantity": "0.5", "qc_note": "重复"}).status_code == 409
        before_shortage = len(client.get(f"{base}/movements", headers=admin).json())
        assert client.post(f"{base}/production-completions/{first_id}/post", headers=warehouse).status_code == 409
        assert len(client.get(f"{base}/movements", headers=admin).json()) == before_shortage

        # 报工 1 件需要累计领用 2 件组件，补领后才能把质检合格品入库。
        second_issue = client.post(f"{base}/material-issues", headers=planner, json={
            "work_order_id": order_id, "warehouse_id": 1,
            "lines": [{"work_order_line_id": line_id, "quantity": "1"}]}).json()
        client.post(f"{base}/material-issues/{second_issue['id']}/post", headers=warehouse)
        # 报工确认前允许退料草稿，确认后若会低于已消耗需料则须拒绝过期草稿。
        stale_return = client.post(f"{base}/material-returns", headers=planner, json={
            "material_issue_id": first_issue["id"], "reason": "拟退回",
            "lines": [{"material_issue_line_id": first_issue["lines"][0]["id"],
                       "quantity": "0.1"}]}).json()["id"]
        assert client.post(f"{base}/production-completions/{first_id}/post", headers=warehouse).status_code == 200
        assert client.post(f"{base}/production-completions/{first_id}/post", headers=warehouse).status_code == 409
        assert client.post(f"{base}/material-returns/{stale_return}/post", headers=warehouse).status_code == 409
        assert client.post(f"{base}/material-returns/{stale_return}/cancel", headers=planner).status_code == 200
        movement = client.get(f"{base}/movements", headers=admin).json()[0]
        assert movement["source_type"] == "production_completion"
        assert movement["production_completion_id"] == first_id
        assert movement["source_line_id"] == first_id
        assert movement["material_id"] == product
        assert movement["warehouse_id"] == target_warehouse
        assert movement["quantity"] == "0.5"
        assert client.post(f"{base}/production-completions/{stale}/inspect", headers=warehouse,
                           json={"accepted_quantity": "2", "qc_note": "合格"}).status_code == 200
        before_stale = len(client.get(f"{base}/movements", headers=admin).json())
        assert client.post(f"{base}/production-completions/{stale}/post", headers=warehouse).status_code == 409
        assert len(client.get(f"{base}/movements", headers=admin).json()) == before_stale
        assert client.post(f"{base}/production-completions/{stale}/cancel", headers=planner).status_code == 200

        # 已完工报工所需的两件组件不可退回；剩余需料可继续领用并完成第二批。
        assert client.post(f"{base}/material-returns", headers=planner, json={
            "material_issue_id": first_issue["id"], "reason": "误退",
            "lines": [{"material_issue_line_id": first_issue["lines"][0]["id"],
                       "quantity": "0.1"}]}).status_code == 409
        third_issue = client.post(f"{base}/material-issues", headers=planner, json={
            "work_order_id": order_id, "warehouse_id": 1,
            "lines": [{"work_order_line_id": line_id, "quantity": "2"}]}).json()
        client.post(f"{base}/material-issues/{third_issue['id']}/post", headers=warehouse)
        final = client.post(f"{base}/production-completions", headers=planner, json=payload).json()["id"]
        client.post(f"{base}/production-completions/{final}/inspect", headers=warehouse,
                    json={"accepted_quantity": "1", "qc_note": "全数合格"})
        assert client.post(f"{base}/production-completions/{final}/post", headers=warehouse).status_code == 200
        current = client.get(f"{base}/work-orders", headers=planner).json()[0]
        assert current["status"] == "completed"
        assert current["reported_quantity"] == "2"
        assert current["accepted_quantity"] == "1.5"
        assert current["rejected_quantity"] == "0.5"
        assert current["remaining_output_quantity"] == "0"
        assert current["completed_by"] is not None
        assert client.post(f"{base}/production-completions", headers=planner, json=payload).status_code == 409
        stock = client.get(f"{base}/stock?warehouse_id={target_warehouse}", headers=admin).json()
        assert next(item for item in stock if item["id"] == product)["quantity"] == "1.5"

        # 已确认完工须用独立冲销单更正；库存被调走时不得把原仓扣成负数。
        reverse_url = f"{base}/production-completions/{final}/reverse"
        assert client.post(reverse_url, headers=planner, json={"reason": "误报"}).status_code == 403
        assert client.post(reverse_url, headers=warehouse, json={"reason": "误报"}).status_code == 403
        assert client.post(reverse_url, headers=admin, json={"reason": "  "}).status_code == 422
        transfer = client.post(f"{base}/transfers", headers=admin, json={
            "from_warehouse_id": target_warehouse, "to_warehouse_id": 1,
            "lines": [{"material_id": product, "quantity": "1"}]}).json()["id"]
        approve_document(client, admin, 'Transfer', transfer)
        assert client.post(f"{base}/transfers/{transfer}/post", headers=admin).status_code == 200
        before = len(client.get(f"{base}/movements", headers=admin).json())
        assert client.post(reverse_url, headers=admin, json={"reason": "质检数量录错"}).status_code == 409
        assert len(client.get(f"{base}/movements", headers=admin).json()) == before
        back = client.post(f"{base}/transfers", headers=admin, json={
            "from_warehouse_id": 1, "to_warehouse_id": target_warehouse,
            "lines": [{"material_id": product, "quantity": "1"}]}).json()["id"]
        approve_document(client, admin, 'Transfer', back)
        assert client.post(f"{base}/transfers/{back}/post", headers=admin).status_code == 200
        reversed_result = client.post(reverse_url, headers=admin, json={"reason": "  质检数量录错  "})
        assert reversed_result.status_code == 200
        assert reversed_result.json()["status"] == "reversed"
        assert reversed_result.json()["reversal_reason"] == "质检数量录错"
        assert reversed_result.json()["reversed_by_name"] == "admin"
        assert client.post(reverse_url, headers=admin, json={"reason": "重复"}).status_code == 409
        movement = client.get(f"{base}/movements", headers=admin).json()[0]
        assert movement["source_type"] == "production_completion_reversal"
        assert movement["production_completion_reversal_id"] == reversed_result.json()["reversal_id"]
        assert movement["quantity"] == "-1"
        current = client.get(f"{base}/work-orders", headers=planner).json()[0]
        assert current["status"] == "in_progress"
        assert current["reported_quantity"] == "1"
        assert current["remaining_output_quantity"] == "1"
        assert current["completed_by"] is None
        assert client.get(f"{base}/production-completions", headers=planner).json()[0]["status"] == "reversed"
        replacement = client.post(f"{base}/production-completions", headers=planner,
                                  json=payload).json()["id"]
        client.post(f"{base}/production-completions/{replacement}/inspect", headers=warehouse,
                    json={"accepted_quantity": "1", "qc_note": "重新质检合格"})
        assert client.post(f"{base}/production-completions/{replacement}/post",
                           headers=warehouse).status_code == 200
        assert client.get(f"{base}/work-orders", headers=planner).json()[0]["status"] == "completed"
        assert client.post(f"{base}/production-completions/{replacement}/reverse", headers=admin,
                           json={"reason": "重新核验"}).status_code == 200
        rejected = client.post(f"{base}/production-completions", headers=planner,
                               json=payload).json()["id"]
        client.post(f"{base}/production-completions/{rejected}/inspect", headers=warehouse,
                    json={"accepted_quantity": "0", "qc_note": "整批不合格"})
        assert client.post(f"{base}/production-completions/{rejected}/post",
                           headers=warehouse).status_code == 200
        before_zero_reversal = len(client.get(f"{base}/movements", headers=admin).json())
        assert client.post(f"{base}/production-completions/{rejected}/reverse", headers=admin,
                           json={"reason": "报工批次录错"}).status_code == 200
        assert len(client.get(f"{base}/movements", headers=admin).json()) == before_zero_reversal
