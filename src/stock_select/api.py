from __future__ import annotations

from pathlib import Path
from typing import Any

from .agent_runtime import run_phase
from .db import connect, init_db
from .blindspot_review import run_blindspot_review
from .data_ingestion import (
    AkShareProvider,
    BaoStockProvider,
    DemoProvider,
    classify_market_environment,
    publish_canonical_prices,
    sync_all_data,
    sync_daily_prices,
    sync_event_signals,
    sync_factors,
    sync_fundamentals,
    sync_industries,
    sync_index_prices,
    sync_sector_signals,
    sync_stock_universe,
    sync_trading_calendar,
)
from .data_status import data_quality_rows, data_quality_summary, data_source_status
from .deterministic_review import review_decision
from .evolution import promote_challenger, propose_strategy_evolution, rollback_evolution
from .factor_views import factor_status, sector_factors, stock_factors
from .gene_review import get_preopen_strategy_review, list_preopen_strategy_reviews, review_gene
from .graph import query_graph
from .memory import search_memory
from .optimization_signals import list_optimization_signals
from .repository import latest_trading_date, rows_to_dicts
from .review_packets import stock_review, stock_review_history
from .runtime import resolve_runtime
from .simulator import summarize_performance
from .strategies import seed_default_genes
from .system_review import review_summary
from .task_monitor import get_recent_runs, get_daily_report, get_error_summary, get_phase_summary
from .data_health import check_source_health, get_coverage, generate_health_report, get_missing_dates

try:  # pragma: no cover - FastAPI is optional in the local test environment.
    from fastapi import FastAPI, Query
    from fastapi.middleware.cors import CORSMiddleware
except Exception:  # pragma: no cover
    FastAPI = None  # type: ignore[assignment]
    Query = None  # type: ignore[assignment]
    CORSMiddleware = None  # type: ignore[assignment]


DB_PATH = Path("var/stock_select.db")


