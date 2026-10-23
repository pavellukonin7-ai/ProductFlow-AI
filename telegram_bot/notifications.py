from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from html import escape

from aiogram import Bot

from telegram_bot.service import InventoryService

logger = logging.getLogger(__name__)


async def notification_loop(
    *,
    bot: Bot,
    service: InventoryService,
    recipients: tuple[int, ...],
    interval_seconds: int = 300,
    daily_report_hour_utc: int = 6,
) -> None:
    """Send new low-stock alerts plus one daily dashboard to configured recipients."""
    if not recipients:
        logger.info("Notifications disabled: no recipients configured")
        return

    try:
        initial = await service.low_stock_data()
        previous_low = {str(item["sku"]).upper() for item in initial}
    except Exception:
        logger.exception("Failed to initialize low-stock notification state")
        previous_low = set()

    last_daily_date: str | None = None
    logger.info("Notifications enabled for %s recipient(s)", len(recipients))

    while True:
        try:
            low = await service.low_stock_data()
            current = {str(item["sku"]).upper() for item in low}
            new_skus = current - previous_low
            if new_skus:
                selected = [item for item in low if str(item["sku"]).upper() in new_skus]
                lines = ["<b>⚠️ ProductFlow: новый дефицит</b>"]
                for item in selected:
                    lines.append(
                        f"• <code>{escape(str(item['sku']))}</code> — {escape(str(item['name']))}: "
                        f"{item['stock']} / минимум {item['min_stock']} {escape(str(item.get('unit') or 'шт.'))}"
                    )
                text = "\n".join(lines)
                for chat_id in recipients:
                    try:
                        await bot.send_message(chat_id, text)
                    except Exception:
                        logger.exception("Failed to send low-stock alert to %s", chat_id)
            previous_low = current

            now = datetime.now(timezone.utc)
            day_key = now.date().isoformat()
            if now.hour == daily_report_hour_utc and last_daily_date != day_key:
                report = await service.dashboard(1)
                text = "<b>☀️ Ежедневный отчёт ProductFlow</b>\n\n" + report
                for chat_id in recipients:
                    try:
                        await bot.send_message(chat_id, text)
                    except Exception:
                        logger.exception("Failed to send daily report to %s", chat_id)
                last_daily_date = day_key
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Notification cycle failed")

        await asyncio.sleep(max(60, interval_seconds))
