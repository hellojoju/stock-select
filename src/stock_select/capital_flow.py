"""Capital flow analysis — 资金流向模块.

Uses AkShare stock_individual_fund_flow for per-stock main/super-large/large/retail flow.
Falls back to daily_prices estimation when AkShare is unavailable.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CapitalFlowReport:
    trading_date: str
    stock_code: str
    main_net_inflow: float          # 主力净流入（万元）
    super_large_inflow: float       # 超大单净流入（万元）
    large_order_inflow: float       # 大单净流入（万元）
    retail_net: float               # 散户净流入（万元，小单+中单）
    flow_trend: str                 # 大幅流入/流入/平衡/流出/大幅流出
    sector_flow_rank: int | None    # 行业内排名


def _market_for_code(stock_code: str) -> str:
    return "sz" if stock_code.startswith(("0", "3")) else "sh"


def _fetch_akshare_fund_flow(stock_code: str) -> list[dict[str, Any]]:
    """Fetch fund flow history from AkShare."""
    try:
        import akshare as ak  # type: ignore[import-not-found]
    except Exception:
        return []

    market = _market_for_code(stock_code)
    try:
        df = ak.stock_individual_fund_flow(stock=stock_code, market=market)
        if df is None or df.empty:
            return []
        return df.to_dict("records")
    except Exception:
        return []


def _classify_flow_trend(main_net: float, amount: float) -> str:
    pct = abs(main_net) / max(abs(amount), 1) * 100
    if main_net > 0:
        if pct >= 10:
            return "大幅流入"
        return "流入"
    if main_net < 0:
        if pct >= 10:
            return "大幅流出"
        return "流出"
    return "平衡"


def build_capital_flow_report(
    conn: sqlite3.Connection, stock_code: str, trading_date: str
) -> CapitalFlowReport | None:
    """Build capital flow report for a stock on a given date.

    Priority:
    1. Check capital_flow_daily table (cached)
    2. Fetch from AkShare and cache
    3. Estimate from daily_prices
    """
    # 1. Check cache
    cached = conn.execute(
        """
        SELECT main_net_inflow, super_large_inflow, large_order_inflow,
               retail_outflow, flow_trend, sector_flow_rank
        FROM capital_flow_daily
        WHERE trading_date = ? AND stock_code = ?
        """,
        (trading_date, stock_code),
    ).fetchone()
    if cached:
        return CapitalFlowReport(
            trading_date=trading_date,
            stock_code=stock_code,
            main_net_inflow=cached["main_net_inflow"],
            super_large_inflow=cached["super_large_inflow"],
            large_order_inflow=cached["large_order_inflow"],
            retail_net=cached["retail_outflow"],
            flow_trend=cached["flow_trend"] or "平衡",
            sector_flow_rank=cached["sector_flow_rank"],
        )

    # 2. Try AkShare
    records = _fetch_akshare_fund_flow(stock_code)
    if records:
        # Find the record matching trading_date
        for rec in records:
            date_val = str(rec.get("日期", ""))
            normalized = date_val.replace("/", "-")
            if trading_date in normalized or normalized in trading_date:
                main_net = float(rec.get("主力净流入-净额", 0) or 0)
                super_large = float(rec.get("超大单净流入-净额", 0) or 0)
                large_order = float(rec.get("大单净流入-净额", 0) or 0)
                retail = float(rec.get("中单净流入-净额", 0) or 0) + float(rec.get("小单净流入-净额", 0) or 0)

                # Get amount for trend classification
                amount_row = conn.execute(
                    "SELECT amount FROM daily_prices WHERE stock_code = ? AND trading_date = ?",
                    (stock_code, trading_date),
                ).fetchone()
                amount = float(amount_row["amount"]) if amount_row else 0
                trend = _classify_flow_trend(main_net, amount)

                # Compute sector rank
                sector_rank = _compute_sector_flow_rank(conn, stock_code, trading_date, main_net)

                # Cache to DB
                conn.execute(
                    """
                    INSERT OR IGNORE INTO capital_flow_daily
                    (trading_date, stock_code, main_net_inflow, super_large_inflow,
                     large_order_inflow, retail_outflow, flow_trend, sector_flow_rank)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (trading_date, stock_code, round(main_net, 2), round(super_large, 2),
                     round(large_order, 2), round(retail, 2), trend, sector_rank),
                )
                conn.commit()

                return CapitalFlowReport(
                    trading_date=trading_date,
                    stock_code=stock_code,
                    main_net_inflow=round(main_net, 2),
                    super_large_inflow=round(super_large, 2),
                    large_order_inflow=round(large_order, 2),
                    retail_net=round(retail, 2),
                    flow_trend=trend,
                    sector_flow_rank=sector_rank,
                )

    # 3. Fallback: estimate from daily_prices
    return _estimate_from_prices(conn, stock_code, trading_date)


