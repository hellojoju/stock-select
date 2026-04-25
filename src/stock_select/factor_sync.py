"""Synchronize multidimensional fundamental factors from data providers."""
from __future__ import annotations

import sqlite3
from typing import Any

from . import repository
from .data_ingestion import MarketDataProvider


def sync_fundamental_factors(
    conn: sqlite3.Connection,
    trading_date: str,
    provider: MarketDataProvider,
) -> dict[str, Any]:
    """Fetch and upsert fundamental metrics for all active stocks."""
    active_codes = _active_stock_codes(conn)
    if not active_codes:
        return {"dataset": "fundamental_metrics", "rows_loaded": 0}

    factors = provider.fetch_fundamentals(trading_date, active_codes)
    rows_loaded = 0
    for item in factors:
        repository.upsert_fundamental_metrics(conn, **item.__dict__)
        rows_loaded += 1

    repository.record_data_source_status(
        conn,
        source=provider.source,
        dataset="fundamental_metrics",
        trading_date=trading_date,
        status="ok",
        rows_loaded=rows_loaded,
        source_reliability=reliability_for_source(provider.source),
    )
    conn.commit()
    return {"dataset": "fundamental_metrics", "rows_loaded": rows_loaded}


def sync_sector_strength(conn: sqlite3.Connection, trading_date: str) -> dict[str, Any]:
    """Compute sector strength rankings from sector_theme_signals."""
    rows = conn.execute(
        "SELECT industry, sector_return_pct FROM sector_theme_signals WHERE trading_date = ?",
        (trading_date,),
    ).fetchall()
    if not rows:
        return {"dataset": "sector_strength", "rows_loaded": 0}

    sorted_rows = sorted(rows, key=lambda r: r["sector_return_pct"], reverse=True)
    rows_loaded = 0
    for rank, row in enumerate(sorted_rows, 1):
        conn.execute(
            "UPDATE sector_theme_signals SET relative_strength_rank = ? WHERE trading_date = ? AND industry = ?",
            (rank, trading_date, row["industry"]),
        )
        rows_loaded += 1
    conn.commit()
    return {"dataset": "sector_strength", "rows_loaded": rows_loaded}


def sync_risk_factors(conn: sqlite3.Connection, trading_date: str) -> dict[str, Any]:
    """Update risk flags: ST status, suspension, liquidity thresholds."""
    conn.execute(
        """
        UPDATE stocks SET is_st = 1
        WHERE stock_code LIKE 'ST%' OR stock_code LIKE '*ST%'
        """,
    )
    conn.execute(
        """
        UPDATE stocks SET listing_status = 'suspended'
        WHERE stock_code IN (
            SELECT stock_code FROM daily_prices
            WHERE trading_date = ? AND is_suspended = 1
        )
        """,
        (trading_date,),
    )
    conn.commit()
    return {"dataset": "risk_factors", "status": "updated"}


def _active_stock_codes(conn: sqlite3.Connection) -> list[str]:
    """Return codes for active, non-ST stocks."""
    rows = conn.execute(
        "SELECT stock_code FROM stocks WHERE listing_status = 'active' AND is_st = 0",
    ).fetchall()
    return [r["stock_code"] for r in rows]


def reliability_for_source(source: str) -> str:
    """Map provider source to a reliability tier."""
    mapping = {
        "akshare": "primary",
        "baostock": "secondary",
        "demo": "untrusted",
    }
    return mapping.get(source, "untrusted")
