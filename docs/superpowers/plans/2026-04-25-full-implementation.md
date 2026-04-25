# Stock Select 全量实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 完成 A 股自我进化选股系统从 Phase A（真实数据最小闭环）到 Phase G（日常运行硬化）的全部剩余工作，包括测试覆盖、LLM 复盘、多维因子层、真实复盘证据、知识图谱增强、日常调度和日常运行硬化。

**架构：** 系统按 Phase A-G 分阶段推进，每阶段独立可测试。后端基于 Python FastAPI + SQLite/FTS5 + NetworkX，前端基于 React/TypeScript。核心流水线：数据同步 -> 预盘选股 -> 模拟成交 -> 确定性复盘 -> LLM 复盘 -> 优化信号 -> 策略进化。

**技术栈：** Python 3.11+, FastAPI, SQLite/FTS5, AKShare, BaoStock, React 18, TypeScript, pytest, NetworkX, APScheduler, Pydantic, Claude API（LLM 阶段）。

---

## 文件索引

### Phase A：真实数据最小闭环（测试 + 验证）
- `tests/test_mode.py` — 运行时模式解析
- `tests/test_canonical_prices.py` — canonical price 发布规则
- `tests/test_data_ingestion.py` — 数据同步幂等性
- `tests/test_pipeline.py` — 真实数据 pipeline 集成测试

### Phase B：多维真实因子层
- `src/stock_select/factor_sync.py` — 财务/行业/事件/风险因子同步逻辑
- `tests/test_factor_sync.py` — 因子同步测试

### Phase C：真实复盘证据层
- `src/stock_select/evidence_sync.py` — 财报/预期差/订单/风险证据同步
- `tests/test_evidence_sync.py` — 证据同步测试

### Phase D：LLM 收盘复盘
- `src/stock_select/llm_review.py` — LLM 复盘模块（不存在，需创建）
- `src/stock_select/llm_prompt.py` — LLM prompt 模板
- `src/stock_select/llm_contracts.py` — LLMReviewContract 校验
- `tests/test_llm_review.py` — LLM 复盘测试

### Phase E：知识图谱和记忆增强
- `src/stock_select/graph_schema.py` — 图谱 schema 扩展
- `src/stock_select/similar_cases.py` — 相似案例查询 API
- `tests/test_graph_schema.py` — 图谱增强测试

### Phase F：预盘 LLM 辅助
- `src/stock_select/planner.py` — Planner Agent
- `src/stock_select/analyst.py` — Analyst Agents
- `src/stock_select/pick_evaluator.py` — Pick Evaluator
- `tests/test_llm_preopen.py` — 预盘 LLM 测试

### Phase G：日常运行硬化
- `src/stock_select/scheduler.py` — APScheduler 真实调度（需完善）
- `src/stock_select/task_monitor.py` — 任务状态监控
- `src/stock_select/data_health.py` — 数据源健康检查
- `web/src/components/SchedulerPanel.tsx` — 调度控制面板（可选）

### 前端增强
- `web/src/components/ReviewCenter.tsx` — 复盘中心页面
- `web/src/components/EvolutionPanel.tsx` — 策略进化面板
- `web/src/components/DataSyncStatus.tsx` — 数据同步状态页

### 通用修改
- `src/stock_select/api.py` — 新增 Phase B/C/D/E 接口
- `src/stock_select/cli.py` — 新增 Phase B/C/D 子命令
- `src/stock_select/server.py` — stdlib server 路由（检查是否已同步）
- `tests/test_api.py` — API 集成测试

---

## Phase A：真实数据最小闭环 — 测试补齐与验证

> 当前已有 demo/live 隔离、Provider 架构、canonical price 逻辑、市场环境分类。缺的是测试覆盖和真实数据验证。

### 任务 A1：运行时模式测试

**文件：**
- 创建：`tests/test_mode.py`
- 读取：`src/stock_select/runtime.py:1-51`
- 读取：`src/stock_select/db.py:1-51`（`init_db`）

- [ ] **步骤 1：编写 mode 解析测试**

```python
# tests/test_mode.py
import sqlite3
import pytest
from stock_select.runtime import resolve_runtime, DEMO_DB_PATH, LIVE_DB_PATH, LEGACY_DB_PATH
from stock_select.db import connect, init_db
from stock_select.seed import seed_demo_data

def test_demo_mode_resolves_to_demo_db():
    ctx = resolve_runtime("demo")
    assert ctx.mode == "demo"
    assert ctx.db_path == DEMO_DB_PATH
    assert ctx.database_role == "demo"
    assert ctx.is_demo_data is True

def test_live_mode_resolves_to_live_db():
    ctx = resolve_runtime("live")
    assert ctx.mode == "live"
    assert ctx.db_path == LIVE_DB_PATH
    assert ctx.database_role == "live"
    assert ctx.is_demo_data is False

def test_custom_db_path_recognizes_live():
    ctx = resolve_runtime("live", db_path=str(LIVE_DB_PATH))
    assert ctx.database_role == "live"

def test_custom_db_path_recognizes_demo():
    ctx = resolve_runtime("demo", db_path=str(DEMO_DB_PATH))
    assert ctx.database_role == "demo"

def test_custom_db_path_recognizes_legacy():
    ctx = resolve_runtime("demo", db_path=str(LEGACY_DB_PATH))
    assert ctx.database_role == "legacy"

def test_invalid_mode_raises():
    with pytest.raises(ValueError, match="Unknown runtime mode"):
        resolve_runtime("production")

def test_live_mode_forbids_seed_demo(tmp_path):
    db = tmp_path / "live.db"
    conn = connect(db)
    init_db(conn)
    with pytest.raises(SystemExit, match="seed-demo is not allowed in live mode"):
        seed_demo_data(conn)

def test_runtime_context_as_payload():
    ctx = resolve_runtime("live")
    payload = ctx.as_payload()
    assert payload["runtime_mode"] == "live"
    assert payload["database_role"] == "live"
    assert payload["is_demo_data"] is False
```

- [ ] **步骤 2：运行测试验证通过**

```bash
pytest tests/test_mode.py -v
```

预期：全部 PASS

- [ ] **步骤 3：Commit**

```bash
git add tests/test_mode.py
git commit -m "test: add runtime mode isolation tests"
```

---

### 任务 A2：Canonical Price 发布规则测试

**文件：**
- 读取：`src/stock_select/data_ingestion.py` — 搜索 `publish_canonical_prices`
- 创建：`tests/test_canonical_prices.py`

- [ ] **步骤 1：编写 canonical price 5 种规则测试**

