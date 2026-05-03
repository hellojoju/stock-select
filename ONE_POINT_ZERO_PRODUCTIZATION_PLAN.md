# 自我进化 A 股选股系统 1.0 产品化开发计划

Last updated: 2026-04-26

## 目的

本文档用于把最近一次整体评审发现的问题正式落档，并给出面向 1.0 版本的详细开发计划。

当前系统已经不是空 demo：真实行情、候选池、模拟盘、确定性复盘、LLM 复盘骨架、盲点复盘、优化信号、策略进化、知识库和图谱都已有代码和测试。但要成为一个真正有实用价值的个人 A 股投研产品，下一阶段重点不应继续堆新概念，而应补齐：

- 真实成交约束。
- 复盘证据链。
- 新闻/公告/图谱与复盘闭环。
- 策略进化审计。
- 日常运行稳定性。
- 前端可解释、可操作、可追溯体验。

## 状态标记规则

- `[TODO]`：尚未开始。
- `[IN_PROGRESS]`：正在开发。
- `[VERIFY]`：代码已实现，等待测试或 live smoke。
- `[BLOCKED]`：被数据授权、接口限制、外部服务阻塞。
- `[DONE]`：实现、测试、文档和验收均完成。
- `[DEFERRED]`：明确延期到 1.0 之后。

每完成一个任务，必须补充：

- 完成日期。
- 修改文件。
- 验证命令。
- 是否影响 live 数据。
- 已知限制。

## 当前验证基线

