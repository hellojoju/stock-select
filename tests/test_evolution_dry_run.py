from __future__ import annotations

import sqlite3

from stock_select import repository
from stock_select.db import init_db
from stock_select.deterministic_review import review_decision
from stock_select.evolution import evolution_comparison, propose_strategy_evolution
from stock_select.optimization_signals import list_optimization_signals, upsert_optimization_signal
from stock_select.seed import seed_demo_data
from stock_select.simulator import simulate_day
from stock_select.strategies import generate_picks_for_gene


def prepare_reviewed_signal_db() -> tuple[sqlite3.Connection, str]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_db(conn)
    seed_demo_data(conn)
    decision_ids = generate_picks_for_gene(conn, "2026-01-12", "gene_aggressive_v1")
    simulate_day(conn, "2026-01-12")
    review_id = review_decision(conn, decision_ids[0])
    upsert_optimization_signal(
        conn,
        source_type="decision_review",
        source_id=review_id,
        target_gene_id="gene_aggressive_v1",
        scope="gene",
        scope_key="gene_aggressive_v1",
        signal_type="increase_order_event_weight",
        param_name="order_event_weight",
        direction="up",
        strength=0.8,
        confidence=0.85,
        reason="evidence-backed order signal",
        evidence_ids=[review_id],
    )
    conn.commit()
    return conn, review_id


def test_evolution_dry_run_does_not_mutate_db() -> None:
    conn, _ = prepare_reviewed_signal_db()
    try:
        before_genes = conn.execute("SELECT COUNT(*) AS c FROM strategy_genes").fetchone()["c"]
        before_events = conn.execute("SELECT COUNT(*) AS c FROM strategy_evolution_events").fetchone()["c"]
        result = propose_strategy_evolution(
            conn,
            period_start="2026-01-12",
            period_end="2026-01-12",
            gene_id="gene_aggressive_v1",
            min_trades=1,
            min_signal_samples=1,
            min_signal_dates=1,
            dry_run=True,
        )

        assert result["status"] == "dry_run"
        assert result["proposals"][0]["dry_run"] is True
        assert conn.execute("SELECT COUNT(*) AS c FROM strategy_genes").fetchone()["c"] == before_genes
        assert conn.execute("SELECT COUNT(*) AS c FROM strategy_evolution_events").fetchone()["c"] == before_events
        assert len(list_optimization_signals(conn, gene_id="gene_aggressive_v1", status="open")) >= 1
        proposal = result["proposals"][0]
        assert proposal["before_params"]["event_component_weight"] != proposal["after_params"]["event_component_weight"]
    finally:
        conn.close()


def test_evolution_apply_consumes_signals_and_comparison_reports_diff() -> None:
    conn, _ = prepare_reviewed_signal_db()
    try:
        result = propose_strategy_evolution(
            conn,
            period_start="2026-01-12",
            period_end="2026-01-12",
            gene_id="gene_aggressive_v1",
            min_trades=1,
            min_signal_samples=1,
            min_signal_dates=1,
        )

        assert result["status"] == "proposed"
        child_gene_id = result["proposals"][0]["child_gene_id"]
        child = repository.get_gene(conn, child_gene_id)
        assert child["status"] == "observing"
        assert len(list_optimization_signals(conn, gene_id="gene_aggressive_v1", status="consumed")) >= 1

        comparison = evolution_comparison(
            conn,
            gene_id="gene_aggressive_v1",
            start="2026-01-12",
            end="2026-01-12",
        )
        assert len(comparison["comparisons"]) == 1
        item = comparison["comparisons"][0]
        assert item["parent_gene_id"] == "gene_aggressive_v1"
        assert item["child_gene_id"] == child_gene_id
        assert item["parameter_diff"]
        assert "parent_performance" in item
        assert "child_performance" in item
    finally:
        conn.close()
