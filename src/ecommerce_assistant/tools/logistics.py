from __future__ import annotations

from pathlib import Path

from ecommerce_assistant.db.init_db import DEFAULT_DB_PATH, get_shipment_by_order_id, init_db

LOGISTICS = {
    "1001": "DHL",
    "1002": "FedEx",
    "1003": "UPS",
}


def _legacy_logistics_status(order_id: str) -> str:
    shipping = LOGISTICS.get(order_id)
    if not shipping:
        return f"未找到订单 {order_id} 的物流信息。"
    return f"订单 {order_id} 使用的是 {shipping} 物流服务。"


def get_logistics_status(order_id: str, db_path: str | Path | None = None) -> str:
    order_id = str(order_id).strip()
    database_path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH

    try:
        init_db(database_path)
        row = get_shipment_by_order_id(order_id, database_path)
        if row:
            carrier = row.get("carrier") or "未知承运商"
            tracking_number = row.get("tracking_number") or "未知单号"
            shipping_status = row.get("shipping_status") or "unknown"
            return (
                f"订单 {order_id} 使用的是 {carrier} 物流服务。"
                f"当前状态：{shipping_status}，物流单号：{tracking_number}。"
            )
    except Exception:
        pass

    return _legacy_logistics_status(order_id)
