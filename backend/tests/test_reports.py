"""采购与库存报表沿用服务端筛选结果生成 CSV，保持数量可追溯。"""

from approval_test_helpers import approve_document

import csv
from io import StringIO

from fastapi.testclient import TestClient

from app.main import app
from app.reports.routes import csv_value


def test_report_csv_matches_filtered_rows(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "reports.db"))
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        base = "/api/v1"
        client.post(f"{base}/setup/admin", json={"username": "admin", "password": "secure-pass-123"})
        token = client.post(f"{base}/auth/login", json={
            "username": "admin", "password": "secure-pass-123"}).json()["token"]
        admin = {"Authorization": f"Bearer {token}"}
        material = client.post(f"{base}/materials", headers=admin, json={
            "sku": "RPT", "name": "报表物料", "unit": "件"}).json()["id"]
        supplier = client.post(f"{base}/suppliers", headers=admin, json={"name": "报表供应商"}).json()["id"]
        request = client.post(f"{base}/purchase-requests", headers=admin, json={
            "reference": "RPT-REQ", "note": "采购", "lines": [
                {"material_id": material, "quantity": "5"}]}).json()
        request_id = request["id"]
        client.post(f"{base}/purchase-requests/{request_id}/submit", headers=admin)
        client.post(f"{base}/purchase-requests/{request_id}/approve", headers=admin)
        order = client.post(f"{base}/purchase-orders", headers=admin, json={
            "supplier_id": supplier, "purchase_request_id": request_id,
            "lines": [{"purchase_request_line_id": request["lines"][0]["id"],
                       "material_id": material, "quantity": "3", "unit_price": "4"}]}).json()
        order_id = order["id"]
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, admin, 'PurchaseOrder', order_id)
        client.post(f"{base}/purchase-orders/{order_id}/confirm", headers=admin)
        receipt = client.post(f"{base}/receipts", headers=admin, json={
            "supplier_id": supplier, "warehouse_id": 1, "purchase_order_id": order_id,
            "lines": [{"material_id": material, "quantity": "3"}]}).json()["id"]
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, admin, 'Receipt', receipt)
        client.post(f"{base}/receipts/{receipt}/post", headers=admin)
        report = client.post(f"{base}/reports/query", headers=admin, json={
            "kind": "purchase_requests", "material_id": material}).json()
        # CSV 与筛选结果展示同一业务单号，不能再把内部 ID 当作单号。
        assert report["rows"][0]["document"] == request['document_no']
        assert report["rows"][0]["ordered"] == "3"
        assert report["rows"][0]["remaining"] == "2"
        parsed = list(csv.reader(StringIO(report["csv"].removeprefix("\ufeff"))))
        assert len(parsed) == len(report["rows"]) + 1
        assert parsed[1][0] == report["rows"][0]["document"]
        execution = client.post(f"{base}/reports/query", headers=admin, json={
            "kind": "purchase_orders", "supplier_id": supplier}).json()
        assert execution["rows"][0]["received"] == "3"
        assert execution["rows"][0]["amount"] == "12.00"
        assert client.post(f"{base}/reports/query", headers=admin, json={
            "kind": "purchase_orders", "supplier_id": supplier + 100}).json()["rows"] == []
        balance = client.post(f"{base}/reports/query", headers=admin, json={
            "kind": "inventory_balance", "warehouse_id": 1, "material_id": material}).json()
        assert balance["rows"][0]["quantity"] == "3"
        flow = client.post(f"{base}/reports/query", headers=admin, json={
            "kind": "stock_flow", "warehouse_id": 1, "material_id": material}).json()
        assert flow["rows"][0]["inbound"] == "3"
        assert flow["rows"][0]["closing"] == "3"
        assert client.post(f"{base}/reports/query", headers=admin, json={
            "kind": "stock_flow", "from_date": "2026-10-01", "to_date": "2026-09-30"}).status_code == 422
        assert client.post(f"{base}/reports/query", json={"kind": "stock_flow"}).status_code == 401
        assert csv_value("=HYPERLINK('unsafe')").startswith("'")
