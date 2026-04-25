from __future__ import annotations

import sqlite3

import pytest

from stock_select import repository
from stock_select.db import init_db
from stock_select.review_taxonomy import (
    ERROR_TYPES,
    SIGNAL_TYPES,
    ReviewTaxonomyError,
)


@pytest.fixture()
def conn() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    init_db(db)
    db.execute("INSERT INTO stocks(stock_code, name) VALUES ('000001.SZ', 'Ping An Bank')")
    db.commit()
    return db


def column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_evidence_schema_init_is_idempotent(conn: sqlite3.Connection) -> None:
    init_db(conn)
    init_db(conn)

    assert {
        "actual_id",
        "publish_date",
        "as_of_date",
        "deducted_net_profit",
        "debt_to_assets",
        "source_fetched_at",
        "confidence",
        "raw_json",
    }.issubset(column_names(conn, "financial_actuals"))
    assert {"source_fetched_at", "confidence", "raw_json"}.issubset(
        column_names(conn, "analyst_expectations")
    )
    assert {
        "surprise_amount",
        "surprise_pct",
        "surprise_type",
        "as_of_date",
        "evidence_level",
        "confidence",
        "raw_json",
    }.issubset(column_names(conn, "earnings_surprises"))
    assert {
        "publish_date",
        "as_of_date",
        "title",
        "summary",
        "contract_amount_pct_revenue",
        "counterparty",
        "duration",
        "impact_score",
        "source_fetched_at",
        "raw_json",
    }.issubset(column_names(conn, "order_contract_events"))
    assert {
        "report_period",
        "publish_date",
        "as_of_date",
        "kpi_unit",
        "kpi_yoy",
        "kpi_qoq",
        "industry",
        "source_fetched_at",
        "raw_json",
    }.issubset(column_names(conn, "business_kpi_actuals"))
    assert {
        "risk_event_id",
        "stock_code",
        "event_date",
        "publish_date",
        "as_of_date",
        "risk_type",
        "severity",
        "title",
        "impact_score",
        "confidence",
        "raw_json",
    }.issubset(column_names(conn, "risk_events"))


def test_evidence_upserts_are_idempotent(conn: sqlite3.Connection) -> None:
    actual_id = repository.upsert_financial_actual(
        conn,
        stock_code="000001.SZ",
        report_period="2023Q4",
        publish_date="2024-01-10",
        as_of_date="2024-01-11",
        revenue=100,
        net_profit=10,
        source="test",
    )
    repository.upsert_financial_actual(
        conn,
        stock_code="000001.SZ",
        report_period="2023Q4",
        publish_date="2024-01-10",
        as_of_date="2024-01-11",
        revenue=120,
        net_profit=12,
        source="test",
        actual_id=actual_id,
    )
    assert conn.execute("SELECT COUNT(*) AS c FROM financial_actuals").fetchone()["c"] == 1
    assert conn.execute("SELECT revenue FROM financial_actuals").fetchone()["revenue"] == 120

    expectation_id = repository.upsert_analyst_expectation(
        conn,
        stock_code="000001.SZ",
        report_date="2024-01-05",
        forecast_period="2023Q4",
        forecast_net_profit=8,
        org_name="Org",
        author_name="Analyst",
        source="test",
    )
    repository.upsert_analyst_expectation(
        conn,
        stock_code="000001.SZ",
        report_date="2024-01-05",
        forecast_period="2023Q4",
        forecast_net_profit=9,
        org_name="Org",
        author_name="Analyst",
        source="test",
        expectation_id=expectation_id,
    )
    assert conn.execute("SELECT COUNT(*) AS c FROM analyst_expectations").fetchone()["c"] == 1
    assert conn.execute("SELECT forecast_net_profit FROM analyst_expectations").fetchone()[0] == 9

    repository.upsert_earnings_surprise(
        conn,
        stock_code="000001.SZ",
        report_period="2023Q4",
        as_of_date="2024-01-11",
        expected_net_profit=9,
        actual_net_profit=12,
        surprise_type="positive_surprise",
    )
    repository.upsert_earnings_surprise(
        conn,
        stock_code="000001.SZ",
        report_period="2023Q4",
        as_of_date="2024-01-11",
        expected_net_profit=10,
        actual_net_profit=12,
        surprise_type="positive_surprise",
    )
    assert conn.execute("SELECT COUNT(*) AS c FROM earnings_surprises").fetchone()["c"] == 1

    repository.upsert_order_contract_event(
        conn,
        stock_code="000001.SZ",
        publish_date="2024-01-08",
        event_type="major_contract",
        title="重大合同公告",
        source="test",
    )
    repository.upsert_business_kpi_actual(
        conn,
        stock_code="000001.SZ",
        report_period="2023Q4",
        publish_date="2024-01-09",
        as_of_date="2024-01-10",
        kpi_name="orders",
        kpi_value=100,
        kpi_unit="CNY",
        source="test",
    )
    repository.upsert_risk_event(
        conn,
        stock_code="000001.SZ",
        event_date="2024-01-06",
        publish_date="2024-01-06",
        as_of_date="2024-01-07",
        risk_type="regulatory_penalty",
        title="监管处罚",
        source="test",
    )
    assert conn.execute("SELECT COUNT(*) AS c FROM order_contract_events").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) AS c FROM business_kpi_actuals").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) AS c FROM risk_events").fetchone()["c"] == 1


