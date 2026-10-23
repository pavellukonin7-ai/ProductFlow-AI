from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from mcp_server.commerce import CommerceRepository
from mcp_server.crm import CustomerRepository, OrderWorkflowRepository
from mcp_server.database import Database
from mcp_server.repository import ProductRepository
from mcp_server.warehouse import WarehouseRepository


def make_repos(tmp_path: Path):
    db = Database(tmp_path / "v170.sqlite3")
    return ProductRepository(db), CommerceRepository(db), CustomerRepository(db), OrderWorkflowRepository(db)


def test_customer_card_and_order_history(tmp_path: Path) -> None:
    products, commerce, customers, workflow = make_repos(tmp_path)
    products.create_product(
        sku="CRM-1", name="CRM Product", category="CRM", price=1000,
        purchase_price=600, initial_stock=10, min_stock=1,
    )
    customer = customers.create_customer(
        code="CUST-1", name="ООО Клиент", contact_name="Иван", phone="123", email="c@example.com"
    )
    assert customer["code"] == "CUST-1"
    order = commerce.create_sales_order(
        order_no="SO-CUST", customer_name="", customer_code="CUST-1",
        items=[{"sku": "CRM-1", "quantity": 2}],
    )
    assert order["customer_code"] == "CUST-1"
    assert order["customer_name"] == "ООО Клиент"
    commerce.complete_sales_order("SO-CUST")

    card = customers.get_customer("CUST-1")
    assert card["orders_count"] == 1
    assert card["completed_orders"] == 1
    assert card["revenue"] == 2000
    assert card["gross_profit"] == 800
    history = customers.customer_orders("CUST-1")
    assert history[0]["order_no"] == "SO-CUST"
    assert history[0]["status"] == "completed"


def test_reservation_reduces_available_not_physical_stock(tmp_path: Path) -> None:
    products, commerce, customers, workflow = make_repos(tmp_path)
    products.create_product(
        sku="RES-1", name="Reserved", category="X", price=100, purchase_price=50,
        initial_stock=10, min_stock=0,
    )
    commerce.create_sales_order(
        order_no="SO-R1", customer_name="A", items=[{"sku": "RES-1", "quantity": 6}]
    )
    reserved = workflow.reserve("SO-R1")
    assert reserved["status"] == "reserved"
    assert reserved["items"][0]["reserved_quantity"] == 6
    assert products.get_product("RES-1").stock == 10
    availability = workflow.availability("RES-1")
    assert availability["main_stock"] == 10
    assert availability["reserved"] == 6
    assert availability["available"] == 4

    commerce.create_sales_order(
        order_no="SO-R2", customer_name="B", items=[{"sku": "RES-1", "quantity": 5}]
    )
    with pytest.raises(ValueError, match="Недостаточно доступного товара"):
        workflow.reserve("SO-R2")
    assert commerce.get_sales_order("SO-R2")["status"] == "new"


def test_manual_stock_cannot_consume_reserved_units(tmp_path: Path) -> None:
    products, commerce, customers, workflow = make_repos(tmp_path)
    products.create_product(
        sku="SAFE-1", name="Safe", category="X", price=100, purchase_price=50,
        initial_stock=10, min_stock=0,
    )
    commerce.create_sales_order(
        order_no="SO-SAFE", customer_name="A", items=[{"sku": "SAFE-1", "quantity": 7}]
    )
    workflow.reserve("SO-SAFE")
    with pytest.raises(ValueError, match="резерв"):
        products.stock_operation(sku="SAFE-1", operation="sale", quantity=4, reason="manual")
    products.stock_operation(sku="SAFE-1", operation="sale", quantity=3, reason="manual allowed")
    assert products.get_product("SAFE-1").stock == 7
    assert workflow.availability("SAFE-1")["available"] == 0


def test_partial_shipment_and_final_completion(tmp_path: Path) -> None:
    products, commerce, customers, workflow = make_repos(tmp_path)
    products.create_product(
        sku="SHIP-1", name="Ship", category="X", price=500, purchase_price=200,
        initial_stock=10, min_stock=0,
    )
    commerce.create_sales_order(
        order_no="SO-SHIP", customer_name="Client", items=[{"sku": "SHIP-1", "quantity": 5}]
    )
    workflow.reserve("SO-SHIP")
    workflow.start_processing("SO-SHIP")
    partial = workflow.ship("SO-SHIP", items=[{"sku": "SHIP-1", "quantity": 2}])
    assert partial["status"] == "processing"
    assert partial["items"][0]["fulfilled_quantity"] == 2
    assert partial["items"][0]["reserved_quantity"] == 3
    assert products.get_product("SHIP-1").stock == 8
    with pytest.raises(ValueError, match="частичной отгрузки"):
        workflow.release("SO-SHIP")
    with pytest.raises(ValueError, match="частичной отгрузки"):
        commerce.cancel_sales_order("SO-SHIP")

    done = workflow.ship("SO-SHIP")
    assert done["status"] == "completed"
    assert done["items"][0]["fulfilled_quantity"] == 5
    assert done["items"][0]["reserved_quantity"] == 0
    assert products.get_product("SHIP-1").stock == 5
    analytics = commerce.sales_analytics(days=30)
    assert analytics["orders_count"] == 1
    assert analytics["units_net"] == 5
    assert analytics["revenue"] == 2500
    assert analytics["cost"] == 1000




