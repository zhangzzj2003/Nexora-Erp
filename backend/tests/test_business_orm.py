"""ORM 单据迁移须保留写入后回滚、跨模块状态和并发确认约束。"""

from approval_test_helpers import approve_document, prepare_purchase_return

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, update, inspect
from sqlalchemy.orm import Session

from app.core.models import Base, StockMovement, Receipt, PurchaseOrderRequestLink
from app.core.orm import orm_session, engine_for
from app.core.database import database_path
from app.main import app


@pytest.fixture
def erp(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "business-orm.db"))
    with TestClient(app, client=("127.0.0.1", 12000), raise_server_exceptions=False) as client:
        base = "/api/v1/"

        def request(method, path, payload=None, status=200):
            response = client.request(method, base + path, json=payload)
            assert response.status_code == status, response.text
            return response.json() if status != 204 else None

        request("POST", "setup/admin", {"username": "admin", "password": "secure-pass-123"}, 201)
        token = request("POST", "auth/login", {"username": "admin", "password": "secure-pass-123"})["token"]
        client.headers["Authorization"] = "Bearer " + token
        supplier = request("POST", "suppliers", {"name": "事务供应商"}, 201)["id"]
        customer = request("POST", "customers", {"name": "事务客户"}, 201)["id"]
        materials = [
            request("POST", "materials", {"sku": f"ORM-{i}", "name": f"物料{i}", "unit": "件"}, 201)["id"]
            for i in range(3)
        ]
        warehouse = request("POST", "warehouses", {"code": "TARGET", "name": "目标仓"}, 201)["id"]
        purchase = request(
            "POST",
            "purchase-orders",
            {
                "supplier_id": supplier,
                "lines": [
                    {"material_id": m, "quantity": "10.000", "unit_price": "3.1250"} for m in materials[:2]
                ],
            },
            201,
        )
        # 先完成真实独立审批，保留原业务失败和并发断言。
        approve_document(client, dict(client.headers), 'PurchaseOrder', purchase['id'])
        request("POST", f'purchase-orders/{purchase["id"]}/confirm')
        yield client, request, supplier, customer, materials, warehouse, purchase


def receipt(erp, quantity="10.000"):
    client, request, supplier, _, materials, _, purchase = erp
    result = request(
        "POST",
        "receipts",
        {
            "supplier_id": supplier,
            "purchase_order_id": purchase["id"],
            "lines": [{"material_id": m, "quantity": quantity} for m in materials[:2]],
        },
        201,
    )
    # 显式业务夹具提供可执行入库单，不拦截或自动放宽任何被测接口。
    approve_document(client, dict(client.headers), 'Receipt', result['id'])
    return result


def completion(erp):
    client, request, _, _, materials, _, _ = erp
    bom = request(
        "POST",
        "boms",
        {
            "product_material_id": materials[2],
            "lines": [{"component_material_id": m, "quantity": "1.000"} for m in materials[:2]],
        },
        201,
    )
    request("POST", f'boms/{bom["id"]}/activate')
    order = request(
        "POST", "work-orders", {"bom_id": bom["id"], "warehouse_id": 1, "target_quantity": "2.000"}, 201
    )
    approve_document(client, dict(client.headers), 'WorkOrder', order['id'])
    request("POST", f'work-orders/{order["id"]}/release')
    issue = request(
        "POST",
        "material-issues",
        {
            "work_order_id": order["id"],
            "warehouse_id": 1,
            "lines": [{"work_order_line_id": line["id"], "quantity": "2.000"} for line in order["lines"]],
        },
        201,
    )
    approve_document(client, dict(client.headers), 'MaterialIssue', issue['id'])
    request("POST", f'material-issues/{issue["id"]}/post')
    row = request(
        "POST", "production-completions", {"work_order_id": order["id"], "reported_quantity": "2.000"}, 201
    )
    request(
        "POST",
        f'production-completions/{row["id"]}/inspect',
        {"accepted_quantity": "2.000", "qc_note": "全数合格"},
    )
    return row


