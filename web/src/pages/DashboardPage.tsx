import { useEffect, useMemo, useState } from 'react';
import { Activity, AlertTriangle, Bell, CheckCircle2, Play, ShieldCheck, Wifi, WifiOff, WifiHigh } from 'lucide-react';
import Metric from '../components/Metric';
import Panel from '../components/Panel';
import { PageHeader, SystemStatusStrip } from '../components/PageHeader';
import ReviewSummary from '../sections/ReviewSummary';
import PickList from '../sections/PickList';
import { llmStatusLabel } from '../lib/llmStatus';
import { API_BASE } from '../api/client';
import type { Dashboard, Availability } from '../types';

export interface SimOrder {
  order_id: string;
  decision_id: string;
  trading_date: string;
  stock_code: string;
  stock_name?: string;
  side: string;
  price: number;
  quantity: number;
  position_pct: number;
  fee: number;
  slippage_pct: number;
  status: string;
  reject_reason?: string;
  score?: number;
  strategy_gene_id?: string;
}

export default function DashboardPage() {
  const [date, setDate] = useState('');
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [availability, setAvailability] = useState<Availability | null>(null);
  const [selectedStockCode, setSelectedStockCode] = useState('');
  const [loading, setLoading] = useState(false);
  const [simOrders, setSimOrders] = useState<SimOrder[]>([]);
  const [announcementCount, setAnnouncementCount] = useState<number>(0);

  async function loadDashboard(targetDate = date) {
    setLoading(true);
    const suffix = targetDate ? `?date=${targetDate}` : '';
    const [dashRes, availRes] = await Promise.all([
      fetch(`${API_BASE}/api/dashboard${suffix}`),
      fetch(`${API_BASE}/api/availability${suffix}`),
    ]);
    const json = await dashRes.json();
    setDashboard(json);
    if (!date && json.date) setDate(json.date);
    if (availRes.ok) {
      const availJson = await availRes.json();
      setAvailability(availJson);
    }
    // Load announcement stats
    try {
      const statsRes = await fetch(`${API_BASE}/api/announcements/live-stats${suffix}`);
      if (statsRes.ok) {
        const stats = await statsRes.json();
        setAnnouncementCount(stats.total ?? 0);
      }
    } catch {
      // ignore
    }
    setLoading(false);
  }

  async function loadSimOrders(targetDate: string) {
    if (!targetDate) return;
    try {
      const response = await fetch(`${API_BASE}/api/sim-orders?date=${targetDate}`);
      const json = await response.json();
      setSimOrders(json);
    } catch {
      setSimOrders([]);
    }
  }

  async function trigger(phase: string) {
    if (!date) return;
    setLoading(true);
    await fetch(`${API_BASE}/api/runs/${phase}?date=${date}`, { method: 'POST' });
    await loadDashboard(date);
  }

  useEffect(() => { void loadDashboard(''); }, []);
  useEffect(() => { if (date) void loadSimOrders(date); }, [date]);

  const best = useMemo(() => dashboard?.performance?.[0], [dashboard]);
  const warnings = Number(dashboard?.data_quality_summary?.warning_count ?? dashboard?.data_quality?.length ?? 0);
  const selectedPick = useMemo(
    () => dashboard?.picks?.find((pick) => pick.stock_code === selectedStockCode) ?? dashboard?.picks?.[0],
    [dashboard, selectedStockCode],
  );

  return (
    <div className="page terminal-page">
      <PageHeader
        eyebrow="ASIA/SHANGHAI · PAPER TRADING"
        title="今日工作台"
        date={date}
        onDateChange={setDate}
        onRefresh={() => loadDashboard(date)}
        loading={loading}
      >
        <button className="btn-primary" onClick={() => trigger('preopen_pick')} disabled={!date || loading}><Play size={15} /> 选股</button>
        <button className="btn-secondary" onClick={() => trigger('simulate')} disabled={!date || loading}><ShieldCheck size={15} /> 模拟</button>
      </PageHeader>

      <SystemStatusStrip
        mode={dashboard?.runtime_mode}
        marketEnvironment={dashboard?.market_environment}
        evidenceMessage={dashboard?.evidence_status?.message}
        warnings={warnings}
        dataQualitySummary={dashboard?.data_quality_summary ?? null}
        llmStatus={llmStatusLabel(dashboard?.llm_status)}
      />

      <DataFreshnessBar date={dashboard?.date} runs={dashboard?.runs ?? []} />
      <AvailabilityCard availability={availability} />

      <section className="kpi-row">
        <Metric label="市场环境" value={String(dashboard?.market_environment ?? '-')} />
        <Metric label="推荐数" value={dashboard?.picks?.length ?? 0} />
        <Metric label="模拟成交" value={`${dashboard?.picks?.filter((p) => p.return_pct !== undefined && p.return_pct !== null).length ?? 0}/${dashboard?.picks?.length ?? 0}`} />
        <Metric label="数据健康" value={warnings ? 'Partial' : 'OK'} />
        <Metric label="公告报警" value={announcementCount} />
      </section>

      <section className="workbench-grid">
        <div className="dash-col dash-col-main">
          <Panel title="推荐队列" icon={<Activity size={18} />}>
            <PickList picks={dashboard?.picks ?? []} onSelectStock={setSelectedStockCode} />
          </Panel>
          <Panel title="模拟盘持仓/成交" icon={<ShieldCheck size={18} />}>
            <SimulationTable picks={dashboard?.picks ?? []} orders={simOrders} />
          </Panel>
        </div>
        <div className="dash-col dash-col-side">
          <Panel title="推荐速览" icon={<Activity size={18} />}>
            <PickQuickDetail pick={selectedPick} />
          </Panel>
          <Panel title="Pipeline 时间线" icon={<CheckCircle2 size={18} />}>
            <PipelineTimeline runs={dashboard?.runs ?? []} />
          </Panel>
          <Panel title="数据质量告警" icon={<AlertTriangle size={18} />}>
            <DataAlerts dashboard={dashboard} />
          </Panel>
          <Panel title="复盘摘要" icon={<ShieldCheck size={18} />}>
            <ReviewSummary data={dashboard?.review_summary} />
          </Panel>
          <Panel title="人工待办" icon={<AlertTriangle size={18} />}>
            <div className="task-list">
              <span>审核 {Number(dashboard?.review_summary?.open_optimization_signals ?? 0)} 条优化信号</span>
              <span>查看盲点复盘和漏选原因</span>
              <span>确认市场预期源与 KPI 覆盖</span>
              <small>最佳基因：{String(best?.strategy_gene_id ?? '-')}</small>
            </div>
          </Panel>
        </div>
      </section>
    </div>
  );
}

