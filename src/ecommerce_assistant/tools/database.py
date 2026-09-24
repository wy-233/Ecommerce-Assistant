"""订单 / 库存 / 物流的统一业务查询层。

本模块是**唯一**的业务查询入口：Agent 工具（tools/*.py）、FastAPI 只读端点与
后续页面都从这里取数，禁止任何调用方自行拼 SQL 查询这三类数据。

返回结构统一为：

    {"ok": bool, "code": str, "message": str, "data": Any}

错误码语义：

- ``OK``               查询成功
- ``INVALID_ARGUMENT`` 参数错误（缺失、为空）
- ``NOT_FOUND``        数据不存在（订单 / SKU / 物流单不存在）
- ``NO_LOGISTICS``     订单存在，但该订单没有包裹记录（区别于订单不存在）
- ``DB_ERROR``         数据库错误（sqlite3 异常或未预期异常）

状态码一律返回数据库英文码，中文由展示层经 ``schema/statuses.py`` 转换。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from ecommerce_assistant.db.init_db import (
    DEFAULT_DB_PATH,
    connect,
    get_order_by_id,
    get_order_items_by_order_id,
    get_shipments_by_order_id,
    get_tracking_events,
    init_db,
    seed_demo_data,
)


OK = "OK"
INVALID_ARGUMENT = "INVALID_ARGUMENT"
NOT_FOUND = "NOT_FOUND"
NO_LOGISTICS = "NO_LOGISTICS"
DB_ERROR = "DB_ERROR"


# --------------------------------------------------------------------------
# 基础设施
# --------------------------------------------------------------------------


def _normalize_db_path(db_path: str | Path | None) -> Path:
    return Path(db_path) if db_path is not None else DEFAULT_DB_PATH


def _ensure_demo_seed_if_needed(database_path: Path) -> None:
    if database_path != DEFAULT_DB_PATH:
        init_db(database_path)
        return

    if not database_path.exists():
        init_db(database_path, seed_demo=True)
        return

    try:
        with connect(database_path) as conn:
            table_count = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN "
                "('orders','inventory','shipments','tracking_events')"
            ).fetchone()[0]
            if table_count < 4:
                init_db(database_path, seed_demo=True)
                return
            order_count = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            inventory_count = conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
            shipment_count = conn.execute("SELECT COUNT(*) FROM shipments").fetchone()[0]
            if order_count == 0 or inventory_count == 0 or shipment_count == 0:
                seed_demo_data(database_path)
    except sqlite3.Error:
        init_db(database_path, seed_demo=True)


def _result(ok: bool, code: str, message: str, data: Any | None = None) -> dict[str, Any]:
    return {"ok": bool(ok), "code": code, "message": message, "data": data}


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _execute(subject: str, operation: Callable[[], dict[str, Any]], error_data: Any) -> dict[str, Any]:
    """统一把底层异常转成 DB_ERROR，保证调用方永远拿到结构化结果。"""
    try:
        return operation()
    except sqlite3.Error as exc:
        return _result(False, DB_ERROR, f"数据库查询失败：{exc}", error_data)
    except Exception as exc:
        return _result(False, DB_ERROR, f"查询{subject}时发生未知错误：{exc}", error_data)


def _order_missing(order_id: str) -> dict[str, Any]:
    return _result(
        False,
        NOT_FOUND,
        f"订单 {order_id} 不存在，无法查询到对应订单信息。",
        {"order_id": order_id},
    )


# --------------------------------------------------------------------------
# 库存状态规则
# --------------------------------------------------------------------------


def inventory_status_from_rule(available: int | float, safety_stock: int | float) -> str:
    """库存状态规则（唯一权威来源）：

    - ``available <= 0``             -> ``out_of_stock`` 缺货
    - ``available <= safety_stock``  -> ``low_stock``    库存不足
    - ``available >  safety_stock``  -> ``normal``       正常
    """
    available_value = int(available or 0)
    safety_value = int(safety_stock or 0)
    if available_value <= 0:
        return "out_of_stock"
    if available_value <= safety_value:
        return "low_stock"
    return "normal"


# 兼容工具层内部旧调用名；新调用方请使用公开的业务规则函数。
_inventory_status_from_rule = inventory_status_from_rule


def _normalize_inventory_record(record: dict[str, Any]) -> dict[str, Any]:
    payload = dict(record)
    payload["on_hand"] = int(payload.get("on_hand") or 0)
    payload["reserved"] = int(payload.get("reserved") or 0)
    payload["available"] = int(payload.get("available") or 0)
    payload["safety_stock"] = int(payload.get("safety_stock") or 0)

    # status 以规则计算结果为准；落库列若与规则不一致，说明数据漂移，
    # 保留原值到 stored_status 并打 status_mismatch 标记，供调用方显式暴露而非静默吞掉。
    stored_status = str(payload.get("status") or "").strip().lower()
    payload["status"] = inventory_status_from_rule(payload["available"], payload["safety_stock"])
    payload["stored_status"] = stored_status or None
    payload["status_mismatch"] = bool(stored_status) and stored_status != payload["status"]
    return payload


# --------------------------------------------------------------------------
# 订单查询
# --------------------------------------------------------------------------


def _order_detail_payload(order_id: str, database_path: Path) -> dict[str, Any]:
    _ensure_demo_seed_if_needed(database_path)
    order = get_order_by_id(order_id, database_path)
    if order is None:
        return _order_missing(order_id)

    payload = dict(order)
    payload["items"] = get_order_items_by_order_id(order_id, database_path)
    payload["shipments"] = get_shipments_by_order_id(order_id, database_path)
    payload["status"] = payload.get("order_status", "unknown")
    return _result(True, OK, f"订单 {order_id} 查询成功。", payload)


def query_order(order_id: str | None, db_path: str | Path | None = None) -> dict[str, Any]:
    """按 order_id 查询订单，返回订单主表字段 + items + shipments + status。"""
    order_id_value = _clean(order_id)
    if not order_id_value:
        return _result(False, INVALID_ARGUMENT, "order_id 参数不能为空。", {"order_id": order_id})

    database_path = _normalize_db_path(db_path)
    return _execute(
        "订单",
        lambda: _order_detail_payload(order_id_value, database_path),
        {"order_id": order_id_value},
    )


def list_order_records(
    *,
    search: str | None = None,
    status: str | None = None,
    country: str | None = None,
    carrier: str | None = None,
    warehouse_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """列出订单摘要，支持订单字段及关联承运商筛选。"""
    database_path = _normalize_db_path(db_path)
    where_clauses: list[str] = []
    params: list[str] = []

    if _clean(search):
        where_clauses.append(
            "(o.order_id LIKE ? OR o.customer_name_masked LIKE ? OR o.payment_status LIKE ?)"
        )
        value = f"%{_clean(search)}%"
        params.extend([value, value, value])
    if _clean(status):
        where_clauses.append("o.order_status = ?")
        params.append(_clean(status))
    if _clean(country):
        where_clauses.append("UPPER(o.customer_country) = UPPER(?)")
        params.append(_clean(country))
    if _clean(carrier):
        where_clauses.append(
            """
            EXISTS (
                SELECT 1
                FROM shipments sf
                WHERE sf.order_id = o.order_id
                  AND UPPER(sf.carrier) = UPPER(?)
            )
            """
        )
        params.append(_clean(carrier))
    if _clean(warehouse_id):
        where_clauses.append(
            """
            EXISTS (
                SELECT 1
                FROM order_items oi
                JOIN inventory i ON i.sku = oi.sku
                JOIN warehouses w ON w.warehouse_id = i.warehouse_id
                WHERE oi.order_id = o.order_id
                  AND w.warehouse_id = ?
            )
            """
        )
        params.append(_clean(warehouse_id))

    filters = {
        "search": search,
        "status": status,
        "country": country,
        "carrier": carrier,
        "warehouse_id": warehouse_id,
    }

    def run() -> dict[str, Any]:
        _ensure_demo_seed_if_needed(database_path)
        with connect(database_path) as conn:
            rows = conn.execute(
                "SELECT o.* FROM orders o"
                + (f" WHERE {' AND '.join(where_clauses)}" if where_clauses else "")
                + " ORDER BY o.created_at DESC, o.order_id ASC",
                tuple(params),
            ).fetchall()
        records = [dict(row) for row in rows]
        return _result(
            True,
            OK,
            f"订单列表查询成功，共 {len(records)} 条记录。",
            {"count": len(records), "records": records, "filters": filters},
        )

    return _execute("订单列表", run, filters)


def _order_items_payload(order_id: str, database_path: Path) -> dict[str, Any]:
    _ensure_demo_seed_if_needed(database_path)
    if get_order_by_id(order_id, database_path) is None:
        return _order_missing(order_id)

    items = get_order_items_by_order_id(order_id, database_path)
    data = {"order_id": order_id, "count": len(items), "items": items}
    if not items:
        return _result(False, NOT_FOUND, f"订单 {order_id} 存在，但没有商品明细记录。", data)
    return _result(True, OK, f"订单 {order_id} 共 {len(items)} 个商品明细。", data)


def query_order_items(order_id: str | None, db_path: str | Path | None = None) -> dict[str, Any]:
    """查询订单商品明细。"""
    order_id_value = _clean(order_id)
    if not order_id_value:
        return _result(False, INVALID_ARGUMENT, "order_id 参数不能为空。", {"order_id": order_id})

    database_path = _normalize_db_path(db_path)
    return _execute(
        "订单商品",
        lambda: _order_items_payload(order_id_value, database_path),
        {"order_id": order_id_value},
    )


def _order_shipments_payload(order_id: str, database_path: Path) -> dict[str, Any]:
    _ensure_demo_seed_if_needed(database_path)
    if get_order_by_id(order_id, database_path) is None:
        return _order_missing(order_id)

    shipments = get_shipments_by_order_id(order_id, database_path)
    data = {"order_id": order_id, "count": len(shipments), "shipments": shipments}
    if not shipments:
        return _result(False, NO_LOGISTICS, f"订单 {order_id} 存在，但该订单暂无包裹记录。", data)
    return _result(True, OK, f"订单 {order_id} 共 {len(shipments)} 个包裹。", data)


def query_order_shipments(order_id: str | None, db_path: str | Path | None = None) -> dict[str, Any]:
    """查询订单的全部包裹（不取包裹数量上限，一单多包裹返回全部）。"""
    order_id_value = _clean(order_id)
    if not order_id_value:
        return _result(False, INVALID_ARGUMENT, "order_id 参数不能为空。", {"order_id": order_id})

    database_path = _normalize_db_path(db_path)
    return _execute(
        "订单包裹",
        lambda: _order_shipments_payload(order_id_value, database_path),
        {"order_id": order_id_value},
    )


def _order_status_payload(order_id: str, database_path: Path) -> dict[str, Any]:
    _ensure_demo_seed_if_needed(database_path)
    order = get_order_by_id(order_id, database_path)
    if order is None:
        return _order_missing(order_id)

    status = order.get("order_status") or "unknown"
    data = {
        "order_id": order_id,
        "status": status,
        "payment_status": order.get("payment_status"),
        "fulfillment_status": order.get("fulfillment_status"),
        "customer_country": order.get("customer_country"),
        "item_count": len(get_order_items_by_order_id(order_id, database_path)),
        "shipment_count": len(get_shipments_by_order_id(order_id, database_path)),
    }
    return _result(True, OK, f"订单 {order_id} 当前状态：{status}。", data)


def query_order_status(order_id: str | None, db_path: str | Path | None = None) -> dict[str, Any]:
    """只查订单状态（含商品数、包裹数），不返回明细行，供状态类提问走最短路径。"""
    order_id_value = _clean(order_id)
    if not order_id_value:
        return _result(False, INVALID_ARGUMENT, "order_id 参数不能为空。", {"order_id": order_id})

    database_path = _normalize_db_path(db_path)
    return _execute(
        "订单状态",
        lambda: _order_status_payload(order_id_value, database_path),
        {"order_id": order_id_value},
    )


# --------------------------------------------------------------------------
# 库存查询
# --------------------------------------------------------------------------


def _inventory_filters(
    sku: str | None,
    product_name: str | None,
    warehouse_name: str | None,
    warehouse_id: str | None,
    keyword: str | None,
) -> tuple[list[str], list[str], dict[str, Any]]:
    query_fields: list[str] = []
    params: list[str] = []
    if _clean(sku):
        query_fields.append("i.sku = ?")
        params.append(_clean(sku).upper())
    if _clean(keyword):
        query_fields.append("(i.sku LIKE ? OR COALESCE(p.product_name, i.product_name) LIKE ?)")
        keyword_value = f"%{_clean(keyword)}%"
        params.extend([keyword_value, keyword_value])
    if _clean(product_name):
        query_fields.append("COALESCE(p.product_name, i.product_name) LIKE ?")
        params.append(f"%{_clean(product_name)}%")
    if _clean(warehouse_name):
        query_fields.append("COALESCE(w.warehouse_name, i.warehouse_name) LIKE ?")
        params.append(f"%{_clean(warehouse_name)}%")
    if _clean(warehouse_id):
        query_fields.append("i.warehouse_id = ?")
        params.append(_clean(warehouse_id))
    filters = {
        "sku": sku,
        "keyword": keyword,
        "product_name": product_name,
        "warehouse_name": warehouse_name,
        "warehouse_id": warehouse_id,
    }
    return query_fields, params, filters


def _fetch_inventory(
    database_path: Path,
    query_fields: list[str],
    params: list[str],
) -> list[dict[str, Any]]:
    _ensure_demo_seed_if_needed(database_path)
    with connect(database_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT i.id,
                   i.sku,
                   COALESCE(p.product_name, i.product_name) AS product_name,
                   i.warehouse_id,
                   COALESCE(w.warehouse_name, i.warehouse_name) AS warehouse_name,
                   i.on_hand,
                   i.reserved,
                   i.available,
                   i.safety_stock,
                   i.status,
                   i.updated_at,
                   i.is_demo
            FROM inventory i
            LEFT JOIN products p ON p.sku = i.sku
            LEFT JOIN warehouses w ON w.warehouse_id = i.warehouse_id
            """
            + (f" WHERE {' AND '.join(query_fields)}" if query_fields else "")
            + " ORDER BY i.sku ASC",
            tuple(params),
        ).fetchall()
    return [_normalize_inventory_record(dict(row)) for row in rows]


