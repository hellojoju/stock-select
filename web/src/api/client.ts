import { useState, useCallback, useEffect } from 'react';

export const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:18425';

export interface ApiResult<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return '未知错误';
}

export async function request<T>(endpoint: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.error ?? `请求失败: ${response.status} ${response.statusText}`);
  }

  return response.json() as Promise<T>;
}

export function useApi<T>(fetcher: () => Promise<T>): ApiResult<T> & { reload: () => void } {
  const [result, setResult] = useState<ApiResult<T>>({ data: null, loading: true, error: null });

  const reload = useCallback(() => {
    setResult({ data: null, loading: true, error: null });
    fetcher()
      .then((data) => setResult({ data, loading: false, error: null }))
      .catch((err: unknown) => setResult({ data: null, loading: false, error: getErrorMessage(err) }));
  }, [fetcher]);

  useEffect(() => { reload(); }, [reload]);

  return { ...result, reload };
}

// === Dashboard ===

export interface DashboardPayload {
  picks: Array<Record<string, unknown>>;
  performance: Record<string, unknown>;
  runs: Array<Record<string, unknown>>;
  data_quality: Array<Record<string, unknown>>;
  evidence: Array<Record<string, unknown>>;
  candidate_scores: Array<Record<string, unknown>>;
  review_summary: Record<string, unknown>;
  date?: string;
  mode?: string;
  runtime_mode?: string;
  database_role?: string;
  is_demo_data?: boolean;
  market_environment?: string;
}

export async function fetchDashboard(date?: string): Promise<DashboardPayload> {
  const qs = date ? `?date=${date}` : '';
  return request(`/api/dashboard${qs}`);
}

// === Config ===

export interface ModelConfig {
  provider?: string | null;
  model: string;
  available_models: Array<{ key: string; model: string; label: string }>;
}

export async function fetchConfig(): Promise<ModelConfig> {
  return request('/api/config');
}

export async function updateModel(model: string): Promise<void> {
  await request('/api/config/model', {
    method: 'POST',
    body: JSON.stringify({ model }),
  });
}

// === Picks ===

export async function fetchPicks(params?: { date?: string; gene_id?: string; horizon?: string }) {
  const qs = params ? `?${new URLSearchParams(Object.entries(params).filter(([, v]) => v != null))}` : '';
  return request(`/api/picks${qs}`);
}

// === Genes ===

export async function fetchGenes() {
  return request('/api/genes');
}

export async function fetchGenePerformance(geneId: string) {
  return request(`/api/genes/${geneId}/performance`);
}

export interface EnvPerfItem {
  gene_id: string;
  market_environment: string;
  period_start: string;
  period_end: string;
  trade_count: number;
  win_rate: number;
  avg_return: number;
  max_drawdown: number;
  alpha: number;
}

export async function fetchEnvironmentPerformance(params?: { gene_id?: string; limit?: number }) {
  const entries = Object.entries(params ?? {}).filter(([, v]) => v != null).map(([k, v]) => [k, String(v!)]);
  const qs = entries.length ? `?${new URLSearchParams(entries)}` : '';
  return request<{ items: EnvPerfItem[] }>(`/api/genes/environment-performance${qs}`);
}

// === Evolution ===

export async function fetchEvolutionEvents(limit = 50) {
  return request(`/api/evolution/events?limit=${limit}`);
}

export async function fetchEvolutionComparison(params: { gene_id: string; start: string; end: string }) {
  const qs = new URLSearchParams(params).toString();
  return request(`/api/evolution/comparison?${qs}`);
}

export async function proposeEvolution(params: { start: string; end: string; gene_id?: string; dry_run?: boolean }) {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v != null).map(([k, v]) => [k, String(v)])
  );
  return request(`/api/evolution/propose?${qs}`, { method: 'POST' });
}

export async function rollbackEvolution(params: { child_gene_id?: string; event_id?: string; reason?: string }) {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v != null) as [string, string][]
  );
  return request(`/api/evolution/rollback?${qs}`, { method: 'POST' });
}

