"""Official announcement and finance news source adapters.

Fetches announcement/news indices from public sources and produces
RawDocumentItem instances for downstream storage and graph extraction.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from typing import Any

from . import repository
from .news_providers import RawDocumentItem


# ──────────────────────────────────────────────
# Stock code / company name recognition helpers
# ──────────────────────────────────────────────

_STOCK_CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_A_SHARE_PREFIX = {"sz", "sh", "bj"}


class AnnouncementSourceError(RuntimeError):
    def __init__(self, source: str, message: str):
        super().__init__(f"{source}: {message}")
        self.source = source
        self.message = message


def extract_stock_codes(text: str) -> list[str]:
    """Extract 6-digit A-share stock codes from text."""
    return [m.group(1) for m in _STOCK_CODE_RE.finditer(text or "")]


def guess_source_url(url: str, source: str) -> str:
    """Normalise a possibly-relative URL into an absolute one."""
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    base_map = {
        "cninfo": "https://www.cninfo.com.cn",
        "sse": "https://www.sse.com.cn",
        "szse": "https://www.szse.cn",
        "bse": "https://www.bse.cn",
        "eastmoney": "https://www.eastmoney.com",
        "sina": "https://finance.sina.com.cn",
    }
    base = base_map.get(source, "")
    if not base:
        return url
    # Ensure exactly one slash between base and path
    path = url.lstrip("/")
    return f"{base}/{path}"


def make_cninfo_disclosure_url(stock_code: str, adjunct_url: str) -> str:
    """Build a cninfo disclosure page URL from stock code and PDF path.

    The PDF path like 'finalpage/2026-05-01/1225275041.PDF' is not browsable.
    We construct a disclosure detail page URL instead.

    Handles both raw adjunctUrl ('finalpage/...') and already-prefixed URL
    ('https://www.cninfo.com.cn/finalpage/...').
    """
    if not stock_code or not adjunct_url:
        return ""
    # Strip base URL if present to get just the path
    path = adjunct_url
    if "cninfo.com.cn/" in path:
        path = path.split("cninfo.com.cn/", 1)[1]
    # Extract announcement ID from path like 'finalpage/2026-05-01/1225275041.PDF'
    m = re.search(r"/(\d{10,})\.PDF", path, re.IGNORECASE)
    ann_id = m.group(1) if m else ""
    if not ann_id:
        return ""
    return f"https://www.cninfo.com.cn/new/disclosure/detail?stockCode={stock_code}&announcementId={ann_id}"


def _http_get(url: str, timeout: float = 15) -> str:
    """Minimal HTTP GET returning decoded text."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")


# ──────────────────────────────────────────────
# CNInfo (巨潮资讯) announcement index provider
# ──────────────────────────────────────────────

