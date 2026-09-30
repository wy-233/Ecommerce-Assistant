from __future__ import annotations

import os
import uuid

import streamlit as st

from ecommerce_assistant.client.client import AgentClient
from ecommerce_assistant.llm.client import DEFAULT_MODEL
from ecommerce_assistant.workbench import queries

st.set_page_config(
    page_title="电商运营工作台",
    page_icon=":material/storefront:",
    layout="wide",
)

title_column, status_column = st.columns([4, 1], vertical_alignment="center")
with title_column:
    st.title("电商运营工作台", icon=":material/storefront:")
    st.caption("统一查看订单、库存与物流动态，并通过 AI 助手快速查询业务数据。")
with status_column:
    st.badge("演示数据", icon=":material/science:", color="orange")
    st.caption(queries.DEMO_NOTICE)

dashboard_summary = queries.dashboard_summary()
st.caption(f"数据更新时间：{dashboard_summary['data_updated_at'] or '暂无'}")

with st.container(horizontal=True, wrap=True):
    st.metric(
        "今日订单",
        dashboard_summary["today_order_count"],
        icon=":material/receipt_long:",
        border=True,
        help="今天创建的订单数量",
    )
    st.metric(
        "待处理订单",
        dashboard_summary["pending_order_count"],
        icon=":material/pending_actions:",
        border=True,
        help="待付款、已付款或处理中的订单",
    )
    st.metric(
        "待发货订单",
        dashboard_summary["pending_shipping_order_count"],
        icon=":material/inventory_2:",
        border=True,
        help="已付款或处理中的订单",
    )
    st.metric(
        "运输中包裹",
        dashboard_summary["in_transit_shipment_count"],
        icon=":material/local_shipping:",
        border=True,
        help="运输中或派送中的包裹",
    )
    st.metric(
        "库存预警",
        dashboard_summary["low_stock_sku_count"],
        icon=":material/warning:",
        border=True,
        help="库存不足或缺货的 SKU",
    )
    st.metric(
        "物流异常",
        dashboard_summary["shipment_exception_count"],
        icon=":material/report_problem:",
        border=True,
        help="当前状态为物流异常的包裹",
    )

with st.container(border=True):
    section_title, section_link = st.columns([4, 1], vertical_alignment="center")
    with section_title:
        st.subheader("最近订单", icon=":material/receipt_long:")
        st.caption("按下单时间展示最近 5 条订单")
    with section_link:
        st.page_link(
            "pages/1_订单管理.py",
            label="查看全部订单",
            icon=":material/arrow_forward:",
            width="stretch",
        )

    recent_orders = [
        {
            "订单号": row["order_id"],
            "客户": row["customer_name_masked"],
            "地区": row["country_label"],
            "订单状态": row["order_status_label"],
            "付款状态": row["payment_status_label"],
            "金额": float(row["total_amount"] or 0),
            "下单时间": row["created_at"],
        }
        for row in dashboard_summary["recent_orders"]
    ]
    if recent_orders:
        st.dataframe(
            recent_orders,
            width="stretch",
            hide_index=True,
            column_config={
                "订单号": st.column_config.TextColumn("订单号", pinned=True),
                "金额": st.column_config.NumberColumn("金额", format="%.2f"),
                "下单时间": st.column_config.DatetimeColumn(
                    "下单时间", format="YYYY-MM-DD HH:mm"
                ),
            },
        )
    else:
        st.info("暂无订单记录。", icon=":material/info:")

alert_column, logistics_column = st.columns(2)
with alert_column:
    with st.container(border=True, height="stretch"):
        st.subheader("库存预警", icon=":material/warning:")
        st.caption(f"需要关注的 SKU：{dashboard_summary['low_stock_sku_count']} 个")
        inventory_alerts = [
            {
                "SKU": row["sku"],
                "商品": row["product_name"],
                "仓库": row["warehouse_name"],
                "可售": row["available"],
                "安全库存": row["safety_stock"],
                "状态": row["status_label"],
            }
            for row in dashboard_summary["inventory_alerts"]
        ]
        if inventory_alerts:
            st.dataframe(
                inventory_alerts,
                width="stretch",
                hide_index=True,
                column_config={
                    "SKU": st.column_config.TextColumn("SKU", pinned=True),
                    "可售": st.column_config.NumberColumn("可售", format="%d"),
                    "安全库存": st.column_config.NumberColumn("安全库存", format="%d"),
                },
            )
        else:
            st.success("当前没有库存预警。", icon=":material/check_circle:")
        st.page_link(
            "pages/2_库存看板.py",
            label="打开库存看板",
            icon=":material/arrow_forward:",
        )

with logistics_column:
    with st.container(border=True, height="stretch"):
        st.subheader("物流异常", icon=":material/report_problem:")
        st.caption(f"异常包裹：{dashboard_summary['shipment_exception_count']} 个")
        shipment_alerts = [
            {
                "包裹号": row["shipment_id"],
                "订单号": row["order_id"],
                "承运商": row["carrier"],
                "状态": row["shipping_status_label"],
                "更新时间": row["updated_at"],
            }
            for row in dashboard_summary["shipment_alerts"]
        ]
        if shipment_alerts:
            st.dataframe(
                shipment_alerts,
                width="stretch",
                hide_index=True,
                column_config={
                    "包裹号": st.column_config.TextColumn("包裹号", pinned=True),
                    "更新时间": st.column_config.DatetimeColumn(
                        "更新时间", format="YYYY-MM-DD HH:mm"
                    ),
                },
            )
        else:
            st.success("当前没有物流异常。", icon=":material/check_circle:")
        st.page_link(
            "pages/3_物流跟踪.py",
            label="打开物流跟踪",
            icon=":material/arrow_forward:",
        )

