"""验证盘点差异只经确认单据入账，并拒绝过时快照和越权操作。"""

from approval_test_helpers import approve_document

from fastapi.testclient import TestClient

from app.main import app


def test_stocktake_adjustment_stale_count_and_permissions(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "stocktake.db"))
    with TestClient(app, client=("127.0.0.1", 12000)) as client:
        base = "/api/v1"
        client.post(f"{base}/setup/admin", json={"username": "admin", "password": "secure-pass-123"})
        token = client.post(f"{base}/auth/login", json={
            "username": "admin", "password": "secure-pass-123"}).json()["token"]
        admin = {"Authorization": f"Bearer {token}"}
        client.post(f"{base}/users", headers=admin, json={
            "username": "viewer", "password": "secure-pass-123", "roles": ["viewer"]})
        viewer_token = client.post(f"{base}/auth/login", json={
            "username": "viewer", "password": "secure-pass-123"}).json()["token"]
        view = {"Authorization": f"Bearer {viewer_token}"}
        supplier = client.post(f"{base}/suppliers", headers=admin, json={"name": "供应商"}).json()["id"]
        material = client.post(f"{base}/materials", headers=admin, json={
            "sku": "COUNT", "name": "盘点物料", "unit": "件"}).json()["id"]
        receipt = client.post(f"{base}/receipts", headers=admin, json={
            "supplier_id": supplier, "lines": [{"material_id": material, "quantity": "3.125"}]}).json()["id"]
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, admin, 'Receipt', receipt)
        client.post(f"{base}/receipts/{receipt}/post", headers=admin)
        warehouse = client.post(f"{base}/warehouses", headers=admin, json={
            "code": "SECOND", "name": "第二仓"}).json()["id"]

        # 盘点仅调整目标仓；草稿保留建单时的账面量与实盘量。
        payload = {"warehouse_id": 1, "reference": "月末盘点",
                   "lines": [{"material_id": material, "counted_quantity": "2.125"}]}
        assert client.post(f"{base}/stocktakes", headers=view, json=payload).status_code == 403
        assert client.post(f"{base}/stocktakes", headers=admin, json={
            **payload, "lines": payload["lines"] * 2}).status_code == 422
        assert client.post(f"{base}/stocktakes", headers=admin, json={
            **payload, "lines": [{"material_id": material, "counted_quantity": "1.0001"}]}).status_code == 422
        draft = client.post(f"{base}/stocktakes", headers=admin, json=payload)
        assert draft.status_code == 201
        stocktake_id = draft.json()["id"]
        assert draft.json()["lines"][0]["book_quantity"] == "3.125"
        assert draft.json()["lines"][0]["difference"] == "-1.000"
        approve_document(client, admin, 'Stocktake', stocktake_id)
        assert client.post(f"{base}/stocktakes/{stocktake_id}/post", headers=view).status_code == 403
        assert client.post(f"{base}/stocktakes/{stocktake_id}/post", headers=admin).status_code == 200
        assert client.post(f"{base}/stocktakes/{stocktake_id}/post", headers=admin).status_code == 409
        assert client.post(f"{base}/stocktakes/{stocktake_id}/cancel", headers=admin).status_code == 409
        assert client.get(f"{base}/stock?warehouse_id=1", headers=view).json()[0]["quantity"] == "2.125"
        movements = client.get(f"{base}/movements", headers=view).json()
        assert movements[0]["source_type"] == "stocktake"
        assert movements[0]["stocktake_id"] == stocktake_id
        assert movements[0]["quantity"] == "-1.000"
        assert movements[0]["created_by"] is not None

        # 草稿之后的调拨会改变账面量；旧盘点不得吞掉调拨流水。
        stale = client.post(f"{base}/stocktakes", headers=admin, json=payload).json()["id"]
        transfer = client.post(f"{base}/transfers", headers=admin, json={
            "from_warehouse_id": 1, "to_warehouse_id": warehouse,
            "lines": [{"material_id": material, "quantity": "0.125"}]}).json()["id"]
        approve_document(client, admin, 'Transfer', transfer)
        assert client.post(f"{base}/transfers/{transfer}/post", headers=admin).status_code == 200
        approve_document(client, admin, 'Stocktake', stale)
        assert client.post(f"{base}/stocktakes/{stale}/post", headers=admin).status_code == 409
        state = client.get(f'{base}/system/document-approvals/Stocktake/{stale}', headers=admin).json()
        assert client.post(f'{base}/system/document-approvals/Stocktake/{stale}/withdraw', headers=admin,
                           json={'version': state['version']}).status_code == 200
        assert client.post(f"{base}/stocktakes/{stale}/cancel", headers=admin).status_code == 200
        assert client.get(f"{base}/stock?warehouse_id=1", headers=view).json()[0]["quantity"] == "2.000"
        assert client.get(f"{base}/stock?warehouse_id={warehouse}", headers=view).json()[0]["quantity"] == "0.125"
        assert client.get(f"{base}/stocktakes", headers=view).json()[0]["status"] == "cancelled"

        # 无差异盘点可确认，但不制造一笔零数量流水。
        before = len(client.get(f"{base}/movements", headers=view).json())
        zero = client.post(f"{base}/stocktakes", headers=admin, json={
            "warehouse_id": warehouse, "lines": [{"material_id": material,
                                                     "counted_quantity": "0.125"}]}).json()["id"]
        approve_document(client, admin, 'Stocktake', zero)
        assert client.post(f"{base}/stocktakes/{zero}/post", headers=admin).status_code == 200
        assert len(client.get(f"{base}/movements", headers=view).json()) == before

        # 出入相抵后余额虽未变，旧实盘仍不应覆盖期间发生的交易。
        unchanged_balance = client.post(f"{base}/stocktakes", headers=admin, json={
            "warehouse_id": 1, "lines": [{"material_id": material,
                                            "counted_quantity": "2.000"}]}).json()["id"]
        for source, target in ((1, warehouse), (warehouse, 1)):
            move = client.post(f"{base}/transfers", headers=admin, json={
                "from_warehouse_id": source, "to_warehouse_id": target,
                "lines": [{"material_id": material, "quantity": "0.125"}]}).json()["id"]
            approve_document(client, admin, 'Transfer', move)
            assert client.post(f"{base}/transfers/{move}/post", headers=admin).status_code == 200
        assert client.get(f"{base}/stock?warehouse_id=1", headers=view).json()[0]["quantity"] == "2.000"
        approve_document(client, admin, 'Stocktake', unchanged_balance)
        assert client.post(f"{base}/stocktakes/{unchanged_balance}/post", headers=admin).status_code == 409


