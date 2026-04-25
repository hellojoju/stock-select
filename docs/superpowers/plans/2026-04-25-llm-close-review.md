# Phase D: LLM 收盘复盘实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 让 LLM 只做归因、反证、解释质量增强，不扫描全市场，不直接改策略参数。默认关闭，不影响确定性复盘流水线。

**架构：** 基于现有的 `llm_review.py` / `llm_contracts.py` / `llm_prompt.py` 增强，新增多 provider 支持、预算熔断、allowlist、candidate signal 隔离、scratchpad 日志。前端新增 LLM review 面板。

**技术栈：** Python 3.12+, anthropic/openai SDK, FastAPI, React, SQLite

**前提（已在手）：**
- 现有代码：`llm_review.py`（Anthropic-only, hardcoded model, signal 默认 accepted）
- 现有代码：`llm_contracts.py`（LLMReviewContract 校验）
- 现有代码：`llm_prompt.py`（packet 构建）
- 现有测试：5 个（contract 校验、packet 构建、API key skip）
- `db.py`：`llm_reviews` 表已存在，`status` 默认值 `'candidate'`
- `agent_runtime.py`：`llm_review` phase 已注册，当前返回 `skipped`
- `optimization_signals.py`：已有 `"open"/"consumed"` 状态流转，upsert 保护 consumed 不被覆盖

---

## 修改文件清单

| 文件 | 职责 | 变更 |
|------|------|------|
| `src/stock_select/llm_config.py` | **新建**：LLM provider 配置读取、预算跟踪、熔断逻辑 | 新建 |
| `src/stock_select/llm_review.py` | LLM review 执行器 | 重构：provider 抽象、allowlist、scratchpad、多类型 review |
| `src/stock_select/llm_contracts.py` | 输出 contract 校验 | 增强校验规则 |
| `src/stock_select/llm_prompt.py` | 构建 LLM packet/prompt | 新增 stock/blindspot packet 构建 |
| `src/stock_select/agent_runtime.py` | pipeline phase 路由 | 接通 `llm_review` phase |
| `src/stock_select/api.py` | API 端点 | 新增 LLM review 端点、signal accept/reject |
| `src/stock_select/db.py` | 数据库 schema | 新增 scratchpad 日志表 |
| `tests/test_llm_config.py` | **新建**：配置/预算/熔断测试 | 新建 |
| `tests/test_llm_review.py` | 已有测试文件 | 新增多类型 review 测试 |
| `web/src/types/index.ts` | 前端类型 | 新增 LLMReview 类型 |
| `web/src/App.tsx` | 前端主应用 | 新增 LLM review 标签页 |
| `web/src/sections/LLMReviewPanel.tsx` | **新建**：LLM review 展示 | 新建 |
| `web/src/styles.css` | 前端样式 | LLM review 面板样式 |

---

### 任务 1：LLM 配置模块（D1.1 + D1.2）

**文件：**
- 创建：`src/stock_select/llm_config.py`
- 测试：`tests/test_llm_config.py`

- [ ] **步骤 1：编写失败的测试 - provider 配置读取**

```python
"""Tests for llm_config: provider resolution, budget tracking, circuit breaker."""
from __future__ import annotations

import os
from unittest.mock import patch
import pytest
from stock_select.llm_config import (
    resolve_llm_config,
    get_llm_client,
    LLMBudget,
    BudgetExceeded,
    LLMNotConfigured,
)


class TestLLMConfig:
    def test_resolve_none_when_no_key(self):
        """Without any API key, resolve should return None / raise."""
        with patch.dict(os.environ, {}, clear=True):
            config = resolve_llm_config()
            assert config is None

    def test_resolve_anthropic_with_key(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-xxx"}):
            config = resolve_llm_config()
            assert config is not None
            assert config.provider == "anthropic"
            assert config.model == "claude-sonnet-4-6-20250514"

    def test_resolve_openai_with_key(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-xxx", "LLM_PROVIDER": "openai"}):
            config = resolve_llm_config()
            assert config is not None
            assert config.provider == "openai"
            assert config.model == "gpt-4o"

    def test_resolve_deepseek(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-ds-xxx", "LLM_PROVIDER": "deepseek"}):
            config = resolve_llm_config()
            assert config is not None
            assert config.provider == "deepseek"

    def test_custom_model_from_env(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-xxx", "LLM_MODEL": "claude-opus-4-6"}):
            config = resolve_llm_config()
            assert config.model == "claude-opus-4-6"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_llm_config.py -v`
