# 自我进化 A 股选股系统后续总计划与下一阶段执行计划

## Summary

当前已完成：demo 数据下的选股、模拟盘、确定性复盘、单股复盘、早盘策略整体复盘、盲点复盘、`optimization_signals`、Challenger 提案、回滚/推广框架和前端复盘中心。

接下来总方向是：先真实数据，后 LLM；先结构化证据，后解释增强；先小样本真实闭环，后全市场日常运行。

下一阶段只做真实数据最小闭环，不接 LLM、不接实盘交易、不引入复杂公告抽取。

Phase C 的详细开发执行清单已经单独落档到 `NEXT_PHASE_REVIEW_EVIDENCE_PLAN.md`。后续进入真实复盘证据层时，以该文档为准，并在每个功能完成后更新对应状态。

## 全量剩余路线图

### Phase A：真实数据最小闭环

目标：用真实 A 股行情跑通完整链路。

交付物：
- demo/live 数据隔离。
- AKShare + BaoStock 股票池、交易日历、日线行情、指数行情。
- 双源校验和 canonical price 发布。
- 真实历史交易日可跑：`sync_data -> preopen_pick -> simulate -> review -> optimization_signals`。
- 前端明确展示当前数据模式和数据质量。

验收：
- demo 数据不会污染 live 库。
- 任意一个真实历史交易日可重跑。
- `price_source_checks`、`data_sources`、`daily_prices` 都有真实记录。
- 预盘策略不读取目标日行情。

### Phase B：多维真实因子层

目标：避免系统变成纯技术面选股。

交付物：
- 财务质量因子：ROE、营收增长、净利增长、现金流、负债风险。
- 行业/主题因子：行业涨跌、板块强度、板块内排名。
- 事件因子：公告、业绩预告/快报、重大合同、风险事件索引。
- 风险因子：ST、停牌、流动性、退市风险、负面公告。

验收：
- `candidate_scores` 中技术、基本面、事件、行业、风险都有真实来源或明确 `data_missing`。
- 没有数据时不伪造分数。
- 前端能展示候选评分分解的数据来源状态。

### Phase C：真实复盘证据层

目标：让复盘不只是看涨跌，而能回答为什么选错或漏掉。

交付物：
- 财报实际值 `financial_actuals`。
- 市场预期 `analyst_expectations`。
- 业绩预期差 `earnings_surprises`。
- 订单/合同 `order_contract_events`。
- 经营 KPI `business_kpi_actuals`。
- 风险事件 `risk_events`。
- 单股复盘页面展示证据表。

验收：
- 单股复盘能看到财报、预期差、订单、KPI、风险证据。
- 每条证据有 source、source_url、visibility、confidence。
- 复盘错误类型能覆盖 `missed_earnings_surprise`、`missed_order_signal`、`analyst_expectation_missing`。

### Phase D：LLM 收盘复盘

目标：LLM 只做归因、反证和解释质量增强，不直接改策略。

交付物：
- `llm_review.py`。
- `LLMReviewContract`。
- LLM 只读取 review packet，不读全市场。
- LLM 输出失败只写 `review_errors`，不污染 `optimization_signals`。
- token 成本和调用日志写入 scratchpad/tool events。

验收：
- 无 API key 时系统照常运行确定性复盘。
- 有 API key 时只处理推荐股、盲点股、异常样本。
- LLM 的 `EXTRACTED` claim 必须有 evidence。
- LLM 建议默认进入 `candidate` 状态，不直接被 evolution 消费。

### Phase E：知识图谱和记忆增强

目标：让系统能查询类似案例和跨天模式。

交付物：
- 图谱写入扩展到 MarketDay、Stock、PickDecision、Outcome、NewsEvent、ReviewEvidence、StrategyGene、EvolutionEvent。
- 边带 confidence 和 evidence。
- FTS5 memory 写入复盘摘要、错误类型、优化信号、策略进化记录。
- 相似案例 API。

验收：
- 可以查询某个 gene 在类似市场环境下的历史表现。
- 可以查询某个错误类型过去出现在哪些股票/行业。
- 图谱边区分 EXTRACTED / INFERRED / AMBIGUOUS。

### Phase F：预盘 LLM 辅助

目标：让 LLM 在候选池收敛后做反证和解释增强。

交付物：
- Planner Agent：决定今日关注行业和风险。
- Analyst Agents：只读候选 packet。
- Pick Evaluator：schema、风险、未来函数检查。
- LLM 不能直接扫描几千只股票。
- LLM 不能绕过确定性风险规则。

