from __future__ import annotations

import asyncio

from telegram_bot.config import load_settings
from telegram_bot.mcp_client import ProductMCPClient


async def main() -> None:
    settings = load_settings()
    client = ProductMCPClient(settings.database_path)
    await client.start()
    try:
        dashboard = await client.call_tool("business_dashboard", {"days": 7})
        analytics = await client.call_tool("sales_analytics", {"days": 30})
        suppliers = await client.call_tool("list_suppliers", {"active_only": True, "limit": 10})
        customers = await client.call_tool("list_customers", {"query": "", "active_only": True, "limit": 10})
        purchases = await client.call_tool("list_purchase_orders", {"status": None, "limit": 10})
        sales = await client.call_tool("list_sales_orders", {"status": None, "limit": 10})
        print(
            "Business OK: "
            f"suppliers={len(suppliers)}; customers={len(customers)}; purchases={len(purchases)}; sales={len(sales)}; "
            f"revenue_30d={analytics['revenue']:.2f}; low={dashboard['low_stock_products']}"
        )
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
