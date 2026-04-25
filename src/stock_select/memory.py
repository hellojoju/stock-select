from __future__ import annotations

import sqlite3
from typing import Any

from . import repository


def add_memory(
    conn: sqlite3.Connection,
    *,
    content: str,
    trading_date: str | None,
    source_type: str,
    source_id: str,
) -> None:
    repository.insert_memory(
        conn,
        content=content,
        trading_date=trading_date,
        source_type=source_type,
        source_id=source_id,
    )
    conn.commit()


def search_memory(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[dict[str, Any]]:
    try:
        rows = conn.execute(
            """
            SELECT rowid, content, trading_date, source_type, source_id,
                   bm25(memory_fts) AS rank
            FROM memory_fts
            WHERE memory_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (build_fts_query(query), limit),
        ).fetchall()
        return [
            {
                "rowid": row["rowid"],
                "content": row["content"],
                "trading_date": row["trading_date"],
                "source_type": row["source_type"],
                "source_id": row["source_id"],
                "score": 1 / (1 + max(0, float(row["rank"]))),
            }
            for row in rows
        ]
    except sqlite3.OperationalError:
        rows = conn.execute(
            """
            SELECT rowid, content, trading_date, source_type, source_id
            FROM memory_fts_fallback
            WHERE content LIKE ?
            LIMIT ?
            """,
            (f"%{query}%", limit),
        ).fetchall()
        return [dict(row) | {"score": 0.5} for row in rows]


def build_fts_query(query: str) -> str:
    tokens = [token for token in query.replace('"', " ").split() if token]
    if not tokens:
        return '""'
    return " OR ".join(f'"{token}"' for token in tokens)

