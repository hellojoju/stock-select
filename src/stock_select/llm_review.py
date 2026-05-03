"""LLM review module: calls LLM to produce enriched decision reviews."""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from typing import Any

from . import repository
from .deterministic_review import review_decision
from .llm_config import (
    BudgetExceeded,
    LLMConfig,
    LLMNotConfigured,
    build_allowlist,
    estimate_cost,
    get_budget,
    resolve_llm_config,
)
from .llm_contracts import LLMContractError, LLMReviewContract
from .llm_prompt import (
    build_blindspot_review_packet,
    build_decision_review_packet,
    build_stock_review_packet,
    build_system_prompt,
    build_user_prompt,
)
from .optimization_signals import upsert_optimization_signal

logger = logging.getLogger(__name__)


def run_llm_review(conn: sqlite3.Connection, trading_date: str) -> dict[str, Any]:
    """Run LLM review for all pick decisions on the given date."""
    config = resolve_llm_config()

    # Count total decisions so callers know scope even when config is missing
    total = conn.execute(
        "SELECT COUNT(*) FROM pick_decisions WHERE trading_date = ?",
        (trading_date,),
    ).fetchone()[0]

    if config is None:
        return {"status": "skipped", "reason": "LLM not configured", "reviewed": 0, "skipped": total, "total": total}

    # Build allowlist from decisions
    decisions = conn.execute(
        "SELECT decision_id, stock_code FROM pick_decisions WHERE trading_date = ? ORDER BY strategy_gene_id, score DESC",
        (trading_date,),
    ).fetchall()
    blindspots = conn.execute(
        "SELECT DISTINCT stock_code FROM blindspot_reviews WHERE trading_date = ?",
        (trading_date,),
    ).fetchall()

    allowlist = build_allowlist(
        decisions=[dict(d) for d in decisions],
        blindspots=[dict(b) for b in blindspots],
        max_stocks=config.max_stocks_per_day,
    )

    # Filter decisions to allowlist only
    filtered = [d for d in decisions if d["stock_code"] in allowlist]

    reviewed = 0
    skipped = 0
    budget = get_budget()

    for row in filtered:
        try:
            budget.check(config)
            review_id = review_decision(conn, row["decision_id"])
            result = llm_review_for_decision(conn, review_id, config=config)
            if result:
                reviewed += 1
            else:
                skipped += 1
        except BudgetExceeded:
            logger.warning("LLM budget exceeded, stopping review")
            skipped += len(filtered) - reviewed - skipped
            break
        except Exception as exc:
            logger.error("LLM review failed for %s: %s", row["decision_id"], exc)
            skipped += 1

    conn.commit()
    return {"reviewed": reviewed, "skipped": skipped, "total": len(filtered)}


def llm_review_for_decision(
    conn: sqlite3.Connection,
    review_id: str,
    config: LLMConfig | None = None,
) -> dict[str, Any] | None:
    """Run LLM review for a single decision review."""
    if config is None:
        config = resolve_llm_config()
    if config is None:
        return None

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

    system = build_system_prompt()
    user = build_user_prompt(packet)

    # Compute llm_review_id early for scratchpad logging
    llm_review_id = "llm_" + hashlib.sha1(
        f"{review_id}:llm_review".encode()
    ).hexdigest()[:12]

    llm_result = _call_llm_with_config(
        conn, system, user, config,
        llm_review_id=llm_review_id,
        decision_review_id=review_id,
        packet=packet,
    )
    if llm_result is None:
        return None

    try:
        contract = LLMReviewContract.validate(llm_result)
    except LLMContractError as exc:
        logger.error("LLM output failed contract validation: %s", exc)
        return None

    _persist_llm_review(conn, review_id, review["strategy_gene_id"], contract)
    return {"review_id": review_id, "summary": contract.summary}


