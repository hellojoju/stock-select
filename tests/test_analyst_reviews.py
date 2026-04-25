"""Tests for the analyst review system."""
from __future__ import annotations

import json
import sqlite3

import pytest

from stock_select import repository
from stock_select.analyst_types import AnalystVerdict
from stock_select.analysts.contrarian import contrarian_analyst
from stock_select.analysts.fundamental_check import fundamental_check_analyst
from stock_select.analysts.risk_scanner import risk_scanner_analyst
from stock_select.analysts.trend_follower import trend_follower_analyst
from stock_select.db import init_db
from stock_select.review_analysts import (
    REVIEW_ANALYSTS,
    _emit_signals_from_verdict,
    get_analyst_reviews_for_date,
    load_analyst_evidence,
    load_decision_row,
    persist_analyst_verdict,
    run_analyst_reviews,
)
from stock_select.seed import seed_default_genes


# ── Helpers ──────────────────────────────────────────────────────────

DECISION_KEYS = [
    "decision_id", "trading_date", "horizon", "strategy_gene_id", "stock_code",
    "action", "confidence", "position_pct", "score", "entry_plan_json",
    "sell_rules_json", "thesis_json", "risks_json", "invalid_if_json",
]


def make_decision(overrides: dict | None = None) -> dict:
    base = {
        "decision_id": "pick_test",
        "trading_date": "2024-01-10",
        "horizon": "short",
        "strategy_gene_id": "gene_aggressive_v1",
        "stock_code": "000001.SZ",
        "action": "BUY",
        "confidence": 0.8,
        "position_pct": 0.1,
        "score": 0.5,
        "entry_plan_json": "{}",
        "sell_rules_json": json.dumps({"stop_loss": -0.03}),
        "thesis_json": json.dumps({"reason": "volume breakout"}),
        "risks_json": json.dumps(["market risk"]),
        "invalid_if_json": "{}",
    }
    if overrides:
        base.update(overrides)
    return base


def pick_cols() -> str:
    return ", ".join(DECISION_KEYS)


def pick_placeholders() -> str:
    return ", ".join("?" for _ in DECISION_KEYS)


@pytest.fixture()
def conn() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    init_db(db)
    seed_default_genes(db)
    repository.upsert_stock(db, "000001.SZ", "Test Stock", industry="Bank")
    repository.upsert_stock(db, "000002.SZ", "Risk Stock", industry="Tech")
    repository.upsert_trading_day(db, "2024-01-10", True, index_return_pct=0.01)
    for code, close in [("000001.SZ", 11.0), ("000002.SZ", 9.5)]:
        repository.upsert_daily_price(
            db,
            stock_code=code,
            trading_date="2024-01-10",
            open=10, high=max(10, close), low=min(10, close),
            close=close, volume=1_000_000, amount=10_000_000,
            source="test",
        )
    db.commit()
    return db


