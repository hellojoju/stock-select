from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .agent_runtime import run_phase
from .api import DB_PATH, run_data_sync
from .db import connect, init_db
from .blindspot_review import run_blindspot_review
from .data_status import data_quality_rows, data_quality_summary, data_source_status
from .deterministic_review import review_decision
from .evolution import evolution_comparison, promote_challenger, propose_strategy_evolution, rollback_evolution
from .evidence_views import evidence_status as evidence_status_payload, stock_evidence
from .factor_views import factor_status, sector_factors, stock_factors
from .gene_review import get_preopen_strategy_review, list_preopen_strategy_reviews, review_gene
from .graph import query_graph
from .memory import search_memory
from .optimization_signals import list_optimization_signals
from .repository import latest_trading_date, review_rows_for_date, rows_to_dicts
from .review_packets import stock_review, stock_review_history
from .runtime import resolve_runtime
from .simulator import summarize_performance
from .strategies import seed_default_genes
from .system_review import review_summary


def run_server(host: str = "127.0.0.1", port: int = 8000, db_path: str | Path | None = None, mode: str = "demo") -> None:
    runtime = resolve_runtime(mode, db_path)

    class Handler(ApiHandler):
        database_path = runtime.db_path
        runtime_context = runtime

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Serving stock-select API on http://{host}:{port}")
    server.serve_forever()


