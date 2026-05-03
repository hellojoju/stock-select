from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from . import repository
from .analyst_types import AnalystVerdict, AnalystFunc
from .optimization_signals import upsert_optimization_signal
from .analysts.contrarian import contrarian_analyst
from .analysts.fundamental_check import fundamental_check_analyst
from .analysts.risk_scanner import risk_scanner_analyst
from .analysts.trend_follower import trend_follower_analyst

REVIEW_ANALYSTS: dict[str, dict[str, Any]] = {
    "trend_follower": {
        "display_name": "趋势追踪分析师",
        "perspective": "量价趋势跟踪",
        "description": "从量价趋势角度评估选股，看趋势是否配合、量能是否支持",
        "analyst_func": trend_follower_analyst,
        "use_llm": False,
    },
    "fundamental_check": {
        "display_name": "基本面核查分析师",
        "perspective": "基本面验证",
        "description": "核查选股的财务数据支撑，判断基本面是否被高估或忽视",
        "analyst_func": fundamental_check_analyst,
        "use_llm": False,
    },
    "risk_scanner": {
        "display_name": "风险排查分析师",
        "perspective": "风险扫描",
        "description": "排查已知风险事件、监管问题、ST风险等负面因素",
        "analyst_func": risk_scanner_analyst,
        "use_llm": False,
    },
    "contrarian": {
        "display_name": "逆向思辨分析师",
        "perspective": "逆向思辨",
        "description": "从对立面审视选股逻辑，找出被忽略的反面证据和思维盲区",
        "analyst_func": contrarian_analyst,
        "use_llm": True,
    },
}


def ANALYST_REVIEWS_TABLE() -> str:
    return """
    CREATE TABLE IF NOT EXISTS analyst_reviews (
      analyst_review_id TEXT PRIMARY KEY,
      decision_id TEXT NOT NULL,
      trading_date TEXT NOT NULL,
      stock_code TEXT NOT NULL,
      strategy_gene_id TEXT NOT NULL,
      analyst_key TEXT NOT NULL,
      verdict TEXT NOT NULL,
      confidence REAL NOT NULL,
      reasoning TEXT NOT NULL,
      suggested_errors TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(decision_id, analyst_key)
    );
    """


def run_analyst_reviews(
    conn: sqlite3.Connection,
    trading_date: str,
    *,
    include_llm: bool = True,
) -> list[dict[str, Any]]:
    """Run registered analyst reviews for a given trading date.

    Deterministic review callers should pass ``include_llm=False`` so this
    function never performs an external LLM call as a side effect.
    """
    conn.executescript(ANALYST_REVIEWS_TABLE())

    decision_rows = conn.execute(
        """
        SELECT p.decision_id
        FROM pick_decisions p
        WHERE p.trading_date = ?
        """,
        (trading_date,),
    ).fetchall()

    results: list[dict[str, Any]] = []
    for decision_row in decision_rows:
        decision_id = decision_row["decision_id"]
        row = load_decision_row(conn, decision_id)
        if row is None:
            continue

        evidence = load_analyst_evidence(conn, row["stock_code"], row["trading_date"])

        for analyst_key, config in REVIEW_ANALYSTS.items():
            if config.get("use_llm") and not include_llm:
                continue
            try:
                verdict = config["analyst_func"](conn, decision_id, row, evidence)
                persist_analyst_verdict(conn, verdict, row)
                _emit_signals_from_verdict(conn, verdict, row)
                results.append({
                    "analyst_key": analyst_key,
                    "display_name": config["display_name"],
                    "decision_id": decision_id,
                    "stock_code": row["stock_code"],
                    "verdict": verdict.verdict,
                    "confidence": verdict.confidence,
                    "reasoning": verdict.reasoning,
                })
            except Exception as exc:
                results.append({
                    "analyst_key": analyst_key,
                    "display_name": config["display_name"],
                    "decision_id": decision_id,
                    "stock_code": row["stock_code"],
                    "verdict": "ERROR",
                    "confidence": 0.0,
                    "reasoning": [f"分析师执行异常: {exc}"],
                })

    conn.commit()
    return results


