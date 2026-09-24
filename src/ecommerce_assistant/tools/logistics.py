from __future__ import annotations

from pathlib import Path

from ecommerce_assistant.schema.statuses import SHIPPING_STATUS_LABELS, label_of
from ecommerce_assistant.tools.database import query_logistics


def _format_single_shipment(order_id: str, shipment: dict) -> str:
    carrier = shipment.get("carrier") or "未知承运商"
    tracking_number = shipment.get("tracking_number") or "未知单号"
    status = label_of(SHIPPING_STATUS_LABELS, shipment.get("current_status"))
    return (
        f"订单 {order_id} 使用的是 {carrier} 物流服务。"
        f"当前状态：{status}，物流单号：{tracking_number}。"
    )


def _format_multi_shipment(order_id: str, shipments: list[dict]) -> str:
    segments = []
    for shipment in shipments:
        carrier = shipment.get("carrier") or "未知承运商"
        tracking_number = shipment.get("tracking_number") or "未知单号"
        status = label_of(SHIPPING_STATUS_LABELS, shipment.get("current_status"))
        segments.append(
            f"{shipment.get('shipment_id')}（{carrier}）当前状态：{status}，物流单号：{tracking_number}"
        )
    return f"订单 {order_id} 共 {len(shipments)} 个包裹：" + "；".join(segments) + "。"


def _format_logistics_status_message(order_id: str, result: dict) -> str:
    if not result["ok"]:
        return result["message"]

    data = result["data"]
    shipments = data.get("shipments") or []
    if len(shipments) > 1:
        return _format_multi_shipment(order_id, shipments)

    shipment = data.get("shipment") or (shipments[0] if shipments else {})
    if not shipment:
        return f"订单 {order_id} 暂时没有可用的物流信息。"
    payload = dict(shipment)
    payload.setdefault("current_status", data.get("current_status"))
    return _format_single_shipment(order_id, payload)


def get_logistics_status(order_id: str, db_path: str | Path | None = None) -> str:
    result = query_logistics(order_id=str(order_id), db_path=db_path)
    return _format_logistics_status_message(str(order_id).strip(), result)
