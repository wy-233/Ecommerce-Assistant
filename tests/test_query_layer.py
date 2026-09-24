"""订单 / 库存 / 物流统一业务查询层的单元测试。

全部用例使用 tmp_path 临时库（见 tests/conftest.py），不读写项目根真实库。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ecommerce_assistant.tools.database import (
    DB_ERROR,
    INVALID_ARGUMENT,
    NO_LOGISTICS,
    NOT_FOUND,
    OK,
    list_inventory_records,
    list_order_records,
    list_shipment_records,
    list_tracking_event_records,
    list_warehouse_records,
    query_dashboard_summary,
    query_inventory,
    query_inventory_by_sku,
    query_inventory_summary,
    query_logistics,
    query_order,
    query_order_items,
    query_order_shipments,
    query_order_status,
    query_order_summary,
    query_shipment_events,
    query_shipment_summary,
)

NO_LOGISTICS_ORDERS = ["1003", "1004", "1011", "1016", "1018", "1019"]


# ==========================================================================
# 订单查询
# ==========================================================================


def test_query_order_by_id(demo_db: Path):
    result = query_order("1001", db_path=demo_db)

    assert result["ok"] is True
    assert result["code"] == OK
    assert result["data"]["order_id"] == "1001"
    assert result["data"]["status"] == result["data"]["order_status"]
    assert result["data"]["customer_country"]


def test_query_order_items(demo_db: Path):
    result = query_order_items("1005", db_path=demo_db)

    assert result["ok"] is True
    assert result["data"]["order_id"] == "1005"
    assert result["data"]["count"] == len(result["data"]["items"])
    assert result["data"]["count"] >= 1
    item = result["data"]["items"][0]
    assert item["quantity"] > 0
    assert item["unit_price"] > 0
    assert item["sku"]


def test_query_order_shipments_returns_every_package(demo_db: Path):
    """订单 1005 拆两个包裹，必须两个都返回，不能只给最新的一个。"""
    result = query_order_shipments("1005", db_path=demo_db)

    assert result["ok"] is True
    ids = [shipment["shipment_id"] for shipment in result["data"]["shipments"]]
    assert ids == ["SHP-1005-A", "SHP-1005-B"]
    assert result["data"]["count"] == 2


def test_query_order_status_only_returns_status_and_counts(demo_db: Path):
    result = query_order_status("1001", db_path=demo_db)

    assert result["ok"] is True
    data = result["data"]
    assert data["status"] == "shipped"
    assert data["item_count"] >= 1
    assert data["shipment_count"] >= 1
    assert "items" not in data


def test_query_order_missing_returns_not_found(demo_db: Path):
    result = query_order("999999", db_path=demo_db)

    assert result["ok"] is False
    assert result["code"] == NOT_FOUND
    assert "999999" in result["message"]
    assert "不存在" in result["message"]


@pytest.mark.parametrize("bad_value", [None, "", "   "])
def test_query_order_blank_id_is_invalid_argument(demo_db: Path, bad_value):
    result = query_order(bad_value, db_path=demo_db)

    assert result["ok"] is False
    assert result["code"] == INVALID_ARGUMENT
    assert "order_id" in result["message"]


def test_order_queries_distinguish_not_found_from_invalid_argument(demo_db: Path):
    assert query_order("424242", db_path=demo_db)["code"] == NOT_FOUND
    assert query_order("", db_path=demo_db)["code"] == INVALID_ARGUMENT


def test_list_order_records_filters_by_carrier_without_duplicates(demo_db: Path):
    result = list_order_records(carrier="dhl", db_path=demo_db)

    assert result["ok"] is True
    records = result["data"]["records"]
    assert records
    order_ids = [record["order_id"] for record in records]
    assert len(order_ids) == len(set(order_ids))
    with sqlite3.connect(demo_db) as conn:
        expected = {
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT order_id FROM shipments WHERE UPPER(carrier) = 'DHL'"
            ).fetchall()
        }
    assert set(order_ids) == expected


def test_list_order_records_filters_by_warehouse_without_duplicates(demo_db: Path):
    result = list_order_records(warehouse_id="WH-001", db_path=demo_db)

    assert result["ok"] is True
    records = result["data"]["records"]
    order_ids = [record["order_id"] for record in records]
    assert len(order_ids) == len(set(order_ids))
    with sqlite3.connect(demo_db) as conn:
        expected = {
            row[0]
            for row in conn.execute(
                """
                SELECT DISTINCT oi.order_id
                FROM order_items oi
                JOIN inventory i ON i.sku = oi.sku
                WHERE i.warehouse_id = 'WH-001'
                """
            ).fetchall()
        }
    assert set(order_ids) == expected


# ==========================================================================
# 库存查询
# ==========================================================================


def test_query_inventory_by_sku_returns_all_quantity_fields(demo_db: Path):
    result = query_inventory_by_sku("SKU-001", db_path=demo_db)

    assert result["ok"] is True
    data = result["data"]
    for field in ("on_hand", "reserved", "available", "safety_stock"):
        assert isinstance(data[field], int)
    assert data["on_hand"] - data["reserved"] == data["available"]


def test_query_inventory_by_sku_is_case_insensitive(demo_db: Path):
    upper = query_inventory_by_sku("SKU-002", db_path=demo_db)
    lower = query_inventory_by_sku("sku-002", db_path=demo_db)

    assert upper["data"]["sku"] == lower["data"]["sku"] == "SKU-002"


def test_query_inventory_by_product_name(demo_db: Path):
    result = query_inventory(keyword="充电", db_path=demo_db)

    assert result["ok"] is True
    assert result["data"]["count"] >= 1
    assert all("充电" in record["product_name"] for record in result["data"]["records"])


def test_query_inventory_by_warehouse(demo_db: Path):
    by_id = query_inventory(warehouse_id="WH-001", db_path=demo_db)
    by_name = query_inventory(warehouse_name="深圳", db_path=demo_db)

    assert by_id["ok"] is True
    assert by_id["data"]["records"]
    assert all(record["warehouse_id"] == "WH-001" for record in by_id["data"]["records"])
    assert by_name["ok"] is True
    assert all("深圳" in record["warehouse_name"] for record in by_name["data"]["records"])


@pytest.mark.parametrize(
    ("available", "safety_stock", "expected"),
    [
        (0, 10, "out_of_stock"),
        (-3, 10, "out_of_stock"),
        (1, 10, "low_stock"),
        (10, 10, "low_stock"),
        (11, 10, "normal"),
    ],
)
def test_inventory_status_follows_rule(
    seeded_db: Path, available: int, safety_stock: int, expected: str
):
    """available<=0 缺货；available<=safety_stock 库存不足；available>safety_stock 正常。"""
    with sqlite3.connect(str(seeded_db)) as conn:
        conn.execute(
            "UPDATE inventory SET available = ?, safety_stock = ? WHERE sku = 'SKU-001'",
            (available, safety_stock),
        )
        conn.commit()

    result = query_inventory_by_sku("SKU-001", db_path=seeded_db)

    assert result["data"]["status"] == expected


def test_inventory_status_is_computed_from_rule_not_stored_column(seeded_db: Path):
    """落库 status 被篡改后，返回结果仍按可用量规则，并把漂移暴露出来。"""
    with sqlite3.connect(str(seeded_db)) as conn:
        conn.execute("UPDATE inventory SET available = 50, safety_stock = 10, status = 'out_of_stock' WHERE sku = 'SKU-001'")
        conn.commit()

    result = query_inventory_by_sku("SKU-001", db_path=seeded_db)

    assert result["data"]["status"] == "normal"
    assert result["data"]["stored_status"] == "out_of_stock"
    assert result["data"]["status_mismatch"] is True


def test_inventory_status_reports_no_mismatch_when_consistent(seeded_db: Path):
    result = query_inventory_by_sku("SKU-002", db_path=seeded_db)

    assert result["data"]["status"] == "out_of_stock"
    assert result["data"]["status_mismatch"] is False


def test_list_inventory_records_allows_no_filter(demo_db: Path):
    result = list_inventory_records(db_path=demo_db)

    assert result["ok"] is True
    assert result["data"]["count"] == 10


def test_list_inventory_records_filters_by_computed_status(demo_db: Path):
    result = list_inventory_records(status="out_of_stock", db_path=demo_db)

    assert result["ok"] is True
    assert result["data"]["count"] >= 1
    assert all(record["status"] == "out_of_stock" for record in result["data"]["records"])


def test_inventory_summary_uses_computed_statuses(demo_db: Path):
    records = list_inventory_records(db_path=demo_db)["data"]["records"]
    summary = query_inventory_summary(db_path=demo_db)

    assert summary["ok"] is True
    assert summary["data"]["sku_total"] == len(records)
    assert summary["data"]["low_stock"] == sum(
        record["status"] == "low_stock" for record in records
    )
    assert summary["data"]["out_of_stock"] == sum(
        record["status"] == "out_of_stock" for record in records
    )


def test_query_inventory_missing_sku_returns_not_found(demo_db: Path):
    result = query_inventory_by_sku("SKU-999", db_path=demo_db)

    assert result["ok"] is False
    assert result["code"] == NOT_FOUND
    assert "SKU-999" in result["message"]


def test_query_inventory_without_any_filter_is_invalid_argument(demo_db: Path):
    result = query_inventory(db_path=demo_db)

    assert result["ok"] is False
    assert result["code"] == INVALID_ARGUMENT


# ==========================================================================
# 物流查询
# ==========================================================================


def test_query_logistics_by_shipment_id(demo_db: Path):
    result = query_logistics(shipment_id="SHP-1001-A", db_path=demo_db)

    assert result["ok"] is True
    assert result["data"]["shipment"]["shipment_id"] == "SHP-1001-A"
    assert result["data"]["current_status"]
    assert result["data"]["shipment_count"] == 1


def test_query_logistics_by_tracking_number(demo_db: Path):
    result = query_logistics(tracking_number="SF-1005-B", db_path=demo_db)

    assert result["ok"] is True
    assert result["data"]["shipment"]["order_id"] == "1005"


def test_query_logistics_by_tracking_number_is_case_insensitive(demo_db: Path):
    result = query_logistics(tracking_number="sf-1005-b", db_path=demo_db)

    assert result["ok"] is True
    assert result["data"]["shipment"]["tracking_number"] == "SF-1005-B"


def test_query_logistics_by_order_returns_all_shipments(demo_db: Path):
    """按订单查物流要返回全部包裹，且每个包裹带自己的轨迹与当前状态。"""
    result = query_logistics(order_id="1005", db_path=demo_db)

    assert result["ok"] is True
    data = result["data"]
    assert data["shipment_count"] == 2
    assert [shipment["shipment_id"] for shipment in data["shipments"]] == ["SHP-1005-A", "SHP-1005-B"]
    assert all(shipment["events"] for shipment in data["shipments"])
    assert {shipment["shipment_id"]: shipment["current_status"] for shipment in data["shipments"]} == {
        "SHP-1005-A": "in_transit",
        "SHP-1005-B": "out_for_delivery",
    }
    # 兼容字段仍指向首个包裹
    assert data["shipment"]["shipment_id"] == "SHP-1005-A"
    assert data["current_status"] == "in_transit"


def test_list_shipment_records_filters_by_order_country(demo_db: Path):
    result = list_shipment_records(country="cn", db_path=demo_db)

    assert result["ok"] is True
    records = result["data"]["records"]
    assert records
    with sqlite3.connect(demo_db) as conn:
        countries = {
            row[0]
            for record in records
            for row in conn.execute(
                "SELECT customer_country FROM orders WHERE order_id = ?",
                (record["order_id"],),
            ).fetchall()
        }
    assert {country.upper() for country in countries} == {"CN"}


def test_shipment_list_keyword_matches_order_id(demo_db: Path):
    result = list_shipment_records(search="1005", db_path=demo_db)

    assert result["ok"] is True
    assert {record["shipment_id"] for record in result["data"]["records"]} == {
        "SHP-1005-A",
        "SHP-1005-B",
    }


def test_query_logistics_events_are_sorted_ascending(demo_db: Path):
    result = query_logistics(order_id="1005", db_path=demo_db)

    for shipment in result["data"]["shipments"]:
        times = [event["event_time"] for event in shipment["events"]]
        assert times == sorted(times)
        assert times


def test_query_shipment_events_returns_ascending_timeline(demo_db: Path):
    result = query_shipment_events("SHP-1005-A", db_path=demo_db)

    assert result["ok"] is True
    times = [event["event_time"] for event in result["data"]["events"]]
    assert times == sorted(times)
    assert result["data"]["count"] == len(times)
    assert result["data"]["count"] >= 1


def test_workbench_aggregate_queries_reuse_unified_records(demo_db: Path):
    orders = list_order_records(db_path=demo_db)["data"]["records"]
    shipments = list_shipment_records(db_path=demo_db)["data"]["records"]
    events = list_tracking_event_records(db_path=demo_db)["data"]["records"]
    warehouses = list_warehouse_records(db_path=demo_db)["data"]["records"]

    order_summary = query_order_summary(db_path=demo_db)
    shipment_summary = query_shipment_summary(db_path=demo_db)
    dashboard = query_dashboard_summary(db_path=demo_db)

    assert order_summary["data"]["total"] == len(orders)
    assert shipment_summary["data"]["total"] == len(shipments)
    assert shipment_summary["data"]["event_total"] == len(events)
    assert warehouses
    assert dashboard["ok"] is True
    assert dashboard["data"]["recent_orders"] == orders[:5]
    assert dashboard["data"]["shipment_exception_count"] == sum(
        row["shipping_status"] == "exception" for row in shipments
    )


def test_query_logistics_without_shipment_returns_no_logistics(seeded_db: Path):
    """订单存在但没有包裹：必须与「订单不存在」区分开。"""
    result = query_logistics(order_id="1003", db_path=seeded_db)

    assert result["ok"] is False
    assert result["code"] == NO_LOGISTICS
    assert "1003" in result["message"]
    assert result["data"]["shipments"] == []


@pytest.mark.parametrize("order_id", NO_LOGISTICS_ORDERS)
def test_orders_without_shipment_report_no_logistics(demo_db: Path, order_id: str):
    assert query_order(order_id, db_path=demo_db)["ok"] is True
    assert query_logistics(order_id=order_id, db_path=demo_db)["code"] == NO_LOGISTICS


def test_query_logistics_missing_order_returns_not_found(seeded_db: Path):
    result = query_logistics(order_id="999999", db_path=seeded_db)

    assert result["ok"] is False
    assert result["code"] == NOT_FOUND


def test_query_logistics_missing_shipment_returns_not_found(seeded_db: Path):
    result = query_logistics(shipment_id="SHP-NONE", db_path=seeded_db)

    assert result["ok"] is False
    assert result["code"] == NOT_FOUND
    assert "SHP-NONE" in result["message"]


def test_query_shipment_events_missing_shipment_returns_not_found(seeded_db: Path):
    result = query_shipment_events("SHP-NONE", db_path=seeded_db)

    assert result["ok"] is False
    assert result["code"] == NOT_FOUND


def test_query_logistics_without_any_identifier_is_invalid_argument(seeded_db: Path):
    result = query_logistics(db_path=seeded_db)

    assert result["ok"] is False
    assert result["code"] == INVALID_ARGUMENT


def test_no_logistics_and_not_found_are_different_codes(seeded_db: Path):
    """两类「查不到」必须区分：订单不存在 vs 订单存在但无物流。"""
    assert query_logistics(order_id="1003", db_path=seeded_db)["code"] == NO_LOGISTICS
    assert query_logistics(order_id="999999", db_path=seeded_db)["code"] == NOT_FOUND


# ==========================================================================
# 数据库错误
# ==========================================================================


def test_query_order_reports_db_error_for_corrupt_database(tmp_path: Path):
    broken = tmp_path / "broken.db"
    broken.write_text("这不是一个 SQLite 数据库", encoding="utf-8")

    result = query_order("1001", db_path=broken)

    assert result["ok"] is False
    assert result["code"] == DB_ERROR
    assert result["message"]


@pytest.mark.parametrize(
    "call",
    [
        lambda db: query_order("1001", db_path=db),
        lambda db: query_order_items("1001", db_path=db),
        lambda db: query_order_status("1001", db_path=db),
        lambda db: query_inventory_by_sku("SKU-001", db_path=db),
        lambda db: query_logistics(order_id="1001", db_path=db),
        lambda db: query_shipment_events("SHP-1001-A", db_path=db),
    ],
)
def test_every_tool_surfaces_db_errors_as_structured_result(tmp_path: Path, call):
    """底层异常一律转成 DB_ERROR，不允许直接抛出。"""
    broken = tmp_path / "broken.db"
    broken.write_text("not a database", encoding="utf-8")

    result = call(broken)

    assert result["ok"] is False
    assert result["code"] == DB_ERROR


def test_tool_layer_never_raises(monkeypatch, seeded_db: Path):
    """业务查询函数在任何异常下都返回结构化结果。"""

    def boom(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("ecommerce_assistant.tools.database.get_order_by_id", boom)

    result = query_order("1001", db_path=seeded_db)

    assert result["ok"] is False
    assert result["code"] == DB_ERROR
    assert "database is locked" in result["message"]
