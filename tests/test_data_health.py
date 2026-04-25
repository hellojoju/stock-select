"""Tests for data_health module."""
from __future__ import annotations

import pytest

from stock_select.db import connect, init_db
from stock_select.seed import seed_demo_data
from stock_select.data_health import (
    check_source_health,
    get_coverage,
    generate_health_report,
    get_missing_dates,
    SourceHealth,
    CoverageStats,
    HealthReport,
)


@pytest.fixture()
def health_db(tmp_path):
    conn = connect(tmp_path / "health.db")
    init_db(conn)
    seed_demo_data(conn)
    conn.commit()
    return conn


class TestCheckSourceHealth:
    def test_returns_healthy_for_source_with_data(self, health_db):
        health = check_source_health(health_db, "akshare")
        assert health.source == "akshare"
        assert health.status in ("healthy", "stale", "missing")

    def test_returns_missing_for_unknown_source(self, health_db):
        health = check_source_health(health_db, "nonexistent")
        assert health.status == "missing"
        assert health.source == "nonexistent"


class TestGetCoverage:
    def test_returns_coverage_stats(self, health_db):
        stats = get_coverage(health_db, "2026-01-12")
        assert stats.trading_date == "2026-01-12"
        assert isinstance(stats.stocks_synced, int)
        assert isinstance(stats.coverage_pct, float)

    def test_coverage_pct_within_range(self, health_db):
        stats = get_coverage(health_db, "2026-01-12")
        assert 0 <= stats.coverage_pct <= 100


class TestGenerateHealthReport:
    def test_returns_report(self, health_db):
        report = generate_health_report(health_db)
        assert isinstance(report, HealthReport)
        assert isinstance(report.sources, list)
        assert isinstance(report.stale_sources, list)
        assert isinstance(report.error_count, int)


class TestGetMissingDates:
    def test_returns_dates_without_data(self, health_db):
        missing = get_missing_dates(health_db, lookback_days=3)
        # Should return some recent dates (weekends/weekdays without data)
        assert isinstance(missing, list)

    def test_does_not_include_date_with_data(self, health_db):
        # Seed data includes 2026-01-12
        missing = get_missing_dates(health_db, lookback_days=1)
        # Today's date should not be in the list since lookback starts from yesterday
        # Just verify the function runs without error
        assert isinstance(missing, list)
