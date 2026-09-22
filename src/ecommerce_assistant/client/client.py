from __future__ import annotations

import os

import httpx


class AgentClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or os.getenv("API_BASE_URL") or "http://localhost:8082").rstrip("/")

    def get_info(self) -> dict:
        response = httpx.get(f"{self.base_url}/info", timeout=10)
        response.raise_for_status()
        return response.json()

    def invoke(self, message: str, thread_id: str = "demo-thread", user_id: str = "demo-user") -> dict:
        response = httpx.post(
            f"{self.base_url}/ecommerce-assistant/invoke",
            json={"message": message, "thread_id": thread_id, "user_id": user_id},
            timeout=20,
        )
        response.raise_for_status()
        return response.json()
