"""Contrarian analyst: uses LLM to challenge pick decisions from the opposite perspective."""
from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from ..llm_config import get_budget, resolve_llm_config
from ..llm_review import get_llm_client
from ..analyst_types import AnalystVerdict

logger = logging.getLogger(__name__)

CONTRARIAN_SYSTEM_PROMPT = (
    "你是一个逆向思辨分析师。你的职责是从对立面审视选股决策，找出被忽略的反面证据和思维盲区。\n\n"
    "你需要判断：\n"
    "1. 这笔交易的选股逻辑是否存在明显缺陷？\n"
    "2. 是否有被忽略的负面因素？\n"
    "3. 收益结果是否真实反映了选股质量，还是运气成分？\n\n"
    "输出严格遵循以下JSON格式：\n"
    "{\n"
    '  "verdict": "AGREE" | "DISAGREE" | "NEUTRAL",\n'
    '  "confidence": 0.0-1.0,\n'
    '  "reasoning": ["理由1", "理由2", ...],\n'
    '  "suggested_errors": ["error_type1", ...]\n'
    "}\n\n"
    "verdict说明：\n"
    "- AGREE = 逆向思辨后仍然认为选股逻辑成立\n"
    "- DISAGREE = 发现了被忽略的重大缺陷或风险\n"
    "- NEUTRAL = 证据不足以做出明确判断\n\n"
    "suggested_errors从以下选择（可选）：\n"
    "- missed_risk_event: 遗漏风险事件\n"
    "- overweighted_technical: 过度依赖技术面\n"
    "- underweighted_fundamental: 低估基本面\n"
    "- risk_underestimated: 风险低估\n"
    "- false_catalyst: 虚假催化剂\n"
    "- data_missing: 数据缺失导致误判\n"
    "- liquidity_ignored: 忽略流动性风险\n"
    "- sector_rotation_missed: 忽略行业轮动\n"
)


def contrarian_analyst(
    conn: sqlite3.Connection,
    decision_id: str,
    row: sqlite3.Row,
    evidence: dict[str, Any],
) -> AnalystVerdict:
    """Challenge the pick decision from an opposite perspective using LLM."""
    try:
        return _contrarian_impl(conn, decision_id, row, evidence)
    except Exception as exc:
        logger.warning("Contrarian analyst failed, using fallback: %s", exc)
        return _fallback_contrarian(decision_id, row, evidence)


def _contrarian_impl(
    conn: sqlite3.Connection,
    decision_id: str,
    row: sqlite3.Row,
    evidence: dict[str, Any],
) -> AnalystVerdict:
    config = resolve_llm_config()
    if config is None:
        return _fallback_contrarian(decision_id, row, evidence)

    packet = _build_contrarian_packet(row, evidence)
    user_prompt = (
        f"请从逆向思辨角度审视以下选股决策：\n\n"
        f"{json.dumps(packet, indent=2, ensure_ascii=False)}\n\n"
        f"请输出JSON格式的分析结果。"
    )

    client_fn = get_llm_client(config)
    if client_fn is None:
        return _fallback_contrarian(decision_id, row, evidence)

    budget = get_budget()
    budget.check(config)

    result = client_fn(user_prompt, CONTRARIAN_SYSTEM_PROMPT)
    if result is None:
        return _fallback_contrarian(decision_id, row, evidence)

    verdict = result.get("verdict", "NEUTRAL")
    if verdict not in ("AGREE", "DISAGREE", "NEUTRAL"):
        verdict = "NEUTRAL"

    confidence = max(0.0, min(1.0, float(result.get("confidence", 0.5))))

    reasoning = result.get("reasoning", [])
    if isinstance(reasoning, str):
        reasoning = [reasoning]
    if not reasoning:
        reasoning = ["LLM逆向思辨未返回具体理由"]

    errors = result.get("suggested_errors", [])
    if not isinstance(errors, list):
        errors = []

    return AnalystVerdict(
        analyst_key="contrarian",
        decision_id=decision_id,
        verdict=verdict,
        confidence=round(confidence, 2),
        reasoning=reasoning,
        suggested_errors=list(set(errors)),
    )


def _col(row: sqlite3.Row, key: str, default: Any = None) -> Any:
    """Safely get a value from a sqlite3.Row with a default.

    sqlite3.Row supports __getitem__ but not .get(), and columns may be NULL.
    """
    try:
        val = row[key]
        return val if val is not None else default
    except (KeyError, IndexError):
        return default