export async function promoteChallenger(params: { child_gene_id: string; reason?: string }) {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v != null) as [string, string][]
  );
  return request(`/api/evolution/promote?${qs}`, { method: 'POST' });
}

// === Optimization Signals ===

export async function fetchSignals(params?: { gene_id?: string; status?: string; limit?: number }) {
  const entries = Object.entries(params ?? {}).filter(([, v]) => v != null).map(([k, v]) => [k, String(v!)]);
  const qs = entries.length ? `?${new URLSearchParams(entries)}` : '';
  return request(`/api/optimization-signals${qs}`);
}

export async function acceptSignal(signalId: string): Promise<void> {
  await request(`/api/optimization-signals/${signalId}/accept`, { method: 'POST' });
}

export async function rejectSignal(signalId: string): Promise<void> {
  await request(`/api/optimization-signals/${signalId}/reject`, { method: 'POST' });
}

// === Reviews ===

export async function fetchReviews(params?: { date?: string }) {
  const qs = params?.date ? `?date=${params.date}` : '';
  return request(`/api/reviews${qs}`);
}

export async function fetchLlmReviews(date?: string) {
  const qs = date ? `?date=${date}` : '';
  return request(`/api/reviews/llm${qs}`);
}

export async function fetchAnalystReviews(date?: string) {
  const qs = date ? `?date=${date}` : '';
  return request(`/api/reviews/analysts${qs}`);
}

export async function fetchStockReview(code: string, date?: string, geneId?: string) {
  const params = new URLSearchParams();
  if (date) params.set('date', date);
  if (geneId) params.set('gene_id', geneId);
  const qs = params.toString();
  return request(`/api/reviews/stocks/${code}${qs ? `?${qs}` : ''}`);
}

export async function fetchStockReviewHistory(params: { stock_code: string; start: string; end: string; gene_id?: string }) {
  const { stock_code, ...rest } = params;
  const qs = new URLSearchParams(rest as Record<string, string>).toString();
  return request(`/api/reviews/stocks/${stock_code}/history?${qs}`);
}

export async function fetchHypotheticalReviewHistory(limit = 20) {
  return request(`/api/reviews/history/hypothetical?limit=${limit}`);
}

export async function fetchStrategyPicksHistory(date?: string, limit = 20) {
  const qs = new URLSearchParams(date ? { date, limit: String(limit) } : { limit: String(limit) }).toString();
  return request(`/api/reviews/history/strategy-picks?${qs}`);
}

export async function fetchReviewSteps(sessionId: string) {
  return request(`/api/reviews/steps/${sessionId}`);
}

export async function fetchPreopenStrategies(date?: string) {
  const qs = date ? `?date=${date}` : '';
  return request(`/api/reviews/preopen-strategies${qs}`);
}

export async function fetchPreopenStrategy(geneId: string, date?: string) {
  const qs = date ? `?date=${date}` : '';
  return request(`/api/reviews/preopen-strategies/${geneId}${qs}`);
}

export async function rerunStockReview(stockCode: string, date?: string, geneId?: string) {
  const params = new URLSearchParams();
  if (date) params.set('date', date);
  if (geneId) params.set('gene_id', geneId);
  return request(`/api/reviews/stocks/${stockCode}/rerun?${params}`, { method: 'POST' });
}

export async function rerunLlmReview(date?: string) {
  const qs = date ? `?date=${date}` : '';
  return request(`/api/reviews/llm/rerun?${qs}`, { method: 'POST' });
}

export async function rerunPreopenStrategy(geneId: string, date?: string) {
  const qs = date ? `?date=${date}` : '';
  return request(`/api/reviews/preopen-strategies/${geneId}/rerun?${qs}`, { method: 'POST' });
}

// === Blindspots ===

export async function fetchBlindspots(date?: string) {
  const qs = date ? `?date=${date}` : '';
  return request(`/api/blindspots${qs}`);
}

// === Data ===

export async function fetchDataStatus(date?: string) {
  const qs = date ? `?date=${date}` : '';
  return request(`/api/data/status${qs}`);
}

