from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncio

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession

from telegram_bot.config import load_settings


async def main() -> None:
    settings = load_settings()
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN не задан")
    session = AiohttpSession(proxy=settings.bot_proxy) if settings.bot_proxy else AiohttpSession()
    bot = Bot(settings.bot_token, session=session)
    try:
        me = await bot.get_me()
        print(f"Telegram OK: @{me.username} (id={me.id})")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
