from __future__ import annotations

import hashlib
import sqlite3
from collections import Counter
from typing import Any

from . import repository
from .optimization_signals import list_optimization_signals, upsert_optimization_signal


FACTOR_KEYS = ["technical", "fundamental", "event", "sector", "risk"]


def run_gene_reviews_for_date(conn: sqlite3.Connection, trading_date: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT strategy_gene_id
        FROM pick_decisions
        WHERE trading_date = ?
        ORDER BY strategy_gene_id
        """,
        (trading_date,),
    ).fetchall()
    ids = [
        review_gene(
            conn,
            gene_id=row["strategy_gene_id"],
            period_start=trading_date,
            period_end=trading_date,
        )
        for row in rows
    ]
    conn.commit()
    return ids


def review_gene(
    conn: sqlite3.Connection,
    *,
    gene_id: str,
    period_start: str,
    period_end: str,
    market_environment: str = "all",
) -> str:
    decisions = conn.execute(
        """
        SELECT d.*, o.return_pct, o.max_drawdown_intraday_pct
        FROM decision_reviews d
        JOIN outcomes o ON o.decision_id = d.decision_id
        WHERE d.strategy_gene_id = ?
          AND d.trading_date BETWEEN ? AND ?
        ORDER BY d.trading_date
        """,
        (gene_id, period_start, period_end),
    ).fetchall()
    returns = [float(row["return_pct"]) for row in decisions]
    trades = len(decisions)
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value <= 0]
    avg_loss = abs(mean(losses))
    profit_loss_ratio = mean(wins) / avg_loss if avg_loss else mean(wins)
    factor_edges = compute_factor_edges(conn, gene_id, period_start, period_end)
    top_errors = top_errors_for_gene(conn, gene_id, period_start, period_end)
    blindspot_count = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM blindspot_reviews
        WHERE trading_date BETWEEN ? AND ?
          AND affected_gene_ids_json LIKE ?
        """,
        (period_start, period_end, f"%{gene_id}%"),
    ).fetchone()["count"]
    gene_review_id = build_gene_review_id(gene_id, period_start, period_end, market_environment)
    deterministic = {
        "returns": returns,
        "factor_edges": factor_edges,
        "top_errors": top_errors,
        "blindspot_count": int(blindspot_count or 0),
    }
    summary = (
        f"{gene_id} {period_start}..{period_end}: {trades} trades, "
        f"avg {mean(returns):.2%}, win {len(wins) / trades:.2%}."
        if trades
        else f"{gene_id} {period_start}..{period_end}: no trades."
    )
    conn.execute(
        """
        INSERT INTO gene_reviews(
          gene_review_id, strategy_gene_id, period_start, period_end,
          market_environment, trades, avg_return_pct, win_rate,
          worst_drawdown_pct, profit_loss_ratio, blindspot_count,
          thesis_quality_avg, factor_edges_json, top_errors_json,
          deterministic_json, summary
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(strategy_gene_id, period_start, period_end, market_environment)
        DO UPDATE SET
          trades = excluded.trades,
          avg_return_pct = excluded.avg_return_pct,
          win_rate = excluded.win_rate,
          worst_drawdown_pct = excluded.worst_drawdown_pct,
          profit_loss_ratio = excluded.profit_loss_ratio,
          blindspot_count = excluded.blindspot_count,
          thesis_quality_avg = excluded.thesis_quality_avg,
          factor_edges_json = excluded.factor_edges_json,
          top_errors_json = excluded.top_errors_json,
          deterministic_json = excluded.deterministic_json,
          summary = excluded.summary
        """,
        (
            gene_review_id,
            gene_id,
            period_start,
            period_end,
            market_environment,
            trades,
            mean(returns),
            len(wins) / trades if trades else 0,
            min([float(row["max_drawdown_intraday_pct"]) for row in decisions], default=0),
            profit_loss_ratio,
            int(blindspot_count or 0),
            mean([float(row["thesis_quality_score"]) for row in decisions]),
            repository.dumps(factor_edges),
            repository.dumps(top_errors),
            repository.dumps(deterministic),
            summary,
        ),
    )
    generate_gene_signals(conn, gene_review_id, gene_id, top_errors)
    return gene_review_id


def compute_factor_edges(conn: sqlite3.Connection, gene_id: str, start: str, end: str) -> dict[str, dict[str, float]]:
    rows = conn.execute(
        """
        SELECT p.stock_code, o.return_pct, c.technical_score, c.fundamental_score,
               c.event_score, c.sector_score, c.risk_penalty
        FROM pick_decisions p
        JOIN outcomes o ON o.decision_id = p.decision_id
        LEFT JOIN candidate_scores c
          ON c.trading_date = p.trading_date
         AND c.strategy_gene_id = p.strategy_gene_id
         AND c.stock_code = p.stock_code
        WHERE p.strategy_gene_id = ?
          AND p.trading_date BETWEEN ? AND ?
        """,
        (gene_id, start, end),
    ).fetchall()
    output: dict[str, dict[str, float]] = {}
    for factor, column in [
        ("technical", "technical_score"),
        ("fundamental", "fundamental_score"),
        ("event", "event_score"),
        ("sector", "sector_score"),
        ("risk", "risk_penalty"),
    ]:
        winners = [float(row[column] or 0) for row in rows if float(row["return_pct"]) > 0]
        losers = [float(row[column] or 0) for row in rows if float(row["return_pct"]) <= 0]
        output[factor] = {
            "winner_avg": mean(winners),
            "loser_avg": mean(losers),
            "edge": mean(winners) - mean(losers),
        }
    return output


