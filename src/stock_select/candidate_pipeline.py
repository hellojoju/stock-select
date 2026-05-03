from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from . import repository


@dataclass(frozen=True)
class Candidate:
    stock_code: str
    total_score: float
    confidence: float
    technical_score: float
    fundamental_score: float
    event_score: float
    sector_score: float
    risk_penalty: float
    packet: dict[str, Any]


def rank_candidates_for_gene(
    conn: sqlite3.Connection,
    trading_date: str,
    gene_id: str,
    params: dict[str, Any],
) -> list[Candidate]:
    candidates: list[Candidate] = []
    conn.execute(
        "DELETE FROM candidate_scores WHERE trading_date = ? AND strategy_gene_id = ?",
        (trading_date, gene_id),
    )

    # Read planner focus sectors for bonus scoring
    focus_industries = _get_focus_industries(conn, trading_date)

    for stock_code in repository.active_stock_codes(conn):
        candidate = build_candidate(conn, trading_date, gene_id, stock_code, params, focus_industries=focus_industries)
        if candidate is not None:
            candidates.append(candidate)
            repository.upsert_candidate_score(
                conn,
                candidate_id=candidate_id(trading_date, gene_id, stock_code),
                trading_date=trading_date,
                strategy_gene_id=gene_id,
                stock_code=stock_code,
                total_score=candidate.total_score,
                technical_score=candidate.technical_score,
                fundamental_score=candidate.fundamental_score,
                event_score=candidate.event_score,
                sector_score=candidate.sector_score,
                risk_penalty=candidate.risk_penalty,
                packet_json=repository.dumps(candidate.packet),
            )
    conn.commit()
    candidates.sort(key=lambda item: item.total_score, reverse=True)
    return diversity_rerank(candidates, max_per_industry=int(params.get("max_per_industry", 2)))


