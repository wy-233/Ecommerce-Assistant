from __future__ import annotations

import re

from langgraph.graph import END, StateGraph

from ecommerce_assistant.llm.client import call_llm
from ecommerce_assistant.rag.retriever import retrieve_knowledge
from ecommerce_assistant.schema.routes import (
    ROUTE_AFTER,
    ROUTE_ORDER,
    ROUTE_SHIP,
    ROUTE_STOCK,
    ROUTE_UNKNOWN,
    TOOL_CALL_NAMES,
)
from ecommerce_assistant.tools.inventory import get_inventory_status
from ecommerce_assistant.tools.logistics import get_logistics_status
from ecommerce_assistant.tools.order import get_order_status

SYSTEM_PROMPT = (
    "你是一个跨境电商售后助手，回答要简洁、专业、友好，并优先基于已知订单、库存、物流和售后政策信息。"
    "在适合的场景下可适度使用 emoji（如 😊📦🚚📦）提升亲和感，但不要过度堆砌，保持专业和清晰。"
)


def _is_history_reference_question(question: str) -> bool:
    q = question.lower()
    return bool(
        re.search(
            r"(刚刚|刚才|上次|上一条|上一句|我刚刚|我刚才|你刚刚|你刚才|问了什么|说了什么|回复了什么)",
            q,
        )
    )


def _format_history_context(history: list[dict[str, str]] | None, current_question: str) -> str:
    if not history:
        return current_question

    lines = [f"{item['role']}:{item['content']}" for item in history if item.get("content")]
    if not lines:
        return current_question

    return "\n".join(["以下是最近的对话历史：", *lines, "", "当前问题：" + current_question])


def _detect_intent(question: str) -> str:
    q = question.lower()
    if _is_history_reference_question(question):
        return "llm"
    if any(word in q for word in ["退货", "退款", "退换", "售后", "商品问题", "质量", "怎么退"]):
        return "rag"
    # 库存与物流的关键词比"订单"更具体，必须先判定：
    # 否则「订单 1005 使用了什么物流？」会因含"订单"而被误路由到订单查询。
    if any(word in q for word in ["库存", "sku", "stock", "有货", "缺货"]):
        return "inventory"
    if any(word in q for word in ["物流", "快递", "运输", "配送", "送到"]):
        return "logistics"
    if any(word in q for word in ["订单", "order", "订单号"]):
        return "order"
    return "llm"


def _extract_order_id(question: str) -> str:
    match = re.search(r"(\d{4,})", question)
    return match.group(1) if match else ""


def _extract_sku(question: str) -> str:
    match = re.search(r"[A-Z]+-\d+", question.upper())
    return match.group(0) if match else ""


def _answer(content: str, route: str, intent: str, sources: list[dict] | None = None) -> dict:
    return {
        "content": content,
        "route": route,
        "tool_calls": [],
        "sources": list(sources or []),
        "intent": intent,
    }


def _tool_answer(content: str, route: str, args: dict, intent: str) -> dict:
    return {
        "content": content,
        "route": route,
        "tool_calls": [{"name": TOOL_CALL_NAMES[route], "args": args}],
        "sources": [],
        "intent": intent,
    }


def answer_question(
    question: str, history: list[dict[str, str]] | None = None, model: str | None = None
) -> dict:
    """结构化回答：``{content, route, tool_calls, sources, intent}``。

    route 的判定依据是「回答实际来自哪里」，而非路由关键词命中了哪一类：

    | 回答来源 | route | tool_calls |
    | --- | --- | --- |
    | 订单 / 库存 / 物流工具 | order / stock / ship | 带调用签名；参数缺失时为空 |
    | 知识库命中 | after | 空，来源走 sources |
    | 模型直接作答 | after | 空，sources 为空 |
    | 知识库未命中、本地会话记忆 | unknown | 空 |

    参数缺失（如「现在到哪里了？」没有单号）时 route 保持被路由到的道，但 tool_calls
    为空——因为确实没有调用工具。
    """
    intent = _detect_intent(question)

    if _is_history_reference_question(question):
        previous_user_questions = [
            item["content"]
            for item in reversed(history or [])
            if item.get("role") == "user" and item.get("content") and item["content"] != question
        ]
        content = (
            f"你刚刚问的是：{previous_user_questions[0]}"
            if previous_user_questions
            else "我刚才没有看到你上一条问题。"
        )
        return _answer(content, ROUTE_UNKNOWN, intent)

    if intent == "rag":
        result = retrieve_knowledge(question)
        route = ROUTE_AFTER if result["sources"] else ROUTE_UNKNOWN
        # 来源只走 sources 字段（PRD v0.2 §6.7.1）：正文不再拼接「来源：」，
        # 否则前端正文与来源块会重复展示同一个文档路径。
        return _answer(result["answer"], route, intent, result["sources"])

    if intent == "order":
        order_id = _extract_order_id(question)
        if not order_id:
            return _answer("我需要订单号才能查询订单状态。请告诉我订单号，例如 1005 或 1018。", ROUTE_ORDER, intent)
        return _tool_answer(get_order_status(order_id), ROUTE_ORDER, {"order_id": order_id}, intent)

    if intent == "inventory":
        sku = _extract_sku(question)
        if not sku:
            return _answer("我需要 SKU 才能查询库存。请提供商品 SKU，例如 SKU-005。", ROUTE_STOCK, intent)
        return _tool_answer(get_inventory_status(sku), ROUTE_STOCK, {"sku": sku}, intent)

    if intent == "logistics":
        order_id = _extract_order_id(question)
        if not order_id:
            return _answer("我需要订单号或快递单号才能查询物流状态。请告诉我订单号，例如 1005。", ROUTE_SHIP, intent)
        return _tool_answer(get_logistics_status(order_id), ROUTE_SHIP, {"order_id": order_id}, intent)

    prompt = _format_history_context(history, question)
    llm_answer = call_llm(prompt, system_prompt=SYSTEM_PROMPT, model=model)
    if llm_answer:
        return _answer(llm_answer, ROUTE_AFTER, intent)

    result = retrieve_knowledge(question)
    route = ROUTE_AFTER if result["sources"] else ROUTE_UNKNOWN
    return _answer(result["answer"], route, intent, result["sources"])


def handle_question(
    question: str, history: list[dict[str, str]] | None = None, model: str | None = None
) -> str:
    """``answer_question`` 的文本视图，供只关心回答正文的调用方使用。

    ``model`` 只作用于 LLM 分支；订单、库存、物流三条分支是确定性 SQL 查询，
    不受模型影响。
    """
    return answer_question(question, history, model)["content"]


def build_graph():
    workflow = StateGraph(dict)

    def route_agent(state):
        question = state.get("message", "")
        intent = _detect_intent(question)
        state["intent"] = intent
        return state

    def answer_agent(state):
        result = answer_question(
            state.get("message", ""),
            state.get("history", []),
            state.get("model"),
        )
        state["answer"] = result["content"]
        state["result"] = result
        return state

    workflow.add_node("route", route_agent)
    workflow.add_node("answer", answer_agent)
    workflow.set_entry_point("route")
    workflow.add_edge("route", "answer")
    workflow.add_edge("answer", END)
    return workflow.compile()