function PickQuickDetail({ pick }: { pick?: Dashboard['picks'][number] }) {
  if (!pick) return <p className="empty-state">暂无推荐。运行选股后可在这里快速查看单只股票摘要。</p>;
  return (
    <div className="quick-detail">
      <div className="quick-detail-head">
        <div>
          <strong>{pick.stock_code}</strong>
          <small>{pick.stock_name ?? '未返回名称'}</small>
        </div>
        <span className={Number(pick.return_pct ?? 0) >= 0 ? 'status-tag ok' : 'status-tag danger'}>
          {formatPct(pick.return_pct ?? undefined)}
        </span>
      </div>
      <div className="kv-grid">
        <InfoKV label="Gene" value={pick.strategy_gene_id.replace('gene_', '')} />
        <InfoKV label="Horizon" value={pick.horizon} />
        <InfoKV label="Confidence" value={formatPct(pick.confidence)} />
        <InfoKV label="Position" value={formatPct(pick.position_pct)} />
      </div>
      <p className="detail-copy">点击推荐队列中的股票会更新此速览。完整因子、证据和错误归因请进入复盘中心。</p>
    </div>
  );
}

function InfoKV({ label, value }: { label: string; value: string }) {
  return <div className="info-kv"><span>{label}</span><b>{value}</b></div>;
}

