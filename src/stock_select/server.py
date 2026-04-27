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
from .llm_config import DEEPSEEK_MODELS, get_model_override, resolve_llm_config, set_model_override
from .memory import search_memory
from .optimization_signals import list_optimization_signals
from .repository import latest_trading_date, review_rows_for_date, rows_to_dicts
from .review_packets import stock_review, stock_review_history
from .review_analysts import get_analyst_reviews_for_date
from .runtime import resolve_runtime
from .simulator import summarize_performance
from .strategies import seed_default_genes
from .system_review import review_summary
from .stock_views import search_stocks


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
    except Exception:
        pass

    try:
        from .sentiment_cycle import get_sentiment_cycle, generate_sentiment_cycle
        cycle = get_sentiment_cycle(conn, trading_date)
        if cycle is None:
            cycle = generate_sentiment_cycle(conn, trading_date)
        if cycle:
            result["sentiment_cycle"] = _to_dict(cycle)
    except Exception:
        pass


def _load_sector_quant(conn, stock_code: str, trading_date: str, result: dict) -> None:
    """Load sector analysis, stock quant, psychology review, and next day plan."""
    # Sector analysis
    try:
        from .sector_analysis import analyze_all_sectors, get_top_sectors
        sectors = get_top_sectors(conn, trading_date, limit=5)
        if sectors:
            result["sector_analysis"] = {"top_sectors": [dict(s.__dict__) if hasattr(s, '__dict__') else s for s in sectors]}
        else:
            sectors = analyze_all_sectors(conn, trading_date)
            if sectors:
                result["sector_analysis"] = {"top_sectors": [dict(s.__dict__) if hasattr(s, '__dict__') else s for s in sectors[:5]]}
    except Exception:
        pass

    # Stock quant
    try:
        from .stock_quant import build_stock_quant_report
        quant = build_stock_quant_report(conn, stock_code, trading_date)
        if quant:
                result["stock_quant"] = _to_dict(quant)
    except Exception:
        pass

    # Psychology review
    try:
        from .psychology_review import get_psychology_review, generate_psychology_review
        decisions = result.get("decisions", [])
        if decisions:
            decision = decisions[0]
            review_id = decision.get("review_id", "")
            if review_id:
                psych = get_psychology_review(conn, review_id)
                if psych is None:
                    psych = generate_psychology_review(conn, review_id)
                if psych:
                    result["psychology_review"] = _to_dict(psych)
    except Exception:
        pass

    # Next day plan
    try:
        from .next_day_plan import get_next_day_plan, generate_next_day_plan
        decisions = result.get("decisions", [])
        if decisions:
            decision = decisions[0]
            review_id = decision.get("review_id", "")
            if review_id:
                plan = get_next_day_plan(conn, review_id)
                if plan is None:
                    plan = generate_next_day_plan(conn, review_id)
                if plan:
                    result["next_day_plan"] = _to_dict(plan)
    except Exception:
        pass

    # Capital flow
    try:
        from .capital_flow import build_capital_flow_report
        cf = build_capital_flow_report(conn, stock_code, trading_date)
        if cf:
            result["capital_flow"] = _to_dict(cf)
    except Exception:
        pass

    # Custom sector tags
    try:
        from .stock_classifier import get_custom_sector_tags, classify_custom_sectors
        tags = get_custom_sector_tags(conn, stock_code, trading_date)
        if not tags:
            # Run classification if not yet done
            classify_custom_sectors(conn, trading_date)
            tags = get_custom_sector_tags(conn, stock_code, trading_date)
        if tags:
            result["custom_sector_tags"] = tags
    except Exception:
        pass


