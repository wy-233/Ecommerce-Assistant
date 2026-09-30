from __future__ import annotations

import pytest

from ecommerce_assistant.client.client import AgentClient


class FakeStreamResponse:
    def __init__(self, lines: list[str]) -> None:
        self.lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def raise_for_status(self) -> None:
        pass

    def iter_lines(self):
        yield from self.lines


def test_stream_reads_events_and_selected_model(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_stream(method, url, **kwargs):
        captured.update(method=method, url=url, **kwargs)
        return FakeStreamResponse([
            'data: {"type":"start","run_id":"run_1"}',
            "",
            'data: {"type":"token","content":"订单已发货"}',
            "",
            "data: [DONE]",
            "",
        ])

    monkeypatch.setattr("ecommerce_assistant.client.client.httpx.stream", fake_stream)
    events = list(AgentClient("http://example.test").stream("查订单", model="chosen"))

    assert [event["type"] for event in events] == ["start", "token"]
    assert events[1]["content"] == "订单已发货"
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/ecommerce-assistant/stream")
    assert captured["json"]["model"] == "chosen"


@pytest.mark.parametrize(
    ("lines", "message"),
    [
        (['data: {"type":"error","message":"数据库错误"}', ""], "数据库错误"),
        (['data: {"type":"start","run_id":"run_1"}', ""], "[DONE]"),
    ],
)
def test_stream_reports_server_error_or_truncation(monkeypatch, lines, message) -> None:
    monkeypatch.setattr(
        "ecommerce_assistant.client.client.httpx.stream",
        lambda *_args, **_kwargs: FakeStreamResponse(lines),
    )
    with pytest.raises(RuntimeError, match=message):
        list(AgentClient().stream("查订单"))