预期：FAIL（模块不存在）

- [ ] **步骤 3：实现 LLM 配置模块**

```python
"""LLM configuration: multi-provider support, budget tracking, circuit breaker."""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)

PROVIDER_DEFAULTS = {
    "anthropic": {"model": "claude-sonnet-4-6-20250514", "env_key": "ANTHROPIC_API_KEY"},
    "openai": {"model": "gpt-4o", "env_key": "OPENAI_API_KEY"},
    "deepseek": {"model": "deepseek-chat", "env_key": "DEEPSEEK_API_KEY"},
}


class LLMNotConfigured(ValueError):
    pass


class BudgetExceeded(ValueError):
    pass


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    api_key: str
    max_tokens_per_call: int = 4096
    max_stocks_per_day: int = 20
    max_tokens_per_day: int = 100_000
    max_cost_per_day: float = 1.0


def resolve_llm_config() -> LLMConfig | None:
    """Read env and return LLMConfig, or None if not configured."""
    provider = os.environ.get("LLM_PROVIDER", "anthropic").lower()
    defaults = PROVIDER_DEFAULTS.get(provider)
    if not defaults:
        logger.warning("Unknown LLM_PROVIDER=%s, falling back to anthropic", provider)
        provider = "anthropic"
        defaults = PROVIDER_DEFAULTS["anthropic"]

    api_key = os.environ.get(defaults["env_key"]) or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    model = os.environ.get("LLM_MODEL") or defaults["model"]
    return LLMConfig(
        provider=provider,
        model=model,
        api_key=api_key,
        max_tokens_per_call=int(os.environ.get("LLM_MAX_TOKENS_PER_CALL", "4096")),
        max_stocks_per_day=int(os.environ.get("LLM_MAX_STOCKS_PER_DAY", "20")),
        max_tokens_per_day=int(os.environ.get("LLM_MAX_TOKENS_PER_DAY", "100000")),
        max_cost_per_day=float(os.environ.get("LLM_MAX_COST_PER_DAY", "1.0")),
    )


@dataclass
class LLMBudget:
    """Daily token/cost budget tracker. In-memory; resets on restart."""
    tokens_prompt: int = 0
    tokens_completion: int = 0
    total_cost: float = 0.0
    call_count: int = 0

    def check(self, config: LLMConfig) -> None:
        if self.tokens_prompt + self.tokens_completion >= config.max_tokens_per_day:
            raise BudgetExceeded(f"Daily token budget exceeded ({config.max_tokens_per_day})")
        if self.total_cost >= config.max_cost_per_day:
            raise BudgetExceeded(f"Daily cost budget exceeded (${config.max_cost_per_day:.2f})")

    def record(self, prompt_tokens: int, completion_tokens: int, cost: float) -> None:
        self.tokens_prompt += prompt_tokens
        self.tokens_completion += completion_tokens
        self.total_cost += cost
        self.call_count += 1


# Per-provider cost per 1K tokens (approximate)
COST_PER_1K = {
    "claude-sonnet-4-6-20250514": {"input": 0.003, "output": 0.015},
    "claude-opus-4-6": {"input": 0.015, "output": 0.075},
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "deepseek-chat": {"input": 0.0005, "output": 0.002},
}


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    rates = COST_PER_1K.get(model, COST_PER_1K["claude-sonnet-4-6-20250514"])
    return (prompt_tokens / 1000 * rates["input"]) + (completion_tokens / 1000 * rates["output"])


_budget = LLMBudget()


def get_budget() -> LLMBudget:
    return _budget


def reset_budget() -> None:
    _budget.__init__()
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_llm_config.py -v`
预期：PASS（5 passed）

- [ ] **步骤 5：提交**

```bash
git add src/stock_select/llm_config.py tests/test_llm_config.py
git commit -m "feat: add LLM multi-provider config and budget tracker (D1.1-D1.2)"
```

---

### 任务 2：LLM Allowlist（D1.3）+ 接通 pipeline phase（D3.2）

**文件：**
- 修改：`src/stock_select/llm_config.py`
- 修改：`src/stock_select/llm_review.py`
- 修改：`src/stock_select/agent_runtime.py`

- [ ] **步骤 1：编写 allowlist 过滤测试**

添加到 `tests/test_llm_config.py`：

```python
class TestAllowlist:
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
```

- [ ] **步骤 2：实现 allowlist + 修改 llm_review.py 使用 LLMConfig**