def fetch_cninfo_announcements(
    stock_code: str | None = None,
    date: str | None = None,
    limit: int = 50,
) -> list[RawDocumentItem]:
    """Fetch announcement index from CNInfo.

    Uses the public search endpoint. Returns metadata-level items only
    (title, source, URL, published date). Full PDF text is not fetched
    here — a separate PDF extractor would handle that.
    """
    items: list[RawDocumentItem] = []
    # CNInfo public announcement search API
    base = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
    params: dict[str, str] = {
        "pageNum": "1",
        "pageSize": str(limit),
        "column": "szse",  # default to Shenzhen
        "tabName": "fulltext",
        "plate": "",
        "stock": stock_code or "",
        "searchkey": "",
        "secid": "",
        "category": "",
        "trade": "",
        "seDate": date or "",
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }
    encoded = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(base, data=encoded, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        raise AnnouncementSourceError("cninfo", str(exc)) from exc

    announcements = body.get("announcements", []) or []
    for ann in announcements:
        title = ann.get("announcementTitle", "")
        # strip HTML tags
        title = re.sub(r"<[^>]+>", "", title).strip()
        adjunct_url = ann.get("adjunctUrl", "")
        source_url = make_cninfo_disclosure_url(stock_code or "", adjunct_url) if stock_code else guess_source_url(adjunct_url, "cninfo")
        published = ann.get("announcementTime", "")
        if published and isinstance(published, (int, float)):
            published = datetime.fromtimestamp(published / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        stock_codes = []
        code_str = ann.get("secCode", "")
        if code_str:
            stock_codes = extract_stock_codes(str(code_str))
        if stock_code and not any(c == stock_code for c in stock_codes):
            stock_codes.insert(0, stock_code)

        items.append(RawDocumentItem(
            source="cninfo",
            source_type="official_announcement",
            source_url=source_url,
            title=title,
            summary=None,
            content_text=None,
            published_at=published,
            captured_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            related_stock_codes=stock_codes,
            related_industries=[],
            author=ann.get("secName"),
            license_status="public",
            visibility="preopen",
            raw_path=None,
        ))

    return items


# ──────────────────────────────────────────────
# SSE (上交所) announcement provider
# ──────────────────────────────────────────────

def fetch_sse_announcements(
    stock_code: str | None = None,
    date: str | None = None,
    limit: int = 30,
) -> list[RawDocumentItem]:
    """Fetch announcements from Shanghai Stock Exchange."""
    items: list[RawDocumentItem] = []
    # SSE uses a public disclosure page with JSON API
    url = (
        "http://query.sse.com.cn/portal/api/jsonp/var/"
        "getAnnouncementByDate?pageHelp.pageSize={limit}"
        "&reportType=regular&date={date}&securityCode={code}"
    ).format(
        limit=limit,
        date=date or "",
        code=stock_code or "",
    )
    # SSE requires specific Referer header
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": "http://www.sse.com.cn/disclosure/credibility/announcement/",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            # SSE returns JSONP — strip the callback wrapper
            match = re.search(r"var\s*=\s*(\[.*?\])", text, re.DOTALL)
            if not match:
                return items
            data = json.loads(match.group(1))
    except Exception as exc:
        raise AnnouncementSourceError("sse", str(exc)) from exc

    for row in data:
        title = re.sub(r"<[^>]+>", "", row.get("title", "")).strip()
        source_url = guess_source_url(row.get("url", ""), "sse")
        published = row.get("S_DATE", "")
        stock_codes = extract_stock_codes(title + " " + str(row.get("S_CODE", "")))

        items.append(RawDocumentItem(
            source="sse",
            source_type="official_announcement",
            source_url=source_url,
            title=title,
            summary=None,
            content_text=None,
            published_at=published,
            captured_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            related_stock_codes=stock_codes,
            related_industries=[],
            author=None,
            license_status="public",
            visibility="preopen",
            raw_path=None,
        ))

    return items


# ──────────────────────────────────────────────
# SZSE (深交所) announcement provider
# ──────────────────────────────────────────────

def fetch_szse_announcements(
    stock_code: str | None = None,
    date: str | None = None,
    limit: int = 30,
) -> list[RawDocumentItem]:
    """Fetch announcements from Shenzhen Stock Exchange."""
    items: list[RawDocumentItem] = []
    # SZSE public disclosure API
    base = "http://www.szse.cn/api/disc/announcement/annList"
    params: dict[str, Any] = {
        "seDate": date or "",
        "channelCode": ["listedNotice_disc", "listedNotice_listed"],
        "random": str(time.time())[:12],
    }
    if stock_code:
        params["seCode"] = [stock_code]

    payload = json.dumps(params).encode("utf-8")
    req = urllib.request.Request(base, data=payload, headers={
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        raise AnnouncementSourceError("szse", str(exc)) from exc

    results = body.get("data", []) if isinstance(body, dict) else []
    for row in results[:limit]:
        title = re.sub(r"<[^>]+>", "", row.get("title", "")).strip()
        source_url = guess_source_url(row.get("appendixPath", ""), "szse")
        published = row.get("publishTime", "")
        if published and isinstance(published, (int, float)):
            published = datetime.fromtimestamp(published / 1000, tz=timezone.utc).strftime("%Y-%m-%d")

        stock_codes = []
        code = row.get("secCode", "")
        if code:
            stock_codes = extract_stock_codes(str(code))
        if stock_code and not any(c == stock_code for c in stock_codes):
            stock_codes.insert(0, stock_code)

        items.append(RawDocumentItem(
            source="szse",
            source_type="official_announcement",
            source_url=source_url,
            title=title,
            summary=None,
            content_text=None,
            published_at=published,
            captured_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            related_stock_codes=stock_codes,
            related_industries=[],
            author=None,
            license_status="public",
            visibility="preopen",
            raw_path=None,
        ))

    return items


# ──────────────────────────────────────────────
# EastMoney (东方财富) news provider
# ──────────────────────────────────────────────

def fetch_eastmoney_news(
    stock_code: str | None = None,
    date: str | None = None,
    limit: int = 50,
) -> list[RawDocumentItem]:
    """Fetch individual stock news from EastMoney public pages."""
    items: list[RawDocumentItem] = []
    # EastMoney stock news API
    code_param = stock_code or "1.000001"  # default to market index if no stock
    url = (
        f"https://np-listapi.eastmoney.com/comm/web/getNewsByProduct?"
        f"client=web&biz=web_news_col&param=news&column=0&order=1"
        f"&page_index=1&page_size={limit}&new_energy_ranking=0&fields="
        f"title,content&filter=stockcode:{code_param}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        raise AnnouncementSourceError("eastmoney", str(exc)) from exc

    news_list = body.get("data", {}).get("list", []) if isinstance(body, dict) else []
    for item_data in news_list:
        title = re.sub(r"<[^>]+>", "", item_data.get("title", "")).strip()
        content = re.sub(r"<[^>]+>", "", item_data.get("content", "") or "").strip()[:500]
        published = item_data.get("showtime", "")
        if published and isinstance(published, str) and "T" in published:
            published = published.split("T")[0]
        elif published and isinstance(published, (int, float)):
            published = datetime.fromtimestamp(published, tz=timezone.utc).strftime("%Y-%m-%d")

        article_url = item_data.get("url", "")
        if not article_url.startswith(("http://", "https://")):
            article_url = f"https://www.eastmoney.com{article_url}"

        stock_codes = []
        if stock_code:
            stock_codes.append(stock_code)
        else:
            stock_codes = extract_stock_codes(title + " " + content)

        items.append(RawDocumentItem(
            source="eastmoney",
            source_type="finance_news",
            source_url=article_url,
            title=title,
            summary=content[:200] if content else None,
            content_text=content or None,
            published_at=published,
            captured_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            related_stock_codes=stock_codes,
            related_industries=[],
            author=item_data.get("author"),
            license_status="public",
            visibility="preopen",
            raw_path=None,
        ))

    return items


# ──────────────────────────────────────────────
# Sina Finance (新浪财经) news provider
# ──────────────────────────────────────────────

def fetch_sina_news(
    stock_code: str | None = None,
    date: str | None = None,
    limit: int = 30,
) -> list[RawDocumentItem]:
    """Fetch finance news from Sina Finance public pages."""
    items: list[RawDocumentItem] = []
    # Sina finance news list API
    url = (
        f"https://feed.mix.sina.com.cn/api/roll/get?"
        f"pageid=153&lid=2516&k=&num={limit}&page=1"
        f"&r=0.{int(time.time())}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        raise AnnouncementSourceError("sina", str(exc)) from exc

    news_list = body.get("result", {}).get("data", []) if isinstance(body, dict) else []
    for item_data in news_list:
        title = re.sub(r"<[^>]+>", "", item_data.get("title", "")).strip()
        summary = re.sub(r"<[^>]+>", "", item_data.get("summary", "") or "").strip()[:200]
        published = item_data.get("ctime", "")
        if published and isinstance(published, str):
            try:
                published = datetime.strptime(published, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d")
            except ValueError:
                pass

        source_url = item_data.get("url", "")
        stock_codes = extract_stock_codes(title + " " + summary)
        if stock_code and not any(c == stock_code for c in stock_codes):
            stock_codes.insert(0, stock_code)

        items.append(RawDocumentItem(
            source="sina",
            source_type="finance_news",
            source_url=source_url,
            title=title,
            summary=summary or None,
            content_text=None,
            published_at=published,
            captured_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            related_stock_codes=stock_codes,
            related_industries=[],
            author=item_data.get("author"),
            license_status="public",
            visibility="preopen",
            raw_path=None,
        ))

    return items


# ──────────────────────────────────────────────
# Orchestrator: sync all announcement sources
# ──────────────────────────────────────────────

def sync_announcements(
    stock_code: str | None = None,
    date: str | None = None,
    conn: Any | None = None,
) -> list[RawDocumentItem]:
    """Fetch announcements from all configured official sources."""
    all_items: list[RawDocumentItem] = []

    sources = [
        ("cninfo", fetch_cninfo_announcements, 0.5),
        ("sse", fetch_sse_announcements, 0.5),
        ("szse", fetch_szse_announcements, 0.0),
        ("eastmoney", fetch_eastmoney_news, 0.5),
        ("sina", fetch_sina_news, 0.0),
    ]
    for source, fetcher, pause in sources:
        try:
            items = fetcher(stock_code=stock_code, date=date)
            all_items.extend(items)
            if conn is not None:
                repository.record_data_source_status(
                    conn,
                    source=source,
                    dataset="documents",
                    trading_date=date,
                    status="ok",
                    rows_loaded=len(items),
                    error=None,
                )
        except AnnouncementSourceError as exc:
            error_msg = exc.message
            if len(error_msg) > 150:
                error_msg = error_msg[:150] + "..."
            if conn is not None:
                repository.record_data_source_status(
                    conn,
                    source=source,
                    dataset="documents",
                    trading_date=date,
                    status="error",
                    rows_loaded=0,
                    error=error_msg,
                )
            continue
        if pause:
            time.sleep(pause)

    return all_items
