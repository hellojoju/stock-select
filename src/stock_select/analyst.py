"""Analyst Agent: deep dive into specific industries and stocks."""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from typing import Any

from .planner import plan_preopen_focus


@dataclass(frozen=True)
class IndustrySignal:
    """Industry-level signal with supporting data."""
    industry: str
    sector_return_pct: float
    relative_strength_rank: int | None
    momentum_score: float | None
    catalyst_count: int | None
    recommendation: str


@dataclass(frozen=True)
class StockInsight:
    """Single stock insight from industry analysis."""
    stock_code: str
    stock_name: str
    industry: str
    momentum_score: float
    amount: float
    is_st: bool
    is_suspended: bool
    recommendation: str
    reason: str


def analyze_industry(conn: sqlite3.Connection, industry: str, trading_date: str) -> IndustrySignal:
    """Analyze a specific industry and return a signal."""
    industry_data = conn.execute(
        """
        SELECT industry, sector_return_pct, relative_strength_rank,
               theme_strength, catalyst_count
        FROM sector_theme_signals
        WHERE trading_date = ? AND industry = ?
        """,
        (trading_date, industry),
    ).fetchone()

    if not industry_data:
        return IndustrySignal(
            industry=industry,
            sector_return_pct=0.0,
            relative_strength_rank=None,
            momentum_score=None,
            catalyst_count=None,
            recommendation="skip",
        )

    d = dict(industry_data)
    momentum = _compute_momentum(conn, industry, trading_date)
    recommendation = _classify_industry(d, momentum)

    return IndustrySignal(
        industry=d["industry"],
        sector_return_pct=d["sector_return_pct"] or 0.0,
        relative_strength_rank=d.get("relative_strength_rank"),
        momentum_score=momentum,
        catalyst_count=d.get("catalyst_count"),
        recommendation=recommendation,
    )


def find_stocks_in_industry(
    conn: sqlite3.Connection,
    industry: str,
    trading_date: str,
    *,
    limit: int = 10,
) -> list[StockInsight]:
    """Find stocks in a given industry with scoring data."""
    rows = conn.execute(
        """
        SELECT s.stock_code, s.name, s.industry, s.is_st,
               dp.close, dp.volume, dp.amount, dp.is_suspended,
               dp.is_limit_up, dp.is_limit_down
        FROM stocks s
        LEFT JOIN daily_prices dp ON dp.stock_code = s.stock_code AND dp.trading_date = ?
        WHERE s.industry = ?
        ORDER BY dp.amount DESC
        LIMIT ?
        """,
        (trading_date, industry, limit),
    ).fetchall()

    insights: list[StockInsight] = []
    for r in rows:
        d = dict(r)
        recommendation = _score_stock(conn, d, trading_date)
        reasons = _build_reasons(d, recommendation)
        insights.append(
            StockInsight(
                stock_code=d["stock_code"],
                stock_name=d.get("name", ""),
                industry=d.get("industry", ""),
                momentum_score=_single_stock_momentum(conn, d["stock_code"], trading_date),
                amount=d.get("amount", 0.0) or 0.0,
                is_st=bool(d.get("is_st", False)),
                is_suspended=bool(d.get("is_suspended", False)),
                recommendation=recommendation,
                reason=reasons,
            )
        )
    return insights


def run_analysis(conn: sqlite3.Connection, trading_date: str) -> dict[str, Any]:
    """Run full analysis: planner focus -> industry deep dive -> stock insights."""
    plan = plan_preopen_focus(conn, trading_date)

    industries = plan.get("focus_sectors", [])
    industry_signals = []
    all_insights: list[dict[str, Any]] = []

    for sector in industries[:3]:
        ind_name = sector.get("industry")
        if not ind_name:
            continue
        signal = analyze_industry(conn, ind_name, trading_date)
        industry_signals.append(
            {
                "industry": signal.industry,
                "sector_return_pct": signal.sector_return_pct,
                "momentum_score": signal.momentum_score,
                "recommendation": signal.recommendation,
            }
        )

        if signal.recommendation != "skip":
            insights = find_stocks_in_industry(conn, ind_name, trading_date)
            for insight in insights:
                if insight.recommendation in ("watch", "buy"):
                    all_insights.append(
                        {
                            "stock_code": insight.stock_code,
                            "stock_name": insight.stock_name,
                            "industry": insight.industry,
                            "momentum_score": insight.momentum_score,
                            "amount": insight.amount,
                            "is_st": insight.is_st,
                            "is_suspended": insight.is_suspended,
                            "recommendation": insight.recommendation,
                            "reason": insight.reason,
                        }
                    )

    result = {
        "trading_date": trading_date,
        "planner_focus_count": len(industries),
        "industry_signals": industry_signals,
        "stock_insights": all_insights,
    }

    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
    if api_key and all_insights:
        result["llm_synthesis"] = _call_analyst_llm(result)

    return result


