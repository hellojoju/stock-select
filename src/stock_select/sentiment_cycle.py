from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SentimentCycle:
    trading_date: str
    advance_count: int = 0
    decline_count: int = 0
    limit_up_count: int = 0
    limit_down_count: int = 0
    seal_rate: float | None = None
    promotion_rate: float | None = None
    financing_balance: float | None = None
    financing_change_pct: float | None = None
    short_selling_balance: float | None = None
    short_selling_change_pct: float | None = None
    news_heat: float | None = None
    llm_sentiment_score: float | None = None
    composite_sentiment: float | None = None
    cycle_phase: str = "unknown"
    cycle_reason: str = ""


def _count_distribution(conn: sqlite3.Connection, trading_date: str) -> tuple[int, int]:
    advance = 0
    decline = 0
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
    return advance, decline


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


def _calc_seal_rate(conn: sqlite3.Connection, trading_date: str) -> float | None:
    """Estimate seal rate from limit-up stocks.
    With daily close data, we approximate by counting stocks that
    hit limit-up and have close near high (within 1%).
    """
    rows = conn.execute(
        """
        SELECT close, high FROM daily_prices
        WHERE trading_date = ? AND is_limit_up = 1 AND is_suspended = 0
        """,
        (trading_date,),
    ).fetchall()
    if not rows:
        return None
    sealed = 0
    for row in rows:
        if row["high"] and row["high"] > 0:
            if abs(row["close"] - row["high"]) / row["high"] < 0.01:
                sealed += 1
    return round(sealed / len(rows), 2)


def _calc_promotion_rate(conn: sqlite3.Connection, trading_date: str) -> float | None:
    """Calculate 1-to-2 promotion rate.
    A stock promoted if it was limit-up yesterday and is limit-up today.
    """
    row = conn.execute(
        "SELECT trading_date FROM trading_days WHERE trading_date < ? ORDER BY trading_date DESC LIMIT 1",
        (trading_date,),
    ).fetchone()
    if row is None:
        return None
    prev_date = row["trading_date"]
    yesterday_limit_up = conn.execute(
        "SELECT stock_code FROM daily_prices WHERE trading_date = ? AND is_limit_up = 1",
        (prev_date,),
    ).fetchall()
    if not yesterday_limit_up:
        return None
    promoted = 0
    for r in yesterday_limit_up:
        today = conn.execute(
            "SELECT is_limit_up FROM daily_prices WHERE trading_date = ? AND stock_code = ?",
            (trading_date, r["stock_code"]),
        ).fetchone()
        if today and today["is_limit_up"] == 1:
            promoted += 1
    return round(promoted / len(yesterday_limit_up), 2)


def _calc_news_heat(conn: sqlite3.Connection, trading_date: str) -> float | None:
    """Approximate news heat by counting documents published on that date.
    Normalized against a 30-day rolling average."""
    count = conn.execute(
        """
        SELECT COUNT(*) as cnt FROM raw_documents
        WHERE date(published_at) = date(?)
        """,
        (trading_date,),
    ).fetchone()["cnt"]
    if count == 0:
        return None
    avg_row = conn.execute(
        """
        SELECT AVG(cnt) as avg_cnt FROM (
            SELECT COUNT(*) as cnt FROM raw_documents
            WHERE date(published_at) BETWEEN date(?, '-30 days') AND date(?, '-1 day')
            GROUP BY date(published_at)
        )
        """,
        (trading_date, trading_date),
    ).fetchone()
    avg = avg_row["avg_cnt"] or 1
    return round(min(count / max(avg, 1), 5.0), 2)


def _determine_cycle_phase(
    advance: int,
    decline: int,
    limit_up: int,
    limit_down: int,
    seal_rate: float | None,
    promotion_rate: float | None,
    composite_sentiment: float | None,
) -> tuple[str, str]:
    """Determine market sentiment cycle phase.
    Phases: 冰点/回暖/升温/高潮/退潮/恐慌
    """
    total = advance + decline
    if total == 0:
        return "unknown", "无有效数据"
    advance_ratio = advance / total
    if limit_down >= 50 and advance_ratio < 0.2:
        return "恐慌", f"跌停{limit_down}家，上涨家数占比{advance_ratio:.0%}"
    if advance_ratio < 0.25 and limit_up < 10:
        return "冰点", f"上涨家数占比{advance_ratio:.0%}，涨停仅{limit_up}家"
    if advance_ratio >= 0.25 and advance_ratio < 0.5 and limit_up >= 10:
        return "回暖", f"上涨家数占比{advance_ratio:.0%}，涨停{limit_up}家"
    if advance_ratio >= 0.5 and limit_up >= 1:
        if seal_rate is not None and seal_rate >= 0.7 and promotion_rate is not None and promotion_rate >= 0.3:
            return "高潮", f"上涨家数占比{advance_ratio:.0%}，涨停{limit_up}家，封板率{seal_rate:.0%}，晋级率{promotion_rate:.0%}"
        return "升温", f"上涨家数占比{advance_ratio:.0%}，涨停{limit_up}家"
    if advance_ratio >= 0.25 and limit_up >= 1:
        return "回暖", f"上涨家数占比{advance_ratio:.0%}，涨停{limit_up}家"
    if advance_ratio >= 0.5 and limit_up < 1 and limit_down >= 1:
        return "退潮", f"上涨家数占比{advance_ratio:.0%}，涨停减少至{limit_up}家，跌停{limit_down}家"
    if composite_sentiment is not None:
        if composite_sentiment < -0.5:
            return "恐慌", f"综合情绪分{composite_sentiment:.2f}"
        if composite_sentiment < -0.2:
            return "冰点", f"综合情绪分{composite_sentiment:.2f}"
        if composite_sentiment > 0.5:
            return "高潮", f"综合情绪分{composite_sentiment:.2f}"
    return "unknown", f"上涨家数占比{advance_ratio:.0%}，涨停{limit_up}家，跌停{limit_down}家"