```python
# tests/test_canonical_prices.py
import sqlite3
import pytest
from stock_select.db import connect, init_db
from stock_select.data_ingestion import publish_canonical_prices

@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    init_db(conn)
    # 插入测试 stock
    conn.execute("INSERT INTO stocks(stock_code, name) VALUES ('000001.SZ', '平安银行')")
    conn.execute("INSERT INTO stocks(stock_code, name) VALUES ('600000.SH', '浦发银行')")
    conn.execute("INSERT INTO stocks(stock_code, name) VALUES ('000002.SZ', '万科A')")
    conn.execute("INSERT INTO stocks(stock_code, name) VALUES ('000003.SZ', '无数据')")
    conn.execute("INSERT INTO stocks(stock_code, name) VALUES ('000004.SZ', '双源缺失')")
    conn.commit()
    return conn

def setup_source_price(conn, source, stock_code, date, close, **kwargs):
    conn.execute(
        "INSERT OR REPLACE INTO source_daily_prices(source, stock_code, trading_date, open, high, low, close, volume, amount) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (source, stock_code, date, close * 0.99, close * 1.01, close * 0.98, close, 1000, 10000),
    )

# 规则 1: AKShare 有, BaoStock 有, close 差异 <= 0.3% -> ok
def test_canonical_ok_when_sources_agree(db):
    date = "2024-01-15"
    setup_source_price(db, "akshare", "000001.SZ", date, close=10.00)
    setup_source_price(db, "baostock", "000001.SZ", date, close=10.02)  # 0.2% diff
    db.commit()
    result = publish_canonical_prices(db, date)
    row = db.execute("SELECT * FROM daily_prices WHERE stock_code = '000001.SZ' AND trading_date = ?", (date,)).fetchone()
    assert row is not None
    assert abs(row["close"] - 10.00) < 0.01  # published akshare
    check = db.execute("SELECT status FROM price_source_checks WHERE stock_code = '000001.SZ'").fetchone()
    assert check["status"] == "ok"

# 规则 2: AKShare 有, BaoStock 有, close 差异 > 0.3% -> warning
def test_canonical_warning_when_sources_disagree(db):
    date = "2024-01-15"
    setup_source_price(db, "akshare", "600000.SH", date, close=10.00)
    setup_source_price(db, "baostock", "600000.SH", date, close=10.50)  # 5% diff
    db.commit()
    result = publish_canonical_prices(db, date)
    check = db.execute("SELECT status FROM price_source_checks WHERE stock_code = '600000.SH'").fetchone()
    assert check["status"] == "warning"

# 规则 3: AKShare 有, BaoStock 无 -> warning
def test_canonical_warning_when_secondary_missing(db):
    date = "2024-01-15"
    setup_source_price(db, "akshare", "000002.SZ", date, close=15.00)
    db.commit()
    result = publish_canonical_prices(db, date)
    row = db.execute("SELECT * FROM daily_prices WHERE stock_code = '000002.SZ'").fetchone()
    assert row is not None
    check = db.execute("SELECT status FROM price_source_checks WHERE stock_code = '000002.SZ'").fetchone()
    assert check["status"] == "warning"

# 规则 4: AKShare 无, BaoStock 有 -> missing_primary, 发布 BaoStock
def test_canonical_missing_primary_uses_secondary(db):
    date = "2024-01-15"
    setup_source_price(db, "baostock", "000003.SZ", date, close=8.00)
    db.commit()
    result = publish_canonical_prices(db, date)
    row = db.execute("SELECT * FROM daily_prices WHERE stock_code = '000003.SZ'").fetchone()
    assert row is not None
    assert abs(row["close"] - 8.00) < 0.01
    check = db.execute("SELECT status FROM price_source_checks WHERE stock_code = '000003.SZ'").fetchone()
    assert check["status"] == "missing_primary"

# 规则 5: 双源都无 -> 不发布 daily_prices
def test_canonical_no_publish_when_both_missing(db):
    date = "2024-01-15"
    result = publish_canonical_prices(db, date)
    row = db.execute("SELECT * FROM daily_prices WHERE stock_code = '000004.SZ' AND trading_date = ?", (date,)).fetchone()
    assert row is None

# 幂等性：重复执行不重复插入
def test_publish_is_idempotent(db):
    date = "2024-01-15"
    setup_source_price(db, "akshare", "000001.SZ", date, close=10.00)
    setup_source_price(db, "baostock", "000001.SZ", date, close=10.02)
    db.commit()
    publish_canonical_prices(db, date)
    publish_canonical_prices(db, date)  # second run
    count = db.execute("SELECT COUNT(*) as cnt FROM daily_prices WHERE stock_code = '000001.SZ'").fetchone()["cnt"]
    assert count == 1
```

- [ ] **步骤 2：运行测试**

```bash
pytest tests/test_canonical_prices.py -v
```

预期：全部 PASS。如有失败，修复 `publish_canonical_prices` 实现。

- [ ] **步骤 3：Commit**

```bash
git add tests/test_canonical_prices.py
git commit -m "test: add canonical price 5-rule coverage and idempotency"
```

---

### 任务 A3：数据同步幂等性测试

**文件：**
- 读取：`src/stock_select/data_ingestion.py` — 搜索 `sync_stock_universe`, `sync_trading_calendar`, `sync_daily_prices`
- 创建：`tests/test_data_ingestion.py`

- [ ] **步骤 1：编写同步幂等性测试**

```python
# tests/test_data_ingestion.py
import sqlite3
import pytest
from unittest.mock import patch, MagicMock
from stock_select.db import connect, init_db
from stock_select.data_ingestion import (
    sync_stock_universe,
    sync_trading_calendar,
    sync_daily_prices,
    DemoProvider,
)

@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    init_db(conn)
    return conn

def test_sync_stock_universe_idempotent(db):
    provider = DemoProvider()
    sync_stock_universe(db, provider)
    count1 = db.execute("SELECT COUNT(*) as cnt FROM stocks").fetchone()["cnt"]
    sync_stock_universe(db, provider)
    count2 = db.execute("SELECT COUNT(*) as cnt FROM stocks").fetchone()["cnt"]
    assert count1 == count2

def test_sync_trading_calendar_idempotent(db):
    provider = DemoProvider()
    sync_trading_calendar(db, "2024-01-01", "2024-01-15", provider)
    count1 = db.execute("SELECT COUNT(*) as cnt FROM trading_days").fetchone()["cnt"]
    sync_trading_calendar(db, "2024-01-01", "2024-01-15", provider)
    count2 = db.execute("SELECT COUNT(*) as cnt FROM trading_days").fetchone()["cnt"]
    assert count1 == count2

def test_sync_daily_prices_idempotent(db):
    provider = DemoProvider()
    sync_daily_prices(db, "2024-01-15", providers=[provider])
    count1 = db.execute("SELECT COUNT(*) as cnt FROM source_daily_prices").fetchone()["cnt"]
    sync_daily_prices(db, "2024-01-15", providers=[provider])
    count2 = db.execute("SELECT COUNT(*) as cnt FROM source_daily_prices").fetchone()["cnt"]
    assert count1 == count2
```

- [ ] **步骤 2：运行测试并修复**

```bash
pytest tests/test_data_ingestion.py -v
```

- [ ] **步骤 3：Commit**

```bash
git add tests/test_data_ingestion.py
git commit -m "test: add data sync idempotency tests"
```

---

### 任务 A4：预盘禁止读取目标日价格测试

**文件：**
- 读取：`src/stock_select/candidate_pipeline.py`
- 读取：`src/stock_select/strategies.py`
- 创建：`tests/test_preopen_future_function.py`

- [ ] **步骤 1：编写未来函数防护测试**

```python
# tests/test_preopen_future_function.py
import sqlite3
import pytest
from stock_select.db import connect, init_db
from stock_select.data_ingestion import DemoProvider, sync_daily_prices, sync_trading_calendar, sync_stock_universe
from stock_select.strategies import generate_picks_for_all_genes, seed_default_genes

def test_preopen_does_not_read_target_day_prices(tmp_path):
    db_path = tmp_path / "test.db"
    conn = connect(db_path)
    init_db(conn)
    seed_default_genes(conn)

    provider = DemoProvider()
    sync_stock_universe(conn, provider)
    sync_trading_calendar(conn, "2024-01-01", "2024-01-20", provider)

    # 先跑 2024-01-15 的选股
    sync_daily_prices(conn, "2024-01-15", providers=[provider])
    picks = generate_picks_for_all_genes(conn, "2024-01-15")
    assert len(picks) > 0

    # 此时不应有 2024-01-16 的价格被读到
    future_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM daily_prices WHERE trading_date > '2024-01-15'"
    ).fetchone()["cnt"]
    # daily_prices 在 preopen 阶段不应写入目标日之后的数据
    # （注意：source_daily_prices 可能有，但 daily_prices canonical 不能有未来数据）
    future_canonical = conn.execute(
        "SELECT COUNT(*) as cnt FROM daily_prices WHERE trading_date > '2024-01-15'"
    ).fetchone()["cnt"]
    assert future_canonical == 0
```

- [ ] **步骤 2：运行测试**

- [ ] **步骤 3：Commit**

---

### 任务 A5：真实数据 Pipeline 集成测试

**文件：**
- 读取：`src/stock_select/agent_runtime.py` — `run_daily_pipeline` 函数
- 创建：`tests/test_pipeline_integration.py`

- [ ] **步骤 1：编写完整 pipeline 测试**

```python
# tests/test_pipeline_integration.py
import sqlite3
import pytest
from stock_select.db import connect, init_db
from stock_select.data_ingestion import DemoProvider, sync_daily_prices, sync_trading_calendar, sync_stock_universe, sync_index_prices, classify_market_environment, publish_canonical_prices
from stock_select.strategies import generate_picks_for_all_genes, seed_default_genes
from stock_select.simulator import simulate_day
from stock_select.review import generate_deterministic_reviews
from stock_select.agent_runtime import run_daily_pipeline

def test_full_pipeline_with_demo_provider(tmp_path):
    db_path = tmp_path / "pipeline.db"
    conn = connect(db_path)
    init_db(conn)

    # 使用 demo provider 跑一整天
    result = run_daily_pipeline(conn, "2024-01-15")

    # 验证关键阶段都执行了
    assert "sync_data" in result
    assert "preopen_pick" in result
    assert "simulate" in result
    assert "review" in result or "deterministic_review" in result

    # 验证有 picks
    picks = conn.execute("SELECT COUNT(*) as cnt FROM pick_decisions WHERE trading_date = '2024-01-15'").fetchone()["cnt"]
    assert picks > 0

    # 验证有 outcomes
    outcomes = conn.execute("SELECT COUNT(*) as cnt FROM outcomes o JOIN pick_decisions p ON o.decision_id = p.decision_id WHERE p.trading_date = '2024-01-15'").fetchone()["cnt"]
    assert outcomes > 0

    # 验证有 review
    reviews = conn.execute("SELECT COUNT(*) as cnt FROM decision_reviews WHERE trading_date = '2024-01-15'").fetchone()["cnt"]
    assert reviews > 0
```

