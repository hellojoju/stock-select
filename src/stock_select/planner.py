"""Planner Agent: decides today's focus industries and risks."""
from __future__ import annotations

import os
import sqlite3
from typing import Any

from . import repository


def plan_preopen_focus(conn: sqlite3.Connection, trading_date: str) -> dict[str, Any]:
    """Generate today's focus plan based on recent market data."""
    recent_sectors = conn.execute(
        """
        SELECT industry, sector_return_pct, relative_strength_rank,
               theme_strength, catalyst_count
        FROM sector_theme_signals
        WHERE trading_date < ?
        ORDER BY trading_date DESC, sector_return_pct DESC
        LIMIT 5
        """,
        (trading_date,),
    ).fetchall()

    market_env = conn.execute(
        """
        SELECT market_environment, trend_type, volatility_level
        FROM trading_days
        WHERE trading_date < ? AND market_environment IS NOT NULL
        ORDER BY trading_date DESC LIMIT 1
        """,
        (trading_date,),
    ).fetchone()

    recent_events = conn.execute(
        """
        SELECT event_type, industry, impact_score, summary
        FROM event_signals
        WHERE trading_date = ? AND impact_score > 0.5
        ORDER BY impact_score DESC
        LIMIT 3
        """,
        (trading_date,),
    ).fetchall()

    watch_risks = _extract_risks(conn, trading_date)

    plan: dict[str, Any] = {
        "trading_date": trading_date,
        "focus_sectors": [dict(r) for r in recent_sectors],
        "market_environment": dict(market_env) if market_env else None,
        "high_impact_events": [dict(r) for r in recent_events],
        "watch_risks": watch_risks,
        "llm_notes": None,
    }

    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
    if api_key:
        plan["llm_notes"] = _call_planner_llm(plan)

    return plan


def _extract_risks(conn: sqlite3.Connection, trading_date: str) -> list[str]:
    """Extract risk flags from recent data."""
    risks: list[str] = []

    low_liquidity = conn.execute(
        """
        SELECT COUNT(*) as cnt FROM stocks s
        LEFT JOIN daily_prices dp ON dp.stock_code = s.stock_code AND dp.trading_date = ?
        WHERE dp.amount < 50000000
        """,
        (trading_date,),
    ).fetchone()
    if low_liquidity and low_liquidity["cnt"] > 200:
        risks.append(f"{low_liquidity['cnt']} stocks with low liquidity (<50M)")

    st_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM stocks WHERE is_st = 1"
    ).fetchone()
    if st_count and st_count["cnt"] > 0:
        risks.append(f"{st_count['cnt']} ST stocks in universe")

    return risks


def _call_planner_llm(plan: dict[str, Any]) -> str | None:
    """Call LLM to add focus notes to the plan."""
    try:
        import anthropic
    except ImportError:
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
    if not api_key:
        return None

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            system=(
                "You are a market planning assistant for an A-share stock selection system. "
                "Given today's market data summary, provide concise focus recommendations. "
                "Highlight sectors to watch, risks to monitor, and any anomalies."
            ),
            messages=[{
                "role": "user",
                "content": (
                    f"Today: {plan['trading_date']}\n"
                    f"Top sectors: {plan['focus_sectors']}\n"
                    f"Market environment: {plan['market_environment']}\n"
                    f"Watch risks: {plan['watch_risks']}"
                ),
            }],
        )
        return response.content[0].text
    except Exception:
        return None
