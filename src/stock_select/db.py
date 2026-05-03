from __future__ import annotations

import sqlite3
from pathlib import Path


# 项目根目录（基于此文件所在包的上级目录）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 默认数据库绝对路径
_DEFAULT_DB = _PROJECT_ROOT / "var" / "stock_select.db"

SCHEMA_VERSION = 2


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with project defaults."""
    if db_path is None:
        path = _DEFAULT_DB
    else:
        path = Path(db_path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")  # 5s wait before SQLITE_BUSY
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create all MVP tables.

    The schema is intentionally broad enough for Phase 0/1 and future LLM
    scratchpad work, while the first implementation only writes a subset.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version INTEGER PRIMARY KEY,
          applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS trading_days (
          trading_date TEXT PRIMARY KEY,
          is_open INTEGER NOT NULL DEFAULT 1,
          market_trend TEXT,
          trend_type TEXT,
          volatility_level TEXT,
          volume_level TEXT,
          turnover_level TEXT,
          market_environment TEXT,
          index_return_pct REAL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS stocks (
          stock_code TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          exchange TEXT,
          industry TEXT,
          market_cap_bucket TEXT,
          list_date TEXT,
          is_st INTEGER NOT NULL DEFAULT 0,
          listing_status TEXT NOT NULL DEFAULT 'active',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS daily_prices (
          stock_code TEXT NOT NULL REFERENCES stocks(stock_code),
          trading_date TEXT NOT NULL,
          open REAL NOT NULL,
          high REAL NOT NULL,
          low REAL NOT NULL,
          close REAL NOT NULL,
          prev_close REAL,
          volume REAL NOT NULL DEFAULT 0,
          amount REAL NOT NULL DEFAULT 0,
          is_suspended INTEGER NOT NULL DEFAULT 0,
          is_limit_up INTEGER NOT NULL DEFAULT 0,
          is_limit_down INTEGER NOT NULL DEFAULT 0,
          source TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (stock_code, trading_date)
        );

        CREATE INDEX IF NOT EXISTS idx_daily_prices_date
          ON daily_prices(trading_date);

        CREATE TABLE IF NOT EXISTS source_daily_prices (
          source TEXT NOT NULL,
          stock_code TEXT NOT NULL REFERENCES stocks(stock_code),
          trading_date TEXT NOT NULL,
          open REAL NOT NULL,
          high REAL NOT NULL,
          low REAL NOT NULL,
          close REAL NOT NULL,
          volume REAL NOT NULL DEFAULT 0,
          amount REAL NOT NULL DEFAULT 0,
          is_suspended INTEGER NOT NULL DEFAULT 0,
          is_limit_up INTEGER NOT NULL DEFAULT 0,
          is_limit_down INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (source, stock_code, trading_date)
        );

        CREATE TABLE IF NOT EXISTS source_index_prices (
          source TEXT NOT NULL,
          index_code TEXT NOT NULL,
          trading_date TEXT NOT NULL,
          open REAL NOT NULL,
          high REAL NOT NULL,
          low REAL NOT NULL,
          close REAL NOT NULL,
          volume REAL NOT NULL DEFAULT 0,
          amount REAL NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (source, index_code, trading_date)
        );

        CREATE TABLE IF NOT EXISTS index_prices (
          index_code TEXT NOT NULL,
          trading_date TEXT NOT NULL,
          open REAL NOT NULL,
          high REAL NOT NULL,
          low REAL NOT NULL,
          close REAL NOT NULL,
          volume REAL NOT NULL DEFAULT 0,
          amount REAL NOT NULL DEFAULT 0,
          source TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (index_code, trading_date)
        );

        CREATE TABLE IF NOT EXISTS data_sources (
          source TEXT NOT NULL,
          dataset TEXT NOT NULL,
          trading_date TEXT,
          status TEXT NOT NULL,
          rows_loaded INTEGER NOT NULL DEFAULT 0,
          warning_count INTEGER NOT NULL DEFAULT 0,
          error TEXT,
          source_reliability TEXT NOT NULL DEFAULT 'medium',
          started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          finished_at TEXT,
          PRIMARY KEY (source, dataset, trading_date)
        );

        CREATE TABLE IF NOT EXISTS price_source_checks (
          check_id TEXT PRIMARY KEY,
          stock_code TEXT NOT NULL REFERENCES stocks(stock_code),
          trading_date TEXT NOT NULL,
          primary_source TEXT NOT NULL,
          secondary_source TEXT NOT NULL,
          primary_close REAL,
          secondary_close REAL,
          close_diff_pct REAL,
          status TEXT NOT NULL,
          message TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE (stock_code, trading_date, primary_source, secondary_source)
        );

        CREATE TABLE IF NOT EXISTS strategy_genes (
          gene_id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          version INTEGER NOT NULL DEFAULT 1,
          horizon TEXT NOT NULL CHECK (horizon IN ('short', 'long')),
          risk_profile TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'active',
          parent_gene_id TEXT REFERENCES strategy_genes(gene_id),
          params_json TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS strategy_evolution_events (
          event_id TEXT PRIMARY KEY,
          parent_gene_id TEXT NOT NULL REFERENCES strategy_genes(gene_id),
          child_gene_id TEXT REFERENCES strategy_genes(gene_id),
          event_type TEXT NOT NULL CHECK (event_type IN ('proposal', 'promotion', 'rollback')),
          period_start TEXT NOT NULL,
          period_end TEXT NOT NULL,
          market_environment TEXT NOT NULL DEFAULT 'all',
          status TEXT NOT NULL,
          rationale_json TEXT NOT NULL,
          before_params_json TEXT NOT NULL,
          after_params_json TEXT,
          review_signal_json TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          applied_at TEXT,
          rolled_back_at TEXT,
          UNIQUE (parent_gene_id, child_gene_id, event_type)
        );

        CREATE TABLE IF NOT EXISTS research_runs (
          run_id TEXT PRIMARY KEY,
          trading_date TEXT NOT NULL,
          phase TEXT NOT NULL,
          strategy_gene_id TEXT REFERENCES strategy_genes(gene_id),
          input_snapshot_hash TEXT,
          status TEXT NOT NULL DEFAULT 'running',
          summary TEXT,
          error TEXT,
          started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          finished_at TEXT
        );

        CREATE TABLE IF NOT EXISTS tool_events (
          event_id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id TEXT NOT NULL REFERENCES research_runs(run_id),
          event_type TEXT NOT NULL,
          tool_name TEXT,
          args_json TEXT,
          result_summary TEXT,
          raw_result_path TEXT,
          duration_ms INTEGER,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS scratchpad_events (
          event_id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id TEXT NOT NULL REFERENCES research_runs(run_id),
          scratchpad_path TEXT NOT NULL,
          event_type TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS pick_decisions (
          decision_id TEXT PRIMARY KEY,
          trading_date TEXT NOT NULL,
          horizon TEXT NOT NULL CHECK (horizon IN ('short', 'long')),
          strategy_gene_id TEXT NOT NULL REFERENCES strategy_genes(gene_id),
          stock_code TEXT NOT NULL REFERENCES stocks(stock_code),
          action TEXT NOT NULL CHECK (action IN ('BUY', 'WATCH', 'HOLD')),
          confidence REAL NOT NULL,
          position_pct REAL NOT NULL,
          score REAL NOT NULL,
          entry_plan_json TEXT NOT NULL,
          sell_rules_json TEXT NOT NULL,
          thesis_json TEXT NOT NULL,
          risks_json TEXT NOT NULL,
          invalid_if_json TEXT NOT NULL,
          input_snapshot_hash TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE (trading_date, strategy_gene_id, stock_code)
        );

        CREATE INDEX IF NOT EXISTS idx_pick_decisions_date
          ON pick_decisions(trading_date);

        CREATE INDEX IF NOT EXISTS idx_research_runs_date_phase
          ON research_runs(trading_date, phase);
        CREATE INDEX IF NOT EXISTS idx_research_runs_status
          ON research_runs(status);
        CREATE INDEX IF NOT EXISTS idx_strategy_genes_status
          ON strategy_genes(status);

        CREATE TABLE IF NOT EXISTS sim_orders (
          order_id TEXT PRIMARY KEY,
          decision_id TEXT NOT NULL REFERENCES pick_decisions(decision_id),
          trading_date TEXT NOT NULL,
          stock_code TEXT NOT NULL REFERENCES stocks(stock_code),
          side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
          price REAL NOT NULL,
          quantity REAL NOT NULL,
          position_pct REAL NOT NULL,
          fee REAL NOT NULL DEFAULT 0,
          slippage_pct REAL NOT NULL DEFAULT 0,
          status TEXT NOT NULL DEFAULT 'filled',
          reject_reason TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS outcomes (
          outcome_id TEXT PRIMARY KEY,
          decision_id TEXT NOT NULL REFERENCES pick_decisions(decision_id),
          entry_price REAL NOT NULL,
          exit_price REAL NOT NULL,
          close_price REAL NOT NULL,
          return_pct REAL NOT NULL,
          max_drawdown_intraday_pct REAL NOT NULL,
          hit_sell_rule TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS review_logs (
          review_id TEXT PRIMARY KEY,
          decision_id TEXT REFERENCES pick_decisions(decision_id),
          trading_date TEXT NOT NULL,
          strategy_gene_id TEXT REFERENCES strategy_genes(gene_id),
          fact_json TEXT NOT NULL,
          inference_json TEXT NOT NULL,
          ambiguity_json TEXT NOT NULL,
          summary TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS decision_reviews (
          review_id TEXT PRIMARY KEY,
          decision_id TEXT NOT NULL REFERENCES pick_decisions(decision_id),
          trading_date TEXT NOT NULL,
          strategy_gene_id TEXT NOT NULL REFERENCES strategy_genes(gene_id),
          stock_code TEXT NOT NULL REFERENCES stocks(stock_code),
          verdict TEXT NOT NULL,
          primary_driver TEXT NOT NULL,
          return_pct REAL NOT NULL,
          relative_return_pct REAL NOT NULL DEFAULT 0,
          max_drawdown_intraday_pct REAL NOT NULL,
          thesis_quality_score REAL NOT NULL DEFAULT 0,
          evidence_quality_score REAL NOT NULL DEFAULT 0,
          deterministic_json TEXT NOT NULL,
          llm_json TEXT,
          summary TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(decision_id)
        );

        CREATE INDEX IF NOT EXISTS idx_decision_reviews_date
          ON decision_reviews(trading_date);

        CREATE TABLE IF NOT EXISTS factor_review_items (
          item_id TEXT PRIMARY KEY,
          review_id TEXT NOT NULL REFERENCES decision_reviews(review_id),
          factor_type TEXT NOT NULL,
          expected_json TEXT NOT NULL,
          actual_json TEXT NOT NULL,
          verdict TEXT NOT NULL,
          contribution_score REAL NOT NULL DEFAULT 0,
          error_type TEXT,
          confidence TEXT NOT NULL,
          evidence_ids_json TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(review_id, factor_type)
        );

        CREATE TABLE IF NOT EXISTS blindspot_reviews (
          blindspot_review_id TEXT PRIMARY KEY,
          trading_date TEXT NOT NULL,
          stock_code TEXT NOT NULL REFERENCES stocks(stock_code),
          rank INTEGER NOT NULL,
          return_pct REAL NOT NULL,
          industry TEXT,
          was_candidate INTEGER NOT NULL,
          was_picked INTEGER NOT NULL,
          candidate_rank INTEGER,
          candidate_score REAL,
          missed_stage TEXT NOT NULL,
          primary_reason TEXT NOT NULL,
          affected_gene_ids_json TEXT NOT NULL,
          evidence_json TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(trading_date, stock_code)
        );

        CREATE TABLE IF NOT EXISTS gene_reviews (
          gene_review_id TEXT PRIMARY KEY,
          strategy_gene_id TEXT NOT NULL REFERENCES strategy_genes(gene_id),
          period_start TEXT NOT NULL,
          period_end TEXT NOT NULL,
          market_environment TEXT NOT NULL DEFAULT 'all',
          trades INTEGER NOT NULL,
          avg_return_pct REAL NOT NULL,
          win_rate REAL NOT NULL,
          worst_drawdown_pct REAL NOT NULL,
          profit_loss_ratio REAL NOT NULL,
          blindspot_count INTEGER NOT NULL,
          thesis_quality_avg REAL NOT NULL DEFAULT 0,
          factor_edges_json TEXT NOT NULL,
          top_errors_json TEXT NOT NULL,
          deterministic_json TEXT NOT NULL,
          llm_json TEXT,
          summary TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(strategy_gene_id, period_start, period_end, market_environment)
        );

        CREATE TABLE IF NOT EXISTS system_reviews (
          system_review_id TEXT PRIMARY KEY,
          trading_date TEXT NOT NULL,
          market_environment TEXT NOT NULL DEFAULT 'unknown',
          total_picks INTEGER NOT NULL,
          total_blindspots INTEGER NOT NULL,
          avg_return_pct REAL NOT NULL,
          top_system_errors_json TEXT NOT NULL,
          data_quality_json TEXT NOT NULL,
          observation_json TEXT NOT NULL,
          llm_json TEXT,
          summary TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(trading_date)
        );

        CREATE TABLE IF NOT EXISTS optimization_signals (
          signal_id TEXT PRIMARY KEY,
          source_type TEXT NOT NULL,
          source_id TEXT NOT NULL,
          target_gene_id TEXT REFERENCES strategy_genes(gene_id),
          scope TEXT NOT NULL,
          scope_key TEXT,
          signal_type TEXT NOT NULL,
          param_name TEXT,
          direction TEXT NOT NULL,
          strength REAL NOT NULL,
          confidence REAL NOT NULL,
          sample_size INTEGER NOT NULL DEFAULT 1,
          status TEXT NOT NULL DEFAULT 'open',
          reason TEXT NOT NULL,
          evidence_ids_json TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          consumed_at TEXT,
          UNIQUE(source_type, source_id, target_gene_id, signal_type, param_name, direction, scope, scope_key)
        );

        CREATE TABLE IF NOT EXISTS review_evidence (
          evidence_id TEXT PRIMARY KEY,
          review_id TEXT,
          source_type TEXT NOT NULL,
          source_id TEXT,
          trading_date TEXT NOT NULL,
          stock_code TEXT,
          visibility TEXT NOT NULL,
          confidence TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS review_errors (
          error_id TEXT PRIMARY KEY,
          review_scope TEXT NOT NULL,
          review_id TEXT NOT NULL,
          error_type TEXT NOT NULL,
          severity REAL NOT NULL,
          confidence REAL NOT NULL,
          evidence_ids_json TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(review_scope, review_id, error_type)
        );

        CREATE TABLE IF NOT EXISTS llm_reviews (
          llm_review_id TEXT PRIMARY KEY,
          decision_review_id TEXT NOT NULL REFERENCES decision_reviews(review_id),
          trading_date TEXT NOT NULL,
          strategy_gene_id TEXT NOT NULL,
          attribution_json TEXT NOT NULL,
          reason_check_json TEXT NOT NULL,
          suggested_errors_json TEXT NOT NULL,
          suggested_signals_json TEXT NOT NULL,
          summary TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'candidate',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(decision_review_id)
        );

        CREATE TABLE IF NOT EXISTS llm_scratchpad (
          scratchpad_id TEXT PRIMARY KEY,
          llm_review_id TEXT REFERENCES llm_reviews(llm_review_id),
          decision_review_id TEXT,
          packet_hash TEXT,
          model TEXT,
          provider TEXT,
          prompt_tokens INTEGER DEFAULT 0,
          completion_tokens INTEGER DEFAULT 0,
          estimated_cost REAL DEFAULT 0.0,
          latency_ms INTEGER DEFAULT 0,
          status TEXT NOT NULL DEFAULT 'ok',
          error_message TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_llm_scratchpad_review
          ON llm_scratchpad(llm_review_id);

        CREATE TABLE IF NOT EXISTS analyst_reviews (
          analyst_review_id TEXT PRIMARY KEY,
          decision_id TEXT NOT NULL,
          trading_date TEXT NOT NULL,
          stock_code TEXT NOT NULL,
          strategy_gene_id TEXT NOT NULL,
          analyst_key TEXT NOT NULL,
          verdict TEXT NOT NULL,
          confidence REAL NOT NULL,
          reasoning TEXT NOT NULL,
          suggested_errors TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(decision_id, analyst_key)
        );

        CREATE TABLE IF NOT EXISTS news_items (
          news_id TEXT PRIMARY KEY,
          source TEXT NOT NULL,
          published_at TEXT NOT NULL,
          title TEXT NOT NULL,
          summary TEXT NOT NULL,
          url TEXT,
          related_stock_code TEXT REFERENCES stocks(stock_code),
          related_industry TEXT,
          sentiment REAL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_news_published_at
          ON news_items(published_at DESC);
        CREATE INDEX IF NOT EXISTS idx_news_stock_code
          ON news_items(related_stock_code);

        CREATE TABLE IF NOT EXISTS fundamental_metrics (
          stock_code TEXT NOT NULL REFERENCES stocks(stock_code),
          as_of_date TEXT NOT NULL,
          report_period TEXT NOT NULL,
          roe REAL,
          revenue_growth REAL,
          net_profit_growth REAL,
          gross_margin REAL,
          debt_to_assets REAL,
          operating_cashflow_to_profit REAL,
          pe_percentile REAL,
          pb_percentile REAL,
          dividend_yield REAL,
          quality_note TEXT,
          source TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (stock_code, as_of_date, report_period)
        );

        CREATE TABLE IF NOT EXISTS sector_theme_signals (
          trading_date TEXT NOT NULL,
          industry TEXT NOT NULL,
          sector_return_pct REAL NOT NULL,
          relative_strength_rank INTEGER NOT NULL,
          volume_surge REAL NOT NULL DEFAULT 0,
          theme_strength REAL NOT NULL DEFAULT 0,
          catalyst_count INTEGER NOT NULL DEFAULT 0,
          summary TEXT NOT NULL DEFAULT '',
          source TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (trading_date, industry)
        );

        CREATE TABLE IF NOT EXISTS event_signals (
          event_id TEXT PRIMARY KEY,
          trading_date TEXT NOT NULL,
          published_at TEXT NOT NULL,
          stock_code TEXT REFERENCES stocks(stock_code),
          industry TEXT,
          event_type TEXT NOT NULL,
          title TEXT NOT NULL,
          summary TEXT NOT NULL,
          impact_score REAL NOT NULL DEFAULT 0,
          sentiment REAL NOT NULL DEFAULT 0,
          source TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS candidate_scores (
          candidate_id TEXT PRIMARY KEY,
          trading_date TEXT NOT NULL,
          strategy_gene_id TEXT NOT NULL REFERENCES strategy_genes(gene_id),
          stock_code TEXT NOT NULL REFERENCES stocks(stock_code),
          total_score REAL NOT NULL,
          technical_score REAL NOT NULL,
          fundamental_score REAL NOT NULL,
          event_score REAL NOT NULL,
          sector_score REAL NOT NULL,
          risk_penalty REAL NOT NULL,
          packet_json TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE (trading_date, strategy_gene_id, stock_code)
        );

        CREATE TABLE IF NOT EXISTS analyst_expectations (
          expectation_id TEXT PRIMARY KEY,
          stock_code TEXT NOT NULL REFERENCES stocks(stock_code),
          report_date TEXT NOT NULL,
          forecast_period TEXT NOT NULL,
          org_name TEXT,
          author_name TEXT,
          report_title TEXT,
          forecast_revenue REAL,
          forecast_net_profit REAL,
          forecast_eps REAL,
          forecast_pe REAL,
          rating TEXT,
          target_price_min REAL,
          target_price_max REAL,
          source TEXT NOT NULL,
          source_url TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(stock_code, report_date, forecast_period, org_name, author_name)
        );

        CREATE TABLE IF NOT EXISTS financial_actuals (
          stock_code TEXT NOT NULL REFERENCES stocks(stock_code),
          report_period TEXT NOT NULL,
          ann_date TEXT NOT NULL,
          revenue REAL,
          net_profit REAL,
          net_profit_deducted REAL,
          eps REAL,
          roe REAL,
          gross_margin REAL,
          operating_cashflow REAL,
          source TEXT NOT NULL,
          source_url TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(stock_code, report_period, source)
        );

        CREATE TABLE IF NOT EXISTS earnings_surprises (
          surprise_id TEXT PRIMARY KEY,
          stock_code TEXT NOT NULL REFERENCES stocks(stock_code),
          report_period TEXT NOT NULL,
          ann_date TEXT NOT NULL,
          expected_net_profit REAL,
          actual_net_profit REAL,
          net_profit_surprise_pct REAL,
          expected_revenue REAL,
          actual_revenue REAL,
          revenue_surprise_pct REAL,
          expectation_sample_size INTEGER NOT NULL,
          expectation_source TEXT NOT NULL,
          actual_source TEXT NOT NULL,
          evidence_json TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(stock_code, report_period)
        );

        CREATE TABLE IF NOT EXISTS order_contract_events (
          event_id TEXT PRIMARY KEY,
          stock_code TEXT NOT NULL REFERENCES stocks(stock_code),
          ann_date TEXT NOT NULL,
          event_type TEXT NOT NULL,
          customer_name TEXT,
          product_name TEXT,
          contract_amount REAL,
          currency TEXT DEFAULT 'CNY',
          contract_period_start TEXT,
          contract_period_end TEXT,
          is_framework_agreement INTEGER NOT NULL DEFAULT 0,
          related_revenue_last_year REAL,
          order_to_last_year_revenue_pct REAL,
          source TEXT NOT NULL,
          source_url TEXT,
          extraction_method TEXT NOT NULL,
          confidence REAL NOT NULL,
          raw_text_hash TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS business_kpi_actuals (
          kpi_id TEXT PRIMARY KEY,
          stock_code TEXT NOT NULL REFERENCES stocks(stock_code),
          period TEXT NOT NULL,
          kpi_name TEXT NOT NULL,
          kpi_value REAL NOT NULL,
          unit TEXT NOT NULL,
          yoy_pct REAL,
          qoq_pct REAL,
          source TEXT NOT NULL,
          source_url TEXT,
          extraction_method TEXT NOT NULL,
          confidence REAL NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(stock_code, period, kpi_name, source)
        );

        CREATE TABLE IF NOT EXISTS blindspot_reports (
          report_id TEXT PRIMARY KEY,
          trading_date TEXT NOT NULL,
          stock_code TEXT NOT NULL REFERENCES stocks(stock_code),
          rank INTEGER NOT NULL,
          return_pct REAL NOT NULL,
          was_picked INTEGER NOT NULL,
          missed_by_gene_ids_json TEXT NOT NULL,
          reason TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE (trading_date, stock_code)
        );

        CREATE TABLE IF NOT EXISTS gene_scores (
          score_id TEXT PRIMARY KEY,
          gene_id TEXT NOT NULL REFERENCES strategy_genes(gene_id),
          period_start TEXT NOT NULL,
          period_end TEXT NOT NULL,
          market_environment TEXT NOT NULL,
          trades INTEGER NOT NULL,
          avg_return_pct REAL NOT NULL,
          win_rate REAL NOT NULL,
          worst_drawdown_pct REAL NOT NULL,
          profit_loss_ratio REAL NOT NULL,
          blindspot_penalty REAL NOT NULL,
          score REAL NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE (gene_id, period_start, period_end, market_environment)
        );

        CREATE TABLE IF NOT EXISTS graph_nodes (
          node_id TEXT PRIMARY KEY,
          node_type TEXT NOT NULL,
          label TEXT NOT NULL,
          props_json TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS graph_edges (
          edge_id TEXT PRIMARY KEY,
          source_node_id TEXT NOT NULL REFERENCES graph_nodes(node_id),
          target_node_id TEXT NOT NULL REFERENCES graph_nodes(node_id),
          edge_type TEXT NOT NULL,
          confidence TEXT NOT NULL CHECK (confidence IN ('EXTRACTED', 'INFERRED', 'AMBIGUOUS')),
          props_json TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS planner_plans (
          plan_id TEXT PRIMARY KEY,
          trading_date TEXT NOT NULL,
          focus_sectors_json TEXT NOT NULL,
          market_environment_json TEXT,
          high_impact_events_json TEXT NOT NULL,
          watch_risks_json TEXT NOT NULL,
          llm_notes TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(trading_date)
        );

        CREATE TABLE IF NOT EXISTS pick_evaluations (
          evaluation_id TEXT PRIMARY KEY,
          decision_id TEXT NOT NULL REFERENCES pick_decisions(decision_id),
          trading_date TEXT NOT NULL,
          stock_code TEXT NOT NULL,
          strategy_gene_id TEXT NOT NULL,
          return_pct REAL NOT NULL,
          verdict TEXT NOT NULL,
          thesis_quality REAL NOT NULL DEFAULT 0,
          planner_aligned INTEGER NOT NULL DEFAULT 0,
          notes TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(decision_id)
        );

        CREATE TABLE IF NOT EXISTS pick_rerun_archives (
          archive_id TEXT PRIMARY KEY,
          trading_date TEXT NOT NULL,
          strategy_gene_id TEXT NOT NULL,
          decision_id TEXT,
          artifact_type TEXT NOT NULL,
          artifact_id TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          superseded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS market_overview_daily (
          trading_date TEXT PRIMARY KEY,
          sh_return REAL,
          sz_return REAL,
          cyb_return REAL,
          bse_return REAL,
          advance_count INTEGER DEFAULT 0,
          decline_count INTEGER DEFAULT 0,
          flat_count INTEGER DEFAULT 0,
          limit_up_count INTEGER DEFAULT 0,
          limit_down_count INTEGER DEFAULT 0,
          top_volume_stocks TEXT DEFAULT '[]',
          top_amount_stocks TEXT DEFAULT '[]',
          style_preference TEXT,
          main_sectors TEXT DEFAULT '[]',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS sentiment_cycle_daily (
          trading_date TEXT PRIMARY KEY,
          advance_count INTEGER DEFAULT 0,
          decline_count INTEGER DEFAULT 0,
          limit_up_count INTEGER DEFAULT 0,
          limit_down_count INTEGER DEFAULT 0,
          seal_rate REAL,
          promotion_rate REAL,
          financing_balance REAL,
          financing_change_pct REAL,
          short_selling_balance REAL,
          short_selling_change_pct REAL,
          news_heat REAL,
          llm_sentiment_score REAL,
          composite_sentiment REAL,
          cycle_phase TEXT,
          cycle_reason TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS sector_analysis_daily (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          trading_date TEXT NOT NULL,
          sector_name TEXT NOT NULL,
          sector_return_pct REAL DEFAULT 0,
          strength_1d REAL DEFAULT 0,
          strength_3d REAL DEFAULT 0,
          strength_10d REAL DEFAULT 0,
          stock_count INTEGER DEFAULT 0,
          advance_ratio REAL DEFAULT 0,
          leader_stock TEXT,
          leader_return_pct REAL DEFAULT 0,
          leader_limit_up_days INTEGER DEFAULT 0,
          mid_tier_stocks TEXT DEFAULT '[]',
          follower_stocks TEXT DEFAULT '[]',
          drive_logic TEXT,
          team_complete INTEGER DEFAULT 0,
          sustainability REAL DEFAULT 0,
          limit_up_3d_count INTEGER DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(trading_date, sector_name)
        );

        CREATE TABLE IF NOT EXISTS capital_flow_daily (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          trading_date TEXT NOT NULL,
          stock_code TEXT NOT NULL REFERENCES stocks(stock_code),
          main_net_inflow REAL DEFAULT 0,
          large_order_inflow REAL DEFAULT 0,
          super_large_inflow REAL DEFAULT 0,
          retail_outflow REAL DEFAULT 0,
          flow_trend TEXT,
          sector_flow_rank INTEGER,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(trading_date, stock_code)
        );

        CREATE TABLE IF NOT EXISTS stock_custom_sector (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          trading_date TEXT NOT NULL,
          stock_code TEXT NOT NULL REFERENCES stocks(stock_code),
          sector_key TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(trading_date, stock_code, sector_key)
        );

        CREATE INDEX IF NOT EXISTS idx_custom_sector_date
          ON stock_custom_sector(trading_date, sector_key);

        CREATE INDEX IF NOT EXISTS idx_capital_flow_date
          ON capital_flow_daily(trading_date, stock_code);

        CREATE INDEX IF NOT EXISTS idx_sector_date_name
          ON sector_analysis_daily(trading_date, sector_name);

        CREATE TABLE IF NOT EXISTS psychology_review (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          decision_review_id TEXT NOT NULL UNIQUE REFERENCES decision_reviews(review_id),
          success_reasons TEXT DEFAULT '[]',
          failure_reasons TEXT DEFAULT '[]',
          psychological_category TEXT,
          reproducible_patterns TEXT DEFAULT '[]',
          prevention_strategies TEXT DEFAULT '[]',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS next_day_plan (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          decision_review_id TEXT NOT NULL UNIQUE REFERENCES decision_reviews(review_id),
          scenarios TEXT DEFAULT '[]',
          key_levels TEXT DEFAULT '[]',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS hypothetical_review_log (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          stock_code TEXT NOT NULL,
          trading_date TEXT NOT NULL,
          reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(stock_code, trading_date)
        );

        -- Announcement hunter: alert records
        CREATE TABLE IF NOT EXISTS announcement_alerts (
          alert_id TEXT PRIMARY KEY,
          trading_date TEXT NOT NULL,
          discovered_at TEXT NOT NULL,
          stock_code TEXT NOT NULL,
          stock_name TEXT,
          industry TEXT,
          source TEXT NOT NULL,
          alert_type TEXT NOT NULL,
          title TEXT NOT NULL,
          summary TEXT,
          source_url TEXT,
          event_ids_json TEXT,
          sentiment_score REAL NOT NULL DEFAULT 0,
          capital_flow_score REAL,
          sector_heat_score REAL,
          chip_structure_score REAL,
          shareholder_trend_score REAL,
          confidence REAL NOT NULL DEFAULT 0.5,
          status TEXT NOT NULL DEFAULT 'new',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(stock_code, title, source)
        );

        -- Announcement hunter: polling run audit log
        CREATE TABLE IF NOT EXISTS monitor_runs (
          run_id TEXT PRIMARY KEY,
          started_at TEXT NOT NULL,
          finished_at TEXT,
          source TEXT,
          documents_fetched INTEGER NOT NULL DEFAULT 0,
          new_documents INTEGER NOT NULL DEFAULT 0,
          alerts_generated INTEGER NOT NULL DEFAULT 0,
          error TEXT,
          status TEXT NOT NULL DEFAULT 'running'
        );

        -- Announcement hunter: sector heat cache
        CREATE TABLE IF NOT EXISTS sector_heat_index (
          trading_date TEXT NOT NULL,
          industry TEXT NOT NULL,
          heat_score REAL NOT NULL,
          stock_count INTEGER NOT NULL,
          limit_up_count INTEGER NOT NULL DEFAULT 0,
          total_flow REAL,
          announcement_count INTEGER NOT NULL DEFAULT 0,
          composite_return_pct REAL,
          computed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (trading_date, industry)
        );

        -- Announcement hunter: scan event log (persistent, not in-memory)
        CREATE TABLE IF NOT EXISTS scan_events (
          event_id INTEGER PRIMARY KEY AUTOINCREMENT,
          occurred_at TEXT NOT NULL,
          event_type TEXT NOT NULL,
          message TEXT NOT NULL,
          detail TEXT NOT NULL DEFAULT '',
          level TEXT NOT NULL DEFAULT 'info'
        );

        -- Market environment daily log
        CREATE TABLE IF NOT EXISTS market_environment_logs (
          log_id TEXT PRIMARY KEY,
          trading_date TEXT NOT NULL UNIQUE,
          market_environment TEXT NOT NULL,
          trend_type TEXT,
          volatility_level TEXT,
          breadth_up_count INT,
          breadth_down_count INT,
          limit_up_count INT,
          limit_down_count INT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        -- Gene performance by environment
        CREATE TABLE IF NOT EXISTS gene_environment_performance (
          gene_id TEXT NOT NULL,
          market_environment TEXT NOT NULL,
          period_start TEXT NOT NULL,
          period_end TEXT NOT NULL,
          trade_count INT,
          win_rate REAL,
          avg_return REAL,
          max_drawdown REAL,
          alpha REAL,
          PRIMARY KEY (gene_id, market_environment, period_start)
        );

        -- Evolution proposals
        CREATE TABLE IF NOT EXISTS evolution_proposals (
          proposal_id TEXT PRIMARY KEY,
          parent_gene_id TEXT NOT NULL REFERENCES strategy_genes(gene_id),
          child_gene_id TEXT REFERENCES strategy_genes(gene_id),
          market_environment TEXT,
          alpha_change REAL,
          status TEXT NOT NULL DEFAULT 'pending',
          changes_json TEXT NOT NULL,
          expected_alpha_improvement REAL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          applied_at TEXT
        );
        """
    )

    _ensure_live_schema(conn)
    _create_fts(conn)
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
        (SCHEMA_VERSION,),
    )
    conn.commit()


