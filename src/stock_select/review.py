from __future__ import annotations

import hashlib
import sqlite3
from typing import Any

from . import repository
from .blindspot_review import run_blindspot_review
from .contracts import ReviewContract
from .deterministic_review import run_deterministic_review
from .gene_review import run_gene_reviews_for_date
from .memory import add_memory
from .review_analysts import run_analyst_reviews
from .system_review import run_system_review


def generate_deterministic_reviews(conn: sqlite3.Connection, trading_date: str) -> list[str]:
    """Generate deterministic review records and legacy summaries without API keys."""
    review_ids = run_deterministic_review(conn, trading_date)
    rows = conn.execute(
        """
        SELECT p.*, o.entry_price, o.close_price, o.return_pct,
               o.max_drawdown_intraday_pct, o.hit_sell_rule
        FROM pick_decisions p
        JOIN outcomes o ON o.decision_id = p.decision_id
        WHERE p.trading_date = ?
        ORDER BY p.strategy_gene_id, p.score DESC
        """,
        (trading_date,),
    ).fetchall()

    legacy_ids: list[str] = []
    for row in rows:
        review = ReviewContract.validate(build_review_payload(row))
        review_id = build_review_id(review.decision_id)
        summary = summarize_review(row, review)
        conn.execute(
            """
            INSERT INTO review_logs(
              review_id, decision_id, trading_date, strategy_gene_id,
              fact_json, inference_json, ambiguity_json, summary
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(review_id) DO UPDATE SET
              fact_json = excluded.fact_json,
              inference_json = excluded.inference_json,
              ambiguity_json = excluded.ambiguity_json,
              summary = excluded.summary
            """,
            (
                review_id,
                review.decision_id,
                trading_date,
                row["strategy_gene_id"],
                repository.dumps(review.outcome),
                repository.dumps(review.attribution),
                repository.dumps(review.reason_check["missing_signals"]),
                summary,
            ),
        )
        add_memory(
            conn,
            content=summary,
            trading_date=trading_date,
            source_type="review",
            source_id=review_id,
        )
        legacy_ids.append(review_id)
    conn.commit()
    run_blindspot_review(conn, trading_date)
    run_gene_reviews_for_date(conn, trading_date)
    run_system_review(conn, trading_date)
    run_analyst_reviews(conn, trading_date)
    return review_ids


def build_review_payload(row: sqlite3.Row) -> dict[str, Any]:
    return_pct = float(row["return_pct"])
    return {
        "decision_id": row["decision_id"],
        "outcome": {
            "entry_price": float(row["entry_price"]),
            "close_price": float(row["close_price"]),
            "return_pct": return_pct,
            "max_drawdown_intraday_pct": float(row["max_drawdown_intraday_pct"]),
            "hit_sell_rule": row["hit_sell_rule"],
        },
        "reason_check": {
            "what_was_right": ["positive realized return"] if return_pct > 0 else [],
            "what_was_wrong": ["negative realized return"] if return_pct <= 0 else [],
            "missing_signals": ["LLM attribution not enabled"],
        },
        "attribution": [
            {
                "event": "price action",
                "confidence": "EXTRACTED",
                "evidence": [{"type": "outcome", "decision_id": row["decision_id"]}],
            }
        ],
        "gene_update_signal": {
            "score_delta": return_pct,
            "should_mutate_parameters": [],
        },
        "evidence": [{"type": "daily_price", "stock_code": row["stock_code"], "date": row["trading_date"]}],
    }


def summarize_review(row: sqlite3.Row, review: ReviewContract) -> str:
    return (
        f"{row['trading_date']} {row['strategy_gene_id']} picked {row['stock_code']}; "
        f"return {review.outcome['return_pct']:.2%}, "
        f"drawdown {review.outcome['max_drawdown_intraday_pct']:.2%}, "
        f"exit {review.outcome.get('hit_sell_rule') or 'close'}."
    )


def build_review_id(decision_id: str) -> str:
    return "review_" + hashlib.sha1(decision_id.encode("utf-8")).hexdigest()[:12]
