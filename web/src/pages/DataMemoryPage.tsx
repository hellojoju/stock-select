import { useEffect, useState } from 'react';
import { Database, RefreshCw, Search, ServerCog, Activity, GitBranch } from 'lucide-react';
import Panel from '../components/Panel';
import Metric from '../components/Metric';
import { PageHeader, SystemStatusStrip } from '../components/PageHeader';
import DataQuality from '../sections/DataQuality';
import EvidenceCoverage from '../sections/EvidenceCoverage';
import MemorySearch from '../sections/MemorySearch';
import SchedulerPanel from '../components/SchedulerPanel';
import GraphNeighborhoodPanel from '../sections/GraphNeighborhoodPanel';
import { llmLayerImpact, llmStatusLabel } from '../lib/llmStatus';
import type { Dashboard } from '../types';

interface HealthSource {
  source: string;
  status: string;
  last_sync: string | null;
  staleness_hours: number | null;
}

interface HealthReport {
  generated_at: string;
  sources: HealthSource[];
  latest_trading_date: string | null;
  coverage: {
    trading_date: string;
    stocks_synced: number;
    prices_synced: number;
    coverage_pct: number;
    factor_types: string[];
  } | null;
  stale_sources: string[];
  error_count: number;
}

import { API_BASE } from '../api/client';

export default function DataMemoryPage() {
  const [date, setDate] = useState('');
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(false);
  const [healthReport, setHealthReport] = useState<HealthReport | null>(null);

  const [memoryQuery, setMemoryQuery] = useState('');
  const [memoryResults, setMemoryResults] = useState<Array<Record<string, unknown>>>([]);

  async function loadDashboard(targetDate: string) {
    if (!targetDate) {
      const response = await fetch(`${API_BASE}/api/dashboard`);
      const data = await response.json();
      setDashboard(data);
      if (data.date) setDate(data.date);
      return;
    }
    setLoading(true);
    const response = await fetch(`${API_BASE}/api/dashboard?date=${targetDate}`);
    const data = await response.json();
    setDashboard(data);
    setLoading(false);
  }

  async function loadHealthReport() {
    try {
      const response = await fetch(`${API_BASE}/api/monitor/health`);
      if (response.ok) setHealthReport(await response.json());
    } catch {
      // ignore
    }
  }

  async function searchMemory() {
    if (!memoryQuery.trim()) return;
    try {
      const response = await fetch(`${API_BASE}/api/memory/search?q=${encodeURIComponent(memoryQuery)}&limit=20`);
      setMemoryResults(await response.json());
    } catch {
      setMemoryResults([]);
    }
  }

  useEffect(() => { void loadDashboard(''); void loadHealthReport(); }, []);

  return (
    <div className="page terminal-page">
      <PageHeader
        eyebrow="DATA & OPERATIONS"
        title="数据与运行"
        date={date}
        onDateChange={setDate}
        onRefresh={() => loadDashboard(date)}
        loading={loading}
      >
        <button className="btn-secondary" onClick={() => loadDashboard(date)} disabled={!date || loading}><RefreshCw size={15} /> 刷新状态</button>
      </PageHeader>

      <SystemStatusStrip
        mode={dashboard?.runtime_mode}
        marketEnvironment={dashboard?.market_environment}
        evidenceMessage="缺失代表未知，不代表负面结论"
        warnings={Number(dashboard?.data_quality_summary?.warning_count ?? 0)}
        dataQualitySummary={dashboard?.data_quality_summary ?? null}
        llmStatus={llmStatusLabel(dashboard?.llm_status)}
      />

      <section className="kpi-row data-kpis">
        <Metric label="Runtime" value={String(dashboard?.runtime_mode ?? 'demo').toUpperCase()} />
        <Metric label="Active Stocks" value={dashboard?.evidence_status?.active_stock_count ?? '-'} />
        <Metric label="Canonical Prices" value={dashboard?.data_quality?.length ? 'Partial' : 'OK'} />
        <Metric label="Source Warnings" value={Number(dashboard?.data_quality_summary?.warning_count ?? 0)} />
        <Metric label="Evidence" value={dashboard?.evidence_status ? 'Sparse' : 'Missing'} />
      </section>

      <section className="ops-layout">
        <Panel title="数据源健康" icon={<Activity size={18} />}>
          <HealthScoreCard report={healthReport} />
        </Panel>

        <Panel title="数据质量层级" icon={<Database size={18} />}>
          {dashboard ? <DataLayers dashboard={dashboard} /> : <p className="empty-state">等待数据。</p>}
          {dashboard?.evidence_status && <EvidenceCoverage status={dashboard.evidence_status} />}
        </Panel>

        <Panel title="Pipeline 运行任务" icon={<ServerCog size={18} />}>
          <SchedulerPanel />
          {dashboard && <RecentErrors dashboard={dashboard} />}
        </Panel>

        <Panel title="记忆检索" icon={<Search size={18} />}>
          <MemorySearch
            query={memoryQuery}
            onChange={setMemoryQuery}
            onSearch={searchMemory}
            results={memoryResults}
          />
          {dashboard && (
            <div className="source-status-table">
              <h4>数据源状态</h4>
              <DataQuality dashboard={dashboard} />
            </div>
          )}
        </Panel>

        <Panel title="图谱邻域查询" icon={<GitBranch size={18} />}>
          <GraphNeighborhoodPanel />
        </Panel>
      </section>
    </div>
  );
}

