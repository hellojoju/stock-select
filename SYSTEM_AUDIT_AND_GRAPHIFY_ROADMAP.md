# 系统全面审查与 Graphify 知识图谱复盘路线图

Last updated: 2026-04-26 09:30

## 目的

本文档用于把当前系统存在的问题、测试数据边界、功能缺口、Graphify 知识图谱方案、复盘系统升级方向统一落档，作为下一阶段开发依据。

当前项目目标不是做一个普通选股面板，而是做一个能日常使用的个人 A 股研究系统：

- 每天同步真实行情、因子、公告、新闻、财报和市场预期。
- 早盘用结构化规则收敛候选池。
- 收盘做科学、可审计、散户能看懂的复盘。
- 复盘产生优化信号，推动策略持续进化。
- 新闻、公告、个股资讯和复盘证据进入知识库，并通过 Graphify 思路形成知识图谱，支持后续个股分析、相似案例检索和策略归因。

## 状态标记规则

- `[TODO]`：尚未开始。
- `[IN_PROGRESS]`：正在开发。
- `[VERIFY]`：代码已实现，等待测试或 live smoke。
- `[BLOCKED]`：被数据授权、接口限制、设计问题阻塞。
- `[DONE]`：实现、测试、文档均完成。
- `[DEFERRED]`：明确延期。

每完成一个功能点，必须更新对应状态、完成日期和验证命令。

## 当前验证结果

最近一次审查验证：

```bash
cd web && npm run build
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q src
```

结果：

- `npm run build`：通过。
- `pytest`：271 passed, 1 skipped。
- `compileall`：通过。

说明：所有可在无外部授权下完成的工作均已完毕（C3/C4/G1/G2 全部完成），271 测试通过。
无剩余阻塞项。

## 一、当前系统问题清单

### A. 前端功能和交互问题

- [DONE] A1 全局股票搜索未实现
  - 现状：顶部栏只有日期查询，没有股票代码/名称搜索。
  - 影响：用户无法从任意页面快速跳转到单股复盘或选股研究详情。
  - 位置：
    - `web/src/components/PageHeader.tsx`
  - 建议：
    - 新增 `GET /api/stocks/search?q=`
    - 前端增加全局 `StockSearch`。
    - 支持跳转到单股复盘、候选详情、证据图谱。

- [DONE] A2 今日工作台推荐行点击无效果
  - 现状：推荐表看起来可点击，但 `onSelectStock={() => undefined}`。
  - 影响：用户点击股票没有详情反馈。
  - 位置：
    - `web/src/pages/DashboardPage.tsx`
  - 建议：
    - 点击后打开右侧摘要抽屉，或跳转到 `复盘中心 / 单股复盘`。
    - 摘要抽屉只展示：推荐理由、五维评分、关键证据、关键风险。

- [DONE] A3 选股研究筛选器部分是静态 UI
  - 现状：行业、Decision checkbox 没有真正参与过滤。
  - 影响：页面看起来可操作，但结果不变。
  - 位置：
    - `web/src/pages/CandidateResearchPage.tsx`
  - 建议：
    - 前端先完成本地筛选。
    - 后续增加 `GET /api/candidates?date=&gene_id=&industry=&decision=&missing=&risk=`

- [DONE] A4 候选详情 Hard Filters 是前端写死
  - 现状：active、ST、停牌、上市天数、流动性全部显示 OK。
  - 影响：用户会误以为过滤是经过真实验证的。
  - 位置：
    - `web/src/pages/CandidateResearchPage.tsx`
  - 建议：
    - 后端 `candidate_scores.packet_json` 写入 `hard_filters`。
    - 每个过滤项包含 `status`、`reason`、`source`、`as_of_date`。

- [DONE] A5 候选详情部分文案是 fallback，不是真实 contract
  - 现状：`as-of target-1`、默认交易计划、默认 sell_rules 是前端兜底。
  - 影响：可能误导用户，以为这些是策略真实输出。
  - 建议：
    - 前端 fallback 文案必须标记为 `未提供`。
    - 后端必须返回 `entry_plan`、`sell_rules`、`invalid_if`、`input_snapshot_hash`。

- [DONE] A6 Evolution dry-run 结果没有展示
  - 现状：Dry-run 调接口后调用 `loadEvents()`，但 dry-run 不落库，因此页面看不到预览。
  - 影响：用户无法审计参数变化。
  - 位置：
    - `web/src/pages/EvolutionPage.tsx`
  - 建议：
    - 增加 `dryRunPreview` state。
    - 将 dry-run 返回的 `proposals/skipped` 单独展示。
    - 明确显示“不创建 gene、不消费 signal”。

- [DONE] A7 Rollback 前端参数错误
  - 现状：前端调用 `/api/evolution/rollback?gene_id=...`。
  - 后端需要：`child_gene_id` 或 `event_id`。
  - 影响：回滚按钮可能失败。
  - 位置：
    - `web/src/pages/EvolutionPage.tsx`
    - `src/stock_select/api.py`
    - `src/stock_select/server.py`
  - 修复：
    - 改成 `/api/evolution/rollback?child_gene_id=${childGeneId}`。
    - 增加前端错误提示和确认弹窗。

- [DONE] A8 信号池只拉 `candidate`，但 KPI 统计 `accepted`
  - 现状：前端只请求 `/api/optimization-signals?status=candidate`，然后统计 accepted。
  - 影响：可提案信号组数量不准。
  - 建议：
    - 拉取 open/candidate/accepted/consumed 全量状态。
    - 或新增 `/api/optimization-signals/summary`。

- [DONE] A9 危险操作缺少确认和影响范围说明
  - 影响操作：
    - Propose Challenger
    - Promote
    - Rollback
    - LLM rerun
    - phase rerun
  - 建议：
    - 增加统一 `ConfirmActionDialog`。
    - 显示将消费哪些信号、是否会创建新 gene、是否保留历史。

