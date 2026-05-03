from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass
from typing import Any

from . import repository
from .candidate_pipeline import Candidate, rank_candidates_for_gene
from .contracts import PickContract


DEFAULT_GENES: list[dict[str, Any]] = [
    {
        "gene_id": "gene_aggressive_v1",
        "name": "Aggressive momentum",
        "horizon": "short",
        "risk_profile": "aggressive",
        "strategy_type": "momentum_breakout",
        "market_environments": ["all"],
        "params": {
            "lookback_days": 5,
            "max_picks": 3,
            "momentum_weight": 0.62,
            "volume_weight": 0.24,
            "volatility_weight": 0.14,
            "volatility_penalty": 0.0,
            "position_pct": 0.12,
            "min_score": 0.01,
            "take_profit_pct": 0.06,
            "stop_loss_pct": -0.035,
            "time_exit_days": 1,
            "technical_component_weight": 0.42,
            "fundamental_component_weight": 0.12,
            "event_component_weight": 0.26,
            "sector_component_weight": 0.2,
            "risk_component_weight": 0.28,
            "max_per_industry": 2,
            "min_avg_amount": 0,
        },
    },
    {
        "gene_id": "gene_conservative_v1",
        "name": "Conservative quality trend",
        "horizon": "long",
        "risk_profile": "conservative",
        "strategy_type": "quality_value",
        "market_environments": ["all"],
        "params": {
            "lookback_days": 8,
            "max_picks": 3,
            "momentum_weight": 0.38,
            "volume_weight": 0.12,
            "volatility_weight": 0.0,
            "volatility_penalty": 0.5,
            "position_pct": 0.08,
            "min_score": 0.005,
            "take_profit_pct": 0.10,
            "stop_loss_pct": -0.05,
            "time_exit_days": 5,
            "technical_component_weight": 0.22,
            "fundamental_component_weight": 0.46,
            "event_component_weight": 0.08,
            "sector_component_weight": 0.14,
            "risk_component_weight": 0.42,
            "max_per_industry": 2,
            "min_avg_amount": 0,
        },
    },
    {
        "gene_id": "gene_balanced_v1",
        "name": "Balanced multi-factor",
        "horizon": "short",
        "risk_profile": "balanced",
        "strategy_type": "balanced",
        "market_environments": ["all"],
        "params": {
            "lookback_days": 6,
            "max_picks": 4,
            "momentum_weight": 0.5,
            "volume_weight": 0.18,
            "volatility_weight": 0.08,
            "volatility_penalty": 0.18,
            "position_pct": 0.10,
            "min_score": 0.008,
            "take_profit_pct": 0.075,
            "stop_loss_pct": -0.04,
            "time_exit_days": 3,
            "technical_component_weight": 0.34,
            "fundamental_component_weight": 0.26,
            "event_component_weight": 0.18,
            "sector_component_weight": 0.22,
            "risk_component_weight": 0.34,
            "max_per_industry": 2,
            "min_avg_amount": 0,
        },
    },
]

