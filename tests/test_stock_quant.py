from __future__ import annotations

import pytest

from stock_select.db import connect, init_db
from stock_select.stock_quant import (
    analyze_leader_comparison,
    analyze_limit_up_chain,
    analyze_moving_average,
    analyze_volume,
    build_stock_quant_report,
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
    # Seed 20 trading days
    for i in range(20):
        d = f"2024-01-{i + 1:02d}"
        conn.execute(
            "INSERT OR IGNORE INTO trading_days (trading_date, is_open) VALUES (?, ?)",
            (d, 1),
        )
    # Day 1-10: normal volume, close increasing
    for i in range(10):
        d = f"2024-01-{i + 1:02d}"
        close = 10.0 + i * 0.5
        conn.execute(
            "INSERT INTO daily_prices (stock_code, trading_date, open, high, low, close, volume, amount, is_limit_up, is_limit_down) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("000001.SZ", d, close - 0.5, close + 0.5, close - 1.0, close, 10000, 100000, 0, 0),
        )
    # Day 11-19: high volume (double), limit up on day 20
    for i in range(10, 19):
        d = f"2024-01-{i + 1:02d}"
        close = 10.0 + i * 0.5
        conn.execute(
            "INSERT INTO daily_prices (stock_code, trading_date, open, high, low, close, volume, amount, is_limit_up, is_limit_down) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("000001.SZ", d, close - 0.5, close + 0.5, close - 1.0, close, 20000, 200000, 0, 0),
        )
    # Day 20: limit up
    conn.execute(
        "INSERT INTO daily_prices (stock_code, trading_date, open, high, low, close, volume, amount, is_limit_up, is_limit_down) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("000001.SZ", "2024-01-20", 19.0, 20.9, 19.0, 20.9, 30000, 300000, 1, 0),
    )
    # Another stock in same sector
    for i in range(20):
        d = f"2024-01-{i + 1:02d}"
        close = 8.0 + i * 0.3
        conn.execute(
            "INSERT INTO daily_prices (stock_code, trading_date, open, high, low, close, volume, amount, is_limit_up, is_limit_down) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("600000.SH", d, close - 0.3, close + 0.3, close - 0.6, close, 5000, 40000, 0, 0),
        )
    conn.commit()


def test_analyze_volume(db):
    _seed_data(db)
    result = analyze_volume(db, "000001.SZ", "2024-01-20")
    assert result is not None
    assert result.today_volume == 30000
    assert result.avg_volume_5d > 0
    # Today volume 30000 vs avg ~20000 = 1.5x
    assert result.volume_ratio_5d == pytest.approx(1.5, abs=0.2)
    assert result.trend in ("放量", "大幅放量")


def test_analyze_moving_average(db):
    _seed_data(db)
    result = analyze_moving_average(db, "000001.SZ", "2024-01-20")
    assert result is not None
    assert result.close == 20.9
    assert result.ma5 > 0
    assert result.ma10 > 0
    assert result.ma20 > 0
    # Close is above all MAs (upward trend)
    assert result.position_vs_ma5 > 0
    assert result.trend in ("多头排列", "短期强势")


def test_analyze_limit_up_chain(db):
    _seed_data(db)
    result = analyze_limit_up_chain(db, "000001.SZ", "2024-01-20")
    assert result is not None
    assert result.is_limit_up_today is True
    assert result.current_days == 1
    assert result.max_days_20d == 1


def test_analyze_leader_comparison(db):
    _seed_data(db)
    result = analyze_leader_comparison(db, "600000.SH", "2024-01-20")
    assert result is not None
    assert result.leader_code == "000001.SZ"
    assert result.leader_name == "平安银行"
    # 000001 return ~10%, 600000 return ~3.75%
    assert result.return_gap < 0


def test_build_stock_quant_report(db):
    _seed_data(db)
    report = build_stock_quant_report(db, "000001.SZ", "2024-01-20")
    assert report is not None
    assert report.stock_code == "000001.SZ"
    assert report.volume_analysis is not None
    assert report.moving_average is not None
    assert report.limit_up_chain is not None


def test_empty_history_returns_none(db):
    conn = db
    conn.execute(
        "INSERT INTO stocks (stock_code, name, industry, listing_status) VALUES (?, ?, ?, ?)",
        ("000001.SZ", "A", "银行", "active"),
    )
    conn.commit()
    result = analyze_volume(conn, "000001.SZ", "2024-01-20")
    assert result is None
