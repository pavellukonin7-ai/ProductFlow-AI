from __future__ import annotations

import os

import httpx
from dotenv import load_dotenv

from telegram_bot.config import PROJECT_ROOT


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    host = os.getenv("WEB_HOST", "127.0.0.1")
    port = int(os.getenv("WEB_PORT", "8090"))
    api_key = os.getenv("WEB_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("WEB_API_KEY не задан")
    connect_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    base = f"http://{connect_host}:{port}"
    with httpx.Client(timeout=10.0) as client:
        health = client.get(base + "/api/v1/health")
        health.raise_for_status()
        dashboard = client.get(
            base + "/api/v1/dashboard?days=30",
            headers={"Authorization": f"Bearer {api_key}", "X-ProductFlow-Client": "server-smoke"},
        )
        dashboard.raise_for_status()
        data = dashboard.json()
    print(
        "Web OK:",
        f"status={health.json().get('status')};",
        f"products={data.get('products_total')};",
        f"units={data.get('units_in_stock')};",
        f"revenue={data.get('sales', {}).get('revenue', data.get('revenue', 'n/a'))}",
    )


if __name__ == "__main__":
    main()
