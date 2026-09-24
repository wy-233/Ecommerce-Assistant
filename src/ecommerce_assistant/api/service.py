from __future__ import annotations

import json
import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from ecommerce_assistant.agents.ecommerce_assistant import build_graph
from ecommerce_assistant.db.chat_dao import ChatThreadDAO
from ecommerce_assistant.db.init_db import DEFAULT_DB_PATH, initialize_database
from ecommerce_assistant.llm.client import (
    get_llm_config,
    get_model_candidates,
    list_remote_models,
)
from ecommerce_assistant.schema.routes import ROUTE_UNKNOWN
from ecommerce_assistant.schema.schema import (
    ChatMessage,
    DashboardSummaryResponse,
    InfoResponse,
    InventoryDetailResponse,
    InventoryListResponse,
    MessageRequest,
    ModelListResponse,
    OrderDetailResponse,
    OrderListResponse,
    ShipmentEventListResponse,
    ShipmentListResponse,
    ShippingDetailResponse,
    Source,
    ToolCall,
)
from ecommerce_assistant.tools.database import (
    INVALID_ARGUMENT,
    NO_LOGISTICS,
    NOT_FOUND,
    list_inventory_records,
    list_order_records,
    list_shipment_records,
    query_inventory_by_sku,
    query_dashboard_summary,
    query_logistics,
    query_order,
    query_shipment_events,
)

DB_PATH = Path(os.getenv("ECOMMERCE_DB_PATH", DEFAULT_DB_PATH))
chat_dao = ChatThreadDAO(DB_PATH)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """在应用启动阶段完成唯一一次数据库 schema/演示数据初始化。"""
    _app.state.database = initialize_database(DB_PATH, seed_demo=True)
    yield


app = FastAPI(title="Ecommerce Assistant API", lifespan=lifespan)

# 独立 Web 前端（frontend/index.html）以 file:// 直接打开时，Origin 为 "null"；
# 演示环境不做鉴权，允许任意来源即可覆盖 file:// 与本地开发服务器两种情形。
# 注意 allow_credentials 保持 False：与 allow_origins=["*"] 同时开启会被浏览器拒绝。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

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


def _sanitize_order_detail(raw: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(raw)
    for key in ["customer_phone", "customer_email", "customer_address", "shipping_address"]:
        sanitized.pop(key, None)
    return sanitized


def _raise_for_result(result: dict[str, Any]) -> None:
    """把业务查询层的错误码映射为 HTTP 状态码。

    INVALID_ARGUMENT -> 400，NOT_FOUND / NO_LOGISTICS -> 404，DB_ERROR 等 -> 500。
    """
    code = result["code"]
    if code == INVALID_ARGUMENT:
        raise HTTPException(status_code=400, detail=result["message"])
    if code in (NOT_FOUND, NO_LOGISTICS):
        raise HTTPException(status_code=404, detail=result["message"])
    raise HTTPException(status_code=500, detail=result["message"])


@app.get("/info")
def get_info() -> dict[str, Any]:
    return InfoResponse().model_dump()


@app.get("/models", response_model=ModelListResponse)
def list_models(include_remote: bool = Query(default=False)) -> dict[str, Any]:
    """工作台模型选择器可用的模型清单。

    - 默认只返回 `.env` 中 `OPENAI_MODELS` 配置的短清单（source="env"）。
    - ``include_remote=true`` 时额外拉取中转站 `GET {base_url}/models` 并合并；
      拉取失败则静默回退到短清单，`source` 保持 "env"，页面据此提示降级原因。
    """
    local = get_model_candidates()
    default_model = get_llm_config()[1]

    if not include_remote:
        return {"models": local, "default": default_model, "source": "env"}

    remote = list_remote_models()
    if not remote:
        return {"models": local, "default": default_model, "source": "env"}

    return {
        "models": list(dict.fromkeys([*local, *remote])),
        "default": default_model,
        "source": "merged",
    }


@app.get("/dashboard/summary", response_model=DashboardSummaryResponse)
def get_dashboard_summary() -> dict[str, Any]:
    """返回与工作台首页同源的仪表盘汇总数据。"""
    result = query_dashboard_summary(db_path=DB_PATH)
    if not result["ok"]:
        _raise_for_result(result)
    return result["data"]


@app.get("/orders", response_model=OrderListResponse)
def list_orders(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None),
    status: str | None = Query(default=None),
    country: str | None = Query(default=None),
    carrier: str | None = Query(default=None),
    warehouse_id: str | None = Query(default=None),
) -> dict[str, Any]:
    result = list_order_records(
        search=search,
        status=status,
        country=country,
        carrier=carrier,
        warehouse_id=warehouse_id,
        db_path=DB_PATH,
    )
    if not result["ok"]:
        _raise_for_result(result)
    records = result["data"]["records"]
    total = len(records)
    paged = records[(page - 1) * page_size : page * page_size]
    items = [OrderDetailResponse.model_validate(_sanitize_order_detail(row)).model_dump() for row in paged]
    return {"items": items, "page": page, "page_size": page_size, "total": total}


