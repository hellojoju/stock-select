"""Tests for task_monitor module."""
from __future__ import annotations

import pytest

from stock_select.db import connect, init_db
from stock_select.seed import seed_demo_data
from stock_select.task_monitor import (
    get_recent_runs,
    get_phase_summary,
    get_daily_report,
    get_running_jobs,
    get_error_summary,
    REQUIRED_PHASES,
)


@pytest.fixture()
def demo_db(tmp_path):
    conn = connect(tmp_path / "demo.db")
    init_db(conn)
    seed_demo_data(conn)
    conn.commit()
    return conn


@pytest.fixture()
def db_with_runs(demo_db):
    """Add some research runs for testing."""
    demo_db.execute(
        """
        INSERT INTO research_runs(run_id, trading_date, phase, status, started_at, finished_at)
        VALUES ('run_001', '2026-01-12', 'sync_data', 'ok', '2026-01-12 08:00:00', '2026-01-12 08:05:00')
        """,
    )
    demo_db.execute(
        """
        INSERT INTO research_runs(run_id, trading_date, phase, status, started_at, finished_at)
        VALUES ('run_002', '2026-01-12', 'preopen_pick', 'ok', '2026-01-12 08:10:00', '2026-01-12 08:12:00')
        """,
    )
    demo_db.execute(
        """
        INSERT INTO research_runs(run_id, trading_date, phase, status, error, started_at, finished_at)
        VALUES ('run_003', '2026-01-12', 'simulate', 'error', 'timeout', '2026-01-12 09:25:00', '2026-01-12 09:26:00')
        """,
    )
    demo_db.commit()
    return demo_db


class TestGetRecentRuns:
    def test_returns_runs(self, db_with_runs):
        runs = get_recent_runs(db_with_runs, limit=10)
        assert len(runs) == 3
        assert runs[0].phase == "simulate"

    def test_filter_by_status(self, db_with_runs):
        runs = get_recent_runs(db_with_runs, status="ok")
        assert all(r.status == "ok" for r in runs)

    def test_filter_by_phase(self, db_with_runs):
        runs = get_recent_runs(db_with_runs, phase="sync_data")
        assert len(runs) == 1
        assert runs[0].phase == "sync_data"


class TestGetPhaseSummary:
    def test_returns_summary(self, db_with_runs):
        summary = get_phase_summary(db_with_runs, "sync_data")
        assert summary.phase == "sync_data"
        assert summary.total_runs == 1
        assert summary.ok_runs == 1
        assert summary.error_runs == 0

    def test_empty_phase(self, demo_db):
        summary = get_phase_summary(demo_db, "nonexistent")
        assert summary.total_runs == 0


class TestGetDailyReport:
    def test_reports_missing_phases(self, demo_db):
        demo_db.execute(
            """
            INSERT INTO research_runs(run_id, trading_date, phase, status)
            VALUES ('run_001', '2026-01-12', 'sync_data', 'ok')
            """,
        )
        demo_db.commit()

        report = get_daily_report(demo_db, "2026-01-12")
        assert report.trading_date == "2026-01-12"
        assert "sync_data" in report.phases_run
        assert len(report.phases_missing) > 0
        assert report.all_ok is True

    def test_reports_errors(self, db_with_runs):
        report = get_daily_report(db_with_runs, "2026-01-12")
        assert report.all_ok is False
        assert len(report.errors) > 0


class TestGetRunningJobs:
    def test_returns_empty_when_no_running(self, db_with_runs):
        jobs = get_running_jobs(db_with_runs)
        assert len(jobs) == 0

    def test_returns_running_jobs(self, demo_db):
        demo_db.execute(
            """
            INSERT INTO research_runs(run_id, trading_date, phase, status, started_at)
            VALUES ('run_running', '2026-01-12', 'sync_data', 'running', '2026-01-12 08:00:00')
            """,
        )
        demo_db.commit()

        jobs = get_running_jobs(demo_db)
        assert len(jobs) == 1
        assert jobs[0].status == "running"


class TestGetErrorSummary:
    def test_returns_errors(self, db_with_runs):
        errors = get_error_summary(db_with_runs)
        assert len(errors) == 1
        assert errors[0]["phase"] == "simulate"

    def test_empty_when_no_errors(self, demo_db):
        errors = get_error_summary(demo_db)
        assert len(errors) == 0
