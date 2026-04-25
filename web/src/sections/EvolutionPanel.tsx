import { GitBranch, RotateCcw, Trophy } from 'lucide-react';
import { formatPct } from '../lib/format';

type Comparison = {
  event_id: string;
  parent_gene_id: string;
  child_gene_id?: string | null;
  status: string;
  parent_performance?: Record<string, unknown>;
  child_performance?: Record<string, unknown> | null;
  parameter_diff?: Array<Record<string, unknown>>;
  aggregated_signals?: Array<Record<string, unknown>>;
  promotion_eligible?: boolean;
};

export default function EvolutionPanel({
  comparisons,
  onDryRun,
  onApply,
  onPromote,
  onRollback,
}: {
  comparisons: Comparison[];
  onDryRun: () => void;
  onApply: () => void;
  onPromote: (childGeneId: string) => void;
  onRollback: (childGeneId: string) => void;
}) {
  return (
    <div className="review-detail">
      <div className="chip-row">
        <button onClick={onDryRun}><GitBranch size={15} /> Dry run</button>
        <button onClick={onApply}><Trophy size={15} /> Propose</button>
      </div>
      {!comparisons.length && <p className="memory">暂无 Challenger。先运行 dry-run 审计信号，再按需正式提案。</p>}
      {comparisons.map((item) => (
        <div className="review-card evolution-card" key={item.event_id}>
          <strong>{item.parent_gene_id} → {item.child_gene_id ?? 'pending'}</strong>
          <span>{item.status} · {item.parameter_diff?.length ?? 0} parameter changes · {item.aggregated_signals?.length ?? 0} signal groups</span>
          <div className="evolution-perf">
            <Perf label="Champion" data={item.parent_performance} />
            <Perf label="Challenger" data={item.child_performance ?? undefined} />
          </div>
          <div className="evidence-strip">
            {(item.parameter_diff ?? []).slice(0, 6).map((diff) => (
              <span key={String(diff.param)}>{String(diff.param)} <b>{String(diff.before)} → {String(diff.after)}</b></span>
            ))}
          </div>
          {item.child_gene_id && (
            <div className="chip-row">
              <button onClick={() => onPromote(String(item.child_gene_id))} disabled={!item.promotion_eligible}>
                <Trophy size={15} /> Promote
              </button>
              <button onClick={() => onRollback(String(item.child_gene_id))}>
                <RotateCcw size={15} /> Rollback
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function Perf({ label, data }: { label: string; data?: Record<string, unknown> }) {
  return (
    <div>
      <span>{label}</span>
      <b>{formatPct(Number(data?.avg_return_pct ?? 0))}</b>
      <small>{Number(data?.trades ?? 0)} trades · win {formatPct(Number(data?.win_rate ?? 0))}</small>
    </div>
  );
}