def _to_dict(obj):
    """Recursively convert dataclass to dict."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_to_dict(x) for x in obj]
    if hasattr(obj, '__dataclass_fields__'):
        return {k: _to_dict(v) for k, v in obj.__dict__.items()}
    if hasattr(obj, '__dict__'):
        return {k: _to_dict(v) for k, v in obj.__dict__.items()}
    return obj


def _generate_stock_ai_summary(
    conn, result: dict, stock_code: str, trading_date: str
) -> str | None:
    """用 LLM 生成自然语言复盘总结。"""
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

        import httpx
        if config.provider == "deepseek":
            model = config.model if hasattr(config, 'model') else "deepseek-chat"
            resp = httpx.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 500},
                timeout=30,
            )
            data = resp.json()
            return data.get("choices", [{}])[0].get("message", {}).get("content", "").strip() or None
        elif config.provider == "anthropic":
            base_url = config.base_url or "https://api.anthropic.com"
            resp = httpx.post(
                f"{base_url}/v1/messages",
                headers={"x-api-key": config.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": config.model, "max_tokens": 500, "messages": [{"role": "user", "content": prompt}]},
                timeout=30,
            )
            data = resp.json()
            return data.get("content", [{}])[0].get("text", "").strip() or None
        elif config.provider == "openai":
            base_url = config.base_url or "https://api.openai.com/v1"
            resp = httpx.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"},
                json={"model": config.model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 500},
                timeout=30,
            )
            data = resp.json()
            return data.get("choices", [{}])[0].get("message", {}).get("content", "").strip() or None
    except Exception:
        return None
    return None


def run_server(host: str = "127.0.0.1", port: int = 18425, db_path: str | Path | None = None, mode: str = "demo") -> None:
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
            elif parsed.path == "/api/config":
                self.respond_json(self.get_config())
            elif parsed.path == "/api/picks":
                self.respond_json(self.picks(params))
            elif parsed.path == "/api/stocks/search":
                self.respond_json(self.stock_search(params))
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
            elif parsed.path.startswith("/api/reviews/custom-sectors/"):
                stock_code = parsed.path.split("/")[4]
                self.respond_json(self.custom_sector_tags(stock_code, params))
            elif parsed.path == "/api/reviews/preopen-strategies":
                self.respond_json(self.preopen_strategy_reviews(params))
            elif parsed.path.startswith("/api/reviews/preopen-strategies/"):
                gene_id = parsed.path.split("/")[4]
                self.respond_json(self.preopen_strategy_review(gene_id, params))
            elif parsed.path == "/api/reviews":
                self.respond_json(self.reviews(params["date"]))
            elif parsed.path == "/api/reviews/llm":
                self.respond_json(self.llm_reviews(params["date"]))
            elif parsed.path == "/api/reviews/analysts":
                self.respond_json(self.analyst_reviews(params["date"]))
            elif parsed.path == "/api/optimization-signals":
                self.respond_json(self.optimization_signals(params))
            elif parsed.path == "/api/memory/search":
                self.respond_json(self.memory_search(params.get("q", ""), int(params.get("limit", "10"))))
            elif parsed.path == "/api/blindspots":
                self.respond_json(self.blindspots(params["date"]))
            elif parsed.path == "/api/graph/query":
                self.respond_json(self.graph_query(params))
            elif parsed.path == "/api/reviews/history/hypothetical":
                self.respond_json(self.hypothetical_review_history(params))
            elif parsed.path == "/api/reviews/history/strategy-picks":
                self.respond_json(self.strategy_picks_history(params))
            elif parsed.path.startswith("/api/reviews/steps/"):
                session_id = parsed.path.split("/")[-1]
                self.respond_json(self.review_steps(session_id))
            elif parsed.path == "/api/system/status":
                self.respond_json(self.system_status(params.get("date")))
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
            elif parsed.path == "/api/config/model":
                self.respond_json(self.set_config_model(self.read_body()))
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

    def stock_search(self, params: dict[str, str]):
        conn = self.db()
        try:
            return search_stocks(conn, params.get("q", ""), limit=int(params.get("limit", "12")))
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
        import uuid as _uuid
        from .step_logger import init_session, log_step
        session_id = f"review_{stock_code}_{params.get('date', '')}_{_uuid.uuid4().hex[:8]}"
        init_session(session_id)
        conn = self.db()
        try:
            log_step(session_id, f"开始复盘 {stock_code}",
                     f"日期={params.get('date', '')}, gene_id={params.get('gene_id', 'default')}",
                     request_data={"stock_code": stock_code, "date": params.get("date", ""), "gene_id": params.get("gene_id")})
            result = stock_review(conn, stock_code, params["date"], params.get("gene_id"))
            result["_session_id"] = session_id

            if result.get("hypothetical"):
                log_step(session_id, "触发假设性复盘",
                         "无策略决策记录，启动多维度实时分析",
                         response_data={"stock_code": stock_code, "hypothetical": True})
                conn.execute(
                    "INSERT OR IGNORE INTO hypothetical_review_log (stock_code, trading_date) VALUES (?, ?)",
                    (stock_code, params["date"]),
                )
                conn.commit()
            else:
                log_step(session_id, "找到策略决策记录",
                         f"从数据库加载复盘数据",
                         response_data={"stock_code": stock_code, "hypothetical": False, "decisions_count": len(result.get("decisions", []))})

            log_step(session_id, "加载市场环境与情绪周期",
                     "查询市场概览、涨跌家数、情绪周期阶段",
                     request_data={"trading_date": params.get("date", "")})
            _load_market_context(conn, params.get("date", ""), result)
            market_ok = result.get("market_overview") is not None
            sentiment_ok = result.get("sentiment_cycle") is not None
            log_step(session_id, "市场环境加载完成",
                     f"市场概览: {'有' if market_ok else '无'}, 情绪周期: {'有' if sentiment_ok else '无'}",
                     completed=True,
                     response_data={"market_overview": market_ok, "sentiment_cycle": sentiment_ok})
            log_step(session_id, "加载行业分析与量化因子",
                     "查询行业板块、连板形态、均线量价、资金流向",
                     request_data={"stock_code": stock_code})
            _load_sector_quant(conn, stock_code, params.get("date", ""), result)
            sq = {k: result.get(k) is not None for k in ["sector_analysis", "stock_quant", "capital_flow", "custom_sector_tags"]}
            log_step(session_id, "行业量化加载完成",
                     ", ".join(f"{k}: {'有' if v else '无'}" for k, v in sq.items()),
                     completed=True,
                     response_data=sq)

            # AI summary
            log_step(session_id, "生成 AI 解读", "调用 LLM API 生成自然语言总结", completed=False)
            ai_summary = _generate_stock_ai_summary(conn, result, stock_code, params.get("date", ""))
            result["ai_summary"] = ai_summary
            if ai_summary:
                log_step(session_id, "AI 解读生成成功",
                         ai_summary[:300],
                         completed=True,
                         response_data={"ai_summary_length": len(ai_summary), "ai_summary_preview": ai_summary[:200]})
            else:
                log_step(session_id, "AI 解读跳过",
                         "LLM 未配置或 API 调用失败，跳过 AI 总结",
                         completed=True,
                         response_data={"reason": "LLM not configured or API failed"})

            # Decisions summary
            decisions = result.get("decisions", [])
            decision_keys = []
            for d in decisions:
                dk = {k: v for k, v in d.items() if k in ("strategy_gene_id", "verdict", "return_pct", "primary_driver")}
                decision_keys.append(dk)
            log_step(session_id, "复盘完成",
                     f"返回 {len(result)} 个字段，{len(decisions)} 个决策",
                     completed=True,
                     response_data={
                         "total_fields": len(result),
                         "field_names": list(result.keys()),
                         "decisions": decision_keys,
                     })
            return result
        finally:
            conn.close()

    def stock_review_history(self, stock_code: str, params: dict[str, str]):
        conn = self.db()
        try:
            return stock_review_history(conn, stock_code, params["start"], params["end"], params.get("gene_id"))
        finally:
            conn.close()

    def custom_sector_tags(self, stock_code: str, params: dict[str, str]):
        conn = self.db()
        try:
            from .stock_classifier import get_custom_sector_tags, SECTOR_DISPLAY_NAMES
            date = params.get("date", params.get("trading_date", ""))
            tags = get_custom_sector_tags(conn, stock_code, date)
            return {
                "tags": [
                    {"key": t, "display": SECTOR_DISPLAY_NAMES.get(t, t)}
                    for t in tags
                ],
            }
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

    def analyst_reviews(self, date: str):
        conn = self.db()
        try:
            return get_analyst_reviews_for_date(conn, date)
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
                d["suggested_errors"] = json.loads(d.pop("suggested_errors_json", "[]"))
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

    def get_config(self) -> dict:
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

    def set_config_model(self, body: str) -> dict:
        try:
            data = json.loads(body)
            model = data.get("model", "")
        except (json.JSONDecodeError, TypeError):
            return {"error": "invalid JSON"}
        if not model:
            return {"error": "model required"}
        set_model_override(model)
        return {"status": "ok", "model": model}

    def hypothetical_review_history(self, params: dict) -> dict:
        from .repository import rows_to_dicts
        conn = self.db()
        try:
            limit = int(params.get("limit", "20"))
            rows = rows_to_dicts(conn.execute(
                "SELECT stock_code, trading_date, reviewed_at FROM hypothetical_review_log ORDER BY reviewed_at DESC LIMIT ?",
                (limit,),
            ))
            return {"reviews": rows}
        finally:
            conn.close()

    def strategy_picks_history(self, params: dict) -> dict:
        from .repository import rows_to_dicts
        conn = self.db()
        try:
            date = params.get("date", "")
            limit = int(params.get("limit", "20"))
            clauses = []
            p = []
            if date:
                clauses.append("trading_date = ?")
                p.append(date)
            clauses.append("1=1")
            rows = rows_to_dicts(conn.execute(
                f"""
                SELECT DISTINCT d.stock_code, d.trading_date, d.strategy_gene_id, d.action, d.confidence,
                       s.name as stock_name, s.industry
                FROM pick_decisions d
                LEFT JOIN stocks s ON s.stock_code = d.stock_code
                WHERE {' AND '.join(clauses)}
                ORDER BY d.trading_date DESC, d.stock_code
                LIMIT ?
                """,
                [*p, limit],
            ))
            return {"picks": rows}
        finally:
            conn.close()

    def review_steps(self, session_id: str) -> dict:
        from .step_logger import get_session_steps
        return {"steps": get_session_steps(session_id)}

    def system_status(self, date: str | None) -> dict:
        conn = self.db()
        try:
            current_date = date or latest_trading_date(conn)
            return self.runtime_context.as_payload() | {"date": current_date}
        finally:
            conn.close()

    def read_body(self) -> str:
        length = int(self.headers.get("Content-Length", 0))
        if length > 0:
            return self.rfile.read(length).decode("utf-8")
        return "{}"

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
