from __future__ import annotations

import streamlit as st

from ecommerce_assistant.schema.statuses import ORDER_STATUS_LABELS
from ecommerce_assistant.workbench import queries

st.set_page_config(page_title="订单管理", layout="wide")

st.title("订单管理")
st.caption(queries.DEMO_NOTICE)

summary = queries.order_summary()
metric_columns = st.columns(4)
metric_columns[0].metric("订单总数", summary["total"])
metric_columns[1].metric("待付款", summary["pending_payment"])
metric_columns[2].metric("已发货", summary["shipped"])
metric_columns[3].metric("已取消", summary["cancelled"])

st.divider()

all_orders = queries.list_orders()
status_choices: dict[str, str | None] = {"全部": None}
status_choices.update({label: code for code, label in ORDER_STATUS_LABELS.items()})

country_choices: dict[str, str | None] = {"全部": None}
country_choices.update(
    {order["country_label"]: order["customer_country"] for order in all_orders}
)

filter_columns = st.columns([1, 1, 2])
status_label = filter_columns[0].selectbox("订单状态", options=list(status_choices))
country_label = filter_columns[1].selectbox("客户地区", options=list(country_choices))
keyword = filter_columns[2].text_input("关键字", placeholder="订单号或客户代号，如 1001 / C***")

rows = queries.list_orders(
    status=status_choices[status_label],
    country=country_choices[country_label],
    keyword=keyword.strip() or None,
)

st.subheader(f"订单列表（{len(rows)} 条）")
if not rows:
    st.info("没有符合条件的订单。")
    st.stop()

st.dataframe(
    [
        {
            "订单号": row["order_id"],
            "客户": row["customer_name_masked"],
            "地区": row["country_label"],
            "订单状态": row["order_status_label"],
            "付款状态": row["payment_status_label"],
            "履约状态": row["fulfillment_status_label"],
            "币种": row["currency"],
            "金额": f"{float(row['total_amount']):,.2f}",
            "下单时间": row["created_at"],
            "更新时间": row["updated_at"],
            "数据标记": row["is_demo"],
        }
        for row in rows
    ],
    width="stretch",
    hide_index=True,
)

st.divider()
st.subheader("订单详情")

order_id = st.selectbox("选择订单", options=[row["order_id"] for row in rows])
order = queries.get_order(order_id)
items = queries.list_order_items(order_id)
shipments = queries.list_shipments_by_order(order_id)

if order is None:
    st.error(f"订单 {order_id} 不存在。")
    st.stop()

info_column, item_column = st.columns(2)

with info_column:
    st.markdown("**订单信息**")
    st.write(
        {
            "订单号": order["order_id"],
            "客户": order["customer_name_masked"],
            "地区": order["country_label"],
            "订单状态": order["order_status_label"],
            "付款状态": order["payment_status_label"],
            "履约状态": order["fulfillment_status_label"],
            "币种": order["currency"],
            "订单金额": float(order["total_amount"]),
            "下单时间": order["created_at"],
            "更新时间": order["updated_at"],
        }
    )

with item_column:
    st.markdown("**商品明细**")
    if items:
        st.dataframe(
            [
                {
                    "SKU": item["sku"],
                    "商品": item["product_name"],
                    "数量": item["quantity"],
                    "单价": f"{float(item['unit_price']):,.2f}",
                    "小计": f"{item['subtotal']:,.2f}",
                }
                for item in items
            ],
            width="stretch",
            hide_index=True,
        )
        items_total = round(sum(item["subtotal"] for item in items), 2)
        order_total = round(float(order["total_amount"]), 2)
        if abs(items_total - order_total) > 0.01:
            st.error(f"数据异常：明细合计 {items_total:,.2f} 与订单金额 {order_total:,.2f} 不一致。")
        else:
            st.caption(f"明细合计 {items_total:,.2f} {order['currency']}，与订单金额一致。")
    else:
        st.info("该订单没有商品明细。")

st.markdown("**关联包裹**")
if shipments:
    st.dataframe(
        [
            {
                "包裹号": shipment["shipment_id"],
                "承运商": shipment["carrier"],
                "运单号": shipment["tracking_number"],
                "物流状态": shipment["shipping_status_label"],
                "发货时间": shipment["shipped_at"] or "-",
                "预计送达": shipment["estimated_delivery_at"] or "-",
                "签收时间": shipment["delivered_at"] or "-",
            }
            for shipment in shipments
        ],
        width="stretch",
        hide_index=True,
    )
else:
    st.info("该订单暂无物流记录。")
