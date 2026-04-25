from __future__ import annotations

import hashlib
import sqlite3
from collections import defaultdict
from typing import Any

from . import repository
from .review_schema import OptimizationSignalContract


def signal_id_for(
    *,
    source_type: str,
    source_id: str,
    target_gene_id: str | None,
    signal_type: str,
    param_name: str | None,
    direction: str,
    scope: str,
    scope_key: str | None,
) -> str:
    raw = repository.dumps(
        {
            "source_type": source_type,
            "source_id": source_id,
            "target_gene_id": target_gene_id,
            "signal_type": signal_type,
            "param_name": param_name,
            "direction": direction,
            "scope": scope,
            "scope_key": scope_key,
        }
    )
    return "sig_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14]


def upsert_optimization_signal(
    conn: sqlite3.Connection,
    *,
    source_type: str,
    source_id: str,
    target_gene_id: str | None,
    scope: str,
    scope_key: str | None = None,
    signal_type: str,
    param_name: str | None,
    direction: str,
    strength: float,
    confidence: float,
    sample_size: int = 1,
    status: str = "open",
    reason: str,
    evidence_ids: list[str],
) -> str:
    param_name = param_name or ""
    scope_key = scope_key or ""
    OptimizationSignalContract.validate(
        {
            "signal_type": signal_type,
            "direction": direction,
            "scope": scope,
            "strength": strength,
            "confidence": confidence,
        }
    )
    signal_id = signal_id_for(
        source_type=source_type,
        source_id=source_id,
        target_gene_id=target_gene_id,
        signal_type=signal_type,
        param_name=param_name,
        direction=direction,
        scope=scope,
        scope_key=scope_key,
    )
    conn.execute(
        """
        INSERT INTO optimization_signals(
          signal_id, source_type, source_id, target_gene_id, scope, scope_key,
          signal_type, param_name, direction, strength, confidence, sample_size,
          status, reason, evidence_ids_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_type, source_id, target_gene_id, signal_type, param_name, direction, scope, scope_key)
        DO UPDATE SET
          strength = excluded.strength,
          confidence = excluded.confidence,
          sample_size = excluded.sample_size,
          status = CASE
            WHEN optimization_signals.status = 'consumed' THEN optimization_signals.status
            ELSE excluded.status
          END,
          reason = excluded.reason,
          evidence_ids_json = excluded.evidence_ids_json
        """,
        (
            signal_id,
            source_type,
            source_id,
            target_gene_id,
            scope,
            scope_key,
            signal_type,
            param_name,
            direction,
            float(strength),
            float(confidence),
            int(sample_size),
            status,
            reason,
            repository.dumps(evidence_ids),
        ),
    )
    return signal_id


def list_optimization_signals(
    conn: sqlite3.Connection,
    *,
    gene_id: str | None = None,
    status: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if gene_id:
        clauses.append("target_gene_id = ?")
        params.append(gene_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"""
        SELECT * FROM optimization_signals
        {where}
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def aggregate_optimization_signals(
    conn: sqlite3.Connection,
    *,
    gene_id: str,
    period_start: str,
    period_end: str,
    min_signal_samples: int = 5,
    min_confidence: float = 0.65,
    min_distinct_dates: int = 3,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM optimization_signals
        WHERE status = 'open'
          AND target_gene_id = ?
        ORDER BY created_at
        """,
        (gene_id,),
    ).fetchall()
    grouped: dict[tuple[Any, ...], list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        trading_date = signal_trading_date(conn, row)
        if trading_date and not (period_start <= trading_date <= period_end):
            continue
        key = (row["signal_type"], row["param_name"], row["direction"], row["scope"], row["scope_key"])
        grouped[key].append(row)

    aggregates: list[dict[str, Any]] = []
    for key, items in grouped.items():
        dates = {signal_trading_date(conn, item) for item in items}
        dates.discard(None)
        sample_size = sum(int(item["sample_size"] or 1) for item in items)
        confidence = mean([float(item["confidence"]) for item in items])
        if sample_size < min_signal_samples or confidence < min_confidence or len(dates) < min_distinct_dates:
            continue
        strength = mean([float(item["strength"]) for item in items])
        aggregates.append(
            {
                "signal_type": key[0],
                "param_name": key[1],
                "direction": key[2],
                "scope": key[3],
                "scope_key": key[4],
                "sample_size": sample_size,
                "avg_confidence": confidence,
                "weighted_strength": strength,
                "distinct_dates": sorted(dates),
                "signal_ids": [item["signal_id"] for item in items],
                "evidence_ids": flatten([repository.loads(item["evidence_ids_json"], []) for item in items]),
            }
        )
    return aggregates


def consume_signals(conn: sqlite3.Connection, signal_ids: list[str]) -> None:
    if not signal_ids:
        return
    placeholders = ",".join("?" for _ in signal_ids)
    conn.execute(
        f"""
        UPDATE optimization_signals
        SET status = 'consumed', consumed_at = CURRENT_TIMESTAMP
        WHERE signal_id IN ({placeholders})
        """,
        signal_ids,
    )


def signal_trading_date(conn: sqlite3.Connection, row: sqlite3.Row) -> str | None:
    source_type = row["source_type"]
    source_id = row["source_id"]
    if source_type == "decision_review":
        result = conn.execute("SELECT trading_date FROM decision_reviews WHERE review_id = ?", (source_id,)).fetchone()
    elif source_type == "blindspot_review":
        result = conn.execute("SELECT trading_date FROM blindspot_reviews WHERE blindspot_review_id = ?", (source_id,)).fetchone()
    elif source_type == "gene_review":
        result = conn.execute("SELECT period_end AS trading_date FROM gene_reviews WHERE gene_review_id = ?", (source_id,)).fetchone()
    elif source_type == "system_review":
        result = conn.execute("SELECT trading_date FROM system_reviews WHERE system_review_id = ?", (source_id,)).fetchone()
    else:
        result = None
    return result["trading_date"] if result else None


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def flatten(values: list[Any]) -> list[Any]:
    output: list[Any] = []
    for value in values:
        if isinstance(value, list):
            output.extend(value)
        else:
            output.append(value)
    return output