def test_taxonomy_contains_phase_c_values(conn: sqlite3.Connection) -> None:
    assert "missed_business_kpi_signal" in ERROR_TYPES
    assert "missed_risk_event" in ERROR_TYPES
    assert "financial_actual_missing" in ERROR_TYPES
    assert "increase_earnings_surprise_weight" in SIGNAL_TYPES
    assert "increase_order_event_weight" in SIGNAL_TYPES
    with pytest.raises(ReviewTaxonomyError):
        repository.upsert_risk_event(
            conn,
            stock_code="000001.SZ",
            event_date="2024-01-06",
            publish_date="2024-01-06",
            as_of_date="2024-01-07",
            risk_type="made_up_risk",
            title="invalid",
            source="test",
        )
    with pytest.raises(ReviewTaxonomyError):
        repository.upsert_earnings_surprise(
            conn,
            stock_code="000001.SZ",
            report_period="2023Q4",
            as_of_date="2024-01-11",
            surprise_type="made_up_surprise",
        )
    with pytest.raises(ReviewTaxonomyError):
        repository.upsert_earnings_surprise(
            conn,
            stock_code="000001.SZ",
            report_period="2023Q4",
            as_of_date="2024-01-11",
            surprise_type="in_line",
            evidence_level="made_up_evidence_level",
        )


def test_before_queries_exclude_target_date_and_future(conn: sqlite3.Connection) -> None:
    repository.upsert_financial_actual(
        conn,
        stock_code="000001.SZ",
        report_period="2023Q3",
        publish_date="2024-01-04",
        as_of_date="2024-01-05",
        net_profit=8,
        source="test",
    )
    repository.upsert_financial_actual(
        conn,
        stock_code="000001.SZ",
        report_period="2023Q4",
        publish_date="2024-01-10",
        as_of_date="2024-01-10",
        net_profit=10,
        source="test",
    )
    repository.upsert_financial_actual(
        conn,
        stock_code="000001.SZ",
        report_period="2024Q1",
        publish_date="2024-01-12",
        as_of_date="2024-01-12",
        net_profit=12,
        source="test",
    )
    repository.upsert_analyst_expectation(
        conn,
        stock_code="000001.SZ",
        report_date="2024-01-09",
        forecast_period="2023Q4",
        source="test",
    )
    repository.upsert_analyst_expectation(
        conn,
        stock_code="000001.SZ",
        report_date="2024-01-10",
        forecast_period="2024Q1",
        source="test",
    )
    repository.upsert_earnings_surprise(
        conn,
        stock_code="000001.SZ",
        report_period="2023Q3",
        as_of_date="2024-01-05",
        surprise_type="in_line",
    )
    repository.upsert_earnings_surprise(
        conn,
        stock_code="000001.SZ",
        report_period="2023Q4",
        as_of_date="2024-01-10",
        surprise_type="positive_surprise",
    )
    repository.upsert_order_contract_event(
        conn,
        stock_code="000001.SZ",
        publish_date="2024-01-09",
        event_type="major_contract",
        title="before",
        source="test",
    )
    repository.upsert_order_contract_event(
        conn,
        stock_code="000001.SZ",
        publish_date="2024-01-10",
        event_type="major_contract",
        title="target",
        source="test",
    )
    repository.upsert_business_kpi_actual(
        conn,
        stock_code="000001.SZ",
        report_period="2023Q3",
        publish_date="2024-01-09",
        as_of_date="2024-01-09",
        kpi_name="orders",
        kpi_value=100,
        kpi_unit="CNY",
        source="test",
    )
    repository.upsert_business_kpi_actual(
        conn,
        stock_code="000001.SZ",
        report_period="2023Q4",
        publish_date="2024-01-10",
        as_of_date="2024-01-10",
        kpi_name="orders",
        kpi_value=200,
        kpi_unit="CNY",
        source="test",
    )
    repository.upsert_risk_event(
        conn,
        stock_code="000001.SZ",
        event_date="2024-01-09",
        publish_date="2024-01-09",
        as_of_date="2024-01-09",
        risk_type="litigation",
        title="before",
        source="test",
    )
    repository.upsert_risk_event(
        conn,
        stock_code="000001.SZ",
        event_date="2024-01-10",
        publish_date="2024-01-10",
        as_of_date="2024-01-10",
        risk_type="litigation",
        title="target",
        source="test",
    )

    target_date = "2024-01-10"
    assert repository.latest_financial_actuals_before(conn, "000001.SZ", target_date)["report_period"] == "2023Q3"
    assert [row["forecast_period"] for row in repository.latest_expectations_before(conn, "000001.SZ", target_date)] == ["2023Q4"]
    assert [row["report_period"] for row in repository.latest_earnings_surprises_before(conn, "000001.SZ", target_date)] == ["2023Q3"]
    assert [row["title"] for row in repository.recent_order_contract_events_before(conn, "000001.SZ", target_date)] == ["before"]
    assert [row["report_period"] for row in repository.recent_business_kpis_before(conn, "000001.SZ", target_date)] == ["2023Q3"]
    assert [row["title"] for row in repository.recent_risk_events_before(conn, "000001.SZ", target_date)] == ["before"]
