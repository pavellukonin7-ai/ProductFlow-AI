from __future__ import annotations

from pathlib import Path

import pytest

from mcp_server.audit import AuditRepository
from mcp_server.commerce import CommerceRepository
from mcp_server.database import Database
from mcp_server.repository import ProductRepository
from mcp_server.warehouse import WarehouseRepository
from telegram_bot.access import AccessPolicy
from telegram_bot.codes import make_barcode_png, make_qr_png
from telegram_bot.formatting import ai_text_to_telegram_html


def build(tmp_path: Path):
    db = Database(tmp_path / "v140.sqlite3")
    products = ProductRepository(db)
    warehouses = WarehouseRepository(db)
    audit = AuditRepository(db)
    return db, products, warehouses, audit


def test_default_main_warehouse_receives_legacy_stock(tmp_path: Path) -> None:
    _, products, warehouses, _ = build(tmp_path)
    products.create_product(
        sku="SKU-1", name="Товар", category="Тест", price=1000,
        initial_stock=8, min_stock=2,
    )
    rows = warehouses.product_distribution("SKU-1")
    assert rows[0]["warehouse_code"] == "MAIN"
    assert rows[0]["quantity"] == 8
    assert rows[0]["total_stock"] == 8


def test_transfer_between_warehouses_preserves_total_stock(tmp_path: Path) -> None:
    _, products, warehouses, _ = build(tmp_path)
    products.create_product(
        sku="SKU-1", name="Товар", category="Тест", price=1000,
        initial_stock=10, min_stock=2,
    )
    warehouses.create_warehouse(code="SPB", name="Склад СПб", location="Санкт-Петербург")
    result = warehouses.transfer(
        sku="SKU-1", quantity=4, from_warehouse="MAIN", to_warehouse="SPB",
        document_ref="MOVE-1", actor_user_id="1000000001",
    )
    assert result["total_stock"] == 10
    dist = {row["warehouse_code"]: row["quantity"] for row in warehouses.product_distribution("SKU-1")}
    assert dist == {"MAIN": 6, "SPB": 4}
    assert products.get_product("SKU-1").stock == 10
    movement = warehouses.movements(limit=1)[0]
    assert movement["document_ref"] == "MOVE-1"
    assert movement["actor_user_id"] == "1000000001"


def test_transfer_rejects_insufficient_source_stock(tmp_path: Path) -> None:
    _, products, warehouses, _ = build(tmp_path)
    products.create_product(
        sku="SKU-1", name="Товар", category="Тест", price=1000,
        initial_stock=2, min_stock=0,
    )
    warehouses.create_warehouse(code="SPB", name="Склад СПб")
    with pytest.raises(ValueError, match="Недостаточно товара"):
        warehouses.transfer(
            sku="SKU-1", quantity=3, from_warehouse="MAIN", to_warehouse="SPB"
        )


def test_audit_log_roundtrip(tmp_path: Path) -> None:
    _, _, _, audit = build(tmp_path)
    created = audit.record(
        actor_user_id="1000000001", actor_role="admin", action="warehouse.transfer",
        entity_type="product", entity_id="SKU-1", details={"qty": 2}, success=True,
    )
    assert created["id"] > 0
    rows = audit.list(actor_user_id="1000000001", limit=10)
    assert len(rows) == 1
    assert rows[0]["action"] == "warehouse.transfer"
    assert rows[0]["details"] == {"qty": 2}
    assert rows[0]["success"] is True


def test_qr_and_barcode_png_generation() -> None:
    product = {"sku": "SKU-001", "name": "Мышь", "barcode": "4601234567890"}
    qr = make_qr_png(product)
    barcode = make_barcode_png(product)
    assert qr.startswith(b"\x89PNG\r\n\x1a\n")
    assert barcode.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(qr) > 500
    assert len(barcode) > 500


def test_ai_formatting_removes_raw_markdown_and_space_entity() -> None:
    rendered = ai_text_to_telegram_html("**Заголовок**\n&#x20;• `SKU-001`")
    assert "**" not in rendered
    assert "&#x20;" not in rendered
    assert "<b>Заголовок</b>" in rendered
    assert "<code>SKU-001</code>" in rendered


def test_purchase_and_sale_use_main_warehouse(tmp_path: Path) -> None:
    from mcp_server.commerce import CommerceRepository

    _, products, warehouses, _ = build(tmp_path)
    commerce = CommerceRepository(products.db)
    products.create_product(
        sku="SKU-1", name="Товар", category="Тест", price=200, purchase_price=100,
        initial_stock=5, min_stock=1,
    )
    commerce.create_supplier(code="SUP-1", name="Поставщик")
    commerce.create_purchase_order(
        order_no="PO-1", supplier_code="SUP-1",
        items=[{"sku": "SKU-1", "quantity": 3, "purchase_price": 90}],
    )
    commerce.receive_purchase_order("PO-1")
    main = next(item for item in warehouses.product_distribution("SKU-1") if item["warehouse_code"] == "MAIN")
    assert main["quantity"] == 8
    assert products.get_product("SKU-1").stock == 8

    commerce.create_sales_order(
        order_no="SO-1", customer_name="Клиент",
        items=[{"sku": "SKU-1", "quantity": 2}],
    )
    commerce.complete_sales_order("SO-1")
    main = next(item for item in warehouses.product_distribution("SKU-1") if item["warehouse_code"] == "MAIN")
    assert main["quantity"] == 6
    assert products.get_product("SKU-1").stock == 6


def test_role_permissions_include_multiwarehouse_write_tools() -> None:
    from telegram_bot.access import AccessPolicy

    policy = AccessPolicy(admin_user_ids=(1,), manager_user_ids=(2,), viewer_user_ids=(3,))
    assert "create_warehouse" in policy.allowed_ai_write_tools(1)
    assert "transfer_between_warehouses" in policy.allowed_ai_write_tools(1)
    assert "transfer_between_warehouses" in policy.allowed_ai_write_tools(2)
    assert "create_warehouse" not in policy.allowed_ai_write_tools(2)
    assert policy.allowed_ai_write_tools(3) == set()
    assert policy.role_for(999) is None


def test_regular_stock_adjustment_keeps_main_warehouse_in_sync(tmp_path: Path) -> None:
    db, products, warehouses, _ = build(tmp_path)
    products.create_product(
        sku="SYNC-1", name="Синхронизация", category="Тест", price=100,
        initial_stock=5, min_stock=0,
    )
    products.adjust_stock(sku="SYNC-1", delta=3, reason="Приход")
    dist = {row["warehouse_code"]: row["quantity"] for row in warehouses.product_distribution("SYNC-1")}
    assert dist["MAIN"] == 8
    products.adjust_stock(sku="SYNC-1", delta=-2, reason="Продажа")
    dist = {row["warehouse_code"]: row["quantity"] for row in warehouses.product_distribution("SYNC-1")}
    assert dist["MAIN"] == 6
