from __future__ import annotations

import re

from langgraph.graph import END, StateGraph

from ecommerce_assistant.llm.client import call_llm
from ecommerce_assistant.rag.retriever import retrieve_knowledge
from ecommerce_assistant.tools.inventory import get_inventory_status
from ecommerce_assistant.tools.logistics import get_logistics_status
from ecommerce_assistant.tools.order import get_order_status


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
    if any(word in q for word in ["订单", "order", "快递单", "订单号"]):
        return "order"
    if any(word in q for word in ["库存", "sku", "stock", "有货", "缺货"]):
        return "inventory"
    if any(word in q for word in ["物流", "快递", "运输", "配送", "送到"]):
        return "logistics"
    return "llm"


def _extract_order_id(question: str) -> str:
    match = re.search(r"(\d{4,})", question)
    return match.group(1) if match else ""


def _extract_sku(question: str) -> str:
    match = re.search(r"[A-Z]+-\d+", question.upper())
    return match.group(0) if match else ""


def handle_question(question: str, history: list[dict[str, str]] | None = None) -> str:
    if _is_history_reference_question(question):
        previous_user_questions = [
            item["content"]
            for item in reversed(history or [])
            if item.get("role") == "user" and item.get("content") and item["content"] != question
        ]
        if previous_user_questions:
            return f"你刚刚问的是：{previous_user_questions[0]}"
        return "我刚才没有看到你上一条问题。"

    intent = _detect_intent(question)
    if intent == "rag":
        result = retrieve_knowledge(question)
        return f"{result['answer']}\n来源：{result['source']}"
    if intent == "order":
        order_id = _extract_order_id(question) or "1001"
        return get_order_status(order_id)
    if intent == "inventory":
        sku = _extract_sku(question) or "SKU-001"
        return get_inventory_status(sku)
    if intent == "logistics":
        order_id = _extract_order_id(question) or "1001"
        return get_logistics_status(order_id)

    prompt = _format_history_context(history, question)
    llm_response = call_llm(
        prompt,
        system_prompt=(
            "你是一个跨境电商售后助手，回答要简洁、专业、友好，并优先基于已知订单、库存、物流和售后政策信息。"
            "在适合的场景下可适度使用 emoji（如 😊📦🚚📦）提升亲和感，但不要过度堆砌，保持专业和清晰。"
        ),
    )
    if llm_response:
        return llm_response

    result = retrieve_knowledge(question)
    return f"{result['answer']}\n来源：{result['source']}"


def build_graph():
    workflow = StateGraph(dict)

    def route_agent(state):
        question = state.get("message", "")
        intent = _detect_intent(question)
        state["intent"] = intent
        return state

    def answer_agent(state):
        state["answer"] = handle_question(
            state.get("message", ""),
            state.get("history", []),
        )
        return state

    workflow.add_node("route", route_agent)
    workflow.add_node("answer", answer_agent)
    workflow.set_entry_point("route")
    workflow.add_edge("route", "answer")
    workflow.add_edge("answer", END)
    return workflow.compile()
