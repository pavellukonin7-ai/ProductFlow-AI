from __future__ import annotations

import importlib
import sys


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("PRODUCT_MCP_DB_PATH", str(tmp_path / "web-v160.sqlite3"))
    monkeypatch.setenv("WEB_ADMIN_PASSWORD", "admin-test-password")
    monkeypatch.setenv("WEB_API_KEY", "api-test-key")
    monkeypatch.setenv("WEB_SESSION_SECRET", "session-test-secret")
    monkeypatch.setenv("WEB_HOST", "127.0.0.1")
    monkeypatch.setenv("WEB_PORT", "8099")
    sys.modules.pop("web_admin.app", None)
    module = importlib.import_module("web_admin.app")
    from starlette.testclient import TestClient
    return TestClient(module.app)


def _login(client) -> None:
    response = client.post(
        "/login",
        data={"password": "admin-test-password", "next": "/"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_web_product_supplier_purchase_sale_lifecycle(tmp_path, monkeypatch) -> None:
    with _client(tmp_path, monkeypatch) as client:
        _login(client)

        created = client.post(
            "/actions/product/create",
            data={
                "sku": "WEB-001", "name": "Web Product", "category": "Web",
                "price": "250", "purchase_price": "100", "initial_stock": "5",
                "min_stock": "1", "unit": "шт.", "barcode": "1234567890123",
                "supplier": "", "description": "created from web",
            },
            follow_redirects=False,
        )
        assert created.status_code == 303
        detail = client.get("/products/WEB-001")
        assert detail.status_code == 200
        assert "Web Product" in detail.text

        updated = client.post(
            "/actions/product/WEB-001/update",
            data={
                "name": "Web Product Updated", "category": "Web", "price": "275",
                "purchase_price": "110", "min_stock": "2", "unit": "шт.",
                "barcode": "1234567890123", "supplier": "SUP-WEB",
                "description": "updated", "is_active": "1",
            },
            follow_redirects=False,
        )
        assert updated.status_code == 303

        supplier = client.post(
            "/actions/supplier/create",
            data={"code": "SUP-WEB", "name": "Web Supplier", "contact_name": "Ivan", "phone": "123", "email": "test@example.com", "comment": "test"},
            follow_redirects=False,
        )
        assert supplier.status_code == 303
        supplier_update = client.post(
            "/actions/supplier/SUP-WEB/update",
            data={"name": "Web Supplier 2", "contact_name": "Ivan", "phone": "456", "email": "test@example.com", "comment": "updated", "is_active": "1"},
            follow_redirects=False,
        )
        assert supplier_update.status_code == 303

        purchase = client.post(
            "/actions/purchase/create",
            data={"order_no": "PO-WEB", "supplier_code": "SUP-WEB", "comment": "draft", "items": "WEB-001 | 2 | 90"},
            follow_redirects=False,
        )
        assert purchase.status_code == 303
        purchase_edit = client.post(
            "/actions/purchase/PO-WEB/update",
            data={"supplier_code": "SUP-WEB", "comment": "edited", "items": "WEB-001 | 3 | 95"},
            follow_redirects=False,
        )
        assert purchase_edit.status_code == 303
        purchase_receive = client.post("/actions/purchase/PO-WEB/receive", follow_redirects=False)
        assert purchase_receive.status_code == 303
        po = client.get("/api/v1/purchases/PO-WEB", headers={"Authorization": "Bearer api-test-key"})
        assert po.status_code == 200
        assert po.json()["status"] == "received"
        assert po.json()["items"][0]["quantity"] == 3

        sale = client.post(
            "/actions/sale/create",
            data={"order_no": "SO-WEB", "customer_name": "Client", "comment": "draft", "items": "WEB-001 | 1 | 300"},
            follow_redirects=False,
        )
        assert sale.status_code == 303
        sale_edit = client.post(
            "/actions/sale/SO-WEB/update",
            data={"customer_name": "Client Updated", "comment": "edited", "items": "WEB-001 | 2 | 310"},
            follow_redirects=False,
        )
        assert sale_edit.status_code == 303
        sale_complete = client.post("/actions/sale/SO-WEB/complete", follow_redirects=False)
        assert sale_complete.status_code == 303
        so = client.get("/api/v1/sales/SO-WEB", headers={"Authorization": "Bearer api-test-key"})
        assert so.status_code == 200
        assert so.json()["status"] == "completed"
        assert so.json()["items"][0]["quantity"] == 2

        audit = client.get("/api/v1/audit", headers={"Authorization": "Bearer api-test-key"})
        actions = {row["action"] for row in audit.json()}
        assert "product.create" in actions
        assert "product.update" in actions
        assert "supplier.update" in actions
        assert "purchase.update" in actions
        assert "purchase.receive" in actions
        assert "sale.update" in actions
        assert "sale.complete" in actions


def test_api_patch_supplier_purchase_sale_and_cancel(tmp_path, monkeypatch) -> None:
    with _client(tmp_path, monkeypatch) as client:
        h = {"Authorization": "Bearer api-test-key", "X-ProductFlow-Client": "test-suite"}
        product = client.post("/api/v1/products", headers=h, json={"sku":"API-001","name":"API Product","category":"API","price":100,"purchase_price":50,"initial_stock":10,"min_stock":1})
        assert product.status_code == 201
        sup = client.post("/api/v1/suppliers", headers=h, json={"code":"SUP-API","name":"Supplier"})
        assert sup.status_code == 201
        sup_patch = client.patch("/api/v1/suppliers/SUP-API", headers=h, json={"name":"Supplier Updated","phone":"999"})
        assert sup_patch.status_code == 200
        assert sup_patch.json()["name"] == "Supplier Updated"

        po = client.post("/api/v1/purchases", headers=h, json={"order_no":"PO-API","supplier_code":"SUP-API","items":[{"sku":"API-001","quantity":2,"purchase_price":45}]})
        assert po.status_code == 201
        po_patch = client.patch("/api/v1/purchases/PO-API", headers=h, json={"supplier_code":"SUP-API","items":[{"sku":"API-001","quantity":3,"purchase_price":44}],"comment":"updated"})
        assert po_patch.status_code == 200
        assert po_patch.json()["items"][0]["quantity"] == 3
        po_cancel = client.post("/api/v1/purchases/PO-API/cancel", headers=h)
        assert po_cancel.status_code == 200
        assert po_cancel.json()["status"] == "cancelled"

        so = client.post("/api/v1/sales", headers=h, json={"order_no":"SO-API","customer_name":"A","items":[{"sku":"API-001","quantity":1,"unit_price":120}]})
        assert so.status_code == 201
        so_patch = client.patch("/api/v1/sales/SO-API", headers=h, json={"customer_name":"B","items":[{"sku":"API-001","quantity":2,"unit_price":125}],"comment":"updated"})
        assert so_patch.status_code == 200
        assert so_patch.json()["customer_name"] == "B"
        so_cancel = client.post("/api/v1/sales/SO-API/cancel", headers=h)
        assert so_cancel.status_code == 200
        assert so_cancel.json()["status"] == "cancelled"