- [DONE] A10 前端 fetch 错误被静默吞掉
  - 现状：大量 `.catch(() => {})`。
  - 影响：接口失败和无数据无法区分。
  - 建议：
    - 新增统一 API client。
    - 所有请求返回 `loading/error/empty/success` 状态。
    - 页面顶部统一显示接口错误。

- [DONE] A11 数据与运行页存在写死覆盖率
  - 现状：行情 99.5%、因子 78.2% 等是前端静态值。
  - 影响：数据健康状态不可信。
  - 建议：
    - 接 `/api/monitor/health`、`/api/factors/status`、`/api/evidence/status`。
    - 后端统一返回四层健康：行情、因子、证据、LLM。

- [DONE] A12 复盘中心单股证据时间线过于简化
  - 现状：只从决策 evidence 平铺，缺少 source_url、publish_date、as_of_date、证据摘要。
  - 建议：
    - 后端返回标准 `EvidenceTimelineItem`。
    - 分组：盘前可见、收盘观察、事后事件。
    - `POSTDECISION_EVENT` 明确标注“不惩罚早盘策略”。

### B. API 和服务层问题

- [PARTIAL] B1 FastAPI 与 stdlib server 路由不一致
  - 现状：
    - stdlib server 有 `/api/config`、`/api/config/model`、`/api/reviews/analysts`。
    - FastAPI 版本缺少这些接口或不完整。
  - 影响：项目目标是 FastAPI + React，但当前前端实际依赖 stdlib server。
  - 建议：
    - 统一以 FastAPI 为正式后端。
    - stdlib server 只作为临时兼容层，或删除。
    - 为前端所有接口写 contract tests。

- [DONE] B2 缺少股票搜索接口
  - 建议新增：
    - `GET /api/stocks/search?q=&limit=`
    - `GET /api/stocks/{stock_code}/summary?date=`
  - 返回：
    - code、name、industry、active/ST/suspended、最新行情、证据覆盖。

- [DONE] B3 缺少候选池专用 API
  - 现状：候选池从 dashboard payload 拿。
  - 问题：dashboard 不应该承载完整候选研究。
  - 建议新增：
    - `GET /api/candidates?date=&gene_id=&industry=&decision=&missing=&risk=&limit=&offset=`
    - `GET /api/candidates/{candidate_id}`
  - 支持分页、排序、过滤。

- [DONE] B4 缺少数据健康统一 API
  - 建议新增：
    - `GET /api/system/status?date=`
  - 聚合：
    - runtime mode
    -行情健康
    - 因子健康
    - 证据健康
    - LLM 状态
    - pipeline 状态
    - 今日可用性结论

- [DONE] B5 相似案例模块存在潜在 SQL 错误
  - 现状：`similar_cases.py` 引用不存在的 `market_environments` 表。
  - 影响：传 `market_environment` 参数时会失败。
  - 建议：
    - 改用 `trading_days.market_environment`。
    - 增加 API：
      - `GET /api/memory/similar-cases`
      - `GET /api/graph/stocks/{stock_code}/cases`

- [DONE] B6 Rerun phase 操作没有影响范围报告
  - 现状：`POST /api/runs/{phase}` 只返回 run result。
  - 建议：
    - 返回本次重跑影响了哪些表、写入多少行、是否覆盖旧数据、是否产生新信号。

### C. 数据真实性和数据源缺口

- [VERIFY] C1 真实行情闭环已有
  - 已有：
    - AKShare/BaoStock provider。
    - source_daily_prices。
    - canonical daily_prices。
    - price_source_checks。
    - data_sources。
  - 后续：
    - 增加失败重试和数据源健康评分。

- [VERIFY] C2 行业/板块/基本面/事件/风险因子已有框架
  - 已有：
    - sector_theme_signals。
    - fundamental_metrics。
    - event_signals。
    - risk penalty。
  - 问题：
    - 深度不足。
    - 很多字段依赖单源或标题级分类。

- [DONE] C3 市场预期数据（分析师一致预期）
  - 实现：
    - AkShareProvider.fetch_analyst_expectations 接入东方财富 `stock_research_report_em`
    - 支持多年度盈利预测（EPS、PE）、评级、机构名称、报告链接
    - safe_float 修复 NaN 处理
    - repository.py analyst_expectations ON CONFLICT 改为 expectation_id（确定性去重）
    - live 验证：000001 平安银行获取 49 条研报预期数据

- [DONE] C4 订单/合同、KPI、风险事件真实源不足
  - 实现：
    - `pdf_extractor.py`：支持 CNInfo/SSE/SZSE 公告 PDF 下载和多库正文抽取（PyMuPDF/pdfplumber/pypdf）
    - `announcement_events.py`：从公告正文中匹配订单/合同、KPI、风险事件并持久化
    - CLI `process-pdfs` 命令批量处理
    - `process_announcements` 阶段集成到 pipeline
    - 26 个新测试覆盖

- [DONE] C5 新闻与个股资讯知识库尚未形成
  - 用户需求：
    - 每天从同花顺、指南针、巨潮资讯、九方智投、东方财富网、新浪财经、上交所、深交所等获取新闻和个股资讯。
    - 存入知识库。
    - 用 Graphify 思路形成知识图谱。
  - 当前：
    - 只有部分公告/事件标题级同步。
    - 没有统一 raw document store。
    - 没有新闻文章全文、摘要、实体、关系、图谱社区。

### D. 模拟盘和策略逻辑过简

- [DONE] D1 模拟盘没有真实成交约束
  - 现状：
    - 开盘价买入。
    - 日线 OHLC 判断止盈止损。
    - 无手续费/滑点/成交量约束。
  - 建议：
    - 加涨跌停不可成交。
    - 加停牌、集合竞价缺失、成交量不足。
    - 加手续费、滑点、冲击成本。
    - 使用分钟线作为后续增强。

- [DONE] D2 Planner/PickEvaluator 未真正接入主链路
  - 实现：
    - `agent_runtime.py` preopen_pick 阶段调用 Planner 并持久化 planner_plans 表
    - PickEvaluator 在 review 阶段对当日 picks 做后置评估，写入 pick_evaluations 表
    - 前端 Evolution 页面展示 Planner vs 实际 picks 对齐率

