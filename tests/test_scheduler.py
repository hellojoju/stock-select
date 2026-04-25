"""Tests for Phase G1: Scheduler enhancements."""
from __future__ import annotations

import pytest

from stock_select.scheduler import create_scheduler


def _get_trigger_str(trigger: object, field_name: str) -> str | None:
    """Extract a cron field expression string from a CronTrigger."""
    for field in trigger.fields:
        if field.name == field_name:
            return str(field.expressions[0]) if field.expressions else None
    return None


def test_create_scheduler_returns_scheduler():
    """create_scheduler should return a BackgroundScheduler instance."""
    scheduler = create_scheduler()
    assert scheduler is not None
    assert scheduler.running is False


def test_scheduler_has_required_jobs():
    """Scheduler should have all required jobs."""
    scheduler = create_scheduler()
    job_ids = {job.id for job in scheduler.get_jobs()}

    expected_ids = {
        "sync_data",
        "preopen_pick",
        "open_simulation",
        "close_sync",
        "deterministic_review",
        "llm_review",
        "gene_evolution",
    }
    assert expected_ids.issubset(job_ids), f"Missing jobs: {expected_ids - job_ids}"


def test_weekday_jobs_have_day_of_week_constraint():
    """Weekday jobs should only run mon-fri."""
    scheduler = create_scheduler()
    weekday_job_ids = {
        "sync_data", "preopen_pick", "open_simulation",
        "close_sync", "deterministic_review", "llm_review",
    }

    for job in scheduler.get_jobs():
        if job.id in weekday_job_ids:
            dow = _get_trigger_str(job.trigger, "day_of_week")
            assert dow == "mon-fri", f"{job.id} has day_of_week={dow}, expected mon-fri"


def test_evolution_runs_on_saturday():
    """Gene evolution should run on Saturday at 10:00."""
    scheduler = create_scheduler()
    for job in scheduler.get_jobs():
        if job.id == "gene_evolution":
            dow = _get_trigger_str(job.trigger, "day_of_week")
            hour = _get_trigger_str(job.trigger, "hour")
            minute = _get_trigger_str(job.trigger, "minute")
            assert dow == "sat", f"day_of_week={dow}"
            assert hour == "10", f"hour={hour}"
            assert minute == "0", f"minute={minute}"
            return
    pytest.fail("gene_evolution job not found")


def test_scheduler_has_event_listener():
    """Scheduler should have an event listener registered."""
    scheduler = create_scheduler()
    assert len(scheduler._listeners) > 0


def test_scheduler_job_timing():
    """Verify specific job timing matches the trading day schedule."""
    scheduler = create_scheduler()
    job_map = {job.id: job for job in scheduler.get_jobs()}

    cases = [
        ("sync_data", "8", "0"),
        ("preopen_pick", "8", "10"),
        ("open_simulation", "9", "25"),
        ("close_sync", "15", "5"),
        ("deterministic_review", "15", "15"),
        ("llm_review", "15", "30"),
    ]
    for job_id, expected_hour, expected_minute in cases:
        job = job_map[job_id]
        hour = _get_trigger_str(job.trigger, "hour")
        minute = _get_trigger_str(job.trigger, "minute")
        assert hour == expected_hour, f"{job_id}: hour={hour}, expected {expected_hour}"
        assert minute == expected_minute, f"{job_id}: minute={minute}, expected {expected_minute}"
