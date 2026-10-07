"""验证应收应付只来自已确认单据，退货冲减且历史无价入库不伪造金额。"""

from approval_test_helpers import approve_document, prepare_purchase_return

from fastapi.testclient import TestClient

from app.main import app


def test_receivables_payables_sources_and_permissions(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "finance.db"))
    with TestClient(app, client=("127.0.0.1", 12000)) as client:
        base = "/api/v1"
        client.post(f"{base}/setup/admin", json={"username": "admin", "password": "secure-pass-123"})

        def login(username: str) -> dict:
            token = client.post(f"{base}/auth/login", json={
                "username": username, "password": "secure-pass-123"}).json()["token"]
            return {"Authorization": f"Bearer {token}"}

        admin = login("admin")
        for username, role in (("accountant", "finance"), ("buyer", "buyer")):
            assert client.post(f"{base}/users", headers=admin, json={
                "username": username, "password": "secure-pass-123", "roles": [role]}).status_code == 201
        finance, buyer = login("accountant"), login("buyer")
        assert client.get(f"{base}/finance/receivables-payables", headers=buyer).status_code == 403
        supplier = client.post(f"{base}/suppliers", headers=admin, json={"name": "供应商"}).json()["id"]
        customer = client.post(f"{base}/customers", headers=admin, json={"name": "客户"}).json()["id"]
        material = client.post(f"{base}/materials", headers=admin, json={
            "sku": "FIN", "name": "财务物料", "unit": "件"}).json()["id"]
        purchase_order = client.post(f"{base}/purchase-orders", headers=admin, json={
            "supplier_id": supplier, "lines": [{"material_id": material, "quantity": "2.125",
                                               "unit_price": "2.3456"}]}).json()["id"]
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, admin, 'PurchaseOrder', purchase_order)
        client.post(f"{base}/purchase-orders/{purchase_order}/confirm", headers=admin)
        receipt = client.post(f"{base}/receipts", headers=admin, json={
            "supplier_id": supplier, "purchase_order_id": purchase_order,
            "lines": [{"material_id": material, "quantity": "2.125"}]}).json()
        receipt_id = receipt["id"]
        sales_order = client.post(f"{base}/sales-orders", headers=admin, json={
            "customer_id": customer, "lines": [{"material_id": material, "quantity": "1.125",
                                               "unit_price": "10.0050"}]}).json()["id"]
        client.post(f"{base}/sales-orders/{sales_order}/confirm", headers=admin)
        shipment = client.post(f"{base}/shipments", headers=admin, json={
            "sales_order_id": sales_order, "warehouse_id": 1,
            "lines": [{"material_id": material, "quantity": "1.125"}]}).json()
        shipment_id = shipment["id"]
        # 草稿金额不进入应收应付；确认后按单据行精确舍入到分。
        assert client.get(f"{base}/finance/receivables-payables", headers=finance).json()["entries"] == []
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, admin, 'Receipt', receipt_id)
        client.post(f"{base}/receipts/{receipt_id}/post", headers=admin)
        client.post(f"{base}/shipments/{shipment_id}/post", headers=admin)
        snapshot = client.get(f"{base}/finance/receivables-payables", headers=finance).json()
        assert snapshot["receivable_amount"] == "11.26"
        assert snapshot["payable_amount"] == "4.98"
        assert {item["source_type"] for item in snapshot["entries"]} == {"shipment", "receipt"}
        assert all(item["posted_by"] and item["posted_at"] and item["source_line_id"]
                   for item in snapshot["entries"])

        sale_return = client.post(f"{base}/sales-returns", headers=admin, json={
            "shipment_id": shipment_id, "warehouse_id": 1, "reason": "客户退回",
            "lines": [{"shipment_line_id": shipment["lines"][0]["id"], "quantity": "0.125"}]}).json()["id"]
        purchase_return = client.post(f"{base}/purchase-returns", headers=admin, json={
            "receipt_id": receipt_id, "reason": "供应商退货",
            "lines": [{"receipt_line_id": receipt["lines"][0]["id"], "quantity": "0.125"}]}).json()["id"]
        client.post(f"{base}/sales-returns/{sale_return}/post", headers=admin)
        prepare_purchase_return(client, admin, purchase_return)
        client.post(f"{base}/purchase-returns/{purchase_return}/post", headers=admin)
        adjusted = client.get(f"{base}/finance/receivables-payables", headers=finance).json()
        assert adjusted["receivable_amount"] == "10.01"
        assert adjusted["payable_amount"] == "4.69"
        assert {item["source_type"] for item in adjusted["entries"]} == {
            "shipment", "sales_return", "receipt", "purchase_return"}
        assert len({item["key"] for item in adjusted["entries"]}) == 4

        legacy_receipt = client.post(f"{base}/receipts", headers=admin, json={
            "supplier_id": supplier, "lines": [{"material_id": material, "quantity": "1"}]}).json()
        legacy = legacy_receipt["id"]
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, admin, 'Receipt', legacy)
        client.post(f"{base}/receipts/{legacy}/post", headers=admin)
        unpriced = client.get(f"{base}/finance/receivables-payables", headers=finance).json()
        assert unpriced["unpriced_count"] == 1
        assert unpriced["payable_amount"] == "4.69"
        legacy_entry = next(item for item in unpriced["entries"]
                            if item["source_type"] == "receipt" and item["source_id"] == legacy)
        assert legacy_entry["amount"] is None
        assert legacy_entry["order_id"] is None
        assert legacy_entry["posted_by_name"] == "admin"
        unknown_return = client.post(f"{base}/purchase-returns", headers=admin, json={
            "receipt_id": legacy, "reason": "退回未定价物料",
            "lines": [{"receipt_line_id": legacy_receipt["lines"][0]["id"], "quantity": "0.5"}]}).json()["id"]
        prepare_purchase_return(client, admin, unknown_return)
        client.post(f"{base}/purchase-returns/{unknown_return}/post", headers=admin)
        with_unknown_return = client.get(f"{base}/finance/receivables-payables", headers=finance).json()
        assert with_unknown_return["unpriced_count"] == 2
        assert with_unknown_return["payable_amount"] == "4.69"
