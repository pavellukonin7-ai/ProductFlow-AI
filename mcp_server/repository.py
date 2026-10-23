from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from mcp_server.database import Database
from mcp_server.models import InventorySummaryOut, MovementOut, ProductOut


MOVEMENT_TYPES = {"receipt", "sale", "return", "writeoff", "adjustment", "initial"}
MOVEMENT_LABELS = {
    "receipt": "Приход",
    "sale": "Продажа",
    "return": "Возврат",
    "writeoff": "Списание",
    "adjustment": "Корректировка",
    "initial": "Начальный остаток",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def price_to_minor(value: float | int | str | Decimal) -> int:
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Цена должна быть числом") from exc
    if amount < 0:
        raise ValueError("Цена не может быть отрицательной")
    return int(amount * 100)


def minor_to_price(value: int) -> float:
    return float((Decimal(value) / Decimal(100)).quantize(Decimal("0.01")))


class ProductRepository:
    def __init__(self, database: Database) -> None:
        self.db = database

    @staticmethod
    def _product_from_row(row: Any) -> ProductOut:
        return ProductOut(
            id=row["id"],
            sku=row["sku"],
            name=row["name"],
            category=row["category"],
            price=minor_to_price(row["price_minor"]),
            purchase_price=minor_to_price(row["purchase_price_minor"]),
            stock=row["stock"],
            min_stock=row["min_stock"],
            description=row["description"],
            supplier=row["supplier"],
            barcode=row["barcode"],
            unit=row["unit"],
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _movement_from_row(row: Any) -> MovementOut:
        return MovementOut(
            id=row["id"],
            sku=row["sku"],
            product_name=row["product_name"],
            delta=row["delta"],
            quantity_after=row["quantity_after"],
            movement_type=row["movement_type"],
            reason=row["reason"],
            document_ref=row["document_ref"],
            comment=row["comment"],
            unit_price=minor_to_price(int(row["unit_price_minor"] or 0)) if "unit_price_minor" in row.keys() else 0.0,
            unit_cost=minor_to_price(int(row["unit_cost_minor"] or 0)) if "unit_cost_minor" in row.keys() else 0.0,
            created_at=row["created_at"],
        )

    def create_product(
        self,
        *,
        sku: str,
        name: str,
        category: str,
        price: float,
        initial_stock: int = 0,
        min_stock: int = 0,
        description: str = "",
        purchase_price: float = 0,
        supplier: str = "",
        barcode: str = "",
        unit: str = "шт.",
    ) -> ProductOut:
        sku = sku.strip().upper()
        name = name.strip()
        category = category.strip() or "Без категории"
        description = description.strip()
        supplier = supplier.strip()
        barcode = barcode.strip()
        unit = unit.strip() or "шт."
        if not sku:
            raise ValueError("SKU обязателен")
        if not name:
            raise ValueError("Название товара обязательно")
        if initial_stock < 0 or min_stock < 0:
            raise ValueError("Остаток и минимальный остаток не могут быть отрицательными")

        now = utc_now()
        price_minor = price_to_minor(price)
        purchase_price_minor = price_to_minor(purchase_price)
        try:
            with self.db.transaction() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO products(
                        sku, name, category, price_minor, purchase_price_minor,
                        stock, min_stock, description, supplier, barcode, unit,
                        is_active, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        sku, name, category, price_minor, purchase_price_minor,
                        initial_stock, min_stock, description, supplier, barcode, unit,
                        now, now,
                    ),
                )
                product_id = int(cursor.lastrowid)
                main_id = int(connection.execute(
                    "SELECT id FROM warehouses WHERE code = 'MAIN' COLLATE NOCASE"
                ).fetchone()[0])
                connection.execute(
                    """
                    INSERT OR REPLACE INTO warehouse_stocks(warehouse_id, product_id, quantity, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (main_id, product_id, initial_stock, now),
                )
                if initial_stock:
                    connection.execute(
                        """
                        INSERT INTO stock_movements(
                            product_id, delta, quantity_after, movement_type,
                            reason, document_ref, comment, created_at
                        ) VALUES (?, ?, ?, 'initial', ?, '', '', ?)
                        """,
                        (product_id, initial_stock, initial_stock, "Начальный остаток", now),
                    )
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise ValueError(f"Товар с SKU {sku} уже существует") from exc
            raise
        return self.get_product(sku)

    def get_product(self, sku: str) -> ProductOut:
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT * FROM products WHERE sku = ? COLLATE NOCASE",
                (sku.strip(),),
            ).fetchone()
        if row is None:
            raise ValueError(f"Товар с SKU {sku.strip()} не найден")
        return self._product_from_row(row)

    def search_products(
        self,
        *,
        query: str = "",
        category: str | None = None,
        in_stock_only: bool = False,
        active_only: bool = True,
        limit: int = 20,
    ) -> list[ProductOut]:
        limit = max(1, min(limit, 5000))
        clauses: list[str] = []
        params: list[Any] = []

        if query.strip():
            needle = f"%{query.strip()}%"
            clauses.append(
                "(CASEFOLD(sku) LIKE CASEFOLD(?) OR CASEFOLD(name) LIKE CASEFOLD(?) "
                "OR CASEFOLD(description) LIKE CASEFOLD(?) OR CASEFOLD(supplier) LIKE CASEFOLD(?) "
                "OR CASEFOLD(barcode) LIKE CASEFOLD(?))"
            )
            params.extend([needle, needle, needle, needle, needle])
        if category and category.strip():
            clauses.append("CASEFOLD(category) = CASEFOLD(?)")
            params.append(category.strip())
        if in_stock_only:
            clauses.append("stock > 0")
        if active_only:
            clauses.append("is_active = 1")

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self.db.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM products {where} ORDER BY name COLLATE NOCASE LIMIT ?",
                params,
            ).fetchall()
        return [self._product_from_row(row) for row in rows]

    def update_product(
        self,
        *,
        sku: str,
        name: str | None = None,
        category: str | None = None,
        price: float | None = None,
        purchase_price: float | None = None,
        min_stock: int | None = None,
        description: str | None = None,
        supplier: str | None = None,
        barcode: str | None = None,
        unit: str | None = None,
        is_active: bool | None = None,
    ) -> ProductOut:
        fields: list[str] = []
        params: list[Any] = []

        if name is not None:
            if not name.strip():
                raise ValueError("Название товара не может быть пустым")
            fields.append("name = ?")
            params.append(name.strip())
        if category is not None:
            fields.append("category = ?")
            params.append(category.strip() or "Без категории")
        if price is not None:
            fields.append("price_minor = ?")
            params.append(price_to_minor(price))
        if purchase_price is not None:
            fields.append("purchase_price_minor = ?")
            params.append(price_to_minor(purchase_price))
        if min_stock is not None:
            if min_stock < 0:
                raise ValueError("Минимальный остаток не может быть отрицательным")
            fields.append("min_stock = ?")
            params.append(min_stock)
        if description is not None:
            fields.append("description = ?")
            params.append(description.strip())
        if supplier is not None:
            fields.append("supplier = ?")
            params.append(supplier.strip())
        if barcode is not None:
            fields.append("barcode = ?")
            params.append(barcode.strip())
        if unit is not None:
            if not unit.strip():
                raise ValueError("Единица измерения не может быть пустой")
            fields.append("unit = ?")
            params.append(unit.strip())
        if is_active is not None:
            fields.append("is_active = ?")
            params.append(int(is_active))

        if not fields:
            raise ValueError("Не переданы поля для изменения")

        fields.append("updated_at = ?")
        params.append(utc_now())
        params.append(sku.strip())
        with self.db.transaction() as connection:
            cursor = connection.execute(
                f"UPDATE products SET {', '.join(fields)} WHERE sku = ? COLLATE NOCASE",
                params,
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Товар с SKU {sku.strip()} не найден")
        return self.get_product(sku)

    def adjust_stock(
        self,
        *,
        sku: str,
        delta: int,
        reason: str,
        movement_type: str = "adjustment",
        document_ref: str = "",
        comment: str = "",
    ) -> ProductOut:
        if delta == 0:
            raise ValueError("Изменение остатка не может быть равно нулю")
        reason = reason.strip()
        if not reason:
            raise ValueError("Укажите причину изменения остатка")
        movement_type = movement_type.strip().casefold() or "adjustment"
        if movement_type not in MOVEMENT_TYPES:
            raise ValueError(
                "Неизвестный тип операции. Используйте receipt, sale, return, writeoff или adjustment"
            )
        now = utc_now()

        with self.db.transaction() as connection:
            row = connection.execute(
                "SELECT id, stock, price_minor, purchase_price_minor FROM products WHERE sku = ? COLLATE NOCASE",
                (sku.strip(),),
            ).fetchone()
            if row is None:
                raise ValueError(f"Товар с SKU {sku.strip()} не найден")
            quantity_after = int(row["stock"]) + delta
            if quantity_after < 0:
                raise ValueError(
                    f"Недостаточно товара: текущий остаток {row['stock']}, изменение {delta}"
                )
            connection.execute(
                "UPDATE products SET stock = ?, updated_at = ? WHERE id = ?",
                (quantity_after, now, row["id"]),
            )
            main_id = int(connection.execute(
                "SELECT id FROM warehouses WHERE code = 'MAIN' COLLATE NOCASE"
            ).fetchone()[0])
            connection.execute(
                "INSERT OR IGNORE INTO warehouse_stocks(warehouse_id, product_id, quantity, updated_at) VALUES (?, ?, ?, ?)",
                (main_id, row["id"], int(row["stock"]), now),
            )
            main_before = int(connection.execute(
                "SELECT quantity FROM warehouse_stocks WHERE warehouse_id = ? AND product_id = ?",
                (main_id, row["id"]),
            ).fetchone()[0])
            main_qty = main_before + delta
            if main_qty < 0:
                raise ValueError(
                    f"Недостаточно товара на основном складе MAIN: доступно {main_before}, изменение {delta}"
                )
            if delta < 0:
                reserved = int(connection.execute(
                    """
                    SELECT COALESCE(SUM(i.reserved_quantity), 0)
                    FROM sales_order_items i JOIN sales_orders so ON so.id = i.order_id
                    WHERE i.product_id = ? AND so.status IN ('reserved','processing')
                    """,
                    (row["id"],),
                ).fetchone()[0] or 0)
                if main_qty < reserved:
                    available = max(0, main_before - reserved)
                    raise ValueError(
                        f"Операция затрагивает резерв заказов: на MAIN {main_before}, "
                        f"зарезервировано {reserved}, доступно без резерва {available}"
                    )
            connection.execute(
                "UPDATE warehouse_stocks SET quantity = ?, updated_at = ? WHERE warehouse_id = ? AND product_id = ?",
                (main_qty, now, main_id, row["id"]),
            )
            connection.execute(
                """
                INSERT INTO stock_movements(
                    product_id, delta, quantity_after, movement_type, reason,
                    document_ref, comment, unit_price_minor, unit_cost_minor, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"], delta, quantity_after, movement_type, reason,
                    document_ref.strip(), comment.strip(),
                    int(row["price_minor"]) if movement_type in {"sale", "return"} else 0,
                    int(row["purchase_price_minor"]) if movement_type in {"sale", "return"} else 0,
                    now,
                ),
            )
        return self.get_product(sku)

    def stock_operation(
        self,
        *,
        sku: str,
        operation: str,
        quantity: int,
        reason: str = "",
        document_ref: str = "",
        comment: str = "",
    ) -> ProductOut:
        operation = operation.strip().casefold()
        if operation not in {"receipt", "sale", "return", "writeoff", "adjustment"}:
            raise ValueError("Операция: receipt, sale, return, writeoff или adjustment")
        if quantity == 0:
            raise ValueError("Количество не может быть равно нулю")
        if operation != "adjustment" and quantity < 0:
            raise ValueError("Для прихода/продажи/возврата/списания укажите положительное количество")

        if operation in {"receipt", "return"}:
            delta = abs(quantity)
        elif operation in {"sale", "writeoff"}:
            delta = -abs(quantity)
        else:
            delta = quantity

        return self.adjust_stock(
            sku=sku,
            delta=delta,
            reason=reason.strip() or MOVEMENT_LABELS[operation],
            movement_type=operation,
            document_ref=document_ref,
            comment=comment,
        )

    def set_stock(
        self,
        *,
        sku: str,
        quantity: int,
        reason: str,
        document_ref: str = "",
        comment: str = "",
    ) -> ProductOut:
        if quantity < 0:
            raise ValueError("Остаток не может быть отрицательным")
        current = self.get_product(sku)
        if quantity == current.stock:
            return current
        return self.adjust_stock(
            sku=sku,
            delta=quantity - current.stock,
            reason=reason,
            movement_type="adjustment",
            document_ref=document_ref,
            comment=comment,
        )

    def low_stock_report(self, *, limit: int = 50) -> list[ProductOut]:
        limit = max(1, min(limit, 5000))
        with self.db.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM products
                WHERE is_active = 1 AND stock <= min_stock
                ORDER BY (min_stock - stock) DESC, name COLLATE NOCASE
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._product_from_row(row) for row in rows]

    def inventory_summary(self) -> InventorySummaryOut:
        with self.db.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS products_total,
                    SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) AS active_products,
                    COUNT(DISTINCT category) AS categories_total,
                    COALESCE(SUM(stock), 0) AS units_in_stock,
                    SUM(CASE WHEN is_active = 1 AND stock <= min_stock THEN 1 ELSE 0 END)
                        AS low_stock_products,
                    COALESCE(SUM(price_minor * stock), 0) AS inventory_value_minor,
                    COALESCE(SUM(purchase_price_minor * stock), 0) AS purchase_value_minor
                FROM products
                """
            ).fetchone()
        retail = minor_to_price(int(row["inventory_value_minor"] or 0))
        purchase = minor_to_price(int(row["purchase_value_minor"] or 0))
        return InventorySummaryOut(
            products_total=int(row["products_total"] or 0),
            active_products=int(row["active_products"] or 0),
            categories_total=int(row["categories_total"] or 0),
            units_in_stock=int(row["units_in_stock"] or 0),
            low_stock_products=int(row["low_stock_products"] or 0),
            inventory_value=retail,
            purchase_value=purchase,
            potential_margin=round(retail - purchase, 2),
        )

    def movement_history(self, *, sku: str | None = None, limit: int = 50) -> list[MovementOut]:
        limit = max(1, min(limit, 1000))
        params: list[Any] = []
        where = ""
        if sku and sku.strip():
            where = "WHERE p.sku = ? COLLATE NOCASE"
            params.append(sku.strip())
        params.append(limit)
        with self.db.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    m.id,
                    p.sku,
                    p.name AS product_name,
                    m.delta,
                    m.quantity_after,
                    m.movement_type,
                    m.reason,
                    m.document_ref,
                    m.comment,
                    m.unit_price_minor,
                    m.unit_cost_minor,
                    m.created_at
                FROM stock_movements m
                JOIN products p ON p.id = m.product_id
                {where}
                ORDER BY m.id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._movement_from_row(row) for row in rows]

    def import_products(self, rows: list[dict[str, Any]], *, update_existing: bool = True) -> dict[str, Any]:
        created = 0
        updated = 0
        errors: list[str] = []
        for index, raw in enumerate(rows, start=2):
            try:
                sku = str(raw.get("sku", "")).strip()
                if not sku:
                    raise ValueError("SKU обязателен")
                try:
                    current = self.get_product(sku)
                except ValueError:
                    current = None

                common = {
                    "name": str(raw.get("name", "")).strip(),
                    "category": str(raw.get("category", "Без категории")).strip() or "Без категории",
                    "price": float(raw.get("price", 0) or 0),
                    "purchase_price": float(raw.get("purchase_price", 0) or 0),
                    "min_stock": int(raw.get("min_stock", 0) or 0),
                    "description": str(raw.get("description", "") or ""),
                    "supplier": str(raw.get("supplier", "") or ""),
                    "barcode": str(raw.get("barcode", "") or ""),
                    "unit": str(raw.get("unit", "шт.") or "шт."),
                }
                stock = int(raw.get("stock", 0) or 0)
                is_active = bool(raw.get("is_active", True))

                if current is None:
                    self.create_product(
                        sku=sku,
                        initial_stock=stock,
                        **common,
                    )
                    if not is_active:
                        self.update_product(sku=sku, is_active=False)
                    created += 1
                elif update_existing:
                    self.update_product(sku=sku, is_active=is_active, **common)
                    if stock != current.stock:
                        self.set_stock(
                            sku=sku,
                            quantity=stock,
                            reason="Импорт каталога",
                            comment="Обновление остатка из файла",
                        )
                    updated += 1
            except Exception as exc:
                errors.append(f"Строка {index}: {exc}")
        return {
            "created": created,
            "updated": updated,
            "errors": errors[:50],
            "errors_total": len(errors),
        }

    def seed_demo_data(self) -> int:
        with self.db.connect() as connection:
            existing = int(connection.execute("SELECT COUNT(*) FROM products").fetchone()[0])
        if existing:
            return 0

        samples = [
            ("LP-KBD-001", "Механическая клавиатура", "Периферия", 8990, 5200, 12, 3),
            ("LP-MSE-002", "Беспроводная мышь", "Периферия", 3490, 1900, 4, 5),
            ("LP-HUB-003", "USB-C хаб 8-в-1", "Аксессуары", 5490, 3100, 0, 2),
        ]
        for sku, name, category, price, purchase_price, stock, min_stock in samples:
            self.create_product(
                sku=sku,
                name=name,
                category=category,
                price=price,
                purchase_price=purchase_price,
                initial_stock=stock,
                min_stock=min_stock,
                description="Стартовая позиция каталога",
                supplier="Демо-поставщик",
            )
        return len(samples)