def snapshots(request):
    return {
        path: request("GET", path)
        for path in (
            "stock",
            "movements",
            "purchase-orders",
            "receipts",
            "transfers",
            "purchase-returns",
            "warehouse-outbounds",
            "sales-orders",
            "shipments",
            "work-orders",
            "material-issues",
            "production-completions",
            "finance/overview",
        )
    }


def fail_after_model_flush(model):
    # 在数据库已经收到写入后模拟故障，不能只验证写入前的业务拒绝。
    def before_flush(session, *_):
        if any(isinstance(item, model) for item in session.new):
            session.info["fail_after_business_flush"] = True

    def after_flush(session, *_):
        if session.info.pop("fail_after_business_flush", False):
            raise RuntimeError("模拟业务写入后故障")

    return before_flush, after_flush


@pytest.mark.parametrize(
    "case",
    [
        "receipt_post",
        "transfer_post",
        "shipment_post",
        "purchase_return_post",
        "completion_post",
        "receipt_reverse",
        "transfer_reverse",
        "completion_reverse",
    ],
)
def test_stock_write_failure_rolls_back_document_and_related_modules(erp, case):
    client, request, _, customer, materials, warehouse, _ = erp
    source = receipt(erp)
    if case != "receipt_post":
        request("POST", f'receipts/{source["id"]}/post')
    payload = None
    if case.startswith("receipt"):
        path = f'receipts/{source["id"]}/' + ("reverse" if case.endswith("reverse") else "post")
    elif case.startswith("transfer"):
        source = request(
            "POST",
            "transfers",
            {
                "from_warehouse_id": 1,
                "to_warehouse_id": warehouse,
                "lines": [{"material_id": m, "quantity": "1.125"} for m in materials[:2]],
            },
            201,
        )
        approve_document(client, dict(client.headers), 'Transfer', source['id'])
        if case.endswith("reverse"):
            request("POST", f'transfers/{source["id"]}/post')
        path = f'transfers/{source["id"]}/' + ("reverse" if case.endswith("reverse") else "post")
    elif case == "purchase_return_post":
        source = request(
            "POST",
            "purchase-returns",
            {
                "receipt_id": source["id"],
                "reason": "退货",
                "lines": [{"receipt_line_id": line["id"], "quantity": "1.125"} for line in source["lines"]],
            },
            201,
        )
        prepare_purchase_return(client, dict(client.headers), source['id'])
        path = f'purchase-returns/{source["id"]}/post'
    elif case == "shipment_post":
        order = request(
            "POST",
            "sales-orders",
            {
                "customer_id": customer,
                "lines": [
                    {"material_id": m, "quantity": "10.000", "unit_price": "4.1250"} for m in materials[:2]
                ],
            },
            201,
        )
        approve_document(client, dict(client.headers), 'SalesOrder', order['id'])
        request("POST", f'sales-orders/{order["id"]}/confirm')
        source = request(
            "POST",
            "shipments",
            {
                "sales_order_id": order["id"],
                "warehouse_id": 1,
                "lines": [{"material_id": m, "quantity": "1.125"} for m in materials[:2]],
            },
            201,
        )
        approve_document(client, dict(client.headers), 'Shipment', source['id'])
        path = f'shipments/{source["id"]}/post'
    else:
        # 独立审批完成后，再验证原库存约束或失败回滚。
        source = completion(erp)
        approve_document(client, dict(client.headers), 'ProductionCompletion', source['id'])
        if case.endswith("reverse"):
            request("POST", f'production-completions/{source["id"]}/post')
        path = f'production-completions/{source["id"]}/' + ("reverse" if case.endswith("reverse") else "post")
    if case.endswith("reverse"):
        payload = {"reason": "更正原单"}
    # 先完成真实独立审批，保留原业务失败和并发断言。
    if case == 'transfer_reverse':
        approve_document(client, dict(client.headers), 'Transfer', source['id'], intent='reverse', reason='更正原单')
    if case == 'receipt_reverse':
        approve_document(client, dict(client.headers), 'Receipt', source['id'], intent='reverse', reason='更正原单')
    # 独立审批完成后，再验证原库存约束或失败回滚。
    if case == 'completion_reverse':
        approve_document(client, dict(client.headers), 'ProductionCompletion', source['id'], intent='reverse', reason='更正原单')
    before = snapshots(request)
    before_flush, after_flush = fail_after_model_flush(StockMovement)
    event.listen(Session, "before_flush", before_flush)
    event.listen(Session, "after_flush_postexec", after_flush)
    try:
        assert client.post("/api/v1/" + path, json=payload).status_code == 500
    finally:
        event.remove(Session, "before_flush", before_flush)
        event.remove(Session, "after_flush_postexec", after_flush)
    assert snapshots(request) == before
    request("POST", path, payload, 201 if case in ("receipt_reverse",) else 200)
    assert snapshots(request) != before


