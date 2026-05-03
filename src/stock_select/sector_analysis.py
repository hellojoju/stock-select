from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class StockInSector:
    stock_code: str
    stock_name: str
    return_pct: float
    amount: float
    volume: float
    is_limit_up: bool = False
    limit_up_days: int = 0


@dataclass(frozen=True)
class SectorAnalysis:
    trading_date: str
    sector_name: str
    sector_return_pct: float = 0.0
    strength_1d: float = 0.0
    strength_3d: float = 0.0
    strength_10d: float = 0.0
    stock_count: int = 0
    advance_ratio: float = 0.0
    leader_stock: str = ""
    leader_return_pct: float = 0.0
    leader_limit_up_days: int = 0
    mid_tier_stocks: list[str] = field(default_factory=list)
    follower_stocks: list[str] = field(default_factory=list)
    drive_logic: str = ""
    team_complete: bool = False
    sustainability: float = 0.0
    limit_up_3d_count: int = 0


def _sector_returns(
    conn: sqlite3.Connection, trading_date: str
) -> dict[str, float]:
    """Calculate average return per industry for a given date."""
    rows = conn.execute(
        """
        SELECT s.industry, AVG((dp.close - dp.open) / dp.open * 100) as avg_return
        FROM daily_prices dp
        JOIN stocks s ON dp.stock_code = s.stock_code
        WHERE dp.trading_date = ? AND dp.is_suspended = 0 AND dp.open > 0
        GROUP BY s.industry
        """,
        (trading_date,),
    ).fetchall()
    return {r["industry"]: round(r["avg_return"], 2) for r in rows if r["industry"]}


def _sector_stocks(
    conn: sqlite3.Connection, trading_date: str, sector_name: str
) -> list[StockInSector]:
    """Get all stocks in a sector with their return for the day."""
    rows = conn.execute(
        """
        SELECT dp.stock_code, s.name, dp.open, dp.close, dp.volume, dp.amount, dp.is_limit_up
        FROM daily_prices dp
        JOIN stocks s ON dp.stock_code = s.stock_code
        WHERE dp.trading_date = ? AND s.industry = ? AND dp.is_suspended = 0 AND dp.open > 0
        ORDER BY (dp.close - dp.open) / dp.open DESC
        """,
        (trading_date, sector_name),
    ).fetchall()
    return [
        StockInSector(
            stock_code=r["stock_code"],
            stock_name=r["name"] or "",
            return_pct=round((r["close"] - r["open"]) / r["open"] * 100, 2),
            amount=float(r["amount"]),
            volume=float(r["volume"]),
            is_limit_up=bool(r["is_limit_up"]),
        )
        for r in rows
    ]


def _count_limit_up_3d(
    conn: sqlite3.Connection, trading_date: str, sector_name: str
) -> int:
    """Count limit-up stocks in the sector over the last 3 trading days."""
    prev_dates = conn.execute(
        """
        SELECT trading_date FROM trading_days
        WHERE trading_date <= ? AND is_open = 1
        ORDER BY trading_date DESC
        LIMIT 3
        """,
        (trading_date,),
    ).fetchall()
    if len(prev_dates) < 3:
        return 0
    start_date = prev_dates[-1]["trading_date"]
    count = conn.execute(
        """
        SELECT COUNT(DISTINCT dp.stock_code) as cnt
        FROM daily_prices dp
        JOIN stocks s ON dp.stock_code = s.stock_code
        WHERE dp.trading_date BETWEEN ? AND ?
          AND s.industry = ?
          AND dp.is_limit_up = 1
        """,
        (start_date, trading_date, sector_name),
    ).fetchone()["cnt"]
    return count or 0


def _multi_day_strength(
    conn: sqlite3.Connection, trading_date: str, sector_name: str
) -> tuple[float, float]:
    """Calculate 3-day and 10-day sector strength."""
    prev_dates = conn.execute(
        """
        SELECT trading_date FROM trading_days
        WHERE trading_date <= ? AND is_open = 1
        ORDER BY trading_date DESC
        LIMIT 10
        """,
        (trading_date,),
    ).fetchall()
    if len(prev_dates) < 2:
        return 0.0, 0.0

    def _avg_for_dates(start: str, end: str) -> float:
        row = conn.execute(
            """
            SELECT AVG((dp.close - dp.open) / dp.open * 100) as avg_return
            FROM daily_prices dp
            JOIN stocks s ON dp.stock_code = s.stock_code
            WHERE dp.trading_date BETWEEN ? AND ?
              AND s.industry = ?
              AND dp.is_suspended = 0 AND dp.open > 0
            """,
            (start, end, sector_name),
        ).fetchone()
        return round(row["avg_return"] or 0.0, 2)

    dates = [r["trading_date"] for r in prev_dates]
    strength_3d = _avg_for_dates(dates[min(2, len(dates)-1)], dates[0])
    strength_10d = _avg_for_dates(dates[-1], dates[0]) if len(dates) >= 10 else 0.0
    return strength_3d, strength_10d


