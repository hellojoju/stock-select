---
name: 个股复盘完整方案 - 豆包建议全量落地
description: 将豆包对话中所有复盘建议逐一映射到 stock-select 系统的完整方案和实施计划
type: project
originSessionId: 85a173f2-f738-44e5-93ea-759fd3ca01fe
---
# 个股复盘完整方案 — 豆包建议全量落地

> 对照来源：豆包对话（2026-04-26 存档于 memory/doubao_stock_review_methods.md）
> 现状基线：2026-04-26 完整审计完成

---

## 一、豆包建议逐条映射表

### A. 盘面数据复盘层

| # | 豆包建议 | 现状 | 实现方式 | 模块 |
|---|---------|------|---------|------|
| A1 | 四大指数复盘（上证/深证/创业板/北证） | ⚠️ 有 index_prices 但仅做相对收益基准 | 读取 index_prices 四指数当日涨跌幅、量价关系 | market_overview |
| A2 | 涨跌分布（市场赚钱效应） | ❌ 无 | 扫描 daily_prices 全市场涨跌家数、涨停/跌停统计 | market_overview |
| A3 | 涨停分析（板块集中/龙头/封板质量） | ❌ 无 | daily_prices 推算涨停 + LLM 从公告中提取涨停原因 | market_overview |
| A4 | 跌停分析（获利回吐/利空/高位补跌） | ❌ 无 | daily_prices 推算跌停 + 公告关联跌停原因 | market_overview |
| A5 | 成交量前10（资金博弈焦点） | ❌ 无 | daily_prices 按 volume 排序 Top10 | market_overview |
| A6 | 成交额前10（大资金活动） | ❌ 无 | daily_prices 按 amount 排序 Top10 | market_overview |
| A7 | 市场主线与轮动识别 | ⚠️ 有 sector_theme_signals | 近3天板块涨幅排行 + LLM 提取驱动逻辑 | sector_analysis |
| A8 | 风格偏好（大盘蓝筹 vs 中小盘题材） | ❌ 无 | 指数黄白线关系 or 大盘/小盘指数相对强弱 | market_overview |

### B. 情绪周期层

| # | 豆包建议 | 现状 | 实现方式 | 模块 |
|---|---------|------|---------|------|
| B1 | 上涨家数/下跌家数 | ❌ 无 | daily_prices 全市场统计 | sentiment_cycle |
| B2 | 涨停数/跌停数 | ❌ 无 | daily_prices 推算 | sentiment_cycle |
| B3 | 封板率 | ❌ 无 | 涨停股中封住的比例（需要盘中快照或估算） | sentiment_cycle |
| B4 | 晋级率（一进二等） | ❌ 无 | 连续涨停天数统计，计算晋级成功率 | sentiment_cycle |
| B5 | 情绪周期阶段判定 | ❌ 无 | 规则引擎：B1-B4 → 冰点/回暖/升温/高潮/退潮/恐慌 | sentiment_cycle |
| B6 | 融资余额变化 | ❌ 无 | BaoStock `stk_margin` 接口 | sentiment_cycle |
| B7 | 融券余额变化 | ❌ 无 | BaoStock `stk_margin` 接口 | sentiment_cycle |
| B8 | 社交媒体讨论热度（破圈效应） | ❌ 无 | 现有 news_providers 管道代理：用文章/公告数量作为热度代理指标 | sentiment_cycle |
| B9 | 过度乐观言论检测 | ❌ 无 | LLM 对新闻/公告文本做情感打分 | sentiment_cycle |
| B10 | 重大事件影响评估 | ⚠️ 有 event_signals | 已有12类事件提取，需增强对宏观事件的覆盖 | sentiment_cycle |

### C. 板块联动层

