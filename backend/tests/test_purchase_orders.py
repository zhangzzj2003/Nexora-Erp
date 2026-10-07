"""采购订单、分批入库和超量阻断的业务回归。"""

from approval_test_helpers import approve_document

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi.testclient import TestClient

from app.main import app


def test_purchase_order_receipt_lifecycle(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "orders.db"))
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        base = "/api/v1"
        client.post(f"{base}/setup/admin", json={"username": "admin", "password": "secure-pass-123"})
        token = client.post(f"{base}/auth/login", json={
            "username": "admin", "password": "secure-pass-123"}).json()["token"]
        admin = {"Authorization": f"Bearer {token}"}
        viewer = client.post(f"{base}/users", headers=admin, json={
            "username": "viewer", "password": "secure-pass-123", "roles": ["viewer"]})
        assert viewer.status_code == 201
        viewer_token = client.post(f"{base}/auth/login", json={
            "username": "viewer", "password": "secure-pass-123"}).json()["token"]
        view = {"Authorization": f"Bearer {viewer_token}"}
        supplier = client.post(f"{base}/suppliers", headers=admin, json={"name": "甲供应商"}).json()["id"]
        other_supplier = client.post(f"{base}/suppliers", headers=admin, json={"name": "乙供应商"}).json()["id"]
        material = client.post(f"{base}/materials", headers=admin, json={
            "sku": "A", "name": "物料A", "unit": "件"}).json()["id"]
        other_material = client.post(f"{base}/materials", headers=admin, json={
            "sku": "B", "name": "物料B", "unit": "件"}).json()["id"]
        payload = {"supplier_id": supplier, "reference": "PO-EXT", "lines": [
            {"material_id": material, "quantity": "10.000", "unit_price": "2.3456"}]}

        # 服务端拒绝越权、重复物料及非法单价，草稿不能直接关联入库。
        assert client.post(f"{base}/purchase-orders", headers=view, json=payload).status_code == 403
        assert client.post(f"{base}/purchase-orders", headers=admin, json={
            **payload, "lines": payload["lines"] * 2}).status_code == 422
        assert client.post(f"{base}/purchase-orders", headers=admin, json={
            **payload, "lines": [{**payload["lines"][0], "unit_price": "-1"}]}).status_code == 422
        created = client.post(f"{base}/purchase-orders", headers=admin, json=payload)
        assert created.status_code == 201
        order_id = created.json()["id"]
        assert created.json()["status"] == "draft"
        assert created.json()["total_amount"] == "23.46"
        receipt_input = {"supplier_id": supplier, "warehouse_id": 1, "purchase_order_id": order_id,
                         "lines": [{"material_id": material, "quantity": "6"}]}
        assert client.post(f"{base}/receipts", headers=admin, json=receipt_input).status_code == 409
        assert client.post(f"{base}/purchase-orders/{order_id}/confirm", headers=view).status_code == 403
        # 先完成真实独立审批，保留原业务失败和并发断言。
        approve_document(client, admin, 'PurchaseOrder', order_id)
        assert client.post(f"{base}/purchase-orders/{order_id}/confirm", headers=admin).status_code == 200
        assert client.post(f"{base}/purchase-orders/{order_id}/confirm", headers=admin).status_code == 409
        assert client.post(f"{base}/receipts", headers=admin, json={
            **receipt_input, "supplier_id": other_supplier}).status_code == 422
        assert client.post(f"{base}/receipts", headers=admin, json={
            **receipt_input, "lines": [{"material_id": other_material, "quantity": "1"}]}).status_code == 422
        assert client.post(f"{base}/receipts", headers=admin, json={
            **receipt_input, "lines": [{"material_id": material, "quantity": "11"}]}).status_code == 409

        first = client.post(f"{base}/receipts", headers=admin, json=receipt_input)
        assert first.status_code == 201
        assert first.json()["purchase_order_id"] == order_id
        # 第二张草稿可先创建；确认时须重新计算已入库量，禁止并发草稿超量。
        pending = client.post(f"{base}/receipts", headers=admin, json={
            **receipt_input, "lines": [{"material_id": material, "quantity": "5"}]})
        assert pending.status_code == 201
        # 先完成真实独立审批，保留原业务失败和并发断言。
        approve_document(client, admin, 'Receipt', first.json()['id'])
        assert client.post(f"{base}/receipts/{first.json()['id']}/post", headers=admin).status_code == 200
        # 先完成真实独立审批，保留原业务失败和并发断言。
        approve_document(client, admin, 'Receipt', pending.json()['id'])
        assert client.post(f"{base}/receipts/{pending.json()['id']}/post", headers=admin).status_code == 409
        mid = client.get(f"{base}/purchase-orders", headers=view).json()[0]
        assert mid["status"] == "partially_received"
        assert mid["lines"][0]["received_quantity"] == "6"
        assert mid["lines"][0]["remaining_quantity"] == "4.000"
        assert client.post(f"{base}/purchase-orders/{order_id}/cancel", headers=admin).status_code == 409

        final = client.post(f"{base}/receipts", headers=admin, json={
            **receipt_input, "lines": [{"material_id": material, "quantity": "4"}]})
        assert final.status_code == 201
        # 先完成真实独立审批，保留原业务失败和并发断言。
        approve_document(client, admin, 'Receipt', final.json()['id'])
        assert client.post(f"{base}/receipts/{final.json()['id']}/post", headers=admin).status_code == 200
        complete = client.get(f"{base}/purchase-orders", headers=view).json()[0]
        assert complete["status"] == "received"
        assert complete["lines"][0]["remaining_quantity"] == "0.000"
        assert client.get(f"{base}/stock", headers=view).json()[0]["quantity"] == "10"
        assert client.post(f"{base}/receipts", headers=admin, json={
            **receipt_input, "lines": [{"material_id": material, "quantity": "1"}]}).status_code == 409

        # 未入库订单可以取消，取消后不能再确认或入库；单据留存供审计。
        extra = client.post(f"{base}/purchase-orders", headers=admin, json=payload).json()["id"]
        assert client.post(f"{base}/purchase-orders/{extra}/cancel", headers=admin).status_code == 200
        assert client.post(f"{base}/purchase-orders/{extra}/confirm", headers=admin).status_code == 409


