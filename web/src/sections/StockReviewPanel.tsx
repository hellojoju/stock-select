import { useState } from 'react';
import { formatPct } from '../lib/format';
import type { FactorItem, ReviewDecision, ReviewEvidence, ReviewSignal } from '../types';

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:18425';
const VISIBILITY_LABEL: Record<string, string> = { PREOPEN_VISIBLE: '盘前可见', POSTCLOSE_OBSERVED: '收盘可见', POSTDECISION_EVENT: '事后事件' };
const FACTOR_LABEL: Record<string, string> = { technical: '技术', fundamental: '基本面', event: '事件', sector: '行业', risk: '风险', execution: '执行', earnings_surprise: '预期差', order_contract: '订单合同', business_kpi: '经营 KPI', risk_event: '风险事件', expectation: '市场预期' };

interface LlmReviewJson {
  summary: string;
  attribution: Array<{ claim: string; confidence: string }>;
  reason_check: {
    what_was_right: string[];
    what_was_wrong: string[];
    missing_signals: string[];
  };
}

export default function StockReviewPanel({ data }: { data?: Record<string, unknown> | null }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [signalStatus, setSignalStatus] = useState<Record<string, string>>({});

  if (!data) return <p className="memory">点击推荐列表中的股票查看单股复盘。</p>;

  const stock = (data.stock ?? {}) as Record<string, unknown>;
  const decisions = (data.decisions ?? []) as ReviewDecision[];
  const blindspot = data.blindspot ? (data.blindspot as Record<string, unknown>) : null;
  const facts = (data.domain_facts ?? {}) as Record<string, Array<Record<string, unknown>>>;

  async function handleAccept(signalId: string) {
    await fetch(`${API_BASE}/api/optimization-signals/${signalId}/accept`, { method: 'POST' });
    setSignalStatus((prev) => ({ ...prev, [signalId]: 'accepted' }));
  }
  async function handleReject(signalId: string) {
    await fetch(`${API_BASE}/api/optimization-signals/${signalId}/reject`, { method: 'POST' });
    setSignalStatus((prev) => ({ ...prev, [signalId]: 'rejected' }));
  }

  return (
    <div className="review-detail">
      <div className="stock-header">
        <h3>{String(stock.stock_code ?? '')} {String(stock.name ?? '')}</h3>
        <div className="stock-meta">
          {!!stock.industry && <span>行业: {String(stock.industry)}</span>}
          {blindspot && (
            <span className="blindspot-note">
              盲点: 涨幅榜 #{String(blindspot.rank ?? '')} · {formatPct(Number(blindspot.return_pct ?? 0))}
              {!!blindspot.missed_stage && ` · ${String(blindspot.missed_stage)}`}
            </span>
          )}
        </div>
      </div>

      {decisions.map((decision) => {
        const isOpen = expanded === decision.review_id;
        const llmJson = parseLlmJson(decision.llm_json);
        return (
          <div className={`decision-card ${isOpen ? 'expanded' : ''}`} key={decision.review_id}>
            <div className="decision-header" onClick={() => setExpanded(isOpen ? null : decision.review_id)}>
              <div>
                <strong>{decision.strategy_gene_id}</strong>
                <span className={`verdict-chip verdict-${decision.verdict}`}>{decision.verdict}</span>
              </div>
              <div className="decision-meta">
                <span>driver: {decision.primary_driver}</span>
                <span className={decision.return_pct >= 0 ? 'up' : 'down'}>
                  {formatPct(decision.return_pct)}
                </span>
                <span className="rel-return">{formatPct(decision.relative_return_pct)} vs 指数</span>
              </div>
            </div>

            {isOpen && (
              <div className="decision-body">
                <p className="decision-summary">{decision.summary}</p>

                {/* Factor Checks */}
                {decision.factor_items?.length > 0 && (
                  <section className="detail-section">
                    <h4>因子检查</h4>
                    <table className="detail-table factor-table">
                      <thead><tr><th>因子</th><th>判决</th><th>贡献分</th><th>错误类型</th><th>置信度</th></tr></thead>
                      <tbody>
                        {decision.factor_items.map((f, i) => (
                          <tr key={i}>
                            <td>{FACTOR_LABEL[f.factor_type] ?? f.factor_type}</td>
                            <td><span className={`verdict-badge verdict-${f.verdict}`}>{f.verdict}</span></td>
                            <td>{f.contribution_score > 0 ? '+' : ''}{f.contribution_score.toFixed(2)}</td>
                            <td>{f.error_type ? <span className="error-chip">{f.error_type}</span> : <span className="empty-value">—</span>}</td>
                            <td><span className={`conf-badge conf-${f.confidence}`}>{f.confidence}</span></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </section>
                )}

                {/* Evidence */}
                {decision.evidence?.length > 0 && (
                  <section className="detail-section">
                    <h4>证据溯源</h4>
                    <div className="evidence-list">
                      {decision.evidence.map((ev, i) => (
                        <EvidenceRow key={i} evidence={ev} />
                      ))}
                    </div>
                  </section>
                )}

                {/* Errors */}
                {decision.errors?.length > 0 && (
                  <section className="detail-section">
                    <h4>归因错误</h4>
                    <div className="errors-list">
                      {decision.errors.map((err, i) => (
                        <div className="error-chip-row" key={i}>
                          <span className="error-chip">{err.error_type}</span>
                          <span className="severity-bar" style={{ width: `${err.severity * 100}%` }} />
                          <small>{err.confidence > 0.7 ? '高置信' : err.confidence > 0.4 ? '中置信' : '低置信'}</small>
                        </div>
                      ))}
                    </div>
                  </section>
                )}

                {/* Optimization Signals */}
                {decision.optimization_signals?.length > 0 && (
                  <section className="detail-section">
                    <h4>优化信号</h4>
                    {decision.optimization_signals.map((s, i) => (
                      <SignalRow key={i} signal={s} signalStatus={signalStatus} onAccept={handleAccept} onReject={handleReject} />
                    ))}
                  </section>
                )}

                {/* LLM Attribution */}
                {llmJson && (
                  <section className="detail-section llm-attribution">
                    <h4>LLM 归因</h4>
                    <p className="llm-summary">{llmJson.summary}</p>
                    <table className="detail-table">
                      <thead><tr><th>归因</th><th>置信度</th></tr></thead>
                      <tbody>
                        {(llmJson.attribution ?? []).map((a, i: number) => (
                          <tr key={i}>
                            <td>{a.claim}</td>
                            <td><span className={`conf-badge conf-${a.confidence}`}>{a.confidence}</span></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <div className="reason-check">
                      <div className="reason-col">
                        <strong>做对的</strong>
                        <ul>{(llmJson.reason_check?.what_was_right ?? []).map((s: string, i: number) => <li key={i}>{s}</li>)}</ul>
                      </div>
                      <div className="reason-col">
                        <strong>做错的</strong>
                        <ul>{(llmJson.reason_check?.what_was_wrong ?? []).map((s: string, i: number) => <li key={i}>{s}</li>)}</ul>
                      </div>
                      <div className="reason-col">
                        <strong>遗漏信号</strong>
                        <ul>{(llmJson.reason_check?.missing_signals ?? []).map((s: string, i: number) => <li key={i}>{s}</li>)}</ul>
                      </div>
                    </div>
                  </section>
                )}
              </div>
            )}
          </div>
        );
      })}

      <EvidenceFacts facts={facts} />
    </div>
  );
}

function EvidenceRow({ evidence }: { evidence: ReviewEvidence }) {
  let payload: Record<string, unknown> = {};
  try { payload = JSON.parse(evidence.payload_json); } catch { /* ignore */ }
  const rp = payload.return_pct;
  const returnVal = typeof rp === 'number' ? formatPct(rp) : String(payload.close ?? payload.technical_score ?? payload.net_profit ?? '');
  return (
    <div className="evidence-row">
      <div className="evidence-info">
        <span className="evidence-source">{evidence.source_type.replace(/_/g, ' ')}</span>
        {returnVal && <span className="evidence-value">{returnVal}</span>}
      </div>
      <span className={`vis-badge vis-${evidence.visibility === 'PREOPEN_VISIBLE' ? 'preopen' : evidence.visibility === 'POSTCLOSE_OBSERVED' ? 'postclose' : 'postevent'}`}>
        {VISIBILITY_LABEL[evidence.visibility] ?? evidence.visibility}
      </span>
      <span className={`conf-badge conf-${evidence.confidence}`}>{evidence.confidence}</span>
    </div>
  );
}

function SignalRow({ signal, signalStatus, onAccept, onReject }: {
  signal: ReviewSignal;
  signalStatus: Record<string, string>;
  onAccept: (id: string) => void;
  onReject: (id: string) => void;
}) {
  const status = signalStatus[signal.signal_id] ?? signal.status;
  return (
    <div className="signal-row-item">
      <div className="signal-info">
        <strong>{signal.signal_type.replace(/_/g, ' ')}</strong>
        {signal.param_name && <span> / {signal.param_name}</span>}
        <span className="signal-direction">→ {signal.direction}</span>
        <span className="signal-strength">强度 {signal.strength.toFixed(2)}</span>
      </div>
      <div className="signal-actions">
        {status === 'candidate' || status === 'open' ? (
          <>
            <button className="btn-sm btn-accept" onClick={() => onAccept(signal.signal_id)}>接受</button>
            <button className="btn-sm btn-reject" onClick={() => onReject(signal.signal_id)}>拒绝</button>
          </>
        ) : status === 'accepted' ? (
          <span className="accepted-label">已接受</span>
        ) : (
          <span className="rejected-label">已拒绝</span>
        )}
      </div>
    </div>
  );
}

function parseLlmJson(raw?: string): LlmReviewJson | null {
  if (!raw) return null;
  try { const parsed = JSON.parse(raw) as LlmReviewJson; return parsed; } catch { return null; }
}

/* === Domain Facts (kept from original) === */

function EvidenceFacts({ facts }: { facts: Record<string, Array<Record<string, unknown>>> }) {
  const groups = [
    { title: '财报实际值', rows: (facts.financial_actuals ?? []).map((item) => ({ label: String(item.report_period ?? '-'), value: formatAmount(Number(item.net_profit)), source: item.source, meta: `as-of ${String(item.as_of_date ?? item.ann_date ?? '-')}` })) },
    { title: '市场预期', rows: (facts.analyst_expectations ?? []).map((item) => ({ label: String(item.forecast_period ?? '-'), value: formatAmount(Number(item.forecast_net_profit)), source: item.source, meta: String(item.org_name ?? item.report_date ?? '') })) },
    { title: '预期差', rows: (facts.earnings_surprises ?? []).map((item) => ({ label: String(item.surprise_type ?? 'surprise'), value: formatPct(Number(item.surprise_pct ?? item.net_profit_surprise_pct)), source: item.expectation_source, meta: `as-of ${String(item.as_of_date ?? item.ann_date ?? '-')}` })) },
    { title: '订单/合同', rows: (facts.order_contract_events ?? []).map((item) => ({ label: String(item.title ?? item.event_type ?? 'event'), value: formatAmount(Number(item.contract_amount)), source: item.source, meta: `impact ${Number(item.impact_score ?? 0).toFixed(2)}` })) },
    { title: '经营 KPI', rows: (facts.business_kpi_actuals ?? []).map((item) => ({ label: String(item.kpi_name), value: String(item.kpi_value ?? '-'), source: item.source, meta: `YoY ${formatPct(Number(item.kpi_yoy ?? item.yoy_pct))}` })) },
    { title: '风险事件', rows: (facts.risk_events ?? []).map((item) => ({ label: String(item.title ?? item.risk_type ?? 'risk'), value: String(item.severity ?? '-'), source: item.source, meta: `impact ${Number(item.impact_score ?? 0).toFixed(2)}` })) },
  ];
  return (
    <div className="evidence-table">
      {groups.map((group) => (
        <section className="evidence-group" key={group.title}>
          <h4>{group.title}</h4>
          {group.rows.length ? group.rows.slice(0, 4).map((row, index) => (
            <div key={`${group.title}-${index}`}><span>{row.label}</span><b>{row.value}</b><small>{String(row.source ?? '')} {row.meta ? `· ${row.meta}` : ''}</small></div>
          )) : <p className="missing-evidence">缺失，不代表负面结论</p>}
        </section>
      ))}
    </div>
  );
}

function formatAmount(value?: number) {
  if (value === undefined || value === null || Number.isNaN(value)) return '-';
  if (Math.abs(value) >= 100_000_000) return `${(value / 100_000_000).toFixed(1)} 亿`;
  return `${value.toFixed(0)}`;
}
