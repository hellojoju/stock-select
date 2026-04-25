from __future__ import annotations

import pytest

from stock_select.data_ingestion import publish_canonical_prices
from stock_select.db import connect, init_db


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    init_db(conn)
    conn.execute("INSERT INTO stocks(stock_code, name) VALUES ('000001.SZ', '平安银行')")
    conn.execute("INSERT INTO stocks(stock_code, name) VALUES ('600000.SH', '浦发银行')")
    conn.execute("INSERT INTO stocks(stock_code, name) VALUES ('000002.SZ', '万科A')")
    conn.execute("INSERT INTO stocks(stock_code, name) VALUES ('000003.SZ', '无数据')")
    conn.execute("INSERT INTO stocks(stock_code, name) VALUES ('000004.SZ', '双源缺失')")
    conn.commit()
    return conn


def setup_source_price(conn, source, stock_code, date, close):
    conn.execute(
        "INSERT OR REPLACE INTO source_daily_prices(source, stock_code, trading_date, open, high, low, close, volume, amount) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (source, stock_code, date, close * 0.99, close * 1.01, close * 0.98, close, 1000, 10000),
    )


# 规则 1: 双源一致 -> ok
def test_canonical_ok_when_sources_agree(db):
    date = "2024-01-15"
    setup_source_price(db, "akshare", "000001.SZ", date, close=10.00)
    setup_source_price(db, "baostock", "000001.SZ", date, close=10.02)  # 0.2% diff
    db.commit()
    publish_canonical_prices(db, date)
    row = db.execute(
        "SELECT * FROM daily_prices WHERE stock_code = '000001.SZ' AND trading_date = ?",
        (date,),
    ).fetchone()
    assert row is not None
    assert abs(row["close"] - 10.00) < 0.01
    check = db.execute(
        "SELECT status FROM price_source_checks WHERE stock_code = '000001.SZ'",
    ).fetchone()
    assert check["status"] == "ok"


# 规则 2: 双源差异大 -> warning
def test_canonical_warning_when_sources_disagree(db):
    date = "2024-01-15"
    setup_source_price(db, "akshare", "600000.SH", date, close=10.00)
    setup_source_price(db, "baostock", "600000.SH", date, close=10.50)  # 5% diff
    db.commit()
    publish_canonical_prices(db, date)
    check = db.execute(
        "SELECT status FROM price_source_checks WHERE stock_code = '600000.SH'",
    ).fetchone()
    assert check["status"] == "warning"


# 规则 3: 仅主源 -> warning
def test_canonical_warning_when_secondary_missing(db):
    date = "2024-01-15"
    setup_source_price(db, "akshare", "000002.SZ", date, close=15.00)
    db.commit()
    publish_canonical_prices(db, date)
    row = db.execute(
        "SELECT * FROM daily_prices WHERE stock_code = '000002.SZ'",
    ).fetchone()
    assert row is not None
    check = db.execute(
        "SELECT status FROM price_source_checks WHERE stock_code = '000002.SZ'",
    ).fetchone()
    assert check["status"] == "warning"


# 规则 4: 仅备源 -> missing_primary, 发布 BaoStock
def test_canonical_missing_primary_uses_secondary(db):
    date = "2024-01-15"
    setup_source_price(db, "baostock", "000003.SZ", date, close=8.00)
    db.commit()
    publish_canonical_prices(db, date)
    row = db.execute(
        "SELECT * FROM daily_prices WHERE stock_code = '000003.SZ'",
    ).fetchone()
    assert row is not None
    assert abs(row["close"] - 8.00) < 0.01
    check = db.execute(
        "SELECT status FROM price_source_checks WHERE stock_code = '000003.SZ'",
    ).fetchone()
    assert check["status"] == "missing_primary"


# 规则 5: 双源都无 -> 不发布
def test_canonical_no_publish_when_both_missing(db):
    date = "2024-01-15"
    publish_canonical_prices(db, date)
    row = db.execute(
        "SELECT * FROM daily_prices WHERE stock_code = '000004.SZ' AND trading_date = ?",
        (date,),
    ).fetchone()
    assert row is None


# 幂等性
def test_publish_is_idempotent(db):
    date = "2024-01-15"
    setup_source_price(db, "akshare", "000001.SZ", date, close=10.00)
    setup_source_price(db, "baostock", "000001.SZ", date, close=10.02)
    db.commit()
    publish_canonical_prices(db, date)
    publish_canonical_prices(db, date)  # second run
    count = db.execute(
        "SELECT COUNT(*) as cnt FROM daily_prices WHERE stock_code = '000001.SZ'",
    ).fetchone()["cnt"]
    assert count == 1
