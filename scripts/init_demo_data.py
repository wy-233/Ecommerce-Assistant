from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT_DIR / "data" / "demo"
DEFAULT_DB_PATH = ROOT_DIR / "data" / "ecommerce_assistant.db"

if str(ROOT_DIR / "src") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "src"))

from ecommerce_assistant.db.init_db import init_db


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _clear_demo_tables(conn: sqlite3.Connection) -> None:
    """清空业务表与商品/仓库主数据表。

    用 DELETE 而非 DROP TABLE：
    - DROP 会连带删除表结构与 chat/knowledge 数据，且 CREATE 属于隐式提交，会让
      「表被清空但新数据尚未写入」的中间态对其他连接可见，正是历史上金额不自洽的成因；
    - DELETE 是纯 DML，包在单个事务里对其他连接不可见，可彻底消除该窗口。
    删除顺序按外键依赖反向排列，避免触发 RESTRICT。
    """
    for table in (
        "tracking_events",
        "shipments",
        "order_items",
        "orders",
        "inventory",
        "products",
        "warehouses",
    ):
        conn.execute(f"DELETE FROM {table}")


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader)


def _upsert_orders(conn: sqlite3.Connection) -> int:
    rows = _read_csv_rows(DEMO_DIR / "orders.csv")
    for row in rows:
        conn.execute(
            """
            INSERT OR IGNORE INTO orders (
                order_id, customer_name_masked, customer_country, order_status,
                payment_status, fulfillment_status, currency, total_amount,
                created_at, updated_at, is_demo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                row.get("is_demo") or "DEMO",
            ),
        )
    return conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]


def _verify_amount_consistency(conn: sqlite3.Connection) -> None:
    """订单主表金额必须等于明细汇总，否则导入直接失败，避免脏数据进入演示库。"""
    mismatched = conn.execute(
        """
        SELECT o.order_id,
               o.total_amount AS declared,
               COALESCE(SUM(i.quantity * i.unit_price), 0) AS computed
        FROM orders o
        LEFT JOIN order_items i ON i.order_id = o.order_id
        GROUP BY o.order_id
        HAVING ABS(o.total_amount - computed) > 0.01
        ORDER BY o.order_id
        """
    ).fetchall()
    if mismatched:
        detail = "；".join(
            f"{row['order_id']}（主表 {row['declared']:.2f} / 明细 {row['computed']:.2f}）"
            for row in mismatched
        )
        raise ValueError(f"订单总金额与商品明细不一致：{detail}")


def _upsert_order_items(conn: sqlite3.Connection) -> int:
    rows = _read_csv_rows(DEMO_DIR / "order_items.csv")
    for row in rows:
        conn.execute(
            """
            INSERT OR IGNORE INTO order_items (
                order_id, sku, product_name, quantity, unit_price, currency, is_demo
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["order_id"],
                row["sku"],
                row["product_name"],
                int(row["quantity"]),
                float(row["unit_price"]),
                row["currency"],
                row.get("is_demo") or "DEMO",
            ),
        )
    return conn.execute("SELECT COUNT(*) FROM order_items").fetchone()[0]


def _upsert_inventory(conn: sqlite3.Connection) -> int:
    rows = _read_csv_rows(DEMO_DIR / "inventory.csv")
    for row in rows:
        conn.execute(
            """
            INSERT INTO products (sku, product_name, updated_at, is_demo)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(sku) DO UPDATE SET
                product_name = excluded.product_name,
                updated_at = excluded.updated_at,
                is_demo = excluded.is_demo
            """,
            (
                row["sku"],
                row["product_name"],
                row["updated_at"],
                row.get("is_demo") or "DEMO",
            ),
        )
        conn.execute(
            """
            INSERT INTO warehouses (warehouse_id, warehouse_name, updated_at, is_demo)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(warehouse_id) DO UPDATE SET
                warehouse_name = excluded.warehouse_name,
                updated_at = excluded.updated_at,
                is_demo = excluded.is_demo
            """,
            (
                row["warehouse_id"],
                row["warehouse_name"],
                row["updated_at"],
                row.get("is_demo") or "DEMO",
            ),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO inventory (
                sku, product_name, warehouse_id, warehouse_name,
                on_hand, reserved, available, safety_stock, status, updated_at, is_demo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                row.get("status") or "normal",
                row["updated_at"],
                row.get("is_demo") or "DEMO",
            ),
        )
    return conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]