| # | 豆包建议 | 现状 | 实现方式 | 模块 |
|---|---------|------|---------|------|
| C1 | 板块涨幅排行 | ⚠️ 有 sector_theme_signals | 按 industry 分组计算板块当日/3日/10日涨幅 | sector_analysis |
| C2 | 领涨板块驱动逻辑 | ❌ 无 | LLM 从板块内股票公告/新闻中提取共同驱动因素 | sector_analysis |
| C3 | 板块内部分析（普涨 vs 龙头带动） | ❌ 无 | 板块内个股涨跌比例 + 龙头贡献度 | sector_analysis |
| C4 | 梯队完整性（龙头/中军/跟风） | ❌ 无 | 板块内按涨幅/市值/成交额分级 | sector_analysis |
| C5 | 持续性判断（量价+逻辑） | ❌ 无 | 量价配合度 + 驱动逻辑硬度评分 | sector_analysis |
| C6 | 近3天涨停股最多的板块 | ❌ 无 | 统计近3天各板块涨停数量 | sector_analysis |
| C7 | 主线加强 vs 快速轮动 | ❌ 无 | 板块连续性分析：连续 N 天上榜的板块 = 主线 | sector_analysis |

### D. 个股深度复盘层

| # | 豆包建议 | 现状 | 实现方式 | 模块 |
|---|---------|------|---------|------|
| D1 | 个股所属板块强度 | ⚠️ sector_check 有但不深入 | 关联 sector_analysis，显示板块排名、持续性 | stock_deep_review |
| D2 | 板块内排名 | ❌ 无 | 板块内按涨幅/成交额/换手率排序 | stock_deep_review |
| D3 | 龙头股识别与对比 | ❌ 无 | 识别板块龙头，对比个股与龙头的涨幅/量能 | stock_deep_review |
| D4 | 资金流向（主力/散户） | ❌ 无 | AkShare `stock_individual_fund_flow` 接口 | stock_deep_review |
| D5 | 量能分析（放量/缩量/异常） | ❌ 无 | daily_prices 中 volume 与均量对比 | stock_deep_review |
| D6 | 形态与均线（5日线位置） | ❌ 无 | 计算5/10/20日均线及股价相对位置 | stock_deep_review |
| D7 | 换手率分析 | ❌ 无 | daily_prices 计算 turnover_rate | stock_deep_review |
| D8 | 连板天数 | ❌ 无 | daily_prices 连续涨停统计 | stock_deep_review |
| D9 | 龙头股逻辑与资金流向 | ❌ 无 | 对龙头股执行 D1-D8 全套分析 | stock_deep_review |
| D10 | 第二梯队识别 | ❌ 无 | 龙头不适合时，识别板块内第二强股 | stock_deep_review |
| D11 | 开盘点位判断 | ❌ 无 | 基于前日量价+板块强度判断合理开盘区间 | stock_deep_review |

### E. 交易心理与预案层

| # | 豆包建议 | 现状 | 实现方式 | 模块 |
|---|---------|------|---------|------|
| E1 | 成功归因（为什么好？如何复制？） | ⚠️ 有 review_summary 但偏技术 | LLM 生成成功原因 + 可复制条件 | psychology_review |
| E2 | 失败归因（技术误判/消息遗漏/情绪失控/计划不周/执行偏差） | ⚠️ 有 error_type | 映射 error_type → 心理归因 | psychology_review |
| E3 | 保持和复制成功的方法 | ❌ 无 | LLM 从成功案例中提取可复用模式 | psychology_review |
| E4 | 避免再犯的方法 | ❌ 无 | 从 optimization_signals 中提炼预防策略 | psychology_review |
| E5 | 次日应对方案（多种走势预案） | ❌ 无 | LLM 根据形态/情绪/板块生成 3 种场景预案 | next_day_plan |
| E6 | 各种走势应对方案做到心中有数 | ❌ 无 | 预案写入 review，前端展示 | next_day_plan |

### F. 自定义板块归类层（同花顺式）

| # | 豆包建议 | 现状 | 实现方式 | 模块 |
|---|---------|------|---------|------|
| F1 | 当日涨停板块 | ❌ 无 | daily_prices 筛选涨停股 | custom_sectors |
| F2 | 当日高换手板块（>20%） | ❌ 无 | daily_prices 筛选 | custom_sectors |
| F3 | 十日高换手板块 | ❌ 无 | daily_prices 近10日统计 | custom_sectors |
| F4 | 十日异动板块（涨停+3倍放量） | ❌ 无 | daily_prices 近10日统计 | custom_sectors |
| F5 | 大成交额板块（>10亿） | ❌ 无 | daily_prices 筛选 | custom_sectors |

### G. 情绪分析技术层（LLM 管线）

