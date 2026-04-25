from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stock_select.agent_runtime import run_daily_pipeline
from stock_select.data_ingestion import DemoProvider
from stock_select.db import connect, init_db
from stock_select.seed import seed_demo_data


class PipelineIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = connect(":memory:")
        init_db(self.conn)
        seed_demo_data(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_full_pipeline_with_demo_provider(self) -> None:
        """Run the full daily pipeline with DemoProvider and verify all stages execute."""
        providers = [DemoProvider("akshare"), DemoProvider("baostock", close_adjustment=0.0005)]
        results = run_daily_pipeline(self.conn, "2026-01-13", providers=providers)

        # Verify it returns a list of phase results
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 4)

        # Verify all expected phases ran in order
        phases = [item["phase"] for item in results]
        self.assertEqual(phases, ["sync_data", "preopen_pick", "simulate", "review"])

        # Verify each phase result has the expected structure
        for item in results:
            self.assertIn("run_id", item)
            self.assertIn("phase", item)
            self.assertIn("trading_date", item)
            self.assertIn("result", item)

    def test_pipeline_produces_picks(self) -> None:
        """Verify the pipeline generates pick decisions."""
        providers = [DemoProvider("akshare"), DemoProvider("baostock", close_adjustment=0.0005)]
        run_daily_pipeline(self.conn, "2026-01-13", providers=providers)

        picks = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM pick_decisions WHERE trading_date = '2026-01-13'"
        ).fetchone()["cnt"]
        self.assertGreater(picks, 0, "Expected at least one pick decision for the trading date")

    def test_pipeline_produces_outcomes(self) -> None:
        """Verify the simulation stage produces outcomes linked to picks."""
        providers = [DemoProvider("akshare"), DemoProvider("baostock", close_adjustment=0.0005)]
        run_daily_pipeline(self.conn, "2026-01-13", providers=providers)

        outcomes = self.conn.execute(
            """
            SELECT COUNT(*) as cnt FROM outcomes o
            JOIN pick_decisions p ON o.decision_id = p.decision_id
            WHERE p.trading_date = '2026-01-13'
            """
        ).fetchone()["cnt"]
        self.assertGreater(outcomes, 0, "Expected at least one outcome from simulation")

    def test_pipeline_produces_reviews(self) -> None:
        """Verify the review stage produces decision reviews and review logs."""
        providers = [DemoProvider("akshare"), DemoProvider("baostock", close_adjustment=0.0005)]
        run_daily_pipeline(self.conn, "2026-01-13", providers=providers)

        reviews = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM decision_reviews WHERE trading_date = '2026-01-13'"
        ).fetchone()["cnt"]
        self.assertGreater(reviews, 0, "Expected at least one decision review")

        review_logs = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM review_logs WHERE trading_date = '2026-01-13'"
        ).fetchone()["cnt"]
        self.assertGreater(review_logs, 0, "Expected at least one review log entry")

    def test_pipeline_produces_sim_orders(self) -> None:
        """Verify the simulation stage creates orders."""
        providers = [DemoProvider("akshare"), DemoProvider("baostock", close_adjustment=0.0005)]
        run_daily_pipeline(self.conn, "2026-01-13", providers=providers)

        orders = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM sim_orders WHERE trading_date = '2026-01-13'"
        ).fetchone()["cnt"]
        self.assertGreater(orders, 0, "Expected at least one simulated order")

    def test_pipeline_idempotent_rerun(self) -> None:
        """Verify rerunning the pipeline on the same date does not duplicate records."""
        providers = [DemoProvider("akshare"), DemoProvider("baostock", close_adjustment=0.0005)]

        run_daily_pipeline(self.conn, "2026-01-13", providers=providers)
        first_picks = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM pick_decisions WHERE trading_date = '2026-01-13'"
        ).fetchone()["cnt"]

        run_daily_pipeline(self.conn, "2026-01-13", providers=providers)
        second_picks = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM pick_decisions WHERE trading_date = '2026-01-13'"
        ).fetchone()["cnt"]

        self.assertEqual(first_picks, second_picks, "Rerunning pipeline should not duplicate picks")

    def test_pipeline_records_research_runs(self) -> None:
        """Verify each phase creates a research_run record."""
        providers = [DemoProvider("akshare"), DemoProvider("baostock", close_adjustment=0.0005)]
        run_daily_pipeline(self.conn, "2026-01-13", providers=providers)

        runs = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM research_runs WHERE trading_date = '2026-01-13'"
        ).fetchone()["cnt"]
        self.assertEqual(runs, 4, "Expected 4 research runs (one per phase)")

        statuses = {
            row["phase"]: row["status"]
            for row in self.conn.execute(
                "SELECT phase, status FROM research_runs WHERE trading_date = '2026-01-13'"
            )
        }
        for phase in ["sync_data", "preopen_pick", "simulate", "review"]:
            self.assertEqual(statuses.get(phase), "ok", f"Phase {phase} should have status 'ok'")

    def test_pipeline_without_providers_raises(self) -> None:
        """Verify pipeline without providers on an empty DB fails at sync_data."""
        conn = connect(":memory:")
        init_db(conn)
        try:
            with self.assertRaises(Exception):
                run_daily_pipeline(conn, "2026-01-13")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
