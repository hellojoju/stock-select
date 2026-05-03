"""Pick Evaluator: score and rank pre-open picks against plan and history."""
from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import dataclass
from typing import Any

from .planner import plan_preopen_focus


@dataclass(frozen=True)
class PickScore:
    """Score for a single candidate pick."""
    stock_code: str
    stock_name: str
    industry: str
    overall_score: float
    plan_alignment: float
    momentum_score: float
    liquidity_score: float
    risk_penalty: float
    history_bonus: float
    verdict: str  # "strong", "moderate", "weak", "reject"
    notes: str


def evaluate_candidate(
    conn: sqlite3.Connection,
    stock_code: str,
    trading_date: str,
) -> PickScore:
    """Evaluate a single candidate stock against today's plan and recent history."""
    stock = conn.execute(
        "SELECT stock_code, name, industry, is_st, listing_status FROM stocks WHERE stock_code = ?",
        (stock_code,),
    ).fetchone()
    if not stock:
        return PickScore(
            stock_code=stock_code,
            stock_name="",
            industry="",
            overall_score=0.0,
            plan_alignment=0.0,
            momentum_score=0.0,
            liquidity_score=0.0,
            risk_penalty=0.0,
            history_bonus=0.0,
            verdict="reject",
            notes="stock not found",
        )

    d = dict(stock)
    plan = plan_preopen_focus(conn, trading_date)
    focus_industries = {s.get("industry") for s in plan.get("focus_sectors", [])}

    plan_alignment = 1.0 if d.get("industry") in focus_industries else 0.3

    momentum = _momentum_score(conn, stock_code, trading_date)
    liquidity = _liquidity_score(conn, stock_code, trading_date)
    risk = _risk_penalty(d)
    history = _history_bonus(conn, stock_code)

    overall = (
        plan_alignment * 0.3
        + momentum * 0.25
        + liquidity * 0.25
        + history * 0.2
        - risk
    )

    verdict = _classify_verdict(overall, d)
    notes = _build_evaluator_notes(d, overall, plan_alignment)

    return PickScore(
        stock_code=stock_code,
        stock_name=d.get("name", ""),
        industry=d.get("industry", ""),
        overall_score=round(overall, 3),
        plan_alignment=round(plan_alignment, 3),
        momentum_score=round(momentum, 3),
        liquidity_score=round(liquidity, 3),
        risk_penalty=round(risk, 3),
        history_bonus=round(history, 3),
        verdict=verdict,
        notes=notes,
    )


def rank_candidates(
    conn: sqlite3.Connection,
    trading_date: str,
    *,
    min_score: float = 0.0,
    limit: int = 20,
) -> list[PickScore]:
    """Rank all stocks by their evaluation score."""
    rows = conn.execute(
        """
        SELECT s.stock_code FROM stocks s
        LEFT JOIN daily_prices dp ON dp.stock_code = s.stock_code AND dp.trading_date = ?
        WHERE s.listing_status = 'active'
        ORDER BY dp.amount DESC
        """,
        (trading_date,),
    ).fetchall()

    scores: list[PickScore] = []
    for r in rows:
        code = r["stock_code"]
        score = evaluate_candidate(conn, code, trading_date)
        if score.overall_score >= min_score:
            scores.append(score)

    scores.sort(key=lambda s: s.overall_score, reverse=True)
    return scores[:limit]


def run_evaluation(conn: sqlite3.Connection, trading_date: str) -> dict[str, Any]:
    """Run full evaluation of pre-open candidates and persist to pick_evaluations."""
    plan = plan_preopen_focus(conn, trading_date)
    candidates = rank_candidates(conn, trading_date, min_score=0.0, limit=20)

    plan_focus_industries = {s.get("industry") for s in plan.get("focus_sectors", [])}

    # Evaluate actual picks for the day
    actual_picks = conn.execute(
        "SELECT decision_id, stock_code, strategy_gene_id FROM pick_decisions WHERE trading_date = ? AND action = 'BUY'",
        (trading_date,),
    ).fetchall()

    evaluated_count = 0
    for pick in actual_picks:
        stock = conn.execute("SELECT name, industry FROM stocks WHERE stock_code = ?", (pick["stock_code"],)).fetchone()
        score_obj = evaluate_candidate(conn, pick["stock_code"], trading_date)
        outcome = conn.execute(
            "SELECT return_pct FROM outcomes WHERE decision_id = ?",
            (pick["decision_id"],),
        ).fetchone()

        return_pct = float(outcome["return_pct"]) if outcome else 0.0
        verdict = "win" if return_pct > 0 else "loss"
        planner_aligned = 1 if stock and stock["industry"] in plan_focus_industries else 0

        evaluation_id = "eval_" + hashlib.sha1(
            f"{pick['decision_id']}:evaluation".encode()
        ).hexdigest()[:12]

        conn.execute(
            """
            INSERT INTO pick_evaluations(
              evaluation_id, decision_id, trading_date, stock_code, strategy_gene_id,
              return_pct, verdict, thesis_quality,
              planner_aligned, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(decision_id) DO UPDATE SET
              return_pct = excluded.return_pct,
              verdict = excluded.verdict,
              thesis_quality = excluded.thesis_quality,
              planner_aligned = excluded.planner_aligned,
              notes = excluded.notes
            """,
            (
                evaluation_id,
                pick["decision_id"],
                trading_date,
                pick["stock_code"],
                pick["strategy_gene_id"],
                return_pct,
                verdict,
                score_obj.overall_score,
                planner_aligned,
                score_obj.notes,
            ),
        )
        evaluated_count += 1

    conn.commit()

    result = {
        "trading_date": trading_date,
        "plan_focus": plan.get("focus_sectors", []),
        "top_picks": [
            {
                "stock_code": s.stock_code,
                "stock_name": s.stock_name,
                "industry": s.industry,
                "overall_score": s.overall_score,
                "verdict": s.verdict,
                "notes": s.notes,
            }
            for s in candidates[:10]
        ],
        "actual_picks_evaluated": evaluated_count,
        "total_evaluated": len(candidates),
    }

    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
    if api_key and candidates:
        result["llm_commentary"] = _call_evaluator_llm(result)

    return result


