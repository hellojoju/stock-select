"""Parse extracted announcement text into structured event records.

Matches patterns for order/contract events, business KPIs, and risk events
from announcement body text, then persists to the corresponding tables.
"""
from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Pattern definitions for event extraction
# ──────────────────────────────────────────────

# Order / Contract event patterns
_ORDER_CONTRACT_PATTERNS = [
    (r"签订.*合同", "contract_signed"),
    (r"签订.*协议", "agreement_signed"),
    (r"中标", "bid_won"),
    (r"订单", "order_received"),
    (r"合同金额", "contract_amount"),
    (r"总金额", "total_amount"),
    (r"交易额", "transaction_amount"),
]

# Business KPI patterns
_BUSINESS_KPI_PATTERNS = [
    (r"营业收入", "revenue"),
    (r"净利润", "net_profit"),
    (r"每股收益", "eps"),
    (r"毛利率", "gross_margin"),
    (r"净资产收益率", "roe"),
    (r"同比增长", "yoy_growth"),
    (r"环比增长", "qoq_growth"),
    (r"产能", "production_capacity"),
    (r"产量", "production_volume"),
    (r"销量", "sales_volume"),
]

# Risk event patterns
_RISK_EVENT_PATTERNS = [
    (r"诉讼", "litigation"),
    (r"仲裁", "arbitration"),
    (r"处罚", "penalty"),
    (r"违规", "violation"),
    (r"警示", "warning"),
    (r"调查", "investigation"),
    (r"立案", "case_filed"),
    (r"退市风险", "delisting_risk"),
    (r" ST ", "st_risk"),
    (r"担保", "guarantee"),
    (r"资金占用", "fund_occupation"),
    (r"关联交易", "related_transaction"),
]

# Numeric extraction patterns
_AMOUNT_RE = re.compile(r"([\d,\.]+)\s*(万元|亿元|百万元|元|美元|港元)?")
_PERCENT_RE = re.compile(r"([\d\.]+)\s*%")
_STOCK_CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")


@dataclass(frozen=True)
class OrderContractEvent:
    event_id: str
    stock_code: str
    event_date: str
    event_type: str
    amount: float | None
    currency: str
    description: str
    source_document_id: str | None
    confidence: float


@dataclass(frozen=True)
class BusinessKPIEvent:
    event_id: str
    stock_code: str
    period: str
    kpi_name: str
    kpi_value: float | None
    yoy_change: float | None
    description: str
    source_document_id: str | None
    confidence: float


@dataclass(frozen=True)
class RiskEvent:
    event_id: str
    stock_code: str
    event_date: str
    risk_type: str
    severity: str
    description: str
    source_document_id: str | None
    confidence: float


def _gen_event_id(prefix: str, stock_code: str, event_type: str, date: str) -> str:
    raw = f"{prefix}:{stock_code}:{event_type}:{date}"
    return f"{prefix}_{hashlib.sha1(raw.encode()).hexdigest()[:12]}"


def _extract_amount(text: str) -> tuple[float | None, str | None]:
    """Try to extract a monetary amount from text near keyword."""
    match = _AMOUNT_RE.search(text)
    if not match:
        return None, None
    value_str = match.group(1).replace(",", "")
    unit = match.group(2) or "元"
    try:
        value = float(value_str)
    except ValueError:
        return None, None
    # Convert to 万元 as canonical unit
    multipliers = {"元": 1e-4, "万元": 1, "百万元": 100, "亿元": 1e4, "美元": 1e-4, "港元": 1e-4}
    canonical = value * multipliers.get(unit, 1)
    return round(canonical, 2), unit


