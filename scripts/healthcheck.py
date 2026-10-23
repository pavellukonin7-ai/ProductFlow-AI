from __future__ import annotations

import asyncio

from telegram_bot.config import load_settings
from telegram_bot.mcp_client import ProductMCPClient


async def main() -> None:
    settings = load_settings()
    client = ProductMCPClient(settings.database_path)
    await client.start()
    try:
        tools = await client.list_openai_tools()
        summary = await client.call_tool("inventory_summary", {})
        required = {
            "get_product", "search_products", "stock_operation", "inventory_summary",
            "create_supplier", "create_purchase_order", "receive_purchase_order",
            "create_sales_order", "complete_sales_order", "sales_analytics", "business_dashboard",
            "create_warehouse", "list_warehouses", "warehouse_stock",
            "product_warehouse_distribution", "transfer_between_warehouses",
            "warehouse_movements", "record_audit_event", "list_audit_events",
            "create_customer", "list_customers", "get_customer", "customer_order_history",
            "product_availability", "reserve_sales_order", "release_sales_reservation",
            "start_sales_processing", "ship_sales_order",
        }
        names = {tool["name"] for tool in tools}
        missing = required - names
        if missing:
            raise RuntimeError(f"MCP не содержит обязательные инструменты: {sorted(missing)}")
        dashboard = await client.call_tool("business_dashboard", {"days": 7})
        warehouses = await client.call_tool("list_warehouses", {"active_only": True, "limit": 100})
        if not any(str(w.get("code", "")).upper() == "MAIN" for w in warehouses):
            raise RuntimeError("Основной склад MAIN не создан")
        print(
            f"Health OK: MCP={len(tools)} tools; products={summary['products_total']}; "
            f"units={summary['units_in_stock']}; warehouses={len(warehouses)}; "
            f"suppliers={dashboard['active_suppliers']}; sales_7d={dashboard['sales']['revenue']:.2f}"
        )
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
