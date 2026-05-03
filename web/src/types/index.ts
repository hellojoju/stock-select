export type Pick = {
  decision_id: string;
  stock_code: string;
  stock_name?: string;
  strategy_gene_id: string;
  horizon: string;
  confidence: number;
  position_pct: number;
  score: number;
  return_pct?: number | null;
  hit_sell_rule?: string | null;
};

export type Dashboard = {
  date: string | null;
  runtime_mode?: string;
  database_role?: string;
  is_demo_data?: boolean;
  market_environment?: string | null;
  picks: Pick[];
  performance: Array<Record<string, number | string>>;
  runs: Array<Record<string, string>>;
  data_quality: Array<Record<string, string | number | null>>;
  data_status?: Array<Record<string, string | number | null>>;
  data_quality_summary?: Record<string, unknown>;
  evidence_status?: EvidenceStatus;
  llm_status?: LLMStatus;
  candidate_scores: Array<Record<string, string | number>>;
  review_summary?: Record<string, unknown>;
};

export type LLMStatus = {
  state: 'Ready' | 'Off' | 'Error' | string;
  configured: boolean;
  ready: boolean;
  provider?: string | null;
  model?: string | null;
  last_status?: string | null;
  last_error?: string | null;
  last_run_at?: string | null;
};

export type Availability = {
  date: string;
  status: 'ok' | 'degraded' | 'failed';
  price_coverage_pct: number;
  pick_count: number;
  event_source_count: number;
  review_evidence_count: number;
  reasons: string[];
};

export type Comparison = {
  event_id: string;
  parent_gene_id: string;
  child_gene_id?: string | null;
  status: string;
  parent_performance?: Record<string, unknown>;
  child_performance?: Record<string, unknown> | null;
  parameter_diff?: Array<Record<string, unknown>>;
  aggregated_signals?: Array<Record<string, unknown>>;
  evidence_ids?: string[];
  promotion_eligible?: boolean | Record<string, unknown>;
};

export type PromotionCriteria = {
  name: string;
  label: string;
  pass: boolean;
  value: number | string;
  threshold?: number;
};

export type PromotionEligibility = {
  eligible: boolean;
  criteria: PromotionCriteria[];
  performance: Record<string, unknown>;
};

export type SignalDetail = {
  signal_id: string;
  source_type: string;
  source_id: string;
  target_gene_id: string | null;
  scope: string;
  scope_key: string | null;
  signal_type: string;
  param_name: string;
  direction: string;
  strength: number;
  confidence: number;
  sample_size: number;
  status: string;
  reason: string;
  evidence_ids: string[];
  source_detail?: Record<string, unknown> | null;
  evidence_details?: Array<Record<string, unknown>>;
  created_at?: string;
};

export type RollbackEvent = {
  event_id: string;
  parent_gene_id: string;
  child_gene_id: string | null;
  period_start: string;
  period_end: string;
  rolled_back_at: string | null;
  created_at: string;
  reason: string;
  parent_performance: Record<string, unknown>;
  child_performance: Record<string, unknown> | null;
  parameter_diff: Array<Record<string, unknown>>;
};

export type EvidenceStatus = {
  trading_date: string;
  active_stock_count: number;
  counts: Record<string, number>;
  coverage: Record<string, number>;
  source_status: Array<Record<string, string | number | null>>;
  skipped_sources: Array<Record<string, string | number | null>>;
  error_sources: Array<Record<string, string | number | null>>;
  message: string;
};

export type LLMAttribution = {
  claim: string;
  confidence: 'EXTRACTED' | 'INFERRED' | 'AMBIGUOUS';
  evidence_ids: string[];
};

export type LLMReview = {
  llm_review_id: string;
  decision_review_id: string;
  trading_date: string;
  strategy_gene_id: string;
  attribution: LLMAttribution[];
  reason_check: {
    what_was_right: string[];
    what_was_wrong: string[];
    missing_signals: string[];
  };
  suggested_errors: Array<{
    error_type: string;
    severity: number;
    evidence_ids: string[];
  }>;
  suggested_signals: Array<{
    signal_id: string;
    signal_type: string;
    param_name: string;
    direction: string;
    strength: number;
    status: string;
  }>;
  summary: string;
  status: string;
  token_usage?: {
    prompt_tokens: number;
    completion_tokens: number;
    estimated_cost: number;
  };
  evidence_references?: Array<Record<string, unknown>>;
};

