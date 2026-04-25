from __future__ import annotations

VERDICTS = {"RIGHT", "WRONG", "MIXED", "NEUTRAL", "INCONCLUSIVE", "NOT_APPLICABLE"}
PRIMARY_DRIVERS = {"technical", "fundamental", "event", "sector", "risk", "execution", "market", "unknown"}
FACTOR_TYPES = {"technical", "fundamental", "event", "sector", "risk", "execution", "market"}
EVIDENCE_CONFIDENCE = {"EXTRACTED", "INFERRED", "AMBIGUOUS"}
EVIDENCE_VISIBILITY = {"PREOPEN_VISIBLE", "POSTCLOSE_OBSERVED", "POSTDECISION_EVENT"}
SIGNAL_STATUS = {"open", "candidate", "consumed", "dismissed"}
SIGNAL_TYPES = {
    "increase_weight",
    "decrease_weight",
    "raise_threshold",
    "lower_threshold",
    "add_filter",
    "relax_filter",
    "adjust_position",
    "adjust_sell_rule",
    "add_data_source",
    "observe_only",
}
SIGNAL_DIRECTIONS = {"up", "down", "add", "remove", "hold"}
SCOPES = {"global", "market_environment", "industry", "horizon", "gene"}

ERROR_TYPES = {
    "data_missing",
    "data_stale",
    "source_conflict",
    "bad_snapshot",
    "candidate_not_recalled",
    "hard_filter_too_strict",
    "threshold_too_strict",
    "threshold_too_loose",
    "diversity_rerank_missed",
    "overweighted_technical",
    "underweighted_technical",
    "underweighted_fundamental",
    "overweighted_fundamental",
    "underweighted_event",
    "false_catalyst",
    "underweighted_sector",
    "sector_rotation_missed",
    "sector_weak_but_stock_picked",
    "risk_underestimated",
    "risk_overestimated",
    "liquidity_ignored",
    "entry_unfillable",
    "entry_too_chasing",
    "position_too_large",
    "position_too_small",
    "sell_rule_too_tight",
    "sell_rule_too_loose",
    "time_exit_mismatch",
    "thesis_not_specific",
    "thesis_contradicted_by_data",
    "missing_counterargument",
    "llm_over_inferred",
    "ambiguous_attribution",
    "late_signal",
    "missed_earnings_surprise",
    "false_earnings_surprise",
    "missed_order_signal",
    "overtrusted_framework_order",
    "missed_guidance_revision",
    "analyst_expectation_missing",
}


class ReviewTaxonomyError(ValueError):
    pass


def assert_member(value: str | None, allowed: set[str], field: str) -> str:
    if value not in allowed:
        raise ReviewTaxonomyError(f"Invalid {field}: {value}")
    return value

