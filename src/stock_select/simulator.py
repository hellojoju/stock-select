from __future__ import annotations

import hashlib
import json
import os
import ssl
import sqlite3
import urllib.request
from datetime import date
from typing import Any
from concurrent.futures import ThreadPoolExecutor


# A-share limit thresholds by board
_LIMIT_THRESHOLDS = {
    "main": 0.10,       # 主板 10%
    "st": 0.05,         # ST 5%
    "gem": 0.20,        # 创业板 20%
    "star": 0.20,       # 科创板 20%
    "bse": 0.30,        # 北交所 30%
}

# Tencent realtime quote API
_TENCENT_CTX = ssl.create_default_context()
_TENCENT_CTX.check_hostname = False
_TENCENT_CTX.verify_mode = ssl.CERT_NONE


def _stock_to_tencent(code: str) -> str | None:
    """Convert stock code to Tencent format, e.g. '000001.SZ' -> 'sz000001'."""
    parts = code.split(".")
    if len(parts) != 2:
        return None
    return parts[1].lower() + parts[0]


def _fetch_realtime_prices(stock_codes: list[str]) -> dict[str, dict]:
    """Fetch real-time prices from Tencent API. Returns {code: {open, high, low, close, volume, amount}}."""
    # Clear proxy env
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        os.environ.pop(k, None)

    results: dict[str, dict] = {}
    symbols = []
    code_map: dict[str, str] = {}  # tencent numeric code -> original code
    for code in stock_codes:
        tc = _stock_to_tencent(code)
        if tc:
            symbols.append(tc)
            # Map both full code (sz000001) and numeric code (000001) to original
            numeric = code.split(".")[0]
            code_map[tc] = code
            code_map[numeric] = code

    url = f"https://qt.gtimg.cn/q={','.join(symbols)}"
    try:
        with urllib.request.urlopen(url, timeout=15, context=_TENCENT_CTX) as resp:
            body = resp.read().decode("gbk")
    except Exception:
        return results

    for line in body.split(";"):
        line = line.strip()
        if "~" not in line:
            continue
        parts = line.split("~")
        if len(parts) < 46:
            continue
        # Tencent format: [1]=name, [2]=code, [3]=latest_price, [5]=open,
        # [33]=high, [34]=low, [36]=volume, [37]=amount, [38]=prev_close
        tencent_code = parts[2] if len(parts) > 2 else ""
        if not tencent_code:
            continue
        orig_code = code_map.get(tencent_code)
        if orig_code is None:
            continue
        try:
            open_price = float(parts[5]) if parts[5] else 0
            high = float(parts[33]) if len(parts) > 33 and parts[33] else 0
            low = float(parts[34]) if len(parts) > 34 and parts[34] else 0
            close = float(parts[3]) if parts[3] else 0  # latest price
            volume = float(parts[36]) if len(parts) > 36 and parts[36] else 0
            amount = float(parts[37]) if len(parts) > 37 and parts[37] else 0
            results[orig_code] = {
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "amount": amount,
            }
        except (ValueError, IndexError):
            pass
    return results


class _DictRow:
    """Minimal dict-based row that supports key access like sqlite3.Row."""
    def __init__(self, data: dict):
        self._data = data
    def __getitem__(self, key):
        return self._data.get(key, 0)
    def __setitem__(self, key, value):
        self._data[key] = value
    def __contains__(self, key):
        return key in self._data
    def keys(self):
        return self._data.keys()
    def __bool__(self):
        return True


def _dict_to_row(data: dict) -> _DictRow:
    """Convert API response dict to a row-like object compatible with existing code."""
    return _DictRow({
        "open": data.get("open", 0),
        "high": data.get("high", 0),
        "low": data.get("low", 0),
        "close": data.get("close", 0),
        "volume": data.get("volume", 0),
        "amount": data.get("amount", 0),
        "is_suspended": 0,
    })


def _get_prev_close_from_db(conn: sqlite3.Connection, stock_code: str, trading_date: str) -> float | None:
    """Get prev_close from daily_prices for limit check."""
    row = conn.execute(
        """
        SELECT close FROM daily_prices
        WHERE stock_code = ? AND trading_date < ?
        ORDER BY trading_date DESC LIMIT 1
        """,
        (stock_code, trading_date),
    ).fetchone()
    if row and row["close"] is not None:
        v = float(row["close"])
        return v if v > 0 else None
    return None


