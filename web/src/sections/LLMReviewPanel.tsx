import { useState } from 'react';
import type { LLMReview } from '../types';

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:18425';

export default function LLMReviewPanel({ reviews }: { reviews: LLMReview[] }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [signalStatus, setSignalStatus] = useState<Record<string, string>>({});

  if (!reviews || reviews.length === 0) {
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
      {reviews.map((r) => (
        <div key={r.llm_review_id} className={`llm-review-card ${expanded === r.llm_review_id ? 'expanded' : ''}`}>
          <div className="llm-review-header" onClick={() => setExpanded(
            expanded === r.llm_review_id ? null : r.llm_review_id
          )}>
            <span className="llm-review-id">{r.decision_review_id}</span>
            <span className={`llm-badge ${r.status}`}>{r.status}</span>
          </div>
          {expanded === r.llm_review_id && (
            <div className="llm-review-body">
              <p className="llm-summary">{r.summary}</p>

              <h4>归因分析</h4>
              <table className="attribution-table">
                <thead><tr><th>归因</th><th>置信度</th></tr></thead>
                <tbody>
                  {r.attribution.map((a, i) => (
                    <tr key={i}>
                      <td>{a.claim}</td>
                      <td><span className={`confidence-badge ${a.confidence}`}>{a.confidence}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <div className="reason-section">
                <h4>做对的</h4>
                <ul>{r.reason_check.what_was_right.map((s, i) => <li key={i}>{s}</li>)}</ul>
                <h4>做错的</h4>
                <ul>{r.reason_check.what_was_wrong.map((s, i) => <li key={i}>{s}</li>)}</ul>
                <h4>遗漏信号</h4>
                <ul>{r.reason_check.missing_signals.map((s, i) => <li key={i}>{s}</li>)}</ul>
              </div>

              {r.suggested_signals.length > 0 && (
                <div className="signal-section">
                  <h4>优化建议</h4>
                  {r.suggested_signals.map((s, i) => {
                    const currentStatus = signalStatus[s.signal_id] ?? s.status;
                    return (
                      <div key={i} className="signal-row">
                        <span>{s.signal_type} / {s.param_name} → {s.direction} (强度: {s.strength})</span>
                        {currentStatus === 'candidate' && (
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
                    {' · '}费用: ${r.token_usage.estimated_cost.toFixed(4)}
                  </small>
                </div>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
