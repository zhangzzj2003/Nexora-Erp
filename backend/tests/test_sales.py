"""验证销售订单分批出库、库存扣减、服务端权限及草稿竞争。"""

from approval_test_helpers import approve_document

from fastapi.testclient import TestClient

from app.main import app


def test_sales_orders_shipments_and_audit(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "sales.db"))
    with TestClient(app, client=("127.0.0.1", 12000)) as client:
        base = "/api/v1"
        client.post(f"{base}/setup/admin", json={"username": "admin", "password": "secure-pass-123"})

        def login(username: str) -> dict:
            token = client.post(f"{base}/auth/login", json={
                "username": username, "password": "secure-pass-123"}).json()["token"]
            return {"Authorization": f"Bearer {token}"}

        admin = login("admin")
        for username, role in (("seller", "seller"), ("warehouse", "warehouse"), ("viewer", "viewer")):
            assert client.post(f"{base}/users", headers=admin, json={
                "username": username, "password": "secure-pass-123", "roles": [role]}).status_code == 201
        seller, warehouse, viewer = login("seller"), login("warehouse"), login("viewer")
        assert client.get(f"{base}/customers", headers=viewer).status_code == 403
        assert client.post(f"{base}/customers", headers=admin, json={"name": "   "}).status_code == 422
        customer = client.post(f"{base}/customers", headers=seller, json={"name": "客户甲"})
        assert customer.status_code == 201
        customer_id = customer.json()["id"]
        assert client.post(f"{base}/customers", headers=seller, json={"name": "客户甲"}).status_code == 409
        assert client.post(f"{base}/customers", headers=warehouse, json={"name": "客户乙"}).status_code == 403

        material = client.post(f"{base}/materials", headers=admin, json={
            "sku": "SALE", "name": "销售物料", "unit": "件"}).json()["id"]
        supplier = client.post(f"{base}/suppliers", headers=admin, json={"name": "供应商"}).json()["id"]
        receipt = client.post(f"{base}/receipts", headers=admin, json={
            "supplier_id": supplier, "lines": [{"material_id": material, "quantity": "3.125"}]}).json()["id"]
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, admin, 'Receipt', receipt)
        assert client.post(f"{base}/receipts/{receipt}/post", headers=admin).status_code == 200
        second = client.post(f"{base}/warehouses", headers=admin, json={
            "code": "EMPTY", "name": "空仓"}).json()["id"]

        payload = {"customer_id": customer_id, "reference": "SO-001", "lines": [
            {"material_id": material, "quantity": "3.125", "unit_price": "4.4567"}]}
        assert client.post(f"{base}/sales-orders", headers=viewer, json=payload).status_code == 403
        assert client.post(f"{base}/sales-orders", headers=seller, json={
            **payload, "lines": payload["lines"] * 2}).status_code == 422
        order = client.post(f"{base}/sales-orders", headers=seller, json=payload)
        assert order.status_code == 201
        order_id = order.json()["id"]
        assert order.json()["total_amount"] == "13.93"
        shipment_payload = {"sales_order_id": order_id, "warehouse_id": 1,
                            "lines": [{"material_id": material, "quantity": "1.125"}]}
        assert client.post(f"{base}/shipments", headers=warehouse, json=shipment_payload).status_code == 409
        assert client.post(f"{base}/sales-orders/{order_id}/confirm", headers=viewer).status_code == 403
        approve_document(client, admin, 'SalesOrder', order_id)
        assert client.post(f"{base}/sales-orders/{order_id}/confirm", headers=seller).status_code == 200
        assert client.post(f"{base}/sales-orders/{order_id}/confirm", headers=seller).status_code == 409

        # 出库必须从指定仓扣减；库存不足时既不写流水，也不改变订单进度。
        empty = client.post(f"{base}/shipments", headers=warehouse, json={
            **shipment_payload, "warehouse_id": second}).json()["id"]
        approve_document(client, admin, 'Shipment', empty)
        assert client.post(f"{base}/shipments/{empty}/post", headers=warehouse).status_code == 409
        state = client.get(f'/api/v1/system/document-approvals/Shipment/{empty}', headers=admin).json()
        assert client.post(f'/api/v1/system/document-approvals/Shipment/{empty}/withdraw', headers=admin, json={'version': state['version']}).status_code == 200
        assert client.post(f"{base}/shipments/{empty}/cancel", headers=warehouse).status_code == 200
        assert client.post(f"{base}/shipments/{empty}/post", headers=warehouse).status_code == 409
        first = client.post(f"{base}/shipments", headers=seller, json=shipment_payload).json()["id"]
        assert client.post(f"{base}/shipments/{first}/post", headers=seller).status_code == 403
        approve_document(client, admin, 'Shipment', first)
        assert client.post(f"{base}/shipments/{first}/post", headers=warehouse).status_code == 200
        assert client.post(f"{base}/shipments/{first}/post", headers=warehouse).status_code == 409
        partial = client.get(f"{base}/sales-orders", headers=seller).json()[0]
        assert partial["status"] == "partially_shipped"
        assert partial["lines"][0]["remaining_quantity"] == "2.000"
        assert client.get(f"{base}/stock?warehouse_id=1", headers=admin).json()[0]["quantity"] == "2.000"
        assert client.post(f"{base}/sales-orders/{order_id}/cancel", headers=seller).status_code == 409

        # 两张草稿可同时存在，但确认时重新核对剩余量，只允许一张完成。
        rest = {**shipment_payload, "lines": [{"material_id": material, "quantity": "2.000"}]}
        a = client.post(f"{base}/shipments", headers=warehouse, json=rest).json()["id"]
        b = client.post(f"{base}/shipments", headers=warehouse, json=rest).json()["id"]
        approve_document(client, admin, 'Shipment', a)
        assert client.post(f"{base}/shipments/{a}/post", headers=warehouse).status_code == 200
        approve_document(client, admin, 'Shipment', b)
        assert client.post(f"{base}/shipments/{b}/post", headers=warehouse).status_code == 409
        assert client.get(f"{base}/sales-orders", headers=seller).json()[0]["status"] == "shipped"
        assert client.get(f"{base}/stock?warehouse_id=1", headers=admin).json()[0]["quantity"] == "0.000"
        movements = client.get(f"{base}/movements", headers=admin).json()
        assert [item["quantity"] for item in movements[:2]] == ["-2.000", "-1.125"]
        assert movements[0]["source_type"] == "shipment"
        assert movements[0]["shipment_id"] == a
        assert movements[0]["created_by"] is not None
        assert client.post(f"{base}/shipments/{a}/cancel", headers=warehouse).status_code == 409
        assert client.post(f"{base}/shipments", headers=warehouse, json=rest).status_code == 409

        # 没有任何确认出库的销售订单才允许取消。
        other = client.post(f"{base}/sales-orders", headers=seller, json=payload).json()["id"]
        assert client.post(f"{base}/sales-orders/{other}/cancel", headers=seller).status_code == 200
        assert client.post(f"{base}/sales-orders/{other}/confirm", headers=seller).status_code == 409
