from __future__ import annotations

import sqlite3

from . import repository
from .strategies import seed_default_genes


DEMO_DATES = [
    "2026-01-02",
    "2026-01-05",
    "2026-01-06",
    "2026-01-07",
    "2026-01-08",
    "2026-01-09",
    "2026-01-12",
    "2026-01-13",
]


def seed_demo_data(conn: sqlite3.Connection) -> None:
    seed_default_genes(conn)
    for date in DEMO_DATES:
        repository.upsert_trading_day(conn, date, True)

    repository.upsert_stock(conn, "000001.SZ", "Ping An Bank", exchange="SZSE", industry="Bank")
    repository.upsert_stock(conn, "000002.SZ", "Vanke A", exchange="SZSE", industry="Real Estate")
    repository.upsert_stock(conn, "600519.SH", "Kweichow Moutai", exchange="SSE", industry="Food")
    repository.upsert_stock(conn, "300750.SZ", "CATL", exchange="SZSE", industry="Battery")

    rows = []
    series = {
        "000001.SZ": [10.0, 10.1, 10.25, 10.38, 10.55, 10.7, 10.95, 11.2],
        "000002.SZ": [8.0, 7.95, 7.9, 7.86, 7.88, 7.82, 7.78, 7.75],
        "600519.SH": [1550, 1558, 1560, 1568, 1575, 1588, 1592, 1605],
        "300750.SZ": [210, 214, 218, 225, 232, 238, 250, 262],
    }
    for stock_code, closes in series.items():
        for index, close in enumerate(closes):
            open_price = closes[index - 1] if index > 0 else close * 0.995
            high = max(open_price, close) * 1.015
            low = min(open_price, close) * 0.985
            rows.append(
                {
                    "stock_code": stock_code,
                    "trading_date": DEMO_DATES[index],
                    "open": round(open_price, 4),
                    "high": round(high, 4),
                    "low": round(low, 4),
                    "close": round(close, 4),
                    "volume": 1_000_000 + index * 100_000,
                    "amount": close * (1_000_000 + index * 100_000),
                    "source": "demo",
                }
            )
            repository.upsert_source_daily_price(
                conn,
                source="akshare",
                stock_code=stock_code,
                trading_date=DEMO_DATES[index],
                open=round(open_price, 4),
                high=round(high, 4),
                low=round(low, 4),
                close=round(close, 4),
                volume=1_000_000 + index * 100_000,
                amount=close * (1_000_000 + index * 100_000),
            )
            repository.upsert_source_daily_price(
                conn,
                source="baostock",
                stock_code=stock_code,
                trading_date=DEMO_DATES[index],
                open=round(open_price, 4),
                high=round(high, 4),
                low=round(low, 4),
                close=round(close * 1.0005, 4),
                volume=1_000_000 + index * 100_000,
                amount=close * (1_000_000 + index * 100_000),
            )
    repository.insert_many_prices(conn, rows)
    seed_demo_multidimensional_signals(conn)
    seed_demo_review_facts(conn)
    conn.commit()


