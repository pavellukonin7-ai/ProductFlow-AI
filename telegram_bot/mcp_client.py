from __future__ import annotations

import json
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ProductMCPClient:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self._stack: AsyncExitStack | None = None
        self._client: Client | None = None

    async def start(self) -> None:
        if self._client is not None:
            return
        env = os.environ.copy()
        env.update({
            "PRODUCT_MCP_DB_PATH": str(self.database_path),
            "PYTHONPATH": str(PROJECT_ROOT),
        })
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(PROJECT_ROOT / "mcp_server" / "server.py")],
            env=env,
        )
        self._stack = AsyncExitStack()
        await self._stack.__aenter__()
        transport = stdio_client(params)
        self._client = await self._stack.enter_async_context(Client(transport))

    async def close(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._client = None

    def _require_client(self) -> Client:
        if self._client is None:
            raise RuntimeError("MCP-клиент не запущен")
        return self._client

    async def list_openai_tools(self) -> list[dict[str, Any]]:
        result = await self._require_client().list_tools()
        tools: list[dict[str, Any]] = []
        for tool in result.tools:
            tools.append(
                {
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description or tool.title or tool.name,
                    "parameters": tool.input_schema,
                    "strict": False,
                }
            )
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        result = await self._require_client().call_tool(name, arguments)
        if result.is_error:
            texts = [block.text for block in result.content if isinstance(block, TextContent)]
            raise RuntimeError("; ".join(texts) or f"Ошибка MCP-инструмента {name}")
        if result.structured_content is not None:
            data = result.structured_content
            if isinstance(data, dict) and set(data) == {"result"}:
                return data["result"]
            return data
        texts = [block.text for block in result.content if isinstance(block, TextContent)]
        if len(texts) == 1:
            try:
                return json.loads(texts[0])
            except json.JSONDecodeError:
                return texts[0]
        return texts
