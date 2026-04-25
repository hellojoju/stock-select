from __future__ import annotations

import sqlite3
from typing import Any

from ..analyst_types import AnalystVerdict


def fundamental_check_analyst(
    conn: sqlite3.Connection,
    decision_id: str,
    row: sqlite3.Row,
    evidence: dict[str, Any],
) -> AnalystVerdict:
    """Verify whether the pick had fundamental support."""
    reasoning: list[str] = []
    errors: list[str] = []
    verdict = "NEUTRAL"
    confidence = 0.5

    return_pct = float(row["return_pct"] or 0)
    fundamental_score = float(row["fundamental_score"] or 0)

    # 1. Fundamental score vs outcome
    if fundamental_score > 0.4 and return_pct > 0:
        reasoning.append(f"基本面评分({fundamental_score:.2f})>0.4 且收益({return_pct:.2%})>0，基本面支撑有效")
        verdict = "AGREE"
        confidence = max(confidence, 0.7)
    elif fundamental_score > 0.4 and return_pct <= 0:
        reasoning.append(f"基本面评分较高({fundamental_score:.2f})但收益为负({return_pct:.2%})，可能有利空未被捕获")
        errors.append("underweighted_fundamental")
        verdict = "DISAGREE"
        confidence = max(confidence, 0.55)
    elif fundamental_score < 0.2 and return_pct > 0:
        reasoning.append(f"基本面评分偏低({fundamental_score:.2f})但收益为正，上涨非基本面驱动")
        verdict = "NEUTRAL"
        confidence = 0.4

    # 2. Check financial actuals
    fa = evidence.get("financial_actuals", {})
    if fa:
        revenue_growth = fa.get("revenue_growth")
        net_profit_growth = fa.get("net_profit_growth")
        roe = fa.get("roe")

        if revenue_growth is not None and net_profit_growth is not None:
            if float(revenue_growth) > 0 and float(net_profit_growth) > 0:
                reasoning.append(f"营收同比+{float(revenue_growth)*100:.1f}%，净利润同比+{float(net_profit_growth)*100:.1f}%，基本面稳健")
                confidence = min(confidence + 0.1, 0.9)
            elif float(revenue_growth) < -0.1 or float(net_profit_growth) < -0.2:
                reasoning.append(f"营收同比{float(revenue_growth)*100:.1f}%，净利润同比{float(net_profit_growth)*100:.1f}%，业绩承压")
                errors.append("financial_actual_missing")
                if verdict != "DISAGREE":
                    verdict = "NEUTRAL"

        if roe is not None and float(roe) > 0.1:
            reasoning.append(f"ROE={float(roe)*100:.1f}%，盈利能力较好")

    # 3. Check earnings surprises
    surprises = evidence.get("earnings_surprises", [])
    for s in surprises:
        sp = float(s.get("surprise_pct") or s.get("net_profit_surprise_pct") or 0)
        st = s.get("surprise_type", "")
        if sp > 0:
            reasoning.append(f"业绩超预期(+{sp*100:.1f}%)，利好")
            confidence = min(confidence + 0.1, 0.9)
        elif sp < -0.05:
            reasoning.append(f"业绩不及预期({sp*100:.1f}%)，利空")
            errors.append("missed_earnings_surprise")

    # 4. Check analyst expectations
    expectations = evidence.get("analyst_expectations", [])
    if expectations:
        reasoning.append(f"有{len(expectations)}条分析师预期数据可用")

    if not reasoning:
        reasoning.append("数据不足以进行基本面分析")

    return AnalystVerdict(
        analyst_key="fundamental_check",
        decision_id=decision_id,
        verdict=verdict,
        confidence=round(min(confidence, 0.95), 2),
        reasoning=reasoning,
        suggested_errors=errors,
    )