class ApiHandler(BaseHTTPRequestHandler):
    database_path = DB_PATH
    runtime_context = resolve_runtime("demo", DB_PATH)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        try:
            if parsed.path == "/api/dashboard":
                self.respond_json(self.dashboard(params.get("date")))
            elif parsed.path == "/api/picks":
                self.respond_json(self.picks(params))
            elif parsed.path == "/api/genes":
                self.respond_json(self.genes())
            elif parsed.path == "/api/evolution/events":
                self.respond_json(self.evolution_events(params))
            elif parsed.path == "/api/evolution/comparison":
                self.respond_json(self.evolution_comparison(params))
            elif parsed.path.startswith("/api/genes/") and parsed.path.endswith("/performance"):
                gene_id = parsed.path.split("/")[3]
                self.respond_json(self.gene_performance(gene_id))
            elif parsed.path == "/api/runs":
                self.respond_json(self.runs(params.get("date")))
            elif parsed.path == "/api/data/status":
                self.respond_json(self.data_status(params))
            elif parsed.path == "/api/data/quality":
                self.respond_json(self.data_quality(params))
            elif parsed.path == "/api/factors/status":
                self.respond_json(self.factor_status(params))
            elif parsed.path.startswith("/api/factors/stocks/"):
                stock_code = parsed.path.split("/")[4]
                self.respond_json(self.stock_factors(stock_code, params))
            elif parsed.path == "/api/factors/sectors":
                self.respond_json(self.sector_factors(params))
            elif parsed.path == "/api/evidence/status":
                self.respond_json(self.evidence_status(params))
            elif parsed.path.startswith("/api/evidence/stocks/"):
                stock_code = parsed.path.split("/")[4]
                self.respond_json(self.stock_evidence(stock_code, params))
            elif parsed.path.startswith("/api/reviews/stocks/") and parsed.path.endswith("/history"):
                stock_code = parsed.path.split("/")[4]
                self.respond_json(self.stock_review_history(stock_code, params))
            elif parsed.path.startswith("/api/reviews/stocks/"):
                stock_code = parsed.path.split("/")[4]
                self.respond_json(self.stock_review(stock_code, params))
            elif parsed.path == "/api/reviews/preopen-strategies":
                self.respond_json(self.preopen_strategy_reviews(params))
            elif parsed.path.startswith("/api/reviews/preopen-strategies/"):
                gene_id = parsed.path.split("/")[4]
                self.respond_json(self.preopen_strategy_review(gene_id, params))
            elif parsed.path == "/api/reviews":
                self.respond_json(self.reviews(params["date"]))
            elif parsed.path == "/api/reviews/llm":
                self.respond_json(self.llm_reviews(params["date"]))
            elif parsed.path == "/api/optimization-signals":
                self.respond_json(self.optimization_signals(params))
            elif parsed.path == "/api/memory/search":
                self.respond_json(self.memory_search(params.get("q", ""), int(params.get("limit", "10"))))
            elif parsed.path == "/api/blindspots":
                self.respond_json(self.blindspots(params["date"]))
            elif parsed.path == "/api/graph/query":
                self.respond_json(self.graph_query(params))
            elif parsed.path == "/health":
                self.respond_json({"status": "ok"})
            else:
                self.respond_json({"error": "not found"}, status=404)
        except Exception as exc:
            self.respond_json({"error": str(exc)}, status=500)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        params = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        try:
            if parsed.path.startswith("/api/runs/"):
                phase = parsed.path.split("/")[-1]
                self.respond_json(self.trigger_run(phase, params["date"]))
            elif parsed.path == "/api/evolution/propose":
                self.respond_json(self.propose_evolution(params))
            elif parsed.path == "/api/evolution/rollback":
                self.respond_json(self.rollback_evolution(params))
            elif parsed.path == "/api/evolution/promote":
                self.respond_json(self.promote_challenger(params))
            elif parsed.path == "/api/data/sync":
                self.respond_json(self.data_sync(params))
            elif parsed.path.startswith("/api/reviews/stocks/") and parsed.path.endswith("/rerun"):
                stock_code = parsed.path.split("/")[4]
                self.respond_json(self.rerun_stock_review(stock_code, params))
            elif parsed.path.startswith("/api/optimization-signals/") and parsed.path.endswith("/accept"):
                signal_id = parsed.path.split("/")[4]
                self.respond_json(self.accept_signal(signal_id))
            elif parsed.path.startswith("/api/optimization-signals/") and parsed.path.endswith("/reject"):
                signal_id = parsed.path.split("/")[4]
                self.respond_json(self.reject_signal(signal_id))
            elif parsed.path == "/api/reviews/llm/rerun":
                self.respond_json(self.rerun_llm_review(params["date"]))
            elif parsed.path.startswith("/api/reviews/preopen-strategies/") and parsed.path.endswith("/rerun"):
                gene_id = parsed.path.split("/")[4]
                self.respond_json(self.rerun_preopen_strategy_review(gene_id, params))
            else:
                self.respond_json({"error": "not found"}, status=404)
        except Exception as exc:
            self.respond_json({"error": str(exc)}, status=500)

    def db(self):
        conn = connect(self.database_path)
        init_db(conn)
        seed_default_genes(conn)
        return conn

    def dashboard(self, date: str | None):
        conn = self.db()
        try:
            current_date = date or latest_trading_date(conn)
            if not current_date:
                return self.runtime_context.as_payload() | {"date": None, "picks": [], "performance": [], "runs": [], "data_quality": []}
            quality_summary = data_quality_summary(conn, current_date)
            market = quality_summary.get("market_environment") or {}
            evidence_summary = evidence_status_payload(conn, current_date)
            return self.runtime_context.as_payload() | {
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
                "runs": rows_to_dicts(conn.execute("SELECT * FROM research_runs WHERE trading_date = ?", (current_date,))),
                "data_quality": rows_to_dicts(
                    conn.execute("SELECT * FROM price_source_checks WHERE trading_date = ? LIMIT 50", (current_date,))
                ),
                "data_status": data_source_status(conn, current_date),
                "data_quality_summary": quality_summary,
                "evidence_status": evidence_summary,
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

    def data_status(self, params: dict[str, str]):
        conn = self.db()
        try:
            return data_source_status(conn, params.get("date"))
        finally:
            conn.close()

    def data_quality(self, params: dict[str, str]):
        conn = self.db()
        try:
            return data_quality_rows(
                conn,
                params["date"],
                status=params.get("status"),
                limit=int(params.get("limit", "200")),
            )
        finally:
            conn.close()

    def factor_status(self, params: dict[str, str]):
        conn = self.db()
        try:
            return factor_status(conn, params["date"])
        finally:
            conn.close()

    def stock_factors(self, stock_code: str, params: dict[str, str]):
        conn = self.db()
        try:
            return stock_factors(conn, stock_code, params["date"])
        finally:
            conn.close()

    def sector_factors(self, params: dict[str, str]):
        conn = self.db()
        try:
            return sector_factors(conn, params["date"])
        finally:
            conn.close()

    def evidence_status(self, params: dict[str, str]):
        conn = self.db()
        try:
            return evidence_status_payload(conn, params["date"])
        finally:
            conn.close()

    def stock_evidence(self, stock_code: str, params: dict[str, str]):
        conn = self.db()
        try:
            return stock_evidence(conn, stock_code, params["date"])
        finally:
            conn.close()

    def data_sync(self, params: dict[str, str]):
        conn = self.db()
        try:
            return run_data_sync(
                conn,
                params.get("dataset", "all"),
                params["date"],
                source=params.get("source", "all"),
                limit=int(params["limit"]) if params.get("limit") else None,
                offset=int(params.get("offset", "0")),
                batch_size=int(params.get("batch_size", "100")),
                resume=parse_bool(params.get("resume")),
                max_retries=int(params.get("max_retries", "1")),
                throttle_seconds=float(params.get("throttle_seconds", "0")),
                publish_canonical=parse_bool(params.get("publish_canonical")),
            )
        finally:
            conn.close()

    def picks(self, params: dict[str, str]):
        conn = self.db()
        try:
            date = params["date"]
            clauses = ["trading_date = ?"]
            values: list[str] = [date]
            if params.get("gene_id"):
                clauses.append("strategy_gene_id = ?")
                values.append(params["gene_id"])
            if params.get("horizon"):
                clauses.append("horizon = ?")
                values.append(params["horizon"])
            return rows_to_dicts(
                conn.execute(f"SELECT * FROM pick_decisions WHERE {' AND '.join(clauses)} ORDER BY score DESC", values)
            )
        finally:
            conn.close()

    def genes(self):
        conn = self.db()
        try:
            rows = rows_to_dicts(conn.execute("SELECT * FROM strategy_genes ORDER BY gene_id"))
            perf = {item["strategy_gene_id"]: item for item in summarize_performance(conn)}
            for row in rows:
                row["performance"] = perf.get(row["gene_id"])
            return rows
        finally:
            conn.close()

    def gene_performance(self, gene_id: str):
        conn = self.db()
        try:
            return {"gene_id": gene_id, "summary": summarize_performance(conn)}
        finally:
            conn.close()

    def optimization_signals(self, params: dict[str, str]):
        conn = self.db()
        try:
            return list_optimization_signals(
                conn,
                gene_id=params.get("gene_id"),
                status=params.get("status"),
                limit=int(params.get("limit", "200")),
            )
        finally:
            conn.close()

    def accept_signal(self, signal_id: str):
        conn = self.db()
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

    def reject_signal(self, signal_id: str):
        conn = self.db()
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

    def stock_review(self, stock_code: str, params: dict[str, str]):
        conn = self.db()
        try:
            return stock_review(conn, stock_code, params["date"], params.get("gene_id"))
        finally:
            conn.close()

    def stock_review_history(self, stock_code: str, params: dict[str, str]):
        conn = self.db()
        try:
            return stock_review_history(conn, stock_code, params["start"], params["end"], params.get("gene_id"))
        finally:
            conn.close()

    def rerun_stock_review(self, stock_code: str, params: dict[str, str]):
        conn = self.db()
        try:
            clauses = ["trading_date = ?", "stock_code = ?"]
            values: list[str] = [params["date"], stock_code]
            if params.get("gene_id"):
                clauses.append("strategy_gene_id = ?")
                values.append(params["gene_id"])
            rows = conn.execute(f"SELECT decision_id FROM pick_decisions WHERE {' AND '.join(clauses)}", values).fetchall()
            for row in rows:
                review_decision(conn, row["decision_id"])
            conn.commit()
            return stock_review(conn, stock_code, params["date"], params.get("gene_id"))
        finally:
            conn.close()

    def preopen_strategy_reviews(self, params: dict[str, str]):
        conn = self.db()
        try:
            return list_preopen_strategy_reviews(conn, params["date"])
        finally:
            conn.close()

    def preopen_strategy_review(self, gene_id: str, params: dict[str, str]):
        conn = self.db()
        try:
            return get_preopen_strategy_review(conn, gene_id, params["date"])
        finally:
            conn.close()

    def rerun_preopen_strategy_review(self, gene_id: str, params: dict[str, str]):
        conn = self.db()
        try:
            rows = conn.execute(
                "SELECT decision_id FROM pick_decisions WHERE trading_date = ? AND strategy_gene_id = ?",
                (params["date"], gene_id),
            ).fetchall()
            for row in rows:
                review_decision(conn, row["decision_id"])
            run_blindspot_review(conn, params["date"])
            review_gene(conn, gene_id=gene_id, period_start=params["date"], period_end=params["date"])
            conn.commit()
            return get_preopen_strategy_review(conn, gene_id, params["date"])
        finally:
            conn.close()

    def evolution_events(self, params: dict[str, str]):
        conn = self.db()
        try:
            limit = int(params.get("limit", "100"))
            gene_id = params.get("gene_id")
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

    def propose_evolution(self, params: dict[str, str]):
        conn = self.db()
        try:
            return propose_strategy_evolution(
                conn,
                period_start=params["start"],
                period_end=params["end"],
                gene_id=params.get("gene_id"),
                min_trades=int(params.get("min_trades", "20")),
                min_signal_samples=int(params.get("min_signal_samples", "5")),
                min_signal_confidence=float(params.get("min_signal_confidence", "0.65")),
                min_signal_dates=int(params.get("min_signal_dates", "3")),
                dry_run=parse_bool(params.get("dry_run")),
            )
        finally:
            conn.close()

    def evolution_comparison(self, params: dict[str, str]):
        conn = self.db()
        try:
            return evolution_comparison(
                conn,
                gene_id=params.get("gene_id"),
                start=params.get("start"),
                end=params.get("end"),
            )
        finally:
            conn.close()

    def rollback_evolution(self, params: dict[str, str]):
        conn = self.db()
        try:
            return rollback_evolution(
                conn,
                child_gene_id=params.get("child_gene_id"),
                event_id=params.get("event_id"),
                reason=params.get("reason", "manual rollback"),
            )
        finally:
            conn.close()

    def promote_challenger(self, params: dict[str, str]):
        conn = self.db()
        try:
            return promote_challenger(
                conn,
                child_gene_id=params["child_gene_id"],
                reason=params.get("reason", "manual promotion"),
            )
        finally:
            conn.close()

    def runs(self, date: str | None):
        conn = self.db()
        try:
            if date:
                return rows_to_dicts(conn.execute("SELECT * FROM research_runs WHERE trading_date = ?", (date,)))
            return rows_to_dicts(conn.execute("SELECT * FROM research_runs ORDER BY started_at DESC LIMIT 100"))
        finally:
            conn.close()

    def trigger_run(self, phase: str, date: str):
        conn = self.db()
        try:
            return run_phase(conn, phase, date)
        finally:
            conn.close()

    def reviews(self, date: str):
        conn = self.db()
        try:
            return review_rows_for_date(conn, date)
        finally:
            conn.close()

    def llm_reviews(self, date: str):
        conn = self.db()
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
                d = dict(r)
                d["attribution"] = json.loads(d.pop("attribution_json", "[]"))
                d["reason_check"] = json.loads(d.pop("reason_check_json", "{}"))
                d["suggested_signals"] = json.loads(d.pop("suggested_signals_json", "[]"))
                if d.get("prompt_tokens") is not None:
                    d["token_usage"] = {
                        "prompt_tokens": d.pop("prompt_tokens"),
                        "completion_tokens": d.pop("completion_tokens"),
                        "estimated_cost": d.pop("estimated_cost"),
                    }
                else:
                    for k in ("prompt_tokens", "completion_tokens", "estimated_cost"):
                        d.pop(k, None)
                result.append(d)
            return result
        finally:
            conn.close()

    def rerun_llm_review(self, date: str):
        conn = self.db()
        try:
            from .llm_review import run_llm_review
            return run_llm_review(conn, date)
        finally:
            conn.close()

    def memory_search(self, q: str, limit: int):
        conn = self.db()
        try:
            return search_memory(conn, q, limit)
        finally:
            conn.close()

    def blindspots(self, date: str):
        conn = self.db()
        try:
            return rows_to_dicts(conn.execute("SELECT * FROM blindspot_reports WHERE trading_date = ? ORDER BY rank", (date,)))
        finally:
            conn.close()

    def graph_query(self, params: dict[str, str]):
        conn = self.db()
        try:
            return query_graph(conn, params.get("node_type"), int(params.get("limit", "100")))
        finally:
            conn.close()

    def respond_json(self, payload, status: int = 200) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")


def parse_bool(value: str | None) -> bool:
    return str(value or "").lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    run_server()