def seed_demo_multidimensional_signals(conn: sqlite3.Connection) -> None:
    fundamentals = [
        {
            "stock_code": "000001.SZ",
            "as_of_date": "2025-12-31",
            "report_period": "2025Q3",
            "roe": 0.105,
            "revenue_growth": 0.065,
            "net_profit_growth": 0.09,
            "gross_margin": 0.0,
            "debt_to_assets": 0.91,
            "operating_cashflow_to_profit": 1.05,
            "pe_percentile": 0.38,
            "pb_percentile": 0.32,
            "dividend_yield": 0.035,
            "quality_note": "stable bank profitability",
            "source": "demo",
        },
        {
            "stock_code": "000002.SZ",
            "as_of_date": "2025-12-31",
            "report_period": "2025Q3",
            "roe": 0.035,
            "revenue_growth": -0.12,
            "net_profit_growth": -0.2,
            "gross_margin": 0.18,
            "debt_to_assets": 0.78,
            "operating_cashflow_to_profit": 0.65,
            "pe_percentile": 0.24,
            "pb_percentile": 0.2,
            "dividend_yield": 0.02,
            "quality_note": "real estate balance sheet pressure",
            "source": "demo",
        },
        {
            "stock_code": "600519.SH",
            "as_of_date": "2025-12-31",
            "report_period": "2025Q3",
            "roe": 0.29,
            "revenue_growth": 0.15,
            "net_profit_growth": 0.17,
            "gross_margin": 0.91,
            "debt_to_assets": 0.18,
            "operating_cashflow_to_profit": 1.22,
            "pe_percentile": 0.55,
            "pb_percentile": 0.62,
            "dividend_yield": 0.018,
            "quality_note": "premium consumer franchise",
            "source": "demo",
        },
        {
            "stock_code": "300750.SZ",
            "as_of_date": "2025-12-31",
            "report_period": "2025Q3",
            "roe": 0.18,
            "revenue_growth": 0.24,
            "net_profit_growth": 0.21,
            "gross_margin": 0.25,
            "debt_to_assets": 0.56,
            "operating_cashflow_to_profit": 0.98,
            "pe_percentile": 0.48,
            "pb_percentile": 0.5,
            "dividend_yield": 0.006,
            "quality_note": "growth leader with cyclical volatility",
            "source": "demo",
        },
    ]
    for item in fundamentals:
        repository.upsert_fundamental_metrics(conn, **item)

    sector_signals = [
        ("2026-01-12", "Battery", 0.035, 1, 0.55, 0.92, 3, "battery supply chain is the strongest theme"),
        ("2026-01-12", "Food", 0.008, 3, 0.1, 0.35, 1, "defensive consumption is steady"),
        ("2026-01-12", "Bank", 0.006, 4, 0.04, 0.22, 0, "banks remain stable but not leading"),
        ("2026-01-12", "Real Estate", -0.018, 8, -0.2, 0.08, 0, "property sector remains weak"),
    ]
    for trading_date, industry, ret, rank, volume, theme, catalysts, summary in sector_signals:
        repository.upsert_sector_theme_signal(
            conn,
            trading_date=trading_date,
            industry=industry,
            sector_return_pct=ret,
            relative_strength_rank=rank,
            volume_surge=volume,
            theme_strength=theme,
            catalyst_count=catalysts,
            summary=summary,
            source="demo",
        )

    events = [
        {
            "event_id": "event_battery_policy_20260112",
            "trading_date": "2026-01-12",
            "published_at": "2026-01-12 08:30:00",
            "industry": "Battery",
            "event_type": "policy",
            "title": "新能源链政策预期升温",
            "summary": "市场关注新能源补贴和储能需求改善，电池板块热度上升。",
            "impact_score": 0.85,
            "sentiment": 0.7,
            "source": "demo",
        },
        {
            "event_id": "event_catl_order_20260112",
            "trading_date": "2026-01-12",
            "published_at": "2026-01-12 10:20:00",
            "stock_code": "300750.SZ",
            "industry": "Battery",
            "event_type": "company_news",
            "title": "CATL 储能订单预期改善",
            "summary": "市场传闻储能订单环比改善，强化成长股风险偏好。",
            "impact_score": 0.75,
            "sentiment": 0.65,
            "source": "demo",
        },
        {
            "event_id": "event_property_risk_20260112",
            "trading_date": "2026-01-12",
            "published_at": "2026-01-12 09:10:00",
            "industry": "Real Estate",
            "event_type": "risk",
            "title": "地产销售恢复偏慢",
            "summary": "地产销售数据仍弱，板块风险偏好受压。",
            "impact_score": -0.55,
            "sentiment": -0.7,
            "source": "demo",
        },
    ]
    for event in events:
        repository.upsert_event_signal(conn, **event)


