import { GitBranch, RotateCcw, Trophy, CheckCircle, XCircle, AlertTriangle } from 'lucide-react';
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
  promotion_eligible?: boolean | Record<string, unknown>;
};

type RollbackEvent = {
  event_id: string;
  parent_gene_id: string;
  child_gene_id: string | null;
  period_start: string;
  period_end: string;
  rolled_back_at: string | null;
  reason: string;
  parent_performance: Record<string, unknown>;
  child_performance: Record<string, unknown> | null;
  parameter_diff: Array<Record<string, unknown>>;
};

export default function EvolutionPanel({
  comparisons,
  rollbacks,
  dryRunPreview,
  onDryRun,
  onApply,
  onPromote,
  onRollback,
}: {
  comparisons: Comparison[];
  rollbacks: RollbackEvent[];
  dryRunPreview?: Record<string, unknown> | null;
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
      {dryRunPreview && (
        <div className="review-card dry-run-card">
          <strong>Dry-run preview ready</strong>
          <span>预览已生成，但尚未创建 Challenger，也没有消费 optimization signals。</span>
          <div className="evolution-perf">
            <div><span>Proposals</span><b>{((dryRunPreview.proposals ?? []) as unknown[]).length}</b><small>可正式提案</small></div>
            <div><span>Skipped</span><b>{((dryRunPreview.skipped ?? []) as unknown[]).length}</b><small>未满足样本或置信度</small></div>
          </div>
        </div>
      )}
      {!comparisons.length && <p className="memory">暂无 Challenger。先运行 dry-run 审计信号，再按需正式提案。</p>}
      {comparisons.map((item) => (
        <div className="review-card evolution-card" key={item.event_id}>
          <strong>{item.parent_gene_id} → {item.child_gene_id ?? 'pending'}</strong>
          <span>{item.status} · {(item.parameter_diff ?? []).length} parameter changes · {(item.aggregated_signals ?? []).length} signal groups</span>

          {/* S6.3: Performance with cumulative curve */}
          <div className="evolution-perf">
            <PerfWithData label="Champion" data={item.parent_performance} />
            <PerfWithData label="Challenger" data={item.child_performance ?? undefined} />
          </div>

          {/* S6.3: Cumulative return mini-chart */}
          <CumulativeComparison
            parent={item.parent_performance}
            child={item.child_performance ?? undefined}
          />

          {/* S6.2: Parameter diff with percentage change */}
          <ParameterDiffTable diffs={item.parameter_diff ?? []} />

          {/* S6.4: Promotion eligibility criteria */}
          {item.child_gene_id && (
            <PromotionEligibilityCard
              eligibility={item.promotion_eligible}
              childGeneId={item.child_gene_id}
              onPromote={onPromote}
              onRollback={onRollback}
            />
          )}
        </div>
      ))}

      {/* S6.5: Rollback audit section */}
      {rollbacks && rollbacks.length > 0 && (
        <RollbackAudit rollbacks={rollbacks} />
      )}
    </div>
  );
}

/* S6.3: Performance with full metrics */
function PerfWithData({ label, data }: { label: string; data?: Record<string, unknown> }) {
  if (!data) return null;
  const trades = Number(data?.trades ?? 0);
  const avgReturn = Number(data?.avg_return_pct ?? 0);
  const winRate = Number(data?.win_rate ?? 0);
  const drawdown = Number(data?.worst_drawdown_pct ?? 0);
  const cumulative = Number(data?.cumulative_return ?? 0);
  return (
    <div className="perf-with-data">
      <span className="perf-label">{label}</span>
      <div className="perf-metrics">
        <span className="perf-return" style={{ color: avgReturn >= 0 ? '#10b981' : '#ef4444' }}>
          {formatPct(avgReturn)}
        </span>
        <span className="perf-sub">{trades} trades · win {formatPct(winRate)}</span>
        <span className="perf-sub">累计 {formatPct(cumulative)} · 回撤 {formatPct(drawdown)}</span>
      </div>
    </div>
  );
}

