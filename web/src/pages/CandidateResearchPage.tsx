import { useEffect, useMemo, useState } from 'react';
import { Filter, RefreshCw, Search } from 'lucide-react';
import { PageHeader, SystemStatusStrip } from '../components/PageHeader';
import Panel from '../components/Panel';
import { formatPct } from '../lib/format';
import { llmStatusLabel } from '../lib/llmStatus';
import { labelForFactor, parsePacket, sourceName } from '../lib/packet';
import { API_BASE } from '../api/client';
import type { Dashboard } from '../types';

type CandidateRow = Record<string, string | number>;

export default function CandidateResearchPage() {
  const [date, setDate] = useState('');
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [selected, setSelected] = useState<CandidateRow | null>(null);
  const [geneFilter, setGeneFilter] = useState('全部');
  const [industryFilter, setIndustryFilter] = useState('全部');
  const [decisionFilters, setDecisionFilters] = useState<Record<string, boolean>>({ BUY: true, WATCH: true, REJECT: true });
  const [missingOnly, setMissingOnly] = useState(false);
  const [riskOnly, setRiskOnly] = useState(false);
  const [loading, setLoading] = useState(false);

  async function loadDashboard(targetDate = date) {
    setLoading(true);
    const suffix = targetDate ? `?date=${targetDate}` : '';
    const response = await fetch(`${API_BASE}/api/dashboard${suffix}`);
    const data = await response.json();
    setDashboard(data);
    if (!date && data.date) setDate(data.date);
    const first = (data.candidate_scores ?? [])[0] as CandidateRow | undefined;
    if (first) setSelected(first);
    setLoading(false);
  }

  useEffect(() => { void loadDashboard(''); }, []);

  const candidates = useMemo(() => {
    const rows = (dashboard?.candidate_scores ?? []) as CandidateRow[];
    return rows.filter((row) => {
      const packet = parsePacket(row.packet_json);
      const missing = (packet.missing_fields ?? []) as string[];
      const decision = decisionFor(row);
      const stock = (packet.stock ?? {}) as Record<string, unknown>;
      if (geneFilter !== '全部' && String(row.strategy_gene_id) !== geneFilter) return false;
      if (industryFilter !== '全部' && String(row.industry ?? stock.industry ?? 'unknown') !== industryFilter) return false;
      if (!decisionFilters[decision]) return false;
      if (missingOnly && missing.length === 0) return false;
      if (riskOnly && Number(row.risk_penalty ?? 0) <= 0) return false;
      return true;
    });
  }, [dashboard, geneFilter, industryFilter, decisionFilters, missingOnly, riskOnly]);

  const genes = useMemo(() => {
    const values = new Set((dashboard?.candidate_scores ?? []).map((row) => String(row.strategy_gene_id)));
    return ['全部', ...values];
  }, [dashboard]);

  const industries = useMemo(() => {
    const values = new Set((dashboard?.candidate_scores ?? []).map((row) => {
      const packet = parsePacket(row.packet_json);
      return String(row.industry ?? (packet.stock as Record<string, unknown> | undefined)?.industry ?? 'unknown');
    }));
    return ['全部', ...values];
  }, [dashboard]);

  return (
    <div className="page terminal-page">
      <PageHeader
        eyebrow="PREOPEN RESEARCH"
        title="选股研究"
        date={date}
        onDateChange={setDate}
        onRefresh={() => loadDashboard(date)}
        loading={loading}
      >
        <button className="btn-secondary" type="button" onClick={() => loadDashboard(date)} disabled={loading}>
          <RefreshCw size={15} /> 刷新候选池
        </button>
      </PageHeader>

      <SystemStatusStrip
        mode={dashboard?.runtime_mode}
        marketEnvironment={dashboard?.market_environment}
        evidenceMessage="预盘候选只使用目标日前可见数据"
        warnings={Number(dashboard?.data_quality_summary?.warning_count ?? 0)}
        dataQualitySummary={dashboard?.data_quality_summary ?? null}
        llmStatus={llmStatusLabel(dashboard?.llm_status)}
      />

      <section className="research-layout">
        <Panel title="候选池筛选" icon={<Filter size={17} />}>
          <div className="filter-stack">
            <FilterGroup label="Gene">
              <div className="chip-grid">
                {genes.map((gene) => (
                  <button
                    key={gene}
                    className={`chip ${geneFilter === gene ? 'selected' : ''}`}
                    type="button"
                    onClick={() => setGeneFilter(gene)}
                  >
                    {gene.replace('gene_', '')}
                  </button>
                ))}
              </div>
            </FilterGroup>
            <FilterGroup label="行业">
              <div className="chip-grid">
                {industries.slice(0, 12).map((industry) => (
                  <button
                    key={industry}
                    className={`chip ${industryFilter === industry ? 'selected' : ''}`}
                    type="button"
                    onClick={() => setIndustryFilter(industry)}
                  >
                    {industry}
                  </button>
                ))}
              </div>
            </FilterGroup>
            <FilterGroup label="Decision">
              {(['BUY', 'WATCH', 'REJECT'] as const).map((decision) => (
                <label className="check-line" key={decision}>
                  <input
                    type="checkbox"
                    checked={decisionFilters[decision]}
                    onChange={(event) => setDecisionFilters((prev) => ({ ...prev, [decision]: event.target.checked }))}
                  />
                  {decision}
                </label>
              ))}
            </FilterGroup>
            <FilterGroup label="数据状态">
              <label className="check-line">
                <input type="checkbox" checked={missingOnly} onChange={(event) => setMissingOnly(event.target.checked)} />
                只看缺失证据
              </label>
              <label className="check-line">
                <input type="checkbox" checked={riskOnly} onChange={(event) => setRiskOnly(event.target.checked)} />
                只看风险惩罚
              </label>
            </FilterGroup>
            <div className="filter-actions">
              <button className="btn-secondary" type="button" onClick={() => {
                setGeneFilter('全部');
                setIndustryFilter('全部');
                setDecisionFilters({ BUY: true, WATCH: true, REJECT: true });
                setMissingOnly(false);
                setRiskOnly(false);
              }}>
                重置
              </button>
            </div>
          </div>
        </Panel>

        <Panel title={`候选池 ${candidates.length} → 推荐 ${dashboard?.picks?.length ?? 0}`} icon={<Search size={17} />}>
          <CandidateTable rows={candidates} selected={selected} onSelect={setSelected} />
        </Panel>

        <Panel title="候选详情" icon={<Search size={17} />}>
          <CandidateInspector row={selected} />
        </Panel>
      </section>
    </div>
  );
}

