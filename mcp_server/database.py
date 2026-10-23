from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'Без категории',
    price_minor INTEGER NOT NULL CHECK(price_minor >= 0),
    purchase_price_minor INTEGER NOT NULL DEFAULT 0 CHECK(purchase_price_minor >= 0),
    stock INTEGER NOT NULL DEFAULT 0 CHECK(stock >= 0),
    min_stock INTEGER NOT NULL DEFAULT 0 CHECK(min_stock >= 0),
    description TEXT NOT NULL DEFAULT '',
    supplier TEXT NOT NULL DEFAULT '',
    barcode TEXT NOT NULL DEFAULT '',
    unit TEXT NOT NULL DEFAULT 'шт.',
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_products_name ON products(name);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_products_stock ON products(stock, min_stock);

CREATE TABLE IF NOT EXISTS stock_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    delta INTEGER NOT NULL,
    quantity_after INTEGER NOT NULL CHECK(quantity_after >= 0),
    movement_type TEXT NOT NULL DEFAULT 'adjustment',
    reason TEXT NOT NULL,
    document_ref TEXT NOT NULL DEFAULT '',
    comment TEXT NOT NULL DEFAULT '',
    unit_price_minor INTEGER NOT NULL DEFAULT 0 CHECK(unit_price_minor >= 0),
    unit_cost_minor INTEGER NOT NULL DEFAULT 0 CHECK(unit_cost_minor >= 0),
    created_at TEXT NOT NULL,
    FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_movements_product_id ON stock_movements(product_id);
CREATE INDEX IF NOT EXISTS idx_movements_created_at ON stock_movements(created_at DESC);
CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL,
    contact_name TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    comment TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_suppliers_name ON suppliers(name);