验收：
- 全市场扫描仍由代码完成。
- LLM 只看 Top N 候选和盲点历史。
- LLM 输出不合格时推荐降级为 WATCH 或丢弃。
- 推荐理由更完整，但模拟盘仍由确定性代码执行。

### Phase G：日常运行硬化

目标：把系统变成可以每天使用的个人工具。

交付物：
- APScheduler 真实任务。
- 失败重试、失败告警、任务状态页。
- 历史回测批处理。
- Challenger/Champion 并行表现对比页。
- promotion/rollback 前端操作。
- 数据源健康监控。

验收：
- 每天可自动跑 8:00、9:25、15:05、15:30、周六进化任务。
- 每个任务可手动重跑。
- 失败不会破坏已有数据。
- 用户能看到哪一步失败、失败原因、影响范围。

## 下一阶段详细执行计划：真实数据最小闭环

目标：用真实历史行情跑通一整天。

```text
init live db
-> sync_stock_universe
-> sync_trading_calendar
-> sync_daily_prices
-> sync_index_prices
-> publish_canonical_prices
-> preopen_pick
-> simulate
-> deterministic_review
-> blindspot_review
-> gene_review
-> system_review
-> optimization_signals
```

不做：
- 不接 LLM。
- 不接实盘交易。
- 不接 Tushare。
- 不做公告 PDF 抽取。
- 不追求策略收益，只验收数据链路正确。

### 1. Mode 与数据库隔离

实现要求：
- 增加运行模式：`demo | live`。
- 默认路径：
  - demo：`var/stock_select_demo.db`
  - live：`var/stock_select_live.db`
  - legacy：`var/stock_select.db` 保留兼容。
- CLI 增加：
  - `--mode demo|live`
  - `init-db --mode live`
  - `seed-demo --mode demo`
  - `pipeline --mode live --date YYYY-MM-DD`
- live mode 下执行 `seed-demo` 必须失败，错误信息明确：`seed-demo is not allowed in live mode`。
- API dashboard 返回 `runtime_mode`、`database_role`、`is_demo_data`。

验收：
- demo/live 物理 DB 分离。
- live DB 初始化后没有 demo 财报、demo 订单、demo KPI。
- 前端顶部显示 `DEMO` 或 `LIVE`。

### 2. Provider 接口扩展

新增统一数据对象：
- `StockUniverseItem`
- `TradingCalendarItem`
- `SourcePrice`
- `SourceIndexPrice`

Provider 方法：
- `fetch_stock_universe()`
- `fetch_trading_calendar(start, end)`
- `fetch_daily_prices(trading_date, stock_codes)`
- `fetch_index_prices(trading_date, index_codes)`

默认 provider：
- `AkShareProvider`
- `BaoStockProvider`
- `DemoProvider`

验收：
- mock provider 可以完整驱动测试。
- AKShare/BaoStock 输出统一 stock code 格式：`000001.SZ`、`600000.SH`。
- provider 内部处理中文字段名，外部不出现源特定字段名。

### 3. Schema 补齐

优先复用现有表，只追加必要字段。

需要补齐：
- `data_sources.source_reliability`
- `source_daily_prices.is_limit_up`
- `source_daily_prices.is_limit_down`
- `source_index_prices`
- `index_prices`
- `trading_days.trend_type`
- `trading_days.turnover_level`
- `trading_days.market_environment`
- `stocks.list_date`
- `stocks.is_st`

验收：
- migration 兼容已有 demo DB。
- `init_db` 可重复执行。
- 所有新增表/字段不破坏现有测试。

### 4. 数据同步流程

将 `sync_data` 拆成内部子任务：
- `sync_stock_universe`
- `sync_trading_calendar`
- `sync_daily_prices`
- `sync_index_prices`
- `publish_canonical_prices`
- `classify_market_environment`

CLI 支持额外阶段：
- `run-phase sync_stock_universe`
- `run-phase sync_trading_calendar`
- `run-phase sync_daily_prices`
- `run-phase sync_index_prices`
- `run-phase publish_canonical_prices`
- `run-phase classify_market_environment`

验收：
- 任一子任务可单独重跑。
- 同一天重复同步不重复插入。
- 某个 source 失败时，另一个 source 成功仍可发布 warning 数据。

### 5. Canonical Price 发布规则

规则固定如下：
- AKShare 有，BaoStock 有，close 差异 <= 0.3%：发布 AKShare，check status = `ok`。
- AKShare 有，BaoStock 有，close 差异 > 0.3%：发布 AKShare，check status = `warning`。
- AKShare 有，BaoStock 无：发布 AKShare，check status = `warning`。
- AKShare 无，BaoStock 有：发布 BaoStock，check status = `missing_primary`。
- 双源都无：不发布 `daily_prices`，check status = `missing_all`。

