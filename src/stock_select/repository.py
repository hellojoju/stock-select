from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from typing import Any


def dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def loads(value: str | None, default: object) -> object:
    if not value:
        return default
    return json.loads(value)


def upsert_stock(
    conn: sqlite3.Connection,
    stock_code: str,
    name: str,
    *,
    exchange: str | None = None,
    industry: str | None = None,
    market_cap_bucket: str | None = None,
    list_date: str | None = None,
    is_st: bool = False,
    listing_status: str = "active",
) -> None:
    conn.execute(
        """
        INSERT INTO stocks(
          stock_code, name, exchange, industry, market_cap_bucket,
          list_date, is_st, listing_status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(stock_code) DO UPDATE SET
          name = excluded.name,
          exchange = excluded.exchange,
          industry = excluded.industry,
          market_cap_bucket = excluded.market_cap_bucket,
          list_date = excluded.list_date,
          is_st = excluded.is_st,
          listing_status = excluded.listing_status
        """,
        (stock_code, name, exchange, industry, market_cap_bucket, list_date, int(is_st), listing_status),
    )


def upsert_daily_price(
    conn: sqlite3.Connection,
    *,
    stock_code: str,
    trading_date: str,
    open: float,
    high: float,
    low: float,
    close: float,
    volume: float = 0,
    amount: float = 0,
    is_suspended: bool = False,
    is_limit_up: bool = False,
    is_limit_down: bool = False,
    source: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO daily_prices(
          stock_code, trading_date, open, high, low, close, volume, amount,
          is_suspended, is_limit_up, is_limit_down, source
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(stock_code, trading_date) DO UPDATE SET
          open = excluded.open,
          high = excluded.high,
          low = excluded.low,
          close = excluded.close,
          volume = excluded.volume,
          amount = excluded.amount,
          is_suspended = excluded.is_suspended,
          is_limit_up = excluded.is_limit_up,
          is_limit_down = excluded.is_limit_down,
          source = excluded.source
        """,
        (
            stock_code,
            trading_date,
            open,
            high,
            low,
            close,
            volume,
            amount,
            int(is_suspended),
            int(is_limit_up),
            int(is_limit_down),
            source,
        ),
    )


def upsert_source_daily_price(
    conn: sqlite3.Connection,
    *,
    source: str,
    stock_code: str,
    trading_date: str,
    open: float,
    high: float,
    low: float,
    close: float,
    volume: float = 0,
    amount: float = 0,
    is_suspended: bool = False,
    is_limit_up: bool = False,
    is_limit_down: bool = False,
) -> None:
    conn.execute(
        """
        INSERT INTO source_daily_prices(
          source, stock_code, trading_date, open, high, low, close,
          volume, amount, is_suspended, is_limit_up, is_limit_down
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, stock_code, trading_date) DO UPDATE SET
          open = excluded.open,
          high = excluded.high,
          low = excluded.low,
          close = excluded.close,
          volume = excluded.volume,
          amount = excluded.amount,
          is_suspended = excluded.is_suspended,
          is_limit_up = excluded.is_limit_up,
          is_limit_down = excluded.is_limit_down
        """,
        (
            source,
            stock_code,
            trading_date,
            open,
            high,
            low,
            close,
            volume,
            amount,
            int(is_suspended),
            int(is_limit_up),
            int(is_limit_down),
        ),
    )


def upsert_source_index_price(
    conn: sqlite3.Connection,
    *,
    source: str,
    index_code: str,
    trading_date: str,
    open: float,
    high: float,
    low: float,
    close: float,
    volume: float = 0,
    amount: float = 0,
) -> None:
    conn.execute(
        """
        INSERT INTO source_index_prices(
          source, index_code, trading_date, open, high, low, close,
          volume, amount
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, index_code, trading_date) DO UPDATE SET
          open = excluded.open,
          high = excluded.high,
          low = excluded.low,
          close = excluded.close,
          volume = excluded.volume,
          amount = excluded.amount
        """,
        (source, index_code, trading_date, open, high, low, close, volume, amount),
    )


def upsert_index_price(
    conn: sqlite3.Connection,
    *,
    index_code: str,
    trading_date: str,
    open: float,
    high: float,
    low: float,
    close: float,
    volume: float = 0,
    amount: float = 0,
    source: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO index_prices(
          index_code, trading_date, open, high, low, close, volume, amount, source
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(index_code, trading_date) DO UPDATE SET
          open = excluded.open,
          high = excluded.high,
          low = excluded.low,
          close = excluded.close,
          volume = excluded.volume,
          amount = excluded.amount,
          source = excluded.source
        """,
        (index_code, trading_date, open, high, low, close, volume, amount, source),
    )


def record_data_source_status(
    conn: sqlite3.Connection,
    *,
    source: str,
    dataset: str,
    status: str,
    trading_date: str | None = None,
    rows_loaded: int = 0,
    warning_count: int = 0,
    error: str | None = None,
    source_reliability: str = "medium",
    finished: bool = True,
) -> None:
    db_trading_date = trading_date or "__global__"
    conn.execute(
        """
        INSERT INTO data_sources(
          source, dataset, trading_date, status, rows_loaded, warning_count, error,
          source_reliability, finished_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END)
        ON CONFLICT(source, dataset, trading_date) DO UPDATE SET
          status = excluded.status,
          rows_loaded = excluded.rows_loaded,
          warning_count = excluded.warning_count,
          error = excluded.error,
          source_reliability = excluded.source_reliability,
          finished_at = excluded.finished_at
        """,
        (
            source,
            dataset,
            db_trading_date,
            status,
            rows_loaded,
            warning_count,
            error,
            source_reliability,
            int(finished),
        ),
    )


def insert_price_source_check(
    conn: sqlite3.Connection,
    *,
    check_id: str,
    stock_code: str,
    trading_date: str,
    primary_source: str,
    secondary_source: str,
    primary_close: float | None,
    secondary_close: float | None,
    close_diff_pct: float | None,
    status: str,
    message: str,
) -> None:
    conn.execute(
        """
        INSERT INTO price_source_checks(
          check_id, stock_code, trading_date, primary_source, secondary_source,
          primary_close, secondary_close, close_diff_pct, status, message
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(stock_code, trading_date, primary_source, secondary_source)
        DO UPDATE SET
          primary_close = excluded.primary_close,
          secondary_close = excluded.secondary_close,
          close_diff_pct = excluded.close_diff_pct,
          status = excluded.status,
          message = excluded.message
        """,
        (
            check_id,
            stock_code,
            trading_date,
            primary_source,
            secondary_source,
            primary_close,
            secondary_close,
            close_diff_pct,
            status,
            message,
        ),
    )


def upsert_trading_day(
    conn: sqlite3.Connection,
    trading_date: str,
    is_open: bool = True,
    *,
    market_trend: str | None = None,
    trend_type: str | None = None,
    volatility_level: str | None = None,
    volume_level: str | None = None,
    turnover_level: str | None = None,
    market_environment: str | None = None,
    index_return_pct: float | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO trading_days(
          trading_date, is_open, market_trend, trend_type, volatility_level,
          volume_level, turnover_level, market_environment, index_return_pct
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(trading_date) DO UPDATE SET
          is_open = excluded.is_open,
          market_trend = COALESCE(excluded.market_trend, trading_days.market_trend),
          trend_type = COALESCE(excluded.trend_type, trading_days.trend_type),
          volatility_level = COALESCE(excluded.volatility_level, trading_days.volatility_level),
          volume_level = COALESCE(excluded.volume_level, trading_days.volume_level),
          turnover_level = COALESCE(excluded.turnover_level, trading_days.turnover_level),
          market_environment = COALESCE(excluded.market_environment, trading_days.market_environment),
          index_return_pct = COALESCE(excluded.index_return_pct, trading_days.index_return_pct)
        """,
        (
            trading_date,
            int(is_open),
            market_trend,
            trend_type,
            volatility_level,
            volume_level,
            turnover_level,
            market_environment,
            index_return_pct,
        ),
    )


def get_active_genes(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT * FROM strategy_genes
            WHERE status IN ('active', 'observing')
            ORDER BY status, gene_id
            """
        )
    )


def get_champion_genes(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM strategy_genes WHERE status = 'active' ORDER BY gene_id"
        )
    )


