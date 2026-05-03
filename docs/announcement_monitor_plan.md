# 实施计划：公告猎手 (Announcement Hunter)

## 概览

将 stock-select 系统从"被动复盘"升级为"主动狩猎"。基于已有的 5 个公告源（巨潮、上交所、深交所、东财、新浪）和事件解析基础设施，新增实时公告轮询引擎、短线情绪评分、WebSocket 报警推送和前端监控面板，实现分钟级公告监控与智能机会识别。

## 现有基础设施（可直接复用）

| 模块 | 文件 | 可复用内容 |
|------|------|------------|
| 公告源 | `src/stock_select/announcement_providers.py` | 5 个 provider 函数 + `sync_announcements` orchestrator |
| 事件解析 | `src/stock_select/announcement_events.py` | OrderContract/BusinessKPI/RiskEvent 提取 |
| 资金流向 | `src/stock_select/capital_flow.py` | `build_capital_flow_report` |
| 候选管线 | `src/stock_select/candidate_pipeline.py` | `build_candidate`, `event_signal`, `risk_signal` |
| 调度 | `src/stock_select/scheduler.py` | APScheduler BackgroundScheduler 模式 |
| 数据库 | `src/stock_select/db.py` | `event_signals`, `news_items`, `capital_flow_daily` 表 |
| 情绪周期 | `src/stock_select/sentiment_cycle.py` | `SentimentCycle` dataclass, `get_sentiment_cycle` |
| API | `src/stock_select/api.py` | FastAPI app 创建模式、路由约定 |
| 前端 | `web/src/` | DashboardPage.tsx 组件风格、API 调用模式 |

## 架构变更

### 新建文件

| 文件 | 描述 |
|------|------|
| `src/stock_select/announcement_monitor.py` | 实时公告轮询引擎（增量去重、利好过滤） |
| `src/stock_select/sentiment_scoring.py` | 短线情绪评分（连板/封板强度/板块联动/资金热度） |
| `src/stock_select/alert_service.py` | WebSocket 报警推送服务 + in-memory broadcast manager |
| `web/src/pages/AnnouncementMonitorPage.tsx` | 公告监控面板页 |
| `web/src/components/AlertPanel.tsx` | 实时报警推送组件 |

### 修改文件

| 文件 | 描述 |
|------|------|
| `src/stock_select/db.py` | 新增 3 张表：`announcement_alerts`, `monitor_runs`, `sector_heat_index` |
| `src/stock_select/api.py` | 新增 REST 路由 + WebSocket endpoint |
| `src/stock_select/scheduler.py` | 新增盘中分钟级轮询 job |
| `src/stock_select/server.py` | 引入公告猎手模块 |
| `web/src/App.tsx` | 新增导航入口 |
| `web/src/types/index.ts` | 新增类型定义 |

## 数据库 Schema 变更

在 `db.py` 的 `init_db()` 中新增 3 张表：

```sql
-- 公告报警记录（核心输出）
CREATE TABLE IF NOT EXISTS announcement_alerts (
  alert_id TEXT PRIMARY KEY,
  trading_date TEXT NOT NULL,
  discovered_at TEXT NOT NULL,
  stock_code TEXT NOT NULL REFERENCES stocks(stock_code),
  stock_name TEXT,
  industry TEXT,
  source TEXT NOT NULL,
  alert_type TEXT NOT NULL,
  title TEXT NOT NULL,
  summary TEXT,
  source_url TEXT,
  event_ids_json TEXT,
  sentiment_score REAL NOT NULL,
  capital_flow_score REAL,
  sector_heat_score REAL,
  chip_structure_score REAL,
  shareholder_trend_score REAL,
  confidence REAL NOT NULL DEFAULT 0.5,
  status TEXT NOT NULL DEFAULT 'new',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(stock_code, title, source)
);

-- 轮询运行记录（审计用）
CREATE TABLE IF NOT EXISTS monitor_runs (
  run_id TEXT PRIMARY KEY,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  source TEXT,
  documents_fetched INTEGER NOT NULL DEFAULT 0,
  new_documents INTEGER NOT NULL DEFAULT 0,
  alerts_generated INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  status TEXT NOT NULL DEFAULT 'running'
);

-- 板块热度指数（缓存）
CREATE TABLE IF NOT EXISTS sector_heat_index (
  trading_date TEXT NOT NULL,
  industry TEXT NOT NULL,
  heat_score REAL NOT NULL,
  stock_count INTEGER NOT NULL,
  limit_up_count INTEGER NOT NULL,
  total_flow REAL,
  announcement_count INTEGER NOT NULL,
  composite_return_pct REAL,
  computed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (trading_date, industry)
);
```

## Sprint 1：数据管道层（公告轮询引擎）

**目标**：基于已有 5 个公告源，构建分钟级增量轮询引擎，将利好公告存入 `announcement_alerts` 表。

