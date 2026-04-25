"""Tests for similar case queries."""
from __future__ import annotations

import sqlite3
import pytest

from stock_select.db import connect, init_db
from stock_select.seed import seed_demo_data
from stock_select.similar_cases import find_similar_cases, query_similar_by_error, query_gene_history


@pytest.fixture()
def demo_db(tmp_path):
    conn = connect(tmp_path / "demo.db")
    init_db(conn)
    seed_demo_data(conn)
    return conn


@pytest.fixture()
def reviewed_db(demo_db):
    """Add review decisions for testing."""
    conn = demo_db
    for i, (stock, gene) in enumerate([
        ("300750.SZ", "gene_aggressive_v1"),
        ("600519.SH", "gene_balanced_v1"),
        ("000002.SZ", "gene_conservative_v1"),
    ]):
        conn.execute(
            """
            INSERT INTO pick_decisions(
                decision_id, trading_date, horizon, strategy_gene_id, stock_code,
                action, confidence, position_pct, score, entry_plan_json,
                sell_rules_json, thesis_json, risks_json, invalid_if_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', '{}', '{}', '{}', '{}')
            """,
            (f"pick_sim_{i}", "2026-01-12", "short", gene, stock,
             "BUY", 0.7, 0.05, 0.6),
        )
        conn.execute(
            """
            INSERT INTO decision_reviews(
                review_id, decision_id, trading_date, strategy_gene_id, stock_code,
                verdict, primary_driver, return_pct, relative_return_pct,
                max_drawdown_intraday_pct, thesis_quality_score, evidence_quality_score,
                deterministic_json, summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.5, 0.5, '{}', ?)
            """,
            (f"review_sim_{i}", f"pick_sim_{i}", "2026-01-12", gene, stock,
             "RIGHT", "technical", 0.03, 0.02, -0.01, "Good pick"),
        )
    conn.execute(
        """
        INSERT INTO review_errors(error_id, review_scope, review_id, error_type, severity, confidence, evidence_ids_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("err_sim_0", "decision", "review_sim_0", "overweighted_technical", 0.5, 0.7, '[]'),
    )
    conn.commit()
    return conn


class TestFindSimilarCases:
    def test_returns_all_cases_without_filters(self, reviewed_db):
        cases = find_similar_cases(reviewed_db)
        assert len(cases) == 3

    def test_filters_by_gene(self, reviewed_db):
        cases = find_similar_cases(reviewed_db, gene_id="gene_aggressive_v1")
        assert len(cases) == 1
        assert cases[0]["strategy_gene_id"] == "gene_aggressive_v1"

    def test_filters_by_industry(self, reviewed_db):
        # 300750.SZ is in Battery industry
        cases = find_similar_cases(reviewed_db, industry="Battery")
        assert len(cases) >= 1

    def test_respects_limit(self, reviewed_db):
        cases = find_similar_cases(reviewed_db, limit=2)
        assert len(cases) <= 2

    def test_returns_empty_on_no_match(self, reviewed_db):
        cases = find_similar_cases(reviewed_db, gene_id="nonexistent_gene")
        assert cases == []


class TestQuerySimilarByError:
    def test_finds_cases_with_error(self, reviewed_db):
        errors = query_similar_by_error(reviewed_db, "overweighted_technical")
        assert len(errors) >= 1

    def test_returns_empty_on_unknown_error(self, reviewed_db):
        errors = query_similar_by_error(reviewed_db, "nonexistent_error")
        assert errors == []


class TestQueryGeneHistory:
    def test_returns_reviews_for_gene(self, reviewed_db):
        history = query_gene_history(reviewed_db, "gene_aggressive_v1")
        assert len(history["reviews"]) >= 1

    def test_returns_empty_for_unknown_gene(self, reviewed_db):
        history = query_gene_history(reviewed_db, "unknown_gene")
        assert history["reviews"] == []
        assert history["gene_id"] == "unknown_gene"
