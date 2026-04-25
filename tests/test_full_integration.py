"""Phase Z1: Full integration test exercising the entire system."""
from __future__ import annotations

import os
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stock_select.agent_runtime import run_daily_pipeline, run_phase
from stock_select.analyst import run_analysis
from stock_select.data_ingestion import DemoProvider
from stock_select.db import connect, init_db
from stock_select.deterministic_review import run_deterministic_review
from stock_select.evolution import evolve_weekly
from stock_select.pick_evaluator import run_evaluation
from stock_select.planner import plan_preopen_focus
from stock_select.seed import seed_demo_data
from stock_select.similar_cases import find_similar_cases, query_gene_history


class FullIntegrationTest(unittest.TestCase):
    """End-to-end test: full daily pipeline + analysis + evolution."""

    def setUp(self) -> None:
        self.conn = connect(":memory:")
        init_db(self.conn)
        seed_demo_data(self.conn)
        self.trading_date = "2026-01-13"
        self.providers = [
            DemoProvider("akshare"),
            DemoProvider("baostock", close_adjustment=0.0005),
        ]

    def tearDown(self) -> None:
        self.conn.close()

    def test_full_daily_pipeline(self) -> None:
        """Complete daily pipeline: sync -> pick -> simulate -> review."""
        results = run_daily_pipeline(self.conn, self.trading_date, providers=self.providers)

        self.assertEqual(len(results), 4)
        phases = [r["phase"] for r in results]
        self.assertEqual(phases, ["sync_data", "preopen_pick", "simulate", "review"])

    def test_pipeline_creates_pick_decisions(self) -> None:
        """After pipeline, pick_decisions table should have records."""
        run_daily_pipeline(self.conn, self.trading_date, providers=self.providers)

        picks = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM pick_decisions WHERE trading_date = ?",
            (self.trading_date,),
        ).fetchone()["cnt"]
        self.assertGreater(picks, 0)

    def test_pipeline_creates_outcomes(self) -> None:
        """After pipeline, outcomes should be linked to picks."""
        run_daily_pipeline(self.conn, self.trading_date, providers=self.providers)

        outcomes = self.conn.execute(
            """
            SELECT COUNT(*) as cnt FROM outcomes o
            JOIN pick_decisions p ON o.decision_id = p.decision_id
            WHERE p.trading_date = ?
            """,
            (self.trading_date,),
        ).fetchone()["cnt"]
        self.assertGreater(outcomes, 0)

    def test_pipeline_creates_reviews(self) -> None:
        """After pipeline, decision_reviews should exist."""
        run_daily_pipeline(self.conn, self.trading_date, providers=self.providers)

        reviews = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM decision_reviews WHERE trading_date = ?",
            (self.trading_date,),
        ).fetchone()["cnt"]
        self.assertGreater(reviews, 0)

    def test_deterministic_review_runs(self) -> None:
        """Deterministic review should produce review records."""
        run_daily_pipeline(self.conn, self.trading_date, providers=self.providers)

        review_ids = run_deterministic_review(self.conn, self.trading_date)
        self.assertIsInstance(review_ids, list)

    def test_planner_returns_plan(self) -> None:
        """Planner should return a plan with focus sectors."""
        # Run pipeline first to populate sector data
        run_daily_pipeline(self.conn, self.trading_date, providers=self.providers)

        plan = plan_preopen_focus(self.conn, self.trading_date)
        self.assertEqual(plan["trading_date"], self.trading_date)
        self.assertIsInstance(plan["focus_sectors"], list)
        self.assertIsInstance(plan["watch_risks"], list)

    def test_analyst_runs_without_llm(self) -> None:
        """Analyst should work without LLM API key."""
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("CLAUDE_API_KEY", None)

        run_daily_pipeline(self.conn, self.trading_date, providers=self.providers)

        result = run_analysis(self.conn, self.trading_date)
        self.assertEqual(result["trading_date"], self.trading_date)
        self.assertIsInstance(result["industry_signals"], list)

    def test_pick_evaluator_runs_without_llm(self) -> None:
        """Pick evaluator should work without LLM API key."""
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("CLAUDE_API_KEY", None)

        run_daily_pipeline(self.conn, self.trading_date, providers=self.providers)

        result = run_evaluation(self.conn, self.trading_date)
        self.assertEqual(result["trading_date"], self.trading_date)
        self.assertIsInstance(result["top_picks"], list)

    def test_similar_cases_query(self) -> None:
        """Similar case query should work after pipeline produces reviews."""
        run_daily_pipeline(self.conn, self.trading_date, providers=self.providers)

        cases = find_similar_cases(self.conn, gene_id="gene_aggressive_v1")
        self.assertIsInstance(cases, list)

    def test_gene_history_query(self) -> None:
        """Gene history query should return structured data."""
        run_daily_pipeline(self.conn, self.trading_date, providers=self.providers)

        history = query_gene_history(self.conn, gene_id="gene_aggressive_v1")
        self.assertEqual(history["gene_id"], "gene_aggressive_v1")
        self.assertIsInstance(history["reviews"], list)

    def test_evolution_runs(self) -> None:
        """Weekly evolution should execute without error."""
        run_daily_pipeline(self.conn, self.trading_date, providers=self.providers)

        result = evolve_weekly(self.conn, period_start="2026-01-12", period_end="2026-01-16")
        self.assertIsInstance(result, dict)

    def test_multi_day_pipeline(self) -> None:
        """Running on two consecutive days should produce data for both."""
        for day in ["2026-01-13", "2026-01-14"]:
            run_daily_pipeline(self.conn, day, providers=self.providers)

        total_picks = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM pick_decisions WHERE trading_date IN ('2026-01-13', '2026-01-14')"
        ).fetchone()["cnt"]
        self.assertGreater(total_picks, 0)

    def test_idempotent_rerun_same_day(self) -> None:
        """Rerunning pipeline on same day should not duplicate records."""
        run_daily_pipeline(self.conn, self.trading_date, providers=self.providers)
        first_count = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM pick_decisions WHERE trading_date = ?",
            (self.trading_date,),
        ).fetchone()["cnt"]

        run_daily_pipeline(self.conn, self.trading_date, providers=self.providers)
        second_count = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM pick_decisions WHERE trading_date = ?",
            (self.trading_date,),
        ).fetchone()["cnt"]

        self.assertEqual(first_count, second_count)

    def test_research_runs_recorded(self) -> None:
        """All phases should have research_run records."""
        run_daily_pipeline(self.conn, self.trading_date, providers=self.providers)

        runs = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM research_runs WHERE trading_date = ?",
            (self.trading_date,),
        ).fetchone()["cnt"]
        self.assertEqual(runs, 4)

        statuses = {
            row["phase"]: row["status"]
            for row in self.conn.execute(
                "SELECT phase, status FROM research_runs WHERE trading_date = ?",
                (self.trading_date,),
            )
        }
        for phase in ["sync_data", "preopen_pick", "simulate", "review"]:
            self.assertEqual(statuses.get(phase), "ok")

    def test_phase_by_phase_execution(self) -> None:
        """Individual phases can be run separately via run_phase."""
        # First run full pipeline to populate data, then test individual phases
        run_daily_pipeline(self.conn, self.trading_date, providers=self.providers)

        # Test phases that work with existing data
        for phase in ["preopen_pick", "simulate", "deterministic_review"]:
            result = run_phase(self.conn, phase, self.trading_date)
            self.assertIn("run_id", result)
            self.assertEqual(result["phase"], phase)


if __name__ == "__main__":
    unittest.main()