# Challenger genes: new strategy types, introduced for competition
CHALLENGER_GENES: list[dict[str, Any]] = [
    {
        "gene_id": "gene_mean_reversion_v1",
        "name": "Mean reversion",
        "horizon": "short",
        "risk_profile": "aggressive",
        "strategy_type": "mean_reversion",
        "market_environments": ["all"],
        "params": {
            "lookback_days": 10,
            "max_picks": 3,
            "momentum_weight": -0.3,
            "volume_weight": 0.15,
            "volatility_weight": 0.1,
            "volatility_penalty": 0.05,
            "position_pct": 0.08,
            "min_score": 0.005,
            "take_profit_pct": 0.05,
            "stop_loss_pct": -0.04,
            "time_exit_days": 2,
            "technical_component_weight": 0.55,
            "fundamental_component_weight": 0.1,
            "event_component_weight": 0.15,
            "sector_component_weight": 0.1,
            "risk_component_weight": 0.3,
            "max_per_industry": 2,
            "min_avg_amount": 0,
        },
    },
    {
        "gene_id": "gene_event_driven_v1",
        "name": "Event driven",
        "horizon": "short",
        "risk_profile": "aggressive",
        "strategy_type": "event_driven",
        "market_environments": ["all"],
        "params": {
            "lookback_days": 5,
            "max_picks": 4,
            "momentum_weight": 0.3,
            "volume_weight": 0.2,
            "volatility_weight": 0.05,
            "volatility_penalty": 0.1,
            "position_pct": 0.07,
            "min_score": 0.005,
            "take_profit_pct": 0.08,
            "stop_loss_pct": -0.03,
            "time_exit_days": 1,
            "technical_component_weight": 0.2,
            "fundamental_component_weight": 0.1,
            "event_component_weight": 0.45,
            "sector_component_weight": 0.15,
            "risk_component_weight": 0.25,
            "max_per_industry": 3,
            "min_avg_amount": 0,
        },
    },
    {
        "gene_id": "gene_defensive_v1",
        "name": "Defensive low-vol",
        "horizon": "long",
        "risk_profile": "conservative",
        "strategy_type": "defensive",
        "market_environments": ["all"],
        "params": {
            "lookback_days": 12,
            "max_picks": 2,
            "momentum_weight": 0.2,
            "volume_weight": 0.1,
            "volatility_weight": 0.0,
            "volatility_penalty": 0.6,
            "position_pct": 0.06,
            "min_score": 0.003,
            "take_profit_pct": 0.12,
            "stop_loss_pct": -0.06,
            "time_exit_days": 5,
            "technical_component_weight": 0.18,
            "fundamental_component_weight": 0.35,
            "event_component_weight": 0.05,
            "sector_component_weight": 0.12,
            "risk_component_weight": 0.5,
            "max_per_industry": 1,
            "min_avg_amount": 50000000,
        },
    },
]


@dataclass(frozen=True)
class StockScore:
    stock_code: str
    score: float
    confidence: float
    thesis: dict[str, list[str]]
    risks: list[str]


def seed_default_genes(conn: sqlite3.Connection) -> None:
    for gene in DEFAULT_GENES + CHALLENGER_GENES:
        conn.execute(
            """
            INSERT INTO strategy_genes(
              gene_id, name, version, horizon, risk_profile, status,
              strategy_type, market_environments_json, params_json
            )
            VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(gene_id) DO UPDATE SET
              name = excluded.name,
              horizon = excluded.horizon,
              risk_profile = excluded.risk_profile,
              params_json = excluded.params_json,
              strategy_type = excluded.strategy_type,
              market_environments_json = excluded.market_environments_json,
              updated_at = CURRENT_TIMESTAMP
            """,
            (
                gene["gene_id"],
                gene["name"],
                gene["horizon"],
                gene["risk_profile"],
                "active" if gene in DEFAULT_GENES else "observing",
                gene.get("strategy_type", "generic"),
                json.dumps(gene.get("market_environments", ["all"])),
                repository.dumps(gene["params"]),
            ),
        )
    conn.commit()


