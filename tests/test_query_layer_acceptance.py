"""业务查询层验收条件（用户指定的 8 条「必须满足」）。

这些用例直接使用默认库（不传 db_path），与调用方 `query_order("1001")` 的
真实用法一致，因此读取项目根 `data/ecommerce_assistant.db`（只读）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ecommerce_assistant.agents.ecommerce_assistant import _detect_intent, handle_question
from ecommerce_assistant.db.init_db import DEFAULT_DB_PATH
from ecommerce_assistant.schema.statuses import (
    INVENTORY_STATUS_LABELS,
    ORDER_STATUS_LABELS,
    label_of,
)
from ecommerce_assistant.tools.database import (
    query_inventory,
    query_inventory_by_sku,
    query_logistics,
    query_order,
    query_shipment_events,
)
from ecommerce_assistant.tools.inventory import get_inventory_status
from ecommerce_assistant.tools.logistics import get_logistics_status
from ecommerce_assistant.tools.order import get_order_status


@pytest.fixture
def raw_db():
    conn = sqlite3.connect(str(DEFAULT_DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _inventory_rows(raw_db) -> list[dict]:
    return [
        dict(row)
        for row in raw_db.execute(
            "SELECT sku, available, safety_stock FROM inventory ORDER BY sku"
        )
    ]


# --------------------------------------------------------------------------
# 条件 1：查询结果来自 SQLite
# --------------------------------------------------------------------------


def test_order_result_comes_from_sqlite(raw_db):
    data = query_order("1001")["data"]

    raw_order = dict(raw_db.execute("SELECT * FROM orders WHERE order_id = '1001'").fetchone())
    assert all(data[key] == value for key, value in raw_order.items())

    raw_items = [
        dict(row)
        for row in raw_db.execute("SELECT * FROM order_items WHERE order_id = '1001' ORDER BY id ASC")
    ]
    assert data["items"] == raw_items

    raw_shipments = [
        dict(row)
        for row in raw_db.execute(
            "SELECT * FROM shipments WHERE order_id = '1001' ORDER BY shipment_id ASC"
        )
    ]
    assert data["shipments"] == raw_shipments


def test_inventory_result_comes_from_sqlite(raw_db):
    data = query_inventory("SKU-001")["data"]

    raw_record = dict(raw_db.execute("SELECT * FROM inventory WHERE sku = 'SKU-001'").fetchone())
    assert all(data[key] == value for key, value in raw_record.items())


def test_logistics_result_comes_from_sqlite(raw_db):
    data = query_logistics(order_id="1001")["data"]

    raw_shipment = dict(raw_db.execute("SELECT * FROM shipments WHERE order_id = '1001'").fetchone())
    for key, value in raw_shipment.items():
        assert data["shipment"][key] == value

    raw_events = [
        dict(row)
        for row in raw_db.execute(
            "SELECT * FROM tracking_events WHERE shipment_id = ? ORDER BY event_time ASC, id ASC",
            (raw_shipment["shipment_id"],),
        )
    ]
    assert data["events"] == raw_events


# --------------------------------------------------------------------------
# 条件 2：不存在的订单不会返回虚构状态
# --------------------------------------------------------------------------


def test_missing_order_does_not_return_invented_status():
    result = query_order("999999")

    assert result["ok"] is False
    assert result["code"] == "NOT_FOUND"
    assert "status" not in result["data"]
    assert "order_status" not in result["data"]

    message = get_order_status("999999")
    assert "不存在" in message
    assert not [label for label in ORDER_STATUS_LABELS.values() if label in message]


def test_agent_does_not_invent_status_for_missing_order():
    message = handle_question("订单 999999 是什么状态？")

    assert "不存在" in message
    assert not [label for label in ORDER_STATUS_LABELS.values() if label in message]


# --------------------------------------------------------------------------
# 条件 3：不存在的 SKU 不会被误判成零库存
# --------------------------------------------------------------------------


@pytest.mark.parametrize("sku", ["SKU-999", "S-K-404"])
def test_missing_sku_is_not_treated_as_zero_stock(sku: str):
    for result in (query_inventory(sku), query_inventory_by_sku(sku)):
        assert result["ok"] is False
        assert result["code"] == "NOT_FOUND"
        assert "available" not in (result["data"] or {})

    message = get_inventory_status(sku)
    assert "未找到" in message
    assert "0 件" not in message
    assert "缺货" not in message


def test_missing_product_name_is_not_treated_as_zero_stock():
    result = query_inventory(product_name="不存在的商品名XYZ")

    assert result["ok"] is False
    assert result["code"] == "NOT_FOUND"


# --------------------------------------------------------------------------
# 条件 4 / 5：零库存 -> 缺货；库存不足 -> 库存不足
# --------------------------------------------------------------------------


def test_zero_stock_sku_reports_out_of_stock(raw_db):
    zero_stock = [row for row in _inventory_rows(raw_db) if int(row["available"]) <= 0]
    assert zero_stock, "演示数据应至少有一个零库存 SKU"

    for row in zero_stock:
        result = query_inventory_by_sku(row["sku"])
        assert result["data"]["status"] == "out_of_stock"
        assert label_of(INVENTORY_STATUS_LABELS, result["data"]["status"]) == "缺货"
        assert "状态：缺货" in get_inventory_status(row["sku"])


def test_low_stock_sku_reports_low_stock(raw_db):
    low_stock = [
        row
        for row in _inventory_rows(raw_db)
        if 0 < int(row["available"]) <= int(row["safety_stock"])
    ]
    assert low_stock, "演示数据应至少有一个库存不足 SKU"

    for row in low_stock:
        result = query_inventory_by_sku(row["sku"])
        assert result["data"]["status"] == "low_stock"
        assert label_of(INVENTORY_STATUS_LABELS, result["data"]["status"]) == "库存不足"
        assert "状态：库存不足" in get_inventory_status(row["sku"])


def test_normal_stock_sku_reports_normal(raw_db):
    normal = [
        row
        for row in _inventory_rows(raw_db)
        if int(row["available"]) > int(row["safety_stock"])
    ]
    assert normal, "演示数据应至少有一个正常 SKU"

    for row in normal:
        assert query_inventory_by_sku(row["sku"])["data"]["status"] == "normal"


# --------------------------------------------------------------------------
# 条件 6：多条物流轨迹按时间排序
# --------------------------------------------------------------------------


def test_tracking_events_are_time_ordered(raw_db):
    shipments = [
        row["shipment_id"]
        for row in raw_db.execute(
            "SELECT shipment_id FROM tracking_events GROUP BY shipment_id HAVING COUNT(*) > 1 "
            "ORDER BY shipment_id"
        )
    ]
    assert shipments, "演示数据应至少有一个多轨迹包裹"

    for shipment_id in shipments:
        times = [event["event_time"] for event in query_shipment_events(shipment_id)["data"]["events"]]
        assert times == sorted(times)


def test_multi_package_order_events_are_time_ordered():
    result = query_logistics(order_id="1005")

    assert result["data"]["shipment_count"] == 2
    for shipment in result["data"]["shipments"]:
        times = [event["event_time"] for event in shipment["events"]]
        assert times == sorted(times)
        assert times


# --------------------------------------------------------------------------
# 条件 7：无物流订单返回明确提示
# --------------------------------------------------------------------------


def test_order_without_logistics_returns_clear_message(raw_db):
    orders = [
        row["order_id"]
        for row in raw_db.execute(
            "SELECT o.order_id FROM orders o LEFT JOIN shipments s ON o.order_id = s.order_id "
            "WHERE s.order_id IS NULL ORDER BY o.order_id"
        )
    ]
    assert orders, "演示数据应至少有一个无物流订单"

    for order_id in orders:
        result = query_logistics(order_id=order_id)
        assert result["code"] == "NO_LOGISTICS"
        assert order_id in result["message"]
        assert "物流" in result["message"]
        assert get_logistics_status(order_id) == result["message"]


def test_missing_order_is_distinguishable_from_order_without_logistics():
    assert query_logistics(order_id="999999")["code"] == "NOT_FOUND"
    assert query_logistics(order_id="1003")["code"] == "NO_LOGISTICS"


# --------------------------------------------------------------------------
# 条件 8：Agent 使用的查询结果与工具直接调用结果一致
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "expected_intent", "identifier"),
    [
        ("订单 1001 是什么状态？", "order", "1001"),
        ("订单 1001 现在到哪里了？", "order", "1001"),
        ("订单 999999 是什么状态？", "order", "999999"),
        ("商品 SKU-001 还有库存吗？", "inventory", "SKU-001"),
        ("商品 SKU-002 还有库存吗？", "inventory", "SKU-002"),
        ("商品 SKU-999 还有库存吗？", "inventory", "SKU-999"),
        ("订单 1001 使用了什么物流？", "logistics", "1001"),
        ("订单 1003 使用了什么物流？", "logistics", "1003"),
        ("订单 1005 使用了什么物流？", "logistics", "1005"),
    ],
)
def test_agent_output_matches_direct_tool_call(question: str, expected_intent: str, identifier: str):
    assert _detect_intent(question) == expected_intent

    direct_call = {
        "order": get_order_status,
        "inventory": get_inventory_status,
        "logistics": get_logistics_status,
    }[expected_intent]

    agent_output = handle_question(question)
    assert agent_output == direct_call(identifier)
    assert "知识库" not in agent_output
    assert "暂时无法" not in agent_output