function PipelineTimeline({ runs }: { runs: Array<Record<string, string>> }) {
  const phases = ['sync_data', 'preopen_pick', 'simulate', 'deterministic_review', 'gene_review'];
  return (
    <div className="timeline-list">
      {phases.map((phase) => {
        const run = runs.find((item) => String(item.phase) === phase);
        const status = String(run?.status ?? 'pending');
        return (
          <div className={`timeline-item ${status}`} key={phase}>
            <i />
            <div>
              <strong>{phaseLabel(phase)}</strong>
              <small>{status}{run?.finished_at ? ` · ${String(run.finished_at)}` : ''}</small>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function friendlyError(err: string): string {
  // 将技术性错误消息映射为用户友好的简短描述
  if (!err) return "";
  if (/query\.sse\.com\.cn/.test(err)) return "上交所数据源暂时无法连接";
  if (/push2.*eastmoney\.com/.test(err)) return "东方财富数据源暂时无法连接";
  if (/finance\.sina\.com\.cn/.test(err)) return "新浪财经数据源暂时无法连接";
  if (/akshare is not installed/.test(err)) return "AKShare 未安装";
  if (/baostock is not installed/.test(err)) return "Baostock 未安装";
  if (/Max retries exceeded/.test(err) || /NameResolutionError/.test(err) || /Failed to resolve/.test(err))
    return "外部数据源网络连接异常";
  return err;
}

function DataAlerts({ dashboard }: { dashboard: Dashboard | null }) {
  const quality = dashboard?.data_quality ?? [];
  const status = dashboard?.data_status ?? [];
  if (!quality.length && !status.length) return <p className="empty-state">暂无数据告警。</p>;

  return (
    <div className="alert-list">
      {quality.slice(0, 4).map((item, index) => {
        const msg = String(item.message ?? item.error ?? '');
        const raw = msg;
        const display = friendlyError(msg);
        return (
          <div className="alert-row" key={`quality-${index}`}>
            <b>{String(item.stock_code ?? item.source ?? 'DATA')}</b>
            <span>{String(item.status ?? 'warning')}</span>
            <small title={raw}>{display}</small>
          </div>
        );
      })}
      {status.filter((item) => String(item.status) !== 'ok').slice(0, 3).map((item, index) => {
        const msg = String(item.error ?? item.status ?? '');
        const raw = msg;
        const display = friendlyError(msg);
        return (
          <div className="alert-row" key={`status-${index}`}>
            <b>{String(item.source)}</b>
            <span>{String(item.dataset)}</span>
            <small title={raw}>{display}</small>
          </div>
        );
      })}
    </div>
  );
}

function SimulationTable({ picks, orders }: { picks: Dashboard['picks']; orders: SimOrder[] }) {
  if (!orders.length && !picks.length) {
    return <p className="empty-state">暂无模拟盘数据。运行模拟后可在此查看成交和未成交记录。</p>;
  }

  return (
    <div className="terminal-table sim-table">
      <div className="terminal-thead">
        <span>股票</span><span>状态</span><span>价格</span><span>费用</span><span>滑点</span><span>原因</span>
      </div>
      {orders.length > 0 ? orders.slice(0, 8).map((order) => (
        <div className="terminal-row" key={order.order_id}>
          <span><b>{order.stock_code}</b><small>{order.stock_name ?? ''}</small></span>
          <span className={order.status === 'filled' ? 'up' : 'down'}>
            {order.status === 'filled' ? '成交' : '未成交'}
          </span>
          <span>{order.price?.toFixed(2) ?? '-'}</span>
          <span>{order.fee != null ? order.fee.toFixed(2) : '-'}</span>
          <span>{order.slippage_pct != null ? `${(order.slippage_pct * 100).toFixed(2)}%` : '-'}</span>
          <span className="reject-cell">{order.reject_reason ?? '-'}</span>
        </div>
      )) : picks.slice(0, 6).map((pick) => (
        <div className="terminal-row" key={pick.decision_id}>
          <span><b>{pick.stock_code}</b><small>{pick.stock_name ?? ''}</small></span>
          <span className="down">待模拟</span>
          <span>-</span><span>-</span><span>-</span><span>-</span>
        </div>
      ))}
    </div>
  );
}

function phaseLabel(value: string) {
  return {
    sync_data: '08:00 数据准备',
    preopen_pick: '08:10 选股',
    simulate: '09:25 模拟买入',
    deterministic_review: '15:30 确定性复盘',
    gene_review: '周内 策略复盘',
  }[value] ?? value;
}

function DataFreshnessBar({ date, runs }: { date?: string | null; runs: Array<Record<string, string>> }) {
  const today = new Date().toISOString().slice(0, 10);
  const isToday = date === today;
  const completedPhases = runs.filter((r) => r.status === 'ok' || r.status === 'completed');

  if (!date) return null;

  return (
    <section className={`freshness-bar ${isToday ? '' : 'stale'}`}>
      <span className="freshness-date">
        交易日: <b>{date}</b>
        {isToday ? ' ✅ 今日' : ` ⚠️ ${Math.round((Date.now() - new Date(date).getTime()) / 86400000)} 天前`}
      </span>
      <span className="freshness-phases">
        {completedPhases.length > 0
          ? completedPhases.map((r) => `${r.phase}${r.finished_at ? ' ✓' : ''}`).join(' · ')
          : '暂无运行记录'}
      </span>
    </section>
  );
}

function AvailabilityCard({ availability }: { availability: Availability | null }) {
  if (!availability) return null;

  const statusConfig = {
    ok: { icon: <Wifi size={16} />, label: '全部正常', className: 'avail-ok' },
    degraded: { icon: <WifiHigh size={16} />, label: '降级运行', className: 'avail-degraded' },
    failed: { icon: <WifiOff size={16} />, label: '阻断', className: 'avail-failed' },
  }[availability.status] ?? { icon: <Wifi size={16} />, label: '未知', className: '' };

  return (
    <section className={`availability-card ${statusConfig.className}`}>
      <div className="avail-main">
        <span className="avail-icon">{statusConfig.icon}</span>
        <div>
          <strong>今日可用性：{statusConfig.label}</strong>
          <small>
            行情覆盖 {availability.price_coverage_pct.toFixed(1)}% ·
            候选 {availability.pick_count} 只 ·
            事件源 {availability.event_source_count} 个 ·
            复盘证据 {availability.review_evidence_count} 条
          </small>
        </div>
      </div>
      {availability.reasons.length > 0 && (
        <div className="avail-reasons">
          {availability.reasons.map((r, i) => (
            <span className="avail-reason" key={i}>{r}</span>
          ))}
        </div>
      )}
    </section>
  );
}

function formatPct(value?: number) {
  if (value === undefined || value === null || Number.isNaN(value)) return '-';
  return `${(value * 100).toFixed(2)}%`;
}
