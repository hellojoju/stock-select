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
  candidate_scores: Array<Record<string, string | number>>;
  review_summary?: Record<string, unknown>;
};
