import csv
import sqlite3
from pathlib import Path

import pytest

from scripts.import_data import import_csv_files
from ecommerce_assistant.db.init_db import init_db


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _build_valid_inputs(tmp_path: Path) -> dict[str, Path]:
    orders = tmp_path / "orders.csv"
    _write_csv(
        orders,
        [
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
        ],
        [
            {
                "order_id": "ORD-1001",
                "customer_name_masked": "C***",
                "customer_country": "CN",
                "order_status": "paid",
                "payment_status": "paid",
                "fulfillment_status": "processing",
                "currency": "CNY",
                "total_amount": "528.00",
                "created_at": "2024-01-15T10:00:00Z",
                "updated_at": "2024-01-16T09:30:00Z",
            }
        ],
    )

    order_items = tmp_path / "order_items.csv"
    _write_csv(
        order_items,
        ["order_id", "sku", "product_name", "quantity", "unit_price", "currency"],
        [
            {
                "order_id": "ORD-1001",
                "sku": "SKU-001",
                "product_name": "智能音箱",
                "quantity": "1",
                "unit_price": "299.00",
                "currency": "CNY",
            }
        ],
    )

    inventory = tmp_path / "inventory.csv"
    _write_csv(
        inventory,
        [
            "sku",
            "product_name",
            "warehouse_id",
            "warehouse_name",
            "on_hand",
            "reserved",
            "available",
            "safety_stock",
            "updated_at",
        ],
        [
            {
                "sku": "SKU-001",
                "product_name": "智能音箱",
                "warehouse_id": "WH-001",
                "warehouse_name": "深圳仓",
                "on_hand": "24",
                "reserved": "2",
                "available": "22",
                "safety_stock": "5",
                "updated_at": "2024-01-15T10:00:00Z",
            }
        ],
    )

    shipments = tmp_path / "shipments.csv"
    _write_csv(
        shipments,
        [
            "shipment_id",
            "order_id",
            "carrier",
            "tracking_number",
            "shipping_status",
            "shipped_at",
            "estimated_delivery_at",
            "delivered_at",
            "updated_at",
        ],
        [
            {
                "shipment_id": "SHIP-1001",
                "order_id": "ORD-1001",
                "carrier": "DHL",
                "tracking_number": "DHL123456789",
                "shipping_status": "in_transit",
                "shipped_at": "2024-01-16T08:00:00Z",
                "estimated_delivery_at": "2024-01-18T00:00:00Z",
                "delivered_at": "",
                "updated_at": "2024-01-16T10:00:00Z",
            }
        ],
    )

    tracking_events = tmp_path / "tracking_events.csv"
    _write_csv(
        tracking_events,
        ["shipment_id", "event_time", "event_status", "location", "description"],
        [
            {
                "shipment_id": "SHIP-1001",
                "event_time": "2024-01-16T08:15:00Z",
                "event_status": "picked_up",
                "location": "深圳仓",
                "description": "包裹已离库",
            }
        ],
    )

    return {
        "orders": orders,
        "order_items": order_items,
        "inventory": inventory,
        "shipments": shipments,
        "tracking_events": tracking_events,
    }


def test_import_csv_files_success(tmp_path):
    db_file = tmp_path / "import.db"
    init_db(db_file)
    files = _build_valid_inputs(tmp_path)

    result = import_csv_files(
        db_path=db_file,
        orders_path=files["orders"],
        order_items_path=files["order_items"],
        inventory_path=files["inventory"],
        shipments_path=files["shipments"],
        tracking_events_path=files["tracking_events"],
    )

    assert result["orders_imported"] == 1
    assert result["order_items_imported"] == 1
    assert result["inventory_imported"] == 1
    assert result["shipments_imported"] == 1
    assert result["tracking_events_imported"] == 1

    with sqlite3.connect(db_file) as conn:
        assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM order_items").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM shipments").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM tracking_events").fetchone()[0] == 1


def test_import_fails_for_missing_required_fields(tmp_path):
    db_file = tmp_path / "missing_fields.db"
    init_db(db_file)
    files = _build_valid_inputs(tmp_path)

    with files["orders"].open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows[0]["order_id"] = ""
    _write_csv(
        files["orders"],
        [
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
        ],
        rows,
    )

    with pytest.raises(ValueError, match="订单号|required|字段"):
        import_csv_files(
            db_path=db_file,
            orders_path=files["orders"],
            order_items_path=files["order_items"],
            inventory_path=files["inventory"],
            shipments_path=files["shipments"],
            tracking_events_path=files["tracking_events"],
        )


