import sqlite3
from datetime import datetime

from fastapi.testclient import TestClient

from ecommerce_assistant.agents.ecommerce_assistant import handle_question
from ecommerce_assistant.api.service import DB_PATH, app


client = TestClient(app)


def test_info_endpoint():
    response = client.get("/info")
    assert response.status_code == 200
    payload = response.json()
    assert payload["agents"]
    assert "ecommerce-assistant" in payload["agents"]


def test_invoke_endpoint():
    response = client.post(
        "/ecommerce-assistant/invoke",
        json={
            "message": "订单 1001 现在到哪里了？",
            "thread_id": "demo-thread-001",
            "user_id": "demo-user-001",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["type"] in {"ai", "tool", "error"}
    assert "content" in payload


def test_stream_endpoint():
    response = client.post(
        "/ecommerce-assistant/stream",
        json={
            "message": "订单 1001 现在到哪里了？",
            "thread_id": "demo-thread-002",
            "user_id": "demo-user-002",
        },
    )
    assert response.status_code == 200
    body = response.text
    assert "data:" in body


def test_thread_isolation():
    first = client.post(
        "/ecommerce-assistant/invoke",
        json={"message": "订单 1001 现在到哪里了？", "thread_id": "thread-a", "user_id": "u1"},
    )
    second = client.post(
        "/ecommerce-assistant/invoke",
        json={"message": "订单 1001 现在到哪里了？", "thread_id": "thread-b", "user_id": "u2"},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["content"] == second.json()["content"]


def test_multi_turn_conversation_context():
    first = client.post(
        "/ecommerce-assistant/invoke",
        json={"message": "我的订单号是 1001。", "thread_id": "thread-context", "user_id": "u3"},
    )
    second = client.post(
        "/ecommerce-assistant/invoke",
        json={"message": "现在到哪里了？", "thread_id": "thread-context", "user_id": "u3"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    second_text = second.json()["content"]
    assert "1001" in second_text or "订单" in second_text


def test_recent_question_context_is_not_misread_as_order_lookup():
    history = [
        {"role": "user", "content": "我想要查看订单1002的信息"},
        {"role": "assistant", "content": "订单 1002 当前状态：已签收。"},
        {"role": "user", "content": "我刚刚问了什么"},
    ]

    response = handle_question("我刚刚问了什么", history)

    assert "1002" in response or "刚刚问的是" in response


def test_missing_order_id_is_not_filled_with_default_1001():
    response = handle_question("现在到哪里了？")

    assert "订单号" in response or "SKU" in response or "请告诉我" in response
    assert "订单 1001" not in response


def test_read_only_order_list_and_detail_endpoints():
    list_response = client.get("/orders", params={"page": 1, "page_size": 10})
    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload["page"] == 1
    assert payload["page_size"] == 10
    assert payload["total"] >= 1
    assert payload["items"]

    item_response = client.get("/orders/1001")
    assert item_response.status_code == 200
    order = item_response.json()
    assert order["order_id"] == "1001"
    assert order["items"]
    assert order["shipments"]

    missing = client.get("/orders/NOT_FOUND")
    assert missing.status_code == 404


def test_read_only_inventory_and_shipment_endpoints():
    inventory_list = client.get("/inventory", params={"page": 1, "page_size": 10, "search": "SKU-001"})
    assert inventory_list.status_code == 200
    inventory_payload = inventory_list.json()
    assert inventory_payload["items"]

    inventory_detail = client.get("/inventory/SKU-001")
    assert inventory_detail.status_code == 200
    assert inventory_detail.json()["sku"] == "SKU-001"

    shipment_list = client.get("/shipments", params={"page": 1, "page_size": 10})
    assert shipment_list.status_code == 200
    shipment_payload = shipment_list.json()
    assert shipment_payload["items"]

    shipment_detail = client.get("/shipments/SHP-1001-A")
    assert shipment_detail.status_code == 200
    detail = shipment_detail.json()
    assert detail["shipment_id"] == "SHP-1001-A"
    assert detail["events"]

    events = client.get("/shipments/SHP-1001-A/events")
    assert events.status_code == 200
    assert events.json()["items"]

    bad_page = client.get("/inventory", params={"page_size": 9999})
    assert bad_page.status_code == 422


def test_list_filter_parameters_match_supported_data_relationships():
    schema = client.get("/openapi.json").json()

    order_params = {
        item["name"] for item in schema["paths"]["/orders"]["get"]["parameters"]
    }
    inventory_params = {
        item["name"] for item in schema["paths"]["/inventory"]["get"]["parameters"]
    }
    shipment_params = {
        item["name"] for item in schema["paths"]["/shipments"]["get"]["parameters"]
    }

    assert "carrier" in order_params
    assert "warehouse_id" in order_params
    assert "warehouse_id" in inventory_params
    assert "country" not in inventory_params
    assert "carrier" not in inventory_params
    assert "country" in shipment_params
    assert "warehouse_id" in shipment_params


def test_dashboard_summary_is_driven_by_sqlite_and_changes_with_data_updates():
    before = client.get("/dashboard/summary")
    assert before.status_code == 200
    before_payload = before.json()

    today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO orders (
                order_id, customer_name_masked, customer_country, order_status,
                payment_status, fulfillment_status, currency, total_amount,
                created_at, updated_at, is_demo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "DASH-TEST-001",
                "T***",
                "CN",
                "pending_payment",
                "unpaid",
                "pending",
                "CNY",
                88.0,
                today,
                today,
                "DEMO",
            ),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO shipments (
                shipment_id, order_id, carrier, tracking_number, shipping_status,
                shipped_at, estimated_delivery_at, delivered_at, updated_at, is_demo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "DASH-TEST-SHIP-EXC",
                "DASH-TEST-001",
                "DHL",
                "DASH-TEST-TRACK-EXC",
                "exception",
                today,
                today,
                None,
                today,
                "DEMO",
            ),
        )
        conn.execute(
            "UPDATE inventory SET status = 'out_of_stock', available = 0, safety_stock = 0, updated_at = ? WHERE sku = 'SKU-004'",
            (today,),
        )
        conn.commit()

    after = client.get("/dashboard/summary")
    assert after.status_code == 200
    after_payload = after.json()

    assert after_payload["today_order_count"] >= before_payload["today_order_count"] + 1
    assert after_payload["pending_order_count"] >= before_payload["pending_order_count"] + 1
    assert after_payload["low_stock_sku_count"] >= before_payload["low_stock_sku_count"]
    assert after_payload["shipment_exception_count"] >= before_payload["shipment_exception_count"] + 1

    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.execute("DELETE FROM shipments WHERE shipment_id = 'DASH-TEST-SHIP-EXC'")
        conn.execute("DELETE FROM orders WHERE order_id = 'DASH-TEST-001'")
        conn.execute("UPDATE inventory SET status = 'low_stock', available = 2, safety_stock = 10, updated_at = CURRENT_TIMESTAMP WHERE sku = 'SKU-004'")
        conn.commit()


def test_dashboard_inventory_alerts_use_quantity_rule_when_stored_status_drifts():
    sku = "SKU-001"
    with sqlite3.connect(str(DB_PATH)) as conn:
        original = conn.execute(
            "SELECT available, safety_stock, status, updated_at FROM inventory WHERE sku = ?",
            (sku,),
        ).fetchone()
    assert original is not None
    assert original[0] > original[1]

    baseline = client.get("/dashboard/summary")
    assert baseline.status_code == 200
    baseline_count = baseline.json()["low_stock_sku_count"]

    try:
        # 落库状态声称缺货，但数量规则为正常：Dashboard 不应产生误报。
        with sqlite3.connect(str(DB_PATH)) as conn:
            conn.execute("UPDATE inventory SET status = 'out_of_stock' WHERE sku = ?", (sku,))
            conn.commit()

        stored_status_drift = client.get("/dashboard/summary")
        assert stored_status_drift.status_code == 200
        drift_payload = stored_status_drift.json()
        assert drift_payload["low_stock_sku_count"] == baseline_count
        assert sku not in {item["sku"] for item in drift_payload["inventory_alerts"]}

        # 落库状态声称正常，但 available=0：Dashboard 必须按规则报告缺货。
        with sqlite3.connect(str(DB_PATH)) as conn:
            conn.execute(
                "UPDATE inventory SET available = 0, status = 'normal' WHERE sku = ?",
                (sku,),
            )
            conn.commit()

        quantity_drift = client.get("/dashboard/summary")
        assert quantity_drift.status_code == 200
        quantity_payload = quantity_drift.json()
        assert quantity_payload["low_stock_sku_count"] == baseline_count + 1
        alert = next(item for item in quantity_payload["inventory_alerts"] if item["sku"] == sku)
        assert alert["status"] == "out_of_stock"
    finally:
        with sqlite3.connect(str(DB_PATH)) as conn:
            conn.execute(
                """
                UPDATE inventory
                SET available = ?, safety_stock = ?, status = ?, updated_at = ?
                WHERE sku = ?
                """,
                (*original, sku),
            )
            conn.commit()
