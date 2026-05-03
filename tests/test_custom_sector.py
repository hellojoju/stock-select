from __future__ import annotations

import pytest

from stock_select.db import connect, init_db
from stock_select.custom_sector import (
    classify_all_custom_sectors,
    classify_large_amount,
    classify_limit_up_today,
    classify_unusual_10d,
    generate_custom_sectors,
    get_custom_sectors_for_stock,
    get_custom_sector_stocks,
)


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    init_db(conn)
    yield conn
    conn.close()


def _seed_data(conn):
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
    # Seed 10+ trading days for unusual_10d
    for i in range(15):
        d = f"2024-01-{i+1:02d}"
        conn.execute(
            "INSERT OR IGNORE INTO trading_days (trading_date, is_open) VALUES (?, ?)",
            (d, 1),
        )
    # Day 2024-01-15
    conn.execute(
        "INSERT INTO daily_prices (stock_code, trading_date, open, high, low, close, volume, amount, is_limit_up, is_limit_down) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("000001.SZ", "2024-01-15", 12.0, 12.5, 11.8, 12.3, 50000, 600000, 0, 0),
    )
    conn.execute(
        "INSERT INTO daily_prices (stock_code, trading_date, open, high, low, close, volume, amount, is_limit_up, is_limit_down) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("000002.SZ", "2024-01-15", 15.0, 16.5, 14.9, 16.5, 80000, 1320000000, 1, 0),
    )
    conn.execute(
        "INSERT INTO daily_prices (stock_code, trading_date, open, high, low, close, volume, amount, is_limit_up, is_limit_down) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("600000.SH", "2024-01-15", 8.0, 8.0, 7.5, 7.5, 30000, 225000, 0, 1),
    )
    # Day 2024-01-10: 000002 had limit-up
    conn.execute(
        "INSERT INTO daily_prices (stock_code, trading_date, open, high, low, close, volume, amount, is_limit_up, is_limit_down) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("000002.SZ", "2024-01-10", 13.0, 14.3, 12.9, 14.3, 70000, 1001000000, 1, 0),
    )
    conn.commit()


def test_classify_limit_up_today(db):
    _seed_data(db)
    result = classify_limit_up_today(db, "2024-01-15")
    assert len(result) == 1
    assert result[0].stock_code == "000002.SZ"
    assert result[0].amount == 1320000000


def test_classify_large_amount(db):
    _seed_data(db)
    result = classify_large_amount(db, "2024-01-15")
    assert len(result) == 1
    assert result[0].stock_code == "000002.SZ"
    assert result[0].amount == 1320000000


def test_classify_unusual_10d(db):
    _seed_data(db)
    result = classify_unusual_10d(db, "2024-01-15")
    # 000002 had limit-up on 2024-01-10 and amount > 8亿 on 2024-01-15
    assert len(result) == 1
    assert result[0].stock_code == "000002.SZ"


def test_classify_all_custom_sectors(db):
    _seed_data(db)
    sectors = classify_all_custom_sectors(db, "2024-01-15")
    keys = [s.sector_key for s in sectors]
    assert "limit_up_today" in keys
    assert "large_amount" in keys
    assert "unusual_10d" in keys


def test_generate_and_get_custom_sectors(db):
    _seed_data(db)
    generate_custom_sectors(db, "2024-01-15")

    tags = get_custom_sectors_for_stock(db, "2024-01-15", "000002.SZ")
    assert "limit_up_today" in tags
    assert "large_amount" in tags
    assert "unusual_10d" in tags

    stocks = get_custom_sector_stocks(db, "2024-01-15", "limit_up_today")
    assert len(stocks) == 1
    assert stocks[0].stock_code == "000002.SZ"


def test_no_custom_sectors_empty(db):
    conn = db
    conn.execute(
        "INSERT INTO stocks (stock_code, name, industry, listing_status) VALUES (?, ?, ?, ?)",
        ("000001.SZ", "A", "银行", "active"),
    )
    conn.execute(
        "INSERT INTO trading_days (trading_date, is_open) VALUES (?, ?)",
        ("2024-01-15", 1),
    )
    conn.execute(
        "INSERT INTO daily_prices (stock_code, trading_date, open, high, low, close, volume, amount, is_limit_up, is_limit_down) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("000001.SZ", "2024-01-15", 10.0, 10.1, 9.9, 10.0, 1000, 10000, 0, 0),
    )
    conn.commit()

    sectors = classify_all_custom_sectors(conn, "2024-01-15")
    assert len(sectors) == 0
