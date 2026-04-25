# 单股复盘前端增强实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 补全 StockReviewPanel 缺失的信息层：因子检查明细、证据溯源（visibility/confidence）、错误归因、优化信号、LLM 归因。

**架构：** 后端 API（`GET /api/reviews/stocks/{code}?date=`）已返回完整数据（factor_items、errors、evidence、optimization_signals），前端只需改造展示层。新增 types、重写 StockReviewPanel、补 CSS。

**技术栈：** React + TypeScript + CSS (neo-brutalism)

---

## 文件结构

- 修改：`web/src/types/index.ts` — 新增 `FactorItem`、`ReviewError`、`ReviewEvidence`、`ReviewDecision` 类型
- 修改：`web/src/sections/StockReviewPanel.tsx` — 重写，展示因子表、证据表、错误列表、优化信号
- 修改：`web/src/styles.css` — 新增样式类

---

### 任务 1：新增类型定义

**文件：**
- 修改：`web/src/types/index.ts`

在 `LLMReview` 后追加：

```typescript
export type FactorItem = {
  factor_type: string;
  verdict: string;
  contribution_score: number;
  error_type: string | null;
  confidence: string;
  evidence_ids: string[];
};

export type ReviewError = {
  error_type: string;
  severity: number;
  confidence: number;
  evidence_ids: string[];
};

export type ReviewEvidence = {
  evidence_id: string;
  source_type: string;
  visibility: string;
  confidence: string;
  payload_json: string;
};

export type ReviewSignal = {
  signal_id: string;
  signal_type: string;
  param_name: string;
  direction: string;
  strength: number;
  status: string;
  reason: string;
};

export type ReviewDecision = {
  review_id: string;
  decision_id: string;
  strategy_gene_id: string;
  stock_code: string;
  verdict: string;
  primary_driver: string;
  return_pct: number;
  relative_return_pct: number;
  summary: string;
  factor_items: FactorItem[];
  errors: ReviewError[];
  evidence: ReviewEvidence[];
  optimization_signals: ReviewSignal[];
  llm_json?: string;
};
```

---

### 任务 2：重写 StockReviewPanel

**文件：**
- 修改：`web/src/sections/StockReviewPanel.tsx`

展示结构（从上到下）：

```
┌─ 股票头 ──────────────────────────────┐
│ 000001.SZ 平安银行                     │
│ 行业: Banking · 盲点: 涨幅榜 #3 · +5.2%│
└───────────────────────────────────────┘

┌─ 决策卡片 ────────────────────────────┐  (每 gene 一个)
│ gene_aggressive_v1 · RIGHT            │
│ return +3.2% · driver technical       │
│                                       │
│ ┌─ 因子检查 ──────────────────────┐   │
│ │ 因子       判决   贡献分  错误   │   │
│ │ technical  RIGHT  +0.32  -     │   │
│ │ fundamental MIXED  -0.05  underweighted_fundamental │   │
│ │ event      NEUTRAL 0      -     │   │
│ │ ...                              │   │
│ └─────────────────────────────────┘   │
│                                       │
│ ┌─ 证据溯源 ──────────────────────┐   │
│ │ 类型         可见性        置信度   │   │
│ │ outcome      POSTCLOSE    ✓ 高   │   │
│ │ candidate_scr PREOPEN      ✓ 高   │   │
│ │ earnings_surp PREOPEN      ◆ 中   │   │
│ └─────────────────────────────────┘   │
│                                       │
│ ┌─ 归因错误 ──────────────────────┐   │
│ │ underweighted_event   severity 0.4 │
│ │ risk_underestimated  severity 0.3 │
│ └─────────────────────────────────┘   │
│                                       │
│ ┌─ 优化信号 ──────────────────────┐   │
│ │ increase_weight event_weight    │   │
│ │ → up  强度 0.08  [接受] [拒绝]  │   │
│ └─────────────────────────────────┘   │
└───────────────────────────────────────┘

┌─ LLM 归因（如果存在） ────────────────┐
│ attribution[].claim                   │
│ confidence: EXTRACTED/INFERRED        │
└───────────────────────────────────────┘

┌─ 依据表（保留原有 facts 展示） ─────┐
│ 财报实际值 / 市场预期 / 预期差 / ... │
└──────────────────────────────────────┘
```

关键交互：
- 每个决策卡片可折叠展开（默认展开第一个）
- 优化信号按钮调用 `POST /api/optimization-signals/{id}/accept|reject`
- 证据行显示 visibility 标签（PREOPEN_VISIBLE=蓝, POSTCLOSE_OBSERVED=绿）和 confidence 徽标

类型断言改用新类型：

```typescript
const decisions = (data.decisions ?? []) as ReviewDecision[];
```

---

### 任务 3：补充 CSS 样式

**文件：**
- 修改：`web/src/styles.css`

在文件末尾追加：

```css
/* === Stock Review Detail === */
.factor-table { width: 100%; border-collapse: collapse; margin: 8px 0; font-size: 13px; }
.factor-table th { text-align: left; color: var(--muted); padding: 4px 8px; border-bottom: 2px solid var(--line); }
.factor-table td { padding: 4px 8px; border-bottom: 1px solid rgba(23,18,15,0.12); }
.factor-table .verdict-badge { font-weight: 700; font-size: 11px; padding: 2px 6px; border: 1px solid var(--line); }
.verdict-RIGHT { background: var(--green); color: #fff; }
.verdict-WRONG { background: var(--red); color: #fff; }
.verdict-MIXED { background: var(--gold); }
.verdict-NEUTRAL { background: #ddd4c0; }
.error-chip { color: var(--red); font-size: 11px; }

.evidence-row { display: grid; grid-template-columns: 1fr 120px 80px; gap: 8px; align-items: center; padding: 5px 0; border-bottom: 1px solid rgba(23,18,15,0.08); font-size: 13px; }
.vis-badge { font-size: 10px; padding: 2px 5px; border: 1px solid var(--line); white-space: nowrap; font-weight: 600; }
.vis-preopen { background: #dbeafe; }
.vis-postclose { background: #dcfce7; }
.conf-badge { font-size: 10px; font-weight: 700; }
.conf-EXTRACTED { color: var(--green); }
.conf-INFERRED { color: var(--gold); }
.conf-AMBIGUOUS { color: var(--red); }

.signal-card { display: grid; gap: 4px; border: 1px solid rgba(23,18,15,0.12); padding: 8px; margin-bottom: 6px; background: #fffdf7; }
.signal-card .signal-actions { display: flex; gap: 6px; margin-top: 4px; }

.llm-attribution { margin-top: 12px; }
.llm-attribution table { width: 100%; border-collapse: collapse; font-size: 13px; }
.llm-attribution th, .llm-attribution td { text-align: left; padding: 4px 8px; border-bottom: 1px solid rgba(23,18,15,0.12); }

.empty-value { color: var(--muted); font-style: italic; font-size: 12px; }
```

---

## 验证

构建验证：
```bash
cd web && npm run build
```
预期：tsc 零错误，vite 构建成功。

手动验证（需要后端运行）：
1. 启动后端：`python src/stock_select/server.py --mode demo`
2. 启动前端：`cd web && npm run dev`
3. 打开复盘页面，搜索股票代码，确认：
   - 因子表显示各因子判决和贡献分
   - 证据行显示 visibility/confidence
   - 错误类型高亮显示
   - 优化信号能接受/拒绝
   - LLM 归因在 llm_json 存在时展示
