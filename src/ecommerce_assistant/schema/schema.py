from __future__ import annotations

import os

from pydantic import BaseModel, Field


class MessageRequest(BaseModel):
    message: str
    thread_id: str = "default-thread"
    user_id: str = "anonymous"


class ChatMessage(BaseModel):
    type: str = "ai"
    content: str
    tool_calls: list[str] = Field(default_factory=list)
    run_id: str = "run-001"


class InfoResponse(BaseModel):
    service: str = "ecommerce_assistant"
    agents: list[str] = Field(default_factory=lambda: ["ecommerce-assistant"])
    models: list[str] = Field(
        default_factory=lambda: [os.getenv("OPENAI_MODEL", "gpt-5.6-sol")]
    )
    base_url: str = os.getenv("OPENAI_BASE_URL", "https://aihub.top/v1")