**预计工时**：1-2 天

### 1.1 数据库 Schema 迁移
- **文件**：`src/stock_select/db.py`
- 在 `init_db()` 中添加上述 3 张表的 DDL
- **验收**：`CREATE TABLE IF NOT EXISTS` 幂等安全

### 1.2 公告利好分类器
- **文件**：`src/stock_select/announcement_monitor.py`
- `_classify_alert_type(title: str, text: str | None) -> str | None`
- 识别利好类型：`earnings_beat`, `large_order`, `tech_breakthrough`, `asset_injection`, `m_and_a`
- 非利好返回 None（过滤掉日常公告、风险提示）

### 1.3 公告轮询引擎核心
- **文件**：`src/stock_select/announcement_monitor.py`
- `run_announcement_scan(conn, stock_codes: list[str] | None = None) -> list[AnnouncementAlert]`
- 调用 `announcement_providers.sync_announcements` 获取最新公告
- 增量去重：对比 `raw_documents` 表已有记录
- 对新增公告调用 `_classify_alert_type` 过滤
- 命中利好的，调用 `announcement_events.process_announcement_text` 提取结构化事件
- 结果写入 `announcement_alerts` 表，记录运行日志到 `monitor_runs` 表

### 1.4 单元测试
- **文件**：`tests/test_announcement_monitor.py`
- 测试 `_classify_alert_type` 分类准确性
- 测试 `run_announcement_scan` 增量去重逻辑

### 1.5 调度集成
- **文件**：`src/stock_select/scheduler.py`
- 盘中 9:15-11:30 / 13:00-15:00 每 5 分钟轮询一次

### Sprint 1 验收标准
- [ ] 5 个公告源均可正常获取
- [ ] 增量去重有效
- [ ] 利好分类准确率 > 85%
- [ ] `announcement_alerts` 表写入正确
- [ ] `monitor_runs` 审计记录完整
- [ ] 定时调度在盘中正常触发

---

## Sprint 2：情绪评分层

**目标**：为每条报警计算短线情绪评分，综合行业热度、资金流向、筹码结构、股东户数等维度。

**预计工时**：2-3 天

### 2.1 板块热度指数计算
- **文件**：`src/stock_select/sentiment_scoring.py`
- `compute_sector_heat(conn, trading_date, industry) -> float`
- 查询 `sector_theme_signals` 表 + 板块涨停数 + 资金净流入 + 板块涨跌幅

### 2.2 资金流向子评分
- **文件**：`src/stock_select/sentiment_scoring.py`
- `compute_capital_flow_score(conn, stock_code, trading_date) -> float`
- 复用 `capital_flow.build_capital_flow_report`

### 2.3 筹码结构评分
- **文件**：`src/stock_select/sentiment_scoring.py`
- `compute_chip_structure_score(conn, stock_code, trading_date) -> float`
- 换手率、成交量变化、价格位置、均线密集度

### 2.4 股东户数趋势评分
- **文件**：`src/stock_select/sentiment_scoring.py`
- `compute_shareholder_trend_score(conn, stock_code, trading_date) -> float`
- 股东户数连续减少、人均持股增加

### 2.5 综合情绪评分器
- **文件**：`src/stock_select/sentiment_scoring.py`
- `score_announcement_sentiment(conn, alert_data) -> SentimentScore`
- 综合公式：`capital_flow * 0.30 + sector_heat * 0.30 + chip_structure * 0.20 + shareholder_trend * 0.20`

### 2.6 板块热度缓存写入
- **文件**：`src/stock_select/sentiment_scoring.py`
- `refresh_sector_heat_index(conn, trading_date) -> None`

### 2.7 集成到报警管线
- **文件**：`src/stock_select/announcement_monitor.py`
- 修改 `run_announcement_scan`，写入前调用 `score_announcement_sentiment`

### 2.8 单元测试
- **文件**：`tests/test_sentiment_scoring.py`

### Sprint 2 验收标准
- [ ] 4 个子评分函数独立可测
- [ ] 综合评分范围 0-1，分布合理
- [ ] 板块热度缓存正确写入
- [ ] 报警记录包含完整评分数据
- [ ] 测试覆盖率 > 80%

---

## Sprint 3：WebSocket 报警 + API 层

**目标**：实现 WebSocket 实时推送和 REST API。

**预计工时**：2-3 天

### 3.1 WebSocket Broadcast Manager
- **文件**：`src/stock_select/alert_service.py`
- `BroadcastManager` 类，管理 WebSocket 连接池、过滤订阅、线程安全 broadcast

### 3.2 WebSocket Endpoint
- **文件**：`src/stock_select/api.py`
- `/ws/alerts` WebSocket endpoint

### 3.3 REST API 路由
- **文件**：`src/stock_select/api.py`

