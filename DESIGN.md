# 自我进化选股系统 - 设计文档

## 项目概述

构建一个能够自我进化的选股网站（个人工具），核心工作流：

- **8:00 AM**: 自动同步行情、新闻、财务和行业数据；先对全市场做低成本多维扫描，再收敛到候选池做深度分析
- **9:30 AM前**: 从长线和短线维度分别推荐可当日入手的股票，给出推荐理由和卖出时机
- **3:00 PM后**: 下载行情数据入库，对比早盘选股理由看盈亏，搜索市场情绪/新闻分析涨跌原因，总结入库
- **长期目标**: 经过大量选股实践后，自我进化出一套选股方法

## 核心设计理念

### 多维度分析

不只从技术面，还要从基本面、消息面、市场情绪等多个维度分析，需要用到多Agent技术。

技术面只作为低成本扫描和候选收敛的一部分，不能成为唯一选股依据。正式候选评分必须至少包含：

- 技术结构：动量、成交量、趋势、波动率
- 基本面质量：ROE、营收/利润增长、现金流质量、估值分位、资产负债风险
- 新闻/事件催化：政策、公告、行业新闻、公司事件、负面风险
- 行业/主题强度：板块相对强度、主题热度、催化数量、板块内排名
- 风险惩罚：流动性、波动、负面事件、财务质量缺失或恶化

核心原则：**代码负责广度，因子负责排序，主题负责收敛，LLM负责反证和解释，复盘负责优化策略。**

### 复盘驱动的策略优化（自我进化的核心）

系统不追求随机生成大量策略后淘汰，而是保留少数稳定策略家族，通过每日复盘持续修正参数、阈值和权重：

- **激进基因**: 动量+题材驱动，短线为主
- **保守基因**: 价值+股息驱动，长线为主
- **均衡基因**: 多因子综合，长短结合

每次正式优化必须满足：

- 基于复盘证据：收益、回撤、盲点、遗漏信号、候选分解和解释质量
- 新策略版本以 `observing` 状态生成，不直接替代原策略
- 原策略作为 Champion，新版本作为 Challenger，同期模拟盘并行运行
- 进化事件记录参数前后差异、复盘依据、触发原因和状态
- 支持显式 promotion，也支持 rollback；回滚后 Challenger 退出运行池

### 市场环境分类

不把不同市场环境下学到的经验混在一起。按以下维度分类：

- 趋势类型：牛市/熊市/震荡市
- 波动率级别：高/中/低
- 成交量级别：放量/缩量/正常

每个环境维护独立的经验权重，避免"牛市经验用在熊市"。

### 盲点扫描

每天反向扫描市场涨幅榜，找出系统遗漏的股票，分析为什么错过。

### 模拟盘

每个策略基因独立维护模拟盘：
- 开盘买入（按策略推荐的股票和仓位）
- 按策略规则卖出
- 每日计算盈亏和胜率
- 展示每个策略的进化情况

## 记忆架构：三层模型

### 第一层：基因演化引擎
- 内存读取策略参数和权重
- 决定今天买什么
- 策略自身计数器（正确/错误/部分正确）

### 第二层：FTS5 全文记忆（SQLite + FTS5）
- 每日深度日志、复盘报告、新闻摘要
- BM25 词汇检索召回相关历史经验
- 冻结快照模式：会话开始读，中间写只落盘

### 第三层：知识图谱（NetworkX 有向图 + 时间标注）
- 节点：市场环境、选股决策、实际结果、新闻事件
- 边：置信度标注（EXTRACTED/INFERRED/AMBIGUOUS）
- 社区检测：发现隐藏的选股模式
- 时间查询：支持"通胀上升+科技股 最近5次表现如何?"

## 每日运营流程

```
8:00 AM ─────────────────────────────────────────────
  新闻爬取 → 多智能体分析（4个分析师+多空辩论）
     │
     ├─ 查询图谱层：过去类似行情下各基因表现
     ├─ 查询FTS5层：BM25召回相关历史日志
     ▼
  各基因独立选股 → 输出推荐 + 理由 + 卖出条件

9:30 AM ─────────────────────────────────────────────
  模拟盘开盘买入（记录买入价、理由、基因ID）

3:00 PM ─────────────────────────────────────────────
  收盘 → 下载行情数据入库
  模拟盘按策略卖出 → 计算当日盈亏

3:30 PM ─────────────────────────────────────────────
  【深度复盘阶段】每个基因启动子智能体并行复盘:
    - 复盘Agent 1: 对比选股理由 vs 实际走势，找判断偏差
    - 复盘Agent 2: 搜索新闻/情绪，分析涨跌原因
    - 复盘Agent 3: 对比其他基因，找自己的盲区
  所有复盘结果:
    1. 写入FTS5（深度日志，BM25可检索）
    2. 结构化边写入知识图谱（置信度标注）
    3. 更新基因内部计数器

每周六 ─────────────────────────────────────────────
  策略优化：读取复盘信号 → 生成 Challenger 提案 → Champion/Challenger 并行观察
  进化简报生成 → 推送到前端
```

