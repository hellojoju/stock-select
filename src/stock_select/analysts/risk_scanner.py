from __future__ import annotations

import sqlite3
from typing import Any

from ..analyst_types import AnalystVerdict


def risk_scanner_analyst(
    conn: sqlite3.Connection,
    decision_id: str,
    row: sqlite3.Row,
    evidence: dict[str, Any],
) -> AnalystVerdict:
    """Scan for known risk factors and red flags."""
    reasoning: list[str] = []
    errors: list[str] = []
    verdict = "NEUTRAL"
    confidence = 0.6
    risk_count = 0

    # 1. ST status
    is_st = int(row["is_st"] or 0)
    if is_st:
        reasoning.append("该股票为ST/*ST股票，存在退市风险")
        errors.append("risk_underestimated")
        risk_count += 1
        verdict = "DISAGREE"
        confidence = 0.85

    # 2. Suspension
    is_suspended = int(row["is_suspended"] or 0)
    if is_suspended:
        reasoning.append("选股当日停牌，流动性风险")
        errors.append("liquidity_ignored")
        risk_count += 1

    # 3. Risk penalty from scoring
    risk_penalty = float(row["risk_penalty"] or 0)
    return_pct = float(row["return_pct"] or 0)
    drawdown = float(row["max_drawdown_intraday_pct"] or 0)

    if risk_penalty > 0.3 and return_pct <= 0:
        reasoning.append(f"风险惩罚({risk_penalty:.2f})较高且收益为负({return_pct:.2%})，风险判断准确")
        risk_count += 1
        confidence = min(confidence + 0.1, 0.9)
    elif risk_penalty < 0.1 and drawdown <= -0.04:
        reasoning.append(f"风险惩罚({risk_penalty:.2f})偏低但回撤({drawdown:.2%})较大，风险被低估")
        errors.append("risk_underestimated")
        risk_count += 1
        verdict = "DISAGREE"
        confidence = min(confidence + 0.15, 0.9)

    # 4. Risk events
    risk_events = evidence.get("risk_events", [])
    for re in risk_events:
        event_type = re.get("event_type", "") or re.get("risk_type", "") or ""
        if "减持" in str(event_type) or "减仓" in str(event_type):
            reasoning.append(f"存在减持风险事件: {event_type}")
            errors.append("missed_risk_event")
            risk_count += 1
        elif "监管" in str(event_type) or "处罚" in str(event_type) or "问询" in str(event_type):
            reasoning.append(f"存在监管风险事件: {event_type}")
            errors.append("missed_risk_event")
            risk_count += 1
        elif "st" in str(event_type).lower() or "退市" in str(event_type):
            reasoning.append(f"存在ST/退市风险: {event_type}")
            errors.append("risk_underestimated")
            risk_count += 1

    # 5. Order contract events (large block trades, etc.)
    order_contracts = evidence.get("order_contracts", [])
    for oc in order_contracts:
        event_type = oc.get("event_type", "") or ""
        if "大宗" in str(event_type) or "折价" in str(event_type):
            reasoning.append(f"存在大宗交易折价事件: {event_type}")

    # 6. Overall verdict
    if risk_count >= 2:
        verdict = "DISAGREE"
        confidence = max(confidence, 0.75)
        if not reasoning:
            reasoning.append(f"发现{risk_count}个风险点")
    elif risk_count == 0:
        reasoning.append("未发现明显风险信号")
        verdict = "AGREE"
        confidence = min(confidence + 0.1, 0.85)

    return AnalystVerdict(
        analyst_key="risk_scanner",
        decision_id=decision_id,
        verdict=verdict,
        confidence=round(confidence, 2),
        reasoning=reasoning,
        suggested_errors=list(set(errors)),
    )
