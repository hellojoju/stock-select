"""Tests for Phase F2: Analyst Agent and Pick Evaluator."""
from __future__ import annotations

import os

import pytest

from stock_select.db import connect, init_db
from stock_select.seed import seed_demo_data
from stock_select.analyst import (
    analyze_industry,
    find_stocks_in_industry,
    run_analysis,
    IndustrySignal,
    StockInsight,
)
from stock_select.pick_evaluator import (
    evaluate_candidate,
    rank_candidates,
    run_evaluation,
    PickScore,
)


@pytest.fixture()
def demo_db(tmp_path):
    conn = connect(tmp_path / "demo.db")
    init_db(conn)
    seed_demo_data(conn)
    conn.commit()
    return conn


class TestAnalyzeIndustry:
    def test_returns_skip_for_unknown_industry(self, demo_db):
        signal = analyze_industry(demo_db, "NonExistent", "2026-01-12")
        assert signal.recommendation == "skip"
        assert signal.sector_return_pct == 0.0

    def test_returns_data_for_known_industry(self, demo_db):
        signal = analyze_industry(demo_db, "Battery", "2026-01-12")
        assert signal.industry == "Battery"

    def test_compute_momentum_positive(self, demo_db):
        signal = analyze_industry(demo_db, "Battery", "2026-01-12")
        assert signal.momentum_score is not None


class TestFindStocksInIndustry:
    def test_returns_stocks_for_industry(self, demo_db):
        insights = find_stocks_in_industry(demo_db, "Battery", "2026-01-12")
        assert len(insights) > 0
        assert isinstance(insights[0], StockInsight)

    def test_respects_limit(self, demo_db):
        insights = find_stocks_in_industry(demo_db, "Battery", "2026-01-12", limit=1)
        assert len(insights) <= 1

    def test_suspended_stocks_avoided(self, demo_db):
        demo_db.execute("UPDATE daily_prices SET is_suspended = 1 WHERE stock_code = '000001.SZ'")
        demo_db.commit()

        insights = find_stocks_in_industry(demo_db, "Battery", "2026-01-12")
        suspended = [i for i in insights if i.is_suspended]
        for s in suspended:
            assert s.recommendation == "avoid"


class TestRunAnalysis:
    def test_returns_analysis_without_llm(self, demo_db):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("CLAUDE_API_KEY", None)

        result = run_analysis(demo_db, "2026-01-12")
        assert result["trading_date"] == "2026-01-12"
        assert isinstance(result["industry_signals"], list)
        assert isinstance(result["stock_insights"], list)
        assert "llm_synthesis" not in result or result.get("llm_synthesis") is None


class TestEvaluateCandidate:
    def test_reject_unknown_stock(self, demo_db):
        score = evaluate_candidate(demo_db, "999999.SH", "2026-01-12")
        assert score.verdict == "reject"
        assert score.overall_score == 0.0

    def test_evaluates_known_stock(self, demo_db):
        score = evaluate_candidate(demo_db, "000001.SZ", "2026-01-12")
        assert isinstance(score, PickScore)
        assert score.stock_code == "000001.SZ"

    def test_st_stock_is_rejected(self, demo_db):
        demo_db.execute("UPDATE stocks SET is_st = 1 WHERE stock_code = '000001.SZ'")
        demo_db.commit()

        score = evaluate_candidate(demo_db, "000001.SZ", "2026-01-12")
        assert score.verdict == "reject"
        assert score.risk_penalty > 0

    def test_inactive_stock_is_rejected(self, demo_db):
        demo_db.execute("UPDATE stocks SET listing_status = 'delisted' WHERE stock_code = '000001.SZ'")
        demo_db.commit()

        score = evaluate_candidate(demo_db, "000001.SZ", "2026-01-12")
        assert score.verdict == "reject"


class TestRankCandidates:
    def test_returns_ranked_list(self, demo_db):
        ranked = rank_candidates(demo_db, "2026-01-12")
        assert len(ranked) > 0
        # Should be sorted descending
        for i in range(len(ranked) - 1):
            assert ranked[i].overall_score >= ranked[i + 1].overall_score

    def test_respects_limit(self, demo_db):
        ranked = rank_candidates(demo_db, "2026-01-12", limit=2)
        assert len(ranked) <= 2

    def test_filters_by_min_score(self, demo_db):
        ranked = rank_candidates(demo_db, "2026-01-12", min_score=0.5)
        for s in ranked:
            assert s.overall_score >= 0.5


class TestRunEvaluation:
    def test_returns_evaluation_without_llm(self, demo_db):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("CLAUDE_API_KEY", None)

        result = run_evaluation(demo_db, "2026-01-12")
        assert result["trading_date"] == "2026-01-12"
        assert isinstance(result["top_picks"], list)
        assert isinstance(result["total_evaluated"], int)