def _momentum_score(conn: sqlite3.Connection, stock_code: str, trading_date: str, window: int = 5) -> float:
    """Compute momentum score from recent price changes."""
    rows = conn.execute(
        """
        SELECT close FROM daily_prices
        WHERE stock_code = ? AND trading_date <= ?
        ORDER BY trading_date DESC
        LIMIT ?
        """,
        (stock_code, trading_date, window),
    ).fetchall()

    if len(rows) < 2:
        return 0.0

    closes = [r["close"] for r in rows if r["close"] is not None]
    if len(closes) < 2:
        return 0.0

    change = (closes[0] - closes[-1]) / closes[-1] if closes[-1] != 0 else 0.0
    # Normalize: +10% = 1.0, -10% = -1.0
    return max(-1.0, min(1.0, change / 0.1))


def _liquidity_score(conn: sqlite3.Connection, stock_code: str, trading_date: str) -> float:
    """Score based on trading amount."""
    dp = conn.execute(
        """
        SELECT amount FROM daily_prices
        WHERE stock_code = ? AND trading_date = ?
        """,
        (stock_code, trading_date),
    ).fetchone()

    if not dp:
        return 0.0

    amount = dp["amount"] or 0.0
    # 500M+ = 1.0, 50M = 0.5, 0 = 0.0
    return max(0.0, min(1.0, amount / 500_000_000))


def _risk_penalty(data: dict) -> float:
    """Apply risk penalty for problematic flags."""
    penalty = 0.0
    if data.get("is_st"):
        penalty += 0.5
    if data.get("listing_status") != "active":
        penalty += 0.5
    return penalty


def _history_bonus(conn: sqlite3.Connection, stock_code: str) -> float:
    """Bonus for stocks with positive historical outcomes."""
    rows = conn.execute(
        """
        SELECT o.return_pct FROM pick_decisions pd
        JOIN outcomes o ON o.decision_id = pd.decision_id
        WHERE pd.stock_code = ? AND o.return_pct IS NOT NULL
        ORDER BY pd.created_at DESC
        LIMIT 5
        """,
        (stock_code,),
    ).fetchall()

    if not rows:
        return 0.5  # neutral for no history

    avg_return = sum(r["return_pct"] for r in rows) / len(rows)
    # Normalize: +3% = 1.0, -3% = 0.0
    return max(0.0, min(1.0, 0.5 + avg_return / 6.0))


def _classify_verdict(overall: float, data: dict) -> str:
    """Classify overall score into verdict."""
    if data.get("is_st"):
        return "reject"
    if data.get("listing_status") != "active":
        return "reject"
    if overall >= 0.6:
        return "strong"
    if overall >= 0.3:
        return "moderate"
    if overall >= 0.0:
        return "weak"
    return "reject"


def _build_evaluator_notes(data: dict, overall: float, plan_alignment: float) -> str:
    """Build human-readable evaluation notes."""
    parts: list[str] = []
    if plan_alignment >= 1.0:
        parts.append("aligned with focus sector")
    if data.get("is_st"):
        parts.append("ST flagged")
    parts.append(f"score={overall:.2f}")
    return ", ".join(parts)


def _call_evaluator_llm(result: dict[str, Any]) -> str | None:
    """Call LLM for evaluation commentary."""
    try:
        import anthropic
    except ImportError:
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
    if not api_key:
        return None

    try:
        client = anthropic.Anthropic(api_key=api_key)
        top = result.get("top_picks", [])[:5]
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=(
                "You are a stock pick evaluator. Given today's ranked candidates, "
                "provide brief commentary on the top picks. 2-3 sentences max."
            ),
            messages=[{
                "role": "user",
                "content": f"Top picks: {top}",
            }],
        )
        return response.content[0].text
    except Exception:
        return None
