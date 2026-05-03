from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CustomSectorEntry:
    stock_code: str
    stock_name: str
    return_pct: float
    turnover_rate: float | None = None
    volume: float = 0.0
    amount: float = 0.0
    limit_up_days: int = 0


@dataclass(frozen=True)
class CustomSector:
    sector_key: str
    sector_name: str
    stocks: list[CustomSectorEntry]
    criteria: str


SECTOR_CONFIG: dict[str, dict[str, Any]] = {
    "limit_up_today": {
        "name": "当日涨停",
        "criteria": "今日涨停的股票",
    },
    "large_amount": {
        "name": "大成交额",
        "criteria": "成交额超过10亿元",
    },
    "unusual_10d": {
        "name": "十日异动",
        "criteria": "近10天内有涨停且成交额超过8亿",
    },
}


def _fetch_stock_detail(
    conn: sqlite3.Connection, trading_date: str, stock_code: str
) -> CustomSectorEntry | None:
    row = conn.execute(
        """
        SELECT dp.stock_code, s.name, dp.open, dp.close, dp.volume, dp.amount,
               dp.is_limit_up
        FROM daily_prices dp
        LEFT JOIN stocks s ON dp.stock_code = s.stock_code
        WHERE dp.trading_date = ? AND dp.stock_code = ?
        """,
        (trading_date, stock_code),
    ).fetchone()
    if row is None:
        return None
    open_p = row["open"] or 0
    close = row["close"] or 0
    return_pct = round((close - open_p) / open_p * 100, 2) if open_p > 0 else 0.0
    return CustomSectorEntry(
        stock_code=row["stock_code"],
        stock_name=row["name"] or "",
        return_pct=return_pct,
        volume=float(row["volume"] or 0),
        amount=float(row["amount"] or 0),
        limit_up_days=0,
    )


def classify_limit_up_today(
    conn: sqlite3.Connection, trading_date: str
) -> list[CustomSectorEntry]:
    rows = conn.execute(
        """
        SELECT dp.stock_code, s.name, dp.open, dp.close, dp.volume, dp.amount
        FROM daily_prices dp
        LEFT JOIN stocks s ON dp.stock_code = s.stock_code
        WHERE dp.trading_date = ? AND dp.is_limit_up = 1 AND dp.is_suspended = 0
        ORDER BY dp.amount DESC
        """,
        (trading_date,),
    ).fetchall()
    return [
        CustomSectorEntry(
            stock_code=r["stock_code"],
            stock_name=r["name"] or "",
            return_pct=round((r["close"] - r["open"]) / r["open"] * 100, 2) if r["open"] else 0.0,
            volume=float(r["volume"] or 0),
            amount=float(r["amount"] or 0),
            limit_up_days=0,
        )
        for r in rows
    ]


def classify_large_amount(
    conn: sqlite3.Connection, trading_date: str, threshold: float = 1_000_000_000
) -> list[CustomSectorEntry]:
    rows = conn.execute(
        """
        SELECT dp.stock_code, s.name, dp.open, dp.close, dp.volume, dp.amount
        FROM daily_prices dp
        LEFT JOIN stocks s ON dp.stock_code = s.stock_code
        WHERE dp.trading_date = ? AND dp.amount >= ? AND dp.is_suspended = 0
        ORDER BY dp.amount DESC
        """,
        (trading_date, threshold),
    ).fetchall()
    return [
        CustomSectorEntry(
            stock_code=r["stock_code"],
            stock_name=r["name"] or "",
            return_pct=round((r["close"] - r["open"]) / r["open"] * 100, 2) if r["open"] else 0.0,
            volume=float(r["volume"] or 0),
            amount=float(r["amount"] or 0),
            limit_up_days=0,
        )
        for r in rows
    ]


