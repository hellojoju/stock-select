"""LLM review output contract validation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .review_taxonomy import EVIDENCE_CONFIDENCE


class LLMContractError(ValueError):
    pass


def _require(payload: dict[str, Any], key: str, context: str = "") -> Any:
    if key not in payload or payload[key] is None:
        raise LLMContractError(f"{context} missing required key: {key}")
    return payload[key]


@dataclass(frozen=True)
class AttributionClaim:
    claim: str
    confidence: Literal["EXTRACTED", "INFERRED", "AMBIGUOUS"]
    evidence_ids: list[str]

    @classmethod
    def validate(cls, payload: dict[str, Any]) -> "AttributionClaim":
        confidence = _require(payload, "confidence", "attribution")
        if confidence == "EXTRACTED" and not payload.get("evidence_ids"):
            raise LLMContractError("EXTRACTED claims must have evidence_ids")
        return cls(
            claim=str(_require(payload, "claim", "attribution")),
            confidence=confidence if confidence in EVIDENCE_CONFIDENCE else "AMBIGUOUS",
            evidence_ids=list(payload.get("evidence_ids", [])),
        )


@dataclass(frozen=True)
class LLMReviewContract:
    review_target: dict[str, str]
    attribution: list[AttributionClaim]
    reason_check: dict[str, list[str]]
    suggested_errors: list[dict[str, Any]]
    suggested_optimization_signals: list[dict[str, Any]]
    summary: str

    @classmethod
    def validate(cls, payload: dict[str, Any]) -> "LLMReviewContract":
        target = _require(payload, "review_target", "root")
        _require(target, "type", "review_target")
        _require(target, "id", "review_target")

        attribution = [
            AttributionClaim.validate(item)
            for item in _require(payload, "attribution", "root")
        ]

        reason_check = _require(payload, "reason_check", "root")
        for key in ["what_was_right", "what_was_wrong", "missing_signals"]:
            if key not in reason_check:
                reason_check[key] = []

        return cls(
            review_target=target,
            attribution=attribution,
            reason_check=reason_check,
            suggested_errors=list(payload.get("suggested_errors", [])),
            suggested_optimization_signals=list(payload.get("suggested_optimization_signals", [])),
            summary=str(payload.get("summary", "")),
        )