def test_transfer_from_main_cannot_break_reservation(tmp_path: Path) -> None:
    products, commerce, customers, workflow = make_repos(tmp_path)
    warehouses = WarehouseRepository(products.db)
    products.create_product(
        sku="MOVE-RES", name="Move Reserved", category="X", price=100, purchase_price=50,
        initial_stock=10, min_stock=0,
    )
    warehouses.create_warehouse(code="SPB", name="SPB")
    commerce.create_sales_order(
        order_no="SO-MOVE", customer_name="A", items=[{"sku": "MOVE-RES", "quantity": 8}]
    )
    workflow.reserve("SO-MOVE")
    warehouses.transfer(sku="MOVE-RES", quantity=2, from_warehouse="MAIN", to_warehouse="SPB")
    with pytest.raises(ValueError, match="резерв"):
        warehouses.transfer(sku="MOVE-RES", quantity=1, from_warehouse="MAIN", to_warehouse="SPB")
    dist = {x["warehouse_code"]: x["quantity"] for x in warehouses.product_distribution("MOVE-RES")}
    assert dist["MAIN"] == 8
    assert dist["SPB"] == 2

def test_release_reservation_returns_order_to_new(tmp_path: Path) -> None:
    products, commerce, customers, workflow = make_repos(tmp_path)
    products.create_product(
        sku="REL-1", name="Release", category="X", price=100, purchase_price=50,
        initial_stock=4, min_stock=0,
    )
    commerce.create_sales_order(
        order_no="SO-REL", customer_name="A", items=[{"sku": "REL-1", "quantity": 3}]
    )
    workflow.reserve("SO-REL")
    released = workflow.release("SO-REL")
    assert released["status"] == "new"
    assert released["items"][0]["reserved_quantity"] == 0
    assert workflow.availability("REL-1")["available"] == 4


def _web_client(tmp_path, monkeypatch):
    monkeypatch.setenv("PRODUCT_MCP_DB_PATH", str(tmp_path / "web-v170.sqlite3"))
    monkeypatch.setenv("WEB_ADMIN_PASSWORD", "admin-test-password")
    monkeypatch.setenv("WEB_API_KEY", "api-test-key")
    monkeypatch.setenv("WEB_SESSION_SECRET", "session-test-secret")
    monkeypatch.setenv("WEB_HOST", "127.0.0.1")
    monkeypatch.setenv("WEB_PORT", "8099")
    sys.modules.pop("web_admin.app", None)
    module = importlib.import_module("web_admin.app")
    from starlette.testclient import TestClient
    return TestClient(module.app)


def test_web_api_customer_reserve_and_partial_ship(tmp_path, monkeypatch) -> None:
    with _web_client(tmp_path, monkeypatch) as client:
        h = {"Authorization": "Bearer api-test-key", "X-ProductFlow-Client": "crm-test"}
        p = client.post("/api/v1/products", headers=h, json={
            "sku":"W170","name":"Web CRM","category":"CRM","price":1000,
            "purchase_price":500,"initial_stock":10,"min_stock":1,
        })
        assert p.status_code == 201
        c = client.post("/api/v1/customers", headers=h, json={"code":"WC-1","name":"Web Customer","phone":"123"})
        assert c.status_code == 201
        sale = client.post("/api/v1/sales", headers=h, json={
            "order_no":"WSO-1","customer_code":"WC-1","customer_name":"",
            "items":[{"sku":"W170","quantity":4}],
        })
        assert sale.status_code == 201
        assert sale.json()["customer_code"] == "WC-1"
        r = client.post("/api/v1/sales/WSO-1/reserve", headers=h)
        assert r.status_code == 200
        assert r.json()["status"] == "reserved"
        availability = client.get("/api/v1/availability/W170", headers=h)
        assert availability.json()["available"] == 6
        ship = client.post("/api/v1/sales/WSO-1/ship", headers=h, json={"items":[{"sku":"W170","quantity":1}]})
        assert ship.status_code == 200
        assert ship.json()["status"] == "processing"
        assert ship.json()["items"][0]["fulfilled_quantity"] == 1
        customer = client.get("/api/v1/customers/WC-1", headers=h)
        assert customer.status_code == 200
        customer_page = client.post("/login", data={"password":"admin-test-password","next":"/customers"}, follow_redirects=False)
        assert customer_page.status_code == 303
        page = client.get("/customers")
        assert page.status_code == 200
        assert "Web Customer" in page.text
