from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stock_select.db import connect, init_db
from stock_select.hypothetical_review import (
    hypothetical_stock_review,
    _build_hypothetical_factor_checks,
    _infer_hypothetical_verdict,
    _choose_primary_driver,
    _ensure_hypothetical_gene,
    _fetch_live_market_data,
    _normalize_price_row,
    _to_secid_eastmoney,
)
from stock_select.review_packets import _normalize_stock_code
from stock_select.candidate_pipeline import Candidate


class TestHypotheticalReview(unittest.TestCase):
    """Test hypothetical stock review for stocks not selected by strategy."""

    def setUp(self):
        self.conn = connect(":memory:")
        init_db(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_ensure_hypothetical_gene(self):
        """Gene should be created on first call."""
        _ensure_hypothetical_gene(self.conn)
        row = self.conn.execute(
            "SELECT gene_id, name FROM strategy_genes WHERE gene_id = ?",
            ("gene_hypothetical",),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["gene_id"], "gene_hypothetical")
        self.assertIn("假设", row["name"])

    def test_ensure_hypothetical_gene_idempotent(self):
        """Calling twice should not fail or duplicate."""
        _ensure_hypothetical_gene(self.conn)
        _ensure_hypothetical_gene(self.conn)
        count = self.conn.execute(
            "SELECT COUNT(*) FROM strategy_genes WHERE gene_id = ?",
            ("gene_hypothetical",),
        ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_hypothetical_review_stock_not_in_pool(self):
        """Should return None for stock not in stocks table."""
        result = hypothetical_stock_review(self.conn, "000000", "2024-01-01")
        self.assertIsNone(result)

    def test_hypothetical_review_no_price_data(self):
        """Should return None when no price data available and fetch fails."""
        # Insert stock but no prices — fetch_live will fail for non-existent stock
        self.conn.execute(
            "INSERT INTO stocks (stock_code, name, exchange) VALUES (?, ?, ?)",
            ("000000", "Test Stock", "SZ"),
        )
        self.conn.commit()
        result = hypothetical_stock_review(self.conn, "000000", "2024-01-01")
        # Will be None because akshare can't fetch data for fake stock
        self.assertIsNone(result)

    def test_infer_verdict_from_factors(self):
        """Verdict should reflect average factor scores."""
        positive = [
            {"factor_type": "technical", "contribution_score": 0.3},
            {"factor_type": "fundamental", "contribution_score": 0.2},
        ]
        self.assertEqual(_infer_hypothetical_verdict(positive), "正确")

        negative = [
            {"factor_type": "technical", "contribution_score": -0.3},
            {"factor_type": "risk", "contribution_score": -0.2},
        ]
        self.assertEqual(_infer_hypothetical_verdict(negative), "错误")

        neutral = [
            {"factor_type": "technical", "contribution_score": 0.05},
            {"factor_type": "fundamental", "contribution_score": 0.0},
        ]
        self.assertEqual(_infer_hypothetical_verdict(neutral), "中性")

    def test_choose_primary_driver(self):
        """Should return label of highest-scoring factor."""
        factors = [
            {"factor_type": "technical", "contribution_score": 0.1},
            {"factor_type": "fundamental", "contribution_score": 0.3},
            {"factor_type": "risk", "contribution_score": -0.1},
        ]
        driver = _choose_primary_driver(factors, {})
        self.assertEqual(driver, "基本面")

    def test_factor_checks_structure(self):
        """Factor checks should have required fields."""
        # Create a minimal mock candidate
        packet = {
            "stock": {"code": "002272", "name": "Test", "industry": "软件"},
            "technical": {"score": 0.2, "momentum": 0.05, "volume_surge": 0.1, "volatility": 0.02, "trend_state": "neutral"},
            "fundamental": {"score": 0.5, "available": True, "roe": 0.15, "revenue_growth": 0.1, "net_profit_growth": 0.12, "pe_percentile": 0.4},
            "event": {"score": 0.1, "available": True, "items": []},
            "sector": {"score": 0.3, "available": True, "relative_strength_rank": 5, "theme_strength": 0.4, "sector_return_pct": 0.02},
            "risk": {"score": 0.1, "avg_amount": 1e8, "reasons": []},
            "data_coverage": {"fundamental": "available", "sector": "available", "event": "available"},
            "missing_fields": [],
        }
        candidate = Candidate(
            stock_code="002272",
            total_score=0.25,
            confidence=0.6,
            technical_score=0.2,
            fundamental_score=0.5,
            event_score=0.1,
            sector_score=0.3,
            risk_penalty=0.1,
            packet=packet,
        )

        # Need stock in DB for the function to query events
        self.conn.execute(
            "INSERT INTO stocks (stock_code, name) VALUES (?, ?)",
            ("002272", "Test"),
        )
        self.conn.commit()

        factors = _build_hypothetical_factor_checks(self.conn, "002272", "2024-01-01", candidate)
        self.assertEqual(len(factors), 5)

        factor_types = [f["factor_type"] for f in factors]
        self.assertIn("technical", factor_types)
        self.assertIn("fundamental", factor_types)
        self.assertIn("event", factor_types)
        self.assertIn("sector", factor_types)
        self.assertIn("risk", factor_types)

        for f in factors:
            self.assertIn("verdict", f)
            self.assertIn("contribution_score", f)
            self.assertIn("confidence", f)
            self.assertIn(f["verdict"], ["正确", "错误", "中性"])

    def test_multi_source_fallback_returns_none_for_invalid_stock(self):
        """When all sources fail, should return None."""
        result = _fetch_live_market_data("999999", "2024-01-01")
        self.assertIsNone(result)

    def test_normalize_price_row(self):
        """Should normalize a mock DataFrame row to standard format."""
        try:
            import pandas as pd
        except ImportError:
            self.skipTest("pandas not available")

        row = pd.Series({
            "开盘": 10.5, "收盘": 11.0, "最高": 11.2, "最低": 10.3,
            "成交量": 1000000, "成交额": 11000000, "昨收": 10.8,
        })
        result = _normalize_price_row(row, "002272", "2024-01-15", "test")
        self.assertEqual(result["stock_code"], "002272")
        self.assertEqual(result["close"], 11.0)
        self.assertEqual(result["prev_close"], 10.8)
        self.assertEqual(result["source"], "test")
        self.assertEqual(result["is_limit_up"], 0)  # 11.0 < 10.8 * 1.095 (11.766)

    def test_secid_conversion(self):
        """EastMoney secid conversion should be correct."""
        self.assertEqual(_to_secid_eastmoney("600519"), "1.600519")  # Shanghai
        self.assertEqual(_to_secid_eastmoney("002272"), "0.002272")  # Shenzhen
        self.assertEqual(_to_secid_eastmoney("300750"), "0.300750")  # Shenzhen (ChiNext)

    def test_normalize_stock_code_exact(self):
        """Exact match should return the code as-is."""
        self.conn.execute(
            "INSERT INTO stocks (stock_code, name) VALUES (?, ?)",
            ("002272.SZ", "Test"),
        )
        self.conn.commit()
        result = _normalize_stock_code(self.conn, "002272.SZ")
        self.assertEqual(result, "002272.SZ")

    def test_normalize_stock_code_prefix(self):
        """Prefix match should find the suffixed code."""
        self.conn.execute(
            "INSERT INTO stocks (stock_code, name) VALUES (?, ?)",
            ("002272.SZ", "Test"),
        )
        self.conn.commit()
        result = _normalize_stock_code(self.conn, "002272")
        self.assertEqual(result, "002272.SZ")

    def test_normalize_stock_code_shanghai(self):
        """Should normalize Shanghai stocks too."""
        self.conn.execute(
            "INSERT INTO stocks (stock_code, name) VALUES (?, ?)",
            ("600519.SH", "茅台"),
        )
        self.conn.commit()
        result = _normalize_stock_code(self.conn, "600519")
        self.assertEqual(result, "600519.SH")

    def test_normalize_stock_code_not_found(self):
        """Should return None for non-existent stock."""
        result = _normalize_stock_code(self.conn, "999999")
        self.assertIsNone(result)

    def test_normalize_stock_code_empty(self):
        """Should return None for empty input."""
        result = _normalize_stock_code(self.conn, "")
        self.assertIsNone(result)
        result = _normalize_stock_code(self.conn, "   ")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
