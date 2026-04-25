# 复盘系统技术设计方案

## 1. 目标

复盘系统是自我进化 A 股选股平台的核心学习闭环。它的目标不是生成一段“今天为什么涨跌”的自然语言总结，而是把每次推荐、未推荐、模拟成交和市场结果转化成可审计、可统计、可回滚、可驱动策略优化的结构化数据。

最终要回答四个问题：

1. 早盘为什么选这只股票，输入数据在当时是否可见。
2. 收盘结果如何验证或否定早盘假设。
3. 错误来自数据缺失、因子设计、参数权重、阈值、市场环境、执行规则，还是解释偏差。
4. 哪些稳定复盘信号可以进入策略优化队列，生成 Challenger 版本并和 Champion 并行比较。

复盘系统必须服务平台宗旨：

> 通过每日推荐、模拟交易、结构化复盘和版本化策略优化，逐步形成一套适合 A 股市场环境的个人选股方法。

## 2. 非目标

- 不用 LLM 复盘全市场几千只股票。
- 不让 LLM 直接改策略参数。
- 不因为单日赚钱就判定推荐理由正确。
- 不因为单日亏钱就判定策略无效。
- 不把收盘后才出现的数据用于早盘决策回测。
- 不覆盖旧策略参数；所有策略优化必须版本化、可回滚。

## 3. 总体架构

复盘分成确定性复盘和 LLM 复盘两层。

确定性代码负责计算事实：

- 收益、回撤、止盈止损、持有期。
- 个股相对指数、行业、候选池的表现。
- 技术因子是否兑现。
- 事件、行业、基本面、风险维度的候选分数。
- 涨幅榜盲点股。
- 策略版本的样本数、胜率、盈亏比、回撤、盲点惩罚。

LLM 负责解释和反证：

- 检查早盘 thesis 是否自洽。
- 对结构化复盘包做归因解释。
- 标注哪些结论是事实、推理或不确定。
- 从新闻、行业和盲点样本中提出可能遗漏的信号。
- 输出结构化 review JSON，不直接写策略参数。

整体流程：

```text
close_sync
  -> 写入当日 daily_prices / index_prices / sector_theme_signals / event_signals
  -> simulator 计算 outcomes

deterministic_review
  -> decision_reviews
  -> factor_review_items
  -> review_errors
  -> review_evidence
  -> blindspot_reviews

llm_review
  -> 读取 review_packet
  -> 输出 llm_review_json
  -> schema 校验
  -> 写入 decision_reviews.llm_json / gene_reviews.llm_json / system_reviews.llm_json

review_consolidation
  -> 生成 gene_reviews
  -> 生成 system_reviews
  -> 生成 optimization_signals
  -> 写 FTS5 memory
  -> 写 graph nodes/edges

strategy_optimization
  -> 消费 optimization_signals
  -> 样本数和置信度达标后生成 observing Challenger
  -> Champion/Challenger 并行模拟
  -> promotion 或 rollback 都写 strategy_evolution_events
```

## 4. 复盘分层

### 4.1 decision_review

单笔推荐复盘。输入是一条 `pick_decisions`、对应 `outcomes`、`candidate_scores.packet_json`、当日行情、行业信号、新闻事件和市场环境。

它要回答：

- 推荐理由里每个维度是否被结果验证。
- 推荐是否赚钱只是结果之一，不能替代理由审计。
- 哪个因素是主要驱动，哪个因素是拖累。
- 是否存在早盘不可见的事后信号。
- 是否产生优化信号。

### 4.2 blindspot_review

盲点复盘。输入是当日涨幅榜、强势行业、强事件个股、候选池和最终推荐。

它要回答：

- 强势股是否进入候选池。
- 如果进了候选池，为什么没有被推荐。
- 如果没进候选池，是硬过滤、数据缺失、行业弱识别、事件漏召回、阈值过严，还是策略风格不覆盖。
- 盲点是否应该惩罚某个 gene，还是只记录为策略边界。

### 4.3 gene_review

策略版本复盘。按 `strategy_gene_id + period + market_environment` 聚合。

它要回答：

- 该策略当天/本周是否有正期望。
- 技术、基本面、事件、行业、风险各维度对赢家和输家的区分度。
- 盲点集中在哪些行业、事件类型或市场环境。
- 是否有足够样本生成优化信号。

### 4.4 system_review

系统级复盘。跨策略聚合。

它要回答：

- 今日全系统最明显的问题是什么。
- 是否存在数据源故障或新闻召回不足。
- 是否所有策略同时过度偏向某个维度。
- 是否需要新增数据源、因子或过滤器。

## 5. 数据时点和未来函数规则

复盘可以使用收盘后数据，但必须明确区分：

- `preopen_visible`：早盘推荐时可见的数据。
- `postclose_observed`：收盘后才知道的结果。
- `postevent_later`：推荐之后发生的新事件，只能用于解释，不能作为早盘策略本应知道的证据。

规则：

- `pick_decisions.input_snapshot_hash` 必须引用当时的候选快照。
- `candidate_scores.packet_json.sources.price_history` 必须是 `daily_prices<trading_date`。
- 复盘写 `review_evidence.visibility`，取值为 `PREOPEN_VISIBLE | POSTCLOSE_OBSERVED | POSTDECISION_EVENT`。
- `late_signal` 错误类型不惩罚早盘策略，只用于提醒“无法提前知道”。
- 策略优化只能消费 `PREOPEN_VISIBLE` 相关错误和稳定盲点，不消费纯事后新闻。

## 6. 复盘数据源设计

复盘的关键不是“用 LLM 多读几篇文章”，而是先把可接口化、可量化、可追溯的数据沉淀成结构化事实。LLM 只在结构化接口拿不到、或需要解释非结构化公告文本时介入。

### 6.1 数据源分级

| 等级 | 定位 | 示例 | 使用原则 |
| --- | --- | --- | --- |
| S0 权威原始披露 | 法定公告、交易所披露、上市公司原始文件 | 巨潮资讯网、上交所、深交所、北交所、上市公司公告 PDF | 作为最终证据源，保存 raw document 和 URL |
| S1 结构化数据接口 | 已清洗成表格的数据 | Tushare Pro、BaoStock、AKShare 封装的财务/公告/行情接口 | 优先用于批量计算和全市场扫描 |
| S2 财经聚合网站 | 研报、新闻、资金、板块、公告聚合 | 东方财富、同花顺公开数据页、雪球、财联社等 | 用作辅助来源，必须记录 source 和抓取时间 |
| S3 商业终端/投顾平台 | 付费观点、评级、策略、投顾内容 | 同花顺 iFinD、Choice、Wind、指南针、九方智投 | 仅在有合法授权/API 时接入，不做无授权强爬 |
| S4 文档抽取 | PDF、公告正文、调研纪要、互动问答 | 年报、临时公告、订单公告、投资者关系活动记录 | 只对候选股/盲点股/事件股做抽取，避免 token 爆炸 |

### 6.2 数据源矩阵

