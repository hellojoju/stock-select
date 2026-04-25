import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Activity, AlertTriangle, BrainCircuit, Database, GitBranch, Play, Search, ShieldCheck } from 'lucide-react';
import './styles.css';

type Pick = {
  decision_id: string;
  stock_code: string;
  stock_name?: string;
  strategy_gene_id: string;
  horizon: string;
  confidence: number;
  position_pct: number;
  score: number;
  return_pct?: number | null;
  hit_sell_rule?: string | null;
};

type Dashboard = {
  date: string | null;
  runtime_mode?: string;
  database_role?: string;
  is_demo_data?: boolean;
  market_environment?: string | null;
  picks: Pick[];
  performance: Array<Record<string, number | string>>;
  runs: Array<Record<string, string>>;
  data_quality: Array<Record<string, string | number | null>>;
  data_status?: Array<Record<string, string | number | null>>;
  data_quality_summary?: Record<string, unknown>;
  candidate_scores: Array<Record<string, string | number>>;
  review_summary?: Record<string, unknown>;
};

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000';

function App() {
  const [date, setDate] = useState('');
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [memoryQuery, setMemoryQuery] = useState('收益');
  const [memory, setMemory] = useState<Array<Record<string, unknown>>>([]);
  const [stockReview, setStockReview] = useState<Record<string, unknown> | null>(null);
  const [strategyReviews, setStrategyReviews] = useState<Array<Record<string, unknown>>>([]);
  const [strategyReview, setStrategyReview] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);

  async function loadDashboard(targetDate = date) {
    setLoading(true);
    const suffix = targetDate ? `?date=${targetDate}` : '';
    const response = await fetch(`${API_BASE}/api/dashboard${suffix}`);
    const json = await response.json();
    setDashboard(json);
    if (!date && json.date) setDate(json.date);
    if (json.date) void loadStrategyReviews(json.date);
    setLoading(false);
  }

  async function trigger(phase: string) {
    if (!date) return;
    setLoading(true);
    await fetch(`${API_BASE}/api/runs/${phase}?date=${date}`, { method: 'POST' });
    await loadDashboard(date);
  }

  async function searchMemory() {
    const response = await fetch(`${API_BASE}/api/memory/search?q=${encodeURIComponent(memoryQuery)}`);
    setMemory(await response.json());
  }

  async function loadStockReview(stockCode: string, targetDate = date) {
    if (!targetDate) return;
    const response = await fetch(`${API_BASE}/api/reviews/stocks/${stockCode}?date=${targetDate}`);
    setStockReview(await response.json());
  }

  async function loadStrategyReviews(targetDate = date) {
    if (!targetDate) return;
    const response = await fetch(`${API_BASE}/api/reviews/preopen-strategies?date=${targetDate}`);
    setStrategyReviews(await response.json());
  }

  async function loadStrategyReview(geneId: string, targetDate = date) {
    if (!targetDate) return;
    const response = await fetch(`${API_BASE}/api/reviews/preopen-strategies/${geneId}?date=${targetDate}`);
    setStrategyReview(await response.json());
  }

  useEffect(() => {
    void loadDashboard('');
  }, []);

  const best = useMemo(() => dashboard?.performance?.[0], [dashboard]);

  return (
    <main className="shell">
      <section className="rail">
        <div className="brand">
          <span className="brand-mark">SS</span>
          <div>
            <strong>Stock Select</strong>
            <small>自我进化选股系统</small>
          </div>
        </div>
        <nav>
          <a><Activity size={18} /> 今日工作台</a>
          <a><BrainCircuit size={18} /> 策略基因</a>
          <a><Database size={18} /> 数据质量</a>
          <a><GitBranch size={18} /> 记忆图谱</a>
        </nav>
      </section>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">Asia/Shanghai · 模拟盘</p>
            <div className="title-line">
              <h1>{dashboard?.date ?? '等待数据'}</h1>
              <span className={`mode-badge ${dashboard?.runtime_mode === 'live' ? 'live' : 'demo'}`}>
                {String(dashboard?.runtime_mode ?? 'demo').toUpperCase()}
              </span>
            </div>
          </div>
          <div className="actions">
            <input value={date} onChange={(event) => setDate(event.target.value)} placeholder="YYYY-MM-DD" />
            <button onClick={() => loadDashboard(date)} disabled={loading}><Search size={16} /> 查询</button>
            <button onClick={() => trigger('preopen_pick')} disabled={!date || loading}><Play size={16} /> 选股</button>
            <button onClick={() => trigger('simulate')} disabled={!date || loading}><ShieldCheck size={16} /> 模拟</button>
          </div>
        </header>

        <section className="metrics">
          <Metric label="推荐数" value={dashboard?.picks?.length ?? 0} />
          <Metric label="最佳基因" value={String(best?.strategy_gene_id ?? '-')} />
          <Metric label="市场环境" value={String(dashboard?.market_environment ?? '-')} />
          <Metric label="数据覆盖" value={formatPct(Number((dashboard?.data_quality_summary as Record<string, unknown> | undefined)?.coverage_pct))} />
        </section>

        <section className="content-grid">
          <Panel title="复盘摘要" icon={<ShieldCheck size={18} />}>
            <div className="review-summary">
              <Metric label="单笔复盘" value={Number(dashboard?.review_summary?.decision_reviews ?? 0)} />
              <Metric label="盲点复盘" value={Number(dashboard?.review_summary?.blindspot_reviews ?? 0)} />
              <Metric label="开放信号" value={Number(dashboard?.review_summary?.open_optimization_signals ?? 0)} />
            </div>
            <p className="memory">{String(dashboard?.review_summary?.system_summary ?? '暂无系统复盘')}</p>
          </Panel>

          <Panel title="今日推荐" icon={<Activity size={18} />}>
            <div className="table">
              <div className="thead">
                <span>股票</span><span>基因</span><span>仓位</span><span>置信度</span><span>收益</span>
              </div>
              {(dashboard?.picks ?? []).map((pick) => (
                <button className="row row-button" key={pick.decision_id} onClick={() => loadStockReview(pick.stock_code)}>
                  <span><b>{pick.stock_code}</b><small>{pick.stock_name ?? ''}</small></span>
                  <span>{pick.strategy_gene_id.replace('gene_', '')}</span>
                  <span>{formatPct(pick.position_pct)}</span>
                  <span>{formatPct(pick.confidence)}</span>
                  <span className={Number(pick.return_pct ?? 0) >= 0 ? 'up' : 'down'}>{formatPct(pick.return_pct ?? undefined)}</span>
                </button>
              ))}
            </div>
          </Panel>

          <Panel title="策略表现" icon={<BrainCircuit size={18} />}>
            <div className="stack">
              {(dashboard?.performance ?? []).map((item) => (
                <button className="gene gene-button" key={String(item.strategy_gene_id)} onClick={() => loadStrategyReview(String(item.strategy_gene_id))}>
                  <strong>{String(item.strategy_gene_id)}</strong>
                  <span>{Number(item.trades)} 笔 · 胜率 {formatPct(Number(item.win_rate))}</span>
                  <meter min="0" max="1" value={Math.max(0, Number(item.win_rate ?? 0))} />
                </button>
              ))}
            </div>
          </Panel>

          <Panel title="单股复盘" icon={<Search size={18} />}>
            <StockReviewView data={stockReview} />
          </Panel>

          <Panel title="早盘策略复盘" icon={<BrainCircuit size={18} />}>
            <StrategyReviewView data={strategyReview} list={strategyReviews} onSelect={(geneId) => loadStrategyReview(geneId)} />
          </Panel>

          <Panel title="多维候选评分" icon={<GitBranch size={18} />}>
            <div className="score-list">
              {(dashboard?.candidate_scores ?? []).slice(0, 6).map((item, index) => (
                <div className="score-card" key={`${item.strategy_gene_id}-${item.stock_code}-${index}`}>
                  <div>
                    <strong>{String(item.stock_code)}</strong>
                    <small>{String(item.strategy_gene_id).replace('gene_', '')}</small>
                  </div>
                  <div className="score-bars">
                    <ScoreBar label="技术" value={Number(item.technical_score)} />
                    <ScoreBar label="基本面" value={Number(item.fundamental_score)} />
                    <ScoreBar label="事件" value={Number(item.event_score)} />
                    <ScoreBar label="行业" value={Number(item.sector_score)} />
                    <ScoreBar label="风险" value={Number(item.risk_penalty)} />
                  </div>
                  <FactorSourceLine packet={parsePacket(item.packet_json)} />
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="数据质量" icon={<AlertTriangle size={18} />}>
            <div className="data-note">
              <b>{Number((dashboard?.data_quality_summary as Record<string, unknown> | undefined)?.warning_count ?? 0)} alerts</b>
              <span>{String(((dashboard?.data_quality_summary as Record<string, unknown> | undefined)?.multidimensional_status as Record<string, unknown> | undefined)?.message ?? '等待数据同步')}</span>
            </div>
            <FactorCoverage summary={dashboard?.data_quality_summary as Record<string, unknown> | undefined} />
            <div className="stack compact">
              {(dashboard?.data_status ?? []).slice(0, 6).map((item, index) => (
                <div className="quality source-quality" key={`source-${index}`}>
                  <span>{String(item.source)}</span>
                  <b className={item.status === 'ok' ? 'ok' : 'warn'}>{String(item.dataset)}</b>
                  <small>{String(item.status)} · {Number(item.rows_loaded ?? 0)} rows {item.error ? `· ${String(item.error)}` : ''}</small>
                </div>
              ))}
            </div>
            <div className="stack compact">
              {(dashboard?.data_quality ?? []).slice(0, 8).map((item, index) => (
                <div className="quality" key={index}>
                  <span>{String(item.stock_code)}</span>
                  <b className={item.status === 'ok' ? 'ok' : 'warn'}>{String(item.status)}</b>
                  <small>{String(item.message ?? '')}</small>
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="记忆检索" icon={<Database size={18} />}>
            <div className="memory-search">
              <input value={memoryQuery} onChange={(event) => setMemoryQuery(event.target.value)} />
              <button onClick={searchMemory}><Search size={16} /> 检索</button>
            </div>
            <div className="stack compact">
              {memory.map((item, index) => (
                <p className="memory" key={index}>{String(item.content)}</p>
              ))}
            </div>
          </Panel>
        </section>
      </section>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return <div className="metric"><small>{label}</small><strong>{value}</strong></div>;
}

function Panel({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return <section className="panel"><h2>{icon}{title}</h2>{children}</section>;
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  const width = Math.max(0, Math.min(1, value)) * 100;
  return (
    <label className="score-bar">
      <span>{label}</span>
      <i><b style={{ width: `${width}%` }} /></i>
    </label>
  );
}

function FactorSourceLine({ packet }: { packet: Record<string, unknown> }) {
  const sources = (packet.sources ?? {}) as Record<string, unknown>;
  const missing = (packet.missing_fields ?? []) as string[];
  const status = ['fundamental', 'sector', 'event']
    .map((key) => `${labelForFactor(key)}:${missing.includes(key) ? '缺失' : sourceName(sources[key])}`)
    .join(' · ');
  return <small className="factor-source">{status}</small>;
}

function FactorCoverage({ summary }: { summary?: Record<string, unknown> }) {
  const multi = (summary?.multidimensional_status ?? {}) as Record<string, unknown>;
  return (
    <div className="factor-coverage">
      <span>基本面 {Number(multi.fundamental_rows ?? 0)}</span>
      <span>事件 {Number(multi.event_rows ?? 0)}</span>
      <span>行业 {Number(multi.sector_rows ?? 0)}</span>
    </div>
  );
}

function parsePacket(value: unknown): Record<string, unknown> {
  if (typeof value !== 'string') return {};
  try {
    return JSON.parse(value) as Record<string, unknown>;
  } catch {
    return {};
  }
}

function sourceName(value: unknown): string {
  if (!value) return '缺失';
  if (Array.isArray(value)) return value.length ? '可用' : '缺失';
  if (typeof value === 'object') {
    const obj = value as Record<string, unknown>;
    return String(obj.source ?? obj.dataset ?? '可用');
  }
  return String(value);
}

function labelForFactor(value: string): string {
  return { fundamental: '基本面', sector: '行业', event: '事件' }[value] ?? value;
}

function StockReviewView({ data }: { data: Record<string, unknown> | null }) {
  if (!data) return <p className="memory">点击推荐列表中的股票查看单股复盘。</p>;
  const stock = (data.stock ?? {}) as Record<string, unknown>;
  const decisions = (data.decisions ?? []) as Array<Record<string, unknown>>;
  const facts = (data.domain_facts ?? {}) as Record<string, Array<Record<string, unknown>>>;
  return (
    <div className="review-detail">
      <h3>{String(stock.stock_code ?? '')} {String(stock.name ?? '')}</h3>
      {decisions.map((decision) => (
        <div className="review-card" key={String(decision.review_id)}>
          <strong>{String(decision.strategy_gene_id)} · {String(decision.verdict)}</strong>
          <span>{String(decision.summary)}</span>
          <small>driver {String(decision.primary_driver)} · return {formatPct(Number(decision.return_pct))}</small>
        </div>
      ))}
      <EvidenceFacts facts={facts} />
    </div>
  );
}

function EvidenceFacts({ facts }: { facts: Record<string, Array<Record<string, unknown>>> }) {
  const rows = [
    ...(facts.earnings_surprises ?? []).map((item) => ({ label: '业绩预期差', value: formatPct(Number(item.net_profit_surprise_pct)), source: item.expectation_source })),
    ...(facts.order_contract_events ?? []).map((item) => ({ label: '订单/合同', value: formatAmount(Number(item.contract_amount)), source: item.source })),
    ...(facts.business_kpi_actuals ?? []).map((item) => ({ label: String(item.kpi_name), value: String(item.kpi_value), source: item.source })),
  ].slice(0, 6);
  if (!rows.length) return <p className="memory">暂无财报、订单或经营 KPI 证据。</p>;
  return (
    <div className="evidence-table">
      {rows.map((row, index) => (
        <div key={index}>
          <span>{row.label}</span>
          <b>{row.value}</b>
          <small>{String(row.source ?? '')}</small>
        </div>
      ))}
    </div>
  );
}

function StrategyReviewView({
  data,
  list,
  onSelect,
}: {
  data: Record<string, unknown> | null;
  list: Array<Record<string, unknown>>;
  onSelect: (geneId: string) => void;
}) {
  const target = data ?? list[0] ?? null;
  if (!target) return <p className="memory">运行复盘后显示策略整体复盘。</p>;
  const factorEdges = JSON.parse(String(target.factor_edges_json ?? '{}')) as Record<string, Record<string, number>>;
  const signals = (target.signals ?? []) as Array<Record<string, unknown>>;
  return (
    <div className="review-detail">
      <div className="chip-row">
        {list.map((item) => (
          <button key={String(item.strategy_gene_id)} onClick={() => onSelect(String(item.strategy_gene_id))}>
            {String(item.strategy_gene_id).replace('gene_', '')}
          </button>
        ))}
      </div>
      <h3>{String(target.strategy_gene_id)}</h3>
      <p className="memory">{String(target.summary)}</p>
      <div className="factor-grid">
        {Object.entries(factorEdges).map(([factor, edge]) => (
          <div key={factor}>
            <span>{factor}</span>
            <b>{Number(edge.edge ?? 0).toFixed(3)}</b>
          </div>
        ))}
      </div>
      <small>{signals.length} open optimization signals</small>
    </div>
  );
}

function formatPct(value?: number) {
  if (value === undefined || value === null || Number.isNaN(value)) return '-';
  return `${(value * 100).toFixed(2)}%`;
}

function formatAmount(value?: number) {
  if (value === undefined || value === null || Number.isNaN(value)) return '-';
  if (Math.abs(value) >= 100000000) return `${(value / 100000000).toFixed(1)} 亿`;
  return `${value.toFixed(0)}`;
}

createRoot(document.getElementById('root')!).render(<App />);