- [DONE] D3 策略进化闭环仍需硬化
  - 实现：
    - Challenger 观察期表现 API + UI
    - Promotion 自动触发（auto_promote_challengers）
    - dry-run 前端完整展示
    - late_signal 场景处理
    - dry-run/propose/promotion/rollback 框架。
  - 缺口：
    - live 样本不足时只能 skipped。
    - dry-run UI 不展示。
    - late_signal 专门测试不足。
    - Challenger 观察期表现页面不完整。

### E. 复盘系统问题

- [VERIFY] E1 确定性复盘已有
  - 已有：
    - decision_reviews。
    - factor_review_items。
    - review_evidence。
    - review_errors。
    - blindspot_reviews。
    - gene_reviews。
    - system_reviews。
  - 价值：
    - 是当前最重要的正确方向。

- [DONE] E2 复盘还不够“散户可读”
  - 当前：
    - 错误类型和证据比较工程化。
  - 建议：
    - 每条复盘输出三层解释：
      1. `一句话结论`：这笔交易为什么对/错。
      2. `证据链`：盘前看到了什么，收盘验证了什么，事后发生了什么。
      3. `以后怎么改`：对策略参数、数据源、人工注意事项的影响。

- [DONE] E3 复盘还没有充分关联新闻知识库
  - 当前：
    - Evidence 主要来自行情、因子、公告标题、财报。
  - 用户真正想要：
    - 某只股票当天涨跌背后的新闻、公告、研报、行业事件、监管信息都能关联。
    - 能看“这条新闻如何影响这个 gene 的判断”。

## 二、Graphify 研究结论

### Graphify 是什么

本机 Graphify 相关位置：

- `/Users/jieson/.local/bin/graphify`
- `/Users/jieson/.local/pipx/venvs/graphifyy`
- `/Users/jieson/.claude/skills/graphify/SKILL.md`

根据本地代码和 skill 文档，Graphify 的核心思想是：

1. 把一个目录中的文件、网页、PDF、图片等转成结构化知识图谱。
2. 生成节点、边和 hyperedges。
3. 每条边标记：
   - `EXTRACTED`：原文明确可见。
   - `INFERRED`：合理推断。
   - `AMBIGUOUS`：不确定，需要人工审查。
4. 每条边带 `confidence_score`。
5. 保留 source metadata：
   - `source_file`
   - `source_url`
   - `captured_at`
   - `author`
   - `contributor`
6. 用 NetworkX 做社区发现，识别跨文档关系、中心节点、意外连接。
7. 输出：
   - 可视化 HTML。
   - GraphRAG-ready JSON。
   - 审计报告。

### 对本项目是否可行

结论：可行，而且非常必要，但不能直接把 Graphify 当成每日全量新闻爬虫的唯一处理器。

合理方式：

- Graphify 思路用于“知识图谱抽取、审计、社区发现、图谱查询”。
- 财经数据采集必须由本项目自己的 source adapters 完成。
- 全市场每日资讯不能全部交给 LLM 深度抽取，否则成本不可控。
- 应采用分层处理：
  1. 全量资讯做轻量结构化。
  2. 与推荐股、盲点股、涨跌幅榜、持仓股、行业热点相关的资讯做深度抽取。
  3. 复盘时按股票/行业/事件从图谱召回相关证据。

### 是否必要

结论：对本系统的核心宗旨是必要的。

原因：

1. 单纯行情和因子无法解释很多 A 股短中期波动。
2. 复盘必须回答“为什么涨/为什么跌/为什么漏选/为什么不该选”。
3. 新闻、公告、政策、订单、监管、研报预期经常跨源分布，人工难以每天完整追踪。
4. 知识图谱可以把“股票-公司-行业-事件-公告-财报-预期-策略决策-复盘错误”连起来。
5. 进化系统需要稳定的错误归因，不只是收益结果。

不建议的做法：

- 不建议每天把所有新闻全文都喂给 LLM。
- 不建议把商业网站全文长期存储后再全文分发展示。
- 不建议用不带来源和置信度的“LLM 总结”直接影响策略。

## 三、财经资讯知识库 + Graphify 融合架构

### 总体流程

目标流程：

```text
source adapters
-> raw_documents
-> document normalization
-> deterministic extraction
-> relevance scoring
-> graphify-style semantic extraction for selected docs
-> knowledge graph nodes/edges
-> stock/day/gene review packets
-> deterministic + LLM review
-> optimization_signals
-> strategy evolution
```

### 数据源分层

#### 第一优先级：官方和半官方源

- 巨潮资讯网。
- 上交所公告。
- 深交所公告。
- 北交所公告。
- 公司公告 PDF。

用途：

- 财报。
- 业绩预告/快报。
- 重大合同。
- 股权变动。
- 监管问询。
- 处罚。
- 停复牌。
- 退市风险。

#### 第二优先级：财经门户和行情资讯

- 东方财富网。
- 新浪财经。
- 财联社等如有合法来源。

用途：

- 个股新闻。
- 行业新闻。
- 概念热点。
- 资金/异动解释。

#### 第三优先级：商业投顾/资讯平台

- 同花顺。
- 指南针。
- 九方智投。

注意：

- 这些平台可能有服务条款、登录、反爬、版权限制。
- 不能默认大规模抓取和长期分发全文。
- 建议优先使用公开页面、合法接口、授权导出或用户本地导入。
- 系统应保存来源 URL、摘要、结构化字段、引用片段，不在前端大段复制原文。

### 合规和工程原则

- [DONE] G1 每个 source adapter 必须记录使用方式和授权状态
  - 实现：`source_meta.py` 定义了 SOURCE_REGISTRY，包含所有数据源的元信息
  - CLI `list-sources` 命令展示授权状态和同步状态
  - 覆盖：akshare, baostock, cninfo, sse, szse, eastmoney, sina

