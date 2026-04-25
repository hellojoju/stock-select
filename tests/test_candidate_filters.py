"""Candidate hard filter tests: ST, suspended, and no-price exclusions."""
from __future__ import annotations

import pytest

from stock_select.candidate_pipeline import build_candidate, rank_candidates_for_gene
from stock_select.db import connect, init_db
from stock_select.repository import (
    active_stock_codes,
    upsert_daily_price,
    upsert_fundamental_metrics,
    upsert_sector_theme_signal,
    upsert_stock,
)
from stock_select.seed import seed_demo_data
from stock_select.strategies import seed_default_genes


@pytest.fixture
def db():
    """Create an in-memory database with schema and demo data."""
    conn = connect(":memory:")
    init_db(conn)
    seed_demo_data(conn)
    seed_default_genes(conn)
    return conn


class TestSTStockExclusion:
    """ST stocks must be excluded from candidate pool."""

    def test_st_flag_stored_correctly(self, db):
        """Verify is_st flag is correctly persisted in the database."""
        conn = db
        conn.execute(
            "INSERT INTO stocks(stock_code, name, is_st) VALUES ('000999.SZ', 'ST测试', 1)"
        )
        conn.commit()
        row = conn.execute("SELECT * FROM stocks WHERE is_st = 1").fetchone()
        assert row is not None
        assert row["is_st"] == 1
        assert row["stock_code"] == "000999.SZ"

    def test_st_stock_not_in_active_stock_codes(self, db):
        """ST stocks must not appear in active_stock_codes repository query."""
        conn = db
        upsert_stock(conn, "000999.SZ", "ST测试", is_st=True, exchange="SZSE")
        conn.commit()
        codes = active_stock_codes(conn)
        assert "000999.SZ" not in codes

    def test_st_stock_build_candidate_returns_none(self, db):
        """build_candidate must return None for ST stocks even with valid prices."""
        conn = db
        trading_date = "2026-01-13"
        upsert_stock(
            conn, "888888.SZ", "ST有价格", is_st=True, exchange="SZSE",
            industry="测试", list_date="2020-01-01",
        )
        dates = [
            "2026-01-02", "2026-01-05", "2026-01-06",
            "2026-01-07", "2026-01-08", "2026-01-09",
        ]
        for i, day in enumerate(dates):
            price = 10 + i * 0.1
            upsert_daily_price(
                conn, stock_code="888888.SZ", trading_date=day,
                open=price, high=price + 0.2, low=price - 0.1,
                close=price, volume=1_000_000, amount=price * 1_000_000,
            )
        conn.commit()

        result = build_candidate(conn, trading_date, "gene_aggressive_v1", "888888.SZ", {})
        assert result is None


class TestSuspendedStockExclusion:
    """Suspended stocks must be excluded from candidate pool."""

    def test_suspended_flag_stored_correctly(self, db):
        """Verify is_suspended flag is correctly persisted."""
        conn = db
        date = "2026-01-13"
        upsert_stock(conn, "000888.SZ", "停牌测试", exchange="SZSE")
        upsert_daily_price(
            conn, stock_code="000888.SZ", trading_date=date,
            open=10, high=10, low=10, close=10,
            volume=0, amount=0, is_suspended=True,
        )
        conn.commit()
        row = conn.execute(
            "SELECT is_suspended FROM daily_prices WHERE stock_code = '000888.SZ'"
        ).fetchone()
        assert row is not None
        assert row["is_suspended"] == 1

    def test_suspended_stock_build_candidate_returns_none(self, db):
        """build_candidate must return None when recent days are suspended."""
        conn = db
        trading_date = "2026-01-13"
        upsert_stock(
            conn, "777777.SZ", "近期停牌", exchange="SZSE",
            industry="测试", list_date="2020-01-01",
        )
        # Provide enough valid history, then suspend the last 2 days
        dates = [
            "2026-01-02", "2026-01-05", "2026-01-06",
            "2026-01-07", "2026-01-08", "2026-01-09",
        ]
        for i, day in enumerate(dates[:-2]):
            price = 10 + i * 0.1
            upsert_daily_price(
                conn, stock_code="777777.SZ", trading_date=day,
                open=price, high=price + 0.2, low=price - 0.1,
                close=price, volume=1_000_000, amount=price * 1_000_000,
            )
        # Last 2 days suspended
        for day in dates[-2:]:
            upsert_daily_price(
                conn, stock_code="777777.SZ", trading_date=day,
                open=10, high=10, low=10, close=10,
                volume=0, amount=0, is_suspended=True,
            )
        conn.commit()

        result = build_candidate(
            conn, trading_date, "gene_aggressive_v1", "777777.SZ", {}
        )
        assert result is None

    def test_listing_status_suspended_excluded_from_active(self, db):
        """Stocks with listing_status='suspended' must not be in active_stock_codes."""
        conn = db
        upsert_stock(
            conn, "666666.SZ", "长期停牌",
            exchange="SZSE", listing_status="suspended",
        )
        conn.commit()
        codes = active_stock_codes(conn)
        assert "666666.SZ" not in codes


