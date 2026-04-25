"""Synchronize structured review evidence for Phase C."""
from __future__ import annotations

import sqlite3
import time
from typing import Any, Callable, Iterable

from . import repository
from .data_ingestion import (
    AkShareProvider,
    BaoStockProvider,
    MarketDataProvider,
    UnsupportedDatasetError,
    apply_stock_window,
    date_range,
    liquid_stock_codes_before,
    open_trading_dates,
    reliability_for_source,
)


DEFAULT_EVIDENCE_STOCK_LIMIT = 500


def sync_financial_actuals(
    conn: sqlite3.Connection,
    trading_date: str,
    provider: MarketDataProvider | None = None,
    *,
    providers: list[MarketDataProvider] | None = None,
    stock_codes: list[str] | None = None,
    limit: int | None = DEFAULT_EVIDENCE_STOCK_LIMIT,
    offset: int = 0,
    batch_size: int = 100,
    resume: bool = True,
    throttle_seconds: float = 0.0,
) -> dict[str, Any]:
    selected_codes = select_evidence_stock_codes(conn, trading_date, stock_codes, limit=limit, offset=offset)
    return sync_provider_dataset(
        conn,
        trading_date=trading_date,
        dataset="financial_actuals",
        fetch_name="fetch_financial_actuals",
        upsert=lambda item: repository.upsert_financial_actual(conn, **item.__dict__),
        providers=providers or ([provider] if provider is not None else [BaoStockProvider()]),
        selected_codes=selected_codes,
        batch_size=batch_size,
        resume=resume,
        throttle_seconds=throttle_seconds,
        existing_selector=financial_actuals_existing_codes,
    )


def sync_analyst_expectations(
    conn: sqlite3.Connection,
    trading_date: str,
    provider: MarketDataProvider | None = None,
    *,
    providers: list[MarketDataProvider] | None = None,
    stock_codes: list[str] | None = None,
    limit: int | None = DEFAULT_EVIDENCE_STOCK_LIMIT,
    offset: int = 0,
    batch_size: int = 100,
    resume: bool = True,
    throttle_seconds: float = 0.0,
) -> dict[str, Any]:
    selected_codes = select_evidence_stock_codes(conn, trading_date, stock_codes, limit=limit, offset=offset)
    return sync_provider_dataset(
        conn,
        trading_date=trading_date,
        dataset="analyst_expectations",
        fetch_name="fetch_analyst_expectations",
        upsert=lambda item: repository.upsert_analyst_expectation(conn, **item.__dict__),
        providers=providers or ([provider] if provider is not None else [AkShareProvider(), BaoStockProvider()]),
        selected_codes=selected_codes,
        batch_size=batch_size,
        resume=resume,
        throttle_seconds=throttle_seconds,
        existing_selector=expectation_existing_codes,
    )


def sync_order_contract_events(
    conn: sqlite3.Connection,
    start: str,
    end: str | None = None,
    provider: MarketDataProvider | None = None,
    *,
    providers: list[MarketDataProvider] | None = None,
    stock_codes: list[str] | None = None,
    limit: int | None = DEFAULT_EVIDENCE_STOCK_LIMIT,
    offset: int = 0,
    batch_size: int = 100,
    resume: bool = True,
    throttle_seconds: float = 0.0,
) -> dict[str, Any]:
    end = end or start
    selected_codes = select_evidence_stock_codes(conn, end, stock_codes, limit=limit, offset=offset)
    return sync_event_dataset(
        conn,
        start=start,
        end=end,
        dataset="order_contract_events",
        fetch_name="fetch_order_contract_events",
        upsert=lambda item: repository.upsert_order_contract_event(conn, **item.__dict__),
        providers=providers or ([provider] if provider is not None else [AkShareProvider()]),
        selected_codes=selected_codes,
        batch_size=batch_size,
        resume=resume,
        throttle_seconds=throttle_seconds,
    )