def test_goods_receipt_generated_inbound_failure_can_retry_without_reserving_twice(erp):
    client, request, _, _, _, _, purchase = erp
    source = request(
        "POST",
        "purchase-goods-receipts",
        {
            "purchase_order_id": purchase["id"],
            "warehouse_id": 1,
            "lines": [
                {"purchase_order_line_id": line["id"], "accepted_quantity": "6.000"}
                for line in purchase["lines"]
            ],
        },
        201,
    )
    # 先完成真实独立审批，保留原业务失败和并发断言。
    approve_document(client, dict(client.headers), 'PurchaseGoodsReceipt', source['id'])
    before_flush, after_flush = fail_after_model_flush(Receipt)
    event.listen(Session, "before_flush", before_flush)
    event.listen(Session, "after_flush_postexec", after_flush)
    try:
        assert client.post(f'/api/v1/purchase-goods-receipts/{source["id"]}/confirm').status_code == 500
    finally:
        event.remove(Session, "before_flush", before_flush)
        event.remove(Session, "after_flush_postexec", after_flush)
    assert request("GET", "receipts") == []
    assert request("GET", "purchase-goods-receipts")[0]["status"] == "draft"
    result = request("POST", f'purchase-goods-receipts/{source["id"]}/confirm')
    assert result["inbound_status"] == "draft" and len(request("GET", "receipts")) == 1
    # 先完成真实独立审批，保留原业务失败和并发断言。
    approve_document(client, dict(client.headers), 'Receipt', result['inbound_receipt_id'])
    request("POST", f'receipts/{result["inbound_receipt_id"]}/post')
    assert {line["remaining_quantity"] for line in request("GET", "purchase-orders")[0]["lines"]} == {"4.000"}


def test_request_quota_and_order_links_roll_back_after_insert(erp):
    client, request, supplier, _, materials, _, _ = erp
    source = request(
        "POST",
        "purchase-requests",
        {"lines": [{"material_id": m, "quantity": "1.125"} for m in materials[:2]]},
        201,
    )
    request("POST", f'purchase-requests/{source["id"]}/submit')
    request("POST", f'purchase-requests/{source["id"]}/approve')
    payload = {
        "supplier_id": supplier,
        "purchase_request_id": source["id"],
        "lines": [
            {
                "material_id": line["material_id"],
                "purchase_request_line_id": line["id"],
                "quantity": line["quantity"],
                "unit_price": "3.1250",
            }
            for line in source["lines"]
        ],
    }
    before = request("GET", "purchase-orders")
    before_flush, after_flush = fail_after_model_flush(PurchaseOrderRequestLink)
    event.listen(Session, "before_flush", before_flush)
    event.listen(Session, "after_flush_postexec", after_flush)
    try:
        assert client.post("/api/v1/purchase-orders", json=payload).status_code == 500
    finally:
        event.remove(Session, "before_flush", before_flush)
        event.remove(Session, "after_flush_postexec", after_flush)
    assert request("GET", "purchase-orders") == before
    assert {line["ordered_quantity"] for line in request("GET", "purchase-requests")[0]["lines"]} == {"0"}
    order = request("POST", "purchase-orders", payload, 201)
    assert order["purchase_request_id"] == source["id"]
    assert {line["remaining_quantity"] for line in request("GET", "purchase-requests")[0]["lines"]} == {
        "0.000"
    }


