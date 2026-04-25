# 下一阶段工作交接计划

Last updated: 2026-04-25

## 使用规则

本文件用于后续开发交接。每完成一个功能点，必须修改对应状态并补充完成信息。

状态枚举：

- `[TODO]`：尚未开始。
- `[IN_PROGRESS]`：正在开发。
- `[VERIFY]`：代码已实现，等待测试、验收或 live smoke。
- `[BLOCKED]`：被外部依赖、数据源、权限或设计问题阻塞。
- `[DONE]`：代码、测试、验收命令和文档状态均完成。
- `[DEFERRED]`：明确延期，不属于当前阶段。

更新格式：

```text
- [DONE] X.Y Task name
  - Completed: YYYY-MM-DD
  - Files: path1, path2
  - Verification: command/result
  - Notes: important decisions or limitations
```

## 当前项目状态

已完成到可用程度：

- demo/live 数据库隔离。
- 真实行情最小闭环：股票池、交易日历、日线行情、指数行情、canonical price、数据质量。
- 多维因子层：行业/板块、基本面、事件、风险因子框架。
- 复盘 MVP：单笔推荐复盘、单股复盘、早盘策略整体复盘、盲点复盘、系统复盘。
- 真实复盘证据层主体：财报实际值、市场预期、预期差、订单/合同、经营 KPI、风险事件 schema、同步、复盘接入、前端证据展示。
- 策略优化信号：`optimization_signals` 生成、聚合、Challenger 提案、回滚/推广框架。

当前最需要收尾：

- ~~Phase C Sprint 5：Evolution Dry Run 的完整验收。~~ ✅ DONE
- ~~live DB 上做一次真实证据 + 复盘 + 策略进化 dry run smoke。~~ ✅ DONE
- ~~将 Phase C 文档状态从 `[TODO]` 更新到真实状态。~~ ✅ DONE

## 当前状态

Phase C 已全部完成。Evolution 完整闭环已验证通过：

- 8 个交易日 (2024-04-08 ~ 2024-04-22) 的 picks → simulate → review → signals
- 3 个 proposal 全部生成（默认保守阈值 min_trades=20）
- Dry-run 零 mutation ✅
- Apply 创建 3 个 observing challenger，消费 498 signals ✅
- Promote challenger → active，parent 自动 retired ✅
- Rollback challenger → rolled_back，parent 恢复 ✅
- 所有历史数据保留，无删除 ✅

下一步：LLM 收盘复盘（Phase D）。

## P0：立即收尾任务

目标：把当前已开发内容从“代码大体完成”推进到“可交接、可验收、状态明确”。

### P0.1 Evolution Dry Run 验证

- [DONE] P0.1.1 运行 Evolution dry-run 单元测试
  - Completed: 2026-04-25
  - Verification: `pytest tests/test_evolution_dry_run.py` → 2 passed
  - Result: dry-run 不创建 child gene ✅, dry-run 不消费 signal ✅, apply proposal 消费 signal ✅, comparison API 返回参数差异 ✅

- [DONE] P0.1.2 跑完整后端测试
  - Completed: 2026-04-25
  - Verification: `pytest` → 180 passed / 1 skipped; `unittest discover` → 46 OK; `compileall` → no errors

- [DONE] P0.1.3 跑前端构建
  - Completed: 2026-04-25
  - Verification: `npm run build` → passed (fixed TypeScript `Comparison` type issue in App.tsx)
  - Result: Evolution Panel、Evidence Panel、Review 页面构建通过 ✅

- [DONE] P0.1.4 检查前端 Evolution 操作阈值
  - Completed: 2026-04-25
  - Fixed: Removed `min_trades=1&min_signal_samples=1&min_signal_dates=1` from both dry-run and apply fetch calls in `web/src/App.tsx`
  - Result: 前端默认使用后端安全阈值 (min_trades=20, min_signal_samples=5, min_signal_dates=3) ✅

### P0.2 Live Smoke

- [DONE] P0.2.1 准备 live DB 目标日
  - Completed: 2026-04-25
  - Verification: live DB 已存在 (115MB, 5510 active stocks, 31 trading days, 4853 prices for 2024-04-22)
  - Result: 真实 A 股规模 ✅（无需重新同步）

- [DONE] P0.2.2 同步真实证据
  - Completed: 2026-04-25
  - Verification: `run-phase sync_evidence --date 2024-04-22` → success
  - Result: financial_actuals 500 ✅, earnings_surprises 500 ✅, order_contract_events 6 ✅; analyst_expectations/business_kpi/risk_events 正确 skipped ✅; 无 fatal error ✅