def sync_business_kpi_actuals(
    conn: sqlite3.Connection,
    trading_date: str,
    provider: MarketDataProvider | None = None,
    *,
    providers: list[MarketDataProvider] | None = None,
    stock_codes: list[str] | None = None,
    limit: int | None = DEFAULT_EVIDENCE_STOCK_LIMIT,
    offset: int = 0,
    batch_size: int = 100,
    resume: bool = True,
    throttle_seconds: float = 0.0,
) -> dict[str, Any]:
    selected_codes = select_evidence_stock_codes(conn, trading_date, stock_codes, limit=limit, offset=offset)
    return sync_provider_dataset(
        conn,
        trading_date=trading_date,
        dataset="business_kpi_actuals",
        fetch_name="fetch_business_kpis",
        upsert=lambda item: repository.upsert_business_kpi_actual(conn, **item.__dict__),
        providers=providers or ([provider] if provider is not None else [AkShareProvider(), BaoStockProvider()]),
        selected_codes=selected_codes,
        batch_size=batch_size,
        resume=resume,
        throttle_seconds=throttle_seconds,
        existing_selector=business_kpi_existing_codes,
    )


def sync_risk_events(
    conn: sqlite3.Connection,
    start: str,
    end: str | None = None,
    provider: MarketDataProvider | None = None,
    *,
    providers: list[MarketDataProvider] | None = None,
    stock_codes: list[str] | None = None,
    limit: int | None = DEFAULT_EVIDENCE_STOCK_LIMIT,
    offset: int = 0,
    batch_size: int = 100,
    resume: bool = True,
    throttle_seconds: float = 0.0,
) -> dict[str, Any]:
    end = end or start
    selected_codes = select_evidence_stock_codes(conn, end, stock_codes, limit=limit, offset=offset)
    return sync_event_dataset(
        conn,
        start=start,
        end=end,
        dataset="risk_events",
        fetch_name="fetch_risk_events",
        upsert=lambda item: repository.upsert_risk_event(conn, **item.__dict__),
        providers=providers or ([provider] if provider is not None else [AkShareProvider()]),
        selected_codes=selected_codes,
        batch_size=batch_size,
        resume=resume,
        throttle_seconds=throttle_seconds,
    )


