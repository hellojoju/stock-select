from __future__ import annotations

import sqlite3
from typing import Any

from . import repository


def _normalize_stock_code(conn: sqlite3.Connection, stock_code: str) -> str | None:
    """将用户输入的股票代码归一化为 DB 中的规范格式（如 "002272" → "002272.SZ"）。

    尝试顺序：精确匹配 → LIKE 前缀匹配 → 自动加后缀匹配
    """
    code = stock_code.strip()
    if not code:
        return None

    # 1. 精确匹配
    row = conn.execute("SELECT stock_code FROM stocks WHERE stock_code = ?", (code,)).fetchone()
    if row:
        return row["stock_code"]

    # 2. 前缀匹配（如 "002272" 匹配 "002272.SZ"）
    row = conn.execute(
        "SELECT stock_code FROM stocks WHERE stock_code LIKE ? AND stock_code NOT LIKE '%.%%' LIMIT 1",
        (f"{code}%",),
    ).fetchone()
    if row:
        return row["stock_code"]

    # 3. 带通配符前缀匹配（如 "002272" 匹配 "002272.SZ"）
    row = conn.execute(
        "SELECT stock_code FROM stocks WHERE stock_code LIKE ? LIMIT 1",
        (f"{code}.%",),
    ).fetchone()
    if row:
        return row["stock_code"]

    return None


def stock_review(conn: sqlite3.Connection, stock_code: str, trading_date: str, gene_id: str | None = None) -> dict[str, Any]:
    # 归一化股票代码
    stock_code = _normalize_stock_code(conn, stock_code) or stock_code
    stock = conn.execute("SELECT * FROM stocks WHERE stock_code = ?", (stock_code,)).fetchone()

    # 如果股票不在 DB 中，尝试插入基本记录（为假设性复盘做准备）
    if stock is None:
        # 根据代码前缀推测交易所
        exchange = "SH" if stock_code.startswith(("60", "68")) else "SZ"
        conn.execute(
            "INSERT OR IGNORE INTO stocks (stock_code, name, exchange) VALUES (?, ?, ?)",
            (stock_code, stock_code, exchange),
        )
        conn.commit()
        stock = conn.execute("SELECT * FROM stocks WHERE stock_code = ?", (stock_code,)).fetchone()
    clauses = ["d.stock_code = ?", "d.trading_date = ?"]
    params: list[Any] = [stock_code, trading_date]
    if gene_id:
        clauses.append("d.strategy_gene_id = ?")
        params.append(gene_id)
    decision_rows = conn.execute(
        f"""
        SELECT d.*, p.score, p.confidence, p.position_pct, o.entry_price,
               o.close_price, o.return_pct AS outcome_return_pct
        FROM decision_reviews d
        JOIN pick_decisions p ON p.decision_id = d.decision_id
        LEFT JOIN outcomes o ON o.decision_id = d.decision_id
        WHERE {' AND '.join(clauses)}
        ORDER BY d.strategy_gene_id
        """,
        params,
    ).fetchall()
    decisions = [decision_review_detail(conn, row["review_id"]) for row in decision_rows]
    blindspot = conn.execute(
        "SELECT * FROM blindspot_reviews WHERE trading_date = ? AND stock_code = ?",
        (trading_date, stock_code),
    ).fetchone()

    # Graph context (S5.1)
    try:
        graph_context = stock_graph_context(conn, stock_code, trading_date)
    except Exception:
        graph_context = {"related_documents": [], "graph_edges": [], "industry_peers": []}

    # Evidence timeline (S5.2)
    try:
        evidence_timeline = build_evidence_timeline(conn, stock_code, trading_date)
    except Exception:
        evidence_timeline = {"preopen": [], "postclose": [], "postdecision": []}

    result = {
        "stock": dict(stock) if stock else {"stock_code": stock_code},
        "trading_date": trading_date,
        "decisions": decisions,
        "blindspot": dict(blindspot) if blindspot else None,
        "domain_facts": domain_facts(conn, stock_code, trading_date),
        "graph_context": graph_context,
        "evidence_timeline": evidence_timeline,
    }

    # 无真实决策时，触发假设性深度复盘
    if not decisions:
        from .hypothetical_review import hypothetical_stock_review
        hypo = hypothetical_stock_review(conn, stock_code, trading_date)
        if hypo:
            return hypo | {"hypothetical": True}
        # 假设性复盘也失败（数据不足/停牌等），返回明确的空状态
        stock_data = dict(stock) if stock else {"stock_code": stock_code}
        return {
            "stock": stock_data,
            "trading_date": trading_date,
            "decisions": [],
            "blindspot": None,
            "domain_facts": {},
            "graph_context": {"related_documents": [], "graph_edges": [], "industry_peers": []},
            "evidence_timeline": {"preopen": [], "postclose": [], "postdecision": []},
            "hypothetical": True,
            "data_insufficient": True,
            "data_insufficient_reason": "该股票当日无行情数据（可能停牌或数据未入库），无法进行假设性复盘",
        }

    return result


