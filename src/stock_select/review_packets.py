from __future__ import annotations

import sqlite3
from typing import Any

from . import repository


def stock_review(conn: sqlite3.Connection, stock_code: str, trading_date: str, gene_id: str | None = None) -> dict[str, Any]:
    stock = conn.execute("SELECT * FROM stocks WHERE stock_code = ?", (stock_code,)).fetchone()
    clauses = ["d.stock_code = ?", "d.trading_date = ?"]
    params: list[Any] = [stock_code, trading_date]
    if gene_id:
        clauses.append("d.strategy_gene_id = ?")
        params.append(gene_id)
    decision_rows = conn.execute(
        f"""
        SELECT d.*, p.score, p.confidence, p.position_pct, o.entry_price,
               o.close_price, o.return_pct AS outcome_return_pct
        FROM decision_reviews d
        JOIN pick_decisions p ON p.decision_id = d.decision_id
        LEFT JOIN outcomes o ON o.decision_id = d.decision_id
        WHERE {' AND '.join(clauses)}
        ORDER BY d.strategy_gene_id
        """,
        params,
    ).fetchall()
    decisions = [decision_review_detail(conn, row["review_id"]) for row in decision_rows]
    blindspot = conn.execute(
        "SELECT * FROM blindspot_reviews WHERE trading_date = ? AND stock_code = ?",
        (trading_date, stock_code),
    ).fetchone()
    return {
        "stock": dict(stock) if stock else {"stock_code": stock_code},
        "trading_date": trading_date,
        "decisions": decisions,
        "blindspot": dict(blindspot) if blindspot else None,
        "domain_facts": domain_facts(conn, stock_code, trading_date),
    }


def stock_review_history(
    conn: sqlite3.Connection,
    stock_code: str,
    start: str,
    end: str,
    gene_id: str | None = None,
) -> dict[str, Any]:
    clauses = ["stock_code = ?", "trading_date BETWEEN ? AND ?"]
    params: list[Any] = [stock_code, start, end]
    if gene_id:
        clauses.append("strategy_gene_id = ?")
        params.append(gene_id)
    rows = repository.rows_to_dicts(
        conn.execute(
            f"""
            SELECT review_id, decision_id, trading_date, strategy_gene_id, verdict,
                   primary_driver, return_pct, relative_return_pct, summary
            FROM decision_reviews
            WHERE {' AND '.join(clauses)}
            ORDER BY trading_date DESC, strategy_gene_id
            """,
            params,
        )
    )
    return {
        "stock_code": stock_code,
        "start": start,
        "end": end,
        "reviews": rows,
        "summary": {
            "review_count": len(rows),
            "avg_return_pct": mean([float(row["return_pct"]) for row in rows]),
        },
    }


def decision_review_detail(conn: sqlite3.Connection, review_id: str) -> dict[str, Any]:
    review = conn.execute("SELECT * FROM decision_reviews WHERE review_id = ?", (review_id,)).fetchone()
    if review is None:
        raise KeyError(f"Unknown review_id: {review_id}")
    factors = repository.rows_to_dicts(
        conn.execute(
            "SELECT * FROM factor_review_items WHERE review_id = ? ORDER BY factor_type",
            (review_id,),
        )
    )
    errors = repository.rows_to_dicts(
        conn.execute(
            "SELECT * FROM review_errors WHERE review_scope = 'decision' AND review_id = ? ORDER BY severity DESC",
            (review_id,),
        )
    )
    evidence = repository.rows_to_dicts(
        conn.execute(
            "SELECT * FROM review_evidence WHERE review_id = ? ORDER BY source_type",
            (review_id,),
        )
    )
    signals = repository.rows_to_dicts(
        conn.execute(
            "SELECT * FROM optimization_signals WHERE source_type = 'decision_review' AND source_id = ? ORDER BY created_at",
            (review_id,),
        )
    )
    return dict(review) | {
        "factor_items": factors,
        "errors": errors,
        "evidence": evidence,
        "optimization_signals": signals,
    }


def domain_facts(conn: sqlite3.Connection, stock_code: str, trading_date: str) -> dict[str, list[dict[str, Any]]]:
    return {
        "earnings_surprises": repository.rows_to_dicts(
            conn.execute(
                "SELECT * FROM earnings_surprises WHERE stock_code = ? AND ann_date <= ? ORDER BY ann_date DESC",
                (stock_code, trading_date),
            )
        ),
        "financial_actuals": repository.rows_to_dicts(
            conn.execute(
                "SELECT * FROM financial_actuals WHERE stock_code = ? AND ann_date <= ? ORDER BY ann_date DESC",
                (stock_code, trading_date),
            )
        ),
        "order_contract_events": repository.rows_to_dicts(
            conn.execute(
                "SELECT * FROM order_contract_events WHERE stock_code = ? AND ann_date <= ? ORDER BY ann_date DESC",
                (stock_code, trading_date),
            )
        ),
        "business_kpi_actuals": repository.rows_to_dicts(
            conn.execute(
                "SELECT * FROM business_kpi_actuals WHERE stock_code = ? ORDER BY period DESC",
                (stock_code,),
            )
        ),
        "risk_events": repository.rows_to_dicts(
            conn.execute(
                "SELECT * FROM event_signals WHERE stock_code = ? AND event_type IN ('risk', 'penalty', 'investigation') AND trading_date <= ? ORDER BY published_at DESC",
                (stock_code, trading_date),
            )
        ),
    }


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0