def sync_earnings_surprises(conn: sqlite3.Connection, trading_date: str) -> dict[str, Any]:
    """Compute earnings surprises from actuals vs aggregated expectations."""
    rows = conn.execute(
        """
        SELECT f.stock_code, f.report_period, COALESCE(f.as_of_date, f.ann_date) AS as_of_date,
               COALESCE(f.actual_id, f.stock_code || ':' || f.report_period || ':' || f.source) AS actual_id,
               f.revenue AS actual_revenue, f.net_profit AS actual_net_profit,
               f.eps AS actual_eps, f.source AS actual_source,
               AVG(e.forecast_revenue) AS expected_revenue,
               AVG(e.forecast_net_profit) AS expected_net_profit,
               AVG(e.forecast_eps) AS expected_eps,
               COUNT(e.expectation_id) AS sample_size,
               GROUP_CONCAT(e.expectation_id) AS expectation_ids
        FROM financial_actuals f
        LEFT JOIN analyst_expectations e
          ON e.stock_code = f.stock_code
         AND e.forecast_period = f.report_period
         AND e.report_date < COALESCE(f.as_of_date, f.ann_date)
        WHERE COALESCE(f.as_of_date, f.ann_date) <= ?
        GROUP BY f.stock_code, f.report_period, COALESCE(f.as_of_date, f.ann_date)
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
        actual_rev = row["actual_revenue"]
        expected_rev = row["expected_revenue"]
        sample_size = int(row["sample_size"] or 0)
        if sample_size <= 0:
            surprise_type = "expectation_missing"
            surprise_pct = None
            surprise_amount = None
        elif actual_np is None:
            surprise_type = "actual_missing"
            surprise_pct = None
            surprise_amount = None
        else:
            surprise_amount = actual_np - expected_np if expected_np is not None else None
            surprise_pct = surprise_amount / abs(expected_np) if surprise_amount is not None and expected_np else None
            if surprise_pct is None:
                surprise_type = "expectation_missing"
            elif surprise_pct > 0.1:
                surprise_type = "positive_surprise"
            elif surprise_pct < -0.1:
                surprise_type = "negative_surprise"
            else:
                surprise_type = "in_line"
        rev_surprise_pct = (
            ((actual_rev - expected_rev) / abs(expected_rev))
            if actual_rev is not None and expected_rev
            else None
        )
        repository.upsert_earnings_surprise(
            conn,
            stock_code=row["stock_code"],
            report_period=row["report_period"],
            as_of_date=row["as_of_date"],
            actual_id=row["actual_id"],
            expectation_snapshot_id=row["expectation_ids"],
            expected_net_profit=expected_np,
            actual_net_profit=actual_np,
            surprise_amount=surprise_amount,
            surprise_pct=surprise_pct,
            surprise_type=surprise_type,
            expected_revenue=expected_rev,
            actual_revenue=actual_rev,
            revenue_surprise_pct=rev_surprise_pct,
            expectation_sample_size=sample_size,
            expectation_source="aggregated_expectations",
            actual_source=row["actual_source"] or "financial_actuals",
            raw_json={"method": "computed"},
        )
        rows_loaded += 1
    conn.commit()
    repository.record_data_source_status(
        conn,
        source="system",
        dataset="earnings_surprises",
        trading_date=trading_date,
        status="ok",
        rows_loaded=rows_loaded,
        source_reliability="high",
    )
    conn.commit()
    return {"dataset": "earnings_surprises", "rows_loaded": rows_loaded}


def sync_evidence(
    conn: sqlite3.Connection,
    trading_date: str,
    providers: list[MarketDataProvider] | None = None,
    *,
    limit: int | None = DEFAULT_EVIDENCE_STOCK_LIMIT,
    offset: int = 0,
    batch_size: int = 100,
    resume: bool = True,
    throttle_seconds: float = 0.0,
) -> dict[str, Any]:
    providers = providers or [BaoStockProvider(), AkShareProvider()]
    event_start = trading_date
    return {
        "trading_date": trading_date,
        "financial_actuals": sync_financial_actuals(
            conn,
            trading_date,
            providers=providers,
            limit=limit,
            offset=offset,
            batch_size=batch_size,
            resume=resume,
            throttle_seconds=throttle_seconds,
        ),
        "analyst_expectations": sync_analyst_expectations(
            conn,
            trading_date,
            providers=providers,
            limit=limit,
            offset=offset,
            batch_size=batch_size,
            resume=resume,
            throttle_seconds=throttle_seconds,
        ),
        "earnings_surprises": sync_earnings_surprises(conn, trading_date),
        "order_contract_events": sync_order_contract_events(
            conn,
            event_start,
            trading_date,
            providers=providers,
            limit=limit,
            offset=offset,
            batch_size=batch_size,
            resume=resume,
            throttle_seconds=throttle_seconds,
        ),
        "business_kpi_actuals": sync_business_kpi_actuals(
            conn,
            trading_date,
            providers=providers,
            limit=limit,
            offset=offset,
            batch_size=batch_size,
            resume=resume,
            throttle_seconds=throttle_seconds,
        ),
        "risk_events": sync_risk_events(
            conn,
            event_start,
            trading_date,
            providers=providers,
            limit=limit,
            offset=offset,
            batch_size=batch_size,
            resume=resume,
            throttle_seconds=throttle_seconds,
        ),
    }


def backfill_evidence_range(
    conn: sqlite3.Connection,
    start: str,
    end: str,
    providers: list[MarketDataProvider] | None = None,
    *,
    limit: int | None = DEFAULT_EVIDENCE_STOCK_LIMIT,
    offset: int = 0,
    batch_size: int = 100,
    resume: bool = True,
    throttle_seconds: float = 0.0,
) -> dict[str, Any]:
    if start > end:
        raise ValueError("start must be <= end")
    days = open_trading_dates(conn, start, end)
    results = [
        sync_evidence(
            conn,
            trading_date,
            providers=providers,
            limit=limit,
            offset=offset,
            batch_size=batch_size,
            resume=resume,
            throttle_seconds=throttle_seconds,
        )
        for trading_date in days
    ]
    return {"start": start, "end": end, "trading_days": len(days), "days": days, "results": results}


def sync_provider_dataset(
    conn: sqlite3.Connection,
    *,
    trading_date: str,
    dataset: str,
    fetch_name: str,
    upsert: Callable[[Any], str],
    providers: list[MarketDataProvider],
    selected_codes: list[str],
    batch_size: int,
    resume: bool,
    throttle_seconds: float,
    existing_selector: Callable[[sqlite3.Connection, str, list[str], str], set[str]],
) -> dict[str, Any]:
    source_counts: dict[str, int] = {}
    errors: dict[str, str] = {}
    for provider in providers:
        fetch = getattr(provider, fetch_name, None)
        if fetch is None:
            record_skipped(conn, provider, dataset, trading_date, f"{provider.source} does not support {dataset}")
            source_counts[provider.source] = 0
            continue
        rows_loaded = 0
        failed_chunks: list[dict[str, Any]] = []
        provider_codes = selected_codes
        if resume:
            existing = existing_selector(conn, trading_date, selected_codes, provider.source)
            provider_codes = [code for code in selected_codes if code not in existing]
        for chunk_index, chunk in enumerate(chunked(provider_codes, batch_size), start=1):
            try:
                rows = fetch(trading_date, chunk)
                for item in rows:
                    upsert(item)
                    rows_loaded += 1
                conn.commit()
            except UnsupportedDatasetError as exc:
                record_skipped(conn, provider, dataset, trading_date, str(exc))
                source_counts[provider.source] = 0
                failed_chunks = []
                break
            except Exception as exc:
                failed_chunks.append({"chunk_index": chunk_index, "stock_count": len(chunk), "error": str(exc)})
            if throttle_seconds > 0:
                time.sleep(throttle_seconds)
        else:
            status = "warning" if failed_chunks else "ok"
            if failed_chunks and rows_loaded == 0:
                status = "error"
            repository.record_data_source_status(
                conn,
                source=provider.source,
                dataset=dataset,
                trading_date=trading_date,
                status=status,
                rows_loaded=rows_loaded,
                warning_count=len(failed_chunks),
                error=repository.dumps(failed_chunks) if failed_chunks else None,
                source_reliability=reliability_for_source(provider.source),
            )
            source_counts[provider.source] = rows_loaded
            if failed_chunks:
                errors[provider.source] = repository.dumps(failed_chunks)
    conn.commit()
    return {
        "trading_date": trading_date,
        "dataset": dataset,
        "sources": source_counts,
        "rows_loaded": sum(source_counts.values()),
        "errors": errors,
        "selected_stocks": len(selected_codes),
    }


def sync_event_dataset(
    conn: sqlite3.Connection,
    *,
    start: str,
    end: str,
    dataset: str,
    fetch_name: str,
    upsert: Callable[[Any], str],
    providers: list[MarketDataProvider],
    selected_codes: list[str],
    batch_size: int,
    resume: bool,
    throttle_seconds: float,
) -> dict[str, Any]:
    source_counts: dict[str, int] = {}
    errors: dict[str, str] = {}
    dates = date_range(start, end)
    for provider in providers:
        fetch = getattr(provider, fetch_name, None)
        if fetch is None:
            record_skipped(conn, provider, dataset, end, f"{provider.source} does not support {dataset}")
            source_counts[provider.source] = 0
            continue
        rows_loaded = 0
        failed_chunks: list[dict[str, Any]] = []
        skipped_dates = 0
        for event_date in dates:
            if resume and data_source_ok(conn, provider.source, dataset, event_date):
                skipped_dates += 1
                continue
            day_loaded = 0
            for chunk_index, chunk in enumerate(chunked(selected_codes, batch_size), start=1):
                try:
                    rows = fetch(event_date, event_date, chunk)
                    for item in rows:
                        upsert(item)
                        rows_loaded += 1
                        day_loaded += 1
                    conn.commit()
                except UnsupportedDatasetError as exc:
                    record_skipped(conn, provider, dataset, event_date, str(exc))
                    source_counts[provider.source] = 0
                    failed_chunks = []
                    break
                except Exception as exc:
                    failed_chunks.append({"trading_date": event_date, "chunk_index": chunk_index, "stock_count": len(chunk), "error": str(exc)})
                if throttle_seconds > 0:
                    time.sleep(throttle_seconds)
            else:
                repository.record_data_source_status(
                    conn,
                    source=provider.source,
                    dataset=dataset,
                    trading_date=event_date,
                    status="ok",
                    rows_loaded=day_loaded,
                    source_reliability=reliability_for_source(provider.source),
                )
                continue
            # Unsupported dataset broke out of chunk loop.
            if source_counts.get(provider.source) == 0 and not failed_chunks:
                break
        if provider.source not in source_counts:
            status = "warning" if failed_chunks else "ok"
            if failed_chunks and rows_loaded == 0:
                status = "error"
            repository.record_data_source_status(
                conn,
                source=provider.source,
                dataset=dataset,
                trading_date=end,
                status=status,
                rows_loaded=rows_loaded,
                warning_count=len(failed_chunks),
                error=repository.dumps(failed_chunks) if failed_chunks else None,
                source_reliability=reliability_for_source(provider.source),
            )
            source_counts[provider.source] = rows_loaded
            if failed_chunks:
                errors[provider.source] = repository.dumps(failed_chunks)
    conn.commit()
    return {
        "start": start,
        "end": end,
        "dataset": dataset,
        "dates": len(dates),
        "sources": source_counts,
        "rows_loaded": sum(source_counts.values()),
        "errors": errors,
        "selected_stocks": len(selected_codes),
    }


def select_evidence_stock_codes(
    conn: sqlite3.Connection,
    trading_date: str,
    stock_codes: list[str] | None,
    *,
    limit: int | None,
    offset: int,
) -> list[str]:
    if stock_codes is not None:
        return apply_stock_window(stock_codes, offset=offset, limit=limit)
    return liquid_stock_codes_before(conn, trading_date, limit=limit, offset=offset)


def record_skipped(conn: sqlite3.Connection, provider: MarketDataProvider, dataset: str, trading_date: str, reason: str) -> None:
    repository.record_data_source_status(
        conn,
        source=provider.source,
        dataset=dataset,
        trading_date=trading_date,
        status="skipped",
        rows_loaded=0,
        error=reason,
        source_reliability=reliability_for_source(provider.source),
    )
    conn.commit()


def data_source_ok(conn: sqlite3.Connection, source: str, dataset: str, trading_date: str) -> bool:
    row = conn.execute(
        """
        SELECT status FROM data_sources
        WHERE source = ? AND dataset = ? AND trading_date = ?
        """,
        (source, dataset, trading_date),
    ).fetchone()
    return bool(row and row["status"] == "ok")


def financial_actuals_existing_codes(
    conn: sqlite3.Connection,
    trading_date: str,
    stock_codes: list[str],
    source: str,
) -> set[str]:
    return existing_codes(conn, "financial_actuals", trading_date, stock_codes, source, "COALESCE(as_of_date, ann_date)")


def expectation_existing_codes(
    conn: sqlite3.Connection,
    trading_date: str,
    stock_codes: list[str],
    source: str,
) -> set[str]:
    return existing_codes(conn, "analyst_expectations", trading_date, stock_codes, source, "report_date")


def business_kpi_existing_codes(
    conn: sqlite3.Connection,
    trading_date: str,
    stock_codes: list[str],
    source: str,
) -> set[str]:
    return existing_codes(conn, "business_kpi_actuals", trading_date, stock_codes, source, "COALESCE(as_of_date, publish_date, period)")


def existing_codes(
    conn: sqlite3.Connection,
    table: str,
    trading_date: str,
    stock_codes: list[str],
    source: str,
    date_expr: str,
) -> set[str]:
    if not stock_codes:
        return set()
    placeholders = ",".join("?" for _ in stock_codes)
    rows = conn.execute(
        f"""
        SELECT DISTINCT stock_code FROM {table}
        WHERE {date_expr} < ?
          AND source = ?
          AND stock_code IN ({placeholders})
        """,
        (trading_date, source, *stock_codes),
    ).fetchall()
    return {row["stock_code"] for row in rows}


def chunked(values: list[str], size: int) -> Iterable[list[str]]:
    if size <= 0:
        raise ValueError("batch_size must be positive")
    for index in range(0, len(values), size):
        yield values[index : index + size]
