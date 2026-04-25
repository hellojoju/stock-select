import { useEffect, useMemo, useState } from 'react';
import { Activity, AlertTriangle, BrainCircuit, Database, GitBranch, Play, Search, ShieldCheck } from 'lucide-react';
import Metric from './components/Metric';
import Panel from './components/Panel';
import ReviewSummary from './sections/ReviewSummary';
import PickList from './sections/PickList';
import StrategyPerformance from './sections/StrategyPerformance';
import StockReviewPanel from './sections/StockReviewPanel';
import StrategyReviewPanel from './sections/StrategyReviewPanel';
import CandidateScores from './sections/CandidateScores';
import DataQuality from './sections/DataQuality';
import MemorySearch from './sections/MemorySearch';
import type { Dashboard, Pick } from './types';
import './styles.css';

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000';

export default function App() {
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
          <Metric label="数据覆盖" value={formatPct(Number(dashboard?.data_quality_summary?.coverage_pct))} />
        </section>

        <section className="content-grid">
          <Panel title="复盘摘要" icon={<ShieldCheck size={18} />}>
            <ReviewSummary data={dashboard?.review_summary} />
          </Panel>

          <Panel title="今日推荐" icon={<Activity size={18} />}>
            <PickList picks={dashboard?.picks ?? []} onSelectStock={(code) => loadStockReview(code)} />
          </Panel>

          <Panel title="策略表现" icon={<BrainCircuit size={18} />}>
            <StrategyPerformance performance={dashboard?.performance ?? []} onSelect={(geneId) => loadStrategyReview(geneId)} />
          </Panel>

          <Panel title="单股复盘" icon={<Search size={18} />}>
            <StockReviewPanel data={stockReview} />
          </Panel>

          <Panel title="早盘策略复盘" icon={<BrainCircuit size={18} />}>
            <StrategyReviewPanel data={strategyReview} list={strategyReviews} onSelect={(geneId) => loadStrategyReview(geneId)} />
          </Panel>

          <Panel title="多维候选评分" icon={<GitBranch size={18} />}>
            <CandidateScores candidate_scores={dashboard?.candidate_scores ?? []} />
          </Panel>

          <Panel title="数据质量" icon={<AlertTriangle size={18} />}>
            {dashboard && <DataQuality dashboard={dashboard} />}
          </Panel>

          <Panel title="记忆检索" icon={<Database size={18} />}>
            <MemorySearch query={memoryQuery} onChange={setMemoryQuery} onSearch={searchMemory} results={memory} />
          </Panel>
        </section>
      </section>
    </main>
  );
}

function formatPct(value?: number) {
  if (value === undefined || value === null || Number.isNaN(value)) return '-';
  return `${(value * 100).toFixed(2)}%`;
}