def _ensure_live_schema(conn: sqlite3.Connection) -> None:
    ensure_column(conn, "trading_days", "trend_type", "TEXT")
    ensure_column(conn, "trading_days", "turnover_level", "TEXT")
    ensure_column(conn, "trading_days", "market_environment", "TEXT")
    ensure_column(conn, "stocks", "list_date", "TEXT")
    ensure_column(conn, "stocks", "is_st", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "source_daily_prices", "is_limit_up", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "source_daily_prices", "is_limit_down", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "data_sources", "source_reliability", "TEXT NOT NULL DEFAULT 'medium'")
    ensure_column(conn, "sim_orders", "status", "TEXT NOT NULL DEFAULT 'filled'")
    ensure_column(conn, "sim_orders", "reject_reason", "TEXT")
    ensure_column(conn, "strategy_genes", "strategy_type", "TEXT DEFAULT 'generic'")
    ensure_column(conn, "strategy_genes", "market_environments_json", "TEXT DEFAULT '[\"all\"]'")
    ensure_column(conn, "strategy_genes", "factor_config_json", "TEXT DEFAULT '{}'")
    ensure_column(conn, "strategy_genes", "beta", "REAL DEFAULT 1.0")
    ensure_column(conn, "outcomes", "benchmark_return", "REAL DEFAULT 0.0")
    ensure_column(conn, "outcomes", "sector_return", "REAL DEFAULT 0.0")
    ensure_column(conn, "outcomes", "alpha", "REAL")
    _ensure_knowledge_tables(conn)
    _ensure_evidence_schema(conn)


