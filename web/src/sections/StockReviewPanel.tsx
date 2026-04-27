import { useState } from 'react';
import { BrainCircuit, X, ChevronDown, ChevronRight, TrendingUp, TrendingDown, ArrowUpRight, ArrowDownRight } from 'lucide-react';
import { formatPct } from '../lib/format';
import type { FactorItem, ReviewDecision, ReviewEvidence, ReviewSignal } from '../types';

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:18425';
const VISIBILITY_LABEL: Record<string, string> = { PREOPEN_VISIBLE: '盘前可见', POSTCLOSE_OBSERVED: '收盘可见', POSTDECISION_EVENT: '事后事件' };
const FACTOR_LABEL: Record<string, string> = { technical: '技术面', fundamental: '基本面', event: '事件面', sector: '行业面', risk: '风险面', execution: '执行', earnings_surprise: '预期差', order_contract: '订单合同', business_kpi: '经营 KPI', risk_event: '风险事件', expectation: '市场预期' };
const GENE_LABEL: Record<string, string> = { gene_hypothetical: '假设性分析' };

/** 将 gene_id 转为可读名称 */
function geneName(geneId: string): string {
  const direct = GENE_LABEL[geneId];
  if (direct) return direct;
  return geneId.replace(/^gene_/, '');
}

/** 将 verdict 转为中文（兼容后端返回的中文和英文） */
function verdictLabel(v: string): string {
  if (v === 'RIGHT' || v === '正确') return '正确';
  if (v === 'WRONG' || v === '错误') return '错误';
  if (v === 'MIXED' || v === 'NEUTRAL' || v === '中性') return '中性';
  return v;
}

/** 将 confidence 转为中文 */
function confidenceLabel(c: string): string {
  if (c === 'EXTRACTED' || c === '提取') return '提取';
  if (c === 'INFERRED' || c === '推断') return '推断';
  return c;
}

