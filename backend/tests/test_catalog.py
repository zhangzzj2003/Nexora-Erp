"""基础资料维护、供货多对多关系和历史引用保护。"""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import connection, migrate


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "catalog.db"))
    with TestClient(app, client=("127.0.0.1", 12000)) as client:
        client.post("/api/v1/setup/admin", json={"username": "admin", "password": "secure-pass-123"})
        token = client.post("/api/v1/auth/login", json={"username": "admin", "password": "secure-pass-123"}).json()["token"]
        client.headers["Authorization"] = f"Bearer {token}"
        yield client


def create(client, resource, payload):
    result = client.post(f"/api/v1/{resource}", json=payload)
    assert result.status_code == 201, result.text
    return result.json()["id"]


@pytest.mark.parametrize("resource,original,updated", [
    ("materials", {"sku": "R-1", "name": "电阻 10k", "unit": "件"}, {"sku": "R-1", "name": "电阻 20k", "unit": "个"}),
    ("suppliers", {"name": "甲厂"}, {"name": "乙厂"}),
    ("warehouses", {"code": "EAST", "name": "东仓"}, {"code": "WEST", "name": "西仓"}),
])
def test_crud_validation_and_conflicts(client, resource, original, updated):
    record = create(client, resource, original)
    path = f"/api/v1/{resource}/{record}"
    assert client.post(f"/api/v1/{resource}", json=original).status_code == 409
    assert client.put(path, json={**updated, "name": "   "}).status_code == 422
    if resource == 'materials':
        response = client.put(path, json={**updated, 'version': 1})
        assert response.status_code == 200, response.text
        expected = response.json()
        assert expected['version'] == 2
        assert all(expected[key] == value for key, value in updated.items())
        # 编码固定，不能靠更名或改类覆盖另一个物料档案。
        other = create(client, resource, {**original, 'sku': 'OTHER'})
        assert client.put(f"/api/v1/{resource}/{other}", json={**updated, 'version': 1}).status_code == 409
    else:
        assert client.put(path, json=updated).status_code == 409
        expected = {"id": record, **updated, "version": 2}
        assert client.put(path, json={**updated, "version": 1, "reason": "修正基础资料"}).json() == expected
        other = create(client, resource, original)
        assert client.put(f"/api/v1/{resource}/{other}",
                          json={**updated, "version": 1, "reason": "重复资料"}).status_code == 409
    assert expected in client.get(f"/api/v1/{resource}").json()
    delete_path = path if resource == 'materials' else f'{path}?version=2'
    assert client.delete(delete_path).status_code == 204
    assert client.delete(delete_path).status_code == 404
    assert client.put(path, json=updated).status_code == 404


def test_many_to_many_and_unbind(client):
    suppliers = [create(client, "suppliers", {"name": name}) for name in ["甲厂", "乙厂"]]
    materials = [create(client, "materials", {"sku": sku, "name": sku, "unit": "件"}) for sku in ["R-10K", "C-100N"]]
    for supplier in suppliers:
        for material in materials:
            path = f"/api/v1/suppliers/{supplier}/materials/{material}"
            assert client.put(path).status_code == 204
            assert client.put(path).status_code == 204
    assert len(client.get("/api/v1/supplier-materials").json()) == 4
    assert client.put(f"/api/v1/suppliers/9999/materials/{materials[0]}").status_code == 404
    assert client.put(f"/api/v1/suppliers/{suppliers[0]}/materials/9999").status_code == 404
    assert client.delete(f"/api/v1/suppliers/{suppliers[0]}/materials/{materials[0]}").status_code == 204
    assert len(client.get("/api/v1/supplier-materials").json()) == 3
    assert len(client.get("/api/v1/materials").json()) == 2
    assert client.delete(f"/api/v1/suppliers/{suppliers[0]}?version=1").status_code == 204
    assert len(client.get("/api/v1/supplier-materials").json()) == 2
    assert client.delete(f"/api/v1/materials/{materials[0]}").status_code == 204
    assert client.get("/api/v1/supplier-materials").json() == [{"supplier_id": suppliers[1], "material_id": materials[1]}]


