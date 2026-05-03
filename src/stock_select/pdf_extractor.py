"""PDF text extractor for announcement bodies.

Downloads PDFs from CNInfo/SSE/SZSE and extracts text content
for downstream keyword matching and evidence extraction.
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# CNInfo PDF base URL
_CNINFO_PDF_BASE = "http://static.cninfo.com.cn"

# Keyword patterns for event classification (reuse event_extraction patterns)
EVENT_KEYWORDS = {
    "重大合同": [r"合同", r"协议", r"中标", r"订单"],
    "业绩预告": [r"业绩", r"预告", r"盈利", r"亏损", r"增长"],
    "监管问询": [r"问询", r"监管", r"关注函", r"调查"],
    "股权变动": [r"股权", r"增持", r"减持", r"转让"],
    "停复牌": [r"停牌", r"复牌", r"暂停上市"],
    "分红配股": [r"分红", r"派息", r"配股", r"送股"],
    "诉讼仲裁": [r"诉讼", r"仲裁", r"纠纷", r"判决"],
    "政策利好": [r"政策", r"补贴", r"扶持", r"优惠"],
    "风险事件": [r"风险", r"违规", r"处罚", r"警示"],
    "资产重组": [r"重组", r"并购", r"收购", r"合并"],
    "人事变动": [r"董事", r"监事", r"高管", r"辞职", r"聘任"],
}


def download_pdf(url: str) -> bytes | None:
    """Download PDF from given URL. Handles CNInfo relative URLs."""
    if not url:
        return None
    full_url = url if url.startswith("http") else f"{_CNINFO_PDF_BASE}{url}"
    try:
        req = urllib.request.Request(full_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except Exception as exc:
        logger.debug("Failed to download PDF: %s", exc)
        return None


def extract_text_from_pdf(pdf_bytes: bytes) -> str | None:
    """Extract text from PDF bytes using available library."""
    # Try PyMuPDF (fitz) first
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        return text
    except ImportError:
        pass
    except Exception:
        pass

    # Try pdfplumber
    try:
        import io
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except ImportError:
        pass
    except Exception:
        pass

    # Try pypdf
    try:
        import io
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except ImportError:
        pass
    except Exception:
        pass

    return None


def extract_and_store_announcement_text(
    conn: sqlite3.Connection,
    document_id: str,
    source_url: str,
    *,
    limit: int = 20,
) -> str | None:
    """Download PDF, extract text, update raw_documents.content_text.

    Returns the extracted text or None if extraction failed.
    """
    pdf_bytes = download_pdf(source_url)
    if pdf_bytes is None:
        return None

    text = extract_text_from_pdf(pdf_bytes)
    if text:
        conn.execute(
            "UPDATE raw_documents SET content_text = ? WHERE document_id = ?",
            (text, document_id),
        )
        conn.commit()
    return text


def classify_announcement_text(text: str) -> list[dict[str, Any]]:
    """Classify announcement text into event types using keyword matching.

    Returns list of {event_type, matched_keywords, confidence}.
    """
    results = []
    for event_type, patterns in EVENT_KEYWORDS.items():
        matches = []
        for pattern in patterns:
            if re.search(pattern, text):
                matches.append(pattern)
        if matches:
            confidence = min(0.95, 0.5 + len(matches) * 0.15)
            results.append({
                "event_type": event_type,
                "matched_keywords": matches,
                "confidence": round(confidence, 2),
            })
    results.sort(key=lambda x: x["confidence"], reverse=True)
    return results


def process_pending_announcements(
    conn: sqlite3.Connection,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Find announcements without content_text, download and extract.

    Returns list of processed items with classification results.
    """
    rows = conn.execute(
        """
        SELECT document_id, source_url, title
        FROM raw_documents
        WHERE source_type = 'official_announcement'
          AND (content_text IS NULL OR content_text = '')
          AND source_url IS NOT NULL AND source_url != ''
        ORDER BY published_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    results = []
    for row in rows:
        text = extract_and_store_announcement_text(
            conn, row["document_id"], row["source_url"]
        )
        if text:
            classifications = classify_announcement_text(text)
            results.append({
                "document_id": row["document_id"],
                "title": row["title"],
                "text_length": len(text),
                "classifications": classifications,
            })

    return results
