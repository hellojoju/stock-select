from __future__ import annotations

import sqlite3

import pytest

from stock_select import repository
from stock_select.blindspot_review import upsert_blindspot_review
from stock_select.db import init_db
from stock_select.deterministic_review import review_decision
from stock_select.gene_review import review_gene
from stock_select.review_packets import stock_review
from stock_select.seed import seed_default_genes
from stock_select.system_review import run_system_review


@pytest.fixture()
def conn() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    init_db(db)
    seed_default_genes(db)
    repository.upsert_stock(db, "000001.SZ", "Evidence Winner", industry="Bank")
    repository.upsert_stock(db, "000002.SZ", "Risk Loser", industry="Bank")
    repository.upsert_trading_day(db, "2024-01-10", True, index_return_pct=0.0)
    for stock_code, close in [("000001.SZ", 11.0), ("000002.SZ", 9.0)]:
        repository.upsert_daily_price(
            db,
            stock_code=stock_code,
            trading_date="2024-01-10",
            open=10,
            high=max(10, close),
            low=min(10, close),
            close=close,
            volume=1_000_000,
            amount=10_000_000,
            source="test",
        )
    db.commit()
    return db


def insert_pick(
    conn: sqlite3.Connection,
    *,
    decision_id: str,
    stock_code: str,
    return_pct: float,
    fundamental_score: float = 0.0,
    event_score: float = 0.0,
    risk_penalty: float = 0.0,
) -> None:
    conn.execute(
        """
        INSERT INTO pick_decisions(
          decision_id, trading_date, horizon, strategy_gene_id, stock_code,
          action, confidence, position_pct, score, entry_plan_json,
          sell_rules_json, thesis_json, risks_json, invalid_if_json
        )
        VALUES (?, '2024-01-10', 'short', 'gene_aggressive_v1', ?, 'BUY', 0.7, 0.05, 0.6, '{}', '{}',
                '{"technical":"momentum","fundamental":"", "news":"", "market_environment":"range"}', '{}', '{}')
        """,
        (decision_id, stock_code),
    )
    conn.execute(
        """
        INSERT INTO outcomes(
          outcome_id, decision_id, entry_price, exit_price, close_price,
          return_pct, max_drawdown_intraday_pct, hit_sell_rule
        )
        VALUES (?, ?, 10, ?, ?, ?, -0.02, 'none')
        """,
        (f"out_{decision_id}", decision_id, 10 * (1 + return_pct), 10 * (1 + return_pct), return_pct),
    )
    packet = {
        "missing_fields": [],
        "technical": {"score": 0.5},
        "fundamental": {"score": fundamental_score},
        "event": {"score": event_score},
        "risk": {"score": risk_penalty},
    }
    repository.upsert_candidate_score(
        conn,
        candidate_id=f"cand_{decision_id}",
        trading_date="2024-01-10",
        strategy_gene_id="gene_aggressive_v1",
        stock_code=stock_code,
        total_score=0.5,
        technical_score=0.5,
        fundamental_score=fundamental_score,
        event_score=event_score,
        sector_score=0.1,
        risk_penalty=risk_penalty,
        packet_json=repository.dumps(packet),
    )
    conn.commit()


def seed_positive_evidence(conn: sqlite3.Connection) -> None:
    actual_id = repository.upsert_financial_actual(
        conn,
        stock_code="000001.SZ",
        report_period="2023Q4",
        publish_date="2024-01-08",
        as_of_date="2024-01-09",
        revenue=150,
        net_profit=150,
        source="test",
    )
    expectation_id = repository.upsert_analyst_expectation(
        conn,
        stock_code="000001.SZ",
        report_date="2024-01-05",
        forecast_period="2023Q4",
        forecast_revenue=100,
        forecast_net_profit=100,
        source="test",
    )
    repository.upsert_earnings_surprise(
        conn,
        stock_code="000001.SZ",
        report_period="2023Q4",
        as_of_date="2024-01-09",
        actual_id=actual_id,
        expectation_snapshot_id=expectation_id,
        expected_net_profit=100,
        actual_net_profit=150,
        surprise_type="positive_surprise",
    )
    repository.upsert_order_contract_event(
        conn,
        stock_code="000001.SZ",
        publish_date="2024-01-09",
        event_type="major_contract",
        title="重大合同公告",
        source="test",
        impact_score=0.5,
    )
    repository.upsert_business_kpi_actual(
        conn,
        stock_code="000001.SZ",
        report_period="2023Q4",
        publish_date="2024-01-09",
        as_of_date="2024-01-09",
        kpi_name="orders",
        kpi_value=200,
        kpi_unit="CNY",
        kpi_yoy=0.3,
        source="test",
    )
    conn.commit()


def seed_risk_evidence(conn: sqlite3.Connection) -> None:
    repository.upsert_risk_event(
        conn,
        stock_code="000002.SZ",
        event_date="2024-01-08",
        publish_date="2024-01-08",
        as_of_date="2024-01-09",
        risk_type="litigation",
        title="重大诉讼公告",
        source="test",
        impact_score=-0.5,
    )
    conn.commit()


