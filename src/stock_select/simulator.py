from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from . import repository


def simulate_day(conn: sqlite3.Connection, trading_date: str, capital: float = 1_000_000) -> list[str]:
    """Execute BUY decisions at open and mark outcomes.

    Short genes normally exit the same day. Long genes can use a later
    time_exit_days row when future fixture/history data is available. If both
    stop-loss and take-profit touch on the evaluated bar, stop-loss is assumed
    first to avoid optimistic backtests.
    """
    decisions = list(
        conn.execute(
            """
            SELECT * FROM pick_decisions
            WHERE trading_date = ? AND action = 'BUY'
            ORDER BY strategy_gene_id, score DESC
            """,
            (trading_date,),
        )
    )

    outcome_ids: list[str] = []
    for decision in decisions:
        price = conn.execute(
            """
            SELECT * FROM daily_prices
            WHERE stock_code = ? AND trading_date = ?
            """,
            (decision["stock_code"], trading_date),
        ).fetchone()
        if price is None or int(price["is_suspended"]):
            continue

        order_id = build_id("order", decision["decision_id"])
        entry_price = float(price["open"])
        position_pct = float(decision["position_pct"])
        quantity = 0.0 if entry_price <= 0 else capital * position_pct / entry_price
        conn.execute(
            """
            INSERT INTO sim_orders(
              order_id, decision_id, trading_date, stock_code, side, price,
              quantity, position_pct, fee, slippage_pct
            )
            VALUES (?, ?, ?, ?, 'BUY', ?, ?, ?, 0, 0)
            ON CONFLICT(order_id) DO UPDATE SET
              price = excluded.price,
              quantity = excluded.quantity,
              position_pct = excluded.position_pct
            """,
            (
                order_id,
                decision["decision_id"],
                trading_date,
                decision["stock_code"],
                entry_price,
                quantity,
                position_pct,
            ),
        )

        sell_rules = json.loads(decision["sell_rules_json"])
        exit_row = resolve_exit_row(conn, decision, sell_rules) or price
        exit_price, hit_rule = choose_exit_price(entry_price, exit_row, sell_rules)
        close_price = float(exit_row["close"])
        return_pct = exit_price / entry_price - 1 if entry_price > 0 else 0.0
        max_drawdown = float(price["low"]) / entry_price - 1 if entry_price > 0 else 0.0

        outcome_id = build_id("outcome", decision["decision_id"])
        conn.execute(
            """
            INSERT INTO outcomes(
              outcome_id, decision_id, entry_price, exit_price, close_price,
              return_pct, max_drawdown_intraday_pct, hit_sell_rule
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(outcome_id) DO UPDATE SET
              entry_price = excluded.entry_price,
              exit_price = excluded.exit_price,
              close_price = excluded.close_price,
              return_pct = excluded.return_pct,
              max_drawdown_intraday_pct = excluded.max_drawdown_intraday_pct,
              hit_sell_rule = excluded.hit_sell_rule
            """,
            (
                outcome_id,
                decision["decision_id"],
                entry_price,
                exit_price,
                close_price,
                return_pct,
                max_drawdown,
                hit_rule,
            ),
        )
        outcome_ids.append(outcome_id)

    conn.commit()
    return outcome_ids


def choose_exit_price(
    entry_price: float,
    price_row: sqlite3.Row,
    sell_rules: list[dict[str, Any]],
) -> tuple[float, str | None]:
    take_profit = next(
        (float(rule["threshold_pct"]) for rule in sell_rules if rule.get("type") == "take_profit"),
        None,
    )
    stop_loss = next(
        (float(rule["threshold_pct"]) for rule in sell_rules if rule.get("type") == "stop_loss"),
        None,
    )
    high = float(price_row["high"])
    low = float(price_row["low"])
    close = float(price_row["close"])

    if stop_loss is not None:
        stop_price = entry_price * (1 + stop_loss)
        if low <= stop_price:
            return stop_price, "stop_loss"

    if take_profit is not None:
        take_price = entry_price * (1 + take_profit)
        if high >= take_price:
            return take_price, "take_profit"

    return close, None


def resolve_exit_row(
    conn: sqlite3.Connection,
    decision: sqlite3.Row,
    sell_rules: list[dict[str, Any]],
) -> sqlite3.Row | None:
    days = next((int(rule["days"]) for rule in sell_rules if rule.get("type") == "time_exit"), 1)
    rows = conn.execute(
        """
        SELECT * FROM daily_prices
        WHERE stock_code = ? AND trading_date >= ? AND is_suspended = 0
        ORDER BY trading_date ASC
        LIMIT ?
        """,
        (decision["stock_code"], decision["trading_date"], max(1, days)),
    ).fetchall()
    if not rows:
        return None
    return rows[-1]


def summarize_performance(conn: sqlite3.Connection, trading_date: str | None = None) -> list[dict[str, Any]]:
    params: tuple[str, ...] = ()
    where = ""
    if trading_date:
        where = "WHERE p.trading_date = ?"
        params = (trading_date,)

    rows = conn.execute(
        f"""
        SELECT
          p.strategy_gene_id,
          COUNT(o.outcome_id) AS trades,
          AVG(o.return_pct) AS avg_return_pct,
          SUM(CASE WHEN o.return_pct > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(o.outcome_id) AS win_rate,
          MIN(o.max_drawdown_intraday_pct) AS worst_intraday_drawdown_pct
        FROM outcomes o
        JOIN pick_decisions p ON p.decision_id = o.decision_id
        {where}
        GROUP BY p.strategy_gene_id
        ORDER BY avg_return_pct DESC
        """,
        params,
    )
    return [dict(row) for row in rows]


def build_id(prefix: str, value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"
