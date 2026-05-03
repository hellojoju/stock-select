from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Scenario:
    condition: str
    action: str
    trigger: str


@dataclass(frozen=True)
class NextDayPlan:
    decision_review_id: str
    scenarios: list[Scenario] = field(default_factory=list)
    key_levels: list[dict[str, float]] = field(default_factory=list)


def _fetch_stock_and_return(
    conn: sqlite3.Connection, decision_review_id: str
) -> tuple[str, float] | None:
    row = conn.execute(
        """
        SELECT stock_code, return_pct FROM decision_reviews
        WHERE review_id = ?
        """,
        (decision_review_id,),
    ).fetchone()
    if row is None:
        return None
    return row["stock_code"], row["return_pct"]


def _fetch_ma_position(
    conn: sqlite3.Connection, stock_code: str, trading_date: str
) -> dict[str, float] | None:
    from .stock_quant import analyze_moving_average

    ma = analyze_moving_average(conn, stock_code, trading_date)
    if ma is None:
        return None
    return {
        "ma5": ma.ma5,
        "ma10": ma.ma10,
        "ma20": ma.ma20,
        "close": ma.close,
        "pos_ma5": ma.position_vs_ma5,
        "trend": ma.trend,
    }


def _fetch_sector_context(
    conn: sqlite3.Connection, stock_code: str, trading_date: str
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT industry FROM stocks WHERE stock_code = ?",
        (stock_code,),
    ).fetchone()
    if row is None or not row["industry"]:
        return {}
    industry = row["industry"]
    sector_row = conn.execute(
        """
        SELECT sector_return_pct, sustainability, team_complete
        FROM sector_analysis_daily
        WHERE trading_date = ? AND sector_name = ?
        """,
        (trading_date, industry),
    ).fetchone()
    if sector_row is None:
        return {}
    return {
        "sector_return": sector_row["sector_return_pct"],
        "sustainability": sector_row["sustainability"],
        "team_complete": bool(sector_row["team_complete"]),
    }


def _fetch_sentiment(conn: sqlite3.Connection, trading_date: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT cycle_phase, composite_sentiment FROM sentiment_cycle_daily WHERE trading_date = ?",
        (trading_date,),
    ).fetchone()
    if row is None:
        return {}
    return {
        "cycle_phase": row["cycle_phase"],
        "composite_sentiment": row["composite_sentiment"],
    }


def _build_scenarios(
    ma_ctx: dict[str, float] | None,
    sector_ctx: dict[str, Any],
    sentiment_ctx: dict[str, Any],
    return_pct: float,
) -> list[Scenario]:
    scenarios: list[Scenario] = []

    ma5 = ma_ctx["ma5"] if ma_ctx else 0
    close = ma_ctx["close"] if ma_ctx else 0
    trend = ma_ctx.get("trend", "震荡") if ma_ctx else "震荡"
    sustain = sector_ctx.get("sustainability", 0)
    cycle = sentiment_ctx.get("cycle_phase", "unknown")

    # Scenario 1: 高开3%以上
    if trend in ("多头排列", "短期强势") and sustain >= 0.5:
        action1 = "持股观望，若量能配合可继续持有；若冲高回落考虑减仓"
    elif cycle in ("高潮", "退潮"):
        action1 = "警惕诱多，考虑逢高减仓"
    else:
        action1 = "观察15分钟，确认趋势后决定是否加仓"
    scenarios.append(
        Scenario(
            condition="高开3%以上",
            action=action1,
            trigger=f"开盘价 ≥ {round(close * 1.03, 2) if close else 0}",
        )
    )

    # Scenario 2: 平开（-2% 到 +3%）
    if trend in ("多头排列", "短期强势"):
        action2 = "若回踩5日线企稳且板块强势，考虑加仓"
    elif trend in ("空头排列", "短期弱势"):
        action2 = "反弹减仓，控制风险"
    else:
        action2 = "保持观望，等待方向确认"
    scenarios.append(
        Scenario(
            condition="平开（-2% ~ +3%）",
            action=action2,
            trigger=f"开盘价在 {round(close * 0.98, 2) if close else 0} ~ {round(close * 1.03, 2) if close else 0} 之间",
        )
    )

    # Scenario 3: 低开2%以下
    if return_pct > 0 and trend in ("多头排列", "短期强势"):
        action3 = "若基本面无变化，低开是捡错杀机会，考虑加仓"
    elif cycle in ("恐慌", "冰点"):
        action3 = "情绪恐慌导致低开，若逻辑未变可加仓；否则止损"
    else:
        action3 = "观察板块是否同步低开，若是则减仓避险"
    scenarios.append(
        Scenario(
            condition="低开2%以下",
            action=action3,
            trigger=f"开盘价 ≤ {round(close * 0.98, 2) if close else 0}",
        )
    )

    return scenarios


