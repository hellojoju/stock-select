from __future__ import annotations

import hashlib
import sqlite3
from typing import Any

from . import repository
from .blindspots import scan_blindspots
from .deterministic_review import upsert_review_error
from .optimization_signals import upsert_optimization_signal


def run_blindspot_review(conn: sqlite3.Connection, trading_date: str, top_n: int = 10) -> list[str]:
    scan_blindspots(conn, trading_date, top_n)
    reports = conn.execute(
        """
        SELECT b.*, s.industry
        FROM blindspot_reports b
        JOIN stocks s ON s.stock_code = b.stock_code
        WHERE b.trading_date = ?
        ORDER BY b.rank
        """,
        (trading_date,),
    ).fetchall()
    ids: list[str] = []
    for report in reports:
        ids.append(upsert_blindspot_review(conn, report))
    conn.commit()
    return ids


def upsert_blindspot_review(conn: sqlite3.Connection, report: sqlite3.Row) -> str:
    trading_date = report["trading_date"]
    stock_code = report["stock_code"]
    affected_gene_ids = repository.loads(report["missed_by_gene_ids_json"], [])
    was_picked = bool(report["was_picked"])
    candidate_rows = conn.execute(
        """
        SELECT * FROM candidate_scores
        WHERE trading_date = ? AND stock_code = ?
        ORDER BY total_score DESC
        """,
        (trading_date, stock_code),
    ).fetchall()
    was_candidate = bool(candidate_rows)
    candidate_score = float(candidate_rows[0]["total_score"]) if candidate_rows else None
    candidate_rank = best_candidate_rank(conn, trading_date, stock_code, affected_gene_ids)
    missed_stage, primary_reason = classify_miss(
        was_candidate=was_candidate,
        was_picked=was_picked,
        candidate_rank=candidate_rank,
        candidate_score=candidate_score,
        candidate_rows=candidate_rows,
    )
    evidence = {
        "blindspot_report_id": report["report_id"],
        "candidate_scores": [dict(row) for row in candidate_rows[:3]],
        "return_pct": float(report["return_pct"]),
    }
    blindspot_review_id = build_blindspot_review_id(trading_date, stock_code)
    conn.execute(
        """
        INSERT INTO blindspot_reviews(
          blindspot_review_id, trading_date, stock_code, rank, return_pct,
          industry, was_candidate, was_picked, candidate_rank, candidate_score,
          missed_stage, primary_reason, affected_gene_ids_json, evidence_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(trading_date, stock_code) DO UPDATE SET
          rank = excluded.rank,
          return_pct = excluded.return_pct,
          industry = excluded.industry,
          was_candidate = excluded.was_candidate,
          was_picked = excluded.was_picked,
          candidate_rank = excluded.candidate_rank,
          candidate_score = excluded.candidate_score,
          missed_stage = excluded.missed_stage,
          primary_reason = excluded.primary_reason,
          affected_gene_ids_json = excluded.affected_gene_ids_json,
          evidence_json = excluded.evidence_json
        """,
        (
            blindspot_review_id,
            trading_date,
            stock_code,
            int(report["rank"]),
            float(report["return_pct"]),
            report["industry"],
            int(was_candidate),
            int(was_picked),
            candidate_rank,
            candidate_score,
            missed_stage,
            primary_reason,
            repository.dumps(affected_gene_ids),
            repository.dumps(evidence),
        ),
    )
    if float(report["return_pct"]) > 0 and affected_gene_ids:
        error_type = error_for_missed_stage(missed_stage)
        upsert_review_error(
            conn,
            review_scope="blindspot",
            review_id=blindspot_review_id,
            error_type=error_type,
            severity=min(1.0, float(report["return_pct"]) * 5),
            confidence=0.68,
            evidence_ids=[report["report_id"]],
        )
        for gene_id in affected_gene_ids:
            signal_type, param_name, direction = signal_for_missed_stage(missed_stage)
            upsert_optimization_signal(
                conn,
                source_type="blindspot_review",
                source_id=blindspot_review_id,
                target_gene_id=gene_id,
                scope="gene",
                scope_key=gene_id,
                signal_type=signal_type,
                param_name=param_name,
                direction=direction,
                strength=min(1.0, float(report["return_pct"]) * 4),
                confidence=0.68,
                reason=f"{stock_code} blindspot missed at {missed_stage}",
                evidence_ids=[report["report_id"]],
            )
    return blindspot_review_id


def best_candidate_rank(conn: sqlite3.Connection, trading_date: str, stock_code: str, gene_ids: list[str]) -> int | None:
    ranks: list[int] = []
    for gene_id in gene_ids:
        rows = conn.execute(
            """
            SELECT stock_code
            FROM candidate_scores
            WHERE trading_date = ? AND strategy_gene_id = ?
            ORDER BY total_score DESC
            """,
            (trading_date, gene_id),
        ).fetchall()
        for index, row in enumerate(rows, start=1):
            if row["stock_code"] == stock_code:
                ranks.append(index)
                break
    return min(ranks) if ranks else None


def classify_miss(
    *,
    was_candidate: bool,
    was_picked: bool,
    candidate_rank: int | None,
    candidate_score: float | None,
    candidate_rows: list[sqlite3.Row],
) -> tuple[str, str]:
    if was_picked:
        return "strategy_scope", "picked by at least one strategy"
    if not was_candidate:
        return "candidate_scoring", "stock did not enter candidate_scores"
    if candidate_rows and max(float(row["risk_penalty"]) for row in candidate_rows) >= 0.45:
        return "risk_filter", "risk penalty pushed the stock below picks"
    if candidate_rank and candidate_rank > 4:
        return "max_picks_limit", "candidate ranked below max picks cutoff"
    if candidate_score is not None and candidate_score <= 0:
        return "candidate_scoring", "candidate score was not positive"
    return "max_picks_limit", "candidate was positive but not selected"


def error_for_missed_stage(stage: str) -> str:
    return {
        "candidate_scoring": "threshold_too_strict",
        "risk_filter": "risk_overestimated",
        "max_picks_limit": "threshold_too_strict",
        "hard_filter": "hard_filter_too_strict",
    }.get(stage, "candidate_not_recalled")


def signal_for_missed_stage(stage: str) -> tuple[str, str, str]:
    if stage == "risk_filter":
        return "decrease_weight", "risk_component_weight", "down"
    if stage == "candidate_scoring":
        return "lower_threshold", "min_score", "down"
    return "lower_threshold", "min_score", "down"


def build_blindspot_review_id(trading_date: str, stock_code: str) -> str:
    return "blindrev_" + hashlib.sha1(f"{trading_date}:{stock_code}".encode("utf-8")).hexdigest()[:12]