export async function fetchDataQuality(params?: { date?: string; status?: string; limit?: number }) {
  const entries = Object.entries(params ?? {}).filter(([, v]) => v != null).map(([k, v]) => [k, String(v!)]);
  const qs = entries.length ? `?${new URLSearchParams(entries)}` : '';
  return request(`/api/data/quality${qs}`);
}

// === Factors ===

export async function fetchFactorStatus(date?: string) {
  const qs = date ? `?date=${date}` : '';
  return request(`/api/factors/status${qs}`);
}

export async function fetchStockFactors(stockCode: string, date?: string) {
  const qs = date ? `?date=${date}` : '';
  return request(`/api/factors/stocks/${stockCode}${qs}`);
}

export async function fetchSectorFactors(date?: string) {
  const qs = date ? `?date=${date}` : '';
  return request(`/api/factors/sectors${qs}`);
}

// === Evidence ===

export async function fetchEvidenceStatus(date?: string) {
  const qs = date ? `?date=${date}` : '';
  return request(`/api/evidence/status${qs}`);
}

export async function fetchStockEvidence(stockCode: string, date?: string) {
  const qs = date ? `?date=${date}` : '';
  return request(`/api/evidence/stocks/${stockCode}${qs}`);
}

// === Candidates ===

export async function fetchCandidates(params?: { date?: string; gene_id?: string; limit?: number; offset?: number }) {
  const entries = Object.entries(params ?? {}).filter(([, v]) => v != null).map(([k, v]) => [k, String(v!)]);
  const qs = entries.length ? `?${new URLSearchParams(entries)}` : '';
  return request(`/api/candidates${qs}`);
}

export async function fetchCandidate(candidateId: string) {
  return request(`/api/candidates/${candidateId}`);
}

// === Stocks ===

export async function searchStocks(query: string, limit = 12) {
  return request(`/api/stocks/search?q=${encodeURIComponent(query)}&limit=${limit}`);
}

// === Memory ===

export async function searchMemory(query: string, limit = 20) {
  return request(`/api/memory/search?q=${encodeURIComponent(query)}&limit=${limit}`);
}

// === Graph ===

export async function fetchGraphQuery(params?: { node_type?: string; limit?: number }) {
  const entries = Object.entries(params ?? {}).filter(([, v]) => v != null).map(([k, v]) => [k, String(v!)]);
  const qs = entries.length ? `?${new URLSearchParams(entries)}` : '';
  return request(`/api/graph/query${qs}`);
}

// === Runs ===

export async function fetchRuns(date?: string) {
  const qs = date ? `?date=${date}` : '';
  return request(`/api/runs${qs}`);
}

export async function runPhase(phase: string, date?: string) {
  const qs = date ? `?date=${date}` : '';
  return request(`/api/runs/${phase}${qs}`, { method: 'POST' });
}

// === System Status ===

export async function fetchSystemStatus(date?: string) {
  const qs = date ? `?date=${date}` : '';
  return request(`/api/system/status${qs}`);
}

// === Monitor (FastAPI only) ===

export async function fetchMonitorHealth() {
  return request('/api/monitor/health');
}

export async function fetchMonitorRuns(params?: { status?: string; phase?: string; limit?: number }) {
  const entries = Object.entries(params ?? {}).filter(([, v]) => v != null).map(([k, v]) => [k, String(v!)]);
  const qs = entries.length ? `?${new URLSearchParams(entries)}` : '';
  return request(`/api/monitor/runs${qs}`);
}

export async function fetchMonitorDailyReport(date?: string) {
  const qs = date ? `?date=${date}` : '';
  return request(`/api/monitor/daily-report${qs}`);
}

export async function fetchMonitorErrors(limit = 20) {
  return request(`/api/monitor/errors?limit=${limit}`);
}

export async function fetchMonitorPhaseSummary(phase: string) {
  return request(`/api/monitor/phase-summary?phase=${phase}`);
}

export async function fetchMonitorMissingDates(days = 7) {
  return request(`/api/monitor/missing-dates?days=${days}`);
}

// === Planner ===

