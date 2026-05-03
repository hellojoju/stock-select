"""Real-time announcement monitoring engine.

Polls configured announcement sources, classifies bullish alerts,
deduplicates against existing records, and stores qualified alerts.
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

# 北京时间
_CST = timezone(timedelta(hours=8))

from . import announcement_events, announcement_providers, repository
from .announcement_providers import make_cninfo_disclosure_url
from .db import ensure_column

logger = logging.getLogger(__name__)

# Global broadcast manager reference (set by server.py or scheduler)
_broadcast_manager = None

_MAX_SCAN_EVENTS = 200
_scan_events: list[dict] = []


def _fetch_live_data_for_stock(conn, stock_code: str, trading_date: str) -> None:
    """Fetch live market data from AkShare and store in database."""
    # Ensure stock exists in references table to satisfy FK constraint
    try:
        existing = conn.execute("SELECT 1 FROM stocks WHERE stock_code=?", (stock_code,)).fetchone()
        if not existing:
            conn.execute(
                "INSERT OR IGNORE INTO stocks (stock_code, name, listing_status) VALUES (?, ?, ?)",
                (stock_code, stock_code, "active"),
            )
    except Exception:
        pass
    try:
        import akshare as ak
        logger.info("Fetching live data for %s from AkShare...", stock_code)

        # 1. Get stock name from code-name mapping
        try:
            code_df = ak.stock_info_a_code_name()
            if code_df is not None and not code_df.empty:
                row = code_df[code_df["code"] == stock_code]
                if not row.empty:
                    name = row.iloc[0].get("name", stock_code)
                    conn.execute(
                        "UPDATE stocks SET name=? WHERE stock_code=?",
                        (name, stock_code),
                    )
                    conn.commit()
                    logger.info("Updated stock name for %s: %s", stock_code, name)
        except Exception as e:
            logger.warning("Failed to fetch stock name for %s: %s", stock_code, e)

        # 2. Fetch daily prices via fund flow API (reliable) and hist API (best-effort)
        _fetch_fund_flow_prices(conn, stock_code, trading_date)

        # 3. Best-effort: try to get hist data with volume (may fail on some networks)
        try:
            df_hist = ak.stock_zh_a_hist(symbol=stock_code, period="daily", adjust="qfq")
            if df_hist is not None and not df_hist.empty:
                logger.info("Got %d hist price rows for %s", len(df_hist), stock_code)
                inserted = 0
                for _, row_data in df_hist.iterrows():
                    date_str = str(row_data.get("日期", ""))
                    if trading_date and date_str > trading_date:
                        continue
                    close = float(row_data.get("收盘", 0) or 0)
                    if close <= 0:
                        continue
                    conn.execute(
                        """INSERT OR REPLACE INTO daily_prices
                           (stock_code, trading_date, open, high, low, close, volume, amount,
                            is_suspended, is_limit_up, is_limit_down, source)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 'akshare_hist')""",
                        (stock_code, date_str,
                         float(row_data.get("开盘", 0) or 0),
                         float(row_data.get("最高", 0) or 0),
                         float(row_data.get("最低", 0) or 0),
                         close,
                         float(row_data.get("成交量", 0) or 0),
                         float(row_data.get("成交额", 0) or 0)),
                    )
                    inserted += 1
                conn.commit()
                logger.info("Inserted %d hist prices for %s (with volume)", inserted, stock_code)
            else:
                logger.warning("stock_zh_a_hist returned no data for %s", stock_code)
        except Exception as e:
            logger.warning("stock_zh_a_hist failed for %s (volume will be 0): %s", stock_code, e)
    except ImportError:
        logger.warning("AkShare not installed")
    except Exception as e:
        logger.warning("Failed to fetch live data for %s: %s", stock_code, e)


def _fetch_fund_flow_prices(conn, stock_code, trading_date):
    """Fallback: fetch close prices from fund flow API (no volume)."""
    import akshare as ak
    market = "sh" if stock_code.startswith(("6", "9")) else "sz"
    df = ak.stock_individual_fund_flow(stock=stock_code, market=market)
    if df is not None and not df.empty:
        for _, row_data in df.tail(20).iterrows():
            date_str = str(row_data.get("日期", ""))
            close = float(row_data.get("收盘价", 0) or 0)
            if close <= 0:
                continue
            conn.execute(
                """INSERT OR REPLACE INTO daily_prices
                   (stock_code, trading_date, open, high, low, close, volume, amount,
                    is_suspended, is_limit_up, is_limit_down, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, 'akshare_fundflow')""",
                (stock_code, date_str, close, close, close, close, 0),
            )
        conn.commit()


def _log_scan_event(event_type: str, message: str, detail: str = "", level: str = "info",
                    conn=None) -> None:
    """Persist a scan event to the database (or in-memory fallback)."""
    ts = datetime.now(_CST).strftime("%H:%M:%S")
    if conn is not None:
        try:
            conn.execute(
                "INSERT INTO scan_events (occurred_at, event_type, message, detail, level) VALUES (?, ?, ?, ?, ?)",
                (ts, event_type, message, detail, level),
            )
            conn.commit()
            # Trim old events
            conn.execute(
                "DELETE FROM scan_events WHERE event_id NOT IN (SELECT event_id FROM scan_events ORDER BY event_id DESC LIMIT ?)",
                (_MAX_SCAN_EVENTS,),
            )
        except Exception:
            pass  # best effort — table may not exist yet
    # In-memory fallback
    global _scan_events
    _scan_events.append({
        "timestamp": ts,
        "type": event_type,
        "message": message,
        "detail": detail,
        "level": level,
    })
    _scan_events = _scan_events[-_MAX_SCAN_EVENTS:]


def get_scan_events(limit: int = 50, conn=None) -> list[dict]:
    """Get recent scan events from database (or in-memory fallback)."""
    if conn is not None:
        try:
            rows = conn.execute(
                "SELECT timestamp as occurred_at, event_type as type, message, detail, level FROM scan_events ORDER BY event_id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            pass  # table may not exist yet
    return _scan_events[-limit:]


def clear_scan_events() -> None:
    """Clear the event log."""
    global _scan_events
    _scan_events.clear()


def set_broadcast_manager(bm) -> None:
    """Set the global broadcast manager for real-time push."""
    global _broadcast_manager
    _broadcast_manager = bm


def _try_broadcast(alert: AnnouncementAlert) -> None:
    """Attempt to broadcast a high-scoring alert (non-blocking)."""
    if _broadcast_manager is None:
        return
    if alert.sentiment_score < 0.6:
        return
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(
            _broadcast_manager.broadcast("new_alert", {
                "alert": {
                    "alert_id": alert.alert_id,
                    "stock_code": alert.stock_code,
                    "stock_name": alert.stock_name,
                    "alert_type": alert.alert_type,
                    "title": alert.title,
                    "sentiment_score": alert.sentiment_score,
                    "discovered_at": alert.discovered_at,
                }
            })
        )
    except RuntimeError:
        # No running event loop — use sync fallback
        import threading
        def _bg():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(
                _broadcast_manager.broadcast("new_alert", {
                    "alert": {
                        "alert_id": alert.alert_id,
                        "stock_code": alert.stock_code,
                        "stock_name": alert.stock_name,
                        "alert_type": alert.alert_type,
                        "title": alert.title,
                        "sentiment_score": alert.sentiment_score,
                        "discovered_at": alert.discovered_at,
                    }
                })
            )
        threading.Thread(target=_bg, daemon=True).start()

# ──────────────────────────────────────────────
# Alert type classification
# ──────────────────────────────────────────────

# 业绩大增 / 超预期 / 反转
_EARNINGS_PATTERNS = [
    r"净利.*增", r"利润.*增", r"营收.*增", r"业绩.*增",
    r"同比.*增", r"大幅.*增", r"预增", r"预盈",
    r"扭亏", r"超预期", r"业绩.*升", r"盈利.*升",
    r"earn.*increas", r"profit.*surge",
]

# 大额订单 / 合同
_ORDER_PATTERNS = [
    r"中标", r"签订.*合同", r"签订.*协议", r"大额.*订单",
    r"订单.*亿", r"合同.*亿", r"重大.*合同", r"项目.*中标",
    r"入围", r"获评.*供应商",
]

# 技术突破 / 研发进展
_TECH_PATTERNS = [
    r"技术.*突破", r"研发.*成功", r"专利", r"新产品",
    r"新.*投产", r"量产", r"试产.*成功", r"通过.*认证",
    r"技术.*领先", r"首创", r"填补.*空白",
]

# 资产注入 / 定增 / 回购
_ASSET_PATTERNS = [
    r"资产.*注入", r"定增", r"非公开发行", r"增发",
    r"回购.*注销", r"回购.*完成", r"股权激励",
    r"员工持股", r"资产.*收购", r"购买.*资产",
]

# 兼并重组 / 股权变更
_MA_PATTERNS = [
    r"重组", r"合并", r"兼并", r"吸收", r"换股",
    r"股权.*转让", r"控制.*变更", r"实控人.*变更",
    r"借壳", r"资产.*置换", r"分拆.*上市",
]

_ALERT_TYPE_LABELS: dict[str, str] = {
    "earnings_beat": "业绩大增",
    "large_order": "大额订单",
    "tech_breakthrough": "技术突破",
    "asset_injection": "资产注入",
    "m_and_a": "兼并重组",
}

_ALERT_TYPE_RULES: list[tuple[str, list[str]]] = [
    ("earnings_beat", _EARNINGS_PATTERNS),
    ("large_order", _ORDER_PATTERNS),
    ("tech_breakthrough", _TECH_PATTERNS),
    ("asset_injection", _ASSET_PATTERNS),
    ("m_and_a", _MA_PATTERNS),
]

# Titles that are routine / non-actionable — filter OUT
_NOISE_PATTERNS = [
    r"股东大会", r"召开.*会议", r"董监高", r"减持", r"质押",
    r"解除质押", r"诉讼", r"仲裁", r"违规", r"处罚",
    r"立案.*调查", r"风险提", r"退市风险", r"特别处理",
    r"st\b", r"\*st", r"更正.*公告", r"补充.*公告",
    r"年报", r"中报", r"季报", r"一报", r"三报",  # routine periodic reports
    r"日常经营", r"例行", r"常规",
]


def _classify_alert_type(title: str, text: str | None = None) -> tuple[str | None, str | None, str | None]:
    """Classify announcement into a bullish alert type or None if noise.

    Returns (alert_type, matched_pattern_label, matched_pattern) or (None, reason, None).
    """
    combined = f"{title} {(text or '')}"
    # First check noise — reject early
    for pat in _NOISE_PATTERNS:
        m = re.search(pat, combined, re.IGNORECASE)
        if m:
            return (None, "噪音", m.group(0))
    # Then match alert types — first match wins (priority order)
    for alert_type, patterns in _ALERT_TYPE_RULES:
        for pat in patterns:
            m = re.search(pat, combined, re.IGNORECASE)
            if m:
                return (alert_type, _ALERT_TYPE_LABELS.get(alert_type, alert_type), m.group(0))
    return (None, "未匹配", None)


# ──────────────────────────────────────────────
# Data model
# ──────────────────────────────────────────────

@dataclass
class AnnouncementAlert:
    alert_id: str
    trading_date: str
    discovered_at: str
    stock_code: str
    stock_name: str | None
    industry: str | None
    source: str
    alert_type: str
    title: str
    summary: str | None
    source_url: str
    event_ids_json: str | None
    sentiment_score: float
    capital_flow_score: float | None
    sector_heat_score: float | None
    chip_structure_score: float | None
    shareholder_trend_score: float | None
    confidence: float
    capital_flow_evidence: str | None = None
    sector_heat_evidence: str | None = None
    chip_structure_evidence: str | None = None
    shareholder_trend_evidence: str | None = None
    status: str = "new"


# ──────────────────────────────────────────────
# Polling engine
# ──────────────────────────────────────────────

def _ensure_schema(conn) -> None:
    """Ensure optional score & evidence columns exist (for backward compatibility)."""
    for col in [
        "sentiment_score", "capital_flow_score", "sector_heat_score",
        "chip_structure_score", "shareholder_trend_score",
    ]:
        ensure_column(conn, "announcement_alerts", col, "REAL DEFAULT 0")
    for col in [
        "capital_flow_evidence", "sector_heat_evidence",
        "chip_structure_evidence", "shareholder_trend_evidence",
    ]:
        ensure_column(conn, "announcement_alerts", col, "TEXT DEFAULT ''")


def _is_duplicate(conn, stock_code: str, title: str, source: str) -> bool:
    """Check if this alert already exists."""
    row = conn.execute(
        "SELECT 1 FROM announcement_alerts WHERE stock_code=? AND title=? AND source=?",
        (stock_code, title, source),
    ).fetchone()
    return row is not None


def _insert_alert(conn, alert: AnnouncementAlert) -> None:
    """Insert or replace an alert into the database (updates scores on re-scan)."""
    conn.execute(
        """INSERT OR REPLACE INTO announcement_alerts
           (alert_id, trading_date, discovered_at, stock_code, stock_name,
            industry, source, alert_type, title, summary, source_url,
            event_ids_json, sentiment_score, capital_flow_score,
            sector_heat_score, chip_structure_score, shareholder_trend_score,
            capital_flow_evidence, sector_heat_evidence,
            chip_structure_evidence, shareholder_trend_evidence,
            confidence, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            alert.alert_id, alert.trading_date, alert.discovered_at,
            alert.stock_code, alert.stock_name, alert.industry,
            alert.source, alert.alert_type, alert.title, alert.summary,
            alert.source_url, alert.event_ids_json,
            alert.sentiment_score, alert.capital_flow_score,
            alert.sector_heat_score, alert.chip_structure_score,
            alert.shareholder_trend_score,
            alert.capital_flow_evidence, alert.sector_heat_evidence,
            alert.chip_structure_evidence, alert.shareholder_trend_evidence,
            alert.confidence, alert.status,
        ),
    )


