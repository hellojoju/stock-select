from __future__ import annotations

import sqlite3
from typing import Any

from . import repository
from .data_status import data_quality_summary


def factor_status(conn: sqlite3.Connection, trading_date: str) -> dict[str, Any]:
    summary = data_quality_summary(conn, trading_date)
    active = int(summary.get("active_stocks") or 0)
    industry_rows = conn.execute(
        """
        SELECT COUNT(*) AS count FROM stocks
        WHERE listing_status = 'active'
          AND COALESCE(is_st, 0) = 0
          AND industry IS NOT NULL
          AND industry != ''
        """
    ).fetchone()["count"]
    fundamentals = conn.execute(
        "SELECT COUNT(DISTINCT stock_code) AS count FROM fundamental_metrics WHERE as_of_date < ?",
        (trading_date,),
    ).fetchone()["count"]
    sectors = conn.execute(
        "SELECT COUNT(*) AS count FROM sector_theme_signals WHERE trading_date < ?",
        (trading_date,),
    ).fetchone()["count"]
    events = conn.execute(
        "SELECT COUNT(*) AS count FROM event_signals WHERE trading_date < ?",
        (trading_date,),
    ).fetchone()["count"]
    negative_events = conn.execute(
        "SELECT COUNT(*) AS count FROM event_signals WHERE trading_date < ? AND impact_score < 0",
        (trading_date,),
    ).fetchone()["count"]
    return {
        "trading_date": trading_date,
        "active_stocks": active,
        "industry_coverage_pct": ratio(industry_rows, active),
        "fundamental_coverage_pct": ratio(fundamentals, active),
        "sector_signal_rows": int(sectors or 0),
        "event_signal_rows": int(events or 0),
        "negative_event_rows": int(negative_events or 0),
        "data_quality_summary": summary,
    }


def stock_factors(conn: sqlite3.Connection, stock_code: str, trading_date: str) -> dict[str, Any]:
    stock = conn.execute("SELECT * FROM stocks WHERE stock_code = ?", (stock_code,)).fetchone()
    if stock is None:
        return {"stock": None, "trading_date": trading_date}
    fundamental = repository.latest_fundamentals_before(conn, stock_code, trading_date)
    sector = repository.latest_sector_signal_before(conn, stock["industry"], trading_date)
    events = repository.recent_events_before(
        conn,
        trading_date=trading_date,
        stock_code=stock_code,
        industry=stock["industry"],
        limit=10,
    )
    candidate = conn.execute(
        """
        SELECT * FROM candidate_scores
        WHERE stock_code = ? AND trading_date = ?
        ORDER BY total_score DESC
        LIMIT 1
        """,
        (stock_code, trading_date),
    ).fetchone()
    return {
        "stock": dict(stock),
        "trading_date": trading_date,
        "fundamental": dict(fundamental) if fundamental else None,
        "sector": dict(sector) if sector else None,
        "events": repository.rows_to_dicts(events),
        "candidate_packet": repository.loads(candidate["packet_json"], {}) if candidate else None,
    }


def sector_factors(conn: sqlite3.Connection, trading_date: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM sector_theme_signals
        WHERE trading_date < ?
        ORDER BY trading_date DESC, relative_strength_rank ASC
        LIMIT 100
        """,
        (trading_date,),
    ).fetchall()
    return repository.rows_to_dicts(rows)


def ratio(numerator: int | float, denominator: int | float) -> float:
    return float(numerator or 0) / float(denominator or 1) if denominator else 0.0
