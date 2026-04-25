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
  const signals = (target.signals ?? []) as Array<Record<string, unknown>>;
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
      <div className="factor-grid">
        {Object.entries(factorEdges).map(([factor, edge]) => (
          <div key={factor}>
            <span>{factor}</span>
            <b>{Number(edge.edge ?? 0).toFixed(3)}</b>
          </div>
        ))}
      </div>
      <small>{signals.length} open optimization signals</small>
    </div>
  );
}
