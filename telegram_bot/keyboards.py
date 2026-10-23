from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

BTN_PRODUCTS = "📦 Товары"
BTN_ADD = "➕ Добавить товар"
BTN_SUMMARY = "📊 Сводка"
BTN_DASHBOARD = "📊 Dashboard"
BTN_LOW = "⚠️ Дефицит"
BTN_HISTORY = "📜 История"
BTN_AI = "🤖 AI-помощник"
BTN_EDIT = "✏️ Редактировать товар"
BTN_MOVEMENT = "🔄 Операция склада"
BTN_EXPORT = "📤 Экспорт Excel"
BTN_IMPORT = "📥 Импорт Excel/CSV"
BTN_CUSTOMERS = "👥 Клиенты"
BTN_SUPPLIERS = "🏭 Поставщики"
BTN_PURCHASES = "🚚 Закупки"
BTN_SALES = "🧾 Заказы"
BTN_ANALYTICS = "📈 Аналитика"
BTN_WAREHOUSES = "🏬 Склады"
BTN_CODES = "🏷 QR / Штрихкод"
BTN_AUDIT = "🛡 Аудит"
BTN_SETTINGS = "⚙️ Настройки"
BTN_CANCEL = "Отмена"


def main_menu(role: str = "admin") -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=BTN_PRODUCTS), KeyboardButton(text=BTN_DASHBOARD)],
        [KeyboardButton(text=BTN_SALES), KeyboardButton(text=BTN_PURCHASES)],
        [KeyboardButton(text=BTN_CUSTOMERS), KeyboardButton(text=BTN_SUPPLIERS)],
        [KeyboardButton(text=BTN_ANALYTICS), KeyboardButton(text=BTN_SUMMARY)],
        [KeyboardButton(text=BTN_LOW), KeyboardButton(text=BTN_HISTORY)],
        [KeyboardButton(text=BTN_WAREHOUSES), KeyboardButton(text=BTN_CODES)],
    ]
    if role in {"manager", "admin"}:
        rows.append([KeyboardButton(text=BTN_MOVEMENT)])
    if role == "admin":
        rows.append([KeyboardButton(text=BTN_ADD), KeyboardButton(text=BTN_EDIT)])
        rows.append([KeyboardButton(text=BTN_IMPORT), KeyboardButton(text=BTN_EXPORT)])
        rows.append([KeyboardButton(text=BTN_AUDIT)])
    else:
        rows.append([KeyboardButton(text=BTN_EXPORT)])
    rows.append([KeyboardButton(text=BTN_AI), KeyboardButton(text=BTN_SETTINGS)])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        input_field_placeholder="Выберите действие или напишите запрос",
    )


def confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="✅ Подтвердить", callback_data="ai:confirm"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="ai:cancel"),
        ]]
    )


def import_confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="✅ Импортировать", callback_data="import:confirm"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="import:cancel"),
        ]]
    )


def product_actions_keyboard(sku: str, is_active: bool, role: str = "viewer") -> InlineKeyboardMarkup:
    rows = [[
        InlineKeyboardButton(text="🔳 QR", callback_data=f"product:qr:{sku}"),
        InlineKeyboardButton(text="▥ Штрихкод", callback_data=f"product:barcode:{sku}"),
    ]]
    if role == "admin":
        action = "archive" if is_active else "restore"
        title = "📥 Архивировать" if is_active else "♻️ Восстановить"
        rows.extend([
            [InlineKeyboardButton(text="✏️ Изменить", callback_data=f"product:edit:{sku}")],
            [InlineKeyboardButton(text=title, callback_data=f"product:{action}:{sku}")],
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)
