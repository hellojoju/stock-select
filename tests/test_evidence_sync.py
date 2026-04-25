"""Tests for evidence_sync module."""
from __future__ import annotations

import sqlite3
import pytest

from stock_select.db import connect, init_db
from stock_select.evidence_sync import sync_financial_actuals, sync_earnings_surprises
from stock_select.data_ingestion import DemoProvider


@pytest.fixture()
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    init_db(conn)
    conn.execute("INSERT INTO stocks(stock_code, name) VALUES ('000001.SZ', 'Ping An Bank')")
    conn.execute("INSERT INTO stocks(stock_code, name) VALUES ('600519.SH', 'Kweichow Moutai')")
    conn.commit()
    return conn


class TestSyncFinancialActuals:
    def test_returns_zero_when_provider_lacks_method(self, db):
        """DemoProvider does not implement fetch_financial_actuals."""
        provider = DemoProvider("demo")
        result = sync_financial_actuals(db, "2024-01-15", provider)
        assert result["rows_loaded"] == 0

    def test_returns_zero_for_empty_provider_list(self, db):
        """Provider with empty fetch returns zero."""
        provider = DemoProvider("demo")
        # fetch method doesn't exist, should return 0
        result = sync_financial_actuals(db, "2024-01-15", provider)
        assert result["rows_loaded"] == 0


class TestSyncEarningsSurprises:
    def _seed_expectations_and_actuals(self, db):
        """Insert one expectation and one actual for testing."""
        db.execute(
            """
            INSERT INTO analyst_expectations(
                expectation_id, stock_code, report_date, forecast_period,
                org_name, author_name, forecast_revenue, forecast_net_profit,
                forecast_eps, forecast_pe, rating, target_price_min, target_price_max,
                source, source_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            ("exp_001", "000001.SZ", "2024-01-01", "2023-Q4", "Test Org", "Analyst",
             100_000_000, 1_000_000_000, 1.0, 10, "BUY", 8, 12, "test"),
        )
        db.execute(
            """
            INSERT INTO financial_actuals(
                stock_code, report_period, ann_date, revenue, net_profit,
                net_profit_deducted, eps, roe, gross_margin, operating_cashflow,
                source, source_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'test', NULL)
            """,
            ("000001.SZ", "2023-Q4", "2024-01-10",
             150_000_000, 1_500_000_000, 1_400_000_000, 1.5, 0.12, 0.30, 2_000_000_000),
        )
        db.commit()

    def test_computes_surprise_from_actuals_vs_expectations(self, db):
        self._seed_expectations_and_actuals(db)
        result = sync_earnings_surprises(db, "2024-01-15")
        assert result["rows_loaded"] >= 1

        surprise = db.execute(
            "SELECT net_profit_surprise_pct FROM earnings_surprises WHERE stock_code = '000001.SZ'"
        ).fetchone()
        assert surprise is not None
        # (1.5B - 1.0B) / 1.0B = 0.5 = 50% surprise
        assert abs(surprise["net_profit_surprise_pct"] - 0.5) < 0.01

    def test_idempotent_rerun(self, db):
        self._seed_expectations_and_actuals(db)
        first = sync_earnings_surprises(db, "2024-01-15")
        second = sync_earnings_surprises(db, "2024-01-15")
        assert second["rows_loaded"] == 0  # already computed

    def test_no_actuals_returns_zero(self, db):
        result = sync_earnings_surprises(db, "2024-01-15")
        assert result["rows_loaded"] == 0

    def test_revenue_surprise_computed(self, db):
        self._seed_expectations_and_actuals(db)
        sync_earnings_surprises(db, "2024-01-15")

        surprise = db.execute(
            "SELECT revenue_surprise_pct FROM earnings_surprises WHERE stock_code = '000001.SZ'"
        ).fetchone()
        assert surprise is not None
        # (150M - 100M) / 100M = 0.5 = 50% revenue surprise
        assert abs(surprise["revenue_surprise_pct"] - 0.5) < 0.01