def insert_pick_and_outcome(
    conn: sqlite3.Connection,
    *,
    decision_id: str = "pick_test",
    stock_code: str = "000001.SZ",
    return_pct: float = 0.05,
    max_drawdown: float = -0.02,
    technical_score: float = 0.3,
    fundamental_score: float = 0.3,
    event_score: float = 0.0,
    sector_score: float = 0.0,
    risk_penalty: float = 0.0,
    total_score: float = 0.5,
    is_st: int = 0,
    is_suspended: int = 0,
    is_limit_up: int = 0,
    hit_sell_rule: str | None = None,
    insert_candidate: bool = True,
) -> dict:
    """Insert a pick + outcome + candidate score row and return the full row dict."""
    pick = make_decision({
        "decision_id": decision_id,
        "stock_code": stock_code,
    })
    conn.execute(
        f"INSERT INTO pick_decisions({pick_cols()}) VALUES ({pick_placeholders()})",
        [pick[k] for k in DECISION_KEYS],
    )
    conn.execute(
        """INSERT INTO outcomes(outcome_id, decision_id, entry_price, exit_price, close_price,
                               return_pct, max_drawdown_intraday_pct, hit_sell_rule)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (f"out_{decision_id}", decision_id, 10.0, 10.0, 10.0,
         return_pct, max_drawdown, hit_sell_rule),
    )
    if insert_candidate:
        cid = f"cs_{decision_id}"
        conn.execute(
            """INSERT INTO candidate_scores(candidate_id, trading_date, strategy_gene_id, stock_code,
               total_score, technical_score, fundamental_score, event_score, sector_score, risk_penalty, packet_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (cid, "2024-01-10", "gene_aggressive_v1", stock_code,
             total_score, technical_score, fundamental_score,
             event_score, sector_score, risk_penalty, "{}"),
        )

    # Persist risk/suspension flags that analysts check
    if is_st:
        conn.execute("UPDATE stocks SET is_st = 1 WHERE stock_code = ?", (stock_code,))
    if is_suspended or is_limit_up:
        conn.execute(
            """UPDATE daily_prices SET is_suspended = ?, is_limit_up = ?
               WHERE stock_code = ? AND trading_date = ?""",
            (is_suspended, is_limit_up, stock_code, pick["trading_date"]),
        )

    conn.commit()

    row = load_decision_row(conn, decision_id)
    assert row is not None
    return dict(row)


# ── Analyst unit tests ───────────────────────────────────────────────


class TestTrendFollowerAnalyst:
    def test_agree_when_tech_and_return_positive(self, conn: sqlite3.Connection) -> None:
        row = insert_pick_and_outcome(conn, technical_score=0.5, return_pct=0.03)
        result = trend_follower_analyst(conn, "pick_test", row, {})
        assert result.verdict == "AGREE"
        assert result.confidence >= 0.65

    def test_disagree_when_tech_positive_but_return_negative(self, conn: sqlite3.Connection) -> None:
        row = insert_pick_and_outcome(conn, technical_score=0.5, return_pct=-0.02)
        result = trend_follower_analyst(conn, "pick_test", row, {})
        assert result.verdict == "DISAGREE"
        assert "overweighted_technical" in result.suggested_errors

    def test_suspended_flagged(self, conn: sqlite3.Connection) -> None:
        row = insert_pick_and_outcome(conn, technical_score=0.3, return_pct=0.01, is_suspended=1)
        result = trend_follower_analyst(conn, "pick_test", row, {})
        assert "entry_unfillable" in result.suggested_errors

    def test_limit_up_flagged(self, conn: sqlite3.Connection) -> None:
        row = insert_pick_and_outcome(conn, technical_score=0.3, return_pct=0.01, is_limit_up=1)
        result = trend_follower_analyst(conn, "pick_test", row, {})
        assert "entry_unfillable" in result.suggested_errors

    def test_neutral_when_low_tech_but_positive_return(self, conn: sqlite3.Connection) -> None:
        row = insert_pick_and_outcome(conn, technical_score=0.0, return_pct=0.02)
        result = trend_follower_analyst(conn, "pick_test", row, {})
        assert result.verdict == "NEUTRAL"

    def test_volume_surge_detected(self, conn: sqlite3.Connection) -> None:
        row = insert_pick_and_outcome(conn, technical_score=0.3, return_pct=0.01)
        evidence = {
            "recent_prices": [
                {"volume": 2_000_000, "close": 11.0},
                {"volume": 1_000_000, "close": 10.5},
                {"volume": 900_000, "close": 10.3},
                {"volume": 1_100_000, "close": 10.2},
                {"volume": 950_000, "close": 10.1},
            ],
        }
        result = trend_follower_analyst(conn, "pick_test", row, evidence)
        has_volume_reasoning = any("放量" in r for r in result.reasoning)
        assert has_volume_reasoning


class TestFundamentalCheckAnalyst:
    def test_agree_when_fundamental_and_return_positive(self, conn: sqlite3.Connection) -> None:
        row = insert_pick_and_outcome(conn, fundamental_score=0.5, return_pct=0.03)
        result = fundamental_check_analyst(conn, "pick_test", row, {})
        assert result.verdict == "AGREE"

    def test_disagree_when_high_fundamental_but_negative_return(self, conn: sqlite3.Connection) -> None:
        row = insert_pick_and_outcome(conn, fundamental_score=0.5, return_pct=-0.02)
        result = fundamental_check_analyst(conn, "pick_test", row, {})
        assert result.verdict == "DISAGREE"
        assert "underweighted_fundamental" in result.suggested_errors

    def test_neutral_when_low_fundamental_but_positive_return(self, conn: sqlite3.Connection) -> None:
        row = insert_pick_and_outcome(conn, fundamental_score=0.1, return_pct=0.03)
        result = fundamental_check_analyst(conn, "pick_test", row, {})
        assert result.verdict == "NEUTRAL"

    def test_financial_actuals_revenue_growth(self, conn: sqlite3.Connection) -> None:
        row = insert_pick_and_outcome(conn, fundamental_score=0.3, return_pct=0.01)
        evidence = {
            "financial_actuals": {"revenue_growth": 0.15, "net_profit_growth": 0.20, "roe": 0.12},
        }
        result = fundamental_check_analyst(conn, "pick_test", row, evidence)
        assert any("营收" in r for r in result.reasoning)
        assert any("ROE" in r for r in result.reasoning)

    def test_earnings_surprise_positive(self, conn: sqlite3.Connection) -> None:
        row = insert_pick_and_outcome(conn, fundamental_score=0.3, return_pct=0.01)
        evidence = {
            "earnings_surprises": [{"surprise_pct": 0.10, "surprise_type": "positive"}],
        }
        result = fundamental_check_analyst(conn, "pick_test", row, evidence)
        assert any("超预期" in r for r in result.reasoning)


class TestRiskScannerAnalyst:
    def test_st_stock_flagged(self, conn: sqlite3.Connection) -> None:
        row = insert_pick_and_outcome(conn, is_st=1, return_pct=-0.01)
        result = risk_scanner_analyst(conn, "pick_test", row, {})
        assert result.verdict == "DISAGREE"
        assert "risk_underestimated" in result.suggested_errors

    def test_suspension_flagged(self, conn: sqlite3.Connection) -> None:
        row = insert_pick_and_outcome(conn, is_suspended=1, return_pct=0.0)
        result = risk_scanner_analyst(conn, "pick_test", row, {})
        assert any("停牌" in r for r in result.reasoning)

    def test_risk_penalty_with_negative_return(self, conn: sqlite3.Connection) -> None:
        row = insert_pick_and_outcome(conn, risk_penalty=0.4, return_pct=-0.01)
        result = risk_scanner_analyst(conn, "pick_test", row, {})
        assert any("风险惩罚" in r for r in result.reasoning)

    def test_risk_events_detected(self, conn: sqlite3.Connection) -> None:
        row = insert_pick_and_outcome(conn, return_pct=-0.01)
        evidence = {
            "risk_events": [
                {"event_type": "大股东减持", "risk_type": "减持"},
                {"event_type": "监管问询", "risk_type": "监管"},
            ],
        }
        result = risk_scanner_analyst(conn, "pick_test", row, evidence)
        assert any("减持" in r for r in result.reasoning)
        assert any("监管" in r for r in result.reasoning)

    def test_agree_when_no_risk(self, conn: sqlite3.Connection) -> None:
        row = insert_pick_and_outcome(conn, return_pct=0.02)
        result = risk_scanner_analyst(conn, "pick_test", row, {})
        assert result.verdict == "AGREE"
        assert any("未发现" in r for r in result.reasoning)


class TestContrarianAnalyst:
    def _force_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)

    def test_fallback_on_high_score_good_return(self, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
        self._force_fallback(monkeypatch)
        row = insert_pick_and_outcome(conn, total_score=0.7, return_pct=0.03)
        result = contrarian_analyst(conn, "pick_test", row, {})
        # Without LLM configured, should use rule-based fallback
        assert result.verdict in ("AGREE", "NEUTRAL", "DISAGREE")
        assert result.confidence > 0
        assert len(result.reasoning) > 0

    def test_fallback_on_high_score_bad_return(self, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
        self._force_fallback(monkeypatch)
        row = insert_pick_and_outcome(conn, total_score=0.7, return_pct=-0.03)
        result = contrarian_analyst(conn, "pick_test", row, {})
        assert result.verdict == "DISAGREE"
        assert "risk_underestimated" in result.suggested_errors

    def test_fallback_on_low_score_good_return(self, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
        self._force_fallback(monkeypatch)
        row = insert_pick_and_outcome(conn, total_score=0.2, return_pct=0.05)
        result = contrarian_analyst(conn, "pick_test", row, {})
        assert result.verdict == "NEUTRAL"

    def test_fallback_with_risk_events_and_negative_return(self, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
        self._force_fallback(monkeypatch)
        row = insert_pick_and_outcome(conn, total_score=0.4, return_pct=-0.01)
        evidence = {"risk_events": [{"event_type": "处罚"}]}
        result = contrarian_analyst(conn, "pick_test", row, evidence)
        assert "missed_risk_event" in result.suggested_errors


# ── Integration tests ────────────────────────────────────────────────


class TestRunAnalystReviews:
    def test_all_analysts_run(self, conn: sqlite3.Connection) -> None:
        insert_pick_and_outcome(conn, return_pct=0.02)
        results = run_analyst_reviews(conn, "2024-01-10")
        assert len(results) == 4  # One pick × 4 analysts
        keys = {r["analyst_key"] for r in results}
        assert keys == {"trend_follower", "fundamental_check", "risk_scanner", "contrarian"}

    def test_multiple_picks(self, conn: sqlite3.Connection) -> None:
        insert_pick_and_outcome(conn, decision_id="pick_1", stock_code="000001.SZ")
        insert_pick_and_outcome(conn, decision_id="pick_2", stock_code="000002.SZ")
        results = run_analyst_reviews(conn, "2024-01-10")
        assert len(results) == 8  # 2 picks × 4 analysts
        decision_ids = {r["decision_id"] for r in results}
        assert decision_ids == {"pick_1", "pick_2"}

    def test_no_errors_from_any_analyst(self, conn: sqlite3.Connection) -> None:
        insert_pick_and_outcome(conn, return_pct=0.02)
        results = run_analyst_reviews(conn, "2024-01-10")
        for r in results:
            assert r["verdict"] != "ERROR", f"{r['analyst_key']} returned ERROR: {r.get('reasoning')}"

    def test_idempotent_re_run(self, conn: sqlite3.Connection) -> None:
        insert_pick_and_outcome(conn, return_pct=0.02)
        run_analyst_reviews(conn, "2024-01-10")
        count_1 = conn.execute("SELECT COUNT(*) FROM analyst_reviews").fetchone()[0]
        run_analyst_reviews(conn, "2024-01-10")
        count_2 = conn.execute("SELECT COUNT(*) FROM analyst_reviews").fetchone()[0]
        assert count_1 == count_2  # UNIQUE constraint + ON CONFLICT DO UPDATE


class TestGetAnalystReviewsForDate:
    def test_returns_reviews_for_date(self, conn: sqlite3.Connection) -> None:
        insert_pick_and_outcome(conn, decision_id="pick_1", stock_code="000001.SZ")
        run_analyst_reviews(conn, "2024-01-10")
        reviews = get_analyst_reviews_for_date(conn, "2024-01-10")
        assert len(reviews) == 4
        for r in reviews:
            assert r["trading_date"] == "2024-01-10"
            assert isinstance(r["reasoning"], list)
            assert isinstance(r["suggested_errors"], list)

    def test_empty_date_returns_empty(self, conn: sqlite3.Connection) -> None:
        reviews = get_analyst_reviews_for_date(conn, "2099-01-01")
        assert reviews == []


class TestSignalEmission:
    def test_signals_emitted_on_disagree(self, conn: sqlite3.Connection) -> None:
        row = insert_pick_and_outcome(conn, decision_id="pick_sig", return_pct=-0.02)
        verdict = AnalystVerdict(
            analyst_key="test_risk",
            decision_id="pick_sig",
            verdict="DISAGREE",
            confidence=0.75,
            reasoning=["风险被低估"],
            suggested_errors=["risk_underestimated", "missed_risk_event"],
        )
        persist_analyst_verdict(conn, verdict, row)
        _emit_signals_from_verdict(conn, verdict, row)
        conn.commit()

        signals = conn.execute(
            "SELECT signal_type, param_name, direction FROM optimization_signals WHERE source_type = 'analyst_review'"
        ).fetchall()
        assert len(signals) == 2
        types = {(s["signal_type"], s["param_name"]) for s in signals}
        assert ("increase_risk_penalty", "risk_penalty") in types
        assert ("increase_weight", "event_score") in types

    def test_no_signals_on_agree(self, conn: sqlite3.Connection) -> None:
        row = insert_pick_and_outcome(conn, decision_id="pick_agree", return_pct=0.02)
        verdict = AnalystVerdict(
            analyst_key="test_agree",
            decision_id="pick_agree",
            verdict="AGREE",
            confidence=0.8,
            reasoning=["all good"],
            suggested_errors=[],
        )
        persist_analyst_verdict(conn, verdict, row)
        _emit_signals_from_verdict(conn, verdict, row)
        conn.commit()

        count = conn.execute(
            "SELECT COUNT(*) FROM optimization_signals WHERE source_type = 'analyst_review'"
        ).fetchone()[0]
        assert count == 0


class TestRegistry:
    def test_all_analysts_registered(self) -> None:
        assert len(REVIEW_ANALYSTS) == 4
        assert "trend_follower" in REVIEW_ANALYSTS
        assert "fundamental_check" in REVIEW_ANALYSTS
        assert "risk_scanner" in REVIEW_ANALYSTS
        assert "contrarian" in REVIEW_ANALYSTS

    def test_each_analyst_has_required_fields(self) -> None:
        for key, config in REVIEW_ANALYSTS.items():
            assert "display_name" in config
            assert "perspective" in config
            assert "description" in config
            assert callable(config["analyst_func"])

    def test_contrarian_is_only_llm_analyst(self) -> None:
        for key, config in REVIEW_ANALYSTS.items():
            if key == "contrarian":
                assert config["use_llm"] is True
            else:
                assert config["use_llm"] is False


class TestAnalystVerdictDataclass:
    def test_construction(self) -> None:
        v = AnalystVerdict(
            analyst_key="test",
            decision_id="pick_1",
            verdict="AGREE",
            confidence=0.8,
            reasoning=["good pick"],
            suggested_errors=["test_error"],
        )
        assert v.analyst_key == "test"
        assert v.verdict == "AGREE"
        assert v.confidence == 0.8

    def test_immutable(self) -> None:
        v = AnalystVerdict(
            analyst_key="test",
            decision_id="pick_1",
            verdict="NEUTRAL",
            confidence=0.5,
            reasoning=[],
        )
        with pytest.raises(AttributeError):
            v.verdict = "AGREE"  # type: ignore[misc]

    def test_default_suggested_errors(self) -> None:
        v = AnalystVerdict(
            analyst_key="test",
            decision_id="pick_1",
            verdict="NEUTRAL",
            confidence=0.5,
            reasoning=[],
        )
        assert v.suggested_errors == []


class TestLoadAnalystEvidence:
    def test_loads_evidence_for_stock(self, conn: sqlite3.Connection) -> None:
        insert_pick_and_outcome(conn, decision_id="pick_ev", return_pct=0.01)
        evidence = load_analyst_evidence(conn, "000001.SZ", "2024-01-10")
        assert "financial_actuals" in evidence
        assert "analyst_expectations" in evidence
        assert "earnings_surprises" in evidence
        assert "risk_events" in evidence
        assert "recent_prices" in evidence
        assert "order_contracts" in evidence
        assert "business_kpis" in evidence

    def test_recent_prices_includes_date(self, conn: sqlite3.Connection) -> None:
        insert_pick_and_outcome(conn, decision_id="pick_pr", return_pct=0.01)
        evidence = load_analyst_evidence(conn, "000001.SZ", "2024-01-10")
        assert len(evidence["recent_prices"]) >= 1
        for p in evidence["recent_prices"]:
            assert "close" in p
            assert "volume" in p
