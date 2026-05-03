# 数据源合规指南

本文档记录 stock-select 系统使用的所有外部数据源的授权状态、频率限制、合规要求和版权边界。

## 数据源概览

| 数据源 | 类型 | 授权 | 频率限制 | Robots | 版权 |
|--------|------|------|----------|--------|------|
| AKShare | 开源库 | 无 (MIT) | 无硬性限制 | N/A | MIT License |
| BaoStock | 开源库 | 无 (学术免费) | 无硬性限制 | N/A | 学术/非商业免费 |
| CNInfo | 公告索引 | 公开 API | ~10 req/min | False | 公开披露，需署名 |
| SSE | 公告索引 | 公开 API | ~5 req/min | False | 交易所数据，需署名 |
| SZSE | 公告索引 | 公开 API | ~5 req/min | False | 交易所数据，需署名 |
| EastMoney | 新闻 | 公开 API | ~10 req/min | False | 商业使用受限 |
| Sina | 新闻 | 公开 API | ~10 req/min | False | 商业使用受限 |

## 频率限制策略

系统在 `announcement_providers.py` 中默认实现了请求间隔：
- CNInfo ↔ SSE: 0.5s
- SSE ↔ SZSE: 0.5s
- SZSE ↔ EastMoney: 0.5s
- EastMoney ↔ Sina: 0.5s

CLI 命令支持 `--throttle-seconds` 参数自定义间隔。

## Robots.txt 合规

巨潮、上交所、深交所、东方财富和新浪财经的 `robots.txt` 未明确允许自动化爬取。
系统使用这些公开 API 的原则：
1. **仅用于个人研究和学习目的**
2. **不进行商业分发**
3. **不大量并发请求**
4. **存储的数据不对外公开**

## 版权声明

- **交易所公告**：属于公开信息披露，可合理使用，但再分发需要注明来源
- **财经新闻**：版权属原发布方，仅限个人研究用途
- **AKShare/BaoStock**：开源项目，遵循各自的开源协议

## 数据安全

- 所有数据存储在本地 SQLite 数据库
- 不上传任何数据到第三方服务
- LLM 分析仅发送脱敏后的结构化信号，不发送原始公告全文
