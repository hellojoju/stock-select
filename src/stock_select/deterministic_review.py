from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from . import repository
from .optimization_signals import upsert_optimization_signal
from .review_schema import DecisionReviewContract


REVIEW_FACTORS = [
    "technical",
    "fundamental",
    "event",
    "sector",
    "risk",
    "execution",
    "earnings_surprise",
    "order_contract",
    "business_kpi",
    "risk_event",
    "expectation",
]


def run_deterministic_review(conn: sqlite3.Connection, trading_date: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT decision_id
        FROM pick_decisions
        WHERE trading_date = ?
        ORDER BY strategy_gene_id, score DESC
        """,
        (trading_date,),
    ).fetchall()
    review_ids = [review_decision(conn, row["decision_id"]) for row in rows]
    conn.commit()
    return review_ids


def review_decision(conn: sqlite3.Connection, decision_id: str) -> str:
    row = load_decision_row(conn, decision_id)
    review_id = build_review_id(decision_id)
    packet = repository.loads(row["packet_json"], {}) if row["packet_json"] else {}

    # Rejected decisions have no outcome - record as "rejected"
    if row["entry_price"] is None:
        _record_rejected_review(conn, review_id, row)
        return review_id

    outcome = {
        "entry_price": float(row["entry_price"]),
        "close_price": float(row["close_price"]),
        "return_pct": float(row["return_pct"]),
        "benchmark_return": float(row["benchmark_return"] or 0) if row["benchmark_return"] is not None else 0.0,
        "sector_return": float(row["sector_return"] or 0) if row["sector_return"] is not None else 0.0,
        "alpha": float(row["alpha"]) if row["alpha"] is not None else float(row["return_pct"]),
        "relative_return_pct": float(row["return_pct"]) - float(row["index_return_pct"] or 0),
        "max_drawdown_intraday_pct": float(row["max_drawdown_intraday_pct"]),
        "hit_sell_rule": row["hit_sell_rule"],
    }
    evidence_ids = upsert_decision_evidence(conn, review_id, row, packet)
    evidence_by_source = evidence_ids_by_source(conn, review_id)
    factor_items = build_factor_items(conn, row, packet, evidence_ids, evidence_by_source)
    verdict = overall_verdict(outcome["alpha"], factor_items)
    primary_driver = choose_primary_driver(factor_items, packet)
    summary = (
        f"{row['trading_date']} {row['strategy_gene_id']} {row['stock_code']} "
        f"{verdict.lower()}; return {outcome['return_pct']:.2%}, alpha {outcome['alpha']:.2%}, driver {primary_driver}."
    )
    deterministic = {
        "decision_id": decision_id,
        "candidate_packet": packet,
        "outcome": outcome,
        "factor_checks": factor_items,
        "evidence_ids": evidence_ids,
    }
    payload = {
        "review_id": review_id,
        "decision_id": decision_id,
        "verdict": verdict,
        "primary_driver": primary_driver,
        "factor_checks": factor_items,
    }
    DecisionReviewContract.validate(payload)
    conn.execute(
        """
        INSERT INTO decision_reviews(
          review_id, decision_id, trading_date, strategy_gene_id, stock_code,
          verdict, primary_driver, return_pct, relative_return_pct,
          max_drawdown_intraday_pct, thesis_quality_score, evidence_quality_score,
          deterministic_json, summary, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(decision_id) DO UPDATE SET
          verdict = excluded.verdict,
          primary_driver = excluded.primary_driver,
          return_pct = excluded.return_pct,
          relative_return_pct = excluded.relative_return_pct,
          max_drawdown_intraday_pct = excluded.max_drawdown_intraday_pct,
          thesis_quality_score = excluded.thesis_quality_score,
          evidence_quality_score = excluded.evidence_quality_score,
          deterministic_json = excluded.deterministic_json,
          summary = excluded.summary,
          updated_at = CURRENT_TIMESTAMP
        """,
        (
            review_id,
            decision_id,
            row["trading_date"],
            row["strategy_gene_id"],
            row["stock_code"],
            verdict,
            primary_driver,
            outcome["return_pct"],
            outcome["relative_return_pct"],
            outcome["max_drawdown_intraday_pct"],
            thesis_quality_score(row),
            evidence_quality_score(evidence_ids),
            repository.dumps(deterministic),
            summary,
        ),
    )
    for item in factor_items:
        upsert_factor_item(conn, review_id, item)
        if item.get("error_type"):
            upsert_review_error(
                conn,
                review_scope="decision",
                review_id=review_id,
                error_type=item["error_type"],
                severity=min(1.0, abs(float(item.get("contribution_score", 0))) + 0.25),
                confidence=0.72 if item["confidence"] == "EXTRACTED" else 0.55,
                evidence_ids=item["evidence_ids"],
            )
            maybe_signal_from_error(conn, row, review_id, item)

    for missing_field in packet.get("missing_fields", []):
        upsert_review_error(
            conn,
            review_scope="decision",
            review_id=review_id,
            error_type="data_missing",
            severity=0.3,
            confidence=0.9,
            evidence_ids=evidence_ids[:1],
        )

    return review_id


def load_decision_row(conn: sqlite3.Connection, decision_id: str) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT p.*, s.name AS stock_name, s.industry, o.entry_price, o.close_price,
               o.return_pct, o.max_drawdown_intraday_pct, o.hit_sell_rule,
               o.benchmark_return, o.sector_return, o.alpha,
               t.index_return_pct, c.packet_json, c.technical_score,
               c.fundamental_score, c.event_score, c.sector_score, c.risk_penalty,
               d.open, d.high, d.low, d.close, d.is_suspended, d.is_limit_up
        FROM pick_decisions p
        JOIN stocks s ON s.stock_code = p.stock_code
        LEFT JOIN outcomes o ON o.decision_id = p.decision_id
        LEFT JOIN trading_days t ON t.trading_date = p.trading_date
        LEFT JOIN candidate_scores c
          ON c.trading_date = p.trading_date
         AND c.strategy_gene_id = p.strategy_gene_id
         AND c.stock_code = p.stock_code
        LEFT JOIN daily_prices d
          ON d.trading_date = p.trading_date
         AND d.stock_code = p.stock_code
        WHERE p.decision_id = ?
        """,
        (decision_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"Unknown decision_id: {decision_id}")
    return row


def upsert_decision_evidence(conn: sqlite3.Connection, review_id: str, row: sqlite3.Row, packet: dict[str, Any]) -> list[str]:
    evidence = [
        ("outcome", row["decision_id"], "POSTCLOSE_OBSERVED", "EXTRACTED", {
            "return_pct": float(row["return_pct"]),
            "max_drawdown_intraday_pct": float(row["max_drawdown_intraday_pct"]),
            "hit_sell_rule": row["hit_sell_rule"],
        }),
        ("daily_price", f"{row['stock_code']}:{row['trading_date']}", "POSTCLOSE_OBSERVED", "EXTRACTED", {
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
        }),
        ("candidate_score", f"{row['strategy_gene_id']}:{row['stock_code']}:{row['trading_date']}", "PREOPEN_VISIBLE", "EXTRACTED", {
            "technical_score": row["technical_score"],
            "fundamental_score": row["fundamental_score"],
            "event_score": row["event_score"],
            "sector_score": row["sector_score"],
            "risk_penalty": row["risk_penalty"],
            "packet": packet,
        }),
    ]
    for table, source_type in [
        ("earnings_surprises", "earnings_surprise"),
        ("financial_actuals", "financial_actual"),
        ("analyst_expectations", "analyst_expectation"),
        ("order_contract_events", "order_contract"),
        ("business_kpi_actuals", "business_kpi"),
        ("risk_events", "risk_event"),
    ]:
        for extra in domain_evidence(conn, table, row["stock_code"], row["trading_date"]):
            evidence.append((source_type, extra["source_id"], extra["visibility"], extra["confidence"], extra["payload"]))

    evidence_ids: list[str] = []
    for source_type, source_id, visibility, confidence, payload in evidence:
        evidence_id = build_evidence_id(review_id, source_type, source_id)
        conn.execute(
            """
            INSERT INTO review_evidence(
              evidence_id, review_id, source_type, source_id, trading_date,
              stock_code, visibility, confidence, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(evidence_id) DO UPDATE SET
              payload_json = excluded.payload_json,
              visibility = excluded.visibility,
              confidence = excluded.confidence
            """,
            (
                evidence_id,
                review_id,
                source_type,
                source_id,
                row["trading_date"],
                row["stock_code"],
                visibility,
                confidence,
                repository.dumps(payload),
            ),
        )
        evidence_ids.append(evidence_id)
    return evidence_ids


def domain_evidence(conn: sqlite3.Connection, table: str, stock_code: str, trading_date: str) -> list[dict[str, Any]]:
    if table == "earnings_surprises":
        rows = repository.latest_earnings_surprises_before(conn, stock_code, trading_date)[:2]
        return [
            {
                "source_id": row["surprise_id"],
                "visibility": "PREOPEN_VISIBLE",
                "confidence": row["evidence_level"] or "INFERRED",
                "payload": dict(row),
            }
            for row in rows
        ]
    if table == "financial_actuals":
        row = repository.latest_financial_actuals_before(conn, stock_code, trading_date)
        rows = [row] if row is not None else []
        return [{"source_id": row["actual_id"] or f"{row['stock_code']}:{row['report_period']}:{row['source']}", "visibility": "PREOPEN_VISIBLE", "confidence": "EXTRACTED", "payload": dict(row)} for row in rows]
    if table == "analyst_expectations":
        rows = repository.latest_expectations_before(conn, stock_code, trading_date)[:3]
        return [{"source_id": row["expectation_id"], "visibility": "PREOPEN_VISIBLE", "confidence": "EXTRACTED", "payload": dict(row)} for row in rows]
    if table == "order_contract_events":
        rows = repository.recent_order_contract_events_before(conn, stock_code, trading_date, limit=3)
        return [{"source_id": row["event_id"], "visibility": "PREOPEN_VISIBLE", "confidence": "INFERRED", "payload": dict(row)} for row in rows]
    if table == "business_kpi_actuals":
        rows = repository.recent_business_kpis_before(conn, stock_code, trading_date, limit=3)
        return [{"source_id": row["kpi_id"], "visibility": "PREOPEN_VISIBLE", "confidence": "INFERRED", "payload": dict(row)} for row in rows]
    rows = repository.recent_risk_events_before(conn, stock_code, trading_date, limit=3)
    return [{"source_id": row["risk_event_id"], "visibility": "PREOPEN_VISIBLE", "confidence": "INFERRED", "payload": dict(row)} for row in rows]


def build_factor_items(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    packet: dict[str, Any],
    evidence_ids: list[str],
    evidence_by_source: dict[str, list[str]],
) -> list[dict[str, Any]]:
    # Use alpha (stock selection skill) for attribution when available,
    # otherwise fall back to raw return_pct
    return_pct = float(row["return_pct"])
    alpha = float(row["alpha"]) if row["alpha"] is not None else return_pct
    drawdown = float(row["max_drawdown_intraday_pct"])
    stock_code = row["stock_code"]
    trading_date = row["trading_date"]
    surprises = repository.latest_earnings_surprises_before(conn, stock_code, trading_date)
    expectations = repository.latest_expectations_before(conn, stock_code, trading_date)
    orders = repository.recent_order_contract_events_before(conn, stock_code, trading_date)
    kpis = repository.recent_business_kpis_before(conn, stock_code, trading_date)
    risks = repository.recent_risk_events_before(conn, stock_code, trading_date)
    financial_actual = repository.latest_financial_actuals_before(conn, stock_code, trading_date)
    base_evidence = ids_for_sources(evidence_by_source, ["candidate_score", "daily_price", "outcome"], fallback=evidence_ids)
    items = [
        technical_check(row, packet, alpha, base_evidence),
        fundamental_check(row, packet, alpha, drawdown, ids_for_sources(evidence_by_source, ["financial_actual", "candidate_score"], fallback=evidence_ids)),
        event_check(row, packet, alpha, ids_for_sources(evidence_by_source, ["order_contract", "candidate_score"], fallback=evidence_ids)),
        sector_check(row, packet, alpha, base_evidence),
        risk_check(row, packet, alpha, drawdown, ids_for_sources(evidence_by_source, ["risk_event", "candidate_score"], fallback=evidence_ids)),
        execution_check(row, alpha, base_evidence),
        earnings_surprise_check(row, surprises, ids_for_sources(evidence_by_source, ["earnings_surprise", "analyst_expectation", "financial_actual"], fallback=evidence_ids)),
        order_contract_check(row, orders, ids_for_sources(evidence_by_source, ["order_contract"], fallback=evidence_ids)),
        business_kpi_check(row, kpis, ids_for_sources(evidence_by_source, ["business_kpi"], fallback=evidence_ids)),
        risk_event_check(row, risks, ids_for_sources(evidence_by_source, ["risk_event"], fallback=evidence_ids)),
        expectation_check(row, expectations, financial_actual, ids_for_sources(evidence_by_source, ["analyst_expectation", "financial_actual"], fallback=evidence_ids)),
    ]
    return items


def evidence_ids_by_source(conn: sqlite3.Connection, review_id: str) -> dict[str, list[str]]:
    rows = conn.execute(
        "SELECT evidence_id, source_type FROM review_evidence WHERE review_id = ? ORDER BY source_type",
        (review_id,),
    ).fetchall()
    grouped: dict[str, list[str]] = {}
    for row in rows:
        grouped.setdefault(row["source_type"], []).append(row["evidence_id"])
    return grouped


def ids_for_sources(grouped: dict[str, list[str]], source_types: list[str], *, fallback: list[str]) -> list[str]:
    ids: list[str] = []
    for source_type in source_types:
        ids.extend(grouped.get(source_type, []))
    return ids[:5] if ids else fallback[:3]


def technical_check(row: sqlite3.Row, packet: dict[str, Any], return_pct: float, evidence_ids: list[str]) -> dict[str, Any]:
    score = float(row["technical_score"] or packet.get("technical", {}).get("score") or 0)
    verdict = "RIGHT" if score > 0 and return_pct > 0 else "WRONG" if score > 0 and return_pct <= 0 else "NEUTRAL"
    error_type = "overweighted_technical" if verdict == "WRONG" else None
    return factor_item("technical", {"score": score}, {"return_pct": return_pct}, verdict, score * sign(return_pct), error_type, evidence_ids)


def fundamental_check(row: sqlite3.Row, packet: dict[str, Any], return_pct: float, drawdown: float, evidence_ids: list[str]) -> dict[str, Any]:
    score = float(row["fundamental_score"] or packet.get("fundamental", {}).get("score") or 0)
    if score >= 0.5 and drawdown > -0.04:
        verdict, error_type = "RIGHT", None
    elif score < 0.3 and return_pct <= 0:
        verdict, error_type = "WRONG", "underweighted_fundamental"
    else:
        verdict, error_type = "NEUTRAL", None
    return factor_item("fundamental", {"score": score}, {"return_pct": return_pct, "drawdown": drawdown}, verdict, score * sign(return_pct), error_type, evidence_ids)


def event_check(row: sqlite3.Row, packet: dict[str, Any], return_pct: float, evidence_ids: list[str]) -> dict[str, Any]:
    score = float(row["event_score"] or packet.get("event", {}).get("score") or 0)
    if score > 0 and return_pct > 0:
        verdict, error_type = "RIGHT", None
    elif score > 0 and return_pct <= 0:
        verdict, error_type = "WRONG", "false_catalyst"
    elif score <= 0 and return_pct <= 0:
        verdict, error_type = "RIGHT", None
    else:
        verdict, error_type = "NEUTRAL", None
    return factor_item("event", {"score": score}, {"return_pct": return_pct}, verdict, abs(score) * sign(return_pct), error_type, evidence_ids)


def sector_check(row: sqlite3.Row, packet: dict[str, Any], return_pct: float, evidence_ids: list[str]) -> dict[str, Any]:
    score = float(row["sector_score"] or packet.get("sector", {}).get("score") or 0)
    if score > 0.45 and return_pct > 0:
        verdict, error_type = "RIGHT", None
    elif score < 0.2 and return_pct <= 0:
        verdict, error_type = "RIGHT", None
    elif score < 0.2 and return_pct > 0:
        verdict, error_type = "MIXED", "underweighted_sector"
    else:
        verdict, error_type = "NEUTRAL", None
    return factor_item("sector", {"score": score}, {"return_pct": return_pct}, verdict, score * sign(return_pct), error_type, evidence_ids)


def risk_check(row: sqlite3.Row, packet: dict[str, Any], return_pct: float, drawdown: float, evidence_ids: list[str]) -> dict[str, Any]:
    risk = float(row["risk_penalty"] or packet.get("risk", {}).get("score") or 0)
    reasons = packet.get("risk", {}).get("reasons", []) if isinstance(packet, dict) else []
    if risk > 0.35 and (return_pct <= 0 or drawdown <= -0.04):
        verdict, error_type = "RIGHT", "risk_underestimated"
    elif risk < 0.15 and drawdown <= -0.04:
        verdict, error_type = "WRONG", "risk_underestimated"
    elif "low liquidity" in reasons:
        verdict, error_type = "MIXED", "liquidity_ignored"
    else:
        verdict, error_type = "NEUTRAL", None
    return factor_item("risk", {"risk_penalty": risk, "reasons": reasons}, {"return_pct": return_pct, "drawdown": drawdown}, verdict, -risk * abs(sign(return_pct)), error_type, evidence_ids)


def execution_check(row: sqlite3.Row, return_pct: float, evidence_ids: list[str]) -> dict[str, Any]:
    if int(row["is_suspended"] or 0) or int(row["is_limit_up"] or 0):
        verdict, error_type = "WRONG", "entry_unfillable"
    elif row["hit_sell_rule"] == "stop_loss" and return_pct > 0:
        verdict, error_type = "MIXED", "sell_rule_too_tight"
    else:
        verdict, error_type = "RIGHT", None
    return factor_item("execution", {"entry_plan": repository.loads(row["entry_plan_json"], {})}, {"hit_sell_rule": row["hit_sell_rule"]}, verdict, return_pct, error_type, evidence_ids)


def earnings_surprise_check(
    row: sqlite3.Row,
    surprises: list[sqlite3.Row],
    evidence_ids: list[str],
) -> dict[str, Any]:
    latest = surprises[0] if surprises else None
    surprise_pct = float(latest["surprise_pct"] if latest and latest["surprise_pct"] is not None else latest["net_profit_surprise_pct"] if latest and latest["net_profit_surprise_pct"] is not None else 0)
    surprise_type = latest["surprise_type"] if latest and latest["surprise_type"] else "missing"
    score = float(row["fundamental_score"] or 0)
    if surprise_type == "positive_surprise" and score < 0.3:
        verdict, error_type, contribution = "WRONG", "missed_earnings_surprise", max(0.25, min(1.0, abs(surprise_pct)))
    elif surprise_type == "positive_surprise":
        verdict, error_type, contribution = "RIGHT", None, min(1.0, abs(surprise_pct))
    elif surprise_type == "negative_surprise" and float(row["return_pct"]) <= 0:
        verdict, error_type, contribution = "RIGHT", None, -min(1.0, abs(surprise_pct))
    elif surprise_type == "expectation_missing":
        verdict, error_type, contribution = "INCONCLUSIVE", "analyst_expectation_missing", 0.0
    elif not latest:
        verdict, error_type, contribution = "INCONCLUSIVE", "financial_actual_missing", 0.0
    else:
        verdict, error_type, contribution = "NEUTRAL", None, 0.0
    return factor_item(
        "earnings_surprise",
        {"fundamental_score": score, "surprise_type": surprise_type},
        {"surprise_pct": surprise_pct, "available": bool(latest)},
        verdict,
        contribution,
        error_type,
        evidence_ids,
    )


def order_contract_check(
    row: sqlite3.Row,
    orders: list[sqlite3.Row],
    evidence_ids: list[str],
) -> dict[str, Any]:
    positive_orders = [item for item in orders if float(item["impact_score"] or 0) > 0.25]
    max_impact = max([float(item["impact_score"] or 0) for item in positive_orders], default=0.0)
    score = float(row["event_score"] or 0)
    if positive_orders and score < 0.2:
        verdict, error_type = "WRONG", "missed_order_signal"
    elif positive_orders:
        verdict, error_type = "RIGHT", None
    else:
        verdict, error_type = "NEUTRAL", None
    return factor_item(
        "order_contract",
        {"event_score": score},
        {"positive_event_count": len(positive_orders), "max_impact_score": max_impact},
        verdict,
        max_impact if verdict != "WRONG" else -max_impact,
        error_type,
        evidence_ids,
    )


def business_kpi_check(
    row: sqlite3.Row,
    kpis: list[sqlite3.Row],
    evidence_ids: list[str],
) -> dict[str, Any]:
    positive = [item for item in kpis if float(item["kpi_yoy"] if item["kpi_yoy"] is not None else item["yoy_pct"] or 0) > 0.15]
    max_yoy = max([float(item["kpi_yoy"] if item["kpi_yoy"] is not None else item["yoy_pct"] or 0) for item in positive], default=0.0)
    score = float(row["fundamental_score"] or 0)
    if positive and score < 0.3:
        verdict, error_type = "WRONG", "missed_business_kpi_signal"
    elif positive:
        verdict, error_type = "RIGHT", None
    else:
        verdict, error_type = "NEUTRAL", None
    return factor_item(
        "business_kpi",
        {"fundamental_score": score},
        {"positive_kpi_count": len(positive), "max_yoy": max_yoy},
        verdict,
        max_yoy if verdict != "WRONG" else -max_yoy,
        error_type,
        evidence_ids,
    )


def risk_event_check(
    row: sqlite3.Row,
    risks: list[sqlite3.Row],
    evidence_ids: list[str],
) -> dict[str, Any]:
    negative_risks = [item for item in risks if float(item["impact_score"] or 0) < -0.2]
    worst_impact = min([float(item["impact_score"] or 0) for item in negative_risks], default=0.0)
    risk_penalty = float(row["risk_penalty"] or 0)
    if negative_risks and risk_penalty < 0.2:
        verdict, error_type = "WRONG", "missed_risk_event"
    elif negative_risks:
        verdict, error_type = "RIGHT", None
    else:
        verdict, error_type = "NEUTRAL", None
    return factor_item(
        "risk_event",
        {"risk_penalty": risk_penalty},
        {"negative_event_count": len(negative_risks), "worst_impact_score": worst_impact},
        verdict,
        worst_impact,
        error_type,
        evidence_ids,
    )


def expectation_check(
    row: sqlite3.Row,
    expectations: list[sqlite3.Row],
    financial_actual: sqlite3.Row | None,
    evidence_ids: list[str],
) -> dict[str, Any]:
    if not expectations:
        verdict, error_type = "INCONCLUSIVE", "analyst_expectation_missing"
    elif financial_actual is None:
        verdict, error_type = "INCONCLUSIVE", "financial_actual_missing"
    else:
        verdict, error_type = "RIGHT", None
    return factor_item(
        "expectation",
        {"requires_expectation_snapshot": True},
        {"expectation_count": len(expectations), "has_financial_actual": financial_actual is not None},
        verdict,
        0.0,
        error_type,
        evidence_ids,
    )


def factor_item(
    factor_type: str,
    expected: dict[str, Any],
    actual: dict[str, Any],
    verdict: str,
    contribution_score: float,
    error_type: str | None,
    evidence_ids: list[str],
) -> dict[str, Any]:
    return {
        "factor_type": factor_type,
        "expected": expected,
        "actual": actual,
        "verdict": verdict,
        "contribution_score": contribution_score,
        "error_type": error_type,
        "confidence": "EXTRACTED",
        "evidence_ids": evidence_ids[:3],
    }


def upsert_factor_item(conn: sqlite3.Connection, review_id: str, item: dict[str, Any]) -> None:
    item_id = build_item_id(review_id, item["factor_type"])
    conn.execute(
        """
        INSERT INTO factor_review_items(
          item_id, review_id, factor_type, expected_json, actual_json, verdict,
          contribution_score, error_type, confidence, evidence_ids_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(review_id, factor_type) DO UPDATE SET
          expected_json = excluded.expected_json,
          actual_json = excluded.actual_json,
          verdict = excluded.verdict,
          contribution_score = excluded.contribution_score,
          error_type = excluded.error_type,
          confidence = excluded.confidence,
          evidence_ids_json = excluded.evidence_ids_json
        """,
        (
            item_id,
            review_id,
            item["factor_type"],
            repository.dumps(item["expected"]),
            repository.dumps(item["actual"]),
            item["verdict"],
            item["contribution_score"],
            item["error_type"],
            item["confidence"],
            repository.dumps(item["evidence_ids"]),
        ),
    )


def upsert_review_error(
    conn: sqlite3.Connection,
    *,
    review_scope: str,
    review_id: str,
    error_type: str,
    severity: float,
    confidence: float,
    evidence_ids: list[str],
) -> str:
    error_id = "err_" + hashlib.sha1(f"{review_scope}:{review_id}:{error_type}".encode("utf-8")).hexdigest()[:14]
    conn.execute(
        """
        INSERT INTO review_errors(
          error_id, review_scope, review_id, error_type, severity, confidence, evidence_ids_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(review_scope, review_id, error_type) DO UPDATE SET
          severity = excluded.severity,
          confidence = excluded.confidence,
          evidence_ids_json = excluded.evidence_ids_json
        """,
        (error_id, review_scope, review_id, error_type, severity, confidence, repository.dumps(evidence_ids)),
    )
    return error_id


def maybe_signal_from_error(conn: sqlite3.Connection, row: sqlite3.Row, review_id: str, item: dict[str, Any]) -> None:
    mapping = {
        "overweighted_technical": ("decrease_weight", "technical_component_weight", "down"),
        "underweighted_fundamental": ("increase_weight", "fundamental_component_weight", "up"),
        "false_catalyst": ("decrease_weight", "event_component_weight", "down"),
        "underweighted_sector": ("increase_weight", "sector_component_weight", "up"),
        "risk_underestimated": ("increase_weight", "risk_component_weight", "up"),
        "liquidity_ignored": ("increase_weight", "risk_component_weight", "up"),
        "sell_rule_too_tight": ("adjust_sell_rule", "take_profit_pct", "up"),
        "missed_earnings_surprise": ("increase_earnings_surprise_weight", "earnings_surprise_weight", "up"),
        "missed_order_signal": ("increase_order_event_weight", "order_event_weight", "up"),
        "missed_business_kpi_signal": ("increase_kpi_momentum_weight", "kpi_momentum_weight", "up"),
        "missed_risk_event": ("increase_risk_penalty", "risk_component_weight", "up"),
        "analyst_expectation_missing": ("add_data_source", "analyst_expectations", "add"),
        "financial_actual_missing": ("add_data_source", "financial_actuals", "add"),
    }
    error_type = item.get("error_type")
    if error_type not in mapping:
        return
    signal_type, param_name, direction = mapping[error_type]
    upsert_optimization_signal(
        conn,
        source_type="decision_review",
        source_id=review_id,
        target_gene_id=row["strategy_gene_id"],
        scope="gene",
        scope_key=row["strategy_gene_id"],
        signal_type=signal_type,
        param_name=param_name,
        direction=direction,
        strength=min(1.0, abs(float(item.get("contribution_score", 0))) + 0.1),
        confidence=0.7,
        reason=f"{error_type} detected in {row['stock_code']} review",
        evidence_ids=item["evidence_ids"],
    )


def overall_verdict(return_pct: float, items: list[dict[str, Any]]) -> str:
    wrong = sum(1 for item in items if item["verdict"] == "WRONG")
    if return_pct > 0 and wrong == 0:
        return "RIGHT"
    if return_pct <= 0 and wrong >= 1:
        return "WRONG"
    if wrong:
        return "MIXED"
    return "NEUTRAL"


def choose_primary_driver(items: list[dict[str, Any]], packet: dict[str, Any]) -> str:
    ranked = sorted(
        [item for item in items if item["factor_type"] != "execution"],
        key=lambda item: abs(float(item["contribution_score"])),
        reverse=True,
    )
    return ranked[0]["factor_type"] if ranked else "unknown"


def thesis_quality_score(row: sqlite3.Row) -> float:
    thesis = repository.loads(row["thesis_json"], {})
    populated = sum(1 for value in thesis.values() if value)
    return min(1.0, populated / 4)


def evidence_quality_score(evidence_ids: list[str]) -> float:
    return min(1.0, len(evidence_ids) / 6)


def sign(value: float) -> float:
    if value > 0:
        return 1.0
    if value < 0:
        return -1.0
    return 0.0


def build_review_id(decision_id: str) -> str:
    return "review_" + hashlib.sha1(decision_id.encode("utf-8")).hexdigest()[:12]


def build_item_id(review_id: str, factor_type: str) -> str:
    return "fri_" + hashlib.sha1(f"{review_id}:{factor_type}".encode("utf-8")).hexdigest()[:14]


def build_evidence_id(review_id: str, source_type: str, source_id: str) -> str:
    return "ev_" + hashlib.sha1(f"{review_id}:{source_type}:{source_id}".encode("utf-8")).hexdigest()[:14]


def _record_rejected_review(
    conn: sqlite3.Connection,
    review_id: str,
    row: sqlite3.Row,
) -> None:
    """Create a review entry for rejected (non-executed) decisions."""
    summary = (
        f"{row['trading_date']} {row['strategy_gene_id']} {row['stock_code']} "
        f"rejected; order not executed."
    )
    conn.execute(
        """
        INSERT INTO decision_reviews(
          review_id, decision_id, trading_date, strategy_gene_id, stock_code,
          verdict, primary_driver, return_pct, relative_return_pct,
          max_drawdown_intraday_pct, thesis_quality_score, evidence_quality_score,
          deterministic_json, llm_json, summary
        )
        VALUES (?, ?, ?, ?, ?, 'rejected', 'order_rejected', 0, 0, 0, 0, 0, ?, NULL, ?)
        ON CONFLICT(decision_id) DO UPDATE SET
          verdict = excluded.verdict,
          primary_driver = excluded.primary_driver,
          return_pct = excluded.return_pct,
          summary = excluded.summary,
          updated_at = CURRENT_TIMESTAMP
        """,
        (
            review_id,
            row["decision_id"],
            row["trading_date"],
            row["strategy_gene_id"],
            row["stock_code"],
            json.dumps({"rejected": True, "decision_id": row["decision_id"]}),
            summary,
        ),
    )
