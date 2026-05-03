"""Sprint 1 unit tests: limit constraints, rejected orders, LLM rerun, document queries."""
from __future__ import annotations

import json
import sqlite3
import unittest
from unittest.mock import patch

from stock_select.db import connect, init_db
from stock_select.simulator import (
    _get_limit_threshold,
    _is_limit_up_down,
    _check_reject_reason,
    build_id,
)
from stock_select.news_providers import query_documents


class TestLimitThresholds(unittest.TestCase):
    """S1.1: A-share limit thresholds by board."""

    def test_main_board_10_pct(self) -> None:
        self.assertEqual(_get_limit_threshold("600000"), 0.10)

    def test_st_5_pct(self) -> None:
        self.assertEqual(_get_limit_threshold("600000", is_st=True), 0.05)

    def test_gem_20_pct(self) -> None:
        self.assertEqual(_get_limit_threshold("300001"), 0.20)

    def test_star_20_pct(self) -> None:
        self.assertEqual(_get_limit_threshold("688001"), 0.20)

    def test_bse_30_pct(self) -> None:
        self.assertEqual(_get_limit_threshold("830001"), 0.30)
        self.assertEqual(_get_limit_threshold("870001"), 0.30)
        self.assertEqual(_get_limit_threshold("430001"), 0.30)


class TestIsLimitUpDown(unittest.TestCase):
    """S1.1: Limit detection with threshold."""

    def test_limit_up_detected(self) -> None:
        self.assertTrue(_is_limit_up_down(11.0, 10.0, 0.10))

    def test_limit_down_detected(self) -> None:
        self.assertTrue(_is_limit_up_down(9.0, 10.0, 0.10))

    def test_no_limit(self) -> None:
        self.assertFalse(_is_limit_up_down(10.5, 10.0, 0.10))

    def test_no_prev_close(self) -> None:
        self.assertFalse(_is_limit_up_down(11.0, None, 0.10))

    def test_zero_prev_close(self) -> None:
        self.assertFalse(_is_limit_up_down(11.0, 0, 0.10))

    def test_gem_limit_up(self) -> None:
        self.assertTrue(_is_limit_up_down(12.0, 10.0, 0.20))

    def test_st_limit_up(self) -> None:
        self.assertTrue(_is_limit_up_down(10.5, 10.0, 0.05))


class TestCheckRejectReason(unittest.TestCase):
    """S1.1: Pre-trade rejection checks."""

    def test_no_price_data(self) -> None:
        self.assertEqual(_check_reject_reason(None, "600000", {}), "no_price_data")

    def test_suspended(self) -> None:
        class FakeRow:
            def __init__(self, d):
                self._d = d
            def __getitem__(self, k):
                return self._d[k]
            def keys(self):
                return self._d.keys()

        row = FakeRow({"is_suspended": 1, "open": 10.0})
        self.assertEqual(_check_reject_reason(row, "600000", {}), "suspended")

    def test_no_open_price(self) -> None:
        class FakeRow:
            def __init__(self, d):
                self._d = d
            def __getitem__(self, k):
                return self._d[k]
            def keys(self):
                return self._d.keys()

        row = FakeRow({"is_suspended": 0, "open": 0})
        self.assertEqual(_check_reject_reason(row, "600000", {}), "no_open_price")

    def test_no_rejection(self) -> None:
        class FakeRow:
            def __init__(self, d):
                self._d = d
            def __getitem__(self, k):
                return self._d[k]
            def keys(self):
                return self._d.keys()

        row = FakeRow({"is_suspended": 0, "open": 10.0})
        self.assertIsNone(_check_reject_reason(row, "600000", {}))