@app.get("/orders/{order_id}", response_model=OrderDetailResponse)
def get_order_detail(order_id: str) -> dict[str, Any]:
    """订单详情。数据与 Agent 订单工具同源（tools.database.query_order）。"""
    result = query_order(order_id, db_path=DB_PATH)
    if not result["ok"]:
        _raise_for_result(result)
    return _sanitize_order_detail(result["data"])


@app.get("/inventory", response_model=InventoryListResponse)
def list_inventory(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None),
    status: str | None = Query(default=None),
    warehouse_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """库存列表。数据与 Agent 库存工具同源（tools.database.list_inventory_records）。

    库存状态由 available / safety_stock 规则计算，``status`` 按计算后的英文码过滤。
    """
    result = list_inventory_records(
        keyword=search, warehouse_id=warehouse_id, status=status, db_path=DB_PATH
    )
    if not result["ok"]:
        _raise_for_result(result)

    records = result["data"]["records"]
    total = len(records)
    paged = records[(page - 1) * page_size : page * page_size]
    items = [InventoryDetailResponse.model_validate(record).model_dump() for record in paged]
    return {"items": items, "page": page, "page_size": page_size, "total": total}


@app.get("/inventory/{sku}", response_model=InventoryDetailResponse)
def get_inventory_detail(sku: str) -> dict[str, Any]:
    """库存详情。数据与 Agent 库存工具同源（tools.database.query_inventory_by_sku）。"""
    result = query_inventory_by_sku(sku, db_path=DB_PATH)
    if not result["ok"]:
        _raise_for_result(result)
    return result["data"]


@app.get("/shipments", response_model=ShipmentListResponse)
def list_shipments(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None),
    status: str | None = Query(default=None),
    country: str | None = Query(default=None),
    carrier: str | None = Query(default=None),
    warehouse_id: str | None = Query(default=None),
) -> dict[str, Any]:
    result = list_shipment_records(
        search=search,
        status=status,
        country=country,
        carrier=carrier,
        warehouse_id=warehouse_id,
        db_path=DB_PATH,
    )
    if not result["ok"]:
        _raise_for_result(result)
    records = result["data"]["records"]
    total = len(records)
    paged = records[(page - 1) * page_size : page * page_size]
    return {"items": paged, "page": page, "page_size": page_size, "total": total}


@app.get("/shipments/{shipment_id}", response_model=ShippingDetailResponse)
def get_shipment_detail(shipment_id: str) -> dict[str, Any]:
    """包裹详情。数据与 Agent 物流工具同源（tools.database.query_logistics）。"""
    result = query_logistics(shipment_id=shipment_id, db_path=DB_PATH)
    if not result["ok"]:
        _raise_for_result(result)
    return result["data"]["shipment"]