def _get_limit_threshold(stock_code: str, is_st: bool = False) -> float:
    """Return the limit up/down threshold for a stock."""
    if is_st:
        return _LIMIT_THRESHOLDS["st"]
    # Gem: 300xxx, Star: 688xxx, BSE: 8xxxxx/4xxxxx
    prefix3 = stock_code[:3]
    prefix2 = stock_code[:2]
    if prefix3 == "300":
        return _LIMIT_THRESHOLDS["gem"]
    if prefix3 == "688":
        return _LIMIT_THRESHOLDS["star"]
    if prefix2 in ("83", "87", "43", "44", "82"):
        return _LIMIT_THRESHOLDS["bse"]
    return _LIMIT_THRESHOLDS["main"]


def simulate_day(conn: sqlite3.Connection, trading_date: str, capital: float = 1_000_000) -> list[str]:
    """Execute BUY decisions at open and mark outcomes.

    Short genes normally exit the same day. Long genes can use a later
    time_exit_days row when future fixture/history data is available. If both
    stop-loss and take-profit touch on the evaluated bar, stop-loss is assumed
    first to avoid optimistic backtests.

    Trading constraints:
    - Limit up/down: cannot execute at open if price already at limit
    - Suspension: skip suspended stocks
    - Volume: require sufficient volume to fill order
    - Fee & slippage: applied to entry and exit
    """
    fee_rate = 0.0003  # 万分之三
    slippage_rate = 0.001  # 千分之一

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

    # Pre-load stock info for ST detection
    stock_info = {}
    for code in set(d["stock_code"] for d in decisions):
        row = conn.execute("SELECT name, is_st FROM stocks WHERE stock_code = ?", (code,)).fetchone()
        if row:
            stock_info[code] = {"name": row["name"], "is_st": bool(row["is_st"] or False)}

    # Fetch real-time prices only for today's date (live trading mode)
    today_str = date.today().isoformat()
    use_realtime = (trading_date == today_str)
    realtime_prices: dict[str, dict] = {}
    if use_realtime:
        decision_codes = [d["stock_code"] for d in decisions]
        realtime_prices = _fetch_realtime_prices(decision_codes)

    outcome_ids: list[str] = []
    for decision in decisions:
        stock = stock_info.get(decision["stock_code"], {})
        api_data = realtime_prices.get(decision["stock_code"])

        if api_data is not None:
            # Real-time mode: use API data with full validation
            price = _dict_to_row(api_data)
            prev_close_db = _get_prev_close_from_db(conn, decision["stock_code"], trading_date)
            reject_reason = _check_reject_reason(price, decision["stock_code"], stock)
            if reject_reason:
                _record_rejected_order(conn, decision, price, trading_date, reject_reason)
                continue

            entry_price = float(price["open"])
            limit_threshold = _get_limit_threshold(decision["stock_code"], stock.get("is_st", False))
            if _is_limit_up_down(entry_price, prev_close_db, limit_threshold):
                reject_reason = "limit_up" if entry_price > prev_close_db else "limit_down"
                _record_rejected_order(conn, decision, price, trading_date, reject_reason)
                continue

            required_volume = calculate_required_volume(decision, entry_price, price)
            actual_volume = float(price["volume"])
            if actual_volume < required_volume * 10:
                _record_rejected_order(conn, decision, price, trading_date, "insufficient_volume")
                continue
        else:
            # Fallback: read from DB (for backtesting/replay) — original simple path
            price = conn.execute(
                """
                SELECT * FROM daily_prices
                WHERE stock_code = ? AND trading_date = ?
                """,
                (decision["stock_code"], trading_date),
            ).fetchone()
            if price is None:
                continue
            if int(price["is_suspended"]):
                _record_rejected_order(conn, decision, price, trading_date, "suspended")
                continue
            entry_price = float(price["open"])
            prev_close_db = _get_prev_close(conn, price, decision["stock_code"], trading_date)

            # Check limit up/down in DB fallback mode
            limit_threshold = _get_limit_threshold(decision["stock_code"], stock.get("is_st", False))
            if _is_limit_up_down(entry_price, prev_close_db, limit_threshold):
                reject_reason = "limit_up" if entry_price > prev_close_db else "limit_down"
                _record_rejected_order(conn, decision, price, trading_date, reject_reason)
                continue

        order_id = build_id("order", decision["decision_id"])
        position_pct = float(decision["position_pct"])
        quantity = 0.0 if entry_price <= 0 else capital * position_pct / entry_price
        fee = capital * position_pct * fee_rate
        slippage = entry_price * slippage_rate
        effective_entry = entry_price + slippage

        conn.execute(
            """
            INSERT INTO sim_orders(
              order_id, decision_id, trading_date, stock_code, side, price,
              quantity, position_pct, fee, slippage_pct, status
            )
            VALUES (?, ?, ?, ?, 'BUY', ?, ?, ?, ?, ?, 'filled')
            ON CONFLICT(order_id) DO UPDATE SET
              price = excluded.price,
              quantity = excluded.quantity,
              position_pct = excluded.position_pct,
              fee = excluded.fee,
              slippage_pct = excluded.slippage_pct,
              status = excluded.status
            """,
            (
                order_id,
                decision["decision_id"],
                trading_date,
                decision["stock_code"],
                effective_entry,
                quantity,
                position_pct,
                fee,
                slippage_rate,
            ),
        )

        sell_rules = json.loads(decision["sell_rules_json"])
        exit_row = resolve_exit_row(conn, decision, sell_rules) or price
        exit_price, hit_rule = choose_exit_price(effective_entry, exit_row, sell_rules, fee_rate, slippage_rate)
        close_price = float(exit_row["close"])
        return_pct = (exit_price - effective_entry) / effective_entry if effective_entry > 0 else 0.0
        max_drawdown = float(price["low"]) / effective_entry - 1 if effective_entry > 0 else 0.0

        # Calculate alpha: return_pct - benchmark_return - sector_beta_return
        industry = stock.get("industry")
        benchmark_ret, sector_ret, alpha_val = _compute_alpha(
            conn, trading_date, decision["stock_code"], industry, return_pct,
        )

        outcome_id = build_id("outcome", decision["decision_id"])
        conn.execute(
            """
            INSERT INTO outcomes(
              outcome_id, decision_id, entry_price, exit_price, close_price,
              return_pct, max_drawdown_intraday_pct, hit_sell_rule,
              benchmark_return, sector_return, alpha
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(outcome_id) DO UPDATE SET
              entry_price = excluded.entry_price,
              exit_price = excluded.exit_price,
              close_price = excluded.close_price,
              return_pct = excluded.return_pct,
              max_drawdown_intraday_pct = excluded.max_drawdown_intraday_pct,
              hit_sell_rule = excluded.hit_sell_rule,
              benchmark_return = excluded.benchmark_return,
              sector_return = excluded.sector_return,
              alpha = excluded.alpha
            """,
            (
                outcome_id,
                decision["decision_id"],
                effective_entry,
                exit_price,
                close_price,
                return_pct,
                max_drawdown,
                hit_rule,
                benchmark_ret,
                sector_ret,
                alpha_val,
            ),
        )
        outcome_ids.append(outcome_id)

    conn.commit()
    return outcome_ids


