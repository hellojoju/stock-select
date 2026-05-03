"""Custom sector classification — 自定义板块归类模块.

Classifies stocks into custom sectors based on trading activity:
- limit_up_today: 当日涨停
- high_turnover_today: 当日换手率>20%
- high_turnover_10d: 近10日平均换手率>15%
- unusual_10d: 近10日内有3倍放量
- large_amount: 当日成交额>10亿
"""
from __future__ import annotations

import sqlite3


SECTOR_KEYS = [
    "limit_up_today",
    "high_turnover_today",
    "high_turnover_10d",
    "unusual_10d",
    "large_amount",
]

SECTOR_DISPLAY_NAMES = {
    "limit_up_today": "涨停",
    "high_turnover_today": "高换手",
    "high_turnover_10d": "持续高换手",
    "unusual_10d": "异动放量",
    "large_amount": "大成交额",
}


def classify_custom_sectors(conn: sqlite3.Connection, trading_date: str) -> list[dict]:
    """Run classification for all stocks on the given date.

    Writes results to stock_custom_sector table.
    """
    stocks = conn.execute(
        """
        SELECT dp.stock_code, dp.open, dp.close, dp.volume, dp.amount,
               dp.is_limit_up, s.list_date
        FROM daily_prices dp
        LEFT JOIN stocks s ON dp.stock_code = s.stock_code
        WHERE dp.trading_date = ? AND dp.is_suspended = 0 AND dp.open > 0
        """,
        (trading_date,),
    ).fetchall()

    classifications: list[dict] = []

    for row in stocks:
        code = row["stock_code"]
        amount = float(row["amount"] or 0)
        is_limit = row["is_limit_up"] == 1
        volume = float(row["volume"] or 0)

        tags: list[str] = []

        # 1. limit_up_today
        if is_limit:
            tags.append("limit_up_today")

        # 2. high_turnover_today (estimated from volume vs market cap bucket)
        turnover_today = _estimate_turnover(conn, code, trading_date, volume)
        if turnover_today > 20:
            tags.append("high_turnover_today")

        # 3. high_turnover_10d: average turnover over last 10 days > 15%
        avg_turnover_10d = _avg_turnover(conn, code, trading_date, days=10)
        if avg_turnover_10d > 15:
            tags.append("high_turnover_10d")

        # 4. unusual_10d: volume >= 3x average in last 10 days
        if _has_unusual_volume(conn, code, trading_date):
            tags.append("unusual_10d")

        # 5. large_amount: 成交额 > 10亿
        if amount >= 1_000_000_000:
            tags.append("large_amount")

        for tag in tags:
            conn.execute(
                """
                INSERT OR IGNORE INTO stock_custom_sector
                (trading_date, stock_code, sector_key)
                VALUES (?, ?, ?)
                """,
                (trading_date, code, tag),
            )

            classifications.append({
                "stock_code": code,
                "trading_date": trading_date,
                "sector_key": tag,
            })

    conn.commit()
    return classifications


def get_custom_sector_tags(
    conn: sqlite3.Connection, stock_code: str, trading_date: str
) -> list[str]:
    """Get custom sector tags for a stock on a given date."""
    rows = conn.execute(
        """
        SELECT sector_key FROM stock_custom_sector
        WHERE trading_date = ? AND stock_code = ?
        ORDER BY sector_key
        """,
        (trading_date, stock_code),
    ).fetchall()
    return [r["sector_key"] for r in rows]


def get_custom_sector_stocks(
    conn: sqlite3.Connection, trading_date: str, sector_key: str
) -> list[dict]:
    """Get all stocks in a custom sector."""
    rows = conn.execute(
        """
        SELECT sc.stock_code, s.name, dp.close, dp.amount, dp.volume,
               dp.is_limit_up
        FROM stock_custom_sector sc
        JOIN daily_prices dp ON dp.stock_code = sc.stock_code AND dp.trading_date = sc.trading_date
        JOIN stocks s ON s.stock_code = sc.stock_code
        WHERE sc.trading_date = ? AND sc.sector_key = ?
        ORDER BY dp.amount DESC
        """,
        (trading_date, sector_key),
    ).fetchall()
    return [dict(r) for r in rows]


def _estimate_turnover(
    conn: sqlite3.Connection, stock_code: str, trading_date: str, volume: float
) -> float:
    """Estimate turnover rate from volume and price.

    Without share count data, use a heuristic:
    turnover ≈ volume / (market_cap / price)
    Since we don't have market_cap, use amount/close as proxy for shares traded,
    and compare against typical turnover ranges.
    """
    if volume == 0:
        return 0.0
    # Use amount/close ≈ shares traded * price / price = shares traded
    # This is a rough proxy. For real data we'd need total shares.
    row = conn.execute(
        "SELECT close, amount FROM daily_prices WHERE stock_code = ? AND trading_date = ?",
        (stock_code, trading_date),
    ).fetchone()
    if not row or float(row["close"] or 0) == 0:
        return 0.0
    close = float(row["close"])
    amount = float(row["amount"] or 0)
    # Estimated shares = amount / close
    est_shares = amount / close if close > 0 else 1
    # Simple volume proxy — if volume (lots) is large relative to estimated shares
    # In Chinese market, 1 lot = 100 shares, volume is in lots
    estimated_shares_traded = volume * 100
    if est_shares == 0:
        return 0.0
    return round(estimated_shares_traded / est_shares * 100, 2)


def _avg_turnover(
    conn: sqlite3.Connection, stock_code: str, trading_date: str, days: int = 10
) -> float:
    """Calculate average turnover rate over N days."""
    rows = conn.execute(
        """
        SELECT trading_date, volume, amount, close
        FROM daily_prices
        WHERE stock_code = ? AND trading_date <= ?
        ORDER BY trading_date DESC
        LIMIT ?
        """,
        (stock_code, trading_date, days),
    ).fetchall()

    turnovers = []
    for r in rows:
        vol = float(r["volume"] or 0)
        amt = float(r["amount"] or 0)
        cl = float(r["close"] or 0)
        if cl > 0 and amt > 0:
            est_shares = amt / cl
            est_traded = vol * 100
            t = est_traded / est_shares * 100
            turnovers.append(t)

    return sum(turnovers) / len(turnovers) if turnovers else 0.0


def _has_unusual_volume(
    conn: sqlite3.Connection, stock_code: str, trading_date: str
) -> bool:
    """Check if volume >= 3x average in the last 10 days."""
    rows = conn.execute(
        """
        SELECT volume
        FROM daily_prices
        WHERE stock_code = ? AND trading_date <= ?
        ORDER BY trading_date DESC
        LIMIT 10
        """,
        (stock_code, trading_date),
    ).fetchall()

    volumes = [float(r["volume"] or 0) for r in rows]
    if len(volumes) < 3:
        return False

    today_vol = volumes[0]
    avg_vol = sum(volumes[1:]) / len(volumes[1:]) if volumes[1:] else 0
    return avg_vol > 0 and today_vol >= avg_vol * 3
