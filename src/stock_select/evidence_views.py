from __future__ import annotations

import sqlite3
from typing import Any

from . import repository
from .data_status import data_source_status


EVIDENCE_DATASETS = [
    "financial_actuals",
    "analyst_expectations",
    "earnings_surprises",
    "order_contract_events",
    "business_kpi_actuals",
    "risk_events",
]


def stock_evidence(conn: sqlite3.Connection, stock_code: str, trading_date: str) -> dict[str, Any]:
    financial = repository.latest_financial_actuals_before(conn, stock_code, trading_date)
    expectations = repository.latest_expectations_before(conn, stock_code, trading_date)
    surprises = repository.latest_earnings_surprises_before(conn, stock_code, trading_date)
    orders = repository.recent_order_contract_events_before(conn, stock_code, trading_date)
    kpis = repository.recent_business_kpis_before(conn, stock_code, trading_date)
    risks = repository.recent_risk_events_before(conn, stock_code, trading_date)
    datasets = {
        "financial_actuals": repository.rows_to_dicts([financial] if financial is not None else []),
        "analyst_expectations": repository.rows_to_dicts(expectations),
        "earnings_surprises": repository.rows_to_dicts(surprises),
        "order_contract_events": repository.rows_to_dicts(orders),
        "business_kpi_actuals": repository.rows_to_dicts(kpis),
        "risk_events": repository.rows_to_dicts(risks),
    }
    missing = [name for name, rows in datasets.items() if not rows]
    return {
        "stock_code": stock_code,
        "trading_date": trading_date,
        "datasets": datasets,
        "coverage": coverage_from_datasets(datasets),
        "missing_dimensions": missing,
        "visibility_rule": "all datasets use as_of/report dates strictly before target date",
    }


def evidence_status(conn: sqlite3.Connection, trading_date: str) -> dict[str, Any]:
    active_stock_count = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM stocks
        WHERE listing_status = 'active'
          AND COALESCE(is_st, 0) = 0
        """
    ).fetchone()["count"]
    counts = {
        "financial_actuals": distinct_count(
            conn,
            "financial_actuals",
            "COALESCE(as_of_date, ann_date)",
            trading_date,
        ),
        "analyst_expectations": distinct_count(conn, "analyst_expectations", "report_date", trading_date),
        "earnings_surprises": distinct_count(
            conn,
            "earnings_surprises",
            "COALESCE(as_of_date, ann_date)",
            trading_date,
        ),
        "order_contract_events": row_count(
            conn,
            "order_contract_events",
            "COALESCE(as_of_date, publish_date, ann_date)",
            trading_date,
        ),
        "business_kpi_actuals": distinct_count(
            conn,
            "business_kpi_actuals",
            "COALESCE(as_of_date, publish_date, period)",
            trading_date,
        ),
        "risk_events": row_count(conn, "risk_events", "as_of_date", trading_date),
    }
    coverage = {
        key: (value / active_stock_count if active_stock_count else 0.0)
        for key, value in counts.items()
        if key not in {"order_contract_events", "risk_events"}
    }
    source_rows = [
        row
        for row in data_source_status(conn, trading_date)
        if row.get("dataset") in EVIDENCE_DATASETS
    ]
    skipped = [row for row in source_rows if row.get("status") == "skipped"]
    errors = [row for row in source_rows if row.get("status") == "error"]
    return {
        "trading_date": trading_date,
        "active_stock_count": active_stock_count,
        "counts": counts,
        "coverage": coverage,
        "source_status": source_rows,
        "skipped_sources": skipped,
        "error_sources": errors,
        "message": evidence_status_message(counts, skipped, errors),
    }


def coverage_from_datasets(datasets: dict[str, list[dict[str, Any]]]) -> dict[str, bool]:
    return {key: bool(rows) for key, rows in datasets.items()}


def distinct_count(conn: sqlite3.Connection, table: str, date_expr: str, trading_date: str) -> int:
    return int(
        conn.execute(
            f"""
            SELECT COUNT(DISTINCT stock_code) AS count
            FROM {table}
            WHERE {date_expr} < ?
            """,
            (trading_date,),
        ).fetchone()["count"]
        or 0
    )


def row_count(conn: sqlite3.Connection, table: str, date_expr: str, trading_date: str) -> int:
    return int(
        conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM {table}
            WHERE {date_expr} < ?
            """,
            (trading_date,),
        ).fetchone()["count"]
        or 0
    )


def evidence_status_message(
    counts: dict[str, int],
    skipped: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> str:
    if errors:
        return "部分证据源同步失败，复盘证据不完整"
    if skipped:
        return "部分证据源未配置，缺失会被明确标记"
    if not any(counts.values()):
        return "尚未同步真实复盘证据"
    return "复盘证据已同步，缺失维度会单独标记"