def stock_review_history(
    conn: sqlite3.Connection,
    stock_code: str,
    start: str,
    end: str,
    gene_id: str | None = None,
) -> dict[str, Any]:
    stock_code = _normalize_stock_code(conn, stock_code) or stock_code
    clauses = ["stock_code = ?", "trading_date BETWEEN ? AND ?"]
    params: list[Any] = [stock_code, start, end]
    if gene_id:
        clauses.append("strategy_gene_id = ?")
        params.append(gene_id)
    rows = repository.rows_to_dicts(
        conn.execute(
            f"""
            SELECT review_id, decision_id, trading_date, strategy_gene_id, verdict,
                   primary_driver, return_pct, relative_return_pct, summary
            FROM decision_reviews
            WHERE {' AND '.join(clauses)}
            ORDER BY trading_date DESC, strategy_gene_id
            """,
            params,
        )
    )
    return {
        "stock_code": stock_code,
        "start": start,
        "end": end,
        "reviews": rows,
        "summary": {
            "review_count": len(rows),
            "avg_return_pct": mean([float(row["return_pct"]) for row in rows]),
        },
    }


def decision_review_detail(conn: sqlite3.Connection, review_id: str) -> dict[str, Any]:
    review = conn.execute("SELECT * FROM decision_reviews WHERE review_id = ?", (review_id,)).fetchone()
    if review is None:
        raise KeyError(f"Unknown review_id: {review_id}")
    factors = repository.rows_to_dicts(
        conn.execute(
            "SELECT * FROM factor_review_items WHERE review_id = ? ORDER BY factor_type",
            (review_id,),
        )
    )
    errors = repository.rows_to_dicts(
        conn.execute(
            "SELECT * FROM review_errors WHERE review_scope = 'decision' AND review_id = ? ORDER BY severity DESC",
            (review_id,),
        )
    )
    evidence = repository.rows_to_dicts(
        conn.execute(
            "SELECT * FROM review_evidence WHERE review_id = ? ORDER BY source_type",
            (review_id,),
        )
    )
    signals = repository.rows_to_dicts(
        conn.execute(
            "SELECT * FROM optimization_signals WHERE source_type = 'decision_review' AND source_id = ? ORDER BY created_at",
            (review_id,),
        )
    )
    return dict(review) | {
        "factor_items": factors,
        "errors": errors,
        "evidence": evidence,
        "optimization_signals": signals,
    }


def domain_facts(conn: sqlite3.Connection, stock_code: str, trading_date: str) -> dict[str, list[dict[str, Any]]]:
    financial = repository.latest_financial_actuals_before(conn, stock_code, trading_date)
    return {
        "earnings_surprises": repository.rows_to_dicts(
            repository.latest_earnings_surprises_before(conn, stock_code, trading_date)
        ),
        "financial_actuals": repository.rows_to_dicts(
            [financial] if financial is not None else []
        ),
        "analyst_expectations": repository.rows_to_dicts(
            repository.latest_expectations_before(conn, stock_code, trading_date)
        ),
        "order_contract_events": repository.rows_to_dicts(
            repository.recent_order_contract_events_before(conn, stock_code, trading_date)
        ),
        "business_kpi_actuals": repository.rows_to_dicts(
            repository.recent_business_kpis_before(conn, stock_code, trading_date)
        ),
        "risk_events": repository.rows_to_dicts(
            repository.recent_risk_events_before(conn, stock_code, trading_date)
        ),
    }


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def stock_graph_context(
    conn: sqlite3.Connection,
    stock_code: str,
    trading_date: str,
) -> dict[str, Any]:
    """Get graph neighborhood for a stock on a given date (S5.1)."""
    # Documents related to this stock
    related_docs = conn.execute(
        """
        SELECT r.document_id, r.source, r.source_type, r.title, r.summary,
               r.published_at, r.source_url, dsl.relation_type, dsl.confidence
        FROM document_stock_links dsl
        JOIN raw_documents r ON r.document_id = dsl.document_id
        WHERE dsl.stock_code = ?
          AND (r.published_at <= ? OR r.published_at IS NULL)
        ORDER BY r.published_at DESC
        LIMIT 20
        """,
        (stock_code, trading_date),
    ).fetchall()

    # Graph edges for this stock
    stock_node = f"stock:{stock_code}"
    edges = conn.execute(
        """
        SELECT edge_type, confidence, props_json
        FROM graph_edges
        WHERE source_node_id = ? OR target_node_id = ?
        LIMIT 30
        """,
        (stock_node, stock_node),
    ).fetchall()

    # Industry peers
    industry_row = conn.execute(
        "SELECT industry FROM stocks WHERE stock_code = ?", (stock_code,)
    ).fetchone()
    peers = []
    if industry_row and industry_row["industry"]:
        peers = conn.execute(
            "SELECT stock_code, name FROM stocks WHERE industry = ? AND stock_code != ? LIMIT 5",
            (industry_row["industry"], stock_code),
        ).fetchall()

    return {
        "related_documents": [dict(d) for d in related_docs],
        "graph_edges": [dict(e) for e in edges],
        "industry_peers": [dict(p) for p in peers],
    }