def llm_review_for_stock(
    conn: sqlite3.Connection,
    stock_code: str,
    trading_date: str,
    config: LLMConfig | None = None,
) -> dict[str, Any] | None:
    """Run LLM review for a single stock across all decisions."""
    if config is None:
        config = resolve_llm_config()
    if config is None:
        return None

    decisions = conn.execute(
        "SELECT decision_id, action, score FROM pick_decisions WHERE trading_date = ? AND stock_code = ?",
        (trading_date, stock_code),
    ).fetchall()
    evidence = conn.execute(
        "SELECT * FROM review_evidence WHERE trading_date = ? AND stock_code = ?",
        (trading_date, stock_code),
    ).fetchall()
    blindspots = conn.execute(
        "SELECT * FROM blindspot_reviews WHERE trading_date = ? AND stock_code = ?",
        (trading_date, stock_code),
    ).fetchall()

    packet = build_stock_review_packet(
        stock_code=stock_code,
        trading_date=trading_date,
        decisions=[dict(d) for d in decisions],
        evidence=[dict(e) for e in evidence],
        blindspots=[dict(b) for b in blindspots],
    )

    system = build_system_prompt()
    user = build_user_prompt(packet)
    llm_result = _call_llm_with_config(conn, system, user, config)
    if llm_result is None:
        return None

    try:
        contract = LLMReviewContract.validate(llm_result)
    except LLMContractError as exc:
        logger.error("Stock LLM output failed contract validation: %s", exc)
        return None

    # Persist as llm_review with a synthetic review_id
    synthetic_review_id = f"stock_{stock_code}_{trading_date}"
    _persist_llm_review(conn, synthetic_review_id, "", contract)
    return {"review_id": synthetic_review_id, "summary": contract.summary}


def run_llm_stock_reviews(
    conn: sqlite3.Connection,
    trading_date: str,
    stock_codes: list[str] | None = None,
) -> dict[str, Any]:
    """Run LLM review for all (or specified) stocks with decisions on the given date."""
    config = resolve_llm_config()
    if config is None:
        return {"status": "skipped", "reason": "LLM not configured", "reviewed": 0, "skipped": 0}

    if stock_codes is None:
        rows = conn.execute(
            "SELECT DISTINCT stock_code FROM pick_decisions WHERE trading_date = ?",
            (trading_date,),
        ).fetchall()
        stock_codes = [r["stock_code"] for r in rows]

    reviewed = 0
    skipped = 0
    budget = get_budget()

    for code in stock_codes:
        try:
            budget.check(config)
            result = llm_review_for_stock(conn, code, trading_date, config)
            if result:
                reviewed += 1
            else:
                skipped += 1
        except BudgetExceeded:
            logger.warning("LLM budget exceeded, stopping stock reviews")
            skipped += len(stock_codes) - reviewed - skipped
            break
        except Exception as exc:
            logger.error("Stock LLM review failed for %s: %s", code, exc)
            skipped += 1

    conn.commit()
    return {"reviewed": reviewed, "skipped": skipped, "total": len(stock_codes)}


