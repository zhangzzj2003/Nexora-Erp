"""其他入库只能由单据确认入账，且不会形成采购应付。"""

from approval_test_helpers import approve_document
from fastapi.testclient import TestClient

from app.main import app


def test_other_inbound_post_and_audited_reverse(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "other-inbound.db"))
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        base = "/api/v1"
        assert client.post(f"{base}/setup/admin", json={
            "username": "admin", "password": "secure-pass-123"}).status_code == 201
        token = client.post(f"{base}/auth/login", json={
            "username": "admin", "password": "secure-pass-123"}).json()["token"]
        admin = {"Authorization": f"Bearer {token}"}
        material = client.post(f"{base}/materials", headers=admin, json={
            "sku": "GIFT", "name": "赠品物料", "unit": "件"}).json()["id"]
        second_warehouse = client.post(f"{base}/warehouses", headers=admin, json={
            "code": "SECOND", "name": "第二仓"}).json()["id"]
        payload = {"warehouse_id": 1, "reason": "gift", "note": "赠品入库",
                   "reference": "GIFT-1", "lines": [{"material_id": material, "quantity": "2"}]}
        assert client.post(f"{base}/warehouse-inbounds", headers=admin, json={
            **payload, "lines": payload["lines"] * 2}).status_code == 422
        created = client.post(f"{base}/warehouse-inbounds", headers=admin, json=payload)
        assert created.status_code == 201
        inbound_id = created.json()["id"]
        assert client.get(f"{base}/stock", headers=admin).json()[0]["quantity"] == "0"
        approve_document(client, admin, 'WarehouseInbound', inbound_id)
        assert client.post(f"{base}/warehouse-inbounds/{inbound_id}/post", headers=admin).status_code == 200
        assert client.post(f"{base}/warehouse-inbounds/{inbound_id}/post", headers=admin).status_code == 409
        assert client.get(f"{base}/stock", headers=admin).json()[0]["quantity"] == "2"
        assert client.get(f"{base}/finance/receivables-payables", headers=admin).json()["entries"] == []
        movements = client.get(f"{base}/movements", headers=admin).json()
        assert movements[0]["source_type"] == "other_inbound"
        assert movements[0]["other_inbound_id"] == inbound_id

        transfer = client.post(f"{base}/transfers", headers=admin, json={
            "from_warehouse_id": 1, "to_warehouse_id": second_warehouse,
            "lines": [{"material_id": material, "quantity": "2"}]}).json()["id"]
        approve_document(client, admin, 'Transfer', transfer)
        assert client.post(f"{base}/transfers/{transfer}/post", headers=admin).status_code == 200
        approve_document(client, admin, 'WarehouseInbound', inbound_id, intent='reverse', reason='误录')
        assert client.post(f"{base}/warehouse-inbounds/{inbound_id}/reverse", headers=admin,
                           json={"reason": "误录"}).status_code == 409
        back = client.post(f"{base}/transfers", headers=admin, json={
            "from_warehouse_id": second_warehouse, "to_warehouse_id": 1,
            "lines": [{"material_id": material, "quantity": "2"}]}).json()["id"]
        approve_document(client, admin, 'Transfer', back)
        assert client.post(f"{base}/transfers/{back}/post", headers=admin).status_code == 200
        reversed_entry = client.post(f"{base}/warehouse-inbounds/{inbound_id}/reverse",
                                     headers=admin, json={"reason": "误录"})
        assert reversed_entry.status_code == 201
        assert reversed_entry.json()["reversal_reason"] == "误录"
        assert client.post(f"{base}/warehouse-inbounds/{inbound_id}/reverse", headers=admin,
                           json={"reason": "再次冲销"}).status_code == 409
        assert client.get(f"{base}/stock", headers=admin).json()[0]["quantity"] == "0"
