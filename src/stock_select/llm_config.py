"""LLM configuration: multi-provider support, budget tracking, circuit breaker."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

DEEPSEEK_MODELS = {
    "flash": {"model": "deepseek-chat", "label": "DeepSeek V4 Flash"},
    "pro": {"model": "deepseek-reasoner", "label": "DeepSeek V4 Pro"},
}

PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "anthropic": {"model": "claude-sonnet-4-6-20250514", "env_key": "ANTHROPIC_API_KEY"},
    "openai": {"model": "gpt-4o", "env_key": "OPENAI_API_KEY"},
    "deepseek": {"model": "deepseek-v4-flash", "env_key": "DEEPSEEK_API_KEY"},
}


def resolve_deepseek_model(model_name: str | None) -> str:
    """Map user-friendly DeepSeek model aliases to native API model names."""
    if not model_name:
        return "deepseek-chat"
    model_name = model_name.strip().lower()
    for key, cfg in DEEPSEEK_MODELS.items():
        if key in model_name or cfg["model"] in model_name:
            return cfg["model"]
    if "reasoner" in model_name:
        return "deepseek-reasoner"
    return model_name


class LLMNotConfigured(ValueError):
    """Raised when LLM is not configured or an unsupported provider is used."""


class BudgetExceeded(ValueError):
    """Raised when daily token or cost budget is exceeded."""


@dataclass(frozen=True)
class LLMConfig:
    """Immutable LLM provider configuration resolved from environment."""

    provider: str
    model: str
    api_key: str
    base_url: str | None = None
    max_tokens_per_call: int = 4096
    max_stocks_per_day: int = 20
    max_tokens_per_day: int = 100_000
    max_cost_per_day: float = 1.0


@dataclass
class LLMBudget:
    """Daily token/cost budget tracker. In-memory; resets on restart."""

    tokens_prompt: int = 0
    tokens_completion: int = 0
    total_cost: float = 0.0
    call_count: int = 0

    def check(self, config: LLMConfig) -> None:
        """Raise BudgetExceeded if any daily limit has been reached."""
        if self.tokens_prompt + self.tokens_completion >= config.max_tokens_per_day:
            raise BudgetExceeded(
                f"Daily token budget exceeded ({config.max_tokens_per_day})"
            )
        if self.total_cost >= config.max_cost_per_day:
            raise BudgetExceeded(
                f"Daily cost budget exceeded (${config.max_cost_per_day:.2f})"
            )

    def record(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        cost: float,
    ) -> None:
        """Record a completed LLM call's token usage and cost."""
        self.tokens_prompt += prompt_tokens
        self.tokens_completion += completion_tokens
        self.total_cost += cost
        self.call_count += 1


# Per-provider cost per 1K tokens (approximate, in USD)
COST_PER_1K: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6-20250514": {"input": 0.003, "output": 0.015},
    "claude-opus-4-6": {"input": 0.015, "output": 0.075},
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "deepseek-chat": {"input": 0.00027, "output": 0.0011},
    "deepseek-reasoner": {"input": 0.00055, "output": 0.00219},
}


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate USD cost for a model call based on per-token rates."""
    rates = COST_PER_1K.get(model, COST_PER_1K["claude-sonnet-4-6-20250514"])
    return (
        prompt_tokens / 1000 * rates["input"]
        + completion_tokens / 1000 * rates["output"]
    )


_budget: LLMBudget = LLMBudget()
_model_override: str | None = None


def get_budget() -> LLMBudget:
    """Return the module-level budget singleton."""
    return _budget


def reset_budget() -> None:
    """Reset the module-level budget singleton to zero."""
    _budget.__init__()


def set_model_override(model: str | None) -> None:
    """Override the LLM model at runtime (e.g. switch deepseek-chat <-> deepseek-reasoner)."""
    global _model_override
    _model_override = model


def get_model_override() -> str | None:
    """Return the current model override, or None."""
    return _model_override


def _load_dotenv_silent() -> None:
    """Load .env file if it exists, silently."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass


_load_dotenv_silent()


def resolve_llm_config() -> LLMConfig | None:
    """Read environment variables and return LLMConfig, or None if not configured."""
    provider = os.environ.get("LLM_PROVIDER", "anthropic").lower()
    defaults = PROVIDER_DEFAULTS.get(provider)
    if not defaults:
        logger.warning("Unknown LLM_PROVIDER=%s, falling back to anthropic", provider)
        provider = "anthropic"
        defaults = PROVIDER_DEFAULTS["anthropic"]

    api_key = (
        os.environ.get(defaults["env_key"])
        or os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        or os.environ.get("DEEPSEEK_API_KEY")
    )
    if not api_key:
        return None

    model = os.environ.get("LLM_MODEL") or defaults["model"]
    if _model_override:
        model = _model_override
    if provider == "deepseek":
        model = resolve_deepseek_model(model)
    return LLMConfig(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=os.environ.get("ANTHROPIC_BASE_URL"),
        max_tokens_per_call=int(os.environ.get("LLM_MAX_TOKENS_PER_CALL", "4096")),
        max_stocks_per_day=int(os.environ.get("LLM_MAX_STOCKS_PER_DAY", "20")),
        max_tokens_per_day=int(os.environ.get("LLM_MAX_TOKENS_PER_DAY", "100000")),
        max_cost_per_day=float(os.environ.get("LLM_MAX_COST_PER_DAY", "1.0")),
    )


def build_allowlist(
    decisions: list[dict],
    blindspots: list[dict],
    max_stocks: int = 20,
) -> set[str]:
    """Build allowlist from decision and blindspot stocks. Never scans full market."""
    codes: set[str] = set()
    for d in decisions:
        codes.add(d["stock_code"])
    for b in blindspots:
        if len(codes) >= max_stocks:
            break
        codes.add(b["stock_code"])
    return codes
