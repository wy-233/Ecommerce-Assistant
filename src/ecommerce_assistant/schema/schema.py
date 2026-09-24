from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ecommerce_assistant.llm.client import get_model_candidates
from ecommerce_assistant.schema.routes import ROUTE_UNKNOWN


class MessageRequest(BaseModel):
    message: str
    thread_id: str = "default-thread"
    user_id: str = "anonymous"
    model: str | None = None


class ToolCall(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    result: Any | None = None


class Source(BaseModel):
    doc: str
    snippet: str
    placeholder: bool | None = None


class ChatMessage(BaseModel):
    type: str = "ai"
    content: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    run_id: str = "run-001"
    intent: str | None = None
    route: str = ROUTE_UNKNOWN
    sources: list[Source] = Field(default_factory=list)


class InfoResponse(BaseModel):
    service: str = "ecommerce_assistant"
    agents: list[str] = Field(default_factory=lambda: ["ecommerce-assistant"])
    models: list[str] = Field(default_factory=get_model_candidates)
    base_url: str = os.getenv("OPENAI_BASE_URL", "https://aihub.top/v1")


class ModelListResponse(BaseModel):
    models: list[str] = Field(default_factory=list)
    default: str = ""
    source: str = "env"


class PaginationQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    search: str | None = None
    status: str | None = None
    country: str | None = None
    warehouse_id: str | None = None
    carrier: str | None = None


class OrderItem(BaseModel):
    id: int | None = None
    order_id: str
    sku: str
    product_name: str | None = None
    quantity: int
    unit_price: float
    currency: str = "CNY"


class ShipmentSummary(BaseModel):
    id: int | None = None
    shipment_id: str
    order_id: str
    carrier: str | None = None
    tracking_number: str | None = None
    shipping_status: str
    shipped_at: str | None = None
    estimated_delivery_at: str | None = None
    delivered_at: str | None = None
    updated_at: str | None = None


class OrderSummary(BaseModel):
    id: int | None = None
    order_id: str
    customer_name_masked: str | None = None
    customer_country: str | None = None
    order_status: str
    payment_status: str | None = None
    fulfillment_status: str | None = None
    currency: str | None = None
    total_amount: float | None = None
    created_at: str | None = None
    updated_at: str | None = None


class OrderDetailResponse(OrderSummary):
    items: list[OrderItem] = Field(default_factory=list)
    shipments: list[ShipmentSummary] = Field(default_factory=list)


class InventorySummary(BaseModel):
    id: int | None = None
    sku: str
    product_name: str | None = None
    warehouse_id: str | None = None
    warehouse_name: str | None = None
    on_hand: int = 0
    reserved: int = 0
    available: int = 0
    safety_stock: int = 0
    status: str = "normal"
    updated_at: str | None = None


class InventoryDetailResponse(InventorySummary):
    pass


class TrackingEvent(BaseModel):
    id: int | None = None
    shipment_id: str
    event_time: str | None = None
    event_status: str = "created"
    location: str | None = None
    description: str | None = None


class ShippingDetailResponse(BaseModel):
    id: int | None = None
    shipment_id: str
    order_id: str
    carrier: str | None = None
    tracking_number: str | None = None
    shipping_status: str
    shipped_at: str | None = None
    estimated_delivery_at: str | None = None
    delivered_at: str | None = None
    updated_at: str | None = None
    current_status: str | None = None
    events: list[TrackingEvent] = Field(default_factory=list)


class PaginatedItems(BaseModel):
    items: list[dict[str, object]] | list[OrderSummary] | list[InventorySummary] | list[ShipmentSummary]
    page: int
    page_size: int
    total: int

    model_config = ConfigDict(arbitrary_types_allowed=True)


class OrderListResponse(PaginatedItems):
    items: list[OrderSummary]


class InventoryListResponse(PaginatedItems):
    items: list[InventorySummary]


class ShipmentListResponse(PaginatedItems):
    items: list[ShipmentSummary]


class ShipmentEventListResponse(BaseModel):
    shipment_id: str
    current_status: str | None = None
    items: list[TrackingEvent] = Field(default_factory=list)


class DashboardRecentOrder(BaseModel):
    order_id: str
    customer_name_masked: str | None = None
    customer_country: str | None = None
    order_status: str
    payment_status: str | None = None
    total_amount: float | None = None
    created_at: str | None = None
    updated_at: str | None = None


class DashboardInventoryAlert(BaseModel):
    sku: str
    product_name: str | None = None
    warehouse_name: str | None = None
    available: int = 0
    safety_stock: int = 0
    status: str = "low_stock"
    updated_at: str | None = None


class DashboardShipmentAlert(BaseModel):
    shipment_id: str
    order_id: str
    carrier: str | None = None
    tracking_number: str | None = None
    shipping_status: str
    updated_at: str | None = None


class DashboardSummaryResponse(BaseModel):
    today_order_count: int = 0
    pending_order_count: int = 0
    pending_shipping_order_count: int = 0
    in_transit_shipment_count: int = 0
    low_stock_sku_count: int = 0
    shipment_exception_count: int = 0
    recent_orders: list[DashboardRecentOrder] = Field(default_factory=list)
    inventory_alerts: list[DashboardInventoryAlert] = Field(default_factory=list)
    shipment_alerts: list[DashboardShipmentAlert] = Field(default_factory=list)
    data_updated_at: str | None = None
