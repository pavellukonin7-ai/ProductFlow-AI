from __future__ import annotations

from html import escape
from typing import Any, Protocol


MOVEMENT_NAMES = {
    "initial": "Начальный остаток",
    "receipt": "Приход",
    "sale": "Продажа",
    "return": "Возврат",
    "writeoff": "Списание",
    "adjustment": "Корректировка",
}


class MCPCaller(Protocol):
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any: ...


class InventoryService:
    def __init__(self, mcp: MCPCaller) -> None:
        self.mcp = mcp

    @staticmethod
    def _low_stock_warning(item: dict[str, Any]) -> str:
        if item.get("is_active", True) and item["stock"] <= item["min_stock"]:
            return (
                "\n\n⚠️ <b>Низкий остаток:</b> "
                f"{item['stock']} {escape(item.get('unit') or 'шт.')}, минимум — {item['min_stock']}."
            )
        return ""

    async def summary(self) -> str:
        data = await self.mcp.call_tool("inventory_summary", {})
        return (
            "<b>📊 Сводка склада</b>\n"
            f"Товаров: {data['products_total']}\n"
            f"Активных: {data['active_products']}\n"
            f"Категорий: {data['categories_total']}\n"
            f"Единиц на складе: {data['units_in_stock']}\n"
            f"Дефицитных позиций: {data['low_stock_products']}\n"
            f"Розничная стоимость: {data['inventory_value']:.2f} ₽\n"
            f"Закупочная стоимость: {data.get('purchase_value', 0):.2f} ₽\n"
            f"Потенциальная маржа: {data.get('potential_margin', 0):.2f} ₽"
        )

    async def products_data(self, query: str = "", *, active_only: bool = True, limit: int = 5000) -> list[dict[str, Any]]:
        return await self.mcp.call_tool(
            "search_products",
            {"query": query, "limit": limit, "active_only": active_only},
        )

    async def products(self, query: str = "", *, active_only: bool = True) -> str:
        rows = await self.products_data(query, active_only=active_only, limit=20)
        if not rows:
            return "Товары не найдены."
        lines = ["<b>📦 Товары</b>"]
        for item in rows:
            status = "" if item.get("is_active", True) else " [архив]"
            lines.append(
                f"• <code>{escape(item['sku'])}</code> — {escape(item['name'])}{status}\n"
                f"  {item['price']:.2f} ₽ · остаток {item['stock']} {escape(item.get('unit') or 'шт.')}"
            )
        return "\n".join(lines)

    async def product_data(self, sku: str) -> dict[str, Any]:
        return await self.mcp.call_tool("get_product", {"sku": sku})

    async def product(self, sku: str) -> str:
        item = await self.product_data(sku)
        description = escape(item.get("description") or "—")
        supplier = escape(item.get("supplier") or "—")
        barcode = escape(item.get("barcode") or "—")
        unit = escape(item.get("unit") or "шт.")
        return (
            f"<b>📦 {escape(item['name'])}</b>\n"
            f"SKU: <code>{escape(item['sku'])}</code>\n"
            f"Категория: {escape(item['category'])}\n"
            f"Цена продажи: {item['price']:.2f} ₽\n"
            f"Закупочная цена: {item.get('purchase_price', 0):.2f} ₽\n"
            f"Остаток: {item['stock']} {unit}\n"
            f"Минимум: {item['min_stock']} {unit}\n"
            f"Поставщик: {supplier}\n"
            f"Штрихкод: <code>{barcode}</code>\n"
            f"Описание: {description}\n"
            f"Статус: {'активен' if item['is_active'] else 'архив'}"
            f"{self._low_stock_warning(item)}"
        )

    async def low_stock(self) -> str:
        rows = await self.mcp.call_tool("low_stock_report", {"limit": 50})
        if not rows:
            return "✅ Дефицитных позиций нет."
        lines = ["<b>⚠️ Дефицитные позиции</b>"]
        for item in rows:
            lines.append(
                f"• <code>{escape(item['sku'])}</code> — {escape(item['name'])}: "
                f"{item['stock']} / минимум {item['min_stock']} {escape(item.get('unit') or 'шт.')}"
            )
        return "\n".join(lines)

    async def add_product(self, raw: str) -> str:
        parts = [part.strip() for part in raw.split("|")]
        if len(parts) not in {6, 10}:
            raise ValueError(
                "Формат: SKU | Название | Категория | Цена | Остаток | Минимум "
                "[| Закупочная цена | Поставщик | Штрихкод | Ед.]"
            )
        sku, name, category, price, stock, minimum = parts[:6]
        extra = parts[6:] if len(parts) == 10 else ["0", "", "", "шт."]
        purchase_price, supplier, barcode, unit = extra
        item = await self.mcp.call_tool(
            "create_product",
            {
                "sku": sku,
                "name": name,
                "category": category,
                "price": float(price.replace(",", ".")),
                "initial_stock": int(stock),
                "min_stock": int(minimum),
                "purchase_price": float((purchase_price or "0").replace(",", ".")),
                "supplier": supplier,
                "barcode": barcode,
                "unit": unit or "шт.",
            },
        )
        return (
            f"✅ Товар создан: <code>{escape(item['sku'])}</code>, остаток {item['stock']} "
            f"{escape(item.get('unit') or 'шт.')}."
            f"{self._low_stock_warning(item)}"
        )

    async def adjust_stock(self, raw: str) -> str:
        parts = raw.split(maxsplit=2)
        if len(parts) != 3:
            raise ValueError("Формат: /stock SKU DELTA причина")
        sku, delta, reason = parts
        item = await self.mcp.call_tool(
            "adjust_stock",
            {"sku": sku, "delta": int(delta), "reason": reason},
        )
        return self._stock_result(item, "Остаток изменён")

    async def stock_operation(self, raw: str) -> str:
        main, *details = [part.strip() for part in raw.split("|")]
        tokens = main.split(maxsplit=2)
        if len(tokens) != 3:
            raise ValueError(
                "Формат: operation SKU quantity | причина | документ | комментарий\n"
                "Операции: receipt, sale, return, writeoff, adjustment"
            )
        operation, sku, quantity = tokens
        reason = details[0] if len(details) > 0 else ""
        document_ref = details[1] if len(details) > 1 else ""
        comment = details[2] if len(details) > 2 else ""
        item = await self.mcp.call_tool(
            "stock_operation",
            {
                "sku": sku,
                "operation": operation,
                "quantity": int(quantity),
                "reason": reason,
                "document_ref": document_ref,
                "comment": comment,
            },
        )
        return self._stock_result(item, MOVEMENT_NAMES.get(operation.casefold(), "Операция выполнена"))

    def _stock_result(self, item: dict[str, Any], action: str) -> str:
        return (
            f"✅ {escape(action)}: <code>{escape(item['sku'])}</code>\n"
            f"Новый остаток: {item['stock']} {escape(item.get('unit') or 'шт.')}"
            f"{self._low_stock_warning(item)}"
        )

    async def edit_product(self, raw: str) -> str:
        parts = [part.strip() for part in raw.split("|", 2)]
        if len(parts) != 3:
            raise ValueError("Формат: SKU | поле | значение")
        sku, field, value = parts
        aliases = {
            "name": "name", "название": "name",
            "category": "category", "категория": "category",
            "price": "price", "цена": "price",
            "purchase_price": "purchase_price", "закупочная цена": "purchase_price",
            "min_stock": "min_stock", "минимум": "min_stock", "min": "min_stock",
            "description": "description", "описание": "description",
            "supplier": "supplier", "поставщик": "supplier",
            "barcode": "barcode", "штрихкод": "barcode", "ean": "barcode",
            "unit": "unit", "единица": "unit",
        }
        key = aliases.get(field.casefold())
        if key is None:
            raise ValueError(
                "Поля: name, category, price, purchase_price, min_stock, description, supplier, barcode, unit"
            )
        converted: Any = value
        if key in {"price", "purchase_price"}:
            converted = float(value.replace(",", "."))
        elif key == "min_stock":
            converted = int(value)

        item = await self.mcp.call_tool("update_product", {"sku": sku, key: converted})
        return (
            f"✅ Товар <code>{escape(item['sku'])}</code> обновлён.\n"
            f"{escape(item['name'])} · {item['price']:.2f} ₽ · остаток {item['stock']} · минимум {item['min_stock']}"
            f"{self._low_stock_warning(item)}"
        )

    async def set_active(self, sku: str, is_active: bool) -> str:
        item = await self.mcp.call_tool("update_product", {"sku": sku, "is_active": is_active})
        action = "восстановлен" if is_active else "архивирован"
        return f"✅ Товар <code>{escape(item['sku'])}</code> {action}." + (
            self._low_stock_warning(item) if is_active else ""
        )

    async def history(self, sku: str = "") -> str:
        rows = await self.mcp.call_tool("movement_history", {"sku": sku or None, "limit": 20})
        if not rows:
            return "История движений пуста."
        lines = ["<b>📜 Последние движения</b>"]
        for item in rows:
            sign = "+" if item["delta"] > 0 else ""
            movement = MOVEMENT_NAMES.get(item.get("movement_type", "adjustment"), item.get("movement_type", ""))
            doc = f" · документ: {escape(item['document_ref'])}" if item.get("document_ref") else ""
            comment = f" · {escape(item['comment'])}" if item.get("comment") else ""
            lines.append(
                f"• <code>{escape(item['sku'])}</code> · {escape(movement)} · {sign}{item['delta']} → "
                f"{item['quantity_after']}\n  {escape(item['reason'])}{doc}{comment}"
            )
        return "\n".join(lines)

    async def import_rows(self, rows: list[dict[str, Any]]) -> str:
        result = await self.mcp.call_tool("import_products", {"rows": rows, "update_existing": True})
        text = (
            "✅ <b>Импорт завершён</b>\n"
            f"Создано: {result['created']}\n"
            f"Обновлено: {result['updated']}\n"
            f"Ошибок: {result['errors_total']}"
        )
        if result.get("errors"):
            text += "\n\n" + "\n".join(f"• {escape(error)}" for error in result["errors"][:10])
        return text

    @staticmethod
    def _parse_order_items(raw: str, *, price_key: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for token in raw.split(","):
            token = token.strip()
            if not token:
                continue
            parts = [part.strip() for part in token.split(":")]
            if len(parts) not in {2, 3}:
                raise ValueError("Позиции: SKU:количество[:цена], через запятую")
            item: dict[str, Any] = {"sku": parts[0], "quantity": int(parts[1])}
            if len(parts) == 3 and parts[2]:
                item[price_key] = float(parts[2].replace(",", "."))
            items.append(item)
        if not items:
            raise ValueError("Добавьте хотя бы одну позицию")
        return items

    async def customers(self, query: str = "") -> str:
        rows = await self.mcp.call_tool("list_customers", {"query": query, "active_only": True, "limit": 50})
        if not rows:
            return "Клиентов пока нет."
        lines = ["<b>👥 Клиенты</b>"]
        for item in rows:
            contact = f" · {escape(item['contact_name'])}" if item.get("contact_name") else ""
            lines.append(
                f"• <code>{escape(item['code'])}</code> — {escape(item['name'])}{contact}\n"
                f"  заказов: {item.get('orders_count', 0)} · выручка: {item.get('revenue', 0):.2f} ₽"
            )
        return "\n".join(lines)

    async def add_customer(self, raw: str) -> str:
        parts = [part.strip() for part in raw.split("|")]
        if len(parts) < 2 or len(parts) > 7:
            raise ValueError("Формат: CODE | Название | Контакт | Телефон | Email | Адрес | Комментарий")
        parts += [""] * (7 - len(parts))
        code, name, contact, phone, email, address, comment = parts
        item = await self.mcp.call_tool("create_customer", {
            "code": code, "name": name, "contact_name": contact, "phone": phone,
            "email": email, "address": address, "comment": comment,
        })
        return f"✅ Клиент создан: <code>{escape(item['code'])}</code> — {escape(item['name'])}."

    async def customer_card(self, code: str) -> str:
        item = await self.mcp.call_tool("get_customer", {"code": code.strip()})
        return (
            f"<b>👤 {escape(item['name'])}</b>\n"
            f"Код: <code>{escape(item['code'])}</code>\n"
            f"Контакт: {escape(item.get('contact_name') or '—')}\n"
            f"Телефон: {escape(item.get('phone') or '—')}\n"
            f"Email: {escape(item.get('email') or '—')}\n"
            f"Заказов: {item.get('orders_count',0)} · завершено: {item.get('completed_orders',0)}\n"
            f"Выручка: {item.get('revenue',0):.2f} ₽ · валовая прибыль: {item.get('gross_profit',0):.2f} ₽"
        )

    async def availability(self, sku: str) -> str:
        item = await self.mcp.call_tool("product_availability", {"sku": sku.strip()})
        return (
            f"<b>📦 Доступность {escape(item['sku'])}</b>\n"
            f"{escape(item['name'])}\n"
            f"Физически на MAIN: {item['main_stock']}\n"
            f"В резерве: {item['reserved']}\n"
            f"Доступно к продаже: <b>{item['available']}</b>"
        )

    async def reserve_sale(self, order_no: str) -> str:
        order = await self.mcp.call_tool("reserve_sales_order", {"order_no": order_no.strip()})
        units = sum(int(x.get('reserved_quantity',0)) for x in order['items'])
        return f"✅ Заказ <code>{escape(order['order_no'])}</code> зарезервирован: {units} ед."

    async def release_sale(self, order_no: str) -> str:
        order = await self.mcp.call_tool("release_sales_reservation", {"order_no": order_no.strip()})
        return f"✅ Резерв заказа <code>{escape(order['order_no'])}</code> снят. Статус: {escape(order['status'])}."

    async def process_sale(self, order_no: str) -> str:
        order = await self.mcp.call_tool("start_sales_processing", {"order_no": order_no.strip()})
        return f"✅ Заказ <code>{escape(order['order_no'])}</code> передан в обработку."

    async def ship_sale(self, raw: str) -> str:
        parts = [part.strip() for part in raw.split("|",1)]
        order_no = parts[0] if parts else ""
        if not order_no:
            raise ValueError("Формат: НОМЕР_ЗАКАЗА | SKU:кол-во, ... (позиции необязательны)")
        items = None
        if len(parts) == 2 and parts[1]:
            items = self._parse_order_items(parts[1], price_key="unused")
            for item in items:
                item.pop("unused", None)
        order = await self.mcp.call_tool("ship_sales_order", {"order_no": order_no, "items": items})
        fulfilled = sum(int(x.get('fulfilled_quantity',0)) for x in order['items'])
        total = sum(int(x.get('quantity',0)) for x in order['items'])
        return (
            f"✅ Отгрузка заказа <code>{escape(order['order_no'])}</code>.\n"
            f"Отгружено суммарно: {fulfilled}/{total} ед.\nСтатус: {escape(order['status'])}."
        )

    async def suppliers(self) -> str:
        rows = await self.mcp.call_tool("list_suppliers", {"active_only": True, "limit": 50})
        if not rows:
            return "Поставщиков пока нет."
        lines = ["<b>🏭 Поставщики</b>"]
        for item in rows:
            contact = f" · {escape(item['contact_name'])}" if item.get("contact_name") else ""
            phone = f" · {escape(item['phone'])}" if item.get("phone") else ""
            lines.append(f"• <code>{escape(item['code'])}</code> — {escape(item['name'])}{contact}{phone}")
        return "\n".join(lines)

    async def add_supplier(self, raw: str) -> str:
        parts = [part.strip() for part in raw.split("|")]
        if len(parts) < 2 or len(parts) > 6:
            raise ValueError("Формат: CODE | Название | Контакт | Телефон | Email | Комментарий")
        parts += [""] * (6 - len(parts))
        code, name, contact, phone, email, comment = parts
        item = await self.mcp.call_tool(
            "create_supplier",
            {"code": code, "name": name, "contact_name": contact, "phone": phone, "email": email, "comment": comment},
        )
        return f"✅ Поставщик создан: <code>{escape(item['code'])}</code> — {escape(item['name'])}."

    async def purchases(self, status: str = "") -> str:
        rows = await self.mcp.call_tool("list_purchase_orders", {"status": status or None, "limit": 30})
        if not rows:
            return "Закупок пока нет."
        names = {"ordered": "ожидается", "received": "принята", "cancelled": "отменена"}
        lines = ["<b>🚚 Закупки</b>"]
        for item in rows:
            lines.append(
                f"• <code>{escape(item['order_no'])}</code> · {escape(names.get(item['status'], item['status']))}\n"
                f"  {escape(item['supplier_name'])} · {item['item_count']} поз. · {item['total']:.2f} ₽"
            )
        return "\n".join(lines)

    async def create_purchase(self, raw: str) -> str:
        parts = [part.strip() for part in raw.split("|", 3)]
        if len(parts) < 3:
            raise ValueError("Формат: НОМЕР | КОД_ПОСТАВЩИКА | SKU:кол-во:цена, ... | комментарий")
        parts += [""] * (4 - len(parts))
        order_no, supplier_code, raw_items, comment = parts
        items = self._parse_order_items(raw_items, price_key="purchase_price")
        order = await self.mcp.call_tool(
            "create_purchase_order",
            {"order_no": order_no, "supplier_code": supplier_code, "items": items, "comment": comment},
        )
        return (
            f"✅ Закупка <code>{escape(order['order_no'])}</code> создана.\n"
            f"Поставщик: {escape(order['supplier_name'])}\n"
            f"Позиций: {len(order['items'])} · сумма: {order['total']:.2f} ₽\n"
            "Статус: ожидается приёмка."
        )

    async def receive_purchase(self, order_no: str) -> str:
        order = await self.mcp.call_tool("receive_purchase_order", {"order_no": order_no.strip()})
        units = sum(int(item["received_quantity"]) for item in order["items"])
        return (
            f"✅ Закупка <code>{escape(order['order_no'])}</code> принята.\n"
            f"Поставщик: {escape(order['supplier_name'])}\n"
            f"Оприходовано: {units} ед. · сумма: {order['total']:.2f} ₽"
        )

    async def sales_orders(self, status: str = "") -> str:
        rows = await self.mcp.call_tool("list_sales_orders", {"status": status or None, "limit": 30})
        if not rows:
            return "Заказов клиентов пока нет."
        names = {"new": "новый", "reserved": "резерв", "processing": "в обработке", "completed": "завершён", "cancelled": "отменён"}
        lines = ["<b>🧾 Заказы клиентов</b>"]
        for item in rows:
            customer = escape(item.get("customer_name") or "Без имени")
            lines.append(
                f"• <code>{escape(item['order_no'])}</code> · {escape(names.get(item['status'], item['status']))}\n"
                f"  {customer} · {item['item_count']} поз. · {item['revenue']:.2f} ₽"
            )
        return "\n".join(lines)

    async def create_sale_order(self, raw: str) -> str:
        parts = [part.strip() for part in raw.split("|", 3)]
        if len(parts) < 3:
            raise ValueError("Формат: НОМЕР | КЛИЕНТ | SKU:кол-во[:цена], ... | комментарий")
        parts += [""] * (4 - len(parts))
        order_no, customer, raw_items, comment = parts
        items = self._parse_order_items(raw_items, price_key="unit_price")
        order = await self.mcp.call_tool(
            "create_sales_order",
            {"order_no": order_no, "customer_name": customer, "items": items, "comment": comment},
        )
        return (
            f"✅ Заказ <code>{escape(order['order_no'])}</code> создан.\n"
            f"Клиент: {escape(order['customer_name'] or '—')}\n"
            f"Сумма: {order['revenue']:.2f} ₽ · ожидаемая валовая прибыль: {order['gross_profit']:.2f} ₽\n"
            "Товар будет списан только после завершения заказа."
        )

    async def complete_sale(self, order_no: str) -> str:
        order = await self.mcp.call_tool("complete_sales_order", {"order_no": order_no.strip()})
        units = sum(int(item["fulfilled_quantity"]) for item in order["items"])
        return (
            f"✅ Заказ <code>{escape(order['order_no'])}</code> завершён.\n"
            f"Списано: {units} ед.\n"
            f"Выручка: {order['revenue']:.2f} ₽\n"
            f"Себестоимость: {order['cost']:.2f} ₽\n"
            f"Валовая прибыль: <b>{order['gross_profit']:.2f} ₽</b>"
        )

    async def analytics(self, days: int = 30) -> str:
        data = await self.mcp.call_tool("sales_analytics", {"days": days})
        lines = [
            f"<b>📈 Продажи и прибыль · {data['days']} дн.</b>",
            f"Завершённых заказов: {data['orders_count']}",
            f"Продано по завершённым заказам: {data['units_net']} ед.",
            f"Выручка: {data['revenue']:.2f} ₽",
            f"Себестоимость: {data['cost']:.2f} ₽",
            f"Валовая прибыль: <b>{data['gross_profit']:.2f} ₽</b>",
            f"Валовая маржа: {data['gross_margin_percent']:.2f}%",
        ]
        if data.get("top_products"):
            lines.append("\n<b>Топ товаров по выручке</b>")
            for item in data["top_products"]:
                lines.append(
                    f"• <code>{escape(item['sku'])}</code> — {escape(item['name'])}: "
                    f"{item['units']} ед. · {item['revenue']:.2f} ₽"
                )
        return "\n".join(lines)

    async def dashboard(self, days: int = 7) -> str:
        data = await self.mcp.call_tool("business_dashboard", {"days": days})
        sales = data["sales"]
        return (
            f"<b>📊 ProductFlow Dashboard · {data['days']} дн.</b>\n\n"
            f"<b>Склад</b>\n"
            f"Товаров: {data['products_total']} · единиц: {data['units_in_stock']}\n"
            f"Дефицитных: {data['low_stock_products']}\n"
            f"Розничная стоимость: {data['inventory_retail_value']:.2f} ₽\n"
            f"Закупочная стоимость: {data['inventory_cost_value']:.2f} ₽\n\n"
            f"<b>Продажи</b>\n"
            f"Заказов завершено: {sales['orders_count']}\n"
            f"Выручка: {sales['revenue']:.2f} ₽\n"
            f"Валовая прибыль: <b>{sales['gross_profit']:.2f} ₽</b> · маржа {sales['gross_margin_percent']:.2f}%\n\n"
            f"<b>Операции</b>\n"
            f"Новых заказов клиентов: {data['open_sales_orders']}\n"
            f"Открытых закупок: {data['open_purchase_orders']} на {data['open_purchase_total']:.2f} ₽\n"
            f"Активных поставщиков: {data['active_suppliers']}"
        )

    async def low_stock_data(self) -> list[dict[str, Any]]:
        return await self.mcp.call_tool("low_stock_report", {"limit": 100})

    async def warehouses(self) -> str:
        rows = await self.mcp.call_tool("list_warehouses", {"active_only": True, "limit": 100})
        if not rows:
            return "Складов пока нет."
        lines = ["<b>🏬 Склады</b>"]
        for item in rows:
            location = f" · {escape(item['location'])}" if item.get("location") else ""
            lines.append(
                f"• <code>{escape(item['code'])}</code> — {escape(item['name'])}{location}\n"
                f"  {item['units']} ед. · товаров с остатком: {item['products_with_stock']}"
            )
        return "\n".join(lines)

    async def add_warehouse(self, raw: str) -> str:
        parts = [part.strip() for part in raw.split("|", 2)]
        if len(parts) < 2:
            raise ValueError("Формат: CODE | Название | Локация")
        parts += [""] * (3 - len(parts))
        item = await self.mcp.call_tool(
            "create_warehouse", {"code": parts[0], "name": parts[1], "location": parts[2]}
        )
        return f"✅ Склад создан: <code>{escape(item['code'])}</code> — {escape(item['name'])}."

    async def warehouse_stock(self, warehouse_code: str = "MAIN", query: str = "") -> str:
        rows = await self.mcp.call_tool(
            "warehouse_stock",
            {"warehouse_code": warehouse_code or "MAIN", "query": query, "limit": 50},
        )
        if not rows:
            return "На складе товары не найдены."
        head = rows[0]
        lines = [f"<b>🏬 {escape(head['warehouse_name'])} · {escape(head['warehouse_code'])}</b>"]
        for item in rows:
            if item["quantity"] <= 0 and query == "":
                continue
            lines.append(
                f"• <code>{escape(item['sku'])}</code> — {escape(item['name'])}: "
                f"{item['quantity']} {escape(item.get('unit') or 'шт.')} "
                f"(всего {item['total_stock']})"
            )
        return "\n".join(lines) if len(lines) > 1 else lines[0] + "\nПоложительных остатков нет."

    async def product_distribution(self, sku: str) -> str:
        rows = await self.mcp.call_tool("product_warehouse_distribution", {"sku": sku})
        if not rows:
            return "Распределение не найдено."
        first = rows[0]
        lines = [
            f"<b>📍 Распределение {escape(first['sku'])}</b>",
            f"{escape(first['name'])} · всего {first['total_stock']} {escape(first.get('unit') or 'шт.')}",
        ]
        for item in rows:
            lines.append(
                f"• <code>{escape(item['warehouse_code'])}</code> — {escape(item['warehouse_name'])}: "
                f"{item['quantity']} {escape(item.get('unit') or 'шт.')}"
            )
        return "\n".join(lines)

    async def transfer(self, raw: str, *, actor_user_id: str = "") -> str:
        main, *details = [part.strip() for part in raw.split("|")]
        tokens = main.split()
        if len(tokens) != 4:
            raise ValueError("Формат: SKU количество FROM TO | причина | документ")
        sku, quantity, source, target = tokens
        result = await self.mcp.call_tool(
            "transfer_between_warehouses",
            {
                "sku": sku,
                "quantity": int(quantity),
                "from_warehouse": source,
                "to_warehouse": target,
                "reason": details[0] if details else "Перемещение между складами",
                "document_ref": details[1] if len(details) > 1 else "",
                "actor_user_id": actor_user_id,
            },
        )
        return (
            f"✅ Перемещение выполнено: <code>{escape(result['sku'])}</code> · {result['quantity']} "
            f"{escape(result.get('unit') or 'шт.')}\n"
            f"<code>{escape(result['from_warehouse'])}</code> → <code>{escape(result['to_warehouse'])}</code>\n"
            f"Общий остаток: {result['total_stock']} {escape(result.get('unit') or 'шт.')}"
        )

    async def warehouse_history(self, limit: int = 30) -> str:
        rows = await self.mcp.call_tool("warehouse_movements", {"limit": limit})
        if not rows:
            return "Перемещений между складами пока нет."
        lines = ["<b>🔁 Перемещения между складами</b>"]
        for item in rows:
            doc = f" · документ: {escape(item['document_ref'])}" if item.get("document_ref") else ""
            lines.append(
                f"• <code>{escape(item['sku'])}</code> · {item['quantity']} ед. · "
                f"<code>{escape(item.get('from_code') or '—')}</code> → "
                f"<code>{escape(item.get('to_code') or '—')}</code>{doc}\n"
                f"  {escape(item.get('reason') or 'Перемещение')}"
            )
        return "\n".join(lines)

    async def audit_event(
        self,
        *,
        actor_user_id: int | str,
        actor_role: str,
        action: str,
        entity_type: str = "telegram",
        entity_id: str = "",
        details: dict[str, Any] | None = None,
        success: bool = True,
    ) -> None:
        await self.mcp.call_tool(
            "record_audit_event",
            {
                "actor_user_id": str(actor_user_id),
                "actor_role": actor_role,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "details": details or {},
                "success": success,
            },
        )

    async def audit_log(self, limit: int = 30) -> str:
        rows = await self.mcp.call_tool("list_audit_events", {"limit": limit})
        if not rows:
            return "Журнал аудита пока пуст."
        lines = ["<b>🛡 Журнал аудита</b>"]
        for item in rows:
            state = "✅" if item.get("success", True) else "❌"
            actor = escape(item.get("actor_user_id") or "system")
            entity = ""
            if item.get("entity_id"):
                entity = f" · <code>{escape(item['entity_id'])}</code>"
            details = item.get("details") or {}
            detail_text = ""
            if isinstance(details, dict) and details:
                preferred = []
                request_text = str(details.get("request") or "").strip()
                if request_text:
                    preferred.append(request_text)
                error_text = str(details.get("error") or "").strip()
                if error_text:
                    preferred.append("Ошибка: " + error_text)
                if not preferred:
                    for key in ("sku", "from_warehouse", "to_warehouse", "quantity", "document_ref"):
                        if details.get(key) not in (None, ""):
                            preferred.append(f"{key}={details[key]}")
                if preferred:
                    joined = " · ".join(preferred)
                    detail_text = f"\n  <i>{escape(joined[:260])}</i>"
            lines.append(
                f"{state} {escape(item['created_at'])} · {actor} ({escape(item.get('actor_role') or '—')})\n"
                f"  {escape(item['action'])}{entity}{detail_text}"
            )
        return "\n".join(lines)