def test_import_fails_for_invalid_quantity_and_date(tmp_path):
    db_file = tmp_path / "invalid_numeric.db"
    init_db(db_file)
    files = _build_valid_inputs(tmp_path)

    with files["order_items"].open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows[0]["quantity"] = "abc"
    _write_csv(
        files["order_items"],
        ["order_id", "sku", "product_name", "quantity", "unit_price", "currency"],
        rows,
    )

    with pytest.raises(ValueError, match="数量|数字|日期|格式"):
        import_csv_files(
            db_path=db_file,
            orders_path=files["orders"],
            order_items_path=files["order_items"],
            inventory_path=files["inventory"],
            shipments_path=files["shipments"],
            tracking_events_path=files["tracking_events"],
        )

    files = _build_valid_inputs(tmp_path)
    with files["shipments"].open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows[0]["shipped_at"] = "INVALID-DATE"
    _write_csv(
        files["shipments"],
        [
            "shipment_id",
            "order_id",
            "carrier",
            "tracking_number",
            "shipping_status",
            "shipped_at",
            "estimated_delivery_at",
            "delivered_at",
            "updated_at",
        ],
        rows,
    )

    with pytest.raises(ValueError, match="日期|格式"):
        import_csv_files(
            db_path=db_file,
            orders_path=files["orders"],
            order_items_path=files["order_items"],
            inventory_path=files["inventory"],
            shipments_path=files["shipments"],
            tracking_events_path=files["tracking_events"],
        )


def test_import_fails_for_missing_related_order_and_tracking_reference(tmp_path):
    db_file = tmp_path / "missing_reference.db"
    init_db(db_file)
    files = _build_valid_inputs(tmp_path)

    bad_order_items = files["order_items"].read_text(encoding="utf-8").replace("ORD-1001", "ORD-404", 1)
    files["order_items"].write_text(bad_order_items, encoding="utf-8")

    with pytest.raises(ValueError, match="关联|不存在|订单"):
        import_csv_files(
            db_path=db_file,
            orders_path=files["orders"],
            order_items_path=files["order_items"],
            inventory_path=files["inventory"],
            shipments_path=files["shipments"],
            tracking_events_path=files["tracking_events"],
        )

    valid_shipments = files["shipments"]
    bad_tracking = files["tracking_events"].read_text(encoding="utf-8").replace("SHIP-1001", "SHIP-404", 1)
    files["tracking_events"].write_text(bad_tracking, encoding="utf-8")

    with pytest.raises(ValueError, match="包裹|不存在|关联"):
        import_csv_files(
            db_path=db_file,
            orders_path=files["orders"],
            order_items_path=files["order_items"],
            inventory_path=files["inventory"],
            shipments_path=valid_shipments,
            tracking_events_path=files["tracking_events"],
        )


def test_dry_run_does_not_write_db_and_duplicate_import_is_idempotent(tmp_path):
    db_file = tmp_path / "dry_run.db"
    init_db(db_file)
    files = _build_valid_inputs(tmp_path)

    result = import_csv_files(
        db_path=db_file,
        orders_path=files["orders"],
        order_items_path=files["order_items"],
        inventory_path=files["inventory"],
        shipments_path=files["shipments"],
        tracking_events_path=files["tracking_events"],
        dry_run=True,
    )

    assert result["dry_run"] is True
    with sqlite3.connect(db_file) as conn:
        assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0

    import_csv_files(
        db_path=db_file,
        orders_path=files["orders"],
        order_items_path=files["order_items"],
        inventory_path=files["inventory"],
        shipments_path=files["shipments"],
        tracking_events_path=files["tracking_events"],
    )
    import_csv_files(
        db_path=db_file,
        orders_path=files["orders"],
        order_items_path=files["order_items"],
        inventory_path=files["inventory"],
        shipments_path=files["shipments"],
        tracking_events_path=files["tracking_events"],
    )

    with sqlite3.connect(db_file) as conn:
        assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM order_items").fetchone()[0] == 1
