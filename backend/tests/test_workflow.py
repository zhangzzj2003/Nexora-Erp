"""使用真实本地数据库验证权限、入库事务和重启后的数据。"""

from approval_test_helpers import approve_document

import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.original_path = os.environ.get("NEXORA_DB_PATH")
        os.environ["NEXORA_DB_PATH"] = str(Path(self.directory.name) / "nexora.db")
        self.client_context = TestClient(app, client=("127.0.0.1", 12345))
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        if self.original_path is None:
            os.environ.pop("NEXORA_DB_PATH", None)
        else:
            os.environ["NEXORA_DB_PATH"] = self.original_path
        self.directory.cleanup()

    def login(self, username, password):
        response = self.client.post("/api/v1/auth/login", json={"username": username, "password": password})
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": f"Bearer {response.json()['token']}"}

    def test_health_and_schema(self):
        # 健康接口保持原有响应契约，接口文档包含业务入口。
        self.assertEqual(self.client.get("/api/v1/health").json(),
            {"status": "ok", "service": "nexora-api", "version": "0.1.0"})
        paths = self.client.get("/openapi.json").json()["paths"]
        self.assertIn("/api/v1/health", paths)
        self.assertIn("/api/v1/receipts/{receipt_id}/post", paths)

    def test_permissions_receipt_and_persistence(self):
        base = "/api/v1"
        self.assertTrue(self.client.get(f"{base}/setup/status").json()["needs_setup"])
        self.assertEqual(self.client.get(f"{base}/stock").status_code, 401)
        first = self.client.post(f"{base}/setup/admin", json={"username": "Admin", "password": "secure-pass-123"})
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(self.client.post(f"{base}/setup/admin", json={"username": "other", "password": "secure-pass-123"}).status_code, 409)
        self.assertFalse(self.client.get(f"{base}/setup/status").json()["needs_setup"])
        self.assertEqual(self.client.post(f"{base}/auth/login", json={"username": "admin", "password": "wrong"}).status_code, 401)
        admin = self.login("ADMIN", "secure-pass-123")

        # 管理员创建不同岗位；账号权限不依赖前端是否显示按钮。
        ids = {}
        for name, role in [("buyer", "buyer"), ("warehouse", "warehouse"), ("viewer", "viewer")]:
            response = self.client.post(f"{base}/users", headers=admin,
                json={"username": name, "password": "secure-pass-123", "roles": [role]})
            self.assertEqual(response.status_code, 201, response.text)
            ids[name] = response.json()["id"]
        buyer = self.login("buyer", "secure-pass-123")
        warehouse = self.login("warehouse", "secure-pass-123")
        viewer = self.login("viewer", "secure-pass-123")
        self.assertEqual(self.client.get(f"{base}/users", headers=buyer).status_code, 403)
        self.assertEqual(self.client.post(f"{base}/materials", headers=viewer,
            json={"sku": "X", "name": "X", "unit": "件"}).status_code, 403)

        supplier = self.client.post(f"{base}/suppliers", headers=buyer, json={"name": "甲供应商"})
        material = self.client.post(f"{base}/materials", headers=buyer,
            json={"sku": "MAT-001", "name": "测试物料", "unit": "千克"})
        self.assertEqual(supplier.status_code, 201)
        self.assertEqual(material.status_code, 201)
        receipt_input = {"supplier_id": supplier.json()["id"], "reference": "PO-1",
            "lines": [{"material_id": material.json()["id"], "quantity": "2.125"}]}
        self.assertEqual(self.client.post(f"{base}/receipts", headers=warehouse, json=receipt_input).status_code, 403)
        self.assertEqual(self.client.post(f"{base}/receipts", headers=buyer,
            json={**receipt_input, "lines": [{"material_id": material.json()["id"], "quantity": "0"}]}).status_code, 422)
        receipt = self.client.post(f"{base}/receipts", headers=buyer, json=receipt_input)
        self.assertEqual(receipt.status_code, 201, receipt.text)
        receipt_id = receipt.json()["id"]
        self.assertEqual(self.client.get(f"{base}/stock", headers=viewer).json()[0]["quantity"], "0")
        self.assertEqual(self.client.post(f"{base}/receipts/{receipt_id}/post", headers=buyer).status_code, 403)
        # 先完成真实独立审批，保留原业务失败和并发断言。
        approve_document(self.client, admin, 'Receipt', receipt_id)
        posted = self.client.post(f"{base}/receipts/{receipt_id}/post", headers=warehouse)
        self.assertEqual(posted.status_code, 200, posted.text)
        self.assertEqual(posted.json()["status"], "posted")
        self.assertEqual(self.client.post(f"{base}/receipts/{receipt_id}/post", headers=warehouse).status_code, 409)
        self.assertEqual(self.client.get(f"{base}/stock", headers=viewer).json()[0]["quantity"], "2.125")
        self.assertEqual(len(self.client.get(f"{base}/movements", headers=viewer).json()), 1)

        # 审批测试人员已完成本次业务，撤去临时管理员角色后再验证最后管理员保护。
        reviewer = next(row for row in self.client.get(f"{base}/users", headers=admin).json()
                        if row['username'] == 'independent_reviewer_1')
        self.assertEqual(self.client.put(f"{base}/users/{reviewer['id']}/roles", headers=admin,
            json={"roles": ["viewer"]}).status_code, 200)
        # 角色调整立即作用于已有会话，并且不能撤销最后一个管理员。
        self.assertEqual(self.client.put(f"{base}/users/{first.json()['id']}/roles", headers=admin,
            json={"roles": ["viewer"]}).status_code, 409)
        changed = self.client.put(f"{base}/users/{ids['viewer']}/roles", headers=admin,
            json={"roles": ["buyer"]})
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(self.client.post(f"{base}/receipts", headers=viewer, json=receipt_input).status_code, 201)

        # 关闭并重新打开服务后，数据仍从同一个 SQLite 文件读取。
        self.client_context.__exit__(None, None, None)
        self.client_context = TestClient(app, client=("127.0.0.1", 12345))
        self.client = self.client_context.__enter__()
        fresh_login = self.login("admin", "secure-pass-123")
        self.assertEqual(self.client.get(f"{base}/stock", headers=fresh_login).json()[0]["quantity"], "2.125")
        self.assertEqual(len(self.client.get(f"{base}/movements", headers=fresh_login).json()), 1)


if __name__ == "__main__":
    unittest.main()