## 多智能体分析架构

借鉴 TradingAgents 框架：

```
Analyst Team（4个分析师并行）:
  ├─ 市场/技术分析师：K线形态、均线、MACD、RSI、成交量
  ├─ 社交媒体/情绪分析师：舆论情绪、散户关注度
  ├─ 新闻/宏观分析师：政策、行业动态、宏观经济
  └─ 基本面分析师：PE、PB、ROE、营收增长、现金流

Bull-Bear Debate（多空辩论）:
  基于分析师报告，多方和空方进行辩论

Risk Manager（风险评估）:
  评估每笔交易的风险水平

Portfolio Manager（组合管理）:
  最终决策：BUY / OVERWEIGHT / HOLD / UNDERWEIGHT / SELL
```

## Dexter 与 Harness 研究后的设计修订

### Dexter 可迁移机制

Dexter 是一个自主金融研究 Agent，核心价值不在具体美股数据源，而在“研究运行时”的工程化：

- **Scratchpad 作为单次研究的事实账本**：每次查询创建 JSONL 日志，记录 init、thinking、tool_result。选股系统应把每天 8:00 的预盘分析、3:30 的复盘分析、每周六的进化分析都记录成独立 `ResearchRun`，原始数据、工具参数、LLM 摘要都可追溯。
- **工具调用事件流**：工具执行产生 `tool_start`、`tool_progress`、`tool_end`、`tool_error` 事件。前端不只展示最终推荐，还要展示“正在抓取行情/正在分析新闻/正在复盘原因”的过程状态。
- **只让读工具并发，写工具串行**：行情、新闻、财务数据、记忆检索可以并发；写入数据库、更新基因、写知识图谱必须串行并可回滚。
- **Meta-tool 模式**：Dexter 用 `get_financials`、`get_market_data` 接收完整自然语言请求，再内部路由到具体子工具。本项目也应提供 `a_share_market_data`、`a_share_fundamentals`、`market_news`、`memory_search` 等高层工具，避免主 Agent 直接面对几十个细碎接口。
- **工具使用限额与重复查询检测**：对每个 Agent run 限制同类工具调用次数，检测相似查询，防止新闻搜索或行情接口重试循环。
- **上下文治理**：短期保留最新工具结果；旧工具结果先 micro-compact，再在接近上下文上限时生成结构化摘要；摘要写入每日记忆，原始日志不删除。
- **技能系统**：把复杂稳定流程沉淀成 `SKILL.md` 式工作流，例如“短线题材筛选”“长线估值”“涨停盲点扫描”“收盘归因复盘”，由 Agent 在合适任务中调用。
- **Cron 隔离运行**：定时任务应该用隔离 session 执行，带 active hours、失败退避、重复通知抑制。8:00、9:25、15:05、15:30、周六任务都应是可查询、可手动触发、可重跑的 job。
- **评估集与 LLM-as-judge**：为选股解释、复盘归因、风险提示建立 eval case。LLM 判断只用于解释质量评分，收益、回撤、命中率必须由确定性代码计算。

不直接采用 Dexter 的部分：

- Dexter 面向美股/SEC/FinancialDatasets，本项目数据源要换成 A 股生态（AKShare、BaoStock、交易所公告、巨潮资讯、同花顺/东方财富可访问数据等）。
- Dexter 的“每次会话 fresh start”不适合本项目；这里必须有跨天、跨市场环境的长期记忆和策略基因表现。

### Anthropic Harness 可迁移原则

