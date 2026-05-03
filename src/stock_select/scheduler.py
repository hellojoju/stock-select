from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from .agent_runtime import run_phase
from .db import connect, init_db, _DEFAULT_DB
from .strategies import seed_default_genes

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "Asia/Shanghai"

_scheduler_instance = None


def create_scheduler(db_path: str | Path = _DEFAULT_DB):
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

    def execute(phase: str, max_retries: int = 2) -> None:
        """Execute a phase with automatic retry on failure."""
        conn = connect(db_path)
        try:
            init_db(conn)
            seed_default_genes(conn)
            last_error = None
            for attempt in range(max_retries + 1):
                try:
                    run_phase(conn, phase, date.today().isoformat())
                    return  # success
                except Exception as e:
                    last_error = e
                    if attempt < max_retries:
                        logger.warning("Phase %s attempt %d failed, retrying: %s", phase, attempt + 1, e)
                        import time
                        time.sleep(2 ** attempt * 5)  # exponential backoff: 5s, 10s, 20s
            # All retries exhausted
            logger.error("Phase %s failed after %d retries: %s", phase, max_retries, last_error)
            raise last_error
        except Exception:
            logger.exception("Phase %s failed on %s", phase, date.today().isoformat())
            raise
        finally:
            conn.close()

    # 7:00 - 数据同步（行情、价格、环境）
    scheduler.add_job(lambda: execute("sync_data"), "cron", hour=7, minute=0, day_of_week="mon-fri", id="sync_data", replace_existing=True)
    # 7:15 - 市场概览（涨跌家数、指数等）
    scheduler.add_job(lambda: execute("sync_market_breadth"), "cron", hour=7, minute=15, day_of_week="mon-fri", id="sync_market_breadth", replace_existing=True)
    # 7:20 - 因子数据（基本面、板块、事件）
    scheduler.add_job(lambda: execute("sync_factors"), "cron", hour=7, minute=20, day_of_week="mon-fri", id="sync_factors", replace_existing=True)
    # 7:50 - 预盘选股
    scheduler.add_job(lambda: execute("preopen_pick"), "cron", hour=7, minute=50, day_of_week="mon-fri", id="preopen_pick", replace_existing=True)
    # 9:30 - 模拟交易（开盘后用开盘价模拟买入，收盘后评估收益）
    scheduler.add_job(lambda: execute("simulate"), "cron", hour=9, minute=30, day_of_week="mon-fri", id="simulate", replace_existing=True)
    # 15:05 - 收盘数据同步
    scheduler.add_job(lambda: execute("sync_data"), "cron", hour=15, minute=5, day_of_week="mon-fri", id="close_sync", replace_existing=True)
    # 15:15 - 收盘因子同步（板块信号等）
    scheduler.add_job(lambda: execute("sync_factors"), "cron", hour=15, minute=15, day_of_week="mon-fri", id="close_factors", replace_existing=True)
    # 15:30 - 确定性复盘
    scheduler.add_job(lambda: execute("deterministic_review"), "cron", hour=15, minute=30, day_of_week="mon-fri", id="deterministic_review", replace_existing=True)
    # 15:45 - LLM 复盘（如果有 API key）
    scheduler.add_job(lambda: execute("llm_review"), "cron", hour=15, minute=45, day_of_week="mon-fri", id="llm_review", replace_existing=True)
    # 16:00 - 证据数据同步（财务、订单、KPI、风险事件）
    scheduler.add_job(lambda: execute("sync_evidence"), "cron", hour=16, minute=0, day_of_week="mon-fri", id="sync_evidence", replace_existing=True)
    # 周六 10:00 - 策略进化
    scheduler.add_job(lambda: execute("evolve"), "cron", day_of_week="sat", hour=10, minute=0, id="gene_evolution", replace_existing=True)
    # 周六 11:00 - 环境表现统计更新
    scheduler.add_job(lambda: _reconcile_env_performance(db_path), "cron", day_of_week="sat", hour=11, minute=0, id="env_performance_reconcile", replace_existing=True)

    # Announcement hunter: scan every 5 min during trading hours
    scheduler.add_job(
        lambda: _run_announcement_scan(db_path),
        "cron",
        day_of_week="mon-fri",
        hour="9-11",
        minute="*/5",
        id="announcement_scan_morning",
        replace_existing=True,
    )
    scheduler.add_job(
        lambda: _run_announcement_scan(db_path),
        "cron",
        day_of_week="mon-fri",
        hour="13-14",
        minute="*/5",
        id="announcement_scan_afternoon",
        replace_existing=True,
    )

    return scheduler