def _upsert_shipments(conn: sqlite3.Connection) -> int:
    rows = _read_csv_rows(DEMO_DIR / "shipments.csv")
    for row in rows:
        conn.execute(
            """
            INSERT OR IGNORE INTO shipments (
                shipment_id, order_id, carrier, tracking_number, shipping_status,
                shipped_at, estimated_delivery_at, delivered_at, updated_at, is_demo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["shipment_id"],
                row["order_id"],
                row["carrier"],
                row["tracking_number"],
                row["shipping_status"],
                row["shipped_at"] or None,
                row["estimated_delivery_at"] or None,
                row["delivered_at"] or None,
                row["updated_at"],
                row.get("is_demo") or "DEMO",
            ),
        )
    return conn.execute("SELECT COUNT(*) FROM shipments").fetchone()[0]


def _upsert_tracking_events(conn: sqlite3.Connection) -> int:
    rows = _read_csv_rows(DEMO_DIR / "tracking_events.csv")
    for row in rows:
        conn.execute(
            """
            INSERT OR IGNORE INTO tracking_events (
                shipment_id, event_time, event_status, location, description, is_demo
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                row["shipment_id"],
                row["event_time"],
                row["event_status"],
                row["location"],
                row["description"],
                row.get("is_demo") or "DEMO",
            ),
        )
    return conn.execute("SELECT COUNT(*) FROM tracking_events").fetchone()[0]


def initialize_demo_database(*, db_path: str | Path | None = None, reset: bool = False) -> dict[str, int | str]:
    target = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)

    # 先建表（独立连接、幂等），避免与下面的写事务抢锁
    init_db(target)

    conn = _connect(target)
    try:
        conn.execute("BEGIN")
        try:
            if reset:
                _clear_demo_tables(conn)

            _upsert_orders(conn)
            _upsert_inventory(conn)
            _upsert_order_items(conn)
            _verify_amount_consistency(conn)
            _upsert_shipments(conn)
            _upsert_tracking_events(conn)

            conn.commit()
        except Exception:
            conn.rollback()
            raise

        return {
            "db_path": str(target),
            "reset": bool(reset),
            "order_count": conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
            "order_item_count": conn.execute("SELECT COUNT(*) FROM order_items").fetchone()[0],
            "sku_count": conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0],
            "product_count": conn.execute("SELECT COUNT(*) FROM products").fetchone()[0],
            "warehouse_count": conn.execute("SELECT COUNT(*) FROM warehouses").fetchone()[0],
            "shipment_count": conn.execute("SELECT COUNT(*) FROM shipments").fetchone()[0],
            "tracking_event_count": conn.execute("SELECT COUNT(*) FROM tracking_events").fetchone()[0],
        }
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="初始化本地电商演示数据")
    parser.add_argument("--reset", action="store_true", help="清空并重新初始化演示数据库")
    parser.add_argument("--db-path", type=str, default=str(DEFAULT_DB_PATH), help="目标 SQLite 数据库路径")
    args = parser.parse_args()

    target = Path(args.db_path)
    if not DEMO_DIR.exists():
        raise FileNotFoundError(f"演示 CSV 目录不存在：{DEMO_DIR}")

    summary = initialize_demo_database(db_path=target, reset=args.reset)
    print(f"数据库路径: {summary['db_path']}")
    print(f"是否重建: {summary['reset']}")
    print(f"订单数量: {summary['order_count']}")
    print(f"商品明细数量: {summary['order_item_count']}")
    print(f"SKU 数量: {summary['sku_count']}")
    print(f"商品主数据数量: {summary['product_count']}")
    print(f"仓库主数据数量: {summary['warehouse_count']}")
    print(f"发货记录数量: {summary['shipment_count']}")
    print(f"轨迹数量: {summary['tracking_event_count']}")


if __name__ == "__main__":
    main()