function CandidateTable({
  rows,
  selected,
  onSelect,
}: {
  rows: CandidateRow[];
  selected: CandidateRow | null;
  onSelect: (row: CandidateRow) => void;
}) {
  return (
    <div className="terminal-table candidate-table">
      <div className="terminal-thead">
        <span>Rank</span><span>股票</span><span>Gene</span><span>Decision</span><span>Total</span>
        <span>技术</span><span>基本面</span><span>事件</span><span>行业</span><span>风险</span><span>Missing</span>
      </div>
      {rows.slice(0, 18).map((row, index) => {
        const packet = parsePacket(row.packet_json);
        const missing = (packet.missing_fields ?? []) as string[];
        const decision = decisionFor(row);
        const selectedRow = selected && selected.stock_code === row.stock_code && selected.strategy_gene_id === row.strategy_gene_id;
        return (
          <button
            className={`terminal-row candidate-row ${selectedRow ? 'selected' : ''}`}
            key={`${row.strategy_gene_id}-${row.stock_code}-${index}`}
            type="button"
            onClick={() => onSelect(row)}
          >
            <span>{index + 1}</span>
            <span><b>{String(row.stock_code)}</b><small>{String(row.stock_name ?? row.industry ?? '')}</small></span>
            <span>{String(row.strategy_gene_id).replace('gene_', '')}</span>
            <span><StatusLabel tone={decision === 'BUY' ? 'ok' : decision === 'WATCH' ? 'warn' : 'danger'}>{decision}</StatusLabel></span>
            <span>{Number(row.total_score ?? row.score ?? 0).toFixed(2)}</span>
            <MiniScore value={Number(row.technical_score ?? 0)} />
            <MiniScore value={Number(row.fundamental_score ?? 0)} />
            <MiniScore value={Number(row.event_score ?? 0)} />
            <MiniScore value={Number(row.sector_score ?? 0)} />
            <MiniScore value={Number(row.risk_penalty ?? 0)} danger />
            <span className="missing-cell">{missing.length ? missing.slice(0, 2).join(', ') : '无'}</span>
          </button>
        );
      })}
    </div>
  );
}

