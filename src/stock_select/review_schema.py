from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .review_taxonomy import (
    EVIDENCE_CONFIDENCE,
    FACTOR_TYPES,
    PRIMARY_DRIVERS,
    SCOPES,
    SIGNAL_DIRECTIONS,
    SIGNAL_TYPES,
    VERDICTS,
    assert_member,
)


class ReviewSchemaError(ValueError):
    pass


def require(payload: dict[str, Any], field: str) -> Any:
    if field not in payload or payload[field] is None:
        raise ReviewSchemaError(f"Missing required field: {field}")
    return payload[field]


@dataclass(frozen=True)
class FactorReviewItemContract:
    factor_type: str
    verdict: str
    confidence: str

    @classmethod
    def validate(cls, payload: dict[str, Any]) -> "FactorReviewItemContract":
        return cls(
            factor_type=assert_member(require(payload, "factor_type"), FACTOR_TYPES, "factor_type"),
            verdict=assert_member(require(payload, "verdict"), VERDICTS, "verdict"),
            confidence=assert_member(require(payload, "confidence"), EVIDENCE_CONFIDENCE, "confidence"),
        )


@dataclass(frozen=True)
class DecisionReviewContract:
    review_id: str
    decision_id: str
    verdict: str
    primary_driver: str

    @classmethod
    def validate(cls, payload: dict[str, Any]) -> "DecisionReviewContract":
        items = require(payload, "factor_checks")
        if not isinstance(items, list) or not items:
            raise ReviewSchemaError("factor_checks must be a non-empty list")
        for item in items:
            FactorReviewItemContract.validate(item)
        return cls(
            review_id=str(require(payload, "review_id")),
            decision_id=str(require(payload, "decision_id")),
            verdict=assert_member(require(payload, "verdict"), VERDICTS, "verdict"),
            primary_driver=assert_member(require(payload, "primary_driver"), PRIMARY_DRIVERS, "primary_driver"),
        )


@dataclass(frozen=True)
class OptimizationSignalContract:
    signal_type: str
    direction: str
    scope: str
    strength: float
    confidence: float

    @classmethod
    def validate(cls, payload: dict[str, Any]) -> "OptimizationSignalContract":
        strength = float(require(payload, "strength"))
        confidence = float(require(payload, "confidence"))
        if strength < 0 or strength > 1:
            raise ReviewSchemaError("strength must be between 0 and 1")
        if confidence < 0 or confidence > 1:
            raise ReviewSchemaError("confidence must be between 0 and 1")
        return cls(
            signal_type=assert_member(require(payload, "signal_type"), SIGNAL_TYPES, "signal_type"),
            direction=assert_member(require(payload, "direction"), SIGNAL_DIRECTIONS, "direction"),
            scope=assert_member(require(payload, "scope"), SCOPES, "scope"),
            strength=strength,
            confidence=confidence,
        )

