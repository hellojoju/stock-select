import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Activity, AlertCircle, CheckCircle, ChevronDown, ChevronRight, Eye,
  Loader, Pause, Play, RefreshCw, Search, Terminal, TrendingUp, X, ExternalLink,
} from 'lucide-react';
import Metric from '../components/Metric';
import Panel from '../components/Panel';
import { PageHeader } from '../components/PageHeader';
import {
  fetchAnnouncementAlerts,
  fetchAnnouncementMonitorRuns,
  fetchLiveStats,
  fetchScanEvents,
  fetchScanStatus,
  triggerAnnouncementScan,
  pauseAutoAnnouncementScan,
  resumeAutoAnnouncementScan,
  acknowledgeAlert,
  dismissAlert,
} from '../api/client';
import type { AnnouncementAlert, MonitorRun } from '../types';

type ScanEventType = {
  timestamp: string;
  type: string;
  message: string;
  detail: string;
  level: string;
};

const ALERT_TYPE_LABELS: Record<string, string> = {
  earnings_beat: '业绩大增',
  large_order: '大额订单',
  tech_breakthrough: '技术突破',
  asset_injection: '资产注入',
  m_and_a: '兼并重组',
};

const ALERT_TYPE_TONES: Record<string, string> = {
  earnings_beat: 'status-tag danger',
  large_order: 'status-tag warn',
  tech_breakthrough: 'status-tag ok',
  asset_injection: 'muted',
  m_and_a: 'ok',
};

const EVENT_LEVEL_TONES: Record<string, string> = {
  info: '',
  success: 'ok',
  warning: 'warn',
  error: 'error',
};

