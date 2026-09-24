import sqlite3

import pytest

from ecommerce_assistant.db.init_db import SkuReferenceMigrationError, init_db
from ecommerce_assistant.tools.database import query_inventory_by_sku


def test_init_db_creates_expected_tables(tmp_path):
    db_file = tmp_path / "ecommerce_assistant.db"

    init_db(str(db_file))

    with sqlite3.connect(db_file) as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()

    actual = {name for (name,) in tables}
    expected = {
        "orders",
        "products",
        "warehouses",
        "inventory",
        "shipments",
        "tracking_events",
        "chat_threads",
        "chat_messages",
        "knowledge_articles",
    }

    assert expected.issubset(actual)


def _create_legacy_order_items_schema(db_file, *, orphan: bool = False) -> None:
    with sqlite3.connect(db_file) as conn:
        conn.executescript(
            """
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL UNIQUE,
                customer_name_masked TEXT NOT NULL DEFAULT '***',
                customer_country TEXT NOT NULL DEFAULT 'CN',
                order_status TEXT NOT NULL DEFAULT 'pending_payment',
                payment_status TEXT NOT NULL DEFAULT 'unpaid',
                fulfillment_status TEXT NOT NULL DEFAULT 'pending',
                currency TEXT NOT NULL DEFAULT 'CNY',
                total_amount REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                is_demo TEXT NOT NULL DEFAULT 'DEMO'
            );
            CREATE TABLE inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sku TEXT NOT NULL UNIQUE,
                product_name TEXT,
                warehouse_id TEXT,
                warehouse_name TEXT,
                on_hand INTEGER NOT NULL DEFAULT 0,
                reserved INTEGER NOT NULL DEFAULT 0,
                available INTEGER NOT NULL DEFAULT 0,
                safety_stock INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'normal',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                is_demo TEXT NOT NULL DEFAULT 'DEMO'
            );
            CREATE TABLE order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                product_name TEXT,
                quantity INTEGER NOT NULL DEFAULT 1,
                unit_price REAL NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'CNY',
                is_demo TEXT NOT NULL DEFAULT 'DEMO',
                FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE RESTRICT
            );
            INSERT INTO orders (order_id) VALUES ('LEGACY-ORDER');
            """
        )
        if not orphan:
            conn.execute(
                """
                INSERT INTO inventory (sku, product_name, warehouse_id, warehouse_name)
                VALUES ('LEGACY-SKU', '旧商品', 'LEGACY-WH', '旧仓库')
                """
            )
        conn.execute(
            "INSERT INTO order_items (order_id, sku, product_name) VALUES ('LEGACY-ORDER', ?, '旧商品')",
            ("MISSING-SKU" if orphan else "LEGACY-SKU",),
        )


def test_init_db_adds_sku_foreign_key_and_enforces_it(tmp_path):
    db_file = tmp_path / "sku_fk.db"
    init_db(db_file)

    with sqlite3.connect(db_file) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        foreign_keys = conn.execute("PRAGMA foreign_key_list(order_items)").fetchall()
        assert any(row[2:5] == ("inventory", "sku", "sku") for row in foreign_keys)

        conn.execute("INSERT INTO orders (order_id) VALUES ('ORDER-1')")
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            conn.execute(
                "INSERT INTO order_items (order_id, sku, product_name) VALUES ('ORDER-1', 'UNKNOWN', '未知商品')"
            )

        conn.execute("INSERT INTO products (sku, product_name) VALUES ('SKU-1', '商品')")
        conn.execute("INSERT INTO inventory (sku, product_name) VALUES ('SKU-1', '商品')")
        conn.execute(
            "INSERT INTO order_items (order_id, sku, product_name) VALUES ('ORDER-1', 'SKU-1', '商品')"
        )
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            conn.execute("DELETE FROM inventory WHERE sku = 'SKU-1'")


