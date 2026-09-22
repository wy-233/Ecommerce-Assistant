from __future__ import annotations

from pathlib import Path

DOCS = {
    "return_policy": {
        "source": "data/return_policy.md",
        "content": "退货需要满足以下条件：商品在签收后 7 天内申请，商品未使用、未损坏且附带原包装；特殊定制产品不支持退货；已使用、破损、清洗过的商品不享受退货；在保质期内可申请维修或更换。",
    },
    "shipping_policy": {
        "source": "data/shipping_policy.md",
        "content": "物流配送时效通常为 3-7 个工作日，海外订单可能因清关而延迟；物流状态可在订单详情中查看。",
    },
}


def retrieve_knowledge(query: str) -> dict:
    q = (query or "").lower()
    if "退货" in q or "退款" in q or "退换" in q:
        doc = DOCS["return_policy"]
        return {"answer": doc["content"], "source": doc["source"]}
    if "物流" in q or "快递" in q or "配送" in q or "运输" in q:
        doc = DOCS["shipping_policy"]
        return {"answer": doc["content"], "source": doc["source"]}
    fallback = DOCS["return_policy"]
    return {"answer": fallback["content"], "source": fallback["source"]}
