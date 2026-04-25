import { useEffect, useState } from 'react';
import { Clock, AlertCircle, CheckCircle, RefreshCw } from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:18425';

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

  useEffect(() => {
    void loadAll();
  }, []);

  async function loadAll() {
    setLoading(true);
    try {
      const [runsRes, errorsRes, dashboardRunsRes] = await Promise.all([
        fetch(`${API_BASE}/api/monitor/runs?limit=20`).catch(() => null),
        fetch(`${API_BASE}/api/monitor/errors`).catch(() => null),
        fetch(`${API_BASE}/api/runs?limit=20`).catch(() => null),
      ]);
      if (runsRes?.ok) setRuns(await runsRes.json().catch(() => []));
      if (errorsRes?.ok) setRecentErrors(await errorsRes.json().catch(() => []));
      if (dashboardRunsRes?.ok) {
        const runsData = await dashboardRunsRes.json();
        if (runsData.length > 0 && !date) {
          setDate(runsData[0].trading_date);
        }
      }
    } finally {
      setLoading(false);
    }
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
          <input value={date} onChange={(e) => setDate(e.target.value)} placeholder="YYYY-MM-DD" />
          <button onClick={() => loadDailyReport(date)} disabled={!date || loading}>日报</button>
          <button onClick={loadAll}><RefreshCw size={16} /> 刷新</button>
        </div>
      </header>

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
