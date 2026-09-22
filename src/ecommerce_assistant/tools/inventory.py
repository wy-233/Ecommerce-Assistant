from __future__ import annotations

from pathlib import Path

from ecommerce_assistant.db.init_db import DEFAULT_DB_PATH, get_inventory_by_sku, init_db

INVENTORY = {
    "SKU-001": {"stock": 24, "status": "有货"},
    "SKU-002": {"stock": 0, "status": "缺货"},
    "SKU-003": {"stock": 7, "status": "库存充足"},
}


def _legacy_inventory_status(sku: str) -> str:
    item = INVENTORY.get(sku)
    if not item:
        return f"未找到 SKU {sku}，请确认商品编码是否正确。"
    return f"商品 {sku} 当前库存：{item['stock']} 件，状态：{item['status']}。"


def get_inventory_status(sku: str, db_path: str | Path | None = None) -> str:
    sku = str(sku).strip().upper()
    database_path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH

    try:
        init_db(database_path)
        row = get_inventory_by_sku(sku, database_path)
        if row:
            available = row.get("available", 0)
            on_hand = row.get("on_hand", 0)
            warehouse = row.get("warehouse_name") or "未知仓库"
            return (
                f"商品 {sku} 当前库存：{on_hand} 件，"
                f"可用库存：{available} 件，仓库：{warehouse}。"
            )
    except Exception:
        pass

    return _legacy_inventory_status(sku)