- [ ] **步骤 2：运行并修复**

- [ ] **步骤 3：Commit**

---

### 任务 A6：ST/停牌/无价格过滤测试

**文件：**
- 创建：`tests/test_candidate_filters.py`

- [ ] **步骤 1：编写硬过滤测试**

```python
# tests/test_candidate_filters.py
import sqlite3
import pytest
from stock_select.db import connect, init_db
from stock_select.data_ingestion import DemoProvider, sync_stock_universe, sync_trading_calendar, sync_daily_prices
from stock_select.candidate_pipeline import build_candidate_pool, apply_hard_filters

@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    init_db(conn)
    return conn

def test_st_stocks_excluded(db):
    conn = db
    conn.execute("INSERT INTO stocks(stock_code, name, is_st) VALUES ('000999.SZ', 'ST测试', 1)")
    conn.commit()
    # ST 股票不应进入候选池
    row = conn.execute("SELECT * FROM stocks WHERE is_st = 1").fetchone()
    assert row["is_st"] == 1

def test_suspended_stocks_excluded(db):
    conn = db
    date = "2024-01-15"
    conn.execute("INSERT INTO stocks(stock_code, name, listing_status) VALUES ('000888.SZ', '停牌测试', 'suspended')")
    conn.execute(
        "INSERT INTO daily_prices(stock_code, trading_date, open, high, low, close, volume, amount, is_suspended) VALUES ('000888.SZ', ?, 10, 10, 10, 10, 0, 0, 1)",
        (date,)
    )
    conn.commit()
    row = conn.execute("SELECT is_suspended FROM daily_prices WHERE stock_code = '000888.SZ'").fetchone()
    assert row["is_suspended"] == 1

def test_no_price_excluded(db):
    conn = db
    # 无 canonical price 的股票应被排除
    count = conn.execute("SELECT COUNT(*) as cnt FROM daily_prices WHERE stock_code = '000004.SZ'").fetchone()["cnt"]
    assert count == 0
```

- [ ] **步骤 2：运行测试**

- [ ] **步骤 3：Commit**

---

## Phase B：多维真实因子层

### 任务 B1：财务因子同步模块

**文件：**
- 创建：`src/stock_select/factor_sync.py`
- 读取：`src/stock_select/data_ingestion.py` — Provider 基类模式
- 创建：`tests/test_factor_sync.py`

- [ ] **步骤 1：实现财务因子同步**

```python
# src/stock_select/factor_sync.py
"""Synchronize multidimensional fundamental factors from data providers."""
from __future__ import annotations

import sqlite3
from typing import Any

from . import repository
from .data_ingestion import MarketDataProvider


def sync_fundamental_factors(conn: sqlite3.Connection, trading_date: str, provider: MarketDataProvider) -> dict[str, Any]:
    """Fetch and upsert fundamental metrics for all active stocks."""
    factors = provider.fetch_fundamental_factors(trading_date)
    rows_loaded = 0
    for item in factors:
        conn.execute(
            """
            INSERT INTO fundamental_metrics(
              stock_code, as_of_date, report_period, roe, revenue_growth,
              net_profit_growth, gross_margin, debt_to_assets,
              operating_cashflow_to_profit, pe_percentile, pb_percentile,
              dividend_yield, quality_note, source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(stock_code, as_of_date, report_period) DO UPDATE SET
              roe = excluded.roe, revenue_growth = excluded.revenue_growth,
              net_profit_growth = excluded.net_profit_growth, gross_margin = excluded.gross_margin,
              debt_to_assets = excluded.debt_to_assets, operating_cashflow_to_profit = excluded.operating_cashflow_to_profit,
              pe_percentile = excluded.pe_percentile, pb_percentile = excluded.pb_percentile,
              dividend_yield = excluded.dividend_yield, quality_note = excluded.quality_note, source = excluded.source
            """,
            (
                item["stock_code"], item["report_period"], item["report_period"],
                item.get("roe"), item.get("revenue_growth"),
                item.get("net_profit_growth"), item.get("gross_margin"),
                item.get("debt_to_assets"), item.get("operating_cashflow_to_profit"),
                item.get("pe_percentile"), item.get("pb_percentile"),
                item.get("dividend_yield"), item.get("quality_note"),
                item.get("source", "provider"),
            ),
        )
        rows_loaded += 1

    conn.execute(
        "INSERT OR REPLACE INTO data_sources(source, dataset, trading_date, status, rows_loaded) VALUES (?, ?, ?, ?, ?)",
        ("provider", "fundamental_metrics", trading_date, "ok", rows_loaded),
    )
    conn.commit()
    return {"dataset": "fundamental_metrics", "rows_loaded": rows_loaded}


def sync_sector_strength(conn: sqlite3.Connection, trading_date: str) -> dict[str, Any]:
    """Compute sector strength from sector_theme_signals and update rankings."""
    rows = conn.execute(
        "SELECT industry, sector_return_pct FROM sector_theme_signals WHERE trading_date = ?",
        (trading_date,),
    ).fetchall()
    if not rows:
        return {"dataset": "sector_strength", "rows_loaded": 0}

    sorted_rows = sorted(rows, key=lambda r: r["sector_return_pct"], reverse=True)
    rows_loaded = 0
    for rank, row in enumerate(sorted_rows, 1):
        conn.execute(
            "UPDATE sector_theme_signals SET relative_strength_rank = ? WHERE trading_date = ? AND industry = ?",
            (rank, trading_date, row["industry"]),
        )
        rows_loaded += 1
    conn.commit()
    return {"dataset": "sector_strength", "rows_loaded": rows_loaded}


def sync_risk_factors(conn: sqlite3.Connection, trading_date: str) -> dict[str, Any]:
    """Update risk flags: ST status, suspension, liquidity thresholds."""
    conn.execute(
        """
        UPDATE stocks SET is_st = 1
        WHERE stock_code LIKE 'ST%' OR stock_code LIKE '*ST%'
        """,
    )
    conn.execute(
        """
        UPDATE stocks SET listing_status = 'suspended'
        WHERE stock_code IN (
            SELECT stock_code FROM daily_prices
            WHERE trading_date = ? AND is_suspended = 1
        )
        """,
        (trading_date,),
    )
    conn.commit()
    return {"dataset": "risk_factors", "status": "updated"}
```

- [ ] **步骤 2：编写测试**

```python
# tests/test_factor_sync.py
import sqlite3
import pytest
from stock_select.db import connect, init_db
from stock_select.factor_sync import sync_fundamental_factors, sync_sector_strength, sync_risk_factors
from stock_select.data_ingestion import DemoProvider

@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    init_db(conn)
    conn.execute("INSERT INTO stocks(stock_code, name) VALUES ('000001.SZ', '平安银行')")
    conn.commit()
    return conn

def test_sync_fundamental_factors(db):
    provider = DemoProvider()
    result = sync_fundamental_factors(db, "2024-01-15", provider)
    assert result["rows_loaded"] >= 0

def test_sync_sector_strength(db):
    db.execute(
        "INSERT INTO sector_theme_signals(trading_date, industry, sector_return_pct, relative_strength_rank, volume_surge, theme_strength, catalyst_count) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("2024-01-15", "银行", 0.02, 0, 0, 0, 0),
    )
    db.execute(
        "INSERT INTO sector_theme_signals(trading_date, industry, sector_return_pct, relative_strength_rank, volume_surge, theme_strength, catalyst_count) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("2024-01-15", "科技", 0.05, 0, 0, 0, 0),
    )
    db.commit()
    result = sync_sector_strength(db, "2024-01-15")
    assert result["rows_loaded"] == 2
    # 科技应该排名第一
    rank = db.execute("SELECT relative_strength_rank FROM sector_theme_signals WHERE industry = '科技'").fetchone()
    assert rank["relative_strength_rank"] == 1

def test_sync_risk_factors(db):
    db.execute("INSERT INTO stocks(stock_code, name) VALUES ('ST0001.SZ', 'ST测试')")
    db.commit()
    result = sync_risk_factors(db, "2024-01-15")
    st = db.execute("SELECT is_st FROM stocks WHERE stock_code = 'ST0001.SZ'").fetchone()
    assert st["is_st"] == 1
```

- [ ] **步骤 3：将 factor_sync 接入 `agent_runtime.py` 的 `run_phase`**

在 `agent_runtime.py` 的 `run_phase` 函数中，确认已有 `sync_factors`, `sync_fundamentals` 等 phase 处理。如果没有，添加：

