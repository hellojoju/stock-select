from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)
_MIN_MARKET_COUNT = 100


INDEX_CODES = {
    "sh": "000001.SH",
    "sz": "399001.SZ",
    "cyb": "399006.SZ",
    "bse": "899050.BJ",
}


@dataclass(frozen=True)
class TopStock:
    stock_code: str
    stock_name: str
    value: float


@dataclass(frozen=True)
class SectorLeader:
    sector_name: str
    return_pct: float


@dataclass(frozen=True)
class MarketOverview:
    trading_date: str
    sh_return: float | None = None
    sz_return: float | None = None
    cyb_return: float | None = None
    bse_return: float | None = None
    advance_count: int = 0
    decline_count: int = 0
    flat_count: int = 0
    limit_up_count: int = 0
    limit_down_count: int = 0
    top_volume_stocks: list[TopStock] = field(default_factory=list)
    top_amount_stocks: list[TopStock] = field(default_factory=list)
    style_preference: str = "unknown"
    main_sectors: list[SectorLeader] = field(default_factory=list)


def _return_pct(open_price: float, close: float) -> float:
    if open_price == 0:
        return 0.0
    return round((close - open_price) / open_price * 100, 2)


def _fetch_index_returns(conn: sqlite3.Connection, trading_date: str) -> dict[str, float | None]:
    result: dict[str, float | None] = {k: None for k in INDEX_CODES}
    rows = conn.execute(
        "SELECT index_code, open, close FROM index_prices WHERE trading_date = ?",
        (trading_date,),
    ).fetchall()
    code_map = {"000001.SH": "sh", "399001.SZ": "sz", "399006.SZ": "cyb", "899050.BJ": "bse"}
    for row in rows:
        key = code_map.get(row["index_code"])
        if key and row["open"]:
            result[key] = _return_pct(row["open"], row["close"])
    return result


def _count_distribution(conn: sqlite3.Connection, trading_date: str) -> tuple[int, int, int]:
    advance = 0
    decline = 0
    flat = 0
    rows = conn.execute(
        "SELECT open, close FROM daily_prices WHERE trading_date = ? AND is_suspended = 0",
        (trading_date,),
    ).fetchall()
    for row in rows:
        if row["open"] == 0 or row["close"] == 0:
            continue
        change = row["close"] - row["open"]
        if change > 0:
            advance += 1
        elif change < 0:
            decline += 1
        else:
            flat += 1
    return advance, decline, flat


def _count_limit_up_down(conn: sqlite3.Connection, trading_date: str) -> tuple[int, int]:
    up = conn.execute(
        "SELECT COUNT(*) as cnt FROM daily_prices WHERE trading_date = ? AND is_limit_up = 1",
        (trading_date,),
    ).fetchone()["cnt"]
    down = conn.execute(
        "SELECT COUNT(*) as cnt FROM daily_prices WHERE trading_date = ? AND is_limit_down = 1",
        (trading_date,),
    ).fetchone()["cnt"]
    return up, down


def _top_stocks(
    conn: sqlite3.Connection, trading_date: str, column: str, limit: int = 10
) -> list[TopStock]:
    rows = conn.execute(
        f"""
        SELECT dp.stock_code, s.name, dp.{column} as val
        FROM daily_prices dp
        LEFT JOIN stocks s ON dp.stock_code = s.stock_code
        WHERE dp.trading_date = ? AND dp.is_suspended = 0 AND dp.{column} > 0
        ORDER BY dp.{column} DESC
        LIMIT ?
        """,
        (trading_date, limit),
    ).fetchall()
    return [TopStock(r["stock_code"], r["name"] or "", float(r["val"])) for r in rows]


def _style_preference(conn: sqlite3.Connection, trading_date: str) -> str:
    large_cap_codes = ["000001.SH", "399001.SZ"]
    small_cap_codes = ["399006.SZ", "899050.BJ"]
    large_returns: list[float] = []
    small_returns: list[float] = []
    rows = conn.execute(
        "SELECT index_code, open, close FROM index_prices WHERE trading_date = ?",
        (trading_date,),
    ).fetchall()
    for row in rows:
        if row["open"] and row["close"]:
            ret = _return_pct(row["open"], row["close"])
            if row["index_code"] in large_cap_codes:
                large_returns.append(ret)
            elif row["index_code"] in small_cap_codes:
                small_returns.append(ret)
    if not large_returns or not small_returns:
        return "unknown"
    large_avg = sum(large_returns) / len(large_returns)
    small_avg = sum(small_returns) / len(small_returns)
    diff = small_avg - large_avg
    if diff > 0.5:
        return "small_cap"
    elif diff < -0.5:
        return "large_cap"
    return "balanced"


def _main_sectors(conn: sqlite3.Connection, trading_date: str, limit: int = 5) -> list[SectorLeader]:
    rows = conn.execute(
        """
        SELECT industry, sector_return_pct
        FROM sector_theme_signals
        WHERE trading_date = ?
        ORDER BY sector_return_pct DESC
        LIMIT ?
        """,
        (trading_date, limit),
    ).fetchall()
    return [SectorLeader(r["industry"], float(r["sector_return_pct"])) for r in rows]


