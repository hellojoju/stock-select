from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass

from . import repository


DEFAULT_CLOSE_DIFF_THRESHOLD = 0.003


@dataclass(frozen=True)
class PriceCheckResult:
    stock_code: str
    trading_date: str
    status: str
    primary_close: float | None
    secondary_close: float | None
    close_diff_pct: float | None
    message: str


def compare_and_publish_prices(
    conn: sqlite3.Connection,
    trading_date: str,
    *,
    primary_source: str = "akshare",
    secondary_source: str = "baostock",
    threshold: float = DEFAULT_CLOSE_DIFF_THRESHOLD,
) -> list[PriceCheckResult]:
    """Compare source prices and publish canonical daily prices.

    AKShare is the default canonical source. BaoStock is used to detect missing
    or suspicious rows. Missing secondary data is a warning, not a blocker.
    """
    stock_codes = repository.active_stock_codes(conn)
    results: list[PriceCheckResult] = []

    for stock_code in stock_codes:
        primary = source_price(conn, primary_source, stock_code, trading_date)
        secondary = source_price(conn, secondary_source, stock_code, trading_date)
        result = evaluate_source_pair(stock_code, trading_date, primary, secondary, threshold)
        results.append(result)
        repository.insert_price_source_check(
            conn,
            check_id=check_id(stock_code, trading_date, primary_source, secondary_source),
            stock_code=stock_code,
            trading_date=trading_date,
            primary_source=primary_source,
            secondary_source=secondary_source,
            primary_close=result.primary_close,
            secondary_close=result.secondary_close,
            close_diff_pct=result.close_diff_pct,
            status=result.status,
            message=result.message,
        )
        published = primary if primary is not None else secondary
        published_source = primary_source if primary is not None else secondary_source
        if published is not None and result.status != "missing_all":
            # Look up prev_close from previous trading day
            prev_close_row = conn.execute(
                """
                SELECT close FROM daily_prices
                WHERE stock_code = ? AND trading_date < ?
                ORDER BY trading_date DESC
                LIMIT 1
                """,
                (stock_code, trading_date),
            ).fetchone()
            prev_close = float(prev_close_row["close"]) if prev_close_row else None
            repository.upsert_daily_price(
                conn,
                stock_code=stock_code,
                trading_date=trading_date,
                open=float(published["open"]),
                high=float(published["high"]),
                low=float(published["low"]),
                close=float(published["close"]),
                prev_close=prev_close,
                volume=float(published["volume"]),
                amount=float(published["amount"]),
                is_suspended=bool(published["is_suspended"]),
                is_limit_up=bool(published["is_limit_up"]) if "is_limit_up" in published.keys() else False,
                is_limit_down=bool(published["is_limit_down"]) if "is_limit_down" in published.keys() else False,
                source=f"{published_source}:{result.status}",
            )
        elif result.status == "missing_all":
            conn.execute(
                "DELETE FROM daily_prices WHERE stock_code = ? AND trading_date = ?",
                (stock_code, trading_date),
            )
    conn.commit()
    return results


def source_price(
    conn: sqlite3.Connection,
    source: str,
    stock_code: str,
    trading_date: str,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM source_daily_prices
        WHERE source = ? AND stock_code = ? AND trading_date = ?
        """,
        (source, stock_code, trading_date),
    ).fetchone()


def evaluate_source_pair(
    stock_code: str,
    trading_date: str,
    primary: sqlite3.Row | None,
    secondary: sqlite3.Row | None,
    threshold: float = DEFAULT_CLOSE_DIFF_THRESHOLD,
) -> PriceCheckResult:
    if primary is None and secondary is None:
        return PriceCheckResult(stock_code, trading_date, "missing_all", None, None, None, "missing both sources")
    if primary is None:
        return PriceCheckResult(
            stock_code,
            trading_date,
            "missing_primary",
            None,
            float(secondary["close"]) if secondary else None,
            None,
            "published secondary source because primary missing",
        )
    primary_close = float(primary["close"])
    if secondary is None:
        return PriceCheckResult(
            stock_code,
            trading_date,
            "warning",
            primary_close,
            None,
            None,
            "missing secondary source",
        )

    secondary_close = float(secondary["close"])
    diff_pct = abs(primary_close - secondary_close) / primary_close if primary_close else 0.0
    if diff_pct > threshold:
        return PriceCheckResult(
            stock_code,
            trading_date,
            "warning",
            primary_close,
            secondary_close,
            diff_pct,
            f"close diff {diff_pct:.4%} exceeds {threshold:.4%}",
        )
    return PriceCheckResult(
        stock_code,
        trading_date,
        "ok",
        primary_close,
        secondary_close,
        diff_pct,
        "sources agree",
    )


def check_id(stock_code: str, trading_date: str, primary_source: str, secondary_source: str) -> str:
    raw = f"{stock_code}:{trading_date}:{primary_source}:{secondary_source}"
    return "check_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
