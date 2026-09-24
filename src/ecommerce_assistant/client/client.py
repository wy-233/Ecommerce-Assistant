from __future__ import annotations

import os

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
