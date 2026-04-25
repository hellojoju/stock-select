"""Data Health: check data source health, freshness, and completeness."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any
from datetime import datetime, date as date_type


@dataclass(frozen=True)
class SourceHealth:
    """Health status of a single data source."""
    source: str
    status: str  # "healthy", "stale", "error", "missing"
    last_sync: str | None
    last_error: str | None
    row_count: int | None
    staleness_hours: float | None


@dataclass(frozen=True)
class CoverageStats:
    """Coverage statistics for a trading date."""
    trading_date: str
    stocks_synced: int
    prices_synced: int
    prices_expected: int
    coverage_pct: float
    factors_synced: int
    factor_types: list[str]


@dataclass(frozen=True)
class HealthReport:
    """Overall data health report."""
    generated_at: str
    sources: list[SourceHealth]
    latest_trading_date: str | None
    coverage_today: CoverageStats | None
    stale_sources: list[str]
    error_count: int


KNOWN_SOURCES = ["akshare", "baostock"]


def check_source_health(conn: sqlite3.Connection, source: str) -> SourceHealth:
    """Check health of a specific data source."""
    last_sync = conn.execute(
        """
        SELECT MAX(created_at) as last_sync, COUNT(*) as cnt
        FROM daily_prices
        WHERE source = ?
        """,
        (source,),
    ).fetchone()

    last_error = conn.execute(
        """
        SELECT error FROM research_runs
        WHERE error IS NOT NULL AND phase = 'sync_data'
        ORDER BY started_at DESC
        LIMIT 1
        """,
    ).fetchone()

    d = dict(last_sync) if last_sync else {}
    last_sync_time = d.get("last_sync")
    row_count = d.get("cnt", 0)

    staleness = None
    status = "missing"
    if last_sync_time:
        sync_dt = _parse_timestamp(last_sync_time)
        if sync_dt:
            now = datetime.now()
            hours = (now - sync_dt).total_seconds() / 3600
            staleness = round(hours, 1)
            if hours < 24:
                status = "healthy"
            elif hours < 72:
                status = "stale"
            else:
                status = "stale"

    if last_error and last_error["error"]:
        status = "error"

    return SourceHealth(
        source=source,
        status=status,
        last_sync=last_sync_time,
        last_error=last_error["error"] if last_error else None,
        row_count=row_count,
        staleness_hours=staleness,
    )


def get_coverage(conn: sqlite3.Connection, trading_date: str) -> CoverageStats:
    """Get coverage stats for a specific trading date."""
    stock_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM stocks"
    ).fetchone()["cnt"]

    price_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM daily_prices WHERE trading_date = ?",
        (trading_date,),
    ).fetchone()["cnt"]

    factor_count = conn.execute(
        """
        SELECT COUNT(DISTINCT industry) as cnt
        FROM sector_theme_signals
        WHERE trading_date = ?
        """,
        (trading_date,),
    ).fetchone()["cnt"]

    factor_types = conn.execute(
        """
        SELECT DISTINCT industry
        FROM sector_theme_signals
        WHERE trading_date = ?
        """,
        (trading_date,),
    ).fetchall()

    coverage_pct = (price_count / stock_count * 100) if stock_count > 0 else 0.0

    return CoverageStats(
        trading_date=trading_date,
        stocks_synced=stock_count,
        prices_synced=price_count,
        prices_expected=stock_count,
        coverage_pct=round(coverage_pct, 1),
        factors_synced=factor_count,
        factor_types=[r["industry"] for r in factor_types],
    )


def generate_health_report(conn: sqlite3.Connection) -> HealthReport:
    """Generate comprehensive data health report."""
    sources = [check_source_health(conn, s) for s in KNOWN_SOURCES]
    stale_sources = [s.source for s in sources if s.status in ("stale", "missing")]

    latest_date = conn.execute(
        "SELECT MAX(trading_date) as dt FROM daily_prices"
    ).fetchone()
    latest_dt = latest_date["dt"] if latest_date else None

    coverage = get_coverage(conn, latest_dt) if latest_dt else None

    error_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM research_runs WHERE status = 'error'"
    ).fetchone()["cnt"]

    return HealthReport(
        generated_at=datetime.now().isoformat(),
        sources=sources,
        latest_trading_date=latest_dt,
        coverage_today=coverage,
        stale_sources=stale_sources,
        error_count=error_count,
    )


def get_missing_dates(conn: sqlite3.Connection, lookback_days: int = 5) -> list[str]:
    """Find trading dates with missing data."""
    from datetime import timedelta

    today = date_type.today()
    dates = [(today - timedelta(days=i)).isoformat() for i in range(1, lookback_days + 1)]

    missing = []
    for d in dates:
        count = conn.execute(
            "SELECT COUNT(*) as cnt FROM daily_prices WHERE trading_date = ?",
            (d,),
        ).fetchone()["cnt"]
        if count == 0:
            missing.append(d)

    return missing


def _parse_timestamp(ts: str) -> datetime | None:
    """Parse timestamp string to datetime."""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    return None