def test_two_sessions_cannot_post_receipts_beyond_order_quantity(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "concurrent-receipts.db"))
    with (TestClient(app, client=("127.0.0.1", 12345)) as first,
          TestClient(app, client=("127.0.0.1", 12346)) as second):
        base = "/api/v1"
        assert first.post(f"{base}/setup/admin", json={
            "username": "admin", "password": "secure-pass-123"}).status_code == 201
        # 两个独立登录会话分别持有一张草稿，模拟两台客户端同时确认。
        headers = []
        for client in (first, second):
            token = client.post(f"{base}/auth/login", json={
                "username": "admin", "password": "secure-pass-123"}).json()["token"]
            headers.append({"Authorization": f"Bearer {token}"})
        supplier_id = first.post(f"{base}/suppliers", headers=headers[0], json={
            "name": "并发供应商"}).json()["id"]
        material_id = first.post(f"{base}/materials", headers=headers[0], json={
            "sku": "CONCURRENT", "name": "并发物料", "unit": "件"}).json()["id"]
        order_id = first.post(f"{base}/purchase-orders", headers=headers[0], json={
            "supplier_id": supplier_id,
            "lines": [{"material_id": material_id, "quantity": "10", "unit_price": "2"}]
        }).json()["id"]
        # 先完成真实独立审批，保留原业务失败和并发断言。
        approve_document(first, headers[0], 'PurchaseOrder', order_id)
        assert first.post(f"{base}/purchase-orders/{order_id}/confirm",
                          headers=headers[0]).status_code == 200
        receipt_ids = []
        for client, authorization in zip((first, second), headers):
            response = client.post(f"{base}/receipts", headers=authorization, json={
                "supplier_id": supplier_id, "purchase_order_id": order_id,
                "lines": [{"material_id": material_id, "quantity": "6"}]})
            assert response.status_code == 201
            receipt_ids.append(response.json()["id"])

        # 先完成真实独立审批，保留原业务失败和并发断言。
        for identifier in receipt_ids:
            approve_document(first, headers[0], 'Receipt', identifier)
        ready = Barrier(2)

        def post_receipt(client, authorization, receipt_id):
            ready.wait(timeout=5)
            return client.post(f"{base}/receipts/{receipt_id}/post",
                               headers=authorization).status_code

        with ThreadPoolExecutor(max_workers=2) as workers:
            outcomes = list(workers.map(
                lambda values: post_receipt(*values),
                zip((first, second), headers, receipt_ids)))

        # 任一先取得写锁的请求可以成功；另一请求必须看到更新后的剩余数量。
        assert sorted(outcomes) == [200, 409]
        assert first.get(f"{base}/stock", headers=headers[0]).json()[0]["quantity"] == "6"
        movements = second.get(f"{base}/movements", headers=headers[1]).json()
        assert len(movements) == 1
        assert movements[0]["quantity"] == "6"
        order = first.get(f"{base}/purchase-orders", headers=headers[0]).json()[0]
        assert order["lines"][0]["remaining_quantity"] == "4"
