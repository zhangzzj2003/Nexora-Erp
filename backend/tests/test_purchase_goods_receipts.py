"""分批收货只生成待入库单，拒收和重复确认不改变库存。"""

from approval_test_helpers import approve_document

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi.testclient import TestClient

from app.main import app


def prepare(client):
    base = "/api/v1"
    assert client.post(f"{base}/setup/admin", json={
        "username": "admin", "password": "secure-pass-123"}).status_code == 201
    token = client.post(f"{base}/auth/login", json={
        "username": "admin", "password": "secure-pass-123"}).json()["token"]
    admin = {"Authorization": f"Bearer {token}"}
    supplier = client.post(f"{base}/suppliers", headers=admin, json={"name": "甲供应商"}).json()["id"]
    material = client.post(f"{base}/materials", headers=admin, json={
        "sku": "RCV", "name": "收货物料", "unit": "件"}).json()["id"]
    order = client.post(f"{base}/purchase-orders", headers=admin, json={
        "supplier_id": supplier, "lines": [{"material_id": material,
                                         "quantity": "10", "unit_price": "3"}]}).json()
    # 先完成真实独立审批，保留原业务失败和并发断言。
    approve_document(client, admin, 'PurchaseOrder', order['id'])
    assert client.post(f"{base}/purchase-orders/{order['id']}/confirm", headers=admin).status_code == 200
    return base, admin, order