| 复盘问题 | 需要的数据 | 推荐来源 | 接口化可行性 | 入库表 |
| --- | --- | --- | --- | --- |
| 实际财报是否超预期 | 利润表、收入、净利润、EPS、扣非净利、公告日期 | Tushare `income`、`fina_indicator`；BaoStock 财务指标；巨潮/交易所公告 | 高。Tushare/BaoStock 可结构化；公告 PDF 作原始证据 | `financial_actuals`、`review_evidence` |
| 预期 20 亿、实际 40 亿这种预期差 | 卖方盈利预测、评级、目标价、预测净利润、预测 EPS | Tushare `report_rc`；东方财富研报中心；Choice/Wind/同花顺 iFinD（如有授权） | 中高。Tushare 可结构化但有权限门槛；东方财富公开页可作辅助 | `analyst_expectations` |
| 业绩预告/业绩快报是否兑现 | 预告净利润上下限、变动幅度、变动原因、快报财务数据 | Tushare `forecast`、`express`；AKShare 东方财富业绩预告/快报；BaoStock 业绩预告/快报；巨潮公告 | 高。结构化接口可拿，公告作校验 | `performance_forecasts`、`performance_express` |
| 订单是否支撑未来业绩 | 重大合同、订单金额、客户、期限、订单对应产品、是否已公告 | 巨潮/交易所临时公告；AKShare 东方财富重大合同；上市公司公告 PDF | 中。重大合同有部分结构化入口，但很多细节在公告正文，需要文档抽取 | `order_contract_events` |
| 产能/销量/价格是否改善 | 产能、产量、销量、ASP、产品价格、行业价格指数 | 年报/半年报经营数据、行业协会、国家统计局、商品价格接口、公司公告 | 中低。部分行业有结构化数据，很多要按行业单独建 connector | `business_kpi_actuals`、`industry_kpi_signals` |
| 行业景气是否变化 | 行业指数、板块涨跌、资金流、主题热度、产业新闻 | AKShare/Tushare 行业指数、东方财富/同花顺板块资金、新闻 | 中高。行情和资金较容易，主题热度需要自建规则 | `sector_theme_signals` |
| 资金是否认可 | 成交额、换手、资金流、龙虎榜、北向、融资融券 | Tushare `moneyflow`、`top_list`、`margin`；AKShare 东方财富/同花顺资金流 | 高。作为市场验证，不作为基本面事实 | `capital_flow_signals` |
| 管理层是否释放新信息 | 投资者关系活动、互动易/上证 e 互动问答、业绩说明会 | 深交所互动易、上证 e 互动、巨潮投资者关系记录、AKShare 上证 e 互动接口 | 中。问答可结构化，活动记录常需文档抽取 | `ir_events` |
| 风险是否被忽略 | 监管问询、处罚、诉讼、减持、质押、解禁、审计意见 | 上交所/深交所监管公开、巨潮公告、Tushare 质押/减持/审计意见 | 高到中。监管/质押可结构化，诉讼细节需公告抽取 | `risk_events` |
| 新闻是否只是噪音 | 新闻标题、发布时间、来源、相关股票、情绪 | 东方财富资讯、财联社、公司公告、新闻 API | 中。必须按来源评级，低质量新闻不能直接驱动优化 | `news_items`、`event_signals` |

### 6.3 接口优先级

真实数据前建议按优先级接入：

1. **行情和市场验证层**：AKShare + BaoStock 日线、指数、行业行情、涨跌停、停牌。
2. **财务实际值层**：Tushare 或 BaoStock 的利润表、资产负债表、现金流、财务指标。
3. **业绩预告/快报层**：Tushare `forecast/express`，AKShare 东方财富业绩预告/快报作补充。
4. **公告原文层**：巨潮资讯网、上交所、深交所公告检索和 PDF/HTML 原文归档。
5. **市场预期层**：Tushare `report_rc` 或其他合法授权的卖方盈利预测接口。
6. **订单/合同/经营 KPI 层**：先抓重大合同公告和经营数据公告，再对候选股做文档抽取。
7. **投关和调研层**：互动易、上证 e 互动、投资者关系活动记录。
8. **财经聚合和新闻层**：东方财富、同花顺公开页、财联社等，只作事件辅助和交叉验证。

### 6.4 “接口能不能拿到”的判断

不是所有你在 App 里看到的数据都有稳定公开接口。实现上按三类处理：

1. **稳定结构化接口**：直接批量入库。例如 Tushare 财务表、业绩预告、卖方盈利预测；BaoStock 季频财务；AKShare 行情/公告/部分东方财富和同花顺数据。
2. **公开网页但无正式 API**：用 connector 抓取或使用 AKShare 封装，标记 `source_reliability='medium'`，定期做字段变更检测。东方财富、同花顺公开数据页多属于这一类。
3. **商业授权或非公开内容**：不默认爬。指南针、九方智投、同花顺 iFinD、Choice、Wind 这类如果用户有授权/API，再实现 adapter；否则只作为人工参考来源。

### 6.5 关键结构化表

#### analyst_expectations

用于计算“市场预期 vs 实际财报”的预期差。

```sql
CREATE TABLE analyst_expectations (
  expectation_id TEXT PRIMARY KEY,
  stock_code TEXT NOT NULL REFERENCES stocks(stock_code),
  report_date TEXT NOT NULL,
  forecast_period TEXT NOT NULL,
  org_name TEXT,
  author_name TEXT,
  report_title TEXT,
  forecast_revenue REAL,
  forecast_net_profit REAL,
  forecast_eps REAL,
  forecast_pe REAL,
  rating TEXT,
  target_price_min REAL,
  target_price_max REAL,
  source TEXT NOT NULL,
  source_url TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(stock_code, report_date, forecast_period, org_name, author_name)
);
```

#### financial_actuals

用于记录财报真实值。

```sql
CREATE TABLE financial_actuals (
  stock_code TEXT NOT NULL REFERENCES stocks(stock_code),
  report_period TEXT NOT NULL,
  ann_date TEXT NOT NULL,
  revenue REAL,
  net_profit REAL,
  net_profit_deducted REAL,
  eps REAL,
  roe REAL,
  gross_margin REAL,
  operating_cashflow REAL,
  source TEXT NOT NULL,
  source_url TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(stock_code, report_period, source)
);
```

#### earnings_surprises

预期差计算结果。

```sql
CREATE TABLE earnings_surprises (
  surprise_id TEXT PRIMARY KEY,
  stock_code TEXT NOT NULL REFERENCES stocks(stock_code),
  report_period TEXT NOT NULL,
  ann_date TEXT NOT NULL,
  expected_net_profit REAL,
  actual_net_profit REAL,
  net_profit_surprise_pct REAL,
  expected_revenue REAL,
  actual_revenue REAL,
  revenue_surprise_pct REAL,
  expectation_sample_size INTEGER NOT NULL,
  expectation_source TEXT NOT NULL,
  actual_source TEXT NOT NULL,
  evidence_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(stock_code, report_period)
);
```