st.header("AI 业务助手", icon=":material/smart_toy:")
st.caption("订单、库存和物流问题使用确定性数据库查询；售后政策与通用问题才会使用模型。")

client = AgentClient(os.getenv("API_BASE_URL") or "http://localhost:8084")

if "thread_id" not in st.session_state:
    st.session_state.thread_id = f"streamlit-{uuid.uuid4().hex[:8]}"
if "messages" not in st.session_state:
    st.session_state.messages = []

MODEL_INTENTS = {"llm", "rag"}


def _load_models(include_remote: bool) -> tuple[list[str], str, bool]:
    """返回 (候选模型清单, 默认模型, 是否成功合并中转站清单)。

    后端不可达时回退到内置默认模型，页面不会因为模型清单拉取失败而白屏。
    """
    try:
        payload = client.list_models(include_remote=include_remote)
    except Exception:
        return [DEFAULT_MODEL], DEFAULT_MODEL, False

    options = list(payload.get("models") or [DEFAULT_MODEL])
    default_model = payload.get("default") or options[0]
    return options, default_model, payload.get("source") == "merged"


if "model_options" not in st.session_state:
    options, default_model, _ = _load_models(False)
    st.session_state.model_options = options
    st.session_state.default_model = default_model
if "selected_model" not in st.session_state:
    st.session_state.selected_model = (
        st.session_state.default_model
        if st.session_state.default_model in st.session_state.model_options
        else st.session_state.model_options[0]
    )

with st.container(border=True):
    model_column, action_column = st.columns([4, 1], vertical_alignment="bottom")
    with model_column:
        model_options = st.session_state.model_options
        st.session_state.selected_model = st.selectbox(
            "回复模型",
            options=model_options,
            index=(
                model_options.index(st.session_state.selected_model)
                if st.session_state.selected_model in model_options
                else 0
            ),
            help="只影响售后政策和通用问答；业务数据查询不经过模型。",
        )
    with action_column:
        if st.button(
            "同步模型列表",
            icon=":material/sync:",
            width="stretch",
        ):
            options, default_model, remote_ok = _load_models(True)
            st.session_state.model_options = options
            st.session_state.default_model = default_model
            st.session_state.remote_hint = (
                f"已合并中转站模型清单，共 {len(options)} 个可选模型。"
                if remote_ok
                else "中转站模型清单拉取失败，已沿用 .env 中配置的候选清单。"
            )
            st.rerun()

    if st.session_state.get("remote_hint"):
        st.caption(st.session_state.remote_hint)

with st.container(border=True):
    if not st.session_state.messages:
        st.info(
            "你可以查询订单状态、库存余量、物流轨迹，也可以咨询退换货和配送政策。",
            icon=":material/tips_and_updates:",
        )

    for message in st.session_state.messages:
        role = message["role"] if message["role"] in {"user", "assistant"} else "assistant"
        avatar = ":material/person:" if role == "user" else ":material/smart_toy:"
        with st.chat_message(role, avatar=avatar):
            if role == "assistant" and message.get("intent"):
                if message["intent"] in MODEL_INTENTS:
                    st.caption(f"模型回复 · {message.get('model') or '默认模型'}")
                else:
                    st.caption("业务工具查询 · 未使用模型")
            if message["role"] == "error":
                st.error(message["content"], icon=":material/error:")
            else:
                st.markdown(message["content"])
            if role == "assistant" and message.get("sources"):
                with st.expander(
                    f"查看 {len(message['sources'])} 条来源",
                    icon=":material/library_books:",
                ):
                    for source in message["sources"]:
                        st.markdown(f"**{source.get('doc') or '未命名来源'}**")
                        st.caption(str(source.get("snippet") or ""))
                        if source.get("placeholder"):
                            st.badge("占位内容", color="orange")

prompt = st.chat_input(
    "例如：订单 1005 的物流到哪里了？",
    submit_mode="disable",
)
if prompt:
    used_model = st.session_state.selected_model
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar=":material/person:"):
        st.markdown(prompt)
    try:
        details = {"route": None, "sources": [], "tool_calls": []}

        def answer_tokens():
            for event in client.stream(
                prompt,
                thread_id=st.session_state.thread_id,
                user_id="streamlit-user",
                model=used_model,
            ):
                kind = event.get("type")
                if kind == "route":
                    details["route"] = event.get("route")
                elif kind == "tool_call":
                    details["tool_calls"].append(
                        {"name": event.get("name"), "args": event.get("args") or {}}
                    )
                elif kind == "sources":
                    details["sources"] = event.get("sources") or []
                elif kind == "token":
                    yield event.get("content", "")

        with st.chat_message("assistant", avatar=":material/smart_toy:"):
            answer = st.write_stream(answer_tokens())
        route = details["route"]
        intent = "rag" if details["sources"] else "llm" if route == "after" else route
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": answer,
                "model": used_model,
                "intent": intent,
                "sources": details["sources"],
                "tool_calls": details["tool_calls"],
            }
        )
    except Exception as exc:  # pragma: no cover - UI fallback
        error_text = f"请求失败：{exc}"
        st.session_state.messages.append({"role": "error", "content": error_text})

    st.rerun()

with st.expander("服务诊断", icon=":material/settings:"):
    st.caption("仅用于检查后端服务、模型候选清单和 API 地址。")
    if st.button("获取服务信息", icon=":material/monitor_heart:"):
        try:
            info = client.get_info()
            st.json(info)
        except Exception as exc:  # pragma: no cover - UI fallback
            st.error(f"无法获取服务信息：{exc}", icon=":material/error:")