def _call_llm_with_config(
    conn: sqlite3.Connection,
    system: str,
    prompt: str,
    config: LLMConfig,
    llm_review_id: str | None = None,
    decision_review_id: str | None = None,
    packet: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Call the LLM using provider-abstracted client, record timing, write scratchpad.

    S6.4: LLM failure degrades gracefully — returns None without affecting
    deterministic review. Retries once on transient errors.
    """
    client_fn = get_llm_client(config)
    if client_fn is None:
        return None

    # S6.4: Retry on transient failure
    last_error = None
    for attempt in range(2):
        budget_before = (get_budget().tokens_prompt, get_budget().tokens_completion, get_budget().total_cost)
        start = time.monotonic()
        try:
            result = client_fn(prompt, system)
            latency_ms = int((time.monotonic() - start) * 1000)
            budget_after = (get_budget().tokens_prompt, get_budget().tokens_completion, get_budget().total_cost)
            prompt_tokens = budget_after[0] - budget_before[0]
            completion_tokens = budget_after[1] - budget_before[1]
            cost = budget_after[2] - budget_before[2]

            if result is None:
                _write_scratchpad(conn, llm_review_id, decision_review_id, packet, config, prompt_tokens, completion_tokens, cost, latency_ms, "error", "LLM returned None or invalid JSON")
                return None

            _write_scratchpad(conn, llm_review_id, decision_review_id, packet, config, prompt_tokens, completion_tokens, cost, latency_ms, "ok")
            return result
        except Exception as exc:
            last_error = exc
            latency_ms = int((time.monotonic() - start) * 1000)
            logger.warning("LLM call failed (attempt %d): %s", attempt + 1, exc)
            if attempt == 0:
                time.sleep(1)  # Brief pause before retry
            continue

    # S6.4: All retries exhausted — degrade gracefully
    logger.error("LLM call failed after retries: %s", last_error)
    _write_scratchpad(
        conn, llm_review_id, decision_review_id, packet, config,
        0, 0, 0.0, latency_ms, "error", f"Retry failed: {last_error}",
    )
    return None


def get_llm_client(config: LLMConfig):
    """Return a provider-specific callable ``(prompt, system) -> dict | None``.

    The callable records token usage and cost into the module-level budget.
    Returns ``None`` if the SDK package is not installed.
    """
    if config.provider == "anthropic":
        try:
            import anthropic
        except ImportError:
            logger.warning("anthropic package not installed, skipping LLM review")
            return None

        client = anthropic.Anthropic(api_key=config.api_key, base_url=config.base_url)

        def _call(prompt: str, system: str) -> dict | None:
            resp = client.messages.create(
                model=config.model,
                max_tokens=config.max_tokens_per_call,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text if resp.content else ""
            budget = get_budget()
            cost = estimate_cost(config.model, resp.usage.input_tokens, resp.usage.output_tokens)
            budget.record(resp.usage.input_tokens, resp.usage.output_tokens, cost)
            try:
                return json.loads(text) if text else None
            except json.JSONDecodeError:
                return None

        return _call

    elif config.provider == "openai":
        try:
            from openai import OpenAI
        except ImportError:
            logger.warning("openai package not installed, skipping LLM review")
            return None

        client = OpenAI(api_key=config.api_key)

        def _call(prompt: str, system: str) -> dict | None:
            resp = client.chat.completions.create(
                model=config.model,
                max_tokens=config.max_tokens_per_call,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            )
            text = resp.choices[0].message.content or ""
            budget = get_budget()
            usage = resp.usage
            if usage:
                cost = estimate_cost(config.model, usage.prompt_tokens, usage.completion_tokens)
                budget.record(usage.prompt_tokens, usage.completion_tokens, cost)
            try:
                return json.loads(text) if text else None
            except json.JSONDecodeError:
                return None

        return _call

    elif config.provider == "deepseek":
        try:
            from openai import OpenAI
        except ImportError:
            logger.warning("openai package not installed, skipping LLM review")
            return None

        client = OpenAI(api_key=config.api_key, base_url="https://api.deepseek.com")

        def _call(prompt: str, system: str) -> dict | None:
            resp = client.chat.completions.create(
                model=config.model,
                max_tokens=config.max_tokens_per_call,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            )
            text = resp.choices[0].message.content or ""
            budget = get_budget()
            usage = resp.usage
            if usage:
                cost = estimate_cost(config.model, usage.prompt_tokens, usage.completion_tokens)
                budget.record(usage.prompt_tokens, usage.completion_tokens, cost)
            try:
                return json.loads(text) if text else None
            except json.JSONDecodeError:
                return None

        return _call

    else:
        raise LLMNotConfigured(f"Unsupported provider: {config.provider}")


def _write_scratchpad(
    conn: sqlite3.Connection,
    llm_review_id: str | None,
    decision_review_id: str | None,
    packet: dict[str, Any] | None,
    config: LLMConfig,
    prompt_tokens: int,
    completion_tokens: int,
    cost: float,
    latency_ms: int,
    status: str = "ok",
    error_message: str = "",
) -> None:
    """Insert scratchpad record. Tolerant of missing table (Task 3 creates it)."""
    if decision_review_id is None:
        return
    try:
        packet_hash = ""
        if packet:
            packet_hash = hashlib.sha256(json.dumps(packet, sort_keys=True).encode()).hexdigest()[:16]
        scratchpad_id = "sp_" + hashlib.sha1(
            f"{decision_review_id}:scratchpad".encode()
        ).hexdigest()[:12]
        conn.execute(
            """
            INSERT INTO llm_scratchpad(
              scratchpad_id, llm_review_id, decision_review_id, packet_hash,
              model, provider, prompt_tokens, completion_tokens,
              estimated_cost, latency_ms, status, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scratchpad_id,
                llm_review_id,
                decision_review_id,
                packet_hash,
                config.model,
                config.provider,
                prompt_tokens,
                completion_tokens,
                cost,
                latency_ms,
                status,
                error_message,
            ),
        )
    except Exception:
        logger.debug("Failed to write scratchpad (table may not exist yet)", exc_info=True)


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
          suggested_errors_json = excluded.suggested_errors_json,
          suggested_signals_json = excluded.suggested_signals_json,
          summary = excluded.summary,
          status = excluded.status,
          created_at = CURRENT_TIMESTAMP
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
            "candidate",
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
            status="candidate",
        )