def classify_unusual_10d(
    conn: sqlite3.Connection, trading_date: str, amount_threshold: float = 800_000_000
) -> list[CustomSectorEntry]:
    """Stocks that had limit-up within last 10 days AND amount > threshold today."""
    prev_dates = conn.execute(
        """
        SELECT trading_date FROM trading_days
        WHERE trading_date <= ? AND is_open = 1
        ORDER BY trading_date DESC
        LIMIT 10
        """,
        (trading_date,),
    ).fetchall()
    if len(prev_dates) < 10:
        return []

    start_date = prev_dates[-1]["trading_date"]

    # Find stocks with limit-up in last 10 days
    limit_up_stocks = conn.execute(
        """
        SELECT DISTINCT stock_code FROM daily_prices
        WHERE trading_date BETWEEN ? AND ? AND is_limit_up = 1
        """,
        (start_date, trading_date),
    ).fetchall()

    if not limit_up_stocks:
        return []

    result: list[CustomSectorEntry] = []
    for r in limit_up_stocks:
        code = r["stock_code"]
        entry = _fetch_stock_detail(conn, trading_date, code)
        if entry and entry.amount >= amount_threshold:
            result.append(entry)

    return sorted(result, key=lambda x: x.amount, reverse=True)


def classify_all_custom_sectors(
    conn: sqlite3.Connection, trading_date: str
) -> list[CustomSector]:
    sectors: list[CustomSector] = []

    limit_up = classify_limit_up_today(conn, trading_date)
    if limit_up:
        sectors.append(
            CustomSector(
                sector_key="limit_up_today",
                sector_name=SECTOR_CONFIG["limit_up_today"]["name"],
                stocks=limit_up,
                criteria=SECTOR_CONFIG["limit_up_today"]["criteria"],
            )
        )

    large = classify_large_amount(conn, trading_date)
    if large:
        sectors.append(
            CustomSector(
                sector_key="large_amount",
                sector_name=SECTOR_CONFIG["large_amount"]["name"],
                stocks=large,
                criteria=SECTOR_CONFIG["large_amount"]["criteria"],
            )
        )

    unusual = classify_unusual_10d(conn, trading_date)
    if unusual:
        sectors.append(
            CustomSector(
                sector_key="unusual_10d",
                sector_name=SECTOR_CONFIG["unusual_10d"]["name"],
                stocks=unusual,
                criteria=SECTOR_CONFIG["unusual_10d"]["criteria"],
            )
        )

    return sectors


def save_custom_sectors(
    conn: sqlite3.Connection, trading_date: str, sectors: list[CustomSector]
) -> None:
    # Clear existing entries for the date
    conn.execute(
        "DELETE FROM stock_custom_sector WHERE trading_date = ?",
        (trading_date,),
    )
    for sector in sectors:
        for stock in sector.stocks:
            conn.execute(
                """
                INSERT INTO stock_custom_sector (trading_date, stock_code, sector_key)
                VALUES (?, ?, ?)
                """,
                (trading_date, stock.stock_code, sector.sector_key),
            )
    conn.commit()


def get_custom_sectors_for_stock(
    conn: sqlite3.Connection, trading_date: str, stock_code: str
) -> list[str]:
    rows = conn.execute(
        """
        SELECT sector_key FROM stock_custom_sector
        WHERE trading_date = ? AND stock_code = ?
        """,
        (trading_date, stock_code),
    ).fetchall()
    return [r["sector_key"] for r in rows]


def get_custom_sector_stocks(
    conn: sqlite3.Connection, trading_date: str, sector_key: str
) -> list[CustomSectorEntry]:
    rows = conn.execute(
        """
        SELECT scs.stock_code, s.name, dp.open, dp.close, dp.volume, dp.amount
        FROM stock_custom_sector scs
        LEFT JOIN stocks s ON scs.stock_code = s.stock_code
        LEFT JOIN daily_prices dp ON scs.stock_code = dp.stock_code AND dp.trading_date = ?
        WHERE scs.trading_date = ? AND scs.sector_key = ?
        ORDER BY dp.amount DESC
        """,
        (trading_date, trading_date, sector_key),
    ).fetchall()
    return [
        CustomSectorEntry(
            stock_code=r["stock_code"],
            stock_name=r["name"] or "",
            return_pct=round((r["close"] - r["open"]) / r["open"] * 100, 2) if r["open"] else 0.0,
            volume=float(r["volume"] or 0),
            amount=float(r["amount"] or 0),
        )
        for r in rows
    ]


def generate_custom_sectors(
    conn: sqlite3.Connection, trading_date: str
) -> list[CustomSector]:
    sectors = classify_all_custom_sectors(conn, trading_date)
    save_custom_sectors(conn, trading_date, sectors)
    return sectors