def load_decision_row(conn: sqlite3.Connection, decision_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT p.*, s.name AS stock_name, s.industry, s.is_st, s.listing_status,
               o.entry_price, o.close_price,
               o.return_pct, o.max_drawdown_intraday_pct, o.hit_sell_rule,
               c.packet_json, c.technical_score,
               c.fundamental_score, c.event_score, c.sector_score, c.risk_penalty,
               c.total_score,
               d.open, d.high, d.low, d.close, d.volume, d.amount,
               d.is_suspended, d.is_limit_up, d.is_limit_down
        FROM pick_decisions p
        JOIN stocks s ON s.stock_code = p.stock_code
        JOIN outcomes o ON o.decision_id = p.decision_id
        LEFT JOIN candidate_scores c
          ON c.trading_date = p.trading_date
         AND c.strategy_gene_id = p.strategy_gene_id
         AND c.stock_code = p.stock_code
        LEFT JOIN daily_prices d
          ON d.trading_date = p.trading_date
         AND d.stock_code = p.stock_code
        WHERE p.decision_id = ?
        """,
        (decision_id,),
    ).fetchone()


def load_analyst_evidence(conn: sqlite3.Connection, stock_code: str, trading_date: str) -> dict[str, Any]:
    evidence: dict[str, Any] = {}

    fin = repository.latest_financial_actuals_before(conn, stock_code, trading_date)
    evidence["financial_actuals"] = dict(fin) if fin else {}

    evidence["analyst_expectations"] = [
        dict(r) for r in repository.latest_expectations_before(conn, stock_code, trading_date)[:3]
    ]

    evidence["earnings_surprises"] = [
        dict(r) for r in repository.latest_earnings_surprises_before(conn, stock_code, trading_date)[:3]
    ]

    evidence["order_contracts"] = [
        dict(r) for r in repository.recent_order_contract_events_before(conn, stock_code, trading_date, limit=3)
    ]

    evidence["business_kpis"] = [
        dict(r) for r in repository.recent_business_kpis_before(conn, stock_code, trading_date, limit=3)
    ]

    evidence["risk_events"] = [
        dict(r) for r in repository.recent_risk_events_before(conn, stock_code, trading_date, limit=5)
    ]

    prices = conn.execute(
        """
        SELECT trading_date, open, high, low, close, volume, amount
        FROM daily_prices
        WHERE stock_code = ? AND trading_date <= ?
        ORDER BY trading_date DESC
        LIMIT 20
        """,
        (stock_code, trading_date),
    ).fetchall()
    evidence["recent_prices"] = [dict(r) for r in prices]

    return evidence


def persist_analyst_verdict(conn: sqlite3.Connection, verdict: AnalystVerdict, row: sqlite3.Row) -> None:
    review_id = build_analyst_review_id(verdict.decision_id, verdict.analyst_key)
    conn.execute(
        """
        INSERT INTO analyst_reviews(
          analyst_review_id, decision_id, trading_date, stock_code,
          strategy_gene_id, analyst_key, verdict, confidence,
          reasoning, suggested_errors
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(decision_id, analyst_key) DO UPDATE SET
          verdict = excluded.verdict,
          confidence = excluded.confidence,
          reasoning = excluded.reasoning,
          suggested_errors = excluded.suggested_errors
        """,
        (
            review_id,
            verdict.decision_id,
            row["trading_date"],
            row["stock_code"],
            row["strategy_gene_id"],
            verdict.analyst_key,
            verdict.verdict,
            verdict.confidence,
            json.dumps(verdict.reasoning, ensure_ascii=False),
            json.dumps(verdict.suggested_errors, ensure_ascii=False),
        ),
    )


def build_analyst_review_id(decision_id: str, analyst_key: str) -> str:
    raw = f"analyst_{decision_id}_{analyst_key}"
    return "arev_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14]


# Error type → optimization signal mapping
_ERROR_SIGNAL_MAP: dict[str, tuple[str, str, str]] = {
    "overweighted_technical": ("decrease_weight", "technical_score", "down"),
    "underweighted_fundamental": ("increase_weight", "fundamental_score", "up"),
    "risk_underestimated": ("increase_risk_penalty", "risk_penalty", "up"),
    "missed_risk_event": ("increase_weight", "event_score", "up"),
    "entry_unfillable": ("add_filter", "entry_filter", "add"),
    "financial_actual_missing": ("increase_weight", "fundamental_score", "up"),
    "missed_earnings_surprise": ("increase_weight", "earnings_surprise_weight", "up"),
    "liquidity_ignored": ("add_filter", "suspension_filter", "add"),
    "false_catalyst": ("decrease_weight", "event_score", "down"),
    "data_missing": ("decrease_weight", "fundamental_score", "down"),
    "sector_rotation_missed": ("increase_weight", "sector_score", "up"),
}


def _emit_signals_from_verdict(
    conn: sqlite3.Connection,
    verdict: AnalystVerdict,
    row: sqlite3.Row,
) -> None:
    """Create optimization signals from analyst DISAGREE verdicts."""
    if verdict.verdict != "DISAGREE" or not verdict.suggested_errors:
        return

    review_id = build_analyst_review_id(verdict.decision_id, verdict.analyst_key)
    gene_id = row["strategy_gene_id"]

    for error_type in verdict.suggested_errors:
        mapping = _ERROR_SIGNAL_MAP.get(error_type)
        if mapping is None:
            continue
        signal_type, param_name, direction = mapping

        upsert_optimization_signal(
            conn,
            source_type="analyst_review",
            source_id=review_id,
            target_gene_id=gene_id,
            scope="gene",
            scope_key=gene_id,
            signal_type=signal_type,
            param_name=param_name,
            direction=direction,
            strength=verdict.confidence,
            confidence=verdict.confidence,
            reason="; ".join(verdict.reasoning[:2]),
            evidence_ids=[f"analyst:{verdict.analyst_key}"],
            status="candidate",
        )


def get_analyst_reviews_for_date(conn: sqlite3.Connection, trading_date: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT a.*, s.name AS stock_name
        FROM analyst_reviews a
        JOIN stocks s ON s.stock_code = a.stock_code
        WHERE a.trading_date = ?
        ORDER BY a.stock_code, a.analyst_key
        """,
        (trading_date,),
    ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["reasoning"] = json.loads(row["reasoning"]) if isinstance(row["reasoning"], str) else row["reasoning"]
        d["suggested_errors"] = json.loads(row["suggested_errors"]) if isinstance(row["suggested_errors"], str) else row["suggested_errors"]
        result.append(d)
    return result
