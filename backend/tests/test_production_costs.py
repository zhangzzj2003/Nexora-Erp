"""验证领料核价、退料净额、费用归集与冲销后的待核价状态。"""

from approval_test_helpers import approve_document

from fastapi.testclient import TestClient

from app.main import app


def test_production_cost_collection_and_reversal(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "costs.db"))
    with TestClient(app, client=("127.0.0.1", 12000)) as client:
        base = "/api/v1"
        client.post(f"{base}/setup/admin", json={"username": "admin", "password": "secure-pass-123"})

        def login(username: str) -> dict:
            token = client.post(f"{base}/auth/login", json={
                "username": username, "password": "secure-pass-123"}).json()["token"]
            return {"Authorization": f"Bearer {token}"}

        admin = login("admin")
        for username, role in (("planner", "planner"), ("warehouse", "warehouse"), ("finance", "finance")):
            client.post(f"{base}/users", headers=admin, json={
                "username": username, "password": "secure-pass-123", "roles": [role]})
        planner, warehouse, finance = login("planner"), login("warehouse"), login("finance")
        supplier = client.post(f"{base}/suppliers", headers=admin, json={"name": "供应商"}).json()["id"]
        product = client.post(f"{base}/materials", headers=admin, json={
            "sku": "FIN-COST", "name": "成品", "unit": "件"}).json()["id"]
        component = client.post(f"{base}/materials", headers=admin, json={
            "sku": "PART-COST", "name": "组件", "unit": "件"}).json()["id"]
        receipt = client.post(f"{base}/receipts", headers=admin, json={
            "supplier_id": supplier, "warehouse_id": 1,
            "lines": [{"material_id": component, "quantity": "3"}]}).json()["id"]
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, admin, 'Receipt', receipt)
        client.post(f"{base}/receipts/{receipt}/post", headers=admin)
        bom = client.post(f"{base}/boms", headers=planner, json={
            "product_material_id": product, "base_quantity": "1",
            "lines": [{"component_material_id": component, "quantity": "2"}]}).json()["id"]
        client.post(f"{base}/boms/{bom}/activate", headers=planner)
        order = client.post(f"{base}/work-orders", headers=planner, json={
            "bom_id": bom, "warehouse_id": 1, "target_quantity": "1"}).json()
        order_id = order["id"]
        assert client.post(f"{base}/production-costs/charges", headers=finance, json={
            "work_order_id": order_id, "kind": "labor", "amount": "1",
            "reference": "LAB-DRAFT"}).status_code == 409
        client.post(f"{base}/work-orders/{order_id}/release", headers=planner)
        issue = client.post(f"{base}/material-issues", headers=planner, json={
            "work_order_id": order_id, "warehouse_id": 1,
            "lines": [{"work_order_line_id": order["lines"][0]["id"], "quantity": "2"}]}).json()
        issue_line_id = issue["lines"][0]["id"]
        valuation_url = f"{base}/production-costs/material-valuations"
        payload = {"material_issue_line_id": issue_line_id, "unit_cost": "2.5000", "reference": "INVOICE-1"}
        assert client.post(valuation_url, headers=finance, json=payload).status_code == 409
        client.post(f"{base}/material-issues/{issue['id']}/post", headers=warehouse)

        assert client.get(f"{base}/production-costs", headers=warehouse).status_code == 403
        assert client.get(f"{base}/production-costs", headers=planner).status_code == 200
        assert client.post(valuation_url, headers=planner, json=payload).status_code == 403
        first_report = client.get(f"{base}/production-costs", headers=finance).json()
        report = first_report["orders"][0]
        assert report["unpriced_issue_count"] == 1
        assert report["total_amount"] is None
        assert first_report["unpriced_lines"][0]["material_issue_line_id"] == issue_line_id
        for bad_price in ("-1", "NaN", "1.00001"):
            assert client.post(valuation_url, headers=finance, json={
                **payload, "unit_cost": bad_price}).status_code == 422
        assert client.post(valuation_url, headers=finance, json={
            **payload, "reference": "  "}).status_code == 422
        valuation = client.post(valuation_url, headers=finance, json=payload)
        assert valuation.status_code == 201
        assert valuation.json()["current_amount"] == "5.00"
        assert client.post(valuation_url, headers=finance, json=payload).status_code == 409

        charge_url = f"{base}/production-costs/charges"
        assert client.post(charge_url, headers=finance, json={
            "work_order_id": order_id, "kind": "labor", "amount": "0", "reference": "LAB-1"}).status_code == 422
        labor = client.post(charge_url, headers=finance, json={
            "work_order_id": order_id, "kind": "labor", "amount": "10.20", "reference": "LAB-1"})
        assert labor.status_code == 201
        overhead = client.post(charge_url, headers=finance, json={
            "work_order_id": order_id, "kind": "overhead", "amount": "1.05", "reference": "OH-1"})
        assert overhead.status_code == 201
        report = client.get(f"{base}/production-costs", headers=finance).json()["orders"][0]
        assert report["known_material_amount"] == "5.00"
        assert report["labor_amount"] == "10.20"
        assert report["overhead_amount"] == "1.05"
        assert report["total_amount"] == "16.25"

        # 退料后按领料净数量重算材料额，不改写原始核定单价。
        returned = client.post(f"{base}/material-returns", headers=planner, json={
            "material_issue_id": issue["id"], "reason": "多领退回",
            "lines": [{"material_issue_line_id": issue_line_id, "quantity": "0.5"}]}).json()["id"]
        assert client.post(f"{base}/material-returns/{returned}/post", headers=warehouse).status_code == 200
        report = client.get(f"{base}/production-costs", headers=finance).json()
        assert report["orders"][0]["known_material_amount"] == "3.75"
        assert report["orders"][0]["total_amount"] == "15.00"
        assert next(item for item in report["entries"] if item["id"] == valuation.json()["id"])["net_quantity"] == "1.5"

        reverse_url = f"{base}/production-costs/{valuation.json()['id']}/reverse"
        assert client.post(reverse_url, headers=planner, json={"reason": "单价录错"}).status_code == 403
        assert client.post(reverse_url, headers=finance, json={"reason": " "}).status_code == 422
        reversed_entry = client.post(reverse_url, headers=finance, json={"reason": "单价录错"})
        assert reversed_entry.status_code == 200
        assert reversed_entry.json()["status"] == "reversed"
        assert reversed_entry.json()["reversal_reason"] == "单价录错"
        assert client.post(reverse_url, headers=finance, json={"reason": "重复"}).status_code == 409
        assert client.get(f"{base}/production-costs", headers=finance).json()["orders"][0]["total_amount"] is None
        assert client.post(valuation_url, headers=finance, json={
            **payload, "unit_cost": "3.0000", "reference": "INVOICE-2"}).status_code == 201
        assert client.get(f"{base}/production-costs", headers=finance).json()["orders"][0]["total_amount"] == "15.75"
        assert client.post(f"{base}/production-costs/{labor.json()['id']}/reverse", headers=finance,
                           json={"reason": "人工费用重算"}).status_code == 200
        assert client.get(f"{base}/production-costs", headers=finance).json()["orders"][0]["total_amount"] == "5.55"
