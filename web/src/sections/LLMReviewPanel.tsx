import { useState } from 'react';
import { API_BASE } from '../api/client';
import type { LLMReview } from '../types';

export default function LLMReviewPanel({ reviews }: { reviews: LLMReview[] }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [signalStatus, setSignalStatus] = useState<Record<string, string>>({});

  const safeReviews = Array.isArray(reviews) ? reviews : [];

  if (safeReviews.length === 0) {
    return <div className="empty-state">暂无 LLM 复盘结果（默认关闭）</div>;
  }

  async function handleAccept(signalId: string) {
    await fetch(`${API_BASE}/api/optimization-signals/${signalId}/accept`, { method: 'POST' });
    setSignalStatus((prev) => ({ ...prev, [signalId]: 'accepted' }));
  }

  async function handleReject(signalId: string) {
    await fetch(`${API_BASE}/api/optimization-signals/${signalId}/reject`, { method: 'POST' });
    setSignalStatus((prev) => ({ ...prev, [signalId]: 'rejected' }));
  }

  return (
    <div className="llm-review-list">
      {safeReviews.map((r, reviewIndex) => {
        const reviewId = r.llm_review_id || `${r.decision_review_id || 'llm'}-${reviewIndex}`;
        const attribution = Array.isArray(r.attribution) ? r.attribution : [];
        const reasonCheck = r.reason_check ?? { what_was_right: [], what_was_wrong: [], missing_signals: [] };
        const whatWasRight = Array.isArray(reasonCheck.what_was_right) ? reasonCheck.what_was_right : [];
        const whatWasWrong = Array.isArray(reasonCheck.what_was_wrong) ? reasonCheck.what_was_wrong : [];
        const missingSignals = Array.isArray(reasonCheck.missing_signals) ? reasonCheck.missing_signals : [];
        const suggestedSignals = Array.isArray(r.suggested_signals) ? r.suggested_signals : [];
        return (
        <div key={reviewId} className={`llm-review-card ${expanded === reviewId ? 'expanded' : ''}`}>
          <div className="llm-review-header" onClick={() => setExpanded(
            expanded === reviewId ? null : reviewId
          )}>
            <span className="llm-review-id">{r.decision_review_id || 'LLM Review'}</span>
            <span className={`llm-badge ${r.status}`}>{r.status}</span>
          </div>
          {expanded === reviewId && (
            <div className="llm-review-body">
              <p className="llm-summary">{r.summary || 'LLM 未返回摘要。'}</p>

              <h4>归因分析</h4>
              <table className="attribution-table">
                <thead><tr><th>归因</th><th>置信度</th></tr></thead>
                <tbody>
                  {attribution.length ? attribution.map((a, i) => (
                    <tr key={i}>
                      <td>{a.claim || '-'}</td>
                      <td><span className={`confidence-badge ${a.confidence || 'AMBIGUOUS'}`}>{a.confidence || 'AMBIGUOUS'}</span></td>
                    </tr>
                  )) : (
                    <tr><td colSpan={2} className="empty-value">暂无归因条目</td></tr>
                  )}
                </tbody>
              </table>

              <div className="reason-section">
                <h4>做对的</h4>
                <SafeList items={whatWasRight} />
                <h4>做错的</h4>
                <SafeList items={whatWasWrong} />
                <h4>遗漏信号</h4>
                <SafeList items={missingSignals} />
              </div>

              {r.evidence_references && r.evidence_references.length > 0 && (
                <div className="evidence-references-section">
                  <h4>证据引用</h4>
                  <div className="evidence-ref-list">
                    {r.evidence_references.map((ref: Record<string, unknown>, i: number) => (
                      <div className="evidence-ref-item" key={i}>
                        <span className="evidence-ref-type">{String(ref.source_type ?? ref.type ?? 'evidence')}</span>
                        {!!ref.title && <span className="evidence-ref-title">{String(ref.title)}</span>}
                        {!!ref.confidence && (
                          <span className={`conf-badge conf-${String(ref.confidence)}`}>{String(ref.confidence)}</span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {suggestedSignals.length > 0 && (
                <div className="signal-section">
                  <h4>优化建议</h4>
                  {suggestedSignals.map((s, i) => {
                    const currentStatus = signalStatus[s.signal_id] ?? s.status;
                    return (
                      <div key={i} className="signal-row">
                        <span>{s.signal_type || 'signal'} / {s.param_name || '-'} → {s.direction || '-'} (强度: {Number(s.strength ?? 0).toFixed(2)})</span>
                        {s.signal_id && currentStatus === 'candidate' && (
                          <div className="signal-actions">
                            <button className="btn-accept" onClick={() => handleAccept(s.signal_id)}>接受</button>
                            <button className="btn-reject" onClick={() => handleReject(s.signal_id)}>拒绝</button>
                          </div>
                        )}
                        {currentStatus === 'accepted' && <span className="accepted-label">已接受</span>}
                        {currentStatus === 'rejected' && <span className="rejected-label">已拒绝</span>}
                      </div>
                    );
                  })}
                </div>
              )}

              {r.token_usage && (
                <div className="token-usage">
                  <small>
                    Token: {r.token_usage.prompt_tokens}P / {r.token_usage.completion_tokens}C
                    {' · '}费用: ${Number(r.token_usage.estimated_cost ?? 0).toFixed(4)}
                  </small>
                </div>
              )}
            </div>
          )}
        </div>
      );})}
    </div>
  );
}

function SafeList({ items }: { items: string[] }) {
  if (!items.length) return <p className="empty-value">暂无</p>;
  return <ul>{items.map((s, i) => <li key={i}>{s}</li>)}</ul>;
}