验收：
- 单元测试覆盖全部 5 种情况。
- 前端数据质量显示 warning/missing 数量。
- 策略不能选择没有 canonical price 的股票。

### 6. 真实市场环境分类

初版规则：
- 取沪深 300 或上证指数最近 20 个交易日。
- 20 日收益 > 3%：`uptrend`。
- 20 日收益 < -3%：`downtrend`。
- 否则：`range`。
- 20 日日收益标准差 > 2%：`high`。
- 20 日日收益标准差 < 0.8%：`low`。
- 否则：`medium`。
- 当前成交额 / 20 日均额 > 1.2：`expanding`。
- 当前成交额 / 20 日均额 < 0.8：`contracting`。
- 否则：`normal`。

验收：
- 数据不足 20 天时写 `unknown`，不报错。
- 预盘 target date 只能使用 `< target_date` 的指数数据。
- `dashboard` 展示市场环境。

### 7. 候选池真实数据适配

硬过滤：
- 非 active 股票排除。
- ST 排除。
- 停牌排除。
- 无 canonical price 排除。
- 上市天数不足 60 天排除。
- 最近 20 日平均成交额低于参数阈值则排除。

真实数据缺失处理：
- 基本面缺失：`fundamental_score=0`，packet 记录 `data_missing`。
- 事件缺失：`event_score=0`，packet 记录 `data_missing`。
- 行业缺失：`sector_score=0`，packet 记录 `data_missing`。
- 不允许 fallback 到 demo facts。

验收：
- 真实 live DB 中没有 demo facts 时，候选仍可跑，但复盘能显示缺失原因。
- `candidate_scores.packet_json` 包含 source 和 missing fields。
- `deterministic_review` 能把关键缺失写入 `review_errors`。

### 8. API 与前端

新增/扩展 API：
- `GET /api/data/status?date=YYYY-MM-DD`
- `GET /api/data/quality?date=YYYY-MM-DD&status=`
- `POST /api/data/sync?date=YYYY-MM-DD&dataset=`
- `GET /api/dashboard` 返回 `runtime_mode`、`market_environment`、`data_status`、`data_quality_summary`。

前端改动：
- 顶部显示 `DEMO` / `LIVE`。
- Dashboard 增加数据状态摘要。
- 数据质量 panel 显示 source、dataset、status、rows_loaded、error、warning count。
- 如果是 live mode 但财务/事件数据缺失，显示“行情真实，基本面/事件未接入”。

验收：
- 前端 build 通过。
- live mode 页面不会让用户误以为财务/事件也是真实完整数据。

### 9. 测试计划

单元测试：
- mode 解析和 DB path 选择。
- live 禁止 `seed-demo`。
- provider stock code 标准化。
- canonical price 5 种发布规则。
- `sync_data` 幂等。
- source failure 降级。
- 预盘禁止读取目标日价格。
- market environment 数据不足返回 unknown。
- ST/停牌/无价格过滤。
- live 候选不使用 demo facts。

集成测试：
- mock AKShare + mock BaoStock 跑 live-style pipeline。
- 双源差异生成 warning。
- 缺 primary 时发布 secondary。
- 重跑同一日期 pick/outcome/review 不重复。
- API 返回 runtime mode 和 data quality。
- 前端 build 通过。

手动 smoke test：
- 初始化 live DB。
- 同步一个真实历史交易日。
- 查询 dashboard。
- 查询 data quality。
- 运行 pipeline。
- 打开单股复盘。
- 确认 evidence 使用真实行情 source。

### 10. 执行顺序

1. Mode/DB 隔离。
2. Provider dataclass 和 mock provider。
3. 真实 AKShare/BaoStock provider。
4. Canonical publish 和 data quality。
5. 真实 pipeline 跑通。
6. 验收与文档。

### 11. 最终验收标准

- `python3 -m unittest discover -s tests` 通过。
- `npm run build` 通过。
- demo DB 和 live DB 分离。
- live DB 不包含 demo review facts。
- 一个真实历史交易日可以完整 pipeline。
- 重跑同一天不会重复或外键失败。
- Dashboard 显示 live mode、market environment、data quality。
- 单股复盘可以展示真实行情 evidence。
- 财务/事件未接入时，系统明确显示缺失，不伪造多维结论。

## Assumptions

- 下一阶段仍是本机单用户系统。
- 不接实盘交易。
- 不接 LLM。
- 不接 Tushare。
- AKShare 是主源，BaoStock 是校验源和 fallback。
- 策略收益不是下一阶段验收目标，数据链路正确性才是目标。
- 若真实接口字段和预期不同，先在 provider 内部适配，不改上层业务契约。
