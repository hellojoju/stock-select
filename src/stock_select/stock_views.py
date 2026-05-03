from __future__ import annotations

from sqlite3 import Connection
from typing import Any

from .repository import rows_to_dicts


def search_stocks(conn: Connection, query: str = "", limit: int = 12) -> list[dict[str, Any]]:
    q = query.strip()
    params: list[Any] = []
    where = ""
    if q:
        like = f"%{q}%"
        where = "WHERE s.stock_code LIKE ? OR s.name LIKE ? OR COALESCE(s.industry, '') LIKE ?"
        params.extend([like, like, like])
    params.extend([q, q, q, max(1, min(limit, 50))])
    return rows_to_dicts(
        conn.execute(
            f"""
            SELECT
              s.stock_code,
              s.name,
              s.exchange,
              s.industry,
              s.list_date,
              s.is_st,
              s.listing_status,
              latest.trading_date AS latest_trading_date,
              latest.close AS latest_close
            FROM stocks s
            LEFT JOIN daily_prices latest
              ON latest.stock_code = s.stock_code
             AND latest.trading_date = (
               SELECT MAX(dp.trading_date)
               FROM daily_prices dp
               WHERE dp.stock_code = s.stock_code
             )
            {where}
            ORDER BY
              CASE WHEN s.listing_status = 'active' THEN 0 ELSE 1 END,
              CASE WHEN s.stock_code = ? THEN 0 WHEN s.name = ? THEN 1 WHEN s.stock_code LIKE ? || '%' THEN 2 ELSE 3 END,
              s.stock_code
            LIMIT ?
            """,
            params,
        )
    )
