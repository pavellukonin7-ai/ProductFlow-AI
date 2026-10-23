from telegram_bot.agent import InventoryAgent, WRITE_TOOLS


def test_write_tools_are_protected() -> None:
    assert {
        "create_product", "update_product", "adjust_stock", "stock_operation", "set_stock",
        "import_products", "create_supplier", "create_purchase_order", "receive_purchase_order",
        "create_sales_order", "complete_sales_order", "create_customer", "reserve_sales_order",
        "release_sales_reservation", "start_sales_processing", "ship_sales_order",
    } <= WRITE_TOOLS


def test_confirmation_text_for_stock_change() -> None:
    text = InventoryAgent._confirmation_text(
        "adjust_stock",
        {"sku": "SKU-1", "delta": -2, "reason": "Продажа"},
    )
    assert "подтверждение" in text.casefold()
    assert "SKU-1" in text
    assert "-2" in text
    assert "Продажа" in text


def test_chat_tool_conversion() -> None:
    tools = InventoryAgent._chat_tools([
        {
            "type": "function",
            "name": "inventory_summary",
            "description": "Сводка",
            "parameters": {"type": "object", "properties": {}},
        }
    ])
    assert tools[0]["function"]["name"] == "inventory_summary"
