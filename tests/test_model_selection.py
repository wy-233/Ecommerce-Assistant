"""模型选择功能回归测试。

覆盖三层：
1. ``llm/client.py`` —— 候选清单解析、远端拉取降级、model 透传；
2. ``api/service.py`` —— ``/models`` 端点、``/invoke`` 的 model 字段与 intent 暴露；
3. ``client/client.py`` —— 请求体对旧调用方式的兼容性。
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

import ecommerce_assistant.agents.ecommerce_assistant as agent_module
from ecommerce_assistant.api.service import app
from ecommerce_assistant.client.client import AgentClient
from ecommerce_assistant.llm import client as llm_client
from ecommerce_assistant.schema.schema import MessageRequest

client = TestClient(app)


class _StubResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload


# --- llm/client.py: 候选清单解析 -------------------------------------------------


def test_model_candidates_parses_trims_and_dedupes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_MODELS", " alpha , beta ,alpha, , gamma ")
    assert llm_client.get_model_candidates() == ["alpha", "beta", "gamma"]


def test_model_candidates_falls_back_to_single_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_MODELS", raising=False)
    monkeypatch.setenv("OPENAI_MODEL", "solo-model")
    assert llm_client.get_model_candidates() == ["solo-model"]


def test_model_candidates_falls_back_when_list_is_only_separators(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_MODELS", " , , ")
    monkeypatch.setenv("OPENAI_MODEL", "solo-model")
    assert llm_client.get_model_candidates() == ["solo-model"]


# --- llm/client.py: model 透传 --------------------------------------------------


def test_call_llm_sends_selected_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "env-model")
    captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> _StubResponse:
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return _StubResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(llm_client.httpx, "post", fake_post)

    assert llm_client.call_llm("你好", model="picked-model") == "ok"
    assert captured["json"]["model"] == "picked-model"
    assert str(captured["url"]).endswith("/chat/completions")


def test_call_llm_falls_back_to_env_model_when_no_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "env-model")
    captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> _StubResponse:
        captured["json"] = kwargs["json"]
        return _StubResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(llm_client.httpx, "post", fake_post)

    assert llm_client.call_llm("你好") == "ok"
    assert captured["json"]["model"] == "env-model"


def test_call_llm_returns_empty_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert llm_client.call_llm("你好", model="picked-model") == ""


# --- llm/client.py: 远端模型拉取与降级 -------------------------------------------


def test_list_remote_models_returns_sorted_unique_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def fake_get(url: str, **kwargs: object) -> _StubResponse:
        return _StubResponse({"data": [{"id": "zeta"}, {"id": "alpha"}, {"id": "alpha"}]})

    monkeypatch.setattr(llm_client.httpx, "get", fake_get)
    assert llm_client.list_remote_models() == ["alpha", "zeta"]


def test_list_remote_models_returns_empty_without_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert llm_client.list_remote_models() == []


def test_list_remote_models_swallows_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def boom(url: str, **kwargs: object) -> None:
        raise httpx.ConnectError("unreachable")

    monkeypatch.setattr(llm_client.httpx, "get", boom)
    assert llm_client.list_remote_models() == []


def test_list_remote_models_swallows_malformed_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(llm_client.httpx, "get", lambda url, **kw: _StubResponse(["not", "a", "dict"]))
    assert llm_client.list_remote_models() == []


# --- api/service.py: /models 端点 -----------------------------------------------


def test_models_endpoint_returns_env_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_MODELS", "m1,m2")
    monkeypatch.setenv("OPENAI_MODEL", "m1")

    response = client.get("/models")
    assert response.status_code == 200
    payload = response.json()
    assert payload["models"] == ["m1", "m2"]
    assert payload["default"] == "m1"
    assert payload["source"] == "env"


def test_models_endpoint_merges_remote_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_MODELS", "m1,m2")
    monkeypatch.setattr(
        "ecommerce_assistant.api.service.list_remote_models", lambda: ["m2", "m3"]
    )

    payload = client.get("/models", params={"include_remote": True}).json()
    assert payload["source"] == "merged"
    assert payload["models"] == ["m1", "m2", "m3"]


def test_models_endpoint_degrades_to_env_when_remote_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_MODELS", "m1")
    monkeypatch.setattr("ecommerce_assistant.api.service.list_remote_models", lambda: [])

    payload = client.get("/models", params={"include_remote": True}).json()
    assert payload["source"] == "env"
    assert payload["models"] == ["m1"]


def test_info_endpoint_reports_same_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_MODELS", "i1,i2")
    assert client.get("/info").json()["models"] == ["i1", "i2"]


# --- api/service.py: /invoke 契约 ------------------------------------------------


def test_message_request_model_is_optional() -> None:
    assert MessageRequest(message="hi").model is None
    assert MessageRequest(message="hi", model="m").model == "m"


def test_invoke_without_model_still_works() -> None:
    response = client.post(
        "/ecommerce-assistant/invoke",
        json={"message": "订单 1001 的物流状态", "thread_id": "model-thread-a", "user_id": "u"},
    )
    assert response.status_code == 200
    assert response.json()["content"]


def test_invoke_with_model_returns_intent() -> None:
    response = client.post(
        "/ecommerce-assistant/invoke",
        json={
            "message": "订单 1001 的物流状态",
            "thread_id": "model-thread-b",
            "user_id": "u",
            "model": "picked-model",
        },
    )
    assert response.status_code == 200
    assert response.json()["intent"] == "logistics"


def test_stream_endpoint_accepts_model() -> None:
    response = client.post(
        "/ecommerce-assistant/stream",
        json={
            "message": "订单 1001 的物流状态",
            "thread_id": "model-thread-c",
            "user_id": "u",
            "model": "picked-model",
        },
    )
    assert response.status_code == 200
    assert "data:" in response.text


# --- agents: 模型只作用于 LLM 分支 -----------------------------------------------


def test_llm_branch_receives_selected_model(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_call_llm(
        prompt: str, system_prompt: str | None = None, model: str | None = None
    ) -> str:
        captured["model"] = model
        return "由所选模型生成的回答"

    monkeypatch.setattr(agent_module, "call_llm", fake_call_llm)

    answer = agent_module.handle_question("你好呀", model="picked-model")
    assert captured["model"] == "picked-model"
    assert answer == "由所选模型生成的回答"


def test_tool_branch_does_not_call_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> str:
        raise AssertionError("订单 / 库存 / 物流分支不应调用 LLM")

    monkeypatch.setattr(agent_module, "call_llm", boom)

    answer = agent_module.handle_question("订单 1001 的物流状态", model="picked-model")
    assert "1001" in answer


# --- client/client.py: 请求体兼容性 ----------------------------------------------


def _capture_post(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> _StubResponse:
        captured["json"] = kwargs["json"]
        return _StubResponse({"content": "x"})

    monkeypatch.setattr("ecommerce_assistant.client.client.httpx.post", fake_post)
    return captured


def test_agent_client_omits_model_when_not_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture_post(monkeypatch)
    AgentClient("http://example.test").invoke("hi")
    assert "model" not in captured["json"]


def test_agent_client_sends_selected_model(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture_post(monkeypatch)
    AgentClient("http://example.test").invoke("hi", model="picked-model")
    assert captured["json"]["model"] == "picked-model"


def test_agent_client_reads_model_list_from_api(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_get(url: str, **kwargs: object) -> _StubResponse:
        captured["url"] = url
        captured["params"] = kwargs["params"]
        return _StubResponse({"models": ["m1"], "default": "m1", "source": "env"})

    monkeypatch.setattr("ecommerce_assistant.client.client.httpx.get", fake_get)

    payload = AgentClient("http://example.test").list_models(include_remote=True)
    assert payload["models"] == ["m1"]
    assert str(captured["url"]).endswith("/models")
    assert captured["params"] == {"include_remote": True}