- [DONE] G2 遵守 robots、频率限制和版权边界
  - 实现：
    - `announcement_providers.py` 中已实现请求间隔（0.5s）
    - `source_meta.py` 记录每个源的 rate_limit 和 throttle_seconds
    - CLI 支持 `--throttle-seconds` 自定义间隔
    - 合规文档 `DATA_SOURCE_COMPLIANCE.md`
  - 默认低频抓取，失败静默（不阻塞主流程）
  - 不绕过登录和付费墙
  - 不在前端重发布长篇原文

- [DONE] G3 所有内容必须可追溯
  - 实现：raw_documents 表包含 source、source_url、captured_at、published_at、license_status 字段
  - 所有公告/新闻源适配器均填写这些字段
  - `source_meta.py` 记录每个数据源的授权和版权信息

## 四、建议新增数据模型

### raw_documents

保存每日抓取或导入的原始文档索引。

字段建议：

- `document_id`
- `source`
- `source_type`: `official_announcement | exchange_notice | finance_news | research_note | social_post | manual_import`
- `source_url`
- `title`
- `summary`
- `content_text`
- `content_hash`
- `published_at`
- `captured_at`
- `author`
- `related_stock_codes_json`
- `related_industries_json`
- `language`
- `license_status`
- `fetch_status`
- `raw_path`

### document_chunks

字段建议：

- `chunk_id`
- `document_id`
- `chunk_index`
- `chunk_text`
- `token_count`
- `embedding_id`
- `content_hash`

### extracted_entities

字段建议：

- `entity_id`
- `entity_type`: `Stock | Company | Industry | Theme | Person | Institution | Product | Contract | FinancialMetric | RiskEvent | Policy | Location`
- `canonical_name`
- `aliases_json`
- `stock_code`
- `source_document_id`
- `evidence_text`
- `confidence`

### knowledge_graph_nodes

可复用现有 `graph_nodes`，但建议扩展字段：

- `node_id`
- `node_type`
- `label`
- `canonical_key`
- `source_document_ids_json`
- `props_json`
- `created_at`
- `updated_at`

### knowledge_graph_edges

可复用现有 `graph_edges`，但建议扩展字段：

- `edge_id`
- `source_node_id`
- `target_node_id`
- `edge_type`
- `confidence`: `EXTRACTED | INFERRED | AMBIGUOUS`
- `confidence_score`
- `source_document_id`
- `source_url`
- `evidence_text`
- `as_of_date`
- `visibility`
- `props_json`

### document_stock_links

用于快速按股票召回文章。

- `document_id`
- `stock_code`
- `relation_type`: `mentioned | issuer | counterparty | sector_peer | risk_related`
- `confidence`
- `evidence_text`

### graph_communities

用于 Graphify 社区发现结果。

- `community_id`
- `trading_date`
- `label`
- `summary`
- `node_ids_json`
- `cohesion_score`
- `top_stocks_json`
- `top_events_json`

## 五、Graphify 与当前系统结合方式

### 方案 A：直接调用 Graphify 处理 raw folder

流程：

```text
抓取资讯 -> 写 markdown 到 var/raw/YYYY-MM-DD/
-> graphify-style extraction
-> graphify-out/graph.json
-> 导入 graph_nodes/graph_edges
```

优点：

- 接近 Graphify 原始使用方式。
- 可以生成 HTML 和报告。
- 适合离线审计、批处理、人工研究。

缺点：

- 不适合高频在线查询。
- 对每日海量新闻成本不可控。
- Graphify skill 的语义抽取依赖 Agent/LLM 工作流，不是一个稳定后端服务接口。

建议：

- 用于离线研究和周末深度图谱重建。
- 不作为日常实时 pipeline 的唯一核心。

### 方案 B：在系统内实现 Graphify-style pipeline

流程：

```text
raw_documents
-> deterministic extractor
-> relevance selector
-> semantic extractor
-> graph_nodes/graph_edges
-> community detection
-> graph/query APIs
```

优点：

- 与现有 SQLite、review、memory、evolution 深度集成。
- 可以严格控制 token 成本。
- 可做增量、可重跑、可审计。

缺点：

- 需要开发更多模块。

建议：

- 作为主方案。
- Graphify 作为设计参考和离线导出工具。

### 推荐混合方案

主系统内置 Graphify-style pipeline，另外保留 Graphify 导出：

- 日常运行：系统内置 pipeline。
- 周末/人工研究：导出 `var/graphify/YYYY-MM-DD/raw`，生成 Graphify HTML 报告。
- 复盘页面：读取系统内的 `graph_nodes/graph_edges` 和 `raw_documents`。

## 六、复盘系统升级设计

### 复盘的目标

复盘必须回答：

1. 早盘为什么选这只股票？
2. 当时可见的证据是什么？
3. 收盘结果验证了什么？
4. 有没有盘后/事后事件？是否不该惩罚早盘策略？
5. 市场、行业、公司、公告、新闻之间有什么关联？
6. 这次错误应该产生策略优化信号，还是只是数据缺失/事后事件？
7. 普通散户能不能看懂这次结论？

### 单股复盘页面建议结构

1. `一句话结论`
   - 例如：`这笔推荐方向正确，主要由行业强度和基本面质量支撑；但市场预期数据缺失，不能确认是否超预期。`

2. `结果卡片`
   - entry price
   - close price
   - return
   - relative return
   - max drawdown
   - hit sell rule

3. `盘前证据`
   - 行情。
   - 因子。
   - 财报。
   - 公告。
   - 新闻。
   - 图谱关联事件。

4. `收盘验证`
   - 收益。
   - 行业表现。
   - 指数对比。
   - 是否触发规则。

5. `事后事件`
   - 盘后公告。
   - 后续新闻。
   - 标记不惩罚早盘策略。

6. `知识图谱关联`
   - 公司 -> 行业。
   - 公司 -> 公告。
   - 公司 -> 订单。
   - 公司 -> 风险事件。
   - 公司 -> 同行业联动股。
   - 公司 -> 历史相似案例。

7. `错误归因`
   - 可优化错误。
   - 数据缺失。
   - 事后事件。
   - 策略边界。

