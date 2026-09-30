from __future__ import annotations

import os
import json
from collections.abc import Iterator

import httpx


class AgentClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or os.getenv("API_BASE_URL") or "http://localhost:8084").rstrip("/")

    def get_info(self) -> dict:
        response = httpx.get(f"{self.base_url}/info", timeout=10)
        response.raise_for_status()
        return response.json()

    def list_models(self, include_remote: bool = False) -> dict:
        response = httpx.get(
            f"{self.base_url}/models",
            params={"include_remote": include_remote},
            timeout=60 if include_remote else 10,
        )
        response.raise_for_status()
        return response.json()

    def invoke(
        self,
        message: str,
        thread_id: str = "demo-thread",
        user_id: str = "demo-user",
        model: str | None = None,
    ) -> dict:
        payload: dict[str, str] = {
            "message": message,
            "thread_id": thread_id,
            "user_id": user_id,
        }
        # 不传 model 时保持与旧客户端完全一致的请求体，由服务端回退到 OPENAI_MODEL。
        if model:
            payload["model"] = model

        response = httpx.post(
            f"{self.base_url}/ecommerce-assistant/invoke",
            json=payload,
            # 与 llm/client.py 的 60s 对齐：慢模型下 20s 会在服务端返回前先超时。
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    def stream(
        self,
        message: str,
        thread_id: str = "demo-thread",
        user_id: str = "demo-user",
        model: str | None = None,
    ) -> Iterator[dict]:
        payload = {"message": message, "thread_id": thread_id, "user_id": user_id}
        if model:
            payload["model"] = model

        with httpx.stream(
            "POST",
            f"{self.base_url}/ecommerce-assistant/stream",
            json=payload,
            timeout=60,
        ) as response:
            response.raise_for_status()
            data_lines: list[str] = []
            done = False
            for line in response.iter_lines():
                if line:
                    if line.startswith("data:"):
                        data_lines.append(line[5:].lstrip(" "))
                    continue
                if not data_lines:
                    continue
                data = "\n".join(data_lines)
                data_lines.clear()
                if data == "[DONE]":
                    done = True
                    break
                event = json.loads(data)
                if event.get("type") == "error":
                    raise RuntimeError(event.get("message") or "流式查询失败")
                yield event
            if not done:
                raise RuntimeError("流式响应提前结束，未收到 [DONE]")