def _classify_team(stocks: list[StockInSector]) -> tuple[str, list[str], list[str], int]:
    """Classify stocks in a sector into leader, mid-tier, and followers.
    Returns: (leader_code, mid_tier_codes, follower_codes, leader_limit_up_days)
    """
    if not stocks:
        return "", [], [], 0

    leader = stocks[0]
    leader_code = leader.stock_code

    # Mid-tier: stocks in top 30% by return, minimum 10% return
    threshold_idx = max(1, int(len(stocks) * 0.3))
    mid_tier = [
        s.stock_code
        for s in stocks[1:threshold_idx]
        if s.return_pct >= 5.0
    ]

    # Followers: remaining stocks with positive return
    followers = [
        s.stock_code
        for s in stocks[threshold_idx:]
        if s.return_pct > 0
    ]

    return leader_code, mid_tier, followers, leader.limit_up_days


def _calc_sustainability(
    sector_return: float,
    strength_3d: float,
    advance_ratio: float,
    team_complete: bool,
) -> float:
    """Calculate sector sustainability score (0-1)."""
    score = 0.0
    if sector_return > 2.0:
        score += 0.25
    elif sector_return > 0:
        score += 0.1
    if strength_3d > 1.0:
        score += 0.25
    elif strength_3d > 0:
        score += 0.1
    if advance_ratio > 0.7:
        score += 0.25
    elif advance_ratio > 0.5:
        score += 0.15
    if team_complete:
        score += 0.25
    return round(min(score, 1.0), 2)


def _advance_ratio(stocks: list[StockInSector]) -> float:
    if not stocks:
        return 0.0
    advances = sum(1 for s in stocks if s.return_pct > 0)
    return round(advances / len(stocks), 2)


def analyze_sector(
    conn: sqlite3.Connection, trading_date: str, sector_name: str
) -> SectorAnalysis:
    sector_returns = _sector_returns(conn, trading_date)
    sector_return = sector_returns.get(sector_name, 0.0)

    stocks = _sector_stocks(conn, trading_date, sector_name)
    stock_count = len(stocks)
    adv_ratio = _advance_ratio(stocks)

    leader_code, mid_tier, followers, leader_lu_days = _classify_team(stocks)
    leader_return = stocks[0].return_pct if stocks else 0.0

    strength_3d, strength_10d = _multi_day_strength(conn, trading_date, sector_name)
    limit_up_3d = _count_limit_up_3d(conn, trading_date, sector_name)

    team_complete = len(mid_tier) >= 1 and len(followers) >= 1
    sustainability = _calc_sustainability(
        sector_return, strength_3d, adv_ratio, team_complete
    )

    return SectorAnalysis(
        trading_date=trading_date,
        sector_name=sector_name,
        sector_return_pct=sector_return,
        strength_1d=sector_return,
        strength_3d=strength_3d,
        strength_10d=strength_10d,
        stock_count=stock_count,
        advance_ratio=adv_ratio,
        leader_stock=leader_code,
        leader_return_pct=leader_return,
        leader_limit_up_days=leader_lu_days,
        mid_tier_stocks=mid_tier,
        follower_stocks=followers,
        team_complete=team_complete,
        sustainability=sustainability,
        limit_up_3d_count=limit_up_3d,
    )


def analyze_all_sectors(
    conn: sqlite3.Connection, trading_date: str, limit: int = 20
) -> list[SectorAnalysis]:
    """Analyze top N sectors by daily return."""
    sector_returns = _sector_returns(conn, trading_date)
    sorted_sectors = sorted(
        sector_returns.items(), key=lambda x: x[1], reverse=True
    )[:limit]

    return [
        analyze_sector(conn, trading_date, sector_name)
        for sector_name, _ in sorted_sectors
    ]


