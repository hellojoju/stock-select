from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class DataAvailability:
    """Availability gate result for a trading date."""

    trading_date: str
    price_coverage_pct: float
    pick_count: int
    event_source_count: int
    review_evidence_count: int
    status: str  # 'ok' | 'degraded' | 'failed'
    reasons: list[str]


def _price_coverage(conn: sqlite3.Connection, trading_date: str) -> float:
    """Percentage of active stocks with canonical prices for the date."""
    active = conn.execute(
        """
        SELECT COUNT(*) AS count FROM stocks
        WHERE listing_status = 'active' AND COALESCE(is_st, 0) = 0
        """
    ).fetchone()["count"]
    if not active:
        return 0.0
    have_prices = conn.execute(
        "SELECT COUNT(DISTINCT stock_code) AS count FROM daily_prices WHERE trading_date = ?",
        (trading_date,),
    ).fetchone()["count"]
    return (have_prices / active) * 100


def _pick_count(conn: sqlite3.Connection, trading_date: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS count FROM pick_decisions WHERE trading_date = ?",
        (trading_date,),
    ).fetchone()
    return row["count"] if row else 0


def _event_source_count(conn: sqlite3.Connection, trading_date: str) -> int:
    """Count distinct data sources that provided event signals for the date."""
    row = conn.execute(
        """
        SELECT COUNT(DISTINCT source) AS count FROM event_signals
        WHERE trading_date = ?
        """,
        (trading_date,),
    ).fetchone()
    return row["count"] if row else 0


def _review_evidence_count(conn: sqlite3.Connection, trading_date: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS count FROM review_evidence WHERE trading_date = ?",
        (trading_date,),
    ).fetchone()
    return row["count"] if row else 0


def check_data_availability(
    conn: sqlite3.Connection,
    trading_date: str,
) -> DataAvailability:
    """Return data availability scoring. Block downstream phases on critical failure."""
    price_coverage = _price_coverage(conn, trading_date)
    picks = _pick_count(conn, trading_date)
    events = _event_source_count(conn, trading_date)
    evidence = _review_evidence_count(conn, trading_date)

    reasons: list[str] = []
    status = "ok"

    # Price coverage thresholds
    if price_coverage < 80:
        status = "failed"
        reasons.append(f"price coverage {price_coverage:.1f}% < 80%")
    elif price_coverage < 95:
        if status == "ok":
            status = "degraded"
        reasons.append(f"price coverage {price_coverage:.1f}% < 95%")

    # Pick count thresholds
    if picks == 0:
        status = "failed"
        reasons.append("pick count = 0")

    # Event source thresholds
    if events == 0:
        if status == "ok":
            status = "degraded"
        reasons.append("event sources = 0")

    # Review evidence thresholds
    if evidence == 0:
        if status == "ok":
            status = "degraded"
        reasons.append("review evidence = 0")

    return DataAvailability(
        trading_date=trading_date,
        price_coverage_pct=round(price_coverage, 2),
        pick_count=picks,
        event_source_count=events,
        review_evidence_count=evidence,
        status=status,
        reasons=reasons,
    )
