"""库存调整必须异人审批、仓库确认；不足与重复操作不产生流水。"""

from approval_test_helpers import approve_document
from fastapi.testclient import TestClient

from app.main import app


def test_adjustment_approval_post_and_reverse(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "adjustment.db"))
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        base = "/api/v1"
        client.post(f"{base}/setup/admin", json={"username": "admin", "password": "secure-pass-123"})

        def login(name):
            token = client.post(f"{base}/auth/login", json={
                "username": name, "password": "secure-pass-123"}).json()["token"]
            return {"Authorization": f"Bearer {token}"}

        admin = login("admin")
        client.post(f"{base}/users", headers=admin, json={
            "username": "checker", "password": "secure-pass-123", "roles": ["warehouse"]})
        checker = login("checker")
        material = client.post(f"{base}/materials", headers=admin, json={
            "sku": "ADJ", "name": "调整物料", "unit": "件"}).json()["id"]
        payload = {"warehouse_id": 1, "reason": "在途差异", "reference": "ADJ-1",
                   "lines": [{"material_id": material, "quantity": "2"}]}
        assert client.post(f"{base}/stock-adjustments", headers=admin, json={
            **payload, "lines": [{"material_id": material, "quantity": "0"}]}).status_code == 422
        item = client.post(f"{base}/stock-adjustments", headers=admin, json=payload).json()
        item_id = item["id"]
        before = len(client.get(f"{base}/movements", headers=admin).json())
        assert client.post(f"{base}/stock-adjustments/{item_id}/post", headers=admin).status_code == 409
        approve_document(client, admin, 'StockAdjustment', item_id)
        assert len(client.get(f"{base}/movements", headers=admin).json()) == before
        assert client.post(f"{base}/stock-adjustments/{item_id}/post", headers=checker).status_code == 200
        assert client.post(f"{base}/stock-adjustments/{item_id}/post", headers=checker).status_code == 409
        assert client.get(f"{base}/stock?warehouse_id=1", headers=admin).json()[0]["quantity"] == "2"
        assert len(client.get(f"{base}/movements", headers=admin).json()) == before + 1
        approve_document(client, admin, 'StockAdjustment', item_id, intent='reverse', reason='录入错误')
        assert client.post(f"{base}/stock-adjustments/{item_id}/reverse", headers=admin,
                           json={"reason": "录入错误"}).status_code == 201
        assert client.post(f"{base}/stock-adjustments/{item_id}/reverse", headers=admin,
                           json={"reason": "再次冲销"}).status_code == 409
        assert client.get(f"{base}/stock?warehouse_id=1", headers=admin).json()[0]["quantity"] == "0"

        negative = client.post(f"{base}/stock-adjustments", headers=admin, json={
            **payload, "lines": [{"material_id": material, "quantity": "-1"}]}).json()["id"]
        state = approve_document(client, admin, 'StockAdjustment', negative)
        assert client.post(f"{base}/stock-adjustments/{negative}/post", headers=checker).status_code == 409
        assert client.post(f'{base}/system/document-approvals/StockAdjustment/{negative}/withdraw',
                           headers=admin, json={'version': state['version']}).status_code == 200
        assert client.post(f"{base}/stock-adjustments/{negative}/cancel", headers=admin).status_code == 200