def test_posted_stocktake_reversal_keeps_history_and_checks_current_stock(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "reversal.db"))
    with TestClient(app, client=("127.0.0.1", 12000)) as client:
        base = "/api/v1"
        client.post(f"{base}/setup/admin", json={"username": "admin", "password": "secure-pass-123"})
        token = client.post(f"{base}/auth/login", json={
            "username": "admin", "password": "secure-pass-123"}).json()["token"]
        admin = {"Authorization": f"Bearer {token}"}
        client.post(f"{base}/users", headers=admin, json={
            "username": "viewer", "password": "secure-pass-123", "roles": ["viewer"]})
        view_token = client.post(f"{base}/auth/login", json={
            "username": "viewer", "password": "secure-pass-123"}).json()["token"]
        view = {"Authorization": f"Bearer {view_token}"}
        supplier = client.post(f"{base}/suppliers", headers=admin, json={"name": "供应商"}).json()["id"]
        material = client.post(f"{base}/materials", headers=admin, json={
            "sku": "REV", "name": "冲销物料", "unit": "件"}).json()["id"]
        receipt = client.post(f"{base}/receipts", headers=admin, json={
            "supplier_id": supplier, "lines": [{"material_id": material, "quantity": "2.000"}]}).json()["id"]
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, admin, 'Receipt', receipt)
        assert client.post(f"{base}/receipts/{receipt}/post", headers=admin).status_code == 200
        second = client.post(f"{base}/warehouses", headers=admin, json={
            "code": "REV2", "name": "冲销测试仓"}).json()["id"]
        stocktake = client.post(f"{base}/stocktakes", headers=admin, json={
            "warehouse_id": 1, "lines": [{"material_id": material,
                                          "counted_quantity": "3.000"}]}).json()["id"]
        approve_document(client, admin, 'Stocktake', stocktake)
        assert client.post(f"{base}/stocktakes/{stocktake}/post", headers=admin).status_code == 200
        transfer = client.post(f"{base}/transfers", headers=admin, json={
            "from_warehouse_id": 1, "to_warehouse_id": second,
            "lines": [{"material_id": material, "quantity": "2.500"}]}).json()["id"]
        approve_document(client, admin, 'Transfer', transfer)
        assert client.post(f"{base}/transfers/{transfer}/post", headers=admin).status_code == 200

        path = f"{base}/stocktakes/{stocktake}/reverse"
        assert client.post(path, headers=view, json={"reason": "录错实盘"}).status_code == 403
        assert client.post(path, headers=admin, json={"reason": "  "}).status_code == 422
        approve_document(client, admin, 'Stocktake', stocktake, intent='reverse', reason='录错实盘')
        assert client.post(path, headers=admin, json={"reason": "录错实盘"}).status_code == 409
        assert client.get(f"{base}/stock?warehouse_id=1", headers=admin).json()[0]["quantity"] == "0.500"

        # 把可用库存调回后才能冲销盘盈；失败请求不留下冲销单或部分流水。
        back = client.post(f"{base}/transfers", headers=admin, json={
            "from_warehouse_id": second, "to_warehouse_id": 1,
            "lines": [{"material_id": material, "quantity": "0.500"}]}).json()["id"]
        approve_document(client, admin, 'Transfer', back)
        assert client.post(f"{base}/transfers/{back}/post", headers=admin).status_code == 200
        reversed_record = client.post(path, headers=admin, json={"reason": "录错实盘"})
        assert reversed_record.status_code == 200
        assert reversed_record.json()["status"] == "posted"
        assert reversed_record.json()["reversal_reason"] == "录错实盘"
        assert reversed_record.json()["reversed_by_name"] == "admin"
        assert client.post(path, headers=admin, json={"reason": "再次冲销"}).status_code == 409
        assert client.get(f"{base}/stock?warehouse_id=1", headers=admin).json()[0]["quantity"] == "0.000"
        movements = client.get(f"{base}/movements", headers=view).json()
        reversal = next(item for item in movements if item["source_type"] == "stocktake_reversal")
        original = next(item for item in movements if item["source_type"] == "stocktake")
        assert reversal["stocktake_reversal_id"] == reversed_record.json()["reversal_id"]
        assert reversal["source_line_id"] == original["source_line_id"]
        assert reversal["quantity"] == "-1.000"
        assert original["quantity"] == "1.000"

        # 盘亏冲销只追加回补流水；零差异盘点冲销仍需留原因但不制造流水。
        loss = client.post(f"{base}/stocktakes", headers=admin, json={
            "warehouse_id": second, "lines": [{"material_id": material,
                                               "counted_quantity": "1.000"}]}).json()["id"]
        approve_document(client, admin, 'Stocktake', loss)
        assert client.post(f"{base}/stocktakes/{loss}/post", headers=admin).status_code == 200
        approve_document(client, admin, 'Stocktake', loss, intent='reverse', reason='复核后实物无短缺')
        assert client.post(f"{base}/stocktakes/{loss}/reverse", headers=admin,
                           json={"reason": "复核后实物无短缺"}).status_code == 200
        zero = client.post(f"{base}/stocktakes", headers=admin, json={
            "warehouse_id": second, "lines": [{"material_id": material,
                                               "counted_quantity": "2.000"}]}).json()["id"]
        approve_document(client, admin, 'Stocktake', zero)
        assert client.post(f"{base}/stocktakes/{zero}/post", headers=admin).status_code == 200
        count_before = len(client.get(f"{base}/movements", headers=admin).json())
        approve_document(client, admin, 'Stocktake', zero, intent='reverse', reason='批次编号写错')
        assert client.post(f"{base}/stocktakes/{zero}/reverse", headers=admin,
                           json={"reason": "批次编号写错"}).status_code == 200
        assert len(client.get(f"{base}/movements", headers=admin).json()) == count_before
