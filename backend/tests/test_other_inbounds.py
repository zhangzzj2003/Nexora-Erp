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


def test_cancelled_inbound_copy_creates_new_identity(monkeypatch, tmp_path):
    """重开使用普通新建接口；新单独立审批，原单取消记录与库存保持不变。"""
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "reopen-inbound.db"))
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        base = "/api/v1"
        assert client.post(f"{base}/setup/admin", json={
            "username": "admin", "password": "secure-pass-123"}).status_code == 201
        token = client.post(f"{base}/auth/login", json={
            "username": "admin", "password": "secure-pass-123"}).json()["token"]
        auth = {"Authorization": f"Bearer {token}"}
        material = client.post(f"{base}/materials", headers=auth, json={
            "sku": "REOPEN", "name": "重开物料", "unit": "件"}).json()["id"]
        payload = {"warehouse_id": 1, "reason": "gift", "note": "误取消后重开",
                   "reference": "COPY", "lines": [{"material_id": material, "quantity": "2.125"}]}
        source = client.post(f"{base}/warehouse-inbounds", headers=auth, json=payload).json()
        cancelled = client.post(f'{base}/warehouse-inbounds/{source["id"]}/cancel', headers=auth)
        assert cancelled.status_code == 200
        original = cancelled.json()
        created = client.post(f"{base}/warehouse-inbounds", headers=auth, json=payload)
        assert created.status_code == 201
        reopened = created.json()
        assert reopened["id"] != original["id"]
        assert reopened["document_no"] and reopened["document_no"] != original["document_no"]
        assert reopened["lines"][0]["id"] != original["lines"][0]["id"]
        assert reopened["status"] == "draft"
        for key in ("approval", "reversal_approval"):
            assert reopened[key]["status"] == "draft" and reopened[key]["version"] == 0
            assert reopened[key]["submitted_at"] is None and reopened[key]["steps"] == []
        assert reopened["cancelled_at"] is None and reopened["posted_at"] is None
        assert reopened["lines"][0]["physical_lots"] == []
        # 新单不能借用原单状态直接入库，必须完成自己的审批。
        assert client.post(f'{base}/warehouse-inbounds/{reopened["id"]}/post', headers=auth).status_code == 409
        records = client.get(f"{base}/warehouse-inbounds", headers=auth).json()
        assert next(item for item in records if item["id"] == original["id"]) == original
        assert client.get(f"{base}/stock", headers=auth).json()[0]["quantity"] == "0"