def build_sentiment_cycle(conn: sqlite3.Connection, trading_date: str) -> SentimentCycle:
    # 优先用 API 拉取全市场概览（涨跌家数、涨停跌停）
    advance = 0
    decline = 0
    limit_up = 0
    limit_down = 0
    try:
        from .market_breadth import ensure_market_breadth

        breadth = ensure_market_breadth(conn, trading_date)
        total_market = breadth.get("advance_count", 0) + breadth.get("decline_count", 0)
        if total_market >= 100:
            # 有效全市场数据才使用
            advance = breadth.get("advance_count", 0)
            decline = breadth.get("decline_count", 0)
            limit_up = breadth.get("limit_up_count", 0)
            limit_down = breadth.get("limit_down_count", 0)
        else:
            # API 返回无效数据（历史日期返回 0），退回库内统计
            advance, decline = _count_distribution(conn, trading_date)
            limit_up, limit_down = _count_limit_up_down(conn, trading_date)
    except Exception:
        # API 失败，退回库内统计
        advance, decline = _count_distribution(conn, trading_date)
        limit_up, limit_down = _count_limit_up_down(conn, trading_date)

    seal_rate = _calc_seal_rate(conn, trading_date)
    promotion_rate = _calc_promotion_rate(conn, trading_date)
    news_heat = _calc_news_heat(conn, trading_date)

    # Composite sentiment: simple weighted average of available signals
    signals: list[float] = []
    total = advance + decline
    if total > 0:
        signals.append((advance - decline) / total)
    if limit_up + limit_down > 0:
        signals.append((limit_up - limit_down) / (limit_up + limit_down))
    if seal_rate is not None:
        signals.append(seal_rate * 2 - 1)
    composite = round(sum(signals) / len(signals), 2) if signals else None

    phase, reason = _determine_cycle_phase(
        advance, decline, limit_up, limit_down, seal_rate, promotion_rate, composite,
    )

    return SentimentCycle(
        trading_date=trading_date,
        advance_count=advance,
        decline_count=decline,
        limit_up_count=limit_up,
        limit_down_count=limit_down,
        seal_rate=seal_rate,
        promotion_rate=promotion_rate,
        news_heat=news_heat,
        composite_sentiment=composite,
        cycle_phase=phase,
        cycle_reason=reason,
    )


def save_sentiment_cycle(conn: sqlite3.Connection, cycle: SentimentCycle) -> None:
    conn.execute(
        """
        INSERT INTO sentiment_cycle_daily (
            trading_date, advance_count, decline_count, limit_up_count, limit_down_count,
            seal_rate, promotion_rate, financing_balance, financing_change_pct,
            short_selling_balance, short_selling_change_pct,
            news_heat, llm_sentiment_score, composite_sentiment,
            cycle_phase, cycle_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(trading_date) DO UPDATE SET
            advance_count = excluded.advance_count,
            decline_count = excluded.decline_count,
            limit_up_count = excluded.limit_up_count,
            limit_down_count = excluded.limit_down_count,
            seal_rate = excluded.seal_rate,
            promotion_rate = excluded.promotion_rate,
            financing_balance = excluded.financing_balance,
            financing_change_pct = excluded.financing_change_pct,
            short_selling_balance = excluded.short_selling_balance,
            short_selling_change_pct = excluded.short_selling_change_pct,
            news_heat = excluded.news_heat,
            llm_sentiment_score = excluded.llm_sentiment_score,
            composite_sentiment = excluded.composite_sentiment,
            cycle_phase = excluded.cycle_phase,
            cycle_reason = excluded.cycle_reason,
            created_at = datetime('now')
        """,
        (
            cycle.trading_date,
            cycle.advance_count,
            cycle.decline_count,
            cycle.limit_up_count,
            cycle.limit_down_count,
            cycle.seal_rate,
            cycle.promotion_rate,
            cycle.financing_balance,
            cycle.financing_change_pct,
            cycle.short_selling_balance,
            cycle.short_selling_change_pct,
            cycle.news_heat,
            cycle.llm_sentiment_score,
            cycle.composite_sentiment,
            cycle.cycle_phase,
            cycle.cycle_reason,
        ),
    )
    conn.commit()


def get_sentiment_cycle(conn: sqlite3.Connection, trading_date: str) -> SentimentCycle | None:
    row = conn.execute(
        "SELECT * FROM sentiment_cycle_daily WHERE trading_date = ?",
        (trading_date,),
    ).fetchone()
    if row is None:
        return None
    return SentimentCycle(
        trading_date=row["trading_date"],
        advance_count=row["advance_count"] or 0,
        decline_count=row["decline_count"] or 0,
        limit_up_count=row["limit_up_count"] or 0,
        limit_down_count=row["limit_down_count"] or 0,
        seal_rate=row["seal_rate"],
        promotion_rate=row["promotion_rate"],
        financing_balance=row["financing_balance"],
        financing_change_pct=row["financing_change_pct"],
        short_selling_balance=row["short_selling_balance"],
        short_selling_change_pct=row["short_selling_change_pct"],
        news_heat=row["news_heat"],
        llm_sentiment_score=row["llm_sentiment_score"],
        composite_sentiment=row["composite_sentiment"],
        cycle_phase=row["cycle_phase"] or "unknown",
        cycle_reason=row["cycle_reason"] or "",
    )


def generate_sentiment_cycle(conn: sqlite3.Connection, trading_date: str) -> SentimentCycle:
    cycle = build_sentiment_cycle(conn, trading_date)
    save_sentiment_cycle(conn, cycle)
    return cycle