def generate_picks_for_gene(
    conn: sqlite3.Connection,
    trading_date: str,
    gene_id: str,
    *,
    preserve_audit: bool = False,
) -> list[str]:
    gene = repository.get_gene(conn, gene_id)
    params = json.loads(gene["params_json"])
    required = {"max_picks", "min_score", "position_pct", "take_profit_pct", "stop_loss_pct", "time_exit_days"}
    missing = required - set(params.keys())
    if missing:
        raise ValueError(f"gene {gene_id} params missing required keys: {missing}")
    clear_existing_gene_decisions(conn, trading_date, gene_id, preserve_audit=preserve_audit)
    candidates = rank_candidates_for_gene(conn, trading_date, gene_id, params)
    max_picks = int(params["max_picks"])
    min_score = float(params["min_score"])

    decision_ids: list[str] = []
    for candidate in candidates[:max_picks]:
        if candidate.total_score < min_score:
            continue
        decision_id = build_decision_id(trading_date, gene_id, candidate.stock_code)
        pick = PickContract.validate(
            {
                "trading_date": trading_date,
                "horizon": gene["horizon"],
                "strategy_gene_id": gene_id,
                "stock_code": candidate.stock_code,
                "action": "BUY",
                "confidence": candidate.confidence,
                "position_pct": float(params["position_pct"]),
                "score": candidate.total_score,
                "entry_plan": {"price_source": "open", "max_slippage_pct": 0.002},
                "sell_rules": [
                    {"type": "take_profit", "threshold_pct": params["take_profit_pct"]},
                    {"type": "stop_loss", "threshold_pct": params["stop_loss_pct"]},
                    {"type": "time_exit", "days": params["time_exit_days"]},
                ],
                "thesis": thesis_from_candidate(candidate),
                "risks": risks_from_candidate(candidate),
                "invalid_if": ["data_missing", "limit_up_at_open", "suspended"],
                "input_snapshot_hash": input_snapshot_hash(trading_date, gene_id, candidate.stock_code),
            }
        )
        conn.execute(
            """
            INSERT INTO pick_decisions(
              decision_id, trading_date, horizon, strategy_gene_id, stock_code,
              action, confidence, position_pct, score, entry_plan_json,
              sell_rules_json, thesis_json, risks_json, invalid_if_json,
              input_snapshot_hash
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(trading_date, strategy_gene_id, stock_code) DO UPDATE SET
              action = excluded.action,
              confidence = excluded.confidence,
              position_pct = excluded.position_pct,
              score = excluded.score,
              entry_plan_json = excluded.entry_plan_json,
              sell_rules_json = excluded.sell_rules_json,
              thesis_json = excluded.thesis_json,
              risks_json = excluded.risks_json,
              invalid_if_json = excluded.invalid_if_json,
              input_snapshot_hash = excluded.input_snapshot_hash
            """,
            (
                decision_id,
                pick.trading_date,
                pick.horizon,
                pick.strategy_gene_id,
                pick.stock_code,
                pick.action,
                pick.confidence,
                pick.position_pct,
                pick.score,
                repository.dumps(pick.entry_plan),
                repository.dumps(pick.sell_rules),
                repository.dumps(pick.thesis),
                repository.dumps(pick.risks),
                repository.dumps(pick.invalid_if),
                pick.input_snapshot_hash,
            ),
        )
        decision_ids.append(decision_id)
    conn.commit()
    return decision_ids


def clear_existing_gene_decisions(
    conn: sqlite3.Connection,
    trading_date: str,
    gene_id: str,
    *,
    preserve_audit: bool = False,
) -> None:
    rows = conn.execute(
        """
        SELECT decision_id FROM pick_decisions
        WHERE trading_date = ? AND strategy_gene_id = ?
        """,
        (trading_date, gene_id),
    ).fetchall()
    decision_ids = [row["decision_id"] for row in rows]
    if not decision_ids:
        return
    placeholders = ",".join("?" for _ in decision_ids)
    review_rows = conn.execute(
        f"SELECT review_id FROM decision_reviews WHERE decision_id IN ({placeholders})",
        decision_ids,
    ).fetchall()
    review_ids = [row["review_id"] for row in review_rows]
    if preserve_audit:
        archive_existing_gene_decisions(conn, trading_date, gene_id, decision_ids, review_ids)
    if review_ids:
        review_placeholders = ",".join("?" for _ in review_ids)
        conn.execute(f"DELETE FROM factor_review_items WHERE review_id IN ({review_placeholders})", review_ids)
        conn.execute(f"DELETE FROM review_evidence WHERE review_id IN ({review_placeholders})", review_ids)
        conn.execute(
            f"DELETE FROM review_errors WHERE review_scope = 'decision' AND review_id IN ({review_placeholders})",
            review_ids,
        )
        conn.execute(
            f"DELETE FROM optimization_signals WHERE source_type = 'decision_review' AND source_id IN ({review_placeholders})",
            review_ids,
        )
        conn.execute(f"DELETE FROM decision_reviews WHERE review_id IN ({review_placeholders})", review_ids)
    conn.execute(f"DELETE FROM review_logs WHERE decision_id IN ({placeholders})", decision_ids)
    conn.execute(f"DELETE FROM pick_evaluations WHERE decision_id IN ({placeholders})", decision_ids)
    conn.execute(f"DELETE FROM outcomes WHERE decision_id IN ({placeholders})", decision_ids)
    conn.execute(f"DELETE FROM sim_orders WHERE decision_id IN ({placeholders})", decision_ids)
    conn.execute(f"DELETE FROM pick_decisions WHERE decision_id IN ({placeholders})", decision_ids)


