import { useEffect, useMemo, useState } from 'react';
import { Activity, Play, Search, ShieldCheck } from 'lucide-react';
import Metric from '../components/Metric';
import Panel from '../components/Panel';
import ReviewSummary from '../sections/ReviewSummary';
import PickList from '../sections/PickList';
import StrategyPerformance from '../sections/StrategyPerformance';
import StockReviewPanel from '../sections/StockReviewPanel';
import type { Dashboard, Pick } from '../types';

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:18425';

export default function DashboardPage() {
  const [date, setDate] = useState('');
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
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

  useEffect(() => { void loadDashboard(''); }, []);

  const best = useMemo(() => dashboard?.performance?.[0], [dashboard]);

  return (
    <div className="page">
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
          <input value={date} onChange={(e) => setDate(e.target.value)} placeholder="YYYY-MM-DD" />
          <button onClick={() => loadDashboard(date)} disabled={loading}><Search size={16} /> 查询</button>
          <button onClick={() => trigger('preopen_pick')} disabled={!date || loading}><Play size={16} /> 选股</button>
          <button onClick={() => trigger('simulate')} disabled={!date || loading}><ShieldCheck size={16} /> 模拟</button>
        </div>
      </header>

      <section className="kpi-row">
        <Metric label="推荐数" value={dashboard?.picks?.length ?? 0} />
        <Metric label="最佳基因" value={String(best?.strategy_gene_id ?? '-')} />
        <Metric label="市场环境" value={String(dashboard?.market_environment ?? '-')} />
        <Metric label="财报覆盖" value={formatPct(Number(dashboard?.evidence_status?.coverage?.financial_actuals))} />
      </section>

      <section className="dash-grid">
        <div className="dash-col dash-col-main">
          <Panel title="今日推荐" icon={<Activity size={18} />}>
            <PickList picks={dashboard?.picks ?? []} onSelectStock={(code) => loadStockReview(code)} />
          </Panel>
          <Panel title="单股复盘" icon={<Search size={18} />}>
            <StockReviewPanel data={stockReview} />
          </Panel>
        </div>
        <div className="dash-col dash-col-side">
          <Panel title="复盘摘要" icon={<ShieldCheck size={18} />}>
            <ReviewSummary data={dashboard?.review_summary} />
          </Panel>
          <Panel title="策略表现" icon={<Activity size={18} />}>
            <StrategyPerformance
              performance={dashboard?.performance ?? []}
              onSelect={(geneId) => loadStrategyReview(geneId)}
            />
          </Panel>
        </div>
      </section>
    </div>
  );
}

function formatPct(value?: number) {
  if (value === undefined || value === null || Number.isNaN(value)) return '-';
  return `${(value * 100).toFixed(2)}%`;
}