def build_candidate(
    conn: sqlite3.Connection,
    trading_date: str,
    gene_id: str,
    stock_code: str,
    params: dict[str, Any],
    *,
    focus_industries: set[str] | None = None,
) -> Candidate | None:
    lookback = int(params.get("lookback_days", 6))
    history = repository.price_history_before(conn, stock_code, trading_date, lookback)
    if len(history) < max(3, lookback):
        return None
    if any(int(row["is_suspended"]) for row in history[-2:]):
        return None

    stock = conn.execute("SELECT * FROM stocks WHERE stock_code = ?", (stock_code,)).fetchone()
    if stock is not None and int(stock["is_st"] or 0):
        return None
    if stock is not None and stock["list_date"] and listed_days(stock["list_date"], trading_date) < 60:
        return None
    industry = stock["industry"] if stock else None
    closes = [float(row["close"]) for row in history]
    volumes = [float(row["volume"]) for row in history]
    amounts = [float(row["amount"]) for row in history]
    returns = daily_returns(closes)
    if not returns:
        return None
    avg_amount = mean(amounts[-5:])
    if avg_amount < float(params.get("min_avg_amount", 0)):
        return None

    technical = technical_signal(closes, volumes, returns, params)
    fundamentals = repository.latest_fundamentals_before(conn, stock_code, trading_date)
    fundamental = fundamental_signal(fundamentals)
    sector = repository.latest_sector_signal_before(conn, industry, trading_date)
    sector_sig = sector_signal(sector)

    # Factor config filtering (Phase 3: gene strategy rules)
    factor_config = params.get("factor_config")
    if factor_config:
        min_tech = factor_config.get("min_technical_score", 0.0)
        if min_tech > 0 and technical["score"] < min_tech:
            return None
        min_fund = factor_config.get("min_fundamental_score", 0.0)
        if min_fund > 0 and fundamental["score"] < min_fund:
            return None
    events = repository.recent_events_before(
        conn,
        trading_date=trading_date,
        stock_code=stock_code,
        industry=industry,
        limit=5,
    )
    event_sig = event_signal(events)
    risk = risk_signal(avg_amount, technical["volatility"], fundamentals, events)

    list_date = stock["list_date"] if stock is not None and "list_date" in stock.keys() else None
    listing_days = listed_days(list_date, trading_date) if list_date else None
    hard_filters = [
        {
            "name": "listing_status",
            "status": "pass",
            "reason": "股票在交易日历中",
            "source": "stocks.listing_status",
            "as_of_date": trading_date,
        },
        {
            "name": "not_st",
            "status": "pass",
            "reason": "非 ST 股票",
            "source": "stocks.is_st",
            "as_of_date": trading_date,
        },
        {
            "name": "not_suspended",
            "status": "pass",
            "reason": "最近两日未停牌",
            "source": "daily_prices.is_suspended",
            "as_of_date": trading_date,
        },
        {
            "name": "listing_days",
            "status": "pass",
            "reason": f"已上市 {listing_days if listing_days is not None else '未知'} 天",
            "source": "stocks.list_date",
            "as_of_date": trading_date,
        },
        {
            "name": "min_avg_amount",
            "status": "pass",
            "reason": f"近5日平均成交额 {avg_amount:,.0f} >= {float(params.get('min_avg_amount', 0)):,.0f}",
            "source": "daily_prices.amount",
            "as_of_date": trading_date,
        },
    ]

    planner_bonus = 0.0
    if focus_industries and industry in focus_industries:
        planner_bonus = 0.05  # 5% bonus for planner focus sectors

    total_score = (
        technical["score"] * float(params.get("technical_component_weight", 0.45))
        + fundamental["score"] * float(params.get("fundamental_component_weight", 0.2))
        + event_sig["score"] * float(params.get("event_component_weight", 0.2))
        + sector_sig["score"] * float(params.get("sector_component_weight", 0.15))
        - risk["score"] * float(params.get("risk_component_weight", 0.3))
        + planner_bonus
    )
    confidence = clamp(0.35 + abs(total_score) * 0.8 + coverage_bonus(fundamentals, sector, events), 0.05, 0.95)
    packet = {
        "stock": {
            "code": stock_code,
            "name": stock["name"] if stock else stock_code,
            "industry": industry,
        },
        "strategy_gene_id": gene_id,
        "technical": technical,
        "fundamental": fundamental,
        "event": event_sig,
        "sector": sector_sig,
        "risk": risk,
        "sources": {
            "technical": {"dataset": "daily_prices", "source": "canonical", "visibility": f"<{trading_date}"},
            "fundamental": factor_source(
                fundamentals,
                dataset="fundamental_metrics",
                record_id_fields=("stock_code", "as_of_date", "report_period"),
                date_field="as_of_date",
            ),
            "sector": factor_source(
                sector,
                dataset="sector_theme_signals",
                record_id_fields=("industry", "trading_date"),
                date_field="trading_date",
            ),
            "events": [
                factor_source(
                    event,
                    dataset="event_signals",
                    record_id_fields=("event_id",),
                    date_field="trading_date",
                )
                for event in events
            ],
        },
        "missing_fields": missing_fields(fundamentals, sector, events),
        "data_coverage": data_coverage_detail(fundamentals, sector, events),
        "hard_filters": hard_filters,
    }
    return Candidate(
        stock_code=stock_code,
        total_score=total_score,
        confidence=confidence,
        technical_score=technical["score"],
        fundamental_score=fundamental["score"],
        event_score=event_sig["score"],
        sector_score=sector_sig["score"],
        risk_penalty=risk["score"],
        packet=packet,
    )


def technical_signal(closes: list[float], volumes: list[float], returns: list[float], params: dict[str, Any]) -> dict[str, Any]:
    momentum = closes[-1] / closes[0] - 1
    recent_volume = mean(volumes[-3:])
    prior_volume = mean(volumes[:-3]) if len(volumes) > 3 else recent_volume
    volume_surge = 0 if prior_volume <= 0 else recent_volume / prior_volume - 1
    volatility = stdev(returns)
    score = (
        momentum * float(params.get("momentum_weight", 0.5))
        + clamp(volume_surge, -0.5, 2.0) * float(params.get("volume_weight", 0.2))
        + volatility * float(params.get("volatility_weight", 0.05))
        - volatility * float(params.get("volatility_penalty", 0.1))
    )
    return {
        "score": clamp(score, -1.0, 1.0),
        "momentum": momentum,
        "volume_surge": volume_surge,
        "volatility": volatility,
        "trend_state": "breakout" if momentum > 0.08 and volume_surge > 0.15 else "neutral",
    }


