import { useCallback, useEffect, useRef, useState } from 'react';
import { Activity, AlertTriangle, ArrowRight, Search, ShieldCheck } from 'lucide-react';
import Panel from '../components/Panel';
import { PageHeader, SystemStatusStrip } from '../components/PageHeader';
import StrategyReviewPanel from '../sections/StrategyReviewPanel';
import StockReviewPanel from '../sections/StockReviewPanel';
import LLMReviewPanel from '../sections/LLMReviewPanel';
import AnalystReviewPanel from '../sections/AnalystReviewPanel';
import ReviewHistoryPanel from '../components/ReviewHistoryPanel';
import ExecutionStepsPanel from '../components/ExecutionStepsPanel';
import { llmStatusLabel } from '../lib/llmStatus';
import { API_BASE } from '../api/client';
import type { AnalystReview, Dashboard, LLMReview } from '../types';

export default function ReviewPage({ initialStockCode = '' }: { initialStockCode?: string }) {
  const [activeTab, setActiveTab] = useState<'stock' | 'strategy' | 'blindspot' | 'llm' | 'signals'>('stock');
  const [date, setDate] = useState('');
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [strategyReviews, setStrategyReviews] = useState<Array<Record<string, unknown>>>([]);
  const [strategyReview, setStrategyReview] = useState<Record<string, unknown> | null>(null);
  const [stockCode, setStockCode] = useState('');
  const [stockReview, setStockReview] = useState<Record<string, unknown> | null>(null);
  const [reviewSessionId, setReviewSessionId] = useState<string | null>(null);
  const [llmReviews, setLlmReviews] = useState<LLMReview[]>([]);
  const [analystReviews, setAnalystReviews] = useState<AnalystReview[]>([]);
  const [blindspots, setBlindspots] = useState<Array<Record<string, unknown>>>([]);
  const [loading, setLoading] = useState(false);
  const initRef = useRef(false);

  useEffect(() => {
    if (initRef.current) return;
    initRef.current = true;
    fetch(`${API_BASE}/api/dashboard`).then(r => r.json()).then((d) => {
      setDashboard(d);
      const dte = d.date ?? '';
      setDate(dte);
      if (dte) loadAll(dte);
    }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!initialStockCode) return;
    setActiveTab('stock');
    setStockCode(initialStockCode);
    if (date) void loadStockReview(initialStockCode, date);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialStockCode, date]);

  async function loadAll(targetDate: string) {
    if (!targetDate) return;
    setLoading(true);
    await loadDashboard(targetDate);
    await Promise.all([
      loadStrategyReviews(targetDate),
      loadLlmReviews(targetDate),
      loadAnalystReviews(targetDate),
      loadBlindspots(targetDate),
    ]);
    setLoading(false);
  }

  async function loadDashboard(targetDate: string) {
    const response = await fetch(`${API_BASE}/api/dashboard?date=${targetDate}`);
    setDashboard(await response.json());
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
    const data = await response.json();
    setStockReview(data);
    setReviewSessionId(String(data._session_id ?? ''));
  }

  async function loadAnalystReviews(targetDate: string) {
    try {
      const response = await fetch(`${API_BASE}/api/reviews/analysts?date=${targetDate}`);
      setAnalystReviews(normalizeArrayPayload<AnalystReview>(await response.json(), 'reviews'));
    } catch {
      setAnalystReviews([]);
    }
  }

  async function loadLlmReviews(targetDate: string) {
    try {
      const response = await fetch(`${API_BASE}/api/reviews/llm?date=${targetDate}`);
      setLlmReviews(normalizeArrayPayload<LLMReview>(await response.json(), 'reviews'));
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

  function handleSearchStock() {
    if (stockCode && date) loadStockReview(stockCode, date);
  }

  const handleReviewStock = useCallback((code: string, reviewDate: string) => {
    setStockCode(code);
    setDate(reviewDate);
    loadStockReview(code, reviewDate);
  }, []);

  return (
    <div className="page terminal-page">
      <PageHeader
        eyebrow="POST-MARKET ANALYSIS"
        title="复盘中心"
        date={date}
        onDateChange={setDate}
        onRefresh={() => loadAll(date)}
        loading={loading}
      />

      <SystemStatusStrip
        mode={dashboard?.runtime_mode}
        marketEnvironment={dashboard?.market_environment}
        evidenceMessage="复盘只惩罚盘前可见证据，事后事件仅解释"
        warnings={Number(dashboard?.data_quality_summary?.warning_count ?? 0)}
        dataQualitySummary={dashboard?.data_quality_summary ?? null}
        llmStatus={llmStatusLabel(dashboard?.llm_status)}
      />

      <div className="secondary-tabs">
        {[
          ['stock', '单股复盘'],
          ['strategy', '策略整体复盘'],
          ['blindspot', '盲点复盘'],
          ['llm', 'LLM 复盘'],
          ['signals', '优化信号'],
        ].map(([key, label]) => (
          <button key={key} className={activeTab === key ? 'active' : ''} onClick={() => setActiveTab(key as typeof activeTab)}>
            {label}
          </button>
        ))}
      </div>

      {activeTab === 'stock' && (
        <section className="review-workspace">
          <Panel title="当日决策" icon={<Search size={18} />}>
            <div className="memory-search">
              <input value={stockCode} onChange={(event) => setStockCode(event.target.value)} placeholder="输入股票代码" />
              <button className="btn-primary" onClick={handleSearchStock} disabled={!stockCode || !date || loading}><Search size={15} /> 查看</button>
            </div>
            <DecisionRail data={stockReview} />
            <ReviewHistoryPanel date={date} onReviewStock={handleReviewStock} />
          </Panel>
          <Panel title="决策复盘" icon={<ShieldCheck size={18} />}>
            <StockReviewPanel data={stockReview} date={date} onReviewStock={handleReviewStock} />
          </Panel>
          <Panel title="证据时间线" icon={<Activity size={18} />}>
            <EvidenceTimeline data={stockReview} />
          </Panel>
        </section>
      )}

      {activeTab === 'strategy' && (
        <section className="review-workspace two-plus-one">
          <Panel title="策略列表" icon={<ShieldCheck size={18} />}>
            <StrategyRail list={strategyReviews} onSelect={(geneId) => loadStrategyReview(geneId, date)} />
          </Panel>
          <Panel title="策略复盘主面板" icon={<ShieldCheck size={18} />}>
            <StrategyReviewPanel data={strategyReview} list={strategyReviews} onSelect={(geneId) => loadStrategyReview(geneId, date)} />
          </Panel>
          <Panel title="策略问题" icon={<AlertTriangle size={18} />}>
            <BlindspotList blindspots={blindspots} />
          </Panel>
        </section>
      )}

      {activeTab === 'blindspot' && (
        <section className="single-panel-grid">
          <Panel title="盲点复盘" icon={<AlertTriangle size={18} />}>
            <BlindspotList blindspots={blindspots} grouped />
          </Panel>
        </section>
      )}

      {activeTab === 'llm' && (
        <section className="dash-grid">
          <Panel title="分析师评审" icon={<ShieldCheck size={18} />}>
            <AnalystReviewPanel reviews={analystReviews} />
          </Panel>
          <Panel title="LLM 复盘" icon={<Activity size={18} />}>
            <LLMReviewPanel reviews={llmReviews} />
          </Panel>
        </section>
      )}

      {activeTab === 'signals' && (
        <section className="single-panel-grid">
          <Panel title="优化信号" icon={<ShieldCheck size={18} />}>
            <SignalSummary data={stockReview} onNavigateToEvolution={() => window.dispatchEvent(new Event('stock-select:navigate-evolution'))} />
          </Panel>
        </section>
      )}

      <ExecutionStepsPanel sessionId={reviewSessionId} loading={loading} />
    </div>
  );
}

const VERDICT_LABEL: Record<string, string> = { 正确: '正确', 错误: '错误', 中性: '中性', RIGHT: '正确', WRONG: '错误', MIXED: '中性', NEUTRAL: '中性' };
const GENE_LABEL: Record<string, string> = { gene_hypothetical: '假设性分析' };

function geneName(geneId: string): string {
  const direct = GENE_LABEL[geneId];
  if (direct) return direct;
  return geneId.replace(/^gene_/, '');
}

function DecisionRail({ data }: { data: Record<string, unknown> | null }) {
  const decisions = (data?.decisions ?? []) as Array<Record<string, unknown>>;
  if (!decisions.length) return <p className="empty-state">输入股票代码后查看该股票所有 gene 决策。</p>;
  return (
    <div className="decision-rail">
      {decisions.map((decision) => {
        const geneId = String(decision.strategy_gene_id ?? '');
        const verdict = String(decision.verdict ?? '');
        const returnPct = Number(decision.return_pct ?? 0);
        return (
          <div className="decision-tile" key={String(decision.review_id)}>
            <strong>{geneName(geneId)}</strong>
            <span className={`status-tag ${returnPct >= 0 ? 'ok' : 'danger'}`}>{VERDICT_LABEL[verdict] ?? verdict}</span>
            {returnPct !== 0 && <small>{returnPct >= 0 ? '+' : ''}{(returnPct * 100).toFixed(2)}%</small>}
          </div>
        );
      })}
    </div>
  );
}

function EvidenceTimeline({ data }: { data: Record<string, unknown> | null }) {
  const decisions = (data?.decisions ?? []) as Array<Record<string, unknown>>;
  const evidence = decisions.flatMap((decision) => (decision.evidence ?? []) as Array<Record<string, unknown>>);
  const isHypo = data?.hypothetical === true;
  const groups = [
    ['PREOPEN_VISIBLE', '盘前可见'],
    ['POSTCLOSE_OBSERVED', '收盘观察'],
    ['POSTDECISION_EVENT', '事后事件'],
  ];
  if (!evidence.length) {
    if (isHypo) {
      return <p className="empty-state">假设性复盘基于实时信号分析，不采集外部证据来源，故无证据时间线。</p>;
    }
    return <p className="empty-state">暂无证据。缺失不代表负面结论。</p>;
  }

  function formatTime(ts?: unknown): string {
    if (!ts) return '';
    const s = String(ts);
    return s.length > 10 ? s.slice(0, 19).replace('T', ' ') : s;
  }

  return (
    <div className="evidence-timeline">
      {groups.map(([key, label]) => {
        const items = evidence.filter((item) => String(item.visibility) === key).slice(0, 6);
        if (!items.length) return null;
        return (
          <section key={key}>
            <h4>{label}</h4>
            {items.map((item, index) => {
              let payload: Record<string, unknown> = {};
              try { payload = JSON.parse(String(item.payload_json ?? '{}')); } catch { /* ignore */ }
              const sourceUrl = String(item.source_url ?? payload.source_url ?? '');
              const publishedAt = formatTime(item.published_at ?? payload.published_at);
              const asOfDate = String(item.as_of_date ?? payload.as_of_date ?? '');
              return (
                <div className="evidence-time-item" key={`${key}-${index}`}>
                  <i />
                  <div>
                    <strong>{String(item.source_type).replace(/_/g, ' ')}</strong>
                    {!!item.source && <span className="evidence-source-sub">{String(item.source)}</span>}
                    {publishedAt && <span className="evidence-time-meta">发布于 {publishedAt}</span>}
                    {asOfDate && <span className="evidence-time-meta">数据截至 {asOfDate}</span>}
                    {sourceUrl && (
                      <a className="evidence-link" href={sourceUrl} target="_blank" rel="noopener noreferrer">
                        查看原文 ↗
                      </a>
                    )}
                    <span>{String(item.confidence)} · {key === 'POSTDECISION_EVENT' ? '不惩罚早盘策略' : '可用于复盘'}</span>
                  </div>
                </div>
              );
            })}
          </section>
        );
      })}
    </div>
  );
}

function StrategyRail({ list, onSelect }: { list: Array<Record<string, unknown>>; onSelect: (geneId: string) => void }) {
  if (!list.length) return <p className="empty-state">暂无策略复盘。</p>;
  return (
    <div className="decision-rail">
      {list.map((item) => (
        <button className="decision-tile" key={String(item.strategy_gene_id)} onClick={() => onSelect(String(item.strategy_gene_id))}>
          <strong>{String(item.strategy_gene_id).replace('gene_', '')}</strong>
          <span>{String(item.verdict ?? 'reviewed')}</span>
          <small>{String(item.summary ?? '').slice(0, 42)}</small>
        </button>
      ))}
    </div>
  );
}

const BLINDSPOT_GROUPS: Array<[string, string[]]> = [
  ['可学习盲点', ['选错时机', '选错股票', '忽略风险', '忽略信号', '参数不当', '策略偏差']],
  ['不可惩罚盲点', ['盘后事件', '信息不足', '数据缺失']],
  ['正确避开', ['正确回避']],
  ['数据缺失', ['数据异常', '无数据']],
];

function BlindspotList({ blindspots, grouped }: { blindspots: Array<Record<string, unknown>>; grouped?: boolean }) {
  if (!blindspots.length) return <p className="empty-state">暂无盲点复盘。</p>;

  function classify(item: Record<string, unknown>): string {
    const reason = String(item.primary_reason ?? item.reason ?? item.missed_stage ?? '');
    for (const [group, keywords] of BLINDSPOT_GROUPS) {
      if (keywords.some(kw => reason.includes(kw))) return group;
    }
    return BLINDSPOT_GROUPS[0][0];
  }

  if (!grouped) {
    return (
      <div className="stack compact">
        {blindspots.slice(0, 6).map((item, i) => (
          <div className="review-card" key={`ungrouped-${i}`}>
            <strong>{String(item.stock_code)}</strong>
            <span>{String(item.primary_reason ?? item.reason ?? item.missed_stage ?? '待复盘')}</span>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="blindspot-groups">
      {BLINDSPOT_GROUPS.map(([group]) => {
        const items = blindspots.filter(item => classify(item) === group).slice(0, 5);
        if (!items.length) return null;
        return (
          <section className="blindspot-group" key={group}>
            <h4>{group}</h4>
            {items.map((item, i) => (
              <div className="review-card" key={`${group}-${i}`}>
                <strong>{String(item.stock_code)}</strong>
                <span>{String(item.primary_reason ?? item.reason ?? item.missed_stage ?? '待复盘')}</span>
              </div>
            ))}
          </section>
        );
      })}
    </div>
  );
}

function SignalSummary({ data, onNavigateToEvolution }: { data: Record<string, unknown> | null; onNavigateToEvolution?: () => void }) {
  const decisions = (data?.decisions ?? []) as Array<Record<string, unknown>>;
  const signals = decisions.flatMap((decision) => (decision.optimization_signals ?? []) as Array<Record<string, unknown>>);
  if (!signals.length) return (
    <div>
      <p className="empty-state">暂无当前股票的优化信号。也可以到策略进化页查看全局信号池。</p>
      {onNavigateToEvolution && (
        <button className="btn-primary" onClick={onNavigateToEvolution}>
          <ArrowRight size={15} /> 前往策略进化
        </button>
      )}
    </div>
  );
  return (
    <div>
      <div className="terminal-table signal-table">
        <div className="terminal-thead"><span>Signal</span><span>Param</span><span>Direction</span><span>Strength</span><span>Status</span></div>
        {signals.map((signal, index) => (
          <div className="terminal-row" key={index}>
            <span>{String(signal.signal_type)}</span>
            <span>{String(signal.param_name ?? '-')}</span>
            <span>{String(signal.direction)}</span>
            <span>{Number(signal.strength ?? 0).toFixed(2)}</span>
            <span><span className="status-tag warn">{String(signal.status ?? 'candidate')}</span></span>
          </div>
        ))}
      </div>
      {onNavigateToEvolution && (
        <button className="btn-secondary" style={{ marginTop: 12 }} onClick={onNavigateToEvolution}>
          <ArrowRight size={15} /> 前往策略进化查看完整信号池
        </button>
      )}
    </div>
  );
}

function normalizeArrayPayload<T>(payload: unknown, nestedKey: string): T[] {
  if (Array.isArray(payload)) return payload as T[];
  if (payload && typeof payload === 'object') {
    const nested = (payload as Record<string, unknown>)[nestedKey];
    if (Array.isArray(nested)) return nested as T[];
  }
  return [];
}