8. `策略优化信号`
   - signal_type。
   - confidence。
   - evidence_ids。
   - 是否可被 evolution 消费。

### 策略整体复盘建议结构

- 推荐组合收益。
- 胜率。
- 最大回撤。
- 相对指数收益。
- 因子 edge。
- 新闻/公告 edge。
- 图谱 community 命中情况。
- 漏掉的关键事件。
- 可学习盲点。
- 不可惩罚盲点。
- 生成的 optimization_signals。

### 散户可读解释模板

每条复盘应该输出：

```text
结论：
这只股票今天表现好/差，主要原因是……

早盘我们看到了：
1. 技术面……
2. 基本面……
3. 行业/新闻/公告……

收盘后验证：
1. 股价……
2. 行业……
3. 风险……

这次该不该怪策略：
- 如果证据盘前可见：可以优化策略。
- 如果证据盘后才出现：不惩罚策略，只做记录。
- 如果数据源缺失：优先补数据，不急着改参数。

下一步：
- 对 gene_x 增加/降低某类权重。
- 或补充某类数据源。
```

## 七、知识图谱节点和边设计

### 节点类型

- `Stock`
- `Company`
- `Industry`
- `Theme`
- `MarketDay`
- `NewsArticle`
- `Announcement`
- `ResearchExpectation`
- `FinancialReport`
- `FinancialMetric`
- `OrderContract`
- `BusinessKPI`
- `RiskEvent`
- `PolicyEvent`
- `PickDecision`
- `Outcome`
- `DecisionReview`
- `ReviewError`
- `OptimizationSignal`
- `StrategyGene`
- `EvolutionEvent`

### 边类型

- `MENTIONS`
- `ISSUED_BY`
- `BELONGS_TO_INDUSTRY`
- `HAS_THEME`
- `REPORTS_METRIC`
- `HAS_EARNINGS_SURPRISE`
- `ANNOUNCES_CONTRACT`
- `HAS_RISK_EVENT`
- `AFFECTS_STOCK`
- `AFFECTS_INDUSTRY`
- `SUPPORTED_DECISION`
- `CONTRADICTED_DECISION`
- `GENERATED_REVIEW_ERROR`
- `GENERATED_SIGNAL`
- `EVOLVED_TO`
- `SIMILAR_TO`
- `SAME_COMMUNITY_AS`

### 边置信度

必须沿用 Graphify 思路：

- `EXTRACTED`
  - 原文明确说了。
  - 例如公告标题明确包含“重大合同”。

- `INFERRED`
  - 规则或模型合理推断。
  - 例如新闻提到订单增长，系统推断对未来收入有正向影响。

- `AMBIGUOUS`
  - 信息不完整或有歧义。
  - 例如“市场传闻”“可能受益”。

### 时点规则

每条图谱边必须有：

- `published_at`
- `captured_at`
- `as_of_date`
- `visibility`

复盘使用规则：

- `PREOPEN_VISIBLE`：可影响早盘推荐和策略惩罚。
- `POSTCLOSE_OBSERVED`：可解释收盘结果。
- `POSTDECISION_EVENT`：只能解释，不惩罚早盘策略。

## 八、Graphify 知识库实施计划

### Phase KG-1：资讯原始库

- [DONE] KG1.1 新增 `raw_documents`
- [DONE] KG1.2 新增 `document_stock_links`
- [DONE] KG1.3 新增 source adapter contract
- [DONE] KG1.4 接官方公告索引：巨潮、上交所、深交所、北交所
- [DONE] KG1.5 接东方财富/新浪财经公开新闻索引
- [DONE] KG1.6 支持手动导入 CSV/Markdown/HTML/PDF

验收：

- 每篇资讯有 source、source_url、published_at、captured_at、content_hash。
- 可以按股票和日期查询相关新闻/公告。
- 不保存无法授权的付费全文。

### Phase KG-2：轻量抽取和召回

- [DONE] KG2.1 标题/摘要级实体识别
- [DONE] KG2.2 股票代码/公司名/简称匹配
- [DONE] KG2.3 行业和主题匹配
- [DONE] KG2.4 事件分类：订单、业绩、监管、减持、诉讼、处罚、政策
- [DONE] KG2.5 relevance score

验收：

- 全量新闻不依赖 LLM 即可入库。
- 每日推荐股、盲点股、涨跌幅榜可召回相关新闻。

### Phase KG-3：Graphify-style 图谱抽取

- [DONE] KG3.1 新增 semantic extraction allowlist
  - 只处理：
    - 推荐股。
    - 盲点股。
    - 涨跌幅榜 top N。
    - 高影响事件。
    - 用户手动选择股票。

- [DONE] KG3.2 新增图谱抽取 contract
  - 输出：
    - nodes。
    - edges。
    - hyperedges。
    - confidence。
    - confidence_score。
    - evidence_text。

- [DONE] KG3.3 写入 graph_nodes/graph_edges
- [DONE] KG3.4 图谱社区发现
- [DONE] KG3.5 导出 graphify-compatible JSON

验收：

- 单只股票可以看到相关新闻/公告构成的知识邻域。
- 每条边可追溯到原文。
- INFERRED/AMBIGUOUS 不直接生成策略惩罚。

### Phase KG-4：复盘接入

- [DONE] KG4.1 单股复盘接图谱邻域
- [DONE] KG4.2 盲点复盘接相关新闻和公告证据
- [DONE] KG4.3 策略整体复盘增加新闻/公告 edge
- [DONE] KG4.4 LLM review packet 增加 graph context
- [DONE] KG4.5 optimization_signals 关联 graph edge ids

验收：

- 复盘能说明“哪条新闻/公告/图谱关系支持或反驳了早盘判断”。
- 散户能看懂原因，不需要理解内部表结构。

### Phase KG-5：前端图谱和知识库界面

