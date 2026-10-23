from __future__ import annotations

import io
import logging
import time
from collections import defaultdict, deque

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from telegram_bot.access import AccessPolicy
from telegram_bot.agent import InventoryAgent
from telegram_bot.formatting import ai_text_to_telegram_html
from telegram_bot.codes import make_qr_png, make_barcode_png, make_label_png
from telegram_bot.keyboards import (
    BTN_ADD,
    BTN_AI,
    BTN_EDIT,
    BTN_EXPORT,
    BTN_HISTORY,
    BTN_IMPORT,
    BTN_LOW,
    BTN_MOVEMENT,
    BTN_PRODUCTS,
    BTN_SETTINGS,
    BTN_SUMMARY,
    BTN_DASHBOARD,
    BTN_SUPPLIERS,
    BTN_PURCHASES,
    BTN_SALES,
    BTN_ANALYTICS,
    BTN_WAREHOUSES,
    BTN_CODES,
    BTN_AUDIT,
    BTN_CUSTOMERS,
    confirmation_keyboard,
    import_confirmation_keyboard,
    main_menu,
    product_actions_keyboard,
)
from telegram_bot.service import InventoryService
from telegram_bot.spreadsheet import export_csv, export_xlsx, parse_catalog_file
from telegram_bot.states import (
    AddProductState, EditProductState, ImportCatalogState, MovementState, ProductCodeState
)

logger = logging.getLogger(__name__)

HELP = """<b>ProductFlow AI</b> — товары, склад, закупки, продажи и MCP-ассистент.

<b>Бизнес</b>
/dashboard [дни] — бизнес-сводка
/analytics [дни] — выручка, себестоимость, прибыль и маржа
/customers [поиск] — клиенты
/customer CODE — карточка клиента
/availability SKU — физический остаток, резерв и доступно
/suppliers — поставщики
/purchases [status] — закупки
/sales [status] — заказы клиентов

<b>Просмотр склада</b>
/summary — сводка склада
/products [поиск] — товары
/product SKU — карточка товара
/low — дефицит
/history [SKU] — история движений
/warehouses — склады
/warehouse_stock [CODE] — остатки склада
/distribution SKU — распределение товара
/qr SKU · /barcode SKU · /label SKU — коды товара
/export — экспорт XLSX
/export_csv — экспорт CSV

<b>Склад (manager+)</b>
/move operation SKU quantity | причина | документ | комментарий
/receive НОМЕР_ЗАКУПКИ — принять закупку
/reserve НОМЕР_ЗАКАЗА — зарезервировать товар
/release_reserve НОМЕР_ЗАКАЗА — снять резерв до отгрузки
/process_sale НОМЕР_ЗАКАЗА — передать заказ в обработку
/ship НОМЕР_ЗАКАЗА | SKU:кол-во, ... — частичная/полная отгрузка
/complete_sale НОМЕР_ЗАКАЗА — завершить продажу и списать товар
/transfer SKU КОЛ-ВО FROM TO | причина | документ — перемещение между складами
/warehouse_history — история перемещений

<b>Бизнес-операции (admin)</b>
/supplier CODE | Название | Контакт | Телефон | Email | Комментарий
/purchase НОМЕР | ПОСТАВЩИК | SKU:кол-во:цена, ... | комментарий
/customer_create CODE | Название | Контакт | Телефон | Email | Адрес | Комментарий
/sale_order НОМЕР | КЛИЕНТ | SKU:кол-во[:цена], ... | комментарий

<b>Каталог (admin)</b>
/add SKU | Название | Категория | Цена | Остаток | Минимум
/edit SKU | поле | значение
/archive SKU · /restore SKU
/import — импорт XLSX/CSV
/warehouse CODE | Название | Локация — создать склад
/audit [лимит] — журнал аудита

/whoami — ваша роль

Можно писать обычным русским языком. AI-записи требуют подтверждения.
"""


