from __future__ import annotations

import pytest

from stock_select.db import connect, init_db
from stock_select.market_overview import (
    MarketOverview,
    build_market_overview,
    generate_market_overview,
    get_market_overview,
    save_market_overview,
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
    conn.execute(
        """
        INSERT INTO index_prices (index_code, trading_date, open, high, low, close, volume, amount)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("000001.SH", "2024-01-15", 2800.0, 2850.0, 2790.0, 2828.0, 1000, 50000),
    )
    conn.execute(
        """
        INSERT INTO index_prices (index_code, trading_date, open, high, low, close, volume, amount)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("399006.SZ", "2024-01-15", 1800.0, 1820.0, 1790.0, 1818.0, 800, 30000),
    )
    conn.execute(
        """
        INSERT INTO daily_prices (stock_code, trading_date, open, high, low, close, volume, amount, is_limit_up, is_limit_down)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("000001.SZ", "2024-01-15", 12.0, 12.5, 11.8, 12.3, 50000, 600000, 0, 0),
    )
    conn.execute(
        """
        INSERT INTO daily_prices (stock_code, trading_date, open, high, low, close, volume, amount, is_limit_up, is_limit_down)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("000002.SZ", "2024-01-15", 15.0, 16.5, 14.9, 16.5, 80000, 1320000, 1, 0),
    )
    conn.execute(
        """
        INSERT INTO daily_prices (stock_code, trading_date, open, high, low, close, volume, amount, is_limit_up, is_limit_down)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("600000.SH", "2024-01-15", 8.0, 8.0, 7.5, 7.5, 30000, 225000, 0, 1),
    )
    conn.execute(
        """
        INSERT INTO sector_theme_signals (trading_date, industry, sector_return_pct, relative_strength_rank, volume_surge, theme_strength, catalyst_count, summary)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("2024-01-15", "银行", 2.5, 1, 1.2, 0.8, 2, "银行板块上涨"),
    )
    conn.execute(
        """
        INSERT INTO sector_theme_signals (trading_date, industry, sector_return_pct, relative_strength_rank, volume_surge, theme_strength, catalyst_count, summary)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("2024-01-15", "房地产", 1.8, 2, 1.1, 0.7, 1, "房地产板块上涨"),
    )
    conn.commit()


def test_build_market_overview(db):
    _seed_data(db)
    overview = build_market_overview(db, "2024-01-15")

    assert overview.trading_date == "2024-01-15"
    # 000001.SH: (2828 - 2800) / 2800 = 1.0%
    assert overview.sh_return == pytest.approx(1.0, rel=0.01)
    # 399006.SZ: (1818 - 1800) / 1800 = 1.0%
    assert overview.cyb_return == pytest.approx(1.0, rel=0.01)
    # 000002.SZ 涨停涨10%，000001.SZ 涨2.5%，600000.SH 跌6.25%
    assert overview.advance_count == 2
    assert overview.decline_count == 1
    assert overview.flat_count == 0
    assert overview.limit_up_count == 1
    assert overview.limit_down_count == 1
    assert len(overview.top_volume_stocks) == 3
    assert overview.top_volume_stocks[0].stock_code == "000002.SZ"
    assert len(overview.top_amount_stocks) == 3
    assert overview.top_amount_stocks[0].stock_code == "000002.SZ"
    # 小盘指数 399006 涨幅1%，大盘指数 000001 涨幅1% → 均衡
    assert overview.style_preference in ("balanced", "small_cap", "large_cap")
    assert len(overview.main_sectors) == 2
    assert overview.main_sectors[0].sector_name == "银行"


def test_save_and_get_market_overview(db):
    _seed_data(db)
    overview = build_market_overview(db, "2024-01-15")
    save_market_overview(db, overview)

    loaded = get_market_overview(db, "2024-01-15")
    assert loaded is not None
    assert loaded.advance_count == 2
    assert loaded.limit_up_count == 1
    assert len(loaded.top_volume_stocks) == 3


def test_generate_market_overview(db):
    _seed_data(db)
    overview = generate_market_overview(db, "2024-01-15")
    assert overview.advance_count == 2
    loaded = get_market_overview(db, "2024-01-15")
    assert loaded is not None


def test_get_missing_market_overview(db):
    result = get_market_overview(db, "2024-01-01")
    assert result is None
