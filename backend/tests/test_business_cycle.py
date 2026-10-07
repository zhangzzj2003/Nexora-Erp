"""验证采购、调拨、生产、销售与业务对账共用同一套物料和库存。"""

from approval_test_helpers import approve_document

from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app


def test_procure_produce_sell_cycle(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "business-cycle.db"))
    with TestClient(app, client=("127.0.0.1", 12000)) as client:
        base = "/api/v1"

        def create(path, headers, payload):
            response = client.post(f"{base}{path}", headers=headers, json=payload)
            assert response.status_code == 201, response.text
            return response.json()

        def confirm(path, headers):
            response = client.post(f"{base}{path}", headers=headers)
            assert response.status_code == 200, response.text
            return response.json()

        def login(username):
            response = client.post(f"{base}/auth/login", json={
                "username": username, "password": "secure-pass-123"})
            assert response.status_code == 200, response.text
            return {"Authorization": f"Bearer {response.json()['token']}"}

        create("/setup/admin", None, {"username": "admin", "password": "secure-pass-123"})
        admin = login("admin")
        for username, role in (("buyer", "buyer"), ("warehouse", "warehouse"),
                               ("planner", "planner"), ("seller", "seller"),
                               ("finance", "finance")):
            create("/users", admin, {"username": username, "password": "secure-pass-123",
                                     "roles": [role]})
        buyer, warehouse, planner = login("buyer"), login("warehouse"), login("planner")
        seller, finance = login("seller"), login("finance")

        supplier = create("/suppliers", buyer, {"name": "组件供应商"})["id"]
        customer = create("/customers", seller, {"name": "成品客户"})["id"]
        component = create("/materials", buyer, {"sku": "CYCLE-PART", "name": "组件",
                                                  "unit": "件"})["id"]
        product = create("/materials", buyer, {"sku": "CYCLE-FIN", "name": "成品",
                                                "unit": "件"})["id"]
        production_warehouse = create("/warehouses", admin, {
            "code": "CYCLE", "name": "生产仓"})["id"]

        # 采购入库形成应付与主仓库存，调拨只移动库存，不重复产生采购金额。
        purchase = create("/purchase-orders", buyer, {"supplier_id": supplier, "lines": [
            {"material_id": component, "quantity": "4", "unit_price": "3"}]})["id"]
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, admin, 'PurchaseOrder', purchase)
        confirm(f"/purchase-orders/{purchase}/confirm", buyer)
        receipt = create("/receipts", buyer, {"supplier_id": supplier, "purchase_order_id": purchase,
                                               "warehouse_id": 1, "lines": [
                                                   {"material_id": component, "quantity": "4"}]})["id"]
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, admin, 'Receipt', receipt)
        confirm(f"/receipts/{receipt}/post", warehouse)
        transfer = create("/transfers", warehouse, {"from_warehouse_id": 1,
                                                     "to_warehouse_id": production_warehouse,
                                                     "lines": [{"material_id": component,
                                                                "quantity": "4"}]})["id"]
        approve_document(client, admin, 'Transfer', transfer)
        confirm(f"/transfers/{transfer}/post", warehouse)

        bom = create("/boms", planner, {"product_material_id": product, "base_quantity": "1",
                                        "lines": [{"component_material_id": component,
                                                   "quantity": "2"}]})["id"]
        confirm(f"/boms/{bom}/activate", planner)
        work_order = create("/work-orders", planner, {"bom_id": bom,
                                                       "warehouse_id": production_warehouse,
                                                       "target_quantity": "2"})
        confirm(f"/work-orders/{work_order['id']}/release", planner)
        issue = create("/material-issues", planner, {"work_order_id": work_order["id"],
                                                        "warehouse_id": production_warehouse,
                                                        "lines": [{"work_order_line_id": work_order["lines"][0]["id"],
                                                                   "quantity": "4"}]})
        confirm(f"/material-issues/{issue['id']}/post", warehouse)
        # 领料成本自动沿用采购入库形成的库存平均成本，不再重复人工核价。
        assert client.get(f"{base}/production-costs", headers=finance).json()["orders"][0]["known_material_amount"] == "12.00"
        create("/production-costs/charges", finance, {"work_order_id": work_order["id"],
                                                       "kind": "labor", "amount": "2",
                                                       "reference": "LABOR-CYCLE"})

        sale = create("/sales-orders", seller, {"customer_id": customer, "lines": [
            {"material_id": product, "quantity": "2", "unit_price": "10"}]})["id"]
        confirm(f"/sales-orders/{sale}/confirm", seller)
        shipment = create("/shipments", warehouse, {"sales_order_id": sale,
                                                     "warehouse_id": production_warehouse,
                                                     "lines": [{"material_id": product,
                                                                "quantity": "2"}]})["id"]
        # 成品尚未质检入库时，销售草稿不能透支生产仓，也不能提前形成应收。
        assert client.post(f"{base}/shipments/{shipment}/post", headers=warehouse).status_code == 409
        assert all(item["source_type"] != "shipment" for item in client.get(
            f"{base}/movements", headers=warehouse).json())
        assert client.get(f"{base}/sales-orders", headers=seller).json()[0]["status"] == "confirmed"
        accounts = client.get(f"{base}/finance/accounts", headers=finance).json()
        assert [(item["kind"], item["business_amount"]) for item in accounts] == [("payable", "12.00")]

        completion = create("/production-completions", planner, {
            "work_order_id": work_order["id"], "reported_quantity": "2"})["id"]
        inspected = client.post(f"{base}/production-completions/{completion}/inspect",
                                headers=warehouse, json={"accepted_quantity": "2", "qc_note": "全数合格"})
        assert inspected.status_code == 200, inspected.text
        confirm(f"/production-completions/{completion}/post", warehouse)
        settlement = create('/production-costs/settlements', finance, {
            'work_order_id': work_order['id'], 'reference': 'SETTLE-CYCLE'})
        assert settlement['total_amount'] == '14.00'
        assert settlement['allocations'][0]['amount'] == '14.00'
        produced = client.get(f"{base}/stock?warehouse_id={production_warehouse}", headers=warehouse).json()
        assert Decimal(next(row["quantity"] for row in produced if row["id"] == product)) == Decimal(2)
        confirm(f"/shipments/{shipment}/post", warehouse)

        def quantity(warehouse_id, material_id):
            rows = client.get(f"{base}/stock?warehouse_id={warehouse_id}", headers=warehouse).json()
            return Decimal(next(row["quantity"] for row in rows if row["id"] == material_id))

        assert quantity(1, component) == Decimal(0)
        assert quantity(production_warehouse, component) == Decimal(0)
        assert quantity(production_warehouse, product) == Decimal(0)
        assert client.get(f"{base}/work-orders", headers=planner).json()[0]["status"] == "completed"
        cost = client.get(f"{base}/production-costs", headers=finance).json()["orders"][0]
        assert cost["known_material_amount"] == "12.00"
        assert cost["total_amount"] == "14.00"

        # 两类业务金额分别来自已确认入库和出库，收付款仅核对余额，不改写库存流水。
        accounts = client.get(f"{base}/finance/accounts", headers=finance).json()
        assert {(item["kind"], item["business_amount"]) for item in accounts} == {
            ("payable", "12.00"), ("receivable", "20.00")}
        create("/finance/payment-records", finance, {"kind": "payable", "order_id": purchase,
                                                      "action": "settlement", "amount": "12",
                                                      "reference": "PAY-CYCLE"})
        create("/finance/payment-records", finance, {"kind": "receivable", "order_id": sale,
                                                      "action": "settlement", "amount": "20",
                                                      "reference": "RECEIVE-CYCLE"})
        assert {item["outstanding_amount"] for item in client.get(
            f"{base}/finance/accounts", headers=finance).json()} == {"0.00"}

        movements = client.get(f"{base}/movements", headers=warehouse).json()
        assert {item["source_type"] for item in movements} == {
            "receipt", "transfer_out", "transfer_in", "material_issue",
            "production_completion", "shipment"}
        assert all(item["created_by"] and item["source_line_id"] for item in movements)
        assert {item["material_id"] for item in movements} == {component, product}
