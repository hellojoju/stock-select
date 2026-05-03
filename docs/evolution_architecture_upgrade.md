# 选股系统自优化架构升级设计

## 一、现状问题

当前进化系统（`evolution.py`）存在 4 个根本问题：

| 问题 | 现状 | 后果 |
|------|------|------|
| **优化目标偏差** | 调的是评分权重，但评分权重和最终收益率关系极弱 | 参数在变，效果不明显 |
| **归因链条脆弱** | 个股亏损直接归咎于权重不对，忽略系统性风险 | 震荡市把技术权重越调越低 |
| **市场环境不分层** | 一套参数在所有行情下混用 | 进化出"平均还行，具体都不行"的平庸基因 |
| **进化空间太小** | 3 个基因只调权重，因子固定 | 动量无效也解决不了，只能从 0.62 调到 0.58 |

## 二、设计原则

1. **进化的是策略，不是参数** —— 基因的本质应该是一组"选股规则"，不是"权重分配"
2. **按环境分层** —— 牛市策略不等于熊市策略，不能混在一起统计
3. **归因要干净** —— 系统性风险剥离后，再看个股选股能力
4. **工程上渐进** —— 不推翻重写，在现有表结构和调度框架上扩展

## 三、核心设计

### 3.1 基因结构升级

**当前**：基因 = 权重字典

```json
{
  "gene_id": "gene_aggressive_v1",
  "params": {
    "momentum_weight": 0.62,
    "technical_component_weight": 0.42,
    "fundamental_component_weight": 0.12,
    ...
  }
}
```

**升级后**：基因 = 策略规则集

```json
{
  "gene_id": "gene_momentum_breakout_v1",
  "strategy_type": "momentum_breakout",
  "params": {
    "momentum_weight": 0.62,
    "technical_component_weight": 0.42,
    "fundamental_component_weight": 0.12,
    ...
  },
  "market_environments": ["bull", "range_up"],
  "factor_config": {
    "required_factors": ["momentum", "volume_surge", "sector_strength"],
    "excluded_factors": ["mean_reversion"],
    "min_technical_score": 0.3,
    "min_fundamental_score": 0.0
  }
}
```

关键变化：
- `strategy_type`：标记策略类型（动量突破/反转/价值/事件驱动等），进化时可以替换
- `market_environments`：声明该基因适用的市场环境
- `factor_config`：定义该基因需要的因子和门槛，进化时可以引入/淘汰因子

### 3.2 市场环境分层

**新增表**：`market_environment_logs`

```sql
CREATE TABLE market_environment_logs (
  log_id TEXT PRIMARY KEY,
  trading_date TEXT NOT NULL,
  market_environment TEXT NOT NULL,  -- bull / bear / range_up / range_down / range_medium
  trend_type TEXT,
  volatility_level TEXT,
  breadth_up_count INT,
  breadth_down_count INT,
  limit_up_count INT,
  limit_down_count INT
);
```

每天 `classify_market_environment` 时写入。

**进化时按环境分组统计**：

```
gene_momentum_breakout_v1 在 bull 环境下的表现：
  交易数: 15, 胜率: 60%, 平均收益: +2.1%

gene_momentum_breakout_v1 在 bear 环境下的表现：
  交易数: 8, 胜率: 35%, 平均收益: -1.8%
```

只有当基因在**特定环境**下表现好时才晋升，不会被不同环境的表现互相抵消。

### 3.3 归因质量提升

**当前归因逻辑**（有问题）：
```
个股亏了 3% → 技术面得分 0.8 → "技术面判断错" → 降技术权重
```

**升级后归因逻辑**：

```python
# 1. 先算系统性收益（大盘涨跌 + 行业涨跌）
benchmark_return = market_index_return(trading_date)  # 大盘涨跌
sector_beta_return = sector_return_pct * gene.beta   # 行业贡献

# 2. 个股实际收益 - 系统性收益 = alpha（选股能力）
alpha = stock_return - benchmark_return - sector_beta_return

# 3. 只对 alpha 部分做归因
if alpha < -0.02:
    # 是选股真的选差了，不是大盘拖累了
    signal = OptimizationSignal(
        type="decrease_weight",
        param="technical_component_weight",
        confidence=0.7,
        reason=f"negative alpha {alpha:.2%} after removing systematic risk"
    )
```

