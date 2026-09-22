import sqlite3

from ecommerce_assistant.db.chat_dao import ChatThreadDAO
from ecommerce_assistant.db.init_db import (
    get_inventory_by_sku,
    get_order_by_id,
    get_shipment_by_order_id,
    get_tracking_events,
    init_db,
    seed_demo_data,
)
from ecommerce_assistant.tools.inventory import get_inventory_status
from ecommerce_assistant.tools.logistics import get_logistics_status
from ecommerce_assistant.tools.order import get_order_status


def test_init_db_creates_expected_tables(tmp_path):
    db_file = tmp_path / "ecommerce_assistant.db"

    init_db(db_file)

    with sqlite3.connect(db_file) as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()

    actual = {name for (name,) in tables}
    expected = {
        "orders",
        "order_items",
        "inventory",
        "shipments",
        "tracking_events",
        "chat_threads",
        "chat_messages",
        "knowledge_articles",
    }

    assert expected.issubset(actual)


def test_seed_demo_data_and_accessors(tmp_path):
    db_file = tmp_path / "ecommerce_assistant.db"

    init_db(db_file)
    seed_demo_data(db_file)

    order = get_order_by_id("1001", db_file)
    assert order["order_id"] == "1001"
    assert order["customer_country"] == "CN"

    item = get_inventory_by_sku("SKU-001", db_file)
    assert item["sku"] == "SKU-001"
    assert item["available"] >= 0

    shipment = get_shipment_by_order_id("1001", db_file)
    assert shipment["carrier"] in {"DHL", "FedEx", "UPS"}

    events = get_tracking_events(shipment["shipment_id"], db_file)
    assert isinstance(events, list)
    assert events


def test_public_tools_prefer_sqlite(tmp_path):
    db_file = tmp_path / "ecommerce_assistant.db"
    init_db(db_file)
    seed_demo_data(db_file)

    order_result = get_order_status("1001", db_path=db_file)
    inventory_result = get_inventory_status("SKU-001", db_path=db_file)
    logistics_result = get_logistics_status("1001", db_path=db_file)

    assert "订单 1001" in order_result
    assert "SKU-001" in inventory_result
    assert "DHL" in logistics_result or "FedEx" in logistics_result or "UPS" in logistics_result


def test_chat_thread_dao_lifecycle(tmp_path):
    db_file = tmp_path / "chat.db"
    dao = ChatThreadDAO(db_file)

    dao.ensure_thread("thread-A", user_id="user-1")
    dao.append_message("thread-A", "user", "你好")
    dao.append_message("thread-A", "assistant", "你好，我在呢")

    history = dao.get_history("thread-A", limit=10)
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[-1]["content"] == "你好，我在呢"

    threads = dao.list_threads(user_id="user-1")
    assert any(thread["thread_id"] == "thread-A" for thread in threads)

    dao.delete_thread("thread-A")
    assert dao.get_history("thread-A", limit=10) == []
    assert dao.list_threads(user_id="user-1") == []
