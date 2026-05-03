from __future__ import annotations

import pytest

from stock_select.db import connect, init_db
from stock_select.api import create_app


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    init_db(conn)
    yield conn
    conn.close()


@pytest.fixture
def client(db, tmp_path):
    app = create_app(db_path=str(tmp_path / "test.db"), mode="demo")
    from fastapi.testclient import TestClient
    return TestClient(app)


def _seed_market_data(conn):
    conn.execute(
        "INSERT OR IGNORE INTO trading_days (trading_date, is_open) VALUES (?, ?)",
        ("2024-01-15", 1),
    )
    conn.execute(
        "INSERT OR IGNORE INTO stocks (stock_code, name, industry, listing_status) VALUES (?, ?, ?, ?)",
        ("000001.SZ", "平安银行", "银行", "active"),
    )
    conn.execute(
        "INSERT INTO daily_prices (stock_code, trading_date, open, high, low, close, volume, amount, is_limit_up, is_limit_down) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("000001.SZ", "2024-01-15", 10.0, 11.0, 9.5, 10.5, 100000, 1000000, 0, 0),
    )
    conn.execute(
        "INSERT INTO index_prices (index_code, trading_date, open, high, low, close, volume, amount) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("sh.000001", "2024-01-15", 3000.0, 3050.0, 2990.0, 3030.0, 1000000, 5000000.0),
    )
    conn.execute(
        "INSERT INTO index_prices (index_code, trading_date, open, high, low, close, volume, amount) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("sz.399001", "2024-01-15", 10000.0, 10100.0, 9950.0, 10050.0, 2000000, 8000000.0),
    )
    conn.execute(
        "INSERT INTO index_prices (index_code, trading_date, open, high, low, close, volume, amount) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("sz.399006", "2024-01-15", 2000.0, 2050.0, 1980.0, 2020.0, 500000, 3000000.0),
    )
    conn.execute(
        "INSERT INTO index_prices (index_code, trading_date, open, high, low, close, volume, amount) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("bj.899050", "2024-01-15", 1000.0, 1020.0, 990.0, 1010.0, 100000, 500000.0),
    )
    conn.commit()


def _seed_stock_and_decision(conn):
    conn.execute(
        "INSERT OR IGNORE INTO stocks (stock_code, name, industry, listing_status) VALUES (?, ?, ?, ?)",
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
    conn.commit()


class TestMarketOverviewEndpoint:
    def test_returns_market_overview(self, client, db):
        _seed_market_data(db)
        response = client.get("/api/reviews/market-overview?date=2024-01-15")
        assert response.status_code == 200
        data = response.json()
        assert data["trading_date"] == "2024-01-15"
        assert "sh_return" in data
        assert "advance_count" in data

    def test_generates_on_missing(self, client, db):
        response = client.get("/api/reviews/market-overview?date=2024-01-15")
        assert response.status_code == 200
        data = response.json()
        assert data["trading_date"] == "2024-01-15"


class TestSentimentCycleEndpoint:
    def test_returns_sentiment_cycle(self, client, db):
        _seed_market_data(db)
        response = client.get("/api/reviews/sentiment-cycle?date=2024-01-15")
        assert response.status_code == 200
        data = response.json()
        assert data["trading_date"] == "2024-01-15"
        assert "cycle_phase" in data
        assert "composite_sentiment" in data


class TestSectorsEndpoint:
    def test_returns_sectors(self, client, db):
        _seed_market_data(db)
        response = client.get("/api/reviews/sectors?date=2024-01-15")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


class TestCustomSectorsEndpoint:
    def test_returns_all_custom_sectors(self, client, db):
        _seed_market_data(db)
        response = client.get("/api/reviews/custom-sectors?date=2024-01-15")
        assert response.status_code == 200
        data = response.json()
        assert "sectors" in data

    def test_returns_specific_sector(self, client, db):
        _seed_market_data(db)
        response = client.get("/api/reviews/custom-sectors?date=2024-01-15&sector_key=limit_up_today")
        assert response.status_code == 200
        data = response.json()
        assert data["sector_key"] == "limit_up_today"
        assert "stocks" in data


class TestStockReviewEnhanced:
    def test_stock_review_has_market_context(self, client, db):
        _seed_market_data(db)
        _seed_stock_and_decision(db)
        response = client.get("/api/reviews/stocks/000001.SZ?date=2024-01-15")
        assert response.status_code == 200
        data = response.json()
        assert "market_overview" in data
        assert "sentiment_cycle" in data

    def test_stock_review_has_deep_review(self, client, db):
        _seed_market_data(db)
        _seed_stock_and_decision(db)
        response = client.get("/api/reviews/stocks/000001.SZ?date=2024-01-15")
        assert response.status_code == 200
        data = response.json()
        assert "custom_sector_tags" in data
        assert "stock_quant" in data
        assert "psychology_review" in data
        assert "next_day_plan" in data


class TestHealthEndpoint:
    def test_returns_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestDashboardEndpoint:
    def test_returns_picks_and_performance(self, client, db):
        _seed_market_data(db)
        _seed_stock_and_decision(db)
        response = client.get("/api/dashboard?date=2024-01-15")
        assert response.status_code == 200
        data = response.json()
        assert data["date"] == "2024-01-15"
        assert len(data["picks"]) > 0
        assert "performance" in data


class TestAvailabilityEndpoint:
    def test_returns_availability_status(self, client, db):
        _seed_market_data(db)
        response = client.get("/api/availability?date=2024-01-15")
        assert response.status_code == 200
        data = response.json()
        assert data["date"] == "2024-01-15"
        assert data["status"] in ("ok", "degraded", "failed")
        assert "price_coverage_pct" in data


class TestEvolutionEventsEndpoint:
    def test_returns_events_list(self, client, db):
        from stock_select.strategies import seed_default_genes
        seed_default_genes(db)
        response = client.get("/api/evolution/events")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


class TestDataSyncCreatesRunRecord:
    def test_research_run_recorded(self, db):
        from stock_select.agent_runtime import research_run
        with research_run(db, "sync_data", "2024-01-15") as run:
            run.finish({"rows": 5})
        runs = db.execute(
            "SELECT * FROM research_runs WHERE trading_date = ? AND phase = 'sync_data'",
            ("2024-01-15",),
        ).fetchall()
        assert len(runs) > 0
