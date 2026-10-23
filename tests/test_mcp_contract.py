from pathlib import Path

import pytest

mcp_module = pytest.importorskip("mcp")
from mcp import Client

from mcp_server.server import create_server


@pytest.mark.anyio
async def test_mcp_tools_are_callable(tmp_path: Path) -> None:
    server = create_server(tmp_path / "mcp.sqlite3")
    async with Client(server, raise_exceptions=True) as client:
        tools = await client.list_tools()
        names = {tool.name for tool in tools.tools}
        assert {
            "create_product", "inventory_summary", "adjust_stock", "create_supplier",
            "create_purchase_order", "create_sales_order", "sales_analytics", "business_dashboard",
            "create_customer", "list_customers", "get_customer", "customer_order_history",
            "product_availability", "reserve_sales_order", "release_sales_reservation",
            "start_sales_processing", "ship_sales_order",
        } <= names
        created = await client.call_tool(
            "create_product",
            {
                "sku": "T-1", "name": "Тест", "category": "QA",
                "price": 100, "initial_stock": 2, "min_stock": 1,
            },
        )
        assert created.structured_content["sku"] == "T-1"
