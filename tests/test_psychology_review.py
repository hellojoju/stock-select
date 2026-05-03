from __future__ import annotations

import pytest

from stock_select.db import connect, init_db
from stock_select.psychology_review import (
    PsychologyReview,
    build_psychology_review,
    generate_psychology_review,
    get_psychology_review,
)


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    init_db(conn)
    yield conn
    conn.close()


def _seed_right_review(conn):
    conn.execute(
        """
        INSERT INTO stocks (stock_code, name, industry, listing_status) VALUES (?, ?, ?, ?)
        """,
        ("000001.SZ", "平安银行", "银行", "active"),
    )
    conn.execute(
        """
        INSERT INTO strategy_genes (gene_id, name, horizon, risk_profile, params_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("gene1", "Test Gene", "short", "medium", "{}"),
    )
    conn.execute(
        """
        INSERT INTO pick_decisions (decision_id, trading_date, horizon, strategy_gene_id, stock_code, action, confidence, position_pct, score, entry_plan_json, sell_rules_json, thesis_json, risks_json, invalid_if_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("dec1", "2024-01-15", "short", "gene1", "000001.SZ", "BUY", 0.8, 0.1, 0.7, "{}", "{}", "{}", "{}", "{}"),
    )
    conn.execute(
        """
        INSERT INTO decision_reviews (review_id, decision_id, trading_date, strategy_gene_id, stock_code, verdict, primary_driver, return_pct, relative_return_pct, max_drawdown_intraday_pct, thesis_quality_score, evidence_quality_score, deterministic_json, summary)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("rev1", "dec1", "2024-01-15", "gene1", "000001.SZ", "RIGHT", "technical", 5.0, 3.0, -1.0, 0.8, 0.7, "{}", "Summary"),
    )
    conn.commit()


def _seed_wrong_review(conn):
    conn.execute(
        """
        INSERT INTO stocks (stock_code, name, industry, listing_status) VALUES (?, ?, ?, ?)
        """,
        ("000002.SZ", "万科A", "房地产", "active"),
    )
    conn.execute(
        """
        INSERT INTO strategy_genes (gene_id, name, horizon, risk_profile, params_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("gene2", "Test Gene 2", "short", "medium", "{}"),
    )
    conn.execute(
        """
        INSERT INTO pick_decisions (decision_id, trading_date, horizon, strategy_gene_id, stock_code, action, confidence, position_pct, score, entry_plan_json, sell_rules_json, thesis_json, risks_json, invalid_if_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("dec2", "2024-01-15", "short", "gene2", "000002.SZ", "BUY", 0.7, 0.1, 0.6, "{}", "{}", "{}", "{}", "{}"),
    )
    conn.execute(
        """
        INSERT INTO decision_reviews (review_id, decision_id, trading_date, strategy_gene_id, stock_code, verdict, primary_driver, return_pct, relative_return_pct, max_drawdown_intraday_pct, thesis_quality_score, evidence_quality_score, deterministic_json, summary)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("rev2", "dec2", "2024-01-15", "gene2", "000002.SZ", "WRONG", "technical", -5.0, -3.0, -4.0, 0.5, 0.4, "{}", "Summary"),
    )
    conn.execute(
        """
        INSERT INTO review_errors (error_id, review_scope, review_id, error_type, severity, confidence, evidence_ids_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("err1", "decision", "rev2", "overweighted_technical", 0.8, 0.9, "[]"),
    )
    conn.execute(
        """
        INSERT INTO review_errors (error_id, review_scope, review_id, error_type, severity, confidence, evidence_ids_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("err2", "decision", "rev2", "missed_earnings_surprise", 0.7, 0.8, "[]"),
    )
    conn.commit()


def test_build_psychology_review_right(db):
    _seed_right_review(db)
    review = build_psychology_review(db, "rev1")
    assert review.decision_review_id == "rev1"
    assert review.psychological_category == "执行到位"
    assert len(review.success_reasons) > 0
    assert len(review.failure_reasons) == 0
    assert len(review.reproducible_patterns) > 0


def test_build_psychology_review_wrong(db):
    _seed_wrong_review(db)
    review = build_psychology_review(db, "rev2")
    assert review.decision_review_id == "rev2"
    assert review.psychological_category in ("技术误判", "消息遗漏")
    assert len(review.failure_reasons) > 0
    assert len(review.prevention_strategies) > 0


def test_save_and_get_psychology_review(db):
    _seed_wrong_review(db)
    review = build_psychology_review(db, "rev2")
    from stock_select.psychology_review import save_psychology_review
    save_psychology_review(db, review)

    loaded = get_psychology_review(db, "rev2")
    assert loaded is not None
    assert loaded.psychological_category == review.psychological_category


def test_generate_psychology_review(db):
    _seed_right_review(db)
    review = generate_psychology_review(db, "rev1")
    assert review.psychological_category == "执行到位"
    loaded = get_psychology_review(db, "rev1")
    assert loaded is not None


def test_get_missing_psychology_review(db):
    result = get_psychology_review(db, "nonexistent")
    assert result is None
