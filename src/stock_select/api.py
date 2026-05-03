from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from .agent_runtime import run_phase
from .db import connect, init_db
from .blindspot_review import run_blindspot_review
from .scheduler import get_scheduler_status, start_scheduler, stop_scheduler
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
from .evidence_sync import (
    sync_analyst_expectations,
    sync_business_kpi_actuals,
    sync_earnings_surprises,
    sync_evidence,
    sync_financial_actuals,
    sync_order_contract_events,
    sync_risk_events,
)
from .evidence_views import evidence_status as evidence_status_payload, stock_evidence
from .evolution import evolution_comparison, promote_challenger, propose_strategy_evolution, rollback_evolution, promotion_eligibility_detail, gene_performance, parameter_diff
from .factor_views import factor_status, sector_factors, stock_factors
from .gene_review import get_preopen_strategy_review, list_preopen_strategy_reviews, review_gene
from .graph import query_graph
from .llm_config import DEEPSEEK_MODELS, get_model_override, resolve_llm_config, set_model_override
from .memory import search_memory, search_documents
from .news_providers import query_documents, search_documents_fts
from .optimization_signals import list_optimization_signals, signal_detail
from .repository import latest_trading_date, review_rows_for_date, rows_to_dicts
from .review_analysts import get_analyst_reviews_for_date
from .review_packets import stock_review, stock_review_history
from .review_summary import generate_review_summary
from .runtime import resolve_runtime
from .simulator import summarize_performance
from .strategies import seed_default_genes
from .system_review import review_summary
from .task_monitor import get_recent_runs, get_daily_report, get_error_summary, get_phase_summary
from .data_health import check_source_health, get_coverage, generate_health_report, get_missing_dates
from .stock_views import search_stocks
from .market_overview import get_market_overview, generate_market_overview
from .sentiment_cycle import get_sentiment_cycle, generate_sentiment_cycle
from .sector_analysis import get_top_sectors, analyze_all_sectors, save_sector_analysis
from .custom_sector import get_custom_sectors_for_stock, classify_all_custom_sectors, save_custom_sectors
from .stock_quant import build_stock_quant_report
from .psychology_review import get_psychology_review, build_psychology_review, save_psychology_review
from .next_day_plan import get_next_day_plan, build_next_day_plan, save_next_day_plan

import logging as _logging
_llm_logger = _logging.getLogger(__name__)