def create_app(db_path: str | Path | None = None, mode: str = "demo"):
    if FastAPI is None:  # pragma: no cover
        raise RuntimeError("FastAPI is not installed. Install with: pip install -e '.[api]'")

    runtime = resolve_runtime(mode, db_path)
    app = FastAPI(title="Stock Select", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def db():
        conn = connect(runtime.db_path)
        init_db(conn)
        seed_default_genes(conn)
        return conn

    @app.get("/api/dashboard")
    def dashboard(date: str | None = None) -> dict[str, Any]:
        conn = db()
        try:
            current_date = date or latest_trading_date(conn)
            if not current_date:
                return runtime.as_payload() | {"date": None, "picks": [], "performance": [], "runs": []}
            quality_summary = data_quality_summary(conn, current_date)
            market = quality_summary.get("market_environment") or {}
            return runtime.as_payload() | {
                "date": current_date,
                "market_environment": market.get("market_environment") if isinstance(market, dict) else None,
                "picks": rows_to_dicts(
                    conn.execute(
                        """
                        SELECT p.*, s.name AS stock_name, o.return_pct, o.hit_sell_rule
                        FROM pick_decisions p
                        JOIN stocks s ON s.stock_code = p.stock_code
                        LEFT JOIN outcomes o ON o.decision_id = p.decision_id
                        WHERE p.trading_date = ?
                        ORDER BY p.strategy_gene_id, p.score DESC
                        """,
                        (current_date,),
                    )
                ),
                "performance": summarize_performance(conn, current_date),
                "runs": rows_to_dicts(
                    conn.execute(
                        "SELECT * FROM research_runs WHERE trading_date = ? ORDER BY started_at DESC",
                        (current_date,),
                    )
                ),
                "data_quality": rows_to_dicts(
                    conn.execute(
                        "SELECT * FROM price_source_checks WHERE trading_date = ? ORDER BY status DESC LIMIT 50",
                        (current_date,),
                    )
                ),
                "data_status": data_source_status(conn, current_date),
                "data_quality_summary": quality_summary,
                "candidate_scores": rows_to_dicts(
                    conn.execute(
                        """
                        SELECT * FROM candidate_scores
                        WHERE trading_date = ?
                        ORDER BY total_score DESC
                        LIMIT 50
                        """,
                        (current_date,),
                    )
                ),
                "review_summary": review_summary(conn, current_date),
            }
        finally:
            conn.close()

    @app.get("/api/data/status")
    def data_status(date: str | None = None) -> list[dict[str, Any]]:
        conn = db()
        try:
            return data_source_status(conn, date)
        finally:
            conn.close()

    @app.get("/api/data/quality")
    def data_quality(date: str, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        conn = db()
        try:
            return data_quality_rows(conn, date, status=status, limit=limit)
        finally:
            conn.close()

    @app.get("/api/factors/status")
    def factors_status(date: str) -> dict[str, Any]:
        conn = db()
        try:
            return factor_status(conn, date)
        finally:
            conn.close()

    @app.get("/api/factors/stocks/{stock_code}")
    def factors_stock(stock_code: str, date: str) -> dict[str, Any]:
        conn = db()
        try:
            return stock_factors(conn, stock_code, date)
        finally:
            conn.close()

    @app.get("/api/factors/sectors")
    def factors_sectors(date: str) -> list[dict[str, Any]]:
        conn = db()
        try:
            return sector_factors(conn, date)
        finally:
            conn.close()

    @app.post("/api/data/sync")
    def data_sync(
        date: str,
        dataset: str = "all",
        source: str = "all",
        limit: int | None = None,
        offset: int = 0,
        batch_size: int = 100,
        resume: bool = False,
        max_retries: int = 1,
        throttle_seconds: float = 0.0,
        publish_canonical: bool = False,
    ) -> dict[str, Any]:
        conn = db()
        try:
            return run_data_sync(
                conn,
                dataset,
                date,
                source=source,
                limit=limit,
                offset=offset,
                batch_size=batch_size,
                resume=resume,
                max_retries=max_retries,
                throttle_seconds=throttle_seconds,
                publish_canonical=publish_canonical,
            )
        finally:
            conn.close()

    @app.get("/api/picks")
    def picks(date: str, gene_id: str | None = None, horizon: str | None = None) -> list[dict[str, Any]]:
        conn = db()
        try:
            clauses = ["trading_date = ?"]
            params: list[Any] = [date]
            if gene_id:
                clauses.append("strategy_gene_id = ?")
                params.append(gene_id)
            if horizon:
                clauses.append("horizon = ?")
                params.append(horizon)
            return rows_to_dicts(
                conn.execute(
                    f"SELECT * FROM pick_decisions WHERE {' AND '.join(clauses)} ORDER BY score DESC",
                    params,
                )
            )
        finally:
            conn.close()

    @app.get("/api/genes")
    def genes() -> list[dict[str, Any]]:
        conn = db()
        try:
            rows = rows_to_dicts(conn.execute("SELECT * FROM strategy_genes ORDER BY gene_id"))
            perf = {item["strategy_gene_id"]: item for item in summarize_performance(conn)}
            for row in rows:
                row["performance"] = perf.get(row["gene_id"])
            return rows
        finally:
            conn.close()

    @app.get("/api/evolution/events")
    def evolution_events(gene_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        conn = db()
        try:
            if gene_id:
                return rows_to_dicts(
                    conn.execute(
                        """
                        SELECT * FROM strategy_evolution_events
                        WHERE parent_gene_id = ? OR child_gene_id = ?
                        ORDER BY created_at DESC
                        LIMIT ?
                        """,
                        (gene_id, gene_id, limit),
                    )
                )
            return rows_to_dicts(
                conn.execute(
                    "SELECT * FROM strategy_evolution_events ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )
            )
        finally:
            conn.close()

    @app.get("/api/optimization-signals")
    def optimization_signals(gene_id: str | None = None, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        conn = db()
        try:
            return list_optimization_signals(conn, gene_id=gene_id, status=status, limit=limit)
        finally:
            conn.close()

    @app.post("/api/evolution/propose")
    def propose_evolution(
        start: str,
        end: str,
        gene_id: str | None = None,
        min_trades: int = 20,
        min_signal_samples: int = 5,
        min_signal_confidence: float = 0.65,
        min_signal_dates: int = 3,
    ) -> dict[str, Any]:
        conn = db()
        try:
            return propose_strategy_evolution(
                conn,
                period_start=start,
                period_end=end,
                gene_id=gene_id,
                min_trades=min_trades,
                min_signal_samples=min_signal_samples,
                min_signal_confidence=min_signal_confidence,
                min_signal_dates=min_signal_dates,
            )
        finally:
            conn.close()

    @app.post("/api/evolution/rollback")
    def rollback(
        child_gene_id: str | None = None,
        event_id: str | None = None,
        reason: str = "manual rollback",
    ) -> dict[str, Any]:
        conn = db()
        try:
            return rollback_evolution(conn, child_gene_id=child_gene_id, event_id=event_id, reason=reason)
        finally:
            conn.close()

    @app.post("/api/evolution/promote")
    def promote(child_gene_id: str, reason: str = "manual promotion") -> dict[str, Any]:
        conn = db()
        try:
            return promote_challenger(conn, child_gene_id=child_gene_id, reason=reason)
        finally:
            conn.close()

    @app.get("/api/genes/{gene_id}/performance")
    def gene_performance(gene_id: str) -> dict[str, Any]:
        conn = db()
        try:
            curve = rows_to_dicts(
                conn.execute(
                    """
                    SELECT p.trading_date, AVG(o.return_pct) AS avg_return_pct,
                           COUNT(o.outcome_id) AS trades
                    FROM pick_decisions p
                    JOIN outcomes o ON o.decision_id = p.decision_id
                    WHERE p.strategy_gene_id = ?
                    GROUP BY p.trading_date
                    ORDER BY p.trading_date
                    """,
                    (gene_id,),
                )
            )
            return {"gene_id": gene_id, "summary": summarize_performance(conn), "curve": curve}
        finally:
            conn.close()

    @app.get("/api/runs")
    def runs(date: str | None = None) -> list[dict[str, Any]]:
        conn = db()
        try:
            if date:
                return rows_to_dicts(conn.execute("SELECT * FROM research_runs WHERE trading_date = ?", (date,)))
            return rows_to_dicts(conn.execute("SELECT * FROM research_runs ORDER BY started_at DESC LIMIT 100"))
        finally:
            conn.close()

    @app.post("/api/runs/{phase}")
    def trigger_run(phase: str, date: str) -> dict[str, Any]:
        conn = db()
        try:
            return run_phase(conn, phase, date)
        finally:
            conn.close()

    @app.get("/api/reviews")
    def reviews(date: str) -> list[dict[str, Any]]:
        conn = db()
        try:
            return rows_to_dicts(conn.execute("SELECT * FROM review_logs WHERE trading_date = ?", (date,)))
        finally:
            conn.close()

    @app.get("/api/reviews/stocks/{stock_code}")
    def stock_review_endpoint(stock_code: str, date: str, gene_id: str | None = None) -> dict[str, Any]:
        conn = db()
        try:
            return stock_review(conn, stock_code, date, gene_id)
        finally:
            conn.close()

    @app.get("/api/reviews/stocks/{stock_code}/history")
    def stock_review_history_endpoint(
        stock_code: str,
        start: str,
        end: str,
        gene_id: str | None = None,
    ) -> dict[str, Any]:
        conn = db()
        try:
            return stock_review_history(conn, stock_code, start, end, gene_id)
        finally:
            conn.close()

    @app.post("/api/reviews/stocks/{stock_code}/rerun")
    def rerun_stock_review(stock_code: str, date: str, gene_id: str | None = None) -> dict[str, Any]:
        conn = db()
        try:
            clauses = ["trading_date = ?", "stock_code = ?"]
            params: list[Any] = [date, stock_code]
            if gene_id:
                clauses.append("strategy_gene_id = ?")
                params.append(gene_id)
            rows = conn.execute(
                f"SELECT decision_id FROM pick_decisions WHERE {' AND '.join(clauses)}",
                params,
            ).fetchall()
            for row in rows:
                review_decision(conn, row["decision_id"])
            conn.commit()
            return stock_review(conn, stock_code, date, gene_id)
        finally:
            conn.close()

    @app.get("/api/reviews/preopen-strategies")
    def preopen_strategy_reviews(date: str) -> list[dict[str, Any]]:
        conn = db()
        try:
            return list_preopen_strategy_reviews(conn, date)
        finally:
            conn.close()

    @app.get("/api/reviews/preopen-strategies/{gene_id}")
    def preopen_strategy_review(gene_id: str, date: str) -> dict[str, Any]:
        conn = db()
        try:
            return get_preopen_strategy_review(conn, gene_id, date)
        finally:
            conn.close()

    @app.post("/api/reviews/preopen-strategies/{gene_id}/rerun")
    def rerun_preopen_strategy_review(gene_id: str, date: str) -> dict[str, Any]:
        conn = db()
        try:
            rows = conn.execute(
                "SELECT decision_id FROM pick_decisions WHERE trading_date = ? AND strategy_gene_id = ?",
                (date, gene_id),
            ).fetchall()
            for row in rows:
                review_decision(conn, row["decision_id"])
            run_blindspot_review(conn, date)
            review_gene(conn, gene_id=gene_id, period_start=date, period_end=date)
            conn.commit()
            return get_preopen_strategy_review(conn, gene_id, date)
        finally:
            conn.close()

    @app.get("/api/memory/search")
    def memory_search(q: str, limit: int = 10) -> list[dict[str, Any]]:
        conn = db()
        try:
            return search_memory(conn, q, limit)
        finally:
            conn.close()

    @app.get("/api/blindspots")
    def blindspots(date: str) -> list[dict[str, Any]]:
        conn = db()
        try:
            return rows_to_dicts(conn.execute("SELECT * FROM blindspot_reports WHERE trading_date = ? ORDER BY rank", (date,)))
        finally:
            conn.close()

    @app.get("/api/graph/query")
    def graph_query(node_type: str | None = None, limit: int = 100) -> dict[str, Any]:
        conn = db()
        try:
            return query_graph(conn, node_type, limit)
        finally:
            conn.close()

    # --- Monitor endpoints ---

    @app.get("/api/monitor/runs")
    def monitor_runs(status: str | None = None, phase: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        conn = db()
        try:
            runs = get_recent_runs(conn, status=status, phase=phase, limit=limit)
            return [
                {
                    "run_id": r.run_id,
                    "phase": r.phase,
                    "trading_date": r.trading_date,
                    "status": r.status,
                    "error": r.error,
                    "started_at": r.started_at,
                    "finished_at": r.finished_at,
                }
                for r in runs
            ]
        finally:
            conn.close()

    @app.get("/api/monitor/daily-report")
    def monitor_daily_report(date: str) -> dict[str, Any]:
        conn = db()
        try:
            report = get_daily_report(conn, date)
            return {
                "trading_date": report.trading_date,
                "phases_run": report.phases_run,
                "phases_missing": report.phases_missing,
                "all_ok": report.all_ok,
                "errors": report.errors,
            }
        finally:
            conn.close()

    @app.get("/api/monitor/errors")
    def monitor_errors(limit: int = 20) -> list[dict[str, Any]]:
        conn = db()
        try:
            return get_error_summary(conn, limit=limit)
        finally:
            conn.close()

    @app.get("/api/monitor/phase-summary")
    def monitor_phase_summary(phase: str) -> dict[str, Any]:
        conn = db()
        try:
            summary = get_phase_summary(conn, phase)
            return {
                "phase": summary.phase,
                "total_runs": summary.total_runs,
                "ok_runs": summary.ok_runs,
                "error_runs": summary.error_runs,
                "last_run_date": summary.last_run_date,
                "last_run_status": summary.last_run_status,
            }
        finally:
            conn.close()

    @app.get("/api/monitor/health")
    def monitor_health() -> dict[str, Any]:
        conn = db()
        try:
            report = generate_health_report(conn)
            return {
                "generated_at": report.generated_at,
                "sources": [
                    {
                        "source": s.source,
                        "status": s.status,
                        "last_sync": s.last_sync,
                        "staleness_hours": s.staleness_hours,
                    }
                    for s in report.sources
                ],
                "latest_trading_date": report.latest_trading_date,
                "coverage": {
                    "trading_date": report.coverage_today.trading_date,
                    "stocks_synced": report.coverage_today.stocks_synced,
                    "prices_synced": report.coverage_today.prices_synced,
                    "coverage_pct": report.coverage_today.coverage_pct,
                    "factor_types": report.coverage_today.factor_types,
                } if report.coverage_today else None,
                "stale_sources": report.stale_sources,
                "error_count": report.error_count,
            }
        finally:
            conn.close()

    @app.get("/api/monitor/missing-dates")
    def monitor_missing_dates(days: int = 5) -> list[str]:
        conn = db()
        try:
            return get_missing_dates(conn, lookback_days=days)
        finally:
            conn.close()

    return app


if FastAPI is not None:  # pragma: no cover
    app = create_app()


def run_data_sync(
    conn,
    dataset: str,
    date: str,
    *,
    source: str = "all",
    limit: int | None = None,
    offset: int = 0,
    batch_size: int = 100,
    resume: bool = False,
    max_retries: int = 1,
    throttle_seconds: float = 0.0,
    publish_canonical: bool = False,
) -> dict[str, Any]:
    if dataset == "all":
        return sync_all_data(conn, date)
    if dataset == "stock_universe":
        return sync_stock_universe(conn)
    if dataset == "trading_calendar":
        from .agent_runtime import calendar_start_for

        return sync_trading_calendar(conn, calendar_start_for(date), date)
    if dataset == "daily_prices":
        result = sync_daily_prices(
            conn,
            date,
            providers=providers_for_source(source),
            limit=limit,
            offset=offset,
            batch_size=batch_size,
            resume=resume,
            max_retries=max_retries,
            throttle_seconds=throttle_seconds,
        )
        if publish_canonical:
            result["canonical_prices"] = publish_canonical_prices(conn, date)
        return result
    if dataset == "index_prices":
        return sync_index_prices(conn, date)
    if dataset == "canonical_prices":
        return publish_canonical_prices(conn, date)
    if dataset == "market_environment":
        return classify_market_environment(conn, date)
    if dataset == "industries":
        return sync_industries(conn, date, providers=providers_for_source(source))
    if dataset == "sector_signals":
        return sync_sector_signals(conn, date)
    if dataset == "fundamentals":
        return sync_fundamentals(
            conn,
            date,
            providers=providers_for_source(source),
            limit=limit,
            offset=offset,
            batch_size=batch_size,
            resume=resume,
            throttle_seconds=throttle_seconds,
        )
    if dataset == "event_signals":
        return sync_event_signals(
            conn,
            date,
            date,
            providers=providers_for_source(source),
            limit=limit,
            offset=offset,
            batch_size=batch_size,
            resume=resume,
            throttle_seconds=throttle_seconds,
        )
    if dataset == "factors":
        return sync_factors(conn, date, providers=providers_for_source(source), stock_limit=limit)
    raise ValueError(f"Unknown dataset: {dataset}")


def providers_for_source(source: str):
    if source == "akshare":
        return [AkShareProvider()]
    if source == "baostock":
        return [BaoStockProvider()]
    if source == "demo":
        return [DemoProvider()]
    return [AkShareProvider(), BaoStockProvider()]