参考 Anthropic 官方 Engineering 文章 [Harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) 和 [Harness design for long-running application development](https://www.anthropic.com/engineering/harness-design-long-running-apps) 后，本项目要避免一上来堆复杂多 Agent，而是建立“可验证的长任务运行框架”：

- **Harness 优先于提示词堆叠**：把任务状态、数据快照、评估标准、失败重试、人工审批、记忆写入做成外部运行框架，Agent 只负责在明确边界内推理。
- **Planner / Generator / Evaluator 闭环**：预盘任务分为计划器（确定今日要看的行业、数据、历史案例）、生成器（产出候选股和理由）、评估器（检查数据完整性、风险约束、是否偷看未来数据、输出 schema 是否合格）。
- **每个阶段都有可测试契约**：Agent 输出必须是结构化对象，而不是自由文本。代码校验字段完整性、交易日一致性、价格是否来自正确时间点、仓位是否越界、是否包含卖出条件。
- **外部 QA 比 Agent 自评更重要**：收益、回撤、胜率、遗漏涨幅榜、解释命中率都由系统外部计算；Agent 的自我反思只能作为复盘素材，不能直接等同于策略变好。
- **先用脚手架，后删脚手架**：早期可以用固定规则、明确模板和审批门控让系统跑起来；当基因表现稳定后，再逐步放松模板，让 Agent 生成更灵活的策略假设。
- **完整可观察性**：长任务必须能中断、恢复、重跑，并能看到每一步的输入、输出、耗时、错误、token 成本和写入内容。

### 修订后的 Agent 编排

不采用“很多 Agent 自由聊天”的结构，改成一个 `DailyRun Orchestrator` 管理多个短生命周期 Agent：

```
Scheduler
  └─ DailyRun Orchestrator
      ├─ DataSnapshot Builder（确定性代码）
      ├─ Planner Agent（决定今日关注面）
      ├─ Analyst Agents（技术/基本面/新闻情绪/风险，并发只读）
      ├─ Pick Generator（按每个策略基因生成候选）
      ├─ Pick Evaluator（schema、风险、数据时点、重复性检查）
      ├─ SimPortfolio Executor（确定性模拟成交）
      ├─ Review Agents（收盘复盘、新闻归因、盲点扫描）
      └─ Memory/Graph Writer（串行写入）
```

Agent 之前必须先经过 `candidate_pipeline`，生成压缩候选画像：

```
全 A 股票池
  ├─ 硬过滤：ST/停牌/低流动性/上市天数/不可成交
  ├─ 技术因子粗筛
  ├─ 基本面质量补分
  ├─ 行业/主题强度补分
  ├─ 新闻/事件催化补分
  ├─ 风险惩罚
  └─ 多样性重排 → Top 候选进入 LLM 反证
```

LLM 不扫描全市场，也不直接独裁买卖；它只阅读少量 `candidate_packet`，做逻辑反证、风险审查和推荐解释。

每个 Agent run 都必须产出：

- `run_id`、`trading_date`、`phase`、`strategy_gene_id`
- 输入数据快照 hash
- 工具调用 JSONL
- 结构化输出 JSON
- 人类可读摘要
- 校验结果和错误列表

### 推荐输出契约

早盘推荐不能只写理由，必须结构化：

```json
{
  "trading_date": "YYYY-MM-DD",
  "horizon": "short|long",
  "strategy_gene_id": "gene_aggressive_v1",
  "stock_code": "000001.SZ",
  "action": "BUY|WATCH|HOLD",
  "confidence": 0.0,
  "position_pct": 0.0,
  "entry_plan": {
    "price_source": "open|vwap|limit",
    "max_slippage_pct": 0.0
  },
  "sell_rules": [
    {"type": "take_profit", "threshold_pct": 0.0},
    {"type": "stop_loss", "threshold_pct": 0.0},
    {"type": "time_exit", "days": 0}
  ],
  "thesis": {
    "technical": [],
    "fundamental": [],
    "news": [],
    "market_environment": []
  },
  "risks": [],
  "invalid_if": []
}
```

### 复盘输出契约

收盘复盘要区分事实、推理和不确定判断：

```json
{
  "decision_id": "pick_xxx",
  "outcome": {
    "entry_price": 0.0,
    "close_price": 0.0,
    "return_pct": 0.0,
    "max_drawdown_intraday_pct": 0.0,
    "hit_sell_rule": null
  },
  "reason_check": {
    "what_was_right": [],
    "what_was_wrong": [],
    "missing_signals": []
  },
  "attribution": [
    {
      "event": "新闻/板块/资金/大盘/技术",
      "confidence": "EXTRACTED|INFERRED|AMBIGUOUS",
      "evidence": []
    }
  ],
  "gene_update_signal": {
    "score_delta": 0.0,
    "should_mutate_parameters": []
  }
}
```

## 知识图谱设计

### 节点类型
- MarketDay：交易日快照（日期、环境分类、成交量级别、波动率级别）
- Stock：股票（代码、行业、市值区间）
- PickDecision：选股决策（基因ID、方向、理由摘要）
- Outcome：结果（涨/跌/平、盈亏%）
- NewsEvent：重大新闻事件（类型、关键词）
- StrategyGene：策略基因（版本号、参数快照）

### 边类型
- (StrategyGene) --[执行]--> (PickDecision)
- (PickDecision) --[基于]--> (MarketDay)
- (PickDecision) --[选中]--> (Stock)
- (PickDecision) --[产生]--> (Outcome)
- (MarketDay) --[包含]--> (NewsEvent)
- (Outcome) --[受影响]--> (NewsEvent) [INFERRED]

### 置信度标注
- EXTRACTED：确定性事实（买入价、卖出价、盈亏数字）
- INFERRED：推理结论（"可能因为降息新闻上涨"）
- AMBIGUOUS：不确定关联（"可能和板块轮动有关"）

## 技术选型

| 层面 | 技术 | 理由 |
|------|------|------|
| 后端框架 | Python + FastAPI | 数据科学生态，异步支持好 |
| 数据库 | SQLite + FTS5 | 个人工具够用，全文搜索内建 |
| 知识图谱 | NetworkX | Python原生，社区检测算法丰富 |
| 前端 | React + TypeScript | 生态成熟，可视化库丰富 |
| 定时任务 | APScheduler / Celery | Python原生调度 |
| LLM | Claude API | 多Agent分析质量最高 |
| 数据源 | BaoStock / AKShare | 免费A股数据接口 |

## MVP 实施路线

### Phase 0：数据与交易日基座

- 建 SQLite schema：交易日、股票池、日线行情、分钟行情可选、财务指标、新闻、策略基因、推荐、模拟成交、复盘日志。
- 接入 AKShare/BaoStock，先覆盖全 A 股票列表、日线 OHLCV、复权因子、指数行情、行业板块。
- 建交易日历和数据时点约束，所有预盘输入必须标记“截至何时可见”，防止未来函数。

### Phase 1：无 LLM 的可回测策略基因

- 固化 3 个初始基因：激进、保守、均衡。
- 用确定性因子先跑通每日候选、模拟买入、收盘盈亏、胜率、最大回撤。
- 前端先展示每日推荐、基因表现、持仓、历史收益曲线。

### Phase 2：Scratchpad + FTS5 记忆

- 每个每日任务生成 JSONL scratchpad。
- 收盘后把结构化复盘写入 SQLite，同时把人类可读复盘写入 FTS5。
- 实现 BM25 检索：“类似市场环境/类似题材/类似失败原因”的历史召回。

### Phase 3：LLM 复盘先上线

- 先让 LLM 做收盘归因和盲点扫描，不急着让它决定买什么。
- 原因：复盘阶段已经知道真实结果，评估更容易；可以先训练系统如何写高质量记忆。
- 建复盘 eval：事实是否引用正确、是否区分事实和推理、是否识别遗漏信号。

### Phase 4：LLM 预盘辅助选股

- Planner/Analyst/Pick Generator/Pick Evaluator 闭环上线。
- LLM 推荐必须通过确定性风险检查，失败则降级为 WATCH 或丢弃。
- 每个策略基因保留独立 prompt、参数、因子权重和表现记录。

### Phase 5：知识图谱与基因进化

- 把 MarketDay、PickDecision、Outcome、NewsEvent、StrategyGene 写成图节点和置信度边。
- 每周六按风险调整收益、命中率、解释质量、盲点惩罚生成复盘优化信号。
- 优化只先调整参数、阈值和因子权重；不直接生成完全不同的新策略。
- 每次优化生成 Challenger 版本，原 Champion 保持 active，新版本保持 observing。
- Challenger 样本充足且稳定优于 Champion 后才允许显式 promotion；表现恶化或假设失效时 rollback。

## 核心数据库草案

- `trading_days`：交易日、市场环境、指数涨跌、成交量、波动率。
- `stocks`：股票代码、名称、行业、市值区间、上市状态。
- `daily_prices`：OHLCV、复权价、涨跌停、停牌状态。
- `fundamental_metrics`：ROE、增长率、估值分位、现金流质量、资产负债风险。
- `sector_theme_signals`：行业强度、主题热度、催化数量、板块摘要。
- `event_signals`：政策、公告、新闻、负面风险等结构化事件。
- `candidate_scores`：每个策略版本对候选股的技术/基本面/事件/行业/风险分解。
- `news_items`：新闻来源、发布时间、标题、正文摘要、相关股票/行业。
- `strategy_genes`：基因版本、参数 JSON、父基因、状态、创建时间。
- `strategy_evolution_events`：每次优化、推广、回滚事件；记录参数前后快照、复盘依据、状态和时间。
- `research_runs`：run_id、阶段、输入快照 hash、状态、耗时、错误。
- `tool_events`：run_id、工具名、参数、结果摘要、原始结果路径。
- `pick_decisions`：推荐股票、基因、理由、仓位、卖出规则、置信度。
- `sim_orders`：模拟成交、价格、数量、费用、滑点。
- `outcomes`：收益、回撤、是否触发卖出规则、持有期。
- `review_logs`：复盘结论、归因、遗漏信号、基因更新建议。
- `memory_chunks` / `memory_fts`：复盘和经验的全文检索索引。
- `graph_nodes` / `graph_edges`：知识图谱持久化快照。

## 评估与风控规则

- **禁止未来函数**：预盘 Agent 只能访问当日开盘前可见数据；收盘数据只能用于复盘。
- **不自动实盘交易**：MVP 只做模拟盘和研究推荐，不接真实下单。
- **策略优先看风险调整后收益**：不能只按收益推广策略，还要看回撤、换手、胜率、盈亏比、盲点和样本数。
- **盲点惩罚**：若某基因长期漏掉同类强势股，降低其对应市场环境权重。
- **解释质量独立评分**：复盘解释不能因为当天赚钱就自动判好，必须检查证据链。
- **样本不足不进化**：基因在某市场环境下样本数不足时，只记录观察，不生成正式 Challenger。
- **进化可追溯可回滚**：任何参数变化都必须有事件记录；不能覆盖原策略参数后丢失历史。

## 参考资料

### 已研究的项目
1. **TradingAgents** (`/Users/jieson/TradingAgents/`): 多Agent LLM交易框架
   - 4个分析师 + 多空辩论 + 风险评估 + 组合管理
   - LangGraph编排，BM25记忆检索
   - 限制：记忆为内存模式，重启丢失

2. **hermes-agent** (`/Users/jieson/hermes-agent/`): 自我改进AI Agent
   - SQLite + FTS5全文搜索持久化记忆
   - 冻结快照模式
   - 插件化记忆提供者（Honcho, Mem0, Supermemory等）
   - 自主技能创建
   - Shadow Git检查点

3. **auto-coding** (`/Users/jieson/auto-coding/`): 多Agent开发平台
   - 9个Agent角色
   - 事件溯源（Event Sourcing）实时状态追踪
   - 审批门控机制

4. **graphify** (`/Users/jieson/graphify/`): 知识图谱技能
   - 两阶段提取（AST确定 + LLM语义）
   - 置信度标注边
   - Leiden社区检测
   - MCP服务器暴露图查询

5. **Dexter** (`/tmp/dexter/`): 自主金融研究Agent
   - Agent loop + 工具事件流 + JSONL scratchpad
   - Meta-tool 路由金融数据，读工具并发、写工具审批
   - SQLite/FTS5 + embedding hybrid search + 时间衰减 + MMR
   - cron 隔离任务、失败退避、通知抑制
   - LangSmith eval + LLM-as-judge

6. **Anthropic Harness 官方文章**
   - [Harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
   - [Harness design for long-running application development](https://www.anthropic.com/engineering/harness-design-long-running-apps)
   - 结论：先建设可观测、可恢复、可评估的外部运行框架，再增加 Agent 自主性

### 待研究
- wiki-llm 项目

## 当前状态

Dexter 和 Anthropic Harness 研究已完成，当前设计方向更新为：

1. 先做可回测、可复盘、可观察的单机 MVP。
2. 先让确定性代码负责数据、模拟盘、收益计算和校验。
3. LLM 先从收盘复盘和盲点扫描切入，再进入预盘推荐。
4. 多 Agent 采用 Orchestrator 管理的短生命周期 Agent，不做无约束群聊。
5. Phase 0/1 已启动：已落地 SQLite schema、初始策略基因、基于历史日线的预盘选股、模拟盘和本地 CLI demo。

复盘系统的详细工程方案见 [REVIEW_SYSTEM_DESIGN.md](./REVIEW_SYSTEM_DESIGN.md)。后续接真实数据前，应优先实现该文档里的确定性复盘、盲点复盘、策略复盘、系统复盘和 optimization_signals。
