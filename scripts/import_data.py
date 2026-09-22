from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR / "src") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "src"))

from ecommerce_assistant.db.init_db import init_db

DEFAULT_DB_PATH = ROOT_DIR / "data" / "ecommerce_assistant.db"

SENSITIVE_FIELD_NAMES = {
    "customer_name",
    "customer_phone",
    "phone",
    "mobile",
    "email",
    "address",
    "full_address",
    "shipping_address",
    "contact_name",
    "customer_email",
    "customer_phone_number",
    "recipient_name",
    "recipient_phone",
    "recipient_email",
    "customer_address",
}


def _now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_valid_iso_datetime(value: str | None) -> bool:
    if value is None or value == "":
        return True
    candidate = (value or "").strip()
    if not candidate:
        return True
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        datetime.fromisoformat(candidate)
        return True
    except ValueError:
        return False


def _is_positive_int(value: Any, *, allow_zero: bool = False) -> bool:
    if value is None:
        return False
    if isinstance(value, int):
        return value >= (0 if allow_zero else 1)
    if isinstance(value, float):
        return value.is_integer() and (value >= (0 if allow_zero else 1))
    text = str(value).strip()
    if not text:
        return False
    if not re.fullmatch(r"[0-9]+", text):
        return False
    number = int(text)
    return number >= (0 if allow_zero else 1)


def _is_numeric(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return True
    text = str(value).strip()
    if not text:
        return False
    try:
        float(text)
        return True
    except ValueError:
        return False


def _normalize_csv_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


class ImportValidationError(ValueError):
    pass


def _field_error(file_name: str, row_number: int, reason: str) -> ImportValidationError:
    return ImportValidationError(f"{file_name}:{row_number}: {reason}")


def _validate_sensitive_fields(row: dict[str, Any], file_name: str, row_number: int) -> None:
    for key, value in row.items():
        key_norm = str(key).strip().lower()
        if key_norm in SENSITIVE_FIELD_NAMES and value not in (None, ""):
            raise _field_error(file_name, row_number, f"敏感字段 '{key}' 不允许导入")


def _populate_unique_sets(conn: sqlite3.Connection) -> tuple[set[str], set[str], set[str], set[str]]:
    existing_orders = {row[0] for row in conn.execute("SELECT order_id FROM orders").fetchall()}
    existing_skus = {row[0] for row in conn.execute("SELECT sku FROM inventory").fetchall()}
    existing_shipments = {row[0] for row in conn.execute("SELECT shipment_id FROM shipments").fetchall()}
    existing_tracking = {row[0] for row in conn.execute("SELECT tracking_number FROM shipments WHERE tracking_number IS NOT NULL").fetchall()}
    return existing_orders, existing_skus, existing_shipments, existing_tracking


def _read_csv_rows(path: str | Path) -> list[dict[str, str]]:
    csv_path = Path(path)
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"{csv_path.name}: CSV 文件字段为空")
        return [
            {key: _normalize_csv_value(value) for key, value in row.items()}
            for row in reader
        ]


def _ensure_required_fields(row: dict[str, Any], required_fields: Iterable[str], file_name: str, row_number: int) -> None:
    for field in required_fields:
        value = row.get(field)
        if value is None or str(value).strip() == "":
            raise _field_error(file_name, row_number, f"缺少必填字段 '{field}'")


def _validate_order_row(row: dict[str, Any], file_name: str, row_number: int) -> None:
    required = [
        "order_id",
        "customer_name_masked",
        "customer_country",
        "order_status",
        "payment_status",
        "fulfillment_status",
        "currency",
        "total_amount",
        "created_at",
        "updated_at",
    ]
    _ensure_required_fields(row, required, file_name, row_number)
    _validate_sensitive_fields(row, file_name, row_number)
    order_id = row["order_id"]
    if not re.fullmatch(r"[A-Za-z0-9\-_.]+", order_id):
        raise _field_error(file_name, row_number, f"订单号格式非法: {order_id}")
    if not _is_numeric(row["total_amount"]):
        raise _field_error(file_name, row_number, "金额字段必须为数字")
    for field in ("created_at", "updated_at"):
        if not _is_valid_iso_datetime(row[field]):
            raise _field_error(file_name, row_number, f"日期格式非法: {field}={row[field]}")


def _validate_order_item_row(row: dict[str, Any], file_name: str, row_number: int, order_ids: set[str]) -> None:
    required = ["order_id", "sku", "product_name", "quantity", "unit_price", "currency"]
    _ensure_required_fields(row, required, file_name, row_number)
    _validate_sensitive_fields(row, file_name, row_number)
    if row["order_id"] not in order_ids:
        raise _field_error(file_name, row_number, f"订单关联不存在: order_id={row['order_id']}")
    if not re.fullmatch(r"[A-Za-z0-9\-_.]+", row["sku"]):
        raise _field_error(file_name, row_number, f"SKU格式非法: {row['sku']}")
    if not _is_positive_int(row["quantity"]):
        raise _field_error(file_name, row_number, f"数量字段必须为合法整数: {row['quantity']}")
    if not _is_numeric(row["unit_price"]):
        raise _field_error(file_name, row_number, f"单价字段必须为数字: {row['unit_price']}")


