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

### 后端

```bash
# 配置环境变量
cp .env.example .env
# 编辑 .env 填入 API Key

# 启动
.venv/bin/python -m src.stock_select.server
```

### 前端

```bash
cd web
npm install
npm run dev
```

打开 http://localhost:19283 访问平台界面。

## 功能

- LLM 驱动的股票研究与选股
- 多模型策略构建与回测
- 智能选股面板
- 策略持续迭代优化
- 实时监控与可视化

## 技术栈

- **后端**：Python 3.11+，uv，Anthropic/OpenAI API
- **前端**：React，Vite，TypeScript
- **数据存储**：SQLite

## 环境变量

| 变量 | 说明 |
|------|------|
| `LLM_PROVIDER` | LLM 提供商（如 `deepseek`） |
| `DEEPSEEK_API_KEY` | DeepSeek API Key |
| `DEEPSEEK_BASE_URL` | API 地址（可选） |

## License

MIT
