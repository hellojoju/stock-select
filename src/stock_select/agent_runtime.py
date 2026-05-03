from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from time import perf_counter
from typing import Any, Iterator

from .blindspots import scan_blindspots
from .data_ingestion import (
    MarketDataProvider,
    classify_market_environment,
    publish_canonical_prices,
    sync_factors,
    sync_industries,
    sync_sector_signals,
    sync_fundamentals,
    sync_event_signals,
    sync_all_data,
    sync_daily_prices,
    sync_index_prices,
    sync_stock_universe,
    sync_trading_calendar,
)
from .evidence_sync import (
    sync_analyst_expectations,
    sync_business_kpi_actuals,
    sync_earnings_surprises,
    sync_evidence,
    sync_financial_actuals,
    sync_order_contract_events,
    sync_risk_events,
)
from .blindspot_review import run_blindspot_review
from .deterministic_review import run_deterministic_review
from .evolution import default_week_window, auto_promote_challengers, evolve_weekly
from .gene_review import run_gene_reviews_for_date
from .pick_evaluator import run_evaluation
from .planner import plan_preopen_focus
from .review import generate_deterministic_reviews
from .pdf_extractor import process_pending_announcements
from .announcement_events import process_announcement_text
from .review_analysts import run_analyst_reviews
from .simulator import simulate_day
from .strategies import generate_picks_for_all_genes
from .system_review import run_system_review
from .data_availability import check_data_availability


RUN_PHASES = {
    "sync_data",
    "sync_stock_universe",
    "sync_trading_calendar",
    "sync_daily_prices",
    "sync_index_prices",
    "sync_market_breadth",
    "publish_canonical_prices",
    "classify_market_environment",
    "sync_industries",
    "sync_sector_signals",
    "sync_fundamentals",
    "sync_event_signals",
    "sync_factors",
    "sync_financial_actuals",
    "sync_analyst_expectations",
    "compute_earnings_surprises",
    "sync_order_contract_events",
    "sync_business_kpi_actuals",
    "sync_risk_events",
    "sync_evidence",
    "process_announcements",
    "preopen_pick",
    "simulate",
    "review",
    "deterministic_review",
    "blindspot_review",
    "analyst_review",
    "gene_review",
    "system_review",
    "review_consolidation",
    "llm_review",
    "evolve",
}


