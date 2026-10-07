"""验证已确认入库冲销的库存、采购进度和应付来源保持一致。"""

from approval_test_helpers import approve_document

from fastapi.testclient import TestClient

from app.main import app


def test_receipt_reversal_dependencies_and_balances(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "receipt-reversal.db"))
    with TestClient(app, client=("127.0.0.1", 12000)) as client:
        base = "/api/v1"
        client.post(f"{base}/setup/admin", json={"username": "admin", "password": "secure-pass-123"})
        token = client.post(f"{base}/auth/login", json={
            "username": "admin", "password": "secure-pass-123"}).json()["token"]
        admin = {"Authorization": f"Bearer {token}"}
        client.post(f"{base}/users", headers=admin, json={
            "username": "buyer", "password": "secure-pass-123", "roles": ["buyer"]})
        buyer_token = client.post(f"{base}/auth/login", json={
            "username": "buyer", "password": "secure-pass-123"}).json()["token"]
        buyer = {"Authorization": f"Bearer {buyer_token}"}
        supplier = client.post(f"{base}/suppliers", headers=admin, json={"name": "供应商"}).json()["id"]
        material = client.post(f"{base}/materials", headers=admin, json={
            "sku": "REVERSE-RECEIPT", "name": "物料", "unit": "件"}).json()["id"]
        order = client.post(f"{base}/purchase-orders", headers=admin, json={
            "supplier_id": supplier, "lines": [{"material_id": material,
                                              "quantity": "2.000", "unit_price": "10.0000"}]}).json()["id"]
        # 先完成真实独立审批，保留原业务失败和并发断言。
        approve_document(client, admin, 'PurchaseOrder', order)
        client.post(f"{base}/purchase-orders/{order}/confirm", headers=admin)
        receipt = client.post(f"{base}/receipts", headers=admin, json={
            "supplier_id": supplier, "purchase_order_id": order,
            "lines": [{"material_id": material, "quantity": "2.000"}]}).json()
        receipt_id = receipt["id"]
        url = f"{base}/receipts/{receipt_id}/reverse"
        assert client.post(url, headers=admin, json={"reason": "草稿"}).status_code == 409
        assert client.post(f"{base}/receipts/99999/reverse", headers=admin,
                           json={"reason": "不存在"}).status_code == 404
        # 先完成真实独立审批，保留原业务失败和并发断言。
        approve_document(client, admin, 'Receipt', receipt_id)
        client.post(f"{base}/receipts/{receipt_id}/post", headers=admin)
        assert client.post(url, headers=buyer, json={"reason": "无权"}).status_code == 403
        assert client.post(url, headers=admin, json={"reason": "  "}).status_code == 422

        # 先完成真实独立审批，保留原业务失败和并发断言。
        approve_document(client, admin, 'Receipt', receipt_id, intent='reverse', reason='误入库')
        # 有效采购退货依赖原入库，必须先冲销退货才能冲销入库。
        purchase_return = client.post(f"{base}/purchase-returns", headers=admin, json={
            "receipt_id": receipt_id, "reason": "误退", "lines": [
                {"receipt_line_id": receipt["lines"][0]["id"], "quantity": "0.500"}]}).json()["id"]
        client.post(f"{base}/purchase-returns/{purchase_return}/post", headers=admin)
        before = len(client.get(f"{base}/movements", headers=admin).json())
        assert client.post(url, headers=admin, json={"reason": "误入库"}).status_code == 409
        assert len(client.get(f"{base}/movements", headers=admin).json()) == before
        client.post(f"{base}/purchase-returns/{purchase_return}/reverse", headers=admin,
                    json={"reason": "恢复原入库"})

        # 原仓库存被调走时不能凭空冲销；调回后一次性写入负库存流水。
        warehouse = client.post(f"{base}/warehouses", headers=admin, json={
            "code": "SECOND", "name": "次仓"}).json()["id"]
        transfer = client.post(f"{base}/transfers", headers=admin, json={
            "from_warehouse_id": 1, "to_warehouse_id": warehouse,
            "lines": [{"material_id": material, "quantity": "2.000"}]}).json()["id"]
        client.post(f"{base}/transfers/{transfer}/post", headers=admin)
        assert client.post(url, headers=admin, json={"reason": "误入库"}).status_code == 409
        assert client.post(f"{base}/transfers/{transfer}/reverse", headers=admin,
                           json={"reason": "回原仓"}).status_code == 200
        result = client.post(url, headers=admin, json={"reason": "误入库"})
        assert result.status_code == 201
        assert result.json()["reversal_reason"] == "误入库"
        assert result.json()["reversed_by_name"] == "admin"
        assert result.json()["lines"][0]["returnable_quantity"] == "0"
        assert client.post(url, headers=admin, json={"reason": "重复"}).status_code == 409
        assert client.get(f"{base}/stock?warehouse_id=1", headers=admin).json()[0]["quantity"] == "0.000"
        order_data = client.get(f"{base}/purchase-orders", headers=admin).json()[0]
        assert order_data["status"] == "confirmed"
        assert order_data["lines"][0]["remaining_quantity"] == "2.000"
        report = client.get(f"{base}/finance/receivables-payables", headers=admin).json()
        assert report["payable_amount"] == "0.00"
        assert {item["source_type"] for item in report["entries"]} == {
            "receipt", "receipt_reversal", "purchase_return", "purchase_return_reversal"}
        movement = client.get(f"{base}/movements", headers=admin).json()[0]
        assert movement["source_type"] == "receipt_reversal"
        assert movement["receipt_reversal_id"] == result.json()["reversal_id"]
        assert client.post(f"{base}/purchase-returns", headers=admin, json={
            "receipt_id": receipt_id, "reason": "不可再退", "lines": [
                {"receipt_line_id": receipt["lines"][0]["id"], "quantity": "0.100"}]}).status_code == 409
        replacement = client.post(f"{base}/receipts", headers=admin, json={
            "supplier_id": supplier, "purchase_order_id": order,
            "lines": [{"material_id": material, "quantity": "2.000"}]})
        assert replacement.status_code == 201
        # 先完成真实独立审批，保留原业务失败和并发断言。
        approve_document(client, admin, 'Receipt', replacement.json()['id'])
        assert client.post(f"{base}/receipts/{replacement.json()['id']}/post",
                           headers=admin).status_code == 200