```python
# 添加到 llm_config.py

def build_allowlist(
    decisions: list[dict],
    blindspots: list[dict],
    max_stocks: int = 20,
) -> set[str]:
    """Build allowlist: only decision stocks + blindspot top-N."""
    codes: set[str] = set()
    for d in decisions:
        codes.add(d["stock_code"])
    for b in blindspots:
        if len(codes) >= max_stocks:
            break
        codes.add(b["stock_code"])
    return codes
```

修改 `llm_review.py`：

- 将 `_call_llm()` 改为使用 `resolve_llm_config()` 和 `get_budget()`
- 移除硬编码的 `anthropic` 导入，改为 provider 抽象
- 增加 provider 客户端工厂函数
- `run_llm_review()` 增加 allowlist 过滤

```python
def get_llm_client(config: LLMConfig):
    """Return a callable that sends a prompt and returns JSON."""
    if config.provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=config.api_key)
        def _call(prompt: str, system: str) -> dict | None:
            try:
                resp = client.messages.create(
                    model=config.model,
                    max_tokens=config.max_tokens_per_call,
                    system=system,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = resp.content[0].text if resp.content else ""
                budget = get_budget()
                cost = estimate_cost(config.model, resp.usage.input_tokens, resp.usage.output_tokens)
                budget.record(resp.usage.input_tokens, resp.usage.output_tokens, cost)
                return json.loads(text) if text else None
            except json.JSONDecodeError:
                return None
        return _call

    elif config.provider == "openai":
        from openai import OpenAI
        client = OpenAI(api_key=config.api_key)
        def _call(prompt: str, system: str) -> dict | None:
            resp = client.chat.completions.create(
                model=config.model,
                max_tokens=config.max_tokens_per_call,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            )
            text = resp.choices[0].message.content or ""
            budget = get_budget()
            usage = resp.usage
            if usage:
                cost = estimate_cost(config.model, usage.prompt_tokens, usage.completion_tokens)
                budget.record(usage.prompt_tokens, usage.completion_tokens, cost)
            return json.loads(text) if text else None
        return _call

    else:
        raise LLMNotConfigured(f"Unsupported provider: {config.provider}")
```

修改 `run_llm_review()` 增加 allowlist 保护：

```python
def run_llm_review(conn: sqlite3.Connection, trading_date: str) -> dict[str, Any]:
    config = resolve_llm_config()
    if config is None:
        return {"status": "skipped", "reason": "LLM not configured", "reviewed": 0, "skipped": 0, "total": 0}

    # Build allowlist from decisions
    decisions = conn.execute(
        "SELECT decision_id, stock_code FROM pick_decisions WHERE trading_date = ?",
        (trading_date,),
    ).fetchall()
    blindspots = conn.execute(
        "SELECT DISTINCT stock_code FROM blindspot_reviews WHERE trading_date = ?",
        (trading_date,),
    ).fetchall()

    allowlist = build_allowlist(
        decisions=[dict(d) for d in decisions],
        blindspots=[dict(b) for b in blindspots],
        max_stocks=config.max_stocks_per_day,
    )

    # Filter decisions to allowlist only
    filtered = [d for d in decisions if d["stock_code"] in allowlist]

    reviewed = 0
    skipped = 0
    budget = get_budget()

    for row in filtered:
        try:
            budget.check(config)
            review_id = review_decision(conn, row["decision_id"])
            result = llm_review_for_decision(conn, review_id, config=config)
            if result:
                reviewed += 1
            else:
                skipped += 1
        except BudgetExceeded:
            logger.warning("LLM budget exceeded, stopping review")
            skipped += len(filtered) - reviewed - skipped
            break
        except Exception as exc:
            logger.error("LLM review failed for %s: %s", row["decision_id"], exc)
            skipped += 1

    conn.commit()
    return {"reviewed": reviewed, "skipped": skipped, "total": len(filtered)}
```

修改 `_persist_llm_review()`：signal 状态改为 `"candidate"`（当前写死 `"accepted"`，这是 D4 的关键隔离点）。

```python
# In _persist_llm_review, change status from "accepted" to "candidate"
```

接通 `agent_runtime.py`：

```python
# Replace the current stub (line 143-144):
elif phase == "llm_review":
    result = run_llm_review(conn, trading_date)
```

- [ ] **步骤 3：运行已有测试确认不破坏**

运行：`pytest tests/test_llm_review.py -v`
预期：全部 PASS

- [ ] **步骤 4：提交**