def build_evidence_timeline(
    conn: sqlite3.Connection,
    stock_code: str,
    trading_date: str,
) -> dict[str, list[dict[str, Any]]]:
    """Build evidence timeline grouped by visibility (S5.2).

    Groups:
    - preopen: evidence visible before market open
    - postclose: evidence observed at/after close
    - postdecision: events that happened after the decision (don't penalize)
    """
    items: list[dict[str, Any]] = []

    # News/Announcements
    news_docs = conn.execute(
        """
        SELECT r.document_id, r.source, r.source_type, r.title, r.summary,
               r.published_at, r.source_url,
               CASE
                 WHEN r.published_at < ? THEN 'preopen'
                 WHEN r.published_at = ? THEN 'postclose'
                 ELSE 'postdecision'
               END AS visibility
        FROM document_stock_links dsl
        JOIN raw_documents r ON r.document_id = dsl.document_id
        WHERE dsl.stock_code = ?
        ORDER BY r.published_at
        """,
        (trading_date, trading_date, stock_code),
    ).fetchall()
    for d in news_docs:
        items.append({
            "evidence_id": d["document_id"],
            "source": d["source"],
            "source_type": d["source_type"],
            "title": d["title"],
            "summary": d["summary"],
            "published_at": d["published_at"],
            "source_url": d["source_url"],
            "visibility": d["visibility"],
            "confidence": "EXTRACTED",
        })

    # Event signals
    events = conn.execute(
        """
        SELECT event_id, event_type, title, summary, published_at,
               CASE
                 WHEN published_at < ? THEN 'preopen'
                 WHEN published_at = ? THEN 'postclose'
                 ELSE 'postdecision'
               END AS visibility
        FROM event_signals
        WHERE stock_code = ?
        ORDER BY published_at
        """,
        (trading_date, trading_date, stock_code),
    ).fetchall()
    for e in events:
        items.append({
            "evidence_id": e["event_id"],
            "source": "event_signals",
            "source_type": e["event_type"],
            "title": e["title"],
            "summary": e["summary"],
            "published_at": e["published_at"],
            "source_url": None,
            "visibility": e["visibility"],
            "confidence": "EXTRACTED",
        })

    # Risk events
    risks = conn.execute(
        """
        SELECT risk_event_id, risk_type, title, summary, publish_date,
               CASE
                 WHEN publish_date < ? THEN 'preopen'
                 WHEN publish_date = ? THEN 'postclose'
                 ELSE 'postdecision'
               END AS visibility
        FROM risk_events
        WHERE stock_code = ?
        ORDER BY publish_date
        """,
        (trading_date, trading_date, stock_code),
    ).fetchall()
    for r in risks:
        items.append({
            "evidence_id": r["risk_event_id"],
            "source": "risk_events",
            "source_type": r["risk_type"],
            "title": r["title"],
            "summary": r["summary"],
            "published_at": r["publish_date"],
            "source_url": None,
            "visibility": r["visibility"],
            "confidence": "EXTRACTED",
        })

    # Group by visibility
    timeline: dict[str, list[dict[str, Any]]] = {
        "preopen": [],
        "postclose": [],
        "postdecision": [],
    }
    for item in items:
        visibility = item.pop("visibility")
        timeline.setdefault(visibility, []).append(item)

    return timeline
