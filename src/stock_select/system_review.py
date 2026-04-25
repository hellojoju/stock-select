from __future__ import annotations

import hashlib
import sqlite3
from typing import Any

from . import repository
from .optimization_signals import list_optimization_signals


def run_system_review(conn: sqlite3.Connection, trading_date: str) -> str:
    picks = conn.execute(
        "SELECT COUNT(*) AS count FROM pick_decisions WHERE trading_date = ?",
        (trading_date,),
    ).fetchone()["count"]
    blindspots = conn.execute(
        "SELECT COUNT(*) AS count FROM blindspot_reviews WHERE trading_date = ?",
        (trading_date,),
    ).fetchone()["count"]
    avg_return = conn.execute(
        """
        SELECT AVG(o.return_pct) AS avg_return_pct
        FROM outcomes o
        JOIN pick_decisions p ON p.decision_id = o.decision_id
        WHERE p.trading_date = ?
        """,
        (trading_date,),
    ).fetchone()["avg_return_pct"]
    errors = top_system_errors(conn, trading_date)
    data_quality = repository.rows_to_dicts(
        conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM price_source_checks
            WHERE trading_date = ?
            GROUP BY status
            """,
            (trading_date,),
        )
    )
    observation = {
        "open_signals": len(list_optimization_signals(conn, status="open", limit=500)),
        "reviewed_decisions": conn.execute(
            "SELECT COUNT(*) AS count FROM decision_reviews WHERE trading_date = ?",
            (trading_date,),
        ).fetchone()["count"],
    }
    summary = (
        f"{trading_date}: {int(picks or 0)} picks, {int(blindspots or 0)} blindspots, "
        f"avg return {float(avg_return or 0):.2%}."
    )
    review_id = build_system_review_id(trading_date)
    conn.execute(
        """
        INSERT INTO system_reviews(
          system_review_id, trading_date, market_environment, total_picks,
          total_blindspots, avg_return_pct, top_system_errors_json,
          data_quality_json, observation_json, summary
        )
        VALUES (?, ?, 'unknown', ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(trading_date) DO UPDATE SET
          total_picks = excluded.total_picks,
          total_blindspots = excluded.total_blindspots,
          avg_return_pct = excluded.avg_return_pct,
          top_system_errors_json = excluded.top_system_errors_json,
          data_quality_json = excluded.data_quality_json,
          observation_json = excluded.observation_json,
          summary = excluded.summary
        """,
        (
            review_id,
            trading_date,
            int(picks or 0),
            int(blindspots or 0),
            float(avg_return or 0),
            repository.dumps(errors),
            repository.dumps(data_quality),
            repository.dumps(observation),
            summary,
        ),
    )
    conn.commit()
    return review_id


def get_system_review(conn: sqlite3.Connection, trading_date: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM system_reviews WHERE trading_date = ?", (trading_date,)).fetchone()
    if row is None:
        run_system_review(conn, trading_date)
        row = conn.execute("SELECT * FROM system_reviews WHERE trading_date = ?", (trading_date,)).fetchone()
    return dict(row)


def review_summary(conn: sqlite3.Connection, trading_date: str) -> dict[str, Any]:
    system = get_system_review(conn, trading_date)
    return {
        "decision_reviews": conn.execute(
            "SELECT COUNT(*) AS count FROM decision_reviews WHERE trading_date = ?",
            (trading_date,),
        ).fetchone()["count"],
        "blindspot_reviews": conn.execute(
            "SELECT COUNT(*) AS count FROM blindspot_reviews WHERE trading_date = ?",
            (trading_date,),
        ).fetchone()["count"],
        "top_errors": repository.loads(system["top_system_errors_json"], []),
        "open_optimization_signals": conn.execute(
            "SELECT COUNT(*) AS count FROM optimization_signals WHERE status = 'open'",
        ).fetchone()["count"],
        "system_summary": system["summary"],
    }


def top_system_errors(conn: sqlite3.Connection, trading_date: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT error_type, COUNT(*) AS count, AVG(severity) AS avg_severity
        FROM review_errors
        WHERE review_id IN (
          SELECT review_id FROM decision_reviews WHERE trading_date = ?
          UNION
          SELECT blindspot_review_id FROM blindspot_reviews WHERE trading_date = ?
        )
        GROUP BY error_type
        ORDER BY count DESC, avg_severity DESC
        LIMIT 10
        """,
        (trading_date, trading_date),
    ).fetchall()
    return [dict(row) for row in rows]


def build_system_review_id(trading_date: str) -> str:
    return "sysrev_" + hashlib.sha1(trading_date.encode("utf-8")).hexdigest()[:12]

