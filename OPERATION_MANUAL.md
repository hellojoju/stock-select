# 自我进化 A 股选股系统 — 操作手册

> 本文档面向日常运行、排障、回滚和数据维护。

## 快速开始

```bash
# 1. 初始化数据库（首次运行）
.venv/bin/python -m stock_select.cli init-db

# 2. 运行完整日线流程（demo 模式）
.venv/bin/python -m stock_select.cli --mode demo pipeline --date 2024-04-22

# 3. 启动 API 服务
.venv/bin/python -m stock_select.cli serve

# 4. 前端开发
cd web && npm run dev
```

## 日常运行

### 手动运行单日流程

```bash
.venv/bin/python -m stock_select.cli --mode demo run-daily --date 2024-04-22
```

### 按阶段运行

```bash
.venv/bin/python -m stock_select.cli --mode demo run-phase sync_data --date 2024-04-22
.venv/bin/python -m stock_select.cli --mode demo run-phase sync_factors --date 2024-04-22
.venv/bin/python -m stock_select.cli --mode demo run-phase process_announcements --date 2024-04-22
.venv/bin/python -m stock_select.cli --mode demo run-phase preopen_pick --date 2024-04-22
.venv/bin/python -m stock_select.cli --mode demo run-phase simulate --date 2024-04-22
.venv/bin/python -m stock_select.cli --mode demo run-phase deterministic_review --date 2024-04-22
.venv/bin/python -m stock_select.cli --mode demo run-phase blindspot_review --date 2024-04-22
.venv/bin/python -m stock_select.cli --mode demo run-phase gene_review --date 2024-04-22
.venv/bin/python -m stock_select.cli --mode demo run-phase system_review --date 2024-04-22
```

### 定时调度

系统支持 APScheduler 定时运行（需安装 `apscheduler`）：

```bash
# 启动调度器
.venv/bin/python -m stock_select.cli serve  # 调度器随 API 服务自动启动

# 或通过 API 控制
curl -X POST http://127.0.0.1:18425/api/scheduler/start
curl -X POST http://127.0.0.1:18425/api/scheduler/stop
curl http://127.0.0.1:18425/api/scheduler/status
```

调度时间表（北京时间）：

| 时间 | 阶段 |
|------|------|
| 周一~周五 08:00 | 数据同步 |
| 周一~周五 08:10 | 预盘选股 |
| 周一~周五 09:25 | 模拟开盘 |
| 周一~周五 15:05 | 收盘数据同步 |
| 周一~周五 15:15 | 确定性复盘 |
| 周一~周五 15:30 | LLM 复盘 |
| 周六 10:00 | 策略进化 |

### Smoke 测试

一键验收完整流程：

```bash
.venv/bin/python scripts/smoke_test.py --date 2024-04-22
```

## 复盘

### 单股复盘

访问前端复盘中心，选择日期和股票即可查看：
- 推荐原因（盘前证据）
- 收盘验证结果
- 错误归因（可优化 / 数据缺失 / 事后事件）
- 优化信号

### LLM 复盘

```bash
.venv/bin/python -m stock_select.cli --mode demo run-phase llm_review --date 2024-04-22
```

需要配置 `DEEPSEEK_API_KEY` 环境变量。

## 策略进化

### 查看当前基因

```bash
# 通过 API
curl http://127.0.0.1:18425/api/genes

# 通过前端
访问策略进化页面
```

### 提出进化候选

```bash
.venv/bin/python -m stock_select.cli propose-evolution --period 2024-04-01,2024-04-30
```

### 推广 Challenger

```bash
.venv/bin/python -m stock_select.cli promote-challenger --challenger-id <gene_id>
```

### 回滚

```bash
.venv/bin/python -m stock_select.cli rollback-evolution --challenger-id <gene_id>
```

## 知识库

### 同步新闻

```bash
.venv/bin/python -m stock_select.cli sync-news --date 2024-04-22
```

### 处理 PDF 公告

```bash
.venv/bin/python -m stock_select.cli process-pdfs --date 2024-04-22
```

### 查询文档

```bash
# 全量查询
curl http://127.0.0.1:18425/api/documents

# 按股票
curl http://127.0.0.1:18425/api/documents?stock_code=000001

# 按关键词
curl http://127.0.0.1:18425/api/documents?keyword=业绩
```

## 图谱

### 同步图谱

```bash
.venv/bin/python -m stock_select.cli sync-graph --date 2024-04-22
```

### 查询邻域

```bash
curl http://127.0.0.1:18425/api/graph/stocks/000001/neighborhood?date=2024-04-22
```

### 导出 Graphify

```bash
.venv/bin/python -m stock_select.cli export-graphify
# 输出: graphify-out/graph.json
```

## 排障

### 数据源失败

1. 检查数据源健康：
```bash
curl http://127.0.0.1:18425/api/monitor/health
```

2. 查看缺失日期：
```bash
curl http://127.0.0.1:18425/api/monitor/missing-dates?days=5
```

3. 查看阶段运行状态：
```bash
curl http://127.0.0.1:18425/api/runs?limit=20
```

### 模拟盘异常

- 检查涨跌停判断：确认 `daily_prices` 表有 `prev_close` 字段
- 检查未成交原因：查询 `sim_orders` 表的 `reject_reason` 字段
- 手动重跑：`.venv/bin/python -m stock_select.cli --mode demo run-phase simulate --date <date>`

### LLM 复盘失败

- 确认 `DEEPSEEK_API_KEY` 已设置
- 检查网络连通性：`curl https://api.deepseek.com/v1/chat/completions`
- LLM 失败不影响确定性复盘结果

### 数据库修复

```bash
# 重置数据库（会丢失所有数据）
rm var/stock_select.db
.venv/bin/python -m stock_select.cli init-db
.venv/bin/python -m stock_select.cli seed-demo
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥（LLM 复盘必需） |
| `AKSHARE_ENABLED` | 是否启用 AKShare 数据源 |
| `BAOSTOCK_ENABLED` | 是否启用 BaoStock 数据源 |
| `STOCK_SELECT_DEBUG` | 开启调试日志 |

## 测试

```bash
# 单元测试
.venv/bin/python -m pytest -q

# 编译检查
.venv/bin/python -m compileall -q src

# 前端构建
cd web && npm run build

# Smoke 测试
.venv/bin/python scripts/smoke_test.py --date 2024-04-22
```
