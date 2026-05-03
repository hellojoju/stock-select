export default function StrategyReviewPanel({
  data,
  list,
  onSelect,
}: {
  data: Record<string, unknown> | null;
  list: Array<Record<string, unknown>>;
  onSelect: (geneId: string) => void;
}) {
  const target = data ?? list[0] ?? null;
  if (!target) return <p className="memory">运行复盘后显示策略整体复盘。</p>;

  const factorEdges = JSON.parse(String(target.factor_edges_json ?? '{}')) as Record<string, Record<string, number>>;
  const deterministic = JSON.parse(String(target.deterministic_json ?? '{}')) as Record<string, unknown>;
  const evidenceCoverage = (deterministic.evidence_coverage ?? {}) as Record<string, number>;
  const topErrors = (deterministic.top_errors ?? []) as Array<Record<string, unknown>>;
  const returns = (deterministic.returns ?? []) as number[];
  const signals = (target.signals ?? []) as Array<Record<string, unknown>>;
  const blindspotCount = Number(deterministic.blindspot_count ?? 0);

  const wins = returns.filter((r) => r > 0).length;
  const losses = returns.length - wins;
  const avgReturn = returns.length ? (returns.reduce((a, b) => a + b, 0) / returns.length) : 0;

  return (
    <div className="review-detail">
      <div className="chip-row">
        {list.map((item) => (
          <button key={String(item.strategy_gene_id)} onClick={() => onSelect(String(item.strategy_gene_id))}>
            {String(item.strategy_gene_id).replace('gene_', '')}
          </button>
        ))}
      </div>
      <h3>{String(target.strategy_gene_id)}</h3>
      <p className="memory">{String(target.summary)}</p>

      {/* Performance strip */}
      <div className="strategy-perf-strip">
        <div className="perf-chip">
          <span>交易数</span><b>{returns.length}</b>
        </div>
        <div className="perf-chip">
          <span>胜</span><b>{wins}</b>
        </div>
        <div className="perf-chip">
          <span>负</span><b>{losses}</b>
        </div>
        <div className="perf-chip">
          <span>胜率</span><b>{returns.length ? ((wins / returns.length) * 100).toFixed(0) : 0}%</b>
        </div>
        <div className="perf-chip">
          <span>平均收益</span><b className={avgReturn >= 0 ? 'up' : 'down'}>{(avgReturn * 100).toFixed(2)}%</b>
        </div>
        {!!blindspotCount && (
          <div className="perf-chip blindspot">
            <span>盲点</span><b>{blindspotCount}</b>
          </div>
        )}
      </div>

      {/* Factor edges */}
      <section className="detail-section">
        <h4>因子边</h4>
        <div className="factor-edge-grid">
          {Object.entries(factorEdges).map(([factor, edge]) => {
            const edgeVal = Number(edge.edge ?? 0);
            const barWidth = Math.min(Math.abs(edgeVal) * 100, 100);
            return (
              <div className="factor-edge-row" key={factor}>
                <span className="factor-edge-label">{factor}</span>
                <div className="factor-edge-bar-track">
                  <div
                    className={`factor-edge-bar ${edgeVal >= 0 ? 'positive' : 'negative'}`}
                    style={{ width: `${barWidth}%` }}
                  />
                </div>
                <span className="factor-edge-value">{edgeVal.toFixed(3)}</span>
                <small className="factor-edge-sub">
                  胜 {(Number(edge.winner_avg ?? 0) * 100).toFixed(1)}% / 负 {(Number(edge.loser_avg ?? 0) * 100).toFixed(1)}%
                </small>
              </div>
            );
          })}
        </div>
      </section>

      {/* Evidence coverage */}
      <section className="detail-section">
        <h4>证据覆盖率</h4>
        <div className="evidence-coverage-grid">
          {Object.entries(evidenceCoverage).map(([key, value]) => {
            const pct = Number(value) * 100;
            return (
              <div className="evidence-coverage-item" key={key}>
                <span>{key.replace(/_/g, ' ')}</span>
                <div className="coverage-bar-track">
                  <div className="coverage-bar" style={{ width: `${pct}%` }} />
                </div>
                <b>{pct.toFixed(0)}%</b>
              </div>
            );
          })}
        </div>
      </section>

      {/* Top errors (S2.5) */}
      {topErrors.length > 0 && (
        <section className="detail-section">
          <h4>高频错误</h4>
          <div className="top-errors-list">
            {topErrors.slice(0, 5).map((err, i) => (
              <div className="top-error-row" key={i}>
                <span className="top-error-type">{String(err.error_type)}</span>
                <span className="top-error-count">{Number(err.count)} 次</span>
                <span className="top-error-severity">均严重度 {(Number(err.avg_severity) * 100).toFixed(0)}%</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Signals */}
      <small>{signals.length} open optimization signals</small>
    </div>
  );
}