def _validate_inventory_row(row: dict[str, Any], file_name: str, row_number: int) -> None:
    required = ["sku", "product_name", "warehouse_id", "warehouse_name", "on_hand", "reserved", "available", "safety_stock", "updated_at"]
    _ensure_required_fields(row, required, file_name, row_number)
    _validate_sensitive_fields(row, file_name, row_number)
    if not re.fullmatch(r"[A-Za-z0-9\-_.]+", row["sku"]):
        raise _field_error(file_name, row_number, f"SKU格式非法: {row['sku']}")
    for field in ("on_hand", "reserved", "available", "safety_stock"):
        if not _is_positive_int(row[field], allow_zero=True):
            raise _field_error(file_name, row_number, f"数字字段必须为非负整数: {field}={row[field]}")
    if not _is_valid_iso_datetime(row["updated_at"]):
        raise _field_error(file_name, row_number, f"日期格式非法: updated_at={row['updated_at']}")


def _validate_shipment_row(row: dict[str, Any], file_name: str, row_number: int, order_ids: set[str]) -> None:
    required = ["shipment_id", "order_id", "carrier", "tracking_number", "shipping_status", "shipped_at", "updated_at"]
    _ensure_required_fields(row, required, file_name, row_number)
    _validate_sensitive_fields(row, file_name, row_number)
    if row["order_id"] not in order_ids:
        raise _field_error(file_name, row_number, f"订单关联不存在: order_id={row['order_id']}")
    if not re.fullmatch(r"[A-Za-z0-9\-_.]+", row["shipment_id"]):
        raise _field_error(file_name, row_number, f"包裹号格式非法: {row['shipment_id']}")
    if not re.fullmatch(r"[A-Za-z0-9\-_.]+", row["tracking_number"]):
        raise _field_error(file_name, row_number, f"物流单号格式非法: {row['tracking_number']}")
    for field in ("shipped_at", "updated_at"):
        if field in row and row[field] and not _is_valid_iso_datetime(row[field]):
            raise _field_error(file_name, row_number, f"日期格式非法: {field}={row[field]}")


def _validate_tracking_event_row(row: dict[str, Any], file_name: str, row_number: int, shipment_ids: set[str]) -> None:
    required = ["shipment_id", "event_time", "event_status", "location", "description"]
    _ensure_required_fields(row, required, file_name, row_number)
    _validate_sensitive_fields(row, file_name, row_number)
    if row["shipment_id"] not in shipment_ids:
        raise _field_error(file_name, row_number, f"包裹关联不存在: shipment_id={row['shipment_id']}")
    if not _is_valid_iso_datetime(row["event_time"]):
        raise _field_error(file_name, row_number, f"日期格式非法: event_time={row['event_time']}")


