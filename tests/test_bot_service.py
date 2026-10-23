import asyncio
from typing import Any

from telegram_bot.service import InventoryService


class FakeMCP:
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if name == "inventory_summary":
            return {
                "products_total": 2,
                "active_products": 2,
                "categories_total": 1,
                "units_in_stock": 7,
                "low_stock_products": 1,
                "inventory_value": 12500.0,
            }
        if name == "search_products":
            return [{
                "sku": "A-1", "name": "Товар", "price": 500.0, "stock": 4,
                "is_active": True,
            }]
        if name == "get_product":
            return {
                "sku": arguments["sku"], "name": "Товар", "category": "Тест",
                "price": 500.0, "stock": 2, "min_stock": 3,
                "description": "", "is_active": True,
            }
        if name == "adjust_stock":
            return {
                "sku": arguments["sku"], "name": "Товар", "price": 500.0,
                "stock": 2, "min_stock": 3, "is_active": True,
            }
        if name == "update_product":
            return {
                "sku": arguments["sku"], "name": arguments.get("name", "Товар"),
                "category": arguments.get("category", "Тест"),
                "price": arguments.get("price", 750.0), "stock": 2,
                "min_stock": arguments.get("min_stock", 3),
                "description": arguments.get("description", ""),
                "is_active": arguments.get("is_active", True),
            }
        raise AssertionError(name)


def test_summary_format() -> None:
    text = asyncio.run(InventoryService(FakeMCP()).summary())
    assert "Сводка склада" in text
    assert "12500.00 ₽" in text


def test_products_format() -> None:
    text = asyncio.run(InventoryService(FakeMCP()).products("товар"))
    assert "A-1" in text
    assert "остаток 4" in text


def test_stock_command_warns_about_low_stock() -> None:
    text = asyncio.run(InventoryService(FakeMCP()).adjust_stock("A-1 -2 Продажа"))
    assert "остаток" in text.casefold()
    assert "Низкий остаток" in text


def test_edit_product() -> None:
    text = asyncio.run(InventoryService(FakeMCP()).edit_product("A-1 | price | 750"))
    assert "обновлён" in text
    assert "750.00 ₽" in text


def test_archive_product() -> None:
    text = asyncio.run(InventoryService(FakeMCP()).set_active("A-1", False))
    assert "архивирован" in text
