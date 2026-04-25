import type { Dashboard } from '../types';

export default function DataQuality({ dashboard }: { dashboard: Dashboard }) {
  const summary = dashboard.data_quality_summary as Record<string, unknown> | undefined;
  const multi = (summary?.multidimensional_status ?? {}) as Record<string, unknown>;
  return (
    <>
      <div className="data-note">
        <b>{Number(summary?.warning_count ?? 0)} alerts</b>
        <span>{String((summary?.multidimensional_status as Record<string, unknown> | undefined)?.message ?? '等待数据同步')}</span>
      </div>
      <FactorCoverage summary={summary} />
      <div className="stack compact">
        {(dashboard.data_status ?? []).slice(0, 6).map((item, index) => (
          <div className="quality source-quality" key={`source-${index}`}>
            <span>{String(item.source)}</span>
            <b className={item.status === 'ok' ? 'ok' : 'warn'}>{String(item.dataset)}</b>
            <small>{String(item.status)} · {Number(item.rows_loaded ?? 0)} rows {item.error ? `· ${String(item.error)}` : ''}</small>
          </div>
        ))}
      </div>
      <div className="stack compact">
        {(dashboard.data_quality ?? []).slice(0, 8).map((item, index) => (
          <div className="quality" key={index}>
            <span>{String(item.stock_code)}</span>
            <b className={item.status === 'ok' ? 'ok' : 'warn'}>{String(item.status)}</b>
            <small>{String(item.message ?? '')}</small>
          </div>
        ))}
      </div>
    </>
  );
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