def test_received_goods_wait_for_warehouse_post(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "goods.db"))
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        base, admin, order = prepare(client)
        line_id = order["lines"][0]["id"]
        payload = {"purchase_order_id": order["id"], "warehouse_id": 1,
                   "reference": "DELIVERY-1", "lines": [{
                       "purchase_order_line_id": line_id, "accepted_quantity": "6",
                       "rejected_quantity": "2", "rejection_reason": "外包装破损"}]}
        created = client.post(f"{base}/purchase-goods-receipts", headers=admin, json=payload)
        assert created.status_code == 201
        goods_id = created.json()["id"]
        assert created.json()["inbound_receipt_id"] is None
        assert client.post(f"{base}/purchase-goods-receipts", headers=admin, json={
            **payload, "lines": [{**payload["lines"][0], "rejection_reason": " "}]}).status_code == 422

        # 先完成真实独立审批，保留原业务失败和并发断言。
        approve_document(client, admin, 'PurchaseGoodsReceipt', goods_id)
        confirmed = client.post(f"{base}/purchase-goods-receipts/{goods_id}/confirm", headers=admin)
        assert confirmed.status_code == 200
        inbound_id = confirmed.json()["inbound_receipt_id"]
        assert inbound_id > 0
        assert confirmed.json()["inbound_status"] == "draft"
        assert client.post(f"{base}/purchase-goods-receipts/{goods_id}/confirm", headers=admin).status_code == 409
        assert client.get(f"{base}/stock", headers=admin).json()[0]["quantity"] == "0"
        assert client.get(f"{base}/finance/receivables-payables", headers=admin).json()["entries"] == []
        assert client.post(f"{base}/purchase-goods-receipts", headers=admin, json={
            **payload, "lines": [{"purchase_order_line_id": line_id,
                                   "accepted_quantity": "5", "rejected_quantity": "0"}]}).status_code == 409
        # 先完成真实独立审批，保留原业务失败和并发断言。
        approve_document(client, admin, 'Receipt', inbound_id)
        posted = client.post(f"{base}/receipts/{inbound_id}/post", headers=admin)
        assert posted.status_code == 200
        assert posted.json()["goods_receipt_id"] == goods_id
        assert client.get(f"{base}/stock", headers=admin).json()[0]["quantity"] == "6"
        assert client.get(f"{base}/purchase-orders", headers=admin).json()[0]["lines"][0]["remaining_quantity"] == "4"
        payable = client.get(f"{base}/finance/receivables-payables", headers=admin).json()
        assert payable["payable_amount"] == "18.00"
        assert [entry["source_type"] for entry in payable["entries"]] == ["receipt"]

        # 新收货链路产生的应付只在仓库确认退货出库后减少，待出库阶段不提前冲减。
        purchase_return = client.post(f"{base}/purchase-returns", headers=admin, json={
            "receipt_id": inbound_id, "reason": "质量问题", "lines": [{
                "receipt_line_id": posted.json()["lines"][0]["id"], "quantity": "2"}]}).json()
        approve_document(client, admin, 'PurchaseReturn', purchase_return['id'])
        outbound_id = client.post(f"{base}/purchase-returns/{purchase_return['id']}/submit",
                                  headers=admin).json()["outbound_id"]
        assert client.get(f"{base}/finance/receivables-payables", headers=admin).json()["payable_amount"] == "18.00"
        approve_document(client, admin, 'WarehouseOutbound', outbound_id)
        assert client.post(f"{base}/warehouse-outbounds/{outbound_id}/post", headers=admin).status_code == 200
        assert client.post(f"{base}/warehouse-outbounds/{outbound_id}/post", headers=admin).status_code == 409
        payable_after_return = client.get(f"{base}/finance/receivables-payables", headers=admin).json()
        assert payable_after_return["payable_amount"] == "12.00"
        assert {entry["source_type"] for entry in payable_after_return["entries"]} == {"receipt", "purchase_return"}
        assert client.get(f"{base}/stock", headers=admin).json()[0]["quantity"] == "4"
        ledger = client.post(f"{base}/inventory-ledger/query", headers=admin, json={
            "warehouse_id": 1, "material_id": order["lines"][0]["material_id"]}).json()
        assert [(row["source_type"], row["source_id"], row["balance_quantity"])
                for row in ledger["rows"]] == [
                    ("receipt", inbound_id, "6"), ("purchase_return", purchase_return["id"], "4")]
        assert ledger["groups"][0]["closing_quantity"] == "4"

        # 全数拒收只记录原因，不伪造空入库单。
        rejected = client.post(f"{base}/purchase-goods-receipts", headers=admin, json={
            **payload, "lines": [{"purchase_order_line_id": line_id,
                                   "accepted_quantity": "0", "rejected_quantity": "4",
                                   "rejection_reason": "规格不符"}]}).json()
        # 先完成真实独立审批，保留原业务失败和并发断言。
        approve_document(client, admin, 'PurchaseGoodsReceipt', rejected['id'])
        rejected_done = client.post(f"{base}/purchase-goods-receipts/{rejected['id']}/confirm",
                                    headers=admin).json()
        assert rejected_done["inbound_receipt_id"] is None
        assert client.get(f"{base}/stock", headers=admin).json()[0]["quantity"] == "4"


def test_parallel_goods_confirmation_cannot_overreserve(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "parallel-goods.db"))
    with (TestClient(app, client=("127.0.0.1", 12345)) as first,
          TestClient(app, client=("127.0.0.1", 12346)) as second):
        base, admin, order = prepare(first)
        payload = {"purchase_order_id": order["id"], "warehouse_id": 1, "lines": [{
            "purchase_order_line_id": order["lines"][0]["id"],
            "accepted_quantity": "6", "rejected_quantity": "0"}]}
        ids = [first.post(f"{base}/purchase-goods-receipts", headers=admin, json=payload).json()["id"]
               for _ in range(2)]
        # 先完成真实独立审批，保留原业务失败和并发断言。
        for identifier in ids:
            approve_document(first, admin, 'PurchaseGoodsReceipt', identifier)
        barrier = Barrier(2)

        def confirm(item):
            client, goods_id = item
            barrier.wait(timeout=5)
            return client.post(f"{base}/purchase-goods-receipts/{goods_id}/confirm",
                               headers=admin).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(confirm, zip((first, second), ids)))
        assert sorted(outcomes) == [200, 409]
        assert len(first.get(f"{base}/receipts", headers=admin).json()) == 1