/* S6.3: Cumulative return comparison */
function CumulativeComparison({ parent, child }: { parent?: Record<string, unknown>; child?: Record<string, unknown> }) {
  const parentCurve = (parent?.cumulative_curve as number[] | undefined) ?? [];
  const childCurve = (child?.cumulative_curve as number[] | undefined) ?? [];
  if (!parentCurve.length && !childCurve.length) return null;

  const maxLen = Math.max(parentCurve.length, childCurve.length);
  if (maxLen < 2) return null;

  const allValues = [...parentCurve, ...childCurve];
  const minVal = Math.min(...allValues);
  const maxVal = Math.max(...allValues);
  const range = maxVal - minVal || 1;
  const width = 200;
  const height = 40;

  const toPath = (curve: number[]) => {
    if (curve.length < 2) return '';
    return curve.map((v, i) => {
      const x = (i / (curve.length - 1)) * width;
      const y = height - ((v - minVal) / range) * height;
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
  };

  return (
    <div className="cumulative-chart">
      <small>累计收益曲线</small>
      <svg viewBox={`0 0 ${width} ${height}`} className="cumulative-svg">
        {parentCurve.length >= 2 && <path d={toPath(parentCurve)} stroke="#60a5fa" strokeWidth="1.5" fill="none" />}
        {childCurve.length >= 2 && <path d={toPath(childCurve)} stroke="#f59e0b" strokeWidth="1.5" fill="none" />}
      </svg>
    </div>
  );
}

/* S6.2: Parameter diff with percentage and threshold */
function ParameterDiffTable({ diffs }: { diffs: Array<Record<string, unknown>> }) {
  if (!diffs.length) return null;
  return (
    <div className="param-diff-table">
      <div className="param-diff-header">
        <span>Parameter</span><span>Before</span><span>After</span><span>Change</span>
      </div>
      {diffs.map((diff) => {
        const pctChange = diff.pct_change as number | null;
        const exceeds = !!diff.exceeds_5pct_threshold;
        return (
          <div className="param-diff-row" key={String(diff.param)}>
            <span className="param-name">{String(diff.param)}</span>
            <span className="param-val">{formatParamVal(diff.before)}</span>
            <span className="param-val">{formatParamVal(diff.after)}</span>
            <span className={`param-change ${exceeds ? 'exceeds' : ''}`}>
              {pctChange !== null && pctChange !== undefined ? `${pctChange > 0 ? '+' : ''}${pctChange}%` : '—'}
              {exceeds && <AlertTriangle size={12} className="threshold-icon" />}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function formatParamVal(val: unknown): string {
  if (val === null || val === undefined) return '—';
  if (typeof val === 'number') return val.toFixed(4);
  return String(val);
}

/* S6.4: Promotion eligibility with criteria breakdown */
function PromotionEligibilityCard({
  eligibility,
  childGeneId,
  onPromote,
  onRollback,
}: {
  eligibility: boolean | Record<string, unknown> | undefined;
  childGeneId: string;
  onPromote: (id: string) => void;
  onRollback: (id: string) => void;
}) {
  if (!eligibility || typeof eligibility !== 'object') {
    return (
      <div className="chip-row">
        <button onClick={() => onPromote(childGeneId)}><Trophy size={15} /> Promote</button>
        <button onClick={() => onRollback(childGeneId)}><RotateCcw size={15} /> Rollback</button>
      </div>
    );
  }

  const eligible = !!eligibility.eligible;
  const criteria = (eligibility.criteria ?? []) as Array<Record<string, unknown>>;

  return (
    <div className="promotion-eligibility">
      <div className="promo-header">
        <span className={`promo-badge ${eligible ? 'pass' : 'fail'}`}>
          {eligible ? <CheckCircle size={14} /> : <XCircle size={14} />}
          {eligible ? '可推广' : '暂不可推广'}
        </span>
      </div>
      <div className="promo-criteria">
        {criteria.map((c) => (
          <div className={`promo-item ${c.pass ? 'pass' : 'fail'}`} key={String(c.name)}>
            <span className="promo-icon">{c.pass ? <CheckCircle size={12} /> : <XCircle size={12} />}</span>
            <span className="promo-label">{String(c.label)}</span>
            <span className="promo-value">{formatPromoValue(c)}</span>
          </div>
        ))}
      </div>
      <div className="chip-row">
        <button onClick={() => onPromote(childGeneId)} disabled={!eligible}>
          <Trophy size={15} /> Promote
        </button>
        <button onClick={() => onRollback(childGeneId)}>
          <RotateCcw size={15} /> Rollback
        </button>
      </div>
    </div>
  );
}

function formatPromoValue(c: Record<string, unknown>): string {
  const val = c.value;
  const threshold = c.threshold;
  const base = typeof val === 'number' && Math.abs(val) < 10 ? (val * 100).toFixed(0) + '%' : String(val);
  return threshold !== undefined && typeof threshold === 'number' ? `${base} / ≥${threshold}` : base;
}

/* S6.5: Rollback audit section */
function RollbackAudit({ rollbacks }: { rollbacks: RollbackEvent[] }) {
  if (!rollbacks.length) return null;
  return (
    <div className="rollback-audit">
      <h4><RotateCcw size={16} /> 回滚审计 ({rollbacks.length})</h4>
      {rollbacks.map((rb) => (
        <div className="rollback-item" key={rb.event_id}>
          <div className="rollback-header">
            <strong>{rb.parent_gene_id} → {rb.child_gene_id ?? '—'}</strong>
            <span className="rollback-reason">{rb.reason}</span>
            {rb.rolled_back_at && <small>{rb.rolled_back_at}</small>}
          </div>
          <div className="rollback-perf">
            <span>Parent: {formatPct(Number(rb.parent_performance?.avg_return_pct ?? 0))} · {Number(rb.parent_performance?.trades ?? 0)} trades</span>
            {rb.child_performance && (
              <span>Child: {formatPct(Number(rb.child_performance.avg_return_pct ?? 0))} · {Number(rb.child_performance.trades ?? 0)} trades</span>
            )}
          </div>
          {rb.parameter_diff && rb.parameter_diff.length > 0 && (
            <div className="rollback-params">
              {rb.parameter_diff.slice(0, 4).map((d) => (
                <span key={String(d.param)}>{String(d.param)}: {formatParamVal(d.before)} → {formatParamVal(d.after)}</span>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