class TestRejectedOrders(unittest.TestCase):
    """S1.2: Rejected orders are recorded with reject_reason."""

    def setUp(self) -> None:
        self.conn = connect(":memory:")
        init_db(self.conn)
        self.conn.execute(
            "INSERT INTO stocks(stock_code, name) VALUES ('600000', 'Test Stock')"
        )
        self.conn.execute(
            "INSERT INTO strategy_genes(gene_id, name, version, horizon, risk_profile, params_json) "
            "VALUES ('gene1', 'Test', 1, 'short', 'conservative', '{}')"
        )
        self.conn.execute(
            "INSERT INTO pick_decisions(decision_id, trading_date, horizon, strategy_gene_id, "
            "stock_code, action, confidence, position_pct, score, entry_plan_json, "
            "sell_rules_json, thesis_json, risks_json, invalid_if_json) "
            "VALUES ('dec1', '2026-01-13', 'short', 'gene1', '600000', 'BUY', "
            "0.8, 0.1, 90, '{}', '[{\"type\":\"time_exit\",\"days\":1}]', '{}', '{}', '{}')"
        )
        # Suspended stock
        self.conn.execute(
            "INSERT INTO daily_prices(stock_code, trading_date, open, high, low, close, volume, amount, is_suspended) "
            "VALUES ('600000', '2026-01-13', 10.0, 10.5, 9.8, 10.2, 100000, 1000000, 1)"
        )
        self.conn.commit()

    def test_suspended_order_recorded_as_rejected(self) -> None:
        from stock_select.simulator import simulate_day

        outcomes = simulate_day(self.conn, "2026-01-13")
        self.assertEqual(outcomes, [])

        orders = self.conn.execute(
            "SELECT * FROM sim_orders WHERE decision_id = 'dec1'"
        ).fetchall()
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["status"], "rejected")
        self.assertIn(orders[0]["reject_reason"], ("suspended",))

    def test_limit_up_order_recorded_as_rejected(self) -> None:
        # Update to non-suspended, limit-up open
        self.conn.execute(
            "UPDATE daily_prices SET is_suspended = 0, open = 11.0 "
            "WHERE stock_code = '600000' AND trading_date = '2026-01-13'"
        )
        # Add prev_close for limit detection
        self.conn.execute(
            "INSERT INTO daily_prices(stock_code, trading_date, open, high, low, close, volume, amount, is_suspended) "
            "VALUES ('600000', '2026-01-12', 9.8, 10.0, 9.7, 10.0, 100000, 1000000, 0)"
        )
        self.conn.execute(
            "UPDATE daily_prices SET prev_close = 10.0 "
            "WHERE stock_code = '600000' AND trading_date = '2026-01-13'"
        )
        self.conn.commit()

        from stock_select.simulator import simulate_day

        outcomes = simulate_day(self.conn, "2026-01-13")
        self.assertEqual(outcomes, [])

        orders = self.conn.execute(
            "SELECT * FROM sim_orders WHERE decision_id = 'dec1'"
        ).fetchall()
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["status"], "rejected")
        self.assertEqual(orders[0]["reject_reason"], "limit_up")

    def test_limit_up_uses_prior_close_when_prev_close_missing(self) -> None:
        self.conn.execute(
            "UPDATE daily_prices SET is_suspended = 0, open = 11.0, prev_close = NULL "
            "WHERE stock_code = '600000' AND trading_date = '2026-01-13'"
        )
        self.conn.execute(
            "INSERT INTO daily_prices(stock_code, trading_date, open, high, low, close, volume, amount, is_suspended) "
            "VALUES ('600000', '2026-01-12', 9.8, 10.0, 9.7, 10.0, 100000, 1000000, 0)"
        )
        self.conn.commit()

        from stock_select.simulator import simulate_day

        outcomes = simulate_day(self.conn, "2026-01-13")
        self.assertEqual(outcomes, [])
        order = self.conn.execute("SELECT * FROM sim_orders WHERE decision_id = 'dec1'").fetchone()
        self.assertEqual(order["status"], "rejected")
        self.assertEqual(order["reject_reason"], "limit_up")

    def test_filled_order_has_no_reject_reason(self) -> None:
        # Normal price, not at limit
        self.conn.execute(
            "UPDATE daily_prices SET is_suspended = 0, open = 10.1, prev_close = 10.0 "
            "WHERE stock_code = '600000' AND trading_date = '2026-01-13'"
        )
        self.conn.execute(
            "INSERT INTO daily_prices(stock_code, trading_date, open, high, low, close, volume, amount, is_suspended) "
            "VALUES ('600000', '2026-01-12', 9.8, 10.0, 9.7, 10.0, 100000, 1000000, 0)"
        )
        self.conn.commit()

        from stock_select.simulator import simulate_day

        outcomes = simulate_day(self.conn, "2026-01-13")
        self.assertEqual(len(outcomes), 1)

        orders = self.conn.execute(
            "SELECT * FROM sim_orders WHERE decision_id = 'dec1'"
        ).fetchall()
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["status"], "filled")


