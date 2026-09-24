from __future__ import annotations

import streamlit as st

from ecommerce_assistant.schema.statuses import SHIPPING_STATUS_LABELS
from ecommerce_assistant.workbench import queries

st.set_page_config(page_title="物流跟踪", layout="wide")

st.title("物流跟踪")
st.caption(queries.DEMO_NOTICE)

summary = queries.shipment_summary()
metric_columns = st.columns(5)
metric_columns[0].metric("包裹总数", summary["total"])
metric_columns[1].metric("运输中", summary["in_transit"])
metric_columns[2].metric("物流异常", summary["exception"])
metric_columns[3].metric("已签收", summary["delivered"])
metric_columns[4].metric("轨迹总数", summary["event_total"])

st.divider()

status_choices: dict[str, str | None] = {"全部": None}
status_choices.update({label: code for code, label in SHIPPING_STATUS_LABELS.items()})

filter_columns = st.columns([1, 2])
status_label = filter_columns[0].selectbox("物流状态", options=list(status_choices))
keyword = filter_columns[1].text_input("关键字", placeholder="订单号 / 包裹号 / 运单号，如 1005")

rows = queries.list_shipments(
    status=status_choices[status_label],
    keyword=keyword.strip() or None,
)

st.subheader(f"包裹列表（{len(rows)} 条）")
if not rows:
    st.info("没有符合条件的物流记录。")
    st.stop()

st.dataframe(
    [
        {
            "包裹号": row["shipment_id"],
            "订单号": row["order_id"],
            "承运商": row["carrier"],
            "运单号": row["tracking_number"],
            "物流状态": row["shipping_status_label"],
            "发货时间": row["shipped_at"] or "-",
            "预计送达": row["estimated_delivery_at"] or "-",
            "签收时间": row["delivered_at"] or "-",
            "数据标记": row["is_demo"],
        }
        for row in rows
    ],
    width="stretch",
    hide_index=True,
)

st.divider()
st.subheader("轨迹时间线")

shipment_id = st.selectbox("选择包裹", options=[row["shipment_id"] for row in rows])
events = queries.list_tracking_events(shipment_id)

if not events:
    st.info(f"包裹 {shipment_id} 暂无轨迹记录。")
    st.stop()

for event in events:
    st.markdown(
        f"**{event['event_time']}** ｜ {event['event_status_label']} ｜ {event['location'] or '-'}"
    )
    st.caption(event["description"] or "")
