"""Tests for C3: AKShare analyst expectation data integration."""
import sqlite3

import pytest

from stock_select.data_ingestion import (
    AkShareProvider,
    AnalystExpectationItem,
    BaoStockProvider,
    UnsupportedDatasetError,
)
from stock_select.evidence_sync import sync_analyst_expectations
from stock_select.repository import upsert_analyst_expectation


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("""
        CREATE TABLE analyst_expectations (
            expectation_id TEXT PRIMARY KEY,
            stock_code TEXT NOT NULL,
            report_date TEXT NOT NULL,
            forecast_period TEXT NOT NULL,
            org_name TEXT,
            author_name TEXT,
            report_title TEXT,
            forecast_revenue REAL,
            forecast_net_profit REAL,
            forecast_eps REAL,
            forecast_pe REAL,
            rating TEXT,
            target_price_min REAL,
            target_price_max REAL,
            source TEXT NOT NULL,
            source_url TEXT,
            source_fetched_at TEXT,
            confidence REAL DEFAULT 1.0,
            raw_json TEXT,
            UNIQUE(stock_code, report_date, forecast_period, org_name, author_name)
        )
    """)
    c.execute("""
        CREATE TABLE data_sources (
            source TEXT, dataset TEXT, trading_date TEXT,
            status TEXT, rows_loaded INTEGER,
            PRIMARY KEY(source, dataset, trading_date)
        )
    """)
    return c


class TestAnalystExpectationUpsert:
    def test_upsert_new_expectation(self, conn):
        eid = upsert_analyst_expectation(
            conn,
            stock_code="000001",
            report_date="2026-04-26",
            forecast_period="2026-12-31",
            source="akshare",
            org_name="国泰君安",
            forecast_eps=2.08,
            forecast_pe=5.20,
            rating="买入",
        )
        assert eid.startswith("exp_")
        row = conn.execute(
            "SELECT * FROM analyst_expectations WHERE expectation_id = ?", (eid,)
        ).fetchone()
        assert row is not None
        assert row["stock_code"] == "000001"
        assert row["forecast_eps"] == 2.08
        assert row["forecast_pe"] == 5.20
        assert row["rating"] == "买入"

    def test_upsert_dedup_by_unique_key(self, conn):
        """Same stock/report/period/org should not create duplicates."""
        upsert_analyst_expectation(
            conn,
            stock_code="000001",
            report_date="2026-04-26",
            forecast_period="2026-12-31",
            source="akshare",
            org_name="国泰君安",
            forecast_eps=1.0,
        )
        upsert_analyst_expectation(
            conn,
            stock_code="000001",
            report_date="2026-04-26",
            forecast_period="2026-12-31",
            source="akshare",
            org_name="国泰君安",
            forecast_eps=2.0,
        )
        count = conn.execute(
            "SELECT COUNT(*) FROM analyst_expectations WHERE stock_code = '000001'"
        ).fetchone()[0]
        assert count == 1

    def test_upsert_with_full_fields(self, conn):
        eid = upsert_analyst_expectation(
            conn,
            stock_code="000002",
            report_date="2026-01-15",
            forecast_period="2027-12-31",
            source="akshare",
            org_name="中信证券",
            author_name="张三",
            report_title="2026年一季报点评",
            forecast_revenue=5000000.0,
            forecast_net_profit=800000.0,
            forecast_eps=1.5,
            forecast_pe=12.5,
            rating="增持",
            target_price_min=10.0,
            target_price_max=12.0,
            source_url="https://example.com/report.pdf",
            confidence=0.9,
        )
        row = conn.execute(
            "SELECT * FROM analyst_expectations WHERE expectation_id = ?", (eid,)
        ).fetchone()
        assert row["forecast_revenue"] == 5000000.0
        assert row["forecast_net_profit"] == 800000.0
        assert row["target_price_min"] == 10.0
        assert row["target_price_max"] == 12.0
        assert row["source_url"] == "https://example.com/report.pdf"


class TestAkShareAnalystExpectations:
    def test_provider_has_method(self):
        provider = AkShareProvider()
        assert hasattr(provider, "fetch_analyst_expectations")
        assert callable(provider.fetch_analyst_expectations)

    def test_baostock_raises_unsupported(self):
        provider = BaoStockProvider()
        with pytest.raises(UnsupportedDatasetError):
            provider.fetch_analyst_expectations("2026-04-26", ["000001"])


class TestAnalystExpectationItem:
    def test_item_is_frozen(self):
        item = AnalystExpectationItem(
            source="akshare",
            stock_code="000001",
            report_date="2026-04-26",
            forecast_period="2026-12-31",
        )
        with pytest.raises(Exception):
            item.source = "baostock"

    def test_item_defaults(self):
        item = AnalystExpectationItem(
            source="akshare",
            stock_code="000001",
            report_date="2026-04-26",
            forecast_period="2026-12-31",
        )
        assert item.forecast_revenue is None
        assert item.forecast_net_profit is None
        assert item.forecast_eps is None
        assert item.forecast_pe is None
        assert item.rating is None
        assert item.confidence == 1.0
