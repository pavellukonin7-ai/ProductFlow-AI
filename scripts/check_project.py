from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncio
import socket
from urllib.parse import urlparse

import httpx
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from openai import AsyncOpenAI

from telegram_bot.config import load_settings
from telegram_bot.mcp_client import ProductMCPClient


def check_proxy(proxy: str | None) -> None:
    if not proxy:
        print("[OK] BOT_PROXY: не используется")
        return
    parsed = urlparse(proxy)
    host = parsed.hostname
    port = parsed.port
    if not host or not port:
        raise RuntimeError(f"Некорректный BOT_PROXY: {proxy}")
    with socket.create_connection((host, port), timeout=3):
        pass
    print(f"[OK] BOT_PROXY: {host}:{port}")


async def check_mcp() -> None:
    settings = load_settings()
    client = ProductMCPClient(settings.database_path)
    await client.start()
    try:
        tools = await client.list_openai_tools()
        summary = await client.call_tool("inventory_summary", {})
        print(f"[OK] MCP: {len(tools)} инструментов; товаров {summary['products_total']}")
    finally:
        await client.close()


async def check_telegram() -> None:
    settings = load_settings()
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN не задан")
    session = AiohttpSession(proxy=settings.bot_proxy) if settings.bot_proxy else AiohttpSession()
    bot = Bot(settings.bot_token, session=session)
    try:
        me = await bot.get_me()
        print(f"[OK] Telegram: @{me.username} (id={me.id})")
    finally:
        await bot.session.close()


async def check_ai() -> None:
    settings = load_settings()
    if not settings.openai_api_key:
        print("[SKIP] AI: OPENAI_API_KEY не задан")
        return
    kwargs = {"api_key": settings.openai_api_key}
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
    http_client = httpx.AsyncClient(proxy=settings.openai_proxy, timeout=90.0) if settings.openai_proxy else None
    if http_client:
        kwargs["http_client"] = http_client
    client = AsyncOpenAI(**kwargs)
    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "user", "content": "Ответь одним словом: работает"}],
        )
        text = (response.choices[0].message.content or "").strip()
        print(f"[OK] AI {settings.openai_model}: {text}")
    finally:
        await client.close()
        if http_client:
            await http_client.aclose()


async def main() -> None:
    settings = load_settings()
    print("ProductFlow AI preflight")
    print(f"[OK] DB: {settings.database_path}")
    check_proxy(settings.bot_proxy)
    await check_mcp()
    await check_telegram()
    await check_ai()
    print("[OK] Все проверки завершены")


if __name__ == "__main__":
    asyncio.run(main())