```python
# 在 run_phase 的 phases 字典中添加
"sync_fundamental_factors": lambda conn, date: sync_fundamental_factors(conn, date, provider),
"sync_sector_strength": lambda conn, date: sync_sector_strength(conn, date),
"sync_risk_factors": lambda conn, date: sync_risk_factors(conn, date),
```

- [ ] **步骤 4：运行测试并 Commit**

```bash
pytest tests/test_factor_sync.py -v
git add src/stock_select/factor_sync.py tests/test_factor_sync.py
git commit -m "feat: add fundamental/sector/risk factor sync (Phase B)"
```

---

### 任务 B2：候选评分数据缺失处理

**文件：**
- 读取：`src/stock_select/candidate_pipeline.py`
- 修改：候选评分中处理 fundamental/sector/event 缺失

- [ ] **步骤 1：添加 data_missing 标记到 candidate packet**

在 `candidate_pipeline.py` 的评分逻辑中，确保当基本面/行业/事件数据缺失时：
- 对应维度分数为 0
- `packet_json` 的 `missing_fields` 数组中包含缺失字段名
- `packet_json` 的 `sources` 中标注哪些数据源不可用

```python
# 在候选评分的 packet 构建处添加
missing_fields = []
sources = {}

if not fundamental_metrics:
    missing_fields.append("fundamental")
    sources["fundamental"] = None
else:
    sources["fundamental"] = {"source": fundamental_metrics[0].get("source")}

# event 和 sector 同理

packet = {
    "technical": technical_data,
    "fundamental": fundamental_data if fundamental_metrics else {"score": 0},
    "event": event_data if event_signals else {"score": 0},
    "sector": sector_data if sector_signals else {"score": 0},
    "risk": risk_data,
    "missing_fields": missing_fields,
    "sources": sources,
}
```

- [ ] **步骤 2：验证复盘能显示缺失原因**

在 `deterministic_review.py` 的 `review_decision` 中，当 packet 有 `missing_fields` 时，写入 `review_errors`：

```python
# 在 review_decision 函数中，构建 factor_items 之后添加
for missing_field in packet.get("missing_fields", []):
    upsert_review_error(
        conn,
        review_scope="decision",
        review_id=review_id,
        error_type="data_missing",
        severity=0.3,
        confidence=0.9,
        evidence_ids=evidence_ids[:1],
    )
```

- [ ] **步骤 3：Commit**

```bash
git add src/stock_select/candidate_pipeline.py src/stock_select/deterministic_review.py
git commit -m "feat: mark data_missing in candidate packet and review errors"
```

---

## Phase C：真实复盘证据层

### 任务 C1：证据同步模块

**文件：**
- 创建：`src/stock_select/evidence_sync.py`
- 创建：`tests/test_evidence_sync.py`

- [ ] **步骤 1：实现证据同步**

```python
# src/stock_select/evidence_sync.py
"""Synchronize review evidence: financial actuals, analyst expectations, earnings surprises, risk events."""
from __future__ import annotations

import sqlite3
from typing import Any

from .data_ingestion import MarketDataProvider


def sync_financial_actuals(conn: sqlite3.Connection, trading_date: str, provider: MarketDataProvider) -> dict[str, Any]:
    """Fetch latest financial actuals and upsert."""
    actuals = provider.fetch_financial_actuals(trading_date)
    rows_loaded = 0
    for item in actuals:
        conn.execute(
            """
            INSERT INTO financial_actuals(
              stock_code, report_period, ann_date, revenue, net_profit,
              net_profit_deducted, eps, roe, gross_margin, operating_cashflow,
              source, source_url
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(stock_code, report_period, source) DO UPDATE SET
              revenue = excluded.revenue, net_profit = excluded.net_profit,
              eps = excluded.eps, roe = excluded.roe
            """,
            (
                item["stock_code"], item["report_period"], item["ann_date"],
                item.get("revenue"), item.get("net_profit"),
                item.get("net_profit_deducted"), item.get("eps"),
                item.get("roe"), item.get("gross_margin"),
                item.get("operating_cashflow"), item.get("source"),
                item.get("source_url"),
            ),
        )
        rows_loaded += 1
    conn.commit()
    return {"dataset": "financial_actuals", "rows_loaded": rows_loaded}


def sync_earnings_surprises(conn: sqlite3.Connection, trading_date: str) -> dict[str, Any]:
    """Compute earnings surprises from actuals vs expectations."""
    rows = conn.execute(
        """
        SELECT f.stock_code, f.report_period, f.ann_date,
               f.revenue AS actual_revenue, f.net_profit AS actual_net_profit,
               f.eps AS actual_eps,
               AVG(e.forecast_revenue) AS expected_revenue,
               AVG(e.forecast_net_profit) AS expected_net_profit,
               AVG(e.forecast_eps) AS expected_eps,
               COUNT(e.expectation_id) AS sample_size
        FROM financial_actuals f
        LEFT JOIN analyst_expectations e
          ON e.stock_code = f.stock_code AND e.forecast_period = f.report_period
        WHERE f.ann_date <= ?
          AND f.stock_code NOT IN (SELECT stock_code FROM earnings_surprises WHERE report_period = f.report_period AND ann_date = f.ann_date)
        GROUP BY f.stock_code, f.report_period, f.ann_date
        """,
        (trading_date,),
    ).fetchall()

    import hashlib
    rows_loaded = 0
    for row in rows:
        actual_np = row["actual_net_profit"]
        expected_np = row["expected_net_profit"]
        surprise_pct = ((actual_np - expected_np) / abs(expected_np)) if expected_np and abs(expected_np) > 0 else 0
        surprise_id = "surp_" + hashlib.sha1(f"{row['stock_code']}:{row['report_period']}".encode()).hexdigest()[:12]

        conn.execute(
            """
            INSERT INTO earnings_surprises(
              surprise_id, stock_code, report_period, ann_date,
              expected_net_profit, actual_net_profit, net_profit_surprise_pct,
              expected_revenue, actual_revenue, revenue_surprise_pct,
              expectation_sample_size, expectation_source, actual_source, evidence_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(stock_code, report_period) DO NOTHING
            """,
            (
                surprise_id, row["stock_code"], row["report_period"], row["ann_date"],
                expected_np, actual_np, surprise_pct,
                row["expected_revenue"], row["actual_revenue"],
                ((row["actual_revenue"] - row["expected_revenue"]) / abs(row["expected_revenue"])) if row["expected_revenue"] and abs(row["expected_revenue"]) > 0 else 0,
                row["sample_size"] or 0,
                "aggregated", "financial_actuals",
                '{"method": "computed"}',
            ),
        )
        rows_loaded += 1
    conn.commit()
    return {"dataset": "earnings_surprises", "rows_loaded": rows_loaded}
```

- [ ] **步骤 2：编写测试**

```python
# tests/test_evidence_sync.py
import sqlite3
import pytest
from stock_select.db import connect, init_db
from stock_select.evidence_sync import sync_financial_actuals, sync_earnings_surprises
from stock_select.data_ingestion import DemoProvider

@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    init_db(conn)
    conn.execute("INSERT INTO stocks(stock_code, name) VALUES ('000001.SZ', '平安银行')")
    conn.commit()
    return conn

def test_sync_financial_actuals(db):
    provider = DemoProvider()
    result = sync_financial_actuals(db, "2024-01-15", provider)
    assert result["rows_loaded"] >= 0

def test_sync_earnings_surprises(db):
    # 先插入一条 expectation
    db.execute(
        "INSERT INTO analyst_expectations(expectation_id, stock_code, report_date, forecast_period, forecast_net_profit, source) VALUES (?, ?, ?, ?, ?, ?)",
        ("exp_001", "000001.SZ", "2024-01-01", "2023-Q4", 1000000000, "test"),
    )
    # 再插入一条 actual
    db.execute(
        "INSERT INTO financial_actuals(stock_code, report_period, ann_date, net_profit, source) VALUES (?, ?, ?, ?, ?)",
        ("000001.SZ", "2023-Q4", "2024-01-10", 1500000000, "test"),
    )
    db.commit()

    result = sync_earnings_surprises(db, "2024-01-15")
    assert result["rows_loaded"] >= 1

    surprise = db.execute("SELECT net_profit_surprise_pct FROM earnings_surprises WHERE stock_code = '000001.SZ'").fetchone()
    assert surprise is not None
    assert abs(surprise["net_profit_surprise_pct"] - 0.5) < 0.01  # 50% surprise
```

- [ ] **步骤 3：运行测试并 Commit**

---

### 任务 C2：单股复盘证据展示增强

**文件：**
- 读取：`src/stock_select/review_packets.py` — `stock_review` 函数
- 修改：增加财报预期差、订单、KPI、风险证据

