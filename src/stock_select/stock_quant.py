from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class VolumeAnalysis:
    today_volume: float
    avg_volume_5d: float
    avg_volume_10d: float
    volume_ratio_5d: float
    volume_ratio_10d: float
    trend: str


@dataclass(frozen=True)
class MovingAverage:
    ma5: float
    ma10: float
    ma20: float
    close: float
    position_vs_ma5: float
    position_vs_ma10: float
    position_vs_ma20: float
    trend: str


@dataclass(frozen=True)
class LimitUpChain:
    current_days: int
    max_days_20d: int
    is_limit_up_today: bool


@dataclass(frozen=True)
class LeaderComparison:
    leader_code: str
    leader_name: str
    leader_return_pct: float
    self_return_pct: float
    return_gap: float
    amount_ratio: float


@dataclass(frozen=True)
class StockQuantReport:
    trading_date: str
    stock_code: str
    stock_name: str
    volume_analysis: VolumeAnalysis | None = None
    moving_average: MovingAverage | None = None
    limit_up_chain: LimitUpChain | None = None
    leader_comparison: LeaderComparison | None = None


def _fetch_price_history(
    conn: sqlite3.Connection, stock_code: str, trading_date: str, days: int = 25
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT trading_date, open, high, low, close, volume, amount, is_limit_up
        FROM daily_prices
        WHERE stock_code = ? AND trading_date <= ?
        ORDER BY trading_date DESC
        LIMIT ?
        """,
        (stock_code, trading_date, days),
    ).fetchall()
    return [dict(r) for r in rows]


def analyze_volume(
    conn: sqlite3.Connection, stock_code: str, trading_date: str
) -> VolumeAnalysis | None:
    history = _fetch_price_history(conn, stock_code, trading_date, days=15)
    if not history:
        return None

    today_volume = history[0]["volume"]
    volumes_5d = [h["volume"] for h in history[1:6] if h["volume"] > 0]
    volumes_10d = [h["volume"] for h in history[1:11] if h["volume"] > 0]

    avg_5d = sum(volumes_5d) / len(volumes_5d) if volumes_5d else 0
    avg_10d = sum(volumes_10d) / len(volumes_10d) if volumes_10d else 0

    ratio_5d = round(today_volume / avg_5d, 2) if avg_5d > 0 else 0.0
    ratio_10d = round(today_volume / avg_10d, 2) if avg_10d > 0 else 0.0

    if ratio_5d >= 2.0:
        trend = "大幅放量"
    elif ratio_5d >= 1.5:
        trend = "放量"
    elif ratio_5d <= 0.5:
        trend = "大幅缩量"
    elif ratio_5d <= 0.7:
        trend = "缩量"
    else:
        trend = "平量"

    return VolumeAnalysis(
        today_volume=today_volume,
        avg_volume_5d=round(avg_5d, 2),
        avg_volume_10d=round(avg_10d, 2),
        volume_ratio_5d=ratio_5d,
        volume_ratio_10d=ratio_10d,
        trend=trend,
    )


def analyze_moving_average(
    conn: sqlite3.Connection, stock_code: str, trading_date: str
) -> MovingAverage | None:
    history = _fetch_price_history(conn, stock_code, trading_date, days=25)
    if not history:
        return None

    closes = [h["close"] for h in history if h["close"] is not None]
    if not closes:
        return None

    close = closes[0]
    ma5 = sum(closes[:5]) / len(closes[:5]) if len(closes) >= 5 else 0
    ma10 = sum(closes[:10]) / len(closes[:10]) if len(closes) >= 10 else 0
    ma20 = sum(closes[:20]) / len(closes[:20]) if len(closes) >= 20 else 0

    pos_ma5 = round((close - ma5) / ma5 * 100, 2) if ma5 > 0 else 0.0
    pos_ma10 = round((close - ma10) / ma10 * 100, 2) if ma10 > 0 else 0.0
    pos_ma20 = round((close - ma20) / ma20 * 100, 2) if ma20 > 0 else 0.0

    if close > ma5 > ma10 > ma20:
        trend = "多头排列"
    elif close < ma5 < ma10 < ma20:
        trend = "空头排列"
    elif close > ma5 and close > ma10:
        trend = "短期强势"
    elif close < ma5 and close < ma10:
        trend = "短期弱势"
    else:
        trend = "震荡"

    return MovingAverage(
        ma5=round(ma5, 2),
        ma10=round(ma10, 2),
        ma20=round(ma20, 2),
        close=close,
        position_vs_ma5=pos_ma5,
        position_vs_ma10=pos_ma10,
        position_vs_ma20=pos_ma20,
        trend=trend,
    )


def analyze_limit_up_chain(
    conn: sqlite3.Connection, stock_code: str, trading_date: str
) -> LimitUpChain | None:
    history = _fetch_price_history(conn, stock_code, trading_date, days=25)
    if not history:
        return None

    current_days = 0
    for h in history:
        if h["is_limit_up"] == 1:
            current_days += 1
        else:
            break

    max_days = 0
    current_streak = 0
    for h in history:
        if h["is_limit_up"] == 1:
            current_streak += 1
            max_days = max(max_days, current_streak)
        else:
            current_streak = 0

    return LimitUpChain(
        current_days=current_days,
        max_days_20d=max_days,
        is_limit_up_today=history[0]["is_limit_up"] == 1 if history else False,
    )


def analyze_leader_comparison(
    conn: sqlite3.Connection, stock_code: str, trading_date: str
) -> LeaderComparison | None:
    """Compare the stock against its sector leader."""
    # Get stock's industry
    row = conn.execute(
        "SELECT industry, name FROM stocks WHERE stock_code = ?",
        (stock_code,),
    ).fetchone()
    if row is None or not row["industry"]:
        return None
    industry = row["industry"]
    stock_name = row["name"] or ""

    # Get sector leader for the day
    leader_row = conn.execute(
        """
        SELECT dp.stock_code, s.name, (dp.close - dp.open) / dp.open * 100 as ret, dp.amount
        FROM daily_prices dp
        JOIN stocks s ON dp.stock_code = s.stock_code
        WHERE dp.trading_date = ? AND s.industry = ? AND dp.is_suspended = 0 AND dp.open > 0
        ORDER BY ret DESC
        LIMIT 1
        """,
        (trading_date, industry),
    ).fetchone()
    if leader_row is None:
        return None

    leader_code = leader_row["stock_code"]
    if leader_code == stock_code:
        return None

    # Get self return and amount
    self_row = conn.execute(
        """
        SELECT (close - open) / open * 100 as ret, amount
        FROM daily_prices
        WHERE trading_date = ? AND stock_code = ? AND open > 0
        """,
        (trading_date, stock_code),
    ).fetchone()
    if self_row is None:
        return None

    leader_return = round(leader_row["ret"] or 0, 2)
    self_return = round(self_row["ret"] or 0, 2)
    leader_amount = leader_row["amount"] or 1
    self_amount = self_row["amount"] or 0

    return LeaderComparison(
        leader_code=leader_code,
        leader_name=leader_row["name"] or "",
        leader_return_pct=leader_return,
        self_return_pct=self_return,
        return_gap=round(self_return - leader_return, 2),
        amount_ratio=round(self_amount / leader_amount, 2) if leader_amount > 0 else 0.0,
    )


def build_stock_quant_report(
    conn: sqlite3.Connection, stock_code: str, trading_date: str
) -> StockQuantReport | None:
    row = conn.execute(
        "SELECT name FROM stocks WHERE stock_code = ?",
        (stock_code,),
    ).fetchone()
    if row is None:
        return None

    return StockQuantReport(
        trading_date=trading_date,
        stock_code=stock_code,
        stock_name=row["name"] or "",
        volume_analysis=analyze_volume(conn, stock_code, trading_date),
        moving_average=analyze_moving_average(conn, stock_code, trading_date),
        limit_up_chain=analyze_limit_up_chain(conn, stock_code, trading_date),
        leader_comparison=analyze_leader_comparison(conn, stock_code, trading_date),
    )
