"""LLM review module: calls LLM to produce enriched decision reviews."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
from typing import Any

from . import repository
from .deterministic_review import review_decision
from .llm_contracts import LLMContractError, LLMReviewContract
from .llm_prompt import build_decision_review_packet, build_system_prompt, build_user_prompt
from .optimization_signals import upsert_optimization_signal

logger = logging.getLogger(__name__)


def run_llm_review(conn: sqlite3.Connection, trading_date: str) -> dict[str, Any]:
    """Run LLM review for all pick decisions on the given date."""
    rows = conn.execute(
        "SELECT decision_id FROM pick_decisions WHERE trading_date = ? ORDER BY strategy_gene_id, score DESC",
        (trading_date,),
    ).fetchall()

    reviewed = 0
    skipped = 0
    for row in rows:
        try:
            review_id = review_decision(conn, row["decision_id"])
            result = llm_review_for_decision(conn, review_id)
            if result:
                reviewed += 1
            else:
                skipped += 1
        except Exception as exc:
            logger.error("LLM review failed for %s: %s", row["decision_id"], exc)
            skipped += 1

    conn.commit()
    return {"reviewed": reviewed, "skipped": skipped, "total": len(rows)}


def llm_review_for_decision(conn: sqlite3.Connection, review_id: str) -> dict[str, Any] | None:
    """Run LLM review for a single decision review."""
    review = conn.execute("SELECT * FROM decision_reviews WHERE review_id = ?", (review_id,)).fetchone()
    if review is None:
        return None

    deterministic = json.loads(review["deterministic_json"] or "{}")
    factor_items = deterministic.get("factor_checks", [])
    evidence_list = conn.execute(
        "SELECT * FROM review_evidence WHERE review_id = ?", (review_id,)
    ).fetchall()

    evidence_dicts = [dict(e) for e in evidence_list]
    factor_dicts = [dict(f) if hasattr(f, "keys") else f for f in factor_items]

    packet = build_decision_review_packet(
        decision_row=dict(review),
        outcome_row={
            "entry_price": deterministic.get("outcome", {}).get("entry_price", 0),
            "close_price": deterministic.get("outcome", {}).get("close_price", 0),
            "return_pct": deterministic.get("outcome", {}).get("return_pct", 0),
            "max_drawdown_intraday_pct": deterministic.get("outcome", {}).get("max_drawdown_intraday_pct", 0),
            "index_return_pct": deterministic.get("outcome", {}).get("relative_return_pct", 0),
        },
        factor_checks=factor_dicts,
        evidence=evidence_dicts,
    )

    llm_result = _call_llm(packet)
    if llm_result is None:
        return None

    try:
        contract = LLMReviewContract.validate(llm_result)
    except LLMContractError as exc:
        logger.error("LLM output failed contract validation: %s", exc)
        return None

    _persist_llm_review(conn, review_id, review["strategy_gene_id"], contract)
    return {"review_id": review_id, "summary": contract.summary}


def _call_llm(packet: dict[str, Any]) -> dict[str, Any] | None:
    """Call the LLM to produce a review. Returns None if API is not configured."""
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
    if not api_key:
        logger.info("LLM review skipped: no API key configured")
        return None

    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic package not installed, skipping LLM review")
        return None

    client = anthropic.Anthropic(api_key=api_key)
    system = build_system_prompt()
    user = build_user_prompt(packet)

    response = client.messages.create(
        model="claude-sonnet-4-6-20250514",
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user}],
    )

    text = response.content[0].text if response.content else ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.error("LLM output was not valid JSON")
        return None


def _persist_llm_review(
    conn: sqlite3.Connection,
    review_id: str,
    gene_id: str,
    contract: LLMReviewContract,
) -> None:
    """Persist LLM review results to the database."""
    llm_review_id = "llm_" + hashlib.sha1(
        f"{review_id}:llm_review".encode()
    ).hexdigest()[:12]

    conn.execute(
        """
        INSERT INTO llm_reviews(
          llm_review_id, decision_review_id, trading_date, strategy_gene_id,
          attribution_json, reason_check_json, suggested_errors_json,
          suggested_signals_json, summary, status
        )
        VALUES (?, ?, (SELECT trading_date FROM decision_reviews WHERE review_id = ?), ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(decision_review_id) DO UPDATE SET
          attribution_json = excluded.attribution_json,
          reason_check_json = excluded.reason_check_json,
          summary = excluded.summary,
          status = excluded.status
        """,
        (
            llm_review_id,
            review_id,
            review_id,
            gene_id,
            json.dumps([
                {"claim": a.claim, "confidence": a.confidence, "evidence_ids": a.evidence_ids}
                for a in contract.attribution
            ]),
            json.dumps(contract.reason_check),
            json.dumps(contract.suggested_errors),
            json.dumps(contract.suggested_optimization_signals),
            contract.summary,
            "accepted",
        ),
    )

    for error in contract.suggested_errors:
        error_type = error.get("error_type", "llm_flagged")
        severity = float(error.get("severity", 0.3))
        conn.execute(
            """
            INSERT INTO review_errors(error_id, review_scope, review_id, error_type, severity, confidence, evidence_ids_json)
            VALUES (?, 'llm', ?, ?, ?, 0.6, ?)
            ON CONFLICT(review_scope, review_id, error_type) DO UPDATE SET severity = excluded.severity
            """,
            (
                f"llmerr_{hashlib.sha1(f'{review_id}:{error_type}'.encode()).hexdigest()[:10]}",
                review_id,
                error_type,
                severity,
                json.dumps(error.get("evidence_ids", [])),
            ),
        )

    for signal in contract.suggested_optimization_signals:
        upsert_optimization_signal(
            conn,
            source_type="llm_review",
            source_id=llm_review_id,
            target_gene_id=gene_id,
            scope="gene",
            scope_key=gene_id,
            signal_type=signal.get("signal_type", "adjust_weight"),
            param_name=signal.get("param_name", ""),
            direction=signal.get("direction", "neutral"),
            strength=float(signal.get("strength", 0.3)),
            confidence=0.65,
            reason=signal.get("reason", ""),
            evidence_ids=signal.get("evidence_ids", []),
        )