export default function AnnouncementMonitorPage() {
  const [date, setDate] = useState('');
  const [loading, setLoading] = useState(false);

  // Data
  const [alerts, setAlerts] = useState<AnnouncementAlert[]>([]);
  const [stats, setStats] = useState<{ total: number; new_count: number; max_score: number; by_type: Record<string, number> } | null>(null);
  const [runs, setRuns] = useState<MonitorRun[]>([]);
  const [events, setEvents] = useState<ScanEventType[]>([]);
  const [schedulerRunning, setSchedulerRunning] = useState(false);
  const [autoPaused, setAutoPaused] = useState<boolean | null>(null);

  // Selection
  const [selectedAlert, setSelectedAlert] = useState<AnnouncementAlert | null>(null);

  // Filters
  const [filterType, setFilterType] = useState('all');
  const [filterStatus, setFilterStatus] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');

  // Collapse
  const [logCollapsed, setLogCollapsed] = useState(true);
  const [expandedEventIdx, setExpandedEventIdx] = useState<number | null>(null);

  // Feedback
  const [scanning, setScanning] = useState(false);
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);

  // Auto-clear toast after 4s
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(t);
  }, [toast]);

  // Polling ref
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadData = useCallback(async (targetDate?: string) => {
    setLoading(true);
    const d = targetDate || date;
    try {
      const [alertsData, statsData, runsData, eventsData, statusData] = await Promise.all([
        fetchAnnouncementAlerts({ limit: 200, ...(d ? { date: d } : {}) }),
        fetchLiveStats(d || undefined),
        fetchAnnouncementMonitorRuns(20),
        fetchScanEvents(100),
        fetchScanStatus(),
      ]);
      setAlerts(alertsData);
      setStats(statsData);
      setRuns(runsData);
      setEvents(eventsData);
      setSchedulerRunning(statusData.scheduler_running);
      setAutoPaused(statusData.auto_paused);
    } catch {
      // ignore poll errors
    } finally {
      setLoading(false);
    }
  }, [date]);

  const handleRefresh = () => loadData();

  // Auto-poll every 15s
  useEffect(() => {
    loadData();
    // One-shot scan on page mount — always works, no cron needed
    triggerAnnouncementScan().then((r) => { if (r.success) loadData(); });
    pollRef.current = setInterval(loadData, 15000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [loadData]);

  const handleTriggerScan = async () => {
    setScanning(true);
    setToast(null);
    try {
      const r = await triggerAnnouncementScan();
      if (r.success) {
        await loadData();
        setToast({ message: `扫描完成，发现 ${r.alerts_found} 条报警`, type: 'success' });
      } else {
        setToast({ message: r.error || '扫描失败', type: 'error' });
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '网络请求失败，请检查服务端';
      setToast({ message: msg, type: 'error' });
    } finally {
      setScanning(false);
    }
  };

  const handleToggleAuto = async () => {
    if (autoPaused) {
      await resumeAutoAnnouncementScan();
      setAutoPaused(false);
    } else {
      await pauseAutoAnnouncementScan();
      setAutoPaused(true);
    }
  };

  const handleAcknowledge = async (alertId: string) => {
    await acknowledgeAlert(alertId);
    setAlerts((prev) => prev.map((a) => a.alert_id === alertId ? { ...a, status: 'acknowledged' as const } : a));
    setStats((prev) => prev ? { ...prev, new_count: prev.new_count - 1 } : prev);
  };

  const handleDismiss = async (alertId: string) => {
    await dismissAlert(alertId);
    setAlerts((prev) => prev.map((a) => a.alert_id === alertId ? { ...a, status: 'dismissed' as const } : a));
    if (selectedAlert?.alert_id === alertId) setSelectedAlert(null);
    setStats((prev) => prev ? { ...prev, new_count: prev.new_count - 1 } : prev);
  };

  const filteredAlerts = alerts.filter((a) => {
    if (filterType !== 'all' && a.alert_type !== filterType) return false;
    if (filterStatus !== 'all' && a.status !== filterStatus) return false;
    if (searchQuery && !a.stock_code.includes(searchQuery) && !(a.stock_name?.includes(searchQuery))) return false;
    return true;
  });

  return (
    <div className="page terminal-page">
      {/* ── Header ── */}
      <PageHeader
        eyebrow="实时监控 · A股公告猎手"
        title="公告猎手"
        date={date}
        onDateChange={(d) => { setDate(d); loadData(d); }}
        onRefresh={handleRefresh}
        loading={loading}
      >
        <button className="btn-primary" onClick={handleTriggerScan} disabled={scanning}>
          {scanning ? <Loader size={15} className="spin" /> : <Play size={15} />}
          {scanning ? '扫描中...' : '立即扫描'}
        </button>
        {schedulerRunning && (
          <button className="btn-secondary" onClick={handleToggleAuto} title={autoPaused ? '恢复自动扫描' : '暂停自动扫描'}>
            {autoPaused ? <Play size={14} /> : <Pause size={14} />}
            自动: {autoPaused ? '关' : '开'}
          </button>
        )}
        <button className="btn-secondary" onClick={handleRefresh}><RefreshCw size={15} /> 刷新</button>
      </PageHeader>

      {/* ── Status strip ── */}
      <ScannerStatusStrip
        schedulerRunning={schedulerRunning}
        autoPaused={autoPaused}
        alertCount={alerts.length}
        newCount={stats?.new_count ?? 0}
        lastRun={runs[0]}
      />

      {toast && (
        <div className={`toast ${toast.type === 'success' ? 'toast-success' : 'toast-error'}`}>
          {toast.type === 'success' ? <CheckCircle size={16} /> : <AlertCircle size={16} />}
          <span>{toast.message}</span>
          <button className="toast-close" onClick={() => setToast(null)}><X size={14} /></button>
        </div>
      )}

      {/* ── KPI ── */}
      <section className="kpi-row">
        <Metric label="今日报警" value={stats?.total ?? 0} />
        <Metric label="未处理" value={stats?.new_count ?? 0} />
        <Metric label="最高情绪分" value={stats?.max_score ? stats.max_score.toFixed(2) : '-'} />
        <Metric label="覆盖类型" value={stats?.by_type ? Object.keys(stats.by_type).length : 0} />
        <Metric label="自动扫描" value={!schedulerRunning ? '未启动' : autoPaused ? '已暂停' : '运行中'} />
      </section>

      {/* ── Main area: alert list + detail side-by-side ── */}
      <div className="workbench-grid">
        {/* Left: alert list */}
        <div className="dash-col dash-col-main">
          {/* Filters */}
          <div className="filter-bar monitor-filters">
            <div className="stock-search-box" style={{ minWidth: 160 }}>
              <div className="stock-search-input">
                <Search size={14} />
                <input
                  placeholder="搜索代码/名称..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
              </div>
            </div>
            <select
              value={filterType}
              onChange={(e) => setFilterType(e.target.value)}
              className="filter-select"
            >
              <option value="all">全部类型</option>
              <option value="earnings_beat">业绩大增</option>
              <option value="large_order">大额订单</option>
              <option value="tech_breakthrough">技术突破</option>
              <option value="asset_injection">资产注入</option>
              <option value="m_and_a">兼并重组</option>
            </select>
            <select
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value)}
              className="filter-select"
            >
              <option value="all">全部状态</option>
              <option value="new">未处理</option>
              <option value="acknowledged">已确认</option>
              <option value="dismissed">已忽略</option>
            </select>
            <span className="filter-count">{filteredAlerts.length} 条</span>
          </div>

          {/* Alert table */}
          <Panel title="报警列表" icon={<Activity size={18} />}>
            {filteredAlerts.length === 0 ? (
              <p className="empty-state">没有符合条件的报警。启动扫描后将在此显示匹配的利好消息。</p>
            ) : (
              <div className="terminal-table monitor-table">
                <div className="terminal-thead">
                  <span>类型</span>
                  <span>股票</span>
                  <span>标题</span>
                  <span>情绪</span>
                  <span>资金</span>
                  <span>板块</span>
                  <span>状态</span>
                  <span>时间</span>
                </div>
                {filteredAlerts.map((a) => (
                  <button
                    key={a.alert_id}
                    className={`terminal-row candidate-row ${selectedAlert?.alert_id === a.alert_id ? 'selected' : ''}`}
                    onClick={() => setSelectedAlert(a)}
                  >
                    <span className={`status-tag ${ALERT_TYPE_TONES[a.alert_type] || ''}`}>
                      {ALERT_TYPE_LABELS[a.alert_type] || a.alert_type}
                    </span>
                    <span>
                      <b>{a.stock_code}</b>
                      {a.stock_name && <small>{a.stock_name}</small>}
                    </span>
                    <span className="truncate-cell" title={a.title}>{a.title}</span>
                    <span>{a.sentiment_score.toFixed(2)}</span>
                    <span>{a.capital_flow_score != null ? a.capital_flow_score.toFixed(2) : '-'}</span>
                    <span>{a.sector_heat_score != null ? a.sector_heat_score.toFixed(2) : '-'}</span>
                    <span>
                      <span className={`status-tag ${
                        a.status === 'new' ? 'danger' :
                        a.status === 'acknowledged' ? 'ok' : 'muted'
                      }`}>
                        {a.status === 'new' ? '新' : a.status === 'acknowledged' ? '已确认' : '已忽略'}
                      </span>
                    </span>
                    <span className="time-cell">{new Date(a.discovered_at).toLocaleTimeString('zh-CN')}</span>
                  </button>
                ))}
              </div>
            )}
          </Panel>
        </div>

        {/* Right: stock detail */}
        <div className="dash-col dash-col-side">
          <SelectedStockDetail
            alert={selectedAlert}
            onAcknowledge={handleAcknowledge}
            onDismiss={handleDismiss}
          />
        </div>
      </div>

      {/* ── Collapsible scan log ── */}
      <div className="panel collapsible-log">
        <button
          className="collapsible-log-header"
          onClick={() => setLogCollapsed(!logCollapsed)}
        >
          {logCollapsed ? <ChevronRight size={16} /> : <ChevronDown size={16} />}
          <Terminal size={16} />
          <span>扫描活动日志</span>
          <span className="filter-count">{events.length} 条事件</span>
          {events.filter((e) => e.level === 'error').length > 0 && (
            <span className="status-tag danger">{events.filter((e) => e.level === 'error').length} 错误</span>
          )}
        </button>
        {!logCollapsed && (
          <div className="collapsible-log-body">
            <div className="timeline-list compact" style={{ maxHeight: 280, overflowY: 'auto' }}>
              {events.length === 0 ? (
                <div className="empty-state">暂无事件记录。</div>
              ) : (
                events.slice().reverse().map((evt: ScanEventType, i: number) => {
                  // Parse JSON detail for source_result and classify_done
                  let rawItems: Array<{ title: string; stock: string; url?: string }> | null = null;
                  let classifyDetails: Array<Record<string, unknown>> | null = null;
                  const isExpandable = evt.type === 'source_result' || evt.type === 'classify_done';
                  const isExpanded = expandedEventIdx === i;

                  if (evt.type === 'source_result') {
                    try { rawItems = JSON.parse(evt.detail); } catch { /* not JSON */ }
                  } else if (evt.type === 'classify_done') {
                    try { classifyDetails = JSON.parse(evt.detail); } catch { /* not JSON */ }
                  }

                  return (
                    <div key={i} className={`timeline-item ${EVENT_LEVEL_TONES[evt.level] || ''}`}>
                      <i />
                      <div>
                        <strong>
                          <span className="event-type-tag">{evt.message}</span>
                          <span className="event-timestamp">{evt.timestamp}</span>
                        </strong>

                        {rawItems && (
                          <>
                            <button
                              className="raw-items-toggle"
                              onClick={() => setExpandedEventIdx(isExpanded ? null : i)}
                            >
                              {isExpanded ? '收起' : `查看 ${rawItems.length} 条公告`}
                            </button>
                            {isExpanded && (
                              <div className="raw-items-list">
                                {rawItems.map((r, j) => (
                                  <div key={j} className="raw-item">
                                    <span className="raw-item-stock">{r.stock || '—'}</span>
                                    {r.url ? (
                                      <a className="raw-item-title" href={r.url} target="_blank" rel="noopener noreferrer" title={r.title}>
                                        {r.title}
                                        <ExternalLink size={11} className="raw-item-link-icon" />
                                      </a>
                                    ) : (
                                      <span className="raw-item-title" title={r.title}>{r.title}</span>
                                    )}
                                  </div>
                                ))}
                              </div>
                            )}
                          </>
                        )}

                        {classifyDetails && classifyDetails.length > 0 && (
                          <>
                            <button
                              className="raw-items-toggle"
                              onClick={() => setExpandedEventIdx(isExpanded ? null : i)}
                            >
                              {isExpanded ? '收起' : `查看 ${classifyDetails.length} 条详情`}
                            </button>
                            {isExpanded && (
                              <div className="classify-detail-list">
                                {classifyDetails.map((d, j) => (
                                  <ClassifyDetailRow key={j} data={d} />
                                ))}
                              </div>
                            )}
                          </>
                        )}

                        {!isExpandable && evt.detail && <small>{evt.detail}</small>}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
            {/* Recent runs summary */}
            {runs.length > 0 && (
              <div className="collapsible-log-runs">
                <h4>轮询记录</h4>
                <div className="terminal-table run-table">
                  <div className="terminal-thead">
                    <span>数据源</span>
                    <span>状态</span>
                    <span>获取文档</span>
                    <span>产生报警</span>
                    <span>时间</span>
                  </div>
                  {runs.slice(0, 8).map((run) => (
                    <div key={run.run_id} className="terminal-row">
                      <span>{run.source}</span>
                      <span>
                        <span className={`status-tag ${run.status === 'completed' ? 'ok' : run.status === 'error' ? 'danger' : 'warn'}`}>
                          {run.status === 'completed' ? '完成' : run.status === 'error' ? '失败' : '运行中'}
                        </span>
                      </span>
                      <span>{run.new_documents}</span>
                      <span>{run.alerts_generated}</span>
                      <span className="time-cell">{new Date(run.started_at).toLocaleTimeString('zh-CN')}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function ClassifyDetailRow({ data }: { data: Record<string, unknown> }) {
  const resultTag = data.result as string | undefined;
  const [expanded, setExpanded] = useState(false);

  // Filtered items (noise / 去重 / 无股票)
  if (resultTag) {
    const reason = data.reason as string | undefined;
    const matchedPattern = data.matched_pattern as string | undefined;
    const alertType = data.type as string | undefined;
    return (
      <div className="classify-row">
        <span className="classify-row-stock">{data.stock as string}</span>
        <span className="classify-row-title" title={data.title as string}>{data.title as string}</span>
        <span className={`classify-row-tag ${resultTag === '去重' ? 'warn' : resultTag === '过滤' ? 'muted' : 'muted'}`}>
          {resultTag}
        </span>
        {(reason || alertType) && (
          <span className="classify-row-reason">
            {alertType && <span className="classify-type-tag">{alertType}</span>}
            {reason && <span>{reason}{matchedPattern ? `「${matchedPattern}」` : ''}</span>}
          </span>
        )}
      </div>
    );
  }

  // Full sentiment analysis result — show summary + expandable detail
  const composite = data.composite as number | undefined;
  const confidence = data.confidence as number | undefined;
  const opportunityType = data.opportunity_type as string | undefined;
  const typeBonus = data.type_bonus as number | undefined;
  const dimensions = data.dimensions as Record<string, Record<string, unknown>> | undefined;

  if (composite == null) {
    // Error case
    return (
      <div className="classify-row classify-row-error">
        <span className="classify-row-stock">{data.stock as string}</span>
        <span className="classify-row-title">{data.name as string}</span>
        <span className="classify-row-tag ok">{data.alert_type as string}</span>
        <span className="classify-error">{(data.error as string) || '评分失败'}</span>
      </div>
    );
  }

  const dimLabels: Record<string, string> = {
    capital_flow: '资金流向',
    sector_heat: '板块热度',
    chip_structure: '筹码结构',
    shareholder_trend: '股东趋势',
  };

  return (
    <div className="classify-row classify-row-scored">
      <div className="classify-row-header">
        <span className="classify-row-stock">{data.stock as string}</span>
        <span className="classify-row-title" title={data.name as string}>{data.name as string}</span>
        <span className="classify-row-tag ok">{data.alert_type as string}</span>
        <span className="classify-score-badges">
          <span className="classify-composite" style={{
            color: composite >= 0.7 ? 'var(--green)' : composite >= 0.5 ? 'var(--amber)' : 'var(--muted)',
          }}>
            综合 {composite.toFixed(3)}
          </span>
          {confidence != null && (
            <span className="classify-confidence">置信 {confidence.toFixed(2)}</span>
          )}
          {opportunityType && (
            <span className="classify-opportunity">{opportunityType}</span>
          )}
        </span>
        <button className="classify-expand-btn" onClick={() => setExpanded(!expanded)}>
          {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          分析过程
        </button>
      </div>

      {expanded && dimensions && (
        <div className="classify-detail-body">
          {/* Weight breakdown */}
          <div className="classify-weight-summary">
            <span className="classify-weight-label">权重: </span>
            {Object.entries(dimensions).map(([key, dim]) => (
              <span key={key} className="classify-weight-item">
                {dimLabels[key] || key} {(dim.weight as number * 100).toFixed(0)}%
              </span>
            ))}
            {typeBonus != null && typeBonus > 0 && (
              <span className="classify-type-bonus">类型加成 +{typeBonus.toFixed(2)}</span>
            )}
          </div>

          {/* Each dimension */}
          {Object.entries(dimensions).map(([key, dim]) => {
            const score = dim.score as number;
            const evidence = dim.evidence as string | undefined;
            const weight = dim.weight as number;
            const contribution = (score * weight).toFixed(3);
            const scoreColor = score >= 0.7 ? 'var(--green)' : score >= 0.5 ? 'var(--amber)' : 'var(--muted)';
            return (
              <div key={key} className="classify-dimension-row">
                <span className="classify-dim-name">{dimLabels[key] || key}</span>
                <span className="classify-dim-score" style={{ color: scoreColor }}>{score.toFixed(3)}</span>
                <span className="classify-dim-weight">×{(weight * 100).toFixed(0)}%</span>
                <span className="classify-dim-contribution">= {contribution}</span>
                {evidence && <span className="classify-dim-evidence">{evidence}</span>}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ScannerStatusStrip({ schedulerRunning, autoPaused, alertCount, newCount, lastRun }: {
  schedulerRunning: boolean;
  autoPaused: boolean | null;
  alertCount: number;
  newCount: number;
  lastRun: MonitorRun | undefined;
}) {
  const autoLabel = !schedulerRunning ? '未启动' : autoPaused ? '已暂停' : '运行中';
  const isWarn = !schedulerRunning || autoPaused === true;
  return (
    <div className="system-strip" style={{
      background: isWarn ? 'var(--surface-warn)' : '#f0faf8',
      borderColor: isWarn ? '#edd89e' : '#b9deda',
    }}>
      <span className={`status-pill ${isWarn ? 'demo' : 'live'}`}>
        自动: {autoLabel}
      </span>
      <span className="health-badge ok">累计 {alertCount} 条</span>
      {newCount > 0 && <span className="health-badge danger">未处理 {newCount} 条</span>}
      <span className="strip-message">
        {lastRun ? `上次轮询 ${lastRun.source} · ${lastRun.status}` : '尚未扫描'}
        {' · '}点击「立即扫描」手动触发
      </span>
    </div>
  );
}

function SelectedStockDetail({ alert, onAcknowledge, onDismiss }: {
  alert: AnnouncementAlert | null;
  onAcknowledge: (id: string) => void;
  onDismiss: (id: string) => void;
}) {
  const [sentimentExpanded, setSentimentExpanded] = useState(false);

  if (!alert) {
    return (
      <Panel title="选股原因" icon={<Search size={18} />}>
        <p className="empty-state">点击报警列表中的股票可查看详细选股原因。</p>
      </Panel>
    );
  }

  const dimensions = [
    { key: 'capital_flow', label: '资金流向', score: alert.capital_flow_score, evidence: alert.capital_flow_evidence, weight: 0.30 },
    { key: 'sector_heat', label: '板块热度', score: alert.sector_heat_score, evidence: alert.sector_heat_evidence, weight: 0.30 },
    { key: 'chip_structure', label: '筹码结构', score: alert.chip_structure_score, evidence: alert.chip_structure_evidence, weight: 0.20 },
    { key: 'shareholder_trend', label: '股东趋势', score: alert.shareholder_trend_score, evidence: alert.shareholder_trend_evidence, weight: 0.20 },
  ];

  return (
    <Panel title={`选股原因 · ${alert.stock_code}`} icon={<Eye size={18} />}>
      <div className="inspector">
        <div className="inspector-hero">
          <span>{ALERT_TYPE_LABELS[alert.alert_type] || alert.alert_type}</span>
          <h3>
            {alert.stock_code}
            {alert.stock_name ? <span style={{ fontSize: 14, fontWeight: 400, marginLeft: 8, color: 'var(--muted)' }}>{alert.stock_name}</span> : null}
          </h3>
          {alert.industry && <div style={{ fontSize: 12, color: 'var(--teal)' }}>行业: {alert.industry}</div>}
        </div>

        <div className="kv-grid">
          <div className="info-kv">
            <span>情绪评分</span>
            <b style={{ color: alert.sentiment_score >= 0.7 ? 'var(--green)' : alert.sentiment_score >= 0.5 ? 'var(--amber)' : 'var(--muted)' }}>
              {alert.sentiment_score.toFixed(3)}
            </b>
          </div>
          <div className="info-kv">
            <span>置信度</span>
            <b style={{ color: alert.confidence >= 0.7 ? 'var(--green)' : 'var(--amber)' }}>
              {alert.confidence.toFixed(2)}
            </b>
          </div>
        </div>

        {/* Expandable sentiment analysis process */}
        <div className="collapsible-log" style={{ marginTop: 8 }}>
          <button
            className="collapsible-log-header"
            onClick={() => setSentimentExpanded(!sentimentExpanded)}
          >
            {sentimentExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            <TrendingUp size={14} />
            <span>情绪分析过程</span>
          </button>
          {sentimentExpanded && (
            <div className="collapsible-log-body" style={{ padding: '8px 0' }}>
              {/* Weight breakdown */}
              <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8, padding: '0 4px' }}>
                权重: 资金流向 30% · 板块热度 30% · 筹码结构 20% · 股东趋势 20%
              </div>

              {dimensions.map((dim) => {
                const score = dim.score ?? 0.5;
                const contribution = score * dim.weight;
                const scoreColor = score >= 0.7 ? 'var(--green)' : score >= 0.5 ? 'var(--amber)' : 'var(--muted)';
                return (
                  <div key={dim.key} style={{
                    display: 'flex', flexDirection: 'column', gap: 2,
                    padding: '6px 4px', borderBottom: '1px solid var(--border)',
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
                      <span style={{ fontWeight: 600, minWidth: 64 }}>{dim.label}</span>
                      <span style={{ color: scoreColor, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
                        {score.toFixed(3)}
                      </span>
                      <span style={{ color: 'var(--muted)', fontSize: 11 }}>×{dim.weight * 100}%</span>
                      <span style={{ color: 'var(--teal)', fontSize: 12, fontWeight: 600 }}>= {contribution.toFixed(3)}</span>
                    </div>
                    {dim.evidence && (
                      <div style={{ fontSize: 11, color: 'var(--muted)', lineHeight: 1.5, paddingLeft: 64 }}>
                        {dim.evidence}
                      </div>
                    )}
                    {!dim.evidence && (
                      <div style={{ fontSize: 11, color: 'var(--muted-dim)', paddingLeft: 64 }}>暂无数据</div>
                    )}
                  </div>
                );
              })}

              <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 6, padding: '0 4px', fontStyle: 'italic' }}>
                综合评分 = 资金流向×30% + 板块热度×30% + 筹码结构×20% + 股东趋势×20%
              </div>
            </div>
          )}
        </div>

        <h4 style={{ margin: '8px 0 4px', color: 'var(--muted)', fontSize: 12, fontWeight: 800 }}>公告标题</h4>
        {alert.source_url ? (
          <a className="detail-copy" href={alert.source_url} target="_blank" rel="noopener noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: 4, color: 'var(--accent)', textDecoration: 'underline', textUnderlineOffset: 2 }}>
            {alert.title}
            <ExternalLink size={12} />
          </a>
        ) : (
          <p className="detail-copy">{alert.title}</p>
        )}
        {alert.summary && (
          <>
            <h4 style={{ margin: '8px 0 4px', color: 'var(--muted)', fontSize: 12, fontWeight: 800 }}>摘要</h4>
            <p className="detail-copy">{alert.summary}</p>
          </>
        )}

        <div className="detail-meta">
          <span>来源: {alert.source}</span>
          <span>时间: {new Date(alert.discovered_at).toLocaleString('zh-CN')}</span>
        </div>

        {alert.status === 'new' && (
          <div className="filter-actions" style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button className="btn-primary" style={{ flex: 1 }} onClick={() => onAcknowledge(alert.alert_id)}>
              <TrendingUp size={14} /> 确认
            </button>
            <button className="btn-secondary" style={{ flex: 1 }} onClick={() => onDismiss(alert.alert_id)}>
              <X size={14} /> 忽略
            </button>
          </div>
        )}
        {alert.status === 'acknowledged' && <span className="status-tag ok">已确认</span>}
        {alert.status === 'dismissed' && <span className="status-tag muted">已忽略</span>}
      </div>
    </Panel>
  );
}
