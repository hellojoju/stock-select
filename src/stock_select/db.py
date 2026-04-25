from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_VERSION = 2


def connect(db_path: str | Path = "var/stock_select.db") -> sqlite3.Connection:
    """Open a SQLite connection with project defaults."""
    path = Path(db_path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
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
    _ensure_evidence_schema(conn)


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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_fts_fallback (
              rowid INTEGER PRIMARY KEY AUTOINCREMENT,
              content TEXT NOT NULL,
              trading_date TEXT,
              source_type TEXT,
              source_id TEXT
            )
            """
        )
