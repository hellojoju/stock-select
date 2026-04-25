"""Tests for Phase D: LLM review module."""
from __future__ import annotations

import json
import os
import sqlite3
from unittest.mock import patch
import pytest

from stock_select.db import connect, init_db
from stock_select.seed import seed_demo_data
from stock_select.llm_contracts import LLMReviewContract, AttributionClaim, LLMContractError
from stock_select.llm_prompt import build_decision_review_packet, build_system_prompt, build_user_prompt
from stock_select.llm_review import llm_review_for_decision, review_decision, run_llm_review


@pytest.fixture()
def demo_db(tmp_path):
    conn = connect(tmp_path / "demo.db")
    init_db(conn)
    seed_demo_data(conn)
    conn.commit()
    return conn


@pytest.fixture()
def picked_db(demo_db):
    """Add a pick decision + outcome so review can run."""
    conn = demo_db
    conn.execute(
        """
        INSERT INTO pick_decisions(
            decision_id, trading_date, horizon, strategy_gene_id, stock_code,
            action, confidence, position_pct, score, entry_plan_json,
            sell_rules_json, thesis_json, risks_json, invalid_if_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', '{}', '{}', '{}', '{}')
        """,
        ("pick_llm_test", "2026-01-12", "short", "gene_aggressive_v1", "300750.SZ",
         "BUY", 0.8, 0.05, 0.7),
    )
    conn.execute(
        """
        INSERT INTO sim_orders(
            order_id, decision_id, trading_date, stock_code,
            side, price, quantity, position_pct, fee, slippage_pct
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("order_llm_test", "pick_llm_test", "2026-01-12", "300750.SZ",
         "BUY", 250.0, 100.0, 0.05, 0.001, 0.001),
    )
    conn.execute(
        """
        INSERT INTO outcomes(
            outcome_id, decision_id, entry_price, exit_price, close_price,
            return_pct, max_drawdown_intraday_pct, hit_sell_rule
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("outcome_llm_test", "pick_llm_test", 250.0, 262.0, 262.0, 0.048, -0.01, "none"),
    )
    conn.commit()
    return conn


class TestLLMContracts:
    def test_valid_contract(self):
        payload = {
            "review_target": {"type": "decision", "id": "pick_001"},
            "attribution": [
                {"claim": "Tech sector drove gains", "confidence": "EXTRACTED", "evidence_ids": ["ev_001"]}
            ],
            "reason_check": {"what_was_right": ["momentum"], "what_was_wrong": [], "missing_signals": []},
            "summary": "Good pick.",
        }
        contract = LLMReviewContract.validate(payload)
        assert contract.review_target["type"] == "decision"
        assert len(contract.attribution) == 1

    def test_missing_target_raises(self):
        payload = {"attribution": [], "reason_check": {}, "summary": ""}
        with pytest.raises(LLMContractError, match="review_target"):
            LLMReviewContract.validate(payload)


class TestLLMPrompt:
    def test_build_decision_review_packet(self):
        packet = build_decision_review_packet(
            decision_row={
                "decision_id": "pick_001",
                "packet_json": '{"technical": {"score": 0.6}}',
                "thesis_json": '{"momentum": true}',
                "risks_json": '["high volatility"]',
                "industry": "Battery",
            },
            outcome_row={
                "entry_price": 250.0,
                "close_price": 262.0,
                "return_pct": 0.048,
                "max_drawdown_intraday_pct": -0.01,
                "index_return_pct": 0.005,
            },
            factor_checks=[{"factor_type": "technical", "verdict": "RIGHT"}],
            evidence=[{"evidence_id": "ev_001", "source_type": "outcome"}],
        )
        assert packet["target"]["id"] == "pick_001"
        assert packet["postclose_facts"]["outcome"]["return_pct"] == 0.048
        assert len(packet["deterministic_checks"]) == 1

    def test_build_system_prompt_returns_string(self):
        prompt = build_system_prompt()
        assert "review" in prompt.lower()

    def test_build_user_prompt_contains_packet(self):
        packet = build_decision_review_packet(
            {"decision_id": "x", "packet_json": "{}", "thesis_json": "{}", "risks_json": "[]"},
            {"entry_price": 10, "close_price": 11, "return_pct": 0.1, "max_drawdown_intraday_pct": 0, "index_return_pct": 0},
            [], [],
        )
        user = build_user_prompt(packet)
        assert "Review" in user
        assert "decision" in user


class TestLLMReview:
    def test_llm_review_skips_without_api_key(self, picked_db):
        """Without ANTHROPIC_API_KEY, LLM review should gracefully skip."""
        env = os.environ.copy()
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("CLAUDE_API_KEY", None)

        review_id = review_decision(picked_db, "pick_llm_test")
        result = llm_review_for_decision(picked_db, review_id)
        assert result is None

        os.environ.clear()
        os.environ.update(env)

    def test_run_llm_review_graceful_without_api(self, picked_db):
        """run_llm_review should not crash even without API key."""
        env = os.environ.copy()
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("CLAUDE_API_KEY", None)

        result = run_llm_review(picked_db, "2026-01-12")
        assert result["total"] >= 1
        assert result["skipped"] >= 1

        os.environ.clear()
        os.environ.update(env)
