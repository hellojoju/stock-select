"""Build review packets for LLM consumption."""
from __future__ import annotations

import json
from typing import Any


KNOWN_ERROR_TAXONOMY = [
    "data_missing",
    "false_catalyst",
    "overweighted_technical",
    "underweighted_fundamental",
    "risk_underestimated",
    "sector_rotation_missed",
    "entry_unfillable",
]


def build_decision_review_packet(
    decision_row: dict,
    outcome_row: dict,
    factor_checks: list[dict],
    evidence: list[dict],
) -> dict[str, Any]:
    """Build a compressed review packet for LLM decision review."""
    return {
        "target": {"type": "decision", "id": decision_row["decision_id"]},
        "preopen_snapshot": {
            "candidate_packet": json.loads(decision_row.get("packet_json", "{}")),
            "pick_thesis": json.loads(decision_row.get("thesis_json", "{}")),
            "risk_notes": json.loads(decision_row.get("risks_json", "[]")),
        },
        "postclose_facts": {
            "outcome": {
                "entry_price": outcome_row["entry_price"],
                "close_price": outcome_row["close_price"],
                "return_pct": outcome_row["return_pct"],
                "max_drawdown_intraday_pct": outcome_row["max_drawdown_intraday_pct"],
            },
            "relative_performance": {"index_return": outcome_row.get("index_return_pct", 0)},
            "sector_performance": {"industry": decision_row.get("industry", ""), "sector_return": 0},
        },
        "events": {"preopen_visible": [], "postdecision": []},
        "deterministic_checks": [
            {"factor": fc["factor_type"], "verdict": fc["verdict"], "error": fc.get("error_type")}
            for fc in factor_checks
        ],
        "known_error_taxonomy": KNOWN_ERROR_TAXONOMY,
        "allowed_outputs": {
            "max_attributions": 5,
            "must_cite_evidence_for_extracted": True,
            "optimization_signal_default_status": "candidate",
        },
    }


def build_system_prompt() -> str:
    """Return the system prompt for LLM review."""
    return (
        "You are a stock selection review assistant. Your role is to analyze past "
        "pick decisions, identify what went right/wrong, and suggest parameter "
        "adjustments. Always cite evidence for EXTRACTED claims. Never fabricate "
        "data that is not in the provided packet."
    )


def build_user_prompt(packet: dict[str, Any]) -> str:
    """Return the user prompt for LLM review."""
    return (
        f"Review the following decision packet:\n\n"
        f"{json.dumps(packet, indent=2, ensure_ascii=False)}\n\n"
        f"Please provide:\n"
        f"1. Attribution claims about what drove the outcome\n"
        f"2. What was right about the original decision\n"
        f"3. What was wrong or missed\n"
        f"4. Any missing signals\n"
        f"5. Suggested parameter adjustments"
    )