def _compute_sector_flow_rank(
    conn: sqlite3.Connection, stock_code: str, trading_date: str, flow: float
) -> int | None:
    """Compute flow rank within the stock's industry."""
    industry = conn.execute(
        "SELECT industry FROM stocks WHERE stock_code = ?",
        (stock_code,),
    ).fetchone()
    if not industry or not industry["industry"]:
        return None

    # Get flow for all stocks in the same industry on this date
    rows = conn.execute(
        """
        SELECT cf.stock_code, cf.main_net_inflow
        FROM capital_flow_daily cf
        JOIN stocks s ON cf.stock_code = s.stock_code
        WHERE cf.trading_date = ? AND s.industry = ?
        ORDER BY cf.main_net_inflow DESC
        """,
        (trading_date, industry["industry"]),
    ).fetchall()

    for idx, row in enumerate(rows, 1):
        if row["stock_code"] == stock_code:
            return idx
    return None


def _estimate_from_prices(
    conn: sqlite3.Connection, stock_code: str, trading_date: str
) -> CapitalFlowReport | None:
    """Estimate capital flow from daily_prices when AkShare is unavailable."""
    today = conn.execute(
        """
        SELECT amount, volume, close, open, is_limit_up
        FROM daily_prices
        WHERE stock_code = ? AND trading_date = ?
        """,
        (stock_code, trading_date),
    ).fetchone()
    if not today:
        return None

    amount = float(today["amount"] or 0)
    if amount == 0:
        return None

    close = float(today["close"] or 0)
    open_price = float(today["open"] or 0)
    is_limit = today["is_limit_up"] == 1

    # Simple heuristic: if price up and volume high, estimate net inflow
    ret = (close - open_price) / max(open_price, 1)
    # Estimate: strong positive return + high volume → inflow
    strength = ret * 100  # rough scale
    if is_limit:
        estimated_main = amount * 0.3  # assume 30% net inflow on limit up
    elif strength > 3:
        estimated_main = amount * 0.15
    elif strength > 0:
        estimated_main = amount * 0.05
    elif strength > -3:
        estimated_main = -amount * 0.05
    else:
        estimated_main = -amount * 0.15

    main_net_wan = estimated_main / 10000  # convert to 万元
    trend = _classify_flow_trend(main_net_wan, amount / 10000)

    return CapitalFlowReport(
        trading_date=trading_date,
        stock_code=stock_code,
        main_net_inflow=round(main_net_wan, 2),
        super_large_inflow=round(main_net_wan * 0.4, 2),
        large_order_inflow=round(main_net_wan * 0.3, 2),
        retail_net=round(-main_net_wan * 0.3, 2),
        flow_trend=trend,
        sector_flow_rank=None,
    )


def get_capital_flow(
    conn: sqlite3.Connection, stock_code: str, trading_date: str
) -> CapitalFlowReport | None:
    """Get cached capital flow, or generate it."""
    return build_capital_flow_report(conn, stock_code, trading_date)
