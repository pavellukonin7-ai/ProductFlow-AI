from __future__ import annotations

from typing import Any

from mcp_server.database import Database
from mcp_server.repository import utc_now


class WarehouseRepository:
    """Multi-warehouse stock distribution while products.stock remains the aggregate stock."""

    def __init__(self, database: Database) -> None:
        self.db = database

    @staticmethod
    def _warehouse(row: Any) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "code": str(row["code"]),
            "name": str(row["name"]),
            "location": str(row["location"]),
            "is_active": bool(row["is_active"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def create_warehouse(self, *, code: str, name: str, location: str = "") -> dict[str, Any]:
        code = code.strip().upper()
        name = name.strip()
        if not code:
            raise ValueError("Код склада обязателен")
        if not name:
            raise ValueError("Название склада обязательно")
        now = utc_now()
        try:
            with self.db.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO warehouses(code, name, location, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, 1, ?, ?)
                    """,
                    (code, name, location.strip(), now, now),
                )
                warehouse_id = int(connection.execute(
                    "SELECT id FROM warehouses WHERE code = ? COLLATE NOCASE", (code,)
                ).fetchone()[0])
                connection.execute(
                    """
                    INSERT OR IGNORE INTO warehouse_stocks(warehouse_id, product_id, quantity, updated_at)
                    SELECT ?, id, 0, ? FROM products
                    """,
                    (warehouse_id, now),
                )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise ValueError(f"Склад {code} уже существует") from exc
            raise
        return self.get_warehouse(code)

    def get_warehouse(self, code: str) -> dict[str, Any]:
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT * FROM warehouses WHERE code = ? COLLATE NOCASE", (code.strip(),)
            ).fetchone()
        if row is None:
            raise ValueError(f"Склад {code.strip()} не найден")
        return self._warehouse(row)

    def list_warehouses(self, *, active_only: bool = True, limit: int = 100) -> list[dict[str, Any]]:
        where = "WHERE w.is_active = 1" if active_only else ""
        with self.db.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT w.*, COALESCE(SUM(ws.quantity), 0) AS units,
                       SUM(CASE WHEN ws.quantity > 0 THEN 1 ELSE 0 END) AS products_with_stock
                FROM warehouses w
                LEFT JOIN warehouse_stocks ws ON ws.warehouse_id = w.id
                {where}
                GROUP BY w.id ORDER BY w.id LIMIT ?
                """,
                (max(1, min(limit, 1000)),),
            ).fetchall()
        return [
            {
                **self._warehouse(row),
                "units": int(row["units"] or 0),
                "products_with_stock": int(row["products_with_stock"] or 0),
            }
            for row in rows
        ]

    def stock(self, *, warehouse_code: str, query: str = "", limit: int = 100) -> list[dict[str, Any]]:
        warehouse = self.get_warehouse(warehouse_code)
        params: list[Any] = [warehouse["id"]]
        clause = ""
        if query.strip():
            clause = "AND (CASEFOLD(p.sku) LIKE CASEFOLD(?) OR CASEFOLD(p.name) LIKE CASEFOLD(?))"
            needle = f"%{query.strip()}%"
            params.extend([needle, needle])
        params.append(max(1, min(limit, 5000)))
        with self.db.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT p.sku, p.name, p.unit, p.stock AS total_stock,
                       COALESCE(ws.quantity, 0) AS quantity
                FROM products p
                LEFT JOIN warehouse_stocks ws
                  ON ws.product_id = p.id AND ws.warehouse_id = ?
                WHERE p.is_active = 1 {clause}
                ORDER BY p.name COLLATE NOCASE LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            {
                "warehouse_code": warehouse["code"],
                "warehouse_name": warehouse["name"],
                "sku": str(row["sku"]),
                "name": str(row["name"]),
                "unit": str(row["unit"]),
                "quantity": int(row["quantity"]),
                "total_stock": int(row["total_stock"]),
            }
            for row in rows
        ]

    def product_distribution(self, sku: str) -> list[dict[str, Any]]:
        with self.db.connect() as connection:
            product = connection.execute(
                "SELECT id, sku, name, unit, stock FROM products WHERE sku = ? COLLATE NOCASE",
                (sku.strip(),),
            ).fetchone()
            if product is None:
                raise ValueError(f"Товар {sku.strip()} не найден")
            rows = connection.execute(
                """
                SELECT w.code, w.name, w.location, COALESCE(ws.quantity, 0) AS quantity
                FROM warehouses w
                LEFT JOIN warehouse_stocks ws
                  ON ws.warehouse_id = w.id AND ws.product_id = ?
                WHERE w.is_active = 1 ORDER BY w.id
                """,
                (product["id"],),
            ).fetchall()
        return [
            {
                "sku": str(product["sku"]),
                "name": str(product["name"]),
                "unit": str(product["unit"]),
                "total_stock": int(product["stock"]),
                "warehouse_code": str(row["code"]),
                "warehouse_name": str(row["name"]),
                "location": str(row["location"]),
                "quantity": int(row["quantity"]),
            }
            for row in rows
        ]

    def transfer(
        self,
        *,
        sku: str,
        quantity: int,
        from_warehouse: str,
        to_warehouse: str,
        reason: str = "Перемещение между складами",
        document_ref: str = "",
        actor_user_id: str = "",
    ) -> dict[str, Any]:
        if quantity <= 0:
            raise ValueError("Количество перемещения должно быть больше нуля")
        source_code = from_warehouse.strip().upper()
        target_code = to_warehouse.strip().upper()
        if source_code == target_code:
            raise ValueError("Склады отправления и назначения должны отличаться")
        now = utc_now()
        with self.db.transaction() as connection:
            product = connection.execute(
                "SELECT id, sku, name, unit, stock FROM products WHERE sku = ? COLLATE NOCASE AND is_active = 1",
                (sku.strip(),),
            ).fetchone()
            if product is None:
                raise ValueError(f"Активный товар {sku.strip()} не найден")
            source = connection.execute(
                "SELECT id, name, is_active FROM warehouses WHERE code = ? COLLATE NOCASE", (source_code,)
            ).fetchone()
            target = connection.execute(
                "SELECT id, name, is_active FROM warehouses WHERE code = ? COLLATE NOCASE", (target_code,)
            ).fetchone()
            if source is None:
                raise ValueError(f"Склад {source_code} не найден")
            if target is None:
                raise ValueError(f"Склад {target_code} не найден")
            if not source["is_active"] or not target["is_active"]:
                raise ValueError("Перемещение возможно только между активными складами")
            for wid in (source["id"], target["id"]):
                connection.execute(
                    "INSERT OR IGNORE INTO warehouse_stocks(warehouse_id, product_id, quantity, updated_at) VALUES (?, ?, 0, ?)",
                    (wid, product["id"], now),
                )
            current = int(connection.execute(
                "SELECT quantity FROM warehouse_stocks WHERE warehouse_id = ? AND product_id = ?",
                (source["id"], product["id"]),
            ).fetchone()[0])
            if current < quantity:
                raise ValueError(
                    f"Недостаточно товара на складе {source_code}: доступно {current}, требуется {quantity}"
                )
            if source_code == "MAIN":
                reserved = int(connection.execute(
                    """
                    SELECT COALESCE(SUM(i.reserved_quantity), 0)
                    FROM sales_order_items i JOIN sales_orders so ON so.id = i.order_id
                    WHERE i.product_id = ? AND so.status IN ('reserved','processing')
                    """,
                    (product["id"],),
                ).fetchone()[0] or 0)
                if current - quantity < reserved:
                    available = max(0, current - reserved)
                    raise ValueError(
                        f"Перемещение затрагивает резерв заказов: на MAIN {current}, "
                        f"зарезервировано {reserved}, доступно для перемещения {available}"
                    )
            connection.execute(
                "UPDATE warehouse_stocks SET quantity = quantity - ?, updated_at = ? WHERE warehouse_id = ? AND product_id = ?",
                (quantity, now, source["id"], product["id"]),
            )
            connection.execute(
                "UPDATE warehouse_stocks SET quantity = quantity + ?, updated_at = ? WHERE warehouse_id = ? AND product_id = ?",
                (quantity, now, target["id"], product["id"]),
            )
            connection.execute(
                """
                INSERT INTO warehouse_movements(
                    product_id, from_warehouse_id, to_warehouse_id, quantity,
                    reason, document_ref, actor_user_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    product["id"], source["id"], target["id"], quantity,
                    reason.strip() or "Перемещение между складами", document_ref.strip(),
                    str(actor_user_id or ""), now,
                ),
            )
        return {
            "sku": str(product["sku"]),
            "name": str(product["name"]),
            "unit": str(product["unit"]),
            "quantity": quantity,
            "from_warehouse": source_code,
            "to_warehouse": target_code,
            "total_stock": int(product["stock"]),
            "reason": reason.strip() or "Перемещение между складами",
            "document_ref": document_ref.strip(),
        }

    def movements(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self.db.connect() as connection:
            rows = connection.execute(
                """
                SELECT wm.id, p.sku, p.name, wm.quantity, fw.code AS from_code,
                       tw.code AS to_code, wm.reason, wm.document_ref, wm.actor_user_id, wm.created_at
                FROM warehouse_movements wm
                JOIN products p ON p.id = wm.product_id
                LEFT JOIN warehouses fw ON fw.id = wm.from_warehouse_id
                LEFT JOIN warehouses tw ON tw.id = wm.to_warehouse_id
                ORDER BY wm.id DESC LIMIT ?
                """,
                (max(1, min(limit, 500)),),
            ).fetchall()
        return [dict(row) for row in rows]
