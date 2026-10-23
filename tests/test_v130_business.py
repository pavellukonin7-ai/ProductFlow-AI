from pathlib import Path

import pytest

from mcp_server.commerce import CommerceRepository
from mcp_server.database import Database
from mcp_server.repository import ProductRepository


def make_repos(tmp_path: Path):
    db = Database(tmp_path / "db.sqlite3")
    return ProductRepository(db), CommerceRepository(db)


def test_supplier_purchase_receive_updates_stock_and_cost(tmp_path: Path) -> None:
    products, commerce = make_repos(tmp_path)
    products.create_product(
        sku="SKU-1", name="Мышь", category="Периферия", price=1000,
        purchase_price=600, initial_stock=5, min_stock=1,
    )
    supplier = commerce.create_supplier(code="SUP-1", name="ООО Поставка")
    assert supplier["code"] == "SUP-1"

    order = commerce.create_purchase_order(
        order_no="PO-1", supplier_code="SUP-1",
        items=[{"sku": "SKU-1", "quantity": 4, "purchase_price": 550}],
        comment="Тест",
    )
    assert order["status"] == "ordered"
    assert order["total"] == 2200

    received = commerce.receive_purchase_order("PO-1")
    assert received["status"] == "received"
    item = products.get_product("SKU-1")
    assert item.stock == 9
    assert item.purchase_price == 550
    movement = products.movement_history(sku="SKU-1")[0]
    assert movement.movement_type == "receipt"
    assert movement.document_ref == "PO-1"


def test_sales_order_completion_and_profit_analytics(tmp_path: Path) -> None:
    products, commerce = make_repos(tmp_path)
    products.create_product(
        sku="SKU-1", name="Мышь", category="Периферия", price=1000,
        purchase_price=550, initial_stock=9, min_stock=1,
    )
    order = commerce.create_sales_order(
        order_no="SO-1", customer_name="Иван",
        items=[{"sku": "SKU-1", "quantity": 3}],
    )
    assert order["revenue"] == 3000
    assert order["cost"] == 1650
    assert products.get_product("SKU-1").stock == 9

    completed = commerce.complete_sales_order("SO-1")
    assert completed["status"] == "completed"
    assert completed["gross_profit"] == 1350
    assert products.get_product("SKU-1").stock == 6

    analytics = commerce.sales_analytics(days=30)
    assert analytics["orders_count"] == 1
    assert analytics["units_net"] == 3
    assert analytics["revenue"] == 3000
    assert analytics["cost"] == 1650
    assert analytics["gross_profit"] == 1350
    assert analytics["gross_margin_percent"] == 45.0


def test_manual_stock_movements_do_not_distort_commercial_analytics(tmp_path: Path) -> None:
    products, commerce = make_repos(tmp_path)
    products.create_product(
        sku="SKU-1", name="Мышь", category="Периферия", price=1000,
        purchase_price=600, initial_stock=10, min_stock=1,
    )
    products.stock_operation(sku="SKU-1", operation="sale", quantity=2, reason="Ручное списание")
    products.stock_operation(sku="SKU-1", operation="return", quantity=1, reason="Ручной возврат")

    data = commerce.sales_analytics(days=30)
    assert data["orders_count"] == 0
    assert data["units_net"] == 0
    assert data["revenue"] == 0
    assert data["cost"] == 0
    assert data["gross_profit"] == 0
    assert data["top_products"] == []


def test_old_manual_movements_do_not_mix_with_completed_order_kpis(tmp_path: Path) -> None:
    products, commerce = make_repos(tmp_path)
    products.create_product(
        sku="SKU-1", name="Мышь", category="Периферия", price=1000,
        purchase_price=600, initial_stock=20, min_stock=1,
    )
    products.stock_operation(sku="SKU-1", operation="sale", quantity=3, reason="Старое ручное списание")
    products.stock_operation(sku="SKU-1", operation="return", quantity=1, reason="Старый ручной возврат")
    commerce.create_sales_order(
        order_no="SO-REAL", customer_name="Клиент", items=[{"sku": "SKU-1", "quantity": 2}]
    )
    commerce.complete_sales_order("SO-REAL")

    data = commerce.sales_analytics(days=30)
    assert data["orders_count"] == 1
    assert data["units_net"] == 2
    assert data["revenue"] == 2000
    assert data["cost"] == 1200
    assert data["gross_profit"] == 800
    assert data["top_products"][0]["units"] == 2


