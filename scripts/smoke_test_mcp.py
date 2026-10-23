from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncio
from typing import Any

from telegram_bot.config import load_settings
from telegram_bot.mcp_client import ProductMCPClient


def tool_name(tool: dict[str, Any]) -> str:
    if tool.get("name"):
        return str(tool["name"])
    function = tool.get("function")
    if isinstance(function, dict) and function.get("name"):
        return str(function["name"])
    return "<unknown>"


async def main() -> None:
    settings = load_settings()
    client = ProductMCPClient(settings.database_path)
    await client.start()
    try:
        tools = await client.list_openai_tools()
        print("MCP tools:", ", ".join(tool_name(tool) for tool in tools))
        print("Summary:", await client.call_tool("inventory_summary", {}))
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
