"""Graphify-compatible JSON export and offline pipeline runner."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .entity_linker import link_and_store
from .event_extraction import classify_event
from .graph import (
    CONFIDENCE_EXTRACTED,
    CONFIDENCE_INFERRED,
    detect_communities,
    export_graphify_json,
    sync_document_graph,
    store_communities,
)
from .news_providers import query_documents


def process_documents(
    conn: sqlite3.Connection,
    date: str,
    stock_code: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """Process raw documents: link entities, classify events, build graph edges."""
    docs = query_documents(
        conn,
        date=date,
        stock_code=stock_code,
        limit=limit,
    )

    stats = {"processed": 0, "linked": 0, "edges_created": 0}

    for doc in docs:
        doc_id = doc["document_id"]
        text = (doc.get("summary") or "") + " " + (doc.get("content_text") or "")
        title = doc.get("title", "")
        existing_codes = json.loads(doc.get("related_stock_codes_json") or "[]")

        # Entity linking
        linked_codes = link_and_store(
            conn, doc_id, text, title, existing_codes=existing_codes
        )
        if len(linked_codes) > len(existing_codes):
            stats["linked"] += len(linked_codes) - len(existing_codes)

        # Event classification
        event_type, event_confidence = classify_event(title, doc.get("summary"))

        # Graph sync
        confidence = CONFIDENCE_EXTRACTED if event_confidence > 0.7 else CONFIDENCE_INFERRED
        result = sync_document_graph(
            conn,
            document_id=doc_id,
            source=doc["source"],
            source_type=doc["source_type"],
            title=title,
            stock_codes=linked_codes,
            event_type=event_type,
            confidence=confidence,
            as_of_date=doc.get("published_at"),
        )
        stats["edges_created"] += result.get("edges", 0)
        stats["processed"] += 1

    # Community detection
    communities = detect_communities(conn, trading_date=date)
    stored = store_communities(conn, communities)
    stats["communities"] = stored

    conn.commit()
    return stats


def export_for_date(
    conn: sqlite3.Connection,
    date: str,
    output_dir: str = "var/graphify",
) -> str:
    """Export graph for a specific date to Graphify-compatible JSON."""
    out_path = Path(output_dir) / date / "graphify-out" / "graph.json"
    return export_graphify_json(conn, str(out_path))
