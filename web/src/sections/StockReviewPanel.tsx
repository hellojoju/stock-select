import { formatPct } from '../lib/format';

export default function StockReviewPanel({ data }: { data?: Record<string, unknown> | null }) {
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

function formatAmount(value?: number) {
  if (value === undefined || value === null || Number.isNaN(value)) return '-';
  if (Math.abs(value) >= 100_000_000) return `${(value / 100_000_000).toFixed(1)} 亿`;
  return `${value.toFixed(0)}`;
}
