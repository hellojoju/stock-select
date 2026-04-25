"""Query similar historical cases using review data."""
from __future__ import annotations

import sqlite3
from typing import Any


def find_similar_cases(
    conn: sqlite3.Connection,
    *,
    gene_id: str | None = None,
    market_environment: str | None = None,
    industry: str | None = None,
    verdict: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Find similar historical review cases by filtering decision reviews."""
    conditions: list[str] = []
    params: list[Any] = []

    if gene_id:
        conditions.append("strategy_gene_id = ?")
        params.append(gene_id)

    if industry:
        conditions.append("stock_code IN (SELECT stock_code FROM stocks WHERE industry = ?)")
        params.append(industry)

    if verdict:
        conditions.append("verdict = ?")
        params.append(verdict)

    # market_environment: filter via trading_days if available
    if market_environment and market_environment != "all":
        conditions.append("trading_date IN (SELECT trading_date FROM market_environments WHERE environment = ?)")
        params.append(market_environment)

    query = "SELECT * FROM decision_reviews WHERE 1=1"
    if conditions:
        query += " AND " + " AND ".join(conditions)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def query_similar_by_error(
    conn: sqlite3.Connection,
    error_type: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Find decisions that had the same error type."""
    rows = conn.execute(
        """
        SELECT dr.*, re.error_type, re.severity
        FROM decision_reviews dr
        JOIN review_errors re ON re.review_id = dr.review_id
        WHERE re.error_type = ?
        ORDER BY dr.created_at DESC
        LIMIT ?
        """,
        (error_type, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def query_gene_history(
    conn: sqlite3.Connection,
    gene_id: str,
    market_environment: str = "all",
) -> dict[str, Any]:
    """Query a gene's historical review performance."""
    reviews = conn.execute(
        """
        SELECT * FROM decision_reviews
        WHERE strategy_gene_id = ?
        ORDER BY trading_date DESC
        LIMIT 20
        """,
        (gene_id,),
    ).fetchall()

    evolution = conn.execute(
        """
        SELECT * FROM strategy_evolution_events
        WHERE parent_gene_id = ? OR child_gene_id = ?
        ORDER BY created_at DESC
        LIMIT 5
        """,
        (gene_id, gene_id),
    ).fetchall()

    return {
        "gene_id": gene_id,
        "market_environment": market_environment,
        "reviews": [dict(r) for r in reviews],
        "evolution_events": [dict(e) for e in evolution],
    }