计算规则：

```python
net_profit_surprise_pct = (actual_net_profit - expected_net_profit) / abs(expected_net_profit)
```

如果 `expectation_sample_size < 3`，只记录观察，不作为强信号。

#### order_contract_events

用于你说的“上半年订单已经支撑去年产值”。

```sql
CREATE TABLE order_contract_events (
  event_id TEXT PRIMARY KEY,
  stock_code TEXT NOT NULL REFERENCES stocks(stock_code),
  ann_date TEXT NOT NULL,
  event_type TEXT NOT NULL,
  customer_name TEXT,
  product_name TEXT,
  contract_amount REAL,
  currency TEXT DEFAULT 'CNY',
  contract_period_start TEXT,
  contract_period_end TEXT,
  is_framework_agreement INTEGER NOT NULL DEFAULT 0,
  related_revenue_last_year REAL,
  order_to_last_year_revenue_pct REAL,
  source TEXT NOT NULL,
  source_url TEXT,
  extraction_method TEXT NOT NULL,
  confidence REAL NOT NULL,
  raw_text_hash TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

`extraction_method`：

- `STRUCTURED_API`
- `REGEX_FROM_ANNOUNCEMENT`
- `LLM_FROM_ANNOUNCEMENT`
- `MANUAL`

订单类数据必须带 `confidence`，因为框架协议、意向协议、已中标、已签约、已交付的确定性不同。

#### business_kpi_actuals

用于行业和公司经营指标，例如销量、产量、订单量、产能、价格。

```sql
CREATE TABLE business_kpi_actuals (
  kpi_id TEXT PRIMARY KEY,
  stock_code TEXT NOT NULL REFERENCES stocks(stock_code),
  period TEXT NOT NULL,
  kpi_name TEXT NOT NULL,
  kpi_value REAL NOT NULL,
  unit TEXT NOT NULL,
  yoy_pct REAL,
  qoq_pct REAL,
  source TEXT NOT NULL,
  source_url TEXT,
  extraction_method TEXT NOT NULL,
  confidence REAL NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(stock_code, period, kpi_name, source)
);
```

### 6.6 复盘如何使用这些数据

新增复盘因子：

- `earnings_expectation`：业绩实际值 vs 市场预期。
- `order_backlog`：订单、合同、中标、产能利用率对未来收入的支撑。
- `business_kpi`：销量、产量、ASP、毛利率、费用率等经营指标变化。
- `guidance_revision`：业绩预告、快报、公司指引是否上修或下修。
- `analyst_revision`：卖方预测是否集中上修或下修。

对应错误类型：

- `missed_earnings_surprise`：漏掉明显业绩超预期。
- `false_earnings_surprise`：看似超预期但市场不认可，例如一次性收益。
- `missed_order_signal`：漏掉重大订单或经营数据改善。
- `overtrusted_framework_order`：把框架协议当成确定收入。
- `missed_guidance_revision`：漏掉业绩预告/快报上修。
- `analyst_expectation_missing`：缺少市场预期基准，无法判断超预期。

### 6.7 复盘证据表展示给用户

前端复盘详情页需要给用户展示“为什么系统这么判断”的依据表：

| 类型 | 指标 | 实际值 | 预期/对比值 | 差异 | 来源 | 可见性 | 置信度 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 财报预期差 | 归母净利润 | 40 亿 | 卖方一致预期 20 亿 | +100% | Tushare report_rc + 财报 | POSTCLOSE_OBSERVED | EXTRACTED |
| 订单支撑 | 新签订单 | 10 亿 | 去年收入 10 亿 | 100% | 重大合同公告 | PREOPEN_VISIBLE | INFERRED |
| 行业景气 | 板块涨幅 | +3.5% | 沪深 300 +0.8% | +2.7pct | AKShare/Tushare | POSTCLOSE_OBSERVED | EXTRACTED |
| 风险 | 框架协议 | 10 亿 | 未承诺交付 | 不确定 | 公告原文 | PREOPEN_VISIBLE | AMBIGUOUS |

## 7. 错误类型 Taxonomy

错误类型必须稳定，方便跨天统计。

### 7.1 数据类

- `data_missing`：关键数据缺失。
- `data_stale`：数据不是最新可见数据。
- `source_conflict`：AKShare/BaoStock 或其他源差异超阈值。
- `bad_snapshot`：输入快照 hash 与实际使用数据不一致。

### 7.2 候选召回类

- `candidate_not_recalled`：强势股未进入候选池。
- `hard_filter_too_strict`：硬过滤过严。
- `threshold_too_strict`：分数阈值过严。
- `threshold_too_loose`：分数阈值过松。
- `diversity_rerank_missed`：多样性重排导致错过更优候选。

### 7.3 因子权重类

- `overweighted_technical`：技术面权重过高。
- `underweighted_technical`：技术面有效但权重不足。
- `underweighted_fundamental`：基本面保护或质量因子不足。
- `overweighted_fundamental`：基本面权重压制了短线机会。
- `underweighted_event`：事件催化权重不足。
- `false_catalyst`：事件看似利好但市场未兑现。
- `underweighted_sector`：行业/主题强度权重不足。
- `sector_rotation_missed`：板块轮动未识别。
- `sector_weak_but_stock_picked`：板块弱但个股仍被选中。
- `risk_underestimated`：风险惩罚不足。
- `risk_overestimated`：风险惩罚过强，错过有效机会。
- `liquidity_ignored`：流动性不足未充分惩罚。

### 7.4 执行和退出类

- `entry_unfillable`：开盘涨停、停牌或缺价导致无法成交。
- `entry_too_chasing`：开盘价相对信号过高。
- `position_too_large`：仓位过大。
- `position_too_small`：高质量机会仓位过小。
- `sell_rule_too_tight`：止盈/止损过紧。
- `sell_rule_too_loose`：退出规则过松。
- `time_exit_mismatch`：持有期和策略 horizon 不匹配。

### 7.5 解释类

- `thesis_not_specific`：推荐理由过泛。
- `thesis_contradicted_by_data`：推荐理由和候选数据矛盾。
- `missing_counterargument`：缺少反方证据。
- `llm_over_inferred`：LLM 推理超过证据。
- `ambiguous_attribution`：原因可能相关但证据不足。
- `late_signal`：信号发生在决策之后。

## 8. 判定枚举

### 8.1 verdict

- `RIGHT`：该维度判断被结果或证据支持。
- `WRONG`：该维度判断被结果或证据否定。
- `MIXED`：部分正确、部分错误。
- `NEUTRAL`：该维度不是本次主要依据。
- `INCONCLUSIVE`：证据不足。
- `NOT_APPLICABLE`：该策略或该股票不适用。

### 8.2 primary_driver

- `technical`
- `fundamental`
- `event`
- `sector`
- `risk`
- `execution`
- `market`
- `unknown`

### 8.3 evidence_confidence

- `EXTRACTED`：确定性事实，直接来自行情、新闻、财报、板块数据。
- `INFERRED`：基于事实的合理推断。
- `AMBIGUOUS`：可能相关但证据不足。

## 9. 数据库设计

### 9.1 decision_reviews

一条推荐对应一条单笔复盘。

```sql
CREATE TABLE decision_reviews (
  review_id TEXT PRIMARY KEY,
  decision_id TEXT NOT NULL REFERENCES pick_decisions(decision_id),
  trading_date TEXT NOT NULL,
  strategy_gene_id TEXT NOT NULL REFERENCES strategy_genes(gene_id),
  stock_code TEXT NOT NULL REFERENCES stocks(stock_code),
  verdict TEXT NOT NULL,
  primary_driver TEXT NOT NULL,
  return_pct REAL NOT NULL,
  relative_return_pct REAL NOT NULL DEFAULT 0,
  max_drawdown_intraday_pct REAL NOT NULL,
  thesis_quality_score REAL NOT NULL DEFAULT 0,
  evidence_quality_score REAL NOT NULL DEFAULT 0,
  deterministic_json TEXT NOT NULL,
  llm_json TEXT,
  summary TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(decision_id)
);
```

`deterministic_json` 保存确定性复盘包，`llm_json` 保存 LLM 通过 schema 校验后的补充归因。

### 9.2 factor_review_items

单笔复盘的五维拆解。

```sql
CREATE TABLE factor_review_items (
  item_id TEXT PRIMARY KEY,
  review_id TEXT NOT NULL REFERENCES decision_reviews(review_id),
  factor_type TEXT NOT NULL,
  expected_json TEXT NOT NULL,
  actual_json TEXT NOT NULL,
  verdict TEXT NOT NULL,
  contribution_score REAL NOT NULL DEFAULT 0,
  error_type TEXT,
  confidence TEXT NOT NULL,
  evidence_ids_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(review_id, factor_type)
);
```

`factor_type` 取值：

- `technical`
- `fundamental`
- `event`
- `sector`
- `risk`
- `execution`
- `market`

### 9.3 blindspot_reviews

涨幅榜、强势板块和漏选候选复盘。

```sql
CREATE TABLE blindspot_reviews (
  blindspot_review_id TEXT PRIMARY KEY,
  trading_date TEXT NOT NULL,
  stock_code TEXT NOT NULL REFERENCES stocks(stock_code),
  rank INTEGER NOT NULL,
  return_pct REAL NOT NULL,
  industry TEXT,
  was_candidate INTEGER NOT NULL,
  was_picked INTEGER NOT NULL,
  candidate_rank INTEGER,
  candidate_score REAL,
  missed_stage TEXT NOT NULL,
  primary_reason TEXT NOT NULL,
  affected_gene_ids_json TEXT NOT NULL,
  evidence_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(trading_date, stock_code)
);
```

`missed_stage` 取值：

- `not_in_universe`
- `hard_filter`
- `candidate_scoring`
- `diversity_rerank`
- `risk_filter`
- `max_picks_limit`
- `strategy_scope`
- `unknown`

### 9.4 gene_reviews

策略版本周期复盘。

```sql
CREATE TABLE gene_reviews (
  gene_review_id TEXT PRIMARY KEY,
  strategy_gene_id TEXT NOT NULL REFERENCES strategy_genes(gene_id),
  period_start TEXT NOT NULL,
  period_end TEXT NOT NULL,
  market_environment TEXT NOT NULL DEFAULT 'all',
  trades INTEGER NOT NULL,
  avg_return_pct REAL NOT NULL,
  win_rate REAL NOT NULL,
  worst_drawdown_pct REAL NOT NULL,
  profit_loss_ratio REAL NOT NULL,
  blindspot_count INTEGER NOT NULL,
  thesis_quality_avg REAL NOT NULL DEFAULT 0,
  factor_edges_json TEXT NOT NULL,
  top_errors_json TEXT NOT NULL,
  deterministic_json TEXT NOT NULL,
  llm_json TEXT,
  summary TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(strategy_gene_id, period_start, period_end, market_environment)
);
```

`factor_edges_json` 示例：

```json
{
  "technical": {"winner_avg": 0.18, "loser_avg": 0.05, "edge": 0.13},
  "fundamental": {"winner_avg": 0.64, "loser_avg": 0.42, "edge": 0.22},
  "event": {"winner_avg": 0.31, "loser_avg": -0.12, "edge": 0.43},
  "sector": {"winner_avg": 0.58, "loser_avg": 0.25, "edge": 0.33},
  "risk": {"winner_avg": 0.08, "loser_avg": 0.32, "edge": -0.24}
}
```

### 9.5 system_reviews

系统级复盘。

```sql
CREATE TABLE system_reviews (
  system_review_id TEXT PRIMARY KEY,
  trading_date TEXT NOT NULL,
  market_environment TEXT NOT NULL DEFAULT 'unknown',
  total_picks INTEGER NOT NULL,
  total_blindspots INTEGER NOT NULL,
  avg_return_pct REAL NOT NULL,
  top_system_errors_json TEXT NOT NULL,
  data_quality_json TEXT NOT NULL,
  observation_json TEXT NOT NULL,
  llm_json TEXT,
  summary TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(trading_date)
);
```

### 9.6 optimization_signals

复盘产出的策略优化信号。进化模块只消费这个表，不直接根据自然语言或单日收益改参数。

```sql
CREATE TABLE optimization_signals (
  signal_id TEXT PRIMARY KEY,
  source_type TEXT NOT NULL,
  source_id TEXT NOT NULL,
  target_gene_id TEXT REFERENCES strategy_genes(gene_id),
  scope TEXT NOT NULL,
  scope_key TEXT,
  signal_type TEXT NOT NULL,
  param_name TEXT,
  direction TEXT NOT NULL,
  strength REAL NOT NULL,
  confidence REAL NOT NULL,
  sample_size INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'open',
  reason TEXT NOT NULL,
  evidence_ids_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  consumed_at TEXT
);
```

`source_type`：

- `decision_review`
- `blindspot_review`
- `gene_review`
- `system_review`

`scope`：

- `global`
- `market_environment`
- `industry`
- `horizon`
- `gene`

`signal_type`：

- `increase_weight`
- `decrease_weight`
- `raise_threshold`
- `lower_threshold`
- `add_filter`
- `relax_filter`
- `adjust_position`
- `adjust_sell_rule`
- `add_data_source`
- `observe_only`

`direction`：

- `up`
- `down`
- `add`
- `remove`
- `hold`

### 9.7 review_evidence

统一证据表。

```sql
CREATE TABLE review_evidence (
  evidence_id TEXT PRIMARY KEY,
  review_id TEXT,
  source_type TEXT NOT NULL,
  source_id TEXT,
  trading_date TEXT NOT NULL,
  stock_code TEXT,
  visibility TEXT NOT NULL,
  confidence TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

`source_type`：

- `daily_price`
- `index_price`
- `sector_signal`
- `candidate_score`
- `fundamental_metric`
- `event_signal`
- `news_item`
- `blindspot_report`
- `sim_order`
- `outcome`

### 9.8 review_errors

标准错误类型计数。

```sql
CREATE TABLE review_errors (
  error_id TEXT PRIMARY KEY,
  review_scope TEXT NOT NULL,
  review_id TEXT NOT NULL,
  error_type TEXT NOT NULL,
  severity REAL NOT NULL,
  confidence REAL NOT NULL,
  evidence_ids_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(review_scope, review_id, error_type)
);
```

`review_scope`：

- `decision`
- `blindspot`
- `gene`
- `system`

## 10. JSON Contracts

### 10.1 DecisionReviewContract

```json
{
  "review_id": "review_pick_xxx",
  "decision_id": "pick_xxx",
  "trading_date": "YYYY-MM-DD",
  "strategy_gene_id": "gene_x",
  "stock_code": "000001.SZ",
  "verdict": "RIGHT|WRONG|MIXED|NEUTRAL|INCONCLUSIVE",
  "primary_driver": "technical|fundamental|event|sector|risk|execution|market|unknown",
  "outcome": {
    "entry_price": 0.0,
    "close_price": 0.0,
    "return_pct": 0.0,
    "relative_return_pct": 0.0,
    "max_drawdown_intraday_pct": 0.0,
    "hit_sell_rule": null
  },
  "factor_checks": [
    {
      "factor_type": "technical",
      "expected": {},
      "actual": {},
      "verdict": "RIGHT",
      "contribution_score": 0.0,
      "error_type": null,
      "confidence": "EXTRACTED",
      "evidence_ids": []
    }
  ],
  "errors": [
    {
      "error_type": "underweighted_event",
      "severity": 0.4,
      "confidence": 0.7,
      "evidence_ids": []
    }
  ],
  "optimization_signals": [
    {
      "signal_type": "increase_weight",
      "param_name": "event_component_weight",
      "direction": "up",
      "strength": 0.08,
      "confidence": 0.65,
      "reason": "event score separated winners in this review",
      "evidence_ids": []
    }
  ],
  "summary": "..."
}
```

### 10.2 BlindspotReviewContract

```json
{
  "blindspot_review_id": "blind_review_xxx",
  "trading_date": "YYYY-MM-DD",
  "stock_code": "000001.SZ",
  "rank": 1,
  "return_pct": 0.0,
  "industry": "Battery",
  "was_candidate": true,
  "was_picked": false,
  "candidate_rank": 9,
  "candidate_score": 0.41,
  "missed_stage": "max_picks_limit",
  "primary_reason": "candidate scored well but was below max_picks cutoff",
  "affected_gene_ids": ["gene_balanced_v1"],
  "errors": [],
  "optimization_signals": [],
  "evidence_ids": []
}
```

### 10.3 GeneReviewContract

```json
{
  "gene_review_id": "gene_review_xxx",
  "strategy_gene_id": "gene_balanced_v1",
  "period_start": "YYYY-MM-DD",
  "period_end": "YYYY-MM-DD",
  "market_environment": "all",
  "metrics": {
    "trades": 20,
    "avg_return_pct": 0.012,
    "win_rate": 0.55,
    "worst_drawdown_pct": -0.06,
    "profit_loss_ratio": 1.35,
    "blindspot_count": 3,
    "thesis_quality_avg": 0.72
  },
  "factor_edges": {},
  "top_errors": [],
  "optimization_signals": [],
  "summary": "..."
}
```

### 10.4 LLMReviewContract

LLM 输出必须被 Pydantic 或 stdlib validator 校验。失败只记录 error，不更新优化信号。

```json
{
  "review_target": {
    "type": "decision|blindspot|gene|system",
    "id": "..."
  },
  "attribution": [
    {
      "claim": "...",
      "confidence": "EXTRACTED|INFERRED|AMBIGUOUS",
      "evidence_ids": [],
      "counter_evidence_ids": []
    }
  ],
  "reason_check": {
    "what_was_right": [],
    "what_was_wrong": [],
    "missing_signals": [],
    "not_knowable_preopen": []
  },
  "suggested_errors": [
    {
      "error_type": "false_catalyst",
      "severity": 0.4,
      "confidence": 0.6,
      "evidence_ids": []
    }
  ],
  "suggested_optimization_signals": [
    {
      "signal_type": "observe_only",
      "param_name": null,
      "direction": "hold",
      "strength": 0.0,
      "confidence": 0.5,
      "reason": "single sample only"
    }
  ],
  "summary": "..."
}
```

## 11. 确定性复盘算法

### 11.1 单笔推荐复盘

函数：

```python
review_decision(conn, decision_id: str) -> DecisionReview
```

步骤：

1. 读取 `pick_decisions`、`outcomes`、`candidate_scores`、`stocks`。
2. 解析 `thesis_json`、`risks_json`、`sell_rules_json`、`packet_json`。
3. 读取当日 `daily_prices`，并读取指数/行业表现。如果指数行情 MVP 暂无，则 `relative_return_pct = return_pct`。
4. 生成 evidence：
   - outcome evidence
   - daily_price evidence
   - candidate_score evidence
   - sector_signal evidence
   - event_signal evidence
   - fundamental_metric evidence
5. 对每个 factor 生成 `factor_review_items`。
6. 汇总 verdict 和 primary_driver。
7. 生成 `review_errors`。
8. 根据错误和贡献生成低层级 `optimization_signals`，默认 `status='open'`。
9. 写入 `decision_reviews`，upsert 保持幂等。

### 11.2 technical factor check

输入：

- preopen technical score
- momentum
- volume_surge
- volatility
- trend_state
- outcome return
- intraday drawdown

规则 MVP：

- 如果 `technical_score > 0` 且 `return_pct > 0`，verdict = `RIGHT`。
- 如果 `technical_score > 0` 且 `return_pct <= 0`，verdict = `WRONG`。
- 如果 `technical_score <= 0` 但仍被选中，且亏损，错误可能为 `threshold_too_loose`。
- 如果 `trend_state='breakout'` 但收盘低于开盘，错误可能为 `overweighted_technical` 或 `false_breakout`。如果不想新增错误类型，先归入 `overweighted_technical`。

贡献分：

```python
contribution_score = sign(return_pct) * abs(technical_score)
```

### 11.3 fundamental factor check

基本面不应该用单日涨跌简单判对错。它主要用于质量保护和风险过滤。

规则 MVP：

- 高 fundamental score 且回撤小：`RIGHT`。
- 高 fundamental score 但大幅亏损：`MIXED`，检查是否事件或市场风险主导。
- 低 fundamental score 仍被买入并亏损：错误 `underweighted_fundamental` 或 `threshold_too_loose`。
- 财务风险高但风险惩罚低：错误 `risk_underestimated`。

### 11.4 event factor check

规则 MVP：

- 正 event score 且上涨：`RIGHT`。
- 正 event score 但下跌：`WRONG`，错误 `false_catalyst`。
- 盲点股有强事件但候选 score 中 event 缺失：`missed_catalyst` 或 `underweighted_event`。
- 推荐后才发生的事件标记 `late_signal`，不进入策略惩罚。

### 11.5 sector factor check

规则 MVP：

- 个股上涨且行业强：`RIGHT`。
- 个股下跌但行业强：`MIXED`，可能是个股风险。
- 个股上涨但行业弱：`MIXED`，说明行业因子不是主驱动。
- 行业强势股大面积未进入推荐：`sector_rotation_missed` 或 `underweighted_sector`。

### 11.6 risk factor check

规则 MVP：

- 高风险票亏损或大回撤：`RIGHT`，如果仍被买入则 `risk_underestimated`。
- 低风险票大回撤：`WRONG`，检查是否存在漏掉的事件或流动性风险。
- 高风险票上涨但被过滤：不一定是错误，先标记 `risk_overestimated` 观察，样本不足不优化。

### 11.7 execution check

规则 MVP：

- `is_suspended=1`：`entry_unfillable`。
- `is_limit_up=1` 且 entry_plan 要开盘买入：`entry_unfillable`。
- hit stop loss 后又收涨：可能 `sell_rule_too_tight`。
- hit take profit 后继续大涨：可能 `sell_rule_too_tight`，但只作为观察。
- 未触发退出且回撤超过策略承受：`sell_rule_too_loose`。

## 12. 盲点复盘算法

函数：

```python
review_blindspots(conn, trading_date: str, top_n: int = 30) -> list[BlindspotReview]
```

候选来源：

- 当日涨幅榜 top_n。
- 强势行业内涨幅 top N。
- 有高强度事件但未推荐的股票。
- 当日涨停但未推荐的股票。

步骤：

1. 读取当日股票收益并排序。
2. 对每只盲点股检查：
   - 是否在 `stocks` active universe。
   - 是否被硬过滤。
   - 是否存在 `candidate_scores`。
   - 在每个 gene 下候选排名是多少。
   - 是否被 `max_picks` 截断。
   - 是否因风险惩罚过高。
   - 是否因行业多样性重排被挤出。
3. 写 `blindspot_reviews`。
4. 生成 `review_errors`。
5. 生成 `optimization_signals`，但默认需要聚合后才消费。

盲点判断不是“涨了没买就是错”。以下情况不惩罚：

- 策略 horizon 不匹配。
- 开盘涨停无法成交。
- 预盘不可见的事件导致上涨。
- 该股票不在策略定义范围内。
- 风险过高且策略明确保守。

## 13. 策略复盘算法

函数：

```python
review_gene(conn, gene_id: str, period_start: str, period_end: str, market_environment: str = "all") -> GeneReview
```

步骤：

1. 聚合该 gene 的 `decision_reviews` 和 `outcomes`。
2. 计算基础表现：
   - trades
   - avg_return_pct
   - win_rate
   - worst_drawdown_pct
   - profit_loss_ratio
   - blindspot_count
3. 计算 factor edge：
   - winner_avg
   - loser_avg
   - edge = winner_avg - loser_avg
4. 统计 top_errors。
5. 生成 gene-level optimization signals。
6. 写 `gene_reviews`。

优化信号生成规则 MVP：

- `underweighted_event` 连续出现且盲点收益高：增加 `event_component_weight`。
- `false_catalyst` 连续出现：降低 `event_component_weight` 或提高 event 置信阈值。
- `sector_rotation_missed` 连续出现：增加 `sector_component_weight`。
- `risk_underestimated` 连续出现且亏损集中：增加 `risk_component_weight` 或降低 `position_pct`。
- `threshold_too_loose` 多且亏损：提高 `min_score`。
- `threshold_too_strict` 多且盲点明显：降低 `min_score` 或增加候选池宽度。

## 14. 系统复盘算法

函数：

```python
review_system(conn, trading_date: str) -> SystemReview
```

步骤：

1. 聚合全策略表现。
2. 聚合数据质量异常。
3. 聚合盲点行业和事件类型。
4. 检查是否所有策略同向失败。
5. 检查是否候选池过窄或过度集中。
6. 生成系统级观察，不直接改 gene。

系统级 optimization signals 只允许：

- `add_data_source`
- `observe_only`
- `add_filter`
- `relax_filter`

不直接修改某个 gene 参数，除非能映射到稳定 gene_review 信号。

## 15. LLM 复盘设计

### 15.1 输入压缩

LLM 不看全量行情。输入是 review packet：

```json
{
  "target": {"type": "decision", "id": "pick_xxx"},
  "preopen_snapshot": {
    "candidate_packet": {},
    "pick_thesis": {},
    "risk_notes": []
  },
  "postclose_facts": {
    "outcome": {},
    "price_action": {},
    "relative_performance": {},
    "sector_performance": {}
  },
  "events": {
    "preopen_visible": [],
    "postdecision": []
  },
  "deterministic_checks": [],
  "known_error_taxonomy": [],
  "allowed_outputs": {}
}
```

### 15.2 LLM 约束

- 必须输出 `LLMReviewContract`。
- 每个 attribution 必须引用 evidence_id。
- 不允许发明证据。
- 没有证据时必须使用 `AMBIGUOUS`。
- 对推荐之后才发生的新闻必须放入 `not_knowable_preopen`。
- LLM suggested optimization signal 默认不能直接进入 `open`，先写 `status='candidate'` 或进入 deterministic consolidation。

### 15.3 Token 预算

单日 LLM review 只处理：

- 所有已推荐股票，通常少于 30 条。
- 当日亏损最大或回撤最大推荐。
- 涨幅榜盲点 top 10。
- 每个强势行业最多 3 个代表盲点。
- 每个 gene 一个聚合 review packet。
- 一个 system review packet。

预算建议：

- decision review packet 单条小于 2 KB JSON。
- blindspot packet 单条小于 1.5 KB JSON。
- gene review packet 小于 6 KB JSON。
- system review packet 小于 8 KB JSON。

## 16. optimization_signals 到策略进化

当前已有 `strategy_evolution_events`，后续进化模块需要改为消费 `optimization_signals`。

### 16.1 信号聚合

函数：

```python
aggregate_optimization_signals(
    conn,
    gene_id: str,
    period_start: str,
    period_end: str,
    market_environment: str = "all",
) -> list[AggregatedSignal]
```

聚合维度：

- target_gene_id
- param_name
- signal_type
- direction
- scope
- scope_key

聚合指标：

- sample_size
- weighted_strength
- avg_confidence
- evidence_count
- affected_return_pct

### 16.2 生成 Challenger 门槛

必须同时满足：

- gene 样本数 >= 20。
- 单个参数方向一致的 signal sample_size >= 5。
- avg_confidence >= 0.65。
- 涉及 evidence 至少来自 3 个不同 trading_date，避免单日过拟合。
- 参数调整幅度单次不超过 5%。
- 总参数预算保持稳定，例如各 component weight 总和不变。

### 16.3 参数调整规则

示例：

- `increase_weight + event_component_weight`：权重乘以 `1 + min(0.05, weighted_strength * 0.05)`。
- `decrease_weight + event_component_weight`：权重乘以 `1 - min(0.05, weighted_strength * 0.05)`。
- `raise_threshold + min_score`：增加不超过 3%。
- `lower_threshold + min_score`：降低不超过 3%。
- `adjust_position + position_pct down`：仓位降低不超过 5%。
- `adjust_sell_rule + stop_loss_pct tighter`：止损绝对值缩小不超过 3%。

### 16.4 事件记录

每次生成 Challenger：

1. 插入新 `strategy_genes`，status = `observing`。
2. 插入 `strategy_evolution_events`，event_type = `proposal`。
3. 标记被消费的 `optimization_signals.status='consumed'`。
4. 保存 before_params、after_params、aggregated_signals、evidence_ids。

rollback：

1. Challenger status = `rolled_back`。
2. proposal event status = `rolled_back`。
3. 插入 rollback event。
4. 不删除历史模拟记录。

promotion：

1. Champion status = `retired`。
2. Challenger status = `active`。
3. 插入 promotion event。
4. 后续新 Challenger 以 promoted gene 为 parent。

## 17. API 设计

### 17.1 查询接口

- `GET /api/reviews?date=YYYY-MM-DD`
  - 返回当日 decision_reviews、gene_reviews、system_review 摘要。

- `GET /api/reviews/decisions?date=YYYY-MM-DD&gene_id=&stock_code=`
  - 返回单笔复盘列表。

- `GET /api/reviews/decisions/{review_id}`
  - 返回单笔复盘详情、factor_review_items、errors、evidence、optimization_signals。

- `GET /api/reviews/stocks/{stock_code}?date=YYYY-MM-DD&gene_id=`
  - 返回某只股票在某天的复盘视图。它以股票为中心，聚合该股票当天被哪些策略推荐、每条推荐的 outcome、factor checks、证据、错误类型、相关盲点或事件。
  - 前端用于“单个股票复盘”详情页。即使同一股票被多个策略选中，也只打开一个股票页面，然后在页面内切换 gene/decision。

- `GET /api/reviews/stocks/{stock_code}/history?start=YYYY-MM-DD&end=YYYY-MM-DD&gene_id=`
  - 返回某只股票跨日期的复盘历史，包括被推荐次数、平均收益、主要驱动、常见错误、关联事件和策略表现。
  - 前端用于查看“这个股票过去被系统如何判断，后续哪些判断被证实或否定”。

- `GET /api/reviews/preopen-strategies?date=YYYY-MM-DD`
  - 返回早盘策略整体复盘列表，每个策略一条摘要。聚合该策略早盘所有推荐、候选池、未入选强势股、整体收益、factor edge、top errors、optimization signals。
  - 前端用于“早盘策略整体复盘”页面，比较不同 gene 当天为什么表现不同。

- `GET /api/reviews/preopen-strategies/{gene_id}?date=YYYY-MM-DD`
  - 返回某个策略在某天的早盘整体复盘详情，包括：
    - 早盘输入快照 hash。
    - 推荐列表和未推荐候选 top N。
    - 该策略的因子权重和阈值。
    - 当日 outcome 汇总。
    - factor_edges。
    - top_errors。
    - blindspots affected by this gene。
    - generated optimization_signals。

- `GET /api/reviews/blindspots?date=YYYY-MM-DD`
  - 返回盲点复盘。

- `GET /api/reviews/genes/{gene_id}?start=YYYY-MM-DD&end=YYYY-MM-DD`
  - 返回策略周期复盘。

- `GET /api/reviews/system?date=YYYY-MM-DD`
  - 返回系统复盘。

- `GET /api/optimization-signals?gene_id=&status=&start=&end=`
  - 查询优化信号。

### 17.2 触发接口

- `POST /api/runs/deterministic_review?date=YYYY-MM-DD`
- `POST /api/runs/llm_review?date=YYYY-MM-DD`
- `POST /api/runs/review_consolidation?date=YYYY-MM-DD`
- `POST /api/reviews/stocks/{stock_code}/rerun?date=YYYY-MM-DD&gene_id=`
  - 重跑单个股票/单个策略的复盘，便于前端局部刷新。
- `POST /api/reviews/preopen-strategies/{gene_id}/rerun?date=YYYY-MM-DD`
  - 重跑某个策略当天的整体复盘，不影响其他策略。
- `POST /api/evolution/propose?start=YYYY-MM-DD&end=YYYY-MM-DD&gene_id=`
- `POST /api/evolution/rollback?child_gene_id=...`
- `POST /api/evolution/promote?child_gene_id=...`

### 17.3 Dashboard 数据

`GET /api/dashboard` 应增加：

```json
{
  "review_summary": {
    "decision_reviews": 0,
    "blindspot_reviews": 0,
    "top_errors": [],
    "open_optimization_signals": 0,
    "system_summary": "..."
  }
}
```

## 18. 后端模块拆分

建议新增模块：

```text
src/stock_select/
  review_schema.py
  review_taxonomy.py
  review_packets.py
  deterministic_review.py
  blindspot_review.py
  gene_review.py
  system_review.py
  optimization_signals.py
  llm_review.py
```

职责：

- `review_schema.py`：Pydantic/stdlib contract validation。
- `review_taxonomy.py`：枚举、错误类型、合法转换。
- `review_packets.py`：构建给确定性代码和 LLM 的压缩输入包。
- `deterministic_review.py`：单笔推荐复盘。
- `blindspot_review.py`：盲点复盘。
- `gene_review.py`：策略版本复盘。
- `system_review.py`：系统复盘。
- `optimization_signals.py`：信号写入、聚合、消费。
- `llm_review.py`：LLM prompt、schema 校验、失败降级。

现有 `review.py` 后续可以保留为 facade：

```python
def run_deterministic_review(conn, trading_date: str) -> dict:
    ...

def run_llm_review(conn, trading_date: str) -> dict:
    ...

def run_review_consolidation(conn, trading_date: str) -> dict:
    ...
```

## 19. 调度设计

现有 `review` phase 应拆成三个 phase：

- `deterministic_review`
- `llm_review`
- `review_consolidation`

每日调度：

```text
15:05 close_sync
15:10 simulate
15:15 deterministic_review
15:30 llm_review
15:50 review_consolidation
16:00 sync_graph
周六 10:00 strategy_optimization
```

失败策略：

- deterministic_review 失败：阻断后续复盘，记录 error。
- llm_review 失败：不阻断 deterministic review、memory、收益计算。
- review_consolidation 失败：不生成 optimization_signals。
- strategy_optimization 失败：不影响日常模拟盘。

## 20. 幂等与重跑

所有写入必须支持重跑：

- `decision_reviews` 按 `decision_id` upsert。
- `factor_review_items` 按 `review_id + factor_type` upsert。
- `blindspot_reviews` 按 `trading_date + stock_code` upsert。
- `gene_reviews` 按 `gene_id + period + market_environment` upsert。
- `system_reviews` 按 `trading_date` upsert。
- `optimization_signals` 使用稳定 hash 生成 signal_id；同源同类型同参数 upsert。
- FTS5 memory 写入前按 `source_type + source_id` 删除旧记录。

不允许重跑产生重复 review、重复 signal、重复 memory。

## 21. 前端设计

### 21.1 复盘中心

页面：`ReviewCenter`

区域：

- 日期选择。
- 今日复盘总览：总推荐、盈利推荐、亏损推荐、盲点数、主要错误。
- 单笔复盘表：股票、策略、收益、verdict、primary_driver、top error。
- 盲点复盘表：股票、涨幅、missed_stage、primary_reason、affected genes。
- 策略复盘：每个 gene 的胜率、收益、盲点、factor edges。
- 系统复盘：全局问题、数据质量、开放优化信号。

### 21.2 单笔复盘详情

页面：`StockReviewDetail`

入口：

- 从推荐列表点击股票。
- 从盲点复盘点击股票。
- 从策略整体复盘点击某条推荐。

内容：

- 股票基础信息和当日行情。
- 同一股票当天在不同 gene 下的推荐/未推荐状态。
- 推荐原始 thesis。
- 候选分数拆解。
- outcome。
- factor check 列表。
- evidence 列表。
- 财报预期差、订单合同、经营 KPI、行业景气、风险事件等复盘依据表。
- LLM attribution。
- optimization signals。

### 21.3 早盘策略整体复盘

页面：`PreopenStrategyReview`

入口：

- 从复盘中心点击某个 gene。
- 从策略基因页面点击某天表现。

内容：

- 策略参数快照：因子权重、阈值、仓位、卖出规则。
- 早盘候选池 summary：候选数量、行业分布、最高分候选、被过滤数量。
- 推荐组合：推荐股票、仓位、score、confidence。
- 收盘整体表现：平均收益、胜率、最大回撤、相对指数收益。
- 因子兑现情况：technical/fundamental/event/sector/risk 的 winner_avg、loser_avg、edge。
- 盲点影响：该策略漏掉的涨幅榜股票、missed_stage、主要原因。
- 策略错误排行：top_errors。
- 生成的 optimization_signals。

这个页面和单股复盘必须是独立接口，前端不能依赖一个大 dashboard 里混合所有数据。

### 21.4 策略优化页面

内容：

- Open optimization signals。
- 已聚合信号。
- Challenger proposal。
- Champion/Challenger 对比。
- Promotion / rollback 操作入口。

MVP 可以先只读展示，不做按钮；按钮后续加确认弹窗。

## 22. 测试计划

### 22.1 单元测试

- `DecisionReviewContract` 校验必填字段和枚举。
- `LLMReviewContract` 拒绝无 evidence 的 EXTRACTED claim。
- 单笔复盘幂等 upsert。
- factor check 正确生成 RIGHT/WRONG/MIXED。
- 单股复盘接口能聚合同日多个 gene 的 review。
- 早盘策略整体复盘接口只返回指定 gene 的候选、推荐、盲点和 factor edge。
- 盲点复盘能区分 `candidate_scoring` 和 `max_picks_limit`。
- late_signal 不生成策略惩罚。
- optimization_signals 稳定 hash，不重复写入。
- signal 聚合样本不足不生成 Challenger。
- rollback 后 Challenger 不再参与 active/observing 运行池。

### 22.2 集成测试

- demo 数据跑完整流程：
  - seed
  - preopen_pick
  - simulate
  - deterministic_review
  - blindspot_review
  - gene_review
  - system_review
  - propose_evolution

- 重跑同一天 review 不增加重复记录。
- LLM review schema 失败时，deterministic review 保留，optimization_signals 不被 LLM 输出污染。
- FTS5 能检索复盘 summary。
- Dashboard 能显示 review_summary。

### 22.3 回归测试

- 预盘推荐仍不能读取当日行情。
- 复盘允许读取当日行情，但 evidence visibility 必须标注。
- 盲点中由 postdecision event 导致上涨的股票不惩罚策略。
- 策略优化只消费 `open` 且达标的 optimization_signals。
- promotion/rollback 不删除历史 pick/outcome/review。

## 23. 实施顺序

### Step 1：Schema 和 Taxonomy

- 新增复盘相关表。
- 新增 `review_taxonomy.py`。
- 新增 contract validator。
- 写基础单元测试。

### Step 2：确定性单笔复盘

- 实现 `review_decision`。
- 写入 `decision_reviews`、`factor_review_items`、`review_evidence`、`review_errors`。
- 替换当前过于简单的 `generate_deterministic_reviews`。

### Step 3：盲点复盘

- 从 `blindspot_reports` 升级到 `blindspot_reviews`。
- 解释 missed_stage。
- 生成初步 optimization_signals。

### Step 4：策略和系统复盘

- 实现 `gene_reviews`。
- 实现 `system_reviews`。
- 实现 review_summary API。

### Step 5：optimization_signals 聚合

- 实现 signal upsert。
- 实现 signal 聚合。
- 修改 evolution 模块，让它消费 aggregated signals。
- 保留当前 review_signal 逻辑作为 fallback。

### Step 6：LLM 复盘

- 实现 review packet builder。
- 实现 LLM prompt 和 schema 校验。
- LLM 失败只记录 error，不影响 deterministic review。

### Step 7：前端复盘中心

- 新增 ReviewCenter 页面。
- Dashboard 增加 review_summary。
- Gene 页面显示 open signals 和 Challenger 状态。

### Step 8：再切真实数据

复盘闭环跑通后，再接真实 AKShare/BaoStock，否则真实数据只会放大噪音。

## 24. 当前代码映射

现有模块和目标模块关系：

- `review.py`
  - 当前只是最小 deterministic review。
  - 后续改成 facade，调用新的复盘模块。

- `blindspots.py`
  - 当前只生成简单 `blindspot_reports`。
  - 后续补 missed_stage、affected_gene_ids、optimization_signals。

- `evolution.py`
  - 当前已经支持 proposal/rollback/promotion。
  - 后续改为消费 `optimization_signals`。

- `candidate_pipeline.py`
  - 已有多维 candidate packet。
  - 复盘必须优先使用 packet_json 审计早盘理由。

- `memory.py`
  - 可继续用于复盘 summary FTS5 检索。

- `graph.py`
  - 后续增加 Review、Error、OptimizationSignal 节点和边。

## 25. 验收标准

复盘系统第一阶段完成的标准：

- 每条 pick 都有一条 decision_review。
- 每条 decision_review 至少有 technical、fundamental、event、sector、risk、execution 六个 factor item。
- 每条 review 至少有 outcome 和 candidate_score evidence。
- 盲点股能解释 missed_stage。
- gene_review 能输出 factor_edges 和 top_errors。
- optimization_signals 可查询、可聚合、可被 evolution 消费。
- 重跑每日 review 不产生重复数据。
- 无 LLM key 时系统仍可完成确定性复盘和策略优化提案。
- LLM 输出错误不会污染策略优化。
