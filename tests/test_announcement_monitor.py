"""Tests for announcement_monitor module."""
import pytest
import sqlite3
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from stock_select.announcement_monitor import (
    _classify_alert_type,
    AnnouncementAlert,
    run_announcement_scan,
)


@pytest.fixture
def conn():
    from stock_select.db import connect, init_db
    c = connect(":memory:")
    init_db(c)
    yield c
    c.close()


# ──────────────────────────────────────────────
# _classify_alert_type tests
# ──────────────────────────────────────────────

class TestClassifyAlertType:
    """Test the alert type classifier."""

    # Positive cases — should match
    def test_earnings_beat(self):
        assert _classify_alert_type("2024年净利润同比增长150%")[0] == "earnings_beat"

    def test_earnings_beat_revenue(self):
        assert _classify_alert_type("营收大幅增长，业绩超预期")[0] == "earnings_beat"

    def test_earnings_beat_turnaround(self):
        assert _classify_alert_type("公司成功扭亏为盈")[0] == "earnings_beat"

    def test_large_order_winning_bid(self):
        assert _classify_alert_type("中标15亿重大项目合同")[0] == "large_order"

    def test_large_order_contract(self):
        assert _classify_alert_type("签订战略合作协议，订单金额超10亿")[0] == "large_order"

    def test_tech_breakthrough(self):
        assert _classify_alert_type("核心技术取得重大突破，填补国内空白")[0] == "tech_breakthrough"

    def test_tech_breakthrough_certification(self):
        assert _classify_alert_type("新产品通过国际认证，即将量产")[0] == "tech_breakthrough"

    def test_asset_injection(self):
        assert _classify_alert_type("拟非公开发行股份募集资金30亿")[0] == "asset_injection"

    def test_asset_injection_buyback(self):
        assert _classify_alert_type("回购股份并注销，实施股权激励计划")[0] == "asset_injection"

    def test_m_and_a(self):
        assert _classify_alert_type("重大资产重组预案披露")[0] == "m_and_a"

    def test_m_and_a_control_change(self):
        assert _classify_alert_type("实际控制人发生变更")[0] == "m_and_a"

    # Negative cases — should be filtered out
    def test_noise_shareholder_meeting(self):
        assert _classify_alert_type("关于召开2024年第一次股东大会的通知")[0] is None

    def test_noise_risk_warning(self):
        assert _classify_alert_type("股票交易风险提示公告")[0] is None

    def test_noise_st_delisting(self):
        assert _classify_alert_type("*ST某某退市风险警示")[0] is None

    def test_noise_investigation(self):
        assert _classify_alert_type("公司涉嫌违规被立案调查")[0] is None

    def test_noise_routine_report(self):
        assert _classify_alert_type("2024年第三季度报告")[0] is None

    def test_noise_correction(self):
        assert _classify_alert_type("关于年报的更正公告")[0] is None

    def test_noise_pledge(self):
        assert _classify_alert_type("股东质押部分股份")[0] is None

    # Edge cases
    def test_empty_title(self):
        assert _classify_alert_type("")[0] is None

    def test_mixed_positive_and_noise(self):
        """Noise patterns should take priority — risk alerts get filtered."""
        # If it has both risk and positive keywords, noise wins (safer)
        result = _classify_alert_type("净利润增长但存在诉讼风险")
        # "诉讼" is in noise, so type should be None
        assert result[0] is None


# ──────────────────────────────────────────────
# run_announcement_scan tests
# ──────────────────────────────────────────────

class TestRunAnnouncementScan:
    """Test the polling engine (integration with in-memory DB)."""

    def test_creates_alerts_table(self, conn):
        """Verify announcement_alerts table exists after init."""
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='announcement_alerts'"
        ).fetchone()
        assert row is not None

    def test_creates_monitor_runs_table(self, conn):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='monitor_runs'"
        ).fetchone()
        assert row is not None

    def test_creates_sector_heat_index_table(self, conn):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sector_heat_index'"
        ).fetchone()
        assert row is not None

    def test_returns_list(self, conn):
        """Should return a list even with no data."""
        result = run_announcement_scan(conn)
        assert isinstance(result, list)

    def test_inserts_alert_on_duplicate(self, conn):
        """Test dedup logic by checking the UNIQUE constraint works."""
        # Manually insert a test alert
        conn.execute(
            """INSERT INTO announcement_alerts
               (alert_id, trading_date, discovered_at, stock_code, source,
                alert_type, title, sentiment_score, confidence)
               VALUES ('test1', '2026-01-01', '2026-01-01', '000001',
                       'cninfo', 'earnings_beat', 'test title', 0.5, 0.5)"""
        )
        conn.commit()

        # Same unique key should be ignored
        conn.execute(
            """INSERT OR IGNORE INTO announcement_alerts
               (alert_id, trading_date, discovered_at, stock_code, source,
                alert_type, title, sentiment_score, confidence)
               VALUES ('test2', '2026-01-01', '2026-01-01', '000001',
                       'cninfo', 'earnings_beat', 'test title', 0.5, 0.5)"""
        )
        conn.commit()

        count = conn.execute(
            "SELECT COUNT(*) FROM announcement_alerts WHERE stock_code='000001' AND title='test title'"
        ).fetchone()[0]
        assert count == 1


# ──────────────────────────────────────────────
# AnnouncementAlert dataclass tests
# ──────────────────────────────────────────────

class TestAnnouncementAlert:
    """Test the dataclass."""

    def test_create(self):
        alert = AnnouncementAlert(
            alert_id="test123",
            trading_date="2026-01-01",
            discovered_at="2026-01-01T10:00:00Z",
            stock_code="000001",
            stock_name="平安银行",
            industry="银行",
            source="cninfo",
            alert_type="earnings_beat",
            title="净利润增长50%",
            summary=None,
            source_url="https://example.com",
            event_ids_json=None,
            sentiment_score=0.0,
            capital_flow_score=None,
            sector_heat_score=None,
            chip_structure_score=None,
            shareholder_trend_score=None,
            confidence=0.5,
        )
        assert alert.alert_id == "test123"
        assert alert.status == "new"

    def test_frozen_fields(self):
        """Alert should be mutable dataclass (not frozen) for flexibility."""
        alert = AnnouncementAlert(
            alert_id="x", trading_date="d", discovered_at="d",
            stock_code="001", stock_name=None, industry=None,
            source="s", alert_type="t", title="t", summary=None,
            source_url="", event_ids_json=None, sentiment_score=0,
            capital_flow_score=None, sector_heat_score=None,
            chip_structure_score=None, shareholder_trend_score=None,
            confidence=0.5,
        )
        alert.sentiment_score = 0.8
        assert alert.sentiment_score == 0.8