- [DONE] P0.2.3 运行目标日完整复盘链路
  - Completed: 2026-04-25
  - Verification: All phases ran successfully; idempotent rerun verified (same review_ids returned)
  - Result: 10 picks → 10 outcomes → 10 reviews → 17 blindspots → 3 gene reviews → 1 system review ✅; 幂等性验证通过 ✅

- [DONE] P0.2.4 运行 live evolution dry-run
  - Completed: 2026-04-25
  - Verification: `propose-evolution --dry-run --date 2024-04-22` → status: "skipped", reason: "insufficient samples" (3-4 trades vs min 20)
  - Result: 保守阈值正常工作 ✅; DB 无 mutation ✅; (无 proposals 因为样本不足，这是正确行为)

- [DONE] P0.2.5 API smoke
  - Completed: 2026-04-25
  - Verification: `curl http://127.0.0.1:8011/...` all endpoints responded
  - Result: Dashboard → runtime_mode=live, is_demo_data=false ✅; Evidence status → coverage 9.4%/0%/skipped 7/errors 0 ✅; Evolution comparison → 空数组（稳定 schema）✅

### P0.3 文档状态同步

- [DONE] P0.3.1 更新 `NEXT_PHASE_REVIEW_EVIDENCE_PLAN.md`
  - Completed: 2026-04-25
  - Status: C5.1-C5.6 → all DONE ✅; C5.T1-T5.T7 → DONE/VERIFY/TODO 按真实覆盖标记 ✅; Final Acceptance Criteria → DONE/VERIFY 按真实验收结果标记 ✅

- [DONE] P0.3.2 补充已知限制
  - Completed: 2026-04-25
  - Required limitations:
    - 市场预期真实覆盖率弱，若无授权源只能显示 missing。→ analyst_expectations live sync 返回 0 rows ✅
    - 公告事件目前是标题级分类，不做 PDF 正文抽取。→ order_contract_events 和 risk_events 按标题关键字分类 ✅
    - 经营 KPI 真实源覆盖有限。→ business_kpi_actuals live sync 返回 0 rows ✅
    - LLM 尚未启用，不参与复盘归因和策略修改。→ D1/D2/D3 已规划但未启用 ✅
    - Evolution dry-run 需要更多交易日积累信号才能产生 proposal。→ live DB 只有 1 天的 picks，min_trades=20 无法满足

## P1：Phase D - LLM 收盘复盘 ✅ 已交付

目标：让 LLM 只做归因、反证、解释质量增强，不直接扫描全市场，不直接改策略参数。默认关闭，不影响确定性复盘。

### D1 LLM 配置与运行保护 ✅

