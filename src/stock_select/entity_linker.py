"""Deterministic entity linking: stock codes, company names, industries."""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

_STOCK_CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")


@dataclass
class LinkedEntity:
    entity_type: str  # Stock | Industry | Theme
    canonical_name: str
    stock_code: str | None
    confidence: float
    evidence_text: str


def link_entities(
    conn: sqlite3.Connection,
    text: str,
    title: str = "",
) -> list[LinkedEntity]:
    """Link mentions in text to known stocks, industries, and themes."""
    entities: list[LinkedEntity] = []
    search_text = f"{title} {text}"

    # 1. Direct stock code matches
    for code in _STOCK_CODE_RE.findall(search_text):
        row = conn.execute(
            "SELECT stock_code, name, industry FROM stocks WHERE stock_code = ?",
            (code,),
        ).fetchone()
        if row:
            entities.append(LinkedEntity(
                entity_type="Stock",
                canonical_name=row["name"],
                stock_code=row["stock_code"],
                confidence=0.95,
                evidence_text=f"代码 {code}",
            ))

    # 2. Company name fuzzy match
    all_stocks = conn.execute("SELECT stock_code, name FROM stocks").fetchall()
    for row in all_stocks:
        name = row["name"]
        if len(name) >= 3 and name in search_text:
            # Check it's not already linked by code
            if not any(e.stock_code == row["stock_code"] for e in entities):
                entities.append(LinkedEntity(
                    entity_type="Stock",
                    canonical_name=name,
                    stock_code=row["stock_code"],
                    confidence=0.8,
                    evidence_text=f"名称匹配: {name}",
                ))

    # 3. Industry matches
    industries = conn.execute(
        "SELECT DISTINCT industry FROM stocks WHERE industry IS NOT NULL AND industry != ''"
    ).fetchall()
    for row in industries:
        ind = row["industry"]
        if ind and len(ind) >= 2 and ind in search_text:
            entities.append(LinkedEntity(
                entity_type="Industry",
                canonical_name=ind,
                stock_code=None,
                confidence=0.7,
                evidence_text=f"行业: {ind}",
            ))

    return entities


def link_and_store(
    conn: sqlite3.Connection,
    document_id: str,
    text: str,
    title: str = "",
    existing_codes: list[str] | None = None,
) -> list[str]:
    """Link entities and update document_stock_links. Returns linked stock codes."""
    entities = link_entities(conn, text, title)
    codes: list[str] = list(existing_codes or [])

    for entity in entities:
        if entity.stock_code and entity.stock_code not in codes:
            codes.append(entity.stock_code)
            conn.execute(
                """
                INSERT OR IGNORE INTO document_stock_links(
                  document_id, stock_code, relation_type, confidence, evidence_text
                ) VALUES (?, ?, 'mentioned', ?, ?)
                """,
                (document_id, entity.stock_code, entity.confidence, entity.evidence_text),
            )

    return codes
