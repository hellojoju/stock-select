from __future__ import annotations

import argparse
import json

from .agent_runtime import run_daily_pipeline, run_phase
from .announcement_providers import sync_announcements
from .pdf_extractor import process_pending_announcements as _cli_process_pending
from .source_meta import list_all_sources, get_source_meta
from .data_ingestion import (
    AkShareProvider,
    BaoStockProvider,
    DemoProvider,
    backfill_factors_range,
    backfill_daily_prices_range,
    publish_canonical_prices,
    sync_factors,
    sync_daily_prices,
)
from .db import connect, init_db
from .evidence_sync import backfill_evidence_range, sync_evidence
from .evolution import evolution_comparison, promote_challenger, propose_strategy_evolution, rollback_evolution, score_genes
from .graph import sync_decision_graph, sync_review_graph, detect_communities, store_communities
from .graph_export import process_documents, export_for_date
from .manual_import import import_documents
from .memory import search_memory, search_documents
from .news_providers import store_document, query_documents
from .runtime import resolve_runtime
from .seed import seed_demo_data
from .server import run_server
from .simulator import simulate_day, summarize_performance
from .strategies import generate_picks_for_all_genes, seed_default_genes
from .health_check import startup_health_check


def add_runtime_args(parser: argparse.ArgumentParser, *, root: bool = False) -> None:
    default = None if root else argparse.SUPPRESS
    parser.add_argument("--mode", choices=["demo", "live"], default=default, help="Runtime data mode")
    parser.add_argument("--db", default=default, help="SQLite database path")


def providers_for_source(source: str):
    if source == "akshare":
        return [AkShareProvider()]
    if source == "baostock":
        return [BaoStockProvider()]
    if source == "demo":
        return [DemoProvider()]
    return [AkShareProvider(), BaoStockProvider()]


