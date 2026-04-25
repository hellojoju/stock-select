from __future__ import annotations

import hashlib
import sqlite3

from . import repository


def scan_blindspots(conn: sqlite3.Connection, trading_date: str, top_n: int = 10) -> list[str]:
    movers = conn.execute(
        """
        SELECT stock_code, open, close,
               CASE WHEN open > 0 THEN close / open - 1 ELSE 0 END AS return_pct
        FROM daily_prices
        WHERE trading_date = ? AND is_suspended = 0
        ORDER BY return_pct DESC
        LIMIT ?
        """,
        (trading_date, top_n),
    ).fetchall()
    active_genes = [row["gene_id"] for row in repository.get_active_genes(conn)]
    report_ids: list[str] = []
    for rank, row in enumerate(movers, start=1):
        picked_rows = conn.execute(
            """
            SELECT strategy_gene_id FROM pick_decisions
            WHERE trading_date = ? AND stock_code = ?
            """,
            (trading_date, row["stock_code"]),
        ).fetchall()
        picked = {item["strategy_gene_id"] for item in picked_rows}
        missed = [gene_id for gene_id in active_genes if gene_id not in picked]
        was_picked = bool(picked)
        report_id = build_report_id(trading_date, row["stock_code"])
        reason = "picked by at least one gene" if was_picked else "top mover was not selected pre-open"
        conn.execute(
            """
            INSERT INTO blindspot_reports(
              report_id, trading_date, stock_code, rank, return_pct,
              was_picked, missed_by_gene_ids_json, reason
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(trading_date, stock_code) DO UPDATE SET
              rank = excluded.rank,
              return_pct = excluded.return_pct,
              was_picked = excluded.was_picked,
              missed_by_gene_ids_json = excluded.missed_by_gene_ids_json,
              reason = excluded.reason
            """,
            (
                report_id,
                trading_date,
                row["stock_code"],
                rank,
                float(row["return_pct"]),
                int(was_picked),
                repository.dumps(missed),
                reason,
            ),
        )
        report_ids.append(report_id)
    conn.commit()
    return report_ids


def build_report_id(trading_date: str, stock_code: str) -> str:
    raw = f"{trading_date}:{stock_code}"
    return "blind_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]

