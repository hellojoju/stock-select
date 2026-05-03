"""全市场概览数据：涨跌家数、涨跌停统计、主要指数行情。

优先从数据库读取，缺失时实时从 AkShare 拉取并落库。
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, timedelta

from .db import init_db

logger = logging.getLogger(__name__)

# 有效数据的最小涨跌家数阈值（低于此值说明只查了少量个股，不算全市场数据）
_MIN_MARKET_COUNT = 100


def _has_cached_breadth(conn: sqlite3.Connection, trading_date: str) -> dict | None:
    """Return cached market breadth if it looks like real full-market data."""
    row = conn.execute(
        "SELECT * FROM market_overview_daily WHERE trading_date = ?",
        (trading_date,),
    ).fetchone()
    if row is None:
        return None
    total = (row["advance_count"] or 0) + (row["decline_count"] or 0)
    if total < _MIN_MARKET_COUNT:
        return None  # stale/insufficient, refetch
    return dict(row)


def _fetch_from_akshare(trading_date: str) -> dict:
    """Pull full-market breadth data from AkShare."""
    import akshare as ak  # type: ignore[import-not-found]

    date_token = trading_date.replace("-", "")
    result: dict = {
        "trading_date": trading_date,
        "advance_count": 0,
        "decline_count": 0,
        "flat_count": 0,
        "limit_up_count": 0,
        "limit_down_count": 0,
        "suspended_count": 0,
        "activity_pct": 0.0,
        "index_data": {},
    }

    # 1. 市场活跃度（涨跌家数、涨停跌停）
    try:
        df = ak.stock_market_activity_legu()
        kv = {}
        for _, item in df.iterrows():
            key = str(item["item"]).strip()
            val = item["value"]
            kv[key] = val

        result["advance_count"] = int(kv.get("上涨", 0))
        result["decline_count"] = int(kv.get("下跌", 0))
        result["flat_count"] = int(kv.get("平盘", 0))
        result["limit_up_count"] = int(kv.get("涨停", 0))
        result["limit_down_count"] = int(kv.get("跌停", 0))
        result["suspended_count"] = int(kv.get("停牌", 0))
        raw = kv.get("活跃度", "0%")
        if isinstance(raw, str) and "%" in raw:
            result["activity_pct"] = float(raw.replace("%", ""))
    except Exception as e:
        logger.warning("Failed to fetch market activity from AkShare: %s", e)

    # 2. 主要指数日线（用 BaoStock，更稳定）
    # BaoStock 只返回历史数据，取最近 5 个交易日的数据
    lookback_end = (datetime.strptime(trading_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    lookback_start = (datetime.strptime(trading_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")

    try:
        import baostock as bs  # type: ignore[import-not-found]

        index_bs_map = {
            "sh": "sh.000001",
            "sz": "sz.399001",
            "cyb": "sz.399006",
        }
        lg = bs.login()
        for label, bs_code in index_bs_map.items():
            try:
                rs = bs.query_history_k_data_plus(
                    bs_code, "date,open,high,low,close",
                    start_date=lookback_start, end_date=lookback_end,
                    frequency="d",
                )
                # 取不超过目标日期的最新一条
                best_row = None
                while rs.next():
                    row_data = rs.get_row_data()
                    if row_data and row_data[0] and row_data[0] <= trading_date:
                        best_row = row_data
                if best_row:
                    result["index_data"][label] = {
                        "open": float(best_row[1]) if best_row[1] else 0,
                        "close": float(best_row[4]) if best_row[4] else 0,
                        "high": float(best_row[2]) if best_row[2] else 0,
                        "low": float(best_row[3]) if best_row[3] else 0,
                    }
            except Exception as e:
                logger.warning("Failed to fetch BaoStock index %s: %s", bs_code, e)
        bs.logout()
    except Exception as e:
        logger.warning("Failed to connect BaoStock for index data: %s", e)

    return result


def ensure_market_breadth(conn: sqlite3.Connection, trading_date: str) -> dict:
    """Return market breadth data for *trading_date*, fetching from API if missing.

    Note: AkShare's market activity API only returns real-time (today's) data,
    so API fetch is only attempted for today's date.
    """
    init_db(conn)
    cached = _has_cached_breadth(conn, trading_date)
    if cached is not None:
        logger.info("Using cached market breadth for %s", trading_date)
        return cached

    # AkShare 只返回当天实时数据，历史日期跳过 API 调用
    today_str = date.today().isoformat()
    if trading_date != today_str:
        logger.info("Skipping API fetch for historical date %s (only today's data available via API)", trading_date)
        return {"trading_date": trading_date, "advance_count": 0, "decline_count": 0,
                "flat_count": 0, "limit_up_count": 0, "limit_down_count": 0, "index_data": {}}

    logger.info("Fetching market breadth from AkShare for %s", trading_date)
    data = _fetch_from_akshare(trading_date)

    # 保存到 market_overview_daily
    conn.execute(
        """
        INSERT INTO market_overview_daily (
            trading_date, advance_count, decline_count, flat_count,
            limit_up_count, limit_down_count
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(trading_date) DO UPDATE SET
            advance_count = excluded.advance_count,
            decline_count = excluded.decline_count,
            flat_count = excluded.flat_count,
            limit_up_count = excluded.limit_up_count,
            limit_down_count = excluded.limit_down_count
        """,
        (
            trading_date,
            data["advance_count"],
            data["decline_count"],
            data["flat_count"],
            data["limit_up_count"],
            data["limit_down_count"],
        ),
    )

    # 保存指数数据到 index_prices
    index_code_map = {"sh": "000001.SH", "sz": "399001.SZ", "cyb": "399006.SZ"}
    for label, idx in data.get("index_data", {}).items():
        idx_code = index_code_map.get(label)
        if idx_code and idx.get("open") and idx.get("close"):
            conn.execute(
                """
                INSERT INTO index_prices (index_code, trading_date, open, high, low, close, volume, amount, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(index_code, trading_date) DO UPDATE SET
                    open = excluded.open, high = excluded.high, low = excluded.low,
                    close = excluded.close, volume = excluded.volume, amount = excluded.amount
                """,
                (
                    idx_code, trading_date,
                    idx["open"], idx.get("high", 0), idx.get("low", 0), idx["close"],
                    0, 0, "akshare",
                ),
            )

    conn.commit()

    return data