这样大盘跌 2% 导致个股亏 3% 的情况，alpha 只有 -1%，可能不会触发信号。
但大盘涨 1% 个股还亏 2% 的情况，alpha 是 -3%，会正确触发信号。

### 3.4 基因池扩展

从 3 个基因扩展到 6 个，覆盖不同策略类型：

| 策略类型 | 基因 ID | 核心逻辑 | 适用环境 |
|----------|---------|----------|----------|
| 动量突破 | `gene_momentum_breakout_v1` | 追涨 + 放量 + 板块强势 | bull, range_up |
| 均值回归 | `gene_mean_reversion_v1` | 超跌反弹 + 缩量 + 低波动 | bear, range_down |
| 价值质量 | `gene_quality_value_v1` | 高 ROE + 低 PE + 稳定增长 | 所有环境 |
| 事件驱动 | `gene_event_driven_v1` | 公告利好 + 事件催化 | range_up, bull |
| 均衡多因子 | `gene_balanced_v1` | 技术+基本面均衡 | 所有环境 |
| 防守型 | `gene_defensive_v1` | 低波 + 高流动性 + 稳定分红 | bear |

每个基因有独立的 `strategy_type` 和 `market_environments` 声明。

### 3.5 进化方式升级

**当前**：只能调权重（±5%）

**升级后**：三种进化方式

| 进化类型 | 触发条件 | 动作 |
|----------|----------|------|
| **权重调整** | 某因子方向信号积累 | ±3-5% 权重 |
| **因子引入** | 某因子在 winner 中持续出现但当前基因没用 | 加入该因子，设初始权重 0.1 |
| **策略替换** | 某基因在特定环境下连续 30 笔胜率 < 40% | 标记为"环境不适配"，切换环境声明 |

进化输出不再是"改了一个参数"，而是：
```
进化提案 #42:
  父基因: gene_momentum_breakout_v1
  环境: bull
  变化:
    1. technical_component_weight: 0.42 → 0.45 (+3%)
    2. factor_config.required_factors: 新增 "relative_strength"
    3. factor_config.min_technical_score: 0.3 → 0.35
  预期: 在 bull 环境下 alpha 提升 0.5%
```

## 四、数据库变更

### 4.1 strategy_genes 表扩展

```sql
-- 新增列
ALTER TABLE strategy_genes ADD COLUMN strategy_type TEXT DEFAULT 'generic';
ALTER TABLE strategy_genes ADD COLUMN market_environments_json TEXT DEFAULT '["all"]';
ALTER TABLE strategy_genes ADD COLUMN factor_config_json TEXT DEFAULT '{}';
ALTER TABLE strategy_genes ADD COLUMN beta REAL DEFAULT 1.0;
```

### 4.2 新增表

```sql
-- 市场环境日志
CREATE TABLE market_environment_logs (
  log_id TEXT PRIMARY KEY,
  trading_date TEXT NOT NULL UNIQUE,
  market_environment TEXT NOT NULL,
  trend_type TEXT,
  volatility_level TEXT,
  breadth_up_count INT,
  breadth_down_count INT,
  limit_up_count INT,
  limit_down_count INT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 基因表现按环境分组统计
CREATE TABLE gene_environment_performance (
  gene_id TEXT NOT NULL,
  market_environment TEXT NOT NULL,
  period_start TEXT NOT NULL,
  period_end TEXT NOT NULL,
  trade_count INT,
  win_rate REAL,
  avg_return REAL,
  max_drawdown REAL,
  alpha REAL,  -- 扣除系统性风险后的超额收益
  PRIMARY KEY (gene_id, market_environment, period_start)
);

-- 进化提案（带环境标签）
ALTER TABLE evolution_proposals ADD COLUMN market_environment TEXT;
ALTER TABLE evolution_proposals ADD COLUMN alpha_change REAL;
```

### 4.3 outcomes 表扩展