def build_market_overview(
    conn: sqlite3.Connection, trading_date: str, *, api_fallback: bool = True
) -> MarketOverview:
    # 先从 AkShare 拉全市场概览（含涨跌家数、涨停跌停、指数）
    breadth: dict = {}
    if api_fallback:
        try:
            from .market_breadth import ensure_market_breadth

            breadth = ensure_market_breadth(conn, trading_date)
        except Exception:
            logger.warning("Failed to fetch market breadth, falling back to DB counts")

    # 涨跌家数：优先用 API 数据，否则退回到库内统计
    advance = breadth.get("advance_count", 0)
    decline = breadth.get("decline_count", 0)
    flat = breadth.get("flat_count", 0)
    if advance + decline < _MIN_MARKET_COUNT:
        # API 数据缺失，退回到库内统计（虽然只覆盖部分个股）
        advance, decline, flat = _count_distribution(conn, trading_date)

    # 涨跌停：同理
    limit_up = breadth.get("limit_up_count", 0)
    limit_down = breadth.get("limit_down_count", 0)
    if limit_up + limit_down == 0:
        limit_up, limit_down = _count_limit_up_down(conn, trading_date)

    # 指数收益：优先用 API 拉到的指数数据
    index_returns = _fetch_index_returns(conn, trading_date)
    api_index_data = breadth.get("index_data", {})
    for label, idx in api_index_data.items():
        if idx.get("open") and idx["open"] > 0 and idx.get("close") and idx["close"] > 0:
            index_returns[label] = _return_pct(idx["open"], idx["close"])

    top_volume = _top_stocks(conn, trading_date, "volume")
    top_amount = _top_stocks(conn, trading_date, "amount")
    style = _style_preference(conn, trading_date)
    sectors = _main_sectors(conn, trading_date)

    return MarketOverview(
        trading_date=trading_date,
        sh_return=index_returns.get("sh"),
        sz_return=index_returns.get("sz"),
        cyb_return=index_returns.get("cyb"),
        bse_return=index_returns.get("bse"),
        advance_count=advance,
        decline_count=decline,
        flat_count=flat,
        limit_up_count=limit_up,
        limit_down_count=limit_down,
        top_volume_stocks=top_volume,
        top_amount_stocks=top_amount,
        style_preference=style,
        main_sectors=sectors,
    )


def save_market_overview(conn: sqlite3.Connection, overview: MarketOverview) -> None:
    conn.execute(
        """
        INSERT INTO market_overview_daily (
            trading_date, sh_return, sz_return, cyb_return, bse_return,
            advance_count, decline_count, flat_count,
            limit_up_count, limit_down_count,
            top_volume_stocks, top_amount_stocks,
            style_preference, main_sectors
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(trading_date) DO UPDATE SET
            sh_return = excluded.sh_return,
            sz_return = excluded.sz_return,
            cyb_return = excluded.cyb_return,
            bse_return = excluded.bse_return,
            advance_count = excluded.advance_count,
            decline_count = excluded.decline_count,
            flat_count = excluded.flat_count,
            limit_up_count = excluded.limit_up_count,
            limit_down_count = excluded.limit_down_count,
            top_volume_stocks = excluded.top_volume_stocks,
            top_amount_stocks = excluded.top_amount_stocks,
            style_preference = excluded.style_preference,
            main_sectors = excluded.main_sectors,
            created_at = datetime('now')
        """,
        (
            overview.trading_date,
            overview.sh_return,
            overview.sz_return,
            overview.cyb_return,
            overview.bse_return,
            overview.advance_count,
            overview.decline_count,
            overview.flat_count,
            overview.limit_up_count,
            overview.limit_down_count,
            json.dumps([{"stock_code": s.stock_code, "stock_name": s.stock_name, "value": s.value} for s in overview.top_volume_stocks]),
            json.dumps([{"stock_code": s.stock_code, "stock_name": s.stock_name, "value": s.value} for s in overview.top_amount_stocks]),
            overview.style_preference,
            json.dumps([{"sector_name": s.sector_name, "return_pct": s.return_pct} for s in overview.main_sectors]),
        ),
    )
    conn.commit()


def get_market_overview(conn: sqlite3.Connection, trading_date: str) -> MarketOverview | None:
    row = conn.execute(
        "SELECT * FROM market_overview_daily WHERE trading_date = ?",
        (trading_date,),
    ).fetchone()
    if row is None:
        return None
    return MarketOverview(
        trading_date=row["trading_date"],
        sh_return=row["sh_return"],
        sz_return=row["sz_return"],
        cyb_return=row["cyb_return"],
        bse_return=row["bse_return"],
        advance_count=row["advance_count"] or 0,
        decline_count=row["decline_count"] or 0,
        flat_count=row["flat_count"] or 0,
        limit_up_count=row["limit_up_count"] or 0,
        limit_down_count=row["limit_down_count"] or 0,
        top_volume_stocks=[TopStock(s["stock_code"], s["stock_name"], s["value"]) for s in json.loads(row["top_volume_stocks"] or "[]")],
        top_amount_stocks=[TopStock(s["stock_code"], s["stock_name"], s["value"]) for s in json.loads(row["top_amount_stocks"] or "[]")],
        style_preference=row["style_preference"] or "unknown",
        main_sectors=[SectorLeader(s["sector_name"], s["return_pct"]) for s in json.loads(row["main_sectors"] or "[]")],
    )


def generate_market_overview(conn: sqlite3.Connection, trading_date: str) -> MarketOverview:
    overview = build_market_overview(conn, trading_date)
    save_market_overview(conn, overview)
    return overview