def _extract_percent(text: str) -> float | None:
    match = _PERCENT_RE.search(text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def _find_stock_codes(text: str, known_codes: list[str] | None = None) -> list[str]:
    codes = _STOCK_CODE_RE.findall(text)
    if known_codes:
        for c in known_codes:
            if c not in codes:
                codes.insert(0, c)
    return codes[:3]  # limit to top 3


def _split_into_sentences(text: str) -> list[str]:
    """Split text into sentences using common Chinese/English delimiters."""
    parts = re.split(r'[。；\n\r]', text)
    return [p.strip() for p in parts if len(p.strip()) > 5]


def extract_order_contract_events(
    text: str,
    document_id: str,
    event_date: str,
    known_stock_codes: list[str] | None = None,
) -> list[OrderContractEvent]:
    """Extract order/contract events from announcement text."""
    events = []
    for pattern, event_type in _ORDER_CONTRACT_PATTERNS:
        if not re.search(pattern, text):
            continue
        # Find the sentence containing the match
        for sentence in _split_into_sentences(text):
            if re.search(pattern, sentence):
                stock_codes = _find_stock_codes(sentence, known_stock_codes)
                amount, currency = _extract_amount(sentence)
                for code in (stock_codes or ["unknown"]):
                    eid = _gen_event_id("oc", code, event_type, event_date)
                    events.append(OrderContractEvent(
                        event_id=eid,
                        stock_code=code,
                        event_date=event_date,
                        event_type=event_type,
                        amount=amount,
                        currency=currency or "万元",
                        description=sentence[:200],
                        source_document_id=document_id,
                        confidence=0.75,
                    ))
                break  # one sentence per pattern type
    return events


def extract_business_kpi_events(
    text: str,
    document_id: str,
    event_date: str,
    known_stock_codes: list[str] | None = None,
) -> list[BusinessKPIEvent]:
    """Extract business KPI events from announcement text."""
    events = []
    for pattern, kpi_name in _BUSINESS_KPI_PATTERNS:
        if not re.search(pattern, text):
            continue
        for sentence in _split_into_sentences(text):
            if re.search(pattern, sentence):
                stock_codes = _find_stock_codes(sentence, known_stock_codes)
                value = _extract_percent(sentence)
                yoy = None
                if "同比" in sentence:
                    yoy = _extract_percent(sentence)
                for code in (stock_codes or ["unknown"]):
                    eid = _gen_event_id("kpi", code, kpi_name, event_date)
                    events.append(BusinessKPIEvent(
                        event_id=eid,
                        stock_code=code,
                        period=event_date,
                        kpi_name=kpi_name,
                        kpi_value=value,
                        yoy_change=yoy,
                        description=sentence[:200],
                        source_document_id=document_id,
                        confidence=0.7,
                    ))
                break
    return events


def extract_risk_events(
    text: str,
    document_id: str,
    event_date: str,
    known_stock_codes: list[str] | None = None,
) -> list[RiskEvent]:
    """Extract risk events from announcement text."""
    events = []
    for pattern, risk_type in _RISK_EVENT_PATTERNS:
        if not re.search(pattern, text):
            continue
        for sentence in _split_into_sentences(text):
            if re.search(pattern, sentence):
                stock_codes = _find_stock_codes(sentence, known_stock_codes)
                severity = "high" if any(k in sentence for k in ["退市", "立案", "处罚"]) else "medium"
                for code in (stock_codes or ["unknown"]):
                    eid = _gen_event_id("risk", code, risk_type, event_date)
                    events.append(RiskEvent(
                        event_id=eid,
                        stock_code=code,
                        event_date=event_date,
                        risk_type=risk_type,
                        severity=severity,
                        description=sentence[:200],
                        source_document_id=document_id,
                        confidence=0.7,
                    ))
                break
    return events


def upsert_order_contract_event(conn: sqlite3.Connection, event: OrderContractEvent) -> None:
    """Persist an OrderContractEvent, deduping by event_id."""
    conn.execute(
        """
        INSERT INTO order_contract_events(
            event_id, stock_code, event_date, event_type,
            amount, currency, description, source_document_id, confidence
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(event_id) DO NOTHING
        """,
        (
            event.event_id, event.stock_code, event.event_date, event.event_type,
            event.amount, event.currency, event.description, event.source_document_id, event.confidence,
        ),
    )


def upsert_business_kpi_event(conn: sqlite3.Connection, event: BusinessKPIEvent) -> None:
    """Persist a BusinessKPIEvent, deduping by event_id."""
    conn.execute(
        """
        INSERT INTO business_kpi_actuals(
            kpi_id, stock_code, period, kpi_name, kpi_value,
            yoy_change, description, source_document_id, confidence
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(kpi_id) DO NOTHING
        """,
        (
            event.event_id, event.stock_code, event.period, event.kpi_name, event.kpi_value,
            event.yoy_change, event.description, event.source_document_id, event.confidence,
        ),
    )


def upsert_risk_event(conn: sqlite3.Connection, event: RiskEvent) -> None:
    """Persist a RiskEvent, deduping by event_id."""
    conn.execute(
        """
        INSERT INTO risk_events(
            event_id, stock_code, event_date, risk_type, severity,
            description, source_document_id, confidence
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(event_id) DO NOTHING
        """,
        (
            event.event_id, event.stock_code, event.event_date, event.risk_type, event.severity,
            event.description, event.source_document_id, event.confidence,
        ),
    )


def process_announcement_text(
    conn: sqlite3.Connection,
    document_id: str,
    text: str,
    event_date: str,
    known_stock_codes: list[str] | None = None,
) -> dict[str, int]:
    """Extract and persist all event types from announcement text.

    Returns counts of extracted events by type.
    """
    oc_events = extract_order_contract_events(text, document_id, event_date, known_stock_codes)
    kpi_events = extract_business_kpi_events(text, document_id, event_date, known_stock_codes)
    risk_events_list = extract_risk_events(text, document_id, event_date, known_stock_codes)

    for ev in oc_events:
        upsert_order_contract_event(conn, ev)
    for ev in kpi_events:
        upsert_business_kpi_event(conn, ev)
    for ev in risk_events_list:
        upsert_risk_event(conn, ev)

    conn.commit()

    return {
        "order_contract_events": len(oc_events),
        "business_kpi_events": len(kpi_events),
        "risk_events": len(risk_events_list),
        "total": len(oc_events) + len(kpi_events) + len(risk_events_list),
    }
