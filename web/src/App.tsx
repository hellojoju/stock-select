import { useEffect, useState } from 'react';
import { Activity, Bell, BrainCircuit, Database, LineChart, Search, Settings, ShieldCheck, Zap } from 'lucide-react';
import DashboardPage from './pages/DashboardPage';
import CandidateResearchPage from './pages/CandidateResearchPage';
import ReviewPage from './pages/ReviewPage';
import EvolutionPage from './pages/EvolutionPage';
import DataMemoryPage from './pages/DataMemoryPage';
import AdvancedPage from './pages/AdvancedPage';
import SettingsPage from './pages/SettingsPage';
import AnnouncementMonitorPage from './pages/AnnouncementMonitorPage';
import AlertPanel from './components/AlertPanel';
import { fetchConfig, fetchDashboard, updateModel, useApi } from './api/client';
import './styles.css';

type View = 'dashboard' | 'research' | 'review' | 'evolution' | 'data' | 'advanced' | 'settings' | 'monitor';

export default function App() {
  const [view, setView] = useState<View>('dashboard');
  const [reviewStockCode, setReviewStockCode] = useState('');

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<{ stockCode?: string }>).detail;
      if (!detail?.stockCode) return;
      setReviewStockCode(detail.stockCode);
      setView('review');
    };
    window.addEventListener('stock-select:navigate-stock-review', handler);
    return () => window.removeEventListener('stock-select:navigate-stock-review', handler);
  }, []);

  useEffect(() => {
    const handler = () => setView('evolution');
    window.addEventListener('stock-select:navigate-evolution', handler);
    return () => window.removeEventListener('stock-select:navigate-evolution', handler);
  }, []);

  const nav = [
    { key: 'dashboard' as View, icon: <Activity size={18} />, label: '今日工作台' },
    { key: 'research' as View, icon: <LineChart size={18} />, label: '选股研究' },
    { key: 'review' as View, icon: <Search size={18} />, label: '复盘中心' },
    { key: 'evolution' as View, icon: <BrainCircuit size={18} />, label: '策略进化' },
    { key: 'data' as View, icon: <Database size={18} />, label: '数据与运行' },
    { key: 'monitor' as View, icon: <Bell size={18} />, label: '公告猎手' },
  ];

  const bottomNav = [
    { key: 'advanced' as View, icon: <Zap size={18} />, label: '高级功能' },
    { key: 'settings' as View, icon: <Settings size={18} />, label: '系统设置' },
  ];

  return (
    <main className="shell">
      <aside className="rail">
        <div className="brand">
          <span className="brand-mark">SS</span>
          <div>
            <strong>Stock Select</strong>
            <small>自我进化选股系统</small>
          </div>
        </div>
        <nav>
          {nav.map((item) => (
            <a
              key={item.key}
              className={view === item.key ? 'active' : ''}
              onClick={() => setView(item.key)}
            >
              {item.icon} {item.label}
            </a>
          ))}
        </nav>
        <nav className="nav-bottom">
          {bottomNav.map((item) => (
            <a
              key={item.key}
              className={view === item.key ? 'active' : ''}
              onClick={() => setView(item.key)}
            >
              {item.icon} {item.label}
            </a>
          ))}
        </nav>
        <RailFooter />
      </aside>

      <section className="workspace" style={{ position: 'relative' }}>
        <div className="absolute top-3 right-3 z-40">
          <AlertPanel />
        </div>
        {view === 'dashboard' && <DashboardPage />}
        {view === 'research' && <CandidateResearchPage />}
        {view === 'review' && <ReviewPage initialStockCode={reviewStockCode} />}
        {view === 'evolution' && <EvolutionPage />}
        {view === 'data' && <DataMemoryPage />}
        {view === 'advanced' && <AdvancedPage />}
        {view === 'settings' && <SettingsPage />}
        {view === 'monitor' && <AnnouncementMonitorPage />}
      </section>
    </main>
  );
}

function RailFooter() {
  const { data: dashboard } = useApi(fetchDashboard);
  const { data: config } = useApi(fetchConfig);
  const mode = String(dashboard?.runtime_mode ?? dashboard?.mode ?? 'demo');
  const llmReady = Boolean(config?.provider && config?.model);
  return (
    <div className="rail-footer">
      <span className={`mode-badge ${mode === 'live' ? 'live' : 'demo'}`}>{mode.toUpperCase()}</span>
      <span className="rail-chip"><ShieldCheck size={13} /> 模拟盘</span>
      <span className={llmReady ? 'rail-chip' : 'rail-chip muted'}>{llmReady ? 'LLM Ready' : 'LLM Off'}</span>
      <ModelSwitcher />
      <small>v0.2 · Research Terminal</small>
    </div>
  );
}

/* === Model Switcher (sidebar) === */

function ModelSwitcher() {
  const { data: config, error, reload } = useApi(fetchConfig);
  const [switching, setSwitching] = useState<string | null>(null);
  const [switchError, setSwitchError] = useState<string | null>(null);

  if (error) return null;
  if (!config || config.available_models.length < 2) return null;

  return (
    <div className="model-switcher">
      {config.available_models.map((m) => (
        <button
          key={m.key}
          className={`model-btn ${config.model === m.model ? 'active' : ''}`}
          disabled={switching !== null}
          title={switchError && switching === m.model ? switchError : undefined}
          onClick={() => {
            setSwitching(m.model);
            setSwitchError(null);
            updateModel(m.model)
              .then(() => reload())
              .then(() => setSwitching(null))
              .catch((err: unknown) => {
                setSwitchError(err instanceof Error ? err.message : '切换失败');
                setSwitching(null);
              });
          }}
        >
          {switching === m.model ? '...' : m.label.replace('DeepSeek ', '')}
        </button>
      ))}
    </div>
  );
}
