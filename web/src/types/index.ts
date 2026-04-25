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
  candidate_scores: Array<Record<string, string | number>>;
  review_summary?: Record<string, unknown>;
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
  promotion_eligible?: boolean;
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
};

/* === Stock Review Detail === */

export type FactorItem = {
  factor_type: string;
  verdict: string;
  contribution_score: number;
  error_type: string | null;
  confidence: string;
  evidence_ids: string[];
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
  decision_id: string;
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
