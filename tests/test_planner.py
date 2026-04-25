"""Tests for Phase F1: Planner Agent."""
from __future__ import annotations

import os
import pytest

from stock_select.db import connect, init_db
from stock_select.seed import seed_demo_data
from stock_select.planner import plan_preopen_focus


@pytest.fixture()
def demo_db(tmp_path):
    conn = connect(tmp_path / "demo.db")
    init_db(conn)
    seed_demo_data(conn)
    conn.commit()
    return conn


class TestPlanPreopenFocus:
    def test_returns_plan_without_llm(self, demo_db):
        """Without API key, plan should have llm_notes=None."""
        api_key = os.environ.pop("ANTHROPIC_API_KEY", None)
        claude_key = os.environ.pop("CLAUDE_API_KEY", None)

        plan = plan_preopen_focus(demo_db, "2026-01-12")

        assert plan["trading_date"] == "2026-01-12"
        assert plan["llm_notes"] is None
        assert isinstance(plan["focus_sectors"], list)
        assert isinstance(plan["watch_risks"], list)

        if api_key:
            os.environ["ANTHROPIC_API_KEY"] = api_key
        if claude_key:
            os.environ["CLAUDE_API_KEY"] = claude_key

    def test_plan_includes_sectors(self, demo_db):
        """Plan should include seeded sector signals."""
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("CLAUDE_API_KEY", None)

        plan = plan_preopen_focus(demo_db, "2026-01-12")
        industries = [s["industry"] for s in plan["focus_sectors"]]
        assert "Battery" in industries
        assert "Food" in industries

    def test_plan_includes_risks(self, demo_db):
        """Plan should detect ST stocks as risks."""
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("CLAUDE_API_KEY", None)

        demo_db.execute("UPDATE stocks SET is_st = 1 WHERE stock_code = '000001.SZ'")
        demo_db.commit()

        plan = plan_preopen_focus(demo_db, "2026-01-12")
        assert any("ST" in risk for risk in plan["watch_risks"])

    def test_plan_handles_missing_date_gracefully(self, demo_db):
        """Plan should work even with no data for the date."""
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("CLAUDE_API_KEY", None)

        plan = plan_preopen_focus(demo_db, "2099-01-01")
        assert plan["trading_date"] == "2099-01-01"
        assert plan["focus_sectors"] == []