class TestDocumentQueryNoStock(unittest.TestCase):
    """S1.4: Document query without stock_code filter works."""

    def setUp(self) -> None:
        self.conn = connect(":memory:")
        init_db(self.conn)

    def test_query_all_documents(self) -> None:
        from stock_select.news_providers import store_document, RawDocumentItem

        item = RawDocumentItem(
            source="test",
            source_type="official_announcement",
            source_url="http://example.com/1",
            title="Test Announcement",
            summary="Test summary",
            content_text="Test content",
            published_at="2026-01-13",
            captured_at="2026-01-13T10:00:00",
        )
        store_document(self.conn, item)
        self.conn.commit()

        # Query without stock_code should work
        results = query_documents(self.conn)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Test Announcement")

    def test_query_by_stock(self) -> None:
        from stock_select.news_providers import store_document, RawDocumentItem

        self.conn.execute(
            "INSERT INTO stocks(stock_code, name) VALUES ('600000', 'Test')"
        )
        item = RawDocumentItem(
            source="test",
            source_type="official_announcement",
            source_url="http://example.com/2",
            title="Test for Stock",
            summary="Test",
            content_text="Test",
            published_at="2026-01-13",
            captured_at="2026-01-13T10:00:00",
            related_stock_codes=["600000"],
        )
        store_document(self.conn, item)
        self.conn.commit()

        results = query_documents(self.conn, stock_code="600000")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Test for Stock")

    def test_query_by_date(self) -> None:
        from stock_select.news_providers import store_document, RawDocumentItem

        item = RawDocumentItem(
            source="test",
            source_type="finance_news",
            source_url="http://example.com/3",
            title="News",
            summary="Summary",
            content_text="Content",
            published_at="2026-01-13",
            captured_at="2026-01-13T10:00:00",
        )
        store_document(self.conn, item)
        self.conn.commit()

        results = query_documents(self.conn, date="2026-01-13")
        self.assertEqual(len(results), 1)

    def test_query_by_keyword(self) -> None:
        from stock_select.news_providers import store_document, RawDocumentItem

        item = RawDocumentItem(
            source="test",
            source_type="finance_news",
            source_url="http://example.com/4",
            title="Market Analysis Report",
            summary="Analysis content",
            content_text="Full text",
            published_at="2026-01-13",
            captured_at="2026-01-13T10:00:00",
        )
        store_document(self.conn, item)
        self.conn.commit()

        results = query_documents(self.conn, keyword="Market")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Market Analysis Report")

    def test_fts_index_error_is_visible(self) -> None:
        from stock_select.news_providers import store_document, RawDocumentItem

        self.conn.execute("DROP TABLE documents_fts")
        self.conn.execute("CREATE TABLE documents_fts(title TEXT)")
        item = RawDocumentItem(
            source="test",
            source_type="finance_news",
            source_url="http://example.com/bad-fts",
            title="Broken FTS",
            summary="Summary",
            content_text="Content",
            published_at="2026-01-13",
            captured_at="2026-01-13T10:00:00",
        )
        with self.assertRaises(RuntimeError):
            store_document(self.conn, item)
        row = self.conn.execute(
            "SELECT fetch_status FROM raw_documents WHERE document_id = ?",
            (item.document_id,),
        ).fetchone()
        self.assertEqual(row["fetch_status"], "index_error")