- [DONE] KG5.1 单股页面增加“知识图谱邻域”
- [DONE] KG5.2 证据时间线增加新闻/公告来源卡片
- [DONE] KG5.3 增加“相似历史案例”
- [DONE] KG5.4 增加图谱社区视图
- [DONE] KG5.5 增加 source health 和抓取日志

验收：

- 用户可以从一只股票进入：
  - 相关新闻。
  - 相关公告。
  - 相关行业。
  - 相关风险。
  - 历史相似复盘。

## 九、推荐下一阶段执行顺序

### Sprint 1：先修前端交互和接口一致性

- [DONE] 修复 rollback 参数。
- [DONE] Dry-run 结果前端展示。
- [DONE] 推荐点击打开单股详情。
- [DONE] 全局股票搜索。
- [DONE] 统一 API client 和错误提示。
- [DONE] FastAPI 补齐 stdlib server 独有路由。

原因：

- 这是当前用户可见风险最大的一层。
- 不修会导致“按钮看起来能用，但行为不可信”。

### Sprint 2：真实数据健康和候选详情

- [DONE] 数据与运行页所有覆盖率改成后端真实计算。
- [DONE] 候选详情接真实 hard_filters。
- [DONE] 候选池 API 独立出来。
- [DONE] 模拟盘表接真实 order/outcome。

### Sprint 3：资讯原始库 KG-1

- [DONE] 新增 raw_documents。
- [DONE] 官方公告索引。
- [DONE] 东方财富/新浪财经新闻索引。
- [DONE] 手动导入。

### Sprint 4：Graphify-style 图谱 KG-2/KG-3

- [DONE] 轻量实体和事件抽取。
- [DONE] 图谱 nodes/edges。
- [DONE] 社区发现。
- [DONE] graphify-compatible export。

### Sprint 5：复盘系统升级 KG-4

- [DONE] 单股复盘接图谱。
- [DONE] 盲点复盘接新闻/公告证据。
- [DONE] LLM review packet 增加 graph context。
- [DONE] 散户可读复盘模板。

## 十、关键原则

1. 复盘是核心，不是附属页面。
2. 先结构化证据，再 LLM 解释。
3. 新闻/公告/资讯必须入知识库，并可追溯。
4. Graphify 的核心价值是可审计图谱，不是简单可视化。
5. 全量资讯轻量处理，重点样本深度抽取。
6. `EXTRACTED/INFERRED/AMBIGUOUS` 必须贯穿图谱、复盘和策略进化。
7. 散户界面必须说人话，但底层必须保留证据链。
8. 数据缺失不能伪装成负面结论。
9. 事后事件不能惩罚早盘策略。
10. 每次策略进化必须可审计、可回滚、可对比。

## 十一、下一阶段可执行任务看板

本节用于后续逐项开发和交接。每个任务完成后必须把状态从 `[TODO]` 改为 `[DONE]`，并补充：

- 完成日期。
- 修改文件。
- 验证命令。
- 已知限制。

### Sprint 1：前端交互与 API 可信度修复

| 状态 | 编号 | 任务 | 主要文件 | 验收标准 |
| --- | --- | --- | --- | --- |
| [DONE] | S1.1 | 统一前端 API client，禁止静默吞错 | `web/src/api/client.ts`, `web/src/App.tsx` | 所有页面有 loading/error/empty/success；接口失败可见 |
| [DONE] | S1.2 | 修复 Evolution rollback 参数 | `web/src/pages/EvolutionPage.tsx`, `src/stock_select/api.py` | rollback 使用 `child_gene_id` 或 `event_id`；失败有提示 |
| [DONE] | S1.3 | 展示 Evolution dry-run preview | `web/src/pages/EvolutionPage.tsx` | dry-run 不落库但能展示 proposals/skipped/parameter diff |
| [DONE] | S1.4 | 推荐行点击进入单股详情 | `web/src/pages/DashboardPage.tsx`, `web/src/pages/ReviewPage.tsx` | 点击推荐可打开单股复盘或详情抽屉 |
| [DONE] | S1.5 | 全局股票搜索 | `web/src/components/PageHeader.tsx`, `src/stock_select/api.py` | 支持代码/名称模糊搜索并跳转 |
| [DONE] | S1.6 | FastAPI 补齐 stdlib server 独有路由 | `src/stock_select/api.py`, `src/stock_select/server.py` | 前端只连 FastAPI 时所有页面可用 |
| [DONE] | S1.7 | 危险操作确认弹窗 | `web/src/components/ConfirmActionDialog.tsx`, `web/src/pages/EvolutionPage.tsx` | propose/promote/rollback/rerun 都显示影响范围 |

完成日期：2026-04-26
验证命令：`cd web && npm run build` + `.venv/bin/python -m pytest -q` (238 passed, 1 skipped)

### Sprint 2：真实候选详情与数据健康

| 状态 | 编号 | 任务 | 主要文件 | 验收标准 |
| --- | --- | --- | --- | --- |
| [DONE] | S2.1 | 独立候选池 API | `src/stock_select/api.py`, `src/stock_select/strategy_engine.py` | `GET /api/candidates` 支持分页、排序、过滤 |
| [DONE] | S2.2 | 候选 hard_filters 入库和展示 | `candidate_scores.packet_json`, `web/src/pages/CandidateResearchPage.tsx` | 不再前端写死 OK |
| [DONE] | S2.3 | 数据健康统一 API | `src/stock_select/api.py` | `GET /api/system/status?date=` 返回行情/因子/证据/LLM/pipeline |
| [DONE] | S2.4 | 数据与运行页去掉静态覆盖率 | `web/src/pages/DataMemoryPage.tsx` | 覆盖率全部来自后端 |
| [DONE] | S2.5 | 修复相似案例 SQL | `src/stock_select/similar_cases.py` | 使用 `trading_days.market_environment`；新增测试 |
| [DONE] | S2.6 | 模拟盘成交约束第一版 | `src/stock_select/simulator.py` | 涨停/停牌/无开盘价不可成交；有手续费/滑点配置 |

### Sprint 3：资讯原始库 MVP

