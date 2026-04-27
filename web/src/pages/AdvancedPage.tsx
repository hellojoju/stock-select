import { useCallback, useEffect, useRef, useState } from 'react';
import { Save, Server, Zap } from 'lucide-react';
import Panel from '../components/Panel';
import { PageHeader } from '../components/PageHeader';
import { fetchConfig, updateModel, fetchRuns, runPhase, fetchSystemStatus } from '../api/client';
import type { ModelConfig } from '../api/client';

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:18425';

const PHASES = ['sync_data', 'preopen_pick', 'simulate', 'deterministic_review', 'llm_review', 'evolve'];
const PHASE_LABELS: Record<string, string> = {
  sync_data: '数据同步',
  preopen_pick: '盘前选股',
  simulate: '模拟交易',
  deterministic_review: '确定性复盘',
  llm_review: 'LLM 复盘',
  evolve: '策略进化',
};

export default function AdvancedPage() {
  const [config, setConfig] = useState<ModelConfig | null>(null);
  const [date, setDate] = useState('');
  const [loading, setLoading] = useState(false);
  const [phaseLoading, setPhaseLoading] = useState<string | null>(null);
  const [runs, setRuns] = useState<Array<Record<string, unknown>>>([]);
  const [systemInfo, setSystemInfo] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    fetchConfig().then(setConfig).catch(() => {});
    const d = new Date().toISOString().slice(0, 10);
    setDate(d);
    loadRuns(d);
    loadSystemInfo(d);
  }, []);

  async function loadRuns(targetDate: string) {
    try {
      const data = await fetchRuns(targetDate);
      setRuns(Array.isArray(data) ? data : []);
    } catch { setRuns([]); }
  }

  async function loadSystemInfo(targetDate: string) {
    try {
      const data = await fetchSystemStatus(targetDate);
      setSystemInfo(data);
    } catch { setSystemInfo(null); }
  }

  async function handleRerunLlm() {
    if (!date) return;
    setLoading(true);
    await fetch(`${API_BASE}/api/reviews/llm/rerun?date=${date}`, { method: 'POST' });
    setLoading(false);
  }

  async function handleRerunPhase(phase: string) {
    if (!date) return;
    setPhaseLoading(phase);
    await runPhase(phase, date);
    await loadRuns(date);
    setPhaseLoading(null);
  }

  return (
    <div className="page terminal-page">
      <PageHeader
        eyebrow="ADVANCED"
        title="高级功能"
        date={date}
        onDateChange={(d) => { setDate(d); loadRuns(d); loadSystemInfo(d); }}
      />

      <div className="advanced-grid">
        <Panel title="运行控制" icon={<Zap size={18} />}>
          <div className="advanced-section">
            <h4>全量重跑</h4>
            <button className="btn-primary" onClick={handleRerunLlm} disabled={!date || loading} title="对选定交易日重新执行 LLM 复盘全流程（含假设性分析与策略决策）">
              重跑 LLM 复盘
            </button>
          </div>
          <div className="advanced-section">
            <h4>阶段重跑</h4>
            <div className="phase-grid">
              {PHASES.map((phase) => (
                <button
                  key={phase}
                  className="btn-secondary phase-btn"
                  disabled={!date || phaseLoading !== null}
                  onClick={() => handleRerunPhase(phase)}
                >
                  {phaseLoading === phase ? '运行中...' : PHASE_LABELS[phase]}
                </button>
              ))}
            </div>
          </div>
        </Panel>

        <Panel title="运行状态" icon={<Server size={18} />}>
          {systemInfo ? (
            <div className="system-info">
              <div className="info-row">
                <span>数据库</span>
                <span className="info-value">{String(systemInfo.database_role ?? 'unknown')}</span>
              </div>
              <div className="info-row">
                <span>运行模式</span>
                <span className="info-value">{String(systemInfo.mode ?? 'demo')}</span>
              </div>
              <div className="info-row">
                <span>当前日期</span>
                <span className="info-value">{String(systemInfo.date ?? '')}</span>
              </div>
              {config && (
                <>
                  <div className="info-row">
                    <span>LLM 提供商</span>
                    <span className="info-value">{String(config.provider ?? '未配置')}</span>
                  </div>
                  <div className="info-row">
                    <span>当前模型</span>
                    <span className="info-value">{String(config.model ?? '-')}</span>
                  </div>
                </>
              )}
            </div>
          ) : (
            <p className="empty-state">暂无系统状态信息。</p>
          )}
        </Panel>

        <Panel title="今日运行记录" icon={<Save size={18} />}>
          {runs.length === 0 ? (
            <p className="empty-state">今日无运行记录。</p>
          ) : (
            <div className="terminal-table">
              <div className="terminal-thead">
                <span>阶段</span>
                <span>状态</span>
                <span>时间</span>
              </div>
              {runs.slice(0, 10).map((run, i) => (
                <div className="terminal-row" key={i}>
                  <span>{String(run.phase ?? '')}</span>
                  <span className={`status-tag ${run.status === 'completed' ? 'ok' : run.status === 'failed' ? 'danger' : 'warn'}`}>
                    {String(run.status ?? '')}
                  </span>
                  <span>{String(run.created_at ?? '').slice(0, 19)}</span>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
