from __future__ import annotations

import pytest

from stock_select.db import connect, init_db
from stock_select.next_day_plan import (
    NextDayPlan,
    build_next_day_plan,
    generate_next_day_plan,
    get_next_day_plan,
)


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    init_db(conn)
    yield conn
    conn.close()


def _seed_data(conn):
    conn.execute(
        "INSERT INTO stocks (stock_code, name, industry, listing_status) VALUES (?, ?, ?, ?)",
        ("000001.SZ", "平安银行", "银行", "active"),
    )
    conn.execute(
        "INSERT INTO strategy_genes (gene_id, name, horizon, risk_profile, params_json) VALUES (?, ?, ?, ?, ?)",
        ("gene1", "Test Gene", "short", "medium", "{}"),
    )
    conn.execute(
        "INSERT INTO pick_decisions (decision_id, trading_date, horizon, strategy_gene_id, stock_code, action, confidence, position_pct, score, entry_plan_json, sell_rules_json, thesis_json, risks_json, invalid_if_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("dec1", "2024-01-15", "short", "gene1", "000001.SZ", "BUY", 0.8, 0.1, 0.7, "{}", "{}", "{}", "{}", "{}"),
    )
    conn.execute(
        "INSERT INTO decision_reviews (review_id, decision_id, trading_date, strategy_gene_id, stock_code, verdict, primary_driver, return_pct, relative_return_pct, max_drawdown_intraday_pct, thesis_quality_score, evidence_quality_score, deterministic_json, summary) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("rev1", "dec1", "2024-01-15", "gene1", "000001.SZ", "RIGHT", "technical", 5.0, 3.0, -1.0, 0.8, 0.7, "{}", "Summary"),
    )
    # Seed 20 trading days for MA calculation
    for i in range(20):
        d = f"2024-01-{i + 1:02d}"
        conn.execute(
            "INSERT OR IGNORE INTO trading_days (trading_date, is_open) VALUES (?, ?)",
            (d, 1),
        )
    for i in range(20):
        d = f"2024-01-{i + 1:02d}"
        close = 10.0 + i * 0.5
        conn.execute(
            "INSERT INTO daily_prices (stock_code, trading_date, open, high, low, close, volume, amount, is_limit_up, is_limit_down) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("000001.SZ", d, close - 0.5, close + 0.5, close - 1.0, close, 10000, 100000, 0, 0),
        )
    # Sentiment cycle
    conn.execute(
        "INSERT INTO sentiment_cycle_daily (trading_date, advance_count, decline_count, limit_up_count, limit_down_count, cycle_phase, composite_sentiment) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("2024-01-15", 3000, 1000, 50, 5, "升温", 0.4),
    )
    # Sector analysis
    conn.execute(
        "INSERT INTO sector_analysis_daily (trading_date, sector_name, sector_return_pct, sustainability, team_complete) VALUES (?, ?, ?, ?, ?)",
        ("2024-01-15", "银行", 2.5, 0.8, 1),
    )
    conn.commit()


def test_build_next_day_plan(db):
    _seed_data(db)
    plan = build_next_day_plan(db, "rev1")
    assert plan is not None
    assert plan.decision_review_id == "rev1"
    assert len(plan.scenarios) == 3
    conditions = [s.condition for s in plan.scenarios]
    assert "高开3%以上" in conditions
    assert "平开（-2% ~ +3%）" in conditions
    assert "低开2%以下" in conditions
    assert len(plan.key_levels) >= 1


def test_save_and_get_next_day_plan(db):
    _seed_data(db)
    plan = build_next_day_plan(db, "rev1")
    from stock_select.next_day_plan import save_next_day_plan
    save_next_day_plan(db, plan)

    loaded = get_next_day_plan(db, "rev1")
    assert loaded is not None
    assert len(loaded.scenarios) == 3


def test_generate_next_day_plan(db):
    _seed_data(db)
    plan = generate_next_day_plan(db, "rev1")
    assert plan is not None
    loaded = get_next_day_plan(db, "rev1")
    assert loaded is not None


def test_get_missing_next_day_plan(db):
    result = get_next_day_plan(db, "nonexistent")
    assert result is None
