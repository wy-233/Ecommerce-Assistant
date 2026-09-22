from pathlib import Path
import sqlite3

from scripts.init_demo_data import DEFAULT_DB_PATH, initialize_demo_database


def test_demo_csv_files_exist_and_have_required_minimums():
    demo_dir = Path(__file__).resolve().parents[1] / "data" / "demo"
    assert (demo_dir / "orders.csv").exists()
    assert (demo_dir / "order_items.csv").exists()
    assert (demo_dir / "inventory.csv").exists()
    assert (demo_dir / "shipments.csv").exists()
    assert (demo_dir / "tracking_events.csv").exists()

    orders = sum(1 for _ in (demo_dir / "orders.csv").open("r", encoding="utf-8")) - 1
    order_items = sum(1 for _ in (demo_dir / "order_items.csv").open("r", encoding="utf-8")) - 1
    inventory = sum(1 for _ in (demo_dir / "inventory.csv").open("r", encoding="utf-8")) - 1
    shipments = sum(1 for _ in (demo_dir / "shipments.csv").open("r", encoding="utf-8")) - 1
    tracking_events = sum(1 for _ in (demo_dir / "tracking_events.csv").open("r", encoding="utf-8")) - 1

    assert orders >= 20
    assert order_items >= 30
    assert inventory >= 10
    assert shipments >= 15
    assert tracking_events >= 30


def test_initialize_demo_database_is_idempotent_and_resettable():
    initialize_demo_database(reset=True)
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    try:
        order_count = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        item_count = conn.execute("SELECT COUNT(*) FROM order_items").fetchone()[0]
        sku_count = conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
        shipment_count = conn.execute("SELECT COUNT(*) FROM shipments").fetchone()[0]
        tracking_count = conn.execute("SELECT COUNT(*) FROM tracking_events").fetchone()[0]
        assert order_count >= 20
        assert item_count >= 30
        assert sku_count >= 10
        assert shipment_count >= 15
        assert tracking_count >= 30
    finally:
        conn.close()

    initialize_demo_database(reset=False)
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    try:
        assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] >= 20
        assert conn.execute("SELECT COUNT(*) FROM order_items").fetchone()[0] >= 30
    finally:
        conn.close()
