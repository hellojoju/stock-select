"""News and announcement source adapters."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class RawDocumentItem:
    source: str
    source_type: str  # official_announcement | finance_news | research_note | manual_import
    source_url: str
    title: str
    summary: str | None
    content_text: str | None
    published_at: str | None
    captured_at: str
    related_stock_codes: list[str] = field(default_factory=list)
    related_industries: list[str] = field(default_factory=list)
    author: str | None = None
    license_status: str = "unknown"
    visibility: str = "preopen"  # preopen / postclose / postdecision
    raw_path: str | None = None
    event_category: str | None = None  # earnings | regulatory | risk | contract | management | other

    @property
    def document_id(self) -> str:
        raw = f"{self.source}:{self.source_url}:{self.title}"
        return "doc_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    @property
    def content_hash(self) -> str:
        text = self.content_text or self.summary or self.title
        return hashlib.md5(text.encode("utf-8")).hexdigest()


# S3.5: Keyword-based event classification for titles and summaries
_EVENT_CATEGORIES = [
    ("earnings", ["业绩", "财报", "净利润", "营收", "盈利", "亏损", "每股收益", "季报", "年报", "中报", "pre-announcement"]),
    ("regulatory", ["监管", "问询", "处罚", "罚款", "立案调查", "违规", "纪律处分", "证监会", "交易所"]),
    ("risk", ["风险", "退市", "减持", "质押", "诉讼", "仲裁", "担保", "违约", "ST", "退市风险"]),
    ("contract", ["合同", "订单", "中标", "签约", "合作", "协议", "采购", "出售", "资产"]),
    ("management", ["董事", "监事", "高管", "辞职", "增持", "减持", "股权变更", "重组", "并购"]),
    ("dividend", ["分红", "派息", "股息", "股利", "利润分配", "转增"]),
    ("issuance", ["增发", "配股", "发债", "定增", "IPO", "上市"]),
]


def classify_event(title: str, summary: str | None = None) -> str:
    """Classify document into event category based on title/summary keywords."""
    text = (title + " " + (summary or "")).lower()
    scores: dict[str, int] = {}
    for category, keywords in _EVENT_CATEGORIES:
        for kw in keywords:
            if kw in text:
                scores[category] = scores.get(category, 0) + 1
    if not scores:
        return "other"
    return max(scores, key=scores.get)  # type: ignore[arg-type]


def store_document(conn: sqlite3.Connection, item: RawDocumentItem) -> str:
    """Store a RawDocumentItem into raw_documents and document_stock_links."""
    doc_id = item.document_id
    # Auto-classify event category if not already set
    event_cat = item.event_category or classify_event(item.title, item.summary)

    conn.execute(
        """
        INSERT OR IGNORE INTO raw_documents(
          document_id, source, source_type, source_url, title, summary,
          content_text, content_hash, published_at, captured_at,
          author, related_stock_codes_json, related_industries_json,
          language, license_status, fetch_status, raw_path, event_category
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            doc_id,
            item.source,
            item.source_type,
            item.source_url,
            item.title,
            item.summary,
            item.content_text,
            item.content_hash,
            item.published_at,
            item.captured_at,
            item.author,
            json.dumps(item.related_stock_codes, ensure_ascii=False),
            json.dumps(item.related_industries, ensure_ascii=False),
            "zh",
            item.license_status,
            "ok",
            item.raw_path,
            event_cat,
        ),
    )

    for stock_code in item.related_stock_codes:
        conn.execute(
            """
            INSERT OR IGNORE INTO document_stock_links(
              document_id, stock_code, relation_type, confidence, evidence_text
            ) VALUES (?, ?, 'mentioned', 0.8, ?)
            """,
            (doc_id, stock_code, item.title[:120]),
        )

    try:
        _ensure_documents_fts(conn)
        conn.execute(
            "INSERT INTO documents_fts(title, summary, content_text, document_id) VALUES (?, ?, ?, ?)",
            (
                item.title,
                item.summary or "",
                item.content_text or "",
                doc_id,
            ),
        )
    except sqlite3.Error as exc:
        conn.execute(
            "UPDATE raw_documents SET fetch_status = ? WHERE document_id = ?",
            ("index_error", doc_id),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO document_fetch_logs(
              log_id, source, status, records_fetched, records_stored, error_message, raw_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"fts_{doc_id}",
                item.source,
                "error",
                1,
                0,
                str(exc),
                item.source_url,
            ),
        )
        raise RuntimeError(f"documents_fts indexing failed for {doc_id}: {exc}") from exc

    return doc_id


def _ensure_documents_fts(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
          title,
          summary,
          content_text,
          document_id UNINDEXED,
          tokenize='unicode61'
        )
        """
    )


def query_documents(
    conn: sqlite3.Connection,
    *,
    date: str | None = None,
    stock_code: str | None = None,
    source_type: str | None = None,
    keyword: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Query documents with optional filters.

    Supports full-text search, date, stock, source_type, and keyword filters.
    When stock_code is provided, filters to documents linked to that stock.
    When omitted, returns all documents with their linked stocks via GROUP_CONCAT.
    """
    conditions: list[str] = []
    params: list[Any] = []

    if date:
        conditions.append("(r.published_at = ? OR DATE(r.captured_at) = ?)")
        params.extend([date, date])

    if stock_code:
        conditions.append("dsl.stock_code = ?")
        params.append(stock_code)

    if source_type:
        conditions.append("r.source_type = ?")
        params.append(source_type)

    if keyword:
        conditions.append("(r.title LIKE ? OR r.summary LIKE ? OR r.content_text LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"])

    query = f"""
        SELECT r.document_id, r.source, r.source_type, r.source_url, r.title,
               r.summary, r.content_text, r.content_hash, r.published_at,
               r.captured_at, r.author, r.language, r.license_status,
               r.fetch_status, r.raw_path,
               r.related_stock_codes_json, r.related_industries_json,
               GROUP_CONCAT(DISTINCT dsl.stock_code) AS linked_stock_codes,
               GROUP_CONCAT(DISTINCT dsl.relation_type) AS linked_relations,
               MAX(dsl.confidence) AS max_link_confidence
        FROM raw_documents r
        LEFT JOIN document_stock_links dsl ON r.document_id = dsl.document_id
        {'WHERE ' + ' AND '.join(conditions) if conditions else ''}
        GROUP BY r.document_id
        ORDER BY r.published_at DESC, r.captured_at DESC
        LIMIT ?
    """
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def search_documents_fts(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Search documents using FTS5."""
    rows = conn.execute(
        """
        SELECT r.*, snippets(fts, 0, '[', ']', '...', 20) as title_snippet,
               snippets(fts, 1, '[', ']', '...', 20) as summary_snippet
        FROM documents_fts fts
        JOIN raw_documents r ON r.document_id = fts.document_id
        WHERE fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (query, limit),
    ).fetchall()
    return [dict(row) for row in rows]
