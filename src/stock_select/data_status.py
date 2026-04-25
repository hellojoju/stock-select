from __future__ import annotations

import sqlite3
from typing import Any

from . import repository


def data_source_status(conn: sqlite3.Connection, trading_date: str | None = None) -> list[dict[str, Any]]:
    if trading_date:
        rows = conn.execute(
            """
            SELECT * FROM data_sources
            WHERE trading_date IN (?, '__global__')
            ORDER BY dataset, source
            """,
            (trading_date,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM data_sources ORDER BY started_at DESC LIMIT 100").fetchall()
    return repository.rows_to_dicts(rows)


def data_quality_rows(
    conn: sqlite3.Connection,
    trading_date: str,
    *,
    status: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    clauses = ["trading_date = ?"]
    params: list[Any] = [trading_date]
    if status:
        clauses.append("status = ?")
        params.append(status)
    rows = conn.execute(
        f"""
        SELECT * FROM price_source_checks
        WHERE {' AND '.join(clauses)}
        ORDER BY status DESC, stock_code
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    return repository.rows_to_dicts(rows)


def data_quality_summary(conn: sqlite3.Connection, trading_date: str) -> dict[str, Any]:
    checks = conn.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM price_source_checks
        WHERE trading_date = ?
        GROUP BY status
        """,
        (trading_date,),
    ).fetchall()
    source_rows = data_source_status(conn, trading_date)
    trading_day = conn.execute("SELECT * FROM trading_days WHERE trading_date = ?", (trading_date,)).fetchone()
    canonical_prices = conn.execute(
        "SELECT COUNT(*) AS count FROM daily_prices WHERE trading_date = ?",
        (trading_date,),
    ).fetchone()["count"]
    index_prices = conn.execute(
        "SELECT COUNT(*) AS count FROM index_prices WHERE trading_date = ?",
        (trading_date,),
    ).fetchone()["count"]
    active_stocks = conn.execute(
        "SELECT COUNT(*) AS count FROM stocks WHERE listing_status = 'active' AND COALESCE(is_st, 0) = 0"
    ).fetchone()["count"]
    fundamentals = conn.execute(
        "SELECT COUNT(*) AS count FROM fundamental_metrics WHERE as_of_date < ?",
        (trading_date,),
    ).fetchone()["count"]
    events = conn.execute(
        "SELECT COUNT(*) AS count FROM event_signals WHERE trading_date < ?",
        (trading_date,),
    ).fetchone()["count"]
    sectors = conn.execute(
        "SELECT COUNT(*) AS count FROM sector_theme_signals WHERE trading_date < ?",
        (trading_date,),
    ).fetchone()["count"]
    industries = conn.execute(
        """
        SELECT COUNT(*) AS count FROM stocks
        WHERE listing_status = 'active'
          AND COALESCE(is_st, 0) = 0
          AND industry IS NOT NULL
          AND industry != ''
        """
    ).fetchone()["count"]
    negative_events = conn.execute(
        "SELECT COUNT(*) AS count FROM event_signals WHERE trading_date < ? AND impact_score < 0",
        (trading_date,),
    ).fetchone()["count"]
    status_counts = {row["status"]: int(row["count"]) for row in checks}
    return {
        "status_counts": status_counts,
        "warning_count": sum(count for status, count in status_counts.items() if status != "ok"),
        "canonical_prices": int(canonical_prices or 0),
        "active_stocks": int(active_stocks or 0),
        "coverage_pct": (float(canonical_prices or 0) / float(active_stocks or 1)) if active_stocks else 0.0,
        "index_prices": int(index_prices or 0),
        "market_environment": dict(trading_day) if trading_day else None,
        "source_status": source_rows,
        "multidimensional_status": {
            "fundamental_rows": int(fundamentals or 0),
            "event_rows": int(events or 0),
            "negative_event_rows": int(negative_events or 0),
            "sector_rows": int(sectors or 0),
            "industry_rows": int(industries or 0),
            "industry_coverage_pct": (float(industries or 0) / float(active_stocks or 1)) if active_stocks else 0.0,
            "message": multidimensional_message(fundamentals, events, sectors),
        },
    }


def multidimensional_message(fundamentals: int, events: int, sectors: int) -> str:
    missing = []
    if not fundamentals:
        missing.append("基本面")
    if not events:
        missing.append("事件")
    if not sectors:
        missing.append("行业")
    if not missing:
        return "多维数据已接入"
    return f"行情可用，{'/'.join(missing)}数据未接入或不足"
