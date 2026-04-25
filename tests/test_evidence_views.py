from __future__ import annotations

import sqlite3

import pytest

from stock_select import repository
from stock_select.api import create_app
from stock_select.db import init_db
from stock_select.evidence_views import evidence_status, stock_evidence
from stock_select.seed import seed_default_genes


@pytest.fixture()
def conn() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    init_db(db)
    seed_default_genes(db)
    repository.upsert_stock(db, "000001.SZ", "Evidence Stock", industry="Bank")
    repository.upsert_financial_actual(
        db,
        stock_code="000001.SZ",
        report_period="2023Q4",
        publish_date="2024-01-08",
        as_of_date="2024-01-09",
        revenue=100,
        net_profit=10,
        source="test",
    )
    repository.upsert_analyst_expectation(
        db,
        stock_code="000001.SZ",
        report_date="2024-01-05",
        forecast_period="2023Q4",
        forecast_net_profit=8,
        source="test",
    )
    repository.upsert_risk_event(
        db,
        stock_code="000001.SZ",
        event_date="2024-01-08",
        publish_date="2024-01-08",
        as_of_date="2024-01-09",
        risk_type="litigation",
        title="诉讼公告",
        source="test",
        impact_score=-0.4,
    )
    db.commit()
    return db


def test_stock_evidence_returns_datasets_and_missing_dimensions(conn: sqlite3.Connection) -> None:
    payload = stock_evidence(conn, "000001.SZ", "2024-01-10")

    assert payload["stock_code"] == "000001.SZ"
    assert len(payload["datasets"]["financial_actuals"]) == 1
    assert len(payload["datasets"]["analyst_expectations"]) == 1
    assert len(payload["datasets"]["risk_events"]) == 1
    assert payload["coverage"]["financial_actuals"] is True
    assert "business_kpi_actuals" in payload["missing_dimensions"]


def test_evidence_status_counts_and_message(conn: sqlite3.Connection) -> None:
    payload = evidence_status(conn, "2024-01-10")

    assert payload["active_stock_count"] == 1
    assert payload["counts"]["financial_actuals"] == 1
    assert payload["counts"]["analyst_expectations"] == 1
    assert payload["counts"]["risk_events"] == 1
    assert "message" in payload


def test_fastapi_evidence_routes_expose_stable_schema(tmp_path) -> None:
    fastapi = pytest.importorskip("fastapi")
    testclient = pytest.importorskip("fastapi.testclient")
    db_path = tmp_path / "api.db"
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    init_db(db)
    seed_default_genes(db)
    repository.upsert_stock(db, "000001.SZ", "Evidence Stock", industry="Bank")
    repository.upsert_financial_actual(
        db,
        stock_code="000001.SZ",
        report_period="2023Q4",
        publish_date="2024-01-08",
        as_of_date="2024-01-09",
        net_profit=10,
        source="test",
    )
    db.commit()
    db.close()

    app = create_app(db_path=db_path, mode="demo")
    client = testclient.TestClient(app)
    status = client.get("/api/evidence/status", params={"date": "2024-01-10"})
    assert status.status_code == 200
    assert status.json()["counts"]["financial_actuals"] == 1

    stock = client.get("/api/evidence/stocks/000001.SZ", params={"date": "2024-01-10"})
    assert stock.status_code == 200
    assert stock.json()["coverage"]["financial_actuals"] is True

    dashboard = client.get("/api/dashboard", params={"date": "2024-01-10"})
    assert dashboard.status_code == 200
    assert "evidence_status" in dashboard.json()
