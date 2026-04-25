from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stock_select import repository
from stock_select.agent_runtime import run_daily_pipeline
from stock_select.candidate_pipeline import rank_candidates_for_gene
from stock_select.contracts import ContractError, PickContract, ReviewContract
from stock_select.data_ingestion import (
    AkShareProvider,
    DemoProvider,
    backfill_daily_prices_range,
    classify_market_environment,
    classify_event_title,
    conservative_visible_date,
    filter_known_active_stock_codes,
    is_a_share_stock_code,
    open_trading_dates,
    publish_canonical_prices,
    sync_factors,
    sync_fundamentals,
    sync_sector_signals,
    sync_daily_prices,
    sync_daily_sources,
    sync_index_prices,
    sync_stock_universe,
    sync_trading_calendar,
)
from stock_select.data_status import data_quality_summary, data_source_status
from stock_select.data_quality import compare_and_publish_prices
from stock_select.db import connect, init_db
from stock_select.evolution import evolve_weekly, propose_strategy_evolution, rollback_evolution, score_genes
from stock_select.graph import query_graph, sync_decision_graph
from stock_select.memory import search_memory
from stock_select.gene_review import get_preopen_strategy_review, list_preopen_strategy_reviews
from stock_select.optimization_signals import list_optimization_signals, upsert_optimization_signal
from stock_select.review import generate_deterministic_reviews
from stock_select.review_packets import stock_review, stock_review_history
from stock_select.review_schema import DecisionReviewContract, OptimizationSignalContract, ReviewSchemaError
from stock_select.runtime import resolve_runtime
from stock_select.seed import DEMO_DATES, seed_demo_data
from stock_select.simulator import simulate_day, summarize_performance
from stock_select.strategies import generate_picks_for_all_genes, generate_picks_for_gene, seed_default_genes


class CoreFlowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = connect(":memory:")
        init_db(self.conn)
        seed_demo_data(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_generates_picks_and_outcomes(self) -> None:
        decision_ids = generate_picks_for_all_genes(self.conn, "2026-01-12")
        self.assertGreater(len(decision_ids), 0)
        pick = self.conn.execute(
            "SELECT thesis_json FROM pick_decisions WHERE decision_id = ?",
            (decision_ids[0],),
        ).fetchone()
        thesis = repository.loads(pick["thesis_json"], {})
        self.assertTrue(thesis["fundamental"])
        self.assertTrue(thesis["market_environment"])

        outcome_ids = simulate_day(self.conn, "2026-01-12")
        self.assertEqual(len(outcome_ids), len(decision_ids))

        performance = summarize_performance(self.conn, "2026-01-12")
        self.assertGreaterEqual(len(performance), 1)
        self.assertIn("strategy_gene_id", performance[0])

    def test_preopen_generation_does_not_use_same_day_prices(self) -> None:
        repository.upsert_stock(self.conn, "999999.SZ", "Future Spike", exchange="SZSE")
        for date in DEMO_DATES[:-1]:
            repository.upsert_daily_price(
                self.conn,
                stock_code="999999.SZ",
                trading_date=date,
                open=10,
                high=10.1,
                low=9.9,
                close=10,
                volume=1_000_000,
                amount=10_000_000,
                source="test",
            )
        repository.upsert_daily_price(
            self.conn,
            stock_code="999999.SZ",
            trading_date="2026-01-13",
            open=10,
            high=100,
            low=10,
            close=100,
            volume=50_000_000,
            amount=500_000_000,
            source="test",
        )
        self.conn.commit()

        generate_picks_for_gene(self.conn, "2026-01-13", "gene_aggressive_v1")
        rows = self.conn.execute(
            """
            SELECT stock_code FROM pick_decisions
            WHERE trading_date = '2026-01-13'
              AND strategy_gene_id = 'gene_aggressive_v1'
            """
        ).fetchall()
        picked = {row["stock_code"] for row in rows}
        self.assertNotIn("999999.SZ", picked)

    def test_dual_source_quality_records_warning_and_publishes_primary(self) -> None:
        repository.upsert_source_daily_price(
            self.conn,
            source="akshare",
            stock_code="000001.SZ",
            trading_date="2026-02-02",
            open=10,
            high=11,
            low=9,
            close=10,
        )
        repository.upsert_source_daily_price(
            self.conn,
            source="baostock",
            stock_code="000001.SZ",
            trading_date="2026-02-02",
            open=10,
            high=11,
            low=9,
            close=10.1,
        )
        self.conn.commit()

        checks = compare_and_publish_prices(self.conn, "2026-02-02")
        warning = [item for item in checks if item.stock_code == "000001.SZ"][0]
        self.assertEqual(warning.status, "warning")
        row = self.conn.execute(
            "SELECT close, source FROM daily_prices WHERE stock_code='000001.SZ' AND trading_date='2026-02-02'"
        ).fetchone()
        self.assertEqual(row["close"], 10)
        self.assertIn("akshare", row["source"])

    def test_canonical_price_falls_back_to_secondary_and_clears_missing_all(self) -> None:
        repository.upsert_source_daily_price(
            self.conn,
            source="baostock",
            stock_code="000001.SZ",
            trading_date="2026-02-03",
            open=9,
            high=10,
            low=8,
            close=9.5,
        )
        checks = compare_and_publish_prices(self.conn, "2026-02-03")
        fallback = [item for item in checks if item.stock_code == "000001.SZ"][0]
        self.assertEqual(fallback.status, "missing_primary")
        row = self.conn.execute(
            "SELECT close, source FROM daily_prices WHERE stock_code='000001.SZ' AND trading_date='2026-02-03'"
        ).fetchone()
        self.assertEqual(row["close"], 9.5)
        self.assertIn("baostock", row["source"])

        repository.upsert_daily_price(
            self.conn,
            stock_code="000001.SZ",
            trading_date="2026-02-04",
            open=1,
            high=1,
            low=1,
            close=1,
        )
        checks = compare_and_publish_prices(self.conn, "2026-02-04")
        missing = [item for item in checks if item.stock_code == "000001.SZ"][0]
        self.assertEqual(missing.status, "missing_all")
        row = self.conn.execute(
            "SELECT * FROM daily_prices WHERE stock_code='000001.SZ' AND trading_date='2026-02-04'"
        ).fetchone()
        self.assertIsNone(row)

    def test_runtime_mode_resolves_separate_default_databases(self) -> None:
        demo = resolve_runtime("demo")
        live = resolve_runtime("live")
        self.assertNotEqual(demo.db_path, live.db_path)
        self.assertEqual(demo.database_role, "demo")
        self.assertEqual(live.database_role, "live")
        self.assertTrue(demo.is_demo_data)
        self.assertFalse(live.is_demo_data)

    def test_contract_validation_rejects_bad_pick_and_accepts_review(self) -> None:
        with self.assertRaises(ContractError):
            PickContract.validate({"trading_date": "2026-01-01"})

        review = ReviewContract.validate(
            {
                "decision_id": "pick_x",
                "outcome": {
                    "entry_price": 1,
                    "close_price": 1.1,
                    "return_pct": 0.1,
                    "max_drawdown_intraday_pct": -0.01,
                },
                "reason_check": {
                    "what_was_right": [],
                    "what_was_wrong": [],
                    "missing_signals": [],
                },
                "attribution": [
                    {"event": "price", "confidence": "EXTRACTED", "evidence": ["bar"]}
                ],
                "gene_update_signal": {"score_delta": 0.1},
                "evidence": [{"type": "daily_price"}],
            }
        )
        self.assertEqual(review.decision_id, "pick_x")

    def test_review_schema_rejects_bad_taxonomy_values(self) -> None:
        with self.assertRaises(ValueError):
            DecisionReviewContract.validate(
                {
                    "review_id": "rev_x",
                    "decision_id": "pick_x",
                    "verdict": "LUCKY",
                    "primary_driver": "technical",
                    "factor_checks": [
                        {"factor_type": "technical", "verdict": "RIGHT", "confidence": "EXTRACTED"}
                    ],
                }
            )
        with self.assertRaises(ReviewSchemaError):
            OptimizationSignalContract.validate(
                {
                    "signal_type": "increase_weight",
                    "direction": "up",
                    "scope": "gene",
                    "strength": 1.2,
                    "confidence": 0.7,
                }
            )

    def test_review_memory_graph_and_gene_scoring(self) -> None:
        generate_picks_for_all_genes(self.conn, "2026-01-12")
        simulate_day(self.conn, "2026-01-12")
        review_ids = generate_deterministic_reviews(self.conn, "2026-01-12")
        self.assertGreater(len(review_ids), 0)
        review_rows = repository.review_rows_for_date(self.conn, "2026-01-12")
        self.assertEqual(len(review_rows), len(review_ids))
        self.assertIn("verdict", review_rows[0])
        factor_count = self.conn.execute(
            "SELECT COUNT(*) AS count FROM factor_review_items WHERE review_id = ?",
            (review_ids[0],),
        ).fetchone()["count"]
        self.assertGreaterEqual(factor_count, 6)
        evidence_count = self.conn.execute(
            "SELECT COUNT(*) AS count FROM review_evidence WHERE review_id = ?",
            (review_ids[0],),
        ).fetchone()["count"]
        self.assertGreater(evidence_count, 0)
        self.assertGreater(len(search_memory(self.conn, "return")), 0)

        graph_counts = sync_decision_graph(self.conn, "2026-01-12")
        self.assertGreater(graph_counts["nodes"], 0)
        self.assertGreater(len(query_graph(self.conn)["nodes"]), 0)

        scores = score_genes(self.conn, period_start="2026-01-01", period_end="2026-01-31")
        self.assertGreaterEqual(len(scores), 1)
        evolution = evolve_weekly(self.conn, period_start="2026-01-01", period_end="2026-01-31")
        self.assertEqual(evolution["status"], "skipped")

    def test_stock_and_preopen_strategy_reviews_are_queryable(self) -> None:
        generate_picks_for_all_genes(self.conn, "2026-01-12")
        simulate_day(self.conn, "2026-01-12")
        generate_deterministic_reviews(self.conn, "2026-01-12")

        stock_payload = stock_review(self.conn, "300750.SZ", "2026-01-12")
        self.assertEqual(stock_payload["stock"]["stock_code"], "300750.SZ")
        self.assertGreaterEqual(len(stock_payload["decisions"]), 1)
        self.assertIn("earnings_surprises", stock_payload["domain_facts"])

        history = stock_review_history(self.conn, "300750.SZ", "2026-01-01", "2026-01-31")
        self.assertGreaterEqual(history["summary"]["review_count"], 1)

        strategy_reviews = list_preopen_strategy_reviews(self.conn, "2026-01-12")
        self.assertGreaterEqual(len(strategy_reviews), 1)
        detail = get_preopen_strategy_review(self.conn, strategy_reviews[0]["strategy_gene_id"], "2026-01-12")
        self.assertIn("candidate_summary", detail)
        self.assertIn("factor_edges_json", detail)

    def test_optimization_signal_upsert_uses_stable_identity(self) -> None:
        first = upsert_optimization_signal(
            self.conn,
            source_type="decision_review",
            source_id="rev_demo",
            target_gene_id="gene_aggressive_v1",
            scope="gene",
            scope_key="gene_aggressive_v1",
            signal_type="increase_weight",
            param_name="event_component_weight",
            direction="up",
            strength=0.4,
            confidence=0.7,
            reason="demo",
            evidence_ids=["ev1"],
        )
        second = upsert_optimization_signal(
            self.conn,
            source_type="decision_review",
            source_id="rev_demo",
            target_gene_id="gene_aggressive_v1",
            scope="gene",
            scope_key="gene_aggressive_v1",
            signal_type="increase_weight",
            param_name="event_component_weight",
            direction="up",
            strength=0.6,
            confidence=0.8,
            reason="demo rerun",
            evidence_ids=["ev1"],
        )
        self.assertEqual(first, second)
        rows = list_optimization_signals(self.conn, gene_id="gene_aggressive_v1")
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["strength"], 0.6)

    def test_orchestrator_pipeline_is_idempotent(self) -> None:
        providers = [DemoProvider("akshare"), DemoProvider("baostock", close_adjustment=0.0005)]
        results = run_daily_pipeline(self.conn, "2026-01-13", providers=providers)
        self.assertEqual([item["phase"] for item in results], ["sync_data", "preopen_pick", "simulate", "review"])
        second = run_daily_pipeline(self.conn, "2026-01-13", providers=providers)
        self.assertEqual(len(second), 4)
        runs = self.conn.execute("SELECT COUNT(*) AS count FROM research_runs").fetchone()
        self.assertEqual(runs["count"], 4)

    def test_candidate_pipeline_uses_fundamental_event_and_sector_signals(self) -> None:
        gene = repository.get_gene(self.conn, "gene_aggressive_v1")
        params = repository.loads(gene["params_json"], {})
        candidates = rank_candidates_for_gene(self.conn, "2026-01-13", "gene_aggressive_v1", params)
        self.assertGreater(len(candidates), 0)
        top = candidates[0]
        self.assertGreater(top.fundamental_score, 0)
        self.assertGreaterEqual(top.sector_score, 0)
        self.assertIn("fundamental", top.packet)
        rows = self.conn.execute(
            """
            SELECT COUNT(*) AS count FROM candidate_scores
            WHERE trading_date = '2026-01-13'
              AND strategy_gene_id = 'gene_aggressive_v1'
            """
        ).fetchone()
        self.assertGreater(rows["count"], 0)

    def test_live_style_sync_subtasks_with_mock_provider_and_market_environment(self) -> None:
        conn = connect(":memory:")
        init_db(conn)
        seed_default_genes(conn)
        try:
            ak = DemoProvider("akshare")
            bao = DemoProvider("baostock", close_adjustment=0.0005)
            universe = sync_stock_universe(conn, providers=[ak])
            self.assertEqual(universe["rows"], 4)
            calendar = sync_trading_calendar(conn, "2026-01-01", "2026-02-02", providers=[ak])
            self.assertGreater(calendar["sources"]["akshare"], 0)
            for day in [
                "2026-01-02",
                "2026-01-05",
                "2026-01-06",
                "2026-01-07",
                "2026-01-08",
                "2026-01-09",
                "2026-01-12",
                "2026-01-13",
                "2026-01-14",
                "2026-01-15",
                "2026-01-16",
                "2026-01-19",
                "2026-01-20",
                "2026-01-21",
                "2026-01-22",
                "2026-01-23",
                "2026-01-26",
                "2026-01-27",
                "2026-01-28",
                "2026-01-29",
                "2026-01-30",
            ]:
                sync_index_prices(conn, day, providers=[ak, bao], index_codes=["000300.SH"])
            daily = sync_daily_prices(conn, "2026-02-02", providers=[ak, bao])
            self.assertEqual(daily["sources"]["akshare"], 4)
            canonical = publish_canonical_prices(conn, "2026-02-02")
            self.assertEqual(canonical["checks"], 4)
            env = classify_market_environment(conn, "2026-02-02", index_code="000300.SH")
            self.assertIn("market_environment", env)
            status_rows = data_source_status(conn, "2026-02-02")
            self.assertGreaterEqual(len(status_rows), 1)
            summary = data_quality_summary(conn, "2026-02-02")
            self.assertEqual(summary["canonical_prices"], 4)
        finally:
            conn.close()

    def test_daily_price_sync_supports_limit_offset_and_resume(self) -> None:
        conn = connect(":memory:")
        init_db(conn)
        try:
            provider = DemoProvider("akshare")
            sync_stock_universe(conn, providers=[provider])
            first = sync_daily_prices(
                conn,
                "2026-02-02",
                providers=[provider],
                limit=2,
                offset=1,
                batch_size=1,
            )
            self.assertEqual(first["selected_stocks"], 2)
            self.assertEqual(first["sources"]["akshare"], 2)
            rows = conn.execute("SELECT COUNT(*) AS count FROM source_daily_prices").fetchone()
            self.assertEqual(rows["count"], 2)
            synced_codes = {
                row["stock_code"]
                for row in conn.execute(
                    """
                    SELECT stock_code FROM source_daily_prices
                    WHERE source='akshare' AND trading_date='2026-02-02'
                    """
                )
            }
            self.assertEqual(synced_codes, {"000002.SZ", "300750.SZ"})

            second = sync_daily_prices(
                conn,
                "2026-02-02",
                providers=[provider],
                limit=2,
                offset=1,
                batch_size=1,
                resume=True,
            )
            self.assertEqual(second["sources"]["akshare"], 0)
            self.assertEqual(second["skipped_existing"]["akshare"], 2)
        finally:
            conn.close()

    def test_daily_price_sync_records_failed_chunks_and_keeps_progress(self) -> None:
        class PartialFailProvider(DemoProvider):
            def fetch_daily_prices(self, trading_date: str, stock_codes: list[str]):
                if stock_codes == ["000002.SZ"]:
                    raise RuntimeError("temporary provider failure")
                return super().fetch_daily_prices(trading_date, stock_codes)

        conn = connect(":memory:")
        init_db(conn)
        try:
            provider = PartialFailProvider("akshare")
            sync_stock_universe(conn, providers=[provider])
            result = sync_daily_prices(
                conn,
                "2026-02-03",
                providers=[provider],
                batch_size=1,
                max_retries=0,
            )
            self.assertEqual(result["sources"]["akshare"], 3)
            self.assertEqual(len(result["failed_chunks"]["akshare"]), 1)
            status = conn.execute(
                """
                SELECT status, rows_loaded, warning_count FROM data_sources
                WHERE source='akshare' AND dataset='daily_prices' AND trading_date='2026-02-03'
                """
            ).fetchone()
            self.assertEqual(status["status"], "warning")
            self.assertEqual(status["rows_loaded"], 3)
            self.assertEqual(status["warning_count"], 1)
        finally:
            conn.close()

    def test_backfill_daily_prices_range_uses_open_days_and_resume(self) -> None:
        conn = connect(":memory:")
        init_db(conn)
        try:
            provider = DemoProvider("akshare")
            sync_stock_universe(conn, providers=[provider])
            repository.upsert_trading_day(conn, "2026-02-02", True)
            repository.upsert_trading_day(conn, "2026-02-03", False)
            repository.upsert_trading_day(conn, "2026-02-04", True)
            conn.commit()

            first = backfill_daily_prices_range(
                conn,
                "2026-02-02",
                "2026-02-04",
                providers=[provider],
                limit=2,
                batch_size=1,
                resume=True,
                publish_canonical=True,
            )
            self.assertEqual(first["days"], ["2026-02-02", "2026-02-04"])
            self.assertEqual(first["trading_days"], 2)
            self.assertEqual(first["source_rows_loaded"]["akshare"], 4)
            canonical_rows = conn.execute(
                """
                SELECT COUNT(*) AS count FROM daily_prices
                WHERE trading_date IN ('2026-02-02', '2026-02-04')
                """
            ).fetchone()
            self.assertEqual(canonical_rows["count"], 4)

            second = backfill_daily_prices_range(
                conn,
                "2026-02-02",
                "2026-02-04",
                providers=[provider],
                limit=2,
                batch_size=1,
                resume=True,
            )
            self.assertEqual(second["source_rows_loaded"]["akshare"], 0)
            skipped = [item["daily_prices"]["skipped_existing"]["akshare"] for item in second["results"]]
            self.assertEqual(skipped, [2, 2])
        finally:
            conn.close()

    def test_open_trading_dates_falls_back_to_weekdays_without_calendar(self) -> None:
        conn = connect(":memory:")
        init_db(conn)
        try:
            self.assertEqual(
                open_trading_dates(conn, "2026-02-06", "2026-02-09"),
                ["2026-02-06", "2026-02-09"],
            )
        finally:
            conn.close()

    def test_backfill_stock_code_filter_excludes_indexes_and_unknown_codes(self) -> None:
        conn = connect(":memory:")
        init_db(conn)
        try:
            repository.upsert_stock(conn, "000001.SZ", "Ping An", exchange="SZSE", list_date="1991-04-03")
            repository.upsert_stock(conn, "300001.SZ", "ChiNext", exchange="SZSE", list_date="2009-10-30")
            repository.upsert_stock(
                conn,
                "600000.SH",
                "Pudong Bank",
                exchange="SSE",
                list_date="1999-11-10",
                is_st=True,
            )
            conn.commit()
            self.assertTrue(is_a_share_stock_code("300001.SZ"))
            self.assertFalse(is_a_share_stock_code("399001.SZ"))
            self.assertEqual(
                filter_known_active_stock_codes(
                    conn,
                    ["000001.SZ", "300001.SZ", "399001.SZ", "600000.SH", "999999.SH"],
                ),
                ["000001.SZ", "300001.SZ"],
            )
        finally:
            conn.close()

    def test_factor_visibility_dates_and_event_classification(self) -> None:
        self.assertEqual(conservative_visible_date("2023-03-31", None), "2023-06-01")
        self.assertEqual(conservative_visible_date("2023-06-30", None), "2023-09-01")
        self.assertEqual(conservative_visible_date("2023-09-30", None), "2023-11-15")
        self.assertEqual(conservative_visible_date("2023-12-31", None), "2024-05-01")
        self.assertEqual(conservative_visible_date("2023-12-31", "2024-03-15"), "2024-03-15")
        positive = classify_event_title("公司签署重大合同")
        negative = classify_event_title("收到监管处罚决定")
        self.assertEqual(positive[0], "major_contract")
        self.assertGreater(positive[1], 0)
        self.assertEqual(negative[0], "penalty")
        self.assertLess(negative[1], 0)

    def test_unconfigured_akshare_fundamentals_are_skipped_not_errors(self) -> None:
        conn = connect(":memory:")
        init_db(conn)
        try:
            repository.upsert_stock(conn, "000001.SZ", "Ping An", exchange="SZSE")
            result = sync_fundamentals(
                conn,
                "2026-02-03",
                providers=[AkShareProvider()],
                stock_codes=["000001.SZ"],
                resume=False,
            )
            self.assertEqual(result["sources"]["akshare"], 0)
            self.assertEqual(result["errors"], {})
            status = conn.execute(
                """
                SELECT status FROM data_sources
                WHERE source='akshare' AND dataset='fundamentals' AND trading_date='2026-02-03'
                """
            ).fetchone()
            self.assertEqual(status["status"], "skipped")
        finally:
            conn.close()

    def test_sync_factors_populates_candidate_packet_sources(self) -> None:
        conn = connect(":memory:")
        init_db(conn)
        seed_default_genes(conn)
        try:
            provider = DemoProvider("demo")
            sync_stock_universe(conn, providers=[provider])
            days = ["2026-01-26", "2026-01-27", "2026-01-28", "2026-01-29", "2026-01-30", "2026-02-02", "2026-02-03"]
            for day in days:
                for item in provider.fetch_daily_prices(day, ["000001.SZ", "000002.SZ"]):
                    repository.upsert_daily_price(conn, **item.__dict__)
                repository.upsert_trading_day(conn, day, True)
            conn.commit()
            result = sync_factors(conn, "2026-02-03", providers=[provider], stock_limit=2)
            self.assertGreater(result["industries"]["rows"], 0)
            self.assertGreater(result["sector_signals"]["rows"], 0)
            self.assertGreater(result["fundamentals"]["sources"]["demo"], 0)
            self.assertGreater(result["event_signals"]["sources"]["demo"], 0)

            gene = repository.get_gene(conn, "gene_aggressive_v1")
            params = repository.loads(gene["params_json"], {})
            candidates = rank_candidates_for_gene(conn, "2026-02-03", "gene_aggressive_v1", params)
            target = next(item for item in candidates if "event" not in item.packet["missing_fields"])
            self.assertNotIn("fundamental", target.packet["missing_fields"])
            self.assertNotIn("event", target.packet["missing_fields"])
            self.assertIn("dataset", target.packet["sources"]["fundamental"])
            self.assertIn("dataset", target.packet["sources"]["sector"])
            self.assertGreater(len(target.packet["sources"]["events"]), 0)
        finally:
            conn.close()

    def test_live_candidate_marks_missing_multidimensional_inputs(self) -> None:
        repository.upsert_stock(
            self.conn,
            "600000.SH",
            "Live Missing Factors",
            exchange="SSE",
            industry="Unknown",
            list_date="2020-01-01",
        )
        dates = [
            "2026-01-02",
            "2026-01-05",
            "2026-01-06",
            "2026-01-07",
            "2026-01-08",
            "2026-01-09",
            "2026-01-12",
            "2026-01-13",
        ]
        for index, day in enumerate(dates):
            price = 10 + index * 0.35
            repository.upsert_daily_price(
                self.conn,
                stock_code="600000.SH",
                trading_date=day,
                open=price - 0.1,
                high=price + 0.2,
                low=price - 0.2,
                close=price,
                volume=2_000_000,
                amount=price * 2_000_000,
                source="akshare:ok",
            )
        gene = repository.get_gene(self.conn, "gene_aggressive_v1")
        params = repository.loads(gene["params_json"], {})
        candidates = rank_candidates_for_gene(self.conn, "2026-01-13", "gene_aggressive_v1", params)
        target = next(item for item in candidates if item.stock_code == "600000.SH")
        self.assertIn("fundamental", target.packet["missing_fields"])
        self.assertIn("sector", target.packet["missing_fields"])
        self.assertIn("event", target.packet["missing_fields"])

    def test_review_driven_evolution_creates_observing_challenger_and_rolls_back(self) -> None:
        generate_picks_for_gene(self.conn, "2026-01-12", "gene_aggressive_v1")
        simulate_day(self.conn, "2026-01-12")
        review_ids = generate_deterministic_reviews(self.conn, "2026-01-12")
        upsert_optimization_signal(
            self.conn,
            source_type="decision_review",
            source_id=review_ids[0],
            target_gene_id="gene_aggressive_v1",
            scope="gene",
            scope_key="gene_aggressive_v1",
            signal_type="increase_weight",
            param_name="event_component_weight",
            direction="up",
            strength=0.6,
            confidence=0.8,
            reason="test review signal",
            evidence_ids=[review_ids[0]],
        )

        result = propose_strategy_evolution(
            self.conn,
            period_start="2026-01-01",
            period_end="2026-01-31",
            gene_id="gene_aggressive_v1",
            min_trades=1,
            min_signal_samples=1,
            min_signal_dates=1,
        )
        self.assertEqual(result["status"], "proposed")
        consumed = list_optimization_signals(self.conn, gene_id="gene_aggressive_v1", status="consumed")
        self.assertGreaterEqual(len(consumed), 1)
        child_gene_id = result["proposals"][0]["child_gene_id"]
        child = repository.get_gene(self.conn, child_gene_id)
        self.assertEqual(child["status"], "observing")
        self.assertEqual(child["parent_gene_id"], "gene_aggressive_v1")

        active_ids = {row["gene_id"] for row in repository.get_active_genes(self.conn)}
        self.assertIn(child_gene_id, active_ids)

        rollback = rollback_evolution(self.conn, child_gene_id=child_gene_id, reason="test rollback")
        self.assertEqual(rollback["status"], "rolled_back")
        self.assertEqual(repository.get_gene(self.conn, child_gene_id)["status"], "rolled_back")
        active_ids_after = {row["gene_id"] for row in repository.get_active_genes(self.conn)}
        self.assertNotIn(child_gene_id, active_ids_after)


if __name__ == "__main__":
    unittest.main()