def seed_demo_review_facts(conn: sqlite3.Connection) -> None:
    expectations = [
        ("exp_catl_2025_demo_a", "300750.SZ", "2026-01-10", "2025FY", "Demo Securities", "Analyst A", "CATL growth preview", 430_000_000_000, 42_000_000_000, 9.4, 28.0, "BUY", 280, 320),
        ("exp_catl_2025_demo_b", "300750.SZ", "2026-01-11", "2025FY", "Demo Research", "Analyst B", "Storage demand improves", 435_000_000_000, 43_000_000_000, 9.6, 27.5, "BUY", 285, 330),
        ("exp_moutai_2025_demo", "600519.SH", "2026-01-09", "2025FY", "Demo Securities", "Analyst C", "Defensive growth", 180_000_000_000, 86_000_000_000, 68.2, 24.0, "OVERWEIGHT", 1700, 1850),
        ("exp_vanke_2025_demo", "000002.SZ", "2026-01-08", "2025FY", "Demo Securities", "Analyst D", "Property pressure", 430_000_000_000, 8_000_000_000, 0.75, 9.0, "HOLD", 8, 10),
    ]
    for item in expectations:
        conn.execute(
            """
            INSERT INTO analyst_expectations(
              expectation_id, stock_code, report_date, forecast_period, org_name,
              author_name, report_title, forecast_revenue, forecast_net_profit,
              forecast_eps, forecast_pe, rating, target_price_min, target_price_max,
              source, source_url
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'demo', NULL)
            ON CONFLICT(stock_code, report_date, forecast_period, org_name, author_name) DO UPDATE SET
              forecast_revenue = excluded.forecast_revenue,
              forecast_net_profit = excluded.forecast_net_profit,
              forecast_eps = excluded.forecast_eps,
              rating = excluded.rating
            """,
            item,
        )

    actuals = [
        ("300750.SZ", "2025FY", "2026-01-12", 450_000_000_000, 48_000_000_000, 46_000_000_000, 10.8, 0.19, 0.26, 52_000_000_000),
        ("600519.SH", "2025FY", "2026-01-12", 182_000_000_000, 88_000_000_000, 87_000_000_000, 69.8, 0.30, 0.91, 96_000_000_000),
        ("000002.SZ", "2025FY", "2026-01-12", 405_000_000_000, 4_000_000_000, 3_200_000_000, 0.38, 0.02, 0.16, 18_000_000_000),
    ]
    for item in actuals:
        conn.execute(
            """
            INSERT INTO financial_actuals(
              stock_code, report_period, ann_date, revenue, net_profit,
              net_profit_deducted, eps, roe, gross_margin, operating_cashflow,
              source, source_url
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'demo', NULL)
            ON CONFLICT(stock_code, report_period, source) DO UPDATE SET
              ann_date = excluded.ann_date,
              revenue = excluded.revenue,
              net_profit = excluded.net_profit,
              net_profit_deducted = excluded.net_profit_deducted,
              eps = excluded.eps,
              roe = excluded.roe,
              gross_margin = excluded.gross_margin,
              operating_cashflow = excluded.operating_cashflow
            """,
            item,
        )

    surprises = [
        ("surprise_catl_2025fy", "300750.SZ", "2025FY", "2026-01-12", 42_500_000_000, 48_000_000_000, 0.1294, 432_500_000_000, 450_000_000_000, 0.0405, 2, "demo_expectations", "demo_actuals"),
        ("surprise_moutai_2025fy", "600519.SH", "2025FY", "2026-01-12", 86_000_000_000, 88_000_000_000, 0.0233, 180_000_000_000, 182_000_000_000, 0.0111, 1, "demo_expectations", "demo_actuals"),
        ("surprise_vanke_2025fy", "000002.SZ", "2025FY", "2026-01-12", 8_000_000_000, 4_000_000_000, -0.5, 430_000_000_000, 405_000_000_000, -0.0581, 1, "demo_expectations", "demo_actuals"),
    ]
    for item in surprises:
        conn.execute(
            """
            INSERT INTO earnings_surprises(
              surprise_id, stock_code, report_period, ann_date, expected_net_profit,
              actual_net_profit, net_profit_surprise_pct, expected_revenue,
              actual_revenue, revenue_surprise_pct, expectation_sample_size,
              expectation_source, actual_source, evidence_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}')
            ON CONFLICT(stock_code, report_period) DO UPDATE SET
              expected_net_profit = excluded.expected_net_profit,
              actual_net_profit = excluded.actual_net_profit,
              net_profit_surprise_pct = excluded.net_profit_surprise_pct,
              expected_revenue = excluded.expected_revenue,
              actual_revenue = excluded.actual_revenue,
              revenue_surprise_pct = excluded.revenue_surprise_pct
            """,
            item,
        )

    contracts = [
        ("contract_catl_storage_20260112", "300750.SZ", "2026-01-12", "signed_order", "Demo Utility", "energy storage system", 12_000_000_000, "CNY", "2026-01-01", "2026-12-31", 0, 400_000_000_000, 0.03, "demo", None, "STRUCTURED_API", 0.82, "demo_hash"),
    ]
    for item in contracts:
        conn.execute(
            """
            INSERT OR REPLACE INTO order_contract_events(
              event_id, stock_code, ann_date, event_type, customer_name, product_name,
              contract_amount, currency, contract_period_start, contract_period_end,
              is_framework_agreement, related_revenue_last_year,
              order_to_last_year_revenue_pct, source, source_url, extraction_method,
              confidence, raw_text_hash
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            item,
        )

    kpis = [
        ("kpi_catl_order_backlog_2025h2", "300750.SZ", "2025H2", "order_backlog", 80_000_000_000, "CNY", 0.35, 0.18, "demo", None, "STRUCTURED_API", 0.76),
        ("kpi_vanke_sales_2025h2", "000002.SZ", "2025H2", "contracted_sales", 180_000_000_000, "CNY", -0.28, -0.1, "demo", None, "STRUCTURED_API", 0.72),
    ]
    for item in kpis:
        conn.execute(
            """
            INSERT INTO business_kpi_actuals(
              kpi_id, stock_code, period, kpi_name, kpi_value, unit, yoy_pct,
              qoq_pct, source, source_url, extraction_method, confidence
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(stock_code, period, kpi_name, source) DO UPDATE SET
              kpi_value = excluded.kpi_value,
              yoy_pct = excluded.yoy_pct,
              qoq_pct = excluded.qoq_pct,
              confidence = excluded.confidence
            """,
            item,
        )
