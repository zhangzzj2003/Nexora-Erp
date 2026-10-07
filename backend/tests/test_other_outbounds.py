"""其他出库确认、库存不足与冲销回归。"""

from approval_test_helpers import approve_document
from fastapi.testclient import TestClient

from app.main import app


def test_other_outbound_requires_stock_and_keeps_source(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "other-outbound.db"))
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        base = "/api/v1"
        assert client.post(f"{base}/setup/admin", json={
            "username": "admin", "password": "secure-pass-123"}).status_code == 201
        token = client.post(f"{base}/auth/login", json={
            "username": "admin", "password": "secure-pass-123"}).json()["token"]
        admin = {"Authorization": f"Bearer {token}"}
        material = client.post(f"{base}/materials", headers=admin, json={
            "sku": "SAMPLE", "name": "样品", "unit": "件"}).json()["id"]
        inbound = client.post(f"{base}/warehouse-inbounds", headers=admin, json={
            "warehouse_id": 1, "reason": "gift", "note": "入库测试",
            "lines": [{"material_id": material, "quantity": "2"}]}).json()["id"]
        approve_document(client, admin, 'WarehouseInbound', inbound)
        assert client.post(f"{base}/warehouse-inbounds/{inbound}/post", headers=admin).status_code == 200
        payload = {"warehouse_id": 1, "reason": "sample", "note": "寄送客户试用",
                   "lines": [{"material_id": material, "quantity": "3"}]}
        assert client.post(f"{base}/warehouse-outbounds", headers=admin, json={
            **payload, "lines": payload["lines"] * 2}).status_code == 422
        draft = client.post(f"{base}/warehouse-outbounds", headers=admin, json=payload)
        assert draft.status_code == 201
        outbound_id = draft.json()["id"]
        # 已批准仍须重核实际库存，失败不消费批准或写入流水。
        state = approve_document(client, admin, 'WarehouseOutbound', outbound_id)
        assert client.post(f"{base}/warehouse-outbounds/{outbound_id}/post", headers=admin).status_code == 409
        assert client.get(f"{base}/stock", headers=admin).json()[0]["quantity"] == "2"
        assert client.post(f"{base}/system/document-approvals/WarehouseOutbound/{outbound_id}/withdraw",
                           headers=admin, json={"version": state["version"]}).status_code == 200
        assert client.post(f"{base}/warehouse-outbounds/{outbound_id}/cancel", headers=admin).status_code == 200
        assert client.post(f"{base}/warehouse-outbounds/{outbound_id}/post", headers=admin).status_code == 409

        posted_id = client.post(f"{base}/warehouse-outbounds", headers=admin, json={
            **payload, "lines": [{"material_id": material, "quantity": "1"}]}).json()["id"]
        approve_document(client, admin, 'WarehouseOutbound', posted_id)
        assert client.post(f"{base}/warehouse-outbounds/{posted_id}/post", headers=admin).status_code == 200
        assert client.post(f"{base}/warehouse-outbounds/{posted_id}/post", headers=admin).status_code == 409
        assert client.get(f"{base}/stock", headers=admin).json()[0]["quantity"] == "1"
        movement = client.get(f"{base}/movements", headers=admin).json()[0]
        assert movement["source_type"] == "other_outbound"
        assert movement["other_outbound_id"] == posted_id
        assert client.get(f"{base}/finance/receivables-payables", headers=admin).json()["entries"] == []
        approve_document(client, admin, 'WarehouseOutbound', posted_id, intent='reverse', reason='样品未寄出')
        reversed_entry = client.post(f"{base}/warehouse-outbounds/{posted_id}/reverse", headers=admin,
                                     json={"reason": "样品未寄出"})
        assert reversed_entry.status_code == 201
        assert reversed_entry.json()["reversal_reason"] == "样品未寄出"
        assert client.post(f"{base}/warehouse-outbounds/{posted_id}/reverse", headers=admin,
                           json={"reason": "重复"}).status_code == 409
        assert client.get(f"{base}/stock", headers=admin).json()[0]["quantity"] == "2"
