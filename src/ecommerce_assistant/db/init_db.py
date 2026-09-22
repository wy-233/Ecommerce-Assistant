from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "ecommerce_assistant.db"


def _connect(db_path: str | Path) -> sqlite3.Connection:
    target = Path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _column_names(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row[1] for row in rows}


def _ensure_table_columns(conn: sqlite3.Connection, table_name: str, columns: list[tuple[str, str]]) -> None:
    existing = _column_names(conn, table_name)
    for column_name, definition in columns:
        if column_name not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def _ensure_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_order_id_unique ON orders(order_id);
        CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(order_status);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_order_items_order_sku_unique ON order_items(order_id, sku, product_name);
        CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items(order_id);
        CREATE INDEX IF NOT EXISTS idx_order_items_sku ON order_items(sku);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_inventory_sku_unique ON inventory(sku);
        CREATE INDEX IF NOT EXISTS idx_inventory_warehouse ON inventory(warehouse_id, warehouse_name);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_shipments_shipment_id_unique ON shipments(shipment_id);
        CREATE INDEX IF NOT EXISTS idx_shipments_order_id ON shipments(order_id);
        CREATE INDEX IF NOT EXISTS idx_shipments_tracking_number ON shipments(tracking_number);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tracking_events_identity_unique ON tracking_events(shipment_id, event_time, event_status, location, description);
        CREATE INDEX IF NOT EXISTS idx_tracking_events_shipment_id ON tracking_events(shipment_id);
        CREATE INDEX IF NOT EXISTS idx_tracking_events_event_time ON tracking_events(event_time);
        CREATE INDEX IF NOT EXISTS idx_chat_threads_thread_id ON chat_threads(thread_id);
        CREATE INDEX IF NOT EXISTS idx_chat_messages_thread_id ON chat_messages(thread_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_articles_slug_unique ON knowledge_articles(slug);
        """
    )


def init_db(db_path: str | Path | None = None, *, seed_demo: bool = False) -> str:
    """Create the SQLite schema for the e-commerce workbench.

    The function is safe to rerun and preserves legacy tables/columns when older
    project versions already created them.
    """
    target = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    conn = _connect(target)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL,
                customer_name_masked TEXT NOT NULL DEFAULT '***',
                customer_country TEXT NOT NULL DEFAULT 'CN',
                order_status TEXT NOT NULL DEFAULT 'pending',
                payment_status TEXT NOT NULL DEFAULT 'pending',
                fulfillment_status TEXT NOT NULL DEFAULT 'pending',
                currency TEXT NOT NULL DEFAULT 'CNY',
                total_amount REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(order_id)
            );

            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                product_name TEXT,
                quantity INTEGER NOT NULL DEFAULT 1,
                unit_price REAL NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'CNY',
                FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sku TEXT NOT NULL,
                product_name TEXT,
                warehouse_id TEXT,
                warehouse_name TEXT,
                on_hand INTEGER NOT NULL DEFAULT 0,
                reserved INTEGER NOT NULL DEFAULT 0,
                available INTEGER NOT NULL DEFAULT 0,
                safety_stock INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(sku)
            );

            CREATE TABLE IF NOT EXISTS shipments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shipment_id TEXT NOT NULL,
                order_id TEXT NOT NULL,
                carrier TEXT,
                tracking_number TEXT,
                shipping_status TEXT NOT NULL DEFAULT 'pending',
                shipped_at TEXT,
                estimated_delivery_at TEXT,
                delivered_at TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(shipment_id),
                UNIQUE(tracking_number),
                FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS tracking_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shipment_id TEXT NOT NULL,
                event_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                event_status TEXT NOT NULL DEFAULT 'created',
                location TEXT,
                description TEXT,
                FOREIGN KEY (shipment_id) REFERENCES shipments(shipment_id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS chat_threads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                user_id TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(thread_id)
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (thread_id) REFERENCES chat_threads(thread_id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS knowledge_articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT NOT NULL,
                category TEXT NOT NULL,
                title TEXT,
                content TEXT NOT NULL,
                source TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(slug)
            );
            """
        )

        _ensure_table_columns(
            conn,
            "orders",
            [
                ("customer_name_masked", "TEXT NOT NULL DEFAULT '***'"),
                ("customer_country", "TEXT NOT NULL DEFAULT 'CN'"),
                ("order_status", "TEXT NOT NULL DEFAULT 'pending'"),
                ("payment_status", "TEXT NOT NULL DEFAULT 'pending'"),
                ("fulfillment_status", "TEXT NOT NULL DEFAULT 'pending'"),
                ("currency", "TEXT NOT NULL DEFAULT 'CNY'"),
                ("total_amount", "REAL NOT NULL DEFAULT 0"),
            ],
        )
        _ensure_table_columns(
            conn,
            "order_items",
            [
                ("order_id", "TEXT NOT NULL"),
                ("sku", "TEXT NOT NULL"),
                ("product_name", "TEXT"),
                ("quantity", "INTEGER NOT NULL DEFAULT 1"),
                ("unit_price", "REAL NOT NULL DEFAULT 0"),
                ("currency", "TEXT NOT NULL DEFAULT 'CNY'"),
            ],
        )
        _ensure_table_columns(
            conn,
            "inventory",
            [
                ("sku", "TEXT NOT NULL"),
                ("product_name", "TEXT"),
                ("warehouse_id", "TEXT"),
                ("warehouse_name", "TEXT"),
                ("on_hand", "INTEGER NOT NULL DEFAULT 0"),
                ("reserved", "INTEGER NOT NULL DEFAULT 0"),
                ("available", "INTEGER NOT NULL DEFAULT 0"),
                ("safety_stock", "INTEGER NOT NULL DEFAULT 0"),
                ("updated_at", "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"),
            ],
        )
        _ensure_table_columns(
            conn,
            "shipments",
            [
                ("shipment_id", "TEXT NOT NULL"),
                ("order_id", "TEXT NOT NULL"),
                ("carrier", "TEXT"),
                ("tracking_number", "TEXT"),
                ("shipping_status", "TEXT NOT NULL DEFAULT 'pending'"),
                ("shipped_at", "TEXT"),
                ("estimated_delivery_at", "TEXT"),
                ("delivered_at", "TEXT"),
                ("updated_at", "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"),
            ],
        )
        _ensure_table_columns(
            conn,
            "tracking_events",
            [
                ("shipment_id", "TEXT NOT NULL"),
                ("event_time", "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"),
                ("event_status", "TEXT NOT NULL DEFAULT 'created'"),
                ("location", "TEXT"),
                ("description", "TEXT"),
            ],
        )
        _ensure_table_columns(
            conn,
            "chat_threads",
            [
                ("thread_id", "TEXT NOT NULL"),
                ("user_id", "TEXT"),
                ("created_at", "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"),
                ("updated_at", "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"),
            ],
        )
        _ensure_table_columns(
            conn,
            "chat_messages",
            [
                ("thread_id", "TEXT NOT NULL"),
                ("role", "TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user', 'assistant', 'system'))"),
                ("content", "TEXT NOT NULL"),
                ("created_at", "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"),
            ],
        )
        _ensure_table_columns(
            conn,
            "knowledge_articles",
            [
                ("slug", "TEXT NOT NULL"),
                ("category", "TEXT NOT NULL"),
                ("title", "TEXT"),
                ("content", "TEXT NOT NULL"),
                ("source", "TEXT"),
                ("updated_at", "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"),
            ],
        )

        _ensure_indexes(conn)
        conn.commit()

        if seed_demo:
            seed_demo_data(target)
        return str(target)
    finally:
        conn.close()


