# 智能选股平台

自进化 A 股选股研究系统。基于 LLM 分析市场数据、构建策略，持续迭代优化选股模型。

## 架构

```
├── src/            # Python 后端（选股引擎）
├── web/            # React 前端（Vite + TypeScript）
├── var/            # 数据存储
└── .env.example    # 环境配置模板
```

## 快速开始

### 安装

```bash
uv sync
cd web && npm install && cd ..
```

### 后端

```bash
# Demo 模式（无需 API Key）
uv run stock-select serve --mode demo --port 18425

# Live 模式
cp .env.example .env  # 编辑 .env 填入 API Key
uv run stock-select serve --mode live
```

后端服务地址：http://localhost:18425

### 前端

```bash
cd web
npm run dev
```

前端地址：http://localhost:5173

## CLI 命令

| 命令 | 说明 |
|------|------|
| `uv run stock-select serve --mode demo` | 启动 Web 服务（含定时调度器） |
| `uv run stock-select serve --mode live` | 生产模式启动 |
| `uv run stock-select pipeline --date YYYY-MM-DD` | 执行一次完整日线流水线 |
| `uv run stock-select run-daily --date YYYY-MM-DD` | 生成选股 + 模拟成交（不同步数据） |
| `uv run stock-select run-phase <phase> --date YYYY-MM-DD` | 执行指定阶段 |
| `uv run stock-select init-db` | 初始化数据库 |
| `uv run stock-select seed-demo` | 灌入 demo 数据 |
| `uv run stock-select performance` | 查看策略表现 |
| `uv run stock-select memory-search --q <关键词>` | 搜索 FTS5 记忆 |

常用 `--mode` 值：`demo`（演示）/ `live`（生产）

## 功能

- LLM 驱动的股票研究与选股
- 多模型策略构建与回测
- 智能选股面板
- 策略持续迭代优化（基因进化）
- 实时监控与可视化
- 自动化每日交易工作流

## 技术栈

- **后端**：Python 3.11+，uv，stdlib HTTPServer（有 uvicorn 时自动切换 FastAPI），APScheduler，SQLite（WAL + FTS5）
- **前端**：React，Vite，TypeScript
- **数据源**：AKShare，BaoStock（支持 Demo 模式）
- **LLM**：Anthropic Claude / DeepSeek

## 测试

```bash
pytest tests/ -q
```

450+ 测试全部通过，覆盖集成测试、单元测试、E2E 测试。

## 环境变量

| 变量 | 说明 |
|------|------|
| `ANTHROPIC_API_KEY` | Claude API Key（LLM 复盘用） |
| `LLM_PROVIDER` | LLM 提供商（`deepseek` / `anthropic` 等） |
| `DEEPSEEK_API_KEY` | DeepSeek API Key |
| `DEEPSEEK_BASE_URL` | DeepSeek API 地址（可选） |
| `MODE` | 运行模式（`demo` / `live`） |

## License

MIT
