import { useEffect, useState } from 'react';
import { Clock, AlertCircle, CheckCircle, RefreshCw, Play, Square } from 'lucide-react';
import { API_BASE } from '../api/client';

type SchedulerJob = {
  id: string;
  name: string;
  next_run: string | null;
};

type SchedulerStatus = {
  running: boolean;
  jobs: SchedulerJob[];
  message?: string;
};

type RunStatus = {
  run_id: string;
  phase: string;
  trading_date: string;
  status: string;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
};

type PhaseSummary = {
  phase: string;
  total_runs: number;
  ok_runs: number;
  error_runs: number;
  last_run_date: string | null;
  last_run_status: string | null;
};

type DailyReport = {
  trading_date: string;
  phases_run: string[];
  phases_missing: string[];
  all_ok: boolean;
  errors: string[];
};

type ErrorEntry = {
  phase: string;
  trading_date: string;
  error: string;
  started_at: string;
};

export default function SchedulerPanel() {
  const [date, setDate] = useState('');
  const [runs, setRuns] = useState<RunStatus[]>([]);
  const [phaseSummary, setPhaseSummary] = useState<PhaseSummary[]>([]);
  const [dailyReport, setDailyReport] = useState<DailyReport | null>(null);
  const [recentErrors, setRecentErrors] = useState<ErrorEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [schedulerStatus, setSchedulerStatus] = useState<SchedulerStatus | null>(null);

  useEffect(() => {
    void loadAll();
  }, []);

  async function loadAll() {
    setLoading(true);
    try {
      const [runsRes, errorsRes, dashboardRunsRes, schedRes] = await Promise.all([
        fetch(`${API_BASE}/api/monitor/runs?limit=20`).catch(() => null),
        fetch(`${API_BASE}/api/monitor/errors`).catch(() => null),
        fetch(`${API_BASE}/api/runs?limit=20`).catch(() => null),
        fetch(`${API_BASE}/api/scheduler/status`).catch(() => null),
      ]);
      if (runsRes?.ok) setRuns(await runsRes.json().catch(() => []));
      if (errorsRes?.ok) setRecentErrors(await errorsRes.json().catch(() => []));
      if (dashboardRunsRes?.ok) {
        const runsData = await dashboardRunsRes.json();
        if (runsData.length > 0 && !date) {
          setDate(runsData[0].trading_date);
        }
      }
      if (schedRes?.ok) setSchedulerStatus(await schedRes.json());
    } finally {
      setLoading(false);
    }
  }

  async function startScheduler() {
    await fetch(`${API_BASE}/api/scheduler/start`, { method: 'POST' });
    await loadAll();
  }

  async function stopScheduler() {
    await fetch(`${API_BASE}/api/scheduler/stop`, { method: 'POST' });
    await loadAll();
  }

  async function loadDailyReport(targetDate = date) {
    if (!targetDate) return;
    const response = await fetch(`${API_BASE}/api/monitor/daily-report?date=${targetDate}`);
    setDailyReport(await response.json());
  }

  async function triggerPhase(phase: string, targetDate = date) {
    if (!targetDate) return;
    await fetch(`${API_BASE}/api/runs/${phase}?date=${targetDate}`, { method: 'POST' });
    await loadAll();
  }

  const PHASES = ['sync_data', 'preopen_pick', 'simulate', 'deterministic_review', 'llm_review', 'evolve'];

  return (
    <div className="scheduler-panel">
      <header className="panel-header">
        <h2>调度监控</h2>
        <div className="actions">
          {schedulerStatus && (
            <div className="scheduler-status-badge">
              <span className={schedulerStatus.running ? 'ok' : 'error'}>
                {schedulerStatus.running ? '运行中' : '已停止'}
              </span>
              {schedulerStatus.running ? (
                <button onClick={stopScheduler} className="btn-stop"><Square size={14} /> 停止</button>
              ) : (
                <button onClick={startScheduler} className="btn-start"><Play size={14} /> 启动</button>
              )}
            </div>
          )}
          <input value={date} onChange={(e) => setDate(e.target.value)} placeholder="YYYY-MM-DD" />
          <button onClick={() => loadDailyReport(date)} disabled={!date || loading}>日报</button>
          <button onClick={loadAll}><RefreshCw size={16} /> 刷新</button>
        </div>
      </header>

      {schedulerStatus && schedulerStatus.jobs.length > 0 && (
        <section className="scheduler-jobs">
          <h3>定时任务</h3>
          <div className="job-list">
            {schedulerStatus.jobs.map((job) => (
              <div className="job-item" key={job.id}>
                <span className="job-id">{job.id}</span>
                <span className="job-next">
                  {job.next_run ? `下次运行: ${job.next_run}` : '未调度'}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="phase-grid">
        {PHASES.map((phase) => {
          const latest = runs.find((r) => r.phase === phase);
          return (
            <div className="phase-card" key={phase}>
              <div className="phase-header">
                <strong>{phase}</strong>
                {latest?.status === 'ok' && <CheckCircle size={16} className="ok" />}
                {latest?.status === 'error' && <AlertCircle size={16} className="error" />}
                {latest?.status === 'running' && <Clock size={16} className="running" />}
              </div>
              <small>
                {latest?.trading_date ?? '未运行'} · {latest?.status ?? '-'}
              </small>
              <div className="phase-actions">
                <button onClick={() => triggerPhase(phase)} disabled={!date || loading}>重跑</button>
              </div>
            </div>
          );
        })}
      </section>

      {dailyReport && (
        <section className="daily-report">
          <h3>{dailyReport.trading_date} 日报</h3>
          <div className="report-status">
            <span className={dailyReport.all_ok ? 'ok' : 'error'}>
              {dailyReport.all_ok ? '全部成功' : '有错误'}
            </span>
          </div>
          {dailyReport.phases_missing.length > 0 && (
            <div className="missing-phases">
              <strong>未执行:</strong> {dailyReport.phases_missing.join(', ')}
            </div>
          )}
          {dailyReport.errors.length > 0 && (
            <div className="errors">
              <strong>错误:</strong> {dailyReport.errors.join(' · ')}
            </div>
          )}
        </section>
      )}

      {recentErrors.length > 0 && (
        <section className="recent-errors">
          <h3>最近错误</h3>
          <div className="error-list">
            {recentErrors.map((entry, index) => (
              <div className="error-item" key={index}>
                <span className="error-phase">{entry.phase}</span>
                <span className="error-date">{entry.trading_date}</span>
                <span className="error-msg">{entry.error}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