def seed_demo_data(db_path: str | Path | None = None) -> None:
    """Insert demo rows without overwriting existing ones."""
    target = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    conn = _connect(target)
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO orders (
                order_id, customer_name_masked, customer_country, order_status,
                payment_status, fulfillment_status, currency, total_amount,
                created_at, updated_at
            ) VALUES
                ('1001', 'C***', 'CN', 'in_transit', 'paid', 'fulfilled', 'CNY', 528.00, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                ('1002', 'L***', 'US', 'delivered', 'paid', 'fulfilled', 'USD', 1299.00, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                ('1003', 'A***', 'DE', 'pending_ship', 'paid', 'processing', 'EUR', 799.00, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ;
            """
        )

        conn.execute(
            """
            INSERT OR IGNORE INTO order_items (order_id, sku, product_name, quantity, unit_price, currency)
            VALUES
                ('1001', 'SKU-001', '智能音箱', 1, 299.00, 'CNY'),
                ('1001', 'SKU-002', '蓝牙耳机', 1, 229.00, 'CNY'),
                ('1002', 'SKU-003', '薄款充电器', 2, 59.00, 'USD'),
                ('1003', 'SKU-004', '旅行背包', 1, 799.00, 'EUR')
            ;
            """
        )

        conn.execute(
            """
            INSERT OR IGNORE INTO inventory (sku, product_name, warehouse_id, warehouse_name, on_hand, reserved, available, safety_stock, updated_at)
            VALUES
                ('SKU-001', '智能音箱', 'WH-001', '深圳仓', 24, 2, 22, 5, CURRENT_TIMESTAMP),
                ('SKU-002', '蓝牙耳机', 'WH-001', '深圳仓', 0, 0, 0, 5, CURRENT_TIMESTAMP),
                ('SKU-003', '薄款充电器', 'WH-002', '上海仓', 120, 10, 110, 20, CURRENT_TIMESTAMP),
                ('SKU-004', '旅行背包', 'WH-003', '柏林仓', 9, 1, 8, 3, CURRENT_TIMESTAMP)
            ;
            """
        )

        conn.execute(
            """
            INSERT OR IGNORE INTO shipments (shipment_id, order_id, carrier, tracking_number, shipping_status, shipped_at, estimated_delivery_at, delivered_at, updated_at)
            VALUES
                ('SHIP-1001', '1001', 'DHL', 'DHL123456789', 'in_transit', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL, CURRENT_TIMESTAMP),
                ('SHIP-1002', '1002', 'FedEx', 'FX987654321', 'delivered', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                ('SHIP-1003', '1003', 'UPS', 'UPS456789123', 'pending', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL, CURRENT_TIMESTAMP)
            ;
            """
        )

        conn.execute(
            """
            INSERT OR IGNORE INTO tracking_events (shipment_id, event_time, event_status, location, description)
            VALUES
                ('SHIP-1001', CURRENT_TIMESTAMP, 'picked_up', '深圳仓', '包裹已离开仓库'),
                ('SHIP-1001', CURRENT_TIMESTAMP, 'in_transit', '深圳中转站', '正在中转'),
                ('SHIP-1002', CURRENT_TIMESTAMP, 'delivered', '纽约配送点', '订单已签收'),
                ('SHIP-1003', CURRENT_TIMESTAMP, 'created', '柏林仓', '等待发货')
            ;
            """
        )

        conn.execute(
            """
            INSERT OR IGNORE INTO chat_threads (thread_id, user_id, created_at, updated_at)
            VALUES
                ('demo-thread-001', 'demo-user', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ;
            """
        )

        conn.execute(
            """
            INSERT OR IGNORE INTO chat_messages (thread_id, role, content, created_at)
            VALUES
                ('demo-thread-001', 'user', '订单1001现在到哪里了？', CURRENT_TIMESTAMP),
                ('demo-thread-001', 'assistant', '订单1001正在运输中，当前在深圳中转站。', CURRENT_TIMESTAMP)
            ;
            """
        )

        conn.execute(
            """
            INSERT OR IGNORE INTO knowledge_articles (slug, category, title, content, source, updated_at)
            VALUES
                ('return-policy', 'returns', '退货政策', '退货需要满足商品未使用、未损坏且附带原包装等条件。', 'data/return_policy.md', CURRENT_TIMESTAMP),
                ('shipping-policy', 'shipping', '物流政策', '物流配送通常在3-7个工作日内完成，海外订单可能受清关影响。', 'data/shipping_policy.md', CURRENT_TIMESTAMP)
            ;
            """
        )
        conn.commit()
    finally:
        conn.close()


def get_order_by_id(order_id: str, db_path: str | Path | None = None) -> dict[str, Any] | None:
    target = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    conn = _connect(target)
    try:
        row = conn.execute(
            "SELECT * FROM orders WHERE order_id = ?",
            (str(order_id),),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_inventory_by_sku(sku: str, db_path: str | Path | None = None) -> dict[str, Any] | None:
    target = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    conn = _connect(target)
    try:
        row = conn.execute(
            "SELECT * FROM inventory WHERE sku = ?",
            (str(sku).strip().upper(),),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_shipment_by_order_id(order_id: str, db_path: str | Path | None = None) -> dict[str, Any] | None:
    target = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    conn = _connect(target)
    try:
        row = conn.execute(
            "SELECT * FROM shipments WHERE order_id = ? ORDER BY updated_at DESC LIMIT 1",
            (str(order_id),),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_tracking_events(shipment_id: str, db_path: str | Path | None = None) -> list[dict[str, Any]]:
    target = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    conn = _connect(target)
    try:
        rows = conn.execute(
            "SELECT * FROM tracking_events WHERE shipment_id = ? ORDER BY event_time ASC",
            (str(shipment_id),),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_order_items_by_order_id(order_id: str, db_path: str | Path | None = None) -> list[dict[str, Any]]:
    target = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    conn = _connect(target)
    try:
        rows = conn.execute(
            "SELECT * FROM order_items WHERE order_id = ? ORDER BY id ASC",
            (str(order_id),),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def ensure_chat_thread(thread_id: str, user_id: str | None = None, db_path: str | Path | None = None) -> None:
    target = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    conn = _connect(target)
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO chat_threads (thread_id, user_id, created_at, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (str(thread_id), str(user_id) if user_id else None),
        )
        if user_id:
            conn.execute(
                "UPDATE chat_threads SET user_id = ?, updated_at = CURRENT_TIMESTAMP WHERE thread_id = ?",
                (str(user_id), str(thread_id)),
            )
        conn.commit()
    finally:
        conn.close()


def append_chat_message(
    thread_id: str,
    role: str,
    content: str,
    user_id: str | None = None,
    db_path: str | Path | None = None,
) -> None:
    target = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    conn = _connect(target)
    try:
        ensure_chat_thread(thread_id, user_id=user_id, db_path=target)
        conn.execute(
            """
            INSERT INTO chat_messages (thread_id, role, content, created_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (str(thread_id), str(role), str(content)),
        )
        conn.execute(
            "UPDATE chat_threads SET updated_at = CURRENT_TIMESTAMP WHERE thread_id = ?",
            (str(thread_id),),
        )
        conn.commit()
    finally:
        conn.close()


def get_chat_history(thread_id: str, limit: int = 12, db_path: str | Path | None = None) -> list[dict[str, str]]:
    target = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    conn = _connect(target)
    try:
        rows = conn.execute(
            """
            SELECT role, content
            FROM chat_messages
            WHERE thread_id = ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (str(thread_id), int(limit)),
        ).fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in rows]
    finally:
        conn.close()


if __name__ == "__main__":
    print(init_db(seed_demo=True))
