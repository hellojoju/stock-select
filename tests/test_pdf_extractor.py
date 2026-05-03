"""Tests for PDF extraction and announcement event parsing."""
import sqlite3
import textwrap

import pytest

from stock_select.pdf_extractor import (
    classify_announcement_text,
    download_pdf,
    extract_text_from_pdf,
    process_pending_announcements,
)
from stock_select.announcement_events import (
    BusinessKPIEvent,
    OrderContractEvent,
    RiskEvent,
    extract_business_kpi_events,
    extract_order_contract_events,
    extract_risk_events,
    process_announcement_text,
    upsert_business_kpi_event,
    upsert_order_contract_event,
    upsert_risk_event,
)


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("""
        CREATE TABLE raw_documents (
            document_id TEXT PRIMARY KEY,
            source_url TEXT,
            title TEXT,
            source_type TEXT,
            content_text TEXT,
            published_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE raw_document_stocks (
            document_id TEXT,
            stock_code TEXT
        )
    """)
    c.execute("""
        CREATE TABLE order_contract_events (
            event_id TEXT PRIMARY KEY,
            stock_code TEXT,
            event_date TEXT,
            event_type TEXT,
            amount REAL,
            currency TEXT,
            description TEXT,
            source_document_id TEXT,
            confidence REAL
        )
    """)
    c.execute("""
        CREATE TABLE business_kpi_actuals (
            kpi_id TEXT PRIMARY KEY,
            stock_code TEXT,
            period TEXT,
            kpi_name TEXT,
            kpi_value REAL,
            yoy_change REAL,
            description TEXT,
            source_document_id TEXT,
            confidence REAL
        )
    """)
    c.execute("""
        CREATE TABLE risk_events (
            event_id TEXT PRIMARY KEY,
            stock_code TEXT,
            event_date TEXT,
            risk_type TEXT,
            severity TEXT,
            description TEXT,
            source_document_id TEXT,
            confidence REAL
        )
    """)
    return c


# ──────────────────────────────────────────────
# PDF extractor tests
# ──────────────────────────────────────────────

class TestClassifyAnnouncementText:
    def test_classifies_contract(self):
        text = "公司签订重大合同，总金额5000万元"
        results = classify_announcement_text(text)
        types = [r["event_type"] for r in results]
        assert "重大合同" in types

    def test_classifies_performance(self):
        text = "公司业绩预告显示净利润同比增长30%"
        results = classify_announcement_text(text)
        types = [r["event_type"] for r in results]
        assert "业绩预告" in types

    def test_classifies_risk(self):
        text = "公司收到监管问询函，涉嫌违规操作"
        results = classify_announcement_text(text)
        types = [r["event_type"] for r in results]
        assert "监管问询" in types
        assert "风险事件" in types

    def test_returns_empty_for_no_match(self):
        results = classify_announcement_text("今天天气不错")
        assert results == []

    def test_sorts_by_confidence(self):
        text = "公司签订重大合同，业绩同比增长，收到监管问询"
        results = classify_announcement_text(text)
        assert len(results) >= 2
        for i in range(len(results) - 1):
            assert results[i]["confidence"] >= results[i + 1]["confidence"]


class TestDownloadPdf:
    def test_returns_none_for_empty_url(self):
        assert download_pdf("") is None
        assert download_pdf(None) is None  # type: ignore


class TestExtractTextFromPdf:
    def test_returns_none_for_invalid_bytes(self):
        result = extract_text_from_pdf(b"not a real pdf")
        assert result is None


# ──────────────────────────────────────────────
# Announcement events tests
# ──────────────────────────────────────────────

class TestExtractOrderContractEvents:
    def test_detects_contract(self):
        text = "公司于2024年1月15日签订重大合同，合同金额为5000万元。"
        events = extract_order_contract_events(text, "doc1", "2024-01-15")
        assert len(events) >= 1
        assert events[0].event_type == "contract_signed"

    def test_detects_bid_won(self):
        text = "公司中标某市政工程项目"
        events = extract_order_contract_events(text, "doc1", "2024-01-15")
        types = [e.event_type for e in events]
        assert "bid_won" in types

    def test_detects_order(self):
        text = "公司收到大批量订单通知"
        events = extract_order_contract_events(text, "doc1", "2024-01-15")
        types = [e.event_type for e in events]
        assert "order_received" in types

    def test_extracts_amount(self):
        text = "签订协议，总金额3000万元"
        events = extract_order_contract_events(text, "doc1", "2024-01-15")
        assert len(events) >= 1
        assert events[0].amount is not None
        assert events[0].amount > 0

    def test_uses_known_stock_codes(self):
        text = "签订重大合同"
        events = extract_order_contract_events(text, "doc1", "2024-01-15", known_stock_codes=["000001"])
        assert events[0].stock_code == "000001"


