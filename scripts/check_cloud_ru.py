from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
from dotenv import load_dotenv
from openai import AsyncOpenAI


async def main() -> None:
    load_dotenv()

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    base_url = os.getenv("OPENAI_BASE_URL", "").strip()
    model = os.getenv("OPENAI_MODEL", "").strip()
    proxy = os.getenv("OPENAI_PROXY", "").strip() or None

    if not api_key:
        raise RuntimeError("OPENAI_API_KEY не задан в .env")
    if not base_url:
        raise RuntimeError("OPENAI_BASE_URL не задан в .env")
    if not model:
        raise RuntimeError("OPENAI_MODEL не задан в .env")

    http_client = httpx.AsyncClient(proxy=proxy, timeout=90.0) if proxy else None
    kwargs: dict[str, Any] = {"api_key": api_key, "base_url": base_url}
    if http_client:
        kwargs["http_client"] = http_client

    client = AsyncOpenAI(**kwargs)
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Ответь одним словом: работает"}],
        )
        print("Cloud.ru OK:", response.choices[0].message.content)
    finally:
        await client.close()
        if http_client:
            await http_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
