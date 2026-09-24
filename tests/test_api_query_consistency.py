"""API 只读端点与业务查询层同源的契约测试。

断言 API 端点的返回只来自 tools.database（Agent 工具走的同一套函数），
避免出现「同一指标两个 SQL 版本」。这些用例读取项目根真实库（只读）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from ecommerce_assistant.api.service import app
from ecommerce_assistant.schema.statuses import INVENTORY_STATUS_CODES, SHIPPING_STATUS_CODES
from ecommerce_assistant.tools.database import (
    list_order_records,
    list_shipment_records,
    query_dashboard_summary,
    query_inventory_by_sku,
    query_logistics,
    query_order,
    query_shipment_events,
)
from ecommerce_assistant.workbench import queries as workbench_queries

client = TestClient(app)


def test_inventory_detail_status_matches_query_layer():
    api_status = client.get("/inventory/SKU-001").json()["status"]

    tool_result = query_inventory_by_sku("SKU-001")
    assert tool_result["ok"] is True
    assert api_status == tool_result["data"]["status"]


def test_inventory_status_is_an_english_code_not_a_chinese_label():
    payload = client.get("/inventory/SKU-001").json()

    assert payload["status"] in INVENTORY_STATUS_CODES
    assert payload["status"] == "normal"


def test_inventory_list_items_use_status_codes():
    payload = client.get("/inventory", params={"page": 1, "page_size": 100}).json()

    assert payload["items"]
    for item in payload["items"]:
        assert item["status"] in INVENTORY_STATUS_CODES


def test_inventory_list_status_filter_is_effective():
    payload = client.get("/inventory", params={"status": "out_of_stock", "page_size": 100}).json()

    assert payload["items"]
    assert {item["status"] for item in payload["items"]} == {"out_of_stock"}


def test_dashboard_api_and_workbench_use_same_business_summary():
    api_payload = client.get("/dashboard/summary").json()
    query_result = query_dashboard_summary()
    workbench_payload = workbench_queries.dashboard_summary()

    assert query_result["ok"] is True
    for key in (
        "today_order_count",
        "pending_order_count",
        "pending_shipping_order_count",
        "in_transit_shipment_count",
        "low_stock_sku_count",
        "shipment_exception_count",
        "data_updated_at",
    ):
        assert api_payload[key] == query_result["data"][key] == workbench_payload[key]
    assert [row["order_id"] for row in api_payload["recent_orders"]] == [
        row["order_id"] for row in workbench_payload["recent_orders"]
    ]
    assert [row["sku"] for row in api_payload["inventory_alerts"]] == [
        row["sku"] for row in workbench_payload["inventory_alerts"]
    ]
    assert [row["shipment_id"] for row in api_payload["shipment_alerts"]] == [
        row["shipment_id"] for row in workbench_payload["shipment_alerts"]
    ]


def test_order_carrier_filter_matches_query_layer():
    api_payload = client.get("/orders", params={"carrier": "DHL", "page_size": 100}).json()
    query_result = list_order_records(carrier="DHL")

    assert [item["order_id"] for item in api_payload["items"]] == [
        item["order_id"] for item in query_result["data"]["records"]
    ]


def test_order_warehouse_filter_matches_query_layer():
    api_payload = client.get(
        "/orders", params={"warehouse_id": "WH-001", "page_size": 100}
    ).json()
    query_result = list_order_records(warehouse_id="WH-001")

    assert [item["order_id"] for item in api_payload["items"]] == [
        item["order_id"] for item in query_result["data"]["records"]
    ]


def test_shipment_country_filter_matches_query_layer():
    api_payload = client.get("/shipments", params={"country": "CN", "page_size": 100}).json()
    query_result = list_shipment_records(country="CN")

    assert [item["shipment_id"] for item in api_payload["items"]] == [
        item["shipment_id"] for item in query_result["data"]["records"]
    ]


def test_shipment_warehouse_filter_matches_query_layer():
    api_payload = client.get(
        "/shipments", params={"warehouse_id": "WH-001", "page_size": 100}
    ).json()
    query_result = list_shipment_records(warehouse_id="WH-001")

    assert [item["shipment_id"] for item in api_payload["items"]] == [
        item["shipment_id"] for item in query_result["data"]["records"]
    ]


def test_order_detail_shipments_match_query_layer():
    api_shipments = client.get("/orders/1005").json()["shipments"]

    tool_shipments = query_order("1005")["data"]["shipments"]
    assert [shipment["shipment_id"] for shipment in api_shipments] == [
        shipment["shipment_id"] for shipment in tool_shipments
    ]
    assert len(api_shipments) == 2


def test_order_detail_items_match_query_layer():
    api_items = client.get("/orders/1001").json()["items"]

    tool_items = query_order("1001")["data"]["items"]
    assert [item["sku"] for item in api_items] == [item["sku"] for item in tool_items]


def test_shipment_detail_matches_query_layer():
    api_detail = client.get("/shipments/SHP-1001-A").json()

    tool_shipment = query_logistics(shipment_id="SHP-1001-A")["data"]["shipment"]
    assert api_detail["shipment_id"] == tool_shipment["shipment_id"]
    assert api_detail["current_status"] == tool_shipment["current_status"]
    assert api_detail["current_status"] in SHIPPING_STATUS_CODES


def test_shipment_events_match_query_layer_and_are_ordered():
    api_items = client.get("/shipments/SHP-1005-A/events").json()["items"]

    tool_events = query_shipment_events("SHP-1005-A")["data"]["events"]
    assert [event["event_time"] for event in api_items] == [
        event["event_time"] for event in tool_events
    ]
    times = [event["event_time"] for event in api_items]
    assert times == sorted(times)


def test_missing_inventory_returns_404():
    assert client.get("/inventory/SKU-NOT-EXIST").status_code == 404


def test_missing_order_returns_404():
    assert client.get("/orders/999999").status_code == 404


def test_missing_shipment_returns_404():
    assert client.get("/shipments/SHP-NOT-EXIST").status_code == 404
    assert client.get("/shipments/SHP-NOT-EXIST/events").status_code == 404
