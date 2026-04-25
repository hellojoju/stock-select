from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


class ContractError(ValueError):
    """Raised when an internal JSON contract is invalid."""


def require_keys(payload: dict[str, Any], keys: list[str], context: str) -> None:
    missing = [key for key in keys if key not in payload]
    if missing:
        raise ContractError(f"{context} missing keys: {', '.join(missing)}")


def require_range(value: float, lower: float, upper: float, field: str) -> None:
    if value < lower or value > upper:
        raise ContractError(f"{field} must be in [{lower}, {upper}], got {value}")


@dataclass(frozen=True)
class PickContract:
    trading_date: str
    horizon: Literal["short", "long"]
    strategy_gene_id: str
    stock_code: str
    action: Literal["BUY", "WATCH", "HOLD"]
    confidence: float
    position_pct: float
    entry_plan: dict[str, Any]
    sell_rules: list[dict[str, Any]]
    thesis: dict[str, list[str]]
    risks: list[str]
    invalid_if: list[str]
    input_snapshot_hash: str
    score: float

    @classmethod
    def validate(cls, payload: dict[str, Any]) -> "PickContract":
        require_keys(
            payload,
            [
                "trading_date",
                "horizon",
                "strategy_gene_id",
                "stock_code",
                "action",
                "confidence",
                "position_pct",
                "entry_plan",
                "sell_rules",
                "thesis",
                "risks",
                "invalid_if",
                "input_snapshot_hash",
                "score",
            ],
            "pick",
        )
        if payload["horizon"] not in {"short", "long"}:
            raise ContractError("pick.horizon must be short or long")
        if payload["action"] not in {"BUY", "WATCH", "HOLD"}:
            raise ContractError("pick.action must be BUY, WATCH, or HOLD")
        require_range(float(payload["confidence"]), 0.0, 1.0, "pick.confidence")
        require_range(float(payload["position_pct"]), 0.0, 1.0, "pick.position_pct")
        thesis = payload["thesis"]
        if not isinstance(thesis, dict):
            raise ContractError("pick.thesis must be an object")
        require_keys(thesis, ["technical", "fundamental", "news", "market_environment"], "pick.thesis")
        if not isinstance(payload["sell_rules"], list) or not payload["sell_rules"]:
            raise ContractError("pick.sell_rules must be a non-empty list")
        return cls(
            trading_date=str(payload["trading_date"]),
            horizon=payload["horizon"],
            strategy_gene_id=str(payload["strategy_gene_id"]),
            stock_code=str(payload["stock_code"]),
            action=payload["action"],
            confidence=float(payload["confidence"]),
            position_pct=float(payload["position_pct"]),
            entry_plan=dict(payload["entry_plan"]),
            sell_rules=list(payload["sell_rules"]),
            thesis={key: list(value) for key, value in thesis.items()},
            risks=list(payload["risks"]),
            invalid_if=list(payload["invalid_if"]),
            input_snapshot_hash=str(payload["input_snapshot_hash"]),
            score=float(payload["score"]),
        )


@dataclass(frozen=True)
class ReviewContract:
    decision_id: str
    outcome: dict[str, Any]
    reason_check: dict[str, list[str]]
    attribution: list[dict[str, Any]]
    gene_update_signal: dict[str, Any]
    evidence: list[dict[str, Any]]

    @classmethod
    def validate(cls, payload: dict[str, Any]) -> "ReviewContract":
        require_keys(
            payload,
            ["decision_id", "outcome", "reason_check", "attribution", "gene_update_signal", "evidence"],
            "review",
        )
        require_keys(
            payload["outcome"],
            ["entry_price", "close_price", "return_pct", "max_drawdown_intraday_pct"],
            "review.outcome",
        )
        require_keys(
            payload["reason_check"],
            ["what_was_right", "what_was_wrong", "missing_signals"],
            "review.reason_check",
        )
        for index, item in enumerate(payload["attribution"]):
            require_keys(item, ["event", "confidence", "evidence"], f"review.attribution[{index}]")
            if item["confidence"] not in {"EXTRACTED", "INFERRED", "AMBIGUOUS"}:
                raise ContractError("review attribution confidence is invalid")
        if not payload["evidence"]:
            raise ContractError("review.evidence must not be empty")
        return cls(
            decision_id=str(payload["decision_id"]),
            outcome=dict(payload["outcome"]),
            reason_check={key: list(value) for key, value in payload["reason_check"].items()},
            attribution=list(payload["attribution"]),
            gene_update_signal=dict(payload["gene_update_signal"]),
            evidence=list(payload["evidence"]),
        )