function CandidateInspector({ row }: { row: CandidateRow | null }) {
  if (!row) return <p className="empty-state">选择候选股票查看选股依据。</p>;
  const packet = parsePacket(row.packet_json);
  const sources = (packet.sources ?? {}) as Record<string, unknown>;
  const missing = (packet.missing_fields ?? []) as string[];
  const hardFilters = Array.isArray(packet.hard_filters) ? packet.hard_filters as Array<Record<string, unknown>> : [];
  return (
    <div className="inspector">
      <div className="inspector-hero">
        <span>{String(row.strategy_gene_id).replace('gene_', '')}</span>
        <h3>{String(row.stock_code)}</h3>
        <b>{Number(row.total_score ?? row.score ?? 0).toFixed(3)}</b>
      </div>
      <div className="kv-grid">
        <InfoKV label="Decision" value={Number(row.total_score ?? row.score ?? 0) > 0.65 ? 'BUY' : 'WATCH'} />
        <InfoKV label="Confidence" value={formatPct(Number(row.confidence ?? row.total_score ?? 0))} />
        <InfoKV label="Position" value={formatPct(Number(row.position_pct ?? 0.03))} />
        <InfoKV label="Snapshot" value={String(packet.input_snapshot_hash ?? 'pending')} />
      </div>

      <section className="inspector-section">
        <h4>五维评分雷达</h4>
        <FactorRadarChart row={row} />
      </section>

      <section className="inspector-section">
        <h4>五维评分来源</h4>
        {['technical', 'fundamental', 'event', 'sector', 'risk'].map((key) => {
          const source = key === 'event' ? sources.events : sources[key];
          const asOf = sourceAsOf(source);
          return (
          <div className="source-line" key={key}>
            <span>{factorLabel(key)}</span>
            <b>{sourceName(source)}</b>
            <small>{missing.includes(key) ? 'data_missing' : asOf}</small>
          </div>
        );})}
      </section>

      <section className="inspector-section">
        <h4>Missing Fields</h4>
        <div className="tag-wrap">
          {missing.length ? missing.map((item) => <span className="status-tag warn" key={item}>{labelForFactor(item)}</span>) : <span className="status-tag ok">无关键缺失</span>}
        </div>
      </section>

      <section className="inspector-section">
        <h4>Hard Filters</h4>
        {hardFilters.length ? hardFilters.map((item, index) => {
          const status = String(item.status ?? 'unknown');
          return (
            <div className="source-line compact-line" key={`${String(item.name ?? item.filter ?? index)}`}>
              <span>{String(item.name ?? item.filter ?? `filter_${index + 1}`)}</span>
              <b className={status === 'pass' || status === 'ok' ? 'ok' : status === 'fail' ? 'down' : 'warn'}>{status.toUpperCase()}</b>
              <small>{String(item.reason ?? item.source ?? '后端未提供细节')}</small>
            </div>
          );
        }) : (
          <p className="detail-copy">后端尚未返回 hard_filters，当前页面不再假设全部通过。</p>
        )}
      </section>

      <section className="inspector-section">
        <h4>交易计划</h4>
        <p className="detail-copy">{formatPlan(packet.entry_plan, 'entry_plan 未由候选 packet 返回')}</p>
        <p className="detail-copy">{formatPlan(packet.sell_rules, 'sell_rules 未由候选 packet 返回')}</p>
      </section>
    </div>
  );
}

function decisionFor(row: CandidateRow) {
  const score = Number(row.total_score ?? row.score ?? 0);
  const risk = Number(row.risk_penalty ?? 0);
  if (risk >= 0.6 || score < 0.35) return 'REJECT';
  if (score > 0.65) return 'BUY';
  return 'WATCH';
}