def run_phase(
    conn: sqlite3.Connection,
    phase: str,
    trading_date: str,
    *,
    runtime_mode: str = "demo",
) -> dict[str, Any]:
    if phase not in RUN_PHASES:
        raise ValueError(f"Unknown phase: {phase}")
    with research_run(conn, phase, trading_date) as run:
        if phase == "sync_data":
            result = sync_all_data(conn, trading_date)
        elif phase == "sync_stock_universe":
            result = sync_stock_universe(conn)
        elif phase == "sync_trading_calendar":
            result = sync_trading_calendar(conn, calendar_start_for(trading_date), trading_date)
        elif phase == "sync_daily_prices":
            result = sync_daily_prices(conn, trading_date)
        elif phase == "sync_index_prices":
            result = sync_index_prices(conn, trading_date)
        elif phase == "sync_market_breadth":
            from .market_breadth import ensure_market_breadth

            result = ensure_market_breadth(conn, trading_date)
        elif phase == "publish_canonical_prices":
            result = publish_canonical_prices(conn, trading_date)
        elif phase == "classify_market_environment":
            result = classify_market_environment(conn, trading_date)
        elif phase == "sync_industries":
            result = sync_industries(conn, trading_date)
        elif phase == "sync_sector_signals":
            result = sync_sector_signals(conn, trading_date)
        elif phase == "sync_fundamentals":
            result = sync_fundamentals(conn, trading_date)
        elif phase == "sync_event_signals":
            result = sync_event_signals(conn, trading_date, trading_date)
        elif phase == "sync_factors":
            result = sync_factors(conn, trading_date)
        elif phase == "sync_financial_actuals":
            result = sync_financial_actuals(conn, trading_date)
        elif phase == "sync_analyst_expectations":
            result = sync_analyst_expectations(conn, trading_date)
        elif phase == "compute_earnings_surprises":
            result = sync_earnings_surprises(conn, trading_date)
        elif phase == "sync_order_contract_events":
            result = sync_order_contract_events(conn, trading_date, trading_date)
        elif phase == "sync_business_kpi_actuals":
            result = sync_business_kpi_actuals(conn, trading_date)
        elif phase == "sync_risk_events":
            result = sync_risk_events(conn, trading_date, trading_date)
        elif phase == "sync_evidence":
            result = sync_evidence(conn, trading_date)
        elif phase == "process_announcements":
            processed = process_pending_announcements(conn, limit=20)
            extracted = []
            for item in processed:
                text = conn.execute(
                    "SELECT content_text FROM raw_documents WHERE document_id = ?",
                    (item["document_id"],),
                ).fetchone()
                if text and text["content_text"]:
                    stocks = conn.execute(
                        "SELECT stock_code FROM document_stock_links WHERE document_id = ?",
                        (item["document_id"],),
                    ).fetchall()
                    known_codes = [r["stock_code"] for r in stocks]
                    counts = process_announcement_text(
                        conn, item["document_id"], text["content_text"], trading_date, known_codes or None
                    )
                    extracted.append({**item, "extracted_events": counts})
            result = {"processed": len(processed), "with_events": len(extracted), "details": extracted}
        elif phase == "preopen_pick":
            plan = plan_preopen_focus(conn, trading_date)
            _store_planner_plan(conn, plan)
            result = {
                "decision_ids": generate_picks_for_all_genes(
                    conn,
                    trading_date,
                    preserve_audit=runtime_mode == "live",
                ),
                "planner_plan": plan,
            }
        elif phase == "simulate":
            result = {"outcome_ids": simulate_day(conn, trading_date)}
        elif phase == "review":
            result = {
                "review_ids": generate_deterministic_reviews(conn, trading_date),
                "blindspot_ids": scan_blindspots(conn, trading_date),
                "pick_evaluations": run_evaluation(conn, trading_date),
            }
        elif phase == "deterministic_review":
            result = {"review_ids": run_deterministic_review(conn, trading_date)}
        elif phase == "blindspot_review":
            result = {"blindspot_review_ids": run_blindspot_review(conn, trading_date)}
        elif phase == "gene_review":
            result = {"gene_review_ids": run_gene_reviews_for_date(conn, trading_date)}
        elif phase == "analyst_review":
            result = {"analyst_reviews": run_analyst_reviews(conn, trading_date, include_llm=True)}
        elif phase == "system_review":
            result = {"system_review_id": run_system_review(conn, trading_date)}
        elif phase == "review_consolidation":
            result = {
                "gene_review_ids": run_gene_reviews_for_date(conn, trading_date),
                "system_review_id": run_system_review(conn, trading_date),
            }
        elif phase == "llm_review":
            from .llm_review import run_llm_review

            result = run_llm_review(conn, trading_date)
        else:
            start, end = default_week_window()
            evolve_result = evolve_weekly(conn, period_start=start, period_end=end)
            auto_promoted = auto_promote_challengers(conn)
            evolve_result["auto_promoted"] = auto_promoted
            result = evolve_result
        # Availability gate for critical phases
        availability = None
        if phase in ("sync_data", "preopen_pick", "simulate", "review", "deterministic_review", "blindspot_review", "analyst_review", "gene_review", "system_review"):
            availability = check_data_availability(conn, trading_date)
            if phase == "preopen_pick" and availability.pick_count == 0:
                run.event("availability_gate", {"status": "failed", "reasons": availability.reasons})
            elif phase in ("review", "deterministic_review", "blindspot_review", "analyst_review", "gene_review", "system_review") and availability.review_evidence_count == 0:
                run.event("availability_gate", {"status": "degraded", "reasons": availability.reasons})
            elif availability.status != "ok":
                run.event("availability_gate", {"status": availability.status, "reasons": availability.reasons})

        run.finish(result)
        resp: dict[str, Any] = {"run_id": run.run_id, "phase": phase, "trading_date": trading_date, "result": result}
        if availability is not None:
            resp["availability"] = {
                "status": availability.status,
                "price_coverage_pct": availability.price_coverage_pct,
                "pick_count": availability.pick_count,
                "event_source_count": availability.event_source_count,
                "review_evidence_count": availability.review_evidence_count,
                "reasons": availability.reasons,
            }
        return resp


def run_daily_pipeline(
    conn: sqlite3.Connection,
    trading_date: str,
    providers: list[MarketDataProvider] | None = None,
    *,
    runtime_mode: str = "demo",
) -> list[dict[str, Any]]:
    if not providers:
        raise ValueError("providers is required: pass at least one MarketDataProvider")
    with research_run(conn, "sync_data", trading_date) as run:
        result = sync_all_data(conn, trading_date, providers=providers)
        run.finish(result)
        sync_result = {"run_id": run.run_id, "phase": "sync_data", "trading_date": trading_date, "result": result}
    return [
        sync_result,
        run_phase(conn, "preopen_pick", trading_date, runtime_mode=runtime_mode),
        run_phase(conn, "simulate", trading_date, runtime_mode=runtime_mode),
        run_phase(conn, "review", trading_date, runtime_mode=runtime_mode),
    ]