最近一次验证：

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q src
cd web && npm run build
```

结果：

- `pytest`：271 passed, 1 skipped。
- `compileall`：通过。
- `npm run build`：通过。

说明：测试通过代表现有代码路径自洽，但不代表 1.0 产品可用性已达标。以下问题仍需作为 1.0 必修项处理。

## 一、Review Findings 落档

### F1：涨跌停成交约束目前基本失效

- 状态：`[TODO]`
- 优先级：P1
- 文件：`src/stock_select/simulator.py`
- 位置：`simulate_day` 中 `prev_close` 判断逻辑。

问题：

当前模拟器用 `prev_close` 判断开盘是否涨跌停，但 `daily_prices` 表没有稳定提供 `prev_close` 字段。缺失时回退为 `entry_price`，导致涨跌停判断几乎永远为 false。结果是系统可能模拟买入现实中买不到的股票，收益和进化信号会偏乐观。

修复目标：

- canonical 行情必须能得到前收盘价。
- 模拟盘必须识别：
  - 开盘涨停无法买入。
  - 停牌无法买入。
  - 无开盘价无法买入。
  - 成交量不足无法完全成交。
  - 一字涨停/跌停要单独记录未成交原因。

建议实现：

1. 在发布 canonical price 时补充 `prev_close`。
   - 如果不改表，可在模拟时查询上一交易日 `daily_prices.close`。
   - 更推荐给 `daily_prices` 增加 `prev_close REAL`，由 `publish_canonical_prices` 写入。
2. 在 `sim_orders` 或新表中记录未成交订单。
   - 当前未成交直接 `continue`，用户看不到为什么没买到。
   - 建议新增 `sim_order_status` 或扩展 `sim_orders.status/reject_reason`。
3. 将涨跌停规则按 A 股真实规则细化：
   - 普通股票 10%。
   - 创业板/科创板 20%。
   - ST 5%。
   - 北交所 30%。
4. 加入手续费、滑点、冲击成本配置。

验收标准：

- 单元测试覆盖：
  - 无 `prev_close` 时查询上一交易日 close。
  - 开盘涨停未成交。
  - 停牌未成交。
  - 成交量不足部分或全部未成交。
  - 普通/ST/创业板不同涨跌停幅度。
- 前端模拟盘表能显示：
  - `成交`
  - `未成交`
  - `未成交原因`
  - `费用`
  - `滑点`

### F2：LLM 复盘重复运行不会更新建议错误和建议信号

- 状态：`[TODO]`
- 优先级：P1
- 文件：`src/stock_select/llm_review.py`
- 位置：`_persist_llm_review`

问题：

`llm_reviews` 冲突更新时只更新：

- `attribution_json`
- `reason_check_json`
- `summary`
- `status`

但没有更新：

- `suggested_errors_json`
- `suggested_signals_json`

如果同一条复盘重跑，页面可能展示旧建议，策略进化可能消费过期信号。

修复目标：

- LLM 复盘重跑后，所有 LLM 输出字段必须一致更新。
- 旧的 LLM 建议如果已经被人工接受或消费，需要保留审计记录，但不能默默覆盖状态。

建议实现：

1. 修改 `ON CONFLICT(decision_review_id) DO UPDATE`。
   - 更新 `suggested_errors_json`。
   - 更新 `suggested_signals_json`。
   - 更新 `created_at` 或新增 `updated_at`。
2. 对 LLM 生成的 optimization signals 使用稳定 hash。
   - 相同复盘、相同 signal 不重复。
   - 信号内容变化时产生新 signal 或新版本。
3. 增加 `llm_review_versions` 或 `llm_scratchpad` 查询入口。
   - 用户能看到每次 LLM rerun 的结果差异。
4. LLM 建议默认保持 `candidate`，不直接被进化消费。

验收标准：

- 单元测试：
  - 第一次 LLM review 写入 suggested errors/signals。
  - 第二次 rerun 改变 suggested errors/signals 后，`llm_reviews` 展示新值。
  - 已 accepted/consumed 的旧 signal 不被删除。
  - scratchpad 保留两次调用日志。
- 前端：
  - LLM 复盘页显示 rerun 时间。
  - 显示 token/cost。
  - 能区分当前建议和历史建议。

### F3：文档查询接口无股票过滤时会生成无效 SQL

- 状态：`[TODO]`
- 优先级：P1
- 文件：`src/stock_select/news_providers.py`
- 位置：`query_documents`

问题：

`query_documents` 只有传 `stock_code` 时才 join `document_stock_links dsl`，但 SELECT 固定引用：

- `dsl.relation_type`
- `dsl.confidence`

当不传 `stock_code` 做全量知识库查询时，会生成无效 SQL。

修复目标：

- 知识库文档接口支持：
  - 全量查询。
  - 按日期查询。
  - 按 source/source_type 查询。
  - 按股票查询。
  - 按关键词 FTS 查询。
- 不同查询条件下 SQL 都稳定可用。

建议实现：

1. 无 `stock_code` 时使用 `LEFT JOIN document_stock_links dsl`。
2. 如果一个文档关联多只股票，避免重复行。
   - 可用 `GROUP_CONCAT(dsl.stock_code)`。
   - 或返回 document + links 子查询。
3. 修复 `search_documents_fts` 中 FTS rowid 与 document_id 的关联方式。
   - 当前通过 `doc_` + printf 推测 document_id，较脆弱。
   - 建议 documents_fts 增加 `document_id UNINDEXED` 或使用 external content 触发器。
4. API 返回结构统一为：

```json
{
  "documents": [],
  "total": 0,
  "filters": {},
  "source_status": {}
}
```

验收标准：

- 单元测试：
  - 无股票过滤可查询。
  - 按股票过滤可查询。
  - 按日期过滤可查询。
  - 按 source_type 过滤可查询。
  - 关键词检索能返回 document_id。
- 前端：
  - 数据与运行页可打开知识库文档列表。
  - 单股复盘能看到该股票相关新闻/公告。

### F4：事件和基本面真实源仍不完整

- 状态：`[TODO]`
- 优先级：P2
- 文件：`src/stock_select/data_ingestion.py`
- 位置：
  - `AkShareProvider.fetch_fundamentals`
  - `BaoStockProvider.fetch_event_signals`

问题：

当前多维因子层已有结构，但部分 provider 仍不完整：

- AKShare 基本面未配置。
- BaoStock 事件信号返回空数组。
- 事件大多仍是标题级分类。

这会导致很多股票的候选评分仍退回技术面为主，偏离最初“不能纯技术选股”的目标。

修复目标：

- 候选评分必须稳定包含：
  - 技术。
  - 基本面。
  - 行业/板块。
  - 事件。
  - 风险。
- 缺失时必须清楚显示缺失来源，而不是伪装为中性或负面。

建议实现：

1. 基本面：
   - BaoStock 继续作为主源。
   - AKShare 补充财务摘要、估值、业绩预告等免费接口。
   - 引入 `as_of_date` 保守可见日。
2. 事件：
   - 官方公告索引作为主源。
   - 东方财富/新浪财经作为新闻源。
   - PDF 正文抽取只对推荐股、盲点股、高影响事件执行。
3. 风险：
   - ST、退市风险、监管问询、处罚、诉讼、减持、质押等单独归类。
4. 数据覆盖率：
   - 每个交易日生成 factor coverage。
   - 前端展示每个候选的缺失字段和来源状态。

验收标准：

- 对一个真实历史日，候选 packet 中每只股票包含：
  - `technical.source`
  - `fundamental.source | data_missing`
  - `sector.source | data_missing`
  - `event.source | data_missing`
  - `risk.source | data_missing`
- 前端五维评分和来源表一致。
- 复盘错误能区分：
  - 策略没利用已有证据。
  - 数据源缺失。
  - 事后事件不可惩罚。

### F5：图谱仍偏基础连线，尚未成为复盘核心证据层

- 状态：`[TODO]`
- 优先级：P2
- 文件：`src/stock_select/graph.py`
- 位置：`sync_document_graph`

问题：

当前图谱主要建立：

- Document -> Stock 的 `MENTIONS` 关系。

但复盘核心节点尚未稳定进入图谱：

- ReviewEvidence。
- ReviewError。
- OptimizationSignal。
- EvolutionEvent。
- StrategyGene。
- Outcome。
- NewsEvent/Announcement/Event。

Graphify 的核心价值是可审计关系网络，而不是简单可视化。现在图谱还没有真正支撑复盘和策略进化。

修复目标：

- 图谱成为复盘证据召回层。
- 单股复盘可以查到：
  - 新闻/公告。
  - 财报/预期差。
  - 风险事件。
  - 历史相似案例。
  - 该股票曾经产生过哪些 review error 和 optimization signal。
- 策略复盘可以查到：
  - 某 gene 在哪些图谱社区里表现好/差。
  - 哪些错误类型跨行业、跨股票重复出现。

建议实现：

1. 扩展节点类型：
   - `ReviewEvidence`
   - `ReviewError`
   - `OptimizationSignal`
   - `EvolutionEvent`
   - `NewsEvent`
   - `Announcement`
   - `FinancialMetric`
   - `OrderContract`
   - `RiskEvent`
2. 扩展边类型：
   - `SUPPORTS_DECISION`
   - `CONTRADICTS_DECISION`
   - `GENERATED_ERROR`
   - `GENERATED_SIGNAL`
   - `EVOLVED_TO`
   - `SIMILAR_TO`
   - `DISCLOSES_EVENT`
3. 所有边保留 Graphify 语义：
   - `EXTRACTED`
   - `INFERRED`
   - `AMBIGUOUS`
   - `confidence_score`
   - `source_document_id`
   - `evidence_text`
   - `visibility`
   - `as_of_date`
4. 新增相似案例 API：
   - `GET /api/graph/stocks/{stock_code}/neighborhood?date=`
   - `GET /api/graph/similar-cases?stock_code=&date=&error_type=`

验收标准：

- 单股复盘能展示图谱邻域。
- 每条图谱边可追溯到 evidence/document。
- 复盘生成的 optimization_signal 能引用 graph edge。
- 图谱导出 `graphify-out/graph.json` 可用于离线审计。

## 二、1.0 产品目标

1.0 不是指所有设想都完成，而是指系统具备日常实用价值：

```text
真实数据可用
-> 早盘推荐可信
-> 模拟盘接近真实约束
-> 收盘复盘能解释对错
-> 新闻/公告/图谱能支撑证据
-> 策略优化信号可审计
-> 每天可以稳定运行
```

1.0 必须回答用户的核心问题：

1. 今天系统能不能用？
2. 今天推荐哪些股票？
3. 为什么推荐？
4. 这些证据在早盘前是否可见？
5. 收盘验证结果如何？
6. 错误是策略问题、数据缺失，还是事后事件？
7. 这次复盘产生了什么优化信号？
8. 策略是否应该进化、推广或回滚？

## 三、1.0 范围边界

### 1.0 必须做

- 真实行情和多维因子可追溯。
- 模拟盘真实成交约束第一版。
- 单股复盘产品化。
- 策略整体复盘产品化。
- 官方公告和财经新闻进入知识库。
- 图谱与复盘 evidence/signal 打通。
- 策略进化全流程可审计。
- 日常运行状态和失败原因可见。

### 1.0 暂不做

- 实盘交易。
- 多用户权限。
- 云端部署。
- Wind/Choice/iFinD 等商业授权源强依赖。
- 对所有新闻全文做 LLM 深度抽取。
- 高频分钟级交易策略。

## 四、1.0 开发路线图

### Sprint 1：可信度缺陷修复

目标：修掉会直接误导用户或破坏后端稳定性的 P1 问题。

| 状态 | 编号 | 任务 | 文件 | 验收 |
| --- | --- | --- | --- | --- |
| [DONE] | S1.1 | 修复涨跌停成交约束 | `simulator.py`, `data_ingestion.py`, `db.py` | 开盘涨停未成交，前端显示原因 |
| [DONE] | S1.2 | 记录未成交模拟订单 | `simulator.py`, `db.py`, 前端模拟盘 | 停牌/涨停/量不足都有 reject_reason |
| [DONE] | S1.3 | LLM rerun 更新 suggested errors/signals | `llm_review.py` | 重跑后页面展示新建议 |
| [DONE] | S1.4 | 修复知识库全量查询 SQL | `news_providers.py` | 无 stock_code 查询不报错 |
| [DONE] | S1.5 | 为上述问题补单元测试 | `tests/*` | 新增测试全部通过 |

验证命令：

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q src
cd web && npm run build
```

### Sprint 2：复盘页面产品化

目标：让复盘成为产品核心，而不是字段堆叠。

| 状态 | 编号 | 任务 | 说明 |
| --- | --- | --- | --- |
| [DONE] | S2.1 | 单股复盘增加”一句话结论” | 面向散户可读 |
| [DONE] | S2.2 | 盘前证据/收盘验证/事后事件三段式 | 严格区分是否惩罚策略 |
| [DONE] | S2.3 | 错误归因分组 | 可优化、数据缺失、事后事件、执行约束 |
| [DONE] | S2.4 | 复盘证据时间线标准化 | source、source_url、published_at、as_of_date、visibility |
| [DONE] | S2.5 | 策略整体复盘增加证据 edge | 不只看收益，还看证据命中 |
| [DONE] | S2.6 | LLM 复盘展示证据引用和成本 | LLM 只做解释增强 |

验收标准：

- 用户打开任意单股复盘，不需要看数据库字段也能理解：
  - 为什么选。
  - 结果如何。
  - 错在哪里。
  - 下一步怎么改。
- `POSTDECISION_EVENT` 明确显示“不惩罚早盘策略”。

### Sprint 3：知识库最小闭环

目标：把新闻、公告、个股资讯真正变成复盘证据。

| 状态 | 编号 | 任务 | 说明 |
| --- | --- | --- | --- |
| [DONE] | S3.1 | 修复 raw_documents 查询和 FTS | 支持全量、股票、日期、关键词 |
| [DONE] | S3.2 | 官方公告源 smoke | 巨潮、上交所、深交所至少稳定一个真实样本 |
| [DONE] | S3.3 | 财经新闻源 smoke | 东方财富/新浪至少稳定一个真实样本 |
| [DONE] | S3.4 | 文档实体链接 | 股票代码、公司名、行业 |
| [DONE] | S3.5 | 标题/摘要事件分类 | 订单、业绩、监管、处罚、减持、风险 |
| [DONE] | S3.6 | 单股复盘接入相关新闻/公告 | 展示证据卡片和来源链接 |

验收标准：

```text
sync_news
-> raw_documents
-> document_stock_links
-> event extraction
-> stock review evidence timeline
```

### Sprint 4：Graphify-style 图谱复盘闭环

目标：让图谱不是装饰，而是复盘和进化的证据网络。

| 状态 | 编号 | 任务 | 说明 |
| --- | --- | --- | --- |
| [DONE] | S4.1 | 扩展 ReviewEvidence 图谱节点 | evidence 写入 graph_nodes |
| [DONE] | S4.2 | 扩展 ReviewError 图谱节点 | error 写入 graph_nodes |
| [DONE] | S4.3 | 扩展 OptimizationSignal 图谱节点 | signal 写入 graph_nodes |
| [DONE] | S4.4 | 扩展 EvolutionEvent 图谱节点 | champion/challenger 可追溯 |
| [DONE] | S4.5 | 复盘图谱邻域 API | 单股、策略、错误类型查询 |
| [DONE] | S4.6 | Graphify JSON 导出验收 | 离线图谱报告可生成 |

验收标准：

- 单股复盘页能看到：
  - 相关公告。
  - 相关新闻。
  - 相关错误。
  - 相关优化信号。
  - 历史相似案例。

### Sprint 5：多维真实因子补强

目标：减少系统退化成纯技术选股。

| 状态 | 编号 | 任务 | 说明 |
| --- | --- | --- | --- |
| [DONE] | S5.1 | 基本面覆盖率监控 | 财报、成长、现金流、负债、估值 |
| [DONE] | S5.2 | 事件覆盖率监控 | 公告、新闻、风险事件 |
| [DONE] | S5.3 | AKShare 基本面补充 | 免费源可用则接入 |
| [DONE] | S5.4 | BaoStock 事件源替代方案 | BaoStock 空事件不作为有效源 |
| [DONE] | S5.5 | 候选评分缺失降权策略 | 缺数据不等于负面 |
| [DONE] | S5.6 | 前端因子覆盖提醒 | 每只候选显示真实来源状态 |

验收标准：

- live 历史日候选 packet 每个维度都有 source 或 data_missing。
- 策略复盘能按维度统计：
  - 命中收益。
  - 缺失率。
  - 错误贡献。

### Sprint 6：策略进化审计增强

目标：让策略进化能被用户信任。

| 状态 | 编号 | 任务 | 说明 |
| --- | --- | --- | --- |
| [DONE] | S6.1 | 信号样本详情页 | 每个 signal 展示来源 review/evidence |
| [DONE] | S6.2 | 参数 diff 可视化 | old/new、变化幅度、是否超过阈值 |
| [DONE] | S6.3 | Champion/Challenger 同期对比 | 收益、回撤、胜率、样本数 |
| [DONE] | S6.4 | Promotion 门槛展示 | 为什么可推广/不可推广 |
| [DONE] | S6.5 | Rollback 审计 | 回滚原因、影响对象、历史保留 |
| [DONE] | S6.6 | 进化事件写图谱 | 与 signal/review/gene 关联 |

验收标准：

- 用户在推广 Challenger 前，能看到：
  - 为什么创建。
  - 消费了哪些信号。
  - 参数变了什么。
  - 新旧表现差异。
  - 回滚后会发生什么。

### Sprint 7：日常运行稳定化

目标：让系统每天可用，而不是每次靠开发者手动排障。

| 状态 | 编号 | 任务 | 说明 |
| --- | --- | --- | --- |
| [DONE] | S7.1 | APScheduler 开关和状态页 | 8:00/9:25/15:05/15:30/周六 + start/stop/status API |
| [DONE] | S7.2 | 任务失败重试 | 指数退避重试 (5s/10s/20s)，max_retries=2 |
| [DONE] | S7.3 | 运行日报 | /api/monitor/daily-report + SchedulerPanel 日报按钮 |
| [DONE] | S7.4 | 数据源健康评分 | /api/monitor/health + DataMemoryPage 健康面板 |
| [DONE] | S7.5 | live smoke 脚本 | scripts/smoke_test.py --date 2024-04-22 |
| [DONE] | S7.6 | 操作文档 | OPERATION_MANUAL.md |

验收标准：

- 一条命令可以完成 1.0 smoke。
- 前端能看到每个阶段是否成功。
- 失败时能看到影响范围。

## 五、1.0 前端验收清单

### 今日工作台

- [DONE] 显示今天是否可用。
- [DONE] 显示行情/因子/证据/LLM 状态。
- [DONE] 推荐队列可点击。
- [DONE] 模拟盘显示成交/未成交原因。
- [DONE] 人工待办来自真实数据。

### 选股研究

- [DONE] 五维评分雷达图和来源表一致。
- [DONE] 候选筛选全部真实生效。
- [DONE] hard filters 来自后端。
- [DONE] 缺失字段明确标注 data_missing。

### 复盘中心

- [DONE] 单股复盘三段式：盘前、收盘、事后。
- [DONE] 策略复盘显示 factor edge 和 evidence edge。
- [DONE] 盲点复盘按可学习/不可惩罚/正确避开/数据缺失分组。
- [DONE] LLM claim 必须显示证据引用。
- [DONE] 优化信号能跳转到策略进化。

### 策略进化

- [DONE] dry-run 可审计。
- [DONE] propose/promote/rollback 有确认和影响范围。
- [DONE] Champion/Challenger 对比清楚。
- [DONE] signal 样本可追溯。

### 数据与运行

- [DONE] 数据源健康真实。
- [DONE] 知识库文档可检索。
- [DONE] 图谱可查询。
- [DONE] 调度和失败原因可见。

## 六、1.0 最终验收标准

### 自动测试

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q src
cd web && npm run build
```

要求：

- 全部通过。
- 不允许因真实网络依赖导致单元测试不稳定。

### Live smoke

固定一个真实历史交易日，例如：

```bash
.venv/bin/python -m stock_select.cli --mode live run-phase sync_data --date 2024-04-22
.venv/bin/python -m stock_select.cli --mode live run-phase sync_factors --date 2024-04-22
.venv/bin/python -m stock_select.cli --mode live run-phase process_announcements --date 2024-04-22
.venv/bin/python -m stock_select.cli --mode live run-phase preopen_pick --date 2024-04-22
.venv/bin/python -m stock_select.cli --mode live run-phase simulate --date 2024-04-22
.venv/bin/python -m stock_select.cli --mode live run-phase deterministic_review --date 2024-04-22
.venv/bin/python -m stock_select.cli --mode live run-phase blindspot_review --date 2024-04-22
.venv/bin/python -m stock_select.cli --mode live run-phase gene_review --date 2024-04-22
.venv/bin/python -m stock_select.cli --mode live run-phase system_review --date 2024-04-22
```

验收：

- dashboard 可打开。
- 单股复盘可打开。
- 策略复盘可打开。
- 数据质量可解释。
- 知识库文档可查询。
- 图谱邻域可查询。
- 模拟盘成交/未成交原因可见。
- 复盘产生 optimization_signals。

## 七、风险和约束

### 数据源合规

- 同花顺、指南针、九方智投等商业平台不能默认大规模爬取。
- 1.0 优先使用：
  - 官方公开公告。
  - 合法公开新闻。
  - AKShare/BaoStock 免费源。
  - 用户手动导入。

### Token 成本

- 全量新闻不进 LLM。
- LLM 只处理：
  - 推荐股。
  - 盲点股。
  - 异常样本。
  - 用户手动指定股票。

### 策略收益

- 1.0 不以收益率为验收目标。
- 1.0 以“数据真实、复盘可信、流程稳定、可审计可回滚”为验收目标。

## 八、推荐执行顺序

建议严格按以下顺序推进：

1. Sprint 1：可信度缺陷修复。
2. Sprint 2：复盘页面产品化。
3. Sprint 3：知识库最小闭环。
4. Sprint 4：图谱复盘闭环。
5. Sprint 5：多维因子补强。
6. Sprint 6：策略进化审计增强。
7. Sprint 7：日常运行稳定化。

不要跳过 Sprint 1。当前 P1 问题会直接影响用户对系统的信任，也会污染策略进化样本。