function sourceAsOf(value: unknown): string {
  if (Array.isArray(value)) {
    if (!value.length) return '无可用记录';
    return value.map(sourceAsOf).join(' · ');
  }
  if (!value || typeof value !== 'object') return '后端未提供 as_of_date';
  const obj = value as Record<string, unknown>;
  return String(obj.as_of_date ?? obj.trading_date ?? obj.visibility ?? obj.report_period ?? '后端未提供 as_of_date');
}

function formatPlan(value: unknown, fallback: string) {
  if (!value) return fallback;
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
}

function FactorRadarChart({ row }: { row: CandidateRow }) {
  const dimensions = [
    { key: 'technical', label: '技术', value: clamp01(Number(row.technical_score ?? 0)) },
    { key: 'fundamental', label: '基本面', value: clamp01(Number(row.fundamental_score ?? 0)) },
    { key: 'event', label: '事件', value: clamp01(Number(row.event_score ?? 0)) },
    { key: 'sector', label: '行业', value: clamp01(Number(row.sector_score ?? 0)) },
    { key: 'risk', label: '风险控制', value: clamp01(1 - Number(row.risk_penalty ?? 0)) },
  ];
  const size = 238;
  const center = size / 2;
  const radius = 74;
  const angleFor = (index: number) => -Math.PI / 2 + (Math.PI * 2 * index) / dimensions.length;
  const point = (index: number, value = 1) => {
    const angle = angleFor(index);
    const distance = radius * value;
    return {
      x: center + Math.cos(angle) * distance,
      y: center + Math.sin(angle) * distance,
    };
  };
  const polygon = dimensions.map((dimension, index) => {
    const p = point(index, dimension.value);
    return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
  }).join(' ');
  const gridLevels = [0.25, 0.5, 0.75, 1];
  return (
    <div className="radar-card">
      <svg className="factor-radar" viewBox={`0 0 ${size} ${size}`} role="img" aria-label="五维评分雷达图">
        {gridLevels.map((level) => (
          <polygon
            key={level}
            points={dimensions.map((_, index) => {
              const p = point(index, level);
              return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
            }).join(' ')}
            className="radar-grid"
          />
        ))}
        {dimensions.map((_, index) => {
          const p = point(index, 1);
          return <line key={index} x1={center} y1={center} x2={p.x} y2={p.y} className="radar-axis" />;
        })}
        <polygon points={polygon} className="radar-shape" />
        {dimensions.map((dimension, index) => {
          const p = point(index, 1.22);
          return (
            <g key={dimension.key}>
              <text x={p.x} y={p.y} textAnchor="middle" dominantBaseline="middle" className="radar-label">
                {dimension.label}
              </text>
              <text x={p.x} y={p.y + 13} textAnchor="middle" dominantBaseline="middle" className="radar-value">
                {dimension.value.toFixed(2)}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="radar-legend">
        {dimensions.map((dimension) => (
          <span key={dimension.key}><b>{dimension.label}</b>{dimension.value.toFixed(2)}</span>
        ))}
      </div>
    </div>
  );
}

function clamp01(value: number) {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(1, value));
}

function MiniScore({ value, danger }: { value: number; danger?: boolean }) {
  const width = Math.max(0, Math.min(100, value * 100));
  return (
    <span className={`mini-score ${danger ? 'danger' : ''}`}>
      <i><b style={{ width: `${width}%` }} /></i>
      <em>{value.toFixed(2)}</em>
    </span>
  );
}

function StatusLabel({ tone, children }: { tone: 'ok' | 'warn' | 'danger'; children: React.ReactNode }) {
  return <span className={`status-tag ${tone}`}>{children}</span>;
}

function FilterGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section className="filter-group">
      <h4>{label}</h4>
      {children}
    </section>
  );
}

function InfoKV({ label, value }: { label: string; value: string }) {
  return <div className="info-kv"><span>{label}</span><b>{value}</b></div>;
}

function factorLabel(value: string) {
  return {
    technical: '技术',
    fundamental: '基本面',
    event: '事件',
    sector: '行业',
    risk: '风险',
  }[value] ?? value;
}