```sql
-- 新增 alpha 字段
ALTER TABLE outcomes ADD COLUMN benchmark_return REAL;
ALTER TABLE outcomes ADD COLUMN sector_return REAL;
ALTER TABLE outcomes ADD COLUMN alpha REAL;
```

## 五、模块变更

### 5.1 classify_market_environment（data_ingestion.py）

扩展：写入 `market_environment_logs` 表，同时计算涨跌家数、涨停家数等广度指标。

### 5.2 build_candidate（candidate_pipeline.py）

扩展：读取基因的 `factor_config`，过滤不符合因子的候选股。

```python
# 新增逻辑
factor_config = gene["factor_config"]
if factor_config.get("min_technical_score", 0) > 0:
    if technical["score"] < factor_config["min_technical_score"]:
        return None  # 不满足技术面门槛，跳过
```

### 5.3 simulate_day（simulator.py）

扩展：写入 `benchmark_return` 和 `sector_return` 到 outcomes。

```python
# 获取当日大盘收益
index_row = conn.execute(
    "SELECT return_pct FROM index_prices WHERE trading_date = ? AND index_code = '000300.SH'",
    (trading_date,)
).fetchone()
benchmark = index_row["return_pct"] if index_row else 0.0

# 获取当日行业收益
sector_row = conn.execute(
    "SELECT sector_return_pct FROM sector_theme_signals WHERE trading_date = ? AND industry = ?",
    (trading_date, industry)
).fetchone()
sector = sector_row["sector_return_pct"] if sector_row else 0.0

alpha = return_pct - benchmark - sector * 0.5  # 行业 beta 假设 0.5
```

### 5.4 deterministic_review（deterministic_review.py）

扩展：归因时用 alpha 代替 raw return。

### 5.5 evolution.py（核心改动）

扩展：
- `evolve_weekly()` 按市场环境分组聚合信号
- 新增 `propose_factor_introduction()` 检查是否需要引入新因子
- 新增 `check_environment_mismatch()` 检测基因与环境不适配
- 进化提案增加 alpha 预期

### 5.6 scheduler.py

扩展：新增周六 11:00 的 `reconcile_environment_performance` 任务，每周更新各基因在各环境下的表现统计。

## 六、实施阶段

### Phase 1：基础设施（不动现有逻辑）
- [ ] 新增表：`market_environment_logs`, `gene_environment_performance`
- [ ] 扩展现有表：`strategy_genes`, `outcomes`
- [ ] `classify_market_environment` 写入 market_environment_logs

### Phase 2：归因质量
- [ ] `simulate_day` 计算并写入 benchmark_return / sector_return / alpha
- [ ] `deterministic_review` 改用 alpha 做归因

### Phase 3：基因池扩展
- [ ] 定义 6 个基因（含 strategy_type, market_environments, factor_config）
- [ ] `candidate_pipeline.py` 支持 factor_config 过滤

### Phase 4：进化升级
- [ ] `evolution.py` 按环境分组统计
- [ ] 新增因子引入进化方式
- [ ] 新增环境不适配检测

### Phase 5：调度完善
- [ ] scheduler 添加环境表现 reconciler
- [ ] 前端展示基因按环境的表现

## 七、风险和回退

| 风险 | 应对 |
|------|------|
| 新基因表现更差 | 保留现有 3 个基因不动，新增 3 个作为 challenger |
| 市场环境分类不准 | 先用现有 `market_environment` 字段，后续可调整分类标准 |
| alpha 计算依赖指数数据 | 如果 index_prices 缺失，alpha 退化为 raw return |
| 进化逻辑变更引入 bug | 用 feature flag 控制，`EVOLUTION_V2=1` 才启用新逻辑 |

## 八、验收标准

1. **归因正确性**：大盘跌 2% 个股亏 3% 不触发强信号，alpha ≈ -1%
2. **环境分层生效**：同一基因在 bull 和 bear 环境下有独立的 performance 记录
3. **进化有效性**：进化后子基因在目标环境下的 alpha 比父基因高
4. **向后兼容**：现有 3 个基因无需修改即可在新系统下运行（默认 environment: all）
