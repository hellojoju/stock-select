"""Retail-readable review summaries for individual stocks and overall strategy."""
from __future__ import annotations

import sqlite3
from typing import Any


def generate_review_summary(
    conn: sqlite3.Connection,
    stock_code: str,
    trading_date: str,
    gene_id: str | None = None,
) -> dict[str, Any]:
    """Generate a three-layer retail explanation for a stock review (S5.6).

    Output:
    - one_line_conclusion
    - what_happened
    - why_we_picked_it
    - supporting_evidence
    - contradicting_evidence
    - where_we_were_wrong
    - should_we_blame_strategy
    - what_to_do_next
    """
    # Get decision review
    clauses = ["d.stock_code = ?", "d.trading_date = ?"]
    params: list[Any] = [stock_code, trading_date]
    if gene_id:
        clauses.append("d.strategy_gene_id = ?")
        params.append(gene_id)

    review = conn.execute(
        f"""
        SELECT d.*, o.return_pct, o.max_drawdown_intraday_pct
        FROM decision_reviews d
        LEFT JOIN outcomes o ON o.decision_id = d.decision_id
        WHERE {' AND '.join(clauses)}
        ORDER BY d.created_at DESC
        LIMIT 1
        """,
        params,
    ).fetchone()

    if not review:
        return {"status": "no_review", "stock_code": stock_code, "trading_date": trading_date}

    review_dict = dict(review)
    return_pct = float(review_dict["return_pct"]) if review_dict["return_pct"] is not None else 0.0
    verdict = review_dict.get("verdict", "unknown")

    # Gather evidence
    preopen_evidence = conn.execute(
        """
        SELECT r.title, r.source, r.source_type, r.source_url, r.published_at
        FROM document_stock_links dsl
        JOIN raw_documents r ON r.document_id = dsl.document_id
        WHERE dsl.stock_code = ?
          AND (r.published_at < ? OR r.published_at IS NULL)
        ORDER BY r.published_at DESC
        LIMIT 5
        """,
        (stock_code, trading_date),
    ).fetchall()

    postclose_evidence = conn.execute(
        """
        SELECT r.title, r.source, r.source_type, r.source_url, r.published_at
        FROM document_stock_links dsl
        JOIN raw_documents r ON r.document_id = dsl.document_id
        WHERE dsl.stock_code = ?
          AND r.published_at >= ?
        ORDER BY r.published_at ASC
        LIMIT 5
        """,
        (stock_code, trading_date),
    ).fetchall()

    # Error analysis
    errors = conn.execute(
        """
        SELECT error_type, severity
        FROM review_errors
        WHERE review_scope = 'decision' AND review_id = ?
        ORDER BY severity DESC
        """,
        (review["review_id"],),
    ).fetchall()

    # Build summary
    stock_name = conn.execute(
        "SELECT name FROM stocks WHERE stock_code = ?", (stock_code,)
    ).fetchone()
    name = stock_name["name"] if stock_name else stock_code

    direction = "涨" if return_pct > 0 else "跌"
    magnitude = f"{abs(return_pct):.1%}"

    one_line = _build_one_line_conclusion(name, direction, magnitude, verdict, review_dict.get("primary_driver"))

    summary = {
        "stock_code": stock_code,
        "stock_name": name,
        "trading_date": trading_date,
        "return_pct": return_pct,
        "verdict": verdict,
        "one_line_conclusion": one_line,
        "what_happened": f"{name} 今天{direction}了 {magnitude}",
        "why_we_picked_it": _build_why_picked(review_dict.get("thesis_json"), preopen_evidence),
        "supporting_evidence": [dict(e) for e in preopen_evidence],
        "contradicting_evidence": [dict(e) for e in postclose_evidence],
        "where_we_were_wrong": _build_errors(errors),
        "should_we_blame_strategy": _blame_assessment(verdict, errors, preopen_evidence),
        "what_to_do_next": _next_steps(errors, review_dict.get("summary")),
    }
    return summary


def _build_one_line_conclusion(
    name: str, direction: str, magnitude: str, verdict: str, primary_driver: str | None
) -> str:
    driver_map = {
        "technical": "技术面",
        "fundamental": "基本面",
        "event": "事件驱动",
        "sector": "行业带动",
        "sentiment": "情绪面",
    }
    driver = driver_map.get(primary_driver or "", primary_driver or "综合因素")
    quality = "成功" if "correct" in verdict.lower() else "失败"
    return f"{name} {direction} {magnitude}，{quality}。主要由{driver}驱动。"


def _build_why_picked(thesis_json: str | None, evidence: list) -> str:
    parts = ["早盘我们看到了以下证据："]
    for i, ev in enumerate(evidence[:3], 1):
        parts.append(f"{i}. {ev.get('title', '相关资讯')}（来源：{ev.get('source', '未知')}）")
    if len(evidence) == 0:
        parts.append("（暂无相关新闻/公告证据）")
    return "\n".join(parts)


def _build_errors(errors: list) -> list[dict[str, str]]:
    error_names = {
        "missed_visible_event": "错过了可见的事件",
        "overweighted_technical": "过度依赖技术面",
        "ignored_risk": "忽略了风险信号",
        "data_missing": "数据缺失",
        "late_signal": "信号过晚",
        "execution_constraint": "执行约束",
        "threshold_too_strict": "阈值过于严格",
        "risk_overestimated": "风险被高估",
    }
    return [
        {"type": e["error_type"], "label": error_names.get(e["error_type"], e["error_type"]), "severity": e["severity"]}
        for e in errors
    ]


def _blame_assessment(verdict: str, errors: list, preopen_evidence: list) -> dict[str, str]:
    has_missed = any(e["error_type"] == "missed_visible_event" for e in errors)
    has_data_missing = any(e["error_type"] == "data_missing" for e in errors)

    if has_missed and preopen_evidence:
        return {
            "verdict": "是",
            "reason": "盘前有可见证据但策略未纳入，可以优化策略。",
        }
    if has_data_missing:
        return {
            "verdict": "不确定",
            "reason": "数据源缺失，优先补数据，不急着改参数。",
        }
    if "correct" in verdict.lower():
        return {
            "verdict": "否",
            "reason": "判断正确，无需惩罚策略。",
        }
    return {
        "verdict": "否",
        "reason": "可能是事后事件，不惩罚早盘策略。",
    }


def _next_steps(errors: list, review_summary: str | None) -> list[str]:
    steps: list[str] = []
    error_types = {e["error_type"] for e in errors}
    if "missed_visible_event" in error_types:
        steps.append("对策略增加该类事件的权重")
    if "data_missing" in error_types:
        steps.append("优先补充缺失的数据源")
    if "overweighted_technical" in error_types:
        steps.append("降低技术面权重，增加基本面验证")
    if "ignored_risk" in error_types:
        steps.append("增加风险因子惩罚阈值")
    if not steps:
        steps.append("继续保持当前策略参数")
    return steps