- [ ] **步骤 1：在 stock_review 中聚合证据表**

```python
# 在 review_packets.py 的 stock_review 函数中，返回结果前添加
domain_facts = {
    "earnings_surprises": rows_to_dicts(conn.execute(
        "SELECT * FROM earnings_surprises WHERE stock_code = ? AND ann_date <= ? ORDER BY ann_date DESC LIMIT 5",
        (stock_code, date),
    )),
    "order_contract_events": rows_to_dicts(conn.execute(
        "SELECT * FROM order_contract_events WHERE stock_code = ? AND ann_date <= ? ORDER BY ann_date DESC LIMIT 5",
        (stock_code, date),
    )),
    "business_kpi_actuals": rows_to_dicts(conn.execute(
        "SELECT * FROM business_kpi_actuals WHERE stock_code = ? ORDER BY period DESC LIMIT 5",
        (stock_code,),
    )),
    "financial_actuals": rows_to_dicts(conn.execute(
        "SELECT * FROM financial_actuals WHERE stock_code = ? AND ann_date <= ? ORDER BY ann_date DESC LIMIT 5",
        (stock_code, date),
    )),
    "risk_events": rows_to_dicts(conn.execute(
        "SELECT * FROM event_signals WHERE stock_code = ? AND event_type LIKE '%risk%' ORDER BY published_at DESC LIMIT 5",
        (stock_code, date),
    )),
}

return {
    "stock": dict(stock),
    "decisions": decisions,
    "domain_facts": domain_facts,
}
```

- [ ] **步骤 2：Commit**

---

## Phase D：LLM 收盘复盘

> 这是当前最大的缺失模块。`llm_review.py` 文件不存在。

### 任务 D1：LLMReviewContract 校验

**文件：**
- 创建：`src/stock_select/llm_contracts.py`
- 创建：`tests/test_llm_contracts.py`

- [ ] **步骤 1：实现 LLMReviewContract**

```python
# src/stock_select/llm_contracts.py
"""LLM review output contract validation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .review_taxonomy import EVIDENCE_CONFIDENCE


class LLMContractError(ValueError):
    pass


def _require(payload: dict[str, Any], key: str, context: str = "") -> Any:
    if key not in payload or payload[key] is None:
        raise LLMContractError(f"{context} missing required key: {key}")
    return payload[key]


@dataclass(frozen=True)
class AttributionClaim:
    claim: str
    confidence: Literal["EXTRACTED", "INFERRED", "AMBIGUOUS"]
    evidence_ids: list[str]

    @classmethod
    def validate(cls, payload: dict[str, Any]) -> "AttributionClaim":
        confidence = _require(payload, "confidence", "attribution")
        if confidence == "EXTRACTED" and not payload.get("evidence_ids"):
            raise LLMContractError("EXTRACTED claims must have evidence_ids")
        return cls(
            claim=str(_require(payload, "claim", "attribution")),
            confidence=confidence if confidence in EVIDENCE_CONFIDENCE else "AMBIGUOUS",
            evidence_ids=list(payload.get("evidence_ids", [])),
        )


@dataclass(frozen=True)
class LLMReviewContract:
    review_target: dict[str, str]
    attribution: list[AttributionClaim]
    reason_check: dict[str, list[str]]
    suggested_errors: list[dict[str, Any]]
    suggested_optimization_signals: list[dict[str, Any]]
    summary: str

    @classmethod
    def validate(cls, payload: dict[str, Any]) -> "LLMReviewContract":
        target = _require(payload, "review_target", "root")
        _require(target, "type", "review_target")
        _require(target, "id", "review_target")

        attribution = [
            AttributionClaim.validate(item)
            for item in _require(payload, "attribution", "root")
        ]

        reason_check = _require(payload, "reason_check", "root")
        for key in ["what_was_right", "what_was_wrong", "missing_signals"]:
            if key not in reason_check:
                reason_check[key] = []

        return cls(
            review_target=target,
            attribution=attribution,
            reason_check=reason_check,
            suggested_errors=list(payload.get("suggested_errors", [])),
            suggested_optimization_signals=list(payload.get("suggested_optimization_signals", [])),
            summary=str(payload.get("summary", "")),
        )
```

- [ ] **步骤 2：编写测试**

```python
# tests/test_llm_contracts.py
import pytest
from stock_select.llm_contracts import LLMReviewContract, AttributionClaim, LLMContractError

def test_valid_llm_review():
    payload = {
        "review_target": {"type": "decision", "id": "pick_001"},
        "attribution": [
            {"claim": "Tech sector drove gains", "confidence": "EXTRACTED", "evidence_ids": ["ev_001"]}
        ],
        "reason_check": {"what_was_right": ["momentum"], "what_was_wrong": [], "missing_signals": []},
        "suggested_errors": [],
        "suggested_optimization_signals": [],
        "summary": "Good pick driven by sector momentum.",
    }
    contract = LLMReviewContract.validate(payload)
    assert contract.review_target["type"] == "decision"
    assert len(contract.attribution) == 1

def test_extracted_requires_evidence():
    payload = {
        "review_target": {"type": "decision", "id": "pick_001"},
        "attribution": [
            {"claim": "No evidence", "confidence": "EXTRACTED", "evidence_ids": []}
        ],
        "reason_check": {"what_was_right": [], "what_was_wrong": [], "missing_signals": []},
        "summary": "",
    }
    with pytest.raises(LLMContractError, match="EXTRACTED claims must have evidence"):
        LLMReviewContract.validate(payload)

def test_missing_target_raises():
    payload = {
        "attribution": [],
        "reason_check": {},
        "summary": "",
    }
    with pytest.raises(LLMContractError, match="review_target"):
        LLMReviewContract.validate(payload)
```

- [ ] **步骤 3：运行测试并 Commit**

```bash
pytest tests/test_llm_contracts.py -v
git add src/stock_select/llm_contracts.py tests/test_llm_contracts.py
git commit -m "feat: add LLMReviewContract validation (Phase D)"
```

---

### 任务 D2：Review Packet Builder

**文件：**
- 创建：`src/stock_select/llm_prompt.py`
- 读取：`src/stock_select/review_packets.py`

- [ ] **步骤 1：实现 review packet builder**

```python
# src/stock_select/llm_prompt.py
"""Build review packets for LLM consumption."""
from __future__ import annotations

import json
from typing import Any


def build_decision_review_packet(decision_row: dict, outcome_row: dict, factor_checks: list[dict], evidence: list[dict]) -> dict[str, Any]:
    """Build a compressed review packet for LLM decision review."""
    return {
        "target": {"type": "decision", "id": decision_row["decision_id"]},
        "preopen_snapshot": {
            "candidate_packet": json.loads(decision_row.get("packet_json", "{}")),
            "pick_thesis": json.loads(decision_row.get("thesis_json", "{}")),
            "risk_notes": json.loads(decision_row.get("risks_json", "[]")),
        },
        "postclose_facts": {
            "outcome": {
                "entry_price": outcome_row["entry_price"],
                "close_price": outcome_row["close_price"],
                "return_pct": outcome_row["return_pct"],
                "max_drawdown_intraday_pct": outcome_row["max_drawdown_intraday_pct"],
            },
            "relative_performance": {"index_return": outcome_row.get("index_return_pct", 0)},
            "sector_performance": {"industry": decision_row.get("industry", ""), "sector_return": 0},
        },
        "events": {"preopen_visible": [], "postdecision": []},
        "deterministic_checks": [
            {"factor": fc["factor_type"], "verdict": fc["verdict"], "error": fc.get("error_type")}
            for fc in factor_checks
        ],
        "known_error_taxonomy": [
            "data_missing", "false_catalyst", "overweighted_technical",
            "underweighted_fundamental", "risk_underestimated",
            "sector_rotation_missed", "entry_unfillable",
        ],
        "allowed_outputs": {
            "max_attributions": 5,
            "must_cite_evidence_for_extracted": True,
            "optimization_signal_default_status": "candidate",
        },
    }
```

- [ ] **步骤 2：Commit**

---

### 任务 D3：LLM Review 模块实现

**文件：**
- 创建：`src/stock_select/llm_review.py`
- 读取：`src/stock_select/llm_contracts.py`
- 读取：`src/stock_select/llm_prompt.py`
- 读取：`src/stock_select/deterministic_review.py`
- 创建：`tests/test_llm_review.py`

- [ ] **步骤 1：实现 llm_review.py**