| 状态 | 编号 | 任务 | 主要文件 | 验收标准 |
| --- | --- | --- | --- | --- |
| [DONE] | S3.1 | 新增资讯库 schema | `src/stock_select/db.py` | `raw_documents`, `document_chunks`, `document_stock_links`, `document_fetch_logs` 可重复 init |
| [DONE] | S3.2 | 新增资讯 provider contract | `src/stock_select/news_providers.py` | 所有来源输出统一 `RawDocumentItem` |
| [DONE] | S3.3 | 接官方公告索引 | `src/stock_select/announcement_providers.py` | 巨潮/上交所/深交所 source adapters 可用 |
| [DONE] | S3.4 | 接财经新闻索引 | `src/stock_select/announcement_providers.py` | 东方财富/新浪公开新闻 source adapters 可用 |
| [DONE] | S3.5 | 手动导入 | `src/stock_select/manual_import.py`, `src/stock_select/cli.py` | CSV/Markdown/HTML/PDF 可导入 raw_documents |
| [DONE] | S3.6 | FTS5 检索 | `src/stock_select/memory.py`, `src/stock_select/api.py` | 可按股票、日期、关键词检索资讯，API `/api/knowledge/documents` 可用 |

完成日期：2026-04-26
验证命令：`cd web && npm run build` + `.venv/bin/python -m pytest -q` (238 passed)

### Sprint 4：Graphify-style 图谱抽取

| 状态 | 编号 | 任务 | 主要文件 | 验收标准 |
| --- | --- | --- | --- | --- |
| [DONE] | S4.1 | 确定性实体链接 | `src/stock_select/entity_linker.py` | 公司名/简称/股票代码/行业可链接，输出置信度 |
| [DONE] | S4.2 | 事件标题分类 | `src/stock_select/event_extraction.py` | 订单、业绩、监管、减持、诉讼、处罚、政策、风险分类可测 |
| [DONE] | S4.3 | 扩展图谱 schema | `src/stock_select/graph.py`, `src/stock_select/graph_export.py` | 支持 NewsArticle/Announcement/Event/ReviewEvidence/OptimizationSignal |
| [DONE] | S4.4 | 图谱边置信度 | `src/stock_select/graph.py` | 每条边有 `EXTRACTED/INFERRED/AMBIGUOUS`, `confidence_score`, `evidence_text` |
| [DONE] | S4.5 | 社区发现 | `src/stock_select/graph.py` | 使用 NetworkX 生成 `graph_communities` |
| [DONE] | S4.6 | Graphify 兼容导出 | `src/stock_select/graph_export.py` | 可导出 `graphify-out/graph.json` 结构 |

完成日期：2026-04-26
验证命令：`cd web && npm run build` + `.venv/bin/python -m pytest -q` (238 passed)

### Sprint 5：复盘系统图谱化

| 状态 | 编号 | 任务 | 主要文件 | 验收标准 |
| --- | --- | --- | --- | --- |
| [DONE] | S5.1 | Review Packet 增加 graph context | `src/stock_select/review_packets.py` | 单股/策略 packet 含相关新闻、公告、图谱邻域、相似案例 |
| [DONE] | S5.2 | 单股复盘证据时间线 | `src/stock_select/review_packets.py`, `src/stock_select/api.py` | 区分盘前可见、收盘观察、事后事件 |
| [DONE] | S5.3 | 盲点复盘接新闻/公告 | `src/stock_select/blindspot_review.py` | 漏选股票能说明是否有盘前可见新闻/公告 |
| [DONE] | S5.4 | 复盘错误关联图谱边 | `src/stock_select/blindspot_review.py` | review_errors 可追溯到 evidence/edge/document |
| [DONE] | S5.5 | optimization_signals 关联证据 | `src/stock_select/optimization_signals.py` | signal 包含 evidence_ids/edge_ids/document_ids |
| [DONE] | S5.6 | 散户可读复盘摘要 | `src/stock_select/review_summary.py`, `src/stock_select/api.py` | 每条复盘有结论、证据、是否该怪策略、下一步 |

完成日期：2026-04-26
验证命令：`cd web && npm run build` + `.venv/bin/python -m pytest -q` (238 passed)

### Sprint 6：LLM 解释增强和成本控制

| 状态 | 编号 | 任务 | 主要文件 | 验收标准 |
| --- | --- | --- | --- | --- |
| [DONE] | S6.1 | LLM allowlist | `src/stock_select/llm_review.py` | 只处理推荐股、盲点股、异常样本、高影响事件 |
| [DONE] | S6.2 | LLM claim 校验 | `src/stock_select/review_schema.py` | `EXTRACTED` claim 必须引用 evidence/document/edge |
| [DONE] | S6.3 | token 成本日志 | `src/stock_select/agent_runtime.py` | 每次调用记录 model/tokens/cost/purpose |
| [DONE] | S6.4 | LLM 失败降级 | `src/stock_select/llm_review.py` | 无 key 或失败不影响确定性复盘 |
| [DONE] | S6.5 | LLM 建议隔离 | `src/stock_select/optimization_signals.py` | LLM 建议默认 `candidate`，不直接被 evolution 消费 |

## 十二、Graphify 技术适配细节

### 本地 Graphify 能力边界

本机 Graphify skill 描述的是一个通用知识图谱工作流：

- 输入：代码、文档、网页、PDF、图片。
- 输出：`graphify-out/graph.json`、交互式 HTML、`GRAPH_REPORT.md`、可选 GraphML/Neo4j。
- 核心机制：结构化抽取、语义抽取、缓存、社区发现、审计报告。
- 关键审计标签：`EXTRACTED`、`INFERRED`、`AMBIGUOUS`。

对本项目的判断：

- Graphify 的图谱思想和审计标签非常适合复盘系统。
- Graphify 当前更像离线工作流和 skill，不应直接替代我们的日常数据 pipeline。
- 日常系统应实现自己的“财经 source adapter + 结构化表 + 图谱表 + Review Packet”。
- Graphify 可作为离线导出、周末深度分析、图谱 HTML 报告生成工具。

### 推荐目录结构

