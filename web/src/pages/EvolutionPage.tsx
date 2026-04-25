import { useEffect, useState } from 'react';
import { Activity, GitBranch, RotateCcw, Search, Trophy } from 'lucide-react';
import Panel from '../components/Panel';
import EvolutionPanel from '../sections/EvolutionPanel';
import CandidateScores from '../sections/CandidateScores';
import type { Comparison } from '../types';

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:18425';

export default function EvolutionPage() {
  const [date, setDate] = useState('');
  const [comparisons, setComparisons] = useState<Comparison[]>([]);
  const [candidateScores, setCandidateScores] = useState<Array<Record<string, string | number>>>([]);
  const [candidateSignals, setCandidateSignals] = useState<Array<Record<string, unknown>>>([]);
  const [loading, setLoading] = useState(false);

  async function loadAll(targetDate: string) {
    setLoading(true);
    await Promise.all([
      loadEvents(),
      loadCandidateScores(targetDate),
      loadCandidateSignals(),
    ]);
    setLoading(false);
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

  async function loadCandidateScores(targetDate: string) {
    try {
      const response = await fetch(`${API_BASE}/api/dashboard?date=${targetDate}`);
      const data = await response.json();
      setCandidateScores(data.candidate_scores ?? []);
    } catch {
      setCandidateScores([]);
    }
  }

  async function loadCandidateSignals() {
    try {
      const response = await fetch(`${API_BASE}/api/optimization-signals?status=candidate`);
      setCandidateSignals(await response.json());
    } catch {
      setCandidateSignals([]);
    }
  }

  async function handleDryRun() {
    setLoading(true);
    try {
      await fetch(`${API_BASE}/api/evolution/propose?start=${date}&end=${date}&dry_run=true`, { method: 'POST' });
      await loadEvents();
    } finally {
      setLoading(false);
    }
  }

  async function handlePropose() {
    setLoading(true);
    try {
      await fetch(`${API_BASE}/api/evolution/propose?start=${date}&end=${date}`, { method: 'POST' });
      await loadEvents();
    } finally {
      setLoading(false);
    }
  }

  async function handlePromote(childGeneId: string) {
    await fetch(`${API_BASE}/api/evolution/promote?child_gene_id=${childGeneId}`, { method: 'POST' });
    await loadEvents();
  }

  async function handleRollback(childGeneId: string) {
    await fetch(`${API_BASE}/api/evolution/rollback?gene_id=${childGeneId}`, { method: 'POST' });
    await loadEvents();
  }

  async function handleAcceptSignal(signalId: string) {
    await fetch(`${API_BASE}/api/optimization-signals/${signalId}/accept`, { method: 'POST' });
    await loadCandidateSignals();
  }

  async function handleRejectSignal(signalId: string) {
    await fetch(`${API_BASE}/api/optimization-signals/${signalId}/reject`, { method: 'POST' });
    await loadCandidateSignals();
  }

  useEffect(() => { void loadAll(''); }, []);

  return (
    <div className="page">
      <header className="topbar">
        <div>
          <p className="eyebrow">STRATEGY ITERATION</p>
          <h1>策略进化</h1>
        </div>
        <div className="actions">
          <input value={date} onChange={(e) => setDate(e.target.value)} placeholder="YYYY-MM-DD" />
          <button onClick={() => loadAll(date)} disabled={!date || loading}><Search size={16} /> 查询</button>
          <button onClick={handleDryRun} disabled={!date || loading}><GitBranch size={16} /> Dry-run</button>
          <button onClick={handlePropose} disabled={!date || loading}><Trophy size={16} /> Propose</button>
        </div>
      </header>

      <div className="dash-grid">
        <div className="dash-col dash-col-main">
          <Panel title="进化对比" icon={<GitBranch size={18} />}>
            <EvolutionPanel
              comparisons={comparisons}
              onDryRun={handleDryRun}
              onApply={handlePropose}
              onPromote={handlePromote}
              onRollback={handleRollback}
            />
          </Panel>

          {candidateScores.length > 0 && (
            <Panel title="候选评分" icon={<Activity size={18} />}>
              <CandidateScores candidate_scores={candidateScores} />
            </Panel>
          )}
        </div>

        <div className="dash-col dash-col-side">
          {candidateSignals.length > 0 && (
            <Panel title="候审信号" icon={<RotateCcw size={18} />}>
              <div className="stack compact">
                {candidateSignals.map((s, i) => (
                  <div className="review-card" key={i}>
                    <strong>{String(s.signal_type)} / {String(s.param_name)}</strong>
                    <span>→ {String(s.direction)} (强度: {String(s.strength)})</span>
                    <div className="signal-actions">
                      <button className="btn-accept" onClick={() => handleAcceptSignal(String(s.signal_id))}>接受</button>
                      <button className="btn-reject" onClick={() => handleRejectSignal(String(s.signal_id))}>拒绝</button>
                    </div>
                  </div>
                ))}
              </div>
            </Panel>
          )}
        </div>
      </div>
    </div>
  );
}