def test_sales_order_is_atomic_when_stock_is_insufficient(tmp_path: Path) -> None:
    products, commerce = make_repos(tmp_path)
    products.create_product(
        sku="A", name="A", category="X", price=100, purchase_price=50, initial_stock=5, min_stock=0
    )
    products.create_product(
        sku="B", name="B", category="X", price=100, purchase_price=50, initial_stock=1, min_stock=0
    )
    commerce.create_sales_order(
        order_no="SO-X", customer_name="Клиент",
        items=[{"sku": "A", "quantity": 2}, {"sku": "B", "quantity": 2}],
    )
    with pytest.raises(ValueError, match="Недостаточно товара"):
        commerce.complete_sales_order("SO-X")
    assert products.get_product("A").stock == 5
    assert products.get_product("B").stock == 1
    assert commerce.get_sales_order("SO-X")["status"] == "new"


def test_dashboard_combines_inventory_orders_and_profit(tmp_path: Path) -> None:
    products, commerce = make_repos(tmp_path)
    products.create_product(
        sku="SKU-1", name="Мышь", category="Периферия", price=1000,
        purchase_price=600, initial_stock=10, min_stock=1,
    )
    commerce.create_supplier(code="SUP", name="Поставщик")
    commerce.create_purchase_order(
        order_no="PO", supplier_code="SUP", items=[{"sku": "SKU-1", "quantity": 2, "purchase_price": 500}]
    )
    commerce.create_sales_order(
        order_no="SO", customer_name="Клиент", items=[{"sku": "SKU-1", "quantity": 1}]
    )
    commerce.complete_sales_order("SO")
    data = commerce.dashboard(days=7)
    assert data["active_suppliers"] == 1
    assert data["open_purchase_orders"] == 1
    assert data["open_sales_orders"] == 0
    assert data["sales"]["gross_profit"] == 400


def test_v120_database_migrates_without_losing_products(tmp_path: Path) -> None:
    import sqlite3

    path = tmp_path / "v120.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku TEXT NOT NULL UNIQUE COLLATE NOCASE,
            name TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'Без категории',
            price_minor INTEGER NOT NULL,
            purchase_price_minor INTEGER NOT NULL DEFAULT 0,
            stock INTEGER NOT NULL DEFAULT 0,
            min_stock INTEGER NOT NULL DEFAULT 0,
            description TEXT NOT NULL DEFAULT '',
            supplier TEXT NOT NULL DEFAULT '',
            barcode TEXT NOT NULL DEFAULT '',
            unit TEXT NOT NULL DEFAULT 'шт.',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE stock_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            delta INTEGER NOT NULL,
            quantity_after INTEGER NOT NULL,
            movement_type TEXT NOT NULL DEFAULT 'adjustment',
            reason TEXT NOT NULL,
            document_ref TEXT NOT NULL DEFAULT '',
            comment TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        INSERT INTO products(
            sku,name,category,price_minor,purchase_price_minor,stock,min_stock,
            description,supplier,barcode,unit,is_active,created_at,updated_at
        ) VALUES ('OLD-1','Старый товар','Тест',100000,60000,7,2,'','','','шт.',1,
                  '2026-10-20T00:00:00+00:00','2026-10-20T00:00:00+00:00');
        """
    )
    conn.close()

    db = Database(path)
    products = ProductRepository(db)
    assert products.get_product("OLD-1").stock == 7
    with db.connect() as migrated:
        movement_cols = {row[1] for row in migrated.execute("PRAGMA table_info(stock_movements)")}
        tables = {row[0] for row in migrated.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"unit_price_minor", "unit_cost_minor"} <= movement_cols
    assert {"suppliers", "purchase_orders", "sales_orders"} <= tables
