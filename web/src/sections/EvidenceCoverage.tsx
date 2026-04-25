import type { EvidenceStatus } from '../types';

const LABELS: Record<string, string> = {
  financial_actuals: '财报实际',
  analyst_expectations: '市场预期',
  earnings_surprises: '预期差',
  order_contract_events: '订单合同',
  business_kpi_actuals: '经营 KPI',
  risk_events: '风险事件',
};

export default function EvidenceCoverage({ status }: { status?: EvidenceStatus }) {
  if (!status) return <p className="memory">等待复盘证据同步。</p>;
  const entries = Object.entries(status.counts ?? {});
  return (
    <div className="evidence-coverage-panel">
      <div className="data-note">
        <b>{status.active_stock_count} active stocks</b>
        <span>{status.message}</span>
      </div>
      <div className="evidence-coverage-grid">
        {entries.map(([key, count]) => {
          const ratio = Number(status.coverage?.[key] ?? 0);
          return (
            <div className="evidence-coverage-cell" key={key}>
              <span>{LABELS[key] ?? key}</span>
              <b>{count}</b>
              <small>{ratio > 0 ? `${(ratio * 100).toFixed(1)}% coverage` : key.includes('events') ? 'event rows' : 'missing or sparse'}</small>
            </div>
          );
        })}
      </div>
      {!!status.skipped_sources?.length && (
        <div className="evidence-warning">
          <b>未配置源</b>
          <span>{status.skipped_sources.map((item) => `${String(item.source)}:${String(item.dataset)}`).join(' · ')}</span>
        </div>
      )}
      {!!status.error_sources?.length && (
        <div className="evidence-warning danger">
          <b>同步失败</b>
          <span>{status.error_sources.map((item) => `${String(item.source)}:${String(item.dataset)}`).join(' · ')}</span>
        </div>
      )}
    </div>
  );
}