@pytest.mark.parametrize("kind", ["receipt", "transfer"])
def test_concurrent_confirmations_cannot_overconsume_order_or_stock(erp, kind):
    client, request, _, _, materials, warehouse, _ = erp
    if kind == "receipt":
        ids = [receipt(erp, "6.000")["id"] for _ in range(2)]
        paths = [f"/api/v1/receipts/{item}/post" for item in ids]
    else:
        source = receipt(erp)
        request("POST", f'receipts/{source["id"]}/post')
        ids = [
            request(
                "POST",
                "transfers",
                {
                    "from_warehouse_id": 1,
                    "to_warehouse_id": warehouse,
                    "lines": [{"material_id": m, "quantity": "6.000"} for m in materials[:2]],
                },
                201,
            )["id"]
            for _ in range(2)
        ]
        for item in ids:
            approve_document(client, dict(client.headers), 'Transfer', item)
        paths = [f"/api/v1/transfers/{item}/post" for item in ids]
    barrier = Barrier(2)

    def confirm(path):
        barrier.wait(timeout=5)
        return client.post(path).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(confirm, paths)) == [200, 409]
    movements = request("GET", "movements")
    assert len([row for row in movements if row["source_type"] == kind]) == (2 if kind == "receipt" else 0)
    if kind == "transfer":
        assert len([row for row in movements if row["source_type"].startswith("transfer_")]) == 4
        assert {row["quantity"] for row in request("GET", "stock") if row["id"] in materials[:2]} == {
            "10.000"
        }


def test_balance_report_uses_inclusive_date_boundary_and_exact_decimal_quantities(erp):
    _, request, _, _, materials, warehouse, _ = erp
    source = receipt(erp, '0.125')
    request('POST', f'receipts/{source["id"]}/post')
    with orm_session(write=True) as session:
        for material, timestamp in zip(materials[:2], ('2026-01-31 23:59:59', '2026-02-01 00:00:00')):
            session.execute(update(StockMovement).where(StockMovement.material_id == material)
                            .values(created_at=timestamp))
    report = request('POST', 'reports/query', {'kind': 'inventory_balance', 'warehouse_id': 1,
                                              'to_date': '2026-01-31'})
    assert [(row['material'], row['quantity']) for row in report['rows']] == [
        ('ORM-0 · 物料0', '0.125'), ('ORM-1 · 物料1', '0'), ('ORM-2 · 物料2', '0')]
    assert '0.125' in report['csv']
    later = request('POST', 'reports/query', {'kind': 'inventory_balance', 'warehouse_id': 1,
                                             'to_date': '2026-02-01'})
    assert [row['quantity'] for row in later['rows']] == ['0.125', '0.125', '0']
    other = request('POST', 'reports/query', {'kind': 'inventory_balance', 'warehouse_id': warehouse})
    assert {row['quantity'] for row in other['rows']} == {'0'}


def test_all_models_match_existing_migration_columns_and_storage_types(erp):
    # 历史迁移仍决定实际结构；模型漏表、漏列或误把十进制文本映射成数值都必须失败。
    inspector = inspect(engine_for(database_path().resolve()))
    actual = set(inspector.get_table_names())
    assert actual == set(Base.metadata.tables)
    for table in actual:
        physical = {column['name']: column for column in inspector.get_columns(table)}
        model = Base.metadata.tables[table]
        assert set(physical) == set(model.columns.keys()), table
        assert set(inspector.get_pk_constraint(table)['constrained_columns']) == {
            column.name for column in model.primary_key}
        for column in model.columns:
            assert isinstance(physical[column.name]['type'], type(column.type)), (table, column.name)