def get_gene(conn: sqlite3.Connection, gene_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM strategy_genes WHERE gene_id = ?",
        (gene_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"Unknown strategy gene: {gene_id}")
    return row


def price_history_before(
    conn: sqlite3.Connection,
    stock_code: str,
    trading_date: str,
    limit: int,
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT * FROM daily_prices
            WHERE stock_code = ?
              AND trading_date < ?
              AND is_suspended = 0
            ORDER BY trading_date DESC
            LIMIT ?
            """,
            (stock_code, trading_date, limit),
        )
    )[::-1]


def active_stock_codes(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT stock_code FROM stocks
        WHERE listing_status = 'active'
          AND COALESCE(is_st, 0) = 0
        ORDER BY stock_code
        """
    )
    return [row["stock_code"] for row in rows]


def existing_source_daily_price_codes(
    conn: sqlite3.Connection,
    *,
    source: str,
    trading_date: str,
    stock_codes: list[str],
) -> set[str]:
    if not stock_codes:
        return set()
    existing: set[str] = set()
    for chunk in chunks(stock_codes, 500):
        placeholders = ",".join("?" for _ in chunk)
        rows = conn.execute(
            f"""
            SELECT stock_code FROM source_daily_prices
            WHERE source = ?
              AND trading_date = ?
              AND stock_code IN ({placeholders})
            """,
            [source, trading_date, *chunk],
        )
        existing.update(row["stock_code"] for row in rows)
    return existing


def complete_source_daily_price_codes(
    conn: sqlite3.Connection,
    *,
    source: str,
    trading_dates: list[str],
    stock_codes: list[str],
) -> set[str]:
    if not trading_dates or not stock_codes:
        return set()
    complete: set[str] = set()
    date_placeholders = ",".join("?" for _ in trading_dates)
    for stock_chunk in chunks(stock_codes, 500):
        stock_placeholders = ",".join("?" for _ in stock_chunk)
        rows = conn.execute(
            f"""
            SELECT stock_code, COUNT(DISTINCT trading_date) AS day_count
            FROM source_daily_prices
            WHERE source = ?
              AND trading_date IN ({date_placeholders})
              AND stock_code IN ({stock_placeholders})
            GROUP BY stock_code
            HAVING day_count >= ?
            """,
            [source, *trading_dates, *stock_chunk, len(trading_dates)],
        )
        complete.update(row["stock_code"] for row in rows)
    return complete


def chunks(values: list[str], size: int) -> Iterable[list[str]]:
    if size <= 0:
        raise ValueError("chunk size must be positive")
    for index in range(0, len(values), size):
        yield values[index : index + size]


def insert_many_prices(conn: sqlite3.Connection, rows: Iterable[dict[str, object]]) -> None:
    for row in rows:
        upsert_daily_price(conn, **row)  # type: ignore[arg-type]


def upsert_fundamental_metrics(
    conn: sqlite3.Connection,
    *,
    stock_code: str,
    as_of_date: str,
    report_period: str,
    roe: float | None = None,
    revenue_growth: float | None = None,
    net_profit_growth: float | None = None,
    gross_margin: float | None = None,
    debt_to_assets: float | None = None,
    operating_cashflow_to_profit: float | None = None,
    pe_percentile: float | None = None,
    pb_percentile: float | None = None,
    dividend_yield: float | None = None,
    quality_note: str | None = None,
    source: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO fundamental_metrics(
          stock_code, as_of_date, report_period, roe, revenue_growth,
          net_profit_growth, gross_margin, debt_to_assets,
          operating_cashflow_to_profit, pe_percentile, pb_percentile,
          dividend_yield, quality_note, source
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(stock_code, as_of_date, report_period) DO UPDATE SET
          roe = excluded.roe,
          revenue_growth = excluded.revenue_growth,
          net_profit_growth = excluded.net_profit_growth,
          gross_margin = excluded.gross_margin,
          debt_to_assets = excluded.debt_to_assets,
          operating_cashflow_to_profit = excluded.operating_cashflow_to_profit,
          pe_percentile = excluded.pe_percentile,
          pb_percentile = excluded.pb_percentile,
          dividend_yield = excluded.dividend_yield,
          quality_note = excluded.quality_note,
          source = excluded.source
        """,
        (
            stock_code,
            as_of_date,
            report_period,
            roe,
            revenue_growth,
            net_profit_growth,
            gross_margin,
            debt_to_assets,
            operating_cashflow_to_profit,
            pe_percentile,
            pb_percentile,
            dividend_yield,
            quality_note,
            source,
        ),
    )


def latest_fundamentals_before(
    conn: sqlite3.Connection,
    stock_code: str,
    trading_date: str,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM fundamental_metrics
        WHERE stock_code = ? AND as_of_date < ?
        ORDER BY as_of_date DESC, report_period DESC
        LIMIT 1
        """,
        (stock_code, trading_date),
    ).fetchone()


def upsert_sector_theme_signal(
    conn: sqlite3.Connection,
    *,
    trading_date: str,
    industry: str,
    sector_return_pct: float,
    relative_strength_rank: int,
    volume_surge: float = 0,
    theme_strength: float = 0,
    catalyst_count: int = 0,
    summary: str = "",
    source: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO sector_theme_signals(
          trading_date, industry, sector_return_pct, relative_strength_rank,
          volume_surge, theme_strength, catalyst_count, summary, source
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(trading_date, industry) DO UPDATE SET
          sector_return_pct = excluded.sector_return_pct,
          relative_strength_rank = excluded.relative_strength_rank,
          volume_surge = excluded.volume_surge,
          theme_strength = excluded.theme_strength,
          catalyst_count = excluded.catalyst_count,
          summary = excluded.summary,
          source = excluded.source
        """,
        (
            trading_date,
            industry,
            sector_return_pct,
            relative_strength_rank,
            volume_surge,
            theme_strength,
            catalyst_count,
            summary,
            source,
        ),
    )


def latest_sector_signal_before(
    conn: sqlite3.Connection,
    industry: str | None,
    trading_date: str,
) -> sqlite3.Row | None:
    if not industry:
        return None
    return conn.execute(
        """
        SELECT * FROM sector_theme_signals
        WHERE industry = ? AND trading_date < ?
        ORDER BY trading_date DESC
        LIMIT 1
        """,
        (industry, trading_date),
    ).fetchone()


def upsert_event_signal(
    conn: sqlite3.Connection,
    *,
    event_id: str,
    trading_date: str,
    published_at: str,
    event_type: str,
    title: str,
    summary: str,
    stock_code: str | None = None,
    industry: str | None = None,
    impact_score: float = 0,
    sentiment: float = 0,
    source: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO event_signals(
          event_id, trading_date, published_at, stock_code, industry, event_type,
          title, summary, impact_score, sentiment, source
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(event_id) DO UPDATE SET
          trading_date = excluded.trading_date,
          published_at = excluded.published_at,
          stock_code = excluded.stock_code,
          industry = excluded.industry,
          event_type = excluded.event_type,
          title = excluded.title,
          summary = excluded.summary,
          impact_score = excluded.impact_score,
          sentiment = excluded.sentiment,
          source = excluded.source
        """,
        (
            event_id,
            trading_date,
            published_at,
            stock_code,
            industry,
            event_type,
            title,
            summary,
            impact_score,
            sentiment,
            source,
        ),
    )


def recent_events_before(
    conn: sqlite3.Connection,
    *,
    trading_date: str,
    stock_code: str,
    industry: str | None,
    limit: int = 5,
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT * FROM event_signals
            WHERE trading_date < ?
              AND (stock_code = ? OR (stock_code IS NULL AND industry = ?))
            ORDER BY trading_date DESC, impact_score DESC
            LIMIT ?
            """,
            (trading_date, stock_code, industry, limit),
        )
    )


def upsert_candidate_score(
    conn: sqlite3.Connection,
    *,
    candidate_id: str,
    trading_date: str,
    strategy_gene_id: str,
    stock_code: str,
    total_score: float,
    technical_score: float,
    fundamental_score: float,
    event_score: float,
    sector_score: float,
    risk_penalty: float,
    packet_json: str,
) -> None:
    conn.execute(
        """
        INSERT INTO candidate_scores(
          candidate_id, trading_date, strategy_gene_id, stock_code, total_score,
          technical_score, fundamental_score, event_score, sector_score,
          risk_penalty, packet_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(trading_date, strategy_gene_id, stock_code) DO UPDATE SET
          total_score = excluded.total_score,
          technical_score = excluded.technical_score,
          fundamental_score = excluded.fundamental_score,
          event_score = excluded.event_score,
          sector_score = excluded.sector_score,
          risk_penalty = excluded.risk_penalty,
          packet_json = excluded.packet_json
        """,
        (
            candidate_id,
            trading_date,
            strategy_gene_id,
            stock_code,
            total_score,
            technical_score,
            fundamental_score,
            event_score,
            sector_score,
            risk_penalty,
            packet_json,
        ),
    )


def latest_trading_date(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT MAX(trading_date) AS date FROM daily_prices").fetchone()
    return row["date"] if row and row["date"] else None


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def insert_memory(
    conn: sqlite3.Connection,
    *,
    content: str,
    trading_date: str | None,
    source_type: str,
    source_id: str,
) -> None:
    try:
        conn.execute(
            "DELETE FROM memory_fts WHERE source_type = ? AND source_id = ?",
            (source_type, source_id),
        )
        conn.execute(
            """
            INSERT INTO memory_fts(content, trading_date, source_type, source_id)
            VALUES (?, ?, ?, ?)
            """,
            (content, trading_date, source_type, source_id),
        )
    except sqlite3.OperationalError:
        conn.execute(
            "DELETE FROM memory_fts_fallback WHERE source_type = ? AND source_id = ?",
            (source_type, source_id),
        )
        conn.execute(
            """
            INSERT INTO memory_fts_fallback(content, trading_date, source_type, source_id)
            VALUES (?, ?, ?, ?)
            """,
            (content, trading_date, source_type, source_id),
        )