def _ensure_knowledge_tables(conn: sqlite3.Connection) -> None:
    """Create knowledge base tables that are only created in the FTS fallback path."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_documents (
          document_id TEXT PRIMARY KEY,
          source TEXT NOT NULL,
          source_type TEXT NOT NULL,
          source_url TEXT,
          title TEXT NOT NULL,
          summary TEXT,
          content_text TEXT,
          content_hash TEXT NOT NULL,
          published_at TEXT,
          captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          author TEXT,
          related_stock_codes_json TEXT NOT NULL DEFAULT '[]',
          related_industries_json TEXT NOT NULL DEFAULT '[]',
          language TEXT DEFAULT 'zh',
          license_status TEXT DEFAULT 'unknown',
          fetch_status TEXT DEFAULT 'ok',
          raw_path TEXT,
          event_category TEXT DEFAULT 'other'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS document_stock_links (
          document_id TEXT NOT NULL REFERENCES raw_documents(document_id),
          stock_code TEXT NOT NULL REFERENCES stocks(stock_code),
          relation_type TEXT NOT NULL DEFAULT 'mentioned',
          confidence REAL NOT NULL DEFAULT 0.5,
          evidence_text TEXT,
          PRIMARY KEY (document_id, stock_code, relation_type)
        )
        """
    )
    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
          title,
          summary,
          content_text,
          document_id UNINDEXED,
          tokenize='unicode61'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS document_fetch_logs (
          log_id TEXT PRIMARY KEY,
          source TEXT NOT NULL,
          fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          status TEXT NOT NULL,
          records_fetched INTEGER DEFAULT 0,
          records_stored INTEGER DEFAULT 0,
          error_message TEXT,
          raw_url TEXT
        )
        """
    )
    # S3.5: Ensure event_category column exists for existing databases
    ensure_column(conn, "raw_documents", "event_category", "TEXT DEFAULT 'other'")


def _ensure_evidence_schema(conn: sqlite3.Connection) -> None:
    ensure_column(conn, "analyst_expectations", "source_fetched_at", "TEXT")
    ensure_column(conn, "analyst_expectations", "confidence", "REAL NOT NULL DEFAULT 1.0")
    ensure_column(conn, "analyst_expectations", "raw_json", "TEXT NOT NULL DEFAULT '{}'")

    ensure_column(conn, "financial_actuals", "actual_id", "TEXT")
    ensure_column(conn, "financial_actuals", "publish_date", "TEXT")
    ensure_column(conn, "financial_actuals", "as_of_date", "TEXT")
    ensure_column(conn, "financial_actuals", "deducted_net_profit", "REAL")
    ensure_column(conn, "financial_actuals", "debt_to_assets", "REAL")
    ensure_column(conn, "financial_actuals", "source_fetched_at", "TEXT")
    ensure_column(conn, "financial_actuals", "confidence", "REAL NOT NULL DEFAULT 1.0")
    ensure_column(conn, "financial_actuals", "raw_json", "TEXT NOT NULL DEFAULT '{}'")

    ensure_column(conn, "earnings_surprises", "actual_id", "TEXT")
    ensure_column(conn, "earnings_surprises", "expectation_snapshot_id", "TEXT")
    ensure_column(conn, "earnings_surprises", "surprise_amount", "REAL")
    ensure_column(conn, "earnings_surprises", "surprise_pct", "REAL")
    ensure_column(conn, "earnings_surprises", "surprise_type", "TEXT")
    ensure_column(conn, "earnings_surprises", "as_of_date", "TEXT")
    ensure_column(conn, "earnings_surprises", "evidence_level", "TEXT NOT NULL DEFAULT 'INFERRED'")
    ensure_column(conn, "earnings_surprises", "confidence", "REAL NOT NULL DEFAULT 1.0")
    ensure_column(conn, "earnings_surprises", "raw_json", "TEXT NOT NULL DEFAULT '{}'")

    ensure_column(conn, "order_contract_events", "publish_date", "TEXT")
    ensure_column(conn, "order_contract_events", "as_of_date", "TEXT")
    ensure_column(conn, "order_contract_events", "title", "TEXT")
    ensure_column(conn, "order_contract_events", "summary", "TEXT")
    ensure_column(conn, "order_contract_events", "contract_amount_pct_revenue", "REAL")
    ensure_column(conn, "order_contract_events", "counterparty", "TEXT")
    ensure_column(conn, "order_contract_events", "duration", "TEXT")
    ensure_column(conn, "order_contract_events", "impact_score", "REAL NOT NULL DEFAULT 0")
    ensure_column(conn, "order_contract_events", "source_fetched_at", "TEXT")
    ensure_column(conn, "order_contract_events", "raw_json", "TEXT NOT NULL DEFAULT '{}'")

    ensure_column(conn, "business_kpi_actuals", "report_period", "TEXT")
    ensure_column(conn, "business_kpi_actuals", "publish_date", "TEXT")
    ensure_column(conn, "business_kpi_actuals", "as_of_date", "TEXT")
    ensure_column(conn, "business_kpi_actuals", "kpi_unit", "TEXT")
    ensure_column(conn, "business_kpi_actuals", "kpi_yoy", "REAL")
    ensure_column(conn, "business_kpi_actuals", "kpi_qoq", "REAL")
    ensure_column(conn, "business_kpi_actuals", "industry", "TEXT")
    ensure_column(conn, "business_kpi_actuals", "source_fetched_at", "TEXT")
    ensure_column(conn, "business_kpi_actuals", "raw_json", "TEXT NOT NULL DEFAULT '{}'")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS risk_events (
          risk_event_id TEXT PRIMARY KEY,
          stock_code TEXT NOT NULL REFERENCES stocks(stock_code),
          event_date TEXT NOT NULL,
          publish_date TEXT NOT NULL,
          as_of_date TEXT NOT NULL,
          risk_type TEXT NOT NULL,
          severity TEXT NOT NULL DEFAULT 'medium',
          title TEXT NOT NULL,
          summary TEXT,
          impact_score REAL NOT NULL DEFAULT 0,
          source TEXT NOT NULL,
          source_url TEXT,
          source_fetched_at TEXT,
          confidence REAL NOT NULL DEFAULT 1.0,
          raw_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_financial_actuals_asof ON financial_actuals(stock_code, as_of_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_analyst_expectations_date ON analyst_expectations(stock_code, report_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_earnings_surprises_asof ON earnings_surprises(stock_code, as_of_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_order_contract_asof ON order_contract_events(stock_code, as_of_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_business_kpi_asof ON business_kpi_actuals(stock_code, as_of_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_risk_events_asof ON risk_events(stock_code, as_of_date)")


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _create_fts(conn: sqlite3.Connection) -> None:
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
              content,
              trading_date UNINDEXED,
              source_type UNINDEXED,
              source_id UNINDEXED
            )
            """
        )
    except sqlite3.OperationalError:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS memory_fts_fallback (
              rowid INTEGER PRIMARY KEY AUTOINCREMENT,
              content TEXT NOT NULL,
              trading_date TEXT,
              source_type TEXT,
              source_id TEXT
            );

            CREATE TABLE IF NOT EXISTS raw_documents (
              document_id TEXT PRIMARY KEY,
              source TEXT NOT NULL,
              source_type TEXT NOT NULL,
              source_url TEXT,
              title TEXT NOT NULL,
              summary TEXT,
              content_text TEXT,
              content_hash TEXT NOT NULL,
              published_at TEXT,
              captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              author TEXT,
              related_stock_codes_json TEXT NOT NULL DEFAULT '[]',
              related_industries_json TEXT NOT NULL DEFAULT '[]',
              language TEXT DEFAULT 'zh',
              license_status TEXT DEFAULT 'unknown',
              fetch_status TEXT DEFAULT 'ok',
              raw_path TEXT,
              event_category TEXT DEFAULT 'other'
            );

            CREATE TABLE IF NOT EXISTS document_chunks (
              chunk_id TEXT PRIMARY KEY,
              document_id TEXT NOT NULL REFERENCES raw_documents(document_id),
              chunk_index INTEGER NOT NULL,
              chunk_text TEXT NOT NULL,
              token_count INTEGER,
              embedding_id TEXT,
              content_hash TEXT
            );

            CREATE TABLE IF NOT EXISTS document_stock_links (
              document_id TEXT NOT NULL REFERENCES raw_documents(document_id),
              stock_code TEXT NOT NULL REFERENCES stocks(stock_code),
              relation_type TEXT NOT NULL DEFAULT 'mentioned',
              confidence REAL NOT NULL DEFAULT 0.5,
              evidence_text TEXT,
              PRIMARY KEY (document_id, stock_code, relation_type)
            );

            CREATE TABLE IF NOT EXISTS document_fetch_logs (
              log_id TEXT PRIMARY KEY,
              source TEXT NOT NULL,
              fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              status TEXT NOT NULL,
              records_fetched INTEGER DEFAULT 0,
              records_stored INTEGER DEFAULT 0,
              error_message TEXT,
              raw_url TEXT
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
              title,
              summary,
              content_text,
              document_id UNINDEXED,
              tokenize='unicode61'
            );
            """
        )