| # | 豆包建议 | 现状 | 实现方式 | 模块 |
|---|---------|------|---------|------|
| G1 | 数据采集（财经媒体/资讯/论坛） | ✅ 已有 5 个新闻提供商 | 扩展现有管道 | llm_sentiment |
| G2 | 数据清洗（去重/去广告/保留金融相关） | ⚠️ 有去重 | 增强清洗规则：去广告模板、非金融内容过滤 | llm_sentiment |
| G3 | 情感分析（词典法 or 深度学习） | ❌ 无 | LLM 对新闻文本做情感打分（-1 到 +1） | llm_sentiment |
| G4 | 主题提取 | ❌ 无 | LLM 从板块新闻中提取共同主题 | llm_sentiment |
| G5 | 降维提纯（多指标情绪合成） | ❌ 无 | PCA/加权合成：量价波动 + 新闻情感 + 讨论热度 → 综合情绪分 | llm_sentiment |

---

## 二、架构设计：三层复盘体系

```
┌─────────────────────────────────────────────────────────────────┐
│                    个股复盘三层体系                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  第一层：市场总览（Market Overview）                               │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ market_overview.py                                        │  │
│  │ - 四大指数涨跌                                             │  │
│  │ - 涨跌分布（全市场赚钱效应）                                   │  │
│  │ - 涨停/跌停分析（板块集中/原因）                               │  │
│  │ - 成交量/成交额 Top10                                      │  │
│  │ - 市场风格（大盘/小盘偏好）                                    │  │
│  │ - 市场主线与轮动（近3天板块排行）                               │  │
│  └───────────────────────────────────────────────────────────┘  │
│                              │                                   │
│                              ▼                                   │
│  第二层：情绪周期（Sentiment Cycle）                               │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ sentiment_cycle.py                                        │  │
│  │ - 涨跌家数比 / 涨停数 / 跌停数                                │  │
│  │ - 封板率 / 晋级率                                            │  │
│  │ - 融资融券余额变化                                           │  │
│  │ - 社交媒体/新闻讨论热度                                       │  │
│  │ - LLM 情感分析管线（G1-G5）                                   │  │
│  │ - 情绪周期阶段判定 → 冰点/回暖/升温/高潮/退潮/恐慌              │  │
│  └───────────────────────────────────────────────────────────┘  │
│                              │                                   │
│                              ▼                                   │
│  第三层：个股深度复盘（Stock Deep Review）                         │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ stock_deep_review.py                                      │  │
│  │                                                             │  │
│  │  A. 板块联动                                                 │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │ sector_analysis.py                                  │  │  │
│  │  │ - 板块涨幅排行（1d/3d/10d）                             │  │  │
│  │  │ - 驱动逻辑（LLM 提取）                                   │  │  │
│  │  │ - 板块内排名 / 梯队结构                                  │  │  │
│  │  │ - 持续性判断                                           │  │  │
│  │  │ - 自定义板块归类（涨停/高换手/异动/大成交额）                  │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  │                                                             │  │
│  │  B. 个股量化                                                │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │ stock_quant.py                                      │  │  │
│  │  │ - 资金流向（主力/超大单/散户）                              │  │  │
│  │  │ - 量价分析（放量/缩量/异常）                                │  │  │
│  │  │ - 均线形态（5/10/20日线位置）                               │  │  │
│  │  │ - 换手率 / 连板天数                                      │  │  │
│  │  │ - 龙头股对比                                            │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  │                                                             │  │
│  │  C. 交易心理与预案                                           │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │ psychology_review.py                                │  │  │
│  │  │ - 成功归因 / 失败归因（映射 error_type → 心理归因）         │  │  │
│  │  │ - 可复制模式提取                                        │  │  │
│  │  │ - 次日应对方案（3 种场景）                                  │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 三、数据流与集成点

### 3.1 数据源映射

| 数据类型 | 数据源 | 现有状态 | 需新增 |
|---------|--------|---------|--------|
| 全市场涨跌统计 | daily_prices（已有） | ✅ 已有 | 仅需聚合计算 |
| 四指数行情 | index_prices（已有） | ✅ 已有 | 扩展读取更多指数 |
| 融资融券 | BaoStock stk_margin | ❌ 无 | 新增 ingestion |
| 资金流向 | AkShare stock_individual_fund_flow | ❌ 无 | 新增 ingestion |
| 板块分类 | 已有 fundamental_metrics + stocks.industry | ✅ 已有 | 增强板块聚合 |
| 公告/新闻 | 已有 5 个新闻提供商 | ✅ 已有 | 扩清洗规则 + 情感分析 |
| 分钟级数据（黄白线） | AkShare stock_zh_index_minute_em | ❌ 无 | 可选，优先级低 |
| 涨停/跌停推算 | daily_prices 已有 OHLCV | ✅ 可推算 | 计算逻辑新增 |

### 3.2 与现有管线的集成

```
review.py (generate_deterministic_reviews)
  │
  ├── [新增] generate_market_overview(date)
  │     ├── 四指数涨跌 ← index_prices
  │     ├── 涨跌分布 ← daily_prices 聚合
  │     ├── 涨停/跌停分析 ← daily_prices + event_signals
  │     ├── Top10 成交量/成交额 ← daily_prices
  │     ├── 市场风格 ← 指数相对强弱
  │     └── 写入 market_overview_daily 表
  │
  ├── [新增] analyze_sentiment_cycle(date)
  │     ├── 涨跌家数/涨停跌停 ← daily_prices 聚合
  │     ├── 封板率/晋级率 ← daily_prices 推算
  │     ├── 融资融券变化 ← BaoStock (新增 ingestion)
  │     ├── 新闻讨论热度 ← raw_documents 聚合
  │     ├── LLM 情感打分 ← LLM pipeline (G3-G5)
  │     ├── 情绪周期阶段判定 ← 规则引擎
  │     └── 写入 sentiment_cycle_daily 表
  │
  ├── [新增] analyze_sector(date)
  │     ├── 板块涨幅排行 ← daily_prices + stocks.industry 聚合
  │     ├── 近3天涨停最多板块 ← daily_prices 统计
  │     ├── 驱动逻辑提取 ← LLM 从新闻/公告提取
  │     ├── 梯队结构 ← 板块内分级
  │     ├── 持续性判断 ← 量价+逻辑评分
  │     └── 写入 sector_analysis_daily 表
  │
  ├── [新增] classify_custom_sectors(date)
  │     ├── 当日涨停/高换手/十日高换手/十日异动/大成交额
  │     └── 写入 stock_custom_sector 表
  │
  ├── review_decision(decision_id)
  │     ├── [已有] 11 factor checks
  │     ├── [新增] market_overview context
  │     ├── [新增] sentiment_cycle context
  │     ├── [新增] sector_analysis context
  │     ├── [新增] capital_flow check
  │     ├── [新增] stock_quant check
  │     └── [已有] optimization signals
  │
  ├── llm_review_for_decision()
  │     ├── [增强] 传入市场总览
  │     ├── [增强] 传入情绪周期
  │     ├── [增强] 传入板块联动信息
  │     ├── [新增] 要求生成心理归因 (E1-E4)
  │     └── [新增] 要求生成次日预案 (E5-E6)
  │
  └── [新增] stock_deep_review(stock_code, date)
        ├── 板块联动完整报告
        ├── 资金流向报告
        ├── 量价形态报告
        ├── 龙头股对比
        ├── 自定义板块标签
        ├── 交易心理归因
        └── 次日应对方案
