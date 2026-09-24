"""状态码与中文展示名的唯一映射来源。

数据库统一存英文码（见 docs/PRD.md 的状态口径），页面、工具自然语言输出、
API 响应在展示前统一经此模块转中文，避免出现第二套词表。
"""

from __future__ import annotations

ORDER_STATUS_LABELS: dict[str, str] = {
    "pending_payment": "待付款",
    "paid": "已付款",
    "processing": "处理中",
    "shipped": "已发货",
    "delivered": "已送达",
    "cancelled": "已取消",
    "refund_requested": "退款申请中",
}

PAYMENT_STATUS_LABELS: dict[str, str] = {
    "unpaid": "未付款",
    "paid": "已付款",
    "refunded": "已退款",
    "partially_refunded": "部分退款",
}

FULFILLMENT_STATUS_LABELS: dict[str, str] = {
    "pending": "待履约",
    "processing": "履约中",
    "partial": "部分发货",
    "fulfilled": "已履约",
    "cancelled": "已取消",
    "held": "已挂起",
}

SHIPPING_STATUS_LABELS: dict[str, str] = {
    "pending": "待发货",
    "shipped": "已发货",
    "in_transit": "运输中",
    "out_for_delivery": "派送中",
    "delivered": "已签收",
    "exception": "物流异常",
}

INVENTORY_STATUS_LABELS: dict[str, str] = {
    "normal": "正常",
    "low_stock": "库存不足",
    "out_of_stock": "缺货",
}

COUNTRY_LABELS: dict[str, str] = {
    "cn": "中国",
    "hk": "中国香港",
    "mo": "中国澳门",
    "tw": "中国台湾",
    "us": "美国",
    "gb": "英国",
    "de": "德国",
    "fr": "法国",
    "nl": "荷兰",
    "es": "西班牙",
    "it": "意大利",
    "au": "澳大利亚",
    "ca": "加拿大",
    "jp": "日本",
    "kr": "韩国",
    "sg": "新加坡",
    "my": "马来西亚",
    "th": "泰国",
    "id": "印度尼西亚",
    "br": "巴西",
}

ORDER_STATUS_CODES = tuple(ORDER_STATUS_LABELS)
PAYMENT_STATUS_CODES = tuple(PAYMENT_STATUS_LABELS)
FULFILLMENT_STATUS_CODES = tuple(FULFILLMENT_STATUS_LABELS)
SHIPPING_STATUS_CODES = tuple(SHIPPING_STATUS_LABELS)
INVENTORY_STATUS_CODES = tuple(INVENTORY_STATUS_LABELS)


def label_of(labels: dict[str, str], code: str | None) -> str:
    """把状态码转成中文；未知码原样返回，便于暴露数据问题而非静默吞掉。"""
    if code is None or not str(code).strip():
        return "未知"
    normalized = str(code).strip().lower()
    return labels.get(normalized, str(code))
