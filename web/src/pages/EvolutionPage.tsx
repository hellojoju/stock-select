import { useEffect, useState } from 'react';
import { GitBranch, RotateCcw, Search, ShieldAlert, Target, Trophy, Eye } from 'lucide-react';
import Panel from '../components/Panel';
import Metric from '../components/Metric';
import { PageHeader, SystemStatusStrip } from '../components/PageHeader';
import ConfirmActionDialog from '../components/ConfirmActionDialog';
import EvolutionPanel from '../sections/EvolutionPanel';
import SignalDetailCard from '../sections/SignalDetailCard';
import { llmStatusLabel } from '../lib/llmStatus';
import type { Comparison, Dashboard, SignalDetail, RollbackEvent } from '../types';
import { API_BASE, fetchPlannerVsPicks, fetchChallengerPerformance, fetchEnvironmentPerformance, type PlannerVsPicks, type ChallengerPerf, type EnvPerfItem } from '../api/client';

export default function EvolutionPage() {
  const [date, setDate] = useState('');
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [comparisons, setComparisons] = useState<Comparison[]>([]);
  const [candidateSignals, setCandidateSignals] = useState<Array<Record<string, unknown>>>([]);
  const [plannerVsPicks, setPlannerVsPicks] = useState<PlannerVsPicks | null>(null);
  const [challengerPerf, setChallengerPerf] = useState<ChallengerPerf[]>([]);
  const [envPerformance, setEnvPerformance] = useState<EnvPerfItem[]>([]);
  const [dryRunPreview, setDryRunPreview] = useState<Record<string, unknown> | null>(null);
  const [rollbacks, setRollbacks] = useState<RollbackEvent[]>([]);
  const [selectedSignal, setSelectedSignal] = useState<SignalDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [pendingAction, setPendingAction] = useState<{
    type: 'propose' | 'promote' | 'rollback';
    title: string;
    description: string;
    impacts: string[];
    execute: () => void;
  } | null>(null);

  async function loadAll(targetDate: string) {
    setLoading(true);
    await Promise.all([
      loadDashboard(targetDate),
      loadEvents(),
      loadCandidateSignals(),
      loadPlannerVsPicks(targetDate),
      loadChallengerPerf(),
      loadEnvPerformance(),
      loadRollbacks(),
    ]);
    setLoading(false);
  }

  async function loadDashboard(targetDate: string) {
    try {
      const suffix = targetDate ? `?date=${targetDate}` : '';
      const response = await fetch(`${API_BASE}/api/dashboard${suffix}`);
      const data = await response.json();
      setDashboard(data);
      if (!date && data.date) setDate(data.date);
    } catch {
      setDashboard(null);
    }
  }

  async function loadEvents() {
    const response = await fetch(`${API_BASE}/api/evolution/events?limit=50`);
    const events = await response.json();

    const enriched = await Promise.all(
      events.map(async (ev: Record<string, unknown>) => {
        try {
          const comp = await fetch(
            `${API_BASE}/api/evolution/comparison?gene_id=${ev.child_gene_id ?? ev.parent_gene_id ?? ''}`
          ).then(r => r.json());
          return { ...ev, ...comp };
        } catch {
          return ev as unknown as Comparison;
        }
      })
    );
    setComparisons(enriched);
  }

  async function loadCandidateSignals() {
    try {
      const response = await fetch(`${API_BASE}/api/optimization-signals?limit=300`);
      setCandidateSignals(await response.json());
    } catch {
      setCandidateSignals([]);
    }
  }

  async function loadRollbacks() {
    try {
      const response = await fetch(`${API_BASE}/api/evolution/rollback-audit`);
      setRollbacks(await response.json());
    } catch {
      setRollbacks([]);
    }
  }

  async function handleDryRun() {
    setLoading(true);
    try {
      const response = await fetch(`${API_BASE}/api/evolution/propose?start=${date}&end=${date}&dry_run=true`, { method: 'POST' });
      setDryRunPreview(await response.json());
    } finally {
      setLoading(false);
    }
  }

  async function handlePropose() {
    setPendingAction({
      type: 'propose',
      title: 'Propose Challenger',
      description: `将为 ${date} 创建新的 Challenger 策略。`,
      impacts: [
        '将消费当前所有 open 状态的 optimization_signals',
        '创建新的 strategy_gene 记录',
        '新 gene 状态设为 observing（观察期）',
      ],
      execute: async () => {
        setLoading(true);
        try {
          await fetch(`${API_BASE}/api/evolution/propose?start=${date}&end=${date}`, { method: 'POST' });
          setDryRunPreview(null);
          await loadEvents();
          await loadCandidateSignals();
        } finally {
          setLoading(false);
        }
      },
    });
  }

  function handlePromote(childGeneId: string) {
    setPendingAction({
      type: 'promote',
      title: 'Promote Challenger',
      description: `将 Challenger gene ${childGeneId} 提升为新的 Champion。`,
      impacts: [
        `Challenger ${childGeneId} 将成为 active Champion`,
        '原 Champion 将被替换',
        '观察期表现将被记录',
      ],
      execute: async () => {
        await fetch(`${API_BASE}/api/evolution/promote?child_gene_id=${childGeneId}`, { method: 'POST' });
        await loadEvents();
        await loadRollbacks();
      },
    });
  }

  function handleRollback(childGeneId: string) {
    setPendingAction({
      type: 'rollback',
      title: 'Rollback Evolution',
      description: `将回滚 gene ${childGeneId} 的进化。`,
      impacts: [
        `Gene ${childGeneId} 状态设为 rolled_back`,
        '将恢复原 Champion 的 active 状态',
        '不会删除历史复盘、收益和信号',
      ],
      execute: async () => {
        await fetch(`${API_BASE}/api/evolution/rollback?child_gene_id=${childGeneId}`, { method: 'POST' });
        await loadEvents();
        await loadRollbacks();
      },
    });
  }

  async function handleAcceptSignal(signalId: string) {
    await fetch(`${API_BASE}/api/optimization-signals/${signalId}/accept`, { method: 'POST' });
    await loadCandidateSignals();
  }

  async function handleRejectSignal(signalId: string) {
    await fetch(`${API_BASE}/api/optimization-signals/${signalId}/reject`, { method: 'POST' });
    await loadCandidateSignals();
  }

  async function handleViewSignal(signalId: string) {
    try {
      const response = await fetch(`${API_BASE}/api/optimization-signals/${signalId}/detail`);
      const detail = await response.json();
      setSelectedSignal(detail);
    } catch {
      setSelectedSignal(null);
    }
  }

  async function loadPlannerVsPicks(targetDate: string) {
    try {
      const result = await fetchPlannerVsPicks(targetDate || undefined);
      setPlannerVsPicks(result);
    } catch {
      setPlannerVsPicks(null);
    }
  }

  async function loadChallengerPerf() {
    try {
      const result = await fetchChallengerPerformance();
      setChallengerPerf(result.challengers);
    } catch {
      setChallengerPerf([]);
    }
  }

  async function loadEnvPerformance() {
    try {
      const result = await fetchEnvironmentPerformance({ limit: 60 });
      setEnvPerformance(result.items);
    } catch {
      setEnvPerformance([]);
    }
  }

  useEffect(() => { void loadAll(''); }, []);

  return (
    <div className="page terminal-page">
      <PageHeader
        eyebrow="STRATEGY ITERATION"
        title="策略进化"
        date={date}
        onDateChange={setDate}
        onRefresh={() => loadAll(date)}
        loading={loading}
      >
        <button className="btn-secondary" onClick={handleDryRun} disabled={!date || loading}><GitBranch size={15} /> Dry-run</button>
        <button className="btn-primary" onClick={handlePropose} disabled={!date || loading}><Trophy size={15} /> Propose</button>
      </PageHeader>

      <SystemStatusStrip
        mode={dashboard?.runtime_mode}
        marketEnvironment={dashboard?.market_environment}
        evidenceMessage="进化只消费合格 optimization_signals，单次参数变化不超过 5%"
        warnings={Number(dashboard?.data_quality_summary?.warning_count ?? 0)}
        dataQualitySummary={dashboard?.data_quality_summary ?? null}
        llmStatus={llmStatusLabel(dashboard?.llm_status)}
      />

      <section className="kpi-row evolution-kpis">
        <Metric label="未消费信号" value={candidateSignals.length} />
        <Metric label="可提案信号组" value={candidateSignals.filter((s) => String(s.status ?? 'candidate') === 'open').length} />
        <Metric label="观察中 Challenger" value={comparisons.filter((c) => String(c.status).includes('observ')).length} />
        <Metric label="可推广" value={comparisons.filter((c) => c.promotion_eligible && typeof c.promotion_eligible === 'object' && (c.promotion_eligible as Record<string, unknown>).eligible).length} />
        <Metric label="已回滚" value={rollbacks.length} />
      </section>

      {/* Signal detail modal */}
      {selectedSignal && (
        <div className="signal-detail-overlay" onClick={() => setSelectedSignal(null)}>
          <div className="signal-detail-modal" onClick={(e) => e.stopPropagation()}>
            <div className="signal-detail-header">
              <h3>信号详情</h3>
              <button className="close-btn" onClick={() => setSelectedSignal(null)}>×</button>
            </div>
            <SignalDetailCard signal={selectedSignal} />
          </div>
        </div>
      )}

      <section className="evolution-layout">
        <Panel title="信号池" icon={<RotateCcw size={18} />}>
          <SignalPool signals={candidateSignals} onAccept={handleAcceptSignal} onReject={handleRejectSignal} onView={handleViewSignal} />
        </Panel>

        <Panel title="Planner vs 实际 picks" icon={<Target size={18} />}>
          {plannerVsPicks ? (
            <PlannerAlignment view={plannerVsPicks} />
          ) : (
            <p className="muted">暂无 Planner 数据，先运行 preopen_pick 阶段。</p>
          )}
        </Panel>

        <Panel title="Champion vs Challenger" icon={<GitBranch size={18} />}>
          <EvolutionPanel
            comparisons={comparisons}
            rollbacks={rollbacks}
            dryRunPreview={dryRunPreview}
            onDryRun={handleDryRun}
            onApply={handlePropose}
            onPromote={handlePromote}
            onRollback={handleRollback}
          />
        </Panel>

        <Panel title="Challenger 观察期表现" icon={<Trophy size={18} />}>
          {challengerPerf.length > 0 ? (
            <ChallengerPerformanceCard challengers={challengerPerf} />
          ) : (
            <p className="muted">暂无观察中的 Challenger。</p>
          )}
        </Panel>

        <Panel title="基因 × 环境表现" icon={<Target size={18} />}>
          {envPerformance.length > 0 ? (
            <EnvironmentPerformanceTable items={envPerformance} />
          ) : (
            <p className="muted">暂无环境分层数据，先运行复盘和周六对账任务。</p>
          )}
        </Panel>

        <Panel title="操作与审计" icon={<ShieldAlert size={18} />}>
          <div className="audit-actions">
            <button className="btn-secondary" onClick={handleDryRun} disabled={!date || loading}><GitBranch size={15} /> Dry-run preview</button>
            <button className="btn-primary" onClick={handlePropose} disabled={!date || loading}><Trophy size={15} /> Propose Challenger</button>
            <div className="audit-note">
              <b>安全规则</b>
              <span>样本、置信度、日期跨度达标后才生成 Challenger。回滚不会删除历史复盘、收益和信号。</span>
            </div>
            {dryRunPreview && <DryRunAudit preview={dryRunPreview} />}
            <div className="event-history">
              <h4>Evolution event history</h4>
              {comparisons.slice(0, 6).map((item) => (
                <div className="event-item" key={item.event_id}>
                  <strong>{String(item.status)}</strong>
                  <span>{item.parent_gene_id} → {item.child_gene_id ?? 'pending'}</span>
                </div>
              ))}
            </div>
          </div>
        </Panel>
      </section>

      {pendingAction && (
        <ConfirmActionDialog
          title={pendingAction.title}
          description={pendingAction.description}
          impacts={pendingAction.impacts}
          confirmText={pendingAction.type === 'rollback' ? '确认回滚' : pendingAction.type === 'promote' ? '确认推广' : '确认提案'}
          danger={pendingAction.type === 'rollback'}
          onConfirm={() => {
            setPendingAction(null);
            pendingAction.execute();
          }}
          onCancel={() => setPendingAction(null)}
        />
      )}
    </div>
  );
}