def _get_prev_close(
    conn: sqlite3.Connection | None,
    price_row: sqlite3.Row | None,
    stock_code: str | None = None,
    trading_date: str | None = None,
) -> float | None:
    """Extract prev_close, falling back to the latest prior canonical close."""
    if price_row is None:
        return None
    keys = price_row.keys()
    if "prev_close" in keys and price_row["prev_close"] is not None:
        v = float(price_row["prev_close"])
        if v > 0:
            return v
    if conn is None or not stock_code or not trading_date:
        return None
    row = conn.execute(
        """
        SELECT close FROM daily_prices
        WHERE stock_code = ? AND trading_date < ?
        ORDER BY trading_date DESC
        LIMIT 1
        """,
        (stock_code, trading_date),
    ).fetchone()
    if not row or row["close"] is None:
        return None
    value = float(row["close"])
    return value if value > 0 else None


def _check_reject_reason(
    price: sqlite3.Row | None,
    stock_code: str,
    stock: dict[str, Any],
) -> str | None:
    """Check if the order should be rejected and return the reason."""
    if price is None:
        return "no_price_data"
    keys = price.keys() if price else set()
    if int(price["is_suspended"] if "is_suspended" in keys else 0):
        return "suspended"
    open_price = float(price["open"] if "open" in keys else 0 or 0)
    if open_price <= 0:
        return "no_open_price"
    return None


