export default function StrategyPerformance({
  performance,
  onSelect,
}: {
  performance: Array<Record<string, number | string>>;
  onSelect: (geneId: string) => void;
}) {
  return (
    <div className="stack">
      {performance.map((item) => (
        <button className="gene gene-button" key={String(item.strategy_gene_id)} onClick={() => onSelect(String(item.strategy_gene_id))}>
          <strong>{String(item.strategy_gene_id)}</strong>
          <span>{Number(item.trades)} 笔 · 胜率 {formatPct(Number(item.win_rate))}</span>
          <meter min="0" max="1" value={Math.max(0, Number(item.win_rate ?? 0))} />
        </button>
      ))}
    </div>
  );
}

function formatPct(value: number) {
  if (value === undefined || value === null || Number.isNaN(value)) return '-';
  return `${(value * 100).toFixed(2)}%`;
}