/* === Stock Review Detail === */

export type FactorItem = {
  factor_type: string;
  verdict: string;
  contribution_score: number;
  error_type: string | null;
  confidence: string;
  evidence_ids: string[];
  actual?: Record<string, unknown>;
  reason?: string;
  expected?: Record<string, unknown>;
};

export type ReviewError = {
  error_type: string;
  severity: number;
  confidence: number;
  evidence_ids: string[];
};

export type ReviewEvidence = {
  evidence_id: string;
  source_type: string;
  visibility: string;
  confidence: string;
  payload_json: string;
};

export type ReviewSignal = {
  signal_id: string;
  signal_type: string;
  param_name: string;
  direction: string;
  strength: number;
  status: string;
  reason: string;
};

export type AnalystReview = {
  analyst_review_id: string;
  decision_id: string;
  trading_date: string;
  stock_code: string;
  stock_name?: string;
  strategy_gene_id: string;
  analyst_key: string;
  display_name?: string;
  verdict: string;
  confidence: number;
  reasoning: string[];
  suggested_errors: string[];
};

export type ReviewDecision = {
  review_id: string;
  decision_id: string | null;
  strategy_gene_id: string;
  stock_code: string;
  verdict: string;
  primary_driver: string;
  return_pct: number;
  relative_return_pct: number;
  summary: string;
  factor_items: FactorItem[];
  errors: ReviewError[];
  evidence: ReviewEvidence[];
  optimization_signals: ReviewSignal[];
  llm_json?: string;
};

export type StockReviewResponse = {
  stock: Record<string, unknown>;
  trading_date: string;
  decisions: ReviewDecision[];
  blindspot: Record<string, unknown> | null;
  domain_facts: Record<string, Array<Record<string, unknown>>>;
  graph_context?: Record<string, unknown>;
  evidence_timeline?: Record<string, unknown>;
  hypothetical?: boolean;
};

/* === Announcement Hunter === */

export type AlertType = 'earnings_beat' | 'large_order' | 'tech_breakthrough' | 'asset_injection' | 'm_and_a';
export type AlertStatus = 'new' | 'acknowledged' | 'dismissed';
export type OpportunityType = 'sector_leader' | 'breakout' | 'event_driven';

export type AnnouncementAlert = {
  alert_id: string;
  trading_date: string;
  discovered_at: string;
  stock_code: string;
  stock_name?: string | null;
  industry?: string | null;
  source: string;
  alert_type: AlertType;
  title: string;
  summary?: string | null;
  source_url?: string | null;
  event_ids_json?: string | null;
  sentiment_score: number;
  capital_flow_score?: number | null;
  sector_heat_score?: number | null;
  chip_structure_score?: number | null;
  shareholder_trend_score?: number | null;
  capital_flow_evidence?: string | null;
  sector_heat_evidence?: string | null;
  chip_structure_evidence?: string | null;
  shareholder_trend_evidence?: string | null;
  confidence: number;
  status: AlertStatus;
  created_at: string;
};

export type MonitorRun = {
  run_id: string;
  started_at: string;
  finished_at?: string | null;
  source: string;
  documents_fetched: number;
  new_documents: number;
  alerts_generated: number;
  error?: string | null;
  status: string;
};

export type SectorHeatItem = {
  trading_date: string;
  industry: string;
  heat_score: number;
  stock_count: number;
  limit_up_count: number;
  total_flow?: number | null;
  announcement_count: number;
  composite_return_pct?: number | null;
  computed_at: string;
};

export type LiveStats = {
  date: string | null;
  total: number;
  by_type: Record<string, number>;
  max_score: number;
  new_count: number;
};

export type AnnouncementEvent = {
  type: 'new_alert';
  alert: {
    alert_id: string;
    stock_code: string;
    stock_name?: string;
    alert_type: AlertType;
    title: string;
    sentiment_score: number;
    discovered_at: string;
  };
};
