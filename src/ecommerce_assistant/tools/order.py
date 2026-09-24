from __future__ import annotations

from pathlib import Path

from ecommerce_assistant.schema.statuses import COUNTRY_LABELS, ORDER_STATUS_LABELS, label_of
from ecommerce_assistant.tools.database import query_order_status


def _format_order_status_message(order_id: str, result: dict) -> str:
    if not result["ok"]:
        return result["message"]

    data = result["data"]
    status = label_of(ORDER_STATUS_LABELS, data.get("status"))
    country = label_of(COUNTRY_LABELS, data.get("customer_country"))
    item_count = data.get("item_count", 0)
    shipment_count = data.get("shipment_count", 0)
    return (
        f"订单 {order_id} 当前状态：{status}。"
        f"客户地区：{country}。"
        f"订单包含 {item_count} 个商品，{shipment_count} 个包裹。"
        f"订单信息已从 SQLite 载入。"
    )


def get_order_status(order_id: str, db_path: str | Path | None = None) -> str:
    result = query_order_status(order_id, db_path=db_path)
    return _format_order_status_message(str(order_id).strip(), result)
