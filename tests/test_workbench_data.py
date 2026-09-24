"""演示数据与工作台数据库的回归测试。

覆盖三类风险：数据是否真的标记为演示数据、状态词表是否收敛到唯一口径、
以及订单金额与明细是否自洽。另含一条防双库复发的路径断言。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ecommerce_assistant.db.init_db import DEFAULT_DB_PATH
from ecommerce_assistant.schema.statuses import (
    INVENTORY_STATUS_CODES,
    ORDER_STATUS_CODES,
    SHIPPING_STATUS_CODES,
)
from scripts.init_demo_data import initialize_demo_database
from ecommerce_assistant.tools.database import (
    list_inventory_records,
    list_order_records,
    list_shipment_records,
)
from ecommerce_assistant.workbench import queries


def _query(sql: str, params: tuple = ()) -> list[dict]:
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _scalar(sql: str, params: tuple = ()):
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    try:
        return conn.execute(sql, params).fetchone()[0]
    finally:
        conn.close()


def test_default_db_path_is_project_root_data():
    assert DEFAULT_DB_PATH.name == "ecommerce_assistant.db"
    assert DEFAULT_DB_PATH.parent.name == "data"
    assert DEFAULT_DB_PATH.parent.parent.name != "src"
    assert DEFAULT_DB_PATH.exists()


def test_every_demo_row_is_tagged_as_demo():
    for table in ("orders", "order_items", "inventory", "shipments", "tracking_events"):
        total = _scalar(f"SELECT COUNT(*) FROM {table}")
        tagged = _scalar(f"SELECT COUNT(*) FROM {table} WHERE is_demo = 'DEMO'")
        assert total > 0
        assert total == tagged


def test_order_status_vocabulary_is_fully_covered():
    codes = {row["order_status"] for row in _query("SELECT DISTINCT order_status FROM orders")}
    assert codes == set(ORDER_STATUS_CODES)


def test_shipping_status_vocabulary_is_fully_covered():
    codes = {row["shipping_status"] for row in _query("SELECT DISTINCT shipping_status FROM shipments")}
    assert codes == set(SHIPPING_STATUS_CODES)


def test_inventory_status_vocabulary_is_fully_covered():
    codes = {row["status"] for row in _query("SELECT DISTINCT status FROM inventory")}
    assert codes == set(INVENTORY_STATUS_CODES)


def test_order_total_matches_item_sum():
    mismatched = _query(
        """
        SELECT o.order_id
        FROM orders o
        LEFT JOIN order_items i ON i.order_id = o.order_id
        GROUP BY o.order_id
        HAVING ABS(o.total_amount - COALESCE(SUM(i.quantity * i.unit_price), 0)) > 0.01
        """
    )
    assert mismatched == []


def test_inventory_numbers_are_self_consistent():
    broken = _query("SELECT sku FROM inventory WHERE on_hand - reserved != available")
    assert broken == []


def test_required_demo_scenarios_are_present():
    assert len(_query("SELECT order_id FROM orders WHERE order_status = 'pending_payment'")) >= 1
    assert len(_query("SELECT order_id FROM orders WHERE order_status = 'cancelled'")) >= 1
    assert len(_query("SELECT order_id FROM orders WHERE order_status = 'delivered'")) >= 1
    assert len(_query("SELECT shipment_id FROM shipments WHERE shipping_status = 'in_transit'")) >= 1
    assert len(_query("SELECT shipment_id FROM shipments WHERE shipping_status = 'exception'")) >= 1
    assert len(_query("SELECT sku FROM inventory WHERE available = 0")) >= 1
    assert len(_query("SELECT sku FROM inventory WHERE status = 'low_stock'")) >= 1
    assert (
        len(
            _query(
                """
                SELECT o.order_id FROM orders o
                WHERE NOT EXISTS (SELECT 1 FROM shipments s WHERE s.order_id = o.order_id)
                """
            )
        )
        >= 1
    )
    assert len(_query("SELECT order_id FROM shipments GROUP BY order_id HAVING COUNT(*) > 1")) >= 1
    assert len(_query("SELECT order_id FROM order_items GROUP BY order_id HAVING COUNT(*) > 1")) >= 1
    assert _scalar("SELECT MAX(c) FROM (SELECT COUNT(*) AS c FROM tracking_events GROUP BY shipment_id)") >= 2


def test_demo_database_can_be_rebuilt_from_csv():
    summary = initialize_demo_database(reset=True)
    assert summary["order_count"] >= 20
    assert summary["order_item_count"] >= 30
    assert summary["sku_count"] >= 10
    assert summary["shipment_count"] >= 15
    assert summary["tracking_event_count"] >= 30


def test_workbench_lists_match_unified_business_queries():
    assert [row["order_id"] for row in queries.list_orders()] == [
        row["order_id"] for row in list_order_records()["data"]["records"]
    ]
    assert [row["sku"] for row in queries.list_inventory()] == [
        row["sku"] for row in list_inventory_records()["data"]["records"]
    ]
    assert [row["shipment_id"] for row in queries.list_shipments()] == [
        row["shipment_id"] for row in list_shipment_records()["data"]["records"]
    ]


def test_workbench_query_adapter_contains_no_database_sql():
    source = Path(queries.__file__).read_text(encoding="utf-8")

    assert "import sqlite3" not in source
    assert "SELECT " not in source.upper()
    assert "INSERT " not in source.upper()
    assert "UPDATE " not in source.upper()
    assert "DELETE " not in source.upper()