def _upsert_order(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO orders (
            order_id, customer_name_masked, customer_country, order_status,
            payment_status, fulfillment_status, currency, total_amount,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(order_id) DO UPDATE SET
            customer_name_masked = excluded.customer_name_masked,
            customer_country = excluded.customer_country,
            order_status = excluded.order_status,
            payment_status = excluded.payment_status,
            fulfillment_status = excluded.fulfillment_status,
            currency = excluded.currency,
            total_amount = excluded.total_amount,
            updated_at = excluded.updated_at
        """,
        (
            row["order_id"],
            row["customer_name_masked"],
            row["customer_country"],
            row["order_status"],
            row["payment_status"],
            row["fulfillment_status"],
            row["currency"],
            float(row["total_amount"]),
            row["created_at"],
            row["updated_at"],
        ),
    )


def _upsert_order_item(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO order_items (order_id, sku, product_name, quantity, unit_price, currency)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(order_id, sku, product_name) DO UPDATE SET
            quantity = excluded.quantity,
            unit_price = excluded.unit_price,
            currency = excluded.currency
        """,
        (
            row["order_id"],
            row["sku"],
            row["product_name"],
            int(row["quantity"]),
            float(row["unit_price"]),
            row["currency"],
        ),
    )


def _upsert_inventory(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO inventory (
            sku, product_name, warehouse_id, warehouse_name, on_hand,
            reserved, available, safety_stock, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(sku) DO UPDATE SET
            product_name = excluded.product_name,
            warehouse_id = excluded.warehouse_id,
            warehouse_name = excluded.warehouse_name,
            on_hand = excluded.on_hand,
            reserved = excluded.reserved,
            available = excluded.available,
            safety_stock = excluded.safety_stock,
            updated_at = excluded.updated_at
        """,
        (
            row["sku"],
            row["product_name"],
            row["warehouse_id"],
            row["warehouse_name"],
            int(row["on_hand"]),
            int(row["reserved"]),
            int(row["available"]),
            int(row["safety_stock"]),
            row["updated_at"],
        ),
    )


def _upsert_shipment(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO shipments (
            shipment_id, order_id, carrier, tracking_number, shipping_status,
            shipped_at, estimated_delivery_at, delivered_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(shipment_id) DO UPDATE SET
            order_id = excluded.order_id,
            carrier = excluded.carrier,
            tracking_number = excluded.tracking_number,
            shipping_status = excluded.shipping_status,
            shipped_at = excluded.shipped_at,
            estimated_delivery_at = excluded.estimated_delivery_at,
            delivered_at = excluded.delivered_at,
            updated_at = excluded.updated_at
        """,
        (
            row["shipment_id"],
            row["order_id"],
            row["carrier"],
            row["tracking_number"],
            row["shipping_status"],
            row["shipped_at"],
            row.get("estimated_delivery_at") or None,
            row.get("delivered_at") or None,
            row["updated_at"],
        ),
    )


def _upsert_tracking_event(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO tracking_events (shipment_id, event_time, event_status, location, description)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(shipment_id, event_time, event_status, location, description) DO NOTHING
        """,
        (
            row["shipment_id"],
            row["event_time"],
            row["event_status"],
            row["location"],
            row["description"],
        ),
    )


def _read_and_validate(
    path: str | Path,
    *,
    validator,
    file_label: str,
    context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    rows = _read_csv_rows(path)
    validated: list[dict[str, Any]] = []
    for idx, row in enumerate(rows, start=2):
        try:
            if context:
                validator(row, file_label, idx, **context)
            else:
                validator(row, file_label, idx)
            validated.append(row)
        except ImportValidationError:
            raise
        except TypeError as exc:
            raise ImportValidationError(f"{file_label}:{idx}: 参数校验错误: {exc}") from exc
        except Exception as exc:  # pragma: no cover - defensive branch
            raise ImportValidationError(f"{file_label}:{idx}: {exc}") from exc
    return validated


def import_csv_files(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    orders_path: str | Path | None = None,
    order_items_path: str | Path | None = None,
    inventory_path: str | Path | None = None,
    shipments_path: str | Path | None = None,
    tracking_events_path: str | Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    target = Path(db_path)
    if not target.parent.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
    init_db(target)

    if all(path is None for path in (orders_path, order_items_path, inventory_path, shipments_path, tracking_events_path)):
        raise ValueError("至少需要提供一份 CSV 文件")

    orders = _read_and_validate(orders_path or "", validator=_validate_order_row, file_label=Path(orders_path or "orders.csv").name) if orders_path else []
    order_items = _read_and_validate(order_items_path or "", validator=_validate_order_item_row, file_label=Path(order_items_path or "order_items.csv").name, context={"order_ids": set(row["order_id"] for row in orders)}) if order_items_path else []
    inventory = _read_and_validate(inventory_path or "", validator=_validate_inventory_row, file_label=Path(inventory_path or "inventory.csv").name) if inventory_path else []
    shipments = _read_and_validate(shipments_path or "", validator=_validate_shipment_row, file_label=Path(shipments_path or "shipments.csv").name, context={"order_ids": set(row["order_id"] for row in orders)}) if shipments_path else []
    tracking_events = _read_and_validate(tracking_events_path or "", validator=_validate_tracking_event_row, file_label=Path(tracking_events_path or "tracking_events.csv").name, context={"shipment_ids": set(row["shipment_id"] for row in shipments)}) if tracking_events_path else []

    if dry_run:
        return {
            "dry_run": True,
            "orders_imported": len(orders),
            "order_items_imported": len(order_items),
            "inventory_imported": len(inventory),
            "shipments_imported": len(shipments),
            "tracking_events_imported": len(tracking_events),
        }

    with sqlite3.connect(str(target)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN")
        try:
            for row in orders:
                _upsert_order(conn, row)
            for row in order_items:
                _upsert_order_item(conn, row)
            for row in inventory:
                _upsert_inventory(conn, row)
            for row in shipments:
                _upsert_shipment(conn, row)
            for row in tracking_events:
                _upsert_tracking_event(conn, row)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return {
        "dry_run": False,
        "orders_imported": len(orders),
        "order_items_imported": len(order_items),
        "inventory_imported": len(inventory),
        "shipments_imported": len(shipments),
        "tracking_events_imported": len(tracking_events),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="将授权、脱敏后的真实业务 CSV 导入 SQLite")
    parser.add_argument("--db-path", type=str, default=str(DEFAULT_DB_PATH), help="SQLite 数据库文件路径")
    parser.add_argument("--orders", type=str, default="", help="orders.csv 路径")
    parser.add_argument("--order-items", type=str, default="", help="order_items.csv 路径")
    parser.add_argument("--inventory", type=str, default="", help="inventory.csv 路径")
    parser.add_argument("--shipments", type=str, default="", help="shipments.csv 路径")
    parser.add_argument("--tracking-events", type=str, default="", help="tracking_events.csv 路径")
    parser.add_argument("--dry-run", action="store_true", help="仅校验 CSV，不写入数据库")
    args = parser.parse_args()

    try:
        result = import_csv_files(
            db_path=args.db_path,
            orders_path=args.orders or None,
            order_items_path=args.order_items or None,
            inventory_path=args.inventory or None,
            shipments_path=args.shipments or None,
            tracking_events_path=args.tracking_events or None,
            dry_run=args.dry_run,
        )
        print(result)
    except Exception as exc:
        print(f"IMPORT_ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