export interface PlannerPlan {
  plan_id: string;
  trading_date: string;
  focus_sectors: Array<Record<string, unknown>>;
  market_environment: Record<string, unknown> | null;
  high_impact_events: Array<Record<string, unknown>>;
  watch_risks: string[];
  llm_notes: string | null;
}

export interface PlannerVsPicks {
  trading_date: string;
  focus_industries: string[];
  picks: Array<{
    stock_code: string;
    strategy_gene_id: string;
    score: number;
    industry: string;
    eval_verdict: string | null;
    planner_aligned: number;
  }>;
  alignment_rate: number;
  aligned_count: number;
  total_picks: number;
}

export async function fetchPlannerPlan(date?: string): Promise<{ plan: PlannerPlan | null }> {
  const qs = date ? `?date=${date}` : '';
  return request(`/api/planner/plan${qs}`);
}

export async function fetchPlannerVsPicks(date?: string): Promise<PlannerVsPicks> {
  const qs = date ? `?date=${date}` : '';
  return request(`/api/planner/vs-picks${qs}`);
}

// === Challenger Performance ===

export interface ChallengerPerf {
  gene_id: string;
  name: string;
  status: string;
  trades: number;
  avg_return_pct: number;
  win_rate: number;
  max_drawdown: number;
  recent_picks: Array<Record<string, unknown>>;
}

export async function fetchChallengerPerformance(geneId?: string): Promise<{ challengers: ChallengerPerf[]; total: number }> {
  const qs = geneId ? `?gene_id=${geneId}` : '';
  return request(`/api/evolution/challenger-performance${qs}`);
}

// === Announcement Hunter ===

import type { AnnouncementAlert, MonitorRun, SectorHeatItem, LiveStats } from '../types';

export async function fetchAnnouncementAlerts(params?: {
  date?: string;
  status?: string;
  alert_type?: string;
  stock_code?: string;
  limit?: number;
}): Promise<AnnouncementAlert[]> {
  const entries = Object.entries(params ?? {}).filter(([, v]) => v != null).map(([k, v]) => [k, String(v!)]);
  const qs = entries.length ? `?${new URLSearchParams(entries)}` : '';
  return request(`/api/announcements/alerts${qs}`);
}

export async function fetchAnnouncementAlert(alertId: string): Promise<AnnouncementAlert | null> {
  return request(`/api/announcements/alerts/${alertId}`);
}

export async function acknowledgeAlert(alertId: string): Promise<void> {
  await request(`/api/announcements/alerts/${alertId}/acknowledge`, { method: 'POST' });
}

export async function dismissAlert(alertId: string): Promise<void> {
  await request(`/api/announcements/alerts/${alertId}/dismiss`, { method: 'POST' });
}

export async function fetchAnnouncementMonitorRuns(limit = 20): Promise<MonitorRun[]> {
  return request(`/api/announcements/monitor-runs?limit=${limit}`);
}

export async function fetchSectorHeat(date?: string): Promise<SectorHeatItem[]> {
  const qs = date ? `?date=${date}` : '';
  return request(`/api/announcements/sector-heat${qs}`);
}

export async function fetchLiveStats(date?: string): Promise<LiveStats> {
  const qs = date ? `?date=${date}` : '';
  return request(`/api/announcements/live-stats${qs}`);
}

export async function triggerAnnouncementScan(): Promise<{ success: boolean; alerts_found: number; error?: string }> {
  return request('/api/announcements/scan/trigger', { method: 'POST' });
}

export async function pauseAutoAnnouncementScan(): Promise<{ success: boolean; message: string }> {
  return request('/api/announcements/scan/pause', { method: 'POST' });
}

export async function resumeAutoAnnouncementScan(): Promise<{ success: boolean; message: string }> {
  return request('/api/announcements/scan/resume', { method: 'POST' });
}

export async function fetchScanStatus(): Promise<{ scheduler_running: boolean; auto_paused: boolean | null }> {
  return request('/api/announcements/scan/status');
}

export async function fetchScanEvents(limit = 50): Promise<Array<{
  timestamp: string;
  type: string;
  message: string;
  detail: string;
  level: string;
}>> {
  return request(`/api/announcements/events?limit=${limit}`);
}
