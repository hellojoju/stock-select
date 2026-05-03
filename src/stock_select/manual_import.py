"""Manual document import: CSV, Markdown, HTML, PDF -> raw_documents."""
from __future__ import annotations

import csv
import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import connect as db_connect
from .news_providers import RawDocumentItem, store_document

_DATE_RE = re.compile(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})")
_STOCK_CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")


def _detect_date(text: str, default: str | None) -> str | None:
    if default:
        return default
    m = _DATE_RE.search(text or "")
    if m:
        return m.group(1).replace("/", "-")
    return None


def _detect_stock_codes(text: str, default: str | None) -> list[str]:
    codes = _STOCK_CODE_RE.findall(text or "")
    if default:
        codes.insert(0, default)
    return list(dict.fromkeys(codes))


def _read_text_file(path: Path) -> str:
    for encoding in ("utf-8", "gbk", "gb2312", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except (UnicodeDecodeError, ValueError):
            continue
    return ""


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _read_pdf_text(path: Path) -> str:
    """Try to extract text from PDF using available tools."""
    # Try PyMuPDF first
    try:
        import fitz
        doc = fitz.open(str(path))
        texts = [page.get_text() for page in doc]
        doc.close()
        return "\n".join(texts)
    except ImportError:
        pass
    # Try pdfplumber
    try:
        import pdfplumber
        text_parts = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    text_parts.append(t)
        return "\n".join(text_parts)
    except ImportError:
        pass
    # Try pypdf
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except ImportError:
        pass
    return ""


def _parse_csv(path: Path, default_date: str | None, default_stock: str | None) -> list[RawDocumentItem]:
    """Parse CSV where each row is a document."""
    items: list[RawDocumentItem] = []
    text = _read_text_file(path)
    if not text:
        return items
    lines = text.splitlines()
    if not lines:
        return items

    # Detect delimiter
    dialect = csv.Sniffer().sniff(lines[0] if lines else "", delimiters=",;\t|")
    delimiter = dialect.delimiter

    reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
    for row in reader:
        title = row.get("title", row.get("标题", row.get("Title", "")))
        if not title:
            continue
        content = row.get("content", row.get("content_text", row.get("正文", row.get("Content", ""))))
        summary = row.get("summary", row.get("摘要", "")) or None
        if not summary and content:
            summary = content[:200]
        url = row.get("url", row.get("source_url", row.get("URL", row.get("链接", ""))))
        date = _detect_date(title + " " + (content or ""), row.get("date", row.get("日期", default_date)))
        stock_codes = _detect_stock_codes(
            title + " " + (content or ""),
            row.get("stock_code", row.get("股票代码", default_stock)),
        )

        items.append(RawDocumentItem(
            source="manual_import",
            source_type="manual_import",
            source_url=url,
            title=title.strip(),
            summary=summary,
            content_text=content.strip() if content else None,
            published_at=date,
            captured_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            related_stock_codes=stock_codes,
            related_industries=[],
            author=row.get("author", row.get("作者")),
            license_status="manual",
            visibility="preopen",
            raw_path=str(path),
        ))
    return items


def _parse_markdown(path: Path, default_date: str | None, default_stock: str | None) -> list[RawDocumentItem]:
    """Parse a Markdown file: H1 = title, rest = content, first date/code found."""
    text = _read_text_file(path)
    if not text:
        return []
    lines = text.splitlines()
    title = ""
    content_lines: list[str] = []
    for line in lines:
        if not title and line.startswith("# "):
            title = line[2:].strip()
            continue
        content_lines.append(line)
    if not title:
        title = path.stem
    content = "\n".join(content_lines).strip()
    date = _detect_date(text, default_date)
    stock_codes = _detect_stock_codes(text, default_stock)

    return [RawDocumentItem(
        source="manual_import",
        source_type="manual_import",
        source_url="",
        title=title,
        summary=content[:200] if content else None,
        content_text=content or None,
        published_at=date,
        captured_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        related_stock_codes=stock_codes,
        related_industries=[],
        author=None,
        license_status="manual",
        visibility="preopen",
        raw_path=str(path),
    )]


def _parse_html(path: Path, default_date: str | None, default_stock: str | None) -> list[RawDocumentItem]:
    """Parse HTML: <title> or <h1> = title, <body> text = content."""
    text = _read_text_file(path)
    if not text:
        return []
    # Try to extract title
    title_m = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
    if not title_m:
        title_m = re.search(r"<h1[^>]*>(.*?)</h1>", text, re.IGNORECASE | re.DOTALL)
    title = _strip_html(title_m.group(1)) if title_m else path.stem
    content = _strip_html(text)
    date = _detect_date(text, default_date)
    stock_codes = _detect_stock_codes(text, default_stock)

    return [RawDocumentItem(
        source="manual_import",
        source_type="manual_import",
        source_url="",
        title=title,
        summary=content[:200] if content else None,
        content_text=content or None,
        published_at=date,
        captured_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        related_stock_codes=stock_codes,
        related_industries=[],
        author=None,
        license_status="manual",
        visibility="preopen",
        raw_path=str(path),
    )]


def _parse_pdf(path: Path, default_date: str | None, default_stock: str | None) -> list[RawDocumentItem]:
    """Parse PDF: extract text, H1 = title, rest = content."""
    text = _read_pdf_text(path)
    if not text:
        return []
    lines = text.splitlines()
    title = lines[0].strip() if lines else path.stem
    date = _detect_date(text, default_date)
    stock_codes = _detect_stock_codes(text, default_stock)

    return [RawDocumentItem(
        source="manual_import",
        source_type="manual_import",
        source_url="",
        title=title,
        summary=text[:200] if text else None,
        content_text=text or None,
        published_at=date,
        captured_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        related_stock_codes=stock_codes,
        related_industries=[],
        author=None,
        license_status="manual",
        visibility="preopen",
        raw_path=str(path),
    )]


def import_documents(
    conn: Any,
    paths: list[str],
    source: str = "manual_import",
    default_date: str | None = None,
    default_stock_code: str | None = None,
) -> dict[str, Any]:
    """Import documents from given paths into raw_documents.

    Supports .csv, .md, .html, .htm, .pdf files and directories.
    Returns {imported: int, failed: int, details: [...]}.
    """
    imported = 0
    failed = 0
    details: list[dict[str, str]] = []

    for path_str in paths:
        path = Path(path_str)
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file():
                    r = _import_single_file(conn, child, source, default_date, default_stock_code)
                    if r["ok"]:
                        imported += 1
                    else:
                        failed += 1
                    details.append(r)
        elif path.is_file():
            r = _import_single_file(conn, path, source, default_date, default_stock_code)
            if r["ok"]:
                imported += 1
            else:
                failed += 1
            details.append(r)

    conn.commit()
    return {"imported": imported, "failed": failed, "details": details}


def _import_single_file(
    conn: Any,
    path: Path,
    source: str,
    default_date: str | None,
    default_stock: str | None,
) -> dict[str, str]:
    ext = path.suffix.lower()
    try:
        if ext == ".csv":
            items = _parse_csv(path, default_date, default_stock)
        elif ext in (".md", ".markdown"):
            items = _parse_markdown(path, default_date, default_stock)
        elif ext in (".html", ".htm"):
            items = _parse_html(path, default_date, default_stock)
        elif ext == ".pdf":
            items = _parse_pdf(path, default_date, default_stock)
        else:
            return {"ok": False, "path": str(path), "error": f"Unsupported file type: {ext}"}

        if not items:
            return {"ok": False, "path": str(path), "error": "No content extracted"}

        doc_ids: list[str] = []
        for item in items:
            doc_id = store_document(conn, item)
            doc_ids.append(doc_id)
        return {"ok": True, "path": str(path), "doc_ids": ",".join(doc_ids)}
    except Exception as e:
        return {"ok": False, "path": str(path), "error": str(e)}
