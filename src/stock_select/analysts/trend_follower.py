from __future__ import annotations

import sqlite3
from typing import Any

from ..analyst_types import AnalystVerdict


def trend_follower_analyst(
    conn: sqlite3.Connection,
    decision_id: str,
    row: sqlite3.Row,
    evidence: dict[str, Any],
) -> AnalystVerdict:
    """Evaluate whether the pick aligned with price trend and volume."""
    reasoning: list[str] = []
    errors: list[str] = []
    verdict = "NEUTRAL"
    confidence = 0.5

    return_pct = float(row["return_pct"] or 0)
    tech_score = float(row["technical_score"] or 0)
    is_suspended = int(row["is_suspended"] or 0)
    is_limit_up = int(row["is_limit_up"] or 0)

    # 1. Technical score vs outcome
    if tech_score > 0 and return_pct > 0:
        reasoning.append(f"技术评分({tech_score:.2f})>0 且收益({return_pct:.2%})>0，趋势判断正确")
        verdict = "AGREE"
        confidence = max(confidence, 0.65 + abs(tech_score) * 0.15)
    elif tech_score > 0 and return_pct <= 0:
        reasoning.append(f"技术评分({tech_score:.2f})>0 但收益({return_pct:.2%})<=0，趋势判断失效")
        errors.append("overweighted_technical")
        verdict = "DISAGREE"
        confidence = max(confidence, 0.6)
    elif tech_score <= 0 and return_pct > 0:
        reasoning.append(f"技术评分不高({tech_score:.2f})但收益为正，可能存在非趋势驱动因素")
        verdict = "NEUTRAL"
        confidence = 0.45

    # 2. Execution quality
    if is_suspended:
        reasoning.append("选股当日停牌，执行受阻")
        errors.append("entry_unfillable")
        verdict = "DISAGREE"
        confidence = min(confidence + 0.15, 0.9)
    if is_limit_up:
        reasoning.append("选股当日涨停，可能无法买入")
        errors.append("entry_unfillable")

    # 3. Volume check from recent prices
    prices = evidence.get("recent_prices", [])
    if len(prices) >= 5:
        volumes = [float(p.get("volume", 0)) for p in prices[:5]]
        avg_volume = sum(volumes) / len(volumes)
        latest_volume = float(prices[0].get("volume", 0)) if prices else 0
        if avg_volume > 0 and latest_volume > avg_volume * 1.5:
            reasoning.append(f"近期成交量放量(当前{latest_volume:.0f}>均值{avg_volume:.0f})，量能支持")
        elif avg_volume > 0 and latest_volume < avg_volume * 0.5:
            reasoning.append(f"近期成交量萎缩({latest_volume:.0f}<均值{avg_volume:.0f})，关注持续性")

    # 4. Momentum from recent price changes
    if len(prices) >= 3:
        closes = [float(p.get("close", 0)) for p in prices[:3]]
        if all(closes[i] >= closes[i + 1] for i in range(len(closes) - 1)):
            reasoning.append("近几日价格持续走高，短期趋势向好")
        elif all(closes[i] <= closes[i + 1] for i in range(len(closes) - 1)):
            reasoning.append("近几日价格持续走低，短期趋势偏弱")

    return AnalystVerdict(
        analyst_key="trend_follower",
        decision_id=decision_id,
        verdict=verdict,
        confidence=round(min(confidence, 0.95), 2),
        reasoning=reasoning if reasoning else ["数据不足以进行趋势分析"],
        suggested_errors=errors,
    )
