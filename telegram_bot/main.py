from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from telegram_bot.access import AccessPolicy
from telegram_bot.agent import InventoryAgent
from telegram_bot.config import load_settings
from telegram_bot.handlers import create_router
from telegram_bot.mcp_client import ProductMCPClient
from telegram_bot.service import InventoryService
from telegram_bot.notifications import notification_loop


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = load_settings()
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN не задан в .env")

    mcp = ProductMCPClient(settings.database_path)
    await mcp.start()
    service = InventoryService(mcp)
    agent = None
    if settings.openai_api_key:
        agent = InventoryAgent(
            mcp=mcp,
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            base_url=settings.openai_base_url,
            proxy=settings.openai_proxy,
        )

    policy = AccessPolicy(
        admin_user_ids=settings.admin_user_ids,
        manager_user_ids=settings.manager_user_ids,
        viewer_user_ids=settings.viewer_user_ids,
        legacy_allowed_user_ids=settings.allowed_user_ids,
    )

    session = AiohttpSession(proxy=settings.bot_proxy) if settings.bot_proxy else AiohttpSession()
    bot = Bot(
        token=settings.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    dispatcher.include_router(create_router(service, agent, policy, settings.security_rate_limit_per_minute))

    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="dashboard", description="Dashboard бизнеса"),
            BotCommand(command="analytics", description="Продажи и прибыль"),
            BotCommand(command="customers", description="Клиенты / контрагенты"),
            BotCommand(command="availability", description="Доступный остаток с резервом"),
            BotCommand(command="suppliers", description="Поставщики"),
            BotCommand(command="purchases", description="Закупки"),
            BotCommand(command="sales", description="Заказы клиентов"),
            BotCommand(command="reserve", description="Зарезервировать заказ"),
            BotCommand(command="ship", description="Отгрузить заказ"),
            BotCommand(command="summary", description="Сводка склада"),
            BotCommand(command="products", description="Список и поиск товаров"),
            BotCommand(command="product", description="Карточка товара по SKU"),
            BotCommand(command="move", description="Складская операция"),
            BotCommand(command="low", description="Дефицитные позиции"),
            BotCommand(command="history", description="История движений"),
            BotCommand(command="warehouses", description="Список складов"),
            BotCommand(command="warehouse_stock", description="Остатки конкретного склада"),
            BotCommand(command="distribution", description="Распределение SKU по складам"),
            BotCommand(command="transfer", description="Перемещение между складами"),
            BotCommand(command="qr", description="QR-код товара"),
            BotCommand(command="barcode", description="Штрихкод товара"),
            BotCommand(command="label", description="Единая товарная этикетка"),
            BotCommand(command="audit", description="Журнал аудита (admin)"),
            BotCommand(command="export", description="Экспорт каталога в Excel"),
            BotCommand(command="import", description="Импорт Excel/CSV"),
            BotCommand(command="whoami", description="Мой ID и роль"),
            BotCommand(command="help", description="Справка"),
        ]
    )

    notification_task = None
    recipients = settings.notification_user_ids or settings.admin_user_ids
    if settings.notifications_enabled and recipients:
        notification_task = asyncio.create_task(
            notification_loop(
                bot=bot,
                service=service,
                recipients=recipients,
                interval_seconds=settings.notification_interval_seconds,
                daily_report_hour_utc=settings.daily_report_hour_utc,
            )
        )

    try:
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        if notification_task:
            notification_task.cancel()
            try:
                await notification_task
            except asyncio.CancelledError:
                pass
        if agent:
            await agent.close()
        await mcp.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