def test_referenced_records_cannot_be_deleted_and_links_survive_rollback(client):
    supplier = create(client, "suppliers", {"name": "甲厂"})
    material = create(client, "materials", {"sku": "R", "name": "电阻", "unit": "件"})
    warehouse = create(client, "warehouses", {"code": "EAST", "name": "东仓"})
    client.put(f"/api/v1/suppliers/{supplier}/materials/{material}")
    create(client, "receipts", {"supplier_id": supplier, "warehouse_id": warehouse, "lines": [{"material_id": material, "quantity": "1"}]})
    for resource, record in [("materials", material), ("suppliers", supplier), ("warehouses", warehouse), ("warehouses", 1)]:
        suffix = '' if resource == 'materials' else '?version=1'
        assert client.delete(f"/api/v1/{resource}/{record}{suffix}").status_code == 409
    assert client.get("/api/v1/supplier-materials").json() == [{"supplier_id": supplier, "material_id": material}]


def test_viewer_cannot_modify_catalog(client):
    create(client, "users", {"username": "viewer", "password": "secure-pass-123", "roles": ["viewer"]})
    token = client.post("/api/v1/auth/login", json={"username": "viewer", "password": "secure-pass-123"}).json()["token"]
    client.headers["Authorization"] = f"Bearer {token}"
    for resource, payload in [("materials", {"sku": "R", "name": "R", "unit": "件"}), ("suppliers", {"name": "甲"}), ("warehouses", {"code": "E", "name": "东"})]:
        assert client.get(f"/api/v1/{resource}").status_code == 200
        assert client.post(f"/api/v1/{resource}", json=payload).status_code == 403
        assert client.put(f"/api/v1/{resource}/1", json=payload).status_code == 403
        assert client.delete(f"/api/v1/{resource}/1").status_code == 403
    assert client.get("/api/v1/supplier-materials").status_code == 200
    assert client.put("/api/v1/suppliers/1/materials/1").status_code == 403
    assert client.delete("/api/v1/suppliers/1/materials/1").status_code == 403


def test_v27_migration_preserves_existing_materials(client, remove_v39_schema):
    material = create(client, "materials", {"sku": "OLD", "name": "旧物料", "unit": "件"})
    with connection() as db:
        db.execute("DROP TABLE inventory_cost_inputs")
        db.execute("DELETE FROM role_permissions WHERE permission_code LIKE 'inventory_valuation.%'")
        db.execute("DELETE FROM permissions WHERE code LIKE 'inventory_valuation.%'")
        db.execute("DELETE FROM permission_groups WHERE code = 'finance.inventory_valuation'")
        db.execute("DELETE FROM role_permissions WHERE permission_code = 'purchase_return.submit'")
        db.execute("DELETE FROM permissions WHERE code = 'purchase_return.submit'")
        db.execute("DELETE FROM role_permissions WHERE permission_code IN ('purchase_report.view', 'inventory_report.view')")
        db.execute("DELETE FROM permissions WHERE code IN ('purchase_report.view', 'inventory_report.view')")
        db.execute("DELETE FROM permission_groups WHERE code IN ('purchase.reports', 'warehouse.reports')")
        db.execute("DROP TABLE stock_adjustment_reversals")
        db.execute("DROP TABLE stock_adjustment_lines")
        db.execute("DROP TABLE stock_adjustments")
        db.execute("DELETE FROM role_permissions WHERE permission_code LIKE 'adjustment.%'")
        db.execute("DELETE FROM permissions WHERE code LIKE 'adjustment.%'")
        db.execute("DELETE FROM permission_groups WHERE code = 'warehouse.adjustment'")
        db.execute("DROP TABLE warehouse_outbound_reversals")
        db.execute("DROP TABLE warehouse_outbound_lines")
        db.execute("DROP TABLE warehouse_outbounds")
        db.execute("DELETE FROM role_permissions WHERE permission_code LIKE 'other_outbound.%'")
        db.execute("DELETE FROM permissions WHERE code LIKE 'other_outbound.%'")
        db.execute("DELETE FROM permission_groups WHERE code = 'warehouse.other_outbound'")
        db.execute("DROP TABLE warehouse_inbound_reversals")
        db.execute("DROP TABLE warehouse_inbound_lines")
        db.execute("DROP TABLE warehouse_inbounds")
        db.execute("DELETE FROM role_permissions WHERE permission_code LIKE 'other_inbound.%'")
        db.execute("DELETE FROM permissions WHERE code LIKE 'other_inbound.%'")
        db.execute("DELETE FROM permission_groups WHERE code = 'warehouse.other_inbound'")
        db.execute("DROP TABLE purchase_goods_receipt_lines")
        db.execute("DROP TABLE purchase_goods_receipts")
        db.execute("DELETE FROM role_permissions WHERE permission_code LIKE 'purchase_receiving.%'")
        db.execute("DELETE FROM permissions WHERE code LIKE 'purchase_receiving.%'")
        db.execute("DELETE FROM permission_groups WHERE code = 'purchase.receiving'")
        # 模拟旧库时同步移除第 29 版采购申请结构。
        db.execute("DROP TABLE purchase_order_request_links")
        db.execute("DROP TABLE purchase_request_lines")
        db.execute("DROP TABLE purchase_requests")
        db.execute("DELETE FROM role_permissions WHERE permission_code LIKE 'purchase_request.%'")
        db.execute("DELETE FROM permissions WHERE code LIKE 'purchase_request.%'")
        db.execute("DELETE FROM permission_groups WHERE code = 'purchase.purchase_request'")
        db.execute("DROP TABLE supplier_materials")
        # 回退版本夹具同步移除新版菜单表，模拟真实旧库。
        db.execute("DROP TABLE menu_icon_changes")
        db.execute("DROP TABLE menu_icons")
        remove_v39_schema(db)
        db.execute("PRAGMA user_version = 27")
    migrate()
    migrate()
    with connection() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 83
        assert db.execute("SELECT name FROM materials WHERE id = ?", (material,)).fetchone()[0] == "旧物料"
        assert db.execute("SELECT COUNT(*) FROM supplier_materials").fetchone()[0] == 0


