"""库存台账按相同筛选结果核对期初、逐笔结余与期末。"""

from approval_test_helpers import approve_document
from fastapi.testclient import TestClient

from app.main import app


def test_ledger_filters_and_balances(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "ledger.db"))
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        base = "/api/v1"
        client.post(f"{base}/setup/admin", json={"username": "admin", "password": "secure-pass-123"})
        token = client.post(f"{base}/auth/login", json={
            "username": "admin", "password": "secure-pass-123"}).json()["token"]
        auth = {"Authorization": f"Bearer {token}"}
        material = client.post(f"{base}/materials", headers=auth, json={
            "sku": "LEDGER", "name": "台账物料", "unit": "件"}).json()["id"]
        inbound = client.post(f"{base}/warehouse-inbounds", headers=auth, json={
            "warehouse_id": 1, "reason": "opening", "note": "期初",
            "lines": [{"material_id": material, "quantity": "5"}]}).json()["id"]
        approve_document(client, auth, 'WarehouseInbound', inbound)
        client.post(f"{base}/warehouse-inbounds/{inbound}/post", headers=auth)
        outbound = client.post(f"{base}/warehouse-outbounds", headers=auth, json={
            "warehouse_id": 1, "reason": "sample", "note": "样品",
            "lines": [{"material_id": material, "quantity": "2"}]}).json()["id"]
        client.post(f"{base}/warehouse-outbounds/{outbound}/post", headers=auth)
        filters = {"warehouse_id": 1, "material_id": material}
        result = client.post(f"{base}/inventory-ledger/query", headers=auth, json=filters).json()
        assert [row["balance_quantity"] for row in result["rows"]] == ["5", "3"]
        assert result["groups"][0]["opening_quantity"] == "0"
        assert result["groups"][0]["closing_quantity"] == "3"
        assert client.post(f"{base}/inventory-ledger/query", headers=auth, json={
            **filters, "from_date": "2999-01-01"}).json()["groups"][0]["opening_quantity"] == "3"
        only_out = client.post(f"{base}/inventory-ledger/query", headers=auth, json={
            **filters, "source_type": "other_outbound"}).json()
        assert only_out["rows"][0]["balance_quantity"] == "-2"
        assert client.post(f"{base}/inventory-ledger/query", headers=auth, json={
            **filters, "from_date": "2026-09-30", "to_date": "2026-09-29"}).status_code == 422
