import { useEffect, useState } from 'react';
import { Activity, BrainCircuit, Database, GitBranch, Search } from 'lucide-react';
import DashboardPage from './pages/DashboardPage';
import ReviewPage from './pages/ReviewPage';
import EvolutionPage from './pages/EvolutionPage';
import DataMemoryPage from './pages/DataMemoryPage';
import type { Dashboard } from './types';
import './styles.css';

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:18425';

type View = 'dashboard' | 'review' | 'evolution' | 'data';

export default function App() {
  const [view, setView] = useState<View>('dashboard');

  const nav = [
    { key: 'dashboard' as View, icon: <Activity size={18} />, label: '今日工作台' },
    { key: 'review' as View, icon: <Search size={18} />, label: '复盘分析' },
    { key: 'evolution' as View, icon: <BrainCircuit size={18} />, label: '策略进化' },
    { key: 'data' as View, icon: <Database size={18} />, label: '数据与记忆' },
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
        <div className="rail-footer">
          <span className="mode-badge live">LIVE</span>
          <ModelSwitcher />
          <small>v0.1 · 模拟盘</small>
        </div>
      </aside>

      <section className="workspace">
        {view === 'dashboard' && <DashboardPage />}
        {view === 'review' && <ReviewPage />}
        {view === 'evolution' && <EvolutionPage />}
        {view === 'data' && <DataMemoryPage />}
      </section>
    </main>
  );
}

/* === Model Switcher (sidebar) === */

function ModelSwitcher() {
  const [config, setConfig] = useState<{ model: string; available: Array<{ key: string; model: string; label: string }> } | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/config`).then(r => r.json()).then((d) => {
      setConfig({ model: d.model, available: d.available_models ?? [] });
    }).catch(() => {});
  }, []);

  if (!config || config.available.length < 2) return null;

  return (
    <div className="model-switcher">
      {config.available.map((m) => (
        <button
          key={m.key}
          className={`model-btn ${config.model === m.model ? 'active' : ''}`}
          onClick={() => {
            fetch(`${API_BASE}/api/config/model`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ model: m.model }),
            }).then(r => r.json()).then(() => {
              setConfig((prev) => prev ? { ...prev, model: m.model } : prev);
            }).catch(() => {});
          }}
        >
          {m.label.replace('DeepSeek ', '')}
        </button>
      ))}
    </div>
  );
}
