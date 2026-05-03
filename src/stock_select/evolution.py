from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date
from typing import Any

from . import repository
from .optimization_signals import aggregate_optimization_signals, consume_signals


MIN_TRADES_TO_EVOLVE = 20
COMPONENT_PARAM_KEYS = {
    "technical": "technical_component_weight",
    "fundamental": "fundamental_component_weight",
    "event": "event_component_weight",
    "sector": "sector_component_weight",
}
COMPONENT_SCORE_KEYS = {
    "technical": "technical_score",
    "fundamental": "fundamental_score",
    "event": "event_score",
    "sector": "sector_score",
}


def score_genes(
    conn: sqlite3.Connection,
    *,
    period_start: str,
    period_end: str,
    market_environment: str = "all",
) -> list[dict[str, Any]]:
    # Check if alpha column exists (may not exist in older DBs)
    has_alpha = _column_exists(conn, "outcomes", "alpha")
    alpha_expr = "AVG(o.alpha)" if has_alpha else "AVG(o.return_pct)"

    rows = conn.execute(
        f"""
        SELECT
          p.strategy_gene_id AS gene_id,
          COUNT(o.outcome_id) AS trades,
          AVG(o.return_pct) AS avg_return_pct,
          {alpha_expr} AS avg_alpha,
          SUM(CASE WHEN o.return_pct > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(o.outcome_id) AS win_rate,
          MIN(o.max_drawdown_intraday_pct) AS worst_drawdown_pct,
          AVG(CASE WHEN o.return_pct > 0 THEN o.return_pct ELSE NULL END) AS avg_win,
          ABS(AVG(CASE WHEN o.return_pct <= 0 THEN o.return_pct ELSE NULL END)) AS avg_loss
        FROM outcomes o
        JOIN pick_decisions p ON p.decision_id = o.decision_id
        WHERE p.trading_date BETWEEN ? AND ?
        GROUP BY p.strategy_gene_id
        """,
        (period_start, period_end),
    ).fetchall()
    scored: list[dict[str, Any]] = []
    for row in rows:
        blindspot_penalty = blindspot_penalty_for_gene(conn, row["gene_id"], period_start, period_end)
        avg_loss = float(row["avg_loss"] or 0)
        profit_loss_ratio = float(row["avg_win"] or 0) / avg_loss if avg_loss else float(row["avg_win"] or 0)
        avg_alpha = float(row["avg_alpha"] or 0) if has_alpha else float(row["avg_return_pct"] or 0)
        score = (
            avg_alpha
            + float(row["win_rate"] or 0) * 0.02
            + float(row["worst_drawdown_pct"] or 0) * 0.5
            + min(profit_loss_ratio, 5.0) * 0.005
            - blindspot_penalty
        )
        item = {
            "gene_id": row["gene_id"],
            "trades": int(row["trades"]),
            "avg_return_pct": float(row["avg_return_pct"] or 0),
            "avg_alpha": avg_alpha,
            "win_rate": float(row["win_rate"] or 0),
            "worst_drawdown_pct": float(row["worst_drawdown_pct"] or 0),
            "profit_loss_ratio": profit_loss_ratio,
            "blindspot_penalty": blindspot_penalty,
            "score": score,
        }
        persist_gene_score(conn, item, period_start, period_end, market_environment)
        scored.append(item)
    conn.commit()
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(r["name"] == column for r in rows)
    except Exception:
        return False


def evolve_weekly(
    conn: sqlite3.Connection,
    *,
    period_start: str,
    period_end: str,
    market_environment: str = "all",
    min_trades: int = MIN_TRADES_TO_EVOLVE,
) -> dict[str, Any]:
    scored = score_genes(
        conn,
        period_start=period_start,
        period_end=period_end,
        market_environment=market_environment,
    )
    proposal_result = propose_strategy_evolution(
        conn,
        period_start=period_start,
        period_end=period_end,
        market_environment=market_environment,
        min_trades=min_trades,
    )
    proposal_result["scores"] = scored
    return proposal_result


