"""验证采购退货的原入库关联、库存不足回滚与历史价格边界。"""

from approval_test_helpers import approve_document

from fastapi.testclient import TestClient

from app.main import app


def test_purchase_returns_source_and_inventory(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "purchase-returns.db"))
    with TestClient(app, client=("127.0.0.1", 12000)) as client:
        base = "/api/v1"
        client.post(f"{base}/setup/admin", json={"username": "admin", "password": "secure-pass-123"})

        def login(username: str) -> dict:
            token = client.post(f"{base}/auth/login", json={
                "username": username, "password": "secure-pass-123"}).json()["token"]
            return {"Authorization": f"Bearer {token}"}

        admin = login("admin")
        for username, role in (("buyer", "buyer"), ("warehouse", "warehouse"), ("viewer", "viewer")):
            client.post(f"{base}/users", headers=admin, json={
                "username": username, "password": "secure-pass-123", "roles": [role]})
        buyer, warehouse, viewer = login("buyer"), login("warehouse"), login("viewer")
        supplier = client.post(f"{base}/suppliers", headers=admin, json={"name": "供应商甲"}).json()["id"]
        material = client.post(f"{base}/materials", headers=admin, json={
            "sku": "PR-A", "name": "退货物料", "unit": "件"}).json()["id"]
        other = client.post(f"{base}/materials", headers=admin, json={
            "sku": "PR-B", "name": "另一物料", "unit": "件"}).json()["id"]
        second = client.post(f"{base}/warehouses", headers=admin, json={
            "code": "PR-2", "name": "另一仓库"}).json()["id"]
        order = client.post(f"{base}/purchase-orders", headers=buyer, json={
            "supplier_id": supplier, "lines": [{"material_id": material, "quantity": "2.125",
                                               "unit_price": "10.0000"}]}).json()["id"]
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, admin, 'PurchaseOrder', order)
        client.post(f"{base}/purchase-orders/{order}/confirm", headers=buyer)
        receipt = client.post(f"{base}/receipts", headers=buyer, json={
            "supplier_id": supplier, "warehouse_id": 1, "purchase_order_id": order,
            "lines": [{"material_id": material, "quantity": "2.125"}]}).json()
        receipt_id, line_id = receipt["id"], receipt["lines"][0]["id"]
        payload = {"receipt_id": receipt_id, "reason": "质量问题",
                   "lines": [{"receipt_line_id": line_id, "quantity": "1.125"}]}
        assert client.post(f"{base}/purchase-returns", headers=buyer, json=payload).status_code == 409

        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, admin, 'Receipt', receipt_id)
        client.post(f"{base}/receipts/{receipt_id}/post", headers=warehouse)
        assert client.post(f"{base}/purchase-returns", headers=viewer, json=payload).status_code == 403
        assert client.post(f"{base}/purchase-returns", headers=buyer, json={
            **payload, "reason": "   "}).status_code == 422
        assert client.post(f"{base}/purchase-returns", headers=buyer, json={
            **payload, "lines": payload["lines"] * 2}).status_code == 422
        assert client.post(f"{base}/purchase-returns", headers=buyer, json={
            **payload, "lines": [{"receipt_line_id": line_id, "quantity": "2.126"}]}).status_code == 409
        assert client.post(f"{base}/purchase-returns", headers=buyer, json={
            **payload, "lines": [{"receipt_line_id": line_id, "quantity": "0.0001"}]}).status_code == 422
        wrong_line = client.post(f"{base}/receipts", headers=buyer, json={
            "supplier_id": supplier, "warehouse_id": 1,
            "lines": [{"material_id": other, "quantity": "1"}]}).json()["lines"][0]["id"]
        assert client.post(f"{base}/purchase-returns", headers=buyer, json={
            **payload, "lines": [{"receipt_line_id": wrong_line, "quantity": "1"}]}).status_code == 422

        first = client.post(f"{base}/purchase-returns", headers=buyer, json=payload)
        assert first.status_code == 201
        first_id = first.json()["id"]
        assert first.json()["total_amount"] == "11.25"
        assert client.post(f"{base}/purchase-returns/{first_id}/reverse", headers=admin,
                           json={"reason": "草稿不可冲销"}).status_code == 409
        assert client.post(f"{base}/purchase-returns/99999/reverse", headers=admin,
                           json={"reason": "不存在"}).status_code == 404
        # 两张草稿都可先保存，确认时仍须在写锁下重新核对可退数量。
        stale = client.post(f"{base}/purchase-returns", headers=buyer, json={
            **payload, "lines": [{"receipt_line_id": line_id, "quantity": "2.125"}]}).json()["id"]
        assert client.post(f"{base}/purchase-returns/{first_id}/post", headers=buyer).status_code == 403
        assert client.post(f"{base}/purchase-returns/{first_id}/post", headers=warehouse).status_code == 200
        assert client.post(f"{base}/purchase-returns/{first_id}/post", headers=warehouse).status_code == 409
        assert client.post(f"{base}/purchase-returns/{first_id}/cancel", headers=buyer).status_code == 409
        assert client.post(f"{base}/purchase-returns/{stale}/post", headers=warehouse).status_code == 409
        assert client.post(f"{base}/purchase-returns/{stale}/cancel", headers=buyer).status_code == 200
        assert client.get(f"{base}/stock?warehouse_id=1", headers=viewer).json()[0]["quantity"] == "1.000"
        assert client.get(f"{base}/receipts", headers=viewer).json()[1]["lines"][0]["returnable_quantity"] == "1.000"
        order_data = client.get(f"{base}/purchase-orders", headers=viewer).json()[0]
        assert order_data["status"] == "received"
        assert order_data["lines"][0]["received_quantity"] == "2.125"
        assert order_data["lines"][0]["returned_quantity"] == "1.125"
        assert order_data["lines"][0]["net_received_quantity"] == "1.000"
        movement = client.get(f"{base}/movements", headers=viewer).json()[0]
        assert movement["purchase_return_id"] == first_id
        assert movement["quantity"] == "-1.125"
        assert movement["warehouse_id"] == 1

        # 库存调往别的仓后，原仓不足时确认退货应整体失败，且不写任何流水。
        transfer = client.post(f"{base}/transfers", headers=warehouse, json={
            "from_warehouse_id": 1, "to_warehouse_id": second,
            "lines": [{"material_id": material, "quantity": "1"}]}).json()["id"]
        client.post(f"{base}/transfers/{transfer}/post", headers=warehouse)
        rest = client.post(f"{base}/purchase-returns", headers=buyer, json={
            **payload, "lines": [{"receipt_line_id": line_id, "quantity": "1.000"}]}).json()["id"]
        before = len(client.get(f"{base}/movements", headers=viewer).json())
        assert client.post(f"{base}/purchase-returns/{rest}/post", headers=warehouse).status_code == 409
        assert len(client.get(f"{base}/movements", headers=viewer).json()) == before
        assert client.get(f"{base}/purchase-returns", headers=viewer).json()[0]["status"] == "draft"
        reverse = client.post(f"{base}/transfers", headers=warehouse, json={
            "from_warehouse_id": second, "to_warehouse_id": 1,
            "lines": [{"material_id": material, "quantity": "1"}]}).json()["id"]
        client.post(f"{base}/transfers/{reverse}/post", headers=warehouse)
        assert client.post(f"{base}/purchase-returns/{rest}/post", headers=warehouse).status_code == 200
        assert client.get(f"{base}/receipts", headers=viewer).json()[1]["lines"][0]["returnable_quantity"] == "0.000"
        assert client.post(f"{base}/purchase-returns", headers=buyer, json=payload).status_code == 409

        # 冲销原退货后恢复原仓库存、采购净入库量和应付；原退货来源仍可追溯。
        reverse_url = f"{base}/purchase-returns/{first_id}/reverse"
        assert client.post(reverse_url, headers=buyer, json={"reason": "误退"}).status_code == 403
        assert client.post(reverse_url, headers=admin, json={"reason": "   "}).status_code == 422
        result = client.post(reverse_url, headers=admin, json={"reason": "供应商未收货"})
        assert result.status_code == 201
        assert result.json()["reversal_reason"] == "供应商未收货"
        assert result.json()["reversed_by_name"] == "admin"
        assert client.post(reverse_url, headers=admin, json={"reason": "重复"}).status_code == 409
        assert client.get(f"{base}/stock?warehouse_id=1", headers=viewer).json()[0]["quantity"] == "1.125"
        assert client.get(f"{base}/receipts", headers=viewer).json()[1]["lines"][0]["returnable_quantity"] == "1.125"
        order_data = client.get(f"{base}/purchase-orders", headers=viewer).json()[0]
        assert order_data["lines"][0]["returned_quantity"] == "1.000"
        assert order_data["lines"][0]["net_received_quantity"] == "1.125"
        ledger = client.get(f"{base}/finance/receivables-payables", headers=admin).json()
        assert ledger["payable_amount"] == "11.25"
        assert {item["source_type"] for item in ledger["entries"]} == {
            "receipt", "purchase_return", "purchase_return_reversal"}
        movement = client.get(f"{base}/movements", headers=viewer).json()[0]
        assert movement["source_type"] == "purchase_return_reversal"
        assert movement["purchase_return_reversal_id"] == result.json()["reversal_id"]
        corrected = client.post(f"{base}/purchase-returns", headers=buyer, json=payload)
        assert corrected.status_code == 201
        assert client.post(f"{base}/purchase-returns/{corrected.json()['id']}/post",
                           headers=warehouse).status_code == 200

        # 不关联采购订单的旧式入库不应被错误地当作零价退货。
        legacy_receipt_id = client.get(f"{base}/receipts", headers=viewer).json()[0]["id"]
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, admin, 'Receipt', legacy_receipt_id)
        assert client.post(f"{base}/receipts/{legacy_receipt_id}/post", headers=warehouse).status_code == 200
        legacy = client.get(f"{base}/receipts", headers=viewer).json()[0]
        unpriced = client.post(f"{base}/purchase-returns", headers=buyer, json={
            "receipt_id": legacy["id"], "reason": "包装破损",
            "lines": [{"receipt_line_id": legacy["lines"][0]["id"], "quantity": "1"}]})
        assert unpriced.status_code == 201
        assert unpriced.json()["total_amount"] is None
        assert client.post(f"{base}/purchase-returns/{unpriced.json()['id']}/post",
                           headers=warehouse).status_code == 200
        assert client.post(f"{base}/purchase-returns/{unpriced.json()['id']}/reverse",
                           headers=admin, json={"reason": "无需退货"}).status_code == 201
        unpriced_entries = client.get(f"{base}/finance/receivables-payables", headers=admin).json()["entries"]
        assert {item["source_type"] for item in unpriced_entries if item["amount"] is None} == {
            "receipt", "purchase_return", "purchase_return_reversal"}
