from __future__ import annotations

from datetime import date
from pathlib import Path

from .agent_runtime import run_phase
from .db import connect, init_db
from .strategies import seed_default_genes


DEFAULT_TIMEZONE = "Asia/Shanghai"


def create_scheduler(db_path: str | Path = "var/stock_select.db"):
    try:
        from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("APScheduler is not installed. Install scheduler dependencies first.") from exc

    scheduler = BackgroundScheduler(timezone=DEFAULT_TIMEZONE)

    def execute(phase: str) -> None:
        conn = connect(db_path)
        try:
            init_db(conn)
            seed_default_genes(conn)
            run_phase(conn, phase, date.today().isoformat())
        finally:
            conn.close()

    scheduler.add_job(lambda: execute("sync_data"), "cron", hour=8, minute=0, id="preopen_prepare", replace_existing=True)
    scheduler.add_job(lambda: execute("preopen_pick"), "cron", hour=8, minute=10, id="preopen_pick", replace_existing=True)
    scheduler.add_job(lambda: execute("simulate"), "cron", hour=9, minute=25, id="open_simulation", replace_existing=True)
    scheduler.add_job(lambda: execute("simulate"), "cron", hour=15, minute=5, id="close_sync", replace_existing=True)
    scheduler.add_job(lambda: execute("review"), "cron", hour=15, minute=30, id="daily_review", replace_existing=True)
    scheduler.add_job(lambda: execute("evolve"), "cron", day_of_week="sat", hour=10, minute=0, id="gene_evolution", replace_existing=True)
    return scheduler

