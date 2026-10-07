"""验证已确认销售出库冲销的库存、订单、应收与退货依赖。"""

from approval_test_helpers import approve_document

from fastapi.testclient import TestClient

from app.main import app


def test_shipment_reversal_restores_order_and_preserves_sources(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "shipment-reversal.db"))
    base = "/api/v1"
    with TestClient(app, client=("127.0.0.1", 12000)) as client:
        client.post(f"{base}/setup/admin", json={
            "username": "admin", "password": "secure-pass-123"})
        token = client.post(f"{base}/auth/login", json={
            "username": "admin", "password": "secure-pass-123"}).json()["token"]
        admin = {"Authorization": f"Bearer {token}"}
        client.post(f"{base}/users", headers=admin, json={
            "username": "seller", "password": "secure-pass-123", "roles": ["seller"]})
        seller_token = client.post(f"{base}/auth/login", json={
            "username": "seller", "password": "secure-pass-123"}).json()["token"]
        seller = {"Authorization": f"Bearer {seller_token}"}
        supplier = client.post(f"{base}/suppliers", headers=admin, json={
            "name": "供应商"}).json()["id"]
        customer = client.post(f"{base}/customers", headers=admin, json={
            "name": "客户"}).json()["id"]
        material = client.post(f"{base}/materials", headers=admin, json={
            "sku": "SHIP-REV", "name": "冲销物料", "unit": "件"}).json()["id"]
        receipt = client.post(f"{base}/receipts", headers=admin, json={
            "supplier_id": supplier, "lines": [{"material_id": material, "quantity": "2"}]}).json()["id"]
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, admin, 'Receipt', receipt)
        assert client.post(f"{base}/receipts/{receipt}/post", headers=admin).status_code == 200
        order = client.post(f"{base}/sales-orders", headers=admin, json={
            "customer_id": customer, "lines": [{"material_id": material,
                                               "quantity": "2", "unit_price": "5"}]}).json()["id"]
        approve_document(client, admin, 'SalesOrder', order)
        assert client.post(f"{base}/sales-orders/{order}/confirm", headers=admin).status_code == 200

        def create_shipment(quantity: str) -> dict:
            result = client.post(f"{base}/shipments", headers=admin, json={
                "sales_order_id": order, "warehouse_id": 1,
                "lines": [{"material_id": material, "quantity": quantity}]})
            assert result.status_code == 201
            return result.json()

        first = create_shipment("1")
        second = create_shipment("1")
        first_url = f"{base}/shipments/{first['id']}/reverse"
        second_url = f"{base}/shipments/{second['id']}/reverse"
        assert client.post(first_url, headers=admin, json={"reason": "草稿"}).status_code == 409
        assert client.post(f"{base}/shipments/999/reverse", headers=admin,
                           json={"reason": "不存在"}).status_code == 404
        approve_document(client, admin, 'Shipment', first['id'])
        assert client.post(f"{base}/shipments/{first['id']}/post", headers=admin).status_code == 200
        approve_document(client, admin, 'Shipment', second['id'])
        assert client.post(f"{base}/shipments/{second['id']}/post", headers=admin).status_code == 200
        assert client.get(f"{base}/sales-orders", headers=admin).json()[0]["status"] == "shipped"
        assert client.post(first_url, headers=seller, json={"reason": "无权"}).status_code == 403
        assert client.post(first_url, headers=admin, json={"reason": "   "}).status_code == 422

        # 有效退货先冲销，否则原出库冲销会重复增加库存与应收更正。
        return_payload = {"shipment_id": first["id"], "warehouse_id": 1,
                          "reason": "客户退回", "lines": [{
                              "shipment_line_id": first["lines"][0]["id"], "quantity": "1"}]}
        returned = client.post(f"{base}/sales-returns", headers=admin,
                               json=return_payload).json()["id"]
        approve_document(client, admin, 'SalesReturn', returned)
        assert client.post(f"{base}/sales-returns/{returned}/post",
                           headers=admin).status_code == 200
        approve_document(client, admin, 'Shipment', first['id'], intent='reverse', reason='误出库')
        assert client.post(first_url, headers=admin, json={"reason": "误出"}).status_code == 409
        approve_document(client, admin, 'SalesReturn', returned, intent='reverse', reason='误退')
        assert client.post(f"{base}/sales-returns/{returned}/reverse", headers=admin,
                           json={"reason": "误退"}).status_code == 201

        approve_document(client, admin, 'Shipment', second['id'], intent='reverse', reason='误出库')
        reversed_second = client.post(second_url, headers=admin, json={"reason": "误出库"})
        assert reversed_second.status_code == 201
        assert reversed_second.json()["reversal_reason"] == "误出库"
        assert reversed_second.json()["reversed_by_name"] == "admin"
        assert reversed_second.json()["lines"][0]["returnable_quantity"] == "0"
        assert client.get(f"{base}/sales-orders", headers=admin).json()[0]["status"] == "partially_shipped"
        assert client.post(second_url, headers=admin, json={"reason": "重复"}).status_code == 409
        assert client.post(first_url, headers=admin, json={"reason": "误出库"}).status_code == 201
        order_after = client.get(f"{base}/sales-orders", headers=admin).json()[0]
        assert order_after["status"] == "confirmed"
        assert order_after["lines"][0]["remaining_quantity"] == "2"
        assert order_after["lines"][0]["returned_quantity"] == "0"
        assert client.get(f"{base}/stock?warehouse_id=1", headers=admin).json()[0]["quantity"] == "2"

        # 冲销后原单仍可查，但原出库不再允许退货；新出库可以重新完成订单。
        assert client.post(f"{base}/sales-returns", headers=admin,
                           json=return_payload).status_code == 409
        entries = client.get(f"{base}/finance/receivables-payables", headers=admin).json()
        assert entries["receivable_amount"] == "0.00"
        assert len([item for item in entries["entries"]
                    if item["source_type"] == "shipment_reversal"]) == 2
        movements = client.get(f"{base}/movements", headers=admin).json()
        assert movements[0]["source_type"] == "shipment_reversal"
        assert movements[0]["shipment_reversal_id"] is not None
        replacement = create_shipment("2")
        approve_document(client, admin, 'Shipment', replacement['id'])
        assert client.post(f"{base}/shipments/{replacement['id']}/post",
                           headers=admin).status_code == 200
        assert client.get(f"{base}/sales-orders", headers=admin).json()[0]["status"] == "shipped"
