"""Fast backfill using Tencent k-line API (no proxy, concurrent)."""

import os
# Bypass proxy for subprocess
for _k in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"]:
    os.environ.pop(_k, None)

import sys
import time
import json
import sqlite3
import urllib.request
import ssl
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, "src")
from stock_select import repository

DB_PATH = "var/stock_select_live.db"
START = "2024-04-23"
END = "2026-05-03"
MAX_WORKERS = 20

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


def stock_to_tencent(code: str) -> str | None:
    parts = code.split(".")
    if len(parts) != 2:
        return None
    return parts[1].lower() + parts[0]


def fetch_one(code: str):
    """Fetch one stock's history from Tencent. Returns list of tuples or None."""
    tc = stock_to_tencent(code)
    if not tc:
        return None
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={tc},day,{START},{END},500,qfq"
    try:
        with urllib.request.urlopen(url, timeout=30, context=ctx) as resp:
            data = json.loads(resp.read())
    except Exception:
        return None

    item = data.get("data", {}).get(tc, {})
    if not isinstance(item, dict):
        return None
    rows = item.get("qfqday")
    if not rows:
        return None

    out = []
    for r in rows:
        if len(r) < 6:
            continue
        d, o, c, h, l, v = r[0], r[1], r[2], r[3], r[4], r[5]
        try:
            out.append((code, d, float(o), float(h), float(l), float(c), float(v)))
        except (ValueError, TypeError):
            continue
    return out


def ensure_schema(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(daily_prices)")]
    if "prev_close" not in cols:
        print("[SCHEMA] Adding prev_close...")
        conn.execute("ALTER TABLE daily_prices ADD COLUMN prev_close REAL")
        conn.commit()


def bulk_publish_day(conn, day):
    conn.execute(
        """
        INSERT INTO daily_prices(
          stock_code, trading_date, open, high, low, close, prev_close,
          volume, amount, is_suspended, is_limit_up, is_limit_down, source
        )
        SELECT
          s.stock_code, s.trading_date, s.open, s.high, s.low, s.close,
          COALESCE(
            (SELECT p.close FROM daily_prices p
             WHERE p.stock_code = s.stock_code AND p.trading_date < s.trading_date
             ORDER BY p.trading_date DESC LIMIT 1),
            s.close
          ),
          s.volume, 0, 0, 0, 0, 'tencent:backfill'
        FROM source_daily_prices s
        WHERE s.source = 'tencent' AND s.trading_date = ?
        ON CONFLICT(stock_code, trading_date) DO UPDATE SET
          open = excluded.open, high = excluded.high, low = excluded.low,
          close = excluded.close, prev_close = excluded.prev_close,
          volume = excluded.volume, is_suspended = 0,
          is_limit_up = 0, is_limit_down = 0, source = excluded.source
        """,
        (day,),
    )


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)

    codes = repository.active_stock_codes(conn)
    print(f"Active stocks: {len(codes)}")

    # Filter to stocks not already in source_daily_prices for this range
    have = set()
    for r in conn.execute(
        "SELECT DISTINCT stock_code FROM source_daily_prices WHERE source = 'tencent' AND trading_date BETWEEN ? AND ?",
        (START, END),
    ):
        have.add(r["stock_code"])
    todo = [c for c in codes if c not in have]
    print(f"Already have: {len(have)}, Need: {len(todo)}")

    if todo:
        t_start = time.time()
        total_rows = 0
        done = 0
        errors = 0

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futmap = {ex.submit(fetch_one, code): code for code in todo}
            for fut in as_completed(futmap):
                code = futmap[fut]
                done += 1
                result = fut.result()
                if not result:
                    errors += 1
                    if done % 200 == 0:
                        print(f"  [{done}/{len(todo)}] {errors} errors, {total_rows} rows, {time.time()-t_start:.0f}s")
                    continue

                for vals in result:
                    repository.upsert_source_daily_price(
                        conn, source="tencent", stock_code=vals[0],
                        trading_date=vals[1], open=vals[2], high=vals[3],
                        low=vals[4], close=vals[5], volume=vals[6], amount=0,
                    )
                total_rows += len(result)
                if done % 200 == 0:
                    conn.commit()
                    rate = done / (time.time() - t_start)
                    eta = (len(todo) - done) / rate if rate > 0 else 0
                    print(f"  [{done}/{len(todo)}] {errors} err, {total_rows} rows, "
                          f"{rate:.0f} stocks/s, ETA {eta//60:.0f}m")

        conn.commit()
        elapsed = time.time() - t_start
        print(f"Fetch done: {total_rows} rows, {errors} errors in {elapsed:.0f}s")

    # Publish
    days = [r["trading_date"] for r in conn.execute(
        "SELECT trading_date FROM trading_days WHERE is_open = 1 AND trading_date BETWEEN ? AND ? ORDER BY trading_date",
        (START, END),
    )]
    print(f"Publishing {len(days)} days...")
    t0 = time.time()
    for i, day in enumerate(days):
        bulk_publish_day(conn, day)
        if (i + 1) % 50 == 0:
            conn.commit()
    conn.commit()

    # Record data source status
    for day in days:
        cnt = conn.execute("SELECT count(*) FROM daily_prices WHERE trading_date = ?", (day,)).fetchone()[0]
        repository.record_data_source_status(
            conn, source="system", dataset="canonical_prices",
            trading_date=day, status="ok" if cnt > 0 else "warning", rows_loaded=cnt,
        )
    conn.commit()

    after = conn.execute("SELECT count(*) FROM daily_prices").fetchone()[0]
    md = conn.execute("SELECT max(trading_date) FROM daily_prices").fetchone()[0]
    print(f"Done! daily_prices: {after} rows, max: {md} (publish: {time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
