"""验证收付款按订单限额、退货退款和不可变冲销记录。"""

from approval_test_helpers import approve_document, prepare_purchase_return, execute_payment

from fastapi.testclient import TestClient

from app.main import app


def test_payment_records_reconciliation_and_reversal(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXORA_DB_PATH", str(tmp_path / "payments.db"))
    with TestClient(app, client=("127.0.0.1", 12000)) as client:
        base = "/api/v1"
        client.post(f"{base}/setup/admin", json={"username": "admin", "password": "secure-pass-123"})

        def login(username: str) -> dict:
            token = client.post(f"{base}/auth/login", json={
                "username": username, "password": "secure-pass-123"}).json()["token"]
            return {"Authorization": f"Bearer {token}"}

        admin = login("admin")
        for username, role in (("accountant", "finance"), ("buyer", "buyer")):
            client.post(f"{base}/users", headers=admin, json={
                "username": username, "password": "secure-pass-123", "roles": [role]})
        finance, buyer = login("accountant"), login("buyer")
        supplier = client.post(f"{base}/suppliers", headers=admin, json={"name": "付款供应商"}).json()["id"]
        customer = client.post(f"{base}/customers", headers=admin, json={"name": "付款客户"}).json()["id"]
        material = client.post(f"{base}/materials", headers=admin, json={
            "sku": "PAY", "name": "收付款物料", "unit": "件"}).json()["id"]
        purchase = client.post(f"{base}/purchase-orders", headers=admin, json={
            "supplier_id": supplier, "lines": [{"material_id": material, "quantity": "2",
                                               "unit_price": "4"}]}).json()["id"]
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, admin, 'PurchaseOrder', purchase)
        client.post(f"{base}/purchase-orders/{purchase}/confirm", headers=admin)
        receipt = client.post(f"{base}/receipts", headers=admin, json={
            "supplier_id": supplier, "purchase_order_id": purchase,
            "lines": [{"material_id": material, "quantity": "2"}]}).json()
        receipt_id = receipt["id"]
        sale = client.post(f"{base}/sales-orders", headers=admin, json={
            "customer_id": customer, "lines": [{"material_id": material, "quantity": "2",
                                               "unit_price": "10"}]}).json()["id"]
        approve_document(client, admin, 'SalesOrder', sale)
        client.post(f"{base}/sales-orders/{sale}/confirm", headers=admin)
        shipment = client.post(f"{base}/shipments", headers=admin, json={
            "sales_order_id": sale, "warehouse_id": 1,
            "lines": [{"material_id": material, "quantity": "2"}]}).json()

        path = f"{base}/finance/payment-records"
        payment = {"kind": "receivable", "order_id": sale, "action": "settlement",
                   "amount": "15.00", "reference": "BANK-001", "note": "客户转账"}
        assert client.post(path, headers=buyer, json=payment).status_code == 403
        assert client.get(path, headers=buyer).status_code == 403
        assert client.post(path, headers=finance, json=payment).status_code == 409
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, admin, 'Receipt', receipt_id)
        client.post(f"{base}/receipts/{receipt_id}/post", headers=admin)
        approve_document(client, admin, 'Shipment', shipment['id'])
        client.post(f"{base}/shipments/{shipment['id']}/post", headers=admin)
        assert client.post(path, headers=finance, json={**payment, "amount": "20.001"}).status_code == 422
        assert client.post(path, headers=finance, json={**payment, "reference": "   "}).status_code == 422
        assert client.post(path, headers=finance, json={**payment, "amount": "21"}).status_code == 409
        assert client.post(path, headers=finance, json={**payment, "action": "refund"}).status_code == 409
        first = client.post(path, headers=finance, json=payment)
        assert first.status_code == 201
        first_id = first.json()["id"]
        assert first.json()["amount"] == "15.00"
        assert first.json()["party_name"] == "付款客户"
        # 保存只是草稿，显式独立批准执行后再验证原余额和退款约束。
        execute_payment(client,finance,first.json(),account_headers=admin)
        assert client.post(path, headers=finance, json=payment).status_code == 409
        accounts = client.get(f"{base}/finance/accounts", headers=finance).json()
        overview = client.get(f"{base}/finance/overview", headers=finance).json()
        assert overview["report"]["receivable_amount"] == "20.00"
        assert overview["accounts"] == accounts
        assert overview["payments"][0]["id"] == first_id
        sale_account = next(item for item in accounts if item["kind"] == "receivable")
        assert sale_account["business_amount"] == "20.00"
        assert sale_account["settled_amount"] == "15.00"
        assert sale_account["outstanding_amount"] == "5.00"
        assert len(sale_account["source_keys"]) == 1

        second_record = client.post(path, headers=finance, json={
            **payment, "amount": "5.00", "reference": "BANK-002"}).json()
        second=execute_payment(client,finance,second_record,account_headers=admin)['id']
        assert client.post(path, headers=finance, json={
            **payment, "amount": "0.01", "reference": "BANK-003"}).status_code == 409
        assert client.post(f"{path}/{second}/reverse", headers=finance, json={
            "reason": "误录收款"}).status_code == 201
        assert client.post(f"{path}/{second}/reverse", headers=finance, json={
            "reason": "再次冲销"}).status_code == 409
        reversal = client.get(path, headers=finance).json()[0]
        assert reversal["reverses_id"] == second
        assert reversal["amount"] == "-5.00"
        assert reversal["created_by_name"] == "accountant"
        execute_payment(client,finance,reversal,account_headers=admin)
        assert client.post(f"{path}/{reversal['id']}/reverse", headers=finance, json={
            "reason": "无效"}).status_code == 409
        last=client.post(path, headers=finance, json={
            **payment, "amount": "5.00", "reference": "BANK-004"}).json()
        execute_payment(client,finance,last,account_headers=admin)

        # 销售退货在已收款后形成贷方余额；退款冲减该余额，原收款不改写。
        sale_return = client.post(f"{base}/sales-returns", headers=admin, json={
            "shipment_id": shipment["id"], "warehouse_id": 1, "reason": "退一件",
            "lines": [{"shipment_line_id": shipment["lines"][0]["id"], "quantity": "1"}]}).json()["id"]
        approve_document(client, admin, 'SalesReturn', sale_return)
        client.post(f"{base}/sales-returns/{sale_return}/post", headers=admin)
        sale_account = next(item for item in client.get(f"{base}/finance/accounts", headers=finance).json()
                            if item["kind"] == "receivable")
        assert sale_account["business_amount"] == "10.00"
        assert sale_account["outstanding_amount"] == "-10.00"
        assert client.post(path, headers=finance, json={
            **payment, "action": "refund", "amount": "11", "reference": "REF-001"}).status_code == 409
        refund = client.post(path, headers=finance, json={
            **payment, "action": "refund", "amount": "10.00", "reference": "REF-002"})
        assert refund.status_code == 201
        assert refund.json()["amount"] == "-10.00"
        execute_payment(client,finance,refund.json(),account_headers=admin)
        assert next(item for item in client.get(f"{base}/finance/accounts", headers=finance).json()
                    if item["kind"] == "receivable")["outstanding_amount"] == "0.00"

        # 应付记录使用采购订单的已确认入库金额，退供应商后的退款同样独立留痕。
        payable = {"kind": "payable", "order_id": purchase, "action": "settlement",
                   "amount": "8.00", "reference": "OUT-001"}
        outgoing=client.post(path, headers=finance, json=payable)
        assert outgoing.status_code == 201
        execute_payment(client,finance,outgoing.json(),account_headers=admin)
        purchase_return = client.post(f"{base}/purchase-returns", headers=admin, json={
            "receipt_id": receipt_id, "reason": "退一件",
            "lines": [{"receipt_line_id": receipt["lines"][0]["id"], "quantity": "1"}]}).json()["id"]
        prepare_purchase_return(client, admin, purchase_return)
        client.post(f"{base}/purchase-returns/{purchase_return}/post", headers=admin)
        payable_account = next(item for item in client.get(f"{base}/finance/accounts", headers=finance).json()
                               if item["kind"] == "payable")
        assert payable_account["business_amount"] == "4.00"
        assert payable_account["outstanding_amount"] == "-4.00"
        incoming=client.post(path, headers=finance, json={
            **payable, "action": "refund", "amount": "4.00", "reference": "IN-001"})
        assert incoming.status_code == 201
        execute_payment(client,finance,incoming.json(),account_headers=admin)
        assert client.get(path, headers=finance).json()[0]["action"] == "refund"
        assert client.get(f"{base}/finance/accounts", headers=buyer).status_code == 403
