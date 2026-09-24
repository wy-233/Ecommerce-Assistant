"""工作台展示适配层。

业务数据全部来自 ``tools.database``；本模块只保留页面需要的字段整形、
中文状态标签和兼容返回值，不直接访问数据库。
"""

from __future__ import annotations

from typing import Any

from ecommerce_assistant.schema.statuses import (
    COUNTRY_LABELS,
    FULFILLMENT_STATUS_LABELS,
    INVENTORY_STATUS_LABELS,
    ORDER_STATUS_LABELS,
    PAYMENT_STATUS_LABELS,
    SHIPPING_STATUS_LABELS,
    label_of,
)
from ecommerce_assistant.tools.database import (
    list_inventory_records,
    list_order_records,
    list_shipment_records,
    list_warehouse_records,
    query_dashboard_summary,
    query_inventory_summary,
    query_order,
    query_order_items,
    query_order_shipments,
    query_order_summary,
    query_shipment_events,
    query_shipment_summary,
)

DEMO_NOTICE = "演示数据，不代表真实商家业务数据"


def _records(result: dict[str, Any]) -> list[dict[str, Any]]:
    if not result.get("ok"):
        return []
    return list(result["data"].get("records") or [])


def _label_order(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    payload["country_label"] = label_of(COUNTRY_LABELS, payload.get("customer_country"))
    payload["order_status_label"] = label_of(
        ORDER_STATUS_LABELS, payload.get("order_status")
    )
    payload["payment_status_label"] = label_of(
        PAYMENT_STATUS_LABELS, payload.get("payment_status")
    )
    payload["fulfillment_status_label"] = label_of(
        FULFILLMENT_STATUS_LABELS, payload.get("fulfillment_status")
    )
    return payload


def _label_shipment(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    payload["shipping_status_label"] = label_of(
        SHIPPING_STATUS_LABELS, payload.get("shipping_status")
    )
    return payload


def list_orders(
    *,
    status: str | None = None,
    country: str | None = None,
    keyword: str | None = None,
) -> list[dict[str, Any]]:
    result = list_order_records(search=keyword, status=status, country=country)
    return [_label_order(row) for row in _records(result)]


def get_order(order_id: str) -> dict[str, Any] | None:
    result = query_order(str(order_id))
    if not result.get("ok"):
        return None
    return _label_order(result["data"])


def list_order_items(order_id: str) -> list[dict[str, Any]]:
    result = query_order_items(str(order_id))
    items = list((result.get("data") or {}).get("items") or [])
    for item in items:
        item["subtotal"] = round(
            float(item.get("quantity") or 0) * float(item.get("unit_price") or 0), 2
        )
    return items


def list_shipments_by_order(order_id: str) -> list[dict[str, Any]]:
    result = query_order_shipments(str(order_id))
    shipments = list((result.get("data") or {}).get("shipments") or [])
    return [_label_shipment(row) for row in shipments]


def order_summary() -> dict[str, int]:
    result = query_order_summary()
    return dict(result["data"]) if result.get("ok") else {
        "total": 0,
        "pending_payment": 0,
        "shipped": 0,
        "cancelled": 0,
    }


def list_inventory(
    *,
    warehouse: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
) -> list[dict[str, Any]]:
    result = list_inventory_records(
        warehouse_id=warehouse,
        status=status,
        keyword=keyword,
    )
    rows = _records(result)
    for row in rows:
        row["status_label"] = label_of(INVENTORY_STATUS_LABELS, row.get("status"))
    return rows


def list_warehouses() -> list[dict[str, str]]:
    return _records(list_warehouse_records())


def inventory_summary() -> dict[str, int]:
    result = query_inventory_summary()
    return dict(result["data"]) if result.get("ok") else {
        "sku_total": 0,
        "on_hand_total": 0,
        "available_total": 0,
        "low_stock": 0,
        "out_of_stock": 0,
    }


def list_shipments(
    *, status: str | None = None, keyword: str | None = None
) -> list[dict[str, Any]]:
    result = list_shipment_records(search=keyword, status=status)
    return [_label_shipment(row) for row in _records(result)]


def list_tracking_events(shipment_id: str) -> list[dict[str, Any]]:
    result = query_shipment_events(str(shipment_id))
    events = list((result.get("data") or {}).get("events") or [])
    for event in events:
        event["event_status_label"] = label_of(
            SHIPPING_STATUS_LABELS, event.get("event_status")
        )
    return events


def shipment_summary() -> dict[str, int]:
    result = query_shipment_summary()
    return dict(result["data"]) if result.get("ok") else {
        "total": 0,
        "in_transit": 0,
        "exception": 0,
        "delivered": 0,
        "event_total": 0,
    }


def dashboard_summary() -> dict[str, Any]:
    result = query_dashboard_summary()
    if not result.get("ok"):
        return {
            "today_order_count": 0,
            "pending_order_count": 0,
            "pending_shipping_order_count": 0,
            "in_transit_shipment_count": 0,
            "low_stock_sku_count": 0,
            "shipment_exception_count": 0,
            "recent_orders": [],
            "inventory_alerts": [],
            "shipment_alerts": [],
            "data_updated_at": "",
        }

    payload = dict(result["data"])
    payload["recent_orders"] = [
        _label_order(row) for row in payload.get("recent_orders", [])
    ]
    for row in payload.get("inventory_alerts", []):
        row["status_label"] = label_of(INVENTORY_STATUS_LABELS, row.get("status"))
    payload["shipment_alerts"] = [
        _label_shipment(row) for row in payload.get("shipment_alerts", [])
    ]
    return payload