def archive_existing_gene_decisions(
    conn: sqlite3.Connection,
    trading_date: str,
    gene_id: str,
    decision_ids: list[str],
    review_ids: list[str],
) -> None:
    if not decision_ids:
        return
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pick_rerun_archives (
          archive_id TEXT PRIMARY KEY,
          trading_date TEXT NOT NULL,
          strategy_gene_id TEXT NOT NULL,
          decision_id TEXT,
          artifact_type TEXT NOT NULL,
          artifact_id TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          superseded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    decision_placeholders = ",".join("?" for _ in decision_ids)
    specs: list[tuple[str, str, str, list[str]]] = [
        ("pick_decision", "decision_id", f"SELECT * FROM pick_decisions WHERE decision_id IN ({decision_placeholders})", decision_ids),
        ("sim_order", "order_id", f"SELECT * FROM sim_orders WHERE decision_id IN ({decision_placeholders})", decision_ids),
        ("outcome", "outcome_id", f"SELECT * FROM outcomes WHERE decision_id IN ({decision_placeholders})", decision_ids),
        ("review_log", "review_id", f"SELECT * FROM review_logs WHERE decision_id IN ({decision_placeholders})", decision_ids),
        ("pick_evaluation", "evaluation_id", f"SELECT * FROM pick_evaluations WHERE decision_id IN ({decision_placeholders})", decision_ids),
    ]
    if review_ids:
        review_placeholders = ",".join("?" for _ in review_ids)
        specs.extend(
            [
                ("decision_review", "review_id", f"SELECT * FROM decision_reviews WHERE review_id IN ({review_placeholders})", review_ids),
                ("factor_review_item", "item_id", f"SELECT * FROM factor_review_items WHERE review_id IN ({review_placeholders})", review_ids),
                ("review_evidence", "evidence_id", f"SELECT * FROM review_evidence WHERE review_id IN ({review_placeholders})", review_ids),
                ("review_error", "error_id", f"SELECT * FROM review_errors WHERE review_scope = 'decision' AND review_id IN ({review_placeholders})", review_ids),
                ("optimization_signal", "signal_id", f"SELECT * FROM optimization_signals WHERE source_type = 'decision_review' AND source_id IN ({review_placeholders})", review_ids),
            ]
        )
    for artifact_type, id_column, query, params in specs:
        for row in conn.execute(query, params).fetchall():
            payload = dict(row)
            artifact_id = str(payload.get(id_column) or payload.get("rowid") or "")
            decision_id = str(payload.get("decision_id") or "")
            archive_id = hashlib.sha1(
                f"{trading_date}:{gene_id}:{artifact_type}:{artifact_id}".encode("utf-8")
            ).hexdigest()
            conn.execute(
                """
                INSERT INTO pick_rerun_archives(
                  archive_id, trading_date, strategy_gene_id, decision_id,
                  artifact_type, artifact_id, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(archive_id) DO UPDATE SET
                  payload_json = excluded.payload_json,
                  superseded_at = CURRENT_TIMESTAMP
                """,
                (
                    f"archive_{archive_id[:16]}",
                    trading_date,
                    gene_id,
                    decision_id or None,
                    artifact_type,
                    artifact_id,
                    repository.dumps(payload),
                ),
            )


def thesis_from_candidate(candidate: Candidate) -> dict[str, list[str]]:
    packet = candidate.packet
    technical = packet["technical"]
    fundamental = packet["fundamental"]
    event = packet["event"]
    sector = packet["sector"]
    return {
        "technical": [
            f"momentum {technical['momentum']:.2%}",
            f"volume surge {technical['volume_surge']:.2%}",
            f"trend {technical['trend_state']}",
        ],
        "fundamental": [
            f"fundamental score {fundamental['score']:.2f}",
            str(fundamental.get("note") or "no fundamental note"),
        ],
        "news": [
            f"{item['event_type']}: {item['title']}"
            for item in event.get("items", [])[:3]
        ],
        "market_environment": [
            f"sector score {sector['score']:.2f}",
            str(sector.get("summary") or "no sector signal"),
        ],
    }


def risks_from_candidate(candidate: Candidate) -> list[str]:
    risks = list(candidate.packet["risk"].get("reasons", []))
    if candidate.fundamental_score <= 0:
        risks.append("fundamental data missing or weak")
    if candidate.event_score < 0:
        risks.append("negative event signal")
    return risks


def generate_picks_for_all_genes(
    conn: sqlite3.Connection,
    trading_date: str,
    *,
    preserve_audit: bool = False,
) -> list[str]:
    decision_ids: list[str] = []
    for gene in repository.get_active_genes(conn):
        decision_ids.extend(
            generate_picks_for_gene(conn, trading_date, gene["gene_id"], preserve_audit=preserve_audit)
        )
    return decision_ids


def score_universe(
    conn: sqlite3.Connection,
    trading_date: str,
    params: dict[str, Any],
) -> list[StockScore]:
    scores: list[StockScore] = []
    for stock_code in repository.active_stock_codes(conn):
        score = score_stock(conn, stock_code, trading_date, params)
        if score is not None:
            scores.append(score)
    scores.sort(key=lambda item: item.score, reverse=True)
    return scores


def score_stock(
    conn: sqlite3.Connection,
    stock_code: str,
    trading_date: str,
    params: dict[str, Any],
) -> StockScore | None:
    lookback = int(params["lookback_days"])
    history = repository.price_history_before(conn, stock_code, trading_date, lookback)
    if len(history) < max(3, lookback):
        return None

    closes = [float(row["close"]) for row in history]
    volumes = [float(row["volume"]) for row in history]
    returns = daily_returns(closes)
    if not returns:
        return None

    momentum = closes[-1] / closes[0] - 1
    recent_volume = mean(volumes[-3:])
    prior_volume = mean(volumes[:-3]) if len(volumes) > 3 else recent_volume
    volume_surge = 0 if prior_volume <= 0 else recent_volume / prior_volume - 1
    volatility = stdev(returns)

    score = (
        momentum * float(params["momentum_weight"])
        + clamp(volume_surge, -0.5, 2.0) * float(params["volume_weight"])
        + volatility * float(params["volatility_weight"])
        - volatility * float(params["volatility_penalty"])
    )
    confidence = clamp(0.45 + abs(score) * 2.5, 0.05, 0.95)

    thesis = {
        "technical": [
            f"{lookback}d momentum {momentum:.2%}",
            f"recent volume change {volume_surge:.2%}",
        ],
        "fundamental": [],
        "news": [],
        "market_environment": [],
    }
    risks = []
    if volatility > 0.06:
        risks.append(f"high recent volatility {volatility:.2%}")
    if momentum < 0:
        risks.append("negative lookback momentum")

    return StockScore(
        stock_code=stock_code,
        score=score,
        confidence=confidence,
        thesis=thesis,
        risks=risks,
    )


def daily_returns(closes: list[float]) -> list[float]:
    return [
        closes[index] / closes[index - 1] - 1
        for index in range(1, len(closes))
        if closes[index - 1] > 0
    ]


def mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    avg = mean(values)
    variance = sum((value - avg) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def build_decision_id(trading_date: str, gene_id: str, stock_code: str) -> str:
    raw = f"{trading_date}:{gene_id}:{stock_code}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"pick_{digest}"


def input_snapshot_hash(trading_date: str, gene_id: str, stock_code: str) -> str:
    raw = f"preopen:{trading_date}:{gene_id}:{stock_code}:prices_before_date"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
