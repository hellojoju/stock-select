"""Synchronize review evidence: financial actuals, earnings surprises."""
from __future__ import annotations

import hashlib
import sqlite3
from typing import Any

from .data_ingestion import MarketDataProvider


def sync_financial_actuals(
    conn: sqlite3.Connection,
    trading_date: str,
    provider: MarketDataProvider,
) -> dict[str, Any]:
    """Fetch latest financial actuals from provider and upsert."""
    fetch = getattr(provider, "fetch_financial_actuals", None)
    if fetch is None:
        return {"dataset": "financial_actuals", "rows_loaded": 0, "note": f"{provider.source} does not support financial_actuals"}

    actuals = fetch(trading_date)
    rows_loaded = 0
    for item in actuals:
        conn.execute(
            """
            INSERT INTO financial_actuals(
              stock_code, report_period, ann_date, revenue, net_profit,
              net_profit_deducted, eps, roe, gross_margin, operating_cashflow,
              source, source_url
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(stock_code, report_period, source) DO UPDATE SET
              revenue = excluded.revenue, net_profit = excluded.net_profit,
              eps = excluded.eps, roe = excluded.roe
            """,
            (
                item.stock_code, item.report_period, item.ann_date,
                getattr(item, "revenue", None), getattr(item, "net_profit", None),
                getattr(item, "net_profit_deducted", None), getattr(item, "eps", None),
                getattr(item, "roe", None), getattr(item, "gross_margin", None),
                getattr(item, "operating_cashflow", None), provider.source,
                getattr(item, "source_url", None),
            ),
        )
        rows_loaded += 1
    conn.commit()
    return {"dataset": "financial_actuals", "rows_loaded": rows_loaded}


def sync_earnings_surprises(conn: sqlite3.Connection, trading_date: str) -> dict[str, Any]:
    """Compute earnings surprises from actuals vs aggregated expectations."""
    rows = conn.execute(
        """
        SELECT f.stock_code, f.report_period, f.ann_date,
               f.revenue AS actual_revenue, f.net_profit AS actual_net_profit,
               f.eps AS actual_eps,
               AVG(e.forecast_revenue) AS expected_revenue,
               AVG(e.forecast_net_profit) AS expected_net_profit,
               AVG(e.forecast_eps) AS expected_eps,
               COUNT(e.expectation_id) AS sample_size
        FROM financial_actuals f
        LEFT JOIN analyst_expectations e
          ON e.stock_code = f.stock_code AND e.forecast_period = f.report_period
        WHERE f.ann_date <= ?
        GROUP BY f.stock_code, f.report_period, f.ann_date
        HAVING f.stock_code || ':' || f.report_period NOT IN (
            SELECT stock_code || ':' || report_period FROM earnings_surprises
        )
        """,
        (trading_date,),
    ).fetchall()

    rows_loaded = 0
    for row in rows:
        actual_np = row["actual_net_profit"]
        expected_np = row["expected_net_profit"]
        surprise_pct = (
            ((actual_np - expected_np) / abs(expected_np))
            if expected_np and abs(expected_np) > 0
            else 0
        )
        actual_rev = row["actual_revenue"]
        expected_rev = row["expected_revenue"]
        rev_surprise_pct = (
            ((actual_rev - expected_rev) / abs(expected_rev))
            if expected_rev and abs(expected_rev) > 0
            else 0
        )
        surprise_id = "surp_" + hashlib.sha1(
            f"{row['stock_code']}:{row['report_period']}".encode()
        ).hexdigest()[:12]

        conn.execute(
            """
            INSERT INTO earnings_surprises(
              surprise_id, stock_code, report_period, ann_date,
              expected_net_profit, actual_net_profit, net_profit_surprise_pct,
              expected_revenue, actual_revenue, revenue_surprise_pct,
              expectation_sample_size, expectation_source, actual_source, evidence_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(stock_code, report_period) DO NOTHING
            """,
            (
                surprise_id,
                row["stock_code"],
                row["report_period"],
                row["ann_date"],
                expected_np,
                actual_np,
                surprise_pct,
                expected_rev,
                actual_rev,
                rev_surprise_pct,
                row["sample_size"] or 0,
                "aggregated_expectations",
                "financial_actuals",
                '{"method": "computed"}',
            ),
        )
        rows_loaded += 1
    conn.commit()
    return {"dataset": "earnings_surprises", "rows_loaded": rows_loaded}