```
GET /api/announcements/alerts?date=&status=&alert_type=&stock_code=&limit=50
GET /api/announcements/alerts/{alert_id}
POST /api/announcements/alerts/{alert_id}/acknowledge
POST /api/announcements/alerts/{alert_id}/dismiss
GET /api/announcements/monitor-runs?limit=20
GET /api/announcements/sector-heat?date=
GET /api/announcements/live-stats
```

### 3.4 全局 BroadcastManager 实例
- **文件**：`src/stock_select/api.py`
- 在 `create_app()` 中创建全局实例

### 3.5 报警触发推送
- **文件**：`src/stock_select/announcement_monitor.py`
- 新报警生成后调用 `broadcast_manager.broadcast`，评分 >= 0.6 时推送

### Sprint 3 验收标准
- [ ] WebSocket 连接/推送/断开均正常
- [ ] 所有 REST API 端点返回正确数据
- [ ] 报警确认/忽略持久化
- [ ] 板块热度排行接口可用
- [ ] 广播过滤正确工作

---

## Sprint 4：前端集成

**目标**：新增公告监控页面和实时报警组件。

**预计工时**：2-3 天

### 4.1 类型定义
- **文件**：`web/src/types/index.ts`
- `AnnouncementAlert`, `SectorHeatItem`, `MonitorRun` 类型

### 4.2 公告监控面板页
- **文件**：`web/src/pages/AnnouncementMonitorPage.tsx`
- 实时统计条（今日报警数、最高评分、热门板块）
- 板块热度排行列表
- 报警列表（按 sentiment_score 降序，颜色分级）
- 轮询运行记录
- 报警详情展开 + 确认/忽略操作

### 4.3 实时报警推送组件
- **文件**：`web/src/components/AlertPanel.tsx`
- WebSocket 连接 `/ws/alerts`
- Toast 通知 + 铃铛图标 + 未读计数
- 新报警闪烁动画（3 秒）

### 4.4 导航入口
- **文件**：`web/src/App.tsx`
- 路由 `/announcements`，使用 lucide `Bell` 或 `Target` 图标

### 4.5 Dashboard 集成
- **文件**：`web/src/pages/DashboardPage.tsx`
- 增加"今日公告报警数"小卡片，点击跳转

### Sprint 4 验收标准
- [ ] 监控面板页面完整可用
- [ ] 板块热度排行可视化清晰
- [ ] 报警列表支持筛选、排序、确认/忽略
- [ ] WebSocket 实推送正常
- [ ] Toast 通知和闪烁效果正常
- [ ] 导航入口可点击跳转
- [ ] Dashboard 集成卡片显示正确

---

## 任务依赖关系

```
Sprint 1:
  1.1 Schema -> 1.2 分类器 -> 1.3 轮询引擎 -> 1.4 测试
                                              -> 1.5 调度

Sprint 2:
  2.1 板块热度
  2.2 资金流向  } -> 2.5 综合评分 -> 2.7 集成 -> 2.8 测试
  2.3 筹码结构  }               -> 2.6 缓存
  2.4 股东趋势  }

Sprint 3:
  3.1 BroadcastManager -> 3.2 WebSocket
                        -> 3.4 全局实例 -> 3.5 推送触发
  3.3 REST API (依赖 Sprint 1,2 数据产出)

Sprint 4:
  4.1 类型 -> 4.2 面板页 -> 4.4 导航
  4.3 报警组件 (依赖 3.2)   -> 4.5 Dashboard (依赖 3.3)
```

## 风险点与应对

| 风险 | 严重程度 | 应对策略 |
|------|----------|----------|
| 公告源 API 频繁变更或限流 | 高 | 重试+退避、请求间隔、错误降级 |
| SQLite 并发写入冲突 | 中 | WAL 模式（已启用）、busy_timeout 5s、监控 job 不重叠 |
| WebSocket 连接数过多 | 低 | 最大连接数限制、心跳保活、超时断开 |
| 利好分类误判 | 中 | 可调置信度阈值、人工确认反馈循环 |
| 评分权重主观性强 | 中 | 权重参数化，后续回测优化 |
| 全量轮询耗时过长 | 中 | 单源超时 15s、增量时间窗口 |
| server.py 使用 stdlib http.server，api.py 使用 FastAPI | 中 | 需确认实际使用路径，WebSocket 只能在 FastAPI 路径下 |

## 技术决策

**WebSocket 方案**：直接使用 FastAPI 内置 WebSocket 支持（`fastapi.WebSocket`），项目已使用 FastAPI，无需额外依赖。

**调度方案**：APScheduler `cron` 触发器，9:15-11:30 和 13:00-15:00 每 5 分钟执行。

**评分权重（初始值，可调整）**：
```
composite_score = capital_flow * 0.30 + sector_heat * 0.30 + chip_structure * 0.20 + shareholder_trend * 0.20
```