def _record_monitor_run(
    conn,
    run_id: str,
    started_at: str,
    source: str,
    documents_fetched: int,
    new_documents: int,
    alerts_generated: int,
    error: str | None = None,
) -> None:
    """Record a monitoring run result."""
    status = "error" if error else "completed"
    finished_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        """INSERT INTO monitor_runs
           (run_id, started_at, finished_at, source, documents_fetched,
            new_documents, alerts_generated, error, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (run_id, started_at, finished_at, source, documents_fetched,
         new_documents, alerts_generated, error, status),
    )


def run_announcement_scan(
    conn,
    stock_codes: list[str] | None = None,
    trading_date: str | None = None,
) -> list[AnnouncementAlert]:
    """Run a single announcement scan.

    Tries sources in fallback order: cninfo → eastmoney → sina.
    Only moves to the next source if the current one fails.

    Uses a 3-day lookback window to catch weekend/holiday announcements.
    """
    _ensure_schema(conn)

    today = trading_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # Look back 3 days to cover weekends/holidays
    try:
        from datetime import timedelta
        dt_today = datetime.strptime(today, "%Y-%m-%d")
        date_start = (dt_today - timedelta(days=3)).strftime("%Y-%m-%d")
        date_range = f"{date_start}~{today}"
    except Exception:
        date_range = today

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id = str(uuid.uuid4())[:12]

    _log_scan_event("scan_start", f"开始扫描公告 — 日期 {date_range}", conn=conn)

    all_alerts: list[AnnouncementAlert] = []
    total_fetched = 0
    total_new = 0

    def _process_items(items, source_name):
        """Process fetched items: classify, dedup, score, insert."""
        nonlocal total_fetched, total_new
        n_new = 0
        n_alerts = 0
        n_classified = 0
        n_filtered = 0
        n_no_stock = 0
        n_dup = 0
        sentiment_calls = 0
        sentiment_fails = 0

        classify_details = []

        # Step 1: classify all items
        for item in items:
            if not item.related_stock_codes:
                n_no_stock += 1
                classify_details.append({
                    "stock": "—",
                    "title": item.title[:80],
                    "result": "无股票",
                    "reason": "未关联股票代码",
                })
                continue
            if stock_codes and not any(c in stock_codes for c in item.related_stock_codes):
                continue

            alert_type, category_label, matched_pat = _classify_alert_type(item.title, item.content_text)
            if alert_type is None:
                n_filtered += 1
                classify_details.append({
                    "stock": ",".join(item.related_stock_codes[:3]),
                    "title": item.title[:80],
                    "result": "过滤",
                    "reason": category_label,
                    "matched_pattern": matched_pat,
                })
                continue
            n_classified += 1

            stock_code = item.related_stock_codes[0]

            is_dup = _is_duplicate(conn, stock_code, item.title, source_name)
            if is_dup:
                n_dup += 1
                classify_details.append({
                    "stock": stock_code,
                    "title": item.title[:80],
                    "type": category_label,
                    "result": "去重但仍分析",
                    "matched_pattern": matched_pat,
                })
                # 去重后仍继续分析，不做静默跳过
                n_new += 1
                total_new += 1
            else:
                n_new += 1
                total_new += 1

            _log_scan_event(
                "alert_found",
                f"命中利好: [{_ALERT_TYPE_LABELS.get(alert_type, alert_type)}] {stock_code}",
                item.title[:80],
                "success",
                conn=conn,
            )

            event_ids_json = None
            if item.content_text:
                try:
                    events = announcement_events.process_announcement_text(
                        item.content_text, stock_code
                    )
                    if events:
                        import json
                        event_ids_json = json.dumps(
                            [{"type": e.__class__.__name__, "detail": str(e)} for e in events[:5]]
                        )
                except Exception:
                    pass  # best effort

            row = conn.execute(
                "SELECT name, industry FROM stocks WHERE stock_code=?",
                (stock_code,),
            ).fetchone()
            stock_name = row[0] if row else None
            industry = row[1] if row else None

            # Fetch live data from AkShare before scoring
            try:
                _fetch_live_data_for_stock(conn, stock_code, today)
                # Re-query stock info after live data fetch
                row2 = conn.execute(
                    "SELECT name, industry FROM stocks WHERE stock_code=?",
                    (stock_code,),
                ).fetchone()
                if row2:
                    stock_name = row2[0] or stock_name
                    industry = row2[1] or industry
            except Exception:
                pass

            # Step 2: sentiment scoring + multi-signal analysis
            sentiment_calls += 1
            scores_detail = None
            try:
                from .sentiment_scoring import (
                    score_announcement_sentiment,
                    compute_capital_flow_score,
                    compute_sector_heat,
                    compute_chip_structure_score,
                    compute_shareholder_trend_score,
                    WEIGHT_CAPITAL_FLOW,
                    WEIGHT_SECTOR_HEAT,
                    WEIGHT_CHIP_STRUCTURE,
                    WEIGHT_SHAREHOLDER_TREND,
                )
                sentiment = score_announcement_sentiment(
                    conn, stock_code, today, alert_type
                )
                sentiment_score = sentiment.composite
                capital_flow_score = sentiment.capital_flow_score
                sector_heat_score = sentiment.sector_heat_score
                chip_structure_score = sentiment.chip_structure_score
                shareholder_trend_score = sentiment.shareholder_trend_score
                confidence = max(0.5, sentiment_score)

                # Get evidence from sub-score functions directly
                _, capital_evidence = compute_capital_flow_score(conn, stock_code, today)
                _, sector_evidence = compute_sector_heat(conn, stock_code, today)
                _, chip_evidence = compute_chip_structure_score(conn, stock_code, today)
                _, shareholder_evidence = compute_shareholder_trend_score(conn, stock_code, today)

                scores_detail = {
                    "stock": stock_code,
                    "name": stock_name,
                    "alert_type": _ALERT_TYPE_LABELS.get(alert_type, alert_type),
                    "composite": round(sentiment_score, 3),
                    "confidence": round(confidence, 3),
                    "opportunity_type": sentiment.opportunity_type,
                    "type_bonus": {
                        "earnings_beat": 0.05, "large_order": 0.05, "m_and_a": 0.08,
                        "asset_injection": 0.06, "tech_breakthrough": 0.04,
                    }.get(alert_type, 0),
                    "dimensions": {
                        "capital_flow": {
                            "score": round(capital_flow_score, 3),
                            "weight": WEIGHT_CAPITAL_FLOW,
                            "evidence": capital_evidence,
                        },
                        "sector_heat": {
                            "score": round(sector_heat_score, 3),
                            "weight": WEIGHT_SECTOR_HEAT,
                            "evidence": sector_evidence,
                        },
                        "chip_structure": {
                            "score": round(chip_structure_score, 3),
                            "weight": WEIGHT_CHIP_STRUCTURE,
                            "evidence": chip_evidence,
                        },
                        "shareholder_trend": {
                            "score": round(shareholder_trend_score, 3),
                            "weight": WEIGHT_SHAREHOLDER_TREND,
                            "evidence": shareholder_evidence,
                        },
                    },
                }
            except Exception as exc:
                logger.warning("sentiment scoring failed for %s: %s", stock_code, exc)
                sentiment_fails += 1
                sentiment_score = 0.0
                capital_flow_score = None
                sector_heat_score = None
                chip_structure_score = None
                shareholder_trend_score = None
                capital_evidence = None
                sector_evidence = None
                chip_evidence = None
                shareholder_evidence = None
                confidence = 0.5
                scores_detail = {
                    "stock": stock_code,
                    "name": stock_name,
                    "alert_type": _ALERT_TYPE_LABELS.get(alert_type, alert_type),
                    "error": str(exc)[:100],
                }

            alert = AnnouncementAlert(
                alert_id=str(uuid.uuid4())[:16],
                trading_date=today,
                discovered_at=now_str,
                stock_code=stock_code,
                stock_name=stock_name,
                industry=industry,
                source=source_name,
                alert_type=alert_type,
                title=item.title,
                summary=item.summary,
                source_url=make_cninfo_disclosure_url(stock_code, item.source_url) if source_name == "cninfo" else item.source_url,
                event_ids_json=event_ids_json,
                sentiment_score=sentiment_score,
                capital_flow_score=capital_flow_score,
                sector_heat_score=sector_heat_score,
                chip_structure_score=chip_structure_score,
                shareholder_trend_score=shareholder_trend_score,
                capital_flow_evidence=capital_evidence,
                sector_heat_evidence=sector_evidence,
                chip_structure_evidence=chip_evidence,
                shareholder_trend_evidence=shareholder_evidence,
                confidence=confidence,
            )
            _insert_alert(conn, alert)
            _try_broadcast(alert)
            n_alerts += 1
            all_alerts.append(alert)

            if scores_detail:
                classify_details.append(scores_detail)

        # Log processing summary
        import json
        _log_scan_event(
            "classify_done",
            f"分类完成: {n_classified} 条命中利好 / {len(items)} 条原始",
            json.dumps(classify_details, ensure_ascii=False),
            "info",
            conn=conn,
        )
        _log_scan_event(
            "sentiment_done",
            f"情绪分析: {sentiment_calls} 条 (成功 {sentiment_calls - sentiment_fails})",
            f"新增报警 {n_alerts} 条 (去重过滤 {n_new} 条)",
            "success",
            conn=conn,
        )

        return n_new, n_alerts

    def _record_run(source_name, fetched, new, alerts, error=None):
        nonlocal total_fetched
        total_fetched += fetched
        _record_monitor_run(
            conn, f"{run_id}-{source_name}", now_str, source_name,
            fetched, new, alerts, error=error,
        )
        conn.commit()

    # ── Fallback chain: cninfo → eastmoney → sina ──
    source_chain = [
        ("cninfo", announcement_providers.fetch_cninfo_announcements),
        ("eastmoney", announcement_providers.fetch_eastmoney_news),
        ("sina", announcement_providers.fetch_sina_news),
    ]

    success_source = None

    for idx, (source_name, fetcher) in enumerate(source_chain):
        # If primary (cninfo) succeeded, skip rest
        if idx > 0 and success_source is not None:
            _log_scan_event("source_skip", f"跳过 {source_name}", f"主数据源 {success_source} 已成功获取", conn=conn)
            continue

        _log_scan_event("source_start", f"对接数据源: {source_name}", conn=conn)

        try:
            items = fetcher(stock_code=None, date=date_range, limit=50)
            source_fetched = len(items)

            # Save raw items summary for display
            import json
            raw_summary = json.dumps([
                {
                    "title": item.title[:80],
                    "stock": ",".join(item.related_stock_codes[:3]) or "无",
                    "url": make_cninfo_disclosure_url(
                        item.related_stock_codes[0], item.source_url
                    ) if source_name == "cninfo" and item.source_url else item.source_url,
                }
                for item in items[:50]
            ], ensure_ascii=False)

            _log_scan_event(
                "source_result",
                f"{source_name} 返回 {source_fetched} 条公告",
                raw_summary,
                "success",
                conn=conn,
            )

            n_new, n_alerts = _process_items(items, source_name)
            success_source = source_name

            _log_scan_event(
                "source_done", f"{source_name} 处理完成",
                f"新增报警 {n_alerts} 条 (去重过滤 {n_new} 条)",
                "success",
                conn=conn,
            )
            _record_run(source_name, source_fetched, n_new, n_alerts)

        except Exception as exc:
            logger.error("announcement_monitor source=%s error=%s", source_name, exc)
            source_fetched = 0
            _log_scan_event(
                "source_fail", f"{source_name} 获取失败",
                str(exc)[:100], "error",
                conn=conn,
            )
            _record_run(source_name, source_fetched, 0, 0, error=str(exc))
            # Fall through to next source

    if success_source is None:
        _log_scan_event("scan_fail", "所有数据源均失败", "请检查网络或数据源状态", "error", conn=conn)
    else:
        _log_scan_event("scan_done", f"扫描完成", f"共获取 {total_fetched} 条 → 新增 {total_new} 条报警", "success", conn=conn)

    return all_alerts
