from __future__ import annotations

VERDICTS = {"RIGHT", "WRONG", "MIXED", "NEUTRAL", "INCONCLUSIVE", "NOT_APPLICABLE"}
PRIMARY_DRIVERS = {
    "technical",
    "fundamental",
    "event",
    "sector",
    "risk",
    "execution",
    "market",
    "earnings_surprise",
    "order_contract",
    "business_kpi",
    "risk_event",
    "expectation",
    "unknown",
}
FACTOR_TYPES = {
    "technical",
    "fundamental",
    "event",
    "sector",
    "risk",
    "execution",
    "market",
    "earnings_surprise",
    "order_contract",
    "business_kpi",
    "risk_event",
    "expectation",
}
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
    "increase_earnings_surprise_weight",
    "decrease_earnings_surprise_weight",
    "increase_order_event_weight",
    "increase_kpi_momentum_weight",
    "increase_risk_penalty",
    "tighten_evidence_coverage_filter",
}
SIGNAL_DIRECTIONS = {"up", "down", "add", "remove", "hold"}
SCOPES = {"global", "market_environment", "industry", "horizon", "gene"}

RISK_TYPES = {
    "regulatory_penalty",
    "exchange_inquiry",
    "litigation",
    "shareholder_reduction",
    "pledge_risk",
    "delisting_risk",
    "st_risk",
    "suspension",
    "negative_earnings_warning",
    "audit_opinion_risk",
}

SURPRISE_TYPES = {
    "positive_surprise",
    "negative_surprise",
    "in_line",
    "expectation_missing",
    "actual_missing",
}

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
    "missed_business_kpi_signal",
    "missed_risk_event",
    "overtrusted_framework_order",
    "missed_guidance_revision",
    "analyst_expectation_missing",
    "financial_actual_missing",
    "evidence_as_of_date_invalid",
    "event_visibility_invalid",
    "low_evidence_coverage",
}


class ReviewTaxonomyError(ValueError):
    pass


def assert_member(value: str | None, allowed: set[str], field: str) -> str:
    if value not in allowed:
        raise ReviewTaxonomyError(f"Invalid {field}: {value}")
    return value