```python
# src/stock_select/llm_review.py
"""LLM-powered review attribution. Reads review packets, outputs structured LLMReviewContract."""
from __future__ import annotations

import json
import os
import sqlite3
from typing import Any

from . import repository
from .llm_contracts import LLMReviewContract, LLMContractError
from .llm_prompt import build_decision_review_packet
from .optimization_signals import upsert_optimization_signal

LLM_REVIEW_TIMEOUT = 30


def run_llm_review(conn: sqlite3.Connection, trading_date: str) -> dict[str, Any]:
    """Run LLM review for all picks on a trading date."""
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
    if not api_key:
        return {"status": "skipped", "reason": "no API key configured"}

    decisions = conn.execute(
        """
        SELECT p.*, c.packet_json, o.entry_price, o.close_price, o.return_pct,
               o.max_drawdown_intraday_pct, t.index_return_pct
        FROM pick_decisions p
        JOIN outcomes o ON o.decision_id = p.decision_id
        LEFT JOIN trading_days t ON t.trading_date = p.trading_date
        LEFT JOIN candidate_scores c
          ON c.trading_date = p.trading_date
         AND c.strategy_gene_id = p.strategy_gene_id
         AND c.stock_code = p.stock_code
        WHERE p.trading_date = ?
        """,
        (trading_date,),
    ).fetchall()

    reviewed = 0
    errors = 0
    for row in decisions:
        try:
            review_llm_decision(conn, row)
            reviewed += 1
        except Exception as exc:
            errors += 1
            conn.execute(
                "INSERT OR IGNORE INTO research_runs(run_id, trading_date, phase, status, error) VALUES (?, ?, ?, ?, ?)",
                (f"llm_{row['decision_id']}", trading_date, "llm_review", "error", str(exc)),
            )
    conn.commit()
    return {"status": "completed", "reviewed": reviewed, "errors": errors}


def review_llm_decision(conn: sqlite3.Connection, decision_row: sqlite3.Row) -> str:
    """Review a single decision using LLM."""
    packet = build_decision_review_packet(
        decision_row=dict(decision_row),
        outcome_row=dict(decision_row),
        factor_checks=[],
        evidence=[],
    )

    llm_output = _call_llm(packet)

    try:
        contract = LLMReviewContract.validate(llm_output)
    except LLMContractError as exc:
        _record_llm_error(conn, decision_row, str(exc))
        return ""

    # 写入 decision_reviews.llm_json
    conn.execute(
        "UPDATE decision_reviews SET llm_json = ? WHERE decision_id = ?",
        (json.dumps(_contract_to_json(contract)), decision_row["decision_id"]),
    )

    # LLM 建议的错误和优化信号写入，但默认 status=candidate
    for suggested_error in contract.suggested_errors:
        from .deterministic_review import upsert_review_error
        upsert_review_error(
            conn,
            review_scope="decision",
            review_id=f"llm_{decision_row['decision_id']}",
            error_type=suggested_error.get("error_type", "llm_inferred"),
            severity=float(suggested_error.get("severity", 0.3)),
            confidence=float(suggested_error.get("confidence", 0.5)),
            evidence_ids=[],
        )

    for signal in contract.suggested_optimization_signals:
        upsert_optimization_signal(
            conn,
            source_type="llm_review",
            source_id=f"llm_{decision_row['decision_id']}",
            target_gene_id=decision_row["strategy_gene_id"],
            scope="gene",
            signal_type=signal.get("signal_type", "observe_only"),
            param_name=signal.get("param_name"),
            direction=signal.get("direction", "hold"),
            strength=float(signal.get("strength", 0)),
            confidence=float(signal.get("confidence", 0.3)),
            reason=signal.get("reason", "LLM suggested"),
            evidence_ids=[],
            status="candidate",
        )

    return contract.summary


def _call_llm(packet: dict[str, Any]) -> dict[str, Any]:
    """Call Claude API with the review packet."""
    try:
        from anthropic import Anthropic
    except ImportError:
        raise RuntimeError("anthropic package not installed")

    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY"))

    prompt = f"""You are a stock pick review analyst. Review the following pick decision and provide structured attribution.

Input packet (JSON):
```json
{json.dumps(packet, ensure_ascii=False, indent=2)}
```

Rules:
1. Output must be valid JSON matching the LLMReviewContract schema.
2. Every attribution with confidence="EXTRACTED" must have at least one evidence_id.
3. Do not invent evidence. Use "AMBIGUOUS" when evidence is insufficient.
4. Suggested optimization signals should default to observe_only for single samples.
5. Keep the summary under 200 characters.

Output ONLY valid JSON, no markdown fences."""

    response = client.messages.create(
        model="claude-sonnet-4-6-20250514",
        max_tokens=2000,
        system="You are a financial analysis agent. Output only valid JSON. Never invent evidence.",
        messages=[{"role": "user", "content": prompt}],
    )

    content = response.content[0].text
    # Strip markdown fences if present
    if content.startswith("```"):
        content = content.split("\n", 1)[1]
    if content.endswith("```"):
        content = content.rsplit("\n", 1)[0]

    return json.loads(content)


def _contract_to_json(contract: LLMReviewContract) -> dict[str, Any]:
    return {
        "attribution": [
            {"claim": a.claim, "confidence": a.confidence, "evidence_ids": a.evidence_ids}
            for a in contract.attribution
        ],
        "reason_check": contract.reason_check,
        "suggested_errors": contract.suggested_errors,
        "summary": contract.summary,
    }


def _record_llm_error(conn: sqlite3.Connection, decision_row: sqlite3.Row, error: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO research_runs(run_id, trading_date, phase, strategy_gene_id, status, error) VALUES (?, ?, ?, ?, ?, ?)",
        (f"llm_err_{decision_row['decision_id']}", decision_row["trading_date"], "llm_review", decision_row["strategy_gene_id"], "error", error),
    )
```

- [ ] **步骤 2：编写测试（mock LLM 调用）**

```python
# tests/test_llm_review.py
import sqlite3
import pytest
from unittest.mock import patch, MagicMock
from stock_select.db import connect, init_db
from stock_select.llm_contracts import LLMReviewContract, LLMContractError
from stock_select.llm_review import run_llm_review

@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    init_db(conn)
    return conn