def save_sector_analysis(conn: sqlite3.Connection, analysis: SectorAnalysis) -> None:
    conn.execute(
        """
        INSERT INTO sector_analysis_daily (
            trading_date, sector_name, sector_return_pct,
            strength_1d, strength_3d, strength_10d,
            stock_count, advance_ratio,
            leader_stock, leader_return_pct, leader_limit_up_days,
            mid_tier_stocks, follower_stocks,
            drive_logic, team_complete, sustainability, limit_up_3d_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(trading_date, sector_name) DO UPDATE SET
            sector_return_pct = excluded.sector_return_pct,
            strength_1d = excluded.strength_1d,
            strength_3d = excluded.strength_3d,
            strength_10d = excluded.strength_10d,
            stock_count = excluded.stock_count,
            advance_ratio = excluded.advance_ratio,
            leader_stock = excluded.leader_stock,
            leader_return_pct = excluded.leader_return_pct,
            leader_limit_up_days = excluded.leader_limit_up_days,
            mid_tier_stocks = excluded.mid_tier_stocks,
            follower_stocks = excluded.follower_stocks,
            drive_logic = excluded.drive_logic,
            team_complete = excluded.team_complete,
            sustainability = excluded.sustainability,
            limit_up_3d_count = excluded.limit_up_3d_count,
            created_at = datetime('now')
        """,
        (
            analysis.trading_date,
            analysis.sector_name,
            analysis.sector_return_pct,
            analysis.strength_1d,
            analysis.strength_3d,
            analysis.strength_10d,
            analysis.stock_count,
            analysis.advance_ratio,
            analysis.leader_stock,
            analysis.leader_return_pct,
            analysis.leader_limit_up_days,
            json.dumps(analysis.mid_tier_stocks),
            json.dumps(analysis.follower_stocks),
            analysis.drive_logic,
            1 if analysis.team_complete else 0,
            analysis.sustainability,
            analysis.limit_up_3d_count,
        ),
    )
    conn.commit()


def get_sector_analysis(
    conn: sqlite3.Connection, trading_date: str, sector_name: str
) -> SectorAnalysis | None:
    row = conn.execute(
        """
        SELECT * FROM sector_analysis_daily
        WHERE trading_date = ? AND sector_name = ?
        """,
        (trading_date, sector_name),
    ).fetchone()
    if row is None:
        return None
    return SectorAnalysis(
        trading_date=row["trading_date"],
        sector_name=row["sector_name"],
        sector_return_pct=row["sector_return_pct"] or 0.0,
        strength_1d=row["strength_1d"] or 0.0,
        strength_3d=row["strength_3d"] or 0.0,
        strength_10d=row["strength_10d"] or 0.0,
        stock_count=row["stock_count"] or 0,
        advance_ratio=row["advance_ratio"] or 0.0,
        leader_stock=row["leader_stock"] or "",
        leader_return_pct=row["leader_return_pct"] or 0.0,
        leader_limit_up_days=row["leader_limit_up_days"] or 0,
        mid_tier_stocks=json.loads(row["mid_tier_stocks"] or "[]"),
        follower_stocks=json.loads(row["follower_stocks"] or "[]"),
        drive_logic=row["drive_logic"] or "",
        team_complete=bool(row["team_complete"]),
        sustainability=row["sustainability"] or 0.0,
        limit_up_3d_count=row["limit_up_3d_count"] or 0,
    )


def get_top_sectors(
    conn: sqlite3.Connection, trading_date: str, limit: int = 10
) -> list[SectorAnalysis]:
    rows = conn.execute(
        """
        SELECT * FROM sector_analysis_daily
        WHERE trading_date = ?
        ORDER BY sector_return_pct DESC
        LIMIT ?
        """,
        (trading_date, limit),
    ).fetchall()
    return [
        SectorAnalysis(
            trading_date=r["trading_date"],
            sector_name=r["sector_name"],
            sector_return_pct=r["sector_return_pct"] or 0.0,
            strength_1d=r["strength_1d"] or 0.0,
            strength_3d=r["strength_3d"] or 0.0,
            strength_10d=r["strength_10d"] or 0.0,
            stock_count=r["stock_count"] or 0,
            advance_ratio=r["advance_ratio"] or 0.0,
            leader_stock=r["leader_stock"] or "",
            leader_return_pct=r["leader_return_pct"] or 0.0,
            leader_limit_up_days=r["leader_limit_up_days"] or 0,
            mid_tier_stocks=json.loads(r["mid_tier_stocks"] or "[]"),
            follower_stocks=json.loads(r["follower_stocks"] or "[]"),
            drive_logic=r["drive_logic"] or "",
            team_complete=bool(r["team_complete"]),
            sustainability=r["sustainability"] or 0.0,
            limit_up_3d_count=r["limit_up_3d_count"] or 0,
        )
        for r in rows
    ]
