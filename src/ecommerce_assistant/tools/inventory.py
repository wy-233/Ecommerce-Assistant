from __future__ import annotations

from pathlib import Path

from ecommerce_assistant.schema.statuses import INVENTORY_STATUS_LABELS, label_of
from ecommerce_assistant.tools.database import query_inventory_by_sku


def _format_inventory_status_message(sku: str, result: dict) -> str:
    if not result["ok"]:
        return result["message"]

    data = result["data"]
    on_hand = data.get("on_hand", 0)
    reserved = data.get("reserved", 0)
    available = data.get("available", 0)
    safety_stock = data.get("safety_stock", 0)
    warehouse = data.get("warehouse_name") or "未知仓库"
    status = label_of(INVENTORY_STATUS_LABELS, data.get("status"))
    message = (
        f"商品 {sku} 当前库存：{on_hand} 件，"
        f"预留：{reserved} 件，"
        f"可用：{available} 件，"
        f"安全库存：{safety_stock} 件，"
        f"仓库：{warehouse}，"
        f"状态：{status}。"
    )
    if data.get("status_mismatch"):
        stored = label_of(INVENTORY_STATUS_LABELS, data.get("stored_status"))
        message += f"（注：库存表落库状态为 {stored}，与可用量规则不一致，请核查数据。）"
    return message


def get_inventory_status(sku: str, db_path: str | Path | None = None) -> str:
    result = query_inventory_by_sku(sku=str(sku), db_path=db_path)
    normalized_sku = str(sku).strip().upper()
    return _format_inventory_status_message(normalized_sku, result)
