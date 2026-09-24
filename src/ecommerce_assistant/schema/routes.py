from __future__ import annotations

# 意图路由结果（route）。枚举与 design/FRONTEND-SPEC.md §6.1、docs/PRD.md v0.2 §6.7.1 一致。
# 语义：
#   after   售后 / 商品 —— 知识库命中，或 LLM 直接作答
#   order   订单
#   stock   库存
#   ship    物流
#   unknown 既未调用业务工具、也未走模型（本地会话记忆回答、知识库未命中）
# 前端据 route 决定分拣带计数、道口高亮与配色，**不得自行推断**。
ROUTE_AFTER = "after"
ROUTE_ORDER = "order"
ROUTE_STOCK = "stock"
ROUTE_SHIP = "ship"
ROUTE_UNKNOWN = "unknown"

ROUTES = (ROUTE_AFTER, ROUTE_ORDER, ROUTE_STOCK, ROUTE_SHIP, ROUTE_UNKNOWN)

# route -> tool_calls[].name。unknown 与 after 不产生工具调用：
# after 的来源走 sources，unknown 不调用任何工具。
TOOL_CALL_NAMES = {
    ROUTE_ORDER: "order_lookup",
    ROUTE_STOCK: "stock_lookup",
    ROUTE_SHIP: "shipping_lookup",
}
