from __future__ import annotations

import pytest
import sys
import types

from stock_select.data_ingestion import (
    AkShareProvider,
    BaoStockProvider,
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


def test_akshare_fundamentals_match_contract(monkeypatch):
    pd = pytest.importorskip("pandas")

    fake_ak = types.SimpleNamespace(
        stock_individual_info_em=lambda symbol: pd.DataFrame(
            [{"item": "市盈率", "value": "12.5"}, {"item": "行业", "value": "银行"}]
        )
    )
    monkeypatch.setitem(sys.modules, "akshare", fake_ak)

    rows = AkShareProvider().fetch_fundamentals("2024-01-15", ["000001.SZ"])

    assert len(rows) == 1
    assert rows[0].stock_code == "000001.SZ"
    assert rows[0].as_of_date == "2024-01-15"
    assert rows[0].pe_percentile == 12.5


def test_baostock_event_fallback_matches_contract(monkeypatch):
    pd = pytest.importorskip("pandas")

    fake_ak = types.SimpleNamespace(
        stock_zh_a_disclosure_report_cninfo=lambda symbol, start_date, end_date: pd.DataFrame(
            [{"公告标题": "关于重大合同中标的公告", "公告时间": "2024-01-15"}]
        )
    )
    monkeypatch.setitem(sys.modules, "akshare", fake_ak)

    rows = BaoStockProvider().fetch_event_signals("2024-01-15", "2024-01-15", ["000001.SZ"])

    assert len(rows) == 1
    assert rows[0].event_id
    assert rows[0].trading_date == "2024-01-15"
    assert rows[0].published_at == "2024-01-15"
    assert rows[0].stock_code == "000001.SZ"
    assert rows[0].event_type == "major_contract"