def _build_contrarian_packet(row: sqlite3.Row, evidence: dict[str, Any]) -> dict[str, Any]:
    """Build a compact data packet for the contrarian LLM prompt."""
    thesis_raw = _col(row, "thesis_json", "{}")
    risks_raw = _col(row, "risks_json", "[]")
    return {
        "stock": {
            "code": row["stock_code"],
            "name": _col(row, "stock_name", ""),
            "industry": _col(row, "industry", ""),
        },
        "decision": {
            "action": _col(row, "action", ""),
            "horizon": _col(row, "horizon", ""),
            "thesis": json.loads(thesis_raw or "{}"),
            "risks": json.loads(risks_raw or "[]"),
        },
        "scores": {
            "technical": _col(row, "technical_score", 0),
            "fundamental": _col(row, "fundamental_score", 0),
            "event": _col(row, "event_score", 0),
            "sector": _col(row, "sector_score", 0),
            "risk_penalty": _col(row, "risk_penalty", 0),
            "total": _col(row, "total_score", 0),
        },
        "outcome": {
            "return_pct": _col(row, "return_pct", 0),
            "max_drawdown": _col(row, "max_drawdown_intraday_pct", 0),
            "hit_sell_rule": _col(row, "hit_sell_rule"),
        },
        "flags": {
            "is_st": bool(int(_col(row, "is_st", 0) or 0)),
            "is_suspended": bool(int(_col(row, "is_suspended", 0) or 0)),
            "is_limit_up": bool(int(_col(row, "is_limit_up", 0) or 0)),
        },
        "evidence_summary": {
            "has_financial_actuals": bool(evidence.get("financial_actuals")),
            "analyst_expectations_count": len(evidence.get("analyst_expectations", [])),
            "risk_events_count": len(evidence.get("risk_events", [])),
            "recent_prices_count": len(evidence.get("recent_prices", [])),
            "order_contracts_count": len(evidence.get("order_contracts", [])),
        },
    }


def _safe_float(row: sqlite3.Row, key: str, default: float = 0.0) -> float:
    try:
        return float(row[key] or default)
    except (KeyError, IndexError, ValueError):
        return default


def _fallback_contrarian(
    decision_id: str,
    row: sqlite3.Row,
    evidence: dict[str, Any],
) -> AnalystVerdict:
    """Rule-based fallback when LLM is not available."""
    reasoning: list[str] = []
    errors: list[str] = []
    verdict = "NEUTRAL"
    confidence = 0.5

    return_pct = _safe_float(row, "return_pct")
    total_score = _safe_float(row, "total_score")

    high_score_good_return = total_score > 0.6 and return_pct > 0
    high_score_bad_return = total_score > 0.6 and return_pct <= 0
    low_score_good_return = total_score < 0.3 and return_pct > 0

    if high_score_bad_return:
        reasoning.append(
            f"综合评分({total_score:.2f})较高但收益为负({return_pct:.2%})"
            "，存在未被评分体系捕获的负面因素"
        )
        errors.append("risk_underestimated")
        verdict = "DISAGREE"
        confidence = 0.6
    elif low_score_good_return:
        reasoning.append(
            f"综合评分不高({total_score:.2f})但收益为正({return_pct:.2%})"
            "，收益可能来自运气而非选股能力"
        )
        verdict = "NEUTRAL"
        confidence = 0.45
    elif high_score_good_return:
        reasoning.append(
            f"综合评分({total_score:.2f})与收益({return_pct:.2%})匹配，未发现明显矛盾"
        )
        verdict = "AGREE"
        confidence = 0.55

    risk_events = evidence.get("risk_events", [])
    if risk_events and return_pct <= 0:
        reasoning.append(f"存在{len(risk_events)}条风险事件且收益为负，风险因素可能被低估")
        errors.append("missed_risk_event")
        if verdict != "DISAGREE":
            verdict = "NEUTRAL"

    return AnalystVerdict(
        analyst_key="contrarian",
        decision_id=decision_id,
        verdict=verdict,
        confidence=round(confidence, 2),
        reasoning=reasoning if reasoning else ["数据不足以进行逆向思辨分析"],
        suggested_errors=errors,
    )