CREATE TABLE IF NOT EXISTS purchase_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_no TEXT NOT NULL UNIQUE COLLATE NOCASE,
    supplier_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'ordered',
    comment TEXT NOT NULL DEFAULT '',
    total_minor INTEGER NOT NULL DEFAULT 0 CHECK(total_minor >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    received_at TEXT,
    FOREIGN KEY(supplier_id) REFERENCES suppliers(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_purchase_orders_status ON purchase_orders(status);
CREATE INDEX IF NOT EXISTS idx_purchase_orders_supplier ON purchase_orders(supplier_id);

CREATE TABLE IF NOT EXISTS purchase_order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    purchase_price_minor INTEGER NOT NULL CHECK(purchase_price_minor >= 0),
    received_quantity INTEGER NOT NULL DEFAULT 0 CHECK(received_quantity >= 0),
    FOREIGN KEY(order_id) REFERENCES purchase_orders(id) ON DELETE CASCADE,
    FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_purchase_items_order ON purchase_order_items(order_id);

CREATE TABLE IF NOT EXISTS sales_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_no TEXT NOT NULL UNIQUE COLLATE NOCASE,
    customer_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new',
    comment TEXT NOT NULL DEFAULT '',
    revenue_minor INTEGER NOT NULL DEFAULT 0 CHECK(revenue_minor >= 0),
    cost_minor INTEGER NOT NULL DEFAULT 0 CHECK(cost_minor >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_sales_orders_status ON sales_orders(status);
CREATE INDEX IF NOT EXISTS idx_sales_orders_completed_at ON sales_orders(completed_at);

CREATE TABLE IF NOT EXISTS sales_order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    unit_price_minor INTEGER NOT NULL CHECK(unit_price_minor >= 0),
    unit_cost_minor INTEGER NOT NULL CHECK(unit_cost_minor >= 0),
    fulfilled_quantity INTEGER NOT NULL DEFAULT 0 CHECK(fulfilled_quantity >= 0),
    FOREIGN KEY(order_id) REFERENCES sales_orders(id) ON DELETE CASCADE,
    FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_sales_items_order ON sales_order_items(order_id);

CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL,
    contact_name TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    comment TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_customers_name ON customers(name);
CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone);
CREATE INDEX IF NOT EXISTS idx_customers_email ON customers(email);

CREATE TABLE IF NOT EXISTS warehouses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS warehouse_stocks (
    warehouse_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0 CHECK(quantity >= 0),
    updated_at TEXT NOT NULL,
    PRIMARY KEY(warehouse_id, product_id),
    FOREIGN KEY(warehouse_id) REFERENCES warehouses(id) ON DELETE CASCADE,
    FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS warehouse_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    from_warehouse_id INTEGER,
    to_warehouse_id INTEGER,
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    reason TEXT NOT NULL DEFAULT '',
    document_ref TEXT NOT NULL DEFAULT '',
    actor_user_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE RESTRICT,
    FOREIGN KEY(from_warehouse_id) REFERENCES warehouses(id) ON DELETE RESTRICT,
    FOREIGN KEY(to_warehouse_id) REFERENCES warehouses(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_warehouse_stocks_product ON warehouse_stocks(product_id);
CREATE INDEX IF NOT EXISTS idx_warehouse_movements_created ON warehouse_movements(created_at DESC);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_user_id TEXT NOT NULL DEFAULT '',
    actor_role TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT '',
    entity_id TEXT NOT NULL DEFAULT '',
    details_json TEXT NOT NULL DEFAULT '{}',
    success INTEGER NOT NULL DEFAULT 1 CHECK(success IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_log(actor_user_id);
"""


class Database:
    """SQLite wrapper with WAL, safe writes and backwards-compatible migrations."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.create_function(
            "CASEFOLD", 1, lambda value: value.casefold() if value else "", deterministic=True
        )
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    @staticmethod
    def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
        return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}

    def _migrate_schema(self, connection: sqlite3.Connection) -> None:
        product_columns = self._columns(connection, "products")
        product_migrations = {
            "purchase_price_minor": "INTEGER NOT NULL DEFAULT 0",
            "supplier": "TEXT NOT NULL DEFAULT ''",
            "barcode": "TEXT NOT NULL DEFAULT ''",
            "unit": "TEXT NOT NULL DEFAULT 'шт.'",
        }
        for column, definition in product_migrations.items():
            if column not in product_columns:
                connection.execute(f"ALTER TABLE products ADD COLUMN {column} {definition}")

        movement_columns = self._columns(connection, "stock_movements")
        movement_migrations = {
            "movement_type": "TEXT NOT NULL DEFAULT 'adjustment'",
            "document_ref": "TEXT NOT NULL DEFAULT ''",
            "comment": "TEXT NOT NULL DEFAULT ''",
            "unit_price_minor": "INTEGER NOT NULL DEFAULT 0",
            "unit_cost_minor": "INTEGER NOT NULL DEFAULT 0",
        }
        for column, definition in movement_migrations.items():
            if column not in movement_columns:
                connection.execute(f"ALTER TABLE stock_movements ADD COLUMN {column} {definition}")

        connection.execute("CREATE INDEX IF NOT EXISTS idx_products_barcode ON products(barcode)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_movements_type ON stock_movements(movement_type)")

        # v1.7.0: CRM customers + reservation/order workflow.
        sales_columns = self._columns(connection, "sales_orders")
        sales_migrations = {
            "customer_id": "INTEGER REFERENCES customers(id) ON DELETE SET NULL",
            "reserved_at": "TEXT",
            "processing_at": "TEXT",
        }
        for column, definition in sales_migrations.items():
            if column not in sales_columns:
                connection.execute(f"ALTER TABLE sales_orders ADD COLUMN {column} {definition}")

        sales_item_columns = self._columns(connection, "sales_order_items")
        if "reserved_quantity" not in sales_item_columns:
            connection.execute("ALTER TABLE sales_order_items ADD COLUMN reserved_quantity INTEGER NOT NULL DEFAULT 0")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_sales_orders_customer ON sales_orders(customer_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_sales_orders_status_v170 ON sales_orders(status)")

        # v1.4.0: migrate the legacy single stock into the default MAIN warehouse.
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        connection.execute(
            """
            INSERT OR IGNORE INTO warehouses(code, name, location, is_active, created_at, updated_at)
            VALUES ('MAIN', 'Основной склад', '', 1, ?, ?)
            """,
            (now, now),
        )
        main_id = connection.execute(
            "SELECT id FROM warehouses WHERE code = 'MAIN' COLLATE NOCASE"
        ).fetchone()[0]
        connection.execute(
            """
            INSERT OR IGNORE INTO warehouse_stocks(warehouse_id, product_id, quantity, updated_at)
            SELECT ?, id, stock, ? FROM products
            """,
            (main_id, now),
        )

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(SCHEMA)
            self._migrate_schema(connection)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock:
            connection = self.connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