def _build_key_levels(
    ma_ctx: dict[str, float] | None,
    close: float,
) -> list[dict[str, float]]:
    levels: list[dict[str, float]] = []
    if ma_ctx:
        levels.append({"label": "5日线", "price": round(ma_ctx["ma5"], 2)})
        levels.append({"label": "10日线", "price": round(ma_ctx["ma10"], 2)})
        levels.append({"label": "20日线", "price": round(ma_ctx["ma20"], 2)})
    levels.append({"label": "今日收盘价", "price": round(close, 2)})
    return levels


def build_next_day_plan(
    conn: sqlite3.Connection, decision_review_id: str
) -> NextDayPlan | None:
    stock_return = _fetch_stock_and_return(conn, decision_review_id)
    if stock_return is None:
        return None
    stock_code, return_pct = stock_return

    # Get trading date from decision review
    row = conn.execute(
        "SELECT trading_date FROM decision_reviews WHERE review_id = ?",
        (decision_review_id,),
    ).fetchone()
    if row is None:
        return None
    trading_date = row["trading_date"]

    # Get price close for key levels
    price_row = conn.execute(
        "SELECT close FROM daily_prices WHERE stock_code = ? AND trading_date = ?",
        (stock_code, trading_date),
    ).fetchone()
    close = price_row["close"] if price_row else 0

    ma_ctx = _fetch_ma_position(conn, stock_code, trading_date)
    sector_ctx = _fetch_sector_context(conn, stock_code, trading_date)
    sentiment_ctx = _fetch_sentiment(conn, trading_date)

    scenarios = _build_scenarios(ma_ctx, sector_ctx, sentiment_ctx, return_pct)
    key_levels = _build_key_levels(ma_ctx, close)

    return NextDayPlan(
        decision_review_id=decision_review_id,
        scenarios=scenarios,
        key_levels=key_levels,
    )


def save_next_day_plan(conn: sqlite3.Connection, plan: NextDayPlan) -> None:
    conn.execute(
        """
        INSERT INTO next_day_plan (decision_review_id, scenarios, key_levels)
        VALUES (?, ?, ?)
        ON CONFLICT(decision_review_id) DO UPDATE SET
            scenarios = excluded.scenarios,
            key_levels = excluded.key_levels,
            created_at = datetime('now')
        """,
        (
            plan.decision_review_id,
            json.dumps([{"condition": s.condition, "action": s.action, "trigger": s.trigger} for s in plan.scenarios]),
            json.dumps(plan.key_levels),
        ),
    )
    conn.commit()


def get_next_day_plan(
    conn: sqlite3.Connection, decision_review_id: str
) -> NextDayPlan | None:
    row = conn.execute(
        "SELECT * FROM next_day_plan WHERE decision_review_id = ?",
        (decision_review_id,),
    ).fetchone()
    if row is None:
        return None
    scenarios_data = json.loads(row["scenarios"] or "[]")
    return NextDayPlan(
        decision_review_id=row["decision_review_id"],
        scenarios=[Scenario(s["condition"], s["action"], s["trigger"]) for s in scenarios_data],
        key_levels=json.loads(row["key_levels"] or "[]"),
    )


def generate_next_day_plan(
    conn: sqlite3.Connection, decision_review_id: str
) -> NextDayPlan | None:
    plan = build_next_day_plan(conn, decision_review_id)
    if plan is None:
        return None
    save_next_day_plan(conn, plan)
    return plan
