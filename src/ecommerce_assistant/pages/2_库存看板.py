from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from ecommerce_assistant.schema.statuses import INVENTORY_STATUS_LABELS
from ecommerce_assistant.workbench import queries

st.set_page_config(page_title="库存看板", layout="wide")

st.title("库存看板")
st.caption(queries.DEMO_NOTICE)

summary = queries.inventory_summary()
metric_columns = st.columns(5)
metric_columns[0].metric("SKU 总数", summary["sku_total"])
metric_columns[1].metric("实际库存合计", summary["on_hand_total"])
metric_columns[2].metric("可售库存合计", summary["available_total"])
metric_columns[3].metric("库存不足", summary["low_stock"])
metric_columns[4].metric("缺货", summary["out_of_stock"])

st.divider()

warehouses = queries.list_warehouses()
warehouse_choices: dict[str, str | None] = {"全部": None}
warehouse_choices.update(
    {f"{row['warehouse_name']}（{row['warehouse_id']}）": row["warehouse_id"] for row in warehouses}
)
status_choices: dict[str, str | None] = {"全部": None}
status_choices.update({label: code for code, label in INVENTORY_STATUS_LABELS.items()})

filter_columns = st.columns([1, 1, 2])
warehouse_label = filter_columns[0].selectbox("仓库", options=list(warehouse_choices))
status_label = filter_columns[1].selectbox("库存状态", options=list(status_choices))
keyword = filter_columns[2].text_input("关键字", placeholder="SKU 或商品名称")

rows = queries.list_inventory(
    warehouse=warehouse_choices[warehouse_label],
    status=status_choices[status_label],
    keyword=keyword.strip() or None,
)

st.subheader(f"库存明细（{len(rows)} 条）")
if not rows:
    st.info("没有符合条件的库存记录。")
    st.stop()

st.dataframe(
    [
        {
            "SKU": row["sku"],
            "商品": row["product_name"],
            "仓库": f"{row['warehouse_name']}（{row['warehouse_id']}）",
            "实际库存": row["on_hand"],
            "已占用": row["reserved"],
            "可售库存": row["available"],
            "安全库存": row["safety_stock"],
            "库存状态": row["status_label"],
            "更新时间": row["updated_at"],
            "数据标记": row["is_demo"],
        }
        for row in rows
    ],
    width="stretch",
    hide_index=True,
)

st.divider()
st.subheader("可售库存与安全库存对比")

status_rank = {
    "out_of_stock": 0,
    "low_stock": 1,
    "normal": 2,
}
chart_frame = pd.DataFrame(
    [
        {
            "SKU": row["sku"],
            "商品": row["product_name"],
            "仓库": row["warehouse_name"],
            "对比项": f"{row['sku']} · {row['warehouse_name']}",
            "可售库存": int(row["available"]),
            "安全库存": int(row["safety_stock"]),
            "差额": int(row["available"]) - int(row["safety_stock"]),
            "差额说明": (
                f"余量 +{int(row['available']) - int(row['safety_stock'])}"
                if int(row["available"]) - int(row["safety_stock"]) > 0
                else f"缺口 {abs(int(row['available']) - int(row['safety_stock']))}"
            ),
            "库存状态": row["status_label"],
            "状态码": row["status"],
            "状态排序": status_rank.get(row["status"], 99),
        }
        for row in rows
    ]
).sort_values(["状态排序", "差额", "SKU", "仓库"])

filtered_out_of_stock = int((chart_frame["状态码"] == "out_of_stock").sum())
filtered_low_stock = int((chart_frame["状态码"] == "low_stock").sum())
replenishment_count = filtered_out_of_stock + filtered_low_stock
largest_shortage = max(0, int(-chart_frame["差额"].min()))

comparison_metrics = st.columns(3)
comparison_metrics[0].metric("当前筛选 SKU", len(chart_frame), border=True)
comparison_metrics[1].metric(
    "需补货 SKU",
    replenishment_count,
    delta=f"缺货 {filtered_out_of_stock} · 库存不足 {filtered_low_stock}",
    delta_color="off",
    border=True,
)
comparison_metrics[2].metric(
    "最大库存缺口",
    largest_shortage,
    help="安全库存减去可售库存后的最大正值。",
    border=True,
)

comparison_order = chart_frame["对比项"].tolist()
tooltip = [
    alt.Tooltip("SKU:N"),
    alt.Tooltip("商品:N"),
    alt.Tooltip("仓库:N"),
    alt.Tooltip("可售库存:Q", format=",d"),
    alt.Tooltip("安全库存:Q", format=",d"),
    alt.Tooltip("差额:Q", format="+d"),
    alt.Tooltip("库存状态:N"),
]
common_y = alt.Y(
    "对比项:N",
    title=None,
    sort=comparison_order,
    axis=alt.Axis(labelLimit=180),
)

available_bars = (
    alt.Chart(chart_frame)
    .mark_bar(size=16, cornerRadiusEnd=4)
    .encode(
        x=alt.X(
            "可售库存:Q",
            title="库存数量",
            scale=alt.Scale(zero=True, nice=True),
            axis=alt.Axis(tickMinStep=1),
        ),
        y=common_y,
        color=alt.Color(
            "库存状态:N",
            title="可售库存状态",
            scale=alt.Scale(
                domain=["缺货", "库存不足", "正常"],
                range=["#DC2626", "#F59E0B", "#16A34A"],
            ),
            legend=alt.Legend(orient="top", direction="horizontal"),
        ),
        tooltip=tooltip,
    )
)

available_points = (
    alt.Chart(chart_frame)
    .mark_point(filled=True, size=70, stroke="white", strokeWidth=1.5)
    .encode(
        x=alt.X("可售库存:Q"),
        y=common_y,
        color=alt.Color(
            "库存状态:N",
            scale=alt.Scale(
                domain=["缺货", "库存不足", "正常"],
                range=["#DC2626", "#F59E0B", "#16A34A"],
            ),
            legend=None,
        ),
        tooltip=tooltip,
    )
)

safety_markers = (
    alt.Chart(chart_frame)
    .mark_tick(color="#475569", thickness=3, size=26)
    .encode(
        x=alt.X("安全库存:Q"),
        y=common_y,
        tooltip=tooltip,
    )
)

comparison_chart = (
    (available_bars + available_points + safety_markers)
    .properties(height=max(320, len(chart_frame) * 42))
    .configure_view(strokeWidth=0)
    .configure_axis(gridColor="#E2E8F0", gridOpacity=0.65, domain=False)
)

st.altair_chart(comparison_chart, width="stretch")

st.caption(
    "彩色横条表示可售库存，深灰短线表示安全库存线。横条未达到安全线时需要关注；"
    "悬停可查看商品、仓库、库存差额和当前状态。"
)
