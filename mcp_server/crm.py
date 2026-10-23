from __future__ import annotations

from typing import Any

from mcp_server.database import Database
from mcp_server.repository import minor_to_price, utc_now


class CustomerRepository:
    """Customers/counterparties and their commercial history."""

    def __init__(self, database: Database) -> None:
        self.db = database

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "code": str(row["code"]),
            "name": str(row["name"]),
            "contact_name": str(row["contact_name"]),
            "phone": str(row["phone"]),
            "email": str(row["email"]),
            "address": str(row["address"]),
            "comment": str(row["comment"]),
            "is_active": bool(row["is_active"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def create_customer(
        self,
        *,
        code: str,
        name: str,
        contact_name: str = "",
        phone: str = "",
        email: str = "",
        address: str = "",
        comment: str = "",
    ) -> dict[str, Any]:
        code = code.strip().upper()
        name = name.strip()
        if not code:
            raise ValueError("Код клиента обязателен")
        if not name:
            raise ValueError("Название клиента обязательно")
        now = utc_now()
        try:
            with self.db.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO customers(code, name, contact_name, phone, email, address, comment,
                                          is_active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (code, name, contact_name.strip(), phone.strip(), email.strip(), address.strip(), comment.strip(), now, now),
                )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise ValueError(f"Клиент с кодом {code} уже существует") from exc
            raise
        return self.get_customer(code)

    def update_customer(
        self,
        *,
        code: str,
        name: str | None = None,
        contact_name: str | None = None,
        phone: str | None = None,
        email: str | None = None,
        address: str | None = None,
        comment: str | None = None,
        is_active: bool | None = None,
    ) -> dict[str, Any]:
        code = code.strip().upper()
        changes: list[str] = []
        values: list[Any] = []
        if name is not None:
            value = name.strip()
            if not value:
                raise ValueError("Название клиента обязательно")
            changes.append("name = ?")
            values.append(value)
        for field, value in (
            ("contact_name", contact_name), ("phone", phone), ("email", email),
            ("address", address), ("comment", comment),
        ):
            if value is not None:
                changes.append(f"{field} = ?")
                values.append(value.strip())
        if is_active is not None:
            changes.append("is_active = ?")
            values.append(1 if is_active else 0)
        if not changes:
            return self.get_customer(code)
        changes.append("updated_at = ?")
        values.extend([utc_now(), code])
        with self.db.transaction() as connection:
            cur = connection.execute(
                f"UPDATE customers SET {', '.join(changes)} WHERE code = ? COLLATE NOCASE",
                values,
            )
            if cur.rowcount == 0:
                raise ValueError(f"Клиент {code} не найден")
        return self.get_customer(code)

    def get_customer(self, code: str) -> dict[str, Any]:
        code = code.strip().upper()
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT * FROM customers WHERE code = ? COLLATE NOCASE", (code,)
            ).fetchone()
            if row is None:
                raise ValueError(f"Клиент {code} не найден")
            stats = connection.execute(
                """
                SELECT COUNT(*) AS orders_count,
                       COALESCE(SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END),0) AS completed_orders,
                       COALESCE(SUM(CASE WHEN status='completed' THEN revenue_minor ELSE 0 END),0) AS revenue_minor,
                       COALESCE(SUM(CASE WHEN status='completed' THEN cost_minor ELSE 0 END),0) AS cost_minor,
                       MAX(created_at) AS last_order_at
                FROM sales_orders WHERE customer_id = ?
                """,
                (row["id"],),
            ).fetchone()
        result = self._row(row)
        revenue = minor_to_price(int(stats["revenue_minor"] or 0))
        cost = minor_to_price(int(stats["cost_minor"] or 0))
        result.update({
            "orders_count": int(stats["orders_count"] or 0),
            "completed_orders": int(stats["completed_orders"] or 0),
            "revenue": revenue,
            "gross_profit": round(revenue - cost, 2),
            "last_order_at": stats["last_order_at"],
        })
        return result

    def list_customers(self, *, query: str = "", active_only: bool = True, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        params: list[Any] = []
        clauses: list[str] = []
        if active_only:
            clauses.append("c.is_active = 1")
        if query.strip():
            q = f"%{query.strip()}%"
            clauses.append("(c.code LIKE ? COLLATE NOCASE OR c.name LIKE ? COLLATE NOCASE OR c.phone LIKE ? OR c.email LIKE ? COLLATE NOCASE)")
            params.extend([q, q, q, q])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self.db.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT c.*,
                       COUNT(so.id) AS orders_count,
                       COALESCE(SUM(CASE WHEN so.status='completed' THEN so.revenue_minor ELSE 0 END),0) AS revenue_minor
                FROM customers c
                LEFT JOIN sales_orders so ON so.customer_id = c.id
                {where}
                GROUP BY c.id
                ORDER BY c.name COLLATE NOCASE
                LIMIT ?
                """,
                params,
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = self._row(row)
            item["orders_count"] = int(row["orders_count"] or 0)
            item["revenue"] = minor_to_price(int(row["revenue_minor"] or 0))
            result.append(item)
        return result

    def customer_orders(self, code: str, *, limit: int = 50) -> list[dict[str, Any]]:
        code = code.strip().upper()
        with self.db.connect() as connection:
            customer = connection.execute("SELECT id FROM customers WHERE code = ? COLLATE NOCASE", (code,)).fetchone()
            if customer is None:
                raise ValueError(f"Клиент {code} не найден")
            rows = connection.execute(
                """
                SELECT order_no, status, revenue_minor, cost_minor, created_at, completed_at
                FROM sales_orders WHERE customer_id = ? ORDER BY id DESC LIMIT ?
                """,
                (customer["id"], max(1, min(int(limit), 500))),
            ).fetchall()
        return [
            {
                "order_no": str(r["order_no"]), "status": str(r["status"]),
                "revenue": minor_to_price(int(r["revenue_minor"])),
                "gross_profit": minor_to_price(int(r["revenue_minor"] - r["cost_minor"])),
                "created_at": str(r["created_at"]), "completed_at": r["completed_at"],
            }
            for r in rows
        ]


class OrderWorkflowRepository:
    """Reservations and controlled order fulfilment on the MAIN warehouse."""

    ACTIVE_RESERVATION_STATUSES = ("reserved", "processing")

    def __init__(self, database: Database) -> None:
        self.db = database

    @staticmethod
    def _main_id(connection: Any) -> int:
        row = connection.execute("SELECT id FROM warehouses WHERE code='MAIN' COLLATE NOCASE").fetchone()
        if row is None:
            raise ValueError("Склад MAIN не найден")
        return int(row[0])

    def _order_items(self, connection: Any, order_id: int) -> list[Any]:
        return connection.execute(
            """
            SELECT i.id AS item_id, i.product_id, i.quantity, i.fulfilled_quantity,
                   i.reserved_quantity, i.unit_price_minor, i.unit_cost_minor,
                   p.sku, p.name, p.stock,
                   COALESCE(ws.quantity,0) AS main_stock
            FROM sales_order_items i
            JOIN products p ON p.id=i.product_id
            LEFT JOIN warehouses w ON w.code='MAIN' COLLATE NOCASE
            LEFT JOIN warehouse_stocks ws ON ws.warehouse_id=w.id AND ws.product_id=p.id
            WHERE i.order_id=? ORDER BY i.id
            """,
            (order_id,),
        ).fetchall()

    def _other_reserved(self, connection: Any, product_id: int, order_id: int) -> int:
        row = connection.execute(
            """
            SELECT COALESCE(SUM(i.reserved_quantity),0)
            FROM sales_order_items i JOIN sales_orders so ON so.id=i.order_id
            WHERE i.product_id=? AND i.order_id<>? AND so.status IN ('reserved','processing')
            """,
            (product_id, order_id),
        ).fetchone()
        return int(row[0] or 0)

    def availability(self, sku: str) -> dict[str, Any]:
        sku = sku.strip().upper()
        with self.db.connect() as connection:
            row = connection.execute(
                """
                SELECT p.id,p.sku,p.name,p.stock,COALESCE(ws.quantity,0) AS main_stock
                FROM products p
                LEFT JOIN warehouses w ON w.code='MAIN' COLLATE NOCASE
                LEFT JOIN warehouse_stocks ws ON ws.warehouse_id=w.id AND ws.product_id=p.id
                WHERE p.sku=? COLLATE NOCASE
                """,
                (sku,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Товар {sku} не найден")
            reserved = int(connection.execute(
                """SELECT COALESCE(SUM(i.reserved_quantity),0)
                   FROM sales_order_items i JOIN sales_orders so ON so.id=i.order_id
                   WHERE i.product_id=? AND so.status IN ('reserved','processing')""",
                (row["id"],),
            ).fetchone()[0] or 0)
        main_stock = int(row["main_stock"])
        return {
            "sku": str(row["sku"]), "name": str(row["name"]), "physical_stock": int(row["stock"]),
            "main_stock": main_stock, "reserved": reserved, "available": max(0, main_stock - reserved),
        }

    def reserve(self, order_no: str) -> dict[str, Any]:
        order_no = order_no.strip().upper()
        now = utc_now()
        with self.db.transaction() as connection:
            order = connection.execute("SELECT id,status FROM sales_orders WHERE order_no=? COLLATE NOCASE", (order_no,)).fetchone()
            if order is None:
                raise ValueError(f"Заказ {order_no} не найден")
            if order["status"] == "reserved":
                return self.order_state(order_no)
            if order["status"] != "new":
                raise ValueError("Резервировать можно только заказ в статусе new")
            items = self._order_items(connection, int(order["id"]))
            for item in items:
                remaining = int(item["quantity"]) - int(item["fulfilled_quantity"])
                other_reserved = self._other_reserved(connection, int(item["product_id"]), int(order["id"]))
                available = int(item["main_stock"]) - other_reserved
                if remaining > available:
                    raise ValueError(
                        f"Недостаточно доступного товара {item['sku']}: нужно {remaining}, доступно {available} "
                        f"(физически {item['main_stock']}, зарезервировано другими {other_reserved})"
                    )
            for item in items:
                remaining = int(item["quantity"]) - int(item["fulfilled_quantity"])
                connection.execute("UPDATE sales_order_items SET reserved_quantity=? WHERE id=?", (remaining, item["item_id"]))
            connection.execute(
                "UPDATE sales_orders SET status='reserved', reserved_at=?, updated_at=? WHERE id=?",
                (now, now, order["id"]),
            )
        return self.order_state(order_no)

    def release(self, order_no: str) -> dict[str, Any]:
        order_no = order_no.strip().upper()
        with self.db.transaction() as connection:
            order = connection.execute("SELECT id,status FROM sales_orders WHERE order_no=? COLLATE NOCASE", (order_no,)).fetchone()
            if order is None:
                raise ValueError(f"Заказ {order_no} не найден")
            if order["status"] not in {"reserved", "processing"}:
                raise ValueError("Снять резерв можно только с зарезервированного заказа")
            fulfilled = int(connection.execute("SELECT COALESCE(SUM(fulfilled_quantity),0) FROM sales_order_items WHERE order_id=?", (order["id"],)).fetchone()[0] or 0)
            if fulfilled:
                raise ValueError("Нельзя снять резерв после частичной отгрузки")
            connection.execute("UPDATE sales_order_items SET reserved_quantity=0 WHERE order_id=?", (order["id"],))
            connection.execute(
                "UPDATE sales_orders SET status='new', reserved_at=NULL, processing_at=NULL, updated_at=? WHERE id=?",
                (utc_now(), order["id"]),
            )
        return self.order_state(order_no)

    def start_processing(self, order_no: str) -> dict[str, Any]:
        order_no = order_no.strip().upper()
        now = utc_now()
        with self.db.transaction() as connection:
            row = connection.execute("SELECT id,status FROM sales_orders WHERE order_no=? COLLATE NOCASE", (order_no,)).fetchone()
            if row is None:
                raise ValueError(f"Заказ {order_no} не найден")
            if row["status"] == "processing":
                return self.order_state(order_no)
            if row["status"] != "reserved":
                raise ValueError("В обработку можно перевести только зарезервированный заказ")
            connection.execute("UPDATE sales_orders SET status='processing',processing_at=?,updated_at=? WHERE id=?", (now, now, row["id"]))
        return self.order_state(order_no)

    def ship(self, order_no: str, items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        order_no = order_no.strip().upper()
        now = utc_now()
        with self.db.transaction() as connection:
            order = connection.execute("SELECT id,status FROM sales_orders WHERE order_no=? COLLATE NOCASE", (order_no,)).fetchone()
            if order is None:
                raise ValueError(f"Заказ {order_no} не найден")
            if order["status"] not in {"reserved", "processing"}:
                raise ValueError("Отгружать можно только зарезервированный/обрабатываемый заказ")
            current = self._order_items(connection, int(order["id"]))
            by_sku = {str(x["sku"]).upper(): x for x in current}
            if items is None:
                requested = {sku: int(x["reserved_quantity"]) for sku, x in by_sku.items() if int(x["reserved_quantity"]) > 0}
            else:
                requested: dict[str, int] = {}
                for raw in items:
                    sku = str(raw.get("sku", "")).strip().upper()
                    qty = int(raw.get("quantity", 0))
                    if sku not in by_sku:
                        raise ValueError(f"SKU {sku} отсутствует в заказе")
                    if qty <= 0:
                        raise ValueError(f"Количество для {sku} должно быть больше нуля")
                    requested[sku] = requested.get(sku, 0) + qty
            if not requested:
                raise ValueError("Нет товара для отгрузки")
            main_id = self._main_id(connection)
            for sku, qty in requested.items():
                item = by_sku[sku]
                if qty > int(item["reserved_quantity"]):
                    raise ValueError(f"Для {sku} зарезервировано только {item['reserved_quantity']} ед.")
                if qty > int(item["main_stock"]):
                    raise ValueError(f"На MAIN для {sku} физически доступно только {item['main_stock']} ед.")
            for sku, qty in requested.items():
                item = by_sku[sku]
                after = int(item["stock"]) - qty
                connection.execute("UPDATE products SET stock=?,updated_at=? WHERE id=?", (after, now, item["product_id"]))
                connection.execute(
                    "UPDATE warehouse_stocks SET quantity=quantity-?,updated_at=? WHERE warehouse_id=? AND product_id=?",
                    (qty, now, main_id, item["product_id"]),
                )
                connection.execute(
                    """
                    INSERT INTO stock_movements(product_id,delta,quantity_after,movement_type,reason,document_ref,comment,
                                                unit_price_minor,unit_cost_minor,created_at)
                    VALUES (?,?,?,'sale','Отгрузка по заказу',?,'частичная/полная отгрузка',?,?,?)
                    """,
                    (item["product_id"], -qty, after, order_no, item["unit_price_minor"], item["unit_cost_minor"], now),
                )
                connection.execute(
                    "UPDATE sales_order_items SET fulfilled_quantity=fulfilled_quantity+?,reserved_quantity=reserved_quantity-? WHERE id=?",
                    (qty, qty, item["item_id"]),
                )
            totals = connection.execute(
                "SELECT COALESCE(SUM(quantity),0),COALESCE(SUM(fulfilled_quantity),0),COALESCE(SUM(reserved_quantity),0) FROM sales_order_items WHERE order_id=?",
                (order["id"],),
            ).fetchone()
            total_qty, fulfilled_qty, reserved_qty = map(int, totals)
            if fulfilled_qty >= total_qty:
                connection.execute(
                    "UPDATE sales_orders SET status='completed',completed_at=?,processing_at=COALESCE(processing_at,?),updated_at=? WHERE id=?",
                    (now, now, now, order["id"]),
                )
            else:
                connection.execute(
                    "UPDATE sales_orders SET status='processing',processing_at=COALESCE(processing_at,?),updated_at=? WHERE id=?",
                    (now, now, order["id"]),
                )
        return self.order_state(order_no)

    def order_state(self, order_no: str) -> dict[str, Any]:
        order_no = order_no.strip().upper()
        with self.db.connect() as connection:
            order = connection.execute(
                """SELECT so.*,c.code AS customer_code,c.name AS customer_account_name
                   FROM sales_orders so LEFT JOIN customers c ON c.id=so.customer_id
                   WHERE so.order_no=? COLLATE NOCASE""",
                (order_no,),
            ).fetchone()
            if order is None:
                raise ValueError(f"Заказ {order_no} не найден")
            items = connection.execute(
                """
                SELECT p.sku,p.name,i.quantity,i.fulfilled_quantity,i.reserved_quantity,
                       i.unit_price_minor,i.unit_cost_minor
                FROM sales_order_items i JOIN products p ON p.id=i.product_id
                WHERE i.order_id=? ORDER BY i.id
                """,
                (order["id"],),
            ).fetchall()
        revenue = minor_to_price(int(order["revenue_minor"]))
        cost = minor_to_price(int(order["cost_minor"]))
        return {
            "order_no": str(order["order_no"]), "customer_name": str(order["customer_name"]),
            "customer_code": order["customer_code"], "status": str(order["status"]),
            "comment": str(order["comment"]), "revenue": revenue, "cost": cost,
            "gross_profit": round(revenue-cost, 2), "reserved_at": order["reserved_at"],
            "processing_at": order["processing_at"], "completed_at": order["completed_at"],
            "items": [
                {"sku":str(x["sku"]),"name":str(x["name"]),"quantity":int(x["quantity"]),
                 "reserved_quantity":int(x["reserved_quantity"]),"fulfilled_quantity":int(x["fulfilled_quantity"]),
                 "unit_price":minor_to_price(int(x["unit_price_minor"])),"unit_cost":minor_to_price(int(x["unit_cost_minor"]))}
                for x in items
            ],
        }