class TestAnnouncementSourceStatus(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = connect(":memory:")
        init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_sync_announcements_records_source_error(self) -> None:
        from stock_select.announcement_providers import AnnouncementSourceError, sync_announcements

        with (
            patch("stock_select.announcement_providers.fetch_cninfo_announcements", side_effect=AnnouncementSourceError("cninfo", "boom")),
            patch("stock_select.announcement_providers.fetch_sse_announcements", return_value=[]),
            patch("stock_select.announcement_providers.fetch_szse_announcements", return_value=[]),
            patch("stock_select.announcement_providers.fetch_eastmoney_news", return_value=[]),
            patch("stock_select.announcement_providers.fetch_sina_news", return_value=[]),
        ):
            items = sync_announcements(date="2026-01-13", conn=self.conn)

        self.assertEqual(items, [])
        row = self.conn.execute(
            """
            SELECT status, error FROM data_sources
            WHERE source = 'cninfo' AND dataset = 'documents' AND trading_date = '2026-01-13'
            """
        ).fetchone()
        self.assertEqual(row["status"], "error")
        self.assertEqual(row["error"], "boom")


class TestLLMRerunUpdatesSignals(unittest.TestCase):
    """S1.3: LLM rerun updates suggested_errors_json and suggested_signals_json."""

    def test_persist_updates_signals_on_conflict(self) -> None:
        from stock_select.llm_contracts import (
            LLMReviewContract,
            AttributionClaim,
        )

        conn = connect(":memory:")
        init_db(conn)
        conn.execute(
            "INSERT INTO stocks(stock_code, name) VALUES ('600000', 'Test')"
        )
        conn.execute(
            "INSERT INTO strategy_genes(gene_id, name, version, horizon, risk_profile, params_json) "
            "VALUES ('gene1', 'Test', 1, 'short', 'conservative', '{}')"
        )
        conn.execute(
            "INSERT INTO pick_decisions(decision_id, trading_date, horizon, strategy_gene_id, "
            "stock_code, action, confidence, position_pct, score, entry_plan_json, "
            "sell_rules_json, thesis_json, risks_json, invalid_if_json) "
            "VALUES ('dec1', '2026-01-13', 'short', 'gene1', '600000', 'BUY', "
            "0.8, 0.1, 90, '{}', '[{\"type\":\"time_exit\",\"days\":1}]', '{}', '{}', '{}')"
        )
        conn.execute(
            "INSERT INTO daily_prices(stock_code, trading_date, open, high, low, close, volume, amount) "
            "VALUES ('600000', '2026-01-13', 10.0, 10.5, 9.8, 10.2, 100000, 1000000)"
        )
        # Create a decision review first
        from stock_select.deterministic_review import review_decision

        review_id = review_decision(conn, "dec1")

        from stock_select.llm_review import _persist_llm_review

        # First LLM review
        contract1 = LLMReviewContract(
            attribution=[AttributionClaim(claim="Test", confidence="high", evidence_ids=[])],
            reason_check={"valid": True},
            suggested_errors=[{"error_type": "weight_too_low", "severity": 0.5}],
            suggested_optimization_signals=[{"signal_type": "increase_weight", "direction": "up"}],
            summary="First review",
            review_target={"type": "decision", "id": "dec1"},
        )
        _persist_llm_review(conn, review_id, "gene1", contract1)

        row1 = conn.execute("SELECT * FROM llm_reviews WHERE decision_review_id = ?", (review_id,)).fetchone()
        self.assertIn("weight_too_low", row1["suggested_errors_json"])

        # Second LLM review with different errors/signals
        contract2 = LLMReviewContract(
            attribution=[AttributionClaim(claim="Updated", confidence="medium", evidence_ids=[])],
            reason_check={"valid": False},
            suggested_errors=[{"error_type": "wrong_entry", "severity": 0.8}],
            suggested_optimization_signals=[{"signal_type": "decrease_weight", "direction": "down"}],
            summary="Second review",
            review_target={"type": "decision", "id": "dec1"},
        )
        _persist_llm_review(conn, review_id, "gene1", contract2)

        row2 = conn.execute("SELECT * FROM llm_reviews WHERE decision_review_id = ?", (review_id,)).fetchone()
        self.assertIn("wrong_entry", row2["suggested_errors_json"])
        self.assertNotIn("weight_too_low", row2["suggested_errors_json"])
        self.assertIn("decrease_weight", row2["suggested_signals_json"])
        self.assertEqual(row2["summary"], "Second review")


if __name__ == "__main__":
    unittest.main()
