from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from mcp_server.database import Database
from mcp_server.repository import minor_to_price, price_to_minor, utc_now


PURCHASE_STATUSES = {"ordered", "received", "cancelled"}
SALES_STATUSES = {"new", "reserved", "processing", "completed", "cancelled"}


class CommerceRepository:
    """Suppliers, purchase orders, sales orders and business analytics."""

    def __init__(self, database: Database) -> None:
        self.db = database

    @staticmethod
    def _supplier_dict(row: Any) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "code": str(row["code"]),
            "name": str(row["name"]),
            "contact_name": str(row["contact_name"]),
            "phone": str(row["phone"]),
            "email": str(row["email"]),
            "comment": str(row["comment"]),
            "is_active": bool(row["is_active"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def create_supplier(
        self,
        *,
        code: str,
        name: str,
        contact_name: str = "",
        phone: str = "",
        email: str = "",
        comment: str = "",
    ) -> dict[str, Any]:
        code = code.strip().upper()
        name = name.strip()
        if not code:
            raise ValueError("Код поставщика обязателен")
        if not name:
            raise ValueError("Название поставщика обязательно")
        now = utc_now()
        try:
            with self.db.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO suppliers(code, name, contact_name, phone, email, comment, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (code, name, contact_name.strip(), phone.strip(), email.strip(), comment.strip(), now, now),
                )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise ValueError(f"Поставщик с кодом {code} уже существует") from exc
            raise
        return self.get_supplier(code)

    def update_supplier(
        self,
        *,
        code: str,
        name: str | None = None,
        contact_name: str | None = None,
        phone: str | None = None,
        email: str | None = None,
        comment: str | None = None,
        is_active: bool | None = None,
    ) -> dict[str, Any]:
        code = code.strip().upper()
        if not code:
            raise ValueError("Код поставщика обязателен")
        changes: list[str] = []
        values: list[Any] = []
        if name is not None:
            value = name.strip()
            if not value:
                raise ValueError("Название поставщика обязательно")
            changes.append("name = ?")
            values.append(value)
        for field, value in (("contact_name", contact_name), ("phone", phone), ("email", email), ("comment", comment)):
            if value is not None:
                changes.append(f"{field} = ?")
                values.append(value.strip())
        if is_active is not None:
            changes.append("is_active = ?")
            values.append(1 if is_active else 0)
        if not changes:
            return self.get_supplier(code)
        changes.append("updated_at = ?")
        values.append(utc_now())
        values.append(code)
        with self.db.transaction() as connection:
            cursor = connection.execute(
                f"UPDATE suppliers SET {', '.join(changes)} WHERE code = ? COLLATE NOCASE",
                values,
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Поставщик {code} не найден")
        return self.get_supplier(code)

    def get_supplier(self, code: str) -> dict[str, Any]:
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT * FROM suppliers WHERE code = ? COLLATE NOCASE", (code.strip(),)
            ).fetchone()
        if row is None:
            raise ValueError(f"Поставщик {code.strip()} не найден")
        return self._supplier_dict(row)

    def list_suppliers(self, *, active_only: bool = True, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 1000))
        where = "WHERE is_active = 1" if active_only else ""
        with self.db.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM suppliers {where} ORDER BY name COLLATE NOCASE LIMIT ?", (limit,)
            ).fetchall()
        return [self._supplier_dict(row) for row in rows]

    def create_purchase_order(
        self,
        *,
        order_no: str,
        supplier_code: str,
        items: list[dict[str, Any]],
        comment: str = "",
    ) -> dict[str, Any]:
        order_no = order_no.strip().upper()
        supplier_code = supplier_code.strip().upper()
        if not order_no:
            raise ValueError("Номер закупки обязателен")
        if not items:
            raise ValueError("В закупке должна быть хотя бы одна позиция")
        now = utc_now()
        with self.db.transaction() as connection:
            supplier = connection.execute(
                "SELECT id, name, is_active FROM suppliers WHERE code = ? COLLATE NOCASE",
                (supplier_code,),
            ).fetchone()
            if supplier is None:
                raise ValueError(f"Поставщик {supplier_code} не найден")
            if not supplier["is_active"]:
                raise ValueError(f"Поставщик {supplier_code} неактивен")

            normalized: list[tuple[int, int, int]] = []
            total_minor = 0
            seen_skus: set[str] = set()
            for item in items:
                sku = str(item.get("sku", "")).strip().upper()
                quantity = int(item.get("quantity", 0))
                if sku in seen_skus:
                    raise ValueError(f"SKU {sku} повторяется в закупке")
                seen_skus.add(sku)
                if quantity <= 0:
                    raise ValueError(f"Количество для {sku or 'позиции'} должно быть больше нуля")
                product = connection.execute(
                    "SELECT id, purchase_price_minor FROM products WHERE sku = ? COLLATE NOCASE AND is_active = 1",
                    (sku,),
                ).fetchone()
                if product is None:
                    raise ValueError(f"Активный товар {sku} не найден")
                raw_price = item.get("purchase_price")
                price_minor = (
                    price_to_minor(raw_price)
                    if raw_price is not None
                    else int(product["purchase_price_minor"])
                )
                normalized.append((int(product["id"]), quantity, price_minor))
                total_minor += quantity * price_minor

            try:
                cursor = connection.execute(
                    """
                    INSERT INTO purchase_orders(order_no, supplier_id, status, comment, total_minor, created_at, updated_at)
                    VALUES (?, ?, 'ordered', ?, ?, ?, ?)
                    """,
                    (order_no, supplier["id"], comment.strip(), total_minor, now, now),
                )
            except Exception as exc:
                if "UNIQUE" in str(exc).upper():
                    raise ValueError(f"Закупка {order_no} уже существует") from exc
                raise
            order_id = int(cursor.lastrowid)
            connection.executemany(
                """
                INSERT INTO purchase_order_items(order_id, product_id, quantity, purchase_price_minor, received_quantity)
                VALUES (?, ?, ?, ?, 0)
                """,
                [(order_id, product_id, qty, price) for product_id, qty, price in normalized],
            )
        return self.get_purchase_order(order_no)

    def update_purchase_order(
        self,
        *,
        order_no: str,
        supplier_code: str,
        items: list[dict[str, Any]],
        comment: str = "",
    ) -> dict[str, Any]:
        order_no = order_no.strip().upper()
        supplier_code = supplier_code.strip().upper()
        if not items:
            raise ValueError("В закупке должна быть хотя бы одна позиция")
        now = utc_now()
        with self.db.transaction() as connection:
            order = connection.execute(
                "SELECT id, status FROM purchase_orders WHERE order_no = ? COLLATE NOCASE",
                (order_no,),
            ).fetchone()
            if order is None:
                raise ValueError(f"Закупка {order_no} не найдена")
            if order["status"] != "ordered":
                raise ValueError("Редактировать можно только закупку в статусе ordered")
            supplier = connection.execute(
                "SELECT id, is_active FROM suppliers WHERE code = ? COLLATE NOCASE",
                (supplier_code,),
            ).fetchone()
            if supplier is None:
                raise ValueError(f"Поставщик {supplier_code} не найден")
            if not supplier["is_active"]:
                raise ValueError(f"Поставщик {supplier_code} неактивен")
            normalized: list[tuple[int, int, int]] = []
            total_minor = 0
            seen_skus: set[str] = set()
            for item in items:
                sku = str(item.get("sku", "")).strip().upper()
                quantity = int(item.get("quantity", 0))
                if not sku:
                    raise ValueError("SKU позиции обязателен")
                if sku in seen_skus:
                    raise ValueError(f"SKU {sku} повторяется в закупке")
                seen_skus.add(sku)
                if quantity <= 0:
                    raise ValueError(f"Количество для {sku} должно быть больше нуля")
                product = connection.execute(
                    "SELECT id, is_active, purchase_price_minor FROM products WHERE sku = ? COLLATE NOCASE",
                    (sku,),
                ).fetchone()
                if product is None or not product["is_active"]:
                    raise ValueError(f"Активный товар {sku} не найден")
                raw_price = item.get("purchase_price")
                price_minor = price_to_minor(raw_price) if raw_price not in (None, "") else int(product["purchase_price_minor"])
                normalized.append((int(product["id"]), quantity, price_minor))
                total_minor += quantity * price_minor
            connection.execute(
                "UPDATE purchase_orders SET supplier_id = ?, comment = ?, total_minor = ?, updated_at = ? WHERE id = ?",
                (supplier["id"], comment.strip(), total_minor, now, order["id"]),
            )
            connection.execute("DELETE FROM purchase_order_items WHERE order_id = ?", (order["id"],))
            connection.executemany(
                """
                INSERT INTO purchase_order_items(order_id, product_id, quantity, purchase_price_minor, received_quantity)
                VALUES (?, ?, ?, ?, 0)
                """,
                [(order["id"], pid, qty, price) for pid, qty, price in normalized],
            )
        return self.get_purchase_order(order_no)

    def cancel_purchase_order(self, order_no: str) -> dict[str, Any]:
        order_no = order_no.strip().upper()
        with self.db.transaction() as connection:
            row = connection.execute(
                "SELECT id, status FROM purchase_orders WHERE order_no = ? COLLATE NOCASE", (order_no,)
            ).fetchone()
            if row is None:
                raise ValueError(f"Закупка {order_no} не найдена")
            if row["status"] == "received":
                raise ValueError("Принятую закупку нельзя отменить")
            if row["status"] != "cancelled":
                connection.execute(
                    "UPDATE purchase_orders SET status = 'cancelled', updated_at = ? WHERE id = ?",
                    (utc_now(), row["id"]),
                )
        return self.get_purchase_order(order_no)

    def get_purchase_order(self, order_no: str) -> dict[str, Any]:
        with self.db.connect() as connection:
            row = connection.execute(
                """
                SELECT po.*, s.code AS supplier_code, s.name AS supplier_name
                FROM purchase_orders po JOIN suppliers s ON s.id = po.supplier_id
                WHERE po.order_no = ? COLLATE NOCASE
                """,
                (order_no.strip(),),
            ).fetchone()
            if row is None:
                raise ValueError(f"Закупка {order_no.strip()} не найдена")
            items = connection.execute(
                """
                SELECT p.sku, p.name, i.quantity, i.received_quantity, i.purchase_price_minor
                FROM purchase_order_items i JOIN products p ON p.id = i.product_id
                WHERE i.order_id = ? ORDER BY i.id
                """,
                (row["id"],),
            ).fetchall()
        return {
            "id": int(row["id"]),
            "order_no": str(row["order_no"]),
            "supplier_code": str(row["supplier_code"]),
            "supplier_name": str(row["supplier_name"]),
            "status": str(row["status"]),
            "comment": str(row["comment"]),
            "total": minor_to_price(int(row["total_minor"])),
            "created_at": str(row["created_at"]),
            "received_at": row["received_at"],
            "items": [
                {
                    "sku": str(i["sku"]), "name": str(i["name"]),
                    "quantity": int(i["quantity"]), "received_quantity": int(i["received_quantity"]),
                    "purchase_price": minor_to_price(int(i["purchase_price_minor"])),
                }
                for i in items
            ],
        }

    def list_purchase_orders(self, *, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        params: list[Any] = []
        where = ""
        if status:
            status = status.strip().casefold()
            if status not in PURCHASE_STATUSES:
                raise ValueError("Статус закупки: ordered, received или cancelled")
            where = "WHERE po.status = ?"
            params.append(status)
        params.append(limit)
        with self.db.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT po.order_no, po.status, po.total_minor, po.created_at, po.received_at,
                       s.code AS supplier_code, s.name AS supplier_name,
                       COUNT(i.id) AS item_count
                FROM purchase_orders po
                JOIN suppliers s ON s.id = po.supplier_id
                LEFT JOIN purchase_order_items i ON i.order_id = po.id
                {where}
                GROUP BY po.id
                ORDER BY po.id DESC LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            {
                "order_no": str(r["order_no"]), "status": str(r["status"]),
                "supplier_code": str(r["supplier_code"]), "supplier_name": str(r["supplier_name"]),
                "total": minor_to_price(int(r["total_minor"])), "item_count": int(r["item_count"]),
                "created_at": str(r["created_at"]), "received_at": r["received_at"],
            }
            for r in rows
        ]

    def receive_purchase_order(self, order_no: str) -> dict[str, Any]:
        order_no = order_no.strip().upper()
        now = utc_now()
        with self.db.transaction() as connection:
            order = connection.execute(
                """
                SELECT po.id, po.status, s.name AS supplier_name
                FROM purchase_orders po JOIN suppliers s ON s.id = po.supplier_id
                WHERE po.order_no = ? COLLATE NOCASE
                """,
                (order_no,),
            ).fetchone()
            if order is None:
                raise ValueError(f"Закупка {order_no} не найдена")
            if order["status"] == "received":
                raise ValueError(f"Закупка {order_no} уже принята")
            if order["status"] == "cancelled":
                raise ValueError(f"Закупка {order_no} отменена")
            items = connection.execute(
                """
                SELECT i.id AS item_id, i.product_id, i.quantity, i.received_quantity,
                       i.purchase_price_minor, p.stock, p.price_minor
                FROM purchase_order_items i JOIN products p ON p.id = i.product_id
                WHERE i.order_id = ? ORDER BY i.id
                """,
                (order["id"],),
            ).fetchall()
            for item in items:
                remaining = int(item["quantity"]) - int(item["received_quantity"])
                if remaining <= 0:
                    continue
                after = int(item["stock"]) + remaining
                connection.execute(
                    "UPDATE products SET stock = ?, purchase_price_minor = ?, supplier = ?, updated_at = ? WHERE id = ?",
                    (after, item["purchase_price_minor"], order["supplier_name"], now, item["product_id"]),
                )
                main_id = int(connection.execute(
                    "SELECT id FROM warehouses WHERE code = 'MAIN' COLLATE NOCASE"
                ).fetchone()[0])
                connection.execute(
                    "INSERT OR IGNORE INTO warehouse_stocks(warehouse_id, product_id, quantity, updated_at) VALUES (?, ?, 0, ?)",
                    (main_id, item["product_id"], now),
                )
                connection.execute(
                    "UPDATE warehouse_stocks SET quantity = quantity + ?, updated_at = ? WHERE warehouse_id = ? AND product_id = ?",
                    (remaining, now, main_id, item["product_id"]),
                )
                connection.execute(
                    """
                    INSERT INTO stock_movements(product_id, delta, quantity_after, movement_type, reason,
                        document_ref, comment, unit_price_minor, unit_cost_minor, created_at)
                    VALUES (?, ?, ?, 'receipt', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item["product_id"], remaining, after, "Приход по закупке", order_no,
                        f"Поставщик: {order['supplier_name']}", item["price_minor"], item["purchase_price_minor"], now,
                    ),
                )
                connection.execute(
                    "UPDATE purchase_order_items SET received_quantity = quantity WHERE id = ?",
                    (item["item_id"],),
                )
            connection.execute(
                "UPDATE purchase_orders SET status = 'received', received_at = ?, updated_at = ? WHERE id = ?",
                (now, now, order["id"]),
            )
        return self.get_purchase_order(order_no)

    def create_sales_order(
        self,
        *,
        order_no: str,
        customer_name: str,
        items: list[dict[str, Any]],
        comment: str = "",
        customer_code: str | None = None,
    ) -> dict[str, Any]:
        order_no = order_no.strip().upper()
        if not order_no:
            raise ValueError("Номер заказа обязателен")
        if not items:
            raise ValueError("В заказе должна быть хотя бы одна позиция")
        now = utc_now()
        with self.db.transaction() as connection:
            customer_id: int | None = None
            resolved_customer_name = customer_name.strip()
            if customer_code and customer_code.strip():
                customer = connection.execute(
                    "SELECT id, name, is_active FROM customers WHERE code = ? COLLATE NOCASE",
                    (customer_code.strip().upper(),),
                ).fetchone()
                if customer is None:
                    raise ValueError(f"Клиент {customer_code.strip().upper()} не найден")
                if not customer["is_active"]:
                    raise ValueError(f"Клиент {customer_code.strip().upper()} неактивен")
                customer_id = int(customer["id"])
                resolved_customer_name = str(customer["name"])
            if not resolved_customer_name:
                raise ValueError("Клиент или название клиента обязательно")
            normalized: list[tuple[int, int, int, int]] = []
            revenue_minor = 0
            cost_minor = 0
            seen_skus: set[str] = set()
            for item in items:
                sku = str(item.get("sku", "")).strip().upper()
                quantity = int(item.get("quantity", 0))
                if sku in seen_skus:
                    raise ValueError(f"SKU {sku} повторяется в заказе")
                seen_skus.add(sku)
                if quantity <= 0:
                    raise ValueError(f"Количество для {sku or 'позиции'} должно быть больше нуля")
                product = connection.execute(
                    """
                    SELECT id, price_minor, purchase_price_minor, is_active
                    FROM products WHERE sku = ? COLLATE NOCASE
                    """,
                    (sku,),
                ).fetchone()
                if product is None or not product["is_active"]:
                    raise ValueError(f"Активный товар {sku} не найден")
                raw_price = item.get("unit_price")
                unit_price_minor = price_to_minor(raw_price) if raw_price is not None else int(product["price_minor"])
                unit_cost_minor = int(product["purchase_price_minor"])
                normalized.append((int(product["id"]), quantity, unit_price_minor, unit_cost_minor))
                revenue_minor += quantity * unit_price_minor
                cost_minor += quantity * unit_cost_minor
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO sales_orders(order_no, customer_name, customer_id, status, comment, revenue_minor, cost_minor, created_at, updated_at)
                    VALUES (?, ?, ?, 'new', ?, ?, ?, ?, ?)
                    """,
                    (order_no, resolved_customer_name, customer_id, comment.strip(), revenue_minor, cost_minor, now, now),
                )
            except Exception as exc:
                if "UNIQUE" in str(exc).upper():
                    raise ValueError(f"Заказ {order_no} уже существует") from exc
                raise
            order_id = int(cursor.lastrowid)
            connection.executemany(
                """
                INSERT INTO sales_order_items(order_id, product_id, quantity, unit_price_minor, unit_cost_minor, fulfilled_quantity)
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                [(order_id, pid, qty, price, cost) for pid, qty, price, cost in normalized],
            )
        return self.get_sales_order(order_no)

    def update_sales_order(
        self,
        *,
        order_no: str,
        customer_name: str,
        items: list[dict[str, Any]],
        comment: str = "",
        customer_code: str | None = None,
    ) -> dict[str, Any]:
        order_no = order_no.strip().upper()
        if not items:
            raise ValueError("В заказе должна быть хотя бы одна позиция")
        now = utc_now()
        with self.db.transaction() as connection:
            order = connection.execute(
                "SELECT id, status FROM sales_orders WHERE order_no = ? COLLATE NOCASE", (order_no,)
            ).fetchone()
            if order is None:
                raise ValueError(f"Заказ {order_no} не найден")
            if order["status"] != "new":
                raise ValueError("Редактировать можно только заказ в статусе new")
            customer_id: int | None = None
            resolved_customer_name = customer_name.strip()
            if customer_code and customer_code.strip():
                customer = connection.execute(
                    "SELECT id, name, is_active FROM customers WHERE code = ? COLLATE NOCASE",
                    (customer_code.strip().upper(),),
                ).fetchone()
                if customer is None:
                    raise ValueError(f"Клиент {customer_code.strip().upper()} не найден")
                if not customer["is_active"]:
                    raise ValueError(f"Клиент {customer_code.strip().upper()} неактивен")
                customer_id = int(customer["id"])
                resolved_customer_name = str(customer["name"])
            if not resolved_customer_name:
                raise ValueError("Клиент или название клиента обязательно")
            normalized: list[tuple[int, int, int, int]] = []
            revenue_minor = 0
            cost_minor = 0
            seen_skus: set[str] = set()
            for item in items:
                sku = str(item.get("sku", "")).strip().upper()
                quantity = int(item.get("quantity", 0))
                if not sku:
                    raise ValueError("SKU позиции обязателен")
                if sku in seen_skus:
                    raise ValueError(f"SKU {sku} повторяется в заказе")
                seen_skus.add(sku)
                if quantity <= 0:
                    raise ValueError(f"Количество для {sku} должно быть больше нуля")
                product = connection.execute(
                    "SELECT id, price_minor, purchase_price_minor, is_active FROM products WHERE sku = ? COLLATE NOCASE",
                    (sku,),
                ).fetchone()
                if product is None or not product["is_active"]:
                    raise ValueError(f"Активный товар {sku} не найден")
                raw_price = item.get("unit_price")
                unit_price_minor = price_to_minor(raw_price) if raw_price not in (None, "") else int(product["price_minor"])
                unit_cost_minor = int(product["purchase_price_minor"])
                normalized.append((int(product["id"]), quantity, unit_price_minor, unit_cost_minor))
                revenue_minor += quantity * unit_price_minor
                cost_minor += quantity * unit_cost_minor
            connection.execute(
                "UPDATE sales_orders SET customer_name = ?, customer_id = ?, comment = ?, revenue_minor = ?, cost_minor = ?, updated_at = ? WHERE id = ?",
                (resolved_customer_name, customer_id, comment.strip(), revenue_minor, cost_minor, now, order["id"]),
            )
            connection.execute("DELETE FROM sales_order_items WHERE order_id = ?", (order["id"],))
            connection.executemany(
                """
                INSERT INTO sales_order_items(order_id, product_id, quantity, unit_price_minor, unit_cost_minor, fulfilled_quantity)
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                [(order["id"], pid, qty, price, cost) for pid, qty, price, cost in normalized],
            )
        return self.get_sales_order(order_no)

    def cancel_sales_order(self, order_no: str) -> dict[str, Any]:
        order_no = order_no.strip().upper()
        with self.db.transaction() as connection:
            row = connection.execute(
                "SELECT id, status FROM sales_orders WHERE order_no = ? COLLATE NOCASE", (order_no,)
            ).fetchone()
            if row is None:
                raise ValueError(f"Заказ {order_no} не найден")
            if row["status"] == "completed":
                raise ValueError("Завершённый заказ нельзя отменить")
            fulfilled = int(connection.execute(
                "SELECT COALESCE(SUM(fulfilled_quantity),0) FROM sales_order_items WHERE order_id = ?",
                (row["id"],),
            ).fetchone()[0] or 0)
            if fulfilled:
                raise ValueError("Нельзя отменить заказ после частичной отгрузки")
            if row["status"] != "cancelled":
                connection.execute("UPDATE sales_order_items SET reserved_quantity = 0 WHERE order_id = ?", (row["id"],))
                connection.execute(
                    "UPDATE sales_orders SET status = 'cancelled', reserved_at = NULL, processing_at = NULL, updated_at = ? WHERE id = ?",
                    (utc_now(), row["id"]),
                )
        return self.get_sales_order(order_no)

    def get_sales_order(self, order_no: str) -> dict[str, Any]:
        with self.db.connect() as connection:
            row = connection.execute(
                """
                SELECT so.*, c.code AS customer_code
                FROM sales_orders so LEFT JOIN customers c ON c.id = so.customer_id
                WHERE so.order_no = ? COLLATE NOCASE
                """,
                (order_no.strip(),),
            ).fetchone()
            if row is None:
                raise ValueError(f"Заказ {order_no.strip()} не найден")
            items = connection.execute(
                """
                SELECT p.sku, p.name, i.quantity, i.fulfilled_quantity, i.reserved_quantity, i.unit_price_minor, i.unit_cost_minor
                FROM sales_order_items i JOIN products p ON p.id = i.product_id
                WHERE i.order_id = ? ORDER BY i.id
                """,
                (row["id"],),
            ).fetchall()
        revenue = minor_to_price(int(row["revenue_minor"]))
        cost = minor_to_price(int(row["cost_minor"]))
        return {
            "id": int(row["id"]), "order_no": str(row["order_no"]),
            "customer_name": str(row["customer_name"]), "customer_code": row["customer_code"],
            "status": str(row["status"]), "comment": str(row["comment"]), "revenue": revenue, "cost": cost,
            "gross_profit": round(revenue - cost, 2), "created_at": str(row["created_at"]),
            "reserved_at": row["reserved_at"], "processing_at": row["processing_at"],
            "completed_at": row["completed_at"],
            "items": [
                {
                    "sku": str(i["sku"]), "name": str(i["name"]), "quantity": int(i["quantity"]),
                    "reserved_quantity": int(i["reserved_quantity"]),
                    "fulfilled_quantity": int(i["fulfilled_quantity"]),
                    "unit_price": minor_to_price(int(i["unit_price_minor"])),
                    "unit_cost": minor_to_price(int(i["unit_cost_minor"])),
                }
                for i in items
            ],
        }

    def list_sales_orders(self, *, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        params: list[Any] = []
        where = ""
        if status:
            status = status.strip().casefold()
            if status not in SALES_STATUSES:
                raise ValueError("Статус заказа: new, reserved, processing, completed или cancelled")
            where = "WHERE so.status = ?"
            params.append(status)
        params.append(limit)
        with self.db.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT so.*, c.code AS customer_code, COUNT(i.id) AS item_count,
                       COALESCE(SUM(i.reserved_quantity),0) AS reserved_units,
                       COALESCE(SUM(i.fulfilled_quantity),0) AS fulfilled_units
                FROM sales_orders so
                LEFT JOIN sales_order_items i ON i.order_id = so.id
                LEFT JOIN customers c ON c.id = so.customer_id
                {where} GROUP BY so.id ORDER BY so.id DESC LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            {
                "order_no": str(r["order_no"]), "customer_name": str(r["customer_name"]),
                "customer_code": r["customer_code"], "status": str(r["status"]),
                "reserved_units": int(r["reserved_units"] or 0), "fulfilled_units": int(r["fulfilled_units"] or 0),
                "revenue": minor_to_price(int(r["revenue_minor"])),
                "cost": minor_to_price(int(r["cost_minor"])),
                "gross_profit": round(minor_to_price(int(r["revenue_minor"] - r["cost_minor"])), 2),
                "item_count": int(r["item_count"]), "created_at": str(r["created_at"]),
                "completed_at": r["completed_at"],
            }
            for r in rows
        ]

    def complete_sales_order(self, order_no: str) -> dict[str, Any]:
        """Complete an order atomically while respecting reservations from other orders."""
        order_no = order_no.strip().upper()
        now = utc_now()
        with self.db.transaction() as connection:
            order = connection.execute(
                "SELECT id, status FROM sales_orders WHERE order_no = ? COLLATE NOCASE", (order_no,)
            ).fetchone()
            if order is None:
                raise ValueError(f"Заказ {order_no} не найден")
            if order["status"] == "completed":
                raise ValueError(f"Заказ {order_no} уже завершён")
            if order["status"] == "cancelled":
                raise ValueError(f"Заказ {order_no} отменён")
            items = connection.execute(
                """
                SELECT i.id AS item_id, i.product_id, i.quantity, i.fulfilled_quantity, i.reserved_quantity,
                       i.unit_price_minor, i.unit_cost_minor, p.sku, p.stock,
                       COALESCE((SELECT ws.quantity FROM warehouse_stocks ws JOIN warehouses w ON w.id=ws.warehouse_id
                                 WHERE ws.product_id=p.id AND w.code='MAIN' COLLATE NOCASE),0) AS main_stock
                FROM sales_order_items i JOIN products p ON p.id=i.product_id
                WHERE i.order_id=? ORDER BY i.id
                """,
                (order["id"],),
            ).fetchall()
            for item in items:
                remaining = int(item["quantity"]) - int(item["fulfilled_quantity"])
                other_reserved = int(connection.execute(
                    """SELECT COALESCE(SUM(si.reserved_quantity),0)
                       FROM sales_order_items si JOIN sales_orders so ON so.id=si.order_id
                       WHERE si.product_id=? AND si.order_id<>? AND so.status IN ('reserved','processing')""",
                    (item["product_id"], order["id"]),
                ).fetchone()[0] or 0)
                available = int(item["main_stock"]) - other_reserved
                if remaining > available:
                    raise ValueError(
                        f"Недостаточно товара {item['sku']} на MAIN для заказа {order_no}: "
                        f"нужно {remaining}, доступно {available}"
                    )
            main_id = int(connection.execute(
                "SELECT id FROM warehouses WHERE code='MAIN' COLLATE NOCASE"
            ).fetchone()[0])
            for item in items:
                remaining = int(item["quantity"]) - int(item["fulfilled_quantity"])
                if remaining <= 0:
                    continue
                after = int(item["stock"]) - remaining
                connection.execute("UPDATE products SET stock=?,updated_at=? WHERE id=?", (after, now, item["product_id"]))
                connection.execute(
                    "UPDATE warehouse_stocks SET quantity=quantity-?,updated_at=? WHERE warehouse_id=? AND product_id=?",
                    (remaining, now, main_id, item["product_id"]),
                )
                connection.execute(
                    """INSERT INTO stock_movements(product_id,delta,quantity_after,movement_type,reason,document_ref,comment,unit_price_minor,unit_cost_minor,created_at)
                       VALUES (?,?,?,'sale','Продажа по заказу',?,'',?,?,?)""",
                    (item["product_id"], -remaining, after, order_no, item["unit_price_minor"], item["unit_cost_minor"], now),
                )
                connection.execute(
                    "UPDATE sales_order_items SET fulfilled_quantity=quantity,reserved_quantity=0 WHERE id=?",
                    (item["item_id"],),
                )
            connection.execute(
                "UPDATE sales_orders SET status='completed',completed_at=?,processing_at=COALESCE(processing_at,?),updated_at=? WHERE id=?",
                (now, now, now, order["id"]),
            )
        return self.get_sales_order(order_no)

    def sales_analytics(self, *, days: int = 30) -> dict[str, Any]:
        """Commercial analytics based only on completed customer orders.

        Manual warehouse movements (sale/return) remain operational stock history and
        must not affect financial KPIs unless they belong to a completed sales order.
        This keeps units, revenue and cost on the same accounting basis.
        """
        days = max(1, min(int(days), 3650))
        since = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()
        with self.db.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    COALESCE(SUM(i.fulfilled_quantity), 0) AS units_net,
                    COALESCE(SUM(i.fulfilled_quantity * i.unit_price_minor), 0) AS revenue_minor,
                    COALESCE(SUM(i.fulfilled_quantity * i.unit_cost_minor), 0) AS cost_minor
                FROM sales_orders so
                JOIN sales_order_items i ON i.order_id = so.id
                WHERE so.status = 'completed' AND so.completed_at >= ?
                """,
                (since,),
            ).fetchone()
            orders_count = int(connection.execute(
                "SELECT COUNT(*) FROM sales_orders WHERE status='completed' AND completed_at >= ?", (since,)
            ).fetchone()[0])
            top = connection.execute(
                """
                SELECT p.sku, p.name,
                       COALESCE(SUM(i.fulfilled_quantity), 0) AS units,
                       COALESCE(SUM(i.fulfilled_quantity * i.unit_price_minor), 0) AS revenue_minor
                FROM sales_orders so
                JOIN sales_order_items i ON i.order_id = so.id
                JOIN products p ON p.id = i.product_id
                WHERE so.status = 'completed' AND so.completed_at >= ?
                GROUP BY p.id
                HAVING units > 0
                ORDER BY revenue_minor DESC
                LIMIT 5
                """,
                (since,),
            ).fetchall()
        revenue = minor_to_price(int(row["revenue_minor"] or 0))
        cost = minor_to_price(int(row["cost_minor"] or 0))
        profit = round(revenue - cost, 2)
        margin = round((profit / revenue * 100), 2) if revenue else 0.0
        return {
            "days": days,
            "orders_count": orders_count,
            "units_net": int(row["units_net"] or 0),
            "revenue": revenue,
            "cost": cost,
            "gross_profit": profit,
            "gross_margin_percent": margin,
            "top_products": [
                {
                    "sku": str(r["sku"]), "name": str(r["name"]), "units": int(r["units"]),
                    "revenue": minor_to_price(int(r["revenue_minor"])),
                }
                for r in top
            ],
        }

    def dashboard(self, *, days: int = 7) -> dict[str, Any]:
        analytics = self.sales_analytics(days=days)
        with self.db.connect() as connection:
            inv = connection.execute(
                """
                SELECT COUNT(*) AS products_total,
                       COALESCE(SUM(stock),0) AS units,
                       COALESCE(SUM(price_minor*stock),0) AS retail_minor,
                       COALESCE(SUM(purchase_price_minor*stock),0) AS cost_minor,
                       SUM(CASE WHEN is_active=1 AND stock<=min_stock THEN 1 ELSE 0 END) AS low_count
                FROM products
                """
            ).fetchone()
            suppliers = int(connection.execute("SELECT COUNT(*) FROM suppliers WHERE is_active=1").fetchone()[0])
            open_purchase = connection.execute(
                "SELECT COUNT(*) AS cnt, COALESCE(SUM(total_minor),0) AS total FROM purchase_orders WHERE status='ordered'"
            ).fetchone()
            open_sales = int(connection.execute("SELECT COUNT(*) FROM sales_orders WHERE status IN ('new','reserved','processing')").fetchone()[0])
        return {
            "days": int(days),
            "products_total": int(inv["products_total"] or 0),
            "units_in_stock": int(inv["units"] or 0),
            "inventory_retail_value": minor_to_price(int(inv["retail_minor"] or 0)),
            "inventory_cost_value": minor_to_price(int(inv["cost_minor"] or 0)),
            "low_stock_products": int(inv["low_count"] or 0),
            "active_suppliers": suppliers,
            "open_purchase_orders": int(open_purchase["cnt"] or 0),
            "open_purchase_total": minor_to_price(int(open_purchase["total"] or 0)),
            "open_sales_orders": open_sales,
            "sales": analytics,
        }