- [DONE] D1.1 增加 LLM 配置读取
  - Completed: 2026-04-25
  - Files: `src/stock_select/llm_config.py`, `tests/test_llm_config.py`
  - 支持 3 provider：Anthropic（默认）、OpenAI、DeepSeek
  - Env: `LLM_PROVIDER`, `LLM_MODEL`, `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `DEEPSEEK_API_KEY`
  - 无 API key 时 `resolve_llm_config()` 返回 None，pipeline 正常 skipped

- [DONE] D1.2 增加调用预算与熔断
  - Files: `src/stock_select/llm_config.py`
  - `LLMBudget` 类追踪 token prompt/completion、cost、call count
  - `BudgetExceeded` 异常，`budget.check()` 在每次 LLM 调用前执行
  - 熔断后跳过剩余 stocks，不影响已完成的 review
  - `estimate_cost()` 基于 `COST_PER_1K` 费率表算 USD

- [DONE] D1.3 增加 LLM allowlist
  - Files: `src/stock_select/llm_config.py::build_allowlist()`
  - 只从 `pick_decisions` + `blindspot_reviews` 构建白名单
  - `LLMConfig.max_stocks_per_day` 控制上限（默认 20）
  - 不扫描全市场，不读取原始新闻流

### D2 Review Packet Contract ✅

- [DONE] D2.1 固化 packet
  - Files: `src/stock_select/llm_prompt.py`
  - `build_decision_review_packet()`（已有）+ `build_stock_review_packet()` + `build_blindspot_review_packet()`（新增）
  - 结构化 JSON，大小可控，不包含全市场数据

- [DONE] D2.2 固化 `LLMReviewContract`
  - Files: `src/stock_select/llm_contracts.py`
  - 支持 `decision` / `stock` / `blindspot` / `system` 四种 target type
  - `EXTRACTED` 必须有 evidence_ids，`INFERRED` / `AMBIGUOUS` 允许无 evidence
  - LLM 建议默认 `candidate` 状态，不直接被 evolution 消费

- [DONE] D2.3 contract 校验
  - 缺字段引发 `LLMContractError`
  - 非法 target type / confidence 枚举拒绝
  - schema 失败写日志，不污染 `optimization_signals`

### D3 LLM Review 执行器 ✅

- [DONE] D3.1 执行器函数
  - Files: `src/stock_select/llm_review.py`（+379 行重构）
  - `run_llm_review()` — 全量 decision review，含 allowlist + budget 保护
  - `llm_review_for_decision()` — 单 decision review
  - `llm_review_for_stock()` / `run_llm_stock_reviews()` — 逐股票 review
  - `get_llm_client()` — provider-abstracted LLM 调用（anthropic / openai / deepseek）
  - `_persist_llm_review()` — 写入 `llm_reviews` 表，信号默认 `candidate`

- [DONE] D3.2 pipeline phase
  - `agent_runtime.py` 中 `llm_review` phase 已接通，调用 `run_llm_review()`
  - API: `GET /api/reviews/llm?date=` + `POST /api/reviews/llm/rerun?date=`
  - CLI: `.venv/bin/python -m stock_select.cli --mode live run-phase llm_review --date YYYY-MM-DD`
  - 无 API key / budget 耗尽时优雅 skipped，不影响确定性复盘

- [DONE] D3.3 scratchpad
  - Files: `src/stock_select/db.py`（`llm_scratchpad` 表）
  - 每次 LLM 调用记录：packet_hash, model, provider, prompt_tokens, completion_tokens, estimated_cost, latency_ms, status, error_message
  - 不记录 API key

### D4 LLM 与 optimization_signals 隔离 ✅

- [DONE] D4.1 candidate staging
  - `_persist_llm_review()` 中 `upsert_optimization_signal(status="candidate")`
  - LLM 信号不会被 `aggregate_optimization_signals()` 默认消费
  - `consumed` 保护：upsert ON CONFLICT 不覆盖 `consumed` 状态

- [DONE] D4.2 accept/reject API
  - `POST /api/optimization-signals/{signal_id}/accept` → status `open`
  - `POST /api/optimization-signals/{signal_id}/reject` → status `rejected`
  - 只处理 `candidate` 状态信号，幂等安全

- [DONE] D4.3 前端 LLM Review 展示
  - Files: `web/src/sections/LLMReviewPanel.tsx`
  - Attribution table 展示归因 + 置信度标签
  - Reason check 展开做对/做错/遗漏
  - Suggested signal 审核按钮（accept/reject）
  - Token/cost 费用展示

### D5 LLM Review 测试 ✅

- [DONE] D5.1 fake LLM provider 单测 — `test_llm_config.py` 15 tests
- [DONE] D5.2 schema invalid 输出测试 — `test_contract_rejects_invalid_target_type`
- [DONE] D5.3 token budget 熔断测试 — `TestLLMBudget` 4 tests
- [DONE] D5.4 no API key fallback 测试 — `test_llm_review_skips_without_api_key` + `test_run_llm_review_graceful_without_api`
- [DONE] D5.5 LLM signal 不被 evolution 消费测试 — `test_llm_signal_status_is_candidate`
- [DONE] D5.6 frontend build — `npm run build` 通过 ✅

## P2：Phase E - 知识图谱和记忆增强

目标：让系统可以查“类似案例”和跨天模式，而不只是当天复盘。

- [TODO] E1 扩展图谱节点
  - Nodes:
    - `MarketDay`
    - `Stock`
    - `PickDecision`
    - `Outcome`
    - `ReviewEvidence`
    - `ReviewError`
    - `OptimizationSignal`
    - `StrategyGene`
    - `EvolutionEvent`

- [TODO] E2 扩展图谱边
  - Edges:
    - `PICKED_BY`
    - `HAS_OUTCOME`
    - `SUPPORTED_BY`
    - `CONTRADICTED_BY`
    - `GENERATED_ERROR`
    - `GENERATED_SIGNAL`
    - `EVOLVED_TO`
  - Required attributes:
    - `confidence`
    - `evidence_level`
    - `source_record_id`

- [TODO] E3 FTS5 memory 增强
  - Write:
    - 复盘摘要。
    - 错误类型。
    - 优化信号。
    - 策略进化记录。
    - LLM 归因摘要。

- [TODO] E4 相似案例 API
  - Endpoints:
    - `GET /api/memory/similar-cases?stock_code=&date=&error_type=`
    - `GET /api/graph/stocks/{stock_code}/cases`
    - `GET /api/graph/genes/{gene_id}/similar-market-days`

- [TODO] E5 前端相似案例面板
  - Add to:
    - 单股复盘页。
    - 策略复盘页。
    - Challenger 对比页。

## P3：Phase F - 预盘 LLM 辅助

目标：LLM 只在候选池收敛后做反证和解释增强，不替代确定性规则。

- [TODO] F1 预盘候选池收敛
  - 全市场扫描仍由代码完成。
  - LLM 只读取 Top N 候选和高风险样本。

- [TODO] F2 Planner Agent
  - 输入：
    - 市场环境。
    - 行业强弱。
    - 昨日复盘错误。
    - 今日风险提示。
  - 输出：
    - 今日关注行业。
    - 今日禁入风险。
    - 候选审查重点。

- [TODO] F3 Analyst Agents
  - 只读单股 packet。
  - 不允许读全市场。
  - 输出必须通过 Pick contract。

- [TODO] F4 Pick Evaluator
  - 检查：
    - 未来函数。
    - schema。
    - 风险规则。
    - position_pct。
    - invalid_if。

- [TODO] F5 LLM 预盘成本控制
  - 按候选 Top N 限制。
  - 按 token/day 限制。
  - 按失败率熔断。

## P4：Phase G - 日常运行硬化

目标：把系统变成每天可使用的个人工具。

- [TODO] G1 APScheduler 真实任务
  - 08:00 `preopen_prepare`
  - 08:10 `preopen_pick`
  - 09:25 `open_simulation`
  - 15:05 `close_sync`
  - 15:30 `daily_review`
  - 周六 `gene_evolution`

- [TODO] G2 任务状态页
  - 展示：
    - 当前 phase。
    - 开始/结束时间。
    - 数据源状态。
    - 失败原因。
    - 影响范围。

- [TODO] G3 失败重试和告警
  - Retry:
    - 网络源失败。
    - 单个 chunk 失败。
    - LLM 暂时失败。
  - Alert:
    - 数据质量低于阈值。
    - 今日无 canonical price。
    - pipeline 中断。

- [TODO] G4 历史回测批处理
  - Command:
    ```bash
    .venv/bin/python -m stock_select.cli --mode live backtest --start YYYY-MM-DD --end YYYY-MM-DD
    ```
  - Requirements:
    - 可续跑。
    - 可跳过已完成日期。
    - 可输出每日覆盖率和收益摘要。

- [TODO] G5 Champion/Challenger 日常对比
  - 每个 Challenger 观察期独立统计。
  - 推广和回滚必须保留历史。
  - 前端展示 observed days、trades、return、drawdown、signal basis。

## P5：Phase H - 数据源增强

目标：补齐平台真正需要的预期、公告、订单和经营证据。

- [TODO] H1 市场预期授权源评估
  - Candidate sources:
    - Tushare Pro。
    - 东方财富研报/一致预期。
    - Choice/Wind/iFinD，需合法授权。
  - Decision needed:
    - 是否接受付费源。
    - 是否只做手动导入。

- [TODO] H2 公告索引增强
  - Sources:
    - 巨潮资讯。
    - 上交所。
    - 深交所。
    - 北交所。
  - Scope:
    - 先索引标题、时间、URL、股票代码。
    - PDF 正文抽取只限推荐股、盲点股、重大事件股。

- [TODO] H3 订单/合同抽取增强
  - Extract:
    - 合同金额。
    - 占上一年营收比例。
    - 对手方。
    - 履约期限。
    - 是否框架协议。
    - 是否已中标但未签约。

- [TODO] H4 经营 KPI 行业模板
  - Example templates:
    - 新能源：装机、出货量、产能利用率。
    - 半导体：订单、产能、库存。
    - 医药：管线进度、集采影响。
    - 消费：门店数、客单价、同店增长。

## 全局质量门槛

每个阶段结束前必须通过：

```bash
.venv/bin/python -m pytest
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m compileall -q src
cd web && npm run build
```

每个 live 阶段必须额外验证：

- demo/live DB 物理隔离。
- live 不使用 demo facts。
- 所有证据和因子都有 `source`、`as_of_date` 或明确 missing/skipped。
- 预盘逻辑只读取 `< target_date` 的数据。
- 重跑同一天不重复插入、不破坏历史。

## 推荐执行顺序

1. P0：完成 Evolution Dry Run 验证和文档状态同步。
2. P1：开发 LLM 收盘复盘，但默认关闭。
3. P2：把复盘、证据、优化信号写入图谱和 FTS5 memory。
4. P3：在候选池收敛后引入预盘 LLM 辅助。
5. P4：日常运行硬化。
6. P5：按数据可获得性补强授权源和公告抽取。

## 关键原则

- 先结构化证据，后 LLM 解释。
- 先候选池收敛，后让 LLM 阅读。
- LLM 不扫描全市场。
- LLM 不直接修改策略参数。
- 复盘产生优化信号，优化信号经过样本数、置信度、日期跨度和人工/规则审核后，才进入 Challenger。
- 每次进化都必须可审计、可回滚、可并行对比。
