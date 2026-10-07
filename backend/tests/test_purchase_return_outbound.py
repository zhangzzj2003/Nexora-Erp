"""采购退货提交后由仓库确认出库，验证预留、重复操作和流水时点。"""

from approval_test_helpers import approve_document

from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app


def test_return_requires_warehouse_outbound_confirmation(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "return-outbound.db"))
    with TestClient(app, client=("127.0.0.1", 12000)) as client:
        base = "/api/v1"
        client.post(f"{base}/setup/admin", json={"username": "admin", "password": "secure-pass-123"})
        token = client.post(f"{base}/auth/login", json={
            "username": "admin", "password": "secure-pass-123"}).json()["token"]
        auth = {"Authorization": f"Bearer {token}"}
        supplier = client.post(f"{base}/suppliers", headers=auth, json={"name": "供货商"}).json()["id"]
        material = client.post(f"{base}/materials", headers=auth, json={
            "sku": "RET-OUT", "name": "退货物料", "unit": "件"}).json()["id"]
        receipt = client.post(f"{base}/receipts", headers=auth, json={
            "supplier_id": supplier, "warehouse_id": 1, "purchase_order_id": None,
            "lines": [{"material_id": material, "quantity": "3"}]}).json()
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, auth, 'Receipt', receipt['id'])
        assert client.post(f"{base}/receipts/{receipt['id']}/post", headers=auth).status_code == 200
        payload = {"receipt_id": receipt["id"], "reason": "质量问题", "lines": [
            {"receipt_line_id": receipt["lines"][0]["id"], "quantity": "2"}]}
        return_id = client.post(f"{base}/purchase-returns", headers=auth, json=payload).json()["id"]
        before = len(client.get(f"{base}/movements", headers=auth).json())

        submitted = client.post(f"{base}/purchase-returns/{return_id}/submit", headers=auth)
        assert submitted.status_code == 200
        outbound_id = submitted.json()["outbound_id"]
        assert submitted.json()["outbound_status"] == "draft"
        assert client.post(f"{base}/purchase-returns/{return_id}/submit", headers=auth).status_code == 409
        assert len(client.get(f"{base}/movements", headers=auth).json()) == before
        assert Decimal(client.get(f"{base}/stock?warehouse_id=1", headers=auth).json()[0]["quantity"]) == 3
        # 待出库量占用可退额度，另一张超量退货不能再提交。
        assert client.post(f"{base}/purchase-returns", headers=auth, json={
            **payload, "lines": [{"receipt_line_id": receipt["lines"][0]["id"], "quantity": "2"}]
        }).status_code == 409

        confirmed = client.post(f"{base}/warehouse-outbounds/{outbound_id}/post", headers=auth)
        assert confirmed.status_code == 200
        assert confirmed.json()["purchase_return_id"] == return_id
        assert client.post(f"{base}/warehouse-outbounds/{outbound_id}/post", headers=auth).status_code == 409
        assert len(client.get(f"{base}/movements", headers=auth).json()) == before + 1
        assert Decimal(client.get(f"{base}/stock?warehouse_id=1", headers=auth).json()[0]["quantity"]) == 1
        assert client.get(f"{base}/purchase-returns", headers=auth).json()[0]["status"] == "posted"
        assert client.post(f"{base}/purchase-returns/{return_id}/cancel", headers=auth).status_code == 409

        # 取消一张新的待出库退货后释放原入库可退量，且不追加库存流水。
        pending = client.post(f"{base}/purchase-returns", headers=auth, json={
            **payload, "lines": [{"receipt_line_id": receipt["lines"][0]["id"], "quantity": "1"}]
        }).json()["id"]
        pending_outbound = client.post(f"{base}/purchase-returns/{pending}/submit",
                                       headers=auth).json()["outbound_id"]
        movement_count = len(client.get(f"{base}/movements", headers=auth).json())
        assert client.post(f"{base}/purchase-returns/{pending}/cancel", headers=auth).status_code == 200
        assert client.post(f"{base}/warehouse-outbounds/{pending_outbound}/post",
                           headers=auth).status_code == 409
        assert len(client.get(f"{base}/movements", headers=auth).json()) == movement_count
        replacement = client.post(f"{base}/purchase-returns", headers=auth, json={
            **payload, "lines": [{"receipt_line_id": receipt["lines"][0]["id"], "quantity": "1"}]
        }).json()["id"]
        assert client.post(f"{base}/purchase-returns/{replacement}/submit", headers=auth).status_code == 200
