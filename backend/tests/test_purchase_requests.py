"""采购申请审批、分批转单与并发额度保护。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi.testclient import TestClient

from app.main import app


def setup(client):
    base = "/api/v1"
    assert client.post(f"{base}/setup/admin", json={
        "username": "admin", "password": "secure-pass-123"}).status_code == 201
    token = client.post(f"{base}/auth/login", json={
        "username": "admin", "password": "secure-pass-123"}).json()["token"]
    admin = {"Authorization": f"Bearer {token}"}
    supplier = client.post(f"{base}/suppliers", headers=admin, json={"name": "供应商甲"}).json()["id"]
    material = client.post(f"{base}/materials", headers=admin, json={
        "sku": "REQ-A", "name": "申请物料", "unit": "件"}).json()["id"]
    return base, admin, supplier, material


def test_request_approval_split_conversion_and_release(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "requests.db"))
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        base, admin, supplier, material = setup(client)
        payload = {"reference": "需求-01", "note": "本月采购", "lines": [
            {"material_id": material, "quantity": "10"}]}
        viewer = client.post(f"{base}/users", headers=admin, json={
            "username": "viewer", "password": "secure-pass-123", "roles": ["viewer"]})
        assert viewer.status_code == 201
        viewer_token = client.post(f"{base}/auth/login", json={
            "username": "viewer", "password": "secure-pass-123"}).json()["token"]
        view = {"Authorization": f"Bearer {viewer_token}"}
        assert client.post(f"{base}/purchase-requests", headers=view, json=payload).status_code == 403

        created = client.post(f"{base}/purchase-requests", headers=admin, json=payload)
        assert created.status_code == 201
        request_id = created.json()["id"]
        line_id = created.json()["lines"][0]["id"]
        order = {"supplier_id": supplier, "purchase_request_id": request_id,
                 "lines": [{"material_id": material, "purchase_request_line_id": line_id,
                            "quantity": "6", "unit_price": "2"}]}
        assert client.post(f"{base}/purchase-orders", headers=admin, json=order).status_code == 409
        assert client.post(f"{base}/purchase-requests/{request_id}/submit", headers=admin).status_code == 200
        assert client.post(f"{base}/purchase-requests/{request_id}/approve", headers=view).status_code == 403
        assert client.post(f"{base}/purchase-requests/{request_id}/approve", headers=admin).status_code == 200
        assert client.post(f"{base}/purchase-requests/{request_id}/approve", headers=admin).status_code == 409

        first = client.post(f"{base}/purchase-orders", headers=admin, json=order)
        assert first.status_code == 201
        assert first.json()["purchase_request_id"] == request_id
        assert first.json()["lines"][0]["purchase_request_line_id"] == line_id
        assert client.post(f"{base}/purchase-orders", headers=admin, json=order).status_code == 409
        remaining = client.get(f"{base}/purchase-requests", headers=admin).json()[0]["lines"][0]
        assert remaining["ordered_quantity"] == "6"
        assert remaining["remaining_quantity"] == "4"
        assert client.post(f"{base}/purchase-requests/{request_id}/cancel", headers=admin).status_code == 409

        second = client.post(f"{base}/purchase-orders", headers=admin, json={
            **order, "lines": [{**order["lines"][0], "quantity": "4"}]})
        assert second.status_code == 201
        assert client.get(f"{base}/purchase-requests", headers=admin).json()[0]["lines"][0]["remaining_quantity"] == "0"
        assert client.post(f"{base}/purchase-orders/{first.json()['id']}/cancel", headers=admin).status_code == 200
        assert client.get(f"{base}/purchase-requests", headers=admin).json()[0]["lines"][0]["remaining_quantity"] == "6"
        # 无申请来源的直接采购继续可用。
        assert client.post(f"{base}/purchase-orders", headers=admin, json={
            "supplier_id": supplier, "lines": [{"material_id": material,
                                                  "quantity": "1", "unit_price": "2"}]}).status_code == 201


def test_rejected_request_can_be_revised_and_invalid_links_fail(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "rejected.db"))
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        base, admin, supplier, material = setup(client)
        payload = {"lines": [{"material_id": material, "quantity": "3"}]}
        assert client.post(f"{base}/purchase-requests", headers=admin,
                           json={"lines": payload["lines"] * 2}).status_code == 422
        request = client.post(f"{base}/purchase-requests", headers=admin, json=payload).json()
        request_id = request["id"]
        assert client.post(f"{base}/purchase-requests/{request_id}/submit", headers=admin).status_code == 200
        assert client.post(f"{base}/purchase-requests/{request_id}/reject", headers=admin,
                           json={"reason": " "}).status_code == 422
        assert client.post(f"{base}/purchase-requests/{request_id}/reject", headers=admin,
                           json={"reason": "数量不符"}).status_code == 200
        revised = client.put(f"{base}/purchase-requests/{request_id}", headers=admin, json={
            "version": client.get(f"{base}/purchase-requests", headers=admin).json()[0]["version"],
            "lines": [{"material_id": material, "quantity": "5"}]}).json()
        assert revised["status"] == "draft"
        assert revised["review_reason"] == ""
        assert client.post(f"{base}/purchase-requests/{request_id}/submit", headers=admin).status_code == 200
        assert client.post(f"{base}/purchase-requests/{request_id}/approve", headers=admin).status_code == 200
        invalid = {"supplier_id": supplier, "purchase_request_id": request_id,
                   "lines": [{"material_id": material, "purchase_request_line_id": 999,
                              "quantity": "1", "unit_price": "2"}]}
        assert client.post(f"{base}/purchase-orders", headers=admin, json=invalid).status_code == 422


def test_two_clients_cannot_convert_same_request_quantity(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "concurrent.db"))
    with (TestClient(app, client=("127.0.0.1", 12345)) as first,
          TestClient(app, client=("127.0.0.1", 12346)) as second):
        base, admin, supplier, material = setup(first)
        request = first.post(f"{base}/purchase-requests", headers=admin, json={
            "lines": [{"material_id": material, "quantity": "10"}]}).json()
        first.post(f"{base}/purchase-requests/{request['id']}/submit", headers=admin)
        first.post(f"{base}/purchase-requests/{request['id']}/approve", headers=admin)
        payload = {"supplier_id": supplier, "purchase_request_id": request["id"],
                   "lines": [{"material_id": material,
                              "purchase_request_line_id": request["lines"][0]["id"],
                              "quantity": "6", "unit_price": "1"}]}
        barrier = Barrier(2)

        def convert(client):
            barrier.wait(timeout=5)
            return client.post(f"{base}/purchase-orders", headers=admin, json=payload).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(convert, (first, second)))
        assert sorted(outcomes) == [201, 409]
