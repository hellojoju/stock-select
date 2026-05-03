import { CalendarDays, Search } from 'lucide-react';
import StockSearch from './StockSearch';

type HealthTone = 'ok' | 'warn' | 'danger' | 'info' | 'muted';

export function PageHeader({
  eyebrow,
  title,
  date,
  onDateChange,
  onRefresh,
  loading,
  children,
}: {
  eyebrow: string;
  title: string;
  date: string;
  onDateChange: (value: string) => void;
  onRefresh?: () => void;
  loading?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <header className="terminal-header">
      <div className="terminal-title">
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
      </div>
      <div className="command-bar">
        <label className="date-control">
          <CalendarDays size={15} />
          <input value={date} onChange={(event) => onDateChange(event.target.value)} placeholder="YYYY-MM-DD" />
        </label>
        <button className="btn-secondary" type="button" onClick={onRefresh} disabled={!onRefresh || loading}>
          <Search size={15} /> 查询
        </button>
        <StockSearch />
        {children}
      </div>
    </header>
  );
}

export function SystemStatusStrip({
  mode,
  marketEnvironment,
  evidenceMessage,
  warnings,
  dataQualitySummary,
  llmStatus,
}: {
  mode?: string | null;
  marketEnvironment?: string | null;
  evidenceMessage?: string | null;
  warnings?: number;
  dataQualitySummary?: Record<string, unknown> | null;
  llmStatus?: string | null;
}) {
  const multi = (dataQualitySummary?.multidimensional_status ?? {}) as Record<string, unknown>;
  const factorRows = Number(multi.fundamental_rows ?? 0) + Number(multi.event_rows ?? 0) + Number(multi.sector_rows ?? 0);
  const factorValue = factorRows > 0 ? 'Partial' : 'Unknown';
  const factorTone: HealthTone = factorRows > 0 ? 'warn' : 'muted';
  const priceValue = warnings ? 'Partial' : 'OK';
  return (
    <div className="system-strip">
      <span className={`status-pill ${mode === 'live' ? 'live' : 'demo'}`}>{String(mode ?? 'demo').toUpperCase()}</span>
      <HealthBadge label="行情" value={priceValue} tone={warnings ? 'warn' : 'ok'} />
      <HealthBadge label="因子" value={factorValue} tone={factorTone} />
      <HealthBadge label="证据" value={evidenceMessage ? 'Sparse' : 'Missing'} tone={evidenceMessage ? 'warn' : 'danger'} />
      <HealthBadge label="LLM" value={llmStatus ?? 'Unknown'} tone={llmStatus === 'Ready' ? 'ok' : 'muted'} />
      <span className="strip-message">
        {marketEnvironment ? `市场环境 ${marketEnvironment}` : '等待市场环境'} · {evidenceMessage ?? '证据源未完成同步'}
        {warnings ? ` · ${warnings} 条数据告警` : ''}
      </span>
    </div>
  );
}

export function HealthBadge({ label, value, tone = 'info' }: { label: string; value: string; tone?: HealthTone }) {
  return (
    <span className={`health-badge ${tone}`}>
      {label} <b>{value}</b>
    </span>
  );
}
