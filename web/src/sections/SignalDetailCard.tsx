import { ChevronDown, ChevronRight, FileText, ShieldAlert } from 'lucide-react';
import { useState } from 'react';
import type { SignalDetail as SignalDetailType } from '../types';

export default function SignalDetailCard({ signal }: { signal: SignalDetailType }) {
  const [expanded, setExpanded] = useState(false);

  const statusColor = signal.status === 'consumed' ? '#f59e0b' : signal.status === 'open' ? '#10b981' : signal.status === 'rejected' ? '#ef4444' : '#6b7280';

  return (
    <div className="signal-detail-card">
      <div className="signal-header" onClick={() => setExpanded(!expanded)}>
        <span className="signal-expand-icon">
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>
        <span className="signal-type-badge">{signal.signal_type}</span>
        <span className="signal-param">{signal.param_name || '—'}</span>
        <span className="signal-direction">{signal.direction}</span>
        <span className="signal-strength">{signal.strength.toFixed(2)}</span>
        <span className="signal-status" style={{ color: statusColor }}>{signal.status}</span>
      </div>
      {expanded && (
        <div className="signal-body">
          <div className="signal-section">
            <h4>基本信息</h4>
            <div className="signal-kv">
              <span>Signal ID</span><code>{signal.signal_id}</code>
              <span>Scope</span><code>{signal.scope}{signal.scope_key ? `: ${signal.scope_key}` : ''}</code>
              <span>Confidence</span><span>{signal.confidence.toFixed(2)}</span>
              <span>Sample Size</span><span>{signal.sample_size}</span>
              <span>Reason</span><span>{signal.reason}</span>
              {signal.created_at && (<><span>Created</span><span>{signal.created_at}</span></>)}
            </div>
          </div>

          {signal.source_detail && (
            <div className="signal-section">
              <h4><FileText size={14} /> 来源 {signal.source_type}</h4>
              <div className="signal-kv">
                <span>Source ID</span><code>{signal.source_id}</code>
                {!!signal.source_detail.trading_date && (<><span>Trading Date</span><span>{String(signal.source_detail.trading_date)}</span></>)}
                {!!signal.source_detail.stock_code && (<><span>Stock</span><span>{String(signal.source_detail.stock_code)}</span></>)}
                {!!signal.source_detail.verdict && (<><span>Verdict</span><span>{String(signal.source_detail.verdict)}</span></>)}
                {signal.source_detail.return_pct !== undefined && (<><span>Return</span><span>{Number(signal.source_detail.return_pct).toFixed(2)}%</span></>)}
                {!!signal.source_detail.summary && (<><span>Summary</span><span>{String(signal.source_detail.summary)}</span></>)}
              </div>
            </div>
          )}

          {signal.evidence_details && signal.evidence_details.length > 0 && (
            <div className="signal-section">
              <h4><ShieldAlert size={14} /> 关联证据 ({signal.evidence_details.length})</h4>
              {signal.evidence_details.map((ev) => (
                <div className="evidence-item" key={String(ev.id)}>
                  <span className={`evidence-type-badge type-${String(ev.type)}`}>{String(ev.type)}</span>
                  <span>{formatEvidenceDetail(ev)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function formatEvidenceDetail(ev: Record<string, unknown>): string {
  const detail = (ev.detail ?? {}) as Record<string, unknown>;
  if (ev.type === 'document') {
    return `${String(detail.title ?? '')} (${String(detail.source ?? '')}, ${String(detail.published_at ?? '')})`;
  }
  if (ev.type === 'review_evidence') {
    return `${String(detail.source_type ?? '')} · ${String(detail.visibility ?? '')}`;
  }
  if (ev.type === 'graph_edge') {
    return `${String(detail.type ?? '')}: ${String(detail.source_node_id ?? '')} → ${String(detail.target_node_id ?? '')}`;
  }
  return String(ev.id);
}