```text
var/
  knowledge/
    raw/
      2026-04-26/
        cninfo/
        sse/
        szse/
        eastmoney/
        sina/
        manual/
    normalized/
    graphify/
      2026-04-26/
        raw/
        graphify-out/
```

### Source Adapter 统一契约

```python
@dataclass(frozen=True)
class RawDocumentItem:
    source: str
    source_type: str
    source_url: str
    title: str
    summary: str | None
    content_text: str | None
    published_at: date | datetime | None
    captured_at: datetime
    related_stock_codes: list[str]
    related_industries: list[str]
    author: str | None
    license_status: str
    visibility: str
    raw_path: str | None
```

所有 crawler/provider 必须遵守：

- 不向上层暴露网站原始中文字段名。
- 每条记录必须有 `source`、`source_url`、`captured_at`、`content_hash`。
- 无法确定发布时间时，不能提前作为盘前可见证据。
- 付费/登录/版权受限内容只保存 metadata、摘要或用户授权导入结果。

### 图谱抽取分层

1. 全量轻量抽取
   - 标题、摘要、股票代码、公司名、行业、关键词事件分类。
   - 不用 LLM。
   - 每天可全量跑。

2. 重点深度抽取
   - 推荐股。
   - 盲点股。
   - 涨跌幅榜 top N。
   - 用户手动关注股票。
   - 高影响公告和风险事件。
   - 可用 LLM 或 Graphify-style semantic extraction。

3. 周末离线图谱重建
   - 导出 selected raw documents 到 Graphify raw folder。
   - 生成 HTML 和审计报告。
   - 导入 graphify-compatible graph JSON。

## 十三、复盘系统最终产品形态

复盘页面必须同时满足两类用户：

- 系统开发者：看数据、证据、错误类型、信号、图谱边、可回滚进化。
- 普通散户：看得懂为什么选、为什么错、以后怎么改。

### 单股复盘最终交互

页面结构：

1. 顶部结论区
   - 股票、日期、推荐 gene、收益结果。
   - 一句话结论。
   - 是否该惩罚策略：`是 / 否 / 不确定`。

2. 盘前假设区
   - 技术面假设。
   - 基本面假设。
   - 行业/主题假设。
   - 新闻/公告假设。
   - 风险假设。

3. 证据时间线
   - 盘前可见。
   - 盘中/收盘观察。
   - 盘后/事后事件。
   - 每条证据显示 source、发布时间、可见时间、原文链接、置信度。

4. 知识图谱邻域
   - 当前股票为中心。
   - 一跳：公司、行业、公告、新闻、风险、财报、订单、策略决策。
   - 二跳：同行业联动股、相似事件、历史案例。

5. 错误归因
   - `missed_visible_event`
   - `overweighted_technical`
   - `ignored_risk`
   - `data_missing`
   - `late_signal`
   - `execution_constraint`

6. 优化信号
   - 信号内容。
   - 支持证据。
   - 样本数。
   - 是否可被 evolution 消费。

### 策略整体复盘最终交互

页面结构：

1. 组合表现。
2. 推荐分布。
3. 五维因子 edge。
4. 新闻/公告 edge。
5. 盲点股票。
6. 错误类型排名。
7. 图谱社区命中。
8. 可执行优化建议。
9. Challenger 对比入口。

### 散户解释输出规范

每个复盘结论必须避免只输出工程字段。建议固定输出：

```text
今天发生了什么：
……

早盘为什么会选它：
……

哪些证据支持这个判断：
……

哪些证据反驳这个判断：
……

这次错在哪里：
……

这次应该怎么改：
……
```

## 十四、合规、成本和准确性风险

### 合规风险

- 同花顺、指南针、九方智投可能存在登录、付费、版权和反爬限制。
- 不应默认批量抓取付费内容或绕过访问限制。
- 系统应支持：
  - 官方公开源。
  - 授权 API。
  - 用户手动导入。
  - 只保存摘要和结构化事实。

### Token 成本风险

控制策略：

- 全量资讯只做规则抽取。
- LLM 只看 Review Packet，不看全市场。
- 每天设置 token budget。
- 每篇文档通过 content_hash 缓存抽取结果。
- 只对高相关文档深度抽取。

### 准确性风险

控制策略：

- 图谱边必须有 evidence。
- `INFERRED` 和 `AMBIGUOUS` 不能直接惩罚策略。
- 市场传闻类信息必须降权。
- 复盘区分“盘前可见”和“事后发生”。
- 数据缺失优先生成补数据任务，不急着改策略。

## 十五、最小验收闭环

下一阶段真正完成的最小定义：

```text
抓取/导入 1 天官方公告 + 财经新闻
-> raw_documents 入库
-> 自动链接到股票
-> 生成轻量事件
-> 写入 graph_nodes/graph_edges
-> 单股复盘能展示证据时间线和图谱邻域
-> 策略整体复盘能统计新闻/公告 edge
-> optimization_signals 能引用 document_id/edge_id
```

验收命令建议：

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m compileall -q src
cd web && npm run build

.venv/bin/python -m stock_select.cli --mode live run-phase sync_news --date 2024-04-22
.venv/bin/python -m stock_select.cli --mode live run-phase extract_knowledge --date 2024-04-22
.venv/bin/python -m stock_select.cli --mode live run-phase write_graph --date 2024-04-22
.venv/bin/python -m stock_select.cli --mode live run-phase deterministic_review --date 2024-04-22
```

API 验收：

- `GET /api/knowledge/documents?date=2024-04-22&stock_code=`
- `GET /api/knowledge/graph?stock_code=&date=2024-04-22`
- `GET /api/reviews/stocks/{stock_code}?date=2024-04-22`
- `GET /api/reviews/preopen-strategies/{gene_id}?date=2024-04-22`

前端验收：

- 单股复盘能看到新闻/公告证据时间线。
- 能从证据卡片打开来源链接。
- 能看到知识图谱邻域。
- 能区分盘前可见和事后事件。
- 能看到该复盘生成了哪些优化信号。
