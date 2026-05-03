"""Tests for sentiment_scoring module."""
import pytest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from stock_select.sentiment_scoring import (
    compute_capital_flow_score,
    compute_sector_heat,
    compute_chip_structure_score,
    compute_shareholder_trend_score,
    score_announcement_sentiment,
    refresh_sector_heat_index,
    SentimentScore,
)


@pytest.fixture
def conn():
    from stock_select.db import connect, init_db
    c = connect(":memory:")
    init_db(c)
    # Seed basic stock data
    c.execute(
        "INSERT OR IGNORE INTO stocks (stock_code, name, industry, list_date) VALUES (?, ?, ?, ?)",
        ("000001", "平安银行", "银行", "1991-04-03"),
    )
    c.execute(
        "INSERT OR IGNORE INTO stocks (stock_code, name, industry, list_date) VALUES (?, ?, ?, ?)",
        ("002272", "川润股份", "机械", "2008-06-15"),
    )
    c.commit()
    yield c
    c.close()


class TestCapitalFlowScore:
    """Test capital flow sub-score."""

    def test_neutral_without_data(self, conn):
        score, _ = compute_capital_flow_score(conn, "000001", "2026-01-01")
        assert 0.0 <= score <= 1.0

    def test_with_positive_inflow(self, conn):
        conn.execute(
            """INSERT INTO capital_flow_daily
               (stock_code, trading_date, main_net_inflow, large_order_inflow, super_large_inflow, retail_outflow)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("000001", "2026-01-01", 1000, 3000, 2000, 1000),
        )
        conn.commit()
        score, _ = compute_capital_flow_score(conn, "000001", "2026-01-01")
        assert score > 0.5  # net inflow should score above neutral

    def test_with_negative_inflow(self, conn):
        conn.execute(
            """INSERT INTO capital_flow_daily
               (stock_code, trading_date, main_net_inflow, large_order_inflow, super_large_inflow, retail_outflow)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("000001", "2026-01-01", -1000, 1000, 1000, 4000),
        )
        conn.commit()
        score, _ = compute_capital_flow_score(conn, "000001", "2026-01-01")
        assert score < 0.5  # net outflow should score below neutral


class TestSectorHeat:
    """Test sector heat sub-score."""

    def test_neutral_without_data(self, conn):
        score, _ = compute_sector_heat(conn, "000001", "2026-01-01")
        assert 0.0 <= score <= 1.0

    def test_with_theme_signal(self, conn):
        conn.execute(
            """INSERT INTO sector_theme_signals
               (industry, trading_date, theme_strength, sector_return_pct, relative_strength_rank, volume_surge, catalyst_count, summary)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("银行", "2026-01-01", 0.75, 0.02, 5, 1.2, 1, "test"),
        )
        conn.commit()
        score, _ = compute_sector_heat(conn, "000001", "2026-01-01")
        assert score == pytest.approx(0.75, abs=0.01)


class TestChipStructure:
    """Test chip structure sub-score."""

    def test_neutral_without_data(self, conn):
        score, _ = compute_chip_structure_score(conn, "000001", "2026-01-01")
        assert 0.0 <= score <= 1.0

    def test_with_uptrend_prices(self, conn):
        # Insert 20 days of uptrending data
        import datetime
        base = datetime.date(2026, 1, 1)
        for i in range(20):
            d = (base - datetime.timedelta(days=19 - i)).isoformat()
            close = 10.0 + i * 0.3  # steady uptrend
            vol = 1000000 + (5 if i >= 15 else 0) * 100000
            conn.execute(
                "INSERT INTO daily_prices (stock_code, trading_date, open, high, low, close, volume, prev_close) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("000001", d, close - 0.1, close + 0.2, close - 0.2, close, vol, close - 0.3),
            )
        conn.commit()
        score, _ = compute_chip_structure_score(conn, "000001", "2026-01-01")
        assert 0.0 <= score <= 1.0


class TestShareholderTrend:
    """Test shareholder trend sub-score."""

    def test_neutral_without_table(self, conn):
        # shareholder_data table may not exist
        score, _ = compute_shareholder_trend_score(conn, "000001", "2026-01-01")
        assert 0.0 <= score <= 1.0


class TestCompositeScore:
    """Test the composite sentiment scorer."""

    def test_returns_score_object(self, conn):
        result = score_announcement_sentiment(
            conn, "000001", "2026-01-01", "earnings_beat"
        )
        assert isinstance(result, SentimentScore)
        assert result.stock_code == "000001"
        assert 0.0 <= result.composite <= 1.0

    def test_type_bonus(self, conn):
        """M&A should get higher bonus than tech breakthrough."""
        ma = score_announcement_sentiment(conn, "000001", "2026-01-01", "m_and_a")
        tech = score_announcement_sentiment(conn, "000001", "2026-01-01", "tech_breakthrough")
        # With same sub-scores, M&A composite should be >= tech
        assert ma.composite >= tech.composite - 0.01  # allow rounding

    def test_opportunity_type(self, conn):
        result = score_announcement_sentiment(
            conn, "000001", "2026-01-01", "large_order"
        )
        assert result.opportunity_type in ("sector_leader", "breakout", "event_driven")


class TestSectorHeatIndex:
    """Test sector heat index refresh."""

    def test_refresh_creates_entries(self, conn):
        refresh_sector_heat_index(conn, "2026-01-01")
        count = conn.execute(
            "SELECT COUNT(*) FROM sector_heat_index WHERE trading_date='2026-01-01'"
        ).fetchone()[0]
        # Should have at least entries for seeded stocks' industries
        assert count >= 1
