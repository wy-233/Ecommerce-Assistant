from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ecommerce_assistant.db.init_db import DEFAULT_DB_PATH, init_db


class ChatThreadDAO:
    """SQLite-backed DAO for chat threads and messages."""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
        init_db(self.db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def ensure_thread(self, thread_id: str, user_id: str | None = None) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO chat_threads (thread_id, user_id, created_at, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (str(thread_id), str(user_id) if user_id is not None else None),
            )
            if user_id is not None:
                conn.execute(
                    "UPDATE chat_threads SET user_id = ?, updated_at = CURRENT_TIMESTAMP WHERE thread_id = ?",
                    (str(user_id), str(thread_id)),
                )
            conn.commit()
        finally:
            conn.close()

    def append_message(self, thread_id: str, role: str, content: str, user_id: str | None = None) -> None:
        conn = self._connect()
        try:
            self.ensure_thread(thread_id, user_id=user_id)
            conn.execute(
                """
                INSERT INTO chat_messages (thread_id, role, content, created_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (str(thread_id), str(role), str(content)),
            )
            conn.execute(
                "UPDATE chat_threads SET updated_at = CURRENT_TIMESTAMP WHERE thread_id = ?",
                (str(thread_id),),
            )
            conn.commit()
        finally:
            conn.close()

    def get_history(self, thread_id: str, limit: int = 12) -> list[dict[str, str]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT role, content
                FROM chat_messages
                WHERE thread_id = ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (str(thread_id), int(limit)),
            ).fetchall()
            return [{"role": row["role"], "content": row["content"]} for row in rows]
        finally:
            conn.close()

    def list_threads(self, user_id: str | None = None) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            if user_id is None:
                rows = conn.execute(
                    "SELECT thread_id, user_id, created_at, updated_at FROM chat_threads ORDER BY updated_at DESC"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT thread_id, user_id, created_at, updated_at FROM chat_threads WHERE user_id = ? ORDER BY updated_at DESC",
                    (str(user_id),),
                ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def delete_thread(self, thread_id: str) -> int:
        conn = self._connect()
        try:
            deleted_messages = conn.execute(
                "DELETE FROM chat_messages WHERE thread_id = ?",
                (str(thread_id),),
            ).rowcount
            deleted_threads = conn.execute(
                "DELETE FROM chat_threads WHERE thread_id = ?",
                (str(thread_id),),
            ).rowcount
            conn.commit()
            return int(deleted_messages + deleted_threads)
        finally:
            conn.close()

    def clear_user_threads(self, user_id: str) -> int:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT thread_id FROM chat_threads WHERE user_id = ?",
                (str(user_id),),
            ).fetchall()
            removed = 0
            for row in rows:
                removed += self.delete_thread(row["thread_id"])
            conn.commit()
            return removed
        finally:
            conn.close()