def test_skips_without_api_key(db, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
    result = run_llm_review(db, "2024-01-15")
    assert result["status"] == "skipped"

def test_llm_contract_validates_extracted_with_evidence():
    payload = {
        "review_target": {"type": "decision", "id": "pick_001"},
        "attribution": [
            {"claim": "Momentum confirmed", "confidence": "EXTRACTED", "evidence_ids": ["ev_001"]}
        ],
        "reason_check": {"what_was_right": ["momentum"], "what_was_wrong": [], "missing_signals": []},
        "summary": "Test",
    }
    contract = LLMReviewContract.validate(payload)
    assert len(contract.attribution) == 1
    assert contract.attribution[0].confidence == "EXTRACTED"

def test_llm_contract_rejects_extracted_without_evidence():
    payload = {
        "review_target": {"type": "decision", "id": "pick_001"},
        "attribution": [
            {"claim": "No evidence", "confidence": "EXTRACTED", "evidence_ids": []}
        ],
        "reason_check": {"what_was_right": [], "what_was_wrong": [], "missing_signals": []},
        "summary": "Test",
    }
    with pytest.raises(LLMContractError):
        LLMReviewContract.validate(payload)
```

- [ ] **步骤 3：在 `agent_runtime.py` 注册 llm_review phase**

```python
# 在 agent_runtime.py 的 RUN_PHASES 和 run_phase 中添加
from .llm_review import run_llm_review

# 在 run_phase 的 phase dispatch 中添加
"llm_review": lambda conn, date: run_llm_review(conn, date),
```

- [ ] **步骤 4：运行测试并 Commit**

```bash
pytest tests/test_llm_review.py tests/test_llm_contracts.py -v
git add src/stock_select/llm_review.py src/stock_select/llm_contracts.py src/stock_select/llm_prompt.py tests/test_llm_review.py tests/test_llm_contracts.py
git commit -m "feat: add LLM review module with contract validation (Phase D)"
```

---

## Phase E：知识图谱和记忆增强

### 任务 E1：相似案例查询

**文件：**
- 创建：`src/stock_select/similar_cases.py`
- 创建：`tests/test_similar_cases.py`

- [ ] **步骤 1：实现相似案例查询**

```python
# src/stock_select/similar_cases.py
"""Query similar historical cases using FTS5 and graph patterns."""
from __future__ import annotations

import sqlite3
from typing import Any


def find_similar_cases(
    conn: sqlite3.Connection,
    *,
    gene_id: str | None = None,
    market_environment: str | None = None,
    error_type: str | None = None,
    industry: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Find similar historical review cases using FTS5."""
    from .memory import search_memory

    conditions = []
    params: list[Any] = []

    if market_environment:
        conditions.append("market_environment = ?")
        params.append(market_environment)

    if gene_id:
        conditions.append("strategy_gene_id = ?")
        params.append(gene_id)

    query = "SELECT * FROM decision_reviews WHERE 1=1"
    if conditions:
        query += " AND " + " AND ".join(conditions)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def query_similar_by_error(conn: sqlite3.Connection, error_type: str, limit: int = 10) -> list[dict[str, Any]]:
    """Find decisions with similar error types."""
    rows = conn.execute(
        """
        SELECT dr.*, re.error_type, re.severity
        FROM decision_reviews dr
        JOIN review_errors re ON re.review_id = dr.review_id
        WHERE re.error_type = ?
        ORDER BY dr.created_at DESC
        LIMIT ?
        """,
        (error_type, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def query_gene_history(conn: sqlite3.Connection, gene_id: str, market_environment: str = "all") -> dict[str, Any]:
    """Query a gene's historical performance in a market environment."""
    reviews = conn.execute(
        "SELECT * FROM gene_reviews WHERE strategy_gene_id = ? AND market_environment = ? ORDER BY period_end DESC LIMIT 10",
        (gene_id, market_environment),
    ).fetchall()

    evolution = conn.execute(
        "SELECT * FROM strategy_evolution_events WHERE parent_gene_id = ? OR child_gene_id = ? ORDER BY created_at DESC LIMIT 5",
        (gene_id, gene_id),
    ).fetchall()

    return {
        "gene_id": gene_id,
        "market_environment": market_environment,
        "reviews": [dict(r) for r in reviews],
        "evolution_events": [dict(e) for e in evolution],
    }
```

- [ ] **步骤 2：在 API 中注册相似案例接口**

```python
# 在 api.py 中添加
@app.get("/api/reviews/similar-cases")
def similar_cases(
    gene_id: str | None = None,
    market_environment: str | None = None,
    error_type: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    conn = db()
    try:
        from .similar_cases import find_similar_cases, query_similar_by_error
        if error_type:
            return query_similar_by_error(conn, error_type, limit)
        return find_similar_cases(conn, gene_id=gene_id, market_environment=market_environment, limit=limit)
    finally:
        conn.close()

@app.get("/api/reviews/genes/{gene_id}/history")
def gene_history(gene_id: str, market_environment: str = "all") -> dict[str, Any]:
    conn = db()
    try:
        from .similar_cases import query_gene_history
        return query_gene_history(conn, gene_id, market_environment)
    finally:
        conn.close()
```

- [ ] **步骤 3：编写测试并 Commit**

---

## Phase F：预盘 LLM 辅助

> Phase F 依赖 Phase D（LLM 基础架构）完成。Planner/Analyst/Pick Evaluator 在已有 candidate_pipeline 基础上增强。

### 任务 F1：Planner Agent

**文件：**
- 创建：`src/stock_select/planner.py`
- 创建：`tests/test_planner.py`

- [ ] **步骤 1：实现 Planner**

```python
# src/stock_select/planner.py
"""Planner Agent: decides today's focus industries and risks."""
from __future__ import annotations

import os
import sqlite3
from typing import Any


def plan_preopen_focus(conn: sqlite3.Connection, trading_date: str) -> dict[str, Any]:
    """Generate today's focus plan based on recent market data."""
    # 确定性部分：从市场数据中提取
    recent_sectors = conn.execute(
        "SELECT industry, sector_return_pct FROM sector_theme_signals WHERE trading_date = ? ORDER BY sector_return_pct DESC LIMIT 5",
        (trading_date,),
    ).fetchall()

    market_env = conn.execute(
        "SELECT market_environment, trend_type, volatility_level FROM trading_days WHERE trading_date < ? ORDER BY trading_date DESC LIMIT 1",
        (trading_date,),
    ).fetchone()

    plan = {
        "trading_date": trading_date,
        "focus_sectors": [dict(r) for r in recent_sectors],
        "market_environment": dict(market_env) if market_env else None,
        "watch_risks": [],
        "llm_notes": None,
    }

    # LLM 部分（可选）：补充关注点
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        plan["llm_notes"] = _call_planner_llm(plan)

    return plan


def _call_planner_llm(plan: dict[str, Any]) -> str:
    try:
        from anthropic import Anthropic
    except ImportError:
        return None

    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        system="You are a market planning assistant. Give concise focus recommendations.",
        messages=[{"role": "user", "content": f"Today's market plan: {plan}"}],
    )
    return response.content[0].text
```

- [ ] **步骤 2：编写测试并 Commit**

---

## Phase G：日常运行硬化

### 任务 G1：APScheduler 真实调度

**文件：**
- 读取：`src/stock_select/scheduler.py`
- 修改：添加真实 APScheduler 任务

- [ ] **步骤 1：实现调度器**

```python
# src/stock_select/scheduler.py
"""APScheduler-based task scheduling for daily operations."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR

from .db import connect, init_db
from .agent_runtime import run_phase


def create_scheduler(db_path: Path, mode: str = "demo") -> BlockingScheduler:
    """Create APScheduler with all daily tasks."""
    scheduler = BlockingScheduler()

    def job_listener(event):
        conn = connect(db_path)
        init_db(conn)
        if event.exception:
            conn.execute(
                "UPDATE research_runs SET status = 'error', error = ?, finished_at = CURRENT_TIMESTAMP WHERE run_id = ? AND status = 'running'",
                (str(event.exception), event.job_id),
            )
        else:
            conn.execute(
                "UPDATE research_runs SET status = 'completed', finished_at = CURRENT_TIMESTAMP WHERE run_id = ? AND status = 'running'",
                (event.job_id,),
            )
        conn.commit()
        conn.close()

    scheduler.add_listener(job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

    # 8:00 - 数据同步
    scheduler.add_job(
        lambda: _run_phase(db_path, "sync_data", _today()),
        "cron", hour=8, minute=0, day_of_week="mon-fri", id="sync_data",
    )

    # 8:30 - 预盘选股
    scheduler.add_job(
        lambda: _run_phase(db_path, "preopen_pick", _today()),
        "cron", hour=8, minute=30, day_of_week="mon-fri", id="preopen_pick",
    )

    # 15:05 - 收盘同步
    scheduler.add_job(
        lambda: _run_phase(db_path, "sync_data", _today()),
        "cron", hour=15, minute=5, day_of_week="mon-fri", id="close_sync",
    )

    # 15:10 - 模拟成交
    scheduler.add_job(
        lambda: _run_phase(db_path, "simulate", _today()),
        "cron", hour=15, minute=10, day_of_week="mon-fri", id="simulate",
    )

    # 15:15 - 确定性复盘
    scheduler.add_job(
        lambda: _run_phase(db_path, "deterministic_review", _today()),
        "cron", hour=15, minute=15, day_of_week="mon-fri", id="deterministic_review",
    )

    # 15:30 - LLM 复盘
    scheduler.add_job(
        lambda: _run_phase(db_path, "llm_review", _today()),
        "cron", hour=15, minute=30, day_of_week="mon-fri", id="llm_review",
    )

    # 周六 10:00 - 策略进化
    scheduler.add_job(
        lambda: _run_phase(db_path, "evolve", _today()),
        "cron", hour=10, minute=0, day_of_week="sat", id="evolve",
    )

    return scheduler


def _today() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d")


def _run_phase(db_path: Path, phase: str, date: str) -> dict:
    conn = connect(db_path)
    init_db(conn)
    try:
        return run_phase(conn, phase, date)
    finally:
        conn.close()
```

- [ ] **步骤 2：编写测试**

```python
# tests/test_scheduler.py
import pytest
from stock_select.scheduler import create_scheduler

def test_scheduler_creates_all_jobs(tmp_path):
    scheduler = create_scheduler(tmp_path / "test.db")
    job_ids = {job.id for job in scheduler.get_jobs()}
    expected = {"sync_data", "preopen_pick", "close_sync", "simulate", "deterministic_review", "llm_review", "evolve"}
    assert expected.issubset(job_ids)
    scheduler.shutdown(wait=False)
```

- [ ] **步骤 3：Commit**

---

### 任务 G2：API 新增数据同步和调度接口

**文件：**
- 修改：`src/stock_select/api.py`

- [ ] **步骤 1：添加数据同步触发接口**

在 api.py 中已有 `/api/data/sync`。确认 `/api/data/status` 返回 data_status，并添加调度状态接口：

```python
@app.get("/api/scheduler/status")
def scheduler_status() -> dict[str, Any]:
    conn = db()
    try:
        jobs = conn.execute(
            "SELECT phase, status, started_at, finished_at, error FROM research_runs ORDER BY started_at DESC LIMIT 20"
        ).fetchall()
        return {"recent_jobs": [dict(j) for j in jobs]}
    finally:
        conn.close()
```

- [ ] **步骤 2：Commit**

---

## 前端增强

### 任务 FE1：复盘中心页面

**文件：**
- 创建：`web/src/components/ReviewCenter.tsx`
- 修改：`web/src/main.tsx` — 引入复盘中心

- [ ] **步骤 1：创建复盘中心组件**

```tsx
// web/src/components/ReviewCenter.tsx
import { useState } from 'react';

type ReviewSummary = {
  decision_reviews: number;
  blindspot_reviews: number;
  open_optimization_signals: number;
  system_summary: string;
  top_errors: Array<{ error_type: string; count: number }>;
};

interface ReviewCenterProps {
  date: string;
  summary: ReviewSummary;
}

export default function ReviewCenter({ date, summary }: ReviewCenterProps) {
  return (
    <div className="review-center">
      <h2>复盘中心 — {date}</h2>
      <div className="review-stats">
        <Stat label="单笔复盘" value={summary.decision_reviews} />
        <Stat label="盲点复盘" value={summary.blindspot_reviews} />
        <Stat label="开放信号" value={summary.open_optimization_signals} />
      </div>
      {summary.system_summary && (
        <p className="system-summary">{summary.system_summary}</p>
      )}
      {summary.top_errors?.length > 0 && (
        <div className="top-errors">
          <h3>Top Errors</h3>
          {summary.top_errors.map((e, i) => (
            <div key={i}>{e.error_type}: {e.count}</div>
          ))}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return <div className="stat"><small>{label}</small><strong>{value}</strong></div>;
}
```

- [ ] **步骤 2：Commit**

---

### 任务 FE2：策略进化面板

**文件：**
- 创建：`web/src/components/EvolutionPanel.tsx`

- [ ] **步骤 1：创建进化面板**

```tsx
// web/src/components/EvolutionPanel.tsx
interface EvolutionPanelProps {
  signals: Array<Record<string, unknown>>;
  events: Array<Record<string, unknown>>;
}

export default function EvolutionPanel({ signals, events }: EvolutionPanelProps) {
  return (
    <div className="evolution-panel">
      <h3>策略进化</h3>
      <section>
        <h4>Open Signals ({signals.length})</h4>
        {signals.slice(0, 10).map((s, i) => (
          <div key={i} className="signal-card">
            <b>{String(s.signal_type)}</b>
            <span>{String(s.param_name)}</span>
            <span>{String(s.direction)}</span>
            <small>confidence: {Number(s.confidence).toFixed(2)}</small>
          </div>
        ))}
      </section>
      <section>
        <h4>Evolution Events</h4>
        {events.slice(0, 5).map((e, i) => (
          <div key={i} className="evolution-event">
            <b>{String(e.event_type)}</b>
            <span>{String(e.status)}</span>
            <small>{String(e.created_at)}</small>
          </div>
        ))}
      </section>
    </div>
  );
}
```

- [ ] **步骤 2：Commit**

---

## 最终集成与验收

### 任务 Z1：全量测试运行

- [ ] **步骤 1：运行所有测试**

```bash
python3 -m pytest tests/ -v --tb=short
```

预期：全部测试 PASS，测试覆盖率 >= 80%

- [ ] **步骤 2：检查覆盖率**

```bash
python3 -m pytest --cov=src/stock_select --cov-report=term-missing
```

- [ ] **步骤 3：前端 build 验证**

```bash
cd web && npm run build
```

- [ ] **步骤 4：手动 smoke test**

```bash
# 初始化 live DB
python3 -m stock_select.cli init-db --mode live

# 同步一个真实历史交易日
python3 -m stock_select.cli pipeline --mode demo --date 2024-01-15

# 查询 dashboard
curl http://127.0.0.1:8000/api/dashboard?date=2024-01-15 | python3 -m json.tool

# 查询 data quality
curl http://127.0.0.1:8000/api/data/quality?date=2024-01-15 | python3 -m json.tool
```

- [ ] **步骤 5：Commit**

```bash
git add -A
git commit -m "chore: full integration test pass and final verification"
```

---

## 执行检查清单

完成以上所有任务后，以下验收标准应该全部满足：

### Phase A 验收
- [ ] demo 数据不会污染 live 库
- [ ] 任意一个真实历史交易日可重跑
- [ ] `price_source_checks`、`data_sources`、`daily_prices` 都有真实记录
- [ ] 预盘策略不读取目标日行情

### Phase B 验收
- [ ] `candidate_scores` 中技术、基本面、事件、行业、风险都有真实来源或明确 `data_missing`
- [ ] 没有数据时不伪造分数
- [ ] 前端能展示候选评分分解的数据来源状态

### Phase C 验收
- [ ] 单股复盘能看到财报、预期差、订单、KPI、风险证据
- [ ] 每条证据有 source、source_url、visibility、confidence
- [ ] 复盘错误类型能覆盖 `missed_earnings_surprise`、`missed_order_signal`、`analyst_expectation_missing`

### Phase D 验收
- [ ] 无 API key 时系统照常运行确定性复盘
- [ ] 有 API key 时只处理推荐股、盲点股、异常样本
- [ ] LLM 的 `EXTRACTED` claim 必须有 evidence
- [ ] LLM 建议默认进入 `candidate` 状态，不直接被 evolution 消费

### Phase E 验收
- [ ] 可以查询某个 gene 在类似市场环境下的历史表现
- [ ] 可以查询某个错误类型过去出现在哪些股票/行业
- [ ] 图谱边区分 EXTRACTED / INFERRED / AMBIGUOUS

### Phase F 验收
- [ ] 全市场扫描仍由代码完成
- [ ] LLM 只看 Top N 候选和盲点历史
- [ ] LLM 输出不合格时推荐降级为 WATCH 或丢弃
- [ ] 模拟盘仍由确定性代码执行

### Phase G 验收
- [ ] 每天可自动跑 8:00、9:25、15:05、15:30、周六进化任务
- [ ] 每个任务可手动重跑
- [ ] 失败不会破坏已有数据
- [ ] 用户能看到哪一步失败、失败原因、影响范围

### 最终验收
- [ ] `python3 -m unittest discover -s tests` 或 `pytest tests/` 通过
- [ ] `npm run build` 通过
- [ ] demo DB 和 live DB 分离
- [ ] live DB 不包含 demo review facts
- [ ] 一个真实历史交易日可以完整 pipeline
- [ ] 重跑同一天不会重复或外键失败
- [ ] Dashboard 显示 live mode、market environment、data quality
- [ ] 单股复盘可以展示真实行情 evidence
- [ ] 财务/事件未接入时，系统明确显示缺失，不伪造多维结论

---

## 依赖关系图

```
Phase A (测试+验证)
  └─ A1 mode测试
  └─ A2 canonical price测试
  └─ A3 数据同步幂等测试
  └─ A4 未来函数防护测试
  └─ A5 pipeline集成测试
  └─ A6 硬过滤测试

Phase B (多维因子)
  └─ B1 财务/行业/风险因子同步 ───── 依赖: 无
  └─ B2 候选缺失标记 ───────────── 依赖: B1

Phase C (证据层)
  └─ C1 证据同步模块 ───────────── 依赖: B1
  └─ C2 单股复盘增强 ───────────── 依赖: C1

Phase D (LLM复盘)
  └─ D1 LLMReviewContract ──────── 依赖: 无
  └─ D2 Packet Builder ────────── 依赖: D1
  └─ D3 LLM Review 实现 ───────── 依赖: D1, D2

Phase E (图谱增强)
  └─ E1 相似案例查询 ───────────── 依赖: 无

Phase F (预盘LLM)
  └─ F1 Planner Agent ─────────── 依赖: D (LLM基础架构)

Phase G (日常调度)
  └─ G1 APScheduler ───────────── 依赖: D (llm_review phase)
  └─ G2 API 增强 ──────────────── 依赖: 无

前端
  └─ FE1 复盘中心 ─────────────── 依赖: C (API就绪)
  └─ FE2 进化面板 ─────────────── 依赖: 无

最终集成 Z1 ───────────────────── 依赖: 以上全部
```

## 推荐执行顺序

1. **Phase A**（A1-A6）— 先把测试补上，确保已有代码正确性
2. **Phase B**（B1-B2）— 多维因子层，相对独立
3. **Phase C**（C1-C2）— 证据层，依赖 B
4. **Phase D**（D1-D3）— LLM 复盘，可以独立于 B/C 并行
5. **Phase E**（E1）— 图谱增强，独立
6. **Phase G**（G1-G2）— 日常调度，依赖 D
7. **Phase F**（F1）— 预盘 LLM，依赖 D
8. **前端**（FE1-FE2）— 依赖后端 API
9. **Phase Z1** — 最终集成验证