function DryRunAudit({ preview }: { preview: Record<string, unknown> }) {
  const proposals = (preview.proposals ?? []) as Array<Record<string, unknown>>;
  const skipped = (preview.skipped ?? []) as Array<Record<string, unknown>>;
  return (
    <div className="dry-run-preview">
      <h4>Dry-run preview</h4>
      <p>只预览参数变化，不创建 gene，不消费 signal。</p>
      <div className="kv-grid">
        <div className="info-kv"><span>Proposals</span><b>{proposals.length}</b></div>
        <div className="info-kv"><span>Skipped</span><b>{skipped.length}</b></div>
      </div>
      {proposals.slice(0, 3).map((proposal, index) => (
        <div className="event-item" key={index}>
          <strong>{String(proposal.parent_gene_id ?? proposal.strategy_gene_id ?? 'proposal')}</strong>
          <span>{JSON.stringify(proposal.parameter_diff ?? proposal.params ?? proposal).slice(0, 160)}</span>
        </div>
      ))}
      {!!skipped.length && (
        <small className="muted-copy">{skipped.slice(0, 3).map((item) => String(item.reason ?? item.gene_id ?? 'skipped')).join(' · ')}</small>
      )}
    </div>
  );
}

function ChallengerPerformanceCard({ challengers }: { challengers: ChallengerPerf[] }) {
  return (
    <div className="challenger-perf">
      {challengers.map((ch) => (
        <div className="challenger-card" key={ch.gene_id}>
          <div className="card-header">
            <strong>{ch.name}</strong>
            <span className={`status-badge ${ch.status}`}>{ch.status}</span>
          </div>
          <div className="card-stats">
            <span>交易: {ch.trades}</span>
            <span>收益: {ch.avg_return_pct.toFixed(2)}%</span>
            <span>胜率: {(ch.win_rate * 100).toFixed(0)}%</span>
            <span>最大回撤: {ch.max_drawdown.toFixed(2)}%</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function SignalPool({
  signals,
  onAccept,
  onReject,
  onView,
}: {
  signals: Array<Record<string, unknown>>;
  onAccept: (signalId: string) => void;
  onReject: (signalId: string) => void;
  onView: (signalId: string) => void;
}) {
  if (!signals.length) return <p className="empty-state">暂无候审信号。运行复盘后会在这里显示可审核信号。</p>;
  return (
    <div className="terminal-table signal-pool-table">
      <div className="terminal-thead">
        <span>Signal</span><span>Gene</span><span>Param</span><span>Dir</span><span>Strength</span><span>Status</span><span></span>
      </div>
      {signals.slice(0, 14).map((signal, index) => (
        <div className="terminal-row" key={String(signal.signal_id ?? index)}>
          <span>{String(signal.signal_type)}</span>
          <span>{String(signal.strategy_gene_id ?? '-').replace('gene_', '')}</span>
          <span>{String(signal.param_name ?? '-')}</span>
          <span>{String(signal.direction ?? '-')}</span>
          <span>{Number(signal.strength ?? 0).toFixed(2)}</span>
          <span className="signal-actions-inline">
            <span className="status-tag warn">{String(signal.status ?? 'candidate')}</span>
            <button className="icon-action view" onClick={() => onView(String(signal.signal_id))}><Eye size={12} /></button>
            <button className="icon-action accept" onClick={() => onAccept(String(signal.signal_id))}>接受</button>
            <button className="icon-action reject" onClick={() => onReject(String(signal.signal_id))}>拒绝</button>
          </span>
        </div>
      ))}
    </div>
  );
}

function PlannerAlignment({ view }: { view: PlannerVsPicks }) {
  return (
    <div className="planner-alignment">
      <div className="kpi-row planner-kpis">
        <div className="info-kv"><span>对齐率</span><b>{(view.alignment_rate * 100).toFixed(0)}%</b></div>
        <div className="info-kv"><span>已对齐</span><b>{view.aligned_count}</b></div>
        <div className="info-kv"><span>总 picks</span><b>{view.total_picks}</b></div>
      </div>
      {view.focus_industries.length > 0 && (
        <div className="planner-focus">
          <b>Planner 关注：</b>{view.focus_industries.join('、')}
        </div>
      )}
      {view.picks.length > 0 && (
        <div className="terminal-table">
          <div className="terminal-table-header">
            <div className="col">股票</div>
            <div className="col">行业</div>
            <div className="col">评分</div>
            <div className="col">策略</div>
            <div className="col">评估</div>
            <div className="col">对齐</div>
          </div>
          {view.picks.map((pick, i) => (
            <div className="terminal-table-row" key={i}>
              <div className="col">{pick.stock_code}</div>
              <div className="col">{pick.industry || '-'}</div>
              <div className="col">{pick.score.toFixed(3)}</div>
              <div className="col">{pick.strategy_gene_id}</div>
              <div className="col">{pick.eval_verdict || '-'}</div>
              <div className="col">{pick.planner_aligned ? '✓' : '✗'}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const ENV_LABELS: Record<string, string> = {
  bull: '牛市',
  bear: '熊市',
  range_up: '震荡上行',
  range_down: '震荡下行',
  range_medium: '震荡盘整',
};

function envLabel(env: string): string {
  return ENV_LABELS[env] ?? env;
}

function EnvironmentPerformanceTable({ items }: { items: EnvPerfItem[] }) {
  return (
    <div className="terminal-table env-perf-table">
      <div className="terminal-thead">
        <span>基因</span>
        <span>环境</span>
        <span>区间</span>
        <span>交易数</span>
        <span>胜率</span>
        <span>平均收益</span>
        <span>Alpha</span>
        <span>最大回撤</span>
      </div>
      {items.slice(0, 20).map((item, index) => {
        const alphaColor = item.alpha > 0 ? '#4ade80' : item.alpha < 0 ? '#f87171' : '#888';
        const retColor = item.avg_return > 0 ? '#4ade80' : item.avg_return < 0 ? '#f87171' : '#888';
        return (
          <div className="terminal-row" key={`${item.gene_id}-${item.market_environment}-${item.period_start}-${index}`}>
            <span>{item.gene_id.replace('gene_', '').replace('_v1', '')}</span>
            <span>{envLabel(item.market_environment)}</span>
            <span>{item.period_start} ~ {item.period_end}</span>
            <span>{item.trade_count}</span>
            <span>{(item.win_rate * 100).toFixed(0)}%</span>
            <span style={{ color: retColor }}>{(item.avg_return * 100).toFixed(2)}%</span>
            <span style={{ color: alphaColor }}>{(item.alpha * 100).toFixed(2)}%</span>
            <span>{(item.max_drawdown * 100).toFixed(2)}%</span>
          </div>
        );
      })}
    </div>
  );
}
