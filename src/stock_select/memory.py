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


def search_documents(
    conn: sqlite3.Connection,
    *,
    query: str | None = None,
    stock_code: str | None = None,
    source_type: str | None = None,
    date: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Search raw_documents via FTS5 with optional filters.

    Falls back to LIKE-based search if FTS5 is unavailable.
    """
    conditions: list[str] = []
    params: list[Any] = []

    if stock_code:
        conditions.append("dsl.stock_code = ?")
        params.append(stock_code)

    if source_type:
        conditions.append("r.source_type = ?")
        params.append(source_type)

    if date:
        conditions.append("(r.published_at = ? OR DATE(r.captured_at) = ?)")
        params.extend([date, date])

    join_clause = ""
    if stock_code:
        join_clause = "JOIN document_stock_links dsl ON r.document_id = dsl.document_id"

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    # Try FTS5 first
    if query:
        fts_query = build_fts_query(query)
        try:
            rows = conn.execute(
                f"""
                SELECT r.document_id, r.source, r.source_type, r.source_url,
                       r.title, r.summary, r.published_at, r.captured_at,
                       r.author, r.related_stock_codes_json,
                       snippets(fts, 0, '[', ']', '...', 20) as title_snippet,
                       snippets(fts, 1, '[', ']', '...', 20) as summary_snippet,
                       rank
                FROM documents_fts fts
                JOIN raw_documents r ON r.document_id = fts.document_id
                {join_clause}
                {where_clause}
                  AND fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (*params, fts_query, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            pass

    # Fallback: LIKE-based search
    like_clause = ""
    if query:
        like_clause = f"AND (r.title LIKE ? OR r.summary LIKE ? OR r.content_text LIKE ?)"
        params.extend([f"%{query}%", f"%{query}%", f"%{query}%"])

    rows = conn.execute(
        f"""
        SELECT r.document_id, r.source, r.source_type, r.source_url,
               r.title, r.summary, r.published_at, r.captured_at,
               r.author, r.related_stock_codes_json
        FROM raw_documents r
        {join_clause}
        {where_clause} {like_clause}
        ORDER BY r.published_at DESC, r.captured_at DESC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    return [dict(r) for r in rows]

