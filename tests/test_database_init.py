import sqlite3

from ecommerce_assistant.db.init_db import init_db


def test_init_db_creates_expected_tables(tmp_path):
    db_file = tmp_path / "ecommerce_assistant.db"

    init_db(str(db_file))

    with sqlite3.connect(db_file) as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()

    actual = {name for (name,) in tables}
    expected = {
        "orders",
        "inventory",
        "shipments",
        "tracking_events",
        "chat_threads",
        "chat_messages",
        "knowledge_articles",
    }

    assert expected.issubset(actual)
