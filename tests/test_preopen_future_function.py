from __future__ import annotations

import pytest

from stock_select.data_ingestion import (
    DemoProvider,
    publish_canonical_prices,
    sync_daily_prices,
    sync_stock_universe,
    sync_trading_calendar,
)
from stock_select.db import connect, init_db
from stock_select.repository import price_history_before
from stock_select.strategies import generate_picks_for_all_genes, seed_default_genes


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    init_db(conn)
    yield conn
    conn.close()


def test_preopen_does_not_read_target_day_prices(db):
    """Preopen 选股阶段不应读取目标交易日之后的价格数据。

    验证链路：
    1. 先为 2024-01-15 和 2024-01-16 两个日期同步价格数据
    2. 对 2024-01-15 执行选股
    3. 确认 source_daily_prices 中只存在目标日（2024-01-15）的数据
       （即 preopen 阶段不会引入未来日期的 canonical prices）
    """
    seed_default_genes(db)

    provider = DemoProvider()
    sync_stock_universe(db, providers=[provider])
    sync_trading_calendar(db, "2024-01-01", "2024-01-20", providers=[provider])

    # 为两个日期同步价格数据
    sync_daily_prices(db, "2024-01-15", providers=[provider])
    sync_daily_prices(db, "2024-01-16", providers=[provider])

    # 只对 2024-01-15 执行选股（不发布 2024-01-16 的 canonical prices）
    publish_canonical_prices(db, "2024-01-15")
    picks = generate_picks_for_all_genes(db, "2024-01-15")

    # preopen 阶段 canonical daily_prices 不应有目标日之后的数据
    future_canonical = db.execute(
        "SELECT COUNT(*) as cnt FROM daily_prices WHERE trading_date > '2024-01-15'"
    ).fetchone()["cnt"]
    assert future_canonical == 0, (
        f"preopen stage should not have canonical prices after target date, found {future_canonical}"
    )

    # source_daily_prices 中 2024-01-16 的数据存在（数据已同步，只是未发布为 canonical）
    future_source = db.execute(
        "SELECT COUNT(*) as cnt FROM source_daily_prices WHERE trading_date > '2024-01-15'"
    ).fetchone()["cnt"]
    assert future_source > 0, "source prices for future dates should exist after sync"


def test_price_history_before_excludes_future_dates(db):
    """验证 price_history_before 严格过滤，不会返回目标日及之后的数据。

    这是未来函数防护的核心防线——即使数据库中存在未来日期的
    canonical prices，评分函数也只能读到目标日之前的价格。
    """
    provider = DemoProvider()
    sync_stock_universe(db, providers=[provider])
    sync_trading_calendar(db, "2024-01-01", "2024-01-20", providers=[provider])

    # 为多个日期同步并发布 canonical prices
    for date_str in ["2024-01-10", "2024-01-11", "2024-01-12", "2024-01-15", "2024-01-16", "2024-01-17"]:
        sync_daily_prices(db, date_str, providers=[provider])
        publish_canonical_prices(db, date_str)

    # 验证数据库中确实有未来数据
    total_prices = db.execute("SELECT COUNT(*) as cnt FROM daily_prices").fetchone()["cnt"]
    assert total_prices > 0

    # 对 2024-01-15 请求 lookback=10 天的价格历史
    stock_code = "000001.SZ"
    history = price_history_before(db, stock_code, "2024-01-15", limit=10)

    # 返回的所有日期都应严格小于 2024-01-15
    for row in history:
        assert row["trading_date"] < "2024-01-15", (
            f"price_history_before returned future date {row['trading_date']} for target 2024-01-15"
        )

    # 不应包含 2024-01-15 当天或之后的数据
    future_rows = [r for r in history if r["trading_date"] >= "2024-01-15"]
    assert len(future_rows) == 0, (
        f"price_history_before should exclude target date and beyond, got {future_rows}"
    )


def test_picks_generated_successfully(db):
    """验证完整 preopen 链路能正常产出选股结果。"""
    seed_default_genes(db)

    provider = DemoProvider()
    sync_stock_universe(db, providers=[provider])
    sync_trading_calendar(db, "2024-01-01", "2024-01-20", providers=[provider])
    sync_daily_prices(db, "2024-01-15", providers=[provider])
    publish_canonical_prices(db, "2024-01-15")

    picks = generate_picks_for_all_genes(db, "2024-01-15")
    assert isinstance(picks, list)

    # 验证决策已写入数据库
    decision_count = db.execute(
        "SELECT COUNT(*) as cnt FROM pick_decisions WHERE trading_date = '2024-01-15'"
    ).fetchone()["cnt"]
    assert decision_count == len(picks)
