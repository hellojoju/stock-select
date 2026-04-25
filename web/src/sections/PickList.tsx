import { formatPct } from '../lib/format';
import type { Pick } from '../types';

export default function PickList({ picks, onSelectStock }: { picks: Pick[]; onSelectStock: (code: string) => void }) {
  return (
    <div className="table">
      <div className="thead">
        <span>股票</span><span>基因</span><span>仓位</span><span>置信度</span><span>收益</span>
      </div>
      {picks.map((pick) => (
        <button className="row row-button" key={pick.decision_id} onClick={() => onSelectStock(pick.stock_code)}>
          <span><b>{pick.stock_code}</b><small>{pick.stock_name ?? ''}</small></span>
          <span>{pick.strategy_gene_id.replace('gene_', '')}</span>
          <span>{formatPct(pick.position_pct)}</span>
          <span>{formatPct(pick.confidence)}</span>
          <span className={Number(pick.return_pct ?? 0) >= 0 ? 'up' : 'down'}>{formatPct(pick.return_pct ?? undefined)}</span>
        </button>
      ))}
    </div>
  );
}