```

---

## 四、数据库 Schema 变更

```sql
-- 市场总览日度表
CREATE TABLE market_overview_daily (
    trading_date TEXT PRIMARY KEY,
    sh_return REAL,             -- 上证涨跌幅
    sz_return REAL,             -- 深证涨跌幅
    cyb_return REAL,            -- 创业板涨跌幅
    bse_return REAL,            -- 北证涨跌幅
    advance_count INTEGER,      -- 上涨家数
    decline_count INTEGER,      -- 下跌家数
    flat_count INTEGER,         -- 平盘家数
    limit_up_count INTEGER,     -- 涨停家数
    limit_down_count INTEGER,   -- 跌停家数
    top_volume_stocks TEXT,     -- JSON: 成交量 Top10
    top_amount_stocks TEXT,     -- JSON: 成交额 Top10
    style_preference TEXT,      -- 大盘/小盘/均衡
    main_sectors TEXT,          -- JSON: 领涨板块 Top5
    created_at TEXT DEFAULT (datetime('now'))
);

-- 情绪周期日度表
CREATE TABLE sentiment_cycle_daily (
    trading_date TEXT PRIMARY KEY,
    advance_count INTEGER,
    decline_count INTEGER,
    limit_up_count INTEGER,
    limit_down_count INTEGER,
    seal_rate REAL,             -- 封板率 0-1
    promotion_rate REAL,        -- 晋级率
    financing_balance REAL,     -- 融资余额
    financing_change_pct REAL,  -- 融资余额变化%
    short_selling_balance REAL, -- 融券余额
    short_selling_change_pct REAL,
    news_heat REAL,             -- 新闻/文章数量代理热度 0-1
    llm_sentiment_score REAL,   -- LLM 情感打分 -1 到 +1
    composite_sentiment REAL,   -- 综合情绪分 (PCA/加权合成)
    cycle_phase TEXT,           -- 冰点/回暖/升温/高潮/退潮/恐慌
    cycle_reason TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- 板块分析日度表
CREATE TABLE sector_analysis_daily (
    id INTEGER PRIMARY KEY,
    trading_date TEXT,
    sector_name TEXT,
    sector_return_pct REAL,
    strength_1d REAL,
    strength_3d REAL,
    strength_10d REAL,
    stock_count INTEGER,        -- 板块内股票数
    advance_ratio REAL,         -- 板块内上涨比例
    leader_stock TEXT,          -- 龙头代码
    leader_return_pct REAL,
    leader_limit_up_days INTEGER,
    mid_tier_stocks TEXT,       -- JSON: 中军
    follower_stocks TEXT,       -- JSON: 跟风
    drive_logic TEXT,           -- LLM 提取的驱动逻辑
    team_complete INTEGER,      -- 梯队是否完整 0/1
    sustainability REAL,        -- 持续性评分 0-1
    limit_up_3d_count INTEGER,  -- 近3天涨停数
    UNIQUE(trading_date, sector_name)
);

-- 资金流向日度表
CREATE TABLE capital_flow_daily (
    id INTEGER PRIMARY KEY,
    trading_date TEXT,
    stock_code TEXT,
    main_net_inflow REAL,       -- 主力净流入（万元）
    large_order_inflow REAL,    -- 大单净流入
    super_large_inflow REAL,    -- 超大单净流入
    retail_outflow REAL,        -- 散户净流出
    flow_trend TEXT,            -- 流入/流出/平衡
    sector_flow_rank INTEGER,   -- 行业内排名
    UNIQUE(trading_date, stock_code)
);

-- 自定义板块归类表
CREATE TABLE stock_custom_sector (
    id INTEGER PRIMARY KEY,
    trading_date TEXT,
    stock_code TEXT,
    sector_key TEXT,            -- limit_up_today / high_turnover_today /
                                -- high_turnover_10d / unusual_10d / large_amount
    UNIQUE(trading_date, stock_code, sector_key)
);

-- 交易心理归因表
CREATE TABLE psychology_review (
    id INTEGER PRIMARY KEY,
    decision_review_id INTEGER,
    success_reasons TEXT,       -- JSON: 成功原因列表
    failure_reasons TEXT,       -- JSON: 失败原因列表
    psychological_category TEXT, -- 技术误判/消息遗漏/情绪驱动/计划不周/执行偏差
    reproducible_patterns TEXT, -- JSON: 可复制模式
    prevention_strategies TEXT, -- JSON: 预防策略
    created_at TEXT DEFAULT (datetime('now'))
);

-- 次日预案表
CREATE TABLE next_day_plan (
    id INTEGER PRIMARY KEY,
    decision_review_id INTEGER,
    scenarios TEXT,             -- JSON: [
                                --   {"scenario": "高开3%以上", "action": "...", "condition": "..."},
                                --   {"scenario": "平开", "action": "...", "condition": "..."},
                                --   {"scenario": "低开2%以下", "action": "...", "condition": "..."}
                                -- ]
    key_levels TEXT,            -- JSON: 关键价位
    created_at TEXT DEFAULT (datetime('now'))
);

-- 股票自定义板块关联（用于 API 快速查询）
CREATE INDEX idx_custom_sector_date ON stock_custom_sector(trading_date, sector_key);
CREATE INDEX idx_capital_flow_date ON capital_flow_daily(trading_date, stock_code);
CREATE INDEX idx_sector_date ON sector_analysis_daily(trading_date, sector_return_pct DESC);
```

---

## 五、API 设计

### 5.1 新增 API 端点

```
GET /api/reviews/market-overview?date=YYYY-MM-DD
  → { advance_count, decline_count, limit_up_count, limit_down_count,
      top_volume_stocks[], top_amount_stocks[], style_preference,
      main_sectors[], sh_return, sz_return, cyb_return, bse_return }

GET /api/reviews/sentiment-cycle?date=YYYY-MM-DD
  → { cycle_phase, cycle_reason, seal_rate, promotion_rate,
      financing_change_pct, short_selling_change_pct,
      news_heat, llm_sentiment_score, composite_sentiment }

GET /api/reviews/sectors?date=YYYY-MM-DD&limit=10
  → [{ sector_name, sector_return_pct, strength_1d/3d/10d,
       leader_stock, leader_return_pct, drive_logic,
       team_complete, sustainability }]

GET /api/reviews/stocks/{code}/deep-review?date=YYYY-MM-DD
  → {
      stock: {...},
      market_overview: {...},
      sentiment_cycle: {...},
      sector_analysis: {...},
      capital_flow: {...},
      stock_quant: {...},
      custom_sectors: [...],
      psychology_review: {...},
      next_day_plan: {...},
      // 现有字段保持不变
      decisions: [...],
      blindspot: {...},
      domain_facts: {...}
    }

GET /api/reviews/custom-sectors?date=YYYY-MM-DD&sector_key=limit_up_today
  → [{ stock_code, stock_name, return_pct, turnover_rate, amount, limit_up_days }]
```

### 5.2 增强现有 API

```
GET /api/reviews/stocks/{code}?date=...
  → 新增字段:
     - market_overview: 市场总览
     - sentiment_cycle: 情绪周期
     - sector_analysis: 板块分析
     - custom_sectors: 自定义板块标签
```

---

## 六、前端新增内容

### 6.1 ReviewPage 新增 Tab

在现有 5 个 Tab（stock/strategy/blindspot/llm/signals）基础上，新增：

**Tab: market（市场总览）**
- 四大指数涨跌幅卡片
- 涨跌分布饼图
- 涨停/跌停板块分布
- Top10 成交量/成交额列表
- 市场风格标签（大盘行情/小盘行情/均衡）
- 近3天主线板块排行

**Tab: sentiment（情绪周期）**
- 情绪周期阶段大卡片（带颜色标识：冰点=蓝, 回暖=绿, 升温=黄, 高潮=红, 退潮=橙, 恐慌=紫）
- 封板率/晋级率仪表盘
- 融资融券余额变化趋势
- 新闻讨论热度折线
- LLM 情感打分

### 6.2 StockReviewPanel 新增卡片

在现有股票详情头部新增：

1. **自定义板块标签行** — 显示该股票属于哪些自定义板块（涨停/高换手/异动等），用彩色 badge 展示
2. **市场情绪上下文** — 在股票头部显示当日情绪周期阶段
3. **板块联动卡片** — 显示所属板块排名、龙头、梯队结构、驱动逻辑
4. **资金流向卡片** — 主力/超大单/散户资金流向（用箭头+颜色直观展示）
5. **量价形态卡片** — 均线位置、放量/缩量、换手率、连板天数
6. **交易心理归因卡片** — 成功/失败原因 + 心理分类
7. **次日预案卡片** — 3 种场景 + 应对策略（可展开）

---

## 七、实施计划

### Sprint 8A — 数据基础设施（3-4天）

| 任务 | 文件 | 工作量 | 依赖 |
|------|------|--------|------|
| 新增数据库 schema | migrations/ | 0.5天 | 无 |
| 市场总览模块 | market_overview.py | 1天 | daily_prices 已有 |
| 情绪周期模块 | sentiment_cycle.py | 1.5天 | daily_prices 已有 |
| BaoStock 融资融券 ingestion | data_ingestion.py 扩展 | 1天 | BaoStock 接口 |

### Sprint 8B — 板块与分类（3-4天）

| 任务 | 文件 | 工作量 | 依赖 |
|------|------|--------|------|
| 板块分析模块 | sector_analysis.py | 1.5天 | stocks.industry 已有 |
| 自定义板块归类 | stock_classifier.py | 1天 | daily_prices 已有 |
| LLM 驱动逻辑提取 | sector_analysis.py (LLM部分) | 1天 | llm_review.py 管线 |
| AkShare 资金流向 ingestion | data_ingestion.py 扩展 | 0.5天 | AkShare 接口 |
| 资金流向模块 | capital_flow.py | 1天 | ingestion 完成 |

### Sprint 8C — 个股深度复盘（3-4天）

| 任务 | 文件 | 工作量 | 依赖 |
|------|------|--------|------|
| 股票量化模块 | stock_quant.py | 1.5天 | daily_prices + capital_flow |
| 龙头股识别 | sector_analysis.py 扩展 | 1天 | sector_analysis 完成 |
| 交易心理归因 | psychology_review.py | 1天 | deterministic_review 已有 |
| 次日预案生成 | next_day_plan.py | 1天 | LLM 管线 |

### Sprint 8D — API 与前端整合（3-4天）

| 任务 | 文件 | 工作量 | 依赖 |
|------|------|--------|------|
| 新增 API 端点 | server.py + api.py | 1天 | 后端模块完成 |
| 增强现有 API | api.py | 0.5天 | 后端模块完成 |
| 市场总览前端 | MarketOverviewPage.tsx | 1天 | API 完成 |
| 情绪周期前端 | SentimentCyclePage.tsx | 1天 | API 完成 |
| StockReviewPanel 扩展 | StockReviewPanel.tsx | 1.5天 | API 完成 |
| 自定义板块前端 | CustomSectorPanel.tsx | 0.5天 | API 完成 |

### Sprint 8E — LLM 情感管线（2-3天）

| 任务 | 文件 | 工作量 | 依赖 |
|------|------|--------|------|
| 新闻清洗规则增强 | news_providers.py | 0.5天 | 无 |
| LLM 情感打分 | llm_sentiment.py | 1天 | news_providers 完成 |
| 综合情绪合成 | sentiment_cycle.py 扩展 | 0.5天 | 情感打分完成 |
| 破圈效应检测 | breakout_monitor.py | 1天 | 新闻聚合完成 |

**总工作量**: 14-19 天

---

## 八、与现有 review_decision 的集成细节

在 `review_decision()` 中，新增以下内容：

```python
# 在 review_decision() 的 build_factor_items() 前新增：

# 1. 获取市场总览上下文
market_ctx = get_market_overview(trading_date)
packet['market_context'] = market_ctx

# 2. 获取情绪周期上下文
sentiment_ctx = get_sentiment_cycle(trading_date)
packet['sentiment_context'] = sentiment_ctx

# 3. 获取板块分析上下文
sector_ctx = get_sector_analysis_for_stock(stock_code, trading_date)
packet['sector_context'] = sector_ctx

# 4. 新增 factor checks
new_factor_items = []

# 资金流向检查
capital_flow_item = capital_flow_check(stock_code, trading_date, return_pct)
new_factor_items.append(capital_flow_item)

# 板块强度检查
sector_strength_item = sector_strength_check(stock_code, trading_date, sector_ctx)
new_factor_items.append(sector_strength_item)

# 情绪周期检查
sentiment_item = sentiment_cycle_check(sentiment_ctx, return_pct)
new_factor_items.append(sentiment_item)

# 5. 在 LLM review 中增强 prompt
llm_ctx = {
    'market_overview': market_ctx,
    'sentiment_cycle': sentiment_ctx,
    'sector_analysis': sector_ctx,
}
# 要求 LLM 生成:
# - psychological_attribution (E1-E4)
# - next_day_scenarios (E5-E6)
```

---

## 九、不需要的部分（明确排除）

| 建议 | 排除原因 |
|------|---------|
| 盘中实时封板率 | 系统只做盘后复盘，无盘中快照数据，用日度数据推算近似值即可 |
| 分钟级黄白线分析 | 优先级低，可用大盘/小盘指数相对强弱替代 |
| 雪球/股吧实时爬取 | 合规风险高，用现有新闻提供商管道代理，文章数量 ≈ 讨论热度 |
| PCA 降维提纯 | 简化为加权合成，避免引入 sklearn 依赖 |
