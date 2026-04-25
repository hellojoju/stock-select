import { useEffect, useState } from 'react';
import { Database, Search } from 'lucide-react';
import Panel from '../components/Panel';
import DataQuality from '../sections/DataQuality';
import EvidenceCoverage from '../sections/EvidenceCoverage';
import MemorySearch from '../sections/MemorySearch';
import SchedulerPanel from '../components/SchedulerPanel';
import type { Dashboard } from '../types';

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:18425';

export default function DataMemoryPage() {
  const [date, setDate] = useState('');
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(false);

  const [memoryQuery, setMemoryQuery] = useState('');
  const [memoryResults, setMemoryResults] = useState<Array<Record<string, unknown>>>([]);

  async function loadDashboard(targetDate: string) {
    if (!targetDate) {
      const response = await fetch(`${API_BASE}/api/dashboard`);
      const data = await response.json();
      setDashboard(data);
      if (data.date) setDate(data.date);
      return;
    }
    setLoading(true);
    const response = await fetch(`${API_BASE}/api/dashboard?date=${targetDate}`);
    const data = await response.json();
    setDashboard(data);
    setLoading(false);
  }

  async function searchMemory() {
    if (!memoryQuery.trim()) return;
    try {
      const response = await fetch(`${API_BASE}/api/memory/search?q=${encodeURIComponent(memoryQuery)}&limit=20`);
      setMemoryResults(await response.json());
    } catch {
      setMemoryResults([]);
    }
  }

  useEffect(() => { void loadDashboard(''); }, []);

  return (
    <div className="page">
      <header className="topbar">
        <div>
          <p className="eyebrow">DATA & INFRASTRUCTURE</p>
          <h1>数据与记忆</h1>
        </div>
        <div className="actions">
          <input value={date} onChange={(e) => setDate(e.target.value)} placeholder="YYYY-MM-DD" />
          <button onClick={() => loadDashboard(date)} disabled={!date || loading}><Search size={16} /> 查询</button>
        </div>
      </header>

      <div className="dash-grid">
        <div className="dash-col dash-col-main">
          {dashboard && (
            <Panel title="数据质量" icon={<Database size={18} />}>
              <DataQuality dashboard={dashboard} />
            </Panel>
          )}

          {dashboard?.evidence_status && (
            <Panel title="证据覆盖率" icon={<Database size={18} />}>
              <EvidenceCoverage status={dashboard.evidence_status} />
            </Panel>
          )}
        </div>

        <div className="dash-col dash-col-side">
          <Panel title="记忆检索" icon={<Search size={18} />}>
            <MemorySearch
              query={memoryQuery}
              onChange={setMemoryQuery}
              onSearch={searchMemory}
              results={memoryResults}
            />
          </Panel>

          <Panel title="调度监控" icon={<Database size={18} />}>
            <SchedulerPanel />
          </Panel>
        </div>
      </div>
    </div>
  );
}