def _run_announcement_scan(db_path: str | Path) -> None:
    """Run announcement scan during trading hours."""
    from .announcement_monitor import run_announcement_scan
    conn = connect(db_path)
    try:
        init_db(conn)
        seed_default_genes(conn)
        alerts = run_announcement_scan(conn)
        if alerts:
            logger.info("Announcement scan found %d new bullish alerts", len(alerts))
            for a in alerts:
                logger.info(
                    "  [%s] %s %s - %s",
                    a.stock_code, a.alert_type, a.title[:40], a.source,
                )
    except Exception:
        logger.exception("Announcement scan failed")
    finally:
        conn.close()


def _reconcile_env_performance(db_path: str | Path) -> None:
    """Reconcile gene performance by market environment."""
    from .evolution import reconcile_environment_performance
    from datetime import date, timedelta
    conn = connect(db_path)
    try:
        init_db(conn)
        end = date.today()
        start = end - timedelta(days=30)
        results = reconcile_environment_performance(
            conn,
            period_start=start.isoformat(),
            period_end=end.isoformat(),
        )
        if results:
            logger.info("Environment performance reconciled: %d gene-environment records", len(results))
            for r in results:
                logger.info(
                    "  %s in %s: %d trades, %.0f%% win rate, alpha %.2f%%",
                    r["gene_id"], r["market_environment"],
                    r["trade_count"], r["win_rate"] * 100,
                    (r["alpha"] or 0) * 100,
                )
    except Exception:
        logger.exception("Environment performance reconciliation failed")
    finally:
        conn.close()


def start_scheduler(db_path: str | Path = _DEFAULT_DB) -> None:
    """Create and start the background scheduler globally."""
    global _scheduler_instance
    if _scheduler_instance is not None and _scheduler_instance.running:
        return
    _scheduler_instance = create_scheduler(db_path)
    _scheduler_instance.start()
    logger.info("Scheduler started with %d jobs", len(_scheduler_instance.get_jobs()))


def stop_scheduler() -> None:
    """Shutdown the scheduler gracefully."""
    global _scheduler_instance
    if _scheduler_instance is not None:
        _scheduler_instance.shutdown(wait=False)
        _scheduler_instance = None
        logger.info("Scheduler stopped")


def get_scheduler_status() -> dict:
    """Return scheduler status for the API."""
    global _scheduler_instance
    if _scheduler_instance is None:
        return {"running": False, "jobs": [], "message": "Scheduler not started"}
    jobs = []
    for job in _scheduler_instance.get_jobs():
        next_run = job.next_run_time.isoformat() if job.next_run_time else None
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": next_run,
            "paused": job.next_run_time is None,
        })
    return {
        "running": _scheduler_instance.running,
        "jobs": jobs,
    }


def pause_announcement_scan() -> bool:
    """Pause announcement scan jobs."""
    global _scheduler_instance
    if _scheduler_instance is None:
        return False
    for job_id in ("announcement_scan_morning", "announcement_scan_afternoon"):
        try:
            _scheduler_instance.pause_job(job_id)
        except Exception:
            pass
    logger.info("Announcement scan paused")
    return True


def resume_announcement_scan() -> bool:
    """Resume announcement scan jobs."""
    global _scheduler_instance
    if _scheduler_instance is None:
        return False
    for job_id in ("announcement_scan_morning", "announcement_scan_afternoon"):
        try:
            _scheduler_instance.resume_job(job_id)
        except Exception:
            pass
    logger.info("Announcement scan resumed")
    return True


def is_scan_paused() -> bool:
    """Check if announcement scan is currently paused."""
    global _scheduler_instance
    if _scheduler_instance is None:
        return True
    job = _scheduler_instance.get_job("announcement_scan_morning")
    return job is not None and job.next_run_time is None

