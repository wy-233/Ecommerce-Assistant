from __future__ import annotations

from pathlib import Path

from ecommerce_assistant.db.init_db import DEFAULT_DB_PATH, get_order_by_id, init_db

ORDERS = {
    "1001": {
        "status": "运输中",
        "location": "深圳中转站",
        "shipping_method": "DHL",
    },
    "1002": {
        "status": "已签收",
        "location": "上海市浦东新区",
        "shipping_method": "FedEx",
    },
    "1003": {
        "status": "已出库",
        "location": "宁波港",
        "shipping_method": "UPS",
    },
}


def _legacy_order_status(order_id: str) -> str:
    order = ORDERS.get(order_id)
    if not order:
        return f"未找到订单号 {order_id}，请确认订单号是否正确。"
    return (
        f"订单 {order_id} 当前状态：{order['status']}。"
        f"当前位置：{order['location']}。"
        f"物流方式：{order['shipping_method']}。"
    )


def get_order_status(order_id: str, db_path: str | Path | None = None) -> str:
    order_id = str(order_id).strip()
    database_path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH

    try:
        init_db(database_path)
        row = get_order_by_id(order_id, database_path)
        if row:
            status = row.get("order_status", "unknown")
            country = row.get("customer_country", "CN")
            return (
                f"订单 {order_id} 当前状态：{status}。"
                f"客户地区：{country}。"
                f"订单信息已从 SQLite 载入。"
            )
    except Exception:
        pass

    return _legacy_order_status(order_id)