def create_router(
    service: InventoryService,
    agent: InventoryAgent | None,
    policy: AccessPolicy,
    rate_limit_per_minute: int = 60,
) -> Router:
    router = Router()
    rate_events: dict[int, deque[float]] = defaultdict(deque)

    def user_id(message: Message) -> int | None:
        return message.from_user.id if message.from_user else None

    def role_for_message(message: Message) -> str | None:
        return policy.role_for(user_id(message))

    async def guard(message: Message, minimum_role: str = "viewer") -> bool:
        uid = user_id(message)
        if uid is not None:
            now = time.monotonic()
            events = rate_events[uid]
            while events and now - events[0] > 60:
                events.popleft()
            if len(events) >= rate_limit_per_minute:
                await message.answer("Слишком много запросов. Повторите через минуту.")
                return False
            events.append(now)
        if policy.can(uid, minimum_role):
            return True
        role = role_for_message(message)
        if role is None:
            await message.answer("Доступ к боту ограничен.")
        else:
            await message.answer(f"Недостаточно прав. Ваша роль: {role}.")
        return False

    async def guard_callback(callback: CallbackQuery, minimum_role: str = "viewer") -> bool:
        uid = callback.from_user.id if callback.from_user else None
        if policy.can(uid, minimum_role):
            return True
        await callback.answer("Недостаточно прав для операции.", show_alert=True)
        return False

    async def _audit(message: Message, action: str, *, success: bool = True, details: dict | None = None) -> None:
        try:
            await service.audit_event(
                actor_user_id=user_id(message) or "",
                actor_role=role_for_message(message) or "",
                action=action,
                details=details or {},
                success=success,
            )
        except Exception:
            logger.exception("Audit write failed")

    async def safe(
        message: Message, operation, minimum_role: str = "viewer",
        audit_action: str | None = None, **answer_kwargs
    ) -> None:
        if not await guard(message, minimum_role):
            return
        try:
            result = await operation()
            await message.answer(result, **answer_kwargs)
            if audit_action:
                await _audit(message, audit_action, details={"request": (message.text or "")[:1000]})
        except Exception as exc:
            logger.exception("Bot operation failed")
            if audit_action:
                await _audit(
                    message, audit_action, success=False,
                    details={"request": (message.text or "")[:1000], "error": str(exc)},
                )
            await message.answer(f"Ошибка: {exc}", parse_mode=None)

    async def safe_callback(
        callback: CallbackQuery, operation, minimum_role: str = "viewer", audit_action: str | None = None
    ) -> None:
        if not await guard_callback(callback, minimum_role) or callback.message is None:
            return
        try:
            await callback.answer()
            result = await operation()
            await callback.message.answer(result)
            if audit_action:
                try:
                    await service.audit_event(
                        actor_user_id=callback.from_user.id,
                        actor_role=policy.role_for(callback.from_user.id) or "",
                        action=audit_action,
                        details={"callback": callback.data or ""},
                    )
                except Exception:
                    logger.exception("Audit callback write failed")
        except Exception as exc:
            logger.exception("Callback operation failed")
            await callback.message.answer(f"Ошибка: {exc}", parse_mode=None)

    @router.message(Command("start", "help"))
    async def start(message: Message, state: FSMContext) -> None:
        if not await guard(message):
            return
        await state.clear()
        role = role_for_message(message) or "viewer"
        await message.answer(HELP, reply_markup=main_menu(role))

    @router.message(Command("whoami"))
    async def whoami(message: Message) -> None:
        if not await guard(message):
            return
        role = role_for_message(message) or "нет доступа"
        uid = user_id(message)
        await message.answer(f"Ваш Telegram ID: <code>{uid}</code>\nРоль: <b>{role}</b>")

    @router.message(Command("summary"))
    @router.message(F.text == BTN_SUMMARY)
    async def summary(message: Message) -> None:
        await safe(message, service.summary)

    @router.message(Command("dashboard"))
    async def dashboard_command(message: Message, command: CommandObject) -> None:
        try:
            days = int((command.args or "7").strip())
        except ValueError:
            await message.answer("Формат: /dashboard [дни]")
            return
        await safe(message, lambda: service.dashboard(days))

    @router.message(F.text == BTN_DASHBOARD)
    async def dashboard_button(message: Message) -> None:
        await safe(message, lambda: service.dashboard(7))

    @router.message(Command("analytics"))
    async def analytics_command(message: Message, command: CommandObject) -> None:
        try:
            days = int((command.args or "30").strip())
        except ValueError:
            await message.answer("Формат: /analytics [дни]")
            return
        await safe(message, lambda: service.analytics(days))

    @router.message(F.text == BTN_ANALYTICS)
    async def analytics_button(message: Message) -> None:
        await safe(message, lambda: service.analytics(30))

    @router.message(Command("customers"))
    @router.message(F.text == BTN_CUSTOMERS)
    async def customers_command(message: Message, command: CommandObject | None = None) -> None:
        query = (command.args or "").strip() if command is not None else ""
        await safe(message, lambda: service.customers(query))

    @router.message(Command("customer"))
    async def customer_command(message: Message, command: CommandObject) -> None:
        if not command.args:
            await message.answer("Формат: /customer CODE")
            return
        await safe(message, lambda: service.customer_card(command.args.strip()))

    @router.message(Command("customer_create"))
    async def customer_create_command(message: Message, command: CommandObject) -> None:
        await safe(message, lambda: service.add_customer(command.args or ""), minimum_role="admin", audit_action="customer.create")

    @router.message(Command("availability"))
    async def availability_command(message: Message, command: CommandObject) -> None:
        if not command.args:
            await message.answer("Формат: /availability SKU")
            return
        await safe(message, lambda: service.availability(command.args.strip()))

    @router.message(Command("suppliers"))
    @router.message(F.text == BTN_SUPPLIERS)
    async def suppliers(message: Message) -> None:
        await safe(message, service.suppliers)

    @router.message(Command("supplier"))
    async def supplier_create(message: Message, command: CommandObject) -> None:
        await safe(message, lambda: service.add_supplier(command.args or ""), minimum_role="admin", audit_action="supplier.create")

    @router.message(Command("purchases"))
    async def purchases_command(message: Message, command: CommandObject) -> None:
        await safe(message, lambda: service.purchases((command.args or "").strip()))

    @router.message(F.text == BTN_PURCHASES)
    async def purchases_button(message: Message) -> None:
        await safe(message, service.purchases)

    @router.message(Command("purchase"))
    async def purchase_create(message: Message, command: CommandObject) -> None:
        await safe(message, lambda: service.create_purchase(command.args or ""), minimum_role="admin", audit_action="purchase.create")

    @router.message(Command("receive"))
    async def purchase_receive(message: Message, command: CommandObject) -> None:
        if not command.args:
            await message.answer("Формат: /receive НОМЕР_ЗАКУПКИ")
            return
        await safe(message, lambda: service.receive_purchase(command.args.strip()), minimum_role="manager", audit_action="purchase.receive")

    @router.message(Command("sales"))
    async def sales_command(message: Message, command: CommandObject) -> None:
        await safe(message, lambda: service.sales_orders((command.args or "").strip()))

    @router.message(F.text == BTN_SALES)
    async def sales_button(message: Message) -> None:
        await safe(message, service.sales_orders)

    @router.message(Command("sale_order"))
    async def sale_order_create(message: Message, command: CommandObject) -> None:
        await safe(message, lambda: service.create_sale_order(command.args or ""), minimum_role="admin", audit_action="sale.create")

    @router.message(Command("reserve"))
    async def reserve_sale_command(message: Message, command: CommandObject) -> None:
        if not command.args:
            await message.answer("Формат: /reserve НОМЕР_ЗАКАЗА")
            return
        await safe(message, lambda: service.reserve_sale(command.args.strip()), minimum_role="manager", audit_action="sale.reserve")

    @router.message(Command("release_reserve"))
    async def release_reserve_command(message: Message, command: CommandObject) -> None:
        if not command.args:
            await message.answer("Формат: /release_reserve НОМЕР_ЗАКАЗА")
            return
        await safe(message, lambda: service.release_sale(command.args.strip()), minimum_role="manager", audit_action="sale.release_reserve")

    @router.message(Command("process_sale"))
    async def process_sale_command(message: Message, command: CommandObject) -> None:
        if not command.args:
            await message.answer("Формат: /process_sale НОМЕР_ЗАКАЗА")
            return
        await safe(message, lambda: service.process_sale(command.args.strip()), minimum_role="manager", audit_action="sale.processing")

    @router.message(Command("ship"))
    async def ship_sale_command(message: Message, command: CommandObject) -> None:
        if not command.args:
            await message.answer("Формат: /ship НОМЕР_ЗАКАЗА | SKU:кол-во, ... (позиции можно не указывать)")
            return
        await safe(message, lambda: service.ship_sale(command.args), minimum_role="manager", audit_action="sale.ship")

    @router.message(Command("complete_sale"))
    async def sale_order_complete(message: Message, command: CommandObject) -> None:
        if not command.args:
            await message.answer("Формат: /complete_sale НОМЕР_ЗАКАЗА")
            return
        await safe(message, lambda: service.complete_sale(command.args.strip()), minimum_role="manager", audit_action="sale.complete")

    @router.message(Command("warehouses"))
    @router.message(F.text == BTN_WAREHOUSES)
    async def warehouses(message: Message) -> None:
        await safe(message, service.warehouses)

    @router.message(Command("warehouse"))
    async def warehouse_create(message: Message, command: CommandObject) -> None:
        await safe(
            message, lambda: service.add_warehouse(command.args or ""),
            minimum_role="admin", audit_action="warehouse.create",
        )

    @router.message(Command("warehouse_stock"))
    async def warehouse_stock(message: Message, command: CommandObject) -> None:
        raw = (command.args or "MAIN").strip()
        parts = raw.split(maxsplit=1)
        code = parts[0] if parts else "MAIN"
        query = parts[1] if len(parts) > 1 else ""
        await safe(message, lambda: service.warehouse_stock(code, query))

    @router.message(Command("distribution"))
    async def distribution(message: Message, command: CommandObject) -> None:
        if not command.args:
            await message.answer("Формат: /distribution SKU")
            return
        await safe(message, lambda: service.product_distribution(command.args.strip()))

    @router.message(Command("transfer"))
    async def transfer(message: Message, command: CommandObject) -> None:
        await safe(
            message,
            lambda: service.transfer(command.args or "", actor_user_id=str(user_id(message) or "")),
            minimum_role="manager",
            audit_action="warehouse.transfer",
        )

    @router.message(Command("warehouse_history"))
    async def warehouse_history(message: Message) -> None:
        await safe(message, service.warehouse_history)

    @router.message(Command("audit"))
    async def audit_log_command(message: Message, command: CommandObject) -> None:
        raw = command.args or "30"
        try:
            limit = int(raw.strip())
        except ValueError:
            await message.answer("Формат: /audit [лимит]")
            return
        await safe(message, lambda: service.audit_log(limit), minimum_role="admin")

    @router.message(F.text == BTN_AUDIT)
    async def audit_log_button(message: Message) -> None:
        await safe(message, lambda: service.audit_log(30), minimum_role="admin")

    async def _send_product_codes(message: Message, sku: str, mode: str = "both") -> None:
        if not await guard(message):
            return
        try:
            item = await service.product_data(sku)
            if mode == "label":
                await message.answer_photo(
                    BufferedInputFile(make_label_png(item), filename=f"{item['sku']}-label.png"),
                    caption=f"Этикетка товара <code>{item['sku']}</code> — {item['name']}",
                )
            else:
                if mode in {"qr", "both"}:
                    await message.answer_photo(
                        BufferedInputFile(make_qr_png(item), filename=f"{item['sku']}-qr.png"),
                        caption=f"QR-код товара <code>{item['sku']}</code> — {item['name']}",
                    )
                if mode in {"barcode", "both"}:
                    await message.answer_photo(
                        BufferedInputFile(make_barcode_png(item), filename=f"{item['sku']}-barcode.png"),
                        caption=f"Code128: <code>{item.get('barcode') or item['sku']}</code>",
                    )
        except Exception as exc:
            logger.exception("Product code generation failed")
            await message.answer(f"Ошибка генерации кода: {exc}", parse_mode=None)

    @router.message(Command("qr"))
    async def qr_command(message: Message, command: CommandObject) -> None:
        if not command.args:
            await message.answer("Формат: /qr SKU")
            return
        await _send_product_codes(message, command.args.strip(), "qr")

    @router.message(Command("barcode"))
    async def barcode_command(message: Message, command: CommandObject) -> None:
        if not command.args:
            await message.answer("Формат: /barcode SKU")
            return
        await _send_product_codes(message, command.args.strip(), "barcode")

    @router.message(Command("label"))
    async def label_command(message: Message, command: CommandObject) -> None:
        if not command.args:
            await message.answer("Формат: /label SKU")
            return
        await _send_product_codes(message, command.args.strip(), "label")

    @router.callback_query(F.data.startswith("product:qr:"))
    async def product_qr_callback(callback: CallbackQuery) -> None:
        if not await guard_callback(callback) or callback.message is None:
            return
        sku = (callback.data or "").split(":", 2)[2]
        await callback.answer()
        await _send_product_codes(callback.message, sku, "qr")

    @router.callback_query(F.data.startswith("product:barcode:"))
    async def product_barcode_callback(callback: CallbackQuery) -> None:
        if not await guard_callback(callback) or callback.message is None:
            return
        sku = (callback.data or "").split(":", 2)[2]
        await callback.answer()
        await _send_product_codes(callback.message, sku, "barcode")

    @router.message(F.text == BTN_CODES)
    async def code_button(message: Message, state: FSMContext) -> None:
        if not await guard(message):
            return
        await state.set_state(ProductCodeState.waiting_sku)
        await message.answer("Введите SKU товара. Я пришлю QR-код и штрихкод Code128.")

    @router.message(ProductCodeState.waiting_sku, F.text)
    async def code_payload(message: Message, state: FSMContext) -> None:
        if not await guard(message):
            await state.clear()
            return
        sku = (message.text or "").strip()
        await state.clear()
        await _send_product_codes(message, sku, "both")

    @router.message(Command("products"))
    async def products_command(message: Message, command: CommandObject) -> None:
        await safe(message, lambda: service.products(command.args or ""))

    @router.message(F.text == BTN_PRODUCTS)
    async def products_button(message: Message) -> None:
        await safe(message, service.products)

    @router.message(Command("product"))
    async def product(message: Message, command: CommandObject) -> None:
        if not command.args:
            await message.answer("Формат: /product SKU")
            return
        if not await guard(message):
            return
        try:
            sku = command.args.strip()
            item = await service.product_data(sku)
            role = role_for_message(message) or "viewer"
            await message.answer(
                await service.product(sku),
                reply_markup=product_actions_keyboard(item["sku"], item["is_active"], role),
            )
        except Exception as exc:
            logger.exception("Product card failed")
            await message.answer(f"Ошибка: {exc}", parse_mode=None)

    @router.message(Command("low"))
    @router.message(F.text == BTN_LOW)
    async def low(message: Message) -> None:
        await safe(message, service.low_stock)

    @router.message(Command("history"))
    async def history_command(message: Message, command: CommandObject) -> None:
        await safe(message, lambda: service.history((command.args or "").strip()))

    @router.message(F.text == BTN_HISTORY)
    async def history_button(message: Message) -> None:
        await safe(message, service.history)

    @router.message(Command("add"))
    async def add_command(message: Message, command: CommandObject) -> None:
        await safe(message, lambda: service.add_product(command.args or ""), minimum_role="admin", audit_action="product.create")

    @router.message(F.text == BTN_ADD)
    async def add_button(message: Message, state: FSMContext) -> None:
        if not await guard(message, "admin"):
            return
        await state.set_state(AddProductState.waiting_payload)
        await message.answer(
            "Отправьте товар одной строкой:\n"
            "<code>SKU | Название | Категория | Цена | Остаток | Минимум</code>\n\n"
            "Расширенный вариант:\n"
            "<code>SKU | Название | Категория | Цена | Остаток | Минимум | Закупочная цена | Поставщик | Штрихкод | Ед.</code>\n\n"
            "Для отмены отправьте <b>Отмена</b>."
        )

    @router.message(AddProductState.waiting_payload, F.text)
    async def add_payload(message: Message, state: FSMContext) -> None:
        if not await guard(message, "admin"):
            await state.clear()
            return
        if (message.text or "").casefold() == "отмена":
            await state.clear()
            await message.answer("Добавление отменено.", reply_markup=main_menu("admin"))
            return
        try:
            result = await service.add_product(message.text or "")
        except Exception as exc:
            await message.answer(f"Ошибка: {exc}\nПопробуйте ещё раз или отправьте Отмена.", parse_mode=None)
            return
        await _audit(message, "product.create", details={"request": (message.text or "")[:1000]})
        await state.clear()
        await message.answer(result, reply_markup=main_menu("admin"))

    @router.message(Command("edit"))
    async def edit_command(message: Message, command: CommandObject) -> None:
        await safe(message, lambda: service.edit_product(command.args or ""), minimum_role="admin", audit_action="product.update")

    @router.message(F.text == BTN_EDIT)
    async def edit_button(message: Message, state: FSMContext) -> None:
        if not await guard(message, "admin"):
            return
        await state.set_state(EditProductState.waiting_payload)
        await message.answer(
            "Отправьте изменение:\n<code>SKU | поле | значение</code>\n\n"
            "Поля: name, category, price, purchase_price, min_stock, description, supplier, barcode, unit.\n"
            "Пример: <code>SKU-001 | supplier | ООО Поставщик</code>\n\n"
            "Для отмены отправьте <b>Отмена</b>."
        )

    @router.message(EditProductState.waiting_payload, F.text)
    async def edit_payload(message: Message, state: FSMContext) -> None:
        if not await guard(message, "admin"):
            await state.clear()
            return
        if (message.text or "").casefold() == "отмена":
            await state.clear()
            await message.answer("Редактирование отменено.", reply_markup=main_menu("admin"))
            return
        try:
            result = await service.edit_product(message.text or "")
        except Exception as exc:
            await message.answer(f"Ошибка: {exc}\nПопробуйте ещё раз или отправьте Отмена.", parse_mode=None)
            return
        await _audit(message, "product.update", details={"request": (message.text or "")[:1000]})
        await state.clear()
        await message.answer(result, reply_markup=main_menu("admin"))

    @router.message(Command("archive"))
    async def archive(message: Message, command: CommandObject) -> None:
        if not command.args:
            await message.answer("Формат: /archive SKU")
            return
        await safe(message, lambda: service.set_active(command.args.strip(), False), minimum_role="admin", audit_action="product.archive")

    @router.message(Command("restore"))
    async def restore(message: Message, command: CommandObject) -> None:
        if not command.args:
            await message.answer("Формат: /restore SKU")
            return
        await safe(message, lambda: service.set_active(command.args.strip(), True), minimum_role="admin", audit_action="product.restore")

    @router.callback_query(F.data.startswith("product:archive:"))
    async def archive_callback(callback: CallbackQuery) -> None:
        sku = (callback.data or "").split(":", 2)[2]
        await safe_callback(callback, lambda: service.set_active(sku, False), "admin", "product.archive")

    @router.callback_query(F.data.startswith("product:restore:"))
    async def restore_callback(callback: CallbackQuery) -> None:
        sku = (callback.data or "").split(":", 2)[2]
        await safe_callback(callback, lambda: service.set_active(sku, True), "admin", "product.restore")

    @router.callback_query(F.data.startswith("product:edit:"))
    async def edit_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not await guard_callback(callback, "admin") or callback.message is None:
            return
        sku = (callback.data or "").split(":", 2)[2]
        await callback.answer()
        await state.set_state(EditProductState.waiting_payload)
        await callback.message.answer(
            f"Изменение <code>{sku}</code>. Отправьте <code>{sku} | поле | значение</code>."
        )

    @router.message(Command("stock"))
    async def stock(message: Message, command: CommandObject) -> None:
        await safe(message, lambda: service.adjust_stock(command.args or ""), minimum_role="manager", audit_action="stock.adjust")

    @router.message(Command("move"))
    async def move_command(message: Message, command: CommandObject) -> None:
        await safe(message, lambda: service.stock_operation(command.args or ""), minimum_role="manager", audit_action="stock.operation")

    @router.message(F.text == BTN_MOVEMENT)
    async def move_button(message: Message, state: FSMContext) -> None:
        if not await guard(message, "manager"):
            return
        await state.set_state(MovementState.waiting_payload)
        await message.answer(
            "Складская операция:\n"
            "<code>operation SKU quantity | причина | документ | комментарий</code>\n\n"
            "operation: receipt, sale, return, writeoff, adjustment\n"
            "Пример: <code>sale SKU-001 2 | Продажа | ORD-1045 | Клиентский заказ</code>\n\n"
            "Для отмены отправьте <b>Отмена</b>."
        )

    @router.message(MovementState.waiting_payload, F.text)
    async def move_payload(message: Message, state: FSMContext) -> None:
        if not await guard(message, "manager"):
            await state.clear()
            return
        if (message.text or "").casefold() == "отмена":
            await state.clear()
            role = role_for_message(message) or "viewer"
            await message.answer("Операция отменена.", reply_markup=main_menu(role))
            return
        try:
            result = await service.stock_operation(message.text or "")
        except Exception as exc:
            await message.answer(f"Ошибка: {exc}\nПопробуйте ещё раз или отправьте Отмена.", parse_mode=None)
            return
        await _audit(message, "stock.operation", details={"request": (message.text or "")[:1000]})
        await state.clear()
        role = role_for_message(message) or "viewer"
        await message.answer(result, reply_markup=main_menu(role))

    async def send_export(message: Message, csv_mode: bool = False) -> None:
        if not await guard(message):
            return
        try:
            rows = await service.products_data(active_only=False, limit=5000)
            if csv_mode:
                payload = export_csv(rows)
                filename = "productflow_catalog.csv"
            else:
                payload = export_xlsx(rows)
                filename = "productflow_catalog.xlsx"
            await message.answer_document(
                BufferedInputFile(payload, filename=filename),
                caption=f"📤 Экспортировано товаров: {len(rows)}",
            )
        except Exception as exc:
            logger.exception("Export failed")
            await message.answer(f"Ошибка экспорта: {exc}", parse_mode=None)

    @router.message(Command("export"))
    @router.message(F.text == BTN_EXPORT)
    async def export_excel(message: Message) -> None:
        await send_export(message, csv_mode=False)

    @router.message(Command("export_csv"))
    async def export_csv_command(message: Message) -> None:
        await send_export(message, csv_mode=True)

    @router.message(Command("import"))
    @router.message(F.text == BTN_IMPORT)
    async def import_start(message: Message, state: FSMContext) -> None:
        if not await guard(message, "admin"):
            return
        await state.set_state(ImportCatalogState.waiting_file)
        await message.answer(
            "📥 Отправьте файл <b>.xlsx</b> или <b>.csv</b>.\n"
            "Обязательные колонки: SKU и Название.\n"
            "Существующие SKU будут обновлены, новые — созданы.\n"
            "Перед записью я покажу количество строк и попрошу подтверждение."
        )

    @router.message(ImportCatalogState.waiting_file, F.document)
    async def import_file(message: Message, state: FSMContext) -> None:
        if not await guard(message, "admin"):
            await state.clear()
            return
        document = message.document
        if document is None:
            return
        filename = document.file_name or "catalog.xlsx"
        try:
            tg_file = await message.bot.get_file(document.file_id)
            buffer = io.BytesIO()
            await message.bot.download_file(tg_file.file_path, destination=buffer)
            rows = parse_catalog_file(filename, buffer.getvalue())
            await state.update_data(import_rows=rows, import_filename=filename)
            await state.set_state(ImportCatalogState.waiting_confirm)
            await message.answer(
                f"Файл <b>{filename}</b> прочитан.\nСтрок товаров: <b>{len(rows)}</b>.\n"
                "Импортировать?",
                reply_markup=import_confirmation_keyboard(),
            )
        except Exception as exc:
            logger.exception("Import parse failed")
            await message.answer(f"Ошибка файла: {exc}", parse_mode=None)

    @router.message(ImportCatalogState.waiting_file)
    async def import_wrong_payload(message: Message) -> None:
        await message.answer("Ожидаю документ .xlsx или .csv, либо отправьте /start для выхода.")

    @router.callback_query(F.data == "import:confirm")
    async def import_confirm(callback: CallbackQuery, state: FSMContext) -> None:
        if not await guard_callback(callback, "admin") or callback.message is None:
            return
        data = await state.get_data()
        rows = data.get("import_rows") or []
        if not rows:
            await callback.answer("Нет данных для импорта", show_alert=True)
            await state.clear()
            return
        await callback.answer("Импортирую")
        try:
            result = await service.import_rows(rows)
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer(result)
            try:
                await service.audit_event(
                    actor_user_id=callback.from_user.id, actor_role=policy.role_for(callback.from_user.id) or "",
                    action="catalog.import", details={"rows": len(rows)},
                )
            except Exception:
                logger.exception("Import audit failed")
        except Exception as exc:
            logger.exception("Import failed")
            await callback.message.answer(f"Ошибка импорта: {exc}", parse_mode=None)
        finally:
            await state.clear()

    @router.callback_query(F.data == "import:cancel")
    async def import_cancel(callback: CallbackQuery, state: FSMContext) -> None:
        if not await guard_callback(callback, "admin"):
            return
        await state.clear()
        await callback.answer("Отменено")
        if callback.message:
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer("Импорт отменён.")

    @router.message(F.text == BTN_AI)
    async def ai_help(message: Message) -> None:
        if not await guard(message):
            return
        if agent is None:
            await message.answer("AI не настроен. Добавьте OPENAI_API_KEY в .env.")
            return
        role = role_for_message(message) or "viewer"
        extra = {
            "admin": "Можно читать данные, менять каталог и проводить складские операции.",
            "manager": "Можно читать данные и проводить складские операции. Каталог изменять нельзя.",
            "viewer": "Доступ только на чтение.",
        }[role]
        await message.answer(
            "🤖 <b>AI-помощник активен.</b>\n"
            f"Ваша роль: <b>{role}</b>. {extra}\n\n"
            "Примеры:\n"
            "• Какие товары заканчиваются?\n"
            "• Найди товар по штрихкоду 460...\n"
            "• Проведи продажу 2 шт. SKU-001 по заказу ORD-1045\n\n"
            "Изменения требуют подтверждения."
        )

    @router.message(F.text == BTN_SETTINGS)
    async def settings(message: Message) -> None:
        if not await guard(message):
            return
        role = role_for_message(message) or "viewer"
        await message.answer(
            "⚙️ <b>Настройки ProductFlow AI</b>\n"
            f"AI: {'подключён' if agent is not None else 'не подключён'}\n"
            f"Ваша роль: <b>{role}</b>\n"
            "База: SQLite через MCP\n"
            "Форматы импорта: XLSX, CSV\n"
            "Для системных настроек используется <code>.env</code>."
        )

    @router.callback_query(F.data == "ai:confirm")
    async def ai_confirm(callback: CallbackQuery) -> None:
        if not await guard_callback(callback) or callback.message is None or agent is None:
            return
        await callback.answer("Выполняю")
        try:
            result = await agent.confirm_pending(callback.message.chat.id)
            confirmed = agent.pop_last_confirmed(callback.message.chat.id)
            if confirmed:
                await service.audit_event(
                    actor_user_id=callback.from_user.id,
                    actor_role=policy.role_for(callback.from_user.id) or "",
                    action=f"ai.{confirmed['tool_name']}",
                    details=confirmed.get("arguments") or {},
                    success=bool(confirmed.get("success", True)),
                )
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer(ai_text_to_telegram_html(result))
        except Exception as exc:
            logger.exception("AI confirmation failed")
            await callback.message.answer(f"Ошибка агента: {exc}", parse_mode=None)

    @router.callback_query(F.data == "ai:cancel")
    async def ai_cancel(callback: CallbackQuery) -> None:
        if not await guard_callback(callback) or callback.message is None or agent is None:
            return
        await callback.answer("Отменено")
        result = await agent.cancel_pending(callback.message.chat.id)
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(result)

    @router.message(F.text)
    async def free_text(message: Message) -> None:
        if not await guard(message):
            return
        if agent is None:
            await message.answer("Для запросов обычным текстом добавьте OPENAI_API_KEY в .env.")
            return
        text = (message.text or "").strip()
        lowered = text.casefold()
        try:
            if agent.has_pending_confirmation(message.chat.id):
                if lowered in {"да", "подтверждаю", "подтвердить", "ок", "yes"}:
                    answer = await agent.confirm_pending(message.chat.id)
                    confirmed = agent.pop_last_confirmed(message.chat.id)
                    if confirmed:
                        await service.audit_event(
                            actor_user_id=user_id(message) or "",
                            actor_role=role_for_message(message) or "",
                            action=f"ai.{confirmed['tool_name']}",
                            details=confirmed.get("arguments") or {},
                            success=bool(confirmed.get("success", True)),
                        )
                    await message.answer(ai_text_to_telegram_html(answer))
                    return
                if lowered in {"нет", "отмена", "отменить", "cancel"}:
                    await message.answer(await agent.cancel_pending(message.chat.id))
                    return
                pending = agent.pending_confirmation_text(message.chat.id) or "Операция ожидает подтверждения."
                await message.answer(
                    ai_text_to_telegram_html(pending),
                    reply_markup=confirmation_keyboard(),
                )
                return

            await message.bot.send_chat_action(message.chat.id, "typing")
            uid = user_id(message)
            answer = await agent.answer(
                message.chat.id,
                text,
                allowed_write_tools=policy.allowed_ai_write_tools(uid),
                actor_user_id=uid,
                actor_role=role_for_message(message) or "viewer",
            )
            markup = confirmation_keyboard() if agent.has_pending_confirmation(message.chat.id) else None
            await message.answer(ai_text_to_telegram_html(answer), reply_markup=markup)
        except Exception as exc:
            logger.exception("Agent request failed")
            await message.answer(f"Ошибка агента: {exc}", parse_mode=None)

    return router