def propose_strategy_evolution(
    conn: sqlite3.Connection,
    *,
    period_start: str,
    period_end: str,
    market_environment: str = "all",
    min_trades: int = MIN_TRADES_TO_EVOLVE,
    min_signal_samples: int = 5,
    min_signal_confidence: float = 0.65,
    min_signal_dates: int = 3,
    gene_id: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    proposals: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    champions = repository.get_champion_genes(conn)
    if gene_id:
        champions = [row for row in champions if row["gene_id"] == gene_id]

    for parent in champions:
        parent_gene_id = parent["gene_id"]
        signal = build_review_signal(
            conn,
            parent_gene_id,
            period_start=period_start,
            period_end=period_end,
        )
        if signal["trades"] < min_trades:
            skipped.append(
                {
                    "gene_id": parent_gene_id,
                    "reason": "insufficient samples",
                    "trades": signal["trades"],
                    "min_trades": min_trades,
                }
            )
            continue

        before_params = json.loads(parent["params_json"])
        aggregated_signals = aggregate_optimization_signals(
            conn,
            gene_id=parent_gene_id,
            period_start=period_start,
            period_end=period_end,
            min_signal_samples=min_signal_samples,
            min_confidence=min_signal_confidence,
            min_distinct_dates=min_signal_dates,
        )
        if not aggregated_signals:
            skipped.append(
                {
                    "gene_id": parent_gene_id,
                    "reason": "insufficient optimization signals",
                    "trades": signal["trades"],
                }
            )
            continue

        after_params, rationale = propose_params_from_optimization_signals(before_params, aggregated_signals)
        if not params_changed(before_params, after_params):
            skipped.append({"gene_id": parent_gene_id, "reason": "no material review signal"})
            continue

        child_gene_id = proposed_child_gene_id(parent, period_start=period_start, period_end=period_end, params=after_params)
        consumed_signal_ids = sorted({signal_id for item in aggregated_signals for signal_id in item["signal_ids"]})
        event_id = build_evolution_event_id(
            parent_gene_id=parent_gene_id,
            child_gene_id=child_gene_id,
            event_type="proposal",
            period_start=period_start,
            period_end=period_end,
        )
        child_status = "dry_run"
        if not dry_run:
            child_gene_id = create_observing_child_gene(
                conn,
                parent,
                period_start=period_start,
                period_end=period_end,
                params=after_params,
            )
            event_id = persist_evolution_event(
                conn,
                parent_gene_id=parent_gene_id,
                child_gene_id=child_gene_id,
                event_type="proposal",
                period_start=period_start,
                period_end=period_end,
                market_environment=market_environment,
                status="applied",
                rationale=rationale,
                before_params=before_params,
                after_params=after_params,
                review_signal={"review_signal": signal, "aggregated_signals": aggregated_signals},
            )
            consume_signals(conn, consumed_signal_ids)
            child = repository.get_gene(conn, child_gene_id)
            child_status = child["status"]
        proposals.append(
            {
                "event_id": event_id,
                "parent_gene_id": parent_gene_id,
                "child_gene_id": child_gene_id,
                "child_status": child_status,
                "dry_run": dry_run,
                "rationale": rationale,
                "before_params": before_params,
                "after_params": after_params,
                "review_signal": signal,
                "aggregated_signals": aggregated_signals,
                "consumed_signal_ids": consumed_signal_ids,
                "evidence_ids": sorted({evidence_id for item in aggregated_signals for evidence_id in item.get("evidence_ids", [])}),
            }
        )
    if not dry_run:
        conn.commit()
    if not proposals:
        reason = "insufficient samples" if skipped else "no active champions"
        return {"status": "skipped", "reason": reason, "dry_run": dry_run, "proposals": [], "skipped": skipped}
    return {
        "status": "dry_run" if dry_run else "proposed",
        "dry_run": dry_run,
        "proposals": proposals,
        "skipped": skipped,
    }


def propose_params_from_optimization_signals(
    before_params: dict[str, Any],
    aggregated_signals: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    after = dict(before_params)
    adjustments: list[dict[str, Any]] = []
    for signal in aggregated_signals:
        param_name = resolve_signal_param(signal, after)
        if not param_name or param_name not in after or not isinstance(after[param_name], (int, float)):
            continue
        direction = signal["direction"]
        signal_type = signal["signal_type"]
        strength = float(signal["weighted_strength"])
        factor = 1.0
        if signal_type in {
            "increase_weight",
            "increase_earnings_surprise_weight",
            "increase_order_event_weight",
            "increase_kpi_momentum_weight",
            "increase_risk_penalty",
            "lower_threshold",
            "adjust_position",
            "adjust_sell_rule",
        } and direction in {"up", "down"}:
            factor = 1.0 + min(0.05, strength * 0.05) if direction == "up" else 1.0 - min(0.05, strength * 0.05)
        elif signal_type in {"decrease_weight", "decrease_earnings_surprise_weight", "raise_threshold"} and direction in {"up", "down"}:
            factor = 1.0 - min(0.05, strength * 0.05) if direction == "down" else 1.0 + min(0.05, strength * 0.05)
        elif signal_type == "tighten_evidence_coverage_filter":
            factor = 1.0 + min(0.05, strength * 0.05)
        before = float(after[param_name])
        after[param_name] = round(before * factor, 6)
        adjustments.append(
            {
                "param": param_name,
                "before": before,
                "after": after[param_name],
                "factor": round(factor, 6),
                "source": signal,
            }
        )
    normalize_component_budget(after, before_params)
    round_tunable_params(after)
    return after, {
        "method": "optimization_signal_parameter_adjustment",
        "guardrails": [
            "parent remains active",
            "child starts in observing status",
            "signals are marked consumed after proposal",
            "single parameter movement is capped at 5%",
        ],
        "adjustments": adjustments,
    }


def resolve_signal_param(signal: dict[str, Any], params: dict[str, Any]) -> str | None:
    param_name = signal.get("param_name")
    if param_name in params:
        return str(param_name)
    signal_type = signal.get("signal_type")
    aliases = {
        "increase_earnings_surprise_weight": "fundamental_component_weight",
        "decrease_earnings_surprise_weight": "fundamental_component_weight",
        "increase_order_event_weight": "event_component_weight",
        "increase_kpi_momentum_weight": "fundamental_component_weight",
        "increase_risk_penalty": "risk_component_weight",
        "tighten_evidence_coverage_filter": "min_score",
    }
    return aliases.get(str(signal_type))


def create_observing_child_gene(
    conn: sqlite3.Connection,
    parent: sqlite3.Row,
    *,
    period_start: str,
    period_end: str,
    params: dict[str, Any],
) -> str:
    new_gene_id = proposed_child_gene_id(parent, period_start=period_start, period_end=period_end, params=params)
    version = next_gene_version(conn, parent["gene_id"])
    conn.execute(
        """
        INSERT OR IGNORE INTO strategy_genes(
          gene_id, name, version, horizon, risk_profile, status,
          parent_gene_id, params_json
        )
        VALUES (?, ?, ?, ?, ?, 'observing', ?, ?)
        """,
        (
            new_gene_id,
            f"{parent['name']} challenger {period_end}",
            version,
            parent["horizon"],
            parent["risk_profile"],
            parent["gene_id"],
            repository.dumps(params),
        ),
    )
    return new_gene_id


def proposed_child_gene_id(
    parent: sqlite3.Row,
    *,
    period_start: str,
    period_end: str,
    params: dict[str, Any],
) -> str:
    suffix = hashlib.sha1(
        repository.dumps(
            {
                "parent": parent["gene_id"],
                "period_start": period_start,
                "period_end": period_end,
                "params": params,
            }
        ).encode("utf-8")
    ).hexdigest()[:8]
    return f"{parent['gene_id']}_challenger_{suffix}"


def build_review_signal(
    conn: sqlite3.Connection,
    gene_id: str,
    *,
    period_start: str,
    period_end: str,
) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT
          p.trading_date,
          p.stock_code,
          o.return_pct,
          o.max_drawdown_intraday_pct,
          c.technical_score,
          c.fundamental_score,
          c.event_score,
          c.sector_score,
          c.risk_penalty
        FROM pick_decisions p
        JOIN outcomes o ON o.decision_id = p.decision_id
        LEFT JOIN candidate_scores c
          ON c.trading_date = p.trading_date
         AND c.strategy_gene_id = p.strategy_gene_id
         AND c.stock_code = p.stock_code
        WHERE p.strategy_gene_id = ?
          AND p.trading_date BETWEEN ? AND ?
        ORDER BY p.trading_date, p.stock_code
        """,
        (gene_id, period_start, period_end),
    ).fetchall()
    trades = len(rows)
    returns = [float(row["return_pct"]) for row in rows]
    winners = [row for row in rows if float(row["return_pct"]) > 0]
    losers = [row for row in rows if float(row["return_pct"]) <= 0]
    component_edges: dict[str, float] = {}
    component_averages: dict[str, float] = {}
    for component, score_key in COMPONENT_SCORE_KEYS.items():
        all_avg = avg([row[score_key] for row in rows])
        winner_avg = avg([row[score_key] for row in winners])
        loser_avg = avg([row[score_key] for row in losers])
        component_averages[component] = all_avg
        component_edges[component] = winner_avg - loser_avg if losers else all_avg

    blindspots = blindspots_for_gene(conn, gene_id, period_start, period_end)
    missing_signals = missing_signals_for_gene(conn, gene_id, period_start, period_end)
    worst_drawdown = min([float(row["max_drawdown_intraday_pct"]) for row in rows], default=0.0)
    return {
        "gene_id": gene_id,
        "period_start": period_start,
        "period_end": period_end,
        "trades": trades,
        "avg_return_pct": avg(returns),
        "win_rate": len(winners) / trades if trades else 0.0,
        "loss_rate": len(losers) / trades if trades else 0.0,
        "worst_drawdown_pct": worst_drawdown,
        "component_edges": component_edges,
        "component_averages": component_averages,
        "avg_risk_penalty": avg([row["risk_penalty"] for row in rows]),
        "blindspot_count": len(blindspots),
        "blindspot_avg_return_pct": avg([item["return_pct"] for item in blindspots]),
        "missing_signals": missing_signals,
    }


def propose_params_from_reviews(
    before_params: dict[str, Any],
    signal: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    after = dict(before_params)
    adjustments: list[dict[str, Any]] = []

    if signal["win_rate"] >= 0.55 and signal["avg_return_pct"] > 0 and signal["worst_drawdown_pct"] > -0.06:
        adjust_numeric(after, "position_pct", 1.05, 0.01, 0.2, adjustments, "reviews show positive expectancy")
    elif signal["avg_return_pct"] < 0 or signal["win_rate"] < 0.45:
        adjust_numeric(after, "position_pct", 0.9, 0.01, 0.2, adjustments, "reviews show weak expectancy")

    for component, edge in signal["component_edges"].items():
        key = COMPONENT_PARAM_KEYS[component]
        if edge > 0.05:
            adjust_numeric(after, key, 1.04, 0.02, 2.0, adjustments, f"{component} score separated winners")
        elif edge < -0.05:
            adjust_numeric(after, key, 0.96, 0.02, 2.0, adjustments, f"{component} score appeared in weak picks")

    if signal["blindspot_count"] > 0:
        adjust_numeric(after, "event_component_weight", 1.05, 0.02, 2.0, adjustments, "blindspot review suggests missed catalysts")
        adjust_numeric(after, "sector_component_weight", 1.05, 0.02, 2.0, adjustments, "blindspot review suggests missed sector moves")

    if signal["worst_drawdown_pct"] <= -0.04 or signal["loss_rate"] >= 0.4:
        adjust_numeric(after, "risk_component_weight", 1.06, 0.02, 2.0, adjustments, "reviews show drawdown or loss clustering")

    normalize_component_budget(after, before_params)
    round_tunable_params(after)
    rationale = {
        "method": "review_signal_parameter_adjustment",
        "guardrails": [
            "parent remains active",
            "child starts in observing status",
            "component weights keep the parent budget",
            "promotion or rollback is explicit",
        ],
        "adjustments": adjustments,
    }
    return after, rationale


def rollback_evolution(
    conn: sqlite3.Connection,
    *,
    child_gene_id: str | None = None,
    event_id: str | None = None,
    reason: str = "manual rollback",
) -> dict[str, Any]:
    event = find_proposal_event(conn, child_gene_id=child_gene_id, event_id=event_id)
    conn.execute(
        "UPDATE strategy_genes SET status = 'rolled_back', updated_at = CURRENT_TIMESTAMP WHERE gene_id = ?",
        (event["child_gene_id"],),
    )
    conn.execute(
        """
        UPDATE strategy_evolution_events
        SET status = 'rolled_back', rolled_back_at = CURRENT_TIMESTAMP
        WHERE event_id = ?
        """,
        (event["event_id"],),
    )
    rollback_id = persist_evolution_event(
        conn,
        parent_gene_id=event["parent_gene_id"],
        child_gene_id=event["child_gene_id"],
        event_type="rollback",
        period_start=event["period_start"],
        period_end=event["period_end"],
        market_environment=event["market_environment"],
        status="applied",
        rationale={"reason": reason, "rolled_back_event_id": event["event_id"]},
        before_params=json.loads(event["after_params_json"] or event["before_params_json"]),
        after_params=json.loads(event["before_params_json"]),
        review_signal=json.loads(event["review_signal_json"]),
    )
    conn.commit()
    return {
        "status": "rolled_back",
        "event_id": rollback_id,
        "proposal_event_id": event["event_id"],
        "child_gene_id": event["child_gene_id"],
    }


def promote_challenger(
    conn: sqlite3.Connection,
    *,
    child_gene_id: str,
    reason: str = "manual promotion",
) -> dict[str, Any]:
    event = find_proposal_event(conn, child_gene_id=child_gene_id)
    child = repository.get_gene(conn, event["child_gene_id"])
    if child["status"] == "rolled_back":
        raise ValueError(f"Cannot promote rolled back gene: {child_gene_id}")
    conn.execute(
        "UPDATE strategy_genes SET status = 'retired', updated_at = CURRENT_TIMESTAMP WHERE gene_id = ?",
        (event["parent_gene_id"],),
    )
    conn.execute(
        "UPDATE strategy_genes SET status = 'active', updated_at = CURRENT_TIMESTAMP WHERE gene_id = ?",
        (event["child_gene_id"],),
    )
    promotion_id = persist_evolution_event(
        conn,
        parent_gene_id=event["parent_gene_id"],
        child_gene_id=event["child_gene_id"],
        event_type="promotion",
        period_start=event["period_start"],
        period_end=event["period_end"],
        market_environment=event["market_environment"],
        status="applied",
        rationale={"reason": reason, "proposal_event_id": event["event_id"]},
        before_params=json.loads(event["before_params_json"]),
        after_params=json.loads(event["after_params_json"] or event["before_params_json"]),
        review_signal=json.loads(event["review_signal_json"]),
    )
    conn.commit()
    return {
        "status": "promoted",
        "event_id": promotion_id,
        "parent_gene_id": event["parent_gene_id"],
        "child_gene_id": event["child_gene_id"],
    }


def evolution_comparison(
    conn: sqlite3.Connection,
    *,
    gene_id: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    clauses = ["event_type = 'proposal'"]
    params: list[Any] = []
    if gene_id:
        clauses.append("(parent_gene_id = ? OR child_gene_id = ?)")
        params.extend([gene_id, gene_id])
    rows = conn.execute(
        f"""
        SELECT * FROM strategy_evolution_events
        WHERE {' AND '.join(clauses)}
        ORDER BY created_at DESC
        """,
        params,
    ).fetchall()
    comparisons: list[dict[str, Any]] = []
    for event in rows:
        period_start = start or event["period_start"]
        period_end = end or event["period_end"]
        review_signal = json.loads(event["review_signal_json"] or "{}")
        aggregated = review_signal.get("aggregated_signals", [])
        comparisons.append(
            {
                "event_id": event["event_id"],
                "parent_gene_id": event["parent_gene_id"],
                "child_gene_id": event["child_gene_id"],
                "status": event["status"],
                "period_start": period_start,
                "period_end": period_end,
                "parent_performance": gene_performance(conn, event["parent_gene_id"], period_start, period_end),
                "child_performance": gene_performance(conn, event["child_gene_id"], period_start, period_end)
                if event["child_gene_id"]
                else None,
                "parameter_diff": parameter_diff(
                    json.loads(event["before_params_json"] or "{}"),
                    json.loads(event["after_params_json"] or event["before_params_json"] or "{}"),
                ),
                "aggregated_signals": aggregated,
                "evidence_ids": sorted({evidence_id for item in aggregated for evidence_id in item.get("evidence_ids", [])}),
                "promotion_eligible": promotion_eligibility_detail(conn, event["child_gene_id"], period_start, period_end)
                if event["child_gene_id"]
                else {"eligible": False, "criteria": [], "performance": {}},
            }
        )
    return {"comparisons": comparisons}


def gene_performance(conn: sqlite3.Connection, gene_id: str, start: str, end: str) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT p.trading_date, o.return_pct, o.max_drawdown_intraday_pct
        FROM pick_decisions p
        JOIN outcomes o ON o.decision_id = p.decision_id
        WHERE p.strategy_gene_id = ?
          AND p.trading_date BETWEEN ? AND ?
        ORDER BY p.trading_date
        """,
        (gene_id, start, end),
    ).fetchall()
    returns = [float(row["return_pct"]) for row in rows]
    wins = [value for value in returns if value > 0]
    cumulative = []
    running = 1.0
    for ret in returns:
        running *= (1 + ret)
        cumulative.append(round(running - 1, 6))
    return {
        "gene_id": gene_id,
        "trades": len(rows),
        "avg_return_pct": avg(returns),
        "win_rate": len(wins) / len(rows) if rows else 0.0,
        "worst_drawdown_pct": min([float(row["max_drawdown_intraday_pct"]) for row in rows], default=0.0),
        "cumulative_return": cumulative[-1] if cumulative else 0.0,
        "cumulative_curve": cumulative,
        "trading_dates": [row["trading_date"] for row in rows],
    }


def parameter_diff(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    diffs: list[dict[str, Any]] = []
    for key in sorted(set(before) | set(after)):
        before_val = before.get(key)
        after_val = after.get(key)
        if before_val != after_val:
            pct_change = None
            exceeds_threshold = False
            if isinstance(before_val, (int, float)) and isinstance(after_val, (int, float)) and before_val != 0:
                pct_change = round((after_val - before_val) / abs(before_val) * 100, 2)
                exceeds_threshold = abs(pct_change) > 5.0
            diffs.append({
                "param": key,
                "before": before_val,
                "after": after_val,
                "pct_change": pct_change,
                "exceeds_5pct_threshold": exceeds_threshold,
            })
    return diffs


def promotion_eligible(conn: sqlite3.Connection, child_gene_id: str, start: str, end: str) -> bool:
    detail = promotion_eligibility_detail(conn, child_gene_id, start, end)
    return detail["eligible"]


def promotion_eligibility_detail(
    conn: sqlite3.Connection,
    child_gene_id: str,
    start: str,
    end: str,
) -> dict[str, Any]:
    """S6.4: Return detailed promotion eligibility criteria with pass/fail for each."""
    child = repository.get_gene(conn, child_gene_id)
    status_ok = child["status"] == "observing"
    perf = gene_performance(conn, child_gene_id, start, end)
    trades = int(perf["trades"])
    win_rate = float(perf["win_rate"])
    avg_return = float(perf["avg_return_pct"])
    drawdown = float(perf["worst_drawdown_pct"])

    criteria = [
        {"name": "status_observing", "label": "状态为 observing", "pass": status_ok, "value": child["status"]},
        {"name": "min_trades", "label": "最少 5 笔交易", "pass": trades >= 5, "value": trades, "threshold": 5},
        {"name": "positive_return", "label": "平均收益 > 0", "pass": avg_return > 0, "value": round(avg_return, 4)},
        {"name": "win_rate", "label": "胜率 ≥ 40%", "pass": win_rate >= 0.4, "value": round(win_rate, 4)},
        {"name": "max_drawdown", "label": "最大回撤 > -15%", "pass": drawdown > -0.15, "value": round(drawdown, 4)},
    ]
    eligible = status_ok and all(c["pass"] for c in criteria)
    return {"eligible": eligible, "criteria": criteria, "performance": perf}


def blindspots_for_gene(
    conn: sqlite3.Connection,
    gene_id: str,
    period_start: str,
    period_end: str,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT stock_code, trading_date, rank, return_pct, missed_by_gene_ids_json, reason
        FROM blindspot_reports
        WHERE trading_date BETWEEN ? AND ?
        ORDER BY trading_date, rank
        """,
        (period_start, period_end),
    ).fetchall()
    blindspots: list[dict[str, Any]] = []
    for row in rows:
        missed = json.loads(row["missed_by_gene_ids_json"])
        if gene_id in missed:
            blindspots.append(
                {
                    "stock_code": row["stock_code"],
                    "trading_date": row["trading_date"],
                    "rank": int(row["rank"]),
                    "return_pct": float(row["return_pct"]),
                    "reason": row["reason"],
                }
            )
    return blindspots


def missing_signals_for_gene(
    conn: sqlite3.Connection,
    gene_id: str,
    period_start: str,
    period_end: str,
) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT ambiguity_json FROM review_logs
        WHERE strategy_gene_id = ?
          AND trading_date BETWEEN ? AND ?
        """,
        (gene_id, period_start, period_end),
    ).fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        for signal in json.loads(row["ambiguity_json"] or "[]"):
            key = str(signal)
            counts[key] = counts.get(key, 0) + 1
    return counts


def adjust_numeric(
    params: dict[str, Any],
    key: str,
    factor: float,
    lower: float,
    upper: float,
    adjustments: list[dict[str, Any]],
    reason: str,
) -> None:
    if key not in params or not isinstance(params[key], (int, float)):
        return
    before = float(params[key])
    after = min(max(before * factor, lower), upper)
    if abs(after - before) < 1e-9:
        return
    params[key] = after
    adjustments.append(
        {
            "param": key,
            "before": before,
            "after": after,
            "factor": factor,
            "reason": reason,
        }
    )


def normalize_component_budget(after: dict[str, Any], before: dict[str, Any]) -> None:
    keys = list(COMPONENT_PARAM_KEYS.values())
    target = sum(float(before.get(key, 0)) for key in keys)
    current = sum(float(after.get(key, 0)) for key in keys)
    if target <= 0 or current <= 0:
        return
    ratio = target / current
    for key in keys:
        if isinstance(after.get(key), (int, float)):
            after[key] = float(after[key]) * ratio


def round_tunable_params(params: dict[str, Any]) -> None:
    for key in [
        "position_pct",
        "technical_component_weight",
        "fundamental_component_weight",
        "event_component_weight",
        "sector_component_weight",
        "risk_component_weight",
    ]:
        if isinstance(params.get(key), (int, float)):
            params[key] = round(float(params[key]), 6)


def params_changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    return repository.dumps(before) != repository.dumps(after)


def next_gene_version(conn: sqlite3.Connection, parent_gene_id: str) -> int:
    parent = repository.get_gene(conn, parent_gene_id)
    row = conn.execute(
        """
        SELECT MAX(version) AS version
        FROM strategy_genes
        WHERE gene_id = ? OR parent_gene_id = ?
        """,
        (parent_gene_id, parent_gene_id),
    ).fetchone()
    return max(int(parent["version"]), int(row["version"] or 0)) + 1


def persist_evolution_event(
    conn: sqlite3.Connection,
    *,
    parent_gene_id: str,
    child_gene_id: str | None,
    event_type: str,
    period_start: str,
    period_end: str,
    market_environment: str,
    status: str,
    rationale: dict[str, Any],
    before_params: dict[str, Any],
    after_params: dict[str, Any] | None,
    review_signal: dict[str, Any],
) -> str:
    event_id = build_evolution_event_id(
        parent_gene_id=parent_gene_id,
        child_gene_id=child_gene_id,
        event_type=event_type,
        period_start=period_start,
        period_end=period_end,
    )
    conn.execute(
        """
        INSERT INTO strategy_evolution_events(
          event_id, parent_gene_id, child_gene_id, event_type, period_start,
          period_end, market_environment, status, rationale_json,
          before_params_json, after_params_json, review_signal_json, applied_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(parent_gene_id, child_gene_id, event_type) DO UPDATE SET
          status = excluded.status,
          rationale_json = excluded.rationale_json,
          before_params_json = excluded.before_params_json,
          after_params_json = excluded.after_params_json,
          review_signal_json = excluded.review_signal_json,
          applied_at = excluded.applied_at
        """,
        (
            event_id,
            parent_gene_id,
            child_gene_id,
            event_type,
            period_start,
            period_end,
            market_environment,
            status,
            repository.dumps(rationale),
            repository.dumps(before_params),
            repository.dumps(after_params) if after_params is not None else None,
            repository.dumps(review_signal),
        ),
    )
    return event_id


def build_evolution_event_id(
    *,
    parent_gene_id: str,
    child_gene_id: str | None,
    event_type: str,
    period_start: str,
    period_end: str,
) -> str:
    raw = f"{parent_gene_id}:{child_gene_id}:{event_type}:{period_start}:{period_end}"
    return "evo_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14]


def find_proposal_event(
    conn: sqlite3.Connection,
    *,
    child_gene_id: str | None = None,
    event_id: str | None = None,
) -> sqlite3.Row:
    if event_id:
        row = conn.execute(
            """
            SELECT * FROM strategy_evolution_events
            WHERE event_id = ? AND event_type = 'proposal'
            """,
            (event_id,),
        ).fetchone()
    elif child_gene_id:
        row = conn.execute(
            """
            SELECT * FROM strategy_evolution_events
            WHERE child_gene_id = ? AND event_type = 'proposal'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (child_gene_id,),
        ).fetchone()
    else:
        raise ValueError("child_gene_id or event_id is required")
    if row is None:
        raise KeyError("Evolution proposal event not found")
    return row


def avg(values: list[Any]) -> float:
    numbers = [float(value) for value in values if value is not None]
    if not numbers:
        return 0.0
    return sum(numbers) / len(numbers)


def persist_gene_score(
    conn: sqlite3.Connection,
    item: dict[str, Any],
    period_start: str,
    period_end: str,
    market_environment: str,
) -> None:
    score_id = "score_" + hashlib.sha1(
        f"{item['gene_id']}:{period_start}:{period_end}:{market_environment}".encode("utf-8")
    ).hexdigest()[:12]
    conn.execute(
        """
        INSERT INTO gene_scores(
          score_id, gene_id, period_start, period_end, market_environment,
          trades, avg_return_pct, win_rate, worst_drawdown_pct,
          profit_loss_ratio, blindspot_penalty, score
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(gene_id, period_start, period_end, market_environment)
        DO UPDATE SET
          trades = excluded.trades,
          avg_return_pct = excluded.avg_return_pct,
          win_rate = excluded.win_rate,
          worst_drawdown_pct = excluded.worst_drawdown_pct,
          profit_loss_ratio = excluded.profit_loss_ratio,
          blindspot_penalty = excluded.blindspot_penalty,
          score = excluded.score
        """,
        (
            score_id,
            item["gene_id"],
            period_start,
            period_end,
            market_environment,
            item["trades"],
            item["avg_return_pct"],
            item["win_rate"],
            item["worst_drawdown_pct"],
            item["profit_loss_ratio"],
            item["blindspot_penalty"],
            item["score"],
        ),
    )


def blindspot_penalty_for_gene(conn: sqlite3.Connection, gene_id: str, period_start: str, period_end: str) -> float:
    rows = conn.execute(
        """
        SELECT missed_by_gene_ids_json FROM blindspot_reports
        WHERE trading_date BETWEEN ? AND ?
        """,
        (period_start, period_end),
    ).fetchall()
    misses = 0
    for row in rows:
        if gene_id in json.loads(row["missed_by_gene_ids_json"]):
            misses += 1
    return misses * 0.002


def default_week_window(today: date | None = None) -> tuple[str, str]:
    today = today or date.today()
    start_ord = today.toordinal() - 6
    return date.fromordinal(start_ord).isoformat(), today.isoformat()


def auto_promote_challengers(
    conn: sqlite3.Connection,
    *,
    min_trades: int = 3,
    min_win_rate: float = 0.5,
    min_avg_return: float = 0.0,
    max_drawdown_threshold: float = -0.10,
) -> list[dict[str, Any]]:
    """Auto-promote challengers that meet observation period criteria.

    A challenger is eligible for auto-promotion when:
    - Has at least min_trades during observation period
    - Win rate >= min_win_rate
    - Average return >= min_avg_return
    - Max drawdown <= max_drawdown_threshold (less negative is better)
    """
    # Find observing challengers
    observing = conn.execute(
        """
        SELECT DISTINCT see.child_gene_id, see.parent_gene_id,
               see.period_start, see.period_end, see.market_environment
        FROM strategy_evolution_events see
        WHERE see.event_type = 'proposal' AND see.status IN ('applied', 'observing')
        """
    ).fetchall()

    promoted = []
    for obs in observing:
        picks = conn.execute(
            """
            SELECT pd.decision_id, o.return_pct, o.max_drawdown_intraday_pct
            FROM pick_decisions pd
            LEFT JOIN outcomes o ON o.decision_id = pd.decision_id
            WHERE pd.strategy_gene_id = ?
              AND pd.trading_date BETWEEN ? AND ?
            """,
            (obs["child_gene_id"], obs["period_start"], obs["period_end"]),
        ).fetchall()

        returns = [float(p["return_pct"]) for p in picks if p["return_pct"] is not None]
        if len(returns) < min_trades:
            continue

        win_rate = sum(1 for r in returns if r > 0) / len(returns)
        avg_return = sum(returns) / len(returns)
        max_dd = min((p["max_drawdown_intraday_pct"] for p in picks if p["max_drawdown_intraday_pct"] is not None), default=0)

        if win_rate >= min_win_rate and avg_return >= min_avg_return and max_dd >= max_drawdown_threshold:
            try:
                result = promote_challenger(
                    conn,
                    child_gene_id=obs["child_gene_id"],
                    reason=f"auto-promote: {len(returns)} trades, {win_rate:.0%} win rate, {avg_return:.2%} avg return",
                )
                promoted.append(result)
            except Exception as exc:
                pass  # Log and continue with next challenger

    conn.commit()
    return promoted


def reconcile_environment_performance(
    conn: sqlite3.Connection,
    *,
    period_start: str | None = None,
    period_end: str | None = None,
) -> list[dict[str, Any]]:
    """Update gene_environment_performance table by grouping outcomes by market environment.

    Reads market_environment_logs to classify each trading day's environment,
    then aggregates gene performance per environment.
    """
    if not period_start or not period_end:
        period_start, period_end = default_week_window()

    has_alpha = _column_exists(conn, "outcomes", "alpha")
    alpha_col = "AVG(o.alpha)" if has_alpha else "AVG(o.return_pct)"

    conn.execute(
        f"""
        INSERT INTO gene_environment_performance(
          gene_id, market_environment, period_start, period_end,
          trade_count, win_rate, avg_return, max_drawdown, alpha
        )
        SELECT
          p.strategy_gene_id,
          COALESCE(mel.market_environment, 'unknown'),
          ?,
          ?,
          COUNT(o.outcome_id),
          SUM(CASE WHEN o.return_pct > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(o.outcome_id),
          AVG(o.return_pct),
          MIN(o.max_drawdown_intraday_pct),
          {alpha_col}
        FROM outcomes o
        JOIN pick_decisions p ON p.decision_id = o.decision_id
        LEFT JOIN market_environment_logs mel ON mel.trading_date = p.trading_date
        WHERE p.trading_date BETWEEN ? AND ?
        GROUP BY p.strategy_gene_id, COALESCE(mel.market_environment, 'unknown')
        ON CONFLICT(gene_id, market_environment, period_start) DO UPDATE SET
          period_end = excluded.period_end,
          trade_count = excluded.trade_count,
          win_rate = excluded.win_rate,
          avg_return = excluded.avg_return,
          max_drawdown = excluded.max_drawdown,
          alpha = excluded.alpha
        """,
        (period_start, period_end, period_start, period_end),
    )
    conn.commit()

    rows = conn.execute(
        "SELECT * FROM gene_environment_performance WHERE period_start = ? AND period_end = ?",
        (period_start, period_end),
    ).fetchall()
    return [dict(r) for r in rows]


def propose_factor_introduction(
    conn: sqlite3.Connection,
    gene_id: str,
    *,
    period_start: str,
    period_end: str,
) -> dict[str, Any] | None:
    """Check if a factor that appears in winning picks but is not used by the gene should be introduced.

    Scans candidate_scores for factors that correlate with wins, and proposes
    adding them to the gene's factor_config.
    """
    # Find factors that appear in winning picks for this gene
    winners = conn.execute(
        """
        SELECT c.packet_json
        FROM outcomes o
        JOIN pick_decisions p ON p.decision_id = o.decision_id
        JOIN candidate_scores c
          ON c.trading_date = p.trading_date
         AND c.strategy_gene_id = p.strategy_gene_id
         AND c.stock_code = p.stock_code
        WHERE p.strategy_gene_id = ?
          AND p.trading_date BETWEEN ? AND ?
          AND o.return_pct > 0
        """,
        (gene_id, period_start, period_end),
    ).fetchall()

    if len(winners) < 5:
        return None

    # Count factor presence in winners vs losers
    factor_presence: dict[str, tuple[int, int]] = {}
    for row in winners:
        packet = json.loads(row["packet_json"])
        for key in ("technical", "fundamental", "event", "sector"):
            score = packet.get(key, {}).get("score", 0)
            present = 1 if score > 0.3 else 0
            total_w, total_l = factor_presence.get(key, (0, 0))
            factor_presence[key] = (total_w + present, total_l)

    losers = conn.execute(
        """
        SELECT c.packet_json
        FROM outcomes o
        JOIN pick_decisions p ON p.decision_id = o.decision_id
        JOIN candidate_scores c
          ON c.trading_date = p.trading_date
         AND c.strategy_gene_id = p.strategy_gene_id
         AND c.stock_code = p.stock_code
        WHERE p.strategy_gene_id = ?
          AND p.trading_date BETWEEN ? AND ?
          AND o.return_pct <= 0
        """,
        (gene_id, period_start, period_end),
    ).fetchall()

    for row in losers:
        packet = json.loads(row["packet_json"])
        for key in ("technical", "fundamental", "event", "sector"):
            score = packet.get(key, {}).get("score", 0)
            present = 1 if score > 0.3 else 0
            total_w, total_l = factor_presence.get(key, (0, 0))
            factor_presence[key] = (total_w, total_l + present)

    # Find factors with high win ratio that gene doesn't heavily weight
    gene = repository.get_gene(conn, gene_id)
    params = json.loads(gene["params_json"])
    factor_config = params.get("factor_config", {})

    for factor_key, (wins, losses) in factor_presence.items():
        total = wins + losses
        if total < 3:
            continue
        win_ratio = wins / total
        # If factor has >60% win ratio but gene doesn't require minimum score for it
        if win_ratio > 0.6:
            min_score_key = f"min_{factor_key}_score"
            if not factor_config.get(min_score_key):
                return {
                    "gene_id": gene_id,
                    "factor": factor_key,
                    "win_ratio": win_ratio,
                    "proposal": f"add {min_score_key}=0.2 to factor_config",
                }

    return None


def check_environment_mismatch(
    conn: sqlite3.Connection,
    gene_id: str,
    *,
    period_start: str,
    period_end: str,
) -> list[dict[str, Any]]:
    """Detect if a gene is performing poorly in specific environments.

    Returns environments where the gene has <40% win rate with sufficient trades.
    """
    rows = conn.execute(
        """
        SELECT gep.*, COUNT(*) OVER (PARTITION BY gep.gene_id) AS env_count
        FROM gene_environment_performance gep
        WHERE gep.gene_id = ?
          AND gep.period_start = ?
          AND gep.period_end = ?
        """,
        (gene_id, period_start, period_end),
    ).fetchall()

    mismatches = []
    for row in rows:
        if row["trade_count"] >= 10 and row["win_rate"] < 0.40:
            mismatches.append({
                "gene_id": gene_id,
                "market_environment": row["market_environment"],
                "win_rate": row["win_rate"],
                "trade_count": row["trade_count"],
                "avg_alpha": row["alpha"],
                "action": "consider removing this environment from market_environments",
            })

    return mismatches