function HealthScoreCard({ report }: { report: HealthReport | null }) {
  if (!report) return <p className="empty-state">健康报告加载中…</p>;

  const healthyCount = report.sources.filter((s) => s.status === 'healthy').length;
  const totalCount = report.sources.length;
  const overall = totalCount > 0 ? Math.round((healthyCount / totalCount) * 100) : 0;

  return (
    <div className="health-report">
      <div className="health-summary-row">
        <div className="health-score-circle">
          <span className={`score-${overall >= 80 ? 'ok' : overall >= 50 ? 'warn' : 'error'}`}>{overall}%</span>
        </div>
        <div className="health-meta">
          <span>数据源: {healthyCount}/{totalCount} 健康</span>
          <span>最新交易日: {report.latest_trading_date ?? '-'}</span>
          <span>错误数: {report.error_count}</span>
        </div>
      </div>

      {report.coverage && (
        <div className="health-coverage-row">
          <span>价格覆盖: {report.coverage.prices_synced}/{report.coverage.stocks_synced} ({report.coverage.coverage_pct.toFixed(1)}%)</span>
        </div>
      )}

      <div className="health-source-list">
        {report.sources.map((src) => (
          <div className="health-source-item" key={src.source}>
            <span className={`health-badge ${src.status}`}>{src.source}</span>
            <span className="health-detail">
              {src.staleness_hours != null ? `${src.staleness_hours.toFixed(1)}h 前` : '从未同步'}
              {src.last_sync ? ` · ${src.last_sync}` : ''}
            </span>
            {src.status === 'stale' && <span className="health-stale-label">过期</span>}
            {src.status === 'error' && <span className="health-error-label">错误</span>}
            {src.status === 'missing' && <span className="health-missing-label">缺失</span>}
          </div>
        ))}
      </div>

      {report.stale_sources.length > 0 && (
        <div className="health-stale-warning">
          过期源: {report.stale_sources.join(', ')}
        </div>
      )}
    </div>
  );
}

function DataLayers({ dashboard }: { dashboard: Dashboard }) {
  const evidence = dashboard.evidence_status;
  const activeStocks = Number(evidence?.active_stock_count ?? 0);
  const warningCount = Number(dashboard.data_quality_summary?.warning_count ?? dashboard.data_quality?.length ?? 0);
  const priceCoverage = activeStocks ? Math.max(0, 1 - warningCount / activeStocks) : null;
  const factorCoverage = averageCoverage(evidence?.coverage, ['financial_actuals', 'analyst_expectations', 'earnings_surprises', 'order_contract_events', 'business_kpi_actuals', 'risk_events']);
  const layers = [
    { label: '行情', status: warningCount ? 'Partial' : 'OK', coverage: priceCoverage, source: 'canonical prices / price checks', impact: warningCount ? `${warningCount} 条校验告警` : '推荐和模拟可用' },
    { label: '因子', status: factorCoverage && factorCoverage > 0.5 ? 'Partial' : 'Sparse', coverage: factorCoverage, source: 'sector / fundamentals / events', impact: factorCoverage === null ? '后端未提供覆盖率' : '基本面和事件按真实覆盖显示' },
    { label: '证据', status: evidence ? 'Sparse' : 'Missing', coverage: Number(evidence?.coverage?.financial_actuals ?? 0), source: 'financials / events / risk', impact: '影响复盘证据完整性' },
    { label: 'LLM', status: llmStatusLabel(dashboard.llm_status), coverage: null, source: dashboard.llm_status?.provider ?? 'disabled', impact: llmLayerImpact(dashboard.llm_status) },
  ];
  return (
    <div className="data-layer-list">
      {layers.map((layer) => (
        <div className="data-layer" key={layer.label}>
          <div>
            <strong>{layer.label}</strong>
            <span className={`status-tag ${layer.status === 'OK' ? 'ok' : layer.status === 'Off' ? 'muted' : 'warn'}`}>{layer.status}</span>
          </div>
          <i><b style={{ width: `${layer.coverage === null ? 4 : Math.max(4, layer.coverage * 100)}%` }} /></i>
          <small>{layer.coverage === null ? '未知覆盖率' : `${(layer.coverage * 100).toFixed(1)}%`} · {layer.source}</small>
          <em>{layer.impact}</em>
        </div>
      ))}
    </div>
  );
}

function averageCoverage(coverage: Record<string, number> | undefined, keys: string[]) {
  if (!coverage) return null;
  const values = keys.map((key) => Number(coverage[key])).filter((value) => Number.isFinite(value));
  if (!values.length) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function RecentErrors({ dashboard }: { dashboard: Dashboard }) {
  const rows = [
    ...(dashboard.data_quality ?? []).map((item) => ({ phase: 'price_check', source: item.stock_code, message: item.message ?? item.status })),
    ...(dashboard.data_status ?? []).filter((item) => String(item.status) !== 'ok').map((item) => ({ phase: item.dataset, source: item.source, message: item.error ?? item.status })),
  ];
  if (!rows.length) return <p className="empty-state">暂无最近错误。</p>;
  return (
    <div className="recent-error-table">
      <h4>最近错误</h4>
      {rows.slice(0, 6).map((row, index) => (
        <div className="error-item" key={index}>
          <span>{String(row.phase)}</span>
          <b>{String(row.source)}</b>
          <small>{String(row.message ?? '')}</small>
        </div>
      ))}
    </div>
  );
}
