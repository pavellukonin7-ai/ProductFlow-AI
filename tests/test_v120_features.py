from __future__ import annotations

import sqlite3
from pathlib import Path

from mcp_server.database import Database
from mcp_server.repository import ProductRepository
from telegram_bot.access import AccessPolicy
from telegram_bot.formatting import ai_text_to_telegram_html
from telegram_bot.spreadsheet import export_xlsx, parse_xlsx


def test_extended_product_and_stock_operation(tmp_path: Path) -> None:
    repo = ProductRepository(Database(tmp_path / "db.sqlite3"))
    item = repo.create_product(
        sku="SKU-X",
        name="Товар X",
        category="Тест",
        price=2500,
        purchase_price=1400,
        initial_stock=10,
        min_stock=2,
        supplier="Поставщик",
        barcode="460000000001",
        unit="шт.",
    )
    assert item.purchase_price == 1400
    assert item.supplier == "Поставщик"
    assert item.barcode == "460000000001"

    after = repo.stock_operation(
        sku="SKU-X",
        operation="sale",
        quantity=3,
        reason="Продажа",
        document_ref="ORD-1",
        comment="Тест",
    )
    assert after.stock == 7
    movement = repo.movement_history(sku="SKU-X")[0]
    assert movement.movement_type == "sale"
    assert movement.document_ref == "ORD-1"
    assert movement.comment == "Тест"


def test_summary_purchase_value(tmp_path: Path) -> None:
    repo = ProductRepository(Database(tmp_path / "db.sqlite3"))
    repo.create_product(
        sku="M-1", name="Мышь", category="Периферия", price=1000,
        purchase_price=600, initial_stock=5, min_stock=1,
    )
    summary = repo.inventory_summary()
    assert summary.inventory_value == 5000
    assert summary.purchase_value == 3000
    assert summary.potential_margin == 2000


def test_v11_schema_is_migrated(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku TEXT NOT NULL UNIQUE COLLATE NOCASE,
            name TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'Без категории',
            price_minor INTEGER NOT NULL,
            stock INTEGER NOT NULL DEFAULT 0,
            min_stock INTEGER NOT NULL DEFAULT 0,
            description TEXT NOT NULL DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE stock_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            delta INTEGER NOT NULL,
            quantity_after INTEGER NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.close()
    db = Database(path)
    with db.connect() as migrated:
        product_cols = {row[1] for row in migrated.execute("PRAGMA table_info(products)")}
        movement_cols = {row[1] for row in migrated.execute("PRAGMA table_info(stock_movements)")}
    assert {"purchase_price_minor", "supplier", "barcode", "unit"} <= product_cols
    assert {"movement_type", "document_ref", "comment"} <= movement_cols


def test_roles_and_ai_permissions() -> None:
    policy = AccessPolicy(admin_user_ids=(1,), manager_user_ids=(2,), viewer_user_ids=(3,))
    assert policy.role_for(1) == "admin"
    assert policy.can(2, "manager")
    assert not policy.can(2, "admin")
    assert policy.allowed_ai_write_tools(3) == set()
    assert "stock_operation" in policy.allowed_ai_write_tools(2)
    assert "create_product" in policy.allowed_ai_write_tools(1)


def test_excel_roundtrip() -> None:
    rows = [{
        "sku": "X-1", "name": "Кабель", "category": "Аксессуары",
        "price": 900.0, "purchase_price": 500.0, "stock": 4, "min_stock": 1,
        "unit": "шт.", "supplier": "ООО Тест", "barcode": "123456789",
        "description": "USB-C", "is_active": True,
    }]
    data = export_xlsx(rows)
    parsed = parse_xlsx(data)
    assert parsed[0]["sku"] == "X-1"
    assert parsed[0]["purchase_price"] == 500.0
    assert parsed[0]["supplier"] == "ООО Тест"


def test_ai_markdown_table_is_made_readable() -> None:
    text = "| SKU | Название |\n|---|---|\n| A-1 | **Мышь** |"
    rendered = ai_text_to_telegram_html(text)
    assert "|---|" not in rendered
    assert "<b>SKU:</b> A-1" in rendered
    assert "**" not in rendered