def top_errors_for_gene(conn: sqlite3.Connection, gene_id: str, start: str, end: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT e.error_type, COUNT(*) AS count, AVG(e.severity) AS avg_severity
        FROM review_errors e
        JOIN decision_reviews d ON d.review_id = e.review_id
        WHERE e.review_scope = 'decision'
          AND d.strategy_gene_id = ?
          AND d.trading_date BETWEEN ? AND ?
        GROUP BY e.error_type
        ORDER BY count DESC, avg_severity DESC
        LIMIT 8
        """,
        (gene_id, start, end),
    ).fetchall()
    return [dict(row) for row in rows]


def generate_gene_signals(
    conn: sqlite3.Connection,
    gene_review_id: str,
    gene_id: str,
    top_errors: list[dict[str, Any]],
) -> None:
    mapping = {
        "underweighted_event": ("increase_weight", "event_component_weight", "up"),
        "false_catalyst": ("decrease_weight", "event_component_weight", "down"),
        "underweighted_sector": ("increase_weight", "sector_component_weight", "up"),
        "risk_underestimated": ("increase_weight", "risk_component_weight", "up"),
        "threshold_too_strict": ("lower_threshold", "min_score", "down"),
        "threshold_too_loose": ("raise_threshold", "min_score", "up"),
    }
    for error in top_errors:
        error_type = error["error_type"]
        if error_type not in mapping:
            continue
        signal_type, param_name, direction = mapping[error_type]
        upsert_optimization_signal(
            conn,
            source_type="gene_review",
            source_id=gene_review_id,
            target_gene_id=gene_id,
            scope="gene",
            scope_key=gene_id,
            signal_type=signal_type,
            param_name=param_name,
            direction=direction,
            strength=min(1.0, float(error["avg_severity"] or 0.4)),
            confidence=0.72,
            sample_size=int(error["count"] or 1),
            reason=f"{error_type} repeated in gene review",
            evidence_ids=[gene_review_id],
        )


def list_preopen_strategy_reviews(conn: sqlite3.Connection, trading_date: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM gene_reviews
        WHERE period_start = ? AND period_end = ?
        ORDER BY avg_return_pct DESC
        """,
        (trading_date, trading_date),
    ).fetchall()
    return [enrich_gene_review(conn, row, trading_date) for row in rows]


def get_preopen_strategy_review(conn: sqlite3.Connection, gene_id: str, trading_date: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT * FROM gene_reviews
        WHERE strategy_gene_id = ? AND period_start = ? AND period_end = ?
        """,
        (gene_id, trading_date, trading_date),
    ).fetchone()
    if row is None:
        review_gene(conn, gene_id=gene_id, period_start=trading_date, period_end=trading_date)
        row = conn.execute(
            """
            SELECT * FROM gene_reviews
            WHERE strategy_gene_id = ? AND period_start = ? AND period_end = ?
            """,
            (gene_id, trading_date, trading_date),
        ).fetchone()
    return enrich_gene_review(conn, row, trading_date)


def enrich_gene_review(conn: sqlite3.Connection, row: sqlite3.Row, trading_date: str) -> dict[str, Any]:
    gene_id = row["strategy_gene_id"]
    gene = repository.get_gene(conn, gene_id)
    picks = repository.rows_to_dicts(
        conn.execute(
            """
            SELECT p.*, s.name AS stock_name, o.return_pct
            FROM pick_decisions p
            JOIN stocks s ON s.stock_code = p.stock_code
            LEFT JOIN outcomes o ON o.decision_id = p.decision_id
            WHERE p.trading_date = ? AND p.strategy_gene_id = ?
            ORDER BY p.score DESC
            """,
            (trading_date, gene_id),
        )
    )
    candidates = repository.rows_to_dicts(
        conn.execute(
            """
            SELECT * FROM candidate_scores
            WHERE trading_date = ? AND strategy_gene_id = ?
            ORDER BY total_score DESC
            LIMIT 20
            """,
            (trading_date, gene_id),
        )
    )
    blindspots = repository.rows_to_dicts(
        conn.execute(
            """
            SELECT * FROM blindspot_reviews
            WHERE trading_date = ?
              AND affected_gene_ids_json LIKE ?
            ORDER BY rank
            """,
            (trading_date, f"%{gene_id}%"),
        )
    )
    return dict(row) | {
        "params": repository.loads(gene["params_json"], {}),
        "picks": picks,
        "candidate_summary": candidate_summary(candidates),
        "candidate_top": candidates[:8],
        "blindspots": blindspots,
        "signals": list_optimization_signals(conn, gene_id=gene_id, status="open", limit=50),
    }


def candidate_summary(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    industries = Counter()
    for candidate in candidates:
        packet = repository.loads(candidate.get("packet_json"), {})
        industry = packet.get("stock", {}).get("industry") or "unknown"
        industries[industry] += 1
    return {"count": len(candidates), "industries": dict(industries)}


def build_gene_review_id(gene_id: str, start: str, end: str, market_environment: str) -> str:
    return "generev_" + hashlib.sha1(f"{gene_id}:{start}:{end}:{market_environment}".encode("utf-8")).hexdigest()[:12]


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0