def main() -> None:
    parser = argparse.ArgumentParser(prog="stock-select")
    add_runtime_args(parser, root=True)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_cmd = subparsers.add_parser("init-db", help="Create database schema")
    add_runtime_args(init_cmd)
    seed_cmd = subparsers.add_parser("seed-demo", help="Load demo stocks, prices, and default genes")
    add_runtime_args(seed_cmd)

    run_daily = subparsers.add_parser("run-daily", help="Generate picks and simulate one trading day")
    add_runtime_args(run_daily)
    run_daily.add_argument("--date", required=True, help="Trading date, YYYY-MM-DD")

    pipeline = subparsers.add_parser("pipeline", help="Run sync, picks, simulate, and review")
    add_runtime_args(pipeline)
    pipeline.add_argument("--date", required=True)

    run_phase_cmd = subparsers.add_parser("run-phase", help="Run a named orchestrator phase")
    add_runtime_args(run_phase_cmd)
    run_phase_cmd.add_argument(
        "phase",
        choices=[
            "sync_data",
            "sync_stock_universe",
            "sync_trading_calendar",
            "sync_daily_prices",
            "sync_index_prices",
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
        ],
    )
    run_phase_cmd.add_argument("--date", required=True)

    sync_daily = subparsers.add_parser("sync-daily-prices", help="Sync source daily prices in chunks")
    add_runtime_args(sync_daily)
    sync_daily.add_argument("--date", required=True)
    sync_daily.add_argument("--source", choices=["akshare", "baostock", "demo", "all"], default="all")
    sync_daily.add_argument("--limit", type=int)
    sync_daily.add_argument("--offset", type=int, default=0)
    sync_daily.add_argument("--batch-size", type=int, default=100)
    sync_daily.add_argument("--resume", action="store_true")
    sync_daily.add_argument("--max-retries", type=int, default=1)
    sync_daily.add_argument("--throttle-seconds", type=float, default=0.0)
    sync_daily.add_argument("--publish-canonical", action="store_true")

    backfill_daily = subparsers.add_parser("backfill-daily-prices", help="Backfill source daily prices over open trading days")
    add_runtime_args(backfill_daily)
    backfill_daily.add_argument("--start", required=True)
    backfill_daily.add_argument("--end", required=True)
    backfill_daily.add_argument("--source", choices=["akshare", "baostock", "demo", "all"], default="all")
    backfill_daily.add_argument("--limit", type=int)
    backfill_daily.add_argument("--offset", type=int, default=0)
    backfill_daily.add_argument("--batch-size", type=int, default=100)
    backfill_daily.add_argument("--resume", action="store_true", default=True)
    backfill_daily.add_argument("--no-resume", action="store_false", dest="resume")
    backfill_daily.add_argument("--max-retries", type=int, default=1)
    backfill_daily.add_argument("--throttle-seconds", type=float, default=0.0)
    backfill_daily.add_argument("--publish-canonical", action="store_true", default=True)
    backfill_daily.add_argument("--no-publish-canonical", action="store_false", dest="publish_canonical")
    backfill_daily.add_argument("--sync-indexes", action="store_true")
    backfill_daily.add_argument("--classify-environment", action="store_true")
    backfill_daily.add_argument(
        "--historical-universe-date",
        help="Filter stock universe to securities listed by this date when provider supports it",
    )

    backfill_factors = subparsers.add_parser("backfill-factors", help="Backfill multidimensional factors over open trading days")
    add_runtime_args(backfill_factors)
    backfill_factors.add_argument("--start", required=True)
    backfill_factors.add_argument("--end", required=True)
    backfill_factors.add_argument("--source", choices=["akshare", "baostock", "demo", "all"], default="all")
    backfill_factors.add_argument("--limit", type=int, default=500)
    backfill_factors.add_argument("--offset", type=int, default=0)
    backfill_factors.add_argument("--batch-size", type=int, default=100)
    backfill_factors.add_argument("--resume", action="store_true", default=True)
    backfill_factors.add_argument("--no-resume", action="store_false", dest="resume")
    backfill_factors.add_argument("--throttle-seconds", type=float, default=0.0)

    backfill_evidence = subparsers.add_parser("backfill-evidence", help="Backfill structured review evidence over open trading days")
    add_runtime_args(backfill_evidence)
    backfill_evidence.add_argument("--start", required=True)
    backfill_evidence.add_argument("--end", required=True)
    backfill_evidence.add_argument("--source", choices=["akshare", "baostock", "demo", "all"], default="all")
    backfill_evidence.add_argument("--limit", type=int, default=500)
    backfill_evidence.add_argument("--offset", type=int, default=0)
    backfill_evidence.add_argument("--batch-size", type=int, default=100)
    backfill_evidence.add_argument("--resume", action="store_true", default=True)
    backfill_evidence.add_argument("--no-resume", action="store_false", dest="resume")
    backfill_evidence.add_argument("--throttle-seconds", type=float, default=0.0)

    perf = subparsers.add_parser("performance", help="Show strategy performance")
    add_runtime_args(perf)
    perf.add_argument("--date", help="Optional trading date")

    mem = subparsers.add_parser("memory-search", help="Search FTS5 memory")
    add_runtime_args(mem)
    mem.add_argument("query")

    graph = subparsers.add_parser("sync-graph", help="Persist graph nodes and edges for a date")
    add_runtime_args(graph)
    graph.add_argument("--date", required=True)

    sync_news = subparsers.add_parser("sync-news", help="Fetch announcements and news into raw_documents")
    add_runtime_args(sync_news)
    sync_news.add_argument("--date", required=True)
    sync_news.add_argument("--stock-code", help="Limit to specific stock")
    sync_news.add_argument("--sources", default="all", help="Comma-separated: cninfo,sse,szse,eastmoney,sina,all")

    process_pdfs = subparsers.add_parser("process-pdfs", help="Download PDFs, extract text, classify and persist events")
    add_runtime_args(process_pdfs)
    process_pdfs.add_argument("--date", required=True)
    process_pdfs.add_argument("--limit", type=int, default=20)

    import_docs = subparsers.add_parser("import-docs", help="Manually import CSV/Markdown/HTML/PDF documents")
    add_runtime_args(import_docs)
    import_docs.add_argument("paths", nargs="+", help="Files or directories to import")
    import_docs.add_argument("--source", default="manual_import", help="Source label")
    import_docs.add_argument("--date", help="Default date if not in file")
    import_docs.add_argument("--stock-code", help="Related stock code")

    extract = subparsers.add_parser("extract-knowledge", help="Process raw documents: entity linking, event classification, graph")
    add_runtime_args(extract)
    extract.add_argument("--date", required=True)
    extract.add_argument("--stock-code", help="Limit to specific stock")
    extract.add_argument("--limit", type=int, default=200)

    export_graphify = subparsers.add_parser("export-graphify", help="Export graph to Graphify-compatible JSON")
    add_runtime_args(export_graphify)
    export_graphify.add_argument("--date", required=True)
    export_graphify.add_argument("--output", default="var/graphify", help="Output directory")

    scores = subparsers.add_parser("score-genes", help="Score strategy genes over a period")
    add_runtime_args(scores)
    scores.add_argument("--start", required=True)
    scores.add_argument("--end", required=True)

    propose = subparsers.add_parser("propose-evolution", help="Create review-driven challenger strategy versions")
    add_runtime_args(propose)
    propose.add_argument("--start")
    propose.add_argument("--end")
    propose.add_argument("--date", help="Convenience shortcut for --start DATE --end DATE")
    propose.add_argument("--gene-id")
    propose.add_argument("--dry-run", action="store_true")
    propose.add_argument("--min-trades", type=int, default=20)
    propose.add_argument("--min-signal-samples", type=int, default=5)
    propose.add_argument("--min-signal-confidence", type=float, default=0.65)
    propose.add_argument("--min-signal-dates", type=int, default=3)

    rollback = subparsers.add_parser("rollback-evolution", help="Rollback an observing challenger")
    add_runtime_args(rollback)
    rollback.add_argument("--child-gene-id")
    rollback.add_argument("--event-id")
    rollback.add_argument("--reason", default="manual rollback")

    promote = subparsers.add_parser("promote-challenger", help="Promote an observing challenger to active")
    add_runtime_args(promote)
    promote.add_argument("--child-gene-id", required=True)
    promote.add_argument("--reason", default="manual promotion")

    compare = subparsers.add_parser("evolution-comparison", help="Compare champion and challenger performance")
    add_runtime_args(compare)
    compare.add_argument("--gene-id")
    compare.add_argument("--start")
    compare.add_argument("--end")

    serve = subparsers.add_parser("serve", help="Run the stdlib HTTP API server")
    add_runtime_args(serve)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=18425)

    list_sources_cmd = subparsers.add_parser("list-sources", help="Show configured data sources and their authorization status")

    args = parser.parse_args()
    runtime = resolve_runtime(args.mode or "demo", args.db)
    db_path = runtime.db_path
    conn = connect(db_path)
    init_db(conn)

    if args.command == "init-db":
        seed_default_genes(conn)
        print(json.dumps({"db": str(db_path), "mode": runtime.mode, "status": "initialized"}, indent=2))
    elif args.command == "seed-demo":
        if runtime.mode == "live":
            raise SystemExit("seed-demo is not allowed in live mode")
        seed_demo_data(conn)
        print(json.dumps({"db": str(db_path), "mode": runtime.mode, "status": "demo_seeded"}, indent=2))
    elif args.command == "run-daily":
        decision_ids = generate_picks_for_all_genes(conn, args.date)
        outcome_ids = simulate_day(conn, args.date)
        print(
            json.dumps(
                {
                    "db": str(db_path),
                    "trading_date": args.date,
                    "decisions": len(decision_ids),
                    "outcomes": len(outcome_ids),
                    "performance": summarize_performance(conn, args.date),
                },
                indent=2,
            )
        )
    elif args.command == "pipeline":
        health = startup_health_check(conn)
        if not health["overall_ok"]:
            print(f"WARNING: {health['genes_invalid']} invalid gene(s) marked inactive")
        providers = [AkShareProvider(), BaoStockProvider()]
        print(json.dumps(run_daily_pipeline(conn, args.date, providers=providers, runtime_mode=runtime.mode), indent=2, ensure_ascii=False))
    elif args.command == "run-phase":
        health = startup_health_check(conn)
        if not health["overall_ok"]:
            print(f"WARNING: {health['genes_invalid']} invalid gene(s) marked inactive")
        print(json.dumps(run_phase(conn, args.phase, args.date, runtime_mode=runtime.mode), indent=2, ensure_ascii=False))
    elif args.command == "sync-daily-prices":
        result = sync_daily_prices(
            conn,
            args.date,
            providers=providers_for_source(args.source),
            limit=args.limit,
            offset=args.offset,
            batch_size=args.batch_size,
            resume=args.resume,
            max_retries=args.max_retries,
            throttle_seconds=args.throttle_seconds,
        )
        if args.publish_canonical:
            result["canonical_prices"] = publish_canonical_prices(conn, args.date)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.command == "backfill-daily-prices":
        result = backfill_daily_prices_range(
            conn,
            args.start,
            args.end,
            providers=providers_for_source(args.source),
            limit=args.limit,
            offset=args.offset,
            batch_size=args.batch_size,
            resume=args.resume,
            max_retries=args.max_retries,
            throttle_seconds=args.throttle_seconds,
            publish_canonical=args.publish_canonical,
            sync_indexes=args.sync_indexes,
            classify_environment=args.classify_environment,
            historical_universe_date=args.historical_universe_date,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.command == "backfill-factors":
        result = backfill_factors_range(
            conn,
            args.start,
            args.end,
            providers=providers_for_source(args.source),
            limit=args.limit,
            offset=args.offset,
            batch_size=args.batch_size,
            resume=args.resume,
            throttle_seconds=args.throttle_seconds,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.command == "backfill-evidence":
        result = backfill_evidence_range(
            conn,
            args.start,
            args.end,
            providers=providers_for_source(args.source),
            limit=args.limit,
            offset=args.offset,
            batch_size=args.batch_size,
            resume=args.resume,
            throttle_seconds=args.throttle_seconds,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.command == "performance":
        print(json.dumps(summarize_performance(conn, args.date), indent=2))
    elif args.command == "memory-search":
        print(json.dumps(search_memory(conn, args.query), indent=2, ensure_ascii=False))
    elif args.command == "sync-graph":
        result = sync_decision_graph(conn, args.date)
        review_result = sync_review_graph(conn, args.date)
        result["review_nodes"] = review_result["nodes"]
        result["review_edges"] = review_result["edges"]
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.command == "score-genes":
        print(json.dumps(score_genes(conn, period_start=args.start, period_end=args.end), indent=2, ensure_ascii=False))
    elif args.command == "propose-evolution":
        period_start = args.start or args.date
        period_end = args.end or args.date
        if not period_start or not period_end:
            raise SystemExit("propose-evolution requires --start/--end or --date")
        print(
            json.dumps(
                propose_strategy_evolution(
                    conn,
                    period_start=period_start,
                    period_end=period_end,
                    gene_id=args.gene_id,
                    min_trades=args.min_trades,
                    min_signal_samples=args.min_signal_samples,
                    min_signal_confidence=args.min_signal_confidence,
                    min_signal_dates=args.min_signal_dates,
                    dry_run=args.dry_run,
                ),
                indent=2,
                ensure_ascii=False,
            )
        )
    elif args.command == "rollback-evolution":
        print(
            json.dumps(
                rollback_evolution(
                    conn,
                    child_gene_id=args.child_gene_id,
                    event_id=args.event_id,
                    reason=args.reason,
                ),
                indent=2,
                ensure_ascii=False,
            )
        )
    elif args.command == "promote-challenger":
        print(
            json.dumps(
                promote_challenger(conn, child_gene_id=args.child_gene_id, reason=args.reason),
                indent=2,
                ensure_ascii=False,
            )
        )
    elif args.command == "evolution-comparison":
        print(
            json.dumps(
                evolution_comparison(conn, gene_id=args.gene_id, start=args.start, end=args.end),
                indent=2,
                ensure_ascii=False,
            )
        )
    elif args.command == "sync-news":
        sources = args.sources
        all_items = sync_announcements(stock_code=args.stock_code, date=args.date, conn=conn)
        stored = 0
        for item in all_items:
            if sources != "all":
                allowed = sources.split(",")
                if item.source not in allowed:
                    continue
            doc_id = store_document(conn, item)
            stored += 1
        conn.commit()
        print(json.dumps({
            "fetched": len(all_items),
            "stored": stored,
            "by_source": {},
        }, indent=2, ensure_ascii=False))
    elif args.command == "process-pdfs":
        from .announcement_events import process_announcement_text

        processed = _cli_process_pending(conn, limit=args.limit)
        results = []
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
                    conn, item["document_id"], text["content_text"], args.date, known_codes or None
                )
                results.append({
                    "document_id": item["document_id"],
                    "title": item["title"],
                    "text_length": item["text_length"],
                    "classifications": item.get("classifications", []),
                    "extracted_events": counts,
                })
        print(json.dumps({
            "processed": len(processed),
            "with_events": len(results),
            "details": results,
        }, indent=2, ensure_ascii=False))
    elif args.command == "import-docs":
        results = import_documents(
            conn,
            paths=args.paths,
            source=args.source,
            default_date=args.date,
            default_stock_code=args.stock_code,
        )
        print(json.dumps(results, indent=2, ensure_ascii=False))
    elif args.command == "extract-knowledge":
        stats = process_documents(
            conn,
            date=args.date,
            stock_code=args.stock_code,
            limit=args.limit,
        )
        print(json.dumps(stats, indent=2, ensure_ascii=False))
    elif args.command == "export-graphify":
        out_path = export_for_date(conn, date=args.date, output_dir=args.output)
        print(json.dumps({"output": out_path, "status": "exported"}, indent=2, ensure_ascii=False))
    elif args.command == "serve":
        conn.close()
        try:
            from .api import create_app
            import uvicorn
            app = create_app(db_path, mode=runtime.mode)
            uvicorn.run(app, host=args.host, port=args.port, log_level="info")
        except Exception as e:
            print(f"FastAPI startup failed: {e}")
            print("Falling back to stdlib server (deprecated)...")
            run_server(args.host, args.port, db_path, mode=runtime.mode)
    elif args.command == "list-sources":
        sources = list_all_sources()
        # Enrich with actual sync status from the database
        rows = conn.execute(
            """
            SELECT source, dataset, trading_date, status, rows_loaded
            FROM data_sources
            WHERE (source, dataset, trading_date) IN (
                SELECT source, dataset, MAX(trading_date)
                FROM data_sources
                GROUP BY source, dataset
            )
            ORDER BY source, dataset
            """
        ).fetchall()
        status_map: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = row["source"]
            if key not in status_map:
                status_map[key] = {"datasets": {}}
            status_map[key]["datasets"][row["dataset"]] = {
                "status": row["status"],
                "trading_date": row["trading_date"],
                "rows_loaded": row["rows_loaded"],
            }
        for src in sources:
            src["sync_status"] = status_map.get(src["source"], {}).get("datasets", {})
            meta = get_source_meta(src["source"])
            if meta:
                src["copyright_notice"] = meta.copyright_notice
        print(json.dumps(sources, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
