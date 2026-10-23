from __future__ import annotations

import os
import sys
from pathlib import Path

# Позволяет запускать файл напрямую абсолютным путём из MCP-клиента.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.server import MCPServer

from mcp_server.database import Database
from mcp_server.repository import ProductRepository
from mcp_server.tools import register_tools


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "products.sqlite3"


def create_server(db_path: str | Path | None = None) -> MCPServer:
    resolved_db_path = Path(
        db_path or os.getenv("PRODUCT_MCP_DB_PATH", str(DEFAULT_DB_PATH))
    ).expanduser().resolve()
    repository = ProductRepository(Database(resolved_db_path))
    server = MCPServer(
        "product-mcp",
        instructions=(
            "Сервис каталога, CRM, закупок, продаж, резервов и мультисклада. Используй поиск перед изменением данных, "
            "не допускай отрицательных остатков и двойного резервирования, MAIN считай основным складом и сохраняй причину движения."
        ),
    )
    register_tools(server, repository)
    return server


mcp = create_server()


if __name__ == "__main__":
    mcp.run()
