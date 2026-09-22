from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from ecommerce_assistant.agents.ecommerce_assistant import build_graph
from ecommerce_assistant.db.chat_dao import ChatThreadDAO
from ecommerce_assistant.db.init_db import DEFAULT_DB_PATH, init_db
from ecommerce_assistant.schema.schema import ChatMessage, InfoResponse, MessageRequest

DB_PATH = Path(os.getenv("ECOMMERCE_DB_PATH", DEFAULT_DB_PATH))
init_db(DB_PATH)
chat_dao = ChatThreadDAO(DB_PATH)

app = FastAPI(title="Ecommerce Assistant API")

agent = build_graph()


def _normalize_history(thread_id: str) -> list[dict[str, str]]:
    return chat_dao.get_history(thread_id, limit=12)


def _build_context_prompt(history: list[dict[str, str]], current_message: str) -> str:
    if not history:
        return current_message

    lines = [
        f"{'用户' if item['role'] == 'user' else '助手'}: {item['content']}" for item in history
    ]
    return "\n".join(["以下是历史对话：", *lines, "", "请基于以上上下文回答当前问题：", current_message])


@app.get("/info")
def get_info() -> dict[str, Any]:
    return InfoResponse().model_dump()


@app.post("/ecommerce-assistant/invoke")
def invoke_assistant(request: MessageRequest) -> ChatMessage:
    history = _normalize_history(request.thread_id)
    result = agent.invoke({"message": request.message, "history": history})
    content = result.get("answer", "抱歉，我暂时无法回答这个问题。")

    chat_dao.ensure_thread(request.thread_id, request.user_id)
    chat_dao.append_message(request.thread_id, "user", request.message, request.user_id)
    chat_dao.append_message(request.thread_id, "assistant", content, request.user_id)

    return ChatMessage(content=content, type="ai", tool_calls=[], run_id=f"run-{request.thread_id}")


@app.post("/ecommerce-assistant/stream")
def stream_assistant(request: MessageRequest):
    def event_generator():
        history = _normalize_history(request.thread_id)
        result = agent.invoke({"message": request.message, "history": history})
        content = result.get("answer", "抱歉，我暂时无法回答这个问题。")

        chat_dao.ensure_thread(request.thread_id, request.user_id)
        chat_dao.append_message(request.thread_id, "user", request.message, request.user_id)
        chat_dao.append_message(request.thread_id, "assistant", content, request.user_id)

        for token in content.split():
            yield f"data: {token}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("ecommerce_assistant.api.service:app", host="0.0.0.0", port=8080, reload=False)