def _is_limit_up_down(price: float, prev_close: float | None, threshold: float) -> bool:
    """Check if price is at limit up or limit down for the given threshold."""
    if prev_close is None or prev_close <= 0:
        return False
    change_pct = (price - prev_close) / prev_close
    return change_pct >= (threshold - 0.001) or change_pct <= -(threshold - 0.001)


def _record_rejected_order(
    conn: sqlite3.Connection,
    decision: sqlite3.Row,
    price: sqlite3.Row | None,
    trading_date: str,
    reject_reason: str,
) -> None:
    """Record a rejected order with reject reason."""
    order_id = build_id("order", decision["decision_id"])
    open_price = float(price["open"]) if price and price["open"] is not None else 0.0
    position_pct = float(decision["position_pct"])
    entry_price = open_price if open_price > 0 else 0.0
    capital = 1_000_000
    quantity = capital * position_pct / entry_price if entry_price > 0 else 0.0
    conn.execute(
        """
        INSERT INTO sim_orders(
          order_id, decision_id, trading_date, stock_code, side, price,
          quantity, position_pct, fee, slippage_pct, status, reject_reason
        )
        VALUES (?, ?, ?, ?, 'BUY', ?, ?, ?, 0, 0, 'rejected', ?)
        ON CONFLICT(order_id) DO UPDATE SET
          status = excluded.status,
          reject_reason = excluded.reject_reason
        """,
        (
            order_id,
            decision["decision_id"],
            trading_date,
            decision["stock_code"],
            entry_price,
            quantity,
            position_pct,
            reject_reason,
        ),
    )


def calculate_required_volume(
    decision: sqlite3.Row,
    entry_price: float,
    price_row: sqlite3.Row,
) -> float:
    """Calculate minimum volume needed to fill the order."""
    position_pct = float(decision["position_pct"])
    capital_estimate = 1_000_000
    order_value = capital_estimate * position_pct
    order_volume = order_value / entry_price if entry_price > 0 else 0
    return order_volume


def choose_exit_price(
    entry_price: float,
    price_row: sqlite3.Row,
    sell_rules: list[dict[str, Any]],
    fee_rate: float = 0.0,
    slippage_rate: float = 0.0,
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
            return stop_price * (1 - fee_rate - slippage_rate), "stop_loss"

    if take_profit is not None:
        take_price = entry_price * (1 + take_profit)
        if high >= take_price:
            return take_price * (1 - fee_rate - slippage_rate), "take_profit"

    return close * (1 - fee_rate - slippage_rate), None


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


def _compute_alpha(
    conn: sqlite3.Connection,
    trading_date: str,
    stock_code: str,
    industry: str | None,
    return_pct: float,
) -> tuple[float, float, float]:
    """Calculate benchmark return, sector return, and alpha for a stock outcome.

    alpha = return_pct - benchmark_return - sector_beta * sector_return
    Falls back to 0.0 if data is unavailable.
    """
    # Benchmark return from trading_days index_return_pct
    index_row = conn.execute(
        "SELECT index_return_pct FROM trading_days WHERE trading_date = ?",
        (trading_date,),
    ).fetchone()
    benchmark_ret = float(index_row["index_return_pct"]) if index_row and index_row["index_return_pct"] is not None else 0.0

    # Sector return from sector_theme_signals
    sector_ret = 0.0
    if industry:
        sector_row = conn.execute(
            "SELECT sector_return_pct FROM sector_theme_signals WHERE trading_date = ? AND industry = ?",
            (trading_date, industry),
        ).fetchone()
        if sector_row:
            sector_ret = float(sector_row["sector_return_pct"] or 0.0)

    # Alpha with beta=0.5 for sector exposure
    alpha = return_pct - benchmark_ret - sector_ret * 0.5
    return benchmark_ret, sector_ret, alpha