def test_supplier_pagination_search_and_deleted_last_page(client):
    # 真实接口覆盖稳定分页、字面量搜索、空集和删除后的页码纠正。
    ids = [create(client, "suppliers", {"name": f"供应商 {index:02}"}) for index in range(23)]
    endpoint = "/api/v1/suppliers/query"
    first = client.post(endpoint, json={"page": 1, "page_size": 10}).json()
    second = client.post(endpoint, json={"page": 2, "page_size": 10}).json()
    assert first["total"] == 23
    assert len(first["items"]) == len(second["items"]) == 10
    assert {item["id"] for item in first["items"]}.isdisjoint(item["id"] for item in second["items"])
    filtered = client.post(endpoint, json={"query": " 供应商 2 ", "page_size": 10}).json()
    assert filtered["total"] == 3
    assert [item["id"] for item in filtered["items"]] == ids[20:]
    for record in ids[20:]:
        assert client.delete(f"/api/v1/suppliers/{record}?version=1").status_code == 204
    last = client.post(endpoint, json={"page": 3, "page_size": 10}).json()
    assert (last["page"], last["total"], len(last["items"])) == (2, 20, 10)
    create(client, "suppliers", {"name": "A%_Company"})
    literal = client.post(endpoint, json={"query": "%_company"}).json()
    assert literal["total"] == 1
    empty = client.post(endpoint, json={"query": "没有匹配", "page": 9}).json()
    assert empty == {"items": [], "total": 0, "page": 1, "page_size": 20}
    # 原选项接口保持数组结构，避免采购等表单只拿到第一页。
    assert len(client.get('/api/v1/suppliers').json()) == 21


@pytest.mark.parametrize("payload", [{"page": 0}, {"page": -1}, {"page_size": 0},
                                     {"page_size": 101}, {"query": "字" * 121}])
def test_supplier_pagination_rejects_invalid_bounds(client, payload):
    assert client.post('/api/v1/suppliers/query', json=payload).status_code == 422


def test_supplier_pagination_requires_permission(client):
    create(client, "users", {"username": "finance", "password": "secure-pass-123", "roles": ["finance"]})
    token = client.post('/api/v1/auth/login', json={"username": "finance", "password": "secure-pass-123"}).json()['token']
    client.headers['Authorization'] = f'Bearer {token}'
    assert client.post('/api/v1/suppliers/query', json={}).status_code == 403
    client.headers.pop('Authorization')
    assert client.post('/api/v1/suppliers/query', json={}).status_code == 401
