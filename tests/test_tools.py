import sqlite3

from ecommerce_assistant.db.init_db import init_db
from ecommerce_assistant.tools.database import query_inventory, query_logistics, query_order
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
    assert "未找到" not in result
    assert "SKU-001" in result
    assert "可用：22 件" in result
    assert "状态：正常" in result


def test_logistics_tool_lookup():
    result = get_logistics_status("1001")
    assert "1001" in result
    assert "物流" in result or "快递" in result


def test_query_order_returns_structured_result():
    result = query_order("1001")
    assert result["ok"] is True
    assert result["code"] == "OK"
    assert result["data"]["order_id"] == "1001"
    assert result["data"]["status"] == "shipped"


def test_query_order_missing_returns_not_found():
    result = query_order("NOT_FOUND")
    assert result["ok"] is False
    assert result["code"] == "NOT_FOUND"
    assert "不存在" in result["message"]


def test_query_inventory_returns_status_and_metrics():
    result = query_inventory("SKU-002")
    assert result["ok"] is True
    assert result["data"]["status"] == "out_of_stock"
    assert result["data"]["available"] == 0
    assert result["data"]["on_hand"] == 0


def test_query_logistics_returns_shipment_and_events():
    result = query_logistics(order_id="1001")
    assert result["ok"] is True
    assert result["data"]["shipment"]["order_id"] == "1001"
    assert result["data"]["events"]
    assert result["data"]["current_status"] in {"in_transit", "delivered", "pending"}


def test_query_logistics_not_found_returns_clear_message():
    result = query_logistics(order_id="999999")
    assert result["ok"] is False
    assert result["code"] == "NOT_FOUND"
    assert "物流" in result["message"] or "没有" in result["message"]


def test_rag_retriever_returns_source():
    result = retrieve_knowledge("退货需要满足什么条件")
    assert result["source"]
    assert "退货" in result["answer"] or "退换" in result["answer"]


def test_rag_retriever_reads_article_content_from_database(tmp_path):
    db_file = tmp_path / "knowledge.db"
    init_db(db_file)
    custom_content = "数据库中的最新退货政策：签收后 30 天内可申请。"
    with sqlite3.connect(db_file) as conn:
        conn.execute("DELETE FROM knowledge_articles WHERE slug = 'return-policy'")
        conn.execute(
            """
            INSERT INTO knowledge_articles (slug, category, title, content, source, updated_at)
            VALUES ('return-policy-db', 'returns', '数据库退货政策', ?, 'db://return-policy', '2099-01-01T00:00:00Z')
            """,
            (custom_content,),
        )
        conn.commit()

    result = retrieve_knowledge("退货需要满足什么条件", db_path=db_file)

    assert result["answer"] == custom_content
    assert result["source"] == "db://return-policy"
    assert result["sources"][0]["snippet"] == custom_content


def test_rag_retriever_does_not_use_hardcoded_article_when_database_has_no_article(tmp_path):
    db_file = tmp_path / "empty-knowledge.db"
    init_db(db_file)
    with sqlite3.connect(db_file) as conn:
        conn.execute("DELETE FROM knowledge_articles")
        conn.commit()

    result = retrieve_knowledge("退货需要满足什么条件", db_path=db_file)

    assert result["source"] == "未命中知识库"
    assert result["sources"] == []
