import { useState } from 'react';
import type { AnalystReview } from '../types';

const ANALYST_LABELS: Record<string, string> = {
  trend_follower: '趋势追踪',
  fundamental_check: '基本面核查',
  risk_scanner: '风险排查',
  contrarian: '逆向思辨',
};

const ANALYST_COLORS: Record<string, string> = {
  trend_follower: '#22c55e',
  fundamental_check: '#3b82f6',
  risk_scanner: '#ef4444',
  contrarian: '#f59e0b',
};

function VerdictBadge({ verdict }: { verdict: string }) {
  const cls =
    verdict === 'AGREE' ? 'badge-agree' :
    verdict === 'DISAGREE' ? 'badge-disagree' :
    'badge-neutral';
  return <span className={`verdict-badge ${cls}`}>{verdict}</span>;
}

function AnalystLabel({ analystKey }: { analystKey: string }) {
  const label = ANALYST_LABELS[analystKey] ?? analystKey;
  const color = ANALYST_COLORS[analystKey] ?? '#888';
  return <span style={{ color, fontWeight: 600 }}>{label}</span>;
}

export default function AnalystReviewPanel({ reviews }: { reviews: AnalystReview[] }) {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const safeReviews = Array.isArray(reviews) ? reviews : [];

  if (safeReviews.length === 0) {
    return <div className="empty-state">暂无分析师评审结果</div>;
  }

  // Group by analyst_key
  const grouped: Record<string, AnalystReview[]> = {};
  for (const r of safeReviews) {
    if (!grouped[r.analyst_key]) grouped[r.analyst_key] = [];
    grouped[r.analyst_key].push(r);
  }

  const analystOrder = ['trend_follower', 'fundamental_check', 'risk_scanner', 'contrarian'];

  function toggleCollapse(key: string) {
    setCollapsed((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  return (
    <div className="analyst-review-grid">
      {analystOrder.map((key) => {
        const items = grouped[key] ?? [];
        if (items.length === 0) return null;
        const isCollapsed = collapsed[key];
        const avgConf = items.reduce((s, r) => s + Number(r.confidence ?? 0), 0) / items.length;
        const agreeRate = items.filter((r) => r.verdict === 'AGREE').length / items.length;

        return (
          <div key={key} className="analyst-column" style={{ borderTopColor: ANALYST_COLORS[key] ?? '#888' }}>
            <div className="analyst-column-header" onClick={() => toggleCollapse(key)}>
              <div>
                <AnalystLabel analystKey={key} />
                <span className="analyst-stats">
                  {Math.round(agreeRate * 100)}% 赞同 · 置信 {avgConf.toFixed(2)}
                </span>
              </div>
              <span className="collapse-arrow">{isCollapsed ? '▶' : '▼'}</span>
            </div>

            {!isCollapsed && (
              <div className="analyst-column-body">
                {items.map((r) => (
                  <div key={r.analyst_review_id} className="analyst-item">
                    <div className="analyst-item-header">
                      <strong>{r.stock_name ?? r.stock_code}</strong>
                      <VerdictBadge verdict={r.verdict} />
                      <span className="confidence-num">{Number(r.confidence ?? 0).toFixed(2)}</span>
                    </div>
                    <ul className="analyst-reasoning">
                      {(Array.isArray(r.reasoning) ? r.reasoning : []).map((reason, i) => (
                        <li key={i}>{reason}</li>
                      ))}
                    </ul>
                    {Array.isArray(r.suggested_errors) && r.suggested_errors.length > 0 && (
                      <div className="analyst-errors">
                        {r.suggested_errors.map((e, i) => (
                          <span key={i} className="error-chip">{e}</span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