def fundamental_signal(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {"score": 0.0, "available": False, "note": "missing fundamentals"}
    roe = float(row["roe"] or 0)
    revenue_growth = float(row["revenue_growth"] or 0)
    net_profit_growth = float(row["net_profit_growth"] or 0)
    cashflow = float(row["operating_cashflow_to_profit"] or 0)
    debt = float(row["debt_to_assets"] or 0)
    pe_percentile = float(row["pe_percentile"] or 0.5)
    score = (
        normalize(roe, 0.0, 0.25) * 0.28
        + normalize(revenue_growth, -0.2, 0.4) * 0.22
        + normalize(net_profit_growth, -0.2, 0.4) * 0.18
        + normalize(cashflow, 0.0, 1.5) * 0.14
        + (1 - normalize(debt, 0.2, 0.9)) * 0.1
        + (1 - abs(pe_percentile - 0.45)) * 0.08
    )
    return {
        "score": clamp(score, 0.0, 1.0),
        "available": True,
        "roe": roe,
        "revenue_growth": revenue_growth,
        "net_profit_growth": net_profit_growth,
        "cashflow_quality": cashflow,
        "debt_to_assets": debt,
        "pe_percentile": pe_percentile,
        "note": row["quality_note"],
    }


def sector_signal(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {"score": 0.0, "available": False, "summary": "missing sector signal"}
    rank = int(row["relative_strength_rank"])
    rank_score = clamp((10 - rank) / 9, 0.0, 1.0)
    theme = float(row["theme_strength"] or 0)
    volume = normalize(float(row["volume_surge"] or 0), -0.3, 1.0)
    catalysts = normalize(float(row["catalyst_count"] or 0), 0, 5)
    score = rank_score * 0.35 + theme * 0.35 + volume * 0.15 + catalysts * 0.15
    return {
        "score": clamp(score, 0.0, 1.0),
        "available": True,
        "relative_strength_rank": rank,
        "sector_return_pct": float(row["sector_return_pct"]),
        "theme_strength": theme,
        "volume_surge": float(row["volume_surge"]),
        "catalyst_count": int(row["catalyst_count"]),
        "summary": row["summary"],
    }


def event_signal(events: list[sqlite3.Row]) -> dict[str, Any]:
    if not events:
        return {"score": 0.0, "available": False, "items": []}
    items = []
    total = 0.0
    for event in events[:3]:
        impact = float(event["impact_score"])
        sentiment = float(event["sentiment"])
        item_score = impact * 0.65 + sentiment * 0.35
        total += item_score
        items.append(
            {
                "event_type": event["event_type"],
                "title": event["title"],
                "summary": event["summary"],
                "impact_score": impact,
                "sentiment": sentiment,
            }
        )
    return {
        "score": clamp(total / max(1, len(items)), -1.0, 1.0),
        "available": True,
        "items": items,
    }


def risk_signal(
    avg_amount: float,
    volatility: float,
    fundamentals: sqlite3.Row | None,
    events: list[sqlite3.Row],
) -> dict[str, Any]:
    risk = 0.0
    reasons: list[str] = []
    if avg_amount < 100_000_000:
        risk += 0.18
        reasons.append("low liquidity")
    if volatility > 0.055:
        risk += 0.18
        reasons.append("high recent volatility")
    if fundamentals is None:
        risk += 0.12
        reasons.append("missing fundamentals")
    elif float(fundamentals["debt_to_assets"] or 0) > 0.75 and float(fundamentals["roe"] or 0) < 0.08:
        risk += 0.2
        reasons.append("weak balance sheet quality")
    if any(float(event["impact_score"]) < -0.4 or float(event["sentiment"]) < -0.5 for event in events):
        risk += 0.18
        reasons.append("negative event signal")
    return {"score": clamp(risk, 0.0, 1.0), "avg_amount": avg_amount, "reasons": reasons}


def diversity_rerank(candidates: list[Candidate], max_per_industry: int) -> list[Candidate]:
    counts: dict[str, int] = {}
    primary: list[Candidate] = []
    overflow: list[Candidate] = []
    for candidate in candidates:
        industry = str(candidate.packet["stock"].get("industry") or "unknown")
        if counts.get(industry, 0) < max_per_industry:
            primary.append(candidate)
            counts[industry] = counts.get(industry, 0) + 1
        else:
            overflow.append(candidate)
    return primary + overflow


def _get_focus_industries(conn: sqlite3.Connection, trading_date: str) -> set[str]:
    """Extract focus industries from today's planner plan."""
    row = conn.execute(
        "SELECT focus_sectors_json FROM planner_plans WHERE trading_date = ?",
        (trading_date,),
    ).fetchone()
    if not row or not row["focus_sectors_json"]:
        return set()
    import json
    focus_sectors = json.loads(row["focus_sectors_json"])
    return {s["industry"] for s in focus_sectors if isinstance(s, dict) and "industry" in s}


def candidate_id(trading_date: str, gene_id: str, stock_code: str) -> str:
    raw = f"{trading_date}:{gene_id}:{stock_code}"
    return "cand_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def daily_returns(closes: list[float]) -> list[float]:
    return [
        closes[index] / closes[index - 1] - 1
        for index in range(1, len(closes))
        if closes[index - 1] > 0
    ]


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    avg = mean(values)
    return (sum((value - avg) ** 2 for value in values) / (len(values) - 1)) ** 0.5


def normalize(value: float, lower: float, upper: float) -> float:
    if upper <= lower:
        return 0.0
    return clamp((value - lower) / (upper - lower), 0.0, 1.0)


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def coverage_bonus(fundamentals: sqlite3.Row | None, sector: sqlite3.Row | None, events: list[sqlite3.Row]) -> float:
    """S5.5: Bonus for having data, penalty for missing data."""
    bonus = 0.0
    penalty = 0.0
    if fundamentals is not None:
        bonus += 0.06
    else:
        penalty += 0.05
    if sector is not None:
        bonus += 0.04
    else:
        penalty += 0.03
    if events:
        bonus += 0.04
    else:
        penalty += 0.03
    return bonus - penalty


def listed_days(list_date: str, trading_date: str) -> int:
    try:
        start = datetime.strptime(list_date[:10], "%Y-%m-%d").date()
        end = datetime.strptime(trading_date, "%Y-%m-%d").date()
    except ValueError:
        return 9999
    return (end - start).days


def missing_fields(
    fundamentals: sqlite3.Row | None,
    sector: sqlite3.Row | None,
    events: list[sqlite3.Row],
) -> list[str]:
    """Return list of missing data dimensions for the candidate."""
    missing = []
    if fundamentals is None:
        missing.append("fundamental")
    if sector is None:
        missing.append("sector")
    if not events:
        missing.append("event")
    return missing


def data_coverage_detail(
    fundamentals: sqlite3.Row | None,
    sector: sqlite3.Row | None,
    events: list[sqlite3.Row],
) -> dict[str, str]:
    """S5.6: Detailed data coverage status for each dimension."""
    return {
        "fundamental": "available" if fundamentals else "data_missing",
        "sector": "available" if sector else "data_missing",
        "event": "available" if events else "data_missing",
    }


def factor_source(
    row: sqlite3.Row | None,
    *,
    dataset: str,
    record_id_fields: tuple[str, ...],
    date_field: str,
) -> dict[str, Any] | None:
    if row is None:
        return None
    record_id = ":".join(str(row[field]) for field in record_id_fields if field in row.keys())
    return {
        "dataset": dataset,
        "source": row["source"] if "source" in row.keys() else None,
        "as_of_date": row[date_field] if date_field in row.keys() else None,
        "report_period": row["report_period"] if "report_period" in row.keys() else None,
        "record_id": record_id,
    }
