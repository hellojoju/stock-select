from __future__ import annotations

import pytest

from stock_select.data_ingestion import (
    DemoProvider,
    sync_daily_prices,
    sync_stock_universe,
    sync_trading_calendar,
)
from stock_select.db import connect, init_db


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    init_db(conn)
    yield conn
    conn.close()


def test_sync_stock_universe_idempotent(db):
    provider = DemoProvider()
    sync_stock_universe(db, providers=[provider])
    count1 = db.execute("SELECT COUNT(*) as cnt FROM stocks").fetchone()["cnt"]
    sync_stock_universe(db, providers=[provider])
    count2 = db.execute("SELECT COUNT(*) as cnt FROM stocks").fetchone()["cnt"]
    assert count1 == count2


def test_sync_trading_calendar_idempotent(db):
    provider = DemoProvider()
    sync_trading_calendar(db, "2024-01-01", "2024-01-15", providers=[provider])
    count1 = db.execute("SELECT COUNT(*) as cnt FROM trading_days").fetchone()["cnt"]
    sync_trading_calendar(db, "2024-01-01", "2024-01-15", providers=[provider])
    count2 = db.execute("SELECT COUNT(*) as cnt FROM trading_days").fetchone()["cnt"]
    assert count1 == count2


def test_sync_daily_prices_idempotent(db):
    provider = DemoProvider()
    sync_stock_universe(db, providers=[provider])
    sync_daily_prices(db, "2024-01-15", providers=[provider])
    count1 = db.execute("SELECT COUNT(*) as cnt FROM source_daily_prices").fetchone()["cnt"]
    sync_daily_prices(db, "2024-01-15", providers=[provider])
    count2 = db.execute("SELECT COUNT(*) as cnt FROM source_daily_prices").fetchone()["cnt"]
    assert count1 == count2
