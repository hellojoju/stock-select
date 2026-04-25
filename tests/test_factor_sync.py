"""Tests for factor_sync module."""
from __future__ import annotations

import sqlite3
import pytest

from stock_select.db import connect, init_db
from stock_select.data_ingestion import DemoProvider
from stock_select.factor_sync import (
    sync_fundamental_factors,
    sync_sector_strength,
    sync_risk_factors,
)


@pytest.fixture()
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    init_db(conn)
    conn.execute("INSERT INTO stocks(stock_code, name) VALUES ('000001.SZ', 'Ping An Bank')")
    conn.execute("INSERT INTO stocks(stock_code, name) VALUES ('600519.SH', 'Kweichow Moutai')")
    conn.commit()
    return conn


class TestSyncFundamentalFactors:
    def test_sync_loads_factors_from_demo_provider(self, db):
        provider = DemoProvider("demo")
        result = sync_fundamental_factors(db, "2024-01-15", provider)
        assert result["rows_loaded"] >= 2

    def test_sync_idempotent_on_rerun(self, db):
        provider = DemoProvider("demo")
        first = sync_fundamental_factors(db, "2024-01-15", provider)
        second = sync_fundamental_factors(db, "2024-01-15", provider)
        assert first["rows_loaded"] == second["rows_loaded"]

        count = db.execute("SELECT COUNT(*) as cnt FROM fundamental_metrics").fetchone()["cnt"]
        assert count == first["rows_loaded"]

    def test_sync_records_nothing_when_no_active_stocks(self, db):
        db.execute("UPDATE stocks SET listing_status = 'inactive'")
        db.commit()
        provider = DemoProvider("demo")
        result = sync_fundamental_factors(db, "2024-01-15", provider)
        assert result["rows_loaded"] == 0

    def test_sync_skips_st_stocks(self, db):
        db.execute("UPDATE stocks SET is_st = 1 WHERE stock_code = '000001.SZ'")
        db.commit()
        provider = DemoProvider("demo")
        result = sync_fundamental_factors(db, "2024-01-15", provider)
        assert result["rows_loaded"] == 1

    def test_sync_records_data_source_status(self, db):
        provider = DemoProvider("demo")
        sync_fundamental_factors(db, "2024-01-15", provider)
        row = db.execute(
            "SELECT rows_loaded FROM data_sources WHERE dataset = 'fundamental_metrics'"
        ).fetchone()
        assert row is not None
        assert row["rows_loaded"] >= 2


class TestSyncSectorStrength:
    def _seed_sectors(self, db):
        db.execute(
            "INSERT INTO sector_theme_signals(trading_date, industry, sector_return_pct, relative_strength_rank, volume_surge, theme_strength, catalyst_count) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("2024-01-15", "Bank", 0.02, 0, 0.0, 0.0, 0),
        )
        db.execute(
            "INSERT INTO sector_theme_signals(trading_date, industry, sector_return_pct, relative_strength_rank, volume_surge, theme_strength, catalyst_count) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("2024-01-15", "Food", 0.05, 0, 0.0, 0.0, 0),
        )
        db.execute(
            "INSERT INTO sector_theme_signals(trading_date, industry, sector_return_pct, relative_strength_rank, volume_surge, theme_strength, catalyst_count) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("2024-01-15", "Battery", -0.01, 0, 0.0, 0.0, 0),
        )
        db.commit()

    def test_sector_strength_ranks(self, db):
        self._seed_sectors(db)
        result = sync_sector_strength(db, "2024-01-15")
        assert result["rows_loaded"] == 3

        food_rank = db.execute("SELECT relative_strength_rank FROM sector_theme_signals WHERE industry = 'Food'").fetchone()
        assert food_rank["relative_strength_rank"] == 1

        battery_rank = db.execute("SELECT relative_strength_rank FROM sector_theme_signals WHERE industry = 'Battery'").fetchone()
        assert battery_rank["relative_strength_rank"] == 3

    def test_sector_strength_empty(self, db):
        result = sync_sector_strength(db, "2024-01-15")
        assert result["rows_loaded"] == 0

    def test_sector_strength_only_one_date(self, db):
        db.execute(
            "INSERT INTO sector_theme_signals(trading_date, industry, sector_return_pct, relative_strength_rank, volume_surge, theme_strength, catalyst_count) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("2024-01-14", "Bank", 0.03, 0, 0.0, 0.0, 0),
        )
        db.execute(
            "INSERT INTO sector_theme_signals(trading_date, industry, sector_return_pct, relative_strength_rank, volume_surge, theme_strength, catalyst_count) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("2024-01-15", "Food", 0.05, 0, 0.0, 0.0, 0),
        )
        db.commit()

        result = sync_sector_strength(db, "2024-01-15")
        assert result["rows_loaded"] == 1


class TestSyncRiskFactors:
    def test_st_flag_auto_detected(self, db):
        db.execute("INSERT INTO stocks(stock_code, name) VALUES ('ST0001.SZ', 'ST Test')")
        db.commit()
        result = sync_risk_factors(db, "2024-01-15")
        st = db.execute("SELECT is_st FROM stocks WHERE stock_code = 'ST0001.SZ'").fetchone()
        assert st["is_st"] == 1

    def test_star_st_flag_auto_detected(self, db):
        db.execute("INSERT INTO stocks(stock_code, name) VALUES ('*ST0002.SH', '*ST Test')")
        db.commit()
        result = sync_risk_factors(db, "2024-01-15")
        st = db.execute("SELECT is_st FROM stocks WHERE stock_code = '*ST0002.SH'").fetchone()
        assert st["is_st"] == 1

    def test_suspension_flag_updated(self, db):
        db.execute(
            "INSERT INTO daily_prices(stock_code, trading_date, open, high, low, close, volume, amount, is_suspended) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("000001.SZ", "2024-01-15", 10.0, 10.5, 9.5, 10.0, 1000, 10000.0, 1),
        )
        db.commit()
        sync_risk_factors(db, "2024-01-15")
        status = db.execute("SELECT listing_status FROM stocks WHERE stock_code = '000001.SZ'").fetchone()
        assert status["listing_status"] == "suspended"