class TestNoPriceExclusion:
    """Stocks without canonical price data must be excluded."""

    def test_no_price_stock_has_no_daily_prices(self, db):
        """A stock with no daily_prices rows should have zero price entries."""
        conn = db
        count = conn.execute(
            "SELECT COUNT(*) as cnt FROM daily_prices WHERE stock_code = '000004.SZ'"
        ).fetchone()["cnt"]
        assert count == 0

    def test_stock_with_insufficient_history_returns_none_candidate(self, db):
        """build_candidate returns None when price history is too short."""
        conn = db
        trading_date = "2026-01-13"
        upsert_stock(
            conn, "555555.SZ", "不足数据", exchange="SZSE",
            industry="测试", list_date="2020-01-01",
        )
        # Only 1 day of price data, not enough for lookback
        upsert_daily_price(
            conn, stock_code="555555.SZ", trading_date="2026-01-12",
            open=10, high=10.5, low=9.8, close=10.2,
            volume=1_000_000, amount=10_200_000,
        )
        conn.commit()

        result = build_candidate(
            conn, trading_date, "gene_aggressive_v1", "555555.SZ", {}
        )
        assert result is None


class TestCandidateFilterIntegration:
    """End-to-end tests using rank_candidates_for_gene."""

    def test_non_st_active_stocks_in_candidates(self, db):
        """Non-ST active stocks with sufficient data should appear in candidates."""
        conn = db
        gene = conn.execute(
            "SELECT * FROM strategy_genes WHERE gene_id = 'gene_aggressive_v1'"
        ).fetchone()
        params = {"lookback_days": 6}

        candidates = rank_candidates_for_gene(
            conn, "2026-01-13", "gene_aggressive_v1", params
        )
        # Demo data stocks should be in candidates
        candidate_codes = {c.stock_code for c in candidates}
        assert "000001.SZ" in candidate_codes

    def test_st_stock_excluded_from_ranked_candidates(self, db):
        """ST stocks must not appear in the final ranked candidate list."""
        conn = db
        upsert_stock(
            conn, "999998.SZ", "ST干扰项", is_st=True,
            exchange="SZSE", industry="测试", list_date="2020-01-01",
        )
        # Give it enough price data to ensure it would qualify otherwise
        dates = [
            "2026-01-02", "2026-01-05", "2026-01-06",
            "2026-01-07", "2026-01-08", "2026-01-09",
        ]
        for i, day in enumerate(dates):
            price = 20 + i * 0.5
            upsert_daily_price(
                conn, stock_code="999998.SZ", trading_date=day,
                open=price, high=price + 0.5, low=price - 0.2,
                close=price, volume=5_000_000, amount=price * 5_000_000,
            )
        conn.commit()

        candidates = rank_candidates_for_gene(
            conn, "2026-01-13", "gene_aggressive_v1", {"lookback_days": 6}
        )
        candidate_codes = {c.stock_code for c in candidates}
        assert "999998.SZ" not in candidate_codes
