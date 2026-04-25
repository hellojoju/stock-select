import { useEffect, useRef, useState } from 'react';
import { Activity, Play, RotateCcw, Search, ShieldCheck } from 'lucide-react';
import Panel from '../components/Panel';
import StrategyReviewPanel from '../sections/StrategyReviewPanel';
import StockReviewPanel from '../sections/StockReviewPanel';
import LLMReviewPanel from '../sections/LLMReviewPanel';
import AnalystReviewPanel from '../sections/AnalystReviewPanel';
import type { AnalystReview, LLMReview } from '../types';

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:18425';

export default function ReviewPage() {
  const [date, setDate] = useState('');
  const [strategyReviews, setStrategyReviews] = useState<Array<Record<string, unknown>>>([]);
  const [strategyReview, setStrategyReview] = useState<Record<string, unknown> | null>(null);
  const [stockCode, setStockCode] = useState('');
  const [stockReview, setStockReview] = useState<Record<string, unknown> | null>(null);
  const [llmReviews, setLlmReviews] = useState<LLMReview[]>([]);
  const [analystReviews, setAnalystReviews] = useState<AnalystReview[]>([]);
  const [blindspots, setBlindspots] = useState<Array<Record<string, unknown>>>([]);
  const [loading, setLoading] = useState(false);
  const initRef = useRef(false);

  useEffect(() => {
    if (initRef.current) return;
    initRef.current = true;
    fetch(`${API_BASE}/api/dashboard`).then(r => r.json()).then((d) => {
      const dte = d.date ?? '';
      setDate(dte);
      if (dte) loadAll(dte);
    }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function loadAll(targetDate: string) {
    if (!targetDate) return;
    setLoading(true);
    await Promise.all([
      loadStrategyReviews(targetDate),
      loadLlmReviews(targetDate),
      loadAnalystReviews(targetDate),
      loadBlindspots(targetDate),
    ]);
    setLoading(false);
  }

  async function loadStrategyReviews(targetDate: string) {
    const response = await fetch(`${API_BASE}/api/reviews/preopen-strategies?date=${targetDate}`);
    const data = await response.json();
    setStrategyReviews(data);
    if (data.length > 0) setStrategyReview(data[0]);
  }

  async function loadStrategyReview(geneId: string, targetDate: string) {
    const response = await fetch(`${API_BASE}/api/reviews/preopen-strategies/${geneId}?date=${targetDate}`);
    setStrategyReview(await response.json());
  }

  async function loadStockReview(code: string, targetDate: string) {
    if (!code || !targetDate) return;
    const response = await fetch(`${API_BASE}/api/reviews/stocks/${code}?date=${targetDate}`);
    setStockReview(await response.json());
  }

  async function loadAnalystReviews(targetDate: string) {
    try {
      const response = await fetch(`${API_BASE}/api/reviews/analysts?date=${targetDate}`);
      setAnalystReviews(await response.json());
    } catch {
      setAnalystReviews([]);
    }
  }

  async function loadLlmReviews(targetDate: string) {
    try {
      const response = await fetch(`${API_BASE}/api/reviews/llm?date=${targetDate}`);
      setLlmReviews(await response.json());
    } catch {
      setLlmReviews([]);
    }
  }

  async function loadBlindspots(targetDate: string) {
    try {
      const response = await fetch(`${API_BASE}/api/blindspots?date=${targetDate}`);
      setBlindspots(await response.json());
    } catch {
      setBlindspots([]);
    }
  }

  async function triggerRerunLlm() {
    if (!date) return;
    setLoading(true);
    await fetch(`${API_BASE}/api/reviews/llm/rerun?date=${date}`, { method: 'POST' });
    await loadLlmReviews(date);
    setLoading(false);
  }

  function handleSearchStock() {
    if (stockCode && date) loadStockReview(stockCode, date);
  }

  return (
    <div className="page">
      <header className="topbar">
        <div>
          <p className="eyebrow">POST-MARKET ANALYSIS</p>
          <h1>复盘分析</h1>
        </div>
        <div className="actions">
          <input value={date} onChange={(e) => setDate(e.target.value)} placeholder="YYYY-MM-DD" />
          <button onClick={() => loadAll(date)} disabled={!date || loading}><Search size={16} /> 查询</button>
          <button onClick={triggerRerunLlm} disabled={!date || loading}><RotateCcw size={16} /> 重跑 LLM 复盘</button>
        </div>
      </header>

      <div className="dash-grid">
        <div className="dash-col dash-col-main">
          <Panel title="策略复盘" icon={<ShieldCheck size={18} />}>
            <StrategyReviewPanel
              data={strategyReview}
              list={strategyReviews}
              onSelect={(geneId) => loadStrategyReview(geneId, date)}
            />
          </Panel>

          <Panel title="单股复盘" icon={<Search size={18} />}>
            <div className="memory-search">
              <input value={stockCode} onChange={(e) => setStockCode(e.target.value)} placeholder="输入股票代码" />
              <button onClick={handleSearchStock} disabled={!stockCode || !date || loading}><Search size={16} /> 查看</button>
            </div>
            <StockReviewPanel data={stockReview} />
          </Panel>
        </div>

        <div className="dash-col dash-col-side">
          <Panel title="分析师评审" icon={<ShieldCheck size={18} />}>
            <AnalystReviewPanel reviews={analystReviews} />
          </Panel>

          <Panel title="LLM 复盘" icon={<Activity size={18} />}>
            <LLMReviewPanel reviews={llmReviews} />
          </Panel>

          {blindspots.length > 0 && (
            <Panel title="盲点复盘" icon={<Search size={18} />}>
              <div className="stack compact">
                {blindspots.map((item, i) => (
                  <div className="review-card" key={i}>
                    <strong>{String(item.stock_code)}</strong>
                    <span>{String(item.reason ?? '')}</span>
                  </div>
                ))}
              </div>
            </Panel>
          )}
        </div>
      </div>
    </div>
  );
}