interface ReviewSummary {
  stock_code: string;
  stock_name: string;
  trading_date: string;
  return_pct: number;
  verdict: string;
  one_line_conclusion: string;
  what_happened: string;
  why_we_picked_it: string;
  supporting_evidence: Array<{ title: string; source: string; source_type: string; source_url?: string; published_at?: string }>;
  contradicting_evidence: Array<{ title: string; source: string; source_type: string; source_url?: string; published_at?: string }>;
  where_we_were_wrong: Array<{ error_type: string; label: string; severity: number }>;
  should_we_blame_strategy: string;
  what_to_do_next: string[];
}

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
  const [expandedFactor, setExpandedFactor] = useState<number | null>(null);
  const [aiOpen, setAiOpen] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiSummary, setAiSummary] = useState<string | null>(data?.ai_summary as string | null ?? null);
  const [expandedCard, setExpandedCard] = useState<string | null>(null);

  if (!data) return <p className="memory">点击推荐列表中的股票查看单股复盘。</p>;

  const stock = (data.stock ?? {}) as Record<string, unknown>;
  const decisions = (data.decisions ?? []) as ReviewDecision[];
  const blindspot = data.blindspot ? (data.blindspot as Record<string, unknown>) : null;
  const facts = (data.domain_facts ?? {}) as Record<string, Array<Record<string, unknown>>>;
  const reviewSummaryRaw = data.review_summary as { status?: string; [key: string]: unknown } | undefined;
  const reviewSummary = reviewSummaryRaw && reviewSummaryRaw.status !== 'no_review'
    ? reviewSummaryRaw as unknown as ReviewSummary
    : null;
  const relatedDocs = data.related_documents ? (data.related_documents as Array<Record<string, unknown>>) : null;
  const isHypo = data.hypothetical === true;

  // Extract deep review data
  const marketOverview = data.market_overview as Record<string, unknown> | undefined;
  const sentimentCycle = data.sentiment_cycle as Record<string, unknown> | undefined;
  const sectorAnalysis = data.sector_analysis as Record<string, unknown> | undefined;
  const customSectorTags = data.custom_sector_tags as string[] | undefined;
  const stockQuant = data.stock_quant as Record<string, unknown> | undefined;
  const capitalFlow = data.capital_flow as Record<string, unknown> | undefined;
  const psychologyReview = data.psychology_review as Record<string, unknown> | undefined;
  const nextDayPlan = data.next_day_plan as Record<string, unknown> | undefined;

  // Generate one-line summary
  const oneLineSummary = generateOneLineSummary(stock, marketOverview, sentimentCycle, stockQuant, capitalFlow, sectorAnalysis);

  async function handleAccept(signalId: string) {
    await fetch(`${API_BASE}/api/optimization-signals/${signalId}/accept`, { method: 'POST' });
    setSignalStatus((prev) => ({ ...prev, [signalId]: 'accepted' }));
  }
  async function handleReject(signalId: string) {
    await fetch(`${API_BASE}/api/optimization-signals/${signalId}/reject`, { method: 'POST' });
    setSignalStatus((prev) => ({ ...prev, [signalId]: 'rejected' }));
  }

  async function triggerAiSummary() {
    if (aiSummary || aiLoading) return;
    const stockCode = String(stock.stock_code ?? '');
    const tradingDate = String((data as Record<string, unknown> | undefined)?.trading_date ?? '');
    if (!stockCode || !tradingDate) return;
    setAiLoading(true);
    try {
      const resp = await fetch(`${API_BASE}/api/reviews/stocks/${stockCode}?date=${tradingDate}`);
      const d = await resp.json();
      setAiSummary(d.ai_summary ?? null);
    } catch { /* ignore */ }
    setAiLoading(false);
  }

  return (
    <div className="review-detail">
      <div className="stock-header">
        <div className="stock-title-row">
          <h3>
            {String(stock.stock_code ?? '')}
            {!!stock.name && String(stock.name) !== String(stock.stock_code) && ` ${String(stock.name)}`}
          </h3>
          <button className="ai-trigger-btn" onClick={() => { setAiOpen(true); triggerAiSummary(); }} title="AI 分析解读">
            <BrainCircuit size={18} />
          </button>
        </div>
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

      {data.hypothetical === true && (
        <div className="hypothetical-notice">
          <span className="hypothetical-icon">⚠</span>
          <span>该股票当日未被策略选中，以下为基于实时多维度信号的分析结果</span>
        </div>
      )}

      {reviewSummary && <ReviewSummaryCard summary={reviewSummary} />}

      {relatedDocs && relatedDocs.length > 0 && (
        <section className="detail-section">
          <h4>相关新闻/公告（{relatedDocs.length}）</h4>
          <div className="related-docs-list">
            {relatedDocs.slice(0, 10).map((doc, i) => {
              const sourceType = String(doc.source_type ?? '');
              const eventCat = String(doc.event_category ?? 'other');
              return (
                <div className="related-doc-item" key={i}>
                  <span className={`doc-source-type type-${sourceType.replace(/_/g, '')}`}>
                    {sourceType.replace(/_/g, ' ')}
                  </span>
                  {!!doc.title && <span className="doc-title">{String(doc.title)}</span>}
                  {!!doc.event_category && (
                    <span className={`doc-event-cat cat-${eventCat}`}>{eventCat}</span>
                  )}
                  {!!doc.published_at && <small className="doc-date">{String(doc.published_at)}</small>}
                  {!!doc.source_url && (
                    <a className="doc-link" href={String(doc.source_url)} target="_blank" rel="noopener noreferrer">
                      原文 ↗
                    </a>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* Custom sector tags */}
      {customSectorTags && customSectorTags.length > 0 && (
        <div className="custom-sector-tag-row">
          {customSectorTags.map((tag) => {
            const labelMap: Record<string, string> = { limit_up_today: '涨停', high_turnover_today: '高换手', high_turnover_10d: '持续高换手', unusual_10d: '异动放量', large_amount: '大成交额' };
            return <span className="sector-tag-badge" key={tag}>{labelMap[tag] ?? tag}</span>;
          })}
        </div>
      )}

      {/* One-line summary */}
      {oneLineSummary && (
        <div className="one-line-summary">
          <span className="summary-icon">📊</span>
          <span>{oneLineSummary}</span>
        </div>
      )}

      {/* Deep Review: collapsible cards */}
      <CollapsibleCard
        title="市场环境"
        icon="market"
        summary={marketSummary(marketOverview)}
        expanded={expandedCard === 'market'}
        onToggle={() => setExpandedCard(expandedCard === 'market' ? null : 'market')}
      >
        {marketOverview && <MarketOverviewCard data={marketOverview} />}
      </CollapsibleCard>

      <CollapsibleCard
        title="情绪周期"
        icon="sentiment"
        summary={sentimentSummary(sentimentCycle)}
        expanded={expandedCard === 'sentiment'}
        onToggle={() => setExpandedCard(expandedCard === 'sentiment' ? null : 'sentiment')}
      >
        {sentimentCycle && <SentimentCycleCard data={sentimentCycle} />}
      </CollapsibleCard>

      <CollapsibleCard
        title="板块联动"
        icon="sector"
        summary={sectorSummary(sectorAnalysis, stock)}
        expanded={expandedCard === 'sector'}
        onToggle={() => setExpandedCard(expandedCard === 'sector' ? null : 'sector')}
      >
        {sectorAnalysis && <SectorAnalysisDetail data={sectorAnalysis} stockCode={String(stock.stock_code ?? '')} />}
      </CollapsibleCard>

      <CollapsibleCard
        title="资金流向"
        icon="capital"
        summary={capitalFlowSummary(capitalFlow)}
        expanded={expandedCard === 'capital'}
        onToggle={() => setExpandedCard(expandedCard === 'capital' ? null : 'capital')}
      >
        {capitalFlow && <CapitalFlowDetailCard data={capitalFlow} />}
      </CollapsibleCard>

      <CollapsibleCard
        title="量价形态"
        icon="quant"
        summary={quantSummary(stockQuant)}
        expanded={expandedCard === 'quant'}
        onToggle={() => setExpandedCard(expandedCard === 'quant' ? null : 'quant')}
      >
        {stockQuant && <StockQuantCard data={stockQuant} />}
      </CollapsibleCard>

      <CollapsibleCard
        title="交易心理"
        icon="psychology"
        summary={psychologySummary(psychologyReview)}
        expanded={expandedCard === 'psychology'}
        onToggle={() => setExpandedCard(expandedCard === 'psychology' ? null : 'psychology')}
      >
        {psychologyReview && <PsychologyReviewCard data={psychologyReview} />}
      </CollapsibleCard>

      <CollapsibleCard
        title="次日预案"
        icon="plan"
        summary={planSummary(nextDayPlan)}
        expanded={expandedCard === 'plan'}
        onToggle={() => setExpandedCard(expandedCard === 'plan' ? null : 'plan')}
      >
        {nextDayPlan && <NextDayPlanCard data={nextDayPlan} />}
      </CollapsibleCard>

      {decisions.map((decision) => {
        const isOpen = expanded === decision.review_id;
        const llmJson = parseLlmJson(decision.llm_json);
        // 假设性复盘始终展开
        const alwaysOpen = isHypo;
        return (
          <div className={`decision-card ${alwaysOpen || isOpen ? 'expanded' : ''}`} key={decision.review_id}>
            <div className="decision-header" onClick={() => { if (!alwaysOpen) setExpanded(isOpen ? null : String(decision.review_id ?? '')); }}>
              <div>
                <strong>{geneName(String(decision.strategy_gene_id))}</strong>
                <span className={`verdict-chip verdict-${decision.verdict}`}>{verdictLabel(String(decision.verdict))}</span>
              </div>
              <div className="decision-meta">
                <span>主要驱动: {decision.primary_driver}</span>
                {!isHypo && (
                  <>
                    <span className={decision.return_pct >= 0 ? 'up' : 'down'}>
                      {formatPct(decision.return_pct)}
                    </span>
                    <span className="rel-return">{formatPct(decision.relative_return_pct)} vs 指数</span>
                  </>
                )}
              </div>
            </div>

            {(alwaysOpen || isOpen) && (
              <div className="decision-body">
                <p className="decision-summary">{decision.summary}</p>

                {/* Factor Checks */}
                {decision.factor_items?.length > 0 && (
                  <section className="detail-section">
                    <h4>多维分析</h4>
                    <table className="detail-table factor-table clickable">
                      <thead><tr><th>维度</th><th>判决</th><th title="正分=该维度支持利好结论，负分=支持利空结论。绝对值越大，对最终判决影响越大">贡献分 ⓘ</th><th>置信度</th></tr></thead>
                      <tbody>
                        {decision.factor_items.map((f, i) => (
                          <tr
                            key={i}
                            className={`factor-row ${expandedFactor === i ? 'expanded' : ''} ${f.contribution_score !== 0 ? 'has-signal' : ''}`}
                            onClick={() => setExpandedFactor(expandedFactor === i ? null : i)}
                          >
                            <td>
                              <span className="factor-name">{FACTOR_LABEL[f.factor_type] ?? f.factor_type}</span>
                              <span className="factor-expand-icon">{expandedFactor === i ? '▾' : '▸'}</span>
                            </td>
                            <td><span className={`verdict-badge verdict-${f.verdict}`}>{verdictLabel(String(f.verdict))}</span></td>
                            <td><span className={f.contribution_score > 0 ? 'positive' : f.contribution_score < 0 ? 'negative' : ''}>{f.contribution_score > 0 ? '+' : ''}{f.contribution_score.toFixed(2)}</span></td>
                            <td><span className={`conf-badge conf-${f.confidence}`}>{confidenceLabel(String(f.confidence))}</span></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {/* 展开显示解释和数据 */}
                    {expandedFactor !== null && decision.factor_items[expandedFactor] && (
                      <FactorExplanation factor={decision.factor_items[expandedFactor]} />
                    )}
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

      {/* AI Summary Modal */}
      {aiOpen && (
        <div className="ai-modal-overlay" onClick={() => setAiOpen(false)}>
          <div className="ai-modal" onClick={(e) => e.stopPropagation()}>
            <div className="ai-modal-header">
              <div className="ai-modal-title">
                <BrainCircuit size={16} /> AI 分析解读
              </div>
              <button className="ai-modal-close" onClick={() => setAiOpen(false)}>
                <X size={18} />
              </button>
            </div>
            <div className="ai-modal-body">
              {aiLoading ? (
                <div className="ai-modal-loading">正在生成分析解读...</div>
              ) : aiSummary ? (
                <div className="ai-modal-text">{aiSummary}</div>
              ) : (
                <div className="ai-modal-empty">暂无 AI 解读数据</div>
              )}
            </div>
          </div>
        </div>
      )}
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

/* === Review Summary Card (S2.1, S2.2, S2.3) === */

function ReviewSummaryCard({ summary }: { summary: ReviewSummary }) {
  return (
    <div className="review-summary-card">
      <div className="summary-one-line">
        <strong>结论</strong>
        <p>{summary.one_line_conclusion}</p>
      </div>

      <div className="summary-three-layer">
        <section className="summary-layer summary-preopen">
          <h4>盘前证据</h4>
          <p className="summary-why-picked">{summary.why_we_picked_it}</p>
          {summary.supporting_evidence.length > 0 && (
            <div className="summary-evidence-mini">
              {summary.supporting_evidence.slice(0, 3).map((ev, i) => (
                <span className="evidence-chip" key={i}>
                  {ev.title}
                  {ev.source && <small> · {ev.source}</small>}
                </span>
              ))}
            </div>
          )}
        </section>

        <section className="summary-layer summary-postclose">
          <h4>收盘验证</h4>
          <p>{summary.what_happened}</p>
          {summary.contradicting_evidence.length > 0 && (
            <details>
              <summary>反面证据（{summary.contradicting_evidence.length} 条）</summary>
              <div className="summary-evidence-mini">
                {summary.contradicting_evidence.slice(0, 3).map((ev, i) => (
                  <span className="evidence-chip contradict" key={i}>
                    {ev.title}
                    {ev.source && <small> · {ev.source}</small>}
                  </span>
                ))}
              </div>
            </details>
          )}
        </section>

        <section className="summary-layer summary-errors">
          <h4>错误归因</h4>
          {summary.where_we_were_wrong.length > 0 ? (
            <div className="error-attribution-grouped">
              {summary.where_we_were_wrong.map((err, i) => (
                <div className="error-attribution-row" key={i}>
                  <span className="error-label">{err.label}</span>
                  <span className="error-type">{err.error_type}</span>
                  <span className={`severity-dot severity-${err.severity > 0.7 ? 'high' : err.severity > 0.4 ? 'mid' : 'low'}`} />
                </div>
              ))}
            </div>
          ) : (
            <p className="empty-value">未发现明显错误</p>
          )}
          <div className="blame-assessment">
            <strong>是否该怪策略？</strong>
            <p>{summary.should_we_blame_strategy}</p>
          </div>
        </section>
      </div>

      {summary.what_to_do_next.length > 0 && (
        <section className="summary-next">
          <h4>下一步</h4>
          <ol>
            {summary.what_to_do_next.slice(0, 3).map((step, i) => (
              <li key={i}>{step}</li>
            ))}
          </ol>
        </section>
      )}
    </div>
  );
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
  ].filter((g) => g.rows.length > 0);

  if (groups.length === 0) return null;

  return (
    <div className="evidence-table">
      {groups.map((group) => (
        <section className="evidence-group" key={group.title}>
          <h4>{group.title}</h4>
          {group.rows.slice(0, 4).map((row, index) => (
            <div key={`${group.title}-${index}`}><span>{row.label}</span><b>{row.value}</b><small>{String(row.source ?? '')} {row.meta ? `· ${row.meta}` : ''}</small></div>
          ))}
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

function formatPctNum(v?: number | null): string {
  if (v == null || Number.isNaN(v)) return '-';
  return `${v >= 0 ? '+' : ''}${(v * 100).toFixed(2)}%`;
}

/** 将数据源名称转为中文 */
function sourceLabel(s: string): string {
  if (s === 'baostock_live') return 'BaoStock';
  if (s === 'akshare_live') return 'AkShare';
  if (s === 'eastmoney_live') return '东方财富';
  return s;
}

/** 单维度展开解释面板 */
function FactorExplanation({ factor }: { factor: FactorItem }) {
  const label = FACTOR_LABEL[factor.factor_type] ?? factor.factor_type;
  const actual = factor.actual ?? {};
  const items: Array<{ label: string; value: string }> = [];

  if (factor.factor_type === 'technical') {
    if (actual.momentum != null) items.push({ label: '动量', value: formatPctNum(actual.momentum as number) });
    if (actual.volume_surge != null) items.push({ label: '放量', value: formatPctNum(actual.volume_surge as number) });
    if (actual.volatility != null) items.push({ label: '波动率', value: formatPctNum(actual.volatility as number) });
    if (actual.trend_state) {
      const trendMap: Record<string, string> = { bullish: '多头排列', bearish: '空头排列', neutral: '震荡整理', breakout: '突破形态' };
      items.push({ label: '趋势', value: trendMap[String(actual.trend_state)] ?? String(actual.trend_state) });
    }
  }

  if (factor.factor_type === 'fundamental') {
    if (actual.roe != null) items.push({ label: 'ROE', value: `${(Number(actual.roe) * 100).toFixed(2)}%` });
    if (actual.revenue_growth != null) items.push({ label: '营收增长', value: formatPctNum(actual.revenue_growth as number) });
    if (actual.net_profit_growth != null) items.push({ label: '利润增长', value: formatPctNum(actual.net_profit_growth as number) });
    if (actual.pe_percentile != null) items.push({ label: 'PE 百分位', value: `${(Number(actual.pe_percentile) * 100).toFixed(0)}%` });
  }

  if (factor.factor_type === 'sector') {
    if (actual.relative_strength_rank != null) items.push({ label: '行业强度排名', value: `第 ${String(actual.relative_strength_rank)} 位` });
    if (actual.theme_strength != null) items.push({ label: '主题强度', value: `${(Number(actual.theme_strength) * 100).toFixed(0)}%` });
    if (actual.sector_return_pct != null) items.push({ label: '行业收益', value: formatPctNum(actual.sector_return_pct as number) });
    if (actual.summary) items.push({ label: '摘要', value: String(actual.summary) });
  }

  if (factor.factor_type === 'risk') {
    if (actual.avg_amount != null) items.push({ label: '日均成交额', value: formatAmount(Number(actual.avg_amount)) });
    if (Array.isArray(actual.reasons) && (actual.reasons as unknown[]).length > 0) {
      items.push({ label: '风险提示', value: (actual.reasons as string[]).join('、') });
    }
  }

  if (factor.factor_type === 'event') {
    if (Array.isArray(actual.items) && (actual.items as unknown[]).length > 0) {
      const eventItems = actual.items as Array<{ title?: string; event_type?: string; impact_score?: number; sentiment?: number }>;
      eventItems.slice(0, 5).forEach(ev => {
        const score = ev.impact_score != null ? formatPctNum(ev.impact_score) : '';
        items.push({ label: ev.event_type ?? '事件', value: `${ev.title ?? '-'} ${score ? `[影响: ${score}]` : ''}` });
      });
    }
  }

  const hasScore = factor.expected && typeof factor.expected.score === 'number';
  const rawScore = hasScore ? (factor.expected!.score as number) : factor.contribution_score;

  return (
    <div className="factor-explanation-card">
      {/* 得分计算说明 */}
      <div className="factor-explanation-header">
        <h5>{label}</h5>
        <div className="factor-score-breakdown">
          {hasScore && (
            <span className="score-chip">原始评分: {rawScore > 0 ? '+' : ''}{rawScore.toFixed(4)}</span>
          )}
          <span className="score-chip">贡献分: {factor.contribution_score > 0 ? '+' : ''}{factor.contribution_score.toFixed(2)}</span>
          <span className={`score-chip verdict-${factor.verdict}`}>判决: {verdictLabel(String(factor.verdict))}</span>
        </div>
      </div>

      {/* 解释文案 */}
      {factor.reason && (
        <div className="factor-reason">
          <div className="factor-reason-label">分析逻辑</div>
          <p>{factor.reason}</p>
        </div>
      )}

      {/* 明细数据 */}
      {items.length > 0 && (
        <div className="factor-detail-items">
          {items.map((item, j) => (
            <div className="factor-detail-row" key={j}>
              <span className="factor-detail-label">{item.label}</span>
              <span className="factor-detail-value">{item.value}</span>
            </div>
          ))}
        </div>
      )}

      {items.length === 0 && !factor.reason && (
        <p className="factor-no-data">该维度暂无明细数据或解释文案</p>
      )}
    </div>
  );
}

/** 各维度详细数据卡片 (保留兼容旧版全部展示) */
function FactorDetailList({ factors }: { factors: FactorItem[] }) {
  return (
    <div className="factor-details-grid">
      {factors.map((f, i) => {
        const label = FACTOR_LABEL[f.factor_type] ?? f.factor_type;
        const actual = f.actual ?? {};
        const items: Array<{ label: string; value: string }> = [];

        if (f.factor_type === 'technical' && actual.momentum != null) {
          items.push({ label: '动量', value: formatPctNum(actual.momentum as number) });
        }
        if (f.factor_type === 'technical' && actual.volume_surge != null) {
          items.push({ label: '放量', value: formatPctNum(actual.volume_surge as number) });
        }
        if (f.factor_type === 'technical' && actual.volatility != null) {
          items.push({ label: '波动率', value: formatPctNum(actual.volatility as number) });
        }
        if (f.factor_type === 'technical' && actual.trend_state) {
          const trendMap: Record<string, string> = { bullish: '多头', bearish: '空头', neutral: '震荡', breakout: '突破' };
          items.push({ label: '趋势', value: trendMap[String(actual.trend_state)] ?? String(actual.trend_state) });
        }

        if (f.factor_type === 'fundamental' && actual.roe != null) {
          items.push({ label: 'ROE', value: `${(Number(actual.roe) * 100).toFixed(2)}%` });
        }
        if (f.factor_type === 'fundamental' && actual.revenue_growth != null) {
          items.push({ label: '营收增长', value: formatPctNum(actual.revenue_growth as number) });
        }
        if (f.factor_type === 'fundamental' && actual.net_profit_growth != null) {
          items.push({ label: '利润增长', value: formatPctNum(actual.net_profit_growth as number) });
        }
        if (f.factor_type === 'fundamental' && actual.pe_percentile != null) {
          items.push({ label: 'PE 百分位', value: `${(Number(actual.pe_percentile) * 100).toFixed(0)}%` });
        }

        if (f.factor_type === 'sector' && actual.relative_strength_rank != null) {
          items.push({ label: '行业强度排名', value: String(actual.relative_strength_rank) });
        }
        if (f.factor_type === 'sector' && actual.theme_strength != null) {
          items.push({ label: '主题强度', value: (Number(actual.theme_strength) * 100).toFixed(2) + '%' });
        }
        if (f.factor_type === 'sector' && actual.sector_return_pct != null) {
          items.push({ label: '行业收益', value: formatPctNum(actual.sector_return_pct as number) });
        }

        if (f.factor_type === 'risk' && actual.avg_amount != null) {
          items.push({ label: '日均成交额', value: formatAmount(Number(actual.avg_amount)) });
        }
        if (f.factor_type === 'risk' && Array.isArray(actual.reasons) && (actual.reasons as unknown[]).length > 0) {
          items.push({ label: '风险提示', value: (actual.reasons as string[]).join('、') });
        }

        if (f.factor_type === 'event' && Array.isArray(actual.items) && (actual.items as unknown[]).length > 0) {
          const eventItems = actual.items as Array<{ title?: string; event_type?: string }>;
          eventItems.slice(0, 3).forEach(ev => {
            items.push({ label: ev.event_type ?? '事件', value: ev.title ?? '-' });
          });
        }

        if (items.length === 0) return null;

        return (
          <div className="factor-detail-card" key={i}>
            <h5>{label}</h5>
            <div className="factor-detail-items">
              {items.map((item, j) => (
                <div className="factor-detail-row" key={j}>
                  <span className="factor-detail-label">{item.label}</span>
                  <span className="factor-detail-value">{item.value}</span>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* === Sprint 8: Summary generators (人话翻译) === */

function generateOneLineSummary(
  stock: Record<string, unknown>,
  market?: Record<string, unknown>,
  sentiment?: Record<string, unknown>,
  quant?: Record<string, unknown>,
  flow?: Record<string, unknown>,
  sector?: Record<string, unknown>,
): string | null {
  const parts: string[] = [];

  if (market) {
    const style = String(market.style_preference ?? '');
    const advance = Number(market.advance_count ?? 0);
    const decline = Number(market.decline_count ?? 0);
    if (advance > decline) parts.push(`大盘偏强（涨${advance}跌${decline}）`);
    else if (decline > advance) parts.push(`大盘偏弱（涨${advance}跌${decline}）`);
    if (style === 'large_cap') parts.push('大盘股占优');
    else if (style === 'small_cap') parts.push('小盘股活跃');
  }

  if (sentiment) {
    const phase = String(sentiment.cycle_phase ?? '');
    if (phase && phase !== '未知') parts.push(`情绪处于${phase}阶段`);
  }

  if (sector) {
    const name = String(sector.sector_name ?? '');
    const ret = Number(sector.sector_return_pct ?? 0);
    if (name && ret !== 0) parts.push(`${name}${ret > 0 ? '领涨' : '领跌'}（${formatPct(ret)}）`);
  }

  if (quant) {
    const vol = quant.volume_analysis as Record<string, unknown> | undefined;
    const ma = quant.moving_average as Record<string, unknown> | undefined;
    const chain = quant.limit_up_chain as Record<string, unknown> | undefined;
    if (vol?.trend) parts.push(`量能${String(vol.trend)}`);
    if (ma?.trend) parts.push(String(ma.trend));
    const days = Number(chain?.current_days ?? 0);
    if (days > 0) parts.push(`连板${days}天`);
  }

  if (flow) {
    const mainInflow = Number(flow.main_net_inflow ?? 0);
    const trend = String(flow.flow_trend ?? '');
    if (mainInflow > 0) parts.push(`主力净流入${(mainInflow / 10000).toFixed(1)}亿`);
    else if (mainInflow < 0) parts.push(`主力净流出${Math.abs(mainInflow / 10000).toFixed(1)}亿`);
    if (trend) parts.push(`资金${trend}`);
  }

  if (parts.length === 0) return null;
  if (parts.length <= 2) return parts.join('，');
  if (parts.length <= 4) return `${parts.slice(0, -1).join('，')}；${parts[parts.length - 1]}`;
  return `${parts.slice(0, 3).join('，')}；${parts.slice(3).join('，')}`;
}

function marketSummary(m?: Record<string, unknown>): string | null {
  if (!m) return null;
  const advance = Number(m.advance_count ?? 0);
  const decline = Number(m.decline_count ?? 0);
  const limitUp = Number(m.limit_up_count ?? 0);
  if (advance > decline) return `赚钱效应好，涨${advance}跌${decline}，涨停${limitUp}家`;
  if (decline > advance) return `亏钱效应明显，涨${advance}跌${decline}，跌停${Number(m.limit_down_count ?? 0)}家`;
  return `市场分歧，涨跌各半`;
}

function sentimentSummary(s?: Record<string, unknown>): string | null {
  if (!s) return null;
  const phase = String(s.cycle_phase ?? '');
  const sealRate = Number(s.seal_rate ?? 0);
  if (phase === '冰点') return '市场情绪冰点，短线需等待企稳信号';
  if (phase === '回暖') return '情绪开始回暖，涨停数增加，可轻仓试探';
  if (phase === '升温') return '情绪升温，封板率' + (sealRate > 0.6 ? '良好' : '一般') + '，短线偏安全';
  if (phase === '高潮') return '情绪高潮阶段，涨停集中但注意次日分化';
  if (phase === '退潮') return '情绪明显退潮，封板率下降，短线需谨慎';
  if (phase === '恐慌') return '市场恐慌，跌停数增加，建议观望';
  return `情绪阶段：${phase || '未知'}`;
}

function sectorSummary(s?: Record<string, unknown>, stock?: Record<string, unknown>): string | null {
  if (!s) return null;
  const topSectors = (s.top_sectors as Record<string, unknown>[] | undefined) ?? [];
  if (topSectors.length === 0) return null;
  const first = topSectors[0];
  const name = String(first.sector_name ?? '');
  const ret = Number(first.sector_return_pct ?? 0);
  const leader = String(first.leader_stock ?? '');
  const complete = first.team_complete ? '梯队完整' : '梯队不完整';
  if (ret > 0) return `${name}领涨（${formatPct(ret)}），龙头${leader || '不明'}，${complete}`;
  if (ret < 0) return `${name}领跌（${formatPct(ret)}），注意风险`;
  return `${name}平盘，${complete}`;
}

function capitalFlowSummary(f?: Record<string, unknown>): string | null {
  if (!f) return null;
  const mainInflow = Number(f.main_net_inflow ?? 0);
  if (mainInflow > 5000) return `主力大幅净流入${(mainInflow / 10000).toFixed(1)}亿，资金强烈看好`;
  if (mainInflow > 0) return `主力净流入${(mainInflow / 10000).toFixed(1)}亿，资金态度偏积极`;
  if (mainInflow < -5000) return `主力大幅净流出${Math.abs(mainInflow / 10000).toFixed(1)}亿，资金持续撤出`;
  if (mainInflow < 0) return `主力净流出${Math.abs(mainInflow / 10000).toFixed(1)}亿，资金态度偏谨慎`;
  return `资金进出平衡`;
}

function quantSummary(q?: Record<string, unknown>): string | null {
  if (!q) return null;
  const vol = q.volume_analysis as Record<string, unknown> | undefined;
  const ma = q.moving_average as Record<string, unknown> | undefined;
  const chain = q.limit_up_chain as Record<string, unknown> | undefined;
  const parts: string[] = [];
  if (vol?.trend) parts.push(`量能${String(vol.trend)}`);
  if (ma?.trend) parts.push(String(ma.trend));
  const days = Number(chain?.current_days ?? 0);
  if (days > 0) parts.push(`连板${days}天`);
  return parts.length > 0 ? parts.join('，') : null;
}

function psychologySummary(p?: Record<string, unknown>): string | null {
  if (!p) return null;
  const success = (p.success_reasons as string[] | undefined)?.length ?? 0;
  const failure = (p.failure_reasons as string[] | undefined)?.length ?? 0;
  const cat = String(p.psychological_category ?? '');
  if (success > 0 && failure === 0) return `操作成功，归因明确：${cat || '技术判断准确'}`;
  if (failure > 0) return `发现${failure}个问题：${cat || '需反思'}`;
  return null;
}

function planSummary(p?: Record<string, unknown>): string | null {
  if (!p) return null;
  try {
    const scenarios = JSON.parse(String(p.scenarios ?? '[]')) as Array<Record<string, unknown>>;
    if (scenarios.length > 0) return `已生成${scenarios.length}种场景预案`;
  } catch { /* ignore */ }
  return null;
}

/* === Collapsible Card Component === */

function CollapsibleCard({
  title, summary, expanded, onToggle, children,
}: {
  title: string;
  icon?: string;
  summary: string | null;
  expanded: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  if (!children) return null;
  const Icon = expanded ? ChevronDown : ChevronRight;
  return (
    <div className={`collapsible-card ${expanded ? 'expanded' : ''}`}>
      <div className="collapsible-header" onClick={onToggle}>
        <Icon size={16} />
        <span className="collapsible-title">{title}</span>
        {summary && <span className="collapsible-summary-text">{summary}</span>}
      </div>
      {expanded && <div className="collapsible-body">{children}</div>}
    </div>
  );
}

/* === Deep Review Detail Cards === */

function MarketOverviewCard({ data }: { data: Record<string, unknown> }) {
  const sh = data.sh_return != null ? Number(data.sh_return) : null;
  const sz = data.sz_return != null ? Number(data.sz_return) : null;
  const cyb = data.cyb_return != null ? Number(data.cyb_return) : null;
  const bse = data.bse_return != null ? Number(data.bse_return) : null;
  const advance = Number(data.advance_count ?? 0);
  const decline = Number(data.decline_count ?? 0);
  const limitUp = Number(data.limit_up_count ?? 0);
  const limitDown = Number(data.limit_down_count ?? 0);
  const stylePref = String(data.style_preference ?? '');
  const hasIndexData = sh != null || sz != null || cyb != null || bse != null;
  const styleMap: Record<string, string> = { small_cap: '小盘股占优', large_cap: '大盘股占优', balanced: '均衡' };

  return (
    <div className="context-card market-overview-card">
      <div className="card-interpretation">
        <p>
          {hasIndexData && `四大指数${sh != null && sh >= 0 ? '上证领涨' : '上证领跌'}，`}
          赚钱效应{advance > decline ? '良好' : '偏差'}，{advance > decline ? `超${Math.round(advance / Math.max(advance + decline, 1) * 100)}%个股上涨` : `${Math.round(decline / Math.max(advance + decline, 1) * 100)}%个股下跌`}，
          涨停{limitUp}家{limitDown > 0 ? `，跌停${limitDown}家` : ''}。
          {stylePref && stylePref !== 'unknown' && `当前为${styleMap[stylePref] ?? stylePref}行情。`}
        </p>
      </div>
      <div className="data-section">
        {hasIndexData && (
          <div className="index-returns">
            <div className="index-return-item"><span>上证</span><b className={sh != null && sh >= 0 ? 'up' : sh != null && sh < 0 ? 'down' : ''}>{sh != null ? formatPct(sh) : '--'}</b></div>
            <div className="index-return-item"><span>深证</span><b className={sz != null && sz >= 0 ? 'up' : sz != null && sz < 0 ? 'down' : ''}>{sz != null ? formatPct(sz) : '--'}</b></div>
            <div className="index-return-item"><span>创业板</span><b className={cyb != null && cyb >= 0 ? 'up' : cyb != null && cyb < 0 ? 'down' : ''}>{cyb != null ? formatPct(cyb) : '--'}</b></div>
            <div className="index-return-item"><span>北证</span><b className={bse != null && bse >= 0 ? 'up' : bse != null && bse < 0 ? 'down' : ''}>{bse != null ? formatPct(bse) : '--'}</b></div>
          </div>
        )}
        <div className="market-stats">
          <span className="stat-item">上涨 {advance}</span>
          <span className="stat-item">下跌 {decline}</span>
          <span className="stat-item">涨停 {limitUp}</span>
          <span className="stat-item">跌停 {limitDown}</span>
          {stylePref && stylePref !== 'unknown' && <span className="stat-item">风格 {styleMap[stylePref] ?? stylePref}</span>}
        </div>
      </div>
    </div>
  );
}

function SentimentCycleCard({ data }: { data: Record<string, unknown> }) {
  const phase = String(data.cycle_phase ?? '未知');
  const sentiment = Number(data.composite_sentiment ?? 0);
  const sealRate = Number(data.seal_rate ?? 0);
  const phaseColor: Record<string, string> = { '冰点': 'phase-ice', '回暖': 'phase-warm', '升温': 'phase-hot', '高潮': 'phase-peak', '退潮': 'phase-decline', '恐慌': 'phase-panic' };
  const phaseAdvice: Record<string, string> = {
    '冰点': '情绪极度悲观，通常是短线见底信号，等待放量回暖再介入。',
    '回暖': '情绪开始修复，涨停数增加，可轻仓参与前排个股。',
    '升温': '情绪向好，赚钱效应扩散，短线操作胜率高。',
    '高潮': '情绪极度乐观，涨停集中但次日容易分化，注意高位兑现。',
    '退潮': '情绪走坏，封板率下降，高位股补跌风险加大。',
    '恐慌': '恐慌性抛售，跌停增加，建议观望等待企稳。',
  };

  return (
    <div className="context-card sentiment-cycle-card">
      <div className="card-interpretation">
        <p>当前市场情绪处于<strong>{phase}</strong>阶段。{phaseAdvice[phase] || ''} 综合情绪分{(sentiment * 100).toFixed(0)}分（满100），封板率{(sealRate * 100).toFixed(0)}%。</p>
      </div>
      <div className="data-section">
        <div className="sentiment-main">
          <span className={`cycle-phase ${phaseColor[phase] ?? ''}`}>{phase}</span>
        </div>
        <div className="sentiment-details">
          <span>封板率: {(sealRate * 100).toFixed(0)}%</span>
          <span>晋级率: {(Number(data.promotion_rate ?? 0) * 100).toFixed(0)}%</span>
        </div>
      </div>
    </div>
  );
}

function SectorAnalysisDetail({ data, stockCode }: { data: Record<string, unknown>; stockCode: string }) {
  const topSectors = (data.top_sectors as Record<string, unknown>[] | undefined) ?? [];
  if (topSectors.length === 0) return <p className="no-data">暂无板块分析数据。</p>;

  return (
    <div className="context-card sector-detail-card">
      <div className="card-interpretation">
        <p>
          当日领涨板块为<strong>{String(topSectors[0].sector_name ?? '')}</strong>（{formatPct(Number(topSectors[0].sector_return_pct ?? 0))}）。
          {topSectors[0]?.team_complete !== undefined && topSectors[0].team_complete && '梯队结构完整，龙头-中军-跟风齐全。'}
        </p>
      </div>
      <div className="data-section">
        {topSectors.map((s, i) => (
          <div className="sector-row" key={i}>
            <span className="sector-rank">#{i + 1}</span>
            <span className="sector-name">{String(s.sector_name ?? '')}</span>
            <span className={Number(s.sector_return_pct ?? 0) >= 0 ? 'up' : 'down'}>{formatPct(Number(s.sector_return_pct ?? 0))}</span>
            {s.leader_stock != null && <span className="sector-leader-inline">龙头: {String(s.leader_stock)}</span>}
            {s.team_complete != null && s.team_complete && <span className="team-complete-badge">梯队完整</span>}
          </div>
        ))}
      </div>
    </div>
  );
}

function CapitalFlowDetailCard({ data }: { data: Record<string, unknown> }) {
  const mainInflow = Number(data.main_net_inflow ?? 0);
  const superLarge = Number(data.super_large_inflow ?? 0);
  const largeOrder = Number(data.large_order_inflow ?? 0);
  const retail = Number(data.retail_net ?? 0);
  const trend = String(data.flow_trend ?? '');
  const isInflow = mainInflow > 0;
  const absMain = Math.abs(mainInflow);

  const trendText: Record<string, string> = { '大幅流入': '资金强烈看好，主力大举建仓', '流入': '资金态度偏积极，主力温和买入', '大幅流出': '资金持续撤出，主力大量抛售', '流出': '资金态度偏谨慎，主力小幅撤出', '平衡': '多空力量均衡' };

  const fmt = (v: number) => v >= 10000 ? (v / 10000).toFixed(2) + '亿' : Math.round(v) + '万';

  return (
    <div className="context-card capital-flow-card">
      <div className="card-interpretation">
        <p>主力资金{isInflow ? '净流入' : '净流出'}{fmt(absMain)}，{trendText[trend] || trend}。{superLarge > 0 && '超大单同步净流入。'}{retail < 0 && '散户净流出，筹码向主力集中。'}</p>
      </div>
      <div className="data-section">
        <div className="flow-bars">
          <div className="flow-row"><span className="flow-label">主力</span><span className={`flow-value ${isInflow ? 'up' : 'down'}`}>{isInflow ? '+' : ''}{fmt(mainInflow)}</span></div>
          <div className="flow-row"><span className="flow-label">超大单</span><span className={`flow-value ${superLarge > 0 ? 'up' : 'down'}`}>{fmt(superLarge)}</span></div>
          <div className="flow-row"><span className="flow-label">大单</span><span className={`flow-value ${largeOrder > 0 ? 'up' : 'down'}`}>{fmt(largeOrder)}</span></div>
          <div className="flow-row"><span className="flow-label">散户</span><span className={`flow-value ${retail > 0 ? 'up' : 'down'}`}>{fmt(retail)}</span></div>
        </div>
      </div>
    </div>
  );
}

function StockQuantCard({ data }: { data: Record<string, unknown> }) {
  const ma = data.moving_average as Record<string, unknown> | undefined;
  const vol = data.volume_analysis as Record<string, unknown> | undefined;
  const chain = data.limit_up_chain as Record<string, unknown> | undefined;
  const leader = data.leader_comparison as Record<string, unknown> | undefined;

  return (
    <div className="context-card stock-quant-card">
      <div className="card-interpretation">
        <p>
          {ma && `股价${ma.trend === '多头排列' ? '站上均线，多头排列' : ma.trend === '空头排列' ? '跌破均线，空头排列' : String(ma.trend)}。`}
          {vol && `量能${String(vol.trend)}。`}
          {chain && Number(chain.current_days ?? 0) > 0 && `当前连板${chain.current_days}天。`}
        </p>
      </div>
      <div className="data-section">
        <div className="quant-grid">
          {ma && (
            <div className="quant-section">
              <h5>均线</h5>
              <div className="quant-row"><span>MA5</span><b>{Number(ma.ma5 ?? 0).toFixed(2)}</b></div>
              <div className="quant-row"><span>MA10</span><b>{Number(ma.ma10 ?? 0).toFixed(2)}</b></div>
              <div className="quant-row"><span>MA20</span><b>{Number(ma.ma20 ?? 0).toFixed(2)}</b></div>
              <div className="quant-row"><span>趋势</span><b>{String(ma.trend ?? '-')}</b></div>
            </div>
          )}
          {vol && (
            <div className="quant-section">
              <h5>量能</h5>
              <div className="quant-row"><span>量比</span><b>{Number(vol.volume_ratio_5d ?? 0).toFixed(2)}x</b></div>
              <div className="quant-row"><span>趋势</span><b>{String(vol.trend ?? '-')}</b></div>
            </div>
          )}
          {chain && (
            <div className="quant-section">
              <h5>连板</h5>
              <div className="quant-row"><span>当前连板</span><b>{Number(chain.current_days ?? 0)}天</b></div>
              {chain.is_limit_up_today !== undefined && chain.is_limit_up_today && <div className="quant-row">今日<strong>涨停</strong></div>}
            </div>
          )}
          {leader && (
            <div className="quant-section">
              <h5>龙头对比</h5>
              <div className="quant-row"><span>板块龙头</span><b>{String(leader.leader_code ?? '')} ({formatPct(Number(leader.leader_return_pct ?? 0))})</b></div>
              <div className="quant-row"><span>该股</span><b>{formatPct(Number(leader.self_return_pct ?? 0))}</b></div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function PsychologyReviewCard({ data }: { data: Record<string, unknown> }) {
  const successReasons = (data.success_reasons as string[] | undefined) ?? [];
  const failureReasons = (data.failure_reasons as string[] | undefined) ?? [];
  const reproducible = (data.reproducible_patterns as string[] | undefined) ?? [];
  const preventions = (data.prevention_strategies as string[] | undefined) ?? [];
  const category = String(data.psychological_category ?? '');

  return (
    <div className="context-card psychology-card">
      <div className="card-interpretation">
        <p>
          {successReasons.length > 0 && `做对了：${successReasons.slice(0, 2).join('；')}。`}
          {failureReasons.length > 0 && `存在问题：${failureReasons.slice(0, 2).join('；')}。`}
          {category && `归因：${category}。`}
        </p>
      </div>
      <div className="data-section">
        {successReasons.length > 0 && (
          <div className="psych-section"><h5>成功原因</h5>{successReasons.map((r, i) => <div className="psych-item" key={i}>✅ {r}</div>)}</div>
        )}
        {failureReasons.length > 0 && (
          <div className="psych-section"><h5>失败原因</h5>{failureReasons.map((r, i) => <div className="psych-item error" key={i}>❌ {r}</div>)}</div>
        )}
        {reproducible.length > 0 && (
          <div className="psych-section"><h5>可复制模式</h5>{reproducible.map((r, i) => <div className="psych-item repro" key={i}>🔁 {r}</div>)}</div>
        )}
        {preventions.length > 0 && (
          <div className="psych-section"><h5>预防策略</h5>{preventions.map((r, i) => <div className="psych-item prevent" key={i}>🛡 {r}</div>)}</div>
        )}
      </div>
    </div>
  );
}

function NextDayPlanCard({ data }: { data: Record<string, unknown> }) {
  let scenarios: Array<Record<string, unknown>> = [];
  try { scenarios = JSON.parse(String(data.scenarios ?? '[]')); } catch { /* ignore */ }

  return (
    <div className="context-card plan-card">
      <div className="card-interpretation">
        <p>已为次日准备了{scenarios.length}种场景预案，请结合盘面灵活应对。</p>
      </div>
      <div className="data-section">
        {scenarios.map((s, i) => (
          <div className="scenario-row" key={i}>
            <div className="scenario-header">
              <span className="scenario-name">{String(s.scenario ?? `场景${i + 1}`)}</span>
              {s.condition != null && <span className="scenario-condition">条件: {String(s.condition)}</span>}
            </div>
            {s.action != null && <p className="scenario-action">操作: {String(s.action)}</p>}
            {s.risk != null && <p className="scenario-risk">风险: {String(s.risk)}</p>}
          </div>
        ))}
        {scenarios.length === 0 && <p className="no-data">暂无预案数据。</p>}
      </div>
    </div>
  );
}

