from __future__ import annotations

import pytest

from stock_select.db import connect, init_db
from stock_select.sentiment_cycle import (
    SentimentCycle,
    build_sentiment_cycle,
    generate_sentiment_cycle,
    get_sentiment_cycle,
    save_sentiment_cycle,
)


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    init_db(conn)
    yield conn
    conn.close()


def _seed_two_days(conn):
    conn.execute(
        "INSERT INTO stocks (stock_code, name, industry, listing_status) VALUES (?, ?, ?, ?)",
        ("000001.SZ", "平安银行", "银行", "active"),
    )
    conn.execute(
        "INSERT INTO stocks (stock_code, name, industry, listing_status) VALUES (?, ?, ?, ?)",
        ("000002.SZ", "万科A", "房地产", "active"),
    )
    conn.execute(
        "INSERT INTO stocks (stock_code, name, industry, listing_status) VALUES (?, ?, ?, ?)",
        ("600000.SH", "浦发银行", "银行", "active"),
    )
    # Day 1: 2024-01-14
    conn.execute(
        "INSERT INTO trading_days (trading_date, is_open) VALUES (?, ?)",
        ("2024-01-14", 1),
    )
    conn.execute(
        """
        INSERT INTO daily_prices (stock_code, trading_date, open, high, low, close, volume, amount, is_limit_up, is_limit_down)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("000001.SZ", "2024-01-14", 12.0, 12.0, 12.0, 12.0, 50000, 600000, 0, 0),
    )
    conn.execute(
        """
        INSERT INTO daily_prices (stock_code, trading_date, open, high, low, close, volume, amount, is_limit_up, is_limit_down)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("000002.SZ", "2024-01-14", 15.0, 16.5, 14.9, 16.5, 80000, 1320000, 1, 0),
    )
    conn.execute(
        """
        INSERT INTO daily_prices (stock_code, trading_date, open, high, low, close, volume, amount, is_limit_up, is_limit_down)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("600000.SH", "2024-01-14", 8.0, 8.0, 7.5, 7.5, 30000, 225000, 0, 1),
    )
    # Day 2: 2024-01-15
    conn.execute(
        "INSERT INTO trading_days (trading_date, is_open) VALUES (?, ?)",
        ("2024-01-15", 1),
    )
    conn.execute(
        """
        INSERT INTO daily_prices (stock_code, trading_date, open, high, low, close, volume, amount, is_limit_up, is_limit_down)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("000001.SZ", "2024-01-15", 12.0, 12.3, 11.8, 12.3, 50000, 600000, 0, 0),
    )
    conn.execute(
        """
        INSERT INTO daily_prices (stock_code, trading_date, open, high, low, close, volume, amount, is_limit_up, is_limit_down)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("000002.SZ", "2024-01-15", 16.5, 18.15, 16.5, 18.15, 80000, 1320000, 1, 0),
    )
    conn.execute(
        """
        INSERT INTO daily_prices (stock_code, trading_date, open, high, low, close, volume, amount, is_limit_up, is_limit_down)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("600000.SH", "2024-01-15", 7.5, 7.5, 7.0, 7.0, 30000, 225000, 0, 1),
    )
    conn.commit()


def test_build_sentiment_cycle_basic(db):
    _seed_two_days(db)
    cycle = build_sentiment_cycle(db, "2024-01-15")

    assert cycle.trading_date == "2024-01-15"
    # 000001 涨 2.5%, 000002 涨停 10%, 600000 跌 6.67%
    assert cycle.advance_count == 2
    assert cycle.decline_count == 1
    assert cycle.limit_up_count == 1
    assert cycle.limit_down_count == 1
    # 000002 涨停且 close == high → seal_rate = 1.0
    assert cycle.seal_rate == 1.0
    # 000002 昨天涨停今天也涨停 → promotion
    assert cycle.promotion_rate == 1.0
    assert cycle.cycle_phase in ("回暖", "升温", "高潮")
    assert cycle.cycle_reason != ""


def test_build_sentiment_cycle_ice_point(db):
    """Test ice-point detection: very few advances, many limit downs."""
    conn = db
    conn.execute(
        "INSERT INTO stocks (stock_code, name, industry, listing_status) VALUES (?, ?, ?, ?)",
        ("000001.SZ", "A", "银行", "active"),
    )
    conn.execute(
        "INSERT INTO stocks (stock_code, name, industry, listing_status) VALUES (?, ?, ?, ?)",
        ("000002.SZ", "B", "房地产", "active"),
    )
    conn.execute(
        "INSERT INTO stocks (stock_code, name, industry, listing_status) VALUES (?, ?, ?, ?)",
        ("600000.SH", "C", "银行", "active"),
    )
    conn.execute(
        "INSERT INTO trading_days (trading_date, is_open) VALUES (?, ?)",
        ("2024-01-15", 1),
    )
    # All decline, no limit up
    conn.execute(
        "INSERT INTO daily_prices (stock_code, trading_date, open, high, low, close, volume, amount, is_limit_up, is_limit_down) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("000001.SZ", "2024-01-15", 10.0, 10.0, 9.0, 9.0, 1000, 9000, 0, 0),
    )
    conn.execute(
        "INSERT INTO daily_prices (stock_code, trading_date, open, high, low, close, volume, amount, is_limit_up, is_limit_down) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("000002.SZ", "2024-01-15", 20.0, 20.0, 18.0, 18.0, 2000, 36000, 0, 0),
    )
    conn.execute(
        "INSERT INTO daily_prices (stock_code, trading_date, open, high, low, close, volume, amount, is_limit_up, is_limit_down) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("600000.SH", "2024-01-15", 30.0, 30.0, 27.0, 27.0, 3000, 81000, 0, 0),
    )
    conn.commit()

    cycle = build_sentiment_cycle(conn, "2024-01-15")
    assert cycle.advance_count == 0
    assert cycle.decline_count == 3
    assert cycle.cycle_phase == "冰点"


def test_save_and_get_sentiment_cycle(db):
    _seed_two_days(db)
    cycle = build_sentiment_cycle(db, "2024-01-15")
    save_sentiment_cycle(db, cycle)

    loaded = get_sentiment_cycle(db, "2024-01-15")
    assert loaded is not None
    assert loaded.advance_count == 2
    assert loaded.cycle_phase == cycle.cycle_phase


def test_generate_sentiment_cycle(db):
    _seed_two_days(db)
    cycle = generate_sentiment_cycle(db, "2024-01-15")
    assert cycle.advance_count == 2
    loaded = get_sentiment_cycle(db, "2024-01-15")
    assert loaded is not None


def test_get_missing_sentiment_cycle(db):
    result = get_sentiment_cycle(db, "2024-01-01")
    assert result is None