def _llm_post_with_retry(url: str, headers: dict, json_body: dict, timeout: int = 30, max_retries: int = 2) -> dict | None:
    """POST to LLM API with exponential backoff retry on transient errors."""
    import httpx
    import time
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            resp = httpx.post(url, headers=headers, json=json_body, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                wait = 2 ** attempt * 3  # 3s, 6s
                _llm_logger.warning("LLM API call failed (attempt %d/%d): %s, retrying in %ds", attempt + 1, max_retries + 1, e, wait)
                time.sleep(wait)
    _llm_logger.error("LLM API call failed after %d retries: %s", max_retries, last_err)
    return None

try:  # pragma: no cover - FastAPI is optional in the local test environment.
    from fastapi import FastAPI, Query
    from fastapi.middleware.cors import CORSMiddleware
except Exception:  # pragma: no cover
    FastAPI = None  # type: ignore[assignment]
    Query = None  # type: ignore[assignment]
    CORSMiddleware = None  # type: ignore[assignment]


from .db import _DEFAULT_DB as _DEFAULT_DB_PATH
DB_PATH = _DEFAULT_DB_PATH


def _to_dict(obj: Any) -> dict[str, Any]:
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
    if isinstance(obj, dict):
        return obj
    return {}


def _load_market_context(conn, trading_date: str, result: dict) -> None:
    """Load market overview and sentiment cycle, generating if not available."""
    try:
        from .market_overview import get_market_overview, generate_market_overview
        overview = get_market_overview(conn, trading_date)
        if overview is None:
            overview = generate_market_overview(conn, trading_date)
        if overview:
            from .market_overview import MarketOverview
            result["market_overview"] = _to_dict(overview)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Failed to load market context for %s: %s", trading_date, e)

    try:
        from .sentiment_cycle import get_sentiment_cycle, generate_sentiment_cycle
        cycle = get_sentiment_cycle(conn, trading_date)
        if cycle is None:
            cycle = generate_sentiment_cycle(conn, trading_date)
        if cycle:
            result["sentiment_cycle"] = _to_dict(cycle)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Failed to load sentiment cycle for %s: %s", trading_date, e)


def _load_sector_quant(conn, stock_code: str, trading_date: str, result: dict) -> None:
    """Load sector analysis and quantitative factors for a stock."""
    try:
        from .sector_analysis import get_sector_analysis, get_stock_sector_performance
        sectors = get_sector_analysis(conn, trading_date)
        if sectors:
            result["sector_analysis"] = sectors
        stock_sector = get_stock_sector_performance(conn, stock_code, trading_date)
        if stock_sector:
            result["stock_sector"] = stock_sector
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Failed to load sector data for %s: %s", stock_code, e)

    try:
        from .stock_quant import build_stock_quant_report
        quant = build_stock_quant_report(conn, stock_code, trading_date)
        if quant:
            result["stock_quant"] = quant
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Failed to load quant data for %s: %s", stock_code, e)

    try:
        from .stock_quant import get_capital_flow_summary
        capital = get_capital_flow_summary(conn, stock_code, trading_date)
        if capital:
            result["capital_flow"] = capital
    except Exception:
        pass


def create_app(db_path: str | Path | None = None, mode: str = "demo"):
    if FastAPI is None:  # pragma: no cover
        raise RuntimeError("FastAPI is not installed. Install with: pip install -e '.[api]'")

    runtime = resolve_runtime(mode, db_path)
    app = FastAPI(title="Stock Select", version="0.1.0")

    # Global broadcast manager for WebSocket alerts
    class _BroadcastManagerHolder:
        from .alert_service import BroadcastManager
        manager = BroadcastManager()
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

    @app.on_event("startup")
    def _startup():
        """Auto-start scheduler with the correct runtime DB on server startup."""
        import logging
        logger = logging.getLogger(__name__)
        try:
            start_scheduler(runtime.db_path)
            from .scheduler import _scheduler_instance as _sched
            if _sched:
                job_count = len(_sched.get_jobs())
                logger.info("Scheduler auto-started with %d jobs (db=%s)", job_count, runtime.db_path)
                print(f"Scheduler auto-started with {job_count} jobs")
        except Exception as e:
            logger.warning("Scheduler auto-start failed: %s", e)
            print(f"Scheduler auto-start failed: {e}")

    @app.get("/api/dashboard")
    def dashboard(date: str | None = None) -> dict[str, Any]:
        conn = db()
        try:
            current_date = date or latest_trading_date(conn)
            if not current_date:
                return runtime.as_payload() | {"date": None, "picks": [], "performance": [], "runs": []}
            quality_summary = data_quality_summary(conn, current_date)
            market = quality_summary.get("market_environment") or {}
            evidence_summary = evidence_status_payload(conn, current_date)
            llm_status = llm_status_payload(conn, current_date)
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
                "evidence_status": evidence_summary,
                "llm_status": llm_status,
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

    @app.get("/api/evidence/status")
    def evidence_status_endpoint(date: str) -> dict[str, Any]:
        conn = db()
        try:
            return evidence_status_payload(conn, date)
        finally:
            conn.close()

    @app.get("/api/evidence/stocks/{stock_code}")
    def stock_evidence_endpoint(stock_code: str, date: str) -> dict[str, Any]:
        conn = db()
        try:
            return stock_evidence(conn, stock_code, date)
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

    @app.get("/api/sim-orders")
    def sim_orders(date: str, status: str | None = None) -> list[dict[str, Any]]:
        """Return simulation orders for a date, including rejected/filled."""
        conn = db()
        try:
            clauses = ["o.trading_date = ?"]
            params: list[Any] = [date]
            if status:
                clauses.append("o.status = ?")
                params.append(status)
            return rows_to_dicts(
                conn.execute(
                    f"""
                    SELECT o.*, s.name AS stock_name, pd.score, pd.strategy_gene_id
                    FROM sim_orders o
                    JOIN stocks s ON s.stock_code = o.stock_code
                    JOIN pick_decisions pd ON pd.decision_id = o.decision_id
                    WHERE {' AND '.join(clauses)}
                    ORDER BY o.created_at DESC
                    """,
                    params,
                )
            )
        finally:
            conn.close()

    @app.get("/api/stocks/search")
    def stocks_search(q: str = "", limit: int = 12) -> list[dict[str, Any]]:
        conn = db()
        try:
            return search_stocks(conn, q, limit=limit)
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

    @app.post("/api/optimization-signals/{signal_id}/accept")
    def accept_optimization_signal(signal_id: str) -> dict[str, Any]:
        conn = db()
        try:
            conn.execute(
                "UPDATE optimization_signals SET status = 'open' WHERE signal_id = ? AND status = 'candidate'",
                (signal_id,),
            )
            conn.commit()
            affected = conn.execute("SELECT changes()").fetchone()[0]
            if affected == 0:
                return {"status": "not_found_or_not_candidate"}
            return {"status": "accepted"}
        finally:
            conn.close()

    @app.post("/api/optimization-signals/{signal_id}/reject")
    def reject_optimization_signal(signal_id: str) -> dict[str, Any]:
        conn = db()
        try:
            conn.execute(
                "UPDATE optimization_signals SET status = 'rejected' WHERE signal_id = ? AND status = 'candidate'",
                (signal_id,),
            )
            conn.commit()
            affected = conn.execute("SELECT changes()").fetchone()[0]
            if affected == 0:
                return {"status": "not_found_or_not_candidate"}
            return {"status": "rejected"}
        finally:
            conn.close()

    @app.get("/api/optimization-signals/{signal_id}/detail")
    def optimization_signal_detail(signal_id: str) -> dict[str, Any] | None:
        conn = db()
        try:
            return signal_detail(conn, signal_id)
        finally:
            conn.close()

    @app.post("/api/evolution/propose")
    def propose_evolution(
        start: str,
        end: str,
        gene_id: str | None = None,
        dry_run: bool = False,
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
                dry_run=dry_run,
            )
        finally:
            conn.close()

    @app.get("/api/evolution/comparison")
    def comparison(gene_id: str | None = None, start: str | None = None, end: str | None = None) -> dict[str, Any]:
        conn = db()
        try:
            return evolution_comparison(conn, gene_id=gene_id, start=start, end=end)
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

    @app.get("/api/evolution/promotion-eligibility")
    def promotion_eligibility(child_gene_id: str, start: str | None = None, end: str | None = None) -> dict[str, Any]:
        conn = db()
        try:
            event = conn.execute(
                "SELECT period_start, period_end FROM strategy_evolution_events WHERE child_gene_id = ? AND event_type = 'proposal' ORDER BY created_at DESC LIMIT 1",
                (child_gene_id,),
            ).fetchone()
            p_start = start or (event["period_start"] if event else "")
            p_end = end or (event["period_end"] if event else "")
            return promotion_eligibility_detail(conn, child_gene_id, p_start, p_end)
        finally:
            conn.close()

    @app.get("/api/evolution/rollback-audit")
    def rollback_audit(gene_id: str | None = None) -> list[dict[str, Any]]:
        """S6.5: Return rollback events with full audit details."""
        conn = db()
        try:
            clauses = ["event_type = 'rollback'"]
            params: list[Any] = []
            if gene_id:
                clauses.append("(parent_gene_id = ? OR child_gene_id = ?)")
                params.extend([gene_id, gene_id])
            rows = conn.execute(
                f"""
                SELECT * FROM strategy_evolution_events
                WHERE {' AND '.join(clauses)}
                ORDER BY created_at DESC
                """,
                params,
            ).fetchall()
            results: list[dict[str, Any]] = []
            for row in rows:
                rationale = json.loads(row["rationale_json"] or "{}")
                before_params = json.loads(row["before_params_json"] or "{}")
                after_params = json.loads(row["after_params_json"] or "{}")
                parent_perf = gene_performance(conn, row["parent_gene_id"], row["period_start"], row["period_end"])
                child_perf = gene_performance(conn, row["child_gene_id"], row["period_start"], row["period_end"]) if row["child_gene_id"] else None
                results.append({
                    "event_id": row["event_id"],
                    "parent_gene_id": row["parent_gene_id"],
                    "child_gene_id": row["child_gene_id"],
                    "period_start": row["period_start"],
                    "period_end": row["period_end"],
                    "rolled_back_at": row.get("rolled_back_at"),
                    "created_at": row.get("created_at"),
                    "reason": rationale.get("reason", "unknown"),
                    "parent_performance": parent_perf,
                    "child_performance": child_perf,
                    "parameter_diff": parameter_diff(before_params, after_params),
                })
            return results
        finally:
            conn.close()

    @app.get("/api/genes/environment-performance")
    def environment_performance(limit: int = 50, gene_id: str | None = None) -> dict[str, Any]:
        conn = db()
        try:
            where = ""
            params: tuple = ()
            if gene_id:
                where = "WHERE gene_id = ?"
                params = (gene_id,)
            rows = conn.execute(
                f"""
                SELECT gene_id, market_environment, period_start, period_end,
                       trade_count, win_rate, avg_return, max_drawdown, alpha
                FROM gene_environment_performance
                {where}
                ORDER BY period_end DESC, gene_id, market_environment
                LIMIT ?
                """,
                (*params, limit),
            )
            return {"items": rows_to_dicts(rows)}
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
            return run_phase(conn, phase, date, runtime_mode=runtime.mode)
        finally:
            conn.close()

    @app.get("/api/reviews")
    def reviews(date: str) -> list[dict[str, Any]]:
        conn = db()
        try:
            return review_rows_for_date(conn, date)
        finally:
            conn.close()

    @app.get("/api/reviews/stocks/{stock_code}")
    def stock_review_endpoint(stock_code: str, date: str, gene_id: str | None = None) -> dict[str, Any]:
        session_id = f"review_{stock_code}_{date}_{uuid.uuid4().hex[:8]}"
        from .step_logger import clear_session, init_session, log_step
        init_session(session_id)

        try:
            log_step(session_id, f"开始复盘 {stock_code}（{date}）", "初始化数据连接")
            conn = db()
            log_step(session_id, "检查策略决策记录", f"查询 gene_id={gene_id or 'all'}")
            try:
                result = stock_review(conn, stock_code, date, gene_id)
                # Log hypothetical review for history tracking
                if result.get("hypothetical"):
                    log_step(session_id, "触发假设性复盘", "无策略决策记录，启动多维度实时分析")
                    conn.execute(
                        "INSERT OR IGNORE INTO hypothetical_review_log (stock_code, trading_date) VALUES (?, ?)",
                        (stock_code, date),
                    )
                    conn.commit()
                log_step(session_id, "生成摘要总结", "汇总各维度分析结论")
                result["review_summary"] = generate_review_summary(conn, stock_code, date, gene_id)
                log_step(session_id, "加载相关新闻与公告", f"查询 {stock_code} 关联文档")
                related_docs = query_documents(conn, stock_code=stock_code, date=date, limit=20)
                result["related_documents"] = related_docs
                log_step(session_id, "加载市场环境与情绪周期",
                         "查询市场概览、涨跌家数、情绪周期阶段",
                         request_data={"trading_date": date})
                _attach_market_context(conn, result, date)
                market_data = result.get("market_overview")
                sentiment_data = result.get("sentiment_cycle")
                market_resp = {}
                if market_data:
                    market_resp = {k: market_data[k] for k in market_data if k in (
                        "index_code", "index_name", "close_pct", "up_count", "down_count",
                        "flat_count", "limit_up_count", "limit_down_count", "total_amount",
                        "market_summary", "sh_return", "sz_return", "cyb_return", "bse_return",
                        "advance_count", "decline_count")}
                sentiment_resp = {}
                if sentiment_data:
                    sentiment_resp = {k: sentiment_data[k] for k in sentiment_data if k in (
                        "phase", "phase_name", "up_limit_ratio", "down_limit_ratio",
                        "consecutive_up_days", "consecutive_down_days", "yesterday_limit_up_premium",
                        "summary")}
                log_step(session_id, "市场环境加载完成",
                         f"市场概览: {'有' if market_resp else '无'}, 情绪周期: {'有' if sentiment_resp else '无'}",
                         completed=True,
                         response_data={**market_resp, **sentiment_resp} if (market_resp or sentiment_resp) else {"status": "无数据"})
                log_step(session_id, "加载行业分析与量化因子",
                         "查询行业板块、连板形态、均线量价、资金流向",
                         request_data={"stock_code": stock_code})
                _attach_stock_deep_review(conn, result, stock_code, date)
                sector_resp = {}
                sector_data = result.get("sector_analysis")
                if sector_data:
                    top = sector_data.get("top_sectors", [])[:3]
                    sector_resp["top_sectors"] = [
                        {k: s.get(k) for k in ("sector_name", "sector_code", "return_pct", "limit_up_count", "team_complete")}
                        for s in top
                    ]
                stock_quant_data = result.get("stock_quant")
                if stock_quant_data:
                    stock_quant_resp = {
                        "moving_average": stock_quant_data.get("moving_average"),
                        "volume_analysis": stock_quant_data.get("volume_analysis"),
                        "limit_up_chain": stock_quant_data.get("limit_up_chain"),
                    }
                else:
                    stock_quant_resp = {"status": "无数据"}
                capital_data = result.get("capital_flow")
                capital_resp = {}
                if capital_data:
                    capital_resp = {k: capital_data[k] for k in capital_data if k in (
                        "main_net_inflow", "super_large_net", "large_net", "medium_net",
                        "small_net", "flow_direction", "summary")}
                psychology_data = result.get("psychology_review")
                psychology_resp = {}
                if psychology_data:
                    psychology_resp = {k: psychology_data[k] for k in psychology_data if k in (
                        "verdict", "scenario", "plan", "summary")}
                log_step(session_id, "行业量化加载完成",
                         ", ".join(f"{k}: {'有' if v and v.get('status') != '无数据' else '无'}"
                                   for k, v in [("sector", sector_resp), ("quant", stock_quant_resp),
                                                ("capital", capital_resp), ("psychology", psychology_resp)]),
                         completed=True,
                         response_data={
                             "sector_analysis": sector_resp,
                             "stock_quant": stock_quant_resp,
                             "capital_flow": capital_resp,
                             "psychology_review": psychology_resp,
                         })
                log_step(session_id, "生成 AI 解读", "调用大模型生成自然语言总结")
                result["ai_summary"] = _generate_ai_summary(conn, result, stock_code, date)
                log_step(session_id, "复盘完成", f"返回 {len(result)} 个字段", completed=True)
                result["_session_id"] = session_id
                return result
            finally:
                conn.close()
        except Exception as e:
            log_step(session_id, f"复盘出错: {e}", str(e), completed=True)
            raise

    def _attach_market_context(
        conn, result: dict[str, Any], trading_date: str
    ) -> None:
        """Attach market overview and sentiment cycle to review result."""
        overview = get_market_overview(conn, trading_date)
        if overview is None:
            overview = generate_market_overview(conn, trading_date)
        result["market_overview"] = {
            "trading_date": overview.trading_date,
            "sh_return": overview.sh_return,
            "sz_return": overview.sz_return,
            "cyb_return": overview.cyb_return,
            "bse_return": overview.bse_return,
            "advance_count": overview.advance_count,
            "decline_count": overview.decline_count,
            "limit_up_count": overview.limit_up_count,
            "limit_down_count": overview.limit_down_count,
            "style_preference": overview.style_preference,
            "top_volume_stocks": [
                {"stock_code": s.stock_code, "stock_name": s.stock_name, "value": s.value}
                for s in overview.top_volume_stocks
            ],
            "top_amount_stocks": [
                {"stock_code": s.stock_code, "stock_name": s.stock_name, "value": s.value}
                for s in overview.top_amount_stocks
            ],
            "main_sectors": [
                {"sector_name": s.sector_name, "return_pct": s.return_pct}
                for s in overview.main_sectors
            ],
        }

        sentiment = get_sentiment_cycle(conn, trading_date)
        if sentiment is None:
            sentiment = generate_sentiment_cycle(conn, trading_date)
        result["sentiment_cycle"] = {
            "trading_date": sentiment.trading_date,
            "advance_count": sentiment.advance_count,
            "decline_count": sentiment.decline_count,
            "limit_up_count": sentiment.limit_up_count,
            "limit_down_count": sentiment.limit_down_count,
            "seal_rate": sentiment.seal_rate,
            "promotion_rate": sentiment.promotion_rate,
            "cycle_phase": sentiment.cycle_phase,
            "cycle_reason": sentiment.cycle_reason,
            "composite_sentiment": sentiment.composite_sentiment,
            "news_heat": sentiment.news_heat,
        }

    def _attach_stock_deep_review(
        conn, result: dict[str, Any], stock_code: str, trading_date: str
    ) -> None:
        """Attach sector analysis, custom sectors, stock quant, psychology, and next-day plan."""
        # Custom sector tags
        sector_tags = get_custom_sectors_for_stock(conn, trading_date, stock_code)
        result["custom_sector_tags"] = sector_tags

        # Sector analysis for stock's industry
        row = conn.execute(
            "SELECT industry FROM stocks WHERE stock_code = ?", (stock_code,)
        ).fetchone()
        if row and row["industry"]:
            from .sector_analysis import get_sector_analysis
            sector = get_sector_analysis(conn, trading_date, row["industry"])
            if sector is None:
                from .sector_analysis import analyze_sector, save_sector_analysis
                sector = analyze_sector(conn, trading_date, row["industry"])
                save_sector_analysis(conn, sector)
            result["sector_analysis"] = {
                "sector_name": sector.sector_name,
                "sector_return_pct": sector.sector_return_pct,
                "strength_1d": sector.strength_1d,
                "strength_3d": sector.strength_3d,
                "strength_10d": sector.strength_10d,
                "stock_count": sector.stock_count,
                "advance_ratio": sector.advance_ratio,
                "leader_stock": sector.leader_stock,
                "leader_return_pct": sector.leader_return_pct,
                "team_complete": sector.team_complete,
                "sustainability": sector.sustainability,
                "limit_up_3d_count": sector.limit_up_3d_count,
            }

        # Stock quant report
        quant = build_stock_quant_report(conn, stock_code, trading_date)
        if quant:
            result["stock_quant"] = {
                "volume_analysis": {
                    "today_volume": quant.volume_analysis.today_volume if quant.volume_analysis else None,
                    "avg_volume_5d": quant.volume_analysis.avg_volume_5d if quant.volume_analysis else None,
                    "volume_ratio_5d": quant.volume_analysis.volume_ratio_5d if quant.volume_analysis else None,
                    "trend": quant.volume_analysis.trend if quant.volume_analysis else None,
                },
                "moving_average": {
                    "ma5": quant.moving_average.ma5 if quant.moving_average else None,
                    "ma10": quant.moving_average.ma10 if quant.moving_average else None,
                    "ma20": quant.moving_average.ma20 if quant.moving_average else None,
                    "close": quant.moving_average.close if quant.moving_average else None,
                    "position_vs_ma5": quant.moving_average.position_vs_ma5 if quant.moving_average else None,
                    "trend": quant.moving_average.trend if quant.moving_average else None,
                },
                "limit_up_chain": {
                    "current_days": quant.limit_up_chain.current_days if quant.limit_up_chain else None,
                    "is_limit_up_today": quant.limit_up_chain.is_limit_up_today if quant.limit_up_chain else None,
                },
                "leader_comparison": {
                    "leader_code": quant.leader_comparison.leader_code if quant.leader_comparison else None,
                    "leader_return_pct": quant.leader_comparison.leader_return_pct if quant.leader_comparison else None,
                    "return_gap": quant.leader_comparison.return_gap if quant.leader_comparison else None,
                },
            }

        # Psychology review and next-day plan (attach to first decision if exists)
        # Skip hypothetical reviews (review_id not in decision_reviews table)
        decisions = result.get("decisions", [])
        if decisions:
            first_decision = decisions[0]
            review_id = first_decision.get("review_id")
            if review_id and not review_id.startswith("hypo_"):
                psych = get_psychology_review(conn, review_id)
                if psych is None:
                    psych = build_psychology_review(conn, review_id)
                    save_psychology_review(conn, psych)
                result["psychology_review"] = {
                    "psychological_category": psych.psychological_category,
                    "success_reasons": psych.success_reasons,
                    "failure_reasons": psych.failure_reasons,
                    "reproducible_patterns": psych.reproducible_patterns,
                    "prevention_strategies": psych.prevention_strategies,
                }

                plan = get_next_day_plan(conn, review_id)
                if plan is None:
                    plan = build_next_day_plan(conn, review_id)
                    if plan:
                        save_next_day_plan(conn, plan)
                if plan:
                    result["next_day_plan"] = {
                        "scenarios": [
                            {"condition": s.condition, "action": s.action, "trigger": s.trigger}
                            for s in plan.scenarios
                        ],
                        "key_levels": plan.key_levels,
                    }

    def _generate_ai_summary(
        conn, result: dict[str, Any], stock_code: str, trading_date: str
    ) -> str | None:
        """用 LLM 生成自然语言复盘总结，帮助用户理解采集到的数据。"""
        try:
            from .llm_config import resolve_llm_config
            config = resolve_llm_config()
            if config is None:
                return None

            decisions = result.get("decisions", [])
            is_hypo = result.get("hypothetical")
            verdict = decisions[0].get("verdict", "") if decisions else ""
            driver = decisions[0].get("primary_driver", "") if decisions else ""
            factor_items = decisions[0].get("factor_items", []) if decisions else []
            factor_summary = []
            for f in factor_items[:8]:
                factor_summary.append(f"- {f.get('factor_type', '')}: {f.get('verdict', '')}（{f.get('contribution_score', 0):.2f}）")

            market = result.get("market_overview", {})
            sentiment = result.get("sentiment_cycle", {})

            prompt = (
                f"你是一位资深 A 股分析师。请根据以下数据，用通俗易懂的中文，"
                f"用 3-5 段话总结 {stock_code} 在 {trading_date} 的复盘情况。\n"
                f"{'这是一个假设性复盘，该股票未被策略选中。' if is_hypo else ''}\n"
                f"综合结论：{verdict}\n"
                f"主要驱动因素：{driver}\n"
                f"因子检查：\n{'\n'.join(factor_summary)}\n"
                f"市场环境：{market.get('style_preference', 'unknown')}, "
                f"涨{market.get('advance_count', 0)}跌{market.get('decline_count', 0)}\n"
                f"情绪周期：{sentiment.get('cycle_phase', 'unknown')}\n"
                f"请直接输出总结文字，不要使用 JSON 格式。"
            )

            if config.provider == "deepseek":
                model = config.model if hasattr(config, 'model') else "deepseek-chat"
                data = _llm_post_with_retry(
                    "https://api.deepseek.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"},
                    json={"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 500},
                )
                if data is None:
                    return None
                return data.get("choices", [{}])[0].get("message", {}).get("content", "").strip() or None
            elif config.provider == "anthropic":
                base_url = config.base_url or "https://api.anthropic.com"
                data = _llm_post_with_retry(
                    f"{base_url}/v1/messages",
                    headers={"x-api-key": config.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                    json={"model": config.model, "max_tokens": 500, "messages": [{"role": "user", "content": prompt}]},
                )
                if data is None:
                    return None
                return data.get("content", [{}])[0].get("text", "").strip() or None
            elif config.provider == "openai":
                base_url = config.base_url or "https://api.openai.com/v1"
                data = _llm_post_with_retry(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"},
                    json={"model": config.model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 500},
                )
                if data is None:
                    return None
                return data.get("choices", [{}])[0].get("message", {}).get("content", "").strip() or None
        except Exception:
            return None
        return None

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

    @app.get("/api/reviews/history/hypothetical")
    def hypothetical_review_history_endpoint(limit: int = 20) -> dict[str, Any]:
        conn = db()
        try:
            rows = conn.execute(
                "SELECT stock_code, trading_date, reviewed_at FROM hypothetical_review_log ORDER BY reviewed_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return {"reviews": [dict(r) for r in rows]}
        finally:
            conn.close()

    @app.get("/api/reviews/history/strategy-picks")
    def strategy_picks_history_endpoint(date: str = "", limit: int = 20) -> dict[str, Any]:
        conn = db()
        try:
            clauses = []
            params: list[Any] = []
            if date:
                clauses.append("trading_date = ?")
                params.append(date)
            clauses.append("1=1")
            where = " AND ".join(clauses)
            rows = conn.execute(
                f"""
                SELECT DISTINCT d.stock_code, d.trading_date, d.strategy_gene_id, d.action, d.confidence,
                       s.name as stock_name, s.industry
                FROM pick_decisions d
                LEFT JOIN stocks s ON s.stock_code = d.stock_code
                WHERE {where}
                ORDER BY d.trading_date DESC, d.stock_code
                LIMIT ?
                """,
                [*params, limit],
            ).fetchall()
            return {"picks": [dict(r) for r in rows]}
        finally:
            conn.close()

    @app.get("/api/reviews/steps/{session_id}")
    def review_steps_endpoint(session_id: str) -> dict[str, Any]:
        from .step_logger import get_session_steps
        return {"steps": get_session_steps(session_id)}

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

    @app.get("/api/reviews/llm")
    def list_llm_reviews(date: str) -> list[dict[str, Any]]:
        conn = db()
        try:
            rows = conn.execute(
                """SELECT l.*, s.prompt_tokens, s.completion_tokens, s.estimated_cost
                   FROM llm_reviews l
                   LEFT JOIN llm_scratchpad s ON l.llm_review_id = s.llm_review_id
                   WHERE l.trading_date = ?
                   ORDER BY l.created_at DESC""",
                (date,),
            ).fetchall()
            result = []
            for r in rows:
                row_dict = dict(r)
                result.append(row_dict)
            return result
        finally:
            conn.close()

    @app.get("/api/reviews/llm/cost-summary")
    def llm_cost_summary(date: str | None = None) -> dict[str, Any]:
        """S6.3: Token cost summary for LLM reviews."""
        conn = db()
        try:
            where = ""
            params: list[Any] = []
            if date:
                where = "WHERE s.created_at LIKE ?"
                params.append(f"{date}%")
            row = conn.execute(
                f"""
                SELECT
                  COUNT(*) AS total_calls,
                  SUM(CASE WHEN s.status = 'ok' THEN 1 ELSE 0 END) AS successful,
                  SUM(CASE WHEN s.status = 'error' THEN 1 ELSE 0 END) AS failed,
                  COALESCE(SUM(s.prompt_tokens), 0) AS total_prompt_tokens,
                  COALESCE(SUM(s.completion_tokens), 0) AS total_completion_tokens,
                  COALESCE(SUM(s.estimated_cost), 0) AS total_cost,
                  COALESCE(AVG(s.latency_ms), 0) AS avg_latency_ms,
                  s.model, s.provider
                FROM llm_scratchpad s
                {where}
                GROUP BY s.model, s.provider
                """,
                params,
            ).fetchall()
            return {
                "by_model": [
                    {
                        "model": r["model"],
                        "provider": r["provider"],
                        "total_calls": r["total_calls"],
                        "successful": r["successful"],
                        "failed": r["failed"],
                        "total_prompt_tokens": r["total_prompt_tokens"],
                        "total_completion_tokens": r["total_completion_tokens"],
                        "total_cost": round(r["total_cost"], 6),
                        "avg_latency_ms": round(r["avg_latency_ms"], 0),
                    }
                    for r in row
                ],
            }
        finally:
            conn.close()

    @app.post("/api/reviews/llm/rerun")
    def rerun_llm_review(date: str) -> dict[str, Any]:
        conn = db()
        try:
            from .llm_review import run_llm_review
            return run_llm_review(conn, date)
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

    @app.get("/api/graph/stocks/{stock_code}/neighborhood")
    def graph_neighborhood(stock_code: str, date: str | None = None) -> dict[str, Any]:
        """S4.5: Graph neighborhood for a stock - evidence, errors, signals, related documents."""
        conn = db()
        try:
            stock_node_id = f"stock:{stock_code}"
            # Evidence nodes about this stock
            evidence = conn.execute(
                """
                SELECT * FROM graph_nodes WHERE node_type = 'ReviewEvidence'
                AND EXISTS (
                    SELECT 1 FROM graph_edges e
                    WHERE e.target_node_id = ? AND e.source_node_id = graph_nodes.node_id
                )
                ORDER BY created_at DESC LIMIT 50
                """,
                (stock_node_id,),
            ).fetchall()
            # Error nodes
            errors = conn.execute(
                """
                SELECT * FROM graph_nodes WHERE node_type = 'ReviewError'
                AND EXISTS (
                    SELECT 1 FROM decision_reviews dr
                    JOIN graph_edges e1 ON e1.source_node_id = 'review:' || dr.review_id
                    JOIN graph_edges e2 ON e2.target_node_id = graph_nodes.node_id
                    WHERE dr.stock_code = ?
                )
                ORDER BY created_at DESC LIMIT 50
                """,
                (stock_code,),
            ).fetchall()
            # Signal nodes
            signals = conn.execute(
                """
                SELECT * FROM graph_nodes WHERE node_type = 'OptimizationSignal'
                AND EXISTS (
                    SELECT 1 FROM graph_edges e
                    WHERE e.target_node_id = (
                        SELECT 'gene:' || strategy_gene_id FROM pick_decisions WHERE stock_code = ? LIMIT 1
                    )
                    AND e.source_node_id = graph_nodes.node_id
                )
                ORDER BY created_at DESC LIMIT 50
                """,
                (stock_code,),
            ).fetchall()
            # Related documents
            documents = conn.execute(
                """
                SELECT r.* FROM raw_documents r
                JOIN document_stock_links dsl ON r.document_id = dsl.document_id
                WHERE dsl.stock_code = ?
                ORDER BY r.published_at DESC LIMIT 20
                """,
                (stock_code,),
            ).fetchall()
            return {
                "stock_code": stock_code,
                "evidence": [dict(e) for e in evidence],
                "errors": [dict(e) for e in errors],
                "signals": [dict(e) for e in signals],
                "documents": [dict(d) for d in documents],
            }
        finally:
            conn.close()

    @app.get("/api/graph/similar-cases")
    def similar_cases(stock_code: str | None = None, error_type: str | None = None, limit: int = 10) -> dict[str, Any]:
        """S4.5: Find similar cases by stock, error type."""
        conn = db()
        try:
            from .similar_cases import find_similar_cases, query_similar_by_error
            if error_type:
                cases = query_similar_by_error(conn, error_type=error_type, limit=limit)
            else:
                cases = []
                if stock_code:
                    industry = conn.execute(
                        "SELECT industry FROM stocks WHERE stock_code = ?", (stock_code,)
                    ).fetchone()
                    cases = find_similar_cases(conn, industry=industry["industry"] if industry else None, limit=limit)
            return {"stock_code": stock_code, "cases": cases}
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

    @app.get("/api/system/status")
    def system_status(date: str | None = None) -> dict[str, Any]:
        conn = db()
        try:
            target_date = date or latest_trading_date(conn)
            report = generate_health_report(conn)

            price_ok = report.coverage_today is not None if target_date else False
            factor_rows = conn.execute(
                "SELECT COUNT(*) FROM fundamental_metrics WHERE as_of_date = ?",
                (target_date,) if target_date else (None,),
            ).fetchone()[0] if target_date else 0
            evidence_rows = conn.execute(
                "SELECT COUNT(*) FROM review_evidence WHERE trading_date = ?",
                (target_date,) if target_date else (None,),
            ).fetchone()[0] if target_date else 0
            llm_status = llm_status_payload(conn, target_date)

            latest_run = conn.execute(
                "SELECT phase, status FROM research_runs ORDER BY started_at DESC LIMIT 1"
            ).fetchone()

            return {
                "date": target_date,
                **runtime.as_payload(),
                "price_data": {
                    "healthy": price_ok,
                    "coverage_date": report.coverage_today.trading_date if report.coverage_today else None,
                    "staleness_hours": report.coverage_today.staleness_hours if report.coverage_today else None,
                },
                "factors": {
                    "healthy": factor_rows > 0,
                    "row_count": factor_rows,
                },
                "evidence": {
                    "healthy": evidence_rows > 0,
                    "row_count": evidence_rows,
                },
                "llm": llm_status,
                "pipeline": {
                    "last_phase": latest_run["phase"] if latest_run else None,
                    "last_status": latest_run["status"] if latest_run else None,
                    "stale_sources": report.stale_sources,
                    "error_count": report.error_count,
                },
                "today_available": price_ok and factor_rows > 0,
            }
        finally:
            conn.close()

    @app.get("/api/scheduler/status")
    def scheduler_status() -> dict[str, Any]:
        return get_scheduler_status()

    @app.post("/api/scheduler/start")
    def scheduler_start() -> dict[str, Any]:
        try:
            start_scheduler(runtime.db_path)
            return {"status": "ok", "message": "Scheduler started"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @app.post("/api/scheduler/stop")
    def scheduler_stop() -> dict[str, Any]:
        stop_scheduler()
        return {"status": "ok", "message": "Scheduler stopped"}

    @app.get("/api/config")
    def get_config() -> dict[str, Any]:
        config = resolve_llm_config()
        if not config:
            return {"provider": None, "model": None, "available_models": []}
        models = [
            {"key": k, "model": v["model"], "label": v["label"]}
            for k, v in DEEPSEEK_MODELS.items()
        ] if config.provider == "deepseek" else [
            {"key": config.model, "model": config.model, "label": config.model}
        ]
        return {
            "provider": config.provider,
            "model": config.model,
            "override": get_model_override(),
            "available_models": models,
        }

    @app.post("/api/config/model")
    def set_config_model(body: dict[str, Any]) -> dict[str, Any]:
        model = body.get("model", "")
        if not model:
            return {"error": "model required"}
        set_model_override(model)
        return {"status": "ok", "model": model}

    @app.get("/api/reviews/analysts")
    def analyst_reviews(date: str | None = None) -> dict[str, Any]:
        conn = db()
        try:
            if not date:
                date = latest_trading_date(conn)
            if not date:
                return {"date": None, "reviews": []}
            return get_analyst_reviews_for_date(conn, date)
        finally:
            conn.close()

    @app.get("/api/candidates")
    def candidates_list(
        date: str | None = None,
        gene_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        conn = db()
        try:
            target_date = date or latest_trading_date(conn)
            if not target_date:
                return {"date": None, "items": [], "total": 0, "limit": limit, "offset": offset}

            where = ["c.trading_date = ?"]
            params: list[Any] = [target_date]
            if gene_id:
                where.append("c.strategy_gene_id = ?")
                params.append(gene_id)

            query = f"""
                SELECT c.*, s.name AS stock_name, s.industry
                FROM candidate_scores c
                JOIN stocks s ON s.stock_code = c.stock_code
                WHERE {' AND '.join(where)}
                ORDER BY c.total_score DESC
                LIMIT ? OFFSET ?
            """
            params.extend([limit, offset])
            items = rows_to_dicts(conn.execute(query, params))

            count_query = f"""
                SELECT COUNT(*) FROM candidate_scores c
                JOIN stocks s ON s.stock_code = c.stock_code
                WHERE {' AND '.join(where)}
            """
            total = conn.execute(count_query, params[:-2]).fetchone()[0]

            return {"date": target_date, "items": items, "total": total, "limit": limit, "offset": offset}
        finally:
            conn.close()

    @app.get("/api/candidates/{candidate_id}")
    def candidate_detail(candidate_id: str) -> dict[str, Any]:
        conn = db()
        try:
            row = conn.execute(
                """
                SELECT c.*, s.name AS stock_name, s.industry
                FROM candidate_scores c
                JOIN stocks s ON s.stock_code = c.stock_code
                WHERE c.candidate_id = ?
                """,
                (candidate_id,),
            ).fetchone()
            if row is None:
                return {"error": "candidate not found"}
            return rows_to_dicts([row])[0]
        finally:
            conn.close()

    @app.get("/api/knowledge/documents")
    def knowledge_documents(
        query: str | None = None,
        date: str | None = None,
        stock_code: str | None = None,
        source_type: str | None = None,
        limit: int = 50,
    ):
        conn = db()
        try:
            if query:
                results = search_documents(
                    conn,
                    query=query,
                    stock_code=stock_code,
                    source_type=source_type,
                    date=date,
                    limit=limit,
                )
            else:
                results = query_documents(
                    conn,
                    date=date,
                    stock_code=stock_code,
                    source_type=source_type,
                    limit=limit,
                )
            return {"documents": results, "total": len(results)}
        finally:
            conn.close()

    @app.get("/api/knowledge/stocks/{stock_code}/documents")
    def knowledge_stock_documents(
        stock_code: str,
        date: str | None = None,
        q: str | None = None,
        limit: int = 30,
    ):
        conn = db()
        try:
            if q:
                results = search_documents(
                    conn,
                    query=q,
                    stock_code=stock_code,
                    date=date,
                    limit=limit,
                )
            else:
                results = query_documents(
                    conn,
                    date=date,
                    stock_code=stock_code,
                    limit=limit,
                )
            return {"documents": results, "total": len(results)}
        finally:
            conn.close()

    @app.get("/api/planner/plan")
    def planner_plan(date: str | None = None):
        """Get the planner plan for a given date (defaults to latest)."""
        conn = db()
        try:
            if date:
                row = conn.execute(
                    "SELECT * FROM planner_plans WHERE trading_date = ?", (date,)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM planner_plans ORDER BY trading_date DESC LIMIT 1"
                ).fetchone()
            if row is None:
                return {"plan": None}
            return {
                "plan": dict(row) | {
                    "focus_sectors": json.loads(row["focus_sectors_json"]),
                    "market_environment": json.loads(row["market_environment_json"] or "null"),
                    "high_impact_events": json.loads(row["high_impact_events_json"]),
                    "watch_risks": json.loads(row["watch_risks_json"]),
                },
            }
        finally:
            conn.close()

    @app.get("/api/planner/vs-picks")
    def planner_vs_picks(date: str | None = None):
        """Compare planner focus sectors vs actual picks for a date."""
        conn = db()
        try:
            if not date:
                date_row = conn.execute(
                    "SELECT trading_date FROM pick_decisions ORDER BY trading_date DESC LIMIT 1"
                ).fetchone()
                if not date_row:
                    return {"error": "no picks found"}
                date = date_row["trading_date"]

            plan = conn.execute(
                "SELECT * FROM planner_plans WHERE trading_date = ?", (date,)
            ).fetchone()
            focus_industries = []
            if plan:
                sectors = json.loads(plan["focus_sectors_json"])
                focus_industries = [s.get("industry") for s in sectors if s.get("industry")]

            picks = conn.execute(
                """
                SELECT pd.stock_code, pd.strategy_gene_id, pd.score, s.industry,
                       pe.verdict AS eval_verdict, pe.planner_aligned
                FROM pick_decisions pd
                JOIN stocks s ON s.stock_code = pd.stock_code
                LEFT JOIN pick_evaluations pe ON pe.decision_id = pd.decision_id
                WHERE pd.trading_date = ? AND pd.action = 'BUY'
                """,
                (date,),
            ).fetchall()

            aligned = sum(1 for p in picks if p["planner_aligned"])
            total = len(picks)

            return {
                "trading_date": date,
                "focus_industries": focus_industries,
                "picks": [dict(p) for p in picks],
                "alignment_rate": round(aligned / total, 2) if total else 0.0,
                "aligned_count": aligned,
                "total_picks": total,
            }
        finally:
            conn.close()

    @app.get("/api/evolution/challenger-performance")
    def challenger_performance(gene_id: str | None = None):
        """Get observation period performance for challenger genes."""
        conn = db()
        try:
            # Find challenger genes (status=observing or child of proposal events)
            if gene_id:
                challengers = conn.execute(
                    "SELECT * FROM strategy_genes WHERE gene_id = ?", (gene_id,)
                ).fetchall()
            else:
                challengers = conn.execute(
                    """
                    SELECT DISTINCT sg.* FROM strategy_genes sg
                    JOIN strategy_evolution_events see ON see.child_gene_id = sg.gene_id
                    WHERE see.event_type = 'proposal' AND see.status IN ('applied', 'observing')
                    """
                ).fetchall()

            results = []
            for ch in challengers:
                picks = conn.execute(
                    """
                    SELECT pd.trading_date, pd.stock_code, pd.score,
                           o.return_pct, o.max_drawdown_intraday_pct
                    FROM pick_decisions pd
                    LEFT JOIN outcomes o ON o.decision_id = pd.decision_id
                    WHERE pd.strategy_gene_id = ?
                    ORDER BY pd.trading_date DESC
                    LIMIT 20
                    """,
                    (ch["gene_id"],),
                ).fetchall()

                returns = [float(p["return_pct"]) for p in picks if p["return_pct"] is not None]
                results.append({
                    "gene_id": ch["gene_id"],
                    "name": ch["name"],
                    "status": ch["status"],
                    "trades": len(returns),
                    "avg_return_pct": round(sum(returns) / len(returns), 4) if returns else 0.0,
                    "win_rate": round(sum(1 for r in returns if r > 0) / len(returns), 2) if returns else 0.0,
                    "max_drawdown": round(min((p["max_drawdown_intraday_pct"] for p in picks if p["max_drawdown_intraday_pct"] is not None), default=0), 4),
                    "recent_picks": [dict(p) for p in picks[:5]],
                })

            return {"challengers": results, "total": len(results)}
        finally:
            conn.close()

    @app.get("/api/reviews/market-overview")
    def market_overview_endpoint(date: str) -> dict[str, Any]:
        conn = db()
        try:
            overview = get_market_overview(conn, date)
            if overview is None:
                overview = generate_market_overview(conn, date)
            return {
                "trading_date": overview.trading_date,
                "sh_return": overview.sh_return,
                "sz_return": overview.sz_return,
                "cyb_return": overview.cyb_return,
                "bse_return": overview.bse_return,
                "advance_count": overview.advance_count,
                "decline_count": overview.decline_count,
                "limit_up_count": overview.limit_up_count,
                "limit_down_count": overview.limit_down_count,
                "style_preference": overview.style_preference,
                "top_volume_stocks": [
                    {"stock_code": s.stock_code, "stock_name": s.stock_name, "value": s.value}
                    for s in overview.top_volume_stocks
                ],
                "top_amount_stocks": [
                    {"stock_code": s.stock_code, "stock_name": s.stock_name, "value": s.value}
                    for s in overview.top_amount_stocks
                ],
                "main_sectors": [
                    {"sector_name": s.sector_name, "return_pct": s.return_pct}
                    for s in overview.main_sectors
                ],
            }
        finally:
            conn.close()

    @app.get("/api/reviews/sentiment-cycle")
    def sentiment_cycle_endpoint(date: str) -> dict[str, Any]:
        conn = db()
        try:
            cycle = get_sentiment_cycle(conn, date)
            if cycle is None:
                cycle = generate_sentiment_cycle(conn, date)
            return {
                "trading_date": cycle.trading_date,
                "advance_count": cycle.advance_count,
                "decline_count": cycle.decline_count,
                "limit_up_count": cycle.limit_up_count,
                "limit_down_count": cycle.limit_down_count,
                "seal_rate": cycle.seal_rate,
                "promotion_rate": cycle.promotion_rate,
                "cycle_phase": cycle.cycle_phase,
                "cycle_reason": cycle.cycle_reason,
                "composite_sentiment": cycle.composite_sentiment,
                "news_heat": cycle.news_heat,
            }
        finally:
            conn.close()

    @app.get("/api/reviews/sectors")
    def sectors_endpoint(date: str, limit: int = 10) -> list[dict[str, Any]]:
        conn = db()
        try:
            sectors = get_top_sectors(conn, date, limit=limit)
            if not sectors:
                analyses = analyze_all_sectors(conn, date, limit=limit)
                for a in analyses:
                    save_sector_analysis(conn, a)
                sectors = analyses
            return [
                {
                    "sector_name": s.sector_name,
                    "sector_return_pct": s.sector_return_pct,
                    "strength_1d": s.strength_1d,
                    "strength_3d": s.strength_3d,
                    "strength_10d": s.strength_10d,
                    "stock_count": s.stock_count,
                    "advance_ratio": s.advance_ratio,
                    "leader_stock": s.leader_stock,
                    "leader_return_pct": s.leader_return_pct,
                    "team_complete": s.team_complete,
                    "sustainability": s.sustainability,
                    "limit_up_3d_count": s.limit_up_3d_count,
                }
                for s in sectors
            ]
        finally:
            conn.close()

    @app.get("/api/reviews/custom-sectors")
    def custom_sectors_endpoint(date: str, sector_key: str | None = None) -> dict[str, Any]:
        conn = db()
        try:
            if sector_key:
                from .custom_sector import get_custom_sector_stocks
                stocks = get_custom_sector_stocks(conn, date, sector_key)
                return {
                    "trading_date": date,
                    "sector_key": sector_key,
                    "stocks": [
                        {
                            "stock_code": s.stock_code,
                            "stock_name": s.stock_name,
                            "return_pct": s.return_pct,
                            "amount": s.amount,
                        }
                        for s in stocks
                    ],
                }
            else:
                from .custom_sector import classify_all_custom_sectors, save_custom_sectors
                sectors = classify_all_custom_sectors(conn, date)
                save_custom_sectors(conn, date, sectors)
                return {
                    "trading_date": date,
                    "sectors": [
                        {
                            "sector_key": s.sector_key,
                            "sector_name": s.sector_name,
                            "stock_count": len(s.stocks),
                            "criteria": s.criteria,
                        }
                        for s in sectors
                    ],
                }
        finally:
            conn.close()

    @app.get("/api/availability")
    def availability_endpoint(date: str | None = None) -> dict[str, Any]:
        from .data_availability import check_data_availability
        conn = db()
        try:
            current_date = date or latest_trading_date(conn)
            avail = check_data_availability(conn, current_date)
            return {
                "date": current_date,
                "status": avail.status,
                "price_coverage_pct": avail.price_coverage_pct,
                "pick_count": avail.pick_count,
                "event_source_count": avail.event_source_count,
                "review_evidence_count": avail.review_evidence_count,
                "reasons": avail.reasons,
            }
        finally:
            conn.close()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/reviews/custom-sectors/{stock_code}")
    def custom_sector_tags_endpoint(stock_code: str, date: str | None = None, trading_date: str | None = None) -> dict[str, Any]:
        conn = db()
        try:
            from .stock_classifier import get_custom_sector_tags, SECTOR_DISPLAY_NAMES
            d = date or trading_date or latest_trading_date(conn)
            tags = get_custom_sector_tags(conn, stock_code, d)
            return {
                "tags": [
                    {"key": t, "display": SECTOR_DISPLAY_NAMES.get(t, t)}
                    for t in tags
                ],
            }
        finally:
            conn.close()

    # ──────────────────────────────────────────────
    # Announcement Hunter endpoints
    # ──────────────────────────────────────────────

    @app.get("/api/announcements/alerts")
    def announcement_alerts(
        date: str | None = None,
        status: str | None = None,
        alert_type: str | None = None,
        stock_code: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        conn = db()
        try:
            query = "SELECT * FROM announcement_alerts WHERE 1=1"
            params: list = []
            if date:
                query += " AND trading_date=?"
                params.append(date)
            if status:
                query += " AND status=?"
                params.append(status)
            if alert_type:
                query += " AND alert_type=?"
                params.append(alert_type)
            if stock_code:
                query += " AND stock_code=?"
                params.append(stock_code)
            query += " ORDER BY discovered_at DESC LIMIT ?"
            params.append(limit)
            return rows_to_dicts(conn.execute(query, params))
        finally:
            conn.close()

    @app.get("/api/announcements/alerts/{alert_id}")
    def announcement_alert_detail(alert_id: str) -> dict[str, Any] | None:
        conn = db()
        try:
            row = conn.execute(
                "SELECT * FROM announcement_alerts WHERE alert_id=?",
                (alert_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @app.post("/api/announcements/alerts/{alert_id}/acknowledge")
    def announcement_alert_acknowledge(alert_id: str) -> dict[str, Any]:
        conn = db()
        try:
            conn.execute(
                "UPDATE announcement_alerts SET status='acknowledged' WHERE alert_id=?",
                (alert_id,),
            )
            conn.commit()
            return {"status": "ok", "alert_id": alert_id}
        finally:
            conn.close()

    @app.post("/api/announcements/alerts/{alert_id}/dismiss")
    def announcement_alert_dismiss(alert_id: str) -> dict[str, Any]:
        conn = db()
        try:
            conn.execute(
                "UPDATE announcement_alerts SET status='dismissed' WHERE alert_id=?",
                (alert_id,),
            )
            conn.commit()
            return {"status": "ok", "alert_id": alert_id}
        finally:
            conn.close()

    @app.get("/api/announcements/monitor-runs")
    def announcement_monitor_runs(limit: int = 20) -> list[dict[str, Any]]:
        conn = db()
        try:
            return rows_to_dicts(
                conn.execute(
                    "SELECT * FROM monitor_runs ORDER BY started_at DESC LIMIT ?",
                    (limit,),
                )
            )
        finally:
            conn.close()

    @app.get("/api/announcements/sector-heat")
    def announcement_sector_heat(date: str | None = None) -> list[dict[str, Any]]:
        conn = db()
        try:
            d = date or latest_trading_date(conn)
            if not d:
                return []
            return rows_to_dicts(
                conn.execute(
                    "SELECT * FROM sector_heat_index WHERE trading_date=? ORDER BY heat_score DESC",
                    (d,),
                )
            )
        finally:
            conn.close()

    @app.get("/api/announcements/live-stats")
    def announcement_live_stats(date: str | None = None) -> dict[str, Any]:
        conn = db()
        try:
            d = date
            if not d:
                # Prefer announcement_alerts date range, fall back to daily_prices
                row = conn.execute("SELECT MAX(trading_date) AS date FROM announcement_alerts").fetchone()
                d = row["date"] if row and row["date"] else None
            if not d:
                d = latest_trading_date(conn)
            if not d:
                return {"date": None, "total": 0, "by_type": {}, "max_score": 0, "new_count": 0}

            total = conn.execute(
                "SELECT COUNT(*) FROM announcement_alerts WHERE trading_date=?", (d,)
            ).fetchone()[0]

            by_type = {}
            for row in conn.execute(
                "SELECT alert_type, COUNT(*) as cnt FROM announcement_alerts WHERE trading_date=? GROUP BY alert_type",
                (d,),
            ):
                by_type[row["alert_type"]] = row["cnt"]

            max_score_row = conn.execute(
                "SELECT MAX(sentiment_score) as mx FROM announcement_alerts WHERE trading_date=?", (d,)
            ).fetchone()
            max_score = max_score_row["mx"] or 0

            new_count = conn.execute(
                "SELECT COUNT(*) FROM announcement_alerts WHERE trading_date=? AND status='new'", (d,)
            ).fetchone()[0]

            return {
                "date": d,
                "total": total,
                "by_type": by_type,
                "max_score": round(max_score, 3),
                "new_count": new_count,
            }
        finally:
            conn.close()

    @app.post("/api/announcements/scan/trigger")
    def announcement_scan_trigger() -> dict[str, Any]:
        """Manual one-shot scan — always works, independent of cron."""
        from .announcement_monitor import run_announcement_scan
        conn = db()
        try:
            init_db(conn)
            alerts = run_announcement_scan(conn)
            return {"success": True, "alerts_found": len(alerts)}
        except Exception as exc:
            return {"success": False, "error": str(exc)}
        finally:
            conn.close()

    @app.post("/api/announcements/scan/pause")
    def announcement_scan_pause() -> dict[str, Any]:
        """Pause the cron-driven auto-scan."""
        from .scheduler import pause_announcement_scan
        ok = pause_announcement_scan()
        return {"success": ok, "message": "自动扫描已暂停" if ok else "调度器未运行"}

    @app.post("/api/announcements/scan/resume")
    def announcement_scan_resume() -> dict[str, Any]:
        """Resume the cron-driven auto-scan."""
        from .scheduler import resume_announcement_scan
        ok = resume_announcement_scan()
        return {"success": ok, "message": "自动扫描已恢复" if ok else "调度器未运行"}

    @app.get("/api/announcements/scan/status")
    def announcement_scan_status() -> dict[str, Any]:
        from .scheduler import is_scan_paused, get_scheduler_status
        sched = get_scheduler_status()
        auto_paused = is_scan_paused() if sched["running"] else None
        return {
            "scheduler_running": sched["running"],
            "auto_paused": auto_paused,
        }

    @app.get("/api/announcements/events")
    def announcement_scan_events(limit: int = 50) -> list[dict[str, Any]]:
        from .announcement_monitor import get_scan_events
        conn = db()
        try:
            return get_scan_events(limit, conn=conn)
        finally:
            conn.close()

    # WebSocket endpoint for real-time alerts
    broadcast_manager = _BroadcastManagerHolder()

    @app.websocket("/ws/alerts")
    async def websocket_alerts(ws):
        await ws.accept()
        client_id = await broadcast_manager.manager.register(ws)
        try:
            while True:
                # Keep connection alive — client can send ping
                await ws.receive_text()
        except Exception:
            pass
        finally:
            await broadcast_manager.manager.unregister(ws)

    return app


def llm_status_payload(conn, trading_date: str | None = None) -> dict[str, Any]:
    config = resolve_llm_config()
    latest = conn.execute(
        """
        SELECT status, error_message, provider, model, created_at
        FROM llm_scratchpad
        ORDER BY created_at DESC
        LIMIT 1
        """
    ).fetchone()
    latest_for_date = None
    if trading_date:
        latest_for_date = conn.execute(
            """
            SELECT status, error_message, provider, model, created_at
            FROM llm_scratchpad
            WHERE created_at LIKE ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (f"{trading_date}%",),
        ).fetchone()
    row = latest_for_date or latest
    configured = config is not None
    last_status = row["status"] if row else None
    last_error = row["error_message"] if row and row["error_message"] else None
    if not configured:
        state = "Off"
    elif last_status == "error":
        state = "Error"
    else:
        state = "Ready"
    return {
        "state": state,
        "configured": configured,
        "ready": configured and state != "Error",
        "provider": config.provider if config else (row["provider"] if row else None),
        "model": config.model if config else (row["model"] if row else None),
        "last_status": last_status,
        "last_error": last_error,
        "last_run_at": row["created_at"] if row else None,
    }


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
    if dataset == "financial_actuals":
        return sync_financial_actuals(
            conn,
            date,
            providers=providers_for_source(source),
            limit=limit,
            offset=offset,
            batch_size=batch_size,
            resume=resume,
            throttle_seconds=throttle_seconds,
        )
    if dataset == "analyst_expectations":
        return sync_analyst_expectations(
            conn,
            date,
            providers=providers_for_source(source),
            limit=limit,
            offset=offset,
            batch_size=batch_size,
            resume=resume,
            throttle_seconds=throttle_seconds,
        )
    if dataset == "earnings_surprises":
        return sync_earnings_surprises(conn, date)
    if dataset == "order_contract_events":
        return sync_order_contract_events(
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
    if dataset == "business_kpi_actuals":
        return sync_business_kpi_actuals(
            conn,
            date,
            providers=providers_for_source(source),
            limit=limit,
            offset=offset,
            batch_size=batch_size,
            resume=resume,
            throttle_seconds=throttle_seconds,
        )
    if dataset == "risk_events":
        return sync_risk_events(
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
    if dataset == "evidence":
        return sync_evidence(
            conn,
            date,
            providers=providers_for_source(source),
            limit=limit,
            offset=offset,
            batch_size=batch_size,
            resume=resume,
            throttle_seconds=throttle_seconds,
        )
    raise ValueError(f"Unknown dataset: {dataset}")


def providers_for_source(source: str):
    if source == "akshare":
        return [AkShareProvider()]
    if source == "baostock":
        return [BaoStockProvider()]
    if source == "demo":
        return [DemoProvider()]
    return [AkShareProvider(), BaoStockProvider()]
