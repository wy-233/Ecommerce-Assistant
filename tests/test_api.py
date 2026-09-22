from fastapi.testclient import TestClient

from ecommerce_assistant.agents.ecommerce_assistant import handle_question
from ecommerce_assistant.api.service import app


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
