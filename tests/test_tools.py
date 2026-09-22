from ecommerce_assistant.tools.inventory import get_inventory_status
from ecommerce_assistant.tools.logistics import get_logistics_status
from ecommerce_assistant.tools.order import get_order_status
from ecommerce_assistant.rag.retriever import retrieve_knowledge


def test_order_tool_lookup():
    result = get_order_status("1001")
    assert "1001" in result
    assert "运输中" in result or "已发货" in result


def test_inventory_tool_lookup():
    result = get_inventory_status("SKU-001")
    assert "SKU-001" in result
    assert "库存" in result


def test_logistics_tool_lookup():
    result = get_logistics_status("1001")
    assert "1001" in result
    assert "物流" in result or "快递" in result


def test_rag_retriever_returns_source():
    result = retrieve_knowledge("退货需要满足什么条件")
    assert result["source"]
    assert "退货" in result["answer"] or "退换" in result["answer"]
