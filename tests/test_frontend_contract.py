"""前端数据契约验收：`POST /ecommerce-assistant/invoke` 必须满足
`design/FRONTEND-SPEC.md` §6.1（类型定义）与 §6.2（字段到界面的映射）。

对应的契约文档：
- `design/PRD.md` v0.2 §6.7.1：ChatMessage 的 6 个字段
- `design/FRONTEND-SPEC.md` §6.4：route 一律以后端为准，前端不得自行推断
- `docs/WORKBENCH_PLAN.md`：模型选择与前端接入的链路约定
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from ecommerce_assistant.agents import ecommerce_assistant as agent_module
from ecommerce_assistant.agents.ecommerce_assistant import answer_question, handle_question
from ecommerce_assistant.api.service import app
from ecommerce_assistant.rag.retriever import retrieve_knowledge
from ecommerce_assistant.schema.routes import (
    ROUTE_AFTER,
    ROUTE_ORDER,
    ROUTE_SHIP,
    ROUTE_STOCK,
    ROUTE_UNKNOWN,
    ROUTES,
    TOOL_CALL_NAMES,
)

# PRD v0.2 §6.7.1 约定的字段，缺一不可
CONTRACT_FIELDS = {"type", "content", "tool_calls", "run_id", "route", "sources"}


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def _invoke(client: TestClient, question: str, thread_id: str) -> dict:
    response = client.post(
        "/ecommerce-assistant/invoke",
        json={"message": question, "thread_id": thread_id, "user_id": "contract-test"},
    )
    assert response.status_code == 200
    return response.json()


def _stub_llm(monkeypatch, answer: str) -> None:
    """替换 LLM 调用，使模型分支的断言不依赖网络可达性。"""
    monkeypatch.setattr(agent_module, "call_llm", lambda *args, **kwargs: answer)


# --------------------------------------------------------------------------
# 字段完整性：6 个字段齐全，且数组型字段永不为 null
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "退货需要满足什么条件？",
        "订单 1001 现在到哪里了？",
        "商品 SKU-001 还有库存吗？",
        "订单 1001 使用了什么物流？",
    ],
)
def test_invoke_returns_all_contract_fields(client, question):
    payload = _invoke(client, question, "contract-fields")

    assert CONTRACT_FIELDS <= set(payload)
    assert isinstance(payload["content"], str) and payload["content"]
    assert payload["route"] in ROUTES
    # 前端按 .length / forEach 直接消费，null 会直接抛错
    assert isinstance(payload["tool_calls"], list)
    assert isinstance(payload["sources"], list)
    assert payload["tool_calls"] is not None
    assert payload["sources"] is not None
    assert isinstance(payload["run_id"], str) and payload["run_id"]


def test_tool_call_entries_carry_name_and_args(client):
    payload = _invoke(client, "订单 1001 现在到哪里了？", "contract-toolcall")

    assert len(payload["tool_calls"]) == 1
    call = payload["tool_calls"][0]
    assert {"name", "args"} <= set(call)
    assert call["name"] == TOOL_CALL_NAMES[ROUTE_ORDER]
    assert call["args"] == {"order_id": "1001"}


def test_source_entries_carry_doc_snippet_and_placeholder(client):
    payload = _invoke(client, "退货需要满足什么条件？", "contract-source")

    assert len(payload["sources"]) == 1
    source = payload["sources"][0]
    assert {"doc", "snippet"} <= set(source)
    assert source["doc"] == "data/return_policy.md"
    assert source["snippet"]
    # placeholder=true 时前端要在 cite 行追加「占位文本，待替换」
    assert source["placeholder"] is True


# --------------------------------------------------------------------------
# 逐分支的 route / tool_calls / sources
# --------------------------------------------------------------------------


def test_rag_hit_routes_to_after_with_sources_and_no_tool_call(client):
    payload = _invoke(client, "退货需要满足什么条件？", "contract-rag")

    assert payload["route"] == ROUTE_AFTER
    assert payload["tool_calls"] == []
    assert payload["sources"]
    # 来源只走 sources，正文不再重复拼接文档路径
    assert "data/return_policy.md" not in payload["content"]


def test_order_branch_routes_to_order(client):
    payload = _invoke(client, "订单 1001 现在到哪里了？", "contract-order")

    assert payload["route"] == ROUTE_ORDER
    assert payload["tool_calls"][0]["name"] == "order_lookup"
    assert payload["sources"] == []


def test_stock_branch_routes_to_stock(client):
    payload = _invoke(client, "商品 SKU-001 还有库存吗？", "contract-stock")

    assert payload["route"] == ROUTE_STOCK
    assert payload["tool_calls"][0]["name"] == "stock_lookup"
    assert payload["tool_calls"][0]["args"] == {"sku": "SKU-001"}
    assert payload["sources"] == []


def test_ship_branch_routes_to_ship(client):
    payload = _invoke(client, "订单 1001 使用了什么物流？", "contract-ship")

    assert payload["route"] == ROUTE_SHIP
    assert payload["tool_calls"][0]["name"] == "shipping_lookup"
    assert payload["sources"] == []


def test_missing_identifier_keeps_route_but_produces_no_tool_call(client):
    """参数缺失时 route 保持被路由到的道，但确实没有调用工具 → tool_calls 为空。"""
    payload = _invoke(client, "帮我看看订单的状态", "contract-missing-arg")

    assert payload["route"] == ROUTE_ORDER
    assert payload["tool_calls"] == []
    assert "订单号" in payload["content"]


def test_unmatched_question_routes_to_unknown(client, monkeypatch):
    """知识库未命中且模型不可用 → unknown，前端渲染兜底形态。"""
    _stub_llm(monkeypatch, "")

    payload = _invoke(client, "今天深圳的天气怎么样？", "contract-unknown")

    assert payload["route"] == ROUTE_UNKNOWN
    assert payload["tool_calls"] == []
    assert payload["sources"] == []
    assert "不在售后、订单、库存、物流的处理范围内" in payload["content"]
    # 兜底文案不道歉（FRONTEND-SPEC §5.2）
    assert "抱歉" not in payload["content"]


def test_fallback_answer_is_two_paragraphs(client, monkeypatch):
    """兜底回执按 \n\n 分两段渲染（FRONTEND-SPEC §5.2）。"""
    _stub_llm(monkeypatch, "")

    payload = _invoke(client, "今天深圳的天气怎么样？", "contract-fallback-paragraphs")

    assert len([part for part in payload["content"].split("\n\n") if part.strip()]) == 2


def test_model_branch_routes_to_after_without_sources(client, monkeypatch):
    """intent='llm' 且模型作答成功 → route='after'、无 sources、无 tool_calls。"""
    _stub_llm(monkeypatch, "这是模型的直接回答。")

    payload = _invoke(client, "今天深圳的天气怎么样？", "contract-model")

    assert payload["route"] == ROUTE_AFTER
    assert payload["content"] == "这是模型的直接回答。"
    assert payload["tool_calls"] == []
    assert payload["sources"] == []


# --------------------------------------------------------------------------
# 与既有文本视图保持一致
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    ["退货需要满足什么条件？", "订单 1001 现在到哪里了？", "商品 SKU-001 还有库存吗？"],
)
def test_answer_question_content_matches_handle_question(question):
    structured = answer_question(question)
    assert structured["content"] == handle_question(question)


def test_answer_question_exposes_all_structured_keys():
    result = answer_question("订单 1001 现在到哪里了？")
    assert set(result) == {"content", "route", "tool_calls", "sources", "intent"}


# --------------------------------------------------------------------------
# 检索层结构
# --------------------------------------------------------------------------


def test_retriever_returns_empty_sources_list_on_miss():
    result = retrieve_knowledge("完全不相关的问题 XYZ")
    assert result["sources"] == []
    assert isinstance(result["sources"], list)


def test_retriever_returns_structured_sources_on_hit():
    result = retrieve_knowledge("退货需要满足什么条件")
    assert len(result["sources"]) == 1
    assert result["sources"][0]["doc"] == "data/return_policy.md"
    # 兼容既有调用方：单值 source 仍保留
    assert result["source"] == "data/return_policy.md"


# --------------------------------------------------------------------------
# run_id 与 CORS
# --------------------------------------------------------------------------


def test_run_id_is_unique_per_response(client):
    first = _invoke(client, "订单 1001 现在到哪里了？", "contract-runid")
    second = _invoke(client, "订单 1001 现在到哪里了？", "contract-runid")

    assert first["run_id"] != second["run_id"]
    assert first["run_id"].startswith("run_")


def test_cors_preflight_allows_file_origin(client):
    """前端以 file:// 打开时 Origin 为 null，预检必须放行（否则页面只能看到连接失败）。"""
    response = client.options(
        "/ecommerce-assistant/invoke",
        headers={
            "Origin": "null",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "*"


def test_cors_headers_present_on_actual_response(client):
    response = client.post(
        "/ecommerce-assistant/invoke",
        json={"message": "订单 1001 现在到哪里了？", "thread_id": "contract-cors", "user_id": "u"},
        headers={"Origin": "null"},
    )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "*"


# --------------------------------------------------------------------------
# 流式接口的事件形状（PRD v0.2 §6.7.2、验收项 3）
# --------------------------------------------------------------------------


def _read_sse(body: str) -> list[dict]:
    return [
        json.loads(line[len("data: ") :])
        for line in body.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]


def test_stream_emits_start_route_and_token_events(client):
    """验收项 3：收到 start、route 事件与 token 增量、[DONE] 结束标记。"""
    response = client.post(
        "/ecommerce-assistant/stream",
        json={"message": "订单 1001 现在到哪里了？", "thread_id": "contract-stream", "user_id": "u"},
    )

    assert response.status_code == 200
    body = response.text
    assert body.rstrip().endswith("data: [DONE]")

    events = _read_sse(body)
    assert events, "应至少推送 start / route / token 事件"

    assert events[0]["type"] == "start"
    assert events[0]["run_id"].startswith("run_")

    route_events = [event for event in events if event["type"] == "route"]
    assert len(route_events) == 1
    assert route_events[0]["route"] == ROUTE_ORDER

    # route 必须先于正文到达，前端据此播放投递动效
    assert events.index(route_events[0]) < min(
        index for index, event in enumerate(events) if event["type"] == "token"
    )

    tokens = [event["content"] for event in events if event["type"] == "token"]
    assert tokens
    assert "".join(tokens) == _invoke(client, "订单 1001 现在到哪里了？", "contract-stream-ref")["content"]


def test_stream_emits_tool_call_event_with_signature(client):
    response = client.post(
        "/ecommerce-assistant/stream",
        json={"message": "商品 SKU-001 还有库存吗？", "thread_id": "contract-stream-tool", "user_id": "u"},
    )

    events = _read_sse(response.text)
    tool_events = [event for event in events if event["type"] == "tool_call"]

    assert len(tool_events) == 1
    assert tool_events[0]["name"] == "stock_lookup"
    assert tool_events[0]["args"] == {"sku": "SKU-001"}


def test_stream_emits_sources_event_only_for_rag_hits(client):
    hit = client.post(
        "/ecommerce-assistant/stream",
        json={"message": "退货需要满足什么条件？", "thread_id": "contract-stream-rag", "user_id": "u"},
    )
    hit_events = _read_sse(hit.text)
    sources_events = [event for event in hit_events if event["type"] == "sources"]

    assert len(sources_events) == 1
    assert sources_events[0]["sources"][0]["doc"] == "data/return_policy.md"

    # 非 RAG 链路不发 sources（PRD §6.7.2：可选事件缺失时前端降级）
    order = client.post(
        "/ecommerce-assistant/stream",
        json={"message": "订单 1001 现在到哪里了？", "thread_id": "contract-stream-order", "user_id": "u"},
    )
    assert not [event for event in _read_sse(order.text) if event["type"] == "sources"]
