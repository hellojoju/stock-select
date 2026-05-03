"""Source adapter metadata and compliance tracking.

Each data source declares its capabilities, authorization requirements,
rate limits, and robots.txt compliance status.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SourceMeta:
    """Metadata for a data source adapter."""
    name: str
    base_url: str
    auth_type: str  # "none", "api_key", "oauth", "institutional"
    rate_limit: str  # e.g. "5 req/s", "100 req/day"
    robots_allowed: bool
    copyright_notice: str
    datasets: list[str] = field(default_factory=list)
    requires_throttle: bool = False
    throttle_seconds: float = 0.0


# ──────────────────────────────────────────────
# Source metadata registry
# ──────────────────────────────────────────────

SOURCE_REGISTRY: dict[str, SourceMeta] = {
    "akshare": SourceMeta(
        name="AKShare",
        base_url="https://akshare.akfamily.com",
        auth_type="none",
        rate_limit="unlimited (open source)",
        robots_allowed=True,
        copyright_notice="AKShare is open source under MIT license",
        datasets=[
            "stock_universe", "trading_calendar", "daily_prices",
            "index_prices", "industries", "fundamentals",
            "event_signals", "financial_actuals",
            "analyst_expectations", "order_contract_events",
            "business_kpis", "risk_events",
        ],
        requires_throttle=True,
        throttle_seconds=0.2,
    ),
    "baostock": SourceMeta(
        name="BaoStock",
        base_url="http://baostock.com",
        auth_type="none",
        rate_limit="unlimited (open source)",
        robots_allowed=True,
        copyright_notice="BaoStock is free for academic and non-commercial use",
        datasets=[
            "stock_universe", "trading_calendar", "daily_prices",
            "index_prices", "fundamentals", "financial_actuals",
            "business_kpis",
        ],
        requires_throttle=True,
        throttle_seconds=0.1,
    ),
    "cninfo": SourceMeta(
        name="CNInfo (巨潮资讯)",
        base_url="http://www.cninfo.com.cn",
        auth_type="none",
        rate_limit="~10 req/min (public API)",
        robots_allowed=False,
        copyright_notice="Announcements are public disclosures; reuse requires attribution",
        datasets=["official_announcements"],
        requires_throttle=True,
        throttle_seconds=0.5,
    ),
    "sse": SourceMeta(
        name="SSE (上交所)",
        base_url="http://www.sse.com.cn",
        auth_type="none",
        rate_limit="~5 req/min (public API)",
        robots_allowed=False,
        copyright_notice="Exchange data requires proper attribution",
        datasets=["official_announcements"],
        requires_throttle=True,
        throttle_seconds=0.5,
    ),
    "szse": SourceMeta(
        name="SZSE (深交所)",
        base_url="http://www.szse.cn",
        auth_type="none",
        rate_limit="~5 req/min (public API)",
        robots_allowed=False,
        copyright_notice="Exchange data requires proper attribution",
        datasets=["official_announcements"],
        requires_throttle=True,
        throttle_seconds=0.5,
    ),
    "eastmoney": SourceMeta(
        name="EastMoney (东方财富)",
        base_url="https://www.eastmoney.com",
        auth_type="none",
        rate_limit="~10 req/min (public API)",
        robots_allowed=False,
        copyright_notice="Content copyright EastMoney; scraping for commercial use prohibited",
        datasets=["finance_news"],
        requires_throttle=True,
        throttle_seconds=0.5,
    ),
    "sina": SourceMeta(
        name="Sina Finance (新浪财经)",
        base_url="https://finance.sina.com.cn",
        auth_type="none",
        rate_limit="~10 req/min (public API)",
        robots_allowed=False,
        copyright_notice="Content copyright Sina; commercial reuse restricted",
        datasets=["finance_news"],
        requires_throttle=True,
        throttle_seconds=0.5,
    ),
}


def get_source_meta(source: str) -> SourceMeta | None:
    """Get metadata for a named source."""
    return SOURCE_REGISTRY.get(source)


def list_all_sources() -> list[dict[str, Any]]:
    """List all registered sources with their metadata."""
    return [
        {
            "source": key,
            "name": meta.name,
            "auth_type": meta.auth_type,
            "rate_limit": meta.rate_limit,
            "robots_allowed": meta.robots_allowed,
            "datasets": meta.datasets,
            "requires_throttle": meta.requires_throttle,
        }
        for key, meta in SOURCE_REGISTRY.items()
    ]
