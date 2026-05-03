from __future__ import annotations

import pytest

from stock_select.db import connect, init_db
from stock_select.sector_analysis import (
    SectorAnalysis,
    StockInSector,
    analyze_all_sectors,
    analyze_sector,
    get_sector_analysis,
    get_top_sectors,
    save_sector_analysis,
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
        ("600000.SH", "浦发银行", "银行", "active"),
    )
    conn.execute(
        "INSERT INTO stocks (stock_code, name, industry, listing_status) VALUES (?, ?, ?, ?)",
        ("000002.SZ", "万科A", "房地产", "active"),
    )
    conn.execute(
        "INSERT INTO stocks (stock_code, name, industry, listing_status) VALUES (?, ?, ?, ?)",
        ("600048.SH", "保利发展", "房地产", "active"),
    )
    conn.execute(
        "INSERT INTO trading_days (trading_date, is_open) VALUES (?, ?)",
        ("2024-01-15", 1),
    )
    # Bank sector: 000001 +2.5%, 600000 -6.25%
    conn.execute(
        "INSERT INTO daily_prices (stock_code, trading_date, open, high, low, close, volume, amount, is_limit_up, is_limit_down) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("000001.SZ", "2024-01-15", 12.0, 12.5, 11.8, 12.3, 50000, 600000, 0, 0),
    )
    conn.execute(
        "INSERT INTO daily_prices (stock_code, trading_date, open, high, low, close, volume, amount, is_limit_up, is_limit_down) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("600000.SH", "2024-01-15", 8.0, 8.0, 7.5, 7.5, 30000, 225000, 0, 1),
    )
    # Real estate: 000002 +10% (limit up), 600048 +5%
    conn.execute(
        "INSERT INTO daily_prices (stock_code, trading_date, open, high, low, close, volume, amount, is_limit_up, is_limit_down) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("000002.SZ", "2024-01-15", 15.0, 16.5, 14.9, 16.5, 80000, 1320000, 1, 0),
    )
    conn.execute(
        "INSERT INTO daily_prices (stock_code, trading_date, open, high, low, close, volume, amount, is_limit_up, is_limit_down) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("600048.SH", "2024-01-15", 10.0, 10.5, 9.9, 10.5, 40000, 420000, 0, 0),
    )
    conn.commit()


def test_analyze_sector_real_estate(db):
    _seed_data(db)
    result = analyze_sector(db, "2024-01-15", "房地产")

    assert result.trading_date == "2024-01-15"
    assert result.sector_name == "房地产"
    # (10% + 5%) / 2 = 7.5%
    assert result.sector_return_pct == pytest.approx(7.5, abs=0.1)
    assert result.stock_count == 2
    assert result.advance_ratio == 1.0
    assert result.leader_stock == "000002.SZ"
    assert result.leader_return_pct == pytest.approx(10.0, abs=0.1)
    assert result.team_complete is False  # no mid-tier + followers (only 2 stocks)


def test_analyze_sector_bank(db):
    _seed_data(db)
    result = analyze_sector(db, "2024-01-15", "银行")

    assert result.sector_name == "银行"
    # (2.5% + -6.25%) / 2 = -1.875%
    assert result.sector_return_pct == pytest.approx(-1.88, abs=0.1)
    assert result.stock_count == 2
    assert result.advance_ratio == 0.5
    assert result.leader_stock == "000001.SZ"


def test_analyze_all_sectors(db):
    _seed_data(db)
    results = analyze_all_sectors(db, "2024-01-15", limit=5)

    assert len(results) == 2
    assert results[0].sector_name == "房地产"
    assert results[1].sector_name == "银行"


def test_save_and_get_sector_analysis(db):
    _seed_data(db)
    result = analyze_sector(db, "2024-01-15", "房地产")
    save_sector_analysis(db, result)

    loaded = get_sector_analysis(db, "2024-01-15", "房地产")
    assert loaded is not None
    assert loaded.sector_name == "房地产"
    assert loaded.leader_stock == "000002.SZ"


def test_get_top_sectors(db):
    _seed_data(db)
    for sector in ["房地产", "银行"]:
        result = analyze_sector(db, "2024-01-15", sector)
        save_sector_analysis(db, result)

    top = get_top_sectors(db, "2024-01-15", limit=2)
    assert len(top) == 2
    assert top[0].sector_name == "房地产"


def test_get_missing_sector_analysis(db):
    result = get_sector_analysis(db, "2024-01-15", "不存在")
    assert result is None
