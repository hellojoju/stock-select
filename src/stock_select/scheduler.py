from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from .agent_runtime import run_phase
from .db import connect, init_db
from .strategies import seed_default_genes

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "Asia/Shanghai"


def create_scheduler(db_path: str | Path = "var/stock_select.db"):
    try:
        from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore[import-not-found]
        from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("APScheduler is not installed. Install scheduler dependencies first.") from exc

    scheduler = BackgroundScheduler(timezone=DEFAULT_TIMEZONE)

    def _job_listener(event):
        if event.exception:
            logger.error("Scheduled job %s failed: %s", event.job_id, event.exception)
        else:
            logger.info("Scheduled job %s completed successfully", event.job_id)

    scheduler.add_listener(_job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

    def execute(phase: str) -> None:
        conn = connect(db_path)
        try:
            init_db(conn)
            seed_default_genes(conn)
            run_phase(conn, phase, date.today().isoformat())
        except Exception:
            logger.exception("Phase %s failed on %s", phase, date.today().isoformat())
            raise
        finally:
            conn.close()

    # 8:00 - 数据同步
    scheduler.add_job(lambda: execute("sync_data"), "cron", hour=8, minute=0, day_of_week="mon-fri", id="sync_data", replace_existing=True)
    # 8:10 - 预盘选股
    scheduler.add_job(lambda: execute("preopen_pick"), "cron", hour=8, minute=10, day_of_week="mon-fri", id="preopen_pick", replace_existing=True)
    # 9:25 - 模拟开盘
    scheduler.add_job(lambda: execute("simulate"), "cron", hour=9, minute=25, day_of_week="mon-fri", id="open_simulation", replace_existing=True)
    # 15:05 - 收盘数据同步
    scheduler.add_job(lambda: execute("sync_data"), "cron", hour=15, minute=5, day_of_week="mon-fri", id="close_sync", replace_existing=True)
    # 15:15 - 确定性复盘
    scheduler.add_job(lambda: execute("deterministic_review"), "cron", hour=15, minute=15, day_of_week="mon-fri", id="deterministic_review", replace_existing=True)
    # 15:30 - LLM 复盘（如果有 API key）
    scheduler.add_job(lambda: execute("llm_review"), "cron", hour=15, minute=30, day_of_week="mon-fri", id="llm_review", replace_existing=True)
    # 周六 10:00 - 策略进化
    scheduler.add_job(lambda: execute("evolve"), "cron", day_of_week="sat", hour=10, minute=0, id="gene_evolution", replace_existing=True)
    return scheduler