def query_inventory(
    sku: str | None = None,
    *,
    product_name: str | None = None,
    warehouse_name: str | None = None,
    warehouse_id: str | None = None,
    keyword: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """按 SKU / 商品名称 / 仓库 / 关键词查询库存，返回 on_hand、reserved、available、safety_stock 与状态。"""
    query_fields, params, filters = _inventory_filters(
        sku, product_name, warehouse_name, warehouse_id, keyword
    )
    if not query_fields:
        return _result(
            False,
            INVALID_ARGUMENT,
            "库存查询至少需要提供 SKU、商品名称、仓库名称、仓库编号或关键词中的一个参数。",
            None,
        )

    database_path = _normalize_db_path(db_path)

    def run() -> dict[str, Any]:
        records = _fetch_inventory(database_path, query_fields, params)
        if not records:
            identifier = (
                _clean(sku)
                or _clean(product_name)
                or _clean(warehouse_name)
                or _clean(warehouse_id)
                or _clean(keyword)
            )
            return _result(
                False,
                NOT_FOUND,
                f"未找到 SKU/商品名/仓库为 {identifier} 的库存记录。",
                {"filters": filters},
            )
        if _clean(sku) and len(records) == 1:
            return _result(True, OK, f"SKU {_clean(sku).upper()} 库存查询成功。", records[0])
        return _result(
            True,
            OK,
            f"库存查询成功，共 {len(records)} 条记录。",
            {"count": len(records), "records": records, "filters": filters},
        )

    return _execute("库存", run, filters)


def query_inventory_by_sku(sku: str | None, db_path: str | Path | None = None) -> dict[str, Any]:
    """按 SKU 精确查询单条库存记录。"""
    sku_value = _clean(sku)
    if not sku_value:
        return _result(False, INVALID_ARGUMENT, "sku 参数不能为空。", {"sku": sku})

    database_path = _normalize_db_path(db_path)

    def run() -> dict[str, Any]:
        records = _fetch_inventory(database_path, ["i.sku = ?"], [sku_value.upper()])
        if not records:
            return _result(
                False,
                NOT_FOUND,
                f"未找到 SKU {sku_value.upper()} 的库存记录。",
                {"sku": sku_value.upper()},
            )
        return _result(True, OK, f"SKU {sku_value.upper()} 库存查询成功。", records[0])

    return _execute("库存", run, {"sku": sku_value})


def list_inventory_records(
    *,
    sku: str | None = None,
    product_name: str | None = None,
    warehouse_name: str | None = None,
    warehouse_id: str | None = None,
    keyword: str | None = None,
    status: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """列出库存记录，供 API 分页端点与页面复用。

    与 ``query_inventory`` 的区别：后者面向「按条件查一条或一组」，无条件是参数错误；
    本函数面向「浏览全表」，无条件是合法输入。``status`` 按规则计算后的状态码过滤。
    """
    query_fields, params, filters = _inventory_filters(
        sku, product_name, warehouse_name, warehouse_id, keyword
    )
    database_path = _normalize_db_path(db_path)
    status_value = _clean(status).lower()

    def run() -> dict[str, Any]:
        records = _fetch_inventory(database_path, query_fields, params)
        if status_value:
            records = [record for record in records if record["status"] == status_value]
        return _result(
            True,
            OK,
            f"库存列表查询成功，共 {len(records)} 条记录。",
            {"count": len(records), "records": records, "filters": {**filters, "status": status}},
        )

    return _execute("库存列表", run, filters)


# --------------------------------------------------------------------------
# 物流查询
# --------------------------------------------------------------------------


def list_shipment_records(
    *,
    search: str | None = None,
    status: str | None = None,
    country: str | None = None,
    carrier: str | None = None,
    warehouse_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """列出包裹摘要；国家筛选通过关联订单的客户国家实现。"""
    database_path = _normalize_db_path(db_path)
    where_clauses: list[str] = []
    params: list[str] = []

    if _clean(search):
        where_clauses.append(
            "(s.order_id LIKE ? OR s.shipment_id LIKE ? OR s.tracking_number LIKE ? OR s.carrier LIKE ?)"
        )
        value = f"%{_clean(search)}%"
        params.extend([value, value, value, value])
    if _clean(status):
        where_clauses.append("s.shipping_status = ?")
        params.append(_clean(status))
    if _clean(country):
        where_clauses.append(
            """
            EXISTS (
                SELECT 1
                FROM orders ofilter
                WHERE ofilter.order_id = s.order_id
                  AND UPPER(ofilter.customer_country) = UPPER(?)
            )
            """
        )
        params.append(_clean(country))
    if _clean(carrier):
        where_clauses.append("UPPER(s.carrier) = UPPER(?)")
        params.append(_clean(carrier))
    if _clean(warehouse_id):
        where_clauses.append(
            """
            EXISTS (
                SELECT 1
                FROM order_items oi
                JOIN inventory i ON i.sku = oi.sku
                JOIN warehouses w ON w.warehouse_id = i.warehouse_id
                WHERE oi.order_id = s.order_id
                  AND w.warehouse_id = ?
            )
            """
        )
        params.append(_clean(warehouse_id))

    filters = {
        "search": search,
        "status": status,
        "country": country,
        "carrier": carrier,
        "warehouse_id": warehouse_id,
    }

    def run() -> dict[str, Any]:
        _ensure_demo_seed_if_needed(database_path)
        with connect(database_path) as conn:
            rows = conn.execute(
                "SELECT s.* FROM shipments s"
                + (f" WHERE {' AND '.join(where_clauses)}" if where_clauses else "")
                + " ORDER BY s.updated_at DESC, s.shipment_id ASC",
                tuple(params),
            ).fetchall()
        records = [dict(row) for row in rows]
        return _result(
            True,
            OK,
            f"物流列表查询成功，共 {len(records)} 条记录。",
            {"count": len(records), "records": records, "filters": filters},
        )

    return _execute("物流列表", run, filters)


def _shipment_with_events(shipment: dict[str, Any], database_path: Path) -> dict[str, Any]:
    events = get_tracking_events(shipment["shipment_id"], database_path)
    payload = dict(shipment)
    payload["events"] = events
    payload["current_status"] = (
        shipment.get("shipping_status") or (events[-1].get("event_status") if events else "unknown")
    )
    return payload


def _logistics_by_shipment(shipment: dict[str, Any], database_path: Path) -> dict[str, Any]:
    detail = _shipment_with_events(shipment, database_path)
    data = {
        "shipment": detail,
        "shipments": [detail],
        "shipment_count": 1,
        "events": detail["events"],
        "current_status": detail["current_status"],
    }
    return _result(True, OK, "物流信息查询成功。", data)


def _logistics_by_order(order_id: str, database_path: Path) -> dict[str, Any]:
    if get_order_by_id(order_id, database_path) is None:
        return _result(
            False,
            NOT_FOUND,
            f"订单 {order_id} 不存在，无法查询到该订单的物流记录。",
            {
                "order_id": order_id,
                "shipments": [],
                "shipment_count": 0,
                "events": [],
                "current_status": None,
            },
        )

    shipments = get_shipments_by_order_id(order_id, database_path)
    if not shipments:
        return _result(
            False,
            NO_LOGISTICS,
            f"订单 {order_id} 存在，但该订单暂无物流记录（可能尚未发货）。",
            {"order_id": order_id, "shipments": [], "shipment_count": 0, "events": [], "current_status": None},
        )

    details = [_shipment_with_events(shipment, database_path) for shipment in shipments]
    primary = details[0]
    data = {
        "order_id": order_id,
        "shipment_count": len(details),
        # shipment / events / current_status 为单包裹时代的兼容字段，指向首个包裹。
        "shipment": primary,
        "shipments": details,
        "events": primary["events"],
        "current_status": primary["current_status"],
    }
    message = (
        f"订单 {order_id} 共 {len(details)} 个包裹，物流信息查询成功。"
        if len(details) > 1
        else "物流信息查询成功。"
    )
    return _result(True, OK, message, data)


def query_logistics(
    order_id: str | None = None,
    *,
    shipment_id: str | None = None,
    tracking_number: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """按 shipment_id / order_id / tracking_number 查询物流。

    按 ``order_id`` 查询时返回该订单的**全部**包裹（每个包裹带自己的升序轨迹），
    顶层 ``shipment`` / ``events`` / ``current_status`` 指向首个包裹以兼容旧调用。
    """
    params = {"order_id": order_id, "shipment_id": shipment_id, "tracking_number": tracking_number}
    if not any(_clean(value) for value in params.values()):
        return _result(
            False,
            INVALID_ARGUMENT,
            "物流查询至少需要提供 order_id、shipment_id 或 tracking_number 中的一个参数。",
            params,
        )

    database_path = _normalize_db_path(db_path)

    def run() -> dict[str, Any]:
        _ensure_demo_seed_if_needed(database_path)

        if _clean(shipment_id):
            key = _clean(shipment_id)
            shipment = _fetch_shipment(database_path, "shipment_id = ?", key)
            if shipment is None:
                return _result(False, NOT_FOUND, f"物流单 {key} 不存在。", {**params, "lookup": "shipment_id"})
            return _logistics_by_shipment(shipment, database_path)

        if _clean(tracking_number):
            key = _clean(tracking_number).upper()
            shipment = _fetch_shipment(database_path, "UPPER(tracking_number) = ?", key)
            if shipment is None:
                return _result(
                    False, NOT_FOUND, f"物流单号 {key} 不存在。", {**params, "lookup": "tracking_number"}
                )
            return _logistics_by_shipment(shipment, database_path)

        return _logistics_by_order(_clean(order_id), database_path)

    return _execute("物流", run, params)


def _fetch_shipment(database_path: Path, where: str, value: str) -> dict[str, Any] | None:
    with connect(database_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(f"SELECT * FROM shipments WHERE {where}", (value,)).fetchone()
    return dict(row) if row else None


def query_shipment_events(shipment_id: str | None, db_path: str | Path | None = None) -> dict[str, Any]:
    """查询包裹轨迹，按 event_time 升序（同时间按 id 升序兜底）。"""
    shipment_id_value = _clean(shipment_id)
    if not shipment_id_value:
        return _result(False, INVALID_ARGUMENT, "shipment_id 参数不能为空。", {"shipment_id": shipment_id})

    database_path = _normalize_db_path(db_path)

    def run() -> dict[str, Any]:
        _ensure_demo_seed_if_needed(database_path)
        shipment = _fetch_shipment(database_path, "shipment_id = ?", shipment_id_value)
        if shipment is None:
            return _result(
                False, NOT_FOUND, f"物流单 {shipment_id_value} 不存在。", {"shipment_id": shipment_id_value}
            )
        events = get_tracking_events(shipment_id_value, database_path)
        data = {
            "shipment_id": shipment_id_value,
            "current_status": shipment.get("shipping_status") or "unknown",
            "count": len(events),
            "events": events,
        }
        if not events:
            return _result(False, NOT_FOUND, f"物流单 {shipment_id_value} 存在，但暂无轨迹记录。", data)
        return _result(True, OK, f"物流单 {shipment_id_value} 共 {len(events)} 条轨迹。", data)

    return _execute("物流轨迹", run, {"shipment_id": shipment_id_value})


# --------------------------------------------------------------------------
# 工作台与 Dashboard 聚合查询
# --------------------------------------------------------------------------


def list_warehouse_records(db_path: str | Path | None = None) -> dict[str, Any]:
    """列出仓库主数据，供工作台筛选器复用。"""
    database_path = _normalize_db_path(db_path)

    def run() -> dict[str, Any]:
        _ensure_demo_seed_if_needed(database_path)
        with connect(database_path) as conn:
            rows = conn.execute(
                """
                SELECT warehouse_id, warehouse_name
                FROM warehouses
                ORDER BY warehouse_id ASC
                """
            ).fetchall()
        records = [dict(row) for row in rows]
        return _result(
            True,
            OK,
            f"仓库列表查询成功，共 {len(records)} 条记录。",
            {"count": len(records), "records": records},
        )

    return _execute("仓库列表", run, None)


def list_tracking_event_records(
    *,
    shipment_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """列出轨迹记录，可按包裹号筛选，始终按时间升序。"""
    database_path = _normalize_db_path(db_path)
    shipment_id_value = _clean(shipment_id)

    def run() -> dict[str, Any]:
        _ensure_demo_seed_if_needed(database_path)
        with connect(database_path) as conn:
            rows = conn.execute(
                "SELECT * FROM tracking_events"
                + (" WHERE shipment_id = ?" if shipment_id_value else "")
                + " ORDER BY event_time ASC, id ASC",
                (shipment_id_value,) if shipment_id_value else (),
            ).fetchall()
        records = [dict(row) for row in rows]
        return _result(
            True,
            OK,
            f"物流轨迹列表查询成功，共 {len(records)} 条记录。",
            {
                "count": len(records),
                "records": records,
                "filters": {"shipment_id": shipment_id},
            },
        )

    return _execute("物流轨迹列表", run, {"shipment_id": shipment_id})


def _result_records(result: dict[str, Any]) -> list[dict[str, Any]]:
    if not result["ok"]:
        raise RuntimeError(result["message"])
    return list(result["data"]["records"])


def query_order_summary(db_path: str | Path | None = None) -> dict[str, Any]:
    """返回订单页面指标，仅以统一订单列表为统计源。"""
    database_path = _normalize_db_path(db_path)

    def run() -> dict[str, Any]:
        records = _result_records(list_order_records(db_path=database_path))
        data = {
            "total": len(records),
            "pending_payment": sum(row.get("order_status") == "pending_payment" for row in records),
            "shipped": sum(row.get("order_status") == "shipped" for row in records),
            "cancelled": sum(row.get("order_status") == "cancelled" for row in records),
        }
        return _result(True, OK, "订单汇总计算成功。", data)

    return _execute("订单汇总", run, None)


def query_inventory_summary(db_path: str | Path | None = None) -> dict[str, Any]:
    """返回库存页面指标，状态按 available / safety_stock 规则计算。"""
    database_path = _normalize_db_path(db_path)

    def run() -> dict[str, Any]:
        records = _result_records(list_inventory_records(db_path=database_path))
        data = {
            "sku_total": len(records),
            "on_hand_total": sum(int(row.get("on_hand") or 0) for row in records),
            "available_total": sum(int(row.get("available") or 0) for row in records),
            "low_stock": sum(row.get("status") == "low_stock" for row in records),
            "out_of_stock": sum(row.get("status") == "out_of_stock" for row in records),
        }
        return _result(True, OK, "库存汇总计算成功。", data)

    return _execute("库存汇总", run, None)


def query_shipment_summary(db_path: str | Path | None = None) -> dict[str, Any]:
    """返回物流页面指标，仅以统一物流与轨迹列表为统计源。"""
    database_path = _normalize_db_path(db_path)

    def run() -> dict[str, Any]:
        shipments = _result_records(list_shipment_records(db_path=database_path))
        events = _result_records(list_tracking_event_records(db_path=database_path))
        data = {
            "total": len(shipments),
            "in_transit": sum(row.get("shipping_status") == "in_transit" for row in shipments),
            "exception": sum(row.get("shipping_status") == "exception" for row in shipments),
            "delivered": sum(row.get("shipping_status") == "delivered" for row in shipments),
            "event_total": len(events),
        }
        return _result(True, OK, "物流汇总计算成功。", data)

    return _execute("物流汇总", run, None)


def query_dashboard_summary(db_path: str | Path | None = None) -> dict[str, Any]:
    """Dashboard 唯一业务汇总入口，API 与工作台共同调用。"""
    database_path = _normalize_db_path(db_path)

    def run() -> dict[str, Any]:
        orders = _result_records(list_order_records(db_path=database_path))
        inventory = _result_records(list_inventory_records(db_path=database_path))
        shipments = _result_records(list_shipment_records(db_path=database_path))

        today = datetime.now().date().isoformat()
        inventory_alert_rows = [
            row for row in inventory if row.get("status") in {"low_stock", "out_of_stock"}
        ]
        inventory_alerts = sorted(
            inventory_alert_rows,
            key=lambda row: (int(row.get("available") or 0), str(row.get("sku") or "")),
        )[:10]
        shipment_alert_rows = [
            row for row in shipments if row.get("shipping_status") == "exception"
        ]
        shipment_alerts = shipment_alert_rows[:10]
        updated_values = [
            str(row["updated_at"])
            for row in [*orders, *inventory, *shipments]
            if row.get("updated_at")
        ]

        data = {
            "today_order_count": sum(
                str(row.get("created_at") or "")[:10] == today for row in orders
            ),
            "pending_order_count": sum(
                row.get("order_status") in {"pending_payment", "paid", "processing"}
                for row in orders
            ),
            "pending_shipping_order_count": sum(
                row.get("order_status") in {"paid", "processing"} for row in orders
            ),
            "in_transit_shipment_count": sum(
                row.get("shipping_status") in {"in_transit", "out_for_delivery"}
                for row in shipments
            ),
            "low_stock_sku_count": len(inventory_alert_rows),
            "shipment_exception_count": len(shipment_alert_rows),
            "recent_orders": orders[:5],
            "inventory_alerts": inventory_alerts,
            "shipment_alerts": shipment_alerts,
            "data_updated_at": max(
                updated_values,
                default=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        }
        return _result(True, OK, "Dashboard 汇总计算成功。", data)

    return _execute("Dashboard 汇总", run, None)
