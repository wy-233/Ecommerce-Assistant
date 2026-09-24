from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

# 本文件位于 src/ecommerce_assistant/db/，需上溯 4 层才是项目根，
# 否则会解析到 src/data/ 并脚本（data/）各写一个库，造成数据分裂。
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = _PROJECT_ROOT / "data" / "ecommerce_assistant.db"

MASTER_DATA_TABLES = ("products", "warehouses")
BUSINESS_TABLES = ("orders", "order_items", "inventory", "shipments", "tracking_events")
ALL_BUSINESS_TABLES = (*MASTER_DATA_TABLES, *BUSINESS_TABLES)


class SkuReferenceMigrationError(RuntimeError):
    """旧库含孤儿 SKU，无法安全建立 order_items -> inventory 外键。"""


class MasterDataMigrationError(RuntimeError):
    """旧库存数据无法安全迁移到商品/仓库主数据模型。"""


def _open_connection(db_path: str | Path) -> sqlite3.Connection:
    target = Path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _connect(db_path: str | Path) -> sqlite3.Connection:
    return _open_connection(db_path)


@contextmanager
def connect(db_path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """打开 SQLite 连接，正常退出时提交，异常时回滚，**最终必定关闭**。

    注意：`with sqlite3.connect(...) as conn` 的退出钩子只提交/回滚事务，并不会
    关闭连接，直接用会泄漏连接。所有调用方应使用本函数。
    """
    conn = _open_connection(Path(db_path) if db_path is not None else DEFAULT_DB_PATH)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


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
        -- 历史版本由 scripts/init_demo_data.py 额外创建过两个同定义的唯一索引，
        -- 这里显式清理，避免重复索引在每次重建后回流。
        DROP INDEX IF EXISTS idx_order_items_demo_identity;
        DROP INDEX IF EXISTS idx_tracking_events_demo_identity;

        CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_order_id_unique ON orders(order_id);
        CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(order_status);
        CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_orders_is_demo ON orders(is_demo);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_order_items_order_sku_unique ON order_items(order_id, sku, product_name);
        CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items(order_id);
        CREATE INDEX IF NOT EXISTS idx_order_items_sku ON order_items(sku);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_products_sku_unique ON products(sku);
        CREATE INDEX IF NOT EXISTS idx_products_name ON products(product_name);
        CREATE INDEX IF NOT EXISTS idx_products_is_demo ON products(is_demo);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_warehouses_id_unique ON warehouses(warehouse_id);
        CREATE INDEX IF NOT EXISTS idx_warehouses_name ON warehouses(warehouse_name);
        CREATE INDEX IF NOT EXISTS idx_warehouses_is_demo ON warehouses(is_demo);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_inventory_sku_unique ON inventory(sku);
        CREATE INDEX IF NOT EXISTS idx_inventory_warehouse ON inventory(warehouse_id, warehouse_name);
        CREATE INDEX IF NOT EXISTS idx_inventory_status ON inventory(status);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_shipments_shipment_id_unique ON shipments(shipment_id);
        CREATE INDEX IF NOT EXISTS idx_shipments_order_id ON shipments(order_id);
        CREATE INDEX IF NOT EXISTS idx_shipments_tracking_number ON shipments(tracking_number);
        CREATE INDEX IF NOT EXISTS idx_shipments_updated_at ON shipments(updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_shipments_is_demo ON shipments(is_demo);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tracking_events_identity_unique ON tracking_events(shipment_id, event_time, event_status, location, description);
        CREATE INDEX IF NOT EXISTS idx_tracking_events_shipment_id ON tracking_events(shipment_id);
        CREATE INDEX IF NOT EXISTS idx_tracking_events_event_time ON tracking_events(event_time);
        CREATE INDEX IF NOT EXISTS idx_chat_threads_thread_id ON chat_threads(thread_id);
        CREATE INDEX IF NOT EXISTS idx_chat_messages_thread_id ON chat_messages(thread_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_articles_slug_unique ON knowledge_articles(slug);
        """
    )


def _has_inventory_master_foreign_keys(conn: sqlite3.Connection) -> bool:
    foreign_keys = conn.execute("PRAGMA foreign_key_list(inventory)").fetchall()
    has_product = any(
        row[2] == "products" and row[3] == "sku" and row[4] == "sku"
        for row in foreign_keys
    )
    has_warehouse = any(
        row[2] == "warehouses" and row[3] == "warehouse_id" and row[4] == "warehouse_id"
        for row in foreign_keys
    )
    return has_product and has_warehouse


def _backfill_master_data(conn: sqlite3.Connection) -> None:
    """从库存兼容字段回填商品和仓库主数据，重复执行保持幂等。"""
    conn.execute(
        """
        INSERT INTO products (sku, product_name, updated_at, is_demo)
        SELECT sku, product_name, updated_at, is_demo
        FROM inventory
        WHERE sku IS NOT NULL AND TRIM(sku) <> ''
        ON CONFLICT(sku) DO UPDATE SET
            product_name = COALESCE(products.product_name, excluded.product_name),
            updated_at = CASE
                WHEN excluded.updated_at > products.updated_at THEN excluded.updated_at
                ELSE products.updated_at
            END
        """
    )
    conn.execute(
        """
        INSERT INTO warehouses (warehouse_id, warehouse_name, updated_at, is_demo)
        SELECT warehouse_id, MAX(warehouse_name), MAX(updated_at), MAX(is_demo)
        FROM inventory
        WHERE warehouse_id IS NOT NULL AND TRIM(warehouse_id) <> ''
        GROUP BY warehouse_id
        ON CONFLICT(warehouse_id) DO UPDATE SET
            warehouse_name = COALESCE(warehouses.warehouse_name, excluded.warehouse_name),
            updated_at = CASE
                WHEN excluded.updated_at > warehouses.updated_at THEN excluded.updated_at
                ELSE warehouses.updated_at
            END
        """
    )


def _inventory_master_orphans(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT i.id, i.sku, i.warehouse_id,
               CASE WHEN p.sku IS NULL THEN 1 ELSE 0 END AS missing_product,
               CASE
                   WHEN i.warehouse_id IS NOT NULL AND TRIM(i.warehouse_id) <> ''
                        AND w.warehouse_id IS NULL THEN 1
                   ELSE 0
               END AS missing_warehouse
        FROM inventory i
        LEFT JOIN products p ON p.sku = i.sku
        LEFT JOIN warehouses w ON w.warehouse_id = i.warehouse_id
        WHERE p.sku IS NULL
           OR (i.warehouse_id IS NOT NULL AND TRIM(i.warehouse_id) <> '' AND w.warehouse_id IS NULL)
        ORDER BY i.id ASC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _ensure_inventory_master_foreign_keys(conn: sqlite3.Connection) -> None:
    """为旧库库存表补齐主数据外键，同时保留原行 id 和兼容字段。"""
    _backfill_master_data(conn)
    if _has_inventory_master_foreign_keys(conn):
        return

    orphans = _inventory_master_orphans(conn)
    if orphans:
        preview = ", ".join(
            f"id={row['id']} sku={row['sku']} warehouse_id={row['warehouse_id']}"
            for row in orphans[:10]
        )
        raise MasterDataMigrationError(
            f"inventory 存在 {len(orphans)} 条无法映射到商品/仓库主数据的记录：{preview}"
        )

    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN")
        conn.execute("DROP TABLE IF EXISTS inventory__master_fk_migration")
        conn.execute(
            """
            CREATE TABLE inventory__master_fk_migration (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sku TEXT NOT NULL,
                product_name TEXT,
                warehouse_id TEXT,
                warehouse_name TEXT,
                on_hand INTEGER NOT NULL DEFAULT 0,
                reserved INTEGER NOT NULL DEFAULT 0,
                available INTEGER NOT NULL DEFAULT 0,
                safety_stock INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'normal',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                is_demo TEXT NOT NULL DEFAULT 'DEMO',
                UNIQUE(sku),
                FOREIGN KEY (sku) REFERENCES products(sku) ON UPDATE RESTRICT ON DELETE RESTRICT,
                FOREIGN KEY (warehouse_id) REFERENCES warehouses(warehouse_id) ON UPDATE RESTRICT ON DELETE RESTRICT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO inventory__master_fk_migration (
                id, sku, product_name, warehouse_id, warehouse_name,
                on_hand, reserved, available, safety_stock, status, updated_at, is_demo
            )
            SELECT id, sku, product_name, warehouse_id, warehouse_name,
                   on_hand, reserved, available, safety_stock, status, updated_at, is_demo
            FROM inventory
            ORDER BY id ASC
            """
        )
        conn.execute("DROP TABLE inventory")
        conn.execute("ALTER TABLE inventory__master_fk_migration RENAME TO inventory")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def _ensure_master_sync_triggers(conn: sqlite3.Connection) -> None:
    """主数据名称变更时同步兼容快照字段，旧调用方仍能读取一致名称。"""
    conn.executescript(
        """
        CREATE TRIGGER IF NOT EXISTS trg_products_name_to_inventory
        AFTER UPDATE OF product_name ON products
        FOR EACH ROW
        BEGIN
            UPDATE inventory
            SET product_name = NEW.product_name
            WHERE sku = NEW.sku;
        END;

        CREATE TRIGGER IF NOT EXISTS trg_warehouses_name_to_inventory
        AFTER UPDATE OF warehouse_name ON warehouses
        FOR EACH ROW
        BEGIN
            UPDATE inventory
            SET warehouse_name = NEW.warehouse_name
            WHERE warehouse_id = NEW.warehouse_id;
        END;
        """
    )


def _has_order_items_sku_foreign_key(conn: sqlite3.Connection) -> bool:
    return any(
        row[2] == "inventory" and row[3] == "sku" and row[4] == "sku"
        for row in conn.execute("PRAGMA foreign_key_list(order_items)").fetchall()
    )


def _order_item_sku_orphans(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT i.id, i.order_id, i.sku, i.product_name
        FROM order_items i
        LEFT JOIN inventory v ON v.sku = i.sku
        WHERE v.sku IS NULL
        ORDER BY i.id ASC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _ensure_order_items_sku_foreign_key(conn: sqlite3.Connection) -> None:
    """为旧库无损补齐 SKU 外键；存在孤儿时拒绝迁移并保留原表。"""
    if _has_order_items_sku_foreign_key(conn):
        return

    orphans = _order_item_sku_orphans(conn)
    if orphans:
        preview = ", ".join(
            f"id={row['id']} order_id={row['order_id']} sku={row['sku']}"
            for row in orphans[:10]
        )
        suffix = "" if len(orphans) <= 10 else f"，另有 {len(orphans) - 10} 条"
        raise SkuReferenceMigrationError(
            f"order_items 存在 {len(orphans)} 条孤儿 SKU，已中止外键迁移：{preview}{suffix}"
        )

    conn.execute("SAVEPOINT migrate_order_items_sku_fk")
    try:
        conn.execute("DROP TABLE IF EXISTS order_items__sku_fk_migration")
        conn.execute(
            """
            CREATE TABLE order_items__sku_fk_migration (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                product_name TEXT,
                quantity INTEGER NOT NULL DEFAULT 1,
                unit_price REAL NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'CNY',
                is_demo TEXT NOT NULL DEFAULT 'DEMO',
                FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE RESTRICT,
                FOREIGN KEY (sku) REFERENCES inventory(sku) ON UPDATE RESTRICT ON DELETE RESTRICT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO order_items__sku_fk_migration (
                id, order_id, sku, product_name, quantity, unit_price, currency, is_demo
            )
            SELECT id, order_id, sku, product_name, quantity, unit_price, currency, is_demo
            FROM order_items
            ORDER BY id ASC
            """
        )
        conn.execute("DROP TABLE order_items")
        conn.execute("ALTER TABLE order_items__sku_fk_migration RENAME TO order_items")
        conn.execute("RELEASE SAVEPOINT migrate_order_items_sku_fk")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT migrate_order_items_sku_fk")
        conn.execute("RELEASE SAVEPOINT migrate_order_items_sku_fk")
        raise


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
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sku TEXT NOT NULL,
                product_name TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                is_demo TEXT NOT NULL DEFAULT 'DEMO',
                UNIQUE(sku)
            );

            CREATE TABLE IF NOT EXISTS warehouses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                warehouse_id TEXT NOT NULL,
                warehouse_name TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                is_demo TEXT NOT NULL DEFAULT 'DEMO',
                UNIQUE(warehouse_id)
            );

            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL,
                customer_name_masked TEXT NOT NULL DEFAULT '***',
                customer_country TEXT NOT NULL DEFAULT 'CN',
                order_status TEXT NOT NULL DEFAULT 'pending_payment',
                payment_status TEXT NOT NULL DEFAULT 'unpaid',
                fulfillment_status TEXT NOT NULL DEFAULT 'pending',
                currency TEXT NOT NULL DEFAULT 'CNY',
                total_amount REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                is_demo TEXT NOT NULL DEFAULT 'DEMO',
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
                is_demo TEXT NOT NULL DEFAULT 'DEMO',
                FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE RESTRICT,
                FOREIGN KEY (sku) REFERENCES inventory(sku) ON UPDATE RESTRICT ON DELETE RESTRICT
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
                status TEXT NOT NULL DEFAULT 'normal',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                is_demo TEXT NOT NULL DEFAULT 'DEMO',
                UNIQUE(sku),
                FOREIGN KEY (sku) REFERENCES products(sku) ON UPDATE RESTRICT ON DELETE RESTRICT,
                FOREIGN KEY (warehouse_id) REFERENCES warehouses(warehouse_id) ON UPDATE RESTRICT ON DELETE RESTRICT
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
                is_demo TEXT NOT NULL DEFAULT 'DEMO',
                UNIQUE(shipment_id),
                UNIQUE(tracking_number),
                FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS tracking_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shipment_id TEXT NOT NULL,
                event_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                event_status TEXT NOT NULL DEFAULT 'pending',
                location TEXT,
                description TEXT,
                is_demo TEXT NOT NULL DEFAULT 'DEMO',
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
            "products",
            [
                ("sku", "TEXT NOT NULL"),
                ("product_name", "TEXT"),
                ("updated_at", "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"),
                ("is_demo", "TEXT NOT NULL DEFAULT 'DEMO'"),
            ],
        )
        _ensure_table_columns(
            conn,
            "warehouses",
            [
                ("warehouse_id", "TEXT NOT NULL"),
                ("warehouse_name", "TEXT"),
                ("updated_at", "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"),
                ("is_demo", "TEXT NOT NULL DEFAULT 'DEMO'"),
            ],
        )

        _ensure_table_columns(
            conn,
            "orders",
            [
                ("customer_name_masked", "TEXT NOT NULL DEFAULT '***'"),
                ("customer_country", "TEXT NOT NULL DEFAULT 'CN'"),
                ("order_status", "TEXT NOT NULL DEFAULT 'pending_payment'"),
                ("payment_status", "TEXT NOT NULL DEFAULT 'unpaid'"),
                ("fulfillment_status", "TEXT NOT NULL DEFAULT 'pending'"),
                ("currency", "TEXT NOT NULL DEFAULT 'CNY'"),
                ("total_amount", "REAL NOT NULL DEFAULT 0"),
                ("is_demo", "TEXT NOT NULL DEFAULT 'DEMO'"),
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
                ("is_demo", "TEXT NOT NULL DEFAULT 'DEMO'"),
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
                ("status", "TEXT NOT NULL DEFAULT 'normal'"),
                ("updated_at", "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"),
                ("is_demo", "TEXT NOT NULL DEFAULT 'DEMO'"),
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
                ("is_demo", "TEXT NOT NULL DEFAULT 'DEMO'"),
            ],
        )
        _ensure_table_columns(
            conn,
            "tracking_events",
            [
                ("shipment_id", "TEXT NOT NULL"),
                ("event_time", "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"),
                ("event_status", "TEXT NOT NULL DEFAULT 'pending'"),
                ("location", "TEXT"),
                ("description", "TEXT"),
                ("is_demo", "TEXT NOT NULL DEFAULT 'DEMO'"),
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

        _ensure_inventory_master_foreign_keys(conn)
        _ensure_order_items_sku_foreign_key(conn)
        _ensure_master_sync_triggers(conn)
        _ensure_indexes(conn)
        conn.commit()

        if seed_demo:
            seed_demo_data(target)
        return str(target)
    finally:
        conn.close()


def _all_tables_empty(conn: sqlite3.Connection, tables: tuple[str, ...]) -> bool:
    for table in tables:
        if conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is not None:
            return False
    return True


def seed_demo_data(db_path: str | Path | None = None) -> None:
    """仅在**空库**写入最小演示数据；已有业务数据时本函数不做任何写入。

    守卫是必须的：本函数既作为全新库的兜底播种，也会被 `api.service` 在模块导入时
    调用，还会被 `tools.database._ensure_demo_seed_if_needed` 在表为空时调用。
    若不加守卫，它会在 `initialize_demo_database(reset=True)` 清空表的窗口内写入与
    `data/demo/*.csv` 口径不同的旧种子（1001=528 / 1002=1299 / 1003=799），而
    `orders.order_id` 有唯一索引、`order_items` 没有，于是 CSV 导入会跳过主表行、
    却把明细行追加进去，造成主表金额与明细长期不自洽，并使导入校验直接失败。

    种子内容刻意取 `data/demo/*.csv` 的子集且取值完全一致，保证「先兜底播种、
    再导入 CSV」与「直接导入 CSV」最终收敛到同一份数据。
    """
    target = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    with connect(target) as conn:
        if _all_tables_empty(conn, BUSINESS_TABLES):
            _seed_business_rows(conn)
        if _all_tables_empty(conn, ("chat_threads",)):
            _seed_chat_rows(conn)
        if _all_tables_empty(conn, ("knowledge_articles",)):
            _seed_knowledge_rows(conn)


def initialize_database(
    db_path: str | Path | None = None,
    *,
    seed_demo: bool = True,
) -> dict[str, Any]:
    """初始化应用数据库，并按需执行一次受保护的演示数据播种。

    这是应用启动时应使用的统一入口。它把建表和播种顺序固定为：
    建立/迁移 schema -> 在空库中播种 -> 返回可观测的行数摘要。播种本身仍由
    ``seed_demo_data`` 的空表守卫控制，因此重复启动不会覆盖已有业务数据。
    ``init_db`` 和 ``seed_demo_data`` 继续保留给脚本、测试和兼容调用方。
    """
    target = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    init_db(target)
    if seed_demo and _business_data_is_empty(target):
        # CSV 是应用演示业务数据的唯一权威源。采用局部导入避免在模块顶层
        # 引入 scripts.init_demo_data 造成循环依赖（该脚本本身依赖本模块）。
        from scripts.init_demo_data import initialize_demo_database

        initialize_demo_database(db_path=target, reset=False)

    # chat/knowledge 仍由 schema 初始化模块负责最小兼容种子；其守卫不会触碰
    # 已有业务数据，也不会覆盖 CSV 导入结果。
    if seed_demo:
        seed_demo_data(target)

    with connect(target) as conn:
        counts = {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (*ALL_BUSINESS_TABLES, "chat_threads", "chat_messages", "knowledge_articles")
        }
    return {"db_path": str(target), "seed_demo": bool(seed_demo), "counts": counts}


def _business_data_is_empty(db_path: str | Path) -> bool:
    target = Path(db_path)
    with connect(target) as conn:
        return _all_tables_empty(conn, BUSINESS_TABLES)


def _seed_business_rows(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO products (sku, product_name, updated_at, is_demo)
        VALUES
            ('SKU-001', '智能音箱', '2026-02-10 09:00:00', 'DEMO'),
            ('SKU-002', '蓝牙耳机', '2026-02-10 09:00:00', 'DEMO'),
            ('SKU-003', '便携充电宝', '2026-02-10 09:00:00', 'DEMO'),
            ('SKU-004', '旅行背包', '2026-02-10 09:00:00', 'DEMO'),
            ('SKU-005', '运动水壶', '2026-02-10 09:00:00', 'DEMO'),
            ('SKU-007', '无线鼠标', '2026-02-10 09:00:00', 'DEMO'),
            ('SKU-008', '手机壳', '2026-02-10 09:00:00', 'DEMO')
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO warehouses (warehouse_id, warehouse_name, updated_at, is_demo)
        VALUES
            ('WH-001', '深圳仓', '2026-02-10 09:00:00', 'DEMO'),
            ('WH-002', '上海仓', '2026-02-10 09:00:00', 'DEMO'),
            ('WH-003', '柏林仓', '2026-02-10 09:00:00', 'DEMO'),
            ('WH-005', '法兰克福仓', '2026-02-10 09:00:00', 'DEMO')
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO orders (
            order_id, customer_name_masked, customer_country, order_status,
            payment_status, fulfillment_status, currency, total_amount,
            created_at, updated_at, is_demo
        ) VALUES
            ('1001', 'C***', 'CN', 'shipped', 'paid', 'fulfilled', 'CNY', 527.00, '2026-01-10 09:12:00', '2026-01-12 15:30:00', 'DEMO'),
            ('1002', 'L***', 'US', 'delivered', 'paid', 'fulfilled', 'USD', 888.00, '2026-01-08 11:45:00', '2026-01-11 09:20:00', 'DEMO'),
            ('1003', 'A***', 'DE', 'pending_payment', 'unpaid', 'pending', 'EUR', 129.00, '2026-01-12 13:10:00', '2026-01-12 13:10:00', 'DEMO')
        ;
        """
    )

    conn.execute(
        """
        INSERT OR IGNORE INTO inventory (sku, product_name, warehouse_id, warehouse_name, on_hand, reserved, available, safety_stock, status, updated_at, is_demo)
        VALUES
            ('SKU-001', '智能音箱', 'WH-001', '深圳仓', 24, 2, 22, 10, 'normal', '2026-02-10 09:00:00', 'DEMO'),
            ('SKU-002', '蓝牙耳机', 'WH-001', '深圳仓', 0, 0, 0, 12, 'out_of_stock', '2026-02-10 09:00:00', 'DEMO'),
            ('SKU-003', '便携充电宝', 'WH-002', '上海仓', 5, 3, 2, 10, 'low_stock', '2026-02-10 09:00:00', 'DEMO'),
            ('SKU-004', '旅行背包', 'WH-003', '柏林仓', 8, 2, 6, 12, 'low_stock', '2026-02-10 09:00:00', 'DEMO'),
            ('SKU-005', '运动水壶', 'WH-001', '深圳仓', 16, 1, 15, 8, 'normal', '2026-02-10 09:00:00', 'DEMO'),
            ('SKU-007', '无线鼠标', 'WH-001', '深圳仓', 18, 6, 12, 10, 'normal', '2026-02-10 09:00:00', 'DEMO'),
            ('SKU-008', '手机壳', 'WH-005', '法兰克福仓', 40, 5, 35, 15, 'normal', '2026-02-10 09:00:00', 'DEMO')
        ;
        """
    )

    conn.execute(
        """
        INSERT OR IGNORE INTO order_items (order_id, sku, product_name, quantity, unit_price, currency, is_demo)
        VALUES
            ('1001', 'SKU-001', '智能音箱', 1, 299.00, 'CNY', 'DEMO'),
            ('1001', 'SKU-003', '便携充电宝', 1, 189.00, 'CNY', 'DEMO'),
            ('1001', 'SKU-008', '手机壳', 1, 39.00, 'CNY', 'DEMO'),
            ('1002', 'SKU-004', '旅行背包', 1, 799.00, 'USD', 'DEMO'),
            ('1002', 'SKU-007', '无线鼠标', 1, 89.00, 'USD', 'DEMO'),
            ('1003', 'SKU-005', '运动水壶', 1, 129.00, 'EUR', 'DEMO')
        ;
        """
    )

    conn.execute(
        """
        INSERT OR IGNORE INTO shipments (shipment_id, order_id, carrier, tracking_number, shipping_status, shipped_at, estimated_delivery_at, delivered_at, updated_at, is_demo)
        VALUES
            ('SHP-1001-A', '1001', 'DHL', 'DHL-1001-001', 'in_transit', '2026-01-10 19:15:00', '2026-01-14 18:00:00', NULL, '2026-01-12 15:30:00', 'DEMO'),
            ('SHP-1002-A', '1002', 'FedEx', 'FX-1002-001', 'delivered', '2026-01-08 17:00:00', '2026-01-11 11:00:00', '2026-01-11 10:45:00', '2026-01-11 10:50:00', 'DEMO')
        ;
        """
    )

    conn.execute(
        """
        INSERT OR IGNORE INTO tracking_events (shipment_id, event_time, event_status, location, description, is_demo)
        VALUES
            ('SHP-1001-A', '2026-01-10 19:15:00', 'shipped', '深圳仓', '演示数据：包裹已揽收', 'DEMO'),
            ('SHP-1001-A', '2026-01-11 09:40:00', 'in_transit', '深圳中转站', '演示数据：运输中', 'DEMO'),
            ('SHP-1002-A', '2026-01-08 17:00:00', 'shipped', '纽约仓', '演示数据：已出库', 'DEMO'),
            ('SHP-1002-A', '2026-01-11 10:45:00', 'delivered', '纽约东区配送点', '演示数据：已签收', 'DEMO')
        ;
        """
    )


def _seed_chat_rows(conn: sqlite3.Connection) -> None:
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


def _seed_knowledge_rows(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO knowledge_articles (slug, category, title, content, source, updated_at)
        VALUES
            ('return-policy', 'returns', '退货政策', '退货需要满足商品未使用、未损坏且附带原包装等条件。', 'data/return_policy.md', CURRENT_TIMESTAMP),
            ('shipping-policy', 'shipping', '物流政策', '物流配送通常在3-7个工作日内完成，海外订单可能受清关影响。', 'data/shipping_policy.md', CURRENT_TIMESTAMP)
        ;
        """
    )


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
            """
            SELECT i.id,
                   i.sku,
                   COALESCE(p.product_name, i.product_name) AS product_name,
                   i.warehouse_id,
                   COALESCE(w.warehouse_name, i.warehouse_name) AS warehouse_name,
                   i.on_hand,
                   i.reserved,
                   i.available,
                   i.safety_stock,
                   i.status,
                   i.updated_at,
                   i.is_demo
            FROM inventory i
            LEFT JOIN products p ON p.sku = i.sku
            LEFT JOIN warehouses w ON w.warehouse_id = i.warehouse_id
            WHERE i.sku = ?
            """,
            (str(sku).strip().upper(),),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_shipment_by_order_id(order_id: str, db_path: str | Path | None = None) -> dict[str, Any] | None:
    """取订单最新一个包裹。保留用于兼容既有调用；如需全部包裹用 get_shipments_by_order_id。"""
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


def get_shipments_by_order_id(order_id: str, db_path: str | Path | None = None) -> list[dict[str, Any]]:
    """取订单的全部包裹，按 shipment_id 升序（与 workbench.list_shipments_by_order 口径一致）。

    一个订单可以拆多个包裹（例如演示数据订单 1005 的 SHP-1005-A / SHP-1005-B），
    取"最新一条"会静默丢件，因此业务查询层一律用本函数。
    """
    target = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    conn = _connect(target)
    try:
        rows = conn.execute(
            "SELECT * FROM shipments WHERE order_id = ? ORDER BY shipment_id ASC",
            (str(order_id),),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_tracking_events(shipment_id: str, db_path: str | Path | None = None) -> list[dict[str, Any]]:
    target = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    conn = _connect(target)
    try:
        rows = conn.execute(
            # id 作为同 event_time 的 tiebreaker，避免并列时顺序不确定。
            "SELECT * FROM tracking_events WHERE shipment_id = ? ORDER BY event_time ASC, id ASC",
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


_INTEGRITY_CHECKS: tuple[tuple[str, str], ...] = (
    (
        "inventory.sku -> products.sku",
        "SELECT COUNT(*) FROM inventory i LEFT JOIN products p ON i.sku = p.sku "
        "WHERE p.sku IS NULL",
    ),
    (
        "inventory.warehouse_id -> warehouses.warehouse_id",
        "SELECT COUNT(*) FROM inventory i LEFT JOIN warehouses w ON i.warehouse_id = w.warehouse_id "
        "WHERE i.warehouse_id IS NOT NULL AND TRIM(i.warehouse_id) <> '' AND w.warehouse_id IS NULL",
    ),
    (
        "order_items.order_id -> orders.order_id",
        "SELECT COUNT(*) FROM order_items i LEFT JOIN orders o ON i.order_id = o.order_id "
        "WHERE o.order_id IS NULL",
    ),
    (
        "shipments.order_id -> orders.order_id",
        "SELECT COUNT(*) FROM shipments s LEFT JOIN orders o ON s.order_id = o.order_id "
        "WHERE o.order_id IS NULL",
    ),
    (
        "tracking_events.shipment_id -> shipments.shipment_id",
        "SELECT COUNT(*) FROM tracking_events t LEFT JOIN shipments s "
        "ON t.shipment_id = s.shipment_id WHERE s.shipment_id IS NULL",
    ),
    (
        "order_items.sku -> inventory.sku",
        "SELECT COUNT(*) FROM order_items i LEFT JOIN inventory v ON i.sku = v.sku "
        "WHERE v.sku IS NULL",
    ),
)


def validate_referential_integrity(db_path: str | Path | None = None) -> dict[str, Any]:
    """校验外键关系，返回孤儿记录统计与声明式外键检查结果。

    声明式外键（`inventory` -> `products` / `warehouses`、`order_items` ->
    `orders` / `inventory`、`shipments` -> `orders`、`tracking_events` -> `shipments`）
    在 `PRAGMA foreign_keys = ON` 下由 SQLite 强制；
    这里仍保留显式孤儿统计，便于初始化脚本输出可读报告。
    """
    target = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    with connect(target) as conn:
        checked = {label: conn.execute(sql).fetchone()[0] for label, sql in _INTEGRITY_CHECKS}
        # PRAGMA 形式的声明式外键检查，由 SQLite 自身给出违规行
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        fk_enabled = conn.execute("PRAGMA foreign_keys").fetchone()[0]

    orphans = {label: count for label, count in checked.items() if count}
    return {
        "ok": not orphans and not violations,
        "db_path": str(target),
        "foreign_keys_enabled": bool(fk_enabled),
        "declared_fk_violations": len(violations),
        "checks": checked,
        "orphans": orphans,
    }


if __name__ == "__main__":
    print(init_db(seed_demo=True))