@contextmanager
def research_run(conn: sqlite3.Connection, phase: str, trading_date: str) -> Iterator["ResearchRun"]:
    run = ResearchRun(conn, phase, trading_date)
    run.start()
    try:
        yield run
    except Exception as exc:
        run.fail(exc)
        raise


class ResearchRun:
    def __init__(self, conn: sqlite3.Connection, phase: str, trading_date: str) -> None:
        self.conn = conn
        self.phase = phase
        self.trading_date = trading_date
        self.run_id = build_run_id(phase, trading_date)
        self.started = perf_counter()
        self.scratchpad_path = Path("var") / "scratchpads" / f"{self.run_id}.jsonl"

    def start(self) -> None:
        self.scratchpad_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn.execute(
            """
            INSERT INTO research_runs(run_id, trading_date, phase, input_snapshot_hash, status)
            VALUES (?, ?, ?, ?, 'running')
            ON CONFLICT(run_id) DO UPDATE SET
              status = 'running',
              error = NULL,
              started_at = CURRENT_TIMESTAMP,
              finished_at = NULL
            """,
            (self.run_id, self.trading_date, self.phase, input_snapshot_hash(self.phase, self.trading_date)),
        )
        self.event("init", {"phase": self.phase, "trading_date": self.trading_date})
        self.conn.commit()

    def event(self, event_type: str, payload: dict[str, Any]) -> None:
        line = {"type": event_type, "payload": payload}
        with self.scratchpad_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
        self.conn.execute(
            """
            INSERT INTO scratchpad_events(run_id, scratchpad_path, event_type, payload_json)
            VALUES (?, ?, ?, ?)
            """,
            (self.run_id, str(self.scratchpad_path), event_type, json.dumps(payload, ensure_ascii=False)),
        )

    def finish(self, result: dict[str, Any]) -> None:
        self.event("done", result)
        duration_ms = int((perf_counter() - self.started) * 1000)
        self.conn.execute(
            """
            INSERT INTO tool_events(run_id, event_type, tool_name, result_summary, duration_ms)
            VALUES (?, 'phase_end', ?, ?, ?)
            """,
            (self.run_id, self.phase, json.dumps(result, ensure_ascii=False, sort_keys=True), duration_ms),
        )
        self.conn.execute(
            """
            UPDATE research_runs
            SET status = 'ok', summary = ?, finished_at = CURRENT_TIMESTAMP
            WHERE run_id = ?
            """,
            (json.dumps(result, ensure_ascii=False, sort_keys=True), self.run_id),
        )
        self.conn.commit()

    def fail(self, exc: Exception) -> None:
        self.event("error", {"error": str(exc)})
        self.conn.execute(
            """
            UPDATE research_runs
            SET status = 'error', error = ?, finished_at = CURRENT_TIMESTAMP
            WHERE run_id = ?
            """,
            (str(exc), self.run_id),
        )
        self.conn.commit()


def build_run_id(phase: str, trading_date: str) -> str:
    raw = f"{phase}:{trading_date}"
    return "run_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14]


def input_snapshot_hash(phase: str, trading_date: str) -> str:
    return hashlib.sha256(f"{phase}:{trading_date}:v1".encode("utf-8")).hexdigest()


def calendar_start_for(trading_date: str) -> str:
    from datetime import datetime, timedelta

    return (datetime.strptime(trading_date, "%Y-%m-%d").date() - timedelta(days=45)).isoformat()


def _store_planner_plan(conn: sqlite3.Connection, plan: dict[str, Any]) -> None:
    """Persist the planner plan for later comparison with actual picks."""
    import hashlib

    plan_id = "plan_" + hashlib.sha1(f"{plan['trading_date']}:planner".encode()).hexdigest()[:12]
    conn.execute(
        """
        INSERT INTO planner_plans(
          plan_id, trading_date, focus_sectors_json, market_environment_json,
          high_impact_events_json, watch_risks_json, llm_notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(trading_date) DO UPDATE SET
          focus_sectors_json = excluded.focus_sectors_json,
          market_environment_json = excluded.market_environment_json,
          high_impact_events_json = excluded.high_impact_events_json,
          watch_risks_json = excluded.watch_risks_json,
          llm_notes = excluded.llm_notes
        """,
        (
            plan_id,
            plan["trading_date"],
            json.dumps(plan["focus_sectors"]),
            json.dumps(plan["market_environment"]),
            json.dumps(plan["high_impact_events"]),
            json.dumps(plan["watch_risks"]),
            plan.get("llm_notes"),
        ),
    )
    conn.commit()