class TestExtractBusinessKpiEvents:
    def test_detects_revenue(self):
        text = "公司营业收入同比增长15%"
        events = extract_business_kpi_events(text, "doc1", "2024-01-15")
        types = [e.kpi_name for e in events]
        assert "revenue" in types

    def test_detects_net_profit(self):
        text = "净利润达到500万元，同比增长20%"
        events = extract_business_kpi_events(text, "doc1", "2024-01-15")
        types = [e.kpi_name for e in events]
        assert "net_profit" in types

    def test_detects_eps(self):
        text = "每股收益0.5元"
        events = extract_business_kpi_events(text, "doc1", "2024-01-15")
        types = [e.kpi_name for e in events]
        assert "eps" in types

    def test_extracts_yoy(self):
        text = "营业收入同比增长12.5%"
        events = extract_business_kpi_events(text, "doc1", "2024-01-15")
        kpi = events[0]
        assert kpi.yoy_change is not None


class TestExtractRiskEvents:
    def test_detects_litigation(self):
        text = "公司涉及一起重大诉讼案件"
        events = extract_risk_events(text, "doc1", "2024-01-15")
        types = [e.risk_type for e in events]
        assert "litigation" in types

    def test_detects_penalty(self):
        text = "公司收到证监会处罚通知"
        events = extract_risk_events(text, "doc1", "2024-01-15")
        types = [e.risk_type for e in events]
        assert "penalty" in types

    def test_high_severity_for_delisting(self):
        text = "公司存在退市风险警示"
        events = extract_risk_events(text, "doc1", "2024-01-15")
        assert events[0].severity == "high"

    def test_medium_severity_for_warning(self):
        text = "公司收到监管警示函"
        events = extract_risk_events(text, "doc1", "2024-01-15")
        assert events[0].severity == "medium"


class TestUpsertEvents:
    def test_upsert_order_contract(self, conn):
        event = OrderContractEvent(
            event_id="oc_test",
            stock_code="000001",
            event_date="2024-01-15",
            event_type="contract_signed",
            amount=5000.0,
            currency="万元",
            description="test contract",
            source_document_id="doc1",
            confidence=0.8,
        )
        upsert_order_contract_event(conn, event)
        row = conn.execute("SELECT * FROM order_contract_events WHERE event_id = ?", ("oc_test",)).fetchone()
        assert row is not None
        assert row["stock_code"] == "000001"
        assert row["amount"] == 5000.0

    def test_upsert_business_kpi(self, conn):
        event = BusinessKPIEvent(
            event_id="kpi_test",
            stock_code="000001",
            period="2024-01-15",
            kpi_name="revenue",
            kpi_value=1000.0,
            yoy_change=10.0,
            description="test kpi",
            source_document_id="doc1",
            confidence=0.75,
        )
        upsert_business_kpi_event(conn, event)
        row = conn.execute("SELECT * FROM business_kpi_actuals WHERE kpi_id = ?", ("kpi_test",)).fetchone()
        assert row is not None
        assert row["kpi_name"] == "revenue"

    def test_upsert_risk(self, conn):
        event = RiskEvent(
            event_id="risk_test",
            stock_code="000001",
            event_date="2024-01-15",
            risk_type="litigation",
            severity="high",
            description="test risk",
            source_document_id="doc1",
            confidence=0.8,
        )
        upsert_risk_event(conn, event)
        row = conn.execute("SELECT * FROM risk_events WHERE event_id = ?", ("risk_test",)).fetchone()
        assert row is not None
        assert row["risk_type"] == "litigation"

    def test_dedup_on_conflict(self, conn):
        event = OrderContractEvent(
            event_id="oc_dedup",
            stock_code="000001",
            event_date="2024-01-15",
            event_type="contract_signed",
            amount=100.0,
            currency="万元",
            description="first",
            source_document_id="doc1",
            confidence=0.8,
        )
        upsert_order_contract_event(conn, event)
        event2 = OrderContractEvent(
            event_id="oc_dedup",
            stock_code="000002",
            event_date="2024-01-16",
            event_type="bid_won",
            amount=200.0,
            currency="万元",
            description="second",
            source_document_id="doc2",
            confidence=0.9,
        )
        upsert_order_contract_event(conn, event2)
        count = conn.execute("SELECT COUNT(*) FROM order_contract_events WHERE event_id = ?", ("oc_dedup",)).fetchone()[0]
        assert count == 1


class TestProcessAnnouncementText:
    def test_extracts_all_event_types(self, conn):
        text = textwrap.dedent("""\
            公司于2024年1月15日签订重大合同，合同金额5000万元。
            营业收入同比增长15%，净利润达到800万元。
            同时公司涉及一起诉讼案件，收到监管警示。
        """)
        counts = process_announcement_text(conn, "doc1", text, "2024-01-15", ["000001"])
        assert counts["order_contract_events"] >= 1
        assert counts["business_kpi_events"] >= 1
        assert counts["risk_events"] >= 1
        assert counts["total"] >= 3

    def test_returns_zero_for_no_match(self, conn):
        text = "今天天气真不错，适合出游"
        counts = process_announcement_text(conn, "doc2", text, "2024-01-15")
        assert counts["total"] == 0
