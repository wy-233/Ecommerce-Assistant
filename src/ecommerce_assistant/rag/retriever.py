"""基于 ``knowledge_articles`` 表的轻量知识库检索。"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from ecommerce_assistant.db.init_db import DEFAULT_DB_PATH, connect, init_db


MISS_ANSWER = (
    "这个问题不在售后、订单、库存、物流的处理范围内，没有调用任何工具。\n\n"
    "可以换个问法，例如：退货要满足什么条件、某个订单号现在到哪里了、"
    "SKU-001 还有多少库存、订单用了哪家物流。"
)


def _category_for_query(query: str) -> str | None:
    q = (query or "").lower()
    if any(keyword in q for keyword in ("退货", "退款", "退换")):
        return "returns"
    if any(keyword in q for keyword in ("物流", "快递", "配送", "运输")):
        return "shipping"
    return None


def _query_articles(category: str, query: str, db_path: str | Path | None) -> list[dict[str, Any]]:
    target = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    # 直接调用检索函数时保证目标库有 schema；应用 lifespan 负责播种。
    init_db(target)
    with connect(target) as conn:
        rows = conn.execute(
            """
            SELECT slug, category, title, content, source, updated_at
            FROM knowledge_articles
            WHERE category = ?
            ORDER BY updated_at DESC, id DESC
            """,
            (category,),
        ).fetchall()

    articles = [dict(row) for row in rows]
    if not articles:
        return []

    # 同一分类允许多篇文章，优先返回与问题词面重合最多的数据库文章。
    tokens = [
        token
        for token in re.findall(r"[\w\u4e00-\u9fff]+", (query or "").lower())
        if len(token) > 1
    ]

    def score(article: dict[str, Any]) -> tuple[int, str]:
        haystack = " ".join(
            str(article.get(field) or "").lower()
            for field in ("slug", "title", "content")
        )
        return (sum(token in haystack for token in tokens), str(article.get("updated_at") or ""))

    return sorted(articles, key=score, reverse=True)


def _article_result(article: dict[str, Any]) -> dict[str, Any]:
    source = str(article.get("source") or article.get("slug") or "knowledge_articles")
    content = str(article.get("content") or "")
    return {
        "answer": content,
        "source": source,
        "sources": [
            {
                "doc": source,
                "snippet": content,
                # 保留现有前端契约；当前知识文章是本地演示政策文本。
                "placeholder": True,
            }
        ],
    }


def retrieve_knowledge(query: str, db_path: str | Path | None = None) -> dict[str, Any]:
    """从 ``knowledge_articles`` 查询政策文章，返回 ``answer/source/sources``。"""
    category = _category_for_query(query)
    if category is None:
        return {"answer": MISS_ANSWER, "source": "未命中知识库", "sources": []}

    try:
        articles = _query_articles(category, query, db_path)
    except sqlite3.Error:
        articles = []

    if not articles:
        return {"answer": MISS_ANSWER, "source": "未命中知识库", "sources": []}
    return _article_result(articles[0])