def _compute_momentum(conn: sqlite3.Connection, industry: str, trading_date: str, window: int = 5) -> float:
    """Compute industry momentum as average return over recent days."""
    rows = conn.execute(
        """
        SELECT sector_return_pct FROM sector_theme_signals
        WHERE industry = ? AND trading_date <= ?
        ORDER BY trading_date DESC
        LIMIT ?
        """,
        (industry, trading_date, window),
    ).fetchall()

    if not rows:
        return 0.0

    values = [r["sector_return_pct"] for r in rows if r["sector_return_pct"] is not None]
    return sum(values) / len(values) if values else 0.0


def _classify_industry(data: dict, momentum: float) -> str:
    """Classify industry as buy/watch/avoid based on signals."""
    ret = data.get("sector_return_pct", 0) or 0.0
    strength = data.get("theme_strength", 0) or 0.0
    catalysts = data.get("catalyst_count", 0) or 0

    score = ret * 2 + momentum + strength * 0.5 + catalysts * 0.3
    if score > 5:
        return "buy"
    if score > 1:
        return "watch"
    return "avoid"


def _single_stock_momentum(conn: sqlite3.Connection, stock_code: str, trading_date: str, window: int = 5) -> float:
    """Compute single stock momentum from recent close prices."""
    rows = conn.execute(
        """
        SELECT close FROM daily_prices
        WHERE stock_code = ? AND trading_date <= ?
        ORDER BY trading_date DESC
        LIMIT ?
        """,
        (stock_code, trading_date, window),
    ).fetchall()

    if len(rows) < 2:
        return 0.0

    closes = [r["close"] for r in rows if r["close"] is not None]
    if len(closes) < 2:
        return 0.0

    # Simple momentum: (latest - oldest) / oldest
    return (closes[0] - closes[-1]) / closes[-1] if closes[-1] != 0 else 0.0


def _score_stock(conn: sqlite3.Connection, data: dict, trading_date: str) -> str:
    """Score a stock as buy/watch/avoid based on its characteristics."""
    if data.get("is_suspended"):
        return "avoid"
    if data.get("is_st"):
        return "avoid"

    amount = data.get("amount", 0) or 0.0
    if amount == 0:
        return "skip"

    # Limit up = strong signal
    if data.get("is_limit_up"):
        return "buy"

    # Higher amount = more liquid = better
    if amount > 500_000_000:
        return "buy"
    if amount > 100_000_000:
        return "watch"
    return "avoid"


def _build_reasons(data: dict, recommendation: str) -> str:
    """Build human-readable reason string."""
    parts: list[str] = []
    if data.get("is_st"):
        parts.append("ST stock")
    if data.get("is_suspended"):
        parts.append("suspended")
    if data.get("is_limit_up"):
        parts.append("limit up")
    if recommendation == "buy":
        parts.append("strong signals")
    elif recommendation == "watch":
        parts.append("moderate signals")
    elif recommendation == "avoid":
        parts.append("weak signals or low liquidity")

    amount = data.get("amount", 0) or 0
    if amount > 0:
        parts.append(f"amount={amount/1e6:.0f}M")

    return ", ".join(parts) if parts else "no data"


def _call_analyst_llm(result: dict[str, Any]) -> str | None:
    """Call LLM to synthesize analysis results."""
    try:
        import anthropic
    except ImportError:
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
    if not api_key:
        return None

    try:
        client = anthropic.Anthropic(api_key=api_key)
        summary = result.get("stock_insights", [])[:5]
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=(
                "You are an A-share market analyst. "
                "Given industry signals and stock insights, provide a concise synthesis "
                "of today's opportunities. Max 3 sentences."
            ),
            messages=[{
                "role": "user",
                "content": f"Analysis summary: {summary}",
            }],
        )
        return response.content[0].text
    except Exception:
        return None