def test_decision_review_links_phase_c_evidence_and_errors(conn: sqlite3.Connection) -> None:
    seed_positive_evidence(conn)
    insert_pick(conn, decision_id="pick_pos", stock_code="000001.SZ", return_pct=0.04)

    review_id = review_decision(conn, "pick_pos")

    source_types = {
        row["source_type"]
        for row in conn.execute("SELECT source_type FROM review_evidence WHERE review_id = ?", (review_id,))
    }
    assert {
        "financial_actual",
        "analyst_expectation",
        "earnings_surprise",
        "order_contract",
        "business_kpi",
    }.issubset(source_types)

    factor_types = {
        row["factor_type"]
        for row in conn.execute("SELECT factor_type FROM factor_review_items WHERE review_id = ?", (review_id,))
    }
    assert {"earnings_surprise", "order_contract", "business_kpi", "expectation"}.issubset(factor_types)

    errors = {
        row["error_type"]
        for row in conn.execute("SELECT error_type FROM review_errors WHERE review_id = ?", (review_id,))
    }
    assert {"missed_earnings_surprise", "missed_order_signal", "missed_business_kpi_signal"}.issubset(errors)
    order_error = conn.execute(
        "SELECT evidence_ids_json FROM review_errors WHERE review_id = ? AND error_type = 'missed_order_signal'",
        (review_id,),
    ).fetchone()
    order_evidence_ids = repository.loads(order_error["evidence_ids_json"], [])
    order_sources = {
        row["source_type"]
        for row in conn.execute(
            f"SELECT source_type FROM review_evidence WHERE evidence_id IN ({','.join('?' for _ in order_evidence_ids)})",
            order_evidence_ids,
        )
    }
    assert "order_contract" in order_sources


def test_risk_event_review_and_stock_packet_use_risk_events_table(conn: sqlite3.Connection) -> None:
    seed_risk_evidence(conn)
    insert_pick(conn, decision_id="pick_risk", stock_code="000002.SZ", return_pct=-0.03, risk_penalty=0.0)

    review_id = review_decision(conn, "pick_risk")

    assert conn.execute(
        "SELECT COUNT(*) AS c FROM review_evidence WHERE review_id = ? AND source_type = 'risk_event'",
        (review_id,),
    ).fetchone()["c"] == 1
    assert conn.execute(
        "SELECT COUNT(*) AS c FROM review_errors WHERE review_id = ? AND error_type = 'missed_risk_event'",
        (review_id,),
    ).fetchone()["c"] == 1

    packet = stock_review(conn, "000002.SZ", "2024-01-10")
    assert len(packet["domain_facts"]["risk_events"]) == 1


def test_gene_and_system_reviews_include_evidence_metrics(conn: sqlite3.Connection) -> None:
    seed_positive_evidence(conn)
    seed_risk_evidence(conn)
    insert_pick(conn, decision_id="pick_pos", stock_code="000001.SZ", return_pct=0.04)
    insert_pick(conn, decision_id="pick_risk", stock_code="000002.SZ", return_pct=-0.03, risk_penalty=0.0)
    review_decision(conn, "pick_pos")
    review_decision(conn, "pick_risk")

    gene_review_id = review_gene(conn, gene_id="gene_aggressive_v1", period_start="2024-01-10", period_end="2024-01-10")
    gene = conn.execute("SELECT * FROM gene_reviews WHERE gene_review_id = ?", (gene_review_id,)).fetchone()
    edges = repository.loads(gene["factor_edges_json"], {})
    deterministic = repository.loads(gene["deterministic_json"], {})
    assert "earnings_surprise" in edges
    assert "risk_event" in edges
    assert deterministic["evidence_coverage"]["financial_actuals"] == 0.5

    system_review_id = run_system_review(conn, "2024-01-10")
    system = conn.execute("SELECT observation_json FROM system_reviews WHERE system_review_id = ?", (system_review_id,)).fetchone()
    observation = repository.loads(system["observation_json"], {})
    assert observation["evidence_coverage"]["counts"]["financial_actuals"] == 1
    assert observation["evidence_coverage"]["counts"]["risk_events"] == 1


def test_blindspot_review_prefers_evidence_specific_error(conn: sqlite3.Connection) -> None:
    seed_positive_evidence(conn)
    conn.execute(
        """
        INSERT INTO blindspot_reports(
          report_id, trading_date, stock_code, rank, return_pct,
          was_picked, missed_by_gene_ids_json, reason
        )
        VALUES ('blind_1', '2024-01-10', '000001.SZ', 1, 0.08, 0, '["gene_aggressive_v1"]', 'top gainer')
        """
    )
    conn.commit()
    report = conn.execute(
        """
        SELECT b.*, s.industry
        FROM blindspot_reports b
        JOIN stocks s ON s.stock_code = b.stock_code
        WHERE b.report_id = 'blind_1'
        """
    ).fetchone()
    review_id = upsert_blindspot_review(conn, report)

    error = conn.execute(
        "SELECT error_type FROM review_errors WHERE review_scope = 'blindspot' AND review_id = ?",
        (review_id,),
    ).fetchone()
    assert error["error_type"] == "missed_earnings_surprise"
    signal = conn.execute(
        "SELECT signal_type FROM optimization_signals WHERE source_type = 'blindspot_review' AND source_id = ?",
        (review_id,),
    ).fetchone()
    assert signal["signal_type"] == "increase_earnings_surprise_weight"
