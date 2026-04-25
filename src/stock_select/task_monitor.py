"""Task Monitor: query and monitor research run status."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RunStatus:
    """Status of a single research run."""
    run_id: str
    phase: str
    trading_date: str
    status: str
    error: str | None
    started_at: str | None
    finished_at: str | None
    duration_ms: int | None


@dataclass(frozen=True)
class PhaseSummary:
    """Summary of runs for a given phase."""
    phase: str
    total_runs: int
    ok_runs: int
    error_runs: int
    last_run_date: str | None
    last_run_status: str | None
    avg_duration_ms: float | None


@dataclass(frozen=True)
class DailyReport:
    """Daily execution report."""
    trading_date: str
    phases_run: list[str]
    phases_missing: list[str]
    all_ok: bool
    errors: list[str]
    total_duration_ms: int | None


REQUIRED_PHASES = [
    "sync_data",
    "preopen_pick",
    "simulate",
    "deterministic_review",
]


def get_recent_runs(
    conn: sqlite3.Connection,
    *,
    limit: int = 50,
    status: str | None = None,
    phase: str | None = None,
) -> list[RunStatus]:
    """Query recent research runs."""
    conditions: list[str] = []
    params: list[Any] = []

    if status:
        conditions.append("status = ?")
        params.append(status)
    if phase:
        conditions.append("phase = ?")
        params.append(phase)

    where = " AND ".join(conditions) if conditions else "1=1"
    rows = conn.execute(
        f"""
        SELECT run_id, phase, trading_date, status, error, started_at, finished_at
        FROM research_runs
        WHERE {where}
        ORDER BY started_at DESC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()

    return [
        RunStatus(
            run_id=r["run_id"],
            phase=r["phase"],
            trading_date=r["trading_date"],
            status=r["status"],
            error=r["error"],
            started_at=r["started_at"],
            finished_at=r["finished_at"],
            duration_ms=None,
        )
        for r in rows
    ]


def get_phase_summary(conn: sqlite3.Connection, phase: str) -> PhaseSummary:
    """Get summary statistics for a specific phase."""
    stats = conn.execute(
        """
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN status = 'ok' THEN 1 ELSE 0 END) as ok,
            SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as err,
            MAX(trading_date) as last_date,
            MAX(CASE WHEN trading_date = (SELECT MAX(trading_date) FROM research_runs WHERE phase = ?) THEN status END) as last_status
        FROM research_runs
        WHERE phase = ?
        """,
        (phase, phase),
    ).fetchone()

    d = dict(stats)
    return PhaseSummary(
        phase=phase,
        total_runs=d["total"] or 0,
        ok_runs=d["ok"] or 0,
        error_runs=d["err"] or 0,
        last_run_date=d["last_date"],
        last_run_status=d["last_status"],
        avg_duration_ms=None,
    )


def get_daily_report(conn: sqlite3.Connection, trading_date: str) -> DailyReport:
    """Generate a daily execution report."""
    run_phases = conn.execute(
        """
        SELECT DISTINCT phase, status, error
        FROM research_runs
        WHERE trading_date = ?
        ORDER BY phase
        """,
        (trading_date,),
    ).fetchall()

    phases_run = [r["phase"] for r in run_phases]
    errors = [r["error"] for r in run_phases if r["error"]]
    phases_missing = [p for p in REQUIRED_PHASES if p not in phases_run]
    all_ok = all(r["status"] == "ok" for r in run_phases)

    return DailyReport(
        trading_date=trading_date,
        phases_run=phases_run,
        phases_missing=phases_missing,
        all_ok=all_ok,
        errors=errors,
        total_duration_ms=None,
    )


def get_running_jobs(conn: sqlite3.Connection) -> list[RunStatus]:
    """Get currently running jobs."""
    rows = conn.execute(
        """
        SELECT run_id, phase, trading_date, status, error, started_at, finished_at
        FROM research_runs
        WHERE status = 'running'
        ORDER BY started_at
        """,
    ).fetchall()

    return [
        RunStatus(
            run_id=r["run_id"],
            phase=r["phase"],
            trading_date=r["trading_date"],
            status=r["status"],
            error=r["error"],
            started_at=r["started_at"],
            finished_at=r["finished_at"],
            duration_ms=None,
        )
        for r in rows
    ]


def get_error_summary(conn: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    """Get recent errors with their phase and date."""
    rows = conn.execute(
        """
        SELECT phase, trading_date, error, started_at
        FROM research_runs
        WHERE status = 'error' AND error IS NOT NULL
        ORDER BY started_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    return [dict(r) for r in rows]
