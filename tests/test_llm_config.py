"""Tests for llm_config: provider resolution, budget tracking, circuit breaker."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from stock_select.llm_config import (
    BudgetExceeded,
    LLMConfig,
    LLMBudget,
    build_allowlist,
    estimate_cost,
    get_budget,
    reset_budget,
    resolve_llm_config,
)


class TestLLMConfigResolution:
    """Provider resolution from environment variables."""

    def test_resolve_none_when_no_key(self):
        """Without any API key, resolve should return None."""
        with patch.dict(os.environ, {}, clear=True):
            config = resolve_llm_config()
            assert config is None

    def test_resolve_anthropic_with_key(self):
        """ANTHROPIC_API_KEY + LLM_PROVIDER=anthropic -> provider=anthropic with default model."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-xxx", "LLM_PROVIDER": "anthropic"}):
            config = resolve_llm_config()
            assert config is not None
            assert config.provider == "anthropic"
            assert config.model == "claude-sonnet-4-6-20250514"

    def test_resolve_openai_with_key(self):
        """OPENAI_API_KEY + LLM_PROVIDER=openai -> provider=openai."""
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "sk-xxx", "LLM_PROVIDER": "openai"},
        ):
            config = resolve_llm_config()
            assert config is not None
            assert config.provider == "openai"
            assert config.model == "gpt-4o"

    def test_resolve_deepseek(self):
        """DEEPSEEK_API_KEY + LLM_PROVIDER=deepseek -> provider=deepseek."""
        with patch.dict(
            os.environ,
            {"DEEPSEEK_API_KEY": "sk-ds-xxx", "LLM_PROVIDER": "deepseek"},
        ):
            config = resolve_llm_config()
            assert config is not None
            assert config.provider == "deepseek"
            assert config.model == "deepseek-chat"

    def test_custom_model_from_env(self):
        """LLM_MODEL env var overrides the default model."""
        with patch.dict(
            os.environ,
            {
                "ANTHROPIC_API_KEY": "sk-ant-xxx",
                "LLM_MODEL": "claude-opus-4-6",
            },
        ):
            config = resolve_llm_config()
            assert config is not None
            assert config.model == "claude-opus-4-6"


class TestLLMBudget:
    """Budget tracking and circuit breaker."""

    def test_budget_token_exceeded_raises(self):
        """When max_tokens_per_day is exceeded, check() should raise BudgetExceeded."""
        config = LLMConfig(
            provider="anthropic",
            model="test",
            api_key="sk-test",
            max_tokens_per_day=10,
        )
        budget = LLMBudget()
        budget.record(prompt_tokens=100, completion_tokens=0, cost=0.0)
        with pytest.raises(BudgetExceeded):
            budget.check(config)

    def test_budget_cost_exceeded_raises(self):
        """When max_cost_per_day is exceeded, check() should raise BudgetExceeded."""
        config = LLMConfig(
            provider="anthropic",
            model="test",
            api_key="sk-test",
            max_cost_per_day=0.01,
        )
        budget = LLMBudget()
        budget.record(prompt_tokens=0, completion_tokens=0, cost=0.02)
        with pytest.raises(BudgetExceeded):
            budget.check(config)

    def test_budget_within_limits_passes(self):
        """When within limits, check() should not raise."""
        config = LLMConfig(
            provider="anthropic",
            model="test",
            api_key="sk-test",
            max_tokens_per_day=1000,
            max_cost_per_day=1.0,
        )
        budget = LLMBudget()
        budget.record(prompt_tokens=100, completion_tokens=50, cost=0.005)
        budget.check(config)  # should not raise

    def test_budget_record_accumulates(self):
        """record() should correctly accumulate token and cost counters."""
        budget = LLMBudget()
        budget.record(prompt_tokens=100, completion_tokens=50, cost=0.003)
        budget.record(prompt_tokens=200, completion_tokens=30, cost=0.005)
        assert budget.tokens_prompt == 300
        assert budget.tokens_completion == 80
        assert budget.total_cost == 0.008
        assert budget.call_count == 2


class TestLLMBudgetSingleton:
    """Module-level get_budget / reset_budget."""

    def setup_method(self) -> None:
        reset_budget()

    def test_get_budget_returns_instance(self):
        b = get_budget()
        assert isinstance(b, LLMBudget)

    def test_get_budget_same_instance(self):
        b1 = get_budget()
        b2 = get_budget()
        assert b1 is b2

    def test_reset_budget_clears_counters(self):
        budget = get_budget()
        budget.record(prompt_tokens=100, completion_tokens=50, cost=0.01)
        assert budget.call_count == 1
        reset_budget()
        assert budget.tokens_prompt == 0
        assert budget.tokens_completion == 0
        assert budget.total_cost == 0.0
        assert budget.call_count == 0


class TestEstimateCost:
    """Cost estimation for known and unknown models."""

    def test_anthropic_sonnet_cost(self):
        cost = estimate_cost("claude-sonnet-4-6-20250514", prompt_tokens=1000, completion_tokens=500)
        # 1000 * 0.003/1000 + 500 * 0.015/1000 = 0.003 + 0.0075 = 0.0105
        assert cost == pytest.approx(0.0105)

    def test_deepseek_cost(self):
        cost = estimate_cost("deepseek-chat", prompt_tokens=2000, completion_tokens=1000)
        # 2000 * 0.00027/1000 + 1000 * 0.0011/1000 = 0.00054 + 0.0011 = 0.00164
        assert cost == pytest.approx(0.00164)

    def test_unknown_model_falls_back_to_sonnet(self):
        cost = estimate_cost("unknown-model", prompt_tokens=1000, completion_tokens=500)
        # falls back to sonnet rates: 0.003 + 0.0075 = 0.0105
        assert cost == pytest.approx(0.0105)


class TestAllowlist:
    """Allowlist construction from decisions and blindspots."""

    def test_allowlist_limits_stocks(self):
        allowlist = build_allowlist(
            decisions=[{"decision_id": "d1", "stock_code": "000001.SZ"}],
            blindspots=[{"stock_code": "000002.SZ"}],
            max_stocks=2,
        )
        assert len(allowlist) <= 2
        assert "000001.SZ" in allowlist
        assert "000002.SZ" in allowlist

    def test_allowlist_excludes_non_decision_stocks(self):
        allowlist = build_allowlist(
            decisions=[{"decision_id": "d1", "stock_code": "000001.SZ"}],
            blindspots=[],
            max_stocks=1,
        )
        assert "000003.SZ" not in allowlist
