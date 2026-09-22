from __future__ import annotations

import html
import os
import sqlite3
import uuid
from pathlib import Path

import streamlit as st

from ecommerce_assistant.client.client import AgentClient

DB_PATH = Path(os.getenv("ECOMMERCE_DB_PATH", Path(__file__).resolve().parents[2] / "data" / "ecommerce_assistant.db"))

st.set_page_config(page_title="Ecommerce Assistant", page_icon="🛒")

st.markdown(
    """
    <style>
        .stApp {
            background: linear-gradient(180deg, #f7f7fb 0%, #eef3ff 100%);
            color: #1f2937;
        }
        .main .block-container {
            max-width: 1100px;
            padding-top: 2rem;
            padding-bottom: 2rem;
        }
        h1 {
            font-size: 3rem !important;
            font-weight: 800;
            letter-spacing: -0.04em;
            margin-bottom: 1.5rem !important;
        }
        .chat-shell {
            display: flex;
            flex-direction: column;
            gap: 14px;
            margin-top: 1rem;
        }
        .bubble {
            max-width: 80%;
            padding: 14px 16px;
            border-radius: 18px;
            line-height: 1.6;
            font-size: 15px;
            white-space: pre-wrap;
            word-break: break-word;
            box-shadow: 0 4px 12px rgba(15, 23, 42, 0.06);
        }
        .bubble.user {
            align-self: flex-end;
            background: linear-gradient(135deg, #ddeeff 0%, #cfe1ff 100%);
            color: #1d3557;
            border-bottom-right-radius: 6px;
        }
        .bubble.assistant {
            align-self: flex-start;
            background: linear-gradient(135deg, #ffffff 0%, #f3f4f6 100%);
            color: #1f2937;
            border: 1px solid #e5e7eb;
            border-bottom-left-radius: 6px;
        }
        .bubble.error {
            align-self: flex-start;
            background: #fff1f2;
            color: #9f1239;
            border: 1px solid #fecdd3;
        }
        .stChatInput {
            margin-top: 1rem;
        }
        .stChatInput textarea {
            border-radius: 14px !important;
            border: 1px solid #dbeafe !important;
            background: rgba(255,255,255,0.9) !important;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Ecommerce Assistant")


@st.cache_data
def _load_demo_overview() -> dict[str, list[dict[str, object]] | dict[str, int]]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        order_rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT order_id, customer_name_masked, order_status, payment_status, total_amount
                FROM orders
                ORDER BY created_at DESC
                LIMIT 5
                """
            ).fetchall()
        ]
        low_stock_rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT sku, product_name, available, safety_stock, warehouse_name
                FROM inventory
                WHERE available <= safety_stock
                ORDER BY available ASC
                LIMIT 5
                """
            ).fetchall()
        ]
        shipment_rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT s.order_id, s.shipment_id, s.carrier, s.shipping_status, s.tracking_number,
                       COUNT(te.id) AS tracking_count
                FROM shipments s
                LEFT JOIN tracking_events te ON te.shipment_id = s.shipment_id
                GROUP BY s.shipment_id
                ORDER BY s.updated_at DESC
                LIMIT 6
                """
            ).fetchall()
        ]
        summary = {
            "order_total": conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
            "sku_total": conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0],
            "shipment_total": conn.execute("SELECT COUNT(*) FROM shipments").fetchone()[0],
            "low_stock_total": conn.execute("SELECT COUNT(*) FROM inventory WHERE available <= safety_stock").fetchone()[0],
        }
        return {"summary": summary, "orders": order_rows, "low_stock": low_stock_rows, "shipments": shipment_rows}
    finally:
        conn.close()


overview = _load_demo_overview()
summary = overview["summary"]

st.subheader("演示数据版订单 / 库存 / 物流概览")
col1, col2, col3, col4 = st.columns(4)
col1.metric("订单总数", summary["order_total"])
col2.metric("SKU 总数", summary["sku_total"])
col3.metric("发货记录", summary["shipment_total"])
col4.metric("库存预警", summary["low_stock_total"])

st.write("以下为固定演示数据，明确标注为演示数据，不代表真实平台或真实物流。")

with st.container():
    st.subheader("最近订单")
    st.dataframe(overview["orders"], use_container_width=True)

with st.container():
    st.subheader("库存预警")
    st.dataframe(overview["low_stock"], use_container_width=True)

with st.container():
    st.subheader("物流状态")
    st.dataframe(overview["shipments"], use_container_width=True)

client = AgentClient(os.getenv("API_BASE_URL") or "http://localhost:8082")

if "thread_id" not in st.session_state:
    st.session_state.thread_id = f"streamlit-{uuid.uuid4().hex[:8]}"
if "messages" not in st.session_state:
    st.session_state.messages = []

chat_container = st.container()
with chat_container:
    st.markdown('<div class="chat-shell">', unsafe_allow_html=True)
    for message in st.session_state.messages:
        role = message["role"]
        content = html.escape(message["content"])
        if role == "user":
            bubble_class = "bubble user"
        elif role == "assistant":
            bubble_class = "bubble assistant"
        else:
            bubble_class = "bubble error"
        st.markdown(f'<div class="{bubble_class}">{content}</div>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

prompt = st.chat_input("请输入问题（可使用 emoji ✨📦🚚）")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    try:
        result = client.invoke(prompt, thread_id=st.session_state.thread_id, user_id="streamlit-user")
        answer = result.get("content", "")
        st.session_state.messages.append({"role": "assistant", "content": answer})
    except Exception as exc:  # pragma: no cover - UI fallback
        error_text = f"请求失败: {exc}"
        st.session_state.messages.append({"role": "assistant", "content": error_text})

    st.rerun()

if st.button("查看服务信息"):
    try:
        info = client.get_info()
        st.json(info)
    except Exception as exc:  # pragma: no cover - UI fallback
        st.error(f"无法获取服务信息: {exc}")