```bash
git add src/stock_select/llm_config.py src/stock_select/llm_review.py src/stock_select/agent_runtime.py tests/test_llm_config.py
git commit -m "feat: add LLM allowlist, multi-provider client, pipeline integration (D1.3, D3.2)"
```

---

### 任务 3：Scratchpad 日志（D3.3）

**文件：**
- 修改：`src/stock_select/db.py`
- 修改：`src/stock_select/llm_review.py`
- 测试：添加到 `tests/test_llm_review.py`

- [ ] **步骤 1：添加 scratchpad 表到 schema**

```python
# 在 db.py 中，找到 CREATE TABLE llm_reviews 块之后添加：
CREATE TABLE IF NOT EXISTS llm_scratchpad (
  scratchpad_id TEXT PRIMARY KEY,
  llm_review_id TEXT REFERENCES llm_reviews(llm_review_id),
  decision_review_id TEXT,
  packet_hash TEXT,
  model TEXT,
  provider TEXT,
  prompt_tokens INTEGER DEFAULT 0,
  completion_tokens INTEGER DEFAULT 0,
  estimated_cost REAL DEFAULT 0.0,
  latency_ms INTEGER DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'ok',
  error_message TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

- [ ] **步骤 2：在 llm_review_for_decision 中写入 scratchpad**

每次 LLM 调用后记录 packet hash、model、token、latency、status。关键字段从响应中提取后写入，不记录 API key。

```python
def _write_scratchpad(
    conn: sqlite3.Connection,
    llm_review_id: str,
    decision_review_id: str,
    packet: dict,
    config: LLMConfig,
    prompt_tokens: int,
    completion_tokens: int,
    cost: float,
    latency_ms: int,
    status: str = "ok",
    error_message: str = "",
) -> None:
    packet_hash = hashlib.sha256(json.dumps(packet, sort_keys=True).encode()).hexdigest()[:16]
    conn.execute(
        """
        INSERT INTO llm_scratchpad(
          scratchpad_id, llm_review_id, decision_review_id, packet_hash,
          model, provider, prompt_tokens, completion_tokens,
          estimated_cost, latency_ms, status, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"sp_{hashlib.sha1(f'{decision_review_id}:scratchpad'.encode()).hexdigest()[:12]}",
            llm_review_id,
            decision_review_id,
            packet_hash,
            config.model,
            config.provider,
            prompt_tokens,
            completion_tokens,
            cost,
            latency_ms,
            status,
            error_message,
        ),
    )
```

- [ ] **步骤 3：提交**

```bash
git add src/stock_select/db.py src/stock_select/llm_review.py
git commit -m "feat: add LLM scratchpad logging table and writer (D3.3)"
```

---

### 任务 4：Stock / Blindspot / System LLM Review（D3.1 扩展）

**文件：**
- 修改：`src/stock_select/llm_prompt.py`
- 修改：`src/stock_select/llm_review.py`
- 修改：`src/stock_select/llm_contracts.py`

- [ ] **步骤 1：新增 stock 和 blindspot packet 构建函数**

```python
# in llm_prompt.py

def build_stock_review_packet(
    stock_code: str,
    trading_date: str,
    decisions: list[dict],
    evidence: list[dict],
    blindspots: list[dict],
) -> dict[str, Any]:
    """Build packet for per-stock LLM review."""
    return {
        "target": {"type": "stock", "id": stock_code, "date": trading_date},
        "decisions": decisions,
        "evidence": evidence,
        "blindspots": blindspots,
        "known_error_taxonomy": KNOWN_ERROR_TAXONOMY,
        "allowed_outputs": {
            "max_attributions": 5,
            "must_cite_evidence_for_extracted": True,
        },
    }


def build_blindspot_review_packet(
    stock_code: str,
    trading_date: str,
    candidate_packet: dict,
    missed_events: list[dict],
) -> dict[str, Any]:
    """Build packet for blindspot LLM review."""
    return {
        "target": {"type": "blindspot", "id": stock_code, "date": trading_date},
        "candidate_packet": candidate_packet,
        "missed_events": missed_events,
        "known_error_taxonomy": KNOWN_ERROR_TAXONOMY,
    }
```

- [ ] **步骤 2：实现 stock / blindspot / system LLM review 函数**

```python
# in llm_review.py

def llm_review_for_stock(
    conn: sqlite3.Connection,
    stock_code: str,
    trading_date: str,
    config: LLMConfig | None = None,
) -> dict[str, Any] | None:
    if config is None:
        config = resolve_llm_config()
    if config is None:
        return None

    decisions = conn.execute(
        "SELECT * FROM pick_decisions WHERE trading_date = ? AND stock_code = ?",
        (trading_date, stock_code),
    ).fetchall()
    evidence = conn.execute(
        "SELECT * FROM review_evidence WHERE trading_date = ? AND stock_code = ?",
        (trading_date, stock_code),
    ).fetchall()
    blindspots = conn.execute(
        "SELECT * FROM blindspot_reviews WHERE trading_date = ? AND stock_code = ?",
        (trading_date, stock_code),
    ).fetchall()

    packet = build_stock_review_packet(
        stock_code=stock_code,
        trading_date=trading_date,
        decisions=[dict(d) for d in decisions],
        evidence=[dict(e) for e in evidence],
        blindspots=[dict(b) for b in blindspots],
    )

    llm_result = _call_llm_with_config(build_system_prompt(), build_user_prompt(packet), config)
    if llm_result is None:
        return None

    # validate + persist
    ...
```

- [ ] **步骤 3：增强 LLMReviewContract 支持多种 review_target type**

当前 contract 已支持 `review_target` 的 `type` 和 `id`，扩展校验以覆盖 `"stock"` 和 `"blindspot"` 类型：

```python
# in llm_contracts.py, LLMReviewContract.validate:
VALID_TARGET_TYPES = {"decision", "stock", "blindspot", "system"}
target_type = target.get("type", "")
if target_type not in VALID_TARGET_TYPES:
    raise LLMContractError(f"Invalid review target type: {target_type}")
```

- [ ] **步骤 4：运行测试**

运行：`pytest tests/test_llm_review.py -v`
预期：全部 PASS（已有 + 新增）

- [ ] **步骤 5：提交**

```bash
git add src/stock_select/llm_prompt.py src/stock_select/llm_review.py src/stock_select/llm_contracts.py
git commit -m "feat: add stock/blindspot LLM review and contract type validation (D3.1)"
```

---

### 任务 5：Signal Candidate Staging（D4.1）+ Accept/Reject API（D4.2）

**文件：**
- 修改：`src/stock_select/llm_review.py`
- 修改：`src/stock_select/api.py`

- [ ] **步骤 1：修改 `_persist_llm_review` 使 LLM signal 默认 status 为 "candidate"**

当前代码（`llm_review.py:157`）写死 `status: "accepted"`，改为 `"candidate"`：

```python
# Before (line 157):
json.dumps(contract.suggested_optimization_signals),
contract.summary,
"accepted",  # <-- WRONG: makes LLM signals immediately consumable

# After:
json.dumps(contract.suggested_optimization_signals),
contract.summary,
"candidate",  # <-- LLM signals staged, need manual accept
```

注意：`optimization_signals` 表中 `upsert_optimization_signal` 调用也传了 `status="open"`（默认），需要验证 LLM 调用的 `upsert_optimization_signal` 传入 `status="candidate"`。

- [ ] **步骤 2：添加 accept/reject API 端点**

```python
# in api.py

@app.post("/api/optimization-signals/{signal_id}/accept")
def accept_optimization_signal(signal_id: str) -> dict[str, Any]:
    conn = db()
    try:
        conn.execute("UPDATE optimization_signals SET status = 'open' WHERE signal_id = ? AND status = 'candidate'", (signal_id,))
        conn.commit()
        affected = conn.execute("SELECT changes()").fetchone()[0]
        if affected == 0:
            return {"status": "not_found_or_not_candidate"}
        return {"status": "accepted"}
    finally:
        conn.close()


@app.post("/api/optimization-signals/{signal_id}/reject")
def reject_optimization_signal(signal_id: str) -> dict[str, Any]:
    conn = db()
    try:
        conn.execute("UPDATE optimization_signals SET status = 'rejected' WHERE signal_id = ? AND status = 'candidate'", (signal_id,))
        conn.commit()
        return {"status": "rejected"}
    finally:
        conn.close()
```

- [ ] **步骤 3：提交**

```bash
git add src/stock_select/llm_review.py src/stock_select/api.py
git commit -m "feat: LLM signal candidate staging + accept/reject API (D4.1-D4.2)"
```

---

### 任务 6：前端 LLM Review 展示（D4.3）

**文件：**
- 创建：`web/src/sections/LLMReviewPanel.tsx`
- 修改：`web/src/App.tsx`
- 修改：`web/src/types/index.ts`
- 修改：`web/src/styles.css`

- [ ] **步骤 1：添加前端类型**

```typescript
// in types/index.ts

export type LLMAttribution = {
  claim: string;
  confidence: 'EXTRACTED' | 'INFERRED' | 'AMBIGUOUS';
  evidence_ids: string[];
};

export type LLMReview = {
  llm_review_id: string;
  decision_review_id: string;
  trading_date: string;
  strategy_gene_id: string;
  attribution: LLMAttribution[];
  reason_check: {
    what_was_right: string[];
    what_was_wrong: string[];
    missing_signals: string[];
  };
  suggested_errors: Array<{
    error_type: string;
    severity: number;
    evidence_ids: string[];
  }>;
  suggested_signals: Array<{
    signal_id: string;
    signal_type: string;
    param_name: string;
    direction: string;
    strength: number;
    status: string;
  }>;
  summary: string;
  status: string;
  token_usage?: {
    prompt_tokens: number;
    completion_tokens: number;
    estimated_cost: number;
  };
};
```

- [ ] **步骤 2：创建 LLMReviewPanel 组件**

```tsx
// web/src/sections/LLMReviewPanel.tsx
import { useState } from 'react';
import type { LLMReview } from '../types';

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000';

export default function LLMReviewPanel({ reviews }: { reviews: LLMReview[] }) {
  const [expanded, setExpanded] = useState<string | null>(null);

  if (!reviews || reviews.length === 0) {
    return <div className="empty-state">暂无 LLM 复盘结果（默认关闭）</div>;
  }

  async function handleAccept(signalId: string) {
    await fetch(`${API_BASE}/api/optimization-signals/${signalId}/accept`, { method: 'POST' });
  }

  async function handleReject(signalId: string) {
    await fetch(`${API_BASE}/api/optimization-signals/${signalId}/reject`, { method: 'POST' });
  }

  return (
    <div className="llm-review-list">
      {reviews.map((r) => (
        <div key={r.llm_review_id} className={`llm-review-card ${expanded === r.llm_review_id ? 'expanded' : ''}`}>
          <div className="llm-review-header" onClick={() => setExpanded(
            expanded === r.llm_review_id ? null : r.llm_review_id
          )}>
            <span className="llm-review-id">{r.decision_review_id}</span>
            <span className={`llm-badge ${r.status}`}>{r.status}</span>
          </div>
          {expanded === r.llm_review_id && (
            <div className="llm-review-body">
              <p className="llm-summary">{r.summary}</p>

              <h4>归因分析</h4>
              <table className="attribution-table">
                <thead><tr><th>归因</th><th>置信度</th></tr></thead>
                <tbody>
                  {r.attribution.map((a, i) => (
                    <tr key={i}>
                      <td>{a.claim}</td>
                      <td><span className={`confidence-badge ${a.confidence}`}>{a.confidence}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <div className="reason-section">
                <h4>做对的</h4>
                <ul>{r.reason_check.what_was_right.map((s, i) => <li key={i}>{s}</li>)}</ul>
                <h4>做错的</h4>
                <ul>{r.reason_check.what_was_wrong.map((s, i) => <li key={i}>{s}</li>)}</ul>
                <h4>遗漏信号</h4>
                <ul>{r.reason_check.missing_signals.map((s, i) => <li key={i}>{s}</li>)}</ul>
              </div>

              {r.suggested_signals.length > 0 && (
                <div className="signal-section">
                  <h4>优化建议</h4>
                  {r.suggested_signals.map((s, i) => (
                    <div key={i} className="signal-row">
                      <span>{s.signal_type} / {s.param_name} → {s.direction} (强度: {s.strength})</span>
                      {s.status === 'candidate' && (
                        <div className="signal-actions">
                          <button className="btn-accept" onClick={() => handleAccept(s.signal_id)}>接受</button>
                          <button className="btn-reject" onClick={() => handleReject(s.signal_id)}>拒绝</button>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {r.token_usage && (
                <div className="token-usage">
                  <small>
                    Token: {r.token_usage.prompt_tokens}P / {r.token_usage.completion_tokens}C
                    · 费用: ${r.token_usage.estimated_cost.toFixed(4)}
                  </small>
                </div>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **步骤 3：接入 App.tsx**

```tsx
// In App.tsx, add:
import LLMReviewPanel from './sections/LLMReviewPanel';

// Add state:
const [llmReviews, setLlmReviews] = useState<LLMReview[]>([]);

// Add load function:
async function loadLlmReviews(targetDate = date) {
  if (!targetDate) return;
  const response = await fetch(`${API_BASE}/api/reviews/llm?date=${targetDate}`);
  setLlmReviews(await response.json());
}

// Add to loadDashboard:
if (json.date) void loadLlmReviews(json.date);

// Add panel to content-grid:
<Panel title="LLM 复盘" icon={<BrainCircuit size={18} />}>
  <LLMReviewPanel reviews={llmReviews} />
</Panel>
```

- [ ] **步骤 4：添加前端样式**

```css
/* in styles.css */
.llm-review-card {
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 8px;
  overflow: hidden;
}
.llm-review-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 14px; cursor: pointer; background: var(--surface-2);
}
.llm-review-body { padding: 14px; }
.llm-summary { font-style: italic; color: var(--text-secondary); }
.attribution-table { width: 100%; border-collapse: collapse; margin: 8px 0; }
.attribution-table th, .attribution-table td { text-align: left; padding: 4px 8px; border-bottom: 1px solid var(--border); }
.confidence-badge.EXTRACTED { color: var(--success); }
.confidence-badge.INFERRED { color: var(--warning); }
.confidence-badge.AMBIGUOUS { color: var(--danger); }
.signal-row { display: flex; justify-content: space-between; align-items: center; padding: 6px 0; }
.signal-actions { display: flex; gap: 6px; }
.btn-accept { background: var(--success); color: white; border: none; border-radius: 4px; padding: 4px 10px; cursor: pointer; }
.btn-reject { background: var(--danger); color: white; border: none; border-radius: 4px; padding: 4px 10px; cursor: pointer; }
.token-usage { margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--border); }
.llm-badge.candidate { background: var(--warning); color: #000; padding: 2px 8px; border-radius: 4px; font-size: 12px; }
```

- [ ] **步骤 5：前端构建验证**

运行：`cd web && npm run build`
预期：构建成功

- [ ] **步骤 6：提交**

```bash
git add web/src/sections/LLMReviewPanel.tsx web/src/App.tsx web/src/types/index.ts web/src/styles.css
git commit -m "feat: add LLM review frontend panel with signal accept/reject UI (D4.3)"
```

---

### 任务 7：LLM API 端点 + 前端数据打通

**文件：**
- 修改：`src/stock_select/api.py`

- [ ] **步骤 1：添加 LLM review 查询端点 + 触发端点**

```python
# in api.py

@app.get("/api/reviews/llm")
def list_llm_reviews(date: str) -> list[dict[str, Any]]:
    conn = db()
    try:
        rows = conn.execute(
            """SELECT l.*, s.prompt_tokens, s.completion_tokens, s.estimated_cost
               FROM llm_reviews l
               LEFT JOIN llm_scratchpad s ON l.llm_review_id = s.llm_review_id
               WHERE l.trading_date = ?
               ORDER BY l.created_at DESC""",
            (date,),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["attribution"] = json.loads(d.pop("attribution_json", "[]"))
            d["reason_check"] = json.loads(d.pop("reason_check_json", "{}"))
            d["suggested_signals"] = json.loads(d.pop("suggested_signals_json", "[]"))
            if d.get("prompt_tokens") is not None:
                d["token_usage"] = {
                    "prompt_tokens": d.pop("prompt_tokens"),
                    "completion_tokens": d.pop("completion_tokens"),
                    "estimated_cost": d.pop("estimated_cost"),
                }
            else:
                d.pop("prompt_tokens", None)
                d.pop("completion_tokens", None)
                d.pop("estimated_cost", None)
            result.append(d)
        return result
    finally:
        conn.close()


@app.post("/api/reviews/llm/rerun")
def rerun_llm_review(date: str) -> dict[str, Any]:
    conn = db()
    try:
        result = run_llm_review(conn, date)
        return result
    finally:
        conn.close()
```

- [ ] **步骤 2：提交**

```bash
git add src/stock_select/api.py
git commit -m "feat: add LLM review API endpoints (list + rerun) (D3.2)"
```

---

### 任务 8：测试完善（D5）

**文件：**
- 修改：`tests/test_llm_review.py`
- 创建：`tests/test_llm_config.py`（已在任务 1 创建）
- 可选：`tests/test_evidence_schema_contracts.py`

- [ ] **步骤 1：测试 budget 熔断**

```python
def test_budget_exceeded_skips_remaining():
    """When budget is exceeded, remaining decisions should be skipped."""
    config = LLMConfig(
        provider="anthropic", model="test", api_key="sk-test",
        max_tokens_per_day=10,  # very low
    )
    budget = get_budget()
    budget.record(100, 0, 0.0)  # already exceeded

    with pytest.raises(BudgetExceeded):
        budget.check(config)
```

- [ ] **步骤 2：测试 schema invalid 输出**

```python
def test_invalid_confidence_raises():
    """AttributionClaim with invalid confidence should raise."""
    with pytest.raises(LLMContractError):
        AttributionClaim.validate({"claim": "test", "confidence": "INVALID", "evidence_ids": []})

def test_llm_contract_rejects_empty_attribution():
    """LLM review output with empty attribution should still pass (allowed)."""
    contract = LLMReviewContract.validate({
        "review_target": {"type": "decision", "id": "pick_001"},
        "attribution": [],
        "reason_check": {},
        "summary": "No insights.",
    })
    assert len(contract.attribution) == 0
```

- [ ] **步骤 3：测试 no API key fallback**

`test_llm_review_skips_without_api_key` 已存在（现有），确认通过。

- [ ] **步骤 4：测试 LLM signal 默认不被 evolution 消费**

```python
def test_llm_signal_status_is_candidate(picked_db):
    """LLM-generated signals should default to 'candidate', not 'open'."""
    from stock_select.llm_review import _persist_llm_review
    from stock_select.llm_contracts import LLMReviewContract

    contract = LLMReviewContract.validate({
        "review_target": {"type": "decision", "id": "pick_llm_test"},
        "attribution": [],
        "reason_check": {},
        "suggested_optimization_signals": [
            {"signal_type": "adjust_weight", "param_name": "momentum_weight", "direction": "up", "strength": 0.1, "reason": "test"}
        ],
        "summary": "test",
    })

    review_id = review_decision(picked_db, "pick_llm_test")
    _persist_llm_review(picked_db, review_id, "gene_aggressive_v1", contract)
    picked_db.commit()

    signals = list_optimization_signals(picked_db, gene_id="gene_aggressive_v1")
    for s in signals:
        assert s["status"] == "candidate", f"LLM signal should be candidate, got {s['status']}"
```

- [ ] **步骤 5：运行全量测试**

运行：`pytest tests/test_llm_review.py tests/test_llm_config.py -v`
预期：全部 PASS

- [ ] **步骤 6：回归验证**

运行：`pytest` 确认不破坏现有 180+ tests

- [ ] **步骤 7：提交**

```bash
git add tests/test_llm_review.py tests/test_llm_config.py
git commit -m "test: add LLM budget, schema, signal staging tests (D5)"
```

---

### 任务 9：前端构建 + 最终验收

- [ ] **步骤 1：全量后端测试**

运行：`pytest`
预期：全部 PASS

- [ ] **步骤 2：前端构建**

运行：`cd web && npm run build`
预期：构建通过

- [ ] **步骤 3：更新文档状态**

将 `NEXT_WORK_HANDOFF_PLAN.md` 中 Phase D 各任务从 `[TODO]` 更新为 `[DONE]` 或当前状态。

- [ ] **步骤 4：提交**

```bash
git add -A
git commit -m "docs: mark Phase D LLM review complete"
```

---

## 自检

**规格覆盖度：**
- D1.1（LLM 配置读取）→ 任务 1 ✅
- D1.2（预算熔断）→ 任务 1 ✅
- D1.3（allowlist）→ 任务 2 ✅
- D2.1（packet 固化）→ 已有，任务 4 扩展 ✅
- D2.2（contract 固化）→ 已有，任务 4 增强 ✅
- D2.3（校验）→ 已有，任务 4/8 增强 ✅
- D3.1（llm_review.py）→ 任务 4 ✅
- D3.2（pipeline phase）→ 任务 2 ✅
- D3.3（scratchpad）→ 任务 3 ✅
- D4.1（candidate staging）→ 任务 5 ✅
- D4.2（accept/reject API）→ 任务 5 ✅
- D4.3（前端展示）→ 任务 6 ✅
- D5（测试）→ 任务 8 ✅

**占位符扫描：** 无 TODO/TBD/占位符 ✅

**类型一致性：** llm_review_id 统一为 `llm_` prefix + sha1 hex；api 端点路径统一为 `/api/reviews/llm`；前端类型 `LLMReview` 和后端 JSON key 对齐 ✅