def test_inventory_references_product_and_warehouse_master_data(tmp_path):
    db_file = tmp_path / "master_fk.db"
    init_db(db_file)

    with sqlite3.connect(db_file) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        foreign_keys = conn.execute("PRAGMA foreign_key_list(inventory)").fetchall()
        assert any(row[2:5] == ("products", "sku", "sku") for row in foreign_keys)
        assert any(
            row[2:5] == ("warehouses", "warehouse_id", "warehouse_id")
            for row in foreign_keys
        )

        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            conn.execute(
                "INSERT INTO inventory (sku, warehouse_id) VALUES ('UNKNOWN-SKU', 'UNKNOWN-WH')"
            )


def test_init_db_backfills_master_data_from_legacy_inventory(tmp_path):
    db_file = tmp_path / "legacy_master.db"
    _create_legacy_order_items_schema(db_file)

    init_db(db_file)

    with sqlite3.connect(db_file) as conn:
        assert conn.execute("SELECT sku, product_name FROM products").fetchall() == [
            ("LEGACY-SKU", "旧商品")
        ]
        assert conn.execute(
            "SELECT warehouse_id, warehouse_name FROM warehouses"
        ).fetchall() == [("LEGACY-WH", "旧仓库")]
        assert conn.execute(
            "SELECT sku, product_name FROM inventory"
        ).fetchall() == [("LEGACY-SKU", "旧商品")]
        foreign_keys = conn.execute("PRAGMA foreign_key_list(inventory)").fetchall()
        assert any(row[2:5] == ("products", "sku", "sku") for row in foreign_keys)
        assert any(
            row[2:5] == ("warehouses", "warehouse_id", "warehouse_id")
            for row in foreign_keys
        )


def test_master_names_are_authoritative_and_sync_compatibility_fields(tmp_path):
    db_file = tmp_path / "master_names.db"
    init_db(db_file, seed_demo=True)

    with sqlite3.connect(db_file) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("UPDATE products SET product_name = '主数据商品名' WHERE sku = 'SKU-001'")
        conn.execute(
            "UPDATE warehouses SET warehouse_name = '主数据仓库名' WHERE warehouse_id = 'WH-001'"
        )
        conn.commit()
        snapshot = conn.execute(
            "SELECT product_name, warehouse_name FROM inventory WHERE sku = 'SKU-001'"
        ).fetchone()

    result = query_inventory_by_sku("SKU-001", db_path=db_file)
    assert result["data"]["product_name"] == "主数据商品名"
    assert result["data"]["warehouse_name"] == "主数据仓库名"
    assert snapshot == ("主数据商品名", "主数据仓库名")


def test_init_db_migrates_legacy_order_items_without_data_loss(tmp_path):
    db_file = tmp_path / "legacy.db"
    _create_legacy_order_items_schema(db_file)

    init_db(db_file)

    with sqlite3.connect(db_file) as conn:
        foreign_keys = conn.execute("PRAGMA foreign_key_list(order_items)").fetchall()
        assert any(row[2:5] == ("inventory", "sku", "sku") for row in foreign_keys)
        assert conn.execute(
            "SELECT order_id, sku, product_name FROM order_items"
        ).fetchall() == [("LEGACY-ORDER", "LEGACY-SKU", "旧商品")]


def test_init_db_rejects_orphan_sku_without_deleting_legacy_data(tmp_path):
    db_file = tmp_path / "legacy_orphan.db"
    _create_legacy_order_items_schema(db_file, orphan=True)

    with pytest.raises(SkuReferenceMigrationError, match="孤儿 SKU|MISSING-SKU"):
        init_db(db_file)

    with sqlite3.connect(db_file) as conn:
        assert conn.execute("SELECT order_id, sku FROM order_items").fetchall() == [
            ("LEGACY-ORDER", "MISSING-SKU")
        ]
        assert not any(
            row[2:5] == ("inventory", "sku", "sku")
            for row in conn.execute("PRAGMA foreign_key_list(order_items)").fetchall()
        )