@app.get("/shipments/{shipment_id}/events", response_model=ShipmentEventListResponse)
def get_shipment_events(shipment_id: str) -> dict[str, Any]:
    """包裹轨迹。数据与 Agent 物流工具同源（tools.database.query_shipment_events）。"""
    result = query_shipment_events(shipment_id, db_path=DB_PATH)
    if not result["ok"]:
        _raise_for_result(result)
    data = result["data"]
    return {
        "shipment_id": data["shipment_id"],
        "current_status": data["current_status"],
        "items": data["events"],
    }


def _chat_message_from_state(state: dict[str, Any]) -> ChatMessage:
    """把 Agent 状态里的结构化结果转成 PRD v0.2 §6.7.1 约定的 ChatMessage。

    ``route`` / ``sources`` / ``tool_calls`` 一律以 ``state["result"]`` 为准，
    前端不得自行推断路由（design/FRONTEND-SPEC.md §6.4）。
    run_id 形如 ``run_7f2c41``，与 design/index.html 的展示格式一致，且每条唯一，
    便于轨迹栏区分「最新一次」。
    """
    result = state.get("result") or {}
    content = state.get("answer") or result.get("content") or "抱歉，我暂时无法回答这个问题。"
    return ChatMessage(
        type="ai",
        content=content,
        tool_calls=[ToolCall(**call) for call in result.get("tool_calls", [])],
        run_id=f"run_{uuid.uuid4().hex[:6]}",
        intent=state.get("intent"),
        route=result.get("route", ROUTE_UNKNOWN),
        sources=[Source(**source) for source in result.get("sources", [])],
    )


@app.post("/ecommerce-assistant/invoke")
def invoke_assistant(request: MessageRequest) -> ChatMessage:
    history = _normalize_history(request.thread_id)
    state = agent.invoke(
        {"message": request.message, "history": history, "model": request.model}
    )
    message = _chat_message_from_state(state)

    chat_dao.ensure_thread(request.thread_id, request.user_id)
    chat_dao.append_message(request.thread_id, "user", request.message, request.user_id)
    chat_dao.append_message(request.thread_id, "assistant", message.content, request.user_id)

    return message


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _tokenize(content: str) -> list[str]:
    """把正文切成可无损拼回的增量。

    按「非空白字符 + 其后的空白」切分，``"".join(_tokenize(text)) == text``，
    因此前端逐段追加不会丢失空格。
    """
    return re.findall(r"\S+\s*", content)


@app.post("/ecommerce-assistant/stream")
def stream_assistant(request: MessageRequest):
    """SSE 流式响应，事件类型见 docs/PRD.md v0.2 §6.7.2。

    事件顺序：start → route → tool_call* → sources? → token* → [DONE]。
    ``route`` 先于正文到达，前端据此播放投递动效（FRONTEND-SPEC §7.4）；
    tool_call 与 sources 属可选事件，缺失时前端降级即可。
    """
    def event_generator():
        try:
            history = _normalize_history(request.thread_id)
            state = agent.invoke(
                {"message": request.message, "history": history, "model": request.model}
            )
            message = _chat_message_from_state(state)

            chat_dao.ensure_thread(request.thread_id, request.user_id)
            chat_dao.append_message(request.thread_id, "user", request.message, request.user_id)
            chat_dao.append_message(request.thread_id, "assistant", message.content, request.user_id)

            yield _sse({"type": "start", "run_id": message.run_id})
            yield _sse({"type": "route", "route": message.route})
            for call in message.tool_calls:
                yield _sse({"type": "tool_call", "name": call.name, "args": call.args})
            if message.sources:
                yield _sse({"type": "sources", "sources": [source.model_dump() for source in message.sources]})
            for token in _tokenize(message.content):
                yield _sse({"type": "token", "content": token})
        except Exception as exc:  # noqa: BLE001 - 出错也要以 [DONE] 正常收尾（PRD §6.7.2）
            yield _sse({"type": "error", "message": str(exc)})
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("ecommerce_assistant.api.service:app", host="0.0.0.0", port=8080, reload=False)
